"""Observe mode end to end: an ended run is scanned, and the lead can ask what came of it."""

from __future__ import annotations

import sqlite3
import subprocess
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dodaios.agent_chat.events import make_event
from dodaios.agent_chat.store import AgentChatStore
from dodaios.orchestrator.verification import evidence, gates, verdict
from dodaios.orchestrator.verification import recorder as rec
from dodaios.orchestrator.verification.store import ENDED, VerificationStore
from dodaios.plugins.tool import verify_delegate
from dodaios.rsi.harness_probe import Harness

TEST = "def test_sum():\n    assert add(1, 2) == 3\n"


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
    (main / "tests" / "test_calc.py").write_text(TEST, encoding="utf-8")
    _git(main, "add", "-A")
    _git(main, "commit", "-q", "-m", "first")
    linked = tmp_path / "linked"
    _git(main, "worktree", "add", "-q", "-b", "work", str(linked))
    return linked


class _Rig:
    def __init__(self, tmp_path: Path, folder: Path, **more: Any) -> None:
        self.chat = AgentChatStore(tmp_path / "agent_chat.db")
        self.store = VerificationStore(tmp_path / "verification.db")
        self.session = self.chat.create_session(
            provider="claude-api", model="m", effort="low", cwd=str(folder), surface="agent"
        )
        self.more = more
        self.recorder = self.new_recorder()

    def new_recorder(self) -> rec.RunRecorder:
        """A recorder on the same record, as after an app restart (factory policy)."""
        return rec.RunRecorder(
            self.store, SimpleNamespace(store=self.chat),
            probe=lambda runner: Harness(runner, "2.1.330", "2.1"), **self.more,
        )

    def emit(self, kind: str, payload: dict[str, Any]) -> None:
        stored = self.chat.append_event(self.session.session_id, make_event(kind, payload))
        self.recorder.on_event(self.session.session_id, stored)

    def run_a_turn(self, job_id: str = "job_1", work: Any = None) -> dict[str, Any]:
        """One turn of the thread; ``work`` is what the agent does between start and end."""
        self.emit("turn_started", {"turn_id": "t1", "runner": "claude-cli", "model": "m"})
        self.recorder.note_submission(
            job_id=job_id, session_id=self.session.session_id, prompt="Fix it", started_ms=0
        )
        if work is not None:
            self.recorder.process_pending()  # the run is bound to the commit it started on
            work()
        self.emit("turn_finished", {"turn_id": "t1", "status": "done", "usage": {}})
        self.recorder.process_pending()
        return self.store.get(job_id)


@pytest.fixture
def rig(tmp_path: Path, worktree: Path):
    made: list[_Rig] = []

    def build(folder: Path | None = None, **more: Any) -> _Rig:
        made.append(_Rig(tmp_path, folder or worktree, **more))
        return made[-1]

    yield build
    for item in made:
        item.store.close()
    rec.set_recorder(None)


def test_an_ended_run_is_scanned_and_the_result_recorded(rig, worktree: Path):
    it = rig()
    (worktree / "tests" / "test_calc.py").unlink()
    run = it.run_a_turn()
    assert run["state"] == ENDED
    assert run["gate_status"] == gates.VIOLATIONS
    assert run["churn_lines"] == 2
    assert run["tree_id"]
    steps = it.store.steps("job_1")
    assert [s["step"] for s in steps] == [
        "bound", "turn_started", "turn_finished", "gates", "self_checks", "evidence",
        "follow_up_withheld", "verdict",
    ]
    assert steps[3]["detail"]["findings"][0]["rule"] == "C1"
    # Judged, and nothing sent: the factory policy does not hold the run.
    assert (run["verdict"], run["follow_ups"]) == ("failed", 0)


