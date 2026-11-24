"""Run benchmark tasks under a state of the assistant, and pair two states.

``measure`` runs tasks under one overlay and returns one :class:`Result` per
task. ``pair`` puts the results of two states side by side: one difference per
task both states have a countable result for. That list of differences is what
the gate's test reads.

Each domain registers the function that runs one of its tasks. A domain that
needs no model (recall, skill choice) runs inside this process in
milliseconds. One that asks a model (``first_move``, ``brief``; ``NEEDS_MODEL``) keeps
every result it paid for: ``measure`` with a ``store`` reuses a counted result
of the same task content under the same arm, so an arm that did not change is
never paid for twice, and a comparison the night's budget cut short carries on
from there the next night.
"""

from __future__ import annotations

import hashlib
import random
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Protocol

import dodaios
from dodaios.rsi import lines, params
from dodaios.rsi import overlay as overlays
from dodaios.rsi.fingerprint import Fingerprint

from . import brief_replay, lead_replay, recall
from .model import NEEDS_MODEL, Domain, Measured, Result, Task

__all__ = [
    "REUSE_MS",
    "Paired",
    "ResultStore",
    "Worlds",
    "arm_of",
    "measure",
    "pair",
    "parts",
    "runnable",
    "shuffled",
]

#: World name -> what a domain needs to run a task there (a vault, a repository, ...).
Worlds = Mapping[str, Any]

#: How long a result that asked a model is reused for an unchanged arm.
REUSE_MS: Final[int] = 14 * 24 * 3600 * 1000


class ResultStore(Protocol):
    """Where results are kept (``BenchStore``)."""

    def add_results(self, results: Iterable[Result]) -> None: ...

    def reusable(self, task_id: str, digest: str, arm: str, *, since_ms: int) -> Result | None: ...


def _model_arm(
    overlay: overlays.Overlay | None, domain: Domain, platform: lead_replay.Platform
) -> Fingerprint:
    """The arm of a domain that asks a model: what shapes its runs, and nothing else.

    The values of the parameters the domain reads (the overlay's, else the
    live ones), every standing line's parameter (each is applied to every
    replayed message, whichever domain measures it), and what answers (CLI
    and its version, model, effort, tools, the input a request is put into).
    Nothing else that is learned changes a replay, so two states that agree
    on these are the same arm, and one result serves both.
    """
    names = [p.name for p in params.INDEX.params if domain.value in p.domains]
    names += [name for name in lines.LEARNABLE if name not in names]
    if overlay is None:
        values: dict[str, Any] = {name: params.get(name) for name in names}
    else:
        with overlays.active(overlay):
            values = {name: params.get(name) for name in names}
    values.update(platform.extra())
    return Fingerprint.of(params=values, model=platform.model, seat=platform.seat, cli=platform.cli)


def arm_of(
    overlay: overlays.Overlay | None,
    *,
    changes: Iterable[str] = (),
    domain: Domain | None = None,
    worlds: Worlds | None = None,
) -> Fingerprint:
    """The fingerprint of the assistant as it runs under ``overlay`` (the live one for ``None``).

    For the domains that ask no model: app version, learned changes in effect
    and the parameter values the run reads. For one that asks a model (its
    world names a platform): see :func:`_model_arm`.
    """
    world = (worlds or {}).get(domain.value) if domain is not None else None
    platform = getattr(world, "platform", None)
    if domain is not None and isinstance(platform, lead_replay.Platform):
        return _model_arm(overlay, domain, platform)
    if overlay is None:
        values = params.values()
        active = tuple(changes)
    else:
        with overlays.active(overlay):
            values = params.values()
        active = () if overlay.factory else tuple(c for c in changes if not overlay.excludes(c))
    return Fingerprint.of(app=dodaios.__version__, changes=active, params=values)


def _run_recall(task: Task, worlds: Worlds) -> recall.Scored:
    world = worlds.get(str(task.payload.get("world") or ""))
    if not isinstance(world, recall.RecallWorld):
        raise LookupError(f"no memory to run {task.id} against")
    return recall.score(task, world)


def _run_first_move(task: Task, worlds: Worlds) -> Measured:
    world = worlds.get(lead_replay.WORLD)
    if not isinstance(world, lead_replay.FirstMoveWorld):
        raise LookupError(f"no replay of the lead's turns to run {task.id} with")
    return lead_replay.run(task, world)


def _run_brief(task: Task, worlds: Worlds) -> Measured:
    world = worlds.get(brief_replay.WORLD)
    if not isinstance(world, brief_replay.BriefWorld):
        raise LookupError(f"no replay of the lead's turns to run {task.id} with")
    return brief_replay.run(task, world)


_RUNNERS: dict[Domain, Callable[[Task, Worlds], recall.Scored | Measured]] = {
    Domain.RECALL: _run_recall,
    Domain.FIRST_MOVE: _run_first_move,
    Domain.BRIEF: _run_brief,
}


def runnable() -> list[Domain]:
    """The domains the benchmark can run today, in the order of :class:`Domain`."""
    return [domain for domain in Domain if domain in _RUNNERS]


