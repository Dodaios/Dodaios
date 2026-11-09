"""The shared main checkout warns the moment a session switches it off main.

The hook is run with ``sh`` and the arguments git passes it (``<old-head>
<new-head> <flag>``), so the test does not depend on the temp directory
allowing executables: git skips a hook it cannot execute without failing.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[3] / ".githooks" / "post-checkout"
ZERO = "0" * 40

pytestmark = pytest.mark.skipif(shutil.which("sh") is None, reason="needs a POSIX sh")


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )


def _hook(cwd: Path, flag: str = "1") -> str:
    """Run the hook the way git does after a checkout in ``cwd``; return its stderr."""
    head = _git(cwd, "rev-parse", "HEAD").stdout.strip()
    result = subprocess.run(
        ["sh", str(HOOK), ZERO, head, flag],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stderr


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
    return root


def test_shared_checkout_warns_on_a_feature_branch(repo):
    _git(repo, "config", "dodaios.sharedCheckout", "true")
    _git(repo, "switch", "-q", "-c", "claude/topic")

    stderr = _hook(repo)

    assert "shared main checkout is now on 'claude/topic'" in stderr
    assert "git switch main" in stderr


def test_back_on_main_is_quiet(repo):
    _git(repo, "config", "dodaios.sharedCheckout", "true")
    _git(repo, "switch", "-q", "-c", "claude/topic")
    _git(repo, "switch", "-q", "main")

    assert "WARNING" not in _hook(repo)


def test_file_checkout_is_quiet(repo):
    _git(repo, "config", "dodaios.sharedCheckout", "true")
    _git(repo, "switch", "-q", "-c", "claude/topic")

    assert "WARNING" not in _hook(repo, flag="0")


def test_unmarked_clone_is_quiet(repo):
    _git(repo, "switch", "-q", "-c", "claude/topic")

    assert "WARNING" not in _hook(repo)


def test_ci_is_quiet(repo, monkeypatch):
    _git(repo, "config", "dodaios.sharedCheckout", "true")
    _git(repo, "switch", "-q", "-c", "claude/topic")
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    assert "WARNING" not in _hook(repo)


def test_linked_worktree_is_quiet(repo, tmp_path):
    _git(repo, "config", "dodaios.sharedCheckout", "true")
    linked = tmp_path / "linked"
    _git(repo, "worktree", "add", "-q", "-b", "claude/topic", str(linked))

    assert "WARNING" not in _hook(linked)
