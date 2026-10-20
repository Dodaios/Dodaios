"""Keep the code editor's open tabs and unsaved text across an app restart.

Closing or restarting the desktop app must not cost the user typed code. The
editor therefore mirrors two things here, per workspace folder:

* the open tabs (path, edit/diff mode, preview flag) and the active one, and
* a backup of every buffer with unsaved edits, together with the version of
  the file the edits were made on.

On the next start the editor reopens the tabs and lays each backup over the
file it belongs to. If the file changed on disk meanwhile, the restored buffer
shows the usual conflict bar instead of overwriting anything.

Storage is the per-user data directory (one folder per IDE instance, so the
dev app never restores the live app's buffers), keyed by a hash of the
workspace folder: a workspace id may change between runs, its folder does not.
Every write is atomic; a backup is one small file per edited path, so typing
in one file never rewrites another's backup.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from loguru import logger

from dodaios.core.instance import current_instance
from dodaios.core.paths import user_data_dir

from .file_editing import MAX_EDITABLE_BYTES, EditError, _normalise_relative, is_outside_key

__all__ = [
    "MAX_TABS",
    "drop_backup",
    "folder_state_dir",
    "load_state",
    "read_json",
    "save_backup",
    "save_tabs",
    "write_json",
]

#: More open tabs than this are not worth restoring; the oldest are dropped.
MAX_TABS = 60
#: A backup nobody restored for this long belongs to a file long gone.
MAX_BACKUP_AGE_S = 30 * 24 * 3600
#: Backups restored per workspace at most; the newest win.
MAX_BACKUPS = 100
_MODES = ("edit", "diff")


def _store_root() -> Path:
    return user_data_dir() / f"editor-backups{current_instance().state_file_suffix}"


def folder_state_dir(folder: str | os.PathLike[str]) -> Path:
    real = os.path.normcase(os.path.realpath(os.fspath(folder)))
    return _store_root() / hashlib.sha256(real.encode("utf-8")).hexdigest()[:24]


def _backup_file(folder: str | os.PathLike[str], path: str) -> Path:
    digest = hashlib.sha256(path.encode("utf-8")).hexdigest()[:24]
    return folder_state_dir(folder) / "backups" / f"{digest}.json"


def write_json(target: Path, payload: dict[str, Any]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(prefix=".", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False)
        os.replace(temp_name, target)
    finally:
        if os.path.exists(temp_name):
            try:
                os.unlink(temp_name)
            except OSError as exc:
                logger.warning("Editor backup: could not remove temp file: {}", exc)


def read_json(source: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError:  # no backup yet is the normal case
        return None
    except (OSError, ValueError) as exc:
        # A damaged backup must not keep the editor from starting.
        logger.warning("Editor backup: ignoring unreadable {}: {}", source.name, exc)
        return None
    return data if isinstance(data, dict) else None


def _editor_path(path: str) -> str:
    """A tab's path: workspace-relative, or absolute for a file opened from outside."""
    value = (path or "").strip()
    if is_outside_key(value):
        if any(ord(char) < 32 for char in value):
            raise EditError("That is not a valid file name here.")
        return value.replace("\\", "/")
    return _normalise_relative(value)


def save_tabs(
    folder: str | os.PathLike[str], tabs: list[dict[str, Any]], active: str | None
) -> None:
    """Remember the open tabs of one workspace, in order."""
    clean: list[dict[str, Any]] = []
    for tab in tabs[-MAX_TABS:]:
        try:
            path = _editor_path(str(tab.get("path", "")))
        except EditError:
            continue  # one unusable tab must not cost the others their place
        mode = tab.get("mode") if tab.get("mode") in _MODES else "edit"
        clean.append({"path": path, "mode": mode, "preview": bool(tab.get("preview"))})
    try:
        active_path = _editor_path(active) if active else None
    except EditError:  # an unusable active tab just leaves none active
        active_path = None
    write_json(folder_state_dir(folder) / "tabs.json", {"tabs": clean, "active": active_path})


def save_backup(
    folder: str | os.PathLike[str],
    path: str,
    text: str,
    *,
    base_version: str | None,
    encoding: str,
) -> None:
    """Keep the unsaved text of one file until it is saved or discarded."""
    relative = _editor_path(path)
    if len(text.encode("utf-8")) > MAX_EDITABLE_BYTES:
        raise EditError("That buffer is too large to back up.")
    write_json(
        _backup_file(folder, relative),
        {
            "path": relative,
            "text": text,
            "base_version": base_version,
            "encoding": encoding,
            "saved_at": time.time(),
        },
    )


def drop_backup(folder: str | os.PathLike[str], path: str) -> None:
    """Forget a backup: the buffer was saved, reverted or discarded."""
    target = _backup_file(folder, _editor_path(path))
    try:
        target.unlink()
    except FileNotFoundError:  # already gone is what forgetting wants
        return


def load_state(folder: str | os.PathLike[str]) -> dict[str, Any]:
    """The tabs and backups to restore for one workspace folder."""
    root = folder_state_dir(folder)
    tabs_doc = read_json(root / "tabs.json") or {}
    tabs = [tab for tab in tabs_doc.get("tabs", []) if isinstance(tab, dict)]
    backups: list[dict[str, Any]] = []
    backup_dir = root / "backups"
    if backup_dir.is_dir():
        cutoff = time.time() - MAX_BACKUP_AGE_S
        for entry in sorted(backup_dir.glob("*.json")):
            doc = read_json(entry)
            if not (doc and isinstance(doc.get("path"), str) and isinstance(doc.get("text"), str)):
                continue
            if float(doc.get("saved_at") or 0) < cutoff:
                try:
                    entry.unlink()
                except OSError as exc:
                    logger.warning("Editor backup: could not prune {}: {}", entry.name, exc)
                continue
            backups.append(doc)
    backups.sort(key=lambda doc: float(doc.get("saved_at") or 0), reverse=True)
    return {"tabs": tabs, "active": tabs_doc.get("active"), "backups": backups[:MAX_BACKUPS]}
