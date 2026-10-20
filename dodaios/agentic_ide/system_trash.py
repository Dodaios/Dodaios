"""Send a file or folder to the system trash.

``send2trash`` covers the Windows Recycle Bin, the macOS Trash and the
freedesktop trash on Linux. It is an optional import: an install that lacks
it still gets the Recycle Bin on Windows through the shell's own
``SHFileOperationW``. Elsewhere, without the package, there is no trash and
the caller asks before a permanent delete.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

__all__ = ["move_to_trash"]

_FO_DELETE = 3
_FOF_SILENT = 0x0004
_FOF_NOCONFIRMATION = 0x0010
_FOF_ALLOWUNDO = 0x0040
_FOF_NOERRORUI = 0x0400


def _windows_recycle(target: Path) -> bool:
    """Recycle ``target`` with the Windows shell; False when the shell refuses."""
    import ctypes
    from ctypes import wintypes

    class _FileOp(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("wFunc", wintypes.UINT),
            ("pFrom", wintypes.LPCWSTR),
            ("pTo", wintypes.LPCWSTR),
            ("fFlags", ctypes.c_uint16),
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", ctypes.c_void_p),
            ("lpszProgressTitle", wintypes.LPCWSTR),
        ]

    operation = _FileOp()
    operation.wFunc = _FO_DELETE
    # The list of paths ends with an empty one: a second NUL after the last.
    operation.pFrom = os.path.abspath(target) + "\0"
    operation.fFlags = _FOF_ALLOWUNDO | _FOF_NOCONFIRMATION | _FOF_NOERRORUI | _FOF_SILENT
    result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operation))  # type: ignore[attr-defined]
    return result == 0 and not operation.fAnyOperationsAborted and not os.path.lexists(target)


def move_to_trash(target: Path) -> bool:
    """Move ``target`` to the system trash; False when this machine has none.

    Raises OSError when a trash exists but refused the entry.
    """
    try:
        from send2trash import send2trash  # type: ignore[import-not-found]
    except ImportError:
        if sys.platform == "win32":
            if _windows_recycle(target):
                return True
            raise OSError("the Recycle Bin refused it") from None
        return False
    send2trash(str(target))
    return True
