"""Local ``main`` mirrors the remote: the commit hook refuses a commit on it."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.ci import check_commit_branch


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "test@example.invalid")
    _git(tmp_path, "config", "user.name", "Test")
    _git(tmp_path, "config", "commit.gpgsign", "false")
    (tmp_path / "file.txt").write_text("one\n", encoding="utf-8")
    _git(tmp_path, "add", "--", "file.txt")
    _git(tmp_path, "commit", "-q", "--no-verify", "-m", "chore: seed")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    return tmp_path


def test_commit_on_main_is_refused(repo, capsys):
    assert check_commit_branch.main(["--quiet"]) == check_commit_branch.EXIT_PROTECTED

    err = capsys.readouterr().err
    assert "git worktree add -b" in err
    assert "origin/main" in err


def test_feature_branch_is_allowed(repo):
    _git(repo, "switch", "-q", "-c", "claude/some-topic")

    assert check_commit_branch.main(["--quiet"]) == check_commit_branch.EXIT_OK


def test_branch_that_only_starts_with_main_is_allowed(repo):
    _git(repo, "switch", "-q", "-c", "main-mirror-rule")

    assert check_commit_branch.main(["--quiet"]) == check_commit_branch.EXIT_OK


def test_detached_head_is_allowed(repo):
    _git(repo, "checkout", "-q", "--detach", "HEAD")

    assert check_commit_branch.main(["--quiet"]) == check_commit_branch.EXIT_OK


def test_ci_runner_is_left_alone(repo, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    assert check_commit_branch.main(["--quiet"]) == check_commit_branch.EXIT_OK
