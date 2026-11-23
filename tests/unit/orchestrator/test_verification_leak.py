"""Verified work that turns red after it merged: looked at again after 24 and 72 hours."""

from __future__ import annotations

import pytest

from dodaios.orchestrator.verification.recorder import LEAK_CHECKS_H
from dodaios.rsi import selector
from tests.unit.orchestrator import test_verification_follow_up as base

Rig = base.Rig
evidence = base.evidence
PASSING = base.PASSING


@pytest.fixture
def rig(tmp_path):
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
    yield made
    made.store.close()


HOUR = 3600 * 1000
RED = evidence.Evidence("merged", "failing", pr=4, failing=("main / test",), reason="merged")


def _verified(rig: Rig) -> dict:
    rig.order()
    run = rig.turn("t1", rig.commit)
    assert (run["verdict"], run["landing"]) == ("verified", "merged")
    return run


def test_a_verified_merge_is_looked_at_again_after_a_day(rig: Rig):
    run = _verified(rig)
    assert run["leak_due_ms"] == run["ended_ms"] + LEAK_CHECKS_H[0] * HOUR
    assert rig.recorder.read_leaks(run["leak_due_ms"] - 1) == 0


def test_red_merged_work_is_a_leak_and_no_longer_counts_as_passed(rig: Rig):
    run = _verified(rig)
    rig.github.answer = RED
    assert rig.recorder.read_leaks(run["leak_due_ms"]) == 1
    run = rig.store.get("job_1")
    assert (run["leaked"], run["leak_due_ms"], run["verdict"]) == (1, None, "verified")
    assert [s["step"] for s in rig.store.steps("job_1")][-1] == "leak"
    counted = selector.metrics_of(run)
    assert (counted.passed, counted.hard) == (0.0, True)


def test_green_work_is_looked_at_once_more_after_three_days_and_then_left(rig: Rig):
    run = _verified(rig)
    ended = run["ended_ms"]
    rig.recorder.read_leaks(ended + LEAK_CHECKS_H[0] * HOUR)
    assert rig.store.get("job_1")["leak_due_ms"] == ended + LEAK_CHECKS_H[1] * HOUR
    rig.recorder.read_leaks(ended + LEAK_CHECKS_H[1] * HOUR)
    run = rig.store.get("job_1")
    assert (run["leaked"], run["leak_due_ms"]) == (0, None)


def test_a_restart_keeps_the_watch(rig: Rig):
    run = _verified(rig)
    after = rig.new_recorder(boot_id="boot-b")
    after._resume()
    rig.github.answer = RED
    assert after.read_leaks(run["leak_due_ms"]) == 1
    assert rig.store.get("job_1")["leaked"] == 1


def test_work_that_did_not_merge_is_not_watched(rig: Rig):
    rig.github.answer = evidence.Evidence("pushed", "passing", reason="pushed")
    rig.order()
    run = rig.turn("t1", rig.commit)
    assert run["verdict"] == "verified"
    assert run["leak_due_ms"] is None
    assert PASSING.landing == "merged"
