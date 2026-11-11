"""Bring a GitHub repository onto this computer for a thread.

The thread composer lists the person's GitHub repositories next to the folders
already connected. A repository that is not on this computer yet is cloned into
``~/Dodaios/<name>``; the caller then connects that folder as a project. A
repository that is already there is reused, never cloned twice or overwritten.
"""

from __future__ import annotations

import base64
import os
import shutil
import stat
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger

from dodaios.agentic_ide import git_ops, github_link
from dodaios.agentic_ide.git_ops import GitError

#: A large repository on a slow line; the person waits on a spinner meanwhile.
CLONE_TIMEOUT_S = 900.0

_locks_guard = threading.Lock()
_locks: dict[str, threading.Lock] = {}


@dataclass(slots=True)
class Cloned:
    folder: Path
    repo: str
    #: False when the repository was already on this computer.
    created: bool

    def to_dict(self) -> dict[str, Any]:
        return {"folder": str(self.folder), "repo": self.repo, "created": self.created}


def clone_home() -> Path:
    """Where cloned repositories live: one folder in the person's home."""
    return Path.home() / "Dodaios"


def _lock_for(repo: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(repo.lower(), threading.Lock())


def _auth_env(token: str) -> dict[str, str]:
    """The GitHub login for this one git call: in the environment, so it is
    neither on the command line nor written into the clone's config."""
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode("ascii")
    return {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
        "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {basic}",
    }


def _clone_url(repo: str) -> str:
    return f"https://github.com/{repo}.git"


def _valid(repo: str) -> str:
    repo = repo.strip()
    name = repo.split("/", 1)[1] if "/" in repo else ""
    # "." and ".." match the name pattern but are not folders of their own.
    if not github_link.REPO_RE.match(repo) or not name.strip("."):
        raise GitError("A repository is written as owner/name.", code="bad_repo")
    return repo


def _destination(repo: str) -> tuple[Path, bool]:
    """(folder, already there). A folder of the same name that holds something
    else is left alone: the owner's name is added, and failing that it stops."""
    owner, name = repo.split("/", 1)
    name = name.removesuffix(".git") or name
    home = clone_home()
    for candidate in (home / name, home / f"{name}-{owner}"):
        if not candidate.exists():
            return candidate, False
        if candidate.is_dir() and github_link.remote_repository(candidate).lower() == repo.lower():
            return candidate, True
    raise GitError(
        f"{home / name} already holds something else. Move it, or connect the folder you want.",
        code="exists",
    )


def _discard(folder: Path) -> None:
    """Remove what a failed clone left behind. Only ever called for a folder
    this module created a moment ago."""

    def _writable(function: Any, path: str, _info: Any) -> None:
        # Git marks its object files read-only; Windows refuses to delete those.
        try:
            os.chmod(path, stat.S_IWRITE)
            function(path)
        except OSError as exc:
            logger.debug("GitHub clone: leftover not removed: {}", type(exc).__name__)

    if folder.exists():
        shutil.rmtree(folder, onerror=_writable)


def clone_repository(repo: str, cred: github_link.Credential | None) -> Cloned:
    """Clone ``owner/name`` into the clone home, or find it there.

    The GitHub connection's login is tried first (private repositories); a
    second try without it covers a public repository and a login that git's
    own credential helper holds.
    """
    repo = _valid(repo)
    if not git_ops.git_available():
        raise GitError("Git is not installed.", code="missing")
    with _lock_for(repo):
        target, existing = _destination(repo)
        if existing:
            return Cloned(folder=target, repo=repo, created=False)
        target.parent.mkdir(parents=True, exist_ok=True)
        url = _clone_url(repo)
        attempts: list[dict[str, str]] = [_auth_env(cred.token)] if cred else []
        attempts.append({})
        reason = ""
        for env in attempts:
            try:
                result = git_ops._run(
                    ["clone", "--", url, str(target)],
                    target.parent,
                    timeout=CLONE_TIMEOUT_S,
                    extra_env=env,
                )
            except GitError:
                _discard(target)
                raise
            if result.returncode == 0:
                logger.info("GitHub clone: {} is now at {}", repo, target)
                return Cloned(folder=target, repo=repo, created=True)
            reason = git_ops._reason(result)
            _discard(target)
        raise GitError(f"Git could not download {repo}: {reason}", code="clone_failed")


def linked_repositories() -> dict[str, str]:
    """``project id → owner/name`` for the connected folders that are a GitHub
    repository: the one picked for the folder, else what its remote points at."""
    from dodaios.agentic_ide.library import list_projects

    linked: dict[str, str] = {}
    for project in list_projects():
        if project.scratch or not project.path:
            continue
        if not Path(project.path).is_dir():
            continue
        repo = github_link.bound_repository(project.path) or github_link.remote_repository(
            project.path
        )
        if repo:
            linked[project.id] = repo
    return linked
