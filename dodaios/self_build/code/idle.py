"""Is the person away from the computer? Coding runs wait until they are.

Two readings, both must agree:

* the operating system's input idle time (keyboard and mouse), where it can be
  read without a dependency: Windows (``GetLastInputInfo``), macOS
  (``ioreg``'s ``HIDIdleTime``), Linux with ``xprintidle`` on PATH;
* the Agentic IDE: no key typed into a terminal pane lately.

A platform where neither can be read counts as idle only when the IDE shows
no input, which is the honest best a headless machine allows.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from typing import Final

from loguru import logger

from dodaios.core.process_utils import NO_WINDOW_CREATIONFLAGS

#: No input for this long counts as away.
IDLE_AFTER_S: Final[float] = 15 * 60.0


def _windows_idle_s() -> float | None:
    import ctypes
    from ctypes import wintypes

    class LastInput(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    info = LastInput()
    info.cbSize = ctypes.sizeof(LastInput)
    if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):  # type: ignore[attr-defined]
        return None
    ticks = ctypes.windll.kernel32.GetTickCount() & 0xFFFFFFFF  # type: ignore[attr-defined]
    return ((ticks - info.dwTime) & 0xFFFFFFFF) / 1000.0


def _command_idle_s(argv: list[str], *, scale: float) -> float | None:
    try:
        done = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            creationflags=NO_WINDOW_CREATIONFLAGS,
        )
    except (OSError, subprocess.TimeoutExpired):  # unknown idle time: the IDE reading decides
        return None
    if done.returncode != 0:
        return None
    for token in done.stdout.replace('"', " ").replace("=", " ").split():
        if token.isdigit():
            return int(token) / scale
    return None


def os_idle_s() -> float | None:
    """Seconds since the last keyboard or mouse input, or None when unknown."""
    try:
        if sys.platform == "win32":
            return _windows_idle_s()
        if sys.platform == "darwin":
            argv = ["ioreg", "-c", "IOHIDSystem", "-d", "4", "-k", "HIDIdleTime"]
            return _command_idle_s(argv, scale=1e9)
        if shutil.which("xprintidle"):
            return _command_idle_s(["xprintidle"], scale=1000.0)
    except Exception:  # noqa: BLE001 - an unreadable clock is an unknown, not an error
        logger.opt(exception=True).debug("self-build code: idle time unreadable")
    return None


def ide_idle_s(now: float | None = None) -> float | None:
    """Seconds since a key was typed into any Agentic IDE pane, None without panes."""
    try:
        from dodaios.agentic_ide.session import get_registry

        stamps = [
            float(term.last_input_at)
            for session in get_registry().sessions
            for term in getattr(session, "terminals", []) or []
            if getattr(term, "last_input_at", None)
        ]
    except Exception:  # noqa: BLE001 - no registry (tests, CLI) means no pane input
        logger.opt(exception=True).debug("self-build code: pane activity unreadable")
        return None
    if not stamps:
        return None
    return (now if now is not None else time.time()) - max(stamps)


def person_idle(after_s: float = IDLE_AFTER_S) -> bool:
    for reading in (os_idle_s(), ide_idle_s()):
        if reading is not None and reading < after_s:
            return False
    return True
