"""The decision after a run's output was checked, and the follow-up orders it writes."""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

from dodaios.orchestrator.verification import driver, evidence, prompts
from dodaios.orchestrator.verification.driver import (
    CLOSE,
    EVIDENCE_WAIT_S,
    FOLLOW_UP,
    MAX_FOLLOW_UPS,
    MAX_ROOT_FOLLOW_UPS,
    MAX_RUN_TOKENS_OUT,
    WAIT,
    decide,
    result_line,
)

ENDED = 1_000_000
CLEAN = {"status": "clean", "tree_id": "t1", "committed": True, "base": "b" * 40}
FINDINGS = {**CLEAN, "status": "findings"}
VIOLATION = {
    "rule": "C1", "severity": "violation", "path": "tests/test_calc.py", "line": 0,
    "excerpt": "", "note": "a test file was deleted",
}
WEAKENED = {**CLEAN, "status": "violations", "findings": [VIOLATION]}
PASSING = {"landing": "merged", "checks": "passing", "reason": "pull request #4 is merged"}
FAILING = {
    "landing": "pr_open", "checks": "failing", "pr": 4, "failing": ["unit (ubuntu)", "lint"],
    "reason": "pull request #4 is open",
}
RUNNING = {"landing": "pr_open", "checks": "running", "pr": 4, "reason": "pull request #4 is open"}


def _run(**fields: Any) -> dict[str, Any]:
    return {"turn_status": "done", "ended_ms": ENDED, "follow_ups": 0, **fields}


def _after(seconds: float) -> int:
    return ENDED + int(seconds * 1000)


def _decide(run=None, scan=CLEAN, found=PASSING, **more: Any) -> driver.Decision:
    return decide(run or _run(), scan, found, now_ms=more.pop("now_ms", _after(1)), **more)


# ------------------------------------------------------------------ closing


def test_a_clean_output_with_passing_checks_is_verified():
    got = _decide()
    assert (got.action, got.verdict) == (CLOSE, "verified")
    assert "pull request #4 is merged" in got.reason


@pytest.mark.parametrize(
    ("scan", "says"),
    [
        (FINDINGS, "points to look at"),
        ({**CLEAN, "committed": False}, "beyond the commit"),
    ],
)
def test_passing_checks_on_an_output_with_doubts_are_not_proof(scan, says):
    got = _decide(scan=scan)
    assert (got.action, got.verdict) == (CLOSE, "unverified")
    assert says in got.reason


@pytest.mark.parametrize(
    ("run", "verdict", "says"),
    [
        (_run(person_intervened=1), "superseded", "the person wrote"),
        (_run(turn_status="cancelled"), "superseded", "stopped"),
        (_run(turn_status="error"), "failed", "ended as error"),
        (_run(turn_status=""), "failed", "ended as unknown"),
    ],
)
def test_a_turn_that_did_not_end_well_is_never_asked_again(run, verdict, says):
    got = _decide(run=run, scan=WEAKENED, found=FAILING)
    assert (got.action, got.verdict) == (CLOSE, verdict)
    assert says in got.reason


def test_an_output_that_could_not_be_pinned_on_the_run_is_unverified():
    for scan in ({"status": "unattributed", "reason": "no checkout of its own"}, None, {}):
        got = _decide(scan=scan, found=FAILING)
        assert (got.action, got.verdict) == (CLOSE, "unverified")


def test_work_that_is_not_on_github_is_unverified_at_once():
    found = {"landing": "none", "checks": "none", "reason": "the work is not committed"}
    got = _decide(found=found)
    assert (got.action, got.verdict, got.reason) == (CLOSE, "unverified", found["reason"])
    assert _decide(found=None).verdict == "unverified"


# ------------------------------------------------------------------ waiting


def test_running_checks_are_waited_for_up_to_the_limit():
    assert _decide(found=RUNNING).action == WAIT
    assert _decide(found=RUNNING, now_ms=_after(EVIDENCE_WAIT_S - 1)).action == WAIT
    late = _decide(found=RUNNING, now_ms=_after(EVIDENCE_WAIT_S))
    assert (late.action, late.verdict) == (CLOSE, "unverified")
    assert "still ran after the wait" in late.reason


def test_a_commit_on_github_without_checks_is_given_a_few_minutes():
    found = {"landing": "pushed", "checks": "none", "reason": "in no pull request"}
    assert _decide(found=found).action == WAIT
    got = _decide(found=found, now_ms=_after(evidence.NO_CHECKS_GIVE_UP_S))
    assert (got.action, got.verdict) == (CLOSE, "unverified")
    assert "has no checks" in got.reason


def test_github_out_of_reach_is_waited_for_and_then_given_up():
    found = {"landing": "unknown", "checks": "unknown", "reason": "down", "transient": True}
    assert _decide(found=found).action == WAIT
    assert _decide(found=found, now_ms=_after(evidence.NO_CHECKS_GIVE_UP_S)).verdict == (
        "unverified"
    )
    signed_out = {"landing": "unknown", "checks": "unknown", "reason": "not connected"}
    assert _decide(found=signed_out).verdict == "unverified"


# --------------------------------------------------------------- following up


def test_a_weakened_check_brings_one_follow_up_order_built_from_the_finding():
    got = _decide(scan=WEAKENED, found=PASSING)
    assert got.action == FOLLOW_UP
    assert got.template == prompts.T2
    assert got.signature.startswith("scan:")
    assert "C1 tests/test_calc.py" in got.reason
    assert "- C1 tests/test_calc.py: a test file was deleted" in got.prompt
    assert "`bbbbbbbbbbbb`" in got.prompt
    assert got.prompt.rstrip().endswith(
        "RESULT: needs-decision: <the question the person has to answer>"
    )


