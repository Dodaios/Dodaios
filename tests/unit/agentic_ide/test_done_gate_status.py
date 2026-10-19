"""The pane header's done-gate verdict, read only from the gate's own files."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.agentic_ide import done_gate_status as gate
from dodaios.agentic_ide.agent_sessions import ResumeHandle
from dodaios.agentic_ide.done_gate_status import PaneGateRecord
from dodaios.ui.web import agentic_ide_git_routes as routes
from tests.fakes.fake_done_gate import FakeRepoLocator, iso, write_session

# Real time: the reader skips files by their modification time before parsing them.
NOW = time.time()


@pytest.fixture
def repo(tmp_path: Path) -> SimpleNamespace:
    common = tmp_path / "main" / ".git"
    common.mkdir(parents=True)
    worktree = tmp_path / "wt"
    worktree.mkdir()
    locator = FakeRepoLocator()
    locator.add(tmp_path / "main", common, "main")
    locator.add(worktree, common, "claude/feature")
    return SimpleNamespace(common=common, main=tmp_path / "main", worktree=worktree, locate=locator)


def test_a_pane_with_a_known_session_reads_that_sessions_file(repo) -> None:
    write_session(
        repo.common,
        "abc-123",
        verdict="WAIT",
        at=NOW - 60,
        reason="CI is running",
        next_step="Wait for CI.",
        pr=42,
        branch="claude/feature",
        cwd=repo.worktree,
    )
    answer = gate.board(
        [PaneGateRecord("t1", str(repo.worktree), session_id="abc-123")],
        now=NOW,
        find_repo=repo.locate,
    )
    assert answer["t1"] == {
        "verdict": "WAIT",
        "reason": "CI is running",
        "next": "Wait for CI.",
        "pr": 42,
        "branch": "claude/feature",
        "at": iso(NOW - 60),
        "matched": "session",
    }


def test_session_ids_are_mapped_to_the_gates_file_names(repo) -> None:
    write_session(repo.common, "a/b:c", verdict="FIX", at=NOW)
    assert (repo.common / "agent-done-gate" / "sessions" / "a_b_c.json").exists()
    answer = gate.board(
        [PaneGateRecord("t1", str(repo.main), session_id="a/b:c")], now=NOW, find_repo=repo.locate
    )
    assert answer["t1"]["verdict"] == "FIX"


@pytest.mark.parametrize("verdict", ["NONE", "HOLD"])
def test_quiet_verdicts_show_nothing(repo, verdict: str) -> None:
    write_session(repo.common, "s1", verdict=verdict, at=NOW)
    answer = gate.board(
        [PaneGateRecord("t1", str(repo.main), session_id="s1")], now=NOW, find_repo=repo.locate
    )
    assert answer == {"t1": None}


def test_a_known_session_never_borrows_a_neighbours_record(repo) -> None:
    write_session(
        repo.common, "other", verdict="FIX", at=NOW, cwd=repo.worktree, branch="claude/feature"
    )
    answer = gate.board(
        [PaneGateRecord("t1", str(repo.worktree), session_id="mine")],
        now=NOW,
        find_repo=repo.locate,
    )
    assert answer == {"t1": None}


def test_without_a_session_the_newest_record_for_the_folder_wins(repo) -> None:
    write_session(repo.common, "old", verdict="FIX", at=NOW - 600, cwd=repo.worktree)
    write_session(repo.common, "new", verdict="DONE", at=NOW - 60, cwd=repo.worktree / ".")
    write_session(repo.common, "elsewhere", verdict="STUCK", at=NOW, cwd=repo.main)
    answer = gate.board([PaneGateRecord("t1", str(repo.worktree))], now=NOW, find_repo=repo.locate)
    assert answer["t1"]["verdict"] == "DONE"
    assert answer["t1"]["matched"] == "folder"


def test_without_a_session_a_record_for_the_panes_branch_matches(repo) -> None:
    write_session(
        repo.common,
        "s1",
        verdict="STUCK",
        at=NOW - 60,
        cwd=repo.main / "sub",
        branch="claude/feature",
    )
    by_checkout = gate.board(
        [PaneGateRecord("t1", str(repo.worktree))], now=NOW, find_repo=repo.locate
    )
    assert by_checkout["t1"]["verdict"] == "STUCK"
    by_fork_branch = gate.board(
        [PaneGateRecord("t2", str(repo.main), branch="claude/feature")],
        now=NOW,
        find_repo=repo.locate,
    )
    assert by_fork_branch["t2"]["verdict"] == "STUCK"


def test_folder_matches_older_than_six_hours_are_ignored(repo) -> None:
    write_session(repo.common, "s1", verdict="WAIT", at=NOW - 6 * 3600 - 5, cwd=repo.worktree)
    answer = gate.board([PaneGateRecord("t1", str(repo.worktree))], now=NOW, find_repo=repo.locate)
    assert answer == {"t1": None}


def test_folder_matches_skip_sessions_another_pane_owns(repo) -> None:
    write_session(repo.common, "owned", verdict="FIX", at=NOW, cwd=repo.main)
    answer = gate.board(
        [
            PaneGateRecord("t1", str(repo.main), session_id="owned"),
            PaneGateRecord("t2", str(repo.main)),
        ],
        now=NOW,
        find_repo=repo.locate,
    )
    assert answer["t1"]["verdict"] == "FIX"
    assert answer["t2"] is None


def test_a_newer_quiet_verdict_hides_an_older_loud_one(repo) -> None:
    write_session(repo.common, "a", verdict="FIX", at=NOW - 300, cwd=repo.worktree)
    write_session(repo.common, "b", verdict="HOLD", at=NOW - 10, cwd=repo.worktree)
    answer = gate.board([PaneGateRecord("t1", str(repo.worktree))], now=NOW, find_repo=repo.locate)
    assert answer == {"t1": None}


def test_broken_or_foreign_files_and_folders_outside_git_are_quiet(repo, tmp_path: Path) -> None:
    sessions = repo.common / "agent-done-gate" / "sessions"
    sessions.mkdir(parents=True)
    (sessions / "bad.json").write_text("{not json", encoding="utf-8")
    (sessions / "nolast.json").write_text('{"branches": []}', encoding="utf-8")
    (sessions / "nodate.json").write_text(
        '{"last": {"verdict": "FIX", "at": "yesterday"}}', encoding="utf-8"
    )
    answer = gate.board(
        [
            PaneGateRecord("t1", str(repo.main), session_id="bad"),
            PaneGateRecord("t2", str(repo.main), session_id="nolast"),
            PaneGateRecord("t3", str(repo.main)),
            PaneGateRecord("t4", str(tmp_path / "not-a-repo")),
        ],
        now=NOW,
        find_repo=repo.locate,
    )
    assert answer == {"t1": None, "t2": None, "t3": None, "t4": None}


def test_an_odd_pull_request_field_is_dropped_and_long_text_is_cut(repo) -> None:
    write_session(repo.common, "s1", verdict="fix", at=NOW, reason="x" * 5000)
    path = repo.common / "agent-done-gate" / "sessions" / "s1.json"
    path.write_text(
        path.read_text(encoding="utf-8").replace('"pr": null', '"pr": true'), encoding="utf-8"
    )
    answer = gate.board(
        [PaneGateRecord("t1", str(repo.main), session_id="s1")], now=NOW, find_repo=repo.locate
    )
    assert answer["t1"]["verdict"] == "FIX"
    assert answer["t1"]["pr"] is None
    assert len(answer["t1"]["reason"]) == gate.MAX_TEXT


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_locate_reads_the_common_dir_and_branch_of_a_worktree(tmp_path: Path) -> None:
    main = tmp_path / "main"
    main.mkdir()
    _git(main, "init", "-q", "-b", "main")
    _git(
        main,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@example.invalid",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "c",
    )
    _git(main, "worktree", "add", "-q", "-b", "claude/x", str(tmp_path / "wt"))
    gate.forget_repos()
    info = gate.locate(str(tmp_path / "wt"))
    assert info.branch == "claude/x"
    assert info.common_dir is not None and info.common_dir.resolve() == (main / ".git").resolve()
    assert gate.locate(str(tmp_path / "missing")).common_dir is None
    gate.forget_repos()


def test_the_route_maps_each_local_pane_by_its_session(monkeypatch, repo) -> None:
    write_session(repo.common, "claude-1", verdict="WAIT", at=time.time() - 30, reason="queued")
    write_session(repo.common, "codex-2", verdict="FIX", at=time.time() - 30, cwd=repo.main)

    def pane(
        name: str, folder: str = "", resume: ResumeHandle | None = None, computer_id: str = ""
    ):
        return SimpleNamespace(
            name=name,
            folder=folder,
            branch="",
            resume=resume,
            computer_id=computer_id,
            cwd=lambda workspace, folder=folder: folder or workspace,
        )

    session = SimpleNamespace(
        id="w1",
        folder=str(repo.main),
        terminals=[
            pane("t1", str(repo.worktree), ResumeHandle("claude_session", "claude-1", 0)),
            pane("t2"),
            pane("t3", computer_id="vps"),
        ],
    )
    monkeypatch.setattr(
        routes,
        "get_registry",
        lambda: SimpleNamespace(get=lambda workspace_id: session if workspace_id == "w1" else None),
    )
    monkeypatch.setattr(gate, "locate", repo.locate)
    app = FastAPI()
    app.include_router(routes.router)
    client = TestClient(app)

    body = client.get("/api/agentic-ide/git/done-gate", params={"workspace_id": "w1"}).json()
    assert set(body["panes"]) == {"t1", "t2"}
    assert body["panes"]["t1"]["verdict"] == "WAIT"
    assert body["panes"]["t2"]["verdict"] == "FIX"
    assert body["panes"]["t2"]["matched"] == "folder"
    assert (
        client.get("/api/agentic-ide/git/done-gate", params={"workspace_id": "nope"}).status_code
        == 404
    )
