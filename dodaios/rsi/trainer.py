"""The loop that changes a cell's steering policy, one measured step at a time.

Driven by verdicts, never by a timer: after a run in a cell got its verdict,
:meth:`Trainer.consider` looks at that cell once. Nothing here waits for the
person. Every change goes on trial by itself, the selector's gate decides on
the measured runs, and the person keeps stop and undo (Trust → Self-changes,
and the Self-improvement page).

1. **No candidate on trial, and the active policy does not hold** (the factory
   policy): holding, with the factory's follow-up limits, is the candidate.
   Whether Dodaios should wait for the checks and order fixes is learned like
   any other control. The record cannot replay the follow-up orders a hold
   would have sent (:func:`replay.replay_hold`); it only bounds the gain. When
   even a fix of every run a follow-up order could have reached would not
   raise the PassRate by :data:`selector.DELTA_PASS`, nothing is tried.
   Otherwise the hold goes on trial, its claim (branch A, target ``pass``)
   fixed before its own data.
2. **No candidate on trial, and the active policy holds:** every candidate of
   a small fixed grid of steering parameters is replayed on the record
   (:mod:`replay`). The first one the replay does not reject goes on trial,
   its claim (branch B, target ``cost``) fixed at that moment. When none
   survives, the miner (:mod:`mining`) may find one fixed line for the first
   brief, citing the follow-up orders it would have spared. That line goes on
   trial the same way (branch B, target ``p``).
3. **A candidate on trial:** once both arms have :data:`selector.N_MIN`
   requests since the claim, :func:`selector.gate` decides. Accepted: the
   candidate becomes the active policy (a self-change on probation, with the
   measurement that let it in) and the trial ends. Rejected, or still without
   an answer after :data:`MAX_TRIAL_DAYS`: the trial ends and the active
   policy stays.
4. **A new active policy on probation:** the first run under it whose final
   output weakened a check, or whose merged work turned red, rolls it back to
   the exact previous policy.

A candidate whose trial ended is not tried again in its cell for
:data:`RETRY_AFTER_DAYS`: a trial that just answered would only answer again.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import Any, Final

from . import selector, stats
from .bind import active_policy
from .policy import ACTIVE, CANDIDATE, DEFAULT, Policy, PolicyStore, target_for
from .replay import replay_cell, replay_hold

log = logging.getLogger(__name__)

__all__ = ["AUTHOR", "GRID", "MAX_TRIAL_DAYS", "RETRY_AFTER_DAYS", "Trainer", "claim_for"]

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
#: Days before a candidate whose trial ended is tried again in the same cell.
RETRY_AFTER_DAYS: Final[int] = 28
_DAY_MS: Final[int] = 24 * 60 * 60 * 1000
_RUNS_READ: Final[int] = 5_000
#: How what :meth:`Trainer.consider` did starts when it changed something (logged).
_CHANGED: Final[tuple[str, ...]] = ("candidate ", "trial ended", "trial withdrawn", "rolled back")

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


def claim_for(active: Policy, candidate: Policy) -> tuple[str, str]:
    """The branch and target a candidate is judged by, fixed before its data exist."""
    if candidate.hold and not active.hold:
        # Holding costs follow-up orders and a wait; it is worth it only when
        # more runs pass, so it has to win on quality (branch A).
        return "A", "pass"
    if candidate.domain_block != active.domain_block:
        return "B", "p"  # a line for the first brief would spare follow-up orders
    return "B", "cost"  # fewer follow-up orders or a shorter wait save cost


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

    def _claim(
        self, cell: str, candidate: Policy, change_id: str, now: int, branch: str, target: str
    ) -> Open:
        claim = {"cell": cell, "candidate": candidate.id, "branch": branch, "target": target}
        digest = hashlib.sha256(json.dumps(claim, sort_keys=True).encode()).hexdigest()
        with self._policies._lock:
            self._policies._conn.execute(
                "INSERT INTO claims (cell, candidate, branch, target, t0_ms, digest, change_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (cell, candidate.id, branch, target, now, digest, change_id),
            )
            self._policies._conn.commit()
        return Open(cell, candidate.id, branch, target, now, change_id)

    def _close(self, trial: Open, outcome: str, now: int) -> None:
        with self._policies._lock:
            self._policies._conn.execute(
                "UPDATE claims SET outcome = ?, decided_ms = ? "
                "WHERE cell = ? AND candidate = ? AND t0_ms = ?",
                (outcome, now, trial.cell, trial.candidate, trial.t0_ms),
            )
            self._policies._conn.commit()

    def _tried_lately(self, cell: str, candidate: Policy, now: int) -> bool:
        """True when a trial of ``candidate`` in ``cell`` ended less than a retry period ago."""
        with self._policies._lock:
            row = self._policies._conn.execute(
                "SELECT MAX(decided_ms) FROM claims "
                "WHERE cell = ? AND candidate = ? AND outcome != ''",
                (cell, candidate.id),
            ).fetchone()
        return (
            row is not None
            and row[0] is not None
            and now - int(row[0]) < (RETRY_AFTER_DAYS * _DAY_MS)
        )

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
            r
            for r in rows
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
            if trial is None:
                trial = self._claim_unclaimed(cell, now)
            if trial is not None:
                return self._judge(trial, now)
            done = self._watch_probation(cell)
            if done:
                return done
            return self._propose(cell, now)

    def _claim_unclaimed(self, cell: str, now: int) -> Open | None:
        """A candidate in the slot without any claim gets one now, before its data.

        The trainer claims what it puts on trial at once; this covers a
        candidate that reached the slot another way (one the owner approved by
        hand before candidates went on trial by themselves).
        """
        candidate = self._policies.policy(cell, CANDIDATE)
        if candidate is None:
            return None
        with self._policies._lock:
            known = self._policies._conn.execute(
                "SELECT 1 FROM claims WHERE cell = ? AND candidate = ? LIMIT 1",
                (cell, candidate.id),
            ).fetchone()
        if known is not None:
            return None  # its trial ended; the store will be cleared by that proposal
        branch, target = claim_for(active_policy(self._policies, cell), candidate)
        return self._claim(cell, candidate, "", now, branch, target)

    def _already_proposed(self, cell: str, candidate: Policy) -> bool:
        """True when this very candidate was proposed and is still not applied.

        Nothing the trainer proposes waits for a person; a change stays
        ``proposed`` only when a check of the registry could not run. It is not
        proposed again at every verdict meanwhile.
        """
        target = target_for(cell, CANDIDATE)
        text = candidate.to_text()
        return any(
            c.surface.value == "coding_policy"
            and c.target == target
            and c.state.value == "proposed"
            and c.after == text
            for c in self._registry().store.list(limit=200)
        )

    def _start(
        self,
        cell: str,
        active: Policy,
        candidate: Policy,
        reason: str,
        now: int,
        found: dict[str, Any],
    ) -> str:
        """Put ``candidate`` on trial against ``active``, its claim fixed now."""
        if self._already_proposed(cell, candidate):
            return f"candidate {candidate.id} not applied (proposed)"
        registry = self._registry()
        change = registry.propose(self._draft(target_for(cell, CANDIDATE), candidate, reason))
        if change.state.value not in ("trial", "live"):
            return f"candidate {candidate.id} not applied ({change.state.value})"
        branch, target = claim_for(active, candidate)
        self._claim(cell, candidate, change.id, now, branch, target)
        _record(
            registry,
            change.id,
            "propose",
            "trial",
            {
                "reason": reason,
                "cell": cell,
                "claim": {"branch": branch, "target": target},
                "reference": active.to_text(),
                **found,
            },
        )
        return f"candidate {candidate.id} on trial"

    def _propose(self, cell: str, now: int) -> str:
        active = active_policy(self._policies, cell)
        rows = [r for r in self._cell_runs(cell) if r.get("policy_id") == active.id]
        if len(rows) < selector.N_MIN:
            return "waiting for runs"
        recorded = [(r, self._runs.steps(str(r["run_id"]))) for r in rows]
        if not active.hold:
            return self._propose_hold(cell, active, recorded, now)
        claim = selector.Claim(cell, "B", "cost")
        for shape in GRID:
            # A candidate differs from the active policy in its steering only.
            candidate = replace(shape, hold=active.hold)
            if candidate == active or self._tried_lately(cell, candidate, now):
                continue
            outcome = replay_cell(claim, recorded, candidate)
            if outcome.answer == "reject":
                continue
            return self._start(
                cell,
                active,
                candidate,
                f"steering candidate {candidate.id} for {cell}: the replay of "
                f"{outcome.covered} recorded runs did not reject it ({outcome.reasons[:1]})",
                now,
                {"replay": _replayed(outcome)},
            )
        return self._propose_text(cell, active, recorded, now)

    def _propose_hold(
        self,
        cell: str,
        active: Policy,
        recorded: list[tuple[dict[str, Any], list[Any]]],
        now: int,
    ) -> str:
        """Holding, with the factory's follow-up limits, as a candidate for a cell that does not."""
        candidate = replace(
            active, hold=True, p_max=DEFAULT.p_max, evidence_wait_s=DEFAULT.evidence_wait_s
        )
        if self._tried_lately(cell, candidate, now):
            return f"nothing proposed: holding was tried here less than {RETRY_AFTER_DAYS} days ago"
        branch, target = claim_for(active, candidate)
        outcome = replay_hold(selector.Claim(cell, branch, target), recorded, candidate)
        if outcome.answer == "reject":
            return f"nothing proposed: {outcome.reasons[0]}"
        # The replay never accepts a hold (the follow-up orders were never sent):
        # past its bound, only the canary can show whether holding helps.
        return self._start(
            cell,
            active,
            candidate,
            f"holding the runs of {cell}, with the factory's follow-up limits: "
            f"{outcome.reasons[0]}",
            now,
            {"replay": _replayed(outcome)},
        )

    def _propose_text(
        self,
        cell: str,
        active: Policy,
        recorded: list[tuple[dict[str, Any], list[Any]]],
        now: int,
    ) -> str:
        """One fixed line for the first brief, mined from recurring follow-ups, on trial."""
        from .mining import suggest

        found = suggest(
            active, recorded, allowed=lambda policy: not self._tried_lately(cell, policy, now)
        )
        if found is None:
            return "no candidate survived the replay"
        cited = ", ".join(found.cited[:8]) + (", ..." if len(found.cited) > 8 else "")
        return self._start(
            cell,
            active,
            found.policy(active),
            f"one line for the first brief of {cell}: {found.line!r}. It would have spared "
            f"the follow-up orders of {len(found.cited)} runs ({cited}).",
            now,
            {"line": found.line, "cited": list(found.cited)},
        )

    def _judge(self, trial: Open, now: int) -> str:
        active = active_policy(self._policies, trial.cell)
        candidate = self._policies.policy(trial.cell, CANDIDATE)
        if candidate is None or candidate.id != trial.candidate:
            self._close(trial, "withdrawn", now)  # rolled back or replaced by the owner
            return "trial withdrawn"
        rows = self._cell_runs(trial.cell, since_ms=trial.t0_ms)
        metrics = [m for m in (selector.metrics_of(r) for r in rows) if m is not None]
        claim = selector.Claim(trial.cell, trial.branch, trial.target)
        cand = [m for m in metrics if m.policy == candidate.id]
        ref = [m for m in metrics if m.policy == active.id]
        outcome = selector.gate(claim, cand, ref, samples=self._samples)
        aged = now - trial.t0_ms >= MAX_TRIAL_DAYS * _DAY_MS
        if outcome.answer == "inconclusive" and not aged:
            return "trial goes on"
        registry = self._registry()
        measured = _measured(claim, outcome, cand, ref, active)
        if outcome.answer == "accept":
            change = registry.propose(
                self._draft(
                    target_for(trial.cell, ACTIVE),
                    candidate,
                    f"accepted by the selector's gate: {'; '.join(outcome.reasons)} "
                    f"({outcome.n_candidate} against {outcome.n_reference} requests)",
                )
            )
            if change.state.value in ("trial", "live"):
                _record(registry, change.id, "admit", outcome.answer, measured)
        if trial.change_id:
            step = "admit" if outcome.answer == "accept" else "decline"
            _record(registry, trial.change_id, step, outcome.answer, measured)
        registry.propose(
            self._draft(
                target_for(trial.cell, CANDIDATE),
                None,
                f"the trial of {candidate.id} ended: {outcome.answer}"
                + (" after 28 days without an answer" if aged else ""),
            )
        )
        self._close(trial, outcome.answer if not aged else "expired", now)
        return f"trial ended: {outcome.answer}"

    def _watch_probation(self, cell: str) -> str:
        """Roll a new active policy back at the first hard event under it."""
        registry = self._registry()
        target = target_for(cell, ACTIVE)
        changes = [
            c
            for c in registry.store.list(limit=200)
            if c.surface.value == "coding_policy"
            and c.target == target
            and c.state.value == "trial"
            and c.author == AUTHOR
        ]
        if not changes:
            return ""
        newest = max(changes, key=lambda c: c.seq)
        policy = Policy.from_text(newest.after)
        since = int(getattr(newest, "created_ms", 0) or 0)
        hard = [
            r
            for r in self._cell_runs(cell, since_ms=since)
            if r.get("policy_id") == policy.id
            and (r.get("gate_status") == "violations" or r.get("leaked"))
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
                if done.startswith(_CHANGED):
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
            surface=Surface.CODING_POLICY,
            target=target,
            after=policy.to_text() if policy is not None else None,
            author=AUTHOR,
            reason=reason[:600],
        )


