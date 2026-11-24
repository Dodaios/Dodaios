"""Read a thread's folder through the workspace routes when no workspace has it open.

The IDE's side panel (Folder, Changes, Search, Git and the code editor) talks
to routes keyed by a workspace id, and a workspace id names an OPEN grid
workspace. In the thread layout the panel follows the open thread instead, and
a thread's project may have no open workspace at all: the person chats in a
project they never opened in the grid. Its folder still has to be readable.

A folder view id stands in for the workspace there: ``folder:`` plus the
folder path in URL-safe base64. It is accepted only for a folder a thread may
read (``thread_folders.allowed_thread_folder``: inside a connected project or
an open workspace), so it never reaches a folder the person did not connect.
"""

from __future__ import annotations

import base64
import binascii
from pathlib import Path

from .thread_folders import allowed_thread_folder

PREFIX = "folder:"


def view_id(folder: str | Path) -> str:
    """The folder view id for ``folder``."""
    encoded = base64.urlsafe_b64encode(str(folder).encode("utf-8")).decode("ascii")
    return PREFIX + encoded.rstrip("=")


def is_view_id(workspace_id: str | None) -> bool:
    return bool(workspace_id) and str(workspace_id).startswith(PREFIX)


def folder_of(workspace_id: str) -> Path | None:
    """The folder a folder view id names, or None when it is not one or not allowed.

    Blocking (it stats the folder and reads the project list): call it off the
    event loop.
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
    return allowed_thread_folder(text)
