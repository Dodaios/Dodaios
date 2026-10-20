"""A workspace's repository is reached by naming the workspace, never a path."""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import jsonschema
import pytest

from dodaios.agentic_ide import git_ops, library, resume_store
from dodaios.agentic_ide.folders import probe_project
from dodaios.agentic_ide.orchestration import WorkspaceOrchestrator
from dodaios.agentic_ide.session import Registry, Session, Terminal
from dodaios.brain.tool_gateway import BrainSupervisorToolGateway
from dodaios.brain.workspace_git_tool import WorkspaceGitTool
from dodaios.brain.workspace_tool import WorkspaceOrchestrationTool
from dodaios.live.state import LiveLedger
from tests.fakes.fake_pty_manager import FakePtyManager

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True, encoding="utf-8"
    ).stdout.strip()


def _is_dir(path: str | Path) -> bool:
    return Path(path).is_dir()


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


@pytest.fixture
def rig(tmp_path, monkeypatch):
    for key in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(key, "Test")
    for key in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(key, "test@example.invalid")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    monkeypatch.setattr(library, "_root", lambda: tmp_path / "library")
    monkeypatch.setattr(resume_store, "_store_path", lambda: tmp_path / "snapshot.json")
    registry = Registry(pty_manager=FakePtyManager())
    for name in ("Plain", "Repo"):
        path = tmp_path / name
        path.mkdir()
        if name == "Repo":
            git_ops.init_repository(path)
            (path / "app.py").write_text("print('hi')\n", encoding="utf-8")
            _git(path, "add", "--all")
            _git(path, "commit", "-m", "feat: app")
        project = library.ensure_project(path)
        workspace = Session(
            id=uuid4().hex,
            folder=str(path),
            name=name,
            profile=probe_project(path),
            terminals=[Terminal("t1", "Alex", "codex", "Codex", 0, status="live",
                                activity="idle", activity_at=time.time())],
            created_at=1,
            project_id=project.id,
        )
        registry._sessions[workspace.id] = workspace
        registry._active = workspace.id
    ledger = LiveLedger(tmp_path / "receipts.db")
    orchestrator = WorkspaceOrchestrator(registry, SimpleNamespace(), ledger)
    yield orchestrator, registry, tmp_path / "Repo"
    ledger.close()


async def git(rig, op, **args):
    return await rig[0].run({"action": "git", "op": op, **args})


async def test_state_describes_the_visible_workspace_repository(rig):
    repo = rig[2]
    (repo / "app.py").write_text("print('changed')\n", encoding="utf-8")
    (repo / "new.txt").write_text("x\n", encoding="utf-8")
    state = await git(rig, "state")
    assert state["status"] == "ok" and state["workspace"] == "Repo"
    assert state["branch"] == "main" and state["unstaged"] == 1 and state["untracked"] == 1
    assert {change["path"] for change in state["changes"]} == {"app.py", "new.txt"}
    assert state["more_changes"] == 0 and state["linked_worktree"] is False


async def test_a_folder_without_a_repository_is_refused_with_the_reason(rig):
    refused = await git(rig, "state", workspace="Plain")
    assert refused["status"] == "not_accepted" and refused["code"] == "not_repo"
    assert refused["workspace"] == "Plain" and "not a git repository" in refused["reason"]
    unknown = await git(rig, "state", workspace="No such workspace")
    assert unknown["status"] != "ok" and "branch" not in unknown


async def test_a_worktree_is_created_put_away_with_its_work_and_brought_back(rig):
    made = await git(rig, "worktree_create", branch="feature")
    assert made["status"] == "ok" and made["created"] and made["branch"] == "feature"
    tree = Path(made["folder"])
    assert _is_dir(tree) and "open_workspace" in made["next_step"]
    _write(tree / "notes.md", "unsaved\n")

    listed = await git(rig, "worktrees")
    assert [w["branch"] for w in listed["worktrees"]] == ["main", "feature"]
    assert listed["archived"] == []

    archived = await git(rig, "worktree_archive", worktree="feature")
    assert archived["status"] == "ok" and archived["archived"]["uncommitted"] is True
    assert not _is_dir(tree) and "saved" in archived["message"]
    listed = await git(rig, "worktrees")
    assert [w["branch"] for w in listed["worktrees"]] == ["main"]
    assert [entry["branch"] for entry in listed["archived"]] == ["feature"]

    restored = await git(rig, "worktree_restore", worktree="feature")
    assert restored["status"] == "ok" and Path(restored["folder"]) == tree
    assert _read(tree / "notes.md") == "unsaved\n"


