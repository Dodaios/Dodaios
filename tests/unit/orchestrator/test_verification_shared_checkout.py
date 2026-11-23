"""Runs in a shared checkout: their own change from two snapshots, and the agent's own checks."""

from __future__ import annotations

import subprocess
import time
from itertools import count
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dodaios.agent_chat.events import make_event
from dodaios.agent_chat.store import AgentChatStore
from dodaios.orchestrator.verification import evidence, self_checks, verdict
from dodaios.orchestrator.verification import recorder as rec
from dodaios.orchestrator.verification.store import VerificationStore
from dodaios.rsi.harness_probe import Harness

CODE = "def add(a, b):\n    return a + b\n"
_CALLS = count()
TEST = "from calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n"


def _git(folder: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", *args], cwd=folder, capture_output=True, text=True, check=True, encoding="utf-8"
    )
    return done.stdout.strip()


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    """The person's own checkout: one commit, no remote, shared by every thread."""
    folder = tmp_path / "project"
    (folder / "tests").mkdir(parents=True)
    _git(folder, "init", "-q", "-b", "main")
    _git(folder, "config", "user.email", "t@example.com")
    _git(folder, "config", "user.name", "T")
    (folder / "calc.py").write_text(CODE, encoding="utf-8")
    (folder / "other.py").write_text("X = 1\n", encoding="utf-8")
    (folder / "tests" / "test_calc.py").write_text(TEST, encoding="utf-8")
    _git(folder, "add", "-A")
    _git(folder, "commit", "-q", "-m", "first")
    return folder


class Rig:
    def __init__(self, tmp_path: Path, folder: Path) -> None:
        self.folder = folder
        self.chat = AgentChatStore(tmp_path / "agent_chat.db")
        self.store = VerificationStore(tmp_path / "verification.db")
        self.recorder = rec.RunRecorder(
            self.store, SimpleNamespace(store=self.chat),
            probe=lambda runner: Harness(runner, "2.1.330", "2.1"),
            read_evidence=lambda *_a: pytest.fail("a repository without a remote is not asked"),
        )
        self.threads: dict[str, str] = {}

    def thread(self, name: str) -> str:
        if name not in self.threads:
            session = self.chat.create_session(
                provider="claude-cli", model="m", effort="low", cwd=str(self.folder),
                surface="agent",
            )
            self.threads[name] = session.session_id
        return self.threads[name]

    def emit(self, name: str, kind: str, payload: dict[str, Any]) -> None:
        sid = self.thread(name)
        stored = self.chat.append_event(sid, make_event(kind, payload))
        self.recorder.on_event(sid, stored)

    def order(self, name: str, job_id: str, turn: str) -> None:
        sent_at = int(time.time() * 1000)
        self.emit(name, "turn_started", {"turn_id": turn, "runner": "claude-cli", "model": "m"})
        self.recorder.note_submission(
            job_id=job_id, session_id=self.thread(name), prompt="Fix it", started_ms=sent_at
        )
        self.recorder.process_pending()

    def edit(self, name: str, turn: str, path: str, text: str) -> None:
        """The agent's own tool writes a file, as the CLI reports it."""
        (self.folder / path).write_text(text, encoding="utf-8")
        self.emit(name, "tool_call", {
            "turn_id": turn, "call_id": f"w-{next(_CALLS)}", "name": "Edit",
            "input": {"file_path": str(self.folder / path)},
        })

    def shell(self, name: str, turn: str, command: str, *, ok: bool = True) -> None:
        call = f"s-{next(_CALLS)}"
        self.emit(name, "tool_call", {
            "turn_id": turn, "call_id": call, "name": "Bash", "input": {"command": command},
        })
        self.emit(name, "tool_result", {
            "turn_id": turn, "call_id": call, "output": "", "is_error": not ok,
        })

    def end(self, name: str, turn: str) -> None:
        self.emit(name, "assistant_text", {"turn_id": turn, "text": "Done."})
        self.emit(name, "turn_finished", {"turn_id": turn, "status": "done", "usage": {}})
        self.recorder.process_pending()

    def scan(self, job_id: str) -> dict[str, Any]:
        return next(s for s in self.store.steps(job_id) if s["step"] == "gates")["detail"]


@pytest.fixture
def rig(tmp_path: Path, checkout: Path):
    made = Rig(tmp_path, checkout)
    yield made
    made.store.close()


def test_a_run_in_a_dirty_shared_checkout_is_judged_on_its_own_change(rig: Rig):
    # The person's unfinished work, there before the run began.
    (rig.folder / "other.py").write_text("X = 2  # mine\n", encoding="utf-8")
    (rig.folder / "scratch.py").write_text("print('wip')\n", encoding="utf-8")
    rig.order("a", "job_a", "t1")
    assert rig.store.get("job_a")["start_tree"]
    rig.edit("a", "t1", "calc.py", CODE + "\n\ndef sub(a, b):\n    return a - b\n")
    # The person keeps working in another file meanwhile.
    (rig.folder / "scratch.py").write_text("print('more wip')\n", encoding="utf-8")
    rig.end("a", "t1")

    run = rig.store.get("job_a")
    scan = rig.scan("job_a")
    assert run["gate_status"] == "clean"
    assert scan["work_area"] == "shared_snapshot"
    assert scan["paths"] == ["calc.py"]
    assert (scan["added"], scan["deleted"]) == (4, 0)
    # Uncommitted, no remote: nothing proves it, but it was judged on its own diff.
    assert (run["state"], run["verdict"]) == ("ended", "unverified")
    assert "the work is not committed" in run["verdict_reason"]


