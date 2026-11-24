"""Read a thread's folder through the workspace routes when no workspace has it open.

The IDE's side panel (Folder, Changes, Search, Git and the code editor) talks
to routes keyed by a workspace id, and a workspace id names an OPEN grid
workspace. In the thread layout the panel follows the open thread instead, and
a thread's project may have no open workspace at all: the person chats in a
project they never opened in the grid. Its folder still has to be readable.

A folder view id stands in for the workspace there: ``folder:`` plus the
folder path in URL-safe base64. It is accepted only for a folder a thread may
read (``thread_folders.allowed_thread_folder``: inside a connected project or
an open workspace) or a git worktree of a connected project's repository,
which an agent may have made anywhere on the disk. It never reaches a folder
the person did not connect.
"""

from __future__ import annotations

import base64
import binascii
import os
import threading
import time
from pathlib import Path

from . import git_ops, library
from .thread_folders import allowed_thread_folder

PREFIX = "folder:"

#: Worktree answers per folder, kept a while: the panel asks on every poll and
#: the check runs git once per connected project.
_WORKTREE_TTL_S = 60.0
_worktree_answers: dict[str, tuple[float, bool]] = {}
_lock = threading.Lock()


def view_id(folder: str | Path) -> str:
    """The folder view id for ``folder``."""
    encoded = base64.urlsafe_b64encode(str(folder).encode("utf-8")).decode("ascii")
    return PREFIX + encoded.rstrip("=")


def is_view_id(workspace_id: str | None) -> bool:
    return bool(workspace_id) and str(workspace_id).startswith(PREFIX)


def folder_of(workspace_id: str) -> Path | None:
    """The folder a folder view id names, or None when it is not one or not allowed.

    Blocking (it stats the folder, reads the project list and may run git):
    call it off the event loop.
    """
    if not is_view_id(workspace_id):
        return None
    body = workspace_id[len(PREFIX) :]
    try:
        text = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)).decode("utf-8")
    except (binascii.Error, ValueError):
        return None  # a malformed id names no folder; the route answers 404
    if not text or "\x00" in text:
        return None
    allowed = allowed_thread_folder(text)
    if allowed is not None:
        return allowed
    folder = Path(text)
    return folder if folder.is_absolute() and _worktree_of_a_project(folder) else None


def _worktree_of_a_project(folder: Path) -> bool:
    """Is ``folder`` a checkout of a connected project's repository? Runs git."""
    key = os.path.normcase(str(folder))
    with _lock:
        cached = _worktree_answers.get(key)
    if cached is not None and time.monotonic() - cached[0] < _WORKTREE_TTL_S:
        return cached[1]
    answer = git_ops.repo_root(folder) is not None and any(
        git_ops.same_repository(folder, project.path)
        for project in library.list_projects(include_archived=True)
        if project.path
    )
    with _lock:
        if len(_worktree_answers) > 256:
            _worktree_answers.clear()
        _worktree_answers[key] = (time.monotonic(), answer)
    return answer