async def test_a_worktree_somebody_has_open_is_not_archived(rig):
    orchestrator, registry, _repo = rig
    made = await git(rig, "worktree_create", branch="busy")
    registry.session.terminals[0].folder = made["folder"]  # an agent runs inside it
    refused = await git(rig, "worktree_archive", worktree="busy")
    assert refused["status"] == "not_accepted" and refused["code"] == "in_use"
    assert _is_dir(made["folder"])


async def test_commit_reports_the_new_commit_and_refuses_an_empty_one(rig):
    repo = rig[2]
    (repo / "new.txt").write_text("x\n", encoding="utf-8")
    done = await git(rig, "commit", message="feat: add new file")
    assert done["status"] == "ok" and done["commit"] == _git(repo, "rev-parse", "--short", "HEAD")
    again = await git(rig, "commit", message="feat: nothing")
    assert again["status"] == "not_accepted" and again["code"] == "clean"
    unnamed = await git(rig, "commit")
    assert unnamed["status"] == "not_accepted" and unnamed["code"] == "invalid"


async def test_push_and_pull_request_pass_on_gits_own_refusal(rig, monkeypatch):
    pushed = await git(rig, "push")
    assert pushed["status"] == "not_accepted" and pushed["code"] == "no_remote"
    monkeypatch.setattr(git_ops, "gh_available", lambda: False)
    opened = await git(rig, "pull_request", title="Add the thing")
    assert opened["status"] == "not_accepted" and "url" not in opened


async def test_an_unknown_operation_is_an_argument_error(rig):
    with pytest.raises(ValueError, match="op must be one of"):
        await git(rig, "rebase")


def test_reads_are_safe_and_changes_are_logged_actions(rig):
    tool = WorkspaceGitTool(rig[0])
    for op in ("state", "worktrees", "pull_requests"):
        jsonschema.validate({"op": op}, tool.schema)
        assert tool.risk_tier_for_args({"op": op}) == "safe"
        assert tool.describe_args({"op": op})["level"] == "read"
    for op in ("worktree_create", "worktree_archive", "worktree_restore", "commit", "push",
               "pull_request"):
        jsonschema.validate({"op": op}, tool.schema)
        assert tool.risk_tier_for_args({"op": op}) == "monitor"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"op": "state", "folder": "C:/elsewhere"}, tool.schema)


async def test_the_tool_answers_through_the_workspace_gateway(rig):
    tool = WorkspaceGitTool(rig[0])
    ctx = SimpleNamespace(trace_id=uuid4(), user_utterance="which branch", config={})
    ok = await tool.execute({"op": "state"}, ctx)
    assert ok.success and ok.output["branch"] == "main"
    refused = await tool.execute({"op": "state", "workspace": "Plain"}, ctx)
    assert refused.success is False and refused.output["code"] == "not_repo"
    bad = await tool.execute({"op": "rebase"}, ctx)
    assert bad.success is False and "op must be one of" in bad.error


def test_voice_gets_the_git_tool_next_to_the_workspace_tool(rig):
    manager = SimpleNamespace(_tools={}, _config=SimpleNamespace(computer_use=None))
    gateway = BrainSupervisorToolGateway(
        manager, workspace_tool=WorkspaceOrchestrationTool(rig[0])
    )
    names = {descriptor.name for descriptor in gateway.voice_catalog()}
    assert {"workspace-orchestrate", "workspace-git"} <= names
    assert "workspace-git" not in {d.name for d in gateway.catalog()}  # voice only


