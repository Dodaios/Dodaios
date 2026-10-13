"""Archiving a worktree keeps what was in it; restoring brings it back as it was."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from jarvis.agentic_ide import git_ops, worktree_archive
from jarvis.agentic_ide.git_ops import GitError

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


@pytest.fixture(autouse=True)
def _identity(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.invalid")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@example.invalid")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True, encoding="utf-8"
    ).stdout.strip()


def _status(cwd: Path) -> set[str]:
    """``git status --porcelain`` lines with their leading status columns intact."""
    out = subprocess.run(
        ["git", "status", "--porcelain"], cwd=cwd, capture_output=True, text=True, check=True,
        encoding="utf-8",
    ).stdout
    return set(out.splitlines())


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "p"
    root.mkdir()
    git_ops.init_repository(root)
    (root / "app.py").write_text("print('hi')\n", encoding="utf-8")
    (root / "old.txt").write_text("to be deleted\n", encoding="utf-8")
    (root / ".gitignore").write_text("build/\n", encoding="utf-8")
    _git(root, "add", "--all")
    _git(root, "commit", "-m", "feat: app")
    return root


@pytest.fixture
def tree(repo: Path) -> Path:
    """A linked worktree on ``feature`` with one commit of its own and unsaved work."""
    made = git_ops.prepare(repo, "new_worktree", branch="feature")
    path = Path(made.folder)
    (path / "done.txt").write_text("committed on the branch\n", encoding="utf-8")
    _git(path, "add", "done.txt")
    _git(path, "commit", "-m", "feat: done")
    (path / "app.py").write_text("print('changed')\n", encoding="utf-8")
    (path / "notes.md").write_text("never added\n", encoding="utf-8")
    (path / "old.txt").unlink()
    (path / "build").mkdir()
    (path / "build" / "out.bin").write_text("ignored\n", encoding="utf-8")
    return path


def test_archive_saves_the_work_and_removes_only_the_checkout(repo: Path, tree: Path) -> None:
    tip = _git(repo, "rev-parse", "feature")
    entry = worktree_archive.archive(repo, "feature", open_folders=[str(repo)])
    assert not tree.exists()
    assert entry.branch == "feature" and entry.uncommitted and entry.head == tip
    assert _git(repo, "rev-parse", "feature") == tip  # the branch and its commit stay
    assert "feature" in _git(repo, "branch", "--list", "feature")
    listed = worktree_archive.archived(repo)
    assert [item.to_dict() for item in listed] == [entry.to_dict()]
    # A snapshot is not a branch and does not show up as one.
    assert entry.name not in _git(repo, "branch", "--all")


def test_restore_brings_back_the_files_as_uncommitted_changes(repo: Path, tree: Path) -> None:
    worktree_archive.archive(repo, str(tree), open_folders=[])
    restored = worktree_archive.restore(repo, "feature")
    assert Path(restored.folder) == tree and restored.branch == "feature" and restored.created
    assert (tree / "app.py").read_text(encoding="utf-8") == "print('changed')\n"
    assert (tree / "notes.md").read_text(encoding="utf-8") == "never added\n"
    assert (tree / "done.txt").exists() and not (tree / "old.txt").exists()
    # Nothing was committed or staged: unstaged edits and an untracked file.
    assert _status(tree) == {" M app.py", " D old.txt", "?? notes.md"}
    assert worktree_archive.archived(repo) == []
    assert not (tree / "build").exists()  # ignored files are not part of a snapshot


def test_a_clean_worktree_round_trips_without_changes(repo: Path) -> None:
    path = Path(git_ops.prepare(repo, "new_worktree", branch="tidy").folder)
    entry = worktree_archive.archive(repo, "tidy", open_folders=[])
    assert entry.uncommitted is False and not path.exists()
    worktree_archive.restore(repo, entry.name)
    assert path.is_dir() and _git(path, "status", "--porcelain") == ""


def test_archive_works_on_a_machine_without_a_git_identity(
    repo: Path, tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for key in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"):
        monkeypatch.delenv(key)
    entry = worktree_archive.archive(repo, "feature", open_folders=[])
    assert entry.uncommitted and not tree.exists()


def test_a_branch_that_moved_on_is_restored_detached_at_the_archived_commit(
    repo: Path, tree: Path
) -> None:
    entry = worktree_archive.archive(repo, "feature", open_folders=[])
    _git(repo, "switch", "feature")
    (repo / "later.txt").write_text("after the archive\n", encoding="utf-8")
    _git(repo, "add", "later.txt")
    _git(repo, "commit", "-m", "feat: later")
    _git(repo, "switch", "main")
    restored = worktree_archive.restore(repo, entry.name)
    assert restored.branch == "" and "moved on" in restored.message
    assert _git(tree, "rev-parse", "HEAD") == entry.head
    assert (tree / "notes.md").exists() and not (tree / "later.txt").exists()


def test_what_must_not_be_archived_is_refused_and_nothing_is_lost(repo: Path, tree: Path) -> None:
    with pytest.raises(GitError) as in_use:
        worktree_archive.archive(repo, "feature", open_folders=[str(tree / "sub")])
    assert in_use.value.code == "in_use" and (tree / "notes.md").exists()
    with pytest.raises(GitError) as main:
        worktree_archive.archive(repo, "main", open_folders=[])
    assert main.value.code == "invalid"
    with pytest.raises(GitError) as unknown:
        worktree_archive.archive(repo, "nope", open_folders=[])
    assert unknown.value.code == "not_found" and "feature" in str(unknown.value)
    assert worktree_archive.archived(repo) == []


def test_restore_refuses_an_occupied_path_and_keeps_the_snapshot(repo: Path, tree: Path) -> None:
    entry = worktree_archive.archive(repo, "feature", open_folders=[])
    tree.mkdir(parents=True)
    with pytest.raises(GitError) as taken:
        worktree_archive.restore(repo, entry.name)
    assert taken.value.code == "exists"
    assert [item.name for item in worktree_archive.archived(repo)] == [entry.name]
    with pytest.raises(GitError) as unknown:
        worktree_archive.restore(repo, "nope")
    assert unknown.value.code == "not_found"


def test_archiving_the_same_branch_twice_restores_the_newest(repo: Path, tree: Path) -> None:
    first = worktree_archive.archive(repo, "feature", open_folders=[])
    worktree_archive.restore(repo, first.name)
    (tree / "notes.md").write_text("second round\n", encoding="utf-8")
    second = worktree_archive.archive(repo, "feature", open_folders=[])
    assert [item.name for item in worktree_archive.archived(repo)] == [second.name]
    worktree_archive.restore(repo, "feature")
    assert (tree / "notes.md").read_text(encoding="utf-8") == "second round\n"
