"""The shared main checkout warns the moment a session switches it off main."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[3] / ".githooks" / "post-checkout"

pytestmark = pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX sh")


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    root = tmp_path / "shared"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "commit.gpgsign", "false")
    (root / "file.txt").write_text("one\n", encoding="utf-8")
    _git(root, "add", "--", "file.txt")
    _git(root, "commit", "-q", "--no-verify", "-m", "chore: seed")
    hooks = root / ".hooks"
    hooks.mkdir()
    target = hooks / "post-checkout"
    shutil.copyfile(HOOK, target)
    # git skips a hook without the executable bit on POSIX.
    target.chmod(0o755)
    _git(root, "config", "core.hooksPath", str(hooks))
    return root


def test_shared_checkout_warns_on_a_feature_branch(repo):
    _git(repo, "config", "dodaios.sharedCheckout", "true")

    result = _git(repo, "switch", "-c", "claude/topic")

    assert "shared main checkout is now on 'claude/topic'" in result.stderr
    assert "git switch main" in result.stderr


def test_back_on_main_is_quiet(repo):
    _git(repo, "config", "dodaios.sharedCheckout", "true")
    _git(repo, "switch", "-q", "-c", "claude/topic")

    assert "WARNING" not in _git(repo, "switch", "main").stderr


def test_unmarked_clone_is_quiet(repo):
    assert "WARNING" not in _git(repo, "switch", "-c", "claude/topic").stderr


def test_linked_worktree_is_quiet(repo, tmp_path):
    _git(repo, "config", "dodaios.sharedCheckout", "true")

    result = _git(repo, "worktree", "add", "-b", "claude/topic", str(tmp_path / "linked"))

    assert "WARNING" not in result.stderr
