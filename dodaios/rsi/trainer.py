"""The loop that changes a cell's steering policy, one measured step at a time.

Driven by verdicts, never by a timer: after a run in a cell got its verdict,
:meth:`Trainer.consider` looks at that cell once.

1. **No candidate on trial:** when the cell has enough runs under its active
   policy, every candidate of a small fixed grid of steering parameters is
   replayed on the record (:mod:`replay`). The first one the replay does not
   reject goes on trial as the cell's candidate, as a self-change; its claim
   (branch B, target ``cost``) is fixed at that moment, before its own data.
2. **A candidate on trial:** once both arms have :data:`selector.N_MIN`
   requests since the claim, :func:`selector.gate` decides. Accepted: the
   candidate becomes the active policy (a self-change on probation) and the
   trial ends. Rejected, or still without an answer after
   :data:`MAX_TRIAL_DAYS`: the trial ends and the active policy stays.
3. **A new active policy on probation:** the first run under it whose final
   output weakened a check rolls it back to the exact previous policy.

Only steering parameters are proposed here; nothing writes text for agents
(decision 5.4). Every change shows in Trust → Self-changes with its reason.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

from . import selector, stats
from .policy import ACTIVE, CANDIDATE, DEFAULT, Policy, PolicyStore, target_for
from .replay import replay_cell

log = logging.getLogger(__name__)

__all__ = ["AUTHOR", "GRID", "MAX_TRIAL_DAYS", "Trainer"]

#: Who the registry names as the author of a policy change.
AUTHOR: Final[str] = "rsi-selector"
#: Steering candidates, tried in this order: each saves more than the next.
GRID: Final[tuple[Policy, ...]] = (
    Policy(p_max=1),
    Policy(evidence_wait_s=20 * 60),
    Policy(p_max=1, evidence_wait_s=20 * 60),
    Policy(p_max=0),
)
MAX_TRIAL_DAYS: Final[int] = 28
_DAY_MS: Final[int] = 24 * 60 * 60 * 1000
_RUNS_READ: Final[int] = 5_000

_CLAIMS = """
CREATE TABLE IF NOT EXISTS claims (
    cell         TEXT NOT NULL,
    candidate    TEXT NOT NULL,
    branch       TEXT NOT NULL,
    target       TEXT NOT NULL DEFAULT '',
    t0_ms        INTEGER NOT NULL,
    digest       TEXT NOT NULL,
    change_id    TEXT NOT NULL DEFAULT '',
    outcome      TEXT NOT NULL DEFAULT '',
    decided_ms   INTEGER,
    PRIMARY KEY (cell, candidate, t0_ms)
);
"""


@dataclass(frozen=True, slots=True)
class Open:
    """A candidate's open trial."""

    cell: str
    candidate: str
    branch: str
    target: str
    t0_ms: int
    change_id: str


