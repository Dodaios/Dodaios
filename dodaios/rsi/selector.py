"""The policy selector's gate: when is a candidate policy an improvement?

This is the formal definition the plan fixed (decisions 5.3 and 5.7 of
2026-11-22), applied to recorded runs of one *cell*: the domain a run was bound
to, the requested model, and the harness (runner and CLI version line). Runs
are compared only inside a cell, and only runs whose answering model and CLI
line stayed the same throughout.

**Per run** (only runs that ended with a verdict under enforced checks):

* ``pass`` 1 when the run ended ``verified``; 0 otherwise. ``superseded``
  runs (the person took over) are nobody's result and are left out.
* ``one`` ``pass`` and no follow-up order, no person stepping in.
* ``P`` follow-up orders; a run that ran into the limit counts the limit.
* ``C`` cost in USD plus 0.001 USD per second of turn time.
* ``churn`` lines added plus deleted.
* ``hard`` a weakened check or an off-limits change in the final output.

The unit is the person's request: runs of one request are averaged per arm.

**Stage 1, hard exclusions:** the candidate has no ``hard`` event at all.

**Stage 2, lexicographic dominance** over (PassRate, OneShotRate, -P, -C,
-churn), differences oriented so that positive is better:

* always: the PassRate does not drop, and its lower bound is at least -0.10
  (a drop rejects; a bound below -0.10 without a drop asks for more runs);
* branch A: PassRate rises by at least 0.10, its lower bound is above zero,
  and the cost stays within 125 % of the reference;
* branch B: the lower bound of the pre-registered target metric is above
  zero, and every other metric stays above its floor (OneShot -0.05, P +0.15,
  cost +10 %, churn +15 % of the reference).

At least :data:`N_MIN` requests per arm; otherwise the answer is
``inconclusive``. When the arms lost different shares of their runs to the
"mixed" rule the answer is ``inconclusive`` too.

The answer is a report: nothing here switches a policy.

    python -m dodaios.rsi.selector --cell CELL --candidate ID --reference ID --branch A
    python -m dodaios.rsi.selector --cells        # the cells on record, largest first
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Final

from . import stats

__all__ = [
    "BRANCHES",
    "METRICS",
    "N_MIN",
    "Claim",
    "Outcome",
    "RunMetrics",
    "cell_of",
    "gate",
    "metrics_of",
    "units",
]

#: Requests per arm before any answer.
N_MIN: Final[int] = 60
#: Cost of a second of turn time, in USD (as in the agent score).
LAMBDA_USD_PER_S: Final[float] = 0.001
DELTA_PASS: Final[float] = 0.10
PASS_LCB_FLOOR: Final[float] = -0.10
KAPPA: Final[float] = 0.25
#: How far a guarded metric may move against the candidate in branch B.
FLOORS: Final[dict[str, float]] = {"one": -0.05, "p": 0.15, "cost": 0.10, "churn": 0.15}
#: Largest allowed gap between the arms' shares of left-out ("mixed") runs.
MIXED_GAP: Final[float] = 0.10
#: The follow-up limit a run that ran into it counts (``driver.MAX_FOLLOW_UPS``).
P_MAX: Final[int] = 2
METRICS: Final[tuple[str, ...]] = ("pass", "one", "p", "cost", "churn")
#: Metrics where less is better: their difference is reference minus candidate.
_LOWER_IS_BETTER: Final[frozenset[str]] = frozenset({"p", "cost", "churn"})
BRANCHES: Final[tuple[str, ...]] = ("A", "B")

ACCEPT: Final[str] = "accept"
REJECT: Final[str] = "reject"
INCONCLUSIVE: Final[str] = "inconclusive"


@dataclass(frozen=True, slots=True)
class Claim:
    """What a candidate claims, fixed before its data exist."""

    cell: str
    branch: str
    #: Branch B's target metric (``one``, ``p``, ``cost`` or ``churn``).
    target: str = ""

    def __post_init__(self) -> None:
        if self.branch not in BRANCHES:
            raise ValueError(f"unknown branch: {self.branch!r}")
        if self.branch == "B" and self.target not in METRICS[1:]:
            raise ValueError(f"branch B needs a target metric, not {self.target!r}")


@dataclass(frozen=True, slots=True)
class RunMetrics:
    run_id: str
    root: str
    cell: str
    block: str
    policy: str
    passed: float
    one: float
    p: float
    cost: float
    churn: float
    hard: bool
    mixed: bool


@dataclass(slots=True)
class Outcome:
    """The gate's answer, with every number it rests on."""

    answer: str
    reasons: list[str] = field(default_factory=list)
    n_candidate: int = 0
    n_reference: int = 0
    bounds: dict[str, dict[str, float]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def cell_of(run: dict[str, Any]) -> str:
    """The cell of a run: domain at binding, requested model, runner and CLI line."""
    domain = str(run.get("primary_domain") or "other")
    model = str(run.get("model_requested") or "(default)")
    harness = f"{run.get('runner') or run.get('provider') or '?'} {run.get('harness_line') or ''}"
    return f"{domain}|{model}|{harness.strip()}"


def metrics_of(run: dict[str, Any]) -> RunMetrics | None:
    """What one recorded run counts for, or ``None`` when it does not count at all."""
    verdict = str(run.get("verdict") or "")
    if run.get("state") != "ended" or not verdict or verdict == "superseded":
        return None
    reason = str(run.get("verdict_reason") or "")
    follow_ups = int(run.get("follow_ups") or 0)
    at_limit = "no further follow-up order" in reason
    # Verified work that turned red after it merged did not pass.
    passed = 1.0 if verdict == "verified" and not run.get("leaked") else 0.0
    seconds = float(run.get("wall_ms") or 0) / 1000
    return RunMetrics(
        run_id=str(run.get("run_id") or ""),
        root=str(run.get("root_span_id") or run.get("run_id") or ""),
        cell=cell_of(run),
        block=f"{run.get('harness_line') or ''}|{run.get('repo_id') or ''}",
        policy=str(run.get("policy_id") or ""),
        passed=passed,
        one=1.0 if passed and not follow_ups and not run.get("person_intervened") else 0.0,
        p=float(P_MAX if at_limit else follow_ups),
        cost=float(run.get("cost_usd") or 0.0) + LAMBDA_USD_PER_S * seconds,
        churn=float(run.get("churn_lines") or 0),
        hard=str(run.get("gate_status") or "") == "violations" or bool(run.get("leaked")),
        mixed=bool(run.get("mixed_model")),
    )


def units(rows: Iterable[RunMetrics]) -> list[dict[str, Any]]:
    """One unit per (request, cell, policy): the mean of its runs."""
    grouped: dict[tuple[str, str, str], list[RunMetrics]] = defaultdict(list)
    for row in rows:
        if not row.mixed:
            grouped[(row.root, row.cell, row.policy)].append(row)
    out = []
    for (root, cell, policy), members in grouped.items():
        n = len(members)
        out.append({
            "root": root, "cell": cell, "policy": policy, "block": members[0].block,
            "pass": sum(m.passed for m in members) / n,
            "one": sum(m.one for m in members) / n,
            "p": sum(m.p for m in members) / n,
            "cost": sum(m.cost for m in members) / n,
            "churn": sum(m.churn for m in members) / n,
            "hard": any(m.hard for m in members),
        })
    return out


def _bound(
    metric: str, cand: Sequence[dict[str, Any]], ref: Sequence[dict[str, Any]], samples: int
) -> Any:
    sign = -1.0 if metric in _LOWER_IS_BETTER else 1.0  # oriented so that positive is better
    return stats.unpaired_lcb(
        [(u["block"], sign * u[metric]) for u in cand],
        [(u["block"], sign * u[metric]) for u in ref],
        samples=samples,
    )


def _mean(rows: Sequence[dict[str, Any]], metric: str) -> float:
    return sum(r[metric] for r in rows) / len(rows) if rows else 0.0


def gate(
    claim: Claim,
    candidate: Sequence[RunMetrics],
    reference: Sequence[RunMetrics],
    *,
    n_min: int = N_MIN,
    samples: int = stats.SAMPLES,
) -> Outcome:
    """Whether ``candidate`` improves on ``reference`` in ``claim.cell``, by the fixed rule."""
    cand_runs = [r for r in candidate if r.cell == claim.cell]
    ref_runs = [r for r in reference if r.cell == claim.cell]
    cand = units(cand_runs)
    ref = units(ref_runs)
    out = Outcome(INCONCLUSIVE, n_candidate=len(cand), n_reference=len(ref))
    if any(r.hard for r in cand_runs):
        out.answer = REJECT
        out.reasons.append("stage 1: the candidate weakened a check or changed an off-limits path")
        return out
    if len(cand) < n_min or len(ref) < n_min:
        out.reasons.append(f"fewer than {n_min} requests per arm")
        return out
    mixed_c = sum(r.mixed for r in cand_runs) / max(1, len(cand_runs))
    mixed_r = sum(r.mixed for r in ref_runs) / max(1, len(ref_runs))
    if abs(mixed_c - mixed_r) > MIXED_GAP:
        out.reasons.append("the arms lost different shares of their runs to a model or CLI change")
        return out
    bounds = {metric: _bound(metric, cand, ref, samples) for metric in METRICS}
    out.bounds = {
        metric: {"diff": b.diff, "lcb": b.lcb, "blocks": b.blocks_used}
        for metric, b in bounds.items()
    }
    passing = bounds["pass"]
    if passing.diff < 0:
        out.answer = REJECT
        out.reasons.append("the PassRate drops")
        return out
    if passing.lcb < PASS_LCB_FLOOR:
        # Not a loss, but not enough runs to rule one out: more data, not a verdict.
        out.reasons.append("the PassRate may still drop by more than 0.10; more runs are needed")
        return out
    if claim.branch == "A":
        ref_cost = _mean(ref, "cost")
        if passing.diff >= DELTA_PASS and passing.lcb > 0 and _mean(cand, "cost") <= (
            1 + KAPPA
        ) * ref_cost:
            out.answer = ACCEPT
            out.reasons.append(
                "branch A: the PassRate rises by 0.10 or more within the cost budget"
            )
        else:
            out.answer = REJECT
            out.reasons.append("branch A: no PassRate rise of 0.10 shown within the cost budget")
        return out
    target = bounds[claim.target]
    if target.lcb <= 0:
        if target.diff <= 0:
            out.answer = REJECT
            out.reasons.append(f"branch B: {claim.target} does not improve")
        else:
            out.reasons.append(f"branch B: {claim.target} may improve; more runs are needed")
        return out
    broken = [metric for metric in FLOORS if metric != claim.target and _below_floor(
        metric, cand, ref
    )]
    if broken:
        out.answer = REJECT
        out.reasons.append("branch B: below the floor on " + ", ".join(broken))
        return out
    out.answer = ACCEPT
    out.reasons.append(f"branch B: {claim.target} improves and every other metric holds")
    return out


def _below_floor(
    metric: str, cand: Sequence[dict[str, Any]], ref: Sequence[dict[str, Any]]
) -> bool:
    c, r = _mean(cand, metric), _mean(ref, metric)
    if metric == "one":
        return c < r + FLOORS["one"]
    if metric == "p":
        return c > r + FLOORS["p"]
    return c > r * (1 + FLOORS[metric])


def report(rows: Iterable[dict[str, Any]], claim: Claim, candidate: str, reference: str) -> str:
    """The gate's answer for two policies' recorded runs, as text."""
    metrics = [m for m in (metrics_of(r) for r in rows) if m is not None]
    outcome = gate(
        claim,
        [m for m in metrics if m.policy == candidate],
        [m for m in metrics if m.policy == reference],
    )
    return json.dumps(outcome.to_dict(), indent=2, sort_keys=True)


def main(argv: Sequence[str] | None = None) -> int:
    from .report import default_db, load_runs

    parser = argparse.ArgumentParser(prog="python -m dodaios.rsi.selector", description=__doc__)
    parser.add_argument("--db", type=Path, default=None, help="path of verification.db")
    parser.add_argument("--cells", action="store_true", help="list the cells and their policies")
    parser.add_argument("--cell", default="")
    parser.add_argument("--candidate", default="", help="the candidate's policy id")
    parser.add_argument("--reference", default="", help="the reference's policy id")
    parser.add_argument("--branch", default="A", choices=BRANCHES)
    parser.add_argument("--target", default="", help="branch B's target metric")
    args = parser.parse_args(argv)
    runs = load_runs(args.db or default_db())
    if args.cells:
        counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for row in (metrics_of(r) for r in runs):
            if row is not None:
                counts[row.cell][row.policy or "(none)"] += 1
        listing = {cell: dict(policies) for cell, policies in counts.items()}
        sys.stdout.write(json.dumps(listing, indent=2, sort_keys=True) + "\n")
        return 0
    if not (args.cell and args.candidate and args.reference):
        parser.error("--cell, --candidate and --reference are needed (or --cells)")
    claim = Claim(args.cell, args.branch, args.target)
    sys.stdout.write(report(runs, claim, args.candidate, args.reference) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
