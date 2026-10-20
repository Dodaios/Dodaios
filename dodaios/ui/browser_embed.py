"""Show a real window of the user's own Chrome inside the app (Windows).

The Agentic IDE's browser panel used to be an ``<iframe>``. Most large sites
(GitHub, Google, X, banks) forbid being framed, and a frame never has the
user's sign-ins. This module puts a window of the user's own, already running
browser into the panel instead: same profile, same cookies, same extensions,
the browser's own tabs and address bar.

How it works:

1. The browser is started with ``--profile-directory=<profile> --new-window
   <blank page titled with a one-off token>``. A running browser opens the
   window in its existing process, so it is the user's real session.
2. The window whose title carries the token is taken: its frame is turned into
   a borderless tool window (no taskbar button, no Alt+Tab entry) and it is
   laid exactly over the panel, directly above the app window in the z-order.
3. It stays a top-level window of its own. A child window of another process
   would share the app's input queue and never become the active window: the
   browser then loses clicks and never gets the keyboard (typing landed in the
   app). As its own window it activates and takes focus like any browser.
4. The page reports the panel's rectangle and hides the window with the panel.
   Window events (the app moving, resizing, minimizing or coming to the front;
   the browser being moved or maximized by its own buttons) put it back at
   once; a watchdog timer catches the rest and notices when it is closed.
5. On release (app exit, profile switch, "open in own window") the window gets
   its original styles and placement back, so the browser remembers sensible
   bounds, and is either closed or left as a normal window.

Every native call runs on one thread of the embed's own that pumps messages:
the window events are delivered there.

Limits that come with a foreign window: a popup of the app that overlaps the
panel would sit below the browser (the page hides the browser while one does),
and a link opened from another program can land in this window when it was
the browser's last active one. Links clicked in the app itself go to the panel
on purpose: ``open_tab`` makes its window the active one and opens a tab there.
"""

from __future__ import annotations

import ctypes
import json
import logging
import os
import queue
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Mapping
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar
from urllib.parse import urlparse

from dodaios.ui.browser_profiles import (
    BrowserSpec,
    browser_by_id,
    find_browser_exe,
    handoff_url,
    is_profile_dir,
    new_token,
    panel_to_client_rect,
    read_profiles,
    real_local_app_data,
    safe_start_url,
    user_data_dir,
)

logger = logging.getLogger(__name__)

__all__ = ["ChromeEmbed", "get_embed", "release_host_if_any", "shutdown_embed"]

T = TypeVar("T")

#: How long a launch waits for the browser's new window (a cold start is slow).
LAUNCH_TIMEOUT_S = 25.0
#: How often the watchdog checks the window.
WATCH_INTERVAL_MS = 200
#: How long a caller waits for the native thread before giving up.
CALL_TIMEOUT_S = 5.0
#: How long a visible placement holds without the page confirming it.
LEASE_S = 3.0
#: How long a closed window gets to go away before it is shown again.
CLOSE_GRACE_S = 2.0
#: Where the window in use is remembered, so a restarted app takes it back.
STATE_FILE_NAME = "ide_browser_window.json"

_WINDOW_CLASS = "Chrome_WidgetWin_1"

# winuser.h
GWL_STYLE = -16
GWL_EXSTYLE = -20
WS_CHILD = 0x40000000
WS_POPUP = 0x80000000
WS_VISIBLE = 0x10000000
WS_MINIMIZE = 0x20000000
WS_MAXIMIZE = 0x01000000
WS_CAPTION = 0x00C00000
WS_SYSMENU = 0x00080000
WS_THICKFRAME = 0x00040000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
WS_CLIPSIBLINGS = 0x04000000
WS_CLIPCHILDREN = 0x02000000
WS_EX_APPWINDOW = 0x00040000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
SWP_SHOWWINDOW = 0x0040
SWP_HIDEWINDOW = 0x0080
SWP_ASYNCWINDOWPOS = 0x4000
SW_HIDE = 0
SW_SHOWNORMAL = 1
SW_SHOW = 5
SW_SHOWNA = 8
SW_RESTORE = 9
GW_HWNDNEXT = 2
GW_HWNDPREV = 3
GW_CHILD = 5
WM_CLOSE = 0x0010
WM_TIMER = 0x0113
WM_QUIT = 0x0012
WM_APP_TASK = 0x8000 + 0x51
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
HWND_TOP = 0
EVENT_SYSTEM_FOREGROUND = 0x0003
EVENT_SYSTEM_MINIMIZESTART = 0x0016
EVENT_SYSTEM_MINIMIZEEND = 0x0017
EVENT_OBJECT_SHOW = 0x8002
EVENT_OBJECT_HIDE = 0x8003
EVENT_OBJECT_LOCATIONCHANGE = 0x800B
WINEVENT_OUTOFCONTEXT = 0x0000
OBJID_WINDOW = 0


def _is_windows() -> bool:
    return sys.platform == "win32"


@dataclass
class _Saved:
    """What the browser window looked like before it was taken."""

    style: int
    exstyle: int
    placement: Any