def test_failing_checks_bring_a_follow_up_order_that_names_them():
    got = _decide(found=FAILING)
    assert (got.action, got.template) == (FOLLOW_UP, prompts.T1)
    assert "- unit (ubuntu)\n- lint" in got.prompt
    assert "`gh pr checks 4`" in got.prompt
    assert "(pull request #4 is open)" in got.prompt
    assert "unit (ubuntu), lint" in got.reason


def test_the_same_finding_twice_is_not_asked_about_a_third_time():
    first = _decide(found=FAILING)
    run = _run(follow_ups=1, signatures_json=json.dumps([first.signature]))
    again = _decide(run=run, scan={**CLEAN, "tree_id": "t2"}, found=FAILING, previous_tree="t1")
    assert (again.action, again.verdict) == (CLOSE, "failed")
    assert "again after a follow-up order" in again.reason
    # The order of the names does not make it another finding.
    swapped = {**FAILING, "failing": ["lint", "unit (ubuntu)"]}
    assert _decide(found=swapped).signature == first.signature


def test_a_follow_up_that_changed_nothing_ends_the_run():
    first = _decide(scan=WEAKENED)
    run = _run(follow_ups=1, signatures_json=json.dumps([first.signature]))
    got = _decide(run=run, found=FAILING, previous_tree="t1")
    assert (got.action, got.verdict) == (CLOSE, "failed")
    assert "changed nothing" in got.reason


def test_a_new_finding_after_a_follow_up_is_asked_about():
    first = _decide(scan=WEAKENED)
    run = _run(follow_ups=1, signatures_json=json.dumps([first.signature]))
    got = _decide(run=run, scan={**CLEAN, "tree_id": "t2"}, found=FAILING, previous_tree="t1")
    assert (got.action, got.template) == (FOLLOW_UP, prompts.T1)


@pytest.mark.parametrize(
    ("run", "more", "says"),
    [
        (_run(follow_ups=MAX_FOLLOW_UPS), {}, f"already got {MAX_FOLLOW_UPS}"),
        (_run(), {"root_follow_ups": MAX_ROOT_FOLLOW_UPS}, "request's budget"),
        (_run(tokens_out=MAX_RUN_TOKENS_OUT), {}, "token budget"),
        (_run(), {"same_boot": False}, "app restarted"),
    ],
)
def test_the_limits_turn_a_follow_up_into_a_failure(run, more, says):
    got = _decide(run=run, found=FAILING, **more)
    assert (got.action, got.verdict) == (CLOSE, "failed")
    assert says in got.reason
    assert "fail" in got.reason


def test_the_limits_are_constants_of_the_code():
    assert (MAX_FOLLOW_UPS, MAX_ROOT_FOLLOW_UPS) == (2, 16)
    assert EVIDENCE_WAIT_S == 45 * 60


# ------------------------------------------------------- what the agent says


def test_the_closing_line_is_read_only_after_a_follow_up_order():
    asked = _run(follow_ups=1, signatures_json=json.dumps(["checks:x"]))
    decision = _decide(
        run=asked, found=FAILING, said="I looked.\nRESULT: needs-decision: keep the old API?"
    )
    assert (decision.action, decision.verdict) == (CLOSE, "needs_decision")
    assert decision.reason == "keep the old API?"
    gave_up = _decide(run=asked, said="RESULT: cannot-fix: the CI runner is down")
    assert (gave_up.verdict, gave_up.reason) == (
        "failed", "the agent could not fix it: the CI runner is down",
    )
    # Before any follow-up order the line means nothing: the checks decide.
    assert _decide(said="RESULT: cannot-fix: no").verdict == "verified"


def test_fixed_is_never_taken_for_proof():
    asked = _run(follow_ups=1, signatures_json=json.dumps(["checks:other"]))
    got = _decide(run=asked, scan={**CLEAN, "tree_id": "t2"}, found=FAILING,
                  said="RESULT: fixed", previous_tree="t1")
    assert got.action == FOLLOW_UP


@pytest.mark.parametrize(
    ("text", "wanted"),
    [
        ("Done.\nRESULT: fixed", ("fixed", "")),
        ("RESULT: cannot-fix: flaky runner", ("cannot-fix", "flaky runner")),
        ("**RESULT: needs-decision: which API?**", ("needs-decision", "which API?")),
        ("`RESULT: Fixed`", ("fixed", "")),
        ("The RESULT: fixed line comes later", ("", "")),
        ("", ("", "")),
    ],
)
def test_the_closing_line_is_found_at_the_end(text, wanted):
    assert result_line(text) == wanted


def test_a_closing_line_far_above_the_end_does_not_count():
    text = "RESULT: fixed\n" + "\n".join(f"line {n}" for n in range(10))
    assert result_line(text) == ("", "")


# ------------------------------------------------------------------ templates


def test_the_templates_carry_no_round_number_or_budget():
    for prompt in (
        prompts.failing_checks(["unit"], pr=3),
        prompts.weakened_checks([VIOLATION], base="abc"),
    ):
        words = set(re.findall(r"[a-z]+", prompt.lower()))
        assert not words & {"attempt", "round", "iteration", "budget", "remaining"}
        assert not re.search(r"\d+ (of|out of) \d+", prompt)
        assert prompt.count("RESULT:") == 3


def test_a_long_list_of_findings_is_cut():
    many = [{**VIOLATION, "path": f"tests/test_{n}.py"} for n in range(20)]
    text = prompts.weakened_checks(many)
    assert "tests/test_11.py" in text and "tests/test_12.py" not in text
    assert "and 8 more" in text
    names = prompts.failing_checks([f"job {n}" for n in range(15)])
    assert "- job 11" in names and "- job 12" not in names and "and 3 more" in names
    assert "`gh run list`" in names
