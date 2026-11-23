"""Run benchmark tasks under a state of the assistant, and pair two states.

``measure`` runs tasks under one overlay and returns one :class:`Result` per
task. ``pair`` puts the results of two states side by side: one difference per
task both states have a countable result for. That list of differences is what
the gate's test reads.

Each domain registers the function that runs one of its tasks. A domain that
needs no model (recall, skill choice) runs inside this process in
milliseconds; the others arrive with the replay runner.
"""

from __future__ import annotations

import hashlib
import random
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import dodaios
from dodaios.rsi import overlay as overlays
from dodaios.rsi import params
from dodaios.rsi.fingerprint import Fingerprint

from . import recall
from .model import Domain, Result, Task

__all__ = ["Paired", "Worlds", "arm_of", "measure", "pair", "runnable", "shuffled"]

#: World name -> what a domain needs to run a task there (a vault, a repository, ...).
Worlds = Mapping[str, Any]


def arm_of(overlay: overlays.Overlay | None, *, changes: Iterable[str] = ()) -> Fingerprint:
    """The fingerprint of the assistant as it runs under ``overlay`` (the live one for ``None``).

    For the domains that ask no model: app version, learned changes in effect
    and the parameter values the run reads.
    """
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


_RUNNERS: dict[Domain, Callable[[Task, Worlds], recall.Scored]] = {Domain.RECALL: _run_recall}


def runnable() -> list[Domain]:
    """The domains the benchmark can run today, in the order of :class:`Domain`."""
    return [domain for domain in Domain if domain in _RUNNERS]


def measure(
    tasks: Sequence[Task],
    overlay: overlays.Overlay,
    worlds: Worlds,
    *,
    arm: Fingerprint | None = None,
) -> list[Result]:
    """One result per task, computed under ``overlay``. Never touches live state.

    A task that cannot run (its world is missing, its runner failed) gets a
    void result that says why; one broken task never stops a night.
    """
    fingerprint = arm or arm_of(overlay)
    out: list[Result] = []
    with overlays.active(overlay):
        for task in tasks:
            started = time.perf_counter()
            runner = _RUNNERS.get(task.domain)
            try:
                if runner is None:
                    raise LookupError(f"nothing runs {task.domain.value} tasks yet")
                scored = runner(task, worlds)
                void = ""
            except Exception as exc:  # noqa: BLE001 — recorded on the result, the run goes on
                scored = recall.Scored(0.0, 0, f"{type(exc).__name__}: {exc}"[:200])
                void = "could not run"
            out.append(
                Result(
                    task_id=task.id,
                    task_digest=task.digest,
                    arm=fingerprint.id,
                    score=scored.score,
                    tokens=scored.tokens,
                    wall_ms=round((time.perf_counter() - started) * 1000),
                    void=void,
                    detail=scored.detail,
                    ts_ms=int(time.time() * 1000),
                )
            )
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
    result on an earlier wording of a task never meets one on today's.
    """
    base = {(r.task_id, r.task_digest): r for r in baseline if r.counts}
    rows = [
        (base[(r.task_id, r.task_digest)], r)
        for r in candidate
        if r.counts and (r.task_id, r.task_digest) in base
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
