"""Local ``main`` only moves to a commit a remote ``main`` already has."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[3] / ".githooks" / "reference-transaction"

# git runs hooks through a POSIX shell; without one the hook cannot be exercised.
pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def _commit(repo: Path, message: str) -> str:
    _git(repo, "commit", "-q", "--allow-empty", "-m", message)
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _configure(repo: Path) -> None:
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "commit.gpgsign", "false")


@pytest.fixture
def clone(tmp_path: Path, monkeypatch) -> Path:
    """A clone whose ``origin/main`` is one commit ahead of nothing local."""
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    remote = tmp_path / "remote"
    remote.mkdir()
    _git(remote, "init", "-q", "-b", "main")
    _configure(remote)
    _commit(remote, "chore: seed")

    repo = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(remote), str(repo)], check=True, capture_output=True)
    _configure(repo)
    hooks = tmp_path / "hooks"
    hooks.mkdir()
    target = hooks / "reference-transaction"
    target.write_bytes(HOOK.read_bytes())
    target.chmod(0o755)
    _git(repo, "config", "core.hooksPath", str(hooks))
    return repo


def _remote_advances(clone: Path) -> str:
    remote = clone.parent / "remote"
    tip = _commit(remote, "feat: landed upstream")
    _git(clone, "fetch", "-q", "origin")
    return tip


def test_commit_on_main_is_refused(clone):
    before = _git(clone, "rev-parse", "main").stdout.strip()

    result = _git(clone, "commit", "--allow-empty", "-m", "feat: local only", check=False)

    assert result.returncode != 0
    assert "reference-transaction BLOCKED" in result.stderr
    assert _git(clone, "rev-parse", "main").stdout.strip() == before


def test_update_ref_to_a_local_commit_is_refused(clone):
    _git(clone, "switch", "-q", "-c", "claude/topic")
    local = _commit(clone, "feat: on a branch")
    before = _git(clone, "rev-parse", "main").stdout.strip()

    result = _git(clone, "update-ref", "refs/heads/main", local, check=False)

    assert result.returncode != 0
    assert _git(clone, "rev-parse", "main").stdout.strip() == before


def test_fast_forward_to_the_remote_is_allowed(clone):
    tip = _remote_advances(clone)

    _git(clone, "merge", "-q", "--ff-only", "origin/main")

    assert _git(clone, "rev-parse", "main").stdout.strip() == tip


def test_reset_to_the_remote_is_allowed(clone):
    tip = _remote_advances(clone)

    _git(clone, "reset", "-q", "--hard", "origin/main")

    assert _git(clone, "rev-parse", "main").stdout.strip() == tip


def test_feature_branches_move_freely(clone):
    _git(clone, "switch", "-q", "-c", "claude/topic")

    tip = _commit(clone, "feat: on a branch")

    assert _git(clone, "rev-parse", "claude/topic").stdout.strip() == tip


def test_deleting_main_is_allowed(clone):
    _git(clone, "switch", "-q", "-c", "claude/topic")

    _git(clone, "branch", "-D", "main")

    assert _git(clone, "rev-parse", "--verify", "-q", "refs/heads/main", check=False).returncode


def test_repository_without_a_remote_main_is_left_alone(clone):
    _git(clone, "remote", "remove", "origin")

    tip = _commit(clone, "feat: nothing to mirror")

    assert _git(clone, "rev-parse", "main").stdout.strip() == tip


def test_ci_runner_is_left_alone(clone, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    tip = _commit(clone, "chore: written by a workflow")

    assert _git(clone, "rev-parse", "main").stdout.strip() == tip
