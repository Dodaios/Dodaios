"""What the person did next: a takeover, a request asked again, a closed pull request, a revert."""

from __future__ import annotations

import time

import pytest

from dodaios.orchestrator.verification.recorder import LEAK_CHECKS_H
from dodaios.rsi import selector
from tests.unit.orchestrator import test_verification_follow_up as base

Rig = base.Rig
evidence = base.evidence
HOUR = 3600 * 1000
OPEN_PASSING = evidence.Evidence("pr_open", "passing", pr=4, reason="pull request #4 is open")
CLOSED = evidence.Evidence("pr_closed", "passing", pr=4, reason="pull request #4 was closed")


@pytest.fixture
def rig(tmp_path):
    """The follow-up loop's rig in a linked worktree, under the factory policy."""
    main = tmp_path / "main"
    (main / "tests").mkdir(parents=True)
    base._git(main, "init", "-q", "-b", "main")
    base._git(main, "config", "user.email", "t@example.com")
    base._git(main, "config", "user.name", "T")
    (main / "calc.py").write_text(base.CODE, encoding="utf-8")
    (main / "tests" / "test_calc.py").write_text(base.TEST, encoding="utf-8")
    base._git(main, "add", "-A")
    base._git(main, "commit", "-q", "-m", "first")
    linked = tmp_path / "linked"
    base._git(main, "worktree", "add", "-q", "-b", "work", str(linked))
    made = base.Rig(tmp_path, linked)
    made.recorder = made.new_recorder(hold=False)
    yield made
    made.store.close()


def _steps(rig: Rig) -> list[str]:
    return [s["step"] for s in rig.store.steps("job_1")]


def _next_order(rig: Rig, prompt: str, job_id: str = "job_2") -> None:
    sent_at = int(time.time() * 1000)
    rig.emit("turn_started", {"turn_id": "t9", "runner": "claude-cli"})
    rig.recorder.note_submission(
        job_id=job_id, session_id=rig.sid, prompt=prompt, started_ms=sent_at
    )
    rig.recorder.process_pending()


# ------------------------------------------------------------------ takeover


def test_a_message_in_the_middle_of_the_turn_is_a_takeover_and_counts_as_failed(rig: Rig):
    rig.order()
    rig.emit("user_message", {"text": "let me do this part myself"})
    rig.recorder.process_pending()
    run = rig.turn("t1", rig.commit)
    assert (run["verdict"], run["taken_over"], run["person_intervened"]) == ("superseded", 1, 1)
    [taken] = [s for s in rig.store.steps("job_1") if s["step"] == "taken_over"]
    assert taken["status"] == "midturn"
    counted = selector.metrics_of(run)
    assert counted is not None and counted.passed == 0.0


def test_a_correction_of_the_result_is_a_takeover_and_the_run_is_still_judged(rig: Rig):
    rig.github.answer = base.RUNNING_CHECKS
    rig.order()
    rig.turn("t1", rig.commit)
    rig.emit("user_message", {"text": "No, that is not what I meant."})
    rig.recorder.process_pending()
    run = rig.store.get("job_1")
    assert (run["state"], run["taken_over"]) == ("checking", 1)
    assert "taken_over" in _steps(rig) and "detached" in _steps(rig)
    rig.github.answer = base.PASSING
    rig.clock.ahead += 3 * 60
    rig.recorder.tick()
    run = rig.store.get("job_1")
    assert run["verdict"] == "verified"
    assert selector.metrics_of(run).passed == 0.0  # the person did not get what they wanted


def test_a_held_run_the_person_corrects_ends_superseded_and_counts_as_failed(rig: Rig):
    rig.recorder = rig.new_recorder(hold=True)
    rig.github.answer = base.RUNNING_CHECKS
    rig.order()
    rig.turn("t1", rig.commit)
    rig.emit("user_message", {"text": "undo that, please"})
    rig.recorder.process_pending()
    run = rig.store.get("job_1")
    assert (run["verdict"], run["taken_over"]) == ("superseded", 1)
    assert selector.metrics_of(run).passed == 0.0


def test_an_unrelated_next_order_is_no_takeover_and_the_run_keeps_its_verdict(rig: Rig):
    rig.github.answer = base.RUNNING_CHECKS
    rig.order()
    rig.turn("t1", rig.commit)
    _next_order(rig, "Now also add a page to the docs about the release process.")
    run = rig.store.get("job_1")
    assert (run["state"], run["taken_over"], run["asked_again"]) == ("checking", 0, 0)
    rig.github.answer = base.PASSING
    rig.clock.ahead += 3 * 60
    rig.recorder.tick()
    run = rig.store.get("job_1")
    assert run["verdict"] == "verified"
    assert selector.metrics_of(run).passed == 1.0


