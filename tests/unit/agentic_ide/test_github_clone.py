"""A GitHub repository picked in the thread composer lands on this computer once."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from dodaios.agentic_ide import git_ops, github_clone, github_link, library
from dodaios.agentic_ide.git_ops import GitError

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True, encoding="utf-8"
    ).stdout.strip()


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.invalid")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@example.invalid")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    monkeypatch.setattr(github_clone, "clone_home", lambda: tmp_path / "home")


@pytest.fixture
def upstream(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A repository with one commit that stands in for the one on GitHub."""
    source = tmp_path / "upstream"
    source.mkdir()
    _git(source, "init", "-q", "-b", "main")
    (source / "readme.txt").write_text("hello", encoding="utf-8")
    _git(source, "add", "readme.txt")
    _git(source, "commit", "-q", "-m", "first")
    monkeypatch.setattr(github_clone, "_clone_url", lambda repo: str(source))
    return source


def test_a_repository_is_cloned_into_the_clone_home(upstream: Path, tmp_path: Path) -> None:
    cloned = github_clone.clone_repository("octo/notes", None)
    assert cloned.created is True
    assert cloned.folder == tmp_path / "home" / "notes"
    assert (cloned.folder / "readme.txt").read_text(encoding="utf-8") == "hello"
    assert cloned.to_dict() == {"folder": str(cloned.folder), "repo": "octo/notes", "created": True}


def test_a_repository_that_is_already_there_is_reused(upstream: Path) -> None:
    first = github_clone.clone_repository("octo/notes", None)
    _git(first.folder, "remote", "set-url", "origin", "https://github.com/Octo/notes.git")
    (first.folder / "local.txt").write_text("mine", encoding="utf-8")
    again = github_clone.clone_repository("octo/notes", None)
    assert again.created is False
    assert again.folder == first.folder
    assert (first.folder / "local.txt").exists()


def test_a_folder_that_holds_something_else_is_left_alone(upstream: Path, tmp_path: Path) -> None:
    taken = tmp_path / "home" / "notes"
    taken.mkdir(parents=True)
    (taken / "diary.txt").write_text("private", encoding="utf-8")
    cloned = github_clone.clone_repository("octo/notes", None)
    assert cloned.folder == tmp_path / "home" / "notes-octo"
    assert (taken / "diary.txt").read_text(encoding="utf-8") == "private"
    # Both names taken by other things: nothing is cloned and nothing is touched.
    _git(cloned.folder, "remote", "set-url", "origin", "https://github.com/else/where.git")
    with pytest.raises(GitError) as exc:
        github_clone.clone_repository("octo/notes", None)
    assert exc.value.code == "exists"


@pytest.mark.parametrize("repo", ["notes", "octo/..", "octo/.", "../octo/notes", "octo/a b", ""])
def test_only_an_owner_and_a_name_are_accepted(repo: str, tmp_path: Path) -> None:
    with pytest.raises(GitError) as exc:
        github_clone.clone_repository(repo, None)
    assert exc.value.code == "bad_repo"
    assert not (tmp_path / "home").exists()


def test_a_failed_clone_leaves_no_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(github_clone, "_clone_url", lambda repo: str(tmp_path / "missing"))
    with pytest.raises(GitError) as exc:
        github_clone.clone_repository("octo/notes", None)
    assert exc.value.code == "clone_failed"
    assert "octo/notes" in str(exc.value)
    assert not (tmp_path / "home" / "notes").exists()


def test_the_login_travels_in_the_environment_and_a_refusal_retries_without_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], dict[str, str]]] = []

    def fake_run(args: list[str], cwd: Path, *, timeout: float, extra_env: dict[str, str]):
        calls.append((args, extra_env))
        refused = bool(extra_env)
        return SimpleNamespace(returncode=1 if refused else 0, stdout="", stderr="fatal: refused")

    monkeypatch.setattr(git_ops, "_run", fake_run)
    login = "ghx-login-value"
    cred = github_link.Credential(login, "app")
    cloned = github_clone.clone_repository("octo/notes", cred)
    assert cloned.created is True
    assert len(calls) == 2
    first_args, first_env = calls[0]
    assert login not in " ".join(first_args)
    assert first_env["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraheader"
    assert first_env["GIT_CONFIG_VALUE_0"].startswith("AUTHORIZATION: basic ")
    assert login not in first_env["GIT_CONFIG_VALUE_0"]
    assert first_args[-2] == "https://github.com/octo/notes.git"
    assert calls[1][1] == {}


def test_connected_folders_name_their_github_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    on_github = tmp_path / "app"
    on_github.mkdir()
    _git(on_github, "init", "-q", "-b", "main")
    _git(on_github, "remote", "add", "origin", "git@github.com:octo/app.git")
    plain = tmp_path / "plain"
    plain.mkdir()
    projects = [
        SimpleNamespace(id="p1", path=str(on_github), scratch=False),
        SimpleNamespace(id="p2", path=str(plain), scratch=False),
        SimpleNamespace(id="p3", path=str(tmp_path / "gone"), scratch=False),
        SimpleNamespace(id="p4", path=str(on_github), scratch=True),
    ]
    monkeypatch.setattr(library, "list_projects", lambda include_archived=False: projects)
    monkeypatch.setattr(github_link, "bound_repository", lambda folder: "")
    assert github_clone.linked_repositories() == {"p1": "octo/app"}


def test_the_clone_route_answers_with_the_folder_or_the_reason(
    upstream: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi import HTTPException

    from dodaios.ui.web import agentic_ide_git_routes as routes

    monkeypatch.setattr(github_link, "credential", lambda: None)
    body = routes.clone_github_repository(routes.CloneRequest(repo="octo/notes"))
    assert body["created"] is True and Path(body["folder"]).is_dir()
    with pytest.raises(HTTPException) as exc:
        routes.clone_github_repository(routes.CloneRequest(repo="octo/.."))
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "bad_repo"
