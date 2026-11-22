"""Enforce mode: a run stays open until its output was checked, and may get a follow-up order."""

from __future__ import annotations

import subprocess
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dodaios.agent_chat.events import make_event
from dodaios.agent_chat.store import AgentChatStore
from dodaios.orchestrator.verification import evidence, prompts, send
from dodaios.orchestrator.verification import recorder as rec
from dodaios.orchestrator.verification.store import (
    CHECKING,
    ENDED,
    INTERRUPTED,
    RUNNING,
    VerificationStore,
)
from dodaios.rsi.harness_probe import Harness

TEST = "def test_sum():\n    assert add(1, 2) == 3\n"
CODE = "def add(a, b):\n    return a + b\n"

PASSING = evidence.Evidence("merged", "passing", pr=4, reason="pull request #4 is merged")
FAILING = evidence.Evidence(
    "pr_open", "failing", pr=4, failing=("unit",), reason="pull request #4 is open"
)
RUNNING_CHECKS = evidence.Evidence("pr_open", "running", pr=4, reason="pull request #4 is open")


def _git(folder: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", *args], cwd=folder, capture_output=True, text=True, check=True, encoding="utf-8"
    )
    return done.stdout.strip()


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    main = tmp_path / "main"
    (main / "tests").mkdir(parents=True)
    _git(main, "init", "-q", "-b", "main")
    _git(main, "config", "user.email", "t@example.com")
    _git(main, "config", "user.name", "T")
    (main / "calc.py").write_text(CODE, encoding="utf-8")
    (main / "tests" / "test_calc.py").write_text(TEST, encoding="utf-8")
    _git(main, "add", "-A")
    _git(main, "commit", "-q", "-m", "first")
    linked = tmp_path / "linked"
    _git(main, "worktree", "add", "-q", "-b", "work", str(linked))
    return linked


class GitHub:
    """Stands in for GitHub: what it says about any commit, changeable by the test."""

    def __init__(self, answer: evidence.Evidence = PASSING) -> None:
        self.answer = answer
        self.asked: list[str] = []

    def __call__(self, _repo_id: str, head_sha: str) -> evidence.Evidence:
        self.asked.append(head_sha)
        return replace(self.answer, head_sha=head_sha, checked_sha=head_sha)


class Sender:
    """Stands in for the chat service's send: records the order, starts a turn id."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str, int]] = []
        self.refuse: Exception | None = None

    def __call__(self, session_id: str, prompt: str, run_id: str, output: int) -> str:
        if self.refuse is not None:
            raise self.refuse
        self.sent.append((session_id, prompt, run_id, output))
        return f"t{len(self.sent) + 1}"


class Clock:
    """The real time, moved ahead by ``ahead`` seconds when a test needs it."""

    def __init__(self) -> None:
        self.ahead = 0.0

    def __call__(self) -> float:
        return time.time() + self.ahead


class Rig:
    def __init__(self, tmp_path: Path, folder: Path) -> None:
        self.folder = folder
        self.chat = AgentChatStore(tmp_path / "agent_chat.db")
        self.store = VerificationStore(tmp_path / "verification.db")
        self.session = self.chat.create_session(
            provider="claude-api", model="m", effort="low", cwd=str(folder), surface="agent"
        )
        self.sid = self.session.session_id
        self.github = GitHub()
        self.sender = Sender()
        self.clock = Clock()
        self.verdicts: list[tuple[str, str]] = []
        self.recorder = self.new_recorder()

    def new_recorder(self, *, boot_id: str = "boot-a", verify: str = "enforce") -> rec.RunRecorder:
        made = rec.RunRecorder(
            self.store, SimpleNamespace(store=self.chat), verify=verify, boot_id=boot_id,
            probe=lambda runner: Harness(runner, "2.1.330", "2.1"),
            read_evidence=self.github, clock=self.clock, send_follow_up=self.sender,
        )
        made.add_verdict_listener(lambda run_id, sid: self.verdicts.append((run_id, sid)))
        return made

    def emit(self, kind: str, payload: dict[str, Any], to: rec.RunRecorder | None = None) -> None:
        stored = self.chat.append_event(self.sid, make_event(kind, payload))
        (to or self.recorder).on_event(self.sid, stored)

    def order(self, job_id: str = "job_1", turn: str = "t1") -> None:
        """The lead's order: the thread's turn starts and the order is noted."""
        self.emit("turn_started", {"turn_id": turn, "runner": "claude-cli", "model": "m"})
        self.recorder.note_submission(
            job_id=job_id, session_id=self.sid, prompt="Fix the sum", started_ms=0
        )
        self.recorder.process_pending()

    def turn(
        self, turn: str, work: Any = None, *, said: str = "Done.", status: str = "done",
        follow_up: bool = False,
    ) -> dict[str, Any]:
        """One turn of the thread: the app's order (if any), the work, the end."""
        if follow_up:
            self.emit("user_message", {"text": "order", "author": {"agent_id": prompts.AUTHOR_ID}})
            self.emit("turn_started", {"turn_id": turn, "runner": "claude-cli", "model": "m"})
            self.recorder.process_pending()
        if work is not None:
            work()
        self.emit("assistant_text", {"turn_id": turn, "text": said})
        self.emit("turn_finished", {"turn_id": turn, "status": status, "usage": {
            "output_tokens": 100,
        }})
        self.recorder.process_pending()
        return self.store.get("job_1") or {}

    def commit(self, name: str = "calc.py", text: str = CODE + "\n# more\n") -> None:
        (self.folder / name).write_text(text, encoding="utf-8")
        _git(self.folder, "add", "-A")
        _git(self.folder, "commit", "-q", "-m", "work")

    def delete_test(self) -> None:
        """The shortcut: change the code and delete the test that would catch it."""
        (self.folder / "calc.py").write_text(CODE.replace("a + b", "a + b + 0"), encoding="utf-8")
        _git(self.folder, "rm", "-q", "tests/test_calc.py")
        _git(self.folder, "commit", "-q", "-am", "drop the test")

    def restore_test(self) -> None:
        (self.folder / "tests").mkdir(exist_ok=True)
        (self.folder / "tests" / "test_calc.py").write_text(TEST, encoding="utf-8")
        _git(self.folder, "add", "-A")
        _git(self.folder, "commit", "-q", "-m", "restore the test")

    def steps(self) -> list[tuple[int, str, str]]:
        return [
            (s["iteration"], s["step"], s["status"]) for s in self.store.steps("job_1")
        ]