def test_a_scan_that_fails_leaves_the_run_as_it_ended(rig, monkeypatch):
    it = rig()

    def broken(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("git is gone")

    monkeypatch.setattr(gates, "check_run", broken)
    run = it.run_a_turn()
    assert run["state"] == ENDED
    assert run["gate_status"] == ""


def test_a_weakened_check_fails_the_job(rig, worktree: Path):
    it = rig()
    (worktree / "tests" / "test_calc.py").unlink()
    it.run_a_turn()
    found = verdict.from_run(it.store.get("job_1"), it.store.steps("job_1"))
    assert found.verdict == "failed"
    assert "C1 tests/test_calc.py" in found.summary
    assert [c.name for c in found.checks] == ["turn", "output_scan", "checks"]


def test_a_clean_scan_is_not_proof_that_the_change_works(rig, worktree: Path):
    it = rig()
    (worktree / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    it.run_a_turn()
    found = verdict.from_run(it.store.get("job_1"), it.store.steps("job_1"))
    assert found.verdict == "unverified"
    scan = found.checks[1]
    assert scan.ok is True
    assert "1 file(s), +2/-0" in scan.detail
    assert found.checks[2].ok is None


def test_a_turn_that_failed_fails_the_job_whatever_the_scan_says(rig):
    it = rig()
    it.emit("turn_started", {"turn_id": "t1", "runner": "claude-cli"})
    it.recorder.note_submission(
        job_id="job_1", session_id=it.session.session_id, prompt="Fix it", started_ms=0
    )
    it.emit("turn_finished", {"turn_id": "t1", "status": "error", "error": "crashed"})
    it.recorder.process_pending()
    found = verdict.from_run(it.store.get("job_1"), it.store.steps("job_1"))
    assert found.verdict == "failed"
    assert "ended as error" in found.summary


def test_a_run_that_has_not_ended_is_unverified(rig):
    it = rig()
    it.emit("turn_started", {"turn_id": "t1", "runner": "claude-cli"})
    it.recorder.note_submission(
        job_id="job_1", session_id=it.session.session_id, prompt="Fix it", started_ms=0
    )
    it.recorder.process_pending()
    found = verdict.from_run(it.store.get("job_1"), it.store.steps("job_1"))
    assert found.verdict == "unverified"


async def test_verify_delegate_answers_for_a_thread_job_from_the_record(rig, worktree, ledger):
    it = rig()
    rec.set_recorder(it.recorder)
    ledger.create(
        "ide_submission", job_id="job_1", target=f"thread:{it.session.session_id}", state="done"
    )
    (worktree / "tests" / "test_calc.py").unlink()
    it.run_a_turn("job_1")
    resolved = await verify_delegate.resolve("job_1")
    assert resolved.verdict == "failed"
    assert resolved.kind == "coding"


async def test_verify_delegate_keeps_its_old_answer_while_nothing_is_recorded(ledger):
    rec.set_recorder(None)
    ledger.create("ide_submission", job_id="job_9", target="thread:abc", state="done")
    resolved = await verify_delegate.resolve("job_9")
    assert isinstance(resolved, str)
    assert "nothing to verify" in resolved


def test_a_record_made_before_the_scan_existed_gains_its_columns(tmp_path: Path):
    from dodaios.orchestrator.verification import store as vstore

    # The schema of the first release: today's, without the scan's columns.
    first = vstore._SCHEMA
    for column, kind in vstore._ADDED_COLUMNS:
        first = first.replace(f",\n    {column:<17} {kind}", "")
    assert "gate_status" not in first
    path = tmp_path / "verification.db"
    old = sqlite3.connect(path)
    old.executescript(first)
    old.execute(
        "INSERT INTO runs (run_id, session_id, state, started_ms) "
        "VALUES ('job_old', 'thread-1', 'running', 1)"
    )
    old.commit()
    old.close()
    store = VerificationStore(path)
    try:
        assert store.get("job_old")["gate_status"] == ""
        assert store.update_run("job_old", gate_status=gates.CLEAN, churn_lines=3, tree_id="abc")
        assert store.get("job_old")["churn_lines"] == 3
    finally:
        store.close()


# ------------------------------------------------- landing and checks, from GitHub


class _GitHub:
    """Stands in for GitHub: gives its answers in turn, the last one for good."""

    def __init__(self, *answers: evidence.Evidence) -> None:
        self.answers = list(answers)
        self.asked: list[tuple[str, str]] = []

    def __call__(self, repo_id: str, head_sha: str) -> evidence.Evidence:
        self.asked.append((repo_id, head_sha))
        found = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        return replace(found, head_sha=head_sha)


class _Clock:
    def __init__(self) -> None:
        self.now = time.time()

    def __call__(self) -> float:
        return self.now


OPEN_RUNNING = evidence.Evidence("pr_open", "running", pr=12, reason="pull request #12 is open")
MERGED_PASSING = evidence.Evidence(
    "merged", "passing", pr=12, checked_sha="b" * 40,
    reason="pull request #12 is merged; checks read on the merge commit",
)


def _on_github(worktree: Path) -> None:
    _git(worktree, "remote", "add", "origin", "https://github.com/acme/notes.git")


def _commit(worktree: Path, name: str = "calc.py") -> str:
    (worktree / name).write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    _git(worktree, "add", name)
    _git(worktree, "commit", "-q", "-m", "work")
    return _git(worktree, "rev-parse", "HEAD")


def test_github_is_asked_about_the_commit_the_run_left_behind(rig, worktree: Path):
    _on_github(worktree)
    github = _GitHub(MERGED_PASSING)
    it = rig(read_evidence=github)

    run = it.run_a_turn(work=lambda: _commit(worktree))

    head = _git(worktree, "rev-parse", "HEAD")
    assert github.asked == [("github.com/acme/notes", head)]
    assert (run["head_sha"], run["landing"], run["ci_status"]) == (head, "merged", "passing")
    assert run["evidence_due_ms"] is None
    steps = it.store.steps("job_1")
    assert [s["step"] for s in steps][-4:] == ["gates", "self_checks", "evidence", "verdict"]
    assert steps[-4]["detail"]["head_sha"] == head
    assert steps[-4]["detail"]["committed"] is True
    assert steps[-2]["status"] == "merged/passing"
    assert steps[-2]["detail"]["pr"] == 12
    assert run["verdict"] == "verified"


def test_work_that_is_not_committed_is_not_on_github_and_nobody_asks(rig, worktree: Path):
    _on_github(worktree)
    github = _GitHub(MERGED_PASSING)
    it = rig(read_evidence=github)
    (worktree / "calc.py").write_text("X = 1\n", encoding="utf-8")

    run = it.run_a_turn()

    assert github.asked == []
    assert (run["landing"], run["ci_status"], run["evidence_due_ms"]) == ("none", "none", None)
    assert it.store.steps("job_1")[-1]["detail"]["reason"] == "the work is not committed"


def test_a_run_that_changed_nothing_has_nothing_to_land(rig, worktree: Path):
    _on_github(worktree)
    github = _GitHub(MERGED_PASSING)
    it = rig(read_evidence=github)
    run = it.run_a_turn()
    assert github.asked == []
    assert run["landing"] == "none"
    assert it.store.steps("job_1")[-1]["detail"]["reason"] == "the run changed no file"


def test_a_run_in_the_shared_checkout_is_judged_from_two_snapshots(
    rig, worktree: Path, tmp_path: Path
):
    main = tmp_path / "main"
    _on_github(main)
    github = _GitHub(MERGED_PASSING)
    it = rig(folder=main, read_evidence=github)
    run = it.run_a_turn(work=lambda: _commit(main))
    assert run["start_tree"]
    assert run["gate_status"] == gates.CLEAN
    scan = next(s for s in it.store.steps("job_1") if s["step"] == "gates")["detail"]
    assert (scan["work_area"], scan["paths"]) == ("shared_snapshot", ["calc.py"])
    head = _git(main, "rev-parse", "HEAD")
    assert github.asked == [("github.com/acme/notes", head)]
    assert (run["head_sha"], run["landing"]) == (head, "merged")


def test_checks_that_still_run_are_read_again_when_they_are_due(rig, worktree: Path):
    _on_github(worktree)
    clock = _Clock()
    github = _GitHub(OPEN_RUNNING, OPEN_RUNNING, MERGED_PASSING)
    it = rig(read_evidence=github, clock=clock)

    run = it.run_a_turn(work=lambda: _commit(worktree))

    first_due = run["ended_ms"] + evidence.RECHECK_AFTER_S[0] * 1000
    assert (run["landing"], run["ci_status"], run["evidence_due_ms"]) == (
        "pr_open", "running", first_due,
    )
    # Not due yet: nothing is asked.
    assert it.recorder.read_due(first_due - 1) == 0
    assert len(github.asked) == 1
    # Due, and nothing new: asked, the next read is set, no second step.
    assert it.recorder.read_due(first_due) == 1
    run = it.store.get("job_1")
    second_due = run["ended_ms"] + evidence.RECHECK_AFTER_S[1] * 1000
    assert run["evidence_due_ms"] == second_due
    assert sum(1 for s in it.store.steps("job_1") if evidence.is_step(s)) == 1
    # Due again, merged and green: the record is settled and says so.
    assert it.recorder.read_due(second_due) == 1
    run = it.store.get("job_1")
    assert (run["landing"], run["ci_status"], run["evidence_due_ms"]) == (
        "merged", "passing", None,
    )
    told = [s for s in it.store.steps("job_1") if evidence.is_step(s)]
    assert [(s["step"], s["status"]) for s in told] == [
        ("evidence", "pr_open/running"), ("evidence:1", "merged/passing"),
    ]
    assert it.recorder.read_due(second_due + 10**9) == 0
    # Decided when the checks passed; only the later look for a leak is due.
    assert run["verdict"] == "verified"
    assert list(it.recorder._leak_at) == ["job_1"] and not it.recorder._decide_at


def test_a_commit_that_shows_no_check_is_given_up_on_after_five_minutes(rig, worktree: Path):
    _on_github(worktree)
    clock = _Clock()
    github = _GitHub(evidence.Evidence("pushed", "none"))
    it = rig(read_evidence=github, clock=clock)
    run = it.run_a_turn(work=lambda: _commit(worktree))
    while run["evidence_due_ms"] is not None:
        it.recorder.read_due(run["evidence_due_ms"])
        run = it.store.get("job_1")
    waited = [after for after in evidence.RECHECK_AFTER_S if after <= evidence.NO_CHECKS_GIVE_UP_S]
    assert len(github.asked) == 1 + len(waited)
    assert (run["landing"], run["ci_status"]) == ("pushed", "none")


def test_checks_that_never_end_are_not_waited_for_beyond_the_last_reading(rig, worktree: Path):
    _on_github(worktree)
    clock = _Clock()
    github = _GitHub(OPEN_RUNNING)
    it = rig(read_evidence=github, clock=clock)
    run = it.run_a_turn(work=lambda: _commit(worktree))
    while run["evidence_due_ms"] is not None:
        it.recorder.read_due(run["evidence_due_ms"])
        run = it.store.get("job_1")
    assert len(github.asked) == 1 + len(evidence.RECHECK_AFTER_S)
    assert run["ci_status"] == "running"


def test_a_restart_goes_on_reading_what_was_due(rig, worktree: Path):
    _on_github(worktree)
    clock = _Clock()
    github = _GitHub(OPEN_RUNNING, MERGED_PASSING)
    it = rig(read_evidence=github, clock=clock)
    due = it.run_a_turn(work=lambda: _commit(worktree))["evidence_due_ms"]

    after_restart = it.new_recorder()
    after_restart._resume()

    # The writer thread sleeps until then, at most five minutes at a time.
    clock.now = due / 1000 - 30
    assert after_restart._wait_s() == pytest.approx(30, abs=0.01)
    clock.now = due / 1000 - 3600
    assert after_restart._wait_s() == 300.0
    assert after_restart.read_due(due) == 1
    assert it.store.get("job_1")["landing"] == "merged"


def test_the_writer_thread_reads_due_evidence_by_itself(rig, worktree: Path, monkeypatch):
    monkeypatch.setattr(rec, "_MIN_WAIT_S", 0.01)
    _on_github(worktree)
    clock = _Clock()
    github = _GitHub(OPEN_RUNNING, MERGED_PASSING)
    it = rig(read_evidence=github, clock=clock)
    run = it.run_a_turn(work=lambda: _commit(worktree))
    clock.now = run["evidence_due_ms"] / 1000 + 1

    it.recorder.start()
    try:
        deadline = time.time() + 10
        while time.time() < deadline and it.store.get("job_1")["landing"] != "merged":
            time.sleep(0.02)
    finally:
        it.recorder.stop()

    assert it.store.get("job_1")["landing"] == "merged"
    assert len(github.asked) == 2


def test_github_failing_to_answer_leaves_the_scan_on_record(rig, worktree: Path):
    _on_github(worktree)

    def broken(_repo: str, _sha: str) -> evidence.Evidence:
        raise RuntimeError("boom")

    it = rig(read_evidence=broken)
    run = it.run_a_turn(work=lambda: _commit(worktree))
    assert run["gate_status"] == gates.CLEAN
    assert run["landing"] == ""
    found = verdict.from_run(run, it.store.steps("job_1"))
    assert found.verdict == "unverified"


def test_a_clean_scan_with_passing_checks_on_the_commit_is_verified(rig, worktree: Path):
    _on_github(worktree)
    it = rig(read_evidence=_GitHub(MERGED_PASSING))
    it.run_a_turn(work=lambda: _commit(worktree))
    found = verdict.from_run(it.store.get("job_1"), it.store.steps("job_1"))
    assert found.verdict == "verified"
    assert [c.ok for c in found.checks] == [True, True, True]
    assert "#12 is merged" in found.checks[2].detail


def test_work_left_beside_the_commit_is_not_what_the_checks_ran_on(rig, worktree: Path):
    _on_github(worktree)
    it = rig(read_evidence=_GitHub(MERGED_PASSING))

    def work() -> None:
        _commit(worktree)
        (worktree / "later.py").write_text("LATER = 1\n", encoding="utf-8")

    it.run_a_turn(work=work)
    found = verdict.from_run(it.store.get("job_1"), it.store.steps("job_1"))
    assert found.verdict == "unverified"
    assert "beyond the commit" in found.summary


def _steps(scan: dict[str, Any], found: evidence.Evidence | None) -> list[dict[str, Any]]:
    steps = [{"step": "gates", "status": scan["status"], "detail": scan}]
    if found is not None:
        steps.append({"step": "evidence", "detail": found.to_detail()})
    return steps


CLEAN_SCAN = {"status": "clean", "files": 1, "added": 2, "deleted": 0, "committed": True}
ENDED_RUN = {"run_id": "job_1", "state": ENDED, "turn_status": "done"}


@pytest.mark.parametrize(
    ("scan", "found", "wanted", "says"),
    [
        (CLEAN_SCAN, MERGED_PASSING, "verified", "checks pass on the commit"),
        (CLEAN_SCAN, evidence.Evidence("pr_open", "passing", pr=3), "verified", "checks pass"),
        (
            CLEAN_SCAN,
            evidence.Evidence(
                "pr_open", "failing", pr=3, failing=("test (ubuntu)", "lint"),
                reason="pull request #3 is open",
            ),
            "failed",
            "pull request #3 is open; failing: test (ubuntu), lint",
        ),
        (CLEAN_SCAN, OPEN_RUNNING, "unverified", "they still run"),
        (CLEAN_SCAN, evidence.Evidence("pushed", "none", reason="x"), "unverified", "no checks"),
        (
            CLEAN_SCAN,
            evidence.Evidence("none", "none", reason="the commit is not on GitHub"),
            "unverified",
            "the commit is not on GitHub",
        ),
        (CLEAN_SCAN, None, "unverified", "no independent test evidence"),
        (
            {**CLEAN_SCAN, "status": "findings", "ambiguous": 1},
            MERGED_PASSING,
            "unverified",
            "points someone has to look at",
        ),
        ({**CLEAN_SCAN, "committed": False}, MERGED_PASSING, "unverified", "beyond the commit"),
    ],
)
def test_what_the_record_supports(scan, found, wanted: str, says: str):
    answer = verdict.from_run(ENDED_RUN, _steps(scan, found))
    assert answer.verdict == wanted
    assert says in answer.summary


def test_passing_checks_do_not_outweigh_a_weakened_check():
    scan = {
        **CLEAN_SCAN, "status": "violations",
        "findings": [{"rule": "C1", "severity": "violation", "path": "tests/test_a.py",
                      "note": "a test file was deleted"}],
    }
    answer = verdict.from_run(ENDED_RUN, _steps(scan, MERGED_PASSING))
    assert answer.verdict == "failed"
    assert "C1 tests/test_a.py" in answer.summary
