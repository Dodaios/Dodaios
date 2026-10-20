"""Bring back what the editor's explorer deleted, for its Undo.

A delete still goes to the system trash (or is permanent where there is none),
but the trash has no portable "put it back" call. So before the explorer
deletes an entry, a copy of it is kept here under a random token; Undo moves
that copy back to where the entry was.

Only small entries are kept (a deleted ``node_modules`` is restored from the
trash by hand, as before). Copies live in the per-user data directory, one
folder per IDE instance, and are dropped after a day or when more than
:data:`MAX_KEPT` are held.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import time
from pathlib import Path

from loguru import logger

from dodaios.core.instance import current_instance
from dodaios.core.paths import user_data_dir

from .file_editing import EditError, _resolve_entry

__all__ = ["MAX_KEPT", "MAX_UNDO_BYTES", "MAX_UNDO_FILES", "discard", "keep", "restore"]

#: Entries larger than this are not kept; Undo then points to the trash.
MAX_UNDO_BYTES = 64 * 1024 * 1024
MAX_UNDO_FILES = 2000
#: How many deletes Undo can reach back, across workspaces.
MAX_KEPT = 30
MAX_AGE_S = 24 * 3600

_TOKEN = re.compile(r"^[0-9a-f]{24}$")
_ENTRY = "entry"
_META = "meta.json"


def _store_root() -> Path:
    return user_data_dir() / f"explorer-undo{current_instance().state_file_suffix}"


def _root_key(root: str | os.PathLike[str]) -> str:
    return os.path.normcase(os.path.realpath(os.fspath(root)))


def _small_enough(target: Path) -> bool:
    """True when ``target`` fits the size and file-count limits."""
    if target.is_symlink() or target.is_file():
        try:
            return target.lstat().st_size <= MAX_UNDO_BYTES
        except OSError:  # unreadable size: not kept, the delete still goes to the trash
            return False
    total = 0
    files = 0
    for current, dirs, names in os.walk(target, followlinks=False):
        files += len(names) + len(dirs)
        if files > MAX_UNDO_FILES:
            return False
        for name in names:
            try:
                total += os.lstat(os.path.join(current, name)).st_size
            except OSError:  # unreadable size: not kept, the delete still goes to the trash
                return False
            if total > MAX_UNDO_BYTES:
                return False
    return True


def _prune(store: Path) -> None:
    try:
        held = [entry for entry in store.iterdir() if entry.is_dir()]
    except OSError:  # no store yet, or unreadable: nothing to prune now, the next keep tries again
        return
    now = time.time()

    def age(entry: Path) -> float:
        try:
            return entry.stat().st_mtime
        except OSError:  # vanished meanwhile: oldest, so it is pruned first
            return 0.0

    held.sort(key=age, reverse=True)
    for index, entry in enumerate(held):
        if index >= MAX_KEPT or now - age(entry) > MAX_AGE_S:
            shutil.rmtree(entry, ignore_errors=True)


def keep(root: str | os.PathLike[str], path: str) -> str | None:
    """Copy the entry at ``path`` aside before a delete; returns its token.

    None when it is too large to keep or the copy failed: the delete still
    goes ahead, it just cannot be undone from the editor.
    """
    relative, target = _resolve_entry(root, path)
    if not (target.is_symlink() or target.exists()):
        raise EditError("That file or folder no longer exists.")
    if not _small_enough(target):
        return None
    store = _store_root()
    token = secrets.token_hex(12)
    folder = store / token
    try:
        folder.mkdir(parents=True)
        copy = folder / _ENTRY
        if target.is_dir() and not target.is_symlink():
            shutil.copytree(target, copy, symlinks=True)
        else:
            shutil.copy2(target, copy, follow_symlinks=False)
        meta = {"root": _root_key(root), "path": relative, "created": time.time()}
        (folder / _META).write_text(json.dumps(meta), encoding="utf-8")
    except OSError as exc:
        logger.info("Explorer undo: could not keep a copy of {}: {}", target.name, exc)
        shutil.rmtree(folder, ignore_errors=True)
        return None
    _prune(store)
    return token


def discard(token: str | None) -> None:
    """Drop a kept copy (its delete failed, so there is nothing to undo)."""
    if token and _TOKEN.match(token):
        shutil.rmtree(_store_root() / token, ignore_errors=True)


def restore(root: str | os.PathLike[str], token: str) -> str:
    """Put a kept entry back where it was deleted; returns its relative path."""
    if not _TOKEN.match(token):
        raise EditError("That delete can no longer be undone.")
    folder = _store_root() / token
    try:
        meta = json.loads((folder / _META).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EditError("That delete can no longer be undone.") from exc
    if meta.get("root") != _root_key(root) or not isinstance(meta.get("path"), str):
        raise EditError("That delete belongs to another workspace.")
    relative, target = _resolve_entry(root, meta["path"])
    if target.exists() or target.is_symlink():
        raise EditError("Something with that name already exists.")
    if not target.parent.is_dir():
        raise EditError("The folder it was in no longer exists.")
    copy = folder / _ENTRY
    if not (copy.exists() or copy.is_symlink()):
        raise EditError("That delete can no longer be undone.")
    # A move within one disk; a copy when the data folder is on another.
    shutil.move(str(copy), str(target))
    shutil.rmtree(folder, ignore_errors=True)
    return relative
