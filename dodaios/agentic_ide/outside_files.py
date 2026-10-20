"""Files outside a workspace that the person opened in its code editor.

The editor works on workspace-relative paths, and everything a terminal prints
is confined to the workspace (coding-CLI output is untrusted). A Ctrl+click on
a file outside it, such as a note an agent saved to Downloads, is still a
deliberate request to read that one file. This module keeps a short list of
such files per workspace folder:

* A file joins the list only through :func:`grant`, which the desktop app
  calls for a modifier-click on the computer running Dodaios.
* The editor then addresses it by its absolute POSIX path
  (``C:/Users/me/Downloads/notes.md``); a workspace-relative path never looks
  like that, so the two cannot be confused.
* Every read and write checks the list again (:func:`granted_target`), so a
  crafted absolute path reaches nothing that was not clicked.

The list lives next to the editor's tab state, so restored tabs keep working
after a restart.
"""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath

from .editor_backups import folder_state_dir, read_json, write_json
from .file_editing import EditError, is_outside_key

__all__ = [
    "MAX_GRANTS",
    "grant",
    "granted_target",
    "is_outside_key",
    "key_of",
]

#: Older entries drop off; a tab for one of them simply fails to load.
MAX_GRANTS = 200


def key_of(target: Path) -> str:
    """The editor's name for an absolute file: its path with forward slashes."""
    return str(target).replace("\\", "/")


def _same(path: Path) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


def _store(folder: str | os.PathLike[str]) -> Path:
    return folder_state_dir(folder) / "outside-files.json"


def _load(folder: str | os.PathLike[str]) -> list[str]:
    doc = read_json(_store(folder)) or {}
    return [item for item in doc.get("paths", []) if isinstance(item, str)]


def _refuse_git(target: Path) -> None:
    if any(part.rstrip(". ").lower() == ".git" for part in target.parts):
        raise EditError("Files inside .git cannot be edited here.")


def grant(folder: str | os.PathLike[str], target: Path) -> str:
    """Let the editor of one workspace open ``target``; returns its editor key.

    ``target`` must already be resolved (symlinks followed) and be a file.
    """
    if not target.is_absolute() or not target.is_file():
        raise EditError("That file does not exist.")
    _refuse_git(target)
    key = key_of(target)
    paths = [item for item in _load(folder) if _same(Path(item)) != _same(target)]
    paths.append(key)
    write_json(_store(folder), {"paths": paths[-MAX_GRANTS:]})
    return key


def granted_target(folder: str | os.PathLike[str], path: str) -> Path:
    """The file an absolute editor path names, if it was granted; else EditError.

    The file need not exist any more: a deleted file reports no version, and
    the editor may write it back.
    """
    value = (path or "").strip().replace("\\", "/")
    if not is_outside_key(value) or any(ord(char) < 32 for char in value):
        raise EditError("That file was not opened from a terminal link.")
    if any(part == ".." for part in PurePosixPath(value).parts):
        raise EditError("That file was not opened from a terminal link.")
    target = Path(value)
    wanted = _same(target)
    if not any(_same(Path(item)) == wanted for item in _load(folder)):
        raise EditError("That file was not opened from a terminal link.")
    _refuse_git(target)
    return target
