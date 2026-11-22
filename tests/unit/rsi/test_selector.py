"""The selector's gate: exact bounds, and the fixed rule for "an improvement"."""

from __future__ import annotations

import random
from typing import Any

import pytest

from dodaios.rsi import selector, stats
from dodaios.rsi.selector import Claim, RunMetrics

# ---------------------------------------------------------------------- stats


def test_three_wins_and_no_loss_in_thirty_tasks_is_not_yet_proof():
    """The case a percentile bootstrap gets wrong: the exact sign-flip test says p = 1/8."""
    differences = [1.0] * 3 + [0.0] * 27
    assert stats.paired_p(differences) == pytest.approx(0.125)
    assert stats.paired_lcb(differences).lcb <= 1e-6


def test_a_clear_paired_gain_has_a_bound_above_zero():
    bound = stats.paired_lcb([1.0] * 12 + [0.0] * 18)
    assert bound.diff == pytest.approx(0.4)
    assert 0 < bound.lcb < 0.4


def test_the_unpaired_bound_is_calibrated_under_equal_arms():
    rng = random.Random(7)  # noqa: S311 - test data
    false_wins = 0
    for _ in range(40):
        a = [("x", float(rng.random() < 0.7)) for _ in range(60)]
        b = [("x", float(rng.random() < 0.7)) for _ in range(60)]
        false_wins += stats.unpaired_lcb(a, b, samples=400).lcb > 0
    assert false_wins <= 6  # about 5 % of 40 is 2


def test_a_real_unpaired_gain_is_found_and_the_bound_repeats():
    rng = random.Random(3)  # noqa: S311 - test data
    a = [("x", float(rng.random() < 0.9)) for _ in range(80)]
    b = [("x", float(rng.random() < 0.5)) for _ in range(80)]
    first = stats.unpaired_lcb(a, b, samples=500)
    assert first.lcb > 0.15
    assert stats.unpaired_lcb(a, b, samples=500) == first


def test_labels_are_only_permuted_within_blocks():
    # Block "new" is better for both arms; only the candidate has many runs there.
    a = [("new", 1.0)] * 30 + [("old", 0.0)] * 10
    b = [("new", 1.0)] * 10 + [("old", 0.0)] * 30
    bound = stats.unpaired_lcb(a, b, samples=500)
    # Unblocked, the candidate would look 0.5 better; within blocks it is not.
    assert bound.diff == pytest.approx(0.0)
    assert bound.lcb <= 0
    one_sided = stats.unpaired_lcb([("a", 1.0)] * 5, [("b", 0.0)] * 5)
    assert (one_sided.blocks_used, one_sided.lcb) == (0, float("-inf"))


# ------------------------------------------------------------------- the gate


CELL = "backend|claude-opus-5-5|claude-cli 2.1"


def _run(n: int, policy: str, *, passed: bool = True, follow_ups: int = 0, hard: bool = False,
         cost: float = 0.0, wall_ms: int = 60_000, churn: int = 40, mixed: bool = False,
         verdict: str | None = None) -> dict[str, Any]:
    return {
        "run_id": f"{policy}-{n}", "root_span_id": f"{policy}-root-{n}", "state": "ended",
        "verdict": verdict or ("verified" if passed else "unverified"), "verdict_reason": "",
        "follow_ups": follow_ups, "primary_domain": "backend", "model_requested": "claude-opus-5-5",
        "runner": "claude-cli", "harness_line": "2.1", "repo_id": "github.com/acme/notes",
        "policy_id": policy, "cost_usd": cost, "wall_ms": wall_ms, "churn_lines": churn,
        "gate_status": "violations" if hard else "clean", "mixed_model": int(mixed),
        "person_intervened": 0,
    }


def _gate(claim: Claim, candidate: list[RunMetrics], reference: list[RunMetrics]) -> Any:
    return selector.gate(claim, candidate, reference, samples=300)


def _metrics(rows: list[dict[str, Any]]) -> list[RunMetrics]:
    return [m for m in (selector.metrics_of(r) for r in rows) if m is not None]


def _arm(policy: str, n: int, pass_share: float, seed: int, **more: Any) -> list[RunMetrics]:
    rng = random.Random(seed)  # noqa: S311 - test data
    return _metrics([_run(i, policy, passed=rng.random() < pass_share, **more) for i in range(n)])


def test_what_a_run_counts_for():
    m = selector.metrics_of(_run(1, "p", follow_ups=1, cost=0.5, wall_ms=100_000))
    assert m is not None
    assert (m.passed, m.one, m.p) == (1.0, 0.0, 1.0)
    assert m.cost == pytest.approx(0.5 + 0.1)
    assert m.cell == CELL
    at_limit = _run(2, "p", passed=False, follow_ups=1)
    at_limit["verdict_reason"] = "x; no further follow-up order because it already got 2"
    assert selector.metrics_of(at_limit).p == 2.0
    assert selector.metrics_of(_run(3, "p", verdict="superseded")) is None
    assert selector.metrics_of({**_run(4, "p"), "state": "checking"}) is None