def measure(
    tasks: Sequence[Task],
    overlay: overlays.Overlay,
    worlds: Worlds,
    *,
    arm: Fingerprint | None = None,
    store: ResultStore | None = None,
) -> list[Result]:
    """One result per task, computed under ``overlay``. Never touches live state.

    A task that cannot run (its world is missing, its runner failed) gets a
    void result that says why; one broken task never stops a night.

    With ``store`` every new result is kept there, and a task of a domain that
    asks a model takes a counted result it already has for the same content
    and arm (from the last :data:`REUSE_MS`) instead of asking again.
    """
    fingerprint = arm or arm_of(overlay)
    out: list[Result] = []
    fresh: list[Result] = []
    since = int(time.time() * 1000) - REUSE_MS
    with overlays.active(overlay):
        for task in tasks:
            if store is not None and task.domain in NEEDS_MODEL:
                kept = store.reusable(task.id, task.digest, fingerprint.id, since_ms=since)
                if kept is not None:
                    out.append(kept)
                    continue
            started = time.perf_counter()
            runner = _RUNNERS.get(task.domain)
            scored: recall.Scored | Measured
            try:
                if runner is None:
                    raise LookupError(f"nothing runs {task.domain.value} tasks yet")
                scored = runner(task, worlds)
                void = str(getattr(scored, "void", "") or "")
            except Exception as exc:  # noqa: BLE001 — recorded on the result, the run goes on
                scored = recall.Scored(0.0, 0, f"{type(exc).__name__}: {exc}"[:200])
                void = "could not run"
            result = Result(
                task_id=task.id,
                task_digest=task.digest,
                arm=fingerprint.id,
                score=scored.score,
                tokens=scored.tokens,
                wall_ms=round((time.perf_counter() - started) * 1000),
                seat=str(getattr(scored, "seat", "") or ""),
                void=void,
                detail=scored.detail,
                ts_ms=int(time.time() * 1000),
            )
            out.append(result)
            fresh.append(result)
    if store is not None and fresh:
        store.add_results(fresh)
    return out


@dataclass(frozen=True, slots=True)
class Paired:
    """Two states on the same tasks."""

    #: Task ids, in the order the differences are in.
    task_ids: tuple[str, ...]
    #: Candidate score minus baseline score, per task.
    differences: tuple[float, ...]
    baseline_mean: float
    candidate_mean: float
    #: Mean tokens per task of each state.
    baseline_tokens: float
    candidate_tokens: float

    @property
    def n(self) -> int:
        return len(self.differences)


def pair(baseline: Sequence[Result], candidate: Sequence[Result]) -> Paired:
    """One difference per task that both states have a result for that counts.

    Results are matched by task and by the content they were measured on, so a
    result on an earlier wording of a task never meets one on today's. Two
    results that name a different seat (another model answered one of them)
    are no pair: a change of the model would pass as a change of the assistant.
    """
    base = {(r.task_id, r.task_digest): r for r in baseline if r.counts}
    rows = [
        (base[(r.task_id, r.task_digest)], r)
        for r in candidate
        if r.counts
        and (r.task_id, r.task_digest) in base
        and base[(r.task_id, r.task_digest)].seat == r.seat
    ]
    if not rows:
        return Paired((), (), 0.0, 0.0, 0.0, 0.0)
    n = len(rows)
    return Paired(
        task_ids=tuple(c.task_id for _, c in rows),
        differences=tuple(c.score - b.score for b, c in rows),
        baseline_mean=sum(b.score for b, _ in rows) / n,
        candidate_mean=sum(c.score for _, c in rows) / n,
        baseline_tokens=sum(b.tokens for b, _ in rows) / n,
        candidate_tokens=sum(c.tokens for _, c in rows) / n,
    )


#: Domain -> the part of it a task belongs to, for showing where a difference lies.
_PARTS: dict[Domain, Callable[[Task], str]] = {Domain.RECALL: recall.part_of}


def parts(
    tasks: Sequence[Task], baseline: Sequence[Result], candidate: Sequence[Result]
) -> dict[str, dict[str, Any]]:
    """The two states side by side per part of the domain (``{}`` for a domain without parts).

    Matched like :func:`pair`. Plain means on the tasks of each part, with no
    interval: they show where a difference lies; decisions rest on the whole.
    """
    if not tasks:
        return {}
    part_of = _PARTS.get(tasks[0].domain)
    if part_of is None:
        return {}
    kinds = {t.id: part_of(t) for t in tasks}
    base = {(r.task_id, r.task_digest): r for r in baseline if r.counts}
    sums: dict[str, list[float]] = {}
    for r in candidate:
        b = base.get((r.task_id, r.task_digest))
        if not r.counts or b is None or b.seat != r.seat or r.task_id not in kinds:
            continue
        row = sums.setdefault(kinds[r.task_id], [0.0, 0.0, 0.0, 0.0, 0.0])
        row[0] += 1
        row[1] += b.score
        row[2] += r.score
        row[3] += b.tokens
        row[4] += r.tokens
    return {
        kind: {
            "n": int(n),
            "factory_score": round(b / n, 4),
            "now_score": round(c / n, 4),
            "factory_tokens": round(bt / n, 2),
            "now_tokens": round(ct / n, 2),
        }
        for kind, (n, b, c, bt, ct) in sorted(sums.items())
    }


def shuffled(tasks: Sequence[Task], seed: str) -> list[Task]:
    """The tasks in an order fixed by ``seed`` alone, before any result is known.

    The gate's test may be read after every task only when the order does not
    depend on the results. The seed names the comparison (the candidate, the
    night), so the same comparison always walks the tasks in the same order.
    """
    ordered = sorted(tasks, key=lambda t: t.id)
    digest = hashlib.sha256(seed.encode()).digest()
    random.Random(int.from_bytes(digest[:8], "big")).shuffle(ordered)  # noqa: S311 - an order
    return ordered
