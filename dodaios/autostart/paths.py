"""Does a path stored in an autostart entry name the place the app would write now?

An entry stores absolute paths: the interpreter, the working folder. When the
install folder moves to its current name, a link stays behind at the earlier
path, so an entry written before the move still starts the app, through that
link. Its text no longer matches, though, and an entry judged stale is
rewritten; on Windows the boot repair cannot rewrite a logon task without an
elevation prompt and adds a startup shortcut instead, and the app then starts
twice at login. So a path counts as the same when its text matches (ignoring
letter case and separators on Windows) or when it is the very same file or
folder on disk. A path that does not exist matches only by its text.
"""

from __future__ import annotations

import ntpath
import os


def _windows_text(path: str) -> str:
    return ntpath.normcase(ntpath.normpath(path))


def same_path(stored: str | None, expected: str | None, *, windows: bool = False) -> bool:
    """True when ``stored`` and ``expected`` name one place.

    ``windows`` compares the text the way Windows resolves it: case-blind,
    either separator. Empty values match only each other.
    """
    stored = stored or ""
    expected = expected or ""
    if not stored or not expected:
        return stored == expected
    if windows:
        if _windows_text(stored) == _windows_text(expected):
            return True
    elif stored == expected:
        return True
    try:
        return os.path.samefile(stored, expected)
    except (OSError, ValueError):
        # One side is missing or unreadable: only the text could have matched.
        return False


__all__ = ["same_path"]