@pytest.fixture
def rig(tmp_path: Path, worktree: Path):
    made = Rig(tmp_path, worktree)
    yield made
    made.store.close()


# ------------------------------------------------------------------ the loop


def test_a_clean_output_with_passing_checks_ends_the_run_verified(rig: Rig):
    rig.order()
    run = rig.turn("t1", rig.commit)
    assert (run["state"], run["verdict"]) == (ENDED, "verified")
    assert "pull request #4 is merged" in run["verdict_reason"]
    assert rig.sender.sent == []
    assert rig.verdicts == [("job_1", rig.sid)]
    assert [s[1] for s in rig.steps()][-4:] == ["turn_finished", "gates", "evidence", "verdict"]


def test_a_weakened_check_gets_a_follow_up_and_the_fix_is_verified(rig: Rig):
    rig.order()
    run = rig.turn("t1", rig.delete_test)

    # The run stays open: one follow-up order went out, built from the finding.
    assert (run["state"], run["iteration"], run["follow_ups"]) == (RUNNING, 1, 1)
    [(sid, prompt, run_id, output)] = rig.sender.sent
    assert (sid, run_id, output) == (rig.sid, "job_1", 0)
    assert "C1 tests/test_calc.py" in prompt
    assert rig.verdicts == []

    run = rig.turn("t2", rig.restore_test, said="Restored.\nRESULT: fixed", follow_up=True)

    assert (run["state"], run["verdict"]) == (ENDED, "verified")
    assert run["person_intervened"] == 0
    assert run["tokens_out"] == 200  # both turns
    assert rig.verdicts == [("job_1", rig.sid)]
    assert rig.steps() == [
        (0, "bound", ""),
        (0, "turn_started", ""),
        (0, "turn_finished", "done"),
        (0, "gates", "violations"),
        (0, "evidence", "merged/passing"),
        (0, "follow_up_intent", "T2"),
        (0, "follow_up_sent", "T2"),
        (1, "turn_started", ""),
        (1, "turn_finished", "done"),
        (1, "gates", "clean"),
        (1, "evidence", "merged/passing"),
        (1, "verdict", "verified"),
    ]


def test_failing_checks_get_a_follow_up_and_failing_again_ends_the_run(rig: Rig):
    rig.github.answer = FAILING
    rig.order()
    run = rig.turn("t1", rig.commit)
    assert run["state"] == RUNNING
    assert "- unit" in rig.sender.sent[0][1]

    run = rig.turn("t2", lambda: rig.commit("other.py", "X = 1\n"), follow_up=True)

    assert (run["state"], run["verdict"]) == (ENDED, "failed")
    assert "again after a follow-up order" in run["verdict_reason"]
    assert len(rig.sender.sent) == 1


