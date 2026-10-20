"""Is the person away from the computer? Coding runs wait until they are.

Two readings, both must agree:

* the operating system's input idle time (keyboard and mouse), where it can be
  read without a dependency:

  - Windows: ``GetLastInputInfo``;
  - macOS: ``ioreg``'s ``HIDIdleTime`` of the ``IOHIDSystem`` (nanoseconds);
  - Linux, the first that answers: GNOME's idle monitor over D-Bus (``gdbus``
    or ``dbus-send``; X11 and Wayland), ``xprintidle`` (X11 only: under
    Wayland it sees only X clients, so it is not asked there), the
    freedesktop screen saver's active time (KDE and others: idle at least
    that long), and systemd-logind's ``IdleHint``/``IdleSinceHint``;

* the Agentic IDE: no key typed into a terminal pane lately.

A platform where no OS reading answers counts as idle only when the IDE shows
no input, which is the honest best a headless machine allows. A reading that
can only say "idle since" (screen saver, logind) answers nothing while the
person is active rather than "zero": desktops that never set it would
otherwise block every build.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from typing import Final

from loguru import logger

from dodaios.core.process_utils import NO_WINDOW_CREATIONFLAGS

#: No input for this long counts as away.
IDLE_AFTER_S: Final[float] = 15 * 60.0
_NUMBER: Final[re.Pattern[str]] = re.compile(r"(?<![A-Za-z0-9_.=:])(\d+)(?![A-Za-z0-9_.])")
_MUTTER: Final[tuple[str, str, str]] = (
    "org.gnome.Mutter.IdleMonitor",
    "/org/gnome/Mutter/IdleMonitor/Core",
    "org.gnome.Mutter.IdleMonitor.GetIdletime",
)
_SAVER_DEST: Final[str] = "org.freedesktop.ScreenSaver"
_SAVER_PATH: Final[str] = "/org/freedesktop/ScreenSaver"

Run = Callable[[list[str]], "str | None"]


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


def _output(argv: list[str]) -> str | None:
    """The command's stdout, or None when it is missing, fails or hangs."""
    if not shutil.which(argv[0]):
        return None
    try:
        done = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            creationflags=NO_WINDOW_CREATIONFLAGS,
        )
    except (OSError, subprocess.TimeoutExpired):  # unknown idle time: the next reading decides
        return None
    return done.stdout if done.returncode == 0 else None


def _first_number(text: str | None) -> int | None:
    """The first standalone integer (``(uint64 12345,)`` -> 12345, never the ``64``)."""
    match = _NUMBER.search(text or "")
    return int(match.group(1)) if match else None


def _mac_idle_s(run: Run) -> float | None:
    out = run(["ioreg", "-c", "IOHIDSystem", "-d", "4", "-k", "HIDIdleTime"])
    for line in (out or "").splitlines():
        if "HIDIdleTime" in line:
            # Only this line: the tree lines around it carry other numbers ("busy 0 (0 ms)").
            value = _first_number(line.split("=", 1)[-1])
            return value / 1e9 if value is not None else None
    return None


def _dbus(run: Run, dest: str, path: str, method: str) -> str | None:
    out = run(
        ["gdbus", "call", "--session", "--dest", dest, "--object-path", path, "--method", method]
    )
    if out is None:
        out = run(["dbus-send", "--session", "--print-reply", f"--dest={dest}", path, method])
        if out is not None:
            # Its first line is the reply header ("method return time=... serial=7").
            out = "\n".join(
                line for line in out.splitlines() if not line.startswith("method return")
            )
    return out


def _wayland(env: dict[str, str]) -> bool:
    return bool(env.get("WAYLAND_DISPLAY")) or env.get("XDG_SESSION_TYPE", "").lower() == "wayland"


def _screensaver_idle_s(run: Run) -> float | None:
    active = _dbus(run, _SAVER_DEST, _SAVER_PATH, f"{_SAVER_DEST}.GetActive")
    if active is None or "true" not in active.lower():
        return None
    seconds = _first_number(_dbus(run, _SAVER_DEST, _SAVER_PATH, f"{_SAVER_DEST}.GetActiveTime"))
    # The screen saver came on after some idle time already: at least this long.
    return float(seconds) if seconds is not None else None


def _logind_idle_s(run: Run, env: dict[str, str], now: float) -> float | None:
    session = env.get("XDG_SESSION_ID") or "self"
    out = run(["loginctl", "show-session", session, "-p", "IdleHint", "-p", "IdleSinceHint"])
    if not out:
        return None
    props = dict(line.strip().split("=", 1) for line in out.splitlines() if "=" in line)
    if props.get("IdleHint", "").strip().lower() != "yes":
        return None  # "no" is also all a desktop that never sets the hint says
    since_us = _first_number(props.get("IdleSinceHint"))
    if not since_us:
        return None
    return max(0.0, now - since_us / 1e6)


def _linux_idle_s(run: Run, env: dict[str, str], now: float) -> float | None:
    millis = _first_number(_dbus(run, *_MUTTER))
    if millis is not None:
        return millis / 1000.0
    if env.get("DISPLAY") and not _wayland(env):
        millis = _first_number(run(["xprintidle"]))
        if millis is not None:
            return millis / 1000.0
    saver = _screensaver_idle_s(run)
    if saver is not None:
        return saver
    return _logind_idle_s(run, env, now)


def os_idle_s(
    *,
    platform: str | None = None,
    run: Run | None = None,
    env: dict[str, str] | None = None,
    now: float | None = None,
) -> float | None:
    """Seconds since the last keyboard or mouse input, or None when unknown.

    The keyword arguments are test seams (faked command output).
    """
    platform = platform or sys.platform
    run = run or _output
    try:
        if platform == "win32":
            return _windows_idle_s()
        if platform == "darwin":
            return _mac_idle_s(run)
        if platform.startswith("linux") or "bsd" in platform:
            return _linux_idle_s(
                run,
                dict(os.environ) if env is None else env,
                time.time() if now is None else now,
            )
    except Exception:  # noqa: BLE001 - an unreadable clock is an unknown, not an error
        logger.opt(exception=True).debug("self-build code: idle time unreadable")
    return None


def ide_idle_s(now: float | None = None) -> float | None:
    """Seconds since the person typed into a pane's terminal in the app, None if never."""
    from dodaios.core import presence

    return presence.idle_s(sources=[presence.PANE], now=now)


def dodaios_idle_s(now: float | None = None) -> float | None:
    """Seconds since the person's last turn in Dodaios (0 during a call), None if never."""
    from dodaios.core import presence

    return presence.idle_s(sources=[presence.TURN], now=now)


def person_idle(after_s: float = IDLE_AFTER_S) -> bool:
    """No input from the person for ``after_s``: OS input, a turn in Dodaios, pane typing.

    A coding run is heavy, so it waits until the person is not working at all.
    A prompt Jarvis or an agent wrote into a pane is not the person: the
    pane's ``last_input_at`` stamps those too, so it is not read here; the
    pane reading is the person's own typing in the app (``core/presence.py``).
    """
    for reading in (os_idle_s(), dodaios_idle_s(), ide_idle_s()):
        if reading is not None and reading < after_s:
            return False
    return True
