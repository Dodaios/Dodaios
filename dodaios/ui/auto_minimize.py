"""Minimize the main desktop window after focus moves to another app.

The floating assistant bar remains a separate surface. This monitor only
minimizes the one main pywebview window; owned dialogs and other windows from
the same process do not trigger it.
"""

from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
from collections.abc import Callable
from ctypes import wintypes

_POLL_INTERVAL_S = 0.2
_FOCUS_GRACE_S = 0.45
_SW_MINIMIZE = 6
_GA_ROOTOWNER = 3


class AutoMinimizeOnFocusLoss:
    """Watch the foreground window and minimize the assistant after app switch."""

    def __init__(
        self,
        window_title: str,
        *,
        on_minimized: Callable[[], None],
        enabled: Callable[[], bool],
        poll_interval_s: float = _POLL_INTERVAL_S,
        grace_s: float = _FOCUS_GRACE_S,
    ) -> None:
        self._window_title = window_title
        self._on_minimized = on_minimized
        self._enabled = enabled
        self._poll_interval_s = max(0.05, float(poll_interval_s))
        self._grace_s = max(0.0, float(grace_s))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        """Start one daemon monitor, or leave an existing monitor running."""
        if sys.platform != "win32":
            return
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="desktop-auto-minimize",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        """Stop the monitor without waiting on a native GUI call."""
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(0.5, self._poll_interval_s * 2))

    def _run(self) -> None:
        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
            user32.FindWindowW.restype = wintypes.HWND
            user32.GetForegroundWindow.restype = wintypes.HWND
            user32.GetWindowThreadProcessId.argtypes = [
                wintypes.HWND,
                ctypes.POINTER(wintypes.DWORD),
            ]
            user32.GetWindowThreadProcessId.restype = wintypes.DWORD
            user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
            user32.GetAncestor.restype = wintypes.HWND
            user32.IsWindowVisible.argtypes = [wintypes.HWND]
            user32.IsWindowVisible.restype = wintypes.BOOL
            user32.IsIconic.argtypes = [wintypes.HWND]
            user32.IsIconic.restype = wintypes.BOOL
            user32.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]
            user32.ShowWindowAsync.restype = wintypes.BOOL
        except Exception:  # noqa: BLE001 - this optional behavior must not affect startup
            return

        process_id = os.getpid()
        was_foreground = False
        away_since: float | None = None
        last_hwnd = 0

        while not self._stop.wait(self._poll_interval_s):
            try:
                if not self._enabled():
                    away_since = None
                    was_foreground = False
                    continue

                hwnd = int(user32.FindWindowW(None, self._window_title) or 0)
                if not hwnd:
                    away_since = None
                    self._stop.wait(self._poll_interval_s)
                    continue
                if hwnd != last_hwnd:
                    last_hwnd = hwnd
                    was_foreground = False
                    away_since = None

                if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
                    away_since = None
                    continue

                foreground = int(user32.GetForegroundWindow() or 0)
                if not foreground:
                    away_since = None
                    continue

                foreground_pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(foreground, ctypes.byref(foreground_pid))
                root_owner = int(user32.GetAncestor(foreground, _GA_ROOTOWNER) or foreground)

                if foreground_pid.value == process_id or root_owner == hwnd:
                    was_foreground = True
                    away_since = None
                    continue
                if not was_foreground:
                    continue

                now = time.monotonic()
                if away_since is None:
                    away_since = now
                    continue
                if now - away_since < self._grace_s:
                    continue

                # The short grace period prevents transient focus changes from
                # hiding the assistant while an owned dialog is being opened.
                # ShowWindowAsync returns the window's *previous visibility*,
                # not an operation-success flag. Confirm the resulting state
                # instead so a valid minimize is never skipped on a false return.
                user32.ShowWindowAsync(hwnd, _SW_MINIMIZE)
                if user32.IsIconic(hwnd):
                    was_foreground = False
                    away_since = None
                    self._on_minimized()
            except Exception:  # noqa: BLE001 - a focus transition must not kill the monitor
                away_since = None
                self._stop.wait(self._poll_interval_s)