def _replayed(outcome: Any) -> dict[str, Any]:
    return {
        "answer": outcome.answer,
        "runs": outcome.runs,
        "covered": outcome.covered,
        "reasons": list(outcome.reasons),
        "bounds": outcome.bounds,
    }


def _means(rows: Sequence[selector.RunMetrics]) -> dict[str, Any]:
    """Plain means per request of one arm, for the person to read beside the bound."""
    found = selector.units(rows)
    n = len(found)
    return {
        "n": n,
        **{m: (sum(u[m] for u in found) / n if n else None) for m in selector.METRICS},
    }


def _measured(
    claim: selector.Claim,
    outcome: selector.Outcome,
    cand: Sequence[selector.RunMetrics],
    ref: Sequence[selector.RunMetrics],
    reference: Policy,
) -> dict[str, Any]:
    """The gate's answer on a trial, in the shape the registry keeps as evidence.

    ``target`` follows the kernel's evidence (``diff``, ``low``, ``n``): the
    claimed metric's difference, oriented so that positive is better, and its
    one-sided lower bound. The selector computes no upper bound (``high``).
    """
    metric = claim.target if claim.branch == "B" else "pass"
    bound = outcome.bounds.get(metric) or {}
    arms = {"candidate": _means(cand), "reference": _means(ref)}
    cost_c, cost_r = arms["candidate"]["cost"], arms["reference"]["cost"]
    return {
        "reason": "; ".join(outcome.reasons),
        "split": "",
        "cell": claim.cell,
        "claim": {"branch": claim.branch, "target": claim.target},
        "reference": reference.to_text(),
        "target": {
            "domain": claim.cell.split("|", 1)[0],
            "metric": metric,
            "diff": bound.get("diff"),
            "low": bound.get("lcb"),
            "high": None,
            "n": outcome.n_candidate,
            "n_reference": outcome.n_reference,
            "cost_diff": (cost_c - cost_r if cost_c is not None and cost_r is not None else None),
        },
        "arms": arms,
        "bounds": outcome.bounds,
    }


def _record(registry: Any, change_id: str, step: str, verdict: str, body: dict[str, Any]) -> None:
    """Keep what a policy change rests on beside it in the registry (append-only)."""
    try:
        registry.store.record_evidence(
            change_id, step, verdict, json.dumps(body, sort_keys=True, default=str)
        )
    except Exception:  # noqa: BLE001 - the change stands; only its numbers are missing
        log.warning("rsi trainer: evidence of %s not kept", change_id, exc_info=True)
