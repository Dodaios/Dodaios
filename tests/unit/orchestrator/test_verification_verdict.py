"""Observe mode end to end: an ended run is scanned, and the lead can ask what came of it."""

from __future__ import annotations

import sqlite3
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dodaios.agent_chat.events import make_event
from dodaios.agent_chat.store import AgentChatStore
from dodaios.orchestrator.verification import gates, verdict
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
    def __init__(self, tmp_path: Path, folder: Path, verify: str) -> None:
        self.chat = AgentChatStore(tmp_path / "agent_chat.db")
        self.store = VerificationStore(tmp_path / "verification.db")
        self.session = self.chat.create_session(
            provider="claude-api", model="m", effort="low", cwd=str(folder), surface="agent"
        )
        self.recorder = rec.RunRecorder(
            self.store, SimpleNamespace(store=self.chat), verify=verify,
            probe=lambda runner: Harness(runner, "2.1.330", "2.1"),
        )

    def emit(self, kind: str, payload: dict[str, Any]) -> None:
        stored = self.chat.append_event(self.session.session_id, make_event(kind, payload))
        self.recorder.on_event(self.session.session_id, stored)

    def run_a_turn(self, job_id: str = "job_1") -> dict[str, Any]:
        self.emit("turn_started", {"turn_id": "t1", "runner": "claude-cli", "model": "m"})
        self.recorder.note_submission(
            job_id=job_id, session_id=self.session.session_id, prompt="Fix it", started_ms=0
        )
        self.emit("turn_finished", {"turn_id": "t1", "status": "done", "usage": {}})
        self.recorder.process_pending()
        return self.store.get(job_id)


@pytest.fixture
def rig(tmp_path: Path, worktree: Path):
    made: list[_Rig] = []

    def build(verify: str = "observe") -> _Rig:
        made.append(_Rig(tmp_path, worktree, verify))
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
    assert [s["step"] for s in steps] == ["bound", "turn_started", "turn_finished", "gates"]
    assert steps[-1]["detail"]["findings"][0]["rule"] == "C1"


def test_with_verify_off_nothing_is_scanned(rig, worktree: Path):
    it = rig(verify="off")
    (worktree / "tests" / "test_calc.py").unlink()
    run = it.run_a_turn()
    assert run["gate_status"] == ""
    assert "gates" not in [s["step"] for s in it.store.steps("job_1")]


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
    assert [c.name for c in found.checks] == ["turn", "output_scan", "tests"]


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