def test_an_unrelated_message_from_the_person_is_no_takeover(rig: Rig):
    rig.github.answer = base.RUNNING_CHECKS
    rig.order()
    rig.turn("t1", rig.commit)
    rig.emit("user_message", {"text": "thanks, while you are at it write the changelog"})
    rig.recorder.process_pending()
    run = rig.store.get("job_1")
    assert (run["taken_over"], run["person_intervened"]) == (0, 0)


def test_the_same_request_again_from_the_lead_marks_the_run_asked_again(rig: Rig):
    rig.github.answer = base.RUNNING_CHECKS
    rig.order()  # "Fix the sum"
    rig.turn("t1", rig.commit)
    _next_order(rig, "Fix the sum again please")
    run = rig.store.get("job_1")
    assert run["asked_again"] == 1
    [asked] = [s for s in rig.store.steps("job_1") if s["step"] == "asked_again"]
    assert (asked["status"], asked["detail"]["source"]) == ("repeat", "the next order (job_2)")


# ---------------------------------------------------- the watch after a verdict


def _verified(rig: Rig, answer: evidence.Evidence = base.PASSING) -> dict:
    rig.github.answer = answer
    rig.order()
    run = rig.turn("t1", rig.commit)
    assert run["verdict"] == "verified"
    assert run["leak_due_ms"] == run["ended_ms"] + LEAK_CHECKS_H[0] * HOUR
    return run


def test_a_pull_request_closed_without_merging_takes_the_pass_back(rig: Rig):
    run = _verified(rig, OPEN_PASSING)
    rig.github.answer = CLOSED
    assert rig.recorder.read_after(run["leak_due_ms"]) == 1
    run = rig.store.get("job_1")
    assert (run["pr_closed"], run["verdict"]) == (1, "verified")
    assert "pr_closed" in _steps(rig)
    assert selector.metrics_of(run).passed == 0.0


def test_a_reverted_commit_takes_the_pass_back(rig: Rig):
    run = _verified(rig)
    base._git(rig.folder, "revert", "--no-edit", "HEAD")
    rig.recorder.read_after(run["leak_due_ms"])
    run = rig.store.get("job_1")
    assert run["reverted"] == 1
    [step] = [s for s in rig.store.steps("job_1") if s["step"] == "reverted"]
    assert step["detail"]["head_sha"] == run["head_sha"]
    assert selector.metrics_of(run).passed == 0.0


def test_the_person_correcting_after_the_verdict_is_read_by_the_watch(rig: Rig):
    run = _verified(rig)
    # The run is over and its thread no longer watched: the message is read later.
    rig.emit("user_message", {"text": "That is wrong, the sum must round."})
    rig.recorder.process_pending()
    assert rig.store.get("job_1")["asked_again"] == 0
    rig.recorder.read_after(run["leak_due_ms"])
    run = rig.store.get("job_1")
    assert run["asked_again"] == 1
    [asked] = [s for s in rig.store.steps("job_1") if s["step"] == "asked_again"]
    assert (asked["status"], asked["detail"]["source"]) == ("correction", "the person")
    assert selector.metrics_of(run).passed == 0.0


def test_a_later_unrelated_request_leaves_the_pass(rig: Rig):
    run = _verified(rig)
    rig.emit("user_message", {"text": "great, can you also look at the logging setup"})
    rig.recorder.read_after(run["leak_due_ms"])
    run = rig.store.get("job_1")
    assert (run["asked_again"], run["pr_closed"], run["reverted"], run["leaked"]) == (0, 0, 0, 0)
    assert selector.metrics_of(run).passed == 1.0


def test_github_out_of_reach_leaves_the_record_and_looks_again_soon(rig: Rig):
    run = _verified(rig, OPEN_PASSING)

    def down(*_args):
        raise OSError("no network")

    rig.recorder._read_evidence = down
    due = run["leak_due_ms"]
    assert rig.recorder.read_after(due) == 1
    after = rig.store.get("job_1")
    assert (after["pr_closed"], after["verdict"]) == (0, "verified")
    assert after["leak_due_ms"] == run["ended_ms"] + LEAK_CHECKS_H[1] * HOUR


@pytest.mark.parametrize("flag", ["leaked", "taken_over", "asked_again", "pr_closed", "reverted"])
def test_every_signal_takes_a_verified_pass_back(flag: str):
    run = {"run_id": "r", "state": "ended", "verdict": "verified", flag: 1}
    assert selector.metrics_of(run).passed == 0.0
    assert selector.metrics_of({**run, flag: 0}).passed == 1.0


def test_a_superseded_run_counts_only_when_the_person_took_it_over():
    run = {"run_id": "r", "state": "ended", "verdict": "superseded"}
    assert selector.metrics_of(run) is None
    assert selector.metrics_of({**run, "taken_over": 1}).passed == 0.0
