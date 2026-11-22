"""What recorded runs would have come to under a tighter steering policy.

A candidate that only shortens what a run does (fewer follow-up orders, a
shorter wait for checks) can be judged on the record alone, without starting
an agent or a model: up to the point where it would have stopped, the run is
exactly what was recorded, and at that point the record says what the app
knew. That is the transfer of the paper's replay to Dodaios, limited to what
replay can judge honestly. A candidate that changes the text agents read can
never be replayed; it needs a canary.

* **Fewer follow-up orders** (``p_max`` lower than what a run used): the run
  stops at output ``p_max``, where a follow-up order was due, so it ends
  ``failed`` with the cost, time and churn of the outputs up to then.
* **A shorter wait for checks:** a run whose checks settled later than the
  candidate's wait ends ``unverified`` at the wait.
* **Outside the record** (a longer wait, more follow-up orders than recorded):
  nothing is known, so the run is not covered. Below :data:`MIN_COVERAGE` the
  replay says nothing and a canary has to answer.

Each replayed run is paired with the same run as recorded, so the comparison
is paired (sign flips), not a canary's permutation.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Final

from . import stats
from .policy import Policy
from .selector import (
    DELTA_PASS,
    FLOORS,
    KAPPA,
    LAMBDA_USD_PER_S,
    PASS_LCB_FLOOR,
    Claim,
    RunMetrics,
    metrics_of,
)

__all__ = ["MIN_COVERAGE", "Replay", "replay_run", "replay_cell"]

#: Share of runs the record must cover for a replay to answer.
MIN_COVERAGE: Final[float] = 0.90
#: Paired requests a replay needs (the plan's N_min for pairs).
N_MIN_PAIRED: Final[int] = 40
MIN_NONZERO: Final[int] = 5


@dataclass(slots=True)
class Replay:
    """A candidate's replay over one cell's recorded runs."""

    answer: str
    reasons: list[str] = field(default_factory=list)
    runs: int = 0
    covered: int = 0
    bounds: dict[str, dict[str, float]] = field(default_factory=dict)

    @property
    def coverage(self) -> float:
        return self.covered / self.runs if self.runs else 0.0


def _outputs(steps: Iterable[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """What the record holds per output: its turn's end, its scan, when its checks settled."""
    out: dict[int, dict[str, Any]] = {}
    for step in steps:
        k = int(step.get("iteration") or 0)
        entry = out.setdefault(k, {})
        name = str(step.get("step") or "")
        detail = step.get("detail") or {}
        if name == "turn_finished":
            entry["turn"] = detail
            entry["ended_ms"] = int(step.get("ts_ms") or 0)
        elif name == "gates":
            entry["scan"] = detail
        elif name == "evidence" or name.startswith("evidence:"):
            entry["settled_ms"] = int(step.get("ts_ms") or 0)
            entry["evidence"] = detail
    return out


def replay_run(
    run: dict[str, Any], steps: Sequence[dict[str, Any]], candidate: Policy
) -> RunMetrics | None:
    """``run`` as it would have ended under ``candidate``; ``None`` outside the record."""
    recorded = metrics_of(run)
    if recorded is None:
        return None
    try:
        ran = Policy.from_text(str(run.get("policy_json") or "") or None)
    except ValueError:  # a run without a readable policy is outside what can be replayed
        return None
    if candidate.p_max > ran.p_max or candidate.evidence_wait_s > ran.evidence_wait_s:
        return None  # it would have gone further than anything recorded
    outputs = _outputs(steps)
    follow_ups = int(run.get("follow_ups") or 0)
    if follow_ups > candidate.p_max:
        cut = candidate.p_max
        kept = [outputs.get(k, {}) for k in range(cut + 1)]
        if any("turn" not in o or "scan" not in o for o in kept):
            return None
        turns = [o["turn"] for o in kept]
        if any(t.get("duration_ms") is None for t in turns):
            return None  # a record from before turns kept their own cost
        seconds = sum(int(t.get("duration_ms") or 0) for t in turns) / 1000
        cost = sum(float(t.get("cost_usd") or 0.0) for t in turns) + LAMBDA_USD_PER_S * seconds
        scan = kept[-1]["scan"]
        return replace(
            recorded, passed=0.0, one=0.0, p=float(cut), cost=cost,
            churn=float(int(scan.get("added") or 0) + int(scan.get("deleted") or 0)),
        )
    if candidate.evidence_wait_s < ran.evidence_wait_s and recorded.passed:
        last = outputs.get(max(outputs) if outputs else 0, {})
        if "ended_ms" not in last or "settled_ms" not in last:
            return None
        waited_s = (last["settled_ms"] - last["ended_ms"]) / 1000
        if waited_s > candidate.evidence_wait_s:
            return replace(recorded, passed=0.0, one=0.0)
    return recorded