def test_no_run_gets_more_than_two_follow_up_orders(rig: Rig):
    rig.order()
    rig.turn("t1", rig.delete_test)
    rig.github.answer = FAILING
    rig.turn("t2", rig.restore_test, follow_up=True)
    rig.github.answer = evidence.Evidence(
        "pr_open", "failing", pr=4, failing=("lint",), reason="pull request #4 is open"
    )
    run = rig.turn("t3", lambda: rig.commit("third.py", "Y = 1\n"), follow_up=True)
    assert len(rig.sender.sent) == 2
    assert (run["state"], run["verdict"]) == (ENDED, "failed")
    assert "already got 2 follow-up orders" in run["verdict_reason"]


def test_an_agent_that_asks_for_a_decision_hands_it_on(rig: Rig):
    rig.order()
    rig.turn("t1", rig.delete_test)
    run = rig.turn(
        "t2", None, said="RESULT: needs-decision: the test asks for the old API", follow_up=True
    )
    assert (run["verdict"], run["verdict_reason"]) == (
        "needs_decision", "the test asks for the old API",
    )


def test_running_checks_are_waited_for_and_decided_when_read_again(rig: Rig):
    rig.github.answer = RUNNING_CHECKS
    rig.order()
    run = rig.turn("t1", rig.commit)
    assert run["state"] == CHECKING
    assert rig.recorder._wait_s() is not None
    due = run["evidence_due_ms"]
    assert due is not None

    rig.github.answer = PASSING
    rig.recorder.tick(due)

    run = rig.store.get("job_1")
    assert (run["state"], run["verdict"]) == (ENDED, "verified")
    assert rig.recorder._decide_at == {} and rig.recorder._due == {}


def test_checks_that_never_end_leave_the_run_unverified_after_the_wait(rig: Rig):
    from dodaios.orchestrator.verification.driver import EVIDENCE_WAIT_S

    rig.github.answer = RUNNING_CHECKS
    rig.order()
    run = rig.turn("t1", rig.commit)
    ended = run["ended_ms"]
    rig.recorder.tick(ended + EVIDENCE_WAIT_S * 1000)
    run = rig.store.get("job_1")
    assert (run["state"], run["verdict"]) == (ENDED, "unverified")
    assert "still ran after the wait" in run["verdict_reason"]


def test_a_live_check_shows_signs_of_life(rig: Rig):
    rig.github.answer = RUNNING_CHECKS
    rig.order()
    before = rig.turn("t1", rig.commit)["heartbeat_ms"]
    rig.clock.ahead += 120
    rig.recorder.tick()
    assert rig.store.get("job_1")["heartbeat_ms"] > before


# ------------------------------------------------- when the thread is not the agent's


def test_the_person_writing_while_the_output_is_checked_supersedes_the_run(rig: Rig):
    rig.github.answer = RUNNING_CHECKS
    rig.order()
    rig.turn("t1", rig.commit)
    rig.emit("user_message", {"text": "stop, I take over"})
    rig.recorder.process_pending()
    run = rig.store.get("job_1")
    assert (run["state"], run["verdict"]) == (ENDED, "superseded")
    assert rig.verdicts == [("job_1", rig.sid)]


def test_a_turn_nobody_here_started_supersedes_the_run(rig: Rig):
    rig.github.answer = RUNNING_CHECKS
    rig.order()
    rig.turn("t1", rig.commit)
    rig.emit("turn_started", {"turn_id": "someone-else", "runner": "claude-cli"})
    rig.recorder.process_pending()
    assert rig.store.get("job_1")["verdict"] == "superseded"


def test_a_follow_up_the_thread_refuses_ends_the_run_failed(rig: Rig):
    rig.sender.refuse = send.Refused("the thread waits for the person")
    rig.order()
    run = rig.turn("t1", rig.delete_test)
    assert (run["state"], run["verdict"]) == (ENDED, "failed")
    assert "no follow-up order was sent because the thread waits for the person" in (
        run["verdict_reason"]
    )


def test_a_follow_up_whose_sending_is_unknown_is_never_sent_twice(rig: Rig):
    rig.sender.refuse = TimeoutError()
    rig.order()
    run = rig.turn("t1", rig.delete_test)
    assert run["verdict"] == "failed"
    assert "could not be confirmed" in run["verdict_reason"]
    assert [s[1] for s in rig.steps()].count("follow_up_intent") == 1
    assert "follow_up_sent" not in [s[1] for s in rig.steps()]


