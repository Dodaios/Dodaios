"""Mining recurring follow-up orders for one line the first brief was missing."""

from __future__ import annotations

from typing import Any

from dodaios.rsi import mining
from dodaios.rsi.policy import DEFAULT, Policy


def _run(n: int, template: str, reason: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    steps = [{"step": "follow_up_intent", "status": template, "detail": {"reason": reason}}]
    return {"run_id": f"job_{n}"}, steps


WEAKENED = "the change weakens the checks (C4 pyproject.toml; C1 tests/test_a.py)"
FAILING = "the repository's checks fail (unit (ubuntu), lint)"


def test_a_pattern_in_five_runs_becomes_one_line_citing_them():
    runs = [_run(n, "T2", WEAKENED) for n in range(5)]
    found = mining.suggest(DEFAULT, runs)
    assert found is not None
    assert found.cited == tuple(f"job_{n}" for n in range(5))
    assert found.line in (p.line for p in mining.PATTERNS if p.template == "T2")
    policy = found.policy(DEFAULT)
    assert policy.domain_block == found.line
    assert (policy.p_max, policy.evidence_wait_s) == (DEFAULT.p_max, DEFAULT.evidence_wait_s)


def test_four_runs_are_not_enough():
    assert mining.suggest(DEFAULT, [_run(n, "T2", WEAKENED) for n in range(4)]) is None


def test_a_run_counts_once_per_pattern_and_only_for_its_template():
    once = [({"run_id": "job_1"}, [
        {"step": "follow_up_intent", "status": "T1", "detail": {"reason": FAILING}},
        {"step": "follow_up_intent", "status": "T1", "detail": {"reason": FAILING}},
    ])]
    assert mining.suggest(DEFAULT, once * 4) is None
    wrong_template = [_run(n, "T1", WEAKENED) for n in range(6)]
    found = mining.suggest(DEFAULT, wrong_template)
    assert found is None or found.pattern not in ("check_files", "tests_kept")


def test_a_line_the_block_has_is_not_suggested_again_and_the_next_one_is():
    runs = [_run(n, "T1", FAILING) for n in range(6)]
    first = mining.suggest(DEFAULT, runs)
    assert first is not None
    second = mining.suggest(first.policy(DEFAULT), runs)
    assert second is not None and second.line != first.line
    both = second.policy(first.policy(DEFAULT))
    assert both.domain_block == f"{first.line}\n{second.line}"
    assert mining.suggest(both, runs) is None


def test_no_suggested_line_tells_agents_to_check_less():
    for pattern in mining.PATTERNS:
        Policy(domain_block=pattern.line)  # the policy's own guard would refuse it


def test_a_block_near_its_limit_takes_no_further_line():
    full = Policy(domain_block="x" * 590)
    assert mining.suggest(full, [_run(n, "T2", WEAKENED) for n in range(6)]) is None