async def test_pull_requests_lists_the_branch_ones_first_with_their_checks(rig, monkeypatch):
    from dodaios.agentic_ide import git_overview
    from dodaios.agentic_ide.git_overview import (
        BranchRow,
        CiStatus,
        GitHubState,
        PullRequest,
        RepoOverview,
    )

    mine = PullRequest(
        number=12, title="Add the thing", url="https://example.invalid/pr/12", state="open",
        base="main", head="feature", ci=CiStatus(state="failing", failed=2, running=1),
        review="changes_requested", queue_position=None,
    )
    other = PullRequest(
        number=40, title="Someone else", url="https://example.invalid/pr/40", state="open",
        base="main", head="other", ci=CiStatus(state="passing"), queue_position=3,
        conflicting=True,
    )
    seen = RepoOverview(
        available=True, branch="feature", default_branch="main",
        branches=[BranchRow(name="feature", current=True, pull_requests=[mine])],
        pull_requests=[other, mine],
        github=GitHubState(available=True, repo="owner/repo"),
    )
    monkeypatch.setattr(git_overview, "overview", lambda folder: seen)
    listed = await git(rig, "pull_requests")
    assert listed["status"] == "ok" and listed["github"] == {
        "connected": True, "repository": "owner/repo",
    }
    first, second = listed["pull_requests"]
    assert first == {
        "number": 12, "title": "Add the thing", "state": "open", "branch": "feature",
        "into": "main", "url": "https://example.invalid/pr/12", "checks": "failing",
        "failed_checks": 2, "running_checks": 1, "review": "changes_requested", "here": True,
    }
    assert second["number"] == 40 and second["merge_queue_position"] == 3
    assert second["conflicting"] is True and "here" not in second
    assert listed["more_pull_requests"] == 0


async def test_pull_requests_says_when_github_is_not_connected(rig, monkeypatch):
    from dodaios.agentic_ide import git_overview
    from dodaios.agentic_ide.git_overview import GitHubState, RepoOverview

    seen = RepoOverview(
        available=True, branch="main",
        github=GitHubState(available=False, reason="Sign in to GitHub to see pull requests."),
    )
    monkeypatch.setattr(git_overview, "overview", lambda folder: seen)
    listed = await git(rig, "pull_requests")
    assert listed["status"] == "ok" and listed["pull_requests"] == []
    assert listed["github"] == {
        "connected": False, "reason": "Sign in to GitHub to see pull requests.",
    }
    gone = RepoOverview(available=False, reason="The workspace folder is missing.")
    monkeypatch.setattr(git_overview, "overview", lambda folder: gone)
    refused = await git(rig, "pull_requests")
    assert refused["status"] == "not_accepted" and "missing" in refused["reason"]


async def test_archiving_names_ignored_files_and_needs_the_users_word_to_drop_them(rig):
    made = await git(rig, "worktree_create", branch="scratch")
    tree = Path(made["folder"])
    _write(rig[2] / ".git" / "info" / "exclude", "secret.env" + chr(10))
    _write(tree / "secret.env", "TOKEN=x")
    refused = await git(rig, "worktree_archive", worktree="scratch")
    assert refused["status"] == "not_accepted" and refused["code"] == "ignored_files"
    assert "secret.env" in refused["reason"] and _is_dir(tree)
    done = await git(rig, "worktree_archive", worktree="scratch", drop_ignored=True)
    assert done["status"] == "ok" and not _is_dir(tree)


async def test_opening_a_pull_request_refreshes_what_github_is_known_to_hold(rig, monkeypatch):
    from dodaios.agentic_ide import git_overview, github_pulls

    cleared = []
    monkeypatch.setattr(github_pulls, "open_for_branch", lambda folder, **kw: "https://x/pr/1")
    monkeypatch.setattr(git_overview, "clear_github", cleared.append)
    opened = await git(rig, "pull_request", title="Add the thing")
    assert opened["status"] == "ok" and opened["url"] == "https://x/pr/1"
    assert [Path(folder) for folder in cleared] == [rig[2]]