class Trainer:
    """Proposes, judges and rolls back steering policies through the self-change registry."""

    def __init__(
        self,
        runs: Any,
        policies: PolicyStore,
        registry: Callable[[], Any],
        *,
        clock: Callable[[], float] = time.time,
        samples: int = stats.SAMPLES,
    ) -> None:
        #: The run record (``VerificationStore``).
        self._runs = runs
        self._policies = policies
        self._registry = registry
        self._clock = clock
        self._samples = samples
        self._lock = threading.Lock()
        self._busy: set[str] = set()
        with self._policies._lock:  # one database: the claims sit beside the policies
            self._policies._conn.executescript(_CLAIMS)
            self._policies._conn.commit()

    # ------------------------------------------------------------- claims

    def _open(self, cell: str) -> Open | None:
        with self._policies._lock:
            row = self._policies._conn.execute(
                "SELECT cell, candidate, branch, target, t0_ms, change_id FROM claims "
                "WHERE cell = ? AND outcome = '' ORDER BY t0_ms DESC LIMIT 1",
                (cell,),
            ).fetchone()
        return Open(*row) if row is not None else None

    def _claim(self, cell: str, candidate: Policy, change_id: str, now: int) -> None:
        claim = {"cell": cell, "candidate": candidate.id, "branch": "B", "target": "cost"}
        digest = hashlib.sha256(json.dumps(claim, sort_keys=True).encode()).hexdigest()
        with self._policies._lock:
            self._policies._conn.execute(
                "INSERT INTO claims (cell, candidate, branch, target, t0_ms, digest, change_id) "
                "VALUES (?, ?, 'B', 'cost', ?, ?, ?)",
                (cell, candidate.id, now, digest, change_id),
            )
            self._policies._conn.commit()

    def _close(self, trial: Open, outcome: str, now: int) -> None:
        with self._policies._lock:
            self._policies._conn.execute(
                "UPDATE claims SET outcome = ?, decided_ms = ? "
                "WHERE cell = ? AND candidate = ? AND t0_ms = ?",
                (outcome, now, trial.cell, trial.candidate, trial.t0_ms),
            )
            self._policies._conn.commit()

    def claims(self) -> list[dict[str, Any]]:
        """Every claim on record, newest first (for the report)."""
        with self._policies._lock:
            cur = self._policies._conn.execute(
                "SELECT cell, candidate, branch, target, t0_ms, digest, change_id, outcome, "
                "decided_ms FROM claims ORDER BY t0_ms DESC"
            )
            names = [c[0] for c in cur.description]
            return [dict(zip(names, row, strict=True)) for row in cur.fetchall()]

    # -------------------------------------------------------------- reading

    def _cell_runs(self, cell: str, since_ms: int = 0) -> list[dict[str, Any]]:
        rows = self._runs.runs(since_ms=since_ms, limit=_RUNS_READ)
        return [
            r for r in rows
            if r.get("verdict") and r.get("state") == "ended" and selector.cell_of(r) == cell
        ]

    # ------------------------------------------------------------ the loop

    def consider(self, cell: str) -> str:
        """Look at one cell once. Returns what was done (for the log and the tests)."""
        if self._registry() is None:
            return "no self-change registry in this process"
        with self._lock:
            now = int(self._clock() * 1000)
            trial = self._open(cell)
            if trial is not None:
                return self._judge(trial, now)
            done = self._watch_probation(cell)
            if done:
                return done
            return self._propose(cell, now)

    def _propose(self, cell: str, now: int) -> str:
        active = self._policies.policy(cell, ACTIVE) or DEFAULT
        rows = [r for r in self._cell_runs(cell) if r.get("policy_id") == active.id]
        if len(rows) < selector.N_MIN:
            return "waiting for runs"
        recorded = [(r, self._runs.steps(str(r["run_id"]))) for r in rows]
        claim = selector.Claim(cell, "B", "cost")
        for candidate in GRID:
            if candidate == active:
                continue
            outcome = replay_cell(claim, recorded, candidate)
            if outcome.answer == "reject":
                continue
            change = self._registry().propose(self._draft(
                target_for(cell, CANDIDATE), candidate,
                f"steering candidate {candidate.id} for {cell}: the replay of "
                f"{outcome.covered} recorded runs did not reject it ({outcome.reasons[:1]})",
            ))
            if change.state.value not in ("trial", "live"):
                return f"candidate {candidate.id} not applied ({change.state.value})"
            self._claim(cell, candidate, change.id, now)
            return f"candidate {candidate.id} on trial"
        return "no candidate survived the replay"

    def _judge(self, trial: Open, now: int) -> str:
        active = self._policies.policy(trial.cell, ACTIVE) or DEFAULT
        candidate = self._policies.policy(trial.cell, CANDIDATE)
        if candidate is None or candidate.id != trial.candidate:
            self._close(trial, "withdrawn", now)  # rolled back or replaced by the owner
            return "trial withdrawn"
        rows = self._cell_runs(trial.cell, since_ms=trial.t0_ms)
        metrics = [m for m in (selector.metrics_of(r) for r in rows) if m is not None]
        claim = selector.Claim(trial.cell, trial.branch, trial.target)
        outcome = selector.gate(
            claim,
            [m for m in metrics if m.policy == candidate.id],
            [m for m in metrics if m.policy == active.id],
            samples=self._samples,
        )
        aged = now - trial.t0_ms >= MAX_TRIAL_DAYS * _DAY_MS
        if outcome.answer == "inconclusive" and not aged:
            return "trial goes on"
        registry = self._registry()
        if outcome.answer == "accept":
            registry.propose(self._draft(
                target_for(trial.cell, ACTIVE), candidate,
                f"accepted by the selector's gate: {'; '.join(outcome.reasons)} "
                f"({outcome.n_candidate} against {outcome.n_reference} requests)",
            ))
        registry.propose(self._draft(
            target_for(trial.cell, CANDIDATE), None,
            f"the trial of {candidate.id} ended: {outcome.answer}"
            + (" after 28 days without an answer" if aged else ""),
        ))
        self._close(trial, outcome.answer if not aged else "expired", now)
        return f"trial ended: {outcome.answer}"

    def _watch_probation(self, cell: str) -> str:
        """Roll a new active policy back at the first hard event under it."""
        registry = self._registry()
        target = target_for(cell, ACTIVE)
        changes = [
            c for c in registry.store.list(limit=200)
            if c.surface.value == "coding_policy" and c.target == target
            and c.state.value == "trial" and c.author == AUTHOR
        ]
        if not changes:
            return ""
        newest = max(changes, key=lambda c: c.seq)
        policy = Policy.from_text(newest.after)
        since = int(getattr(newest, "created_ms", 0) or 0)
        hard = [
            r for r in self._cell_runs(cell, since_ms=since)
            if r.get("policy_id") == policy.id and r.get("gate_status") == "violations"
        ]
        if not hard:
            return ""
        registry.rollback(newest.id, actor=AUTHOR)
        return f"rolled back {policy.id}: run {hard[0]['run_id']} weakened a check"

    def on_verdict(self, run_id: str, _session_id: str) -> None:
        """Recorder listener (its writer thread): look at the run's cell in the background."""
        row = self._runs.get(run_id) or {}
        if not row.get("policy_id"):
            return
        cell = selector.cell_of(row)
        with self._lock:
            if cell in self._busy:
                return
            self._busy.add(cell)

        def work() -> None:
            try:
                done = self.consider(cell)
                if done not in ("waiting for runs", "trial goes on", ""):
                    log.info("rsi trainer: %s: %s", cell, done)
            except Exception:  # noqa: BLE001 - a failed look leaves every policy as it was
                log.warning("rsi trainer: %s not considered", cell, exc_info=True)
            finally:
                with self._lock:
                    self._busy.discard(cell)

        threading.Thread(target=work, name="rsi-trainer", daemon=True).start()

    @staticmethod
    def _draft(target: str, policy: Policy | None, reason: str) -> Any:
        from dodaios.self_change.gate import Draft
        from dodaios.self_change.surfaces import Surface

        return Draft(
            surface=Surface.CODING_POLICY, target=target,
            after=policy.to_text() if policy is not None else None,
            author=AUTHOR, reason=reason[:600],
        )