def test_a_shared_run_that_weakens_a_check_fails_on_its_own_change(rig: Rig):
    rig.order("a", "job_a", "t1")
    skipped = TEST.replace("def test_add", "@pytest.mark.skip\ndef test_add")
    rig.edit("a", "t1", "tests/test_calc.py", skipped)
    rig.end("a", "t1")
    run = rig.store.get("job_a")
    assert run["gate_status"] == "violations"
    assert run["verdict"] == "failed"


def test_two_runs_on_the_same_file_at_the_same_time_cannot_be_told_apart(rig: Rig):
    rig.order("a", "job_a", "t1")
    rig.order("b", "job_b", "t2")
    rig.edit("a", "t1", "calc.py", CODE + "# a\n")
    rig.edit("b", "t2", "calc.py", CODE + "# a\n# b\n")
    rig.end("a", "t1")
    run = rig.store.get("job_a")
    assert run["gate_status"] == "unattributed"
    assert "another run (job_b)" in rig.scan("job_a")["reason"]
    assert "calc.py" in rig.scan("job_a")["reason"]
    assert run["verdict"] == "unverified"


def test_two_runs_on_different_files_are_each_judged_on_their_own(rig: Rig):
    rig.order("a", "job_a", "t1")
    rig.order("b", "job_b", "t2")
    rig.edit("a", "t1", "calc.py", CODE + "# a\n")
    rig.edit("b", "t2", "other.py", "X = 3\n")
    rig.end("a", "t1")
    rig.end("b", "t2")
    assert rig.scan("job_a")["paths"] == ["calc.py"]
    assert rig.scan("job_b")["paths"] == ["other.py"]
    assert rig.store.get("job_a")["gate_status"] == "clean"
    assert rig.store.get("job_b")["gate_status"] == "clean"


def test_a_run_whose_own_checks_passed_after_its_edit_is_self_checked(rig: Rig):
    rig.order("a", "job_a", "t1")
    rig.shell("a", "t1", "python -m pytest -q", ok=False)  # red before the fix
    rig.edit("a", "t1", "calc.py", CODE + "# fixed\n")
    rig.shell("a", "t1", "python -m pytest -q tests")
    rig.shell("a", "t1", "ruff check .")
    rig.end("a", "t1")

    run = rig.store.get("job_a")
    assert (run["state"], run["verdict"]) == ("ended", "self_checked")
    assert "the agent's own checks passed after its last edit" in run["verdict_reason"]
    told = verdict.from_run(run, rig.store.steps("job_a"))
    assert told.verdict == "unverified"
    assert "rests only on the agent's own checks" in told.summary
    assert "python -m pytest -q tests" in told.summary
    assert "no repository checks" in told.summary


def test_a_run_whose_own_check_failed_last_is_not_self_checked(rig: Rig):
    rig.order("a", "job_a", "t1")
    rig.edit("a", "t1", "calc.py", CODE + "# fixed\n")
    rig.shell("a", "t1", "npm test", ok=False)
    rig.end("a", "t1")
    run = rig.store.get("job_a")
    assert run["verdict"] == "unverified"
    own = next(s for s in rig.store.steps("job_a") if s["step"] == "self_checks")
    assert own["status"] == "not_passed"
    assert "tests run failed" in own["detail"]["reason"]


def test_repository_checks_outrank_the_agents_own():
    """Where GitHub has checks, the agent's own runs do not change the verdict."""
    from dodaios.orchestrator.verification import driver

    run = {"turn_status": "done", "ended_ms": 1, "signatures_json": "[]"}
    scan = {"status": "clean", "files": 1, "committed": True}
    own = {"passed": True, "reason": "the agent's own checks passed"}
    failing = {"landing": "pushed", "checks": evidence.FAILING, "failing": ["unit"]}
    assert driver.decide(run, scan, failing, now_ms=2, self_checks=own).action == (
        driver.FOLLOW_UP
    )
    passing = {"landing": "merged", "checks": evidence.PASSING, "reason": "merged"}
    assert driver.decide(run, scan, passing, now_ms=2, self_checks=own).verdict == (
        driver.VERIFIED
    )


# ------------------------------------------------------------- self checks


def _call(call: str, name: str, **args: Any) -> dict[str, Any]:
    return {"kind": "tool_call", "ts_ms": 10, "payload": {
        "call_id": call, "name": name, "input": args,
    }}


def _result(call: str, ok: bool) -> dict[str, Any]:
    return {"kind": "tool_result", "ts_ms": 10, "payload": {"call_id": call, "is_error": not ok}}


@pytest.mark.parametrize(
    ("command", "kind"),
    [
        ("python -m pytest -q", "tests"), ("pytest tests/unit", "tests"),
        ("npm run test", "tests"), ("cargo test", "tests"), ("go test ./...", "tests"),
        ("ruff check dodaios", "lint"), ("npx eslint src", "lint"),
        ("python -m mypy dodaios", "types"), ("npx tsc --noEmit", "types"),
        ("git status", ""), ("cat pytest.ini", ""), ("echo test", ""),
    ],
)
def test_what_counts_as_a_check(command: str, kind: str):
    assert self_checks.kind_of(command) == kind


def test_a_check_before_the_last_edit_says_nothing():
    events = [
        _call("c1", "Bash", command="pytest"), _result("c1", True),
        _call("w1", "Write", file_path="a.py"),
    ]
    found = self_checks.read(events)
    assert found["passed"] is False
    assert "before its last edit" in found["reason"]


def test_a_check_without_a_result_proves_nothing():
    events = [_call("w1", "Edit", file_path="a.py"), _call("c1", "Bash", command="pytest")]
    found = self_checks.read(events)
    assert (found["passed"], found["runs"]) == (False, [])