class _Api:
    """user32/kernel32 with real 64-bit signatures (handles are pointers)."""

    def __init__(self) -> None:
        from ctypes import wintypes  # noqa: PLC0415

        self.wt = wintypes
        u = ctypes.WinDLL("user32", use_last_error=True)
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        self.user32, self.kernel32 = u, k
        H, INT, B, UI = wintypes.HWND, ctypes.c_int, wintypes.BOOL, wintypes.UINT
        LP = ctypes.c_ssize_t
        self.ENUMPROC = ctypes.WINFUNCTYPE(B, H, wintypes.LPARAM)
        self.WINEVENTPROC = ctypes.WINFUNCTYPE(
            None, wintypes.HANDLE, wintypes.DWORD, H, wintypes.LONG, wintypes.LONG,
            wintypes.DWORD, wintypes.DWORD,
        )

        class WINDOWPLACEMENT(ctypes.Structure):
            _fields_ = [
                ("length", UI), ("flags", UI), ("showCmd", UI),
                ("ptMinPosition", wintypes.POINT), ("ptMaxPosition", wintypes.POINT),
                ("rcNormalPosition", wintypes.RECT),
            ]

        self.WINDOWPLACEMENT = WINDOWPLACEMENT

        def sig(fn: Any, res: Any, *args: Any) -> None:
            fn.restype = res
            fn.argtypes = list(args)

        sig(u.GetWindowLongPtrW, LP, H, INT)
        sig(u.SetWindowLongPtrW, LP, H, INT, LP)
        sig(u.SetParent, H, H, H)
        sig(u.GetParent, H, H)
        sig(u.GetWindow, H, H, UI)
        sig(u.IsWindow, B, H)
        sig(u.IsWindowVisible, B, H)
        sig(u.IsIconic, B, H)
        sig(u.IsHungAppWindow, B, H)
        sig(u.IsZoomed, B, H)
        sig(u.ShowWindow, B, H, INT)
        sig(u.ShowWindowAsync, B, H, INT)
        sig(u.SetWindowPos, B, H, H, INT, INT, INT, INT, UI)
        sig(u.GetWindowRect, B, H, ctypes.POINTER(wintypes.RECT))
        sig(u.GetClientRect, B, H, ctypes.POINTER(wintypes.RECT))
        sig(u.MapWindowPoints, INT, H, H, ctypes.POINTER(wintypes.POINT), UI)
        sig(u.GetWindowPlacement, B, H, ctypes.POINTER(WINDOWPLACEMENT))
        sig(u.SetWindowPlacement, B, H, ctypes.POINTER(WINDOWPLACEMENT))
        sig(u.PostMessageW, B, H, UI, wintypes.WPARAM, wintypes.LPARAM)
        sig(u.PostThreadMessageW, B, wintypes.DWORD, UI, wintypes.WPARAM, wintypes.LPARAM)
        sig(u.GetMessageW, B, ctypes.POINTER(wintypes.MSG), H, UI, UI)
        sig(u.PeekMessageW, B, ctypes.POINTER(wintypes.MSG), H, UI, UI, UI)
        sig(u.TranslateMessage, B, ctypes.POINTER(wintypes.MSG))
        sig(u.DispatchMessageW, LP, ctypes.POINTER(wintypes.MSG))
        sig(u.SetTimer, ctypes.c_size_t, H, ctypes.c_size_t, UI, ctypes.c_void_p)
        sig(u.EnumWindows, B, self.ENUMPROC, wintypes.LPARAM)
        sig(u.GetClassNameW, INT, H, wintypes.LPWSTR, INT)
        sig(u.GetWindowTextW, INT, H, wintypes.LPWSTR, INT)
        sig(u.GetWindowTextLengthW, INT, H)
        sig(u.GetWindowThreadProcessId, wintypes.DWORD, H, ctypes.POINTER(wintypes.DWORD))
        sig(u.SetForegroundWindow, B, H)
        sig(u.GetForegroundWindow, H)
        sig(u.SetWinEventHook, wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
            wintypes.HMODULE, self.WINEVENTPROC, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD)
        sig(u.UnhookWinEvent, B, wintypes.HANDLE)
        sig(u.SetWindowRgn, INT, H, wintypes.HRGN, B)
        sig(k.GetCurrentThreadId, wintypes.DWORD)
        sig(k.GetModuleHandleW, wintypes.HMODULE, wintypes.LPCWSTR)
        sig(k.OpenProcess, wintypes.HANDLE, wintypes.DWORD, B, wintypes.DWORD)
        sig(k.CloseHandle, B, wintypes.HANDLE)
        sig(k.QueryFullProcessImageNameW, B, wintypes.HANDLE, wintypes.DWORD,
            wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
        gdi = ctypes.WinDLL("gdi32")
        sig(gdi.CreateRectRgn, wintypes.HRGN, INT, INT, INT, INT)
        self.gdi32 = gdi

    # -- small readers ----------------------------------------------------------

    def class_name(self, hwnd: int) -> str:
        buf = ctypes.create_unicode_buffer(128)
        self.user32.GetClassNameW(hwnd, buf, 128)
        return buf.value

    def title(self, hwnd: int) -> str:
        length = self.user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return ""
        buf = ctypes.create_unicode_buffer(length + 1)
        self.user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value

    def image_name(self, hwnd: int) -> str:
        pid = self.wt.DWORD()
        self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        handle = self.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not handle:
            return ""
        try:
            size = self.wt.DWORD(1024)
            buf = ctypes.create_unicode_buffer(size.value)
            if not self.kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return ""
            return Path(buf.value).name.lower()
        finally:
            self.kernel32.CloseHandle(handle)

    def rect(self, hwnd: int, client: bool = False) -> tuple[int, int, int, int]:
        r = self.wt.RECT()
        (self.user32.GetClientRect if client else self.user32.GetWindowRect)(hwnd, ctypes.byref(r))
        return r.left, r.top, r.right - r.left, r.bottom - r.top

    def pid(self, hwnd: int) -> int:
        value = self.wt.DWORD()
        self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(value))
        return int(value.value)

    def client_origin(self, hwnd: int) -> tuple[int, int]:
        """Where ``hwnd``'s client area starts on the screen."""
        point = self.wt.POINT(0, 0)
        self.user32.MapWindowPoints(hwnd, None, ctypes.byref(point), 1)
        return point.x, point.y


