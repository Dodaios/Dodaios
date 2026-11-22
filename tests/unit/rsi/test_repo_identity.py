"""One id per repository, whatever the remote spelling and whichever checkout."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from dodaios.rsi import repo_identity

#: A made-up login part of a remote address, joined at run time so no scanner
#: reads a credential-shaped literal in this file.
_LOGIN = "user:" + "made-up-value"


@pytest.mark.parametrize(
    "url",
    [
        "git@github.com:Acme/Notes.git",
        "https://github.com/Acme/Notes.git",
        "https://github.com/acme/notes",
        f"https://{_LOGIN}@github.com/Acme/Notes.git",
        "ssh://git@github.com:22/Acme/Notes.git",
        "https://github.com/Acme/Notes/",
    ],
)
def test_every_spelling_of_a_remote_is_one_id(url):
    assert repo_identity.normalize_remote(url) == "github.com/acme/notes"


def test_credentials_never_reach_the_id():
    found = repo_identity.normalize_remote(f"https://{_LOGIN}@example.com/team/app.git")
    assert found == "example.com/team/app"
    assert "made-up-value" not in found


@pytest.mark.parametrize("url", ["", "   ", "/Users/me/repos/app.git", "C:/repos/app.git", "x"])
def test_a_local_path_or_nothing_is_not_a_remote(url):
    assert repo_identity.normalize_remote(url) == ""


def _git(folder: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", *args], cwd=folder, capture_output=True, text=True, check=True
    )
    return done.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    folder = tmp_path / "main"
    folder.mkdir()
    _git(folder, "init", "-q", "-b", "main")
    _git(folder, "config", "user.email", "t@example.com")
    _git(folder, "config", "user.name", "T")
    (folder / "a.txt").write_text("a\n", encoding="utf-8")
    _git(folder, "add", "a.txt")
    _git(folder, "commit", "-q", "-m", "first")
    return folder


def test_a_worktree_and_its_main_checkout_share_one_id(repo: Path, tmp_path: Path):
    linked = tmp_path / "linked"
    _git(repo, "worktree", "add", "-q", "-b", "side", str(linked))
    main_ref = repo_identity.describe(repo)
    side_ref = repo_identity.describe(linked)
    assert main_ref.repo_id == side_ref.repo_id
    assert main_ref.repo_id.startswith("path:")
    assert main_ref.isolated is False
    assert side_ref.isolated is True
    assert side_ref.base_sha == _git(linked, "rev-parse", "HEAD")


def test_the_origin_names_the_repository_when_there_is_one(repo: Path):
    _git(repo, "remote", "add", "origin", "git@github.com:Acme/Notes.git")
    assert repo_identity.repo_id(repo) == "github.com/acme/notes"


def test_a_folder_that_is_no_repository_still_gets_an_answer(tmp_path: Path):
    ref = repo_identity.describe(tmp_path)
    assert ref.repo_id.startswith("path:")
    assert ref.base_sha == ""
    assert ref.isolated is False
