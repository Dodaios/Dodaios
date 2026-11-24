"""`scripts/ci/install_git_hooks.py` points git at ONE copy of the tracked hooks.

``core.hooksPath`` written as the relative ``.githooks`` makes git look for the
hooks in whichever tree is checked out, so a linked worktree runs the hook
files of the branch it holds, whoever wrote that branch. The installer writes
the absolute path of the primary checkout's ``.githooks`` and never replaces
an absolute path that is already set.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts.ci import install_git_hooks as hooks

REPO_ROOT = Path(__file__).resolve().parents[3]

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )
    return done.stdout.strip()


def _hooks_path(repo: Path) -> str:
    return _git(repo, "config", "--get", "core.hooksPath")


def _write_hook(repo: Path, body: str) -> None:
    hook = repo / ".githooks" / "post-checkout"
    hook.parent.mkdir(exist_ok=True)
    hook.write_text("#!/bin/sh\n" + body + "\nexit 0\n", encoding="utf-8", newline="\n")
    hook.chmod(0o755)
    _git(repo, "add", "--", ".githooks/post-checkout")
    _git(repo, "update-index", "--chmod=+x", ".githooks/post-checkout")


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    """A clone that tracks a harmless ``.githooks/post-checkout``, on main."""
    root = tmp_path / "primary"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    for key, value in (
        ("user.email", "test@example.invalid"),
        ("user.name", "Test"),
        ("commit.gpgsign", "false"),
        ("core.autocrlf", "false"),
    ):
        _git(root, "config", key, value)
    _write_hook(root, ": the hook of main does nothing")
    _git(root, "commit", "-q", "--no-verify", "-m", "chore: seed")
    monkeypatch.chdir(root)
    return root


def _same(left: str | Path, right: str | Path) -> bool:
    return os.path.samefile(str(left), str(right))


def test_a_fresh_clone_gets_the_absolute_path_of_its_hooks(repo: Path) -> None:
    assert hooks.main() == 0

    path = _hooks_path(repo)
    assert os.path.isabs(path)
    assert _same(path, repo / ".githooks")


def test_a_relative_path_is_replaced_by_the_absolute_one(repo: Path) -> None:
    _git(repo, "config", "core.hooksPath", ".githooks")

    assert hooks.main() == 0

    path = _hooks_path(repo)
    assert path != ".githooks" and os.path.isabs(path)
    assert _same(path, repo / ".githooks")


def test_an_absolute_path_is_never_replaced(repo: Path, tmp_path: Path) -> None:
    """Running the installer again must not weaken what a machine already has."""
    elsewhere = tmp_path / "trusted-hooks"
    elsewhere.mkdir()
    _git(repo, "config", "core.hooksPath", str(elsewhere))

    assert hooks.main() == 0
    assert hooks.main() == 0

    assert _hooks_path(repo) == str(elsewhere)


def test_an_absolute_path_to_a_folder_that_is_gone_is_repaired(repo: Path, tmp_path: Path) -> None:
    _git(repo, "config", "core.hooksPath", str(tmp_path / "moved-away" / ".githooks"))

    assert hooks.main() == 0

    assert _same(_hooks_path(repo), repo / ".githooks")


def test_run_from_a_linked_worktree_it_names_the_primary_checkout(
    repo: Path, tmp_path: Path, monkeypatch
) -> None:
    worktree = tmp_path / "linked"
    _git(repo, "worktree", "add", "-q", "-b", "topic", str(worktree))
    monkeypatch.chdir(worktree)

    assert hooks.main() == 0

    assert _same(_hooks_path(worktree), repo / ".githooks")
    assert not _same(_hooks_path(worktree), worktree / ".githooks")


def test_a_worktree_never_runs_the_hooks_of_the_branch_it_holds(repo: Path, tmp_path: Path) -> None:
    """The reason for the absolute path, shown with git itself."""
    marker = tmp_path / "ran.txt"
    _git(repo, "switch", "-q", "-c", "outside")
    _write_hook(repo, f'echo ran >> "{marker.as_posix()}"')
    _git(repo, "commit", "-q", "--no-verify", "-m", "chore: a hook from outside")
    _git(repo, "switch", "-q", "main")
    assert hooks.main() == 0
    marker.unlink(missing_ok=True)
    worktree = tmp_path / "linked"
    _git(repo, "worktree", "add", "-q", "-b", "review", str(worktree), "main")

    _git(worktree, "switch", "-q", "--detach", "outside")

    assert not marker.exists(), "the worktree ran the hook file of the branch it checked out"

    # The control: with the relative path git does run that file, so the
    # assertion above is not passing merely because hooks cannot run here.
    _git(worktree, "switch", "-q", "--detach", "main")
    _git(repo, "config", "core.hooksPath", ".githooks")
    _git(worktree, "switch", "-q", "--detach", "outside")
    if not marker.exists():
        pytest.skip("git ran no tracked hook here, so the check above proves nothing")


def test_preflight_leaves_the_path_to_the_installer() -> None:
    """``scripts/preflight.ps1`` wired the relative path itself, on every run."""
    text = (REPO_ROOT / "scripts" / "preflight.ps1").read_text(encoding="utf-8")
    assert "scripts/ci/install_git_hooks.py" in text
    assert "config --local core.hooksPath" not in text
    assert "core.hooksPath .githooks" not in text