def test_a_failed_turn_is_failed_without_a_scan(rig: Rig):
    rig.order()
    run = rig.turn("t1", None, status="error")
    assert (run["verdict"], run["gate_status"]) == ("failed", "")
    assert rig.sender.sent == []


def test_a_new_order_to_the_thread_supersedes_a_run_being_checked(rig: Rig):
    rig.github.answer = RUNNING_CHECKS
    rig.order()
    rig.turn("t1", rig.commit)
    sent_at = int(time.time() * 1000)
    rig.emit("turn_started", {"turn_id": "t9", "runner": "claude-cli"})
    rig.recorder.note_submission(
        job_id="job_2", session_id=rig.sid, prompt="Next", started_ms=sent_at
    )
    rig.recorder.process_pending()
    assert rig.store.get("job_1")["verdict"] == "superseded"
    assert rig.store.get("job_2")["state"] == RUNNING


# ------------------------------------------------------------------ restarts


def test_a_restart_while_checks_run_goes_on_waiting_and_decides(rig: Rig):
    rig.github.answer = RUNNING_CHECKS
    rig.order()
    due = rig.turn("t1", rig.commit)["evidence_due_ms"]

    after = rig.new_recorder(boot_id="boot-b")
    after._resume()
    assert rig.store.get("job_1")["state"] == CHECKING

    rig.github.answer = PASSING
    after.tick(due)
    run = rig.store.get("job_1")
    assert (run["state"], run["verdict"]) == (ENDED, "verified")


def test_after_a_restart_no_follow_up_order_is_sent(rig: Rig):
    rig.github.answer = RUNNING_CHECKS
    rig.order()
    due = rig.turn("t1", rig.commit)["evidence_due_ms"]
    after = rig.new_recorder(boot_id="boot-b")
    after._resume()
    rig.github.answer = FAILING
    after.tick(due)
    run = rig.store.get("job_1")
    assert (run["state"], run["verdict"]) == (ENDED, "failed")
    assert "app restarted" in run["verdict_reason"]
    assert rig.sender.sent == []


def test_a_restart_after_a_follow_up_picks_its_turn_up_from_the_log(rig: Rig):
    rig.order()
    rig.turn("t1", rig.delete_test)
    assert rig.store.get("job_1")["state"] == RUNNING
    # The follow-up's turn runs and ends while no recorder listens.
    rig.emit("user_message", {"text": "order", "author": {"agent_id": prompts.AUTHOR_ID}},
             to=SimpleNamespace(on_event=lambda *_a: None))
    rig.emit("turn_started", {"turn_id": "t2", "runner": "claude-cli"},
             to=SimpleNamespace(on_event=lambda *_a: None))
    rig.restore_test()
    rig.emit("turn_finished", {"turn_id": "t2", "status": "done", "usage": {}},
             to=SimpleNamespace(on_event=lambda *_a: None))

    after = rig.new_recorder(boot_id="boot-a")
    after._resume()

    run = rig.store.get("job_1")
    assert (run["state"], run["verdict"]) == (ENDED, "verified")
    # The first turn's end was not read again as news.
    assert [s for s in rig.steps() if s[1] == "turn_finished"] == [
        (0, "turn_finished", "done"), (1, "turn_finished", "done"),
    ]


def test_a_thread_deleted_while_its_output_was_checked_is_closed(rig: Rig):
    rig.github.answer = RUNNING_CHECKS
    rig.order()
    rig.turn("t1", rig.commit)
    rig.chat.delete_session(rig.sid)
    after = rig.new_recorder()
    after._resume()
    run = rig.store.get("job_1")
    assert (run["state"], run["verdict"]) == (INTERRUPTED, "unverified")


# ------------------------------------------------------------- observe mode


def test_observe_mode_records_and_never_sends(rig: Rig):
    observing = rig.new_recorder(verify="observe")
    rig.recorder = observing
    rig.order()
    run = rig.turn("t1", rig.delete_test)
    assert run["state"] == ENDED
    assert (run["verdict"], run["follow_ups"]) == ("", 0)
    assert run["gate_status"] == "violations"
    assert rig.sender.sent == [] and rig.verdicts == []


def test_the_follow_ups_of_one_request_are_counted_together(rig: Rig):
    store = rig.store
    for n, root in enumerate(("root-a", "root-a", "root-b")):
        store.start_run(f"job_{n + 5}", "s", state="running", started_ms=1, root_span_id=root)
        store.update_run(f"job_{n + 5}", follow_ups=2)
    assert store.root_follow_ups("root-a") == 4
    assert store.root_follow_ups("root-b") == 2
    assert store.root_follow_ups("") == 0