@dataclass
class _Request:
    owner: str
    host: int
    rect: Mapping[str, float] | None
    dpr: float
    visible: bool


class ChromeEmbed:
    """One browser window shown inside the app, driven from any thread.

    Public methods are thread-safe and block for at most a few seconds
    (``launch`` up to :data:`LAUNCH_TIMEOUT_S`). Every native window call runs
    on the embed's own message-loop thread.
    """

    def __init__(self) -> None:
        self._api: _Api | None = None
        self._lock = threading.RLock()
        self._tasks: queue.Queue[tuple[Callable[[], Any], Future[Any]]] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._host = 0
        self._chrome = 0
        self._chrome_pid = 0
        self._saved: _Saved | None = None
        self._owner = ""
        self._visible = False
        #: The panel in page pixels, ``(x, y, width, height)`` from the page's top-left.
        self._page_rect: tuple[int, int, int, int] | None = None
        #: Window-event hooks and their callback (kept alive while hooked).
        self._hooks: list[Any] = []
        self._chrome_hooks: list[Any] = []
        self._event_proc: Any = None
        self._syncing = False
        self._clip_key: tuple[int, ...] | None = None
        #: Whether the browser window is on screen over the panel right now.
        self._shown = False
        self._state = "idle"
        self._reason = ""
        self._browser = ""
        self._profile = ""
        self._generation = 0
        self._closing = False
        #: The page re-sends a visible placement about every second; without
        #: one for a while (the page reloaded or crashed without saying so)
        #: the window hides instead of staying over whatever loads next.
        self._lease_until = 0.0

    # -- public API -----------------------------------------------------------

    @staticmethod
    def supported() -> bool:
        return _is_windows()

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "available": self.supported(),
                "state": self._state,
                "reason": self._reason,
                "browser": self._browser,
                "profile": self._profile,
                "visible": self._visible and self._state == "embedded",
            }

    def launch(self, browser_id: str, profile: str, url: str | None, host: int) -> dict[str, Any]:
        """Open a new window of ``browser_id`` with ``profile`` and take it into ``host``.

        A window already shown for the same browser and profile is kept (the
        page only asked again) and moves to ``host``. A different profile closes
        the old window first. A newer launch supersedes one still waiting for
        its window: the older one closes the window it opened.
        """
        if not self.supported():
            return self._fail("unsupported")
        spec = browser_by_id(browser_id)
        if spec is None:
            return self._fail("unknown_browser")
        if not is_profile_dir(profile) or not self._profile_exists(spec, profile):
            return self._fail("bad_profile")
        exe = find_browser_exe(spec)
        if exe is None:
            return self._fail("browser_missing")
        with self._lock:
            if self._closing:
                return self._fail("shutting_down")
            self._generation += 1
            generation = self._generation
            same = (self._browser, self._profile) == (spec.id, profile)
            alive = bool(self._chrome and self._api and self._api.user32.IsWindow(self._chrome))
        try:
            if alive and same:
                self._call(lambda: self._set_host(host))
                return {**self.status(), "ok": True}
            if not alive:
                self._ensure_thread()
                adopted = self._call(lambda: self._adopt_left_over(spec, profile, host))
                if adopted:
                    return {**self.status(), "ok": True}
            if alive:
                self.release(close=True)
            self._ensure_thread()
            with self._lock:
                self._state, self._reason = "launching", ""
                self._browser, self._profile = spec.id, profile
            token = new_token()
            if not self._start_browser(exe, profile, handoff_url(token, safe_start_url(url))):
                return self._fail("launch_failed")
            hwnd = self._wait_for_window(spec, token, generation)
            if not hwnd:
                if not self._current(generation):
                    return {**self.status(), "ok": False, "reason": "superseded"}
                return self._fail("window_not_found")
            if not self._current(generation):
                # A newer launch or the app's shutdown came first.
                self._load_api().user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
                return {**self.status(), "ok": False, "reason": "superseded"}
            try:
                self._call(lambda: self._take(hwnd, host, generation))
            except Exception:
                # A window we opened but could not take must not stay behind.
                self._load_api().user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
                raise
            return {**self.status(), "ok": True}
        except Exception as exc:  # noqa: BLE001 - reported to the page, logged here
            logger.warning("Browser panel launch failed: %s", exc, exc_info=True)
            return self._fail("launch_failed")

    def open_tab(self, url: str) -> dict[str, Any]:
        """Open ``url`` as a new tab in the panel's window.

        A plain start of the browser exe hands the address to the running
        browser, which opens it in its last active window. The panel's window
        is made the active one first, so the tab lands there and not in a
        hidden window or another window of the user. Only works while the
        window is embedded and shown; otherwise ``ok`` is false and the page
        opens a new panel window on the address instead.
        """
        if not self.supported():
            return self._fail_quietly("unsupported")
        target = url.strip()
        parsed = urlparse(target)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return self._fail_quietly("bad_url")
        with self._lock:
            hwnd, browser_id, profile = self._chrome, self._browser, self._profile
            embedded = self._state == "embedded"
        spec = browser_by_id(browser_id)
        exe = find_browser_exe(spec) if spec is not None else None
        if not (embedded and hwnd and exe is not None and self._thread is not None):
            return self._fail_quietly("not_embedded")
        try:
            shown = self._call(lambda: self._activate_for_tab(hwnd))
        except Exception as exc:  # noqa: BLE001 - reported to the page, logged here
            logger.warning("Browser panel activate failed: %s", exc, exc_info=True)
            return self._fail_quietly("activate_failed")
        if not shown:
            return self._fail_quietly("not_shown")
        if not self._start_browser(exe, profile, target, new_window=False):
            return self._fail_quietly("launch_failed")
        return {**self.status(), "ok": True}

    def _activate_for_tab(self, hwnd: int) -> bool:
        """Make the shown panel window the browser's active one (native thread)."""
        user32 = self._load_api().user32
        if hwnd != self._chrome or not user32.IsWindow(hwnd):
            return False
        self._sync()
        if not self._shown:
            return False
        user32.SetForegroundWindow(hwnd)
        return True

    def _fail_quietly(self, reason: str) -> dict[str, Any]:
        """A refusal that leaves the window's own state alone."""
        return {**self.status(), "ok": False, "reason": reason}

    def _current(self, generation: int) -> bool:
        with self._lock:
            return generation == self._generation and not self._closing

    @staticmethod
    def _profile_exists(spec: BrowserSpec, profile: str) -> bool:
        """Only a profile the browser lists may be opened; a typo would create a new one."""
        profiles, _ = read_profiles(user_data_dir(spec))
        if not profiles:
            return profile == "Default"
        return any(p.directory == profile for p in profiles)

    def place(
        self,
        owner: str,
        host: int,
        rect: Mapping[str, float] | None,
        dpr: float,
        visible: bool,
    ) -> dict[str, Any]:
        """Move the window over the panel's rectangle, or hide it.

        ``owner`` names the page component asking. Several hidden panels may
        exist (one per workspace); a hide from a panel that is not the one shown
        last is ignored, so it cannot blank the visible one.
        """
        if not self.supported():
            return {**self.status(), "ok": False}
        request = _Request(owner, host, rect, dpr, visible)
        if self._thread is None:
            # Nothing to move before the first launch; remember who asked.
            with self._lock:
                if visible:
                    self._owner = owner
            return {**self.status(), "ok": True}
        self._call(lambda: self._apply(request))
        return {**self.status(), "ok": True}

    def release(
        self, *, close: bool, focus: bool = False, timeout: float = CALL_TIMEOUT_S,
    ) -> dict[str, Any]:
        """Give the window back to the desktop, then close it or leave it open."""
        if self._thread is None or not self._chrome:
            return {**self.status(), "ok": True}
        try:
            self._call(lambda: self._give_back(close=close, focus=focus), timeout)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Browser panel release failed: %s", exc, exc_info=True)
            return {**self.status(), "ok": False, "reason": "release_failed"}
        return {**self.status(), "ok": True}

    def release_host(self, host: int) -> None:
        """Close the window when ``host`` closes, so it does not stay behind on its own."""
        if host and self._host == host and self._chrome:
            # Called from the closing window's UI thread, which does not pump
            # messages while it waits: keep the wait short.
            hwnd = self._chrome
            result = self.release(close=True, timeout=2.0)
            if not result.get("ok") and hwnd and self._api is not None:
                # At least ask the browser to close the window itself.
                self._api.user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)

    def shutdown(self) -> None:
        """Close the browser window and stop the native thread. Idempotent."""
        with self._lock:
            self._closing = True
            self._generation += 1  # a launch still waiting closes what it finds
            thread = self._thread
        if thread is None:
            return
        try:
            self.release(close=True, timeout=2.0)
            self._call(self._unhook_all, 2.0)
        except Exception:  # noqa: BLE001
            logger.debug("Browser panel shutdown was not clean", exc_info=True)
        api = self._api
        if api is not None and self._thread_id:
            api.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        thread.join(1.0)

    # -- a window left by the previous app run ---------------------------------

    @staticmethod
    def _state_path() -> Path | None:
        try:
            from dodaios.core.config import DATA_DIR  # noqa: PLC0415
        except Exception:  # noqa: BLE001 - without a data folder nothing is remembered
            return None
        return Path(DATA_DIR) / STATE_FILE_NAME

    def _remember(self) -> None:
        """Write down the window in use, with what it looked like before it was taken."""
        path, saved = self._state_path(), self._saved
        if path is None or saved is None or not self._chrome:
            return
        placement = saved.placement
        rect = placement.rcNormalPosition
        record = {
            "hwnd": int(self._chrome), "pid": int(self._chrome_pid),
            "browser": self._browser, "profile": self._profile,
            "style": int(saved.style), "exstyle": int(saved.exstyle),
            "show": int(placement.showCmd),
            "normal": [rect.left, rect.top, rect.right, rect.bottom],
        }
        try:
            path.write_text(json.dumps(record), encoding="utf-8")
        except OSError as exc:
            logger.debug("Browser panel window not remembered: %s", exc)

    def _forget(self) -> None:
        path = self._state_path()
        if path is not None:
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                logger.debug("Browser panel window record not removed: %s", exc)

    def _left_over(self, spec: BrowserSpec) -> dict[str, Any] | None:
        """The remembered window, if it is still that browser's window in panel style."""
        path = self._state_path()
        if path is None or not path.is_file():
            return None
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            hwnd, pid = int(record["hwnd"]), int(record["pid"])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            logger.info("Browser panel window record unreadable, dropped: %s", exc)
            self._forget()
            return None
        api = self._load_api()
        user32 = api.user32
        ok = (
            user32.IsWindow(hwnd) and api.pid(hwnd) == pid
            and api.class_name(hwnd) == _WINDOW_CLASS
            and api.image_name(hwnd) == spec.image_name
            and int(user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)) & WS_EX_TOOLWINDOW
        )
        if not ok:
            self._forget()
            return None
        return record

    def _adopt_left_over(self, spec: BrowserSpec, profile: str, host: int) -> bool:
        """Take back the window a hard-stopped app left on screen, tabs and all.

        A window of another profile is handed back to the desktop instead.
        """
        record = self._left_over(spec)
        if record is None:
            return False
        api = self._load_api()
        placement = api.WINDOWPLACEMENT()
        placement.length = ctypes.sizeof(api.WINDOWPLACEMENT)
        api.user32.GetWindowPlacement(int(record["hwnd"]), ctypes.byref(placement))
        placement.showCmd = int(record.get("show", SW_SHOWNORMAL))
        left, top, right, bottom = (int(v) for v in record.get("normal", [0, 0, 800, 600]))
        rect = placement.rcNormalPosition
        rect.left, rect.top, rect.right, rect.bottom = left, top, right, bottom
        saved = _Saved(int(record["style"]), int(record["exstyle"]), placement)
        with self._lock:
            self._chrome = int(record["hwnd"])
            self._chrome_pid = int(record["pid"])
            self._saved = saved
            self._browser = str(record.get("browser", spec.id))
            self._profile = str(record.get("profile", ""))
            self._host = host or self._host
            self._clip_key = None
            self._state, self._reason = "embedded", ""
        if self._profile != profile:
            self._give_back(close=True, focus=False)
            return False
        self._hook_browser_events()
        self._sync()
        logger.info("Browser panel took back the window of the previous run")
        return True

    # -- launching (caller thread) ----------------------------------------------

    def _fail(self, reason: str) -> dict[str, Any]:
        with self._lock:
            if self._state == "launching":
                self._state = "error"
            self._reason = reason
        return {**self.status(), "ok": False, "reason": reason}

    @staticmethod
    def _start_browser(exe: Path, profile: str, url: str, *, new_window: bool = True) -> bool:
        """Start the browser exe; a running browser opens the window in its own process.

        The browser must not belong to the app's job object: when the browser
        was not running yet, the started exe IS the browser, and closing the
        app must not take it down. Breakaway can be forbidden by the job, so a
        plain start is the fallback.
        """
        from dodaios.core.process_utils import NO_WINDOW_CREATIONFLAGS  # noqa: PLC0415

        window = ["--new-window"] if new_window else []
        argv = [str(exe), f"--profile-directory={profile}", *window, url]
        # The browser finds its profiles below %LOCALAPPDATA%. An app started
        # with that variable pointed elsewhere (an isolated instance) would
        # otherwise start a second, empty browser instead of the user's own.
        env = dict(os.environ)
        local = real_local_app_data()
        if local:
            env["LOCALAPPDATA"] = local
        breakaway = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000)
        for flags in (NO_WINDOW_CREATIONFLAGS | breakaway, NO_WINDOW_CREATIONFLAGS):
            try:
                subprocess.Popen(argv, creationflags=flags, close_fds=True, env=env)  # noqa: S603
                return True
            except OSError as exc:
                logger.info("Browser start with flags %#x failed: %s", flags, exc)
        return False

    def _wait_for_window(self, spec: BrowserSpec, token: str, generation: int) -> int:
        api = self._load_api()
        deadline = time.monotonic() + LAUNCH_TIMEOUT_S
        while time.monotonic() < deadline and self._current(generation):
            hwnd = self._find_window(api, spec, token)
            if hwnd:
                return hwnd
            time.sleep(0.05)
        return 0

    @staticmethod
    def _find_window(api: _Api, spec: BrowserSpec, token: str) -> int:
        hits: list[int] = []

        def visit(hwnd: int, _lparam: int) -> bool:
            if token in api.title(hwnd) and api.class_name(hwnd) == _WINDOW_CLASS:
                hits.append(int(hwnd))
                return False
            return True

        api.user32.EnumWindows(api.ENUMPROC(visit), 0)
        for hwnd in hits:
            if api.image_name(hwnd) == spec.image_name:
                return hwnd
        return 0

    # -- the native thread -------------------------------------------------------

    def _load_api(self) -> _Api:
        if self._api is None:
            self._api = _Api()
        return self._api

    def _ensure_thread(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            if self._closing:
                raise RuntimeError("browser panel is shutting down")
            ready = threading.Event()
            self._thread = threading.Thread(
                target=self._loop, args=(ready,), name="browser-panel-embed", daemon=True,
            )
            self._thread.start()
        if not ready.wait(CALL_TIMEOUT_S):
            raise RuntimeError("browser panel thread did not start")

    def _call(self, fn: Callable[[], T], timeout: float = CALL_TIMEOUT_S) -> T:
        if threading.current_thread() is self._thread:
            return fn()
        self._ensure_thread()
        future: Future[T] = Future()
        self._tasks.put((fn, future))
        self._load_api().user32.PostThreadMessageW(self._thread_id, WM_APP_TASK, 0, 0)
        try:
            return future.result(timeout)
        except FutureTimeout as exc:
            raise RuntimeError("browser panel thread did not answer") from exc

    def _loop(self, ready: threading.Event) -> None:
        api = self._load_api()
        try:
            from dodaios.core.win32_dpi import ensure_dpi_awareness  # noqa: PLC0415

            ensure_dpi_awareness()
        except Exception:  # noqa: BLE001 - only the coordinates' precision depends on it
            logger.debug("DPI awareness not set for the browser panel", exc_info=True)
        msg = api.wt.MSG()
        api.user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)  # creates the queue
        self._thread_id = int(api.kernel32.GetCurrentThreadId())
        self._hook_app_events(api)
        api.user32.SetTimer(None, 0, WATCH_INTERVAL_MS, None)
        ready.set()
        while api.user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            try:
                if msg.message == WM_APP_TASK and not msg.hWnd:
                    self._run_tasks()
                elif msg.message == WM_TIMER and not msg.hWnd:
                    self._watch()
                else:
                    api.user32.TranslateMessage(ctypes.byref(msg))
                    api.user32.DispatchMessageW(ctypes.byref(msg))
            except Exception:  # noqa: BLE001 - the loop outlives one bad message
                logger.warning("Browser panel message failed", exc_info=True)
        self._run_tasks()
        self._unhook_all()

    def _run_tasks(self) -> None:
        while True:
            try:
                fn, future = self._tasks.get_nowait()
            except queue.Empty:  # every queued task has run
                return
            if future.set_running_or_notify_cancel():
                try:
                    future.set_result(fn())
                except BaseException as exc:  # noqa: BLE001 - handed to the caller
                    future.set_exception(exc)

    # -- window events (delivered on the embed thread) ---------------------------

    def zorder_anchor(self, host: int) -> int | None:
        """The browser window when it is shown over ``host``: the app window stays under it.

        Called from the app window's own window procedure (see
        ``window_frame.set_zorder_anchor``), so it only reads plain fields.
        """
        chrome, api = self._chrome, self._api
        if not chrome or api is None or host != self._host or not self._shown:
            return None
        # Only when nothing else lies above the browser window: otherwise the app
        # would come up under another program instead of to the front.
        user32 = api.user32
        window = user32.GetWindow(chrome, GW_HWNDPREV)
        for _ in range(256):
            if not window:
                return chrome
            if user32.IsWindowVisible(window) and not (
                int(user32.GetWindowLongPtrW(window, GWL_EXSTYLE)) & WS_EX_TOPMOST
            ):
                return None
            window = user32.GetWindow(window, GW_HWNDPREV)
        return None

    def _hook_app_events(self, api: _Api) -> None:
        """Follow the app: front, minimize and restore, move and resize, show and hide."""
        try:
            from dodaios.ui.window_frame import set_zorder_anchor  # noqa: PLC0415

            set_zorder_anchor(self.zorder_anchor)
        except Exception:  # noqa: BLE001 - without it the window is raised after the app
            logger.debug("Browser panel z-order anchor not installed", exc_info=True)
        self._event_proc = api.WINEVENTPROC(self._on_event)
        own = os.getpid()
        for low, high, pid in (
            (EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_FOREGROUND, 0),
            (EVENT_SYSTEM_MINIMIZESTART, EVENT_SYSTEM_MINIMIZEEND, own),
            (EVENT_OBJECT_SHOW, EVENT_OBJECT_HIDE, own),
            (EVENT_OBJECT_LOCATIONCHANGE, EVENT_OBJECT_LOCATIONCHANGE, own),
        ):
            hook = api.user32.SetWinEventHook(
                low, high, None, self._event_proc, pid, 0, WINEVENT_OUTOFCONTEXT,
            )
            if hook:
                self._hooks.append(hook)

    def _hook_browser_events(self) -> None:
        """Follow the browser window: its own buttons or a drag must not move it."""
        api = self._load_api()
        self._unhook(self._chrome_hooks)
        if not self._chrome_pid or self._event_proc is None:
            return
        hook = api.user32.SetWinEventHook(
            EVENT_OBJECT_LOCATIONCHANGE, EVENT_OBJECT_LOCATIONCHANGE, None,
            self._event_proc, self._chrome_pid, 0, WINEVENT_OUTOFCONTEXT,
        )
        if hook:
            self._chrome_hooks.append(hook)

    def _unhook(self, hooks: list[Any]) -> None:
        api = self._api
        while hooks:
            hook = hooks.pop()
            if api is not None:
                api.user32.UnhookWinEvent(hook)

    def _unhook_all(self) -> None:
        self._unhook(self._chrome_hooks)
        self._unhook(self._hooks)

    def _on_event(
        self, _hook: Any, event: int, hwnd: Any, id_object: int, _child: int,
        _thread: int, _time: int,
    ) -> None:
        if not self._chrome:
            return
        window = int(hwnd or 0)
        try:
            if event == EVENT_SYSTEM_FOREGROUND:
                if window == self._chrome:
                    self._raise_host_below_browser()
                elif window == self._host:
                    self._sync()
                return
            if id_object != OBJID_WINDOW or window not in (self._host, self._chrome):
                return  # carets, cursors and the app's other windows
            self._sync()
        except Exception:  # noqa: BLE001 - an event must never end the loop
            logger.debug("Browser panel event failed", exc_info=True)

    # -- native work (runs on the embed thread) --------------------------------

    def _set_host(self, host: int) -> None:
        if host and host != self._host:
            self._host = host
            self._sync()

    def _take(self, hwnd: int, host: int, generation: int) -> None:
        if not self._current(generation):
            raise RuntimeError("superseded")
        api = self._load_api()
        user32 = api.user32
        placement = api.WINDOWPLACEMENT()
        placement.length = ctypes.sizeof(api.WINDOWPLACEMENT)
        user32.GetWindowPlacement(hwnd, ctypes.byref(placement))
        style = int(user32.GetWindowLongPtrW(hwnd, GWL_STYLE))
        exstyle = int(user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE))
        self._saved = _Saved(style, exstyle, placement)
        if user32.IsZoomed(hwnd) or user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
        # Hidden until it sits on the panel: no flash at the browser's own bounds.
        user32.ShowWindow(hwnd, SW_HIDE)
        frame = WS_CHILD | WS_CAPTION | WS_THICKFRAME | WS_MINIMIZE | WS_MAXIMIZE
        frame |= WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX | WS_VISIBLE
        user32.SetWindowLongPtrW(hwnd, GWL_STYLE, (style & ~frame) | WS_POPUP)
        # A tool window has no taskbar button and no Alt+Tab entry of its own.
        user32.SetWindowLongPtrW(
            hwnd, GWL_EXSTYLE, (exstyle & ~WS_EX_APPWINDOW) | WS_EX_TOOLWINDOW,
        )
        user32.SetWindowPos(
            hwnd, None, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
        )
        with self._lock:
            self._chrome = hwnd
            self._chrome_pid = api.pid(hwnd)
            self._host = host or self._host
            self._clip_key = None
            self._state, self._reason = "embedded", ""
        self._hook_browser_events()
        self._remember()
        self._sync()
        logger.info("Browser panel took a %s window", self._browser)

    def _apply(self, request: _Request) -> None:
        with self._lock:
            if not request.visible:
                if request.owner != self._owner:
                    return
                self._visible = False
            else:
                self._owner = request.owner
                self._visible = True
                self._lease_until = time.monotonic() + LEASE_S
        if request.host:
            self._host = request.host
        if request.visible and request.rect is not None:
            self._page_rect = panel_to_client_rect(request.rect, request.dpr, (0, 0))
        self._sync()

    def _page_origin(self) -> tuple[int, int]:
        """Where the page (the WebView) starts on the screen.

        The WebView is the host's largest visible child window. A host without
        children shows the page in its own client area.
        """
        api = self._load_api()
        user32 = api.user32
        best, best_area = 0, -1
        child = user32.GetWindow(self._host, GW_CHILD)
        while child:
            if user32.IsWindowVisible(child):
                _, _, w, h = api.rect(child)
                if w * h > best_area:
                    best, best_area = int(child), w * h
            child = user32.GetWindow(child, GW_HWNDNEXT)
        return api.client_origin(best or self._host)

    def _should_show(self) -> bool:
        user32 = self._load_api().user32
        host, rect = self._host, self._page_rect
        return bool(
            self._chrome and self._visible and rect is not None and rect[2] > 0 and rect[3] > 0
            and host and user32.IsWindow(host) and user32.IsWindowVisible(host)
            and not user32.IsIconic(host)
        )

    def _sync(self) -> None:
        """Put the browser window on the panel and just above the app, or hide it.

        Idempotent: it only touches the window when something differs, because
        every move it makes comes back as a window event.
        """
        hwnd = self._chrome
        if not hwnd or self._syncing:
            return
        api = self._load_api()
        user32 = api.user32
        if not user32.IsWindow(hwnd) or user32.IsHungAppWindow(hwnd):
            return
        self._syncing = True
        try:
            if not self._should_show() or self._page_rect is None:
                self._shown = False
                if user32.IsWindowVisible(hwnd):
                    user32.ShowWindow(hwnd, SW_HIDE)
                return
            if user32.IsIconic(hwnd) or user32.IsZoomed(hwnd):
                # The browser's own minimize / maximize buttons: stay on the panel.
                user32.ShowWindow(hwnd, SW_RESTORE)
            ox, oy = self._page_origin()
            x, y, w, h = self._page_rect
            left, top, right, bottom = self._frame_insets()
            want = (ox + x - left, oy + y - top, w + left + right, h + top + bottom)
            shown = bool(user32.IsWindowVisible(hwnd))
            above = shown and self._is_above_host()
            if api.rect(hwnd) != want or not shown or not above:
                flags = SWP_NOACTIVATE | SWP_SHOWWINDOW
                after = None if above else self._insert_after()
                if after is None:
                    flags |= SWP_NOZORDER
                user32.SetWindowPos(hwnd, after, *want, flags)
            self._shown = True
            # The browser keeps an invisible resize border around its page; cut
            # the window to the page so that border cannot catch the app's clicks.
            self._clip(want[2], want[3], (left, top, right, bottom))
        finally:
            self._syncing = False

    def _clip(self, w: int, h: int, insets: tuple[int, int, int, int]) -> None:
        key = (w, h, *insets)
        if self._clip_key == key:
            return
        left, top, right, bottom = insets
        api = self._load_api()
        region = api.gdi32.CreateRectRgn(left, top, w - right, h - bottom)
        # The window owns the region once the call succeeds.
        if region and api.user32.SetWindowRgn(self._chrome, region, True):
            self._clip_key = key

    def _is_above_host(self) -> bool:
        """Whether the browser window lies above the app window in the z-order."""
        user32 = self._load_api().user32
        window = user32.GetWindow(self._host, GW_HWNDPREV)
        for _ in range(64):
            if not window:
                return False
            if int(window) == self._chrome:
                return True
            window = user32.GetWindow(window, GW_HWNDPREV)
        return False

    def _insert_after(self) -> Any:
        """The window to place the browser under: the one just above the app."""
        user32 = self._load_api().user32
        above = user32.GetWindow(self._host, GW_HWNDPREV)
        return above if above and int(above) != self._chrome else HWND_TOP

    def _raise_host_below_browser(self) -> None:
        """The user clicked into the browser: bring the app up right under it."""
        if not self._host or not self._should_show():
            return
        self._load_api().user32.SetWindowPos(
            self._host, self._chrome, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
        )

    def _frame_insets(self) -> tuple[int, int, int, int]:
        """The browser window's border around its page area: left, top, right, bottom."""
        api = self._load_api()
        wx, wy, ww, wh = api.rect(self._chrome)
        _, _, cw, ch = api.rect(self._chrome, client=True)
        ox, oy = api.client_origin(self._chrome)
        left, top = ox - wx, oy - wy
        right, bottom = ww - cw - left, wh - ch - top
        insets = (left, top, right, bottom)
        # A border wider than 32 px is a reading taken mid-change: ignore it.
        return insets if all(0 <= v <= 32 for v in insets) else (0, 0, 0, 0)

    def _watch(self) -> None:
        """Catch what no window event reported, and notice a closed window. Runs on a timer."""
        hwnd = self._chrome
        if not hwnd:
            return
        api = self._load_api()
        user32 = api.user32
        if self._visible and time.monotonic() > self._lease_until:
            with self._lock:
                self._visible = False
        if user32.IsHungAppWindow(hwnd):
            return  # never wait on a browser that does not answer
        try:
            if not user32.IsWindow(hwnd):
                with self._lock:
                    self._lost("closed")
                self._unhook(self._chrome_hooks)
                return
            self._sync()
        except Exception:  # noqa: BLE001 - a watchdog tick must never end the loop
            logger.debug("Browser panel watchdog tick failed", exc_info=True)

    def _lost(self, state: str) -> None:
        self._forget()
        self._shown = False
        self._chrome = 0
        self._chrome_pid = 0
        self._saved = None
        self._clip_key = None
        self._state = state

    def _give_back(self, *, close: bool, focus: bool) -> None:
        hwnd, saved = self._chrome, self._saved
        api = self._load_api()
        user32 = api.user32
        with self._lock:
            self._lost("released" if not close else "idle")
        self._unhook(self._chrome_hooks)
        if not hwnd or not user32.IsWindow(hwnd):
            return
        if user32.IsHungAppWindow(hwnd):
            # Every call below would wait on the frozen browser. Ask it to close
            # once it recovers.
            logger.warning("Browser panel window does not answer; not handing it back")
            if close:
                user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            return
        user32.ShowWindow(hwnd, SW_HIDE)
        user32.SetWindowRgn(hwnd, None, False)
        if saved is not None:
            style = saved.style & ~(WS_VISIBLE | WS_MINIMIZE | WS_MAXIMIZE)
            user32.SetWindowLongPtrW(hwnd, GWL_STYLE, style)
            user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, saved.exstyle)
            placement = saved.placement
            if close:
                placement.showCmd = SW_HIDE
            elif placement.showCmd not in (SW_SHOWNORMAL, 3):  # 3 = SW_SHOWMAXIMIZED
                placement.showCmd = SW_SHOWNORMAL
            user32.SetWindowPlacement(hwnd, ctypes.byref(placement))
            user32.SetWindowPos(
                hwnd, None, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED | SWP_NOACTIVATE,
            )
        logger.info("Browser panel gave its window back (%s)", "closed" if close else "kept open")
        if close:
            user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            if not self._closed_within(hwnd, CLOSE_GRACE_S):
                # The page refused to close (a "Leave site?" prompt). A hidden
                # window would stay hidden for good, and the browser keeps
                # sending new windows into it: show it, prompt included.
                logger.info("Browser panel window did not close; shown again")
                user32.ShowWindow(hwnd, SW_SHOWNA)
        else:
            user32.ShowWindow(hwnd, SW_SHOW)
            if focus:
                user32.SetForegroundWindow(hwnd)

    def _closed_within(self, hwnd: int, seconds: float) -> bool:
        user32 = self._load_api().user32
        deadline = time.monotonic() + seconds
        while user32.IsWindow(hwnd):
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.05)
        return True


_embed: ChromeEmbed | None = None
_embed_lock = threading.Lock()


def get_embed() -> ChromeEmbed:
    """The process-wide embed (one browser window per app)."""
    global _embed
    with _embed_lock:
        if _embed is None:
            _embed = ChromeEmbed()
        return _embed


def release_host_if_any(host: int) -> None:
    """Close the panel's browser window if it sits in ``host``; no-op otherwise."""
    embed = _embed
    if embed is not None:
        embed.release_host(host)


def shutdown_embed() -> None:
    """Close the panel's browser window on app exit. Never raises."""
    embed = _embed
    if embed is None:
        return
    try:
        embed.shutdown()
    except Exception:  # noqa: BLE001
        logger.debug("Browser panel shutdown failed", exc_info=True)