def _paired(metric: str, pairs: Sequence[tuple[RunMetrics, RunMetrics]]) -> Any:
    """Paired bound of candidate minus recorded, oriented so that positive is better."""
    sign = -1.0 if metric in ("p", "cost", "churn") else 1.0
    attr = "passed" if metric == "pass" else metric
    return stats.paired_lcb([sign * (getattr(c, attr) - getattr(r, attr)) for c, r in pairs])


def replay_cell(
    claim: Claim,
    rows: Iterable[tuple[dict[str, Any], Sequence[dict[str, Any]]]],
    candidate: Policy,
) -> Replay:
    """The gate's rule on a candidate's replay over the recorded runs of ``claim.cell``."""
    pairs: list[tuple[RunMetrics, RunMetrics]] = []
    runs = 0
    for run, steps in rows:
        recorded = metrics_of(run)
        if recorded is None or recorded.cell != claim.cell or recorded.mixed:
            continue
        runs += 1
        replayed = replay_run(run, steps, candidate)
        if replayed is not None:
            pairs.append((replayed, recorded))
    out = Replay("inconclusive", runs=runs, covered=len(pairs))
    if runs and out.coverage < MIN_COVERAGE:
        out.reasons.append(f"the record covers {out.coverage:.0%} of the runs; a canary is needed")
        return out
    if len(pairs) < N_MIN_PAIRED:
        out.reasons.append(f"fewer than {N_MIN_PAIRED} recorded runs to replay")
        return out
    bounds = {m: _paired(m, pairs) for m in ("pass", "one", "p", "cost", "churn")}
    out.bounds = {m: {"diff": b.diff, "lcb": b.lcb} for m, b in bounds.items()}
    passing = bounds["pass"]
    if passing.diff < 0:
        out.answer = "reject"
        out.reasons.append("the PassRate drops")
        return out
    if claim.branch == "A":
        ok = passing.diff >= DELTA_PASS and passing.lcb > 0
        cost_ok = sum(c.cost for c, _ in pairs) <= (1 + KAPPA) * sum(r.cost for _, r in pairs)
        out.answer = "accept" if ok and cost_ok else "reject"
        out.reasons.append("branch A on the replay")
        return out
    target = bounds[claim.target]
    nonzero = sum(
        1 for c, r in pairs if abs(getattr(c, claim.target) - getattr(r, claim.target)) > 1e-12
    )
    if nonzero < MIN_NONZERO or target.lcb <= 0:
        out.answer = "reject" if target.diff <= 0 else "inconclusive"
        out.reasons.append(f"branch B: no shown improvement of {claim.target} on the replay")
        return out
    if passing.lcb < PASS_LCB_FLOOR:
        out.reasons.append("the PassRate may drop by more than 0.10; more runs are needed")
        return out
    worse = [m for m in FLOORS if m != claim.target and _slips(m, pairs)]
    if worse:
        out.answer = "reject"
        out.reasons.append("branch B: below the floor on " + ", ".join(worse))
        return out
    out.answer = "accept"
    out.reasons.append(f"branch B: {claim.target} improves on the replay and nothing slips")
    return out


def _slips(metric: str, pairs: Sequence[tuple[RunMetrics, RunMetrics]]) -> bool:
    n = len(pairs)
    cand = sum(getattr(c, metric) for c, _ in pairs) / n
    ref = sum(getattr(r, metric) for _, r in pairs) / n
    if metric == "one":
        return cand < ref + FLOORS["one"]
    if metric == "p":
        return cand > ref + FLOORS["p"]
    return cand > ref * (1 + FLOORS[metric])


def describe(result: Replay) -> str:
    return json.dumps({
        "answer": result.answer, "reasons": result.reasons, "runs": result.runs,
        "covered": result.covered, "bounds": result.bounds,
    }, indent=2, sort_keys=True)
