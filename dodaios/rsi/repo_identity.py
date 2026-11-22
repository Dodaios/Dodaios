"""Which repository a folder belongs to, the same for every checkout of it.

A coding thread runs in a project folder or in a worktree of it. Runs in either
must be counted for one repository, so the id is the ``origin`` address without
credentials, protocol or ``.git`` (``github.com/owner/name``). A repository
without a remote is keyed by its main checkout (``path:<folder>``), which every
linked worktree shares. Reads only: a few ``git`` calls, never a network call.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

__all__ = ["RepoRef", "describe", "normalize_remote", "repo_id"]

_SCP_LIKE = re.compile(r"^(?:[\w.\-]+@)?([\w.\-]+):(?!//)(.+)$")
_URL = re.compile(r"^[a-z][a-z0-9+.\-]*://(?:[^@/]+@)?([^/:]+)(?::\d+)?/(.+)$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class RepoRef:
    """Where a run works: the repository, the commit it started from, and whether
    the folder is a linked worktree (a work area of its own)."""

    repo_id: str
    base_sha: str
    isolated: bool


def normalize_remote(url: str) -> str:
    """``host/owner/name`` of a remote address, lower case; ``""`` when unreadable.

    ``git@github.com:Owner/Repo.git``, ``https://token@github.com/Owner/Repo`` and
    ``ssh://git@github.com:22/Owner/Repo.git`` all give ``github.com/owner/repo``.
    """
    text = (url or "").strip()
    if not text:
        return ""
    match = _URL.match(text) or _SCP_LIKE.match(text)
    if match is None:
        return ""
    host, path = match.group(1), match.group(2)
    path = path.strip("/")
    if path.lower().endswith(".git"):
        path = path[:-4]
    # A one-letter "host" is a Windows drive (``C:/repos/x``), a local path, not a remote.
    if len(host) < 2 or not path:
        return ""
    return f"{host}/{path}".lower()


def _git(args: list[str], folder: Path) -> str:
    from dodaios.agentic_ide.git_local import git_out

    try:
        return (git_out(args, folder) or "").strip()
    except Exception:  # noqa: BLE001 - no git or no repository: the folder has no git facts
        return ""


def repo_id(folder: str | Path) -> str:
    """The repository of ``folder``: its origin, else its main checkout's path."""
    path = Path(folder).expanduser()
    remote = normalize_remote(_git(["remote", "get-url", "origin"], path))
    if remote:
        return remote
    from dodaios.agentic_ide.github_link import folder_key

    return "path:" + folder_key(path)


def describe(folder: str | Path) -> RepoRef:
    """The repository, the checked-out commit and the kind of checkout of ``folder``."""
    path = Path(folder).expanduser()
    git_dir = _git(["rev-parse", "--path-format=absolute", "--git-dir"], path)
    common = _git(["rev-parse", "--path-format=absolute", "--git-common-dir"], path)
    return RepoRef(
        repo_id=repo_id(path),
        base_sha=_git(["rev-parse", "HEAD"], path),
        isolated=bool(git_dir and common and git_dir != common),
    )