def test_too_few_requests_give_no_answer():
    got = _gate(Claim(CELL, "A"), _arm("c", 20, 0.9, 1), _arm("r", 20, 0.5, 2))
    assert got.answer == "inconclusive"
    assert "fewer than 60" in got.reasons[0]


def test_a_single_hard_event_rejects_the_candidate_whatever_else_it_does():
    cand = _arm("c", 70, 0.95, 1) + _metrics([_run(99, "c", hard=True)])
    got = _gate(Claim(CELL, "A"), cand, _arm("r", 70, 0.5, 2))
    assert got.answer == "reject"
    assert got.reasons[0].startswith("stage 1")


def test_branch_a_accepts_a_clear_rise_in_the_pass_rate():
    got = _gate(Claim(CELL, "A"), _arm("c", 80, 0.9, 1), _arm("r", 80, 0.5, 2))
    assert got.answer == "accept", got.reasons
    assert got.bounds["pass"]["lcb"] > 0


def test_branch_a_rejects_a_rise_that_costs_too_much():
    cand = _arm("c", 80, 0.9, 1, cost=2.0)
    got = _gate(Claim(CELL, "A"), cand, _arm("r", 80, 0.5, 2, cost=1.0))
    assert got.answer == "reject"
    assert "cost budget" in got.reasons[0]


def test_a_cheaper_policy_wins_on_branch_b_only_if_nothing_else_slips():
    cheaper = _arm("c", 200, 0.8, 5, wall_ms=30_000)
    reference = _arm("r", 200, 0.8, 5, wall_ms=90_000)
    got = _gate(Claim(CELL, "B", "cost"), cheaper, reference)
    assert got.answer == "accept", got.reasons
    churny = _arm("c", 200, 0.8, 5, wall_ms=30_000, churn=200)
    worse = _gate(Claim(CELL, "B", "cost"), churny, reference)
    assert worse.answer == "reject"
    assert "churn" in worse.reasons[0]


def test_too_few_runs_to_rule_out_a_pass_rate_loss_ask_for_more_not_a_verdict():
    """80 requests per arm at the same pass rate: the bound sits just below -0.10."""
    cheaper = _arm("c", 80, 0.8, 5, wall_ms=30_000)
    reference = _arm("r", 80, 0.8, 5, wall_ms=90_000)
    got = _gate(Claim(CELL, "B", "cost"), cheaper, reference)
    assert got.answer == "inconclusive"
    assert "more runs are needed" in got.reasons[0]


def test_a_policy_that_loses_pass_rate_never_wins_on_cost():
    cheap_but_worse = _arm("c", 80, 0.5, 1, wall_ms=10_000)
    got = _gate(Claim(CELL, "B", "cost"), cheap_but_worse, _arm("r", 80, 0.85, 2))
    assert got.answer == "reject"
    assert got.reasons[0] == "the PassRate drops"


def test_arms_that_lost_different_shares_to_mixed_runs_give_no_answer():
    cand = _arm("c", 70, 0.9, 1) + _metrics([_run(100 + i, "c", mixed=True) for i in range(20)])
    got = _gate(Claim(CELL, "A"), cand, _arm("r", 70, 0.5, 2))
    assert got.answer == "inconclusive"
    assert "model or CLI change" in got.reasons[0]


def test_runs_of_other_cells_do_not_count():
    other = [
        selector.metrics_of({**_run(i, "c"), "model_requested": "claude-haiku-4-5"})
        for i in range(80)
    ]
    got = _gate(Claim(CELL, "A"), [m for m in other if m], _arm("r", 80, 0.5, 2))
    assert (got.answer, got.n_candidate) == ("inconclusive", 0)


def test_a_claim_is_fixed_in_its_shape():
    with pytest.raises(ValueError):
        Claim(CELL, "C")
    with pytest.raises(ValueError):
        Claim(CELL, "B")
    with pytest.raises(ValueError):
        Claim(CELL, "B", "pass")
    assert Claim(CELL, "B", "one").target == "one"


def test_the_rule_is_made_of_constants():
    assert (selector.N_MIN, selector.DELTA_PASS, selector.PASS_LCB_FLOOR, selector.KAPPA) == (
        60, 0.10, -0.10, 0.25,
    )
    assert selector.FLOORS == {"one": -0.05, "p": 0.15, "cost": 0.10, "churn": 0.15}
