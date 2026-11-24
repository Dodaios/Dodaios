"""A scratch folder under the temp directory that belongs to this user only.

On Windows and macOS the temp directory is already per user. On Linux it is
``/tmp``, shared by every account: a fixed folder name there can be read by
others, or prepared by someone else (a folder of theirs, a link) before this
process first writes into it. The folder here carries the user id in its
name, is created owner-only, and is refused when it turns out to belong to
someone else.
"""

from __future__ import annotations

import os
import stat
import tempfile
from pathlib import Path


def private_temp_folder(name: str) -> Path:
    """``<temp>/<name>`` for this user, created and private.

    Raises ``OSError`` when the folder cannot be created or is not this
    user's own directory.
    """
    base = Path(tempfile.gettempdir())
    if os.name == "nt":
        folder = base / name
        folder.mkdir(parents=True, exist_ok=True)
        return folder
    uid = os.getuid()  # type: ignore[attr-defined]
    folder = base / f"{name}-{uid}"
    try:
        folder.mkdir(mode=0o700, parents=True)
    except FileExistsError:  # an existing folder is fine; its ownership is checked below
        pass
    info = os.lstat(folder)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != uid:
        raise OSError(f"{folder} belongs to someone else; nothing is written there")
    if info.st_mode & 0o077:
        os.chmod(folder, 0o700)
    return folder


__all__ = ["private_temp_folder"]
