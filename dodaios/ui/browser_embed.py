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
2. The window whose title carries the token is taken: its frame styles are
   switched to a child window and it is parented into a small container window
   the app owns, which sits on top of the page exactly where the panel is.
3. The page reports the panel's rectangle (and hides the container when the
   panel is hidden). A watchdog keeps the browser window filling the container,
   undoes minimize / maximize from the browser's own buttons, and notices when
   the user closes the window.
4. On release (app exit, profile switch, "open in own window") the window gets
   its original styles and placement back, so the browser remembers sensible
   bounds, and is either closed or left as a normal window.

The container and every native call run on one thread of their own that pumps
messages: a window created on a thread without a message loop would block the
app's UI thread the first time it sent the window a message.

Limits that come with a foreign window: a page popup of the app that overlaps
the panel is drawn below the browser (the page hides the panel's browser while
such a popup covers it), and a link opened from another program can land in
this window when it was the browser's last active one.
"""

from __future__ import annotations

import ctypes
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

_WINDOW_CLASS = "Chrome_WidgetWin_1"
_CONTAINER_CLASS = "DodaiosBrowserPanelHost"

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
WS_EX_NOPARENTNOTIFY = 0x00000004
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
SW_RESTORE = 9
GW_HWNDNEXT = 2
GW_CHILD = 5
WM_CLOSE = 0x0010
WM_TIMER = 0x0113
WM_QUIT = 0x0012
WM_APP_TASK = 0x8000 + 0x51
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
HWND_TOP = 0


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
        self.WNDPROC = ctypes.WINFUNCTYPE(LP, H, UI, wintypes.WPARAM, wintypes.LPARAM)
        self.ENUMPROC = ctypes.WINFUNCTYPE(B, H, wintypes.LPARAM)

        class WNDCLASSEXW(ctypes.Structure):
            _fields_ = [
                ("cbSize", UI), ("style", UI), ("lpfnWndProc", self.WNDPROC),
                ("cbClsExtra", INT), ("cbWndExtra", INT), ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HBRUSH), ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR), ("hIconSm", wintypes.HICON),
            ]

        class WINDOWPLACEMENT(ctypes.Structure):
            _fields_ = [
                ("length", UI), ("flags", UI), ("showCmd", UI),
                ("ptMinPosition", wintypes.POINT), ("ptMaxPosition", wintypes.POINT),
                ("rcNormalPosition", wintypes.RECT),
            ]

        self.WNDCLASSEXW = WNDCLASSEXW
        self.WINDOWPLACEMENT = WINDOWPLACEMENT

        def sig(fn: Any, res: Any, *args: Any) -> None:
            fn.restype = res
            fn.argtypes = list(args)

        sig(u.DefWindowProcW, LP, H, UI, wintypes.WPARAM, wintypes.LPARAM)
        sig(u.RegisterClassExW, wintypes.ATOM, ctypes.POINTER(WNDCLASSEXW))
        sig(u.CreateWindowExW, H, wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
            wintypes.DWORD, INT, INT, INT, INT, H, wintypes.HMENU, wintypes.HINSTANCE,
            wintypes.LPVOID)
        sig(u.DestroyWindow, B, H)
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
        sig(k.GetCurrentThreadId, wintypes.DWORD)
        sig(k.GetModuleHandleW, wintypes.HMODULE, wintypes.LPCWSTR)
        sig(k.OpenProcess, wintypes.HANDLE, wintypes.DWORD, B, wintypes.DWORD)
        sig(k.CloseHandle, B, wintypes.HANDLE)
        sig(k.QueryFullProcessImageNameW, B, wintypes.HANDLE, wintypes.DWORD,
            wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD))
        gdi = ctypes.WinDLL("gdi32")
        sig(gdi.GetStockObject, wintypes.HGDIOBJ, INT)
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
        self._wndproc: Any = None
        self._container = 0
        self._host = 0
        self._chrome = 0
        self._saved: _Saved | None = None
        self._owner = ""
        self._visible = False
        self._client_rect: tuple[int, int, int, int] | None = None
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
                self._call(lambda: self._ensure_container(host))
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
        """Close the window before ``host`` is destroyed (it would take it along)."""
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
            self._call(self._destroy_container, 2.0)
        except Exception:  # noqa: BLE001
            logger.debug("Browser panel shutdown was not clean", exc_info=True)
        api = self._api
        if api is not None and self._thread_id:
            api.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        thread.join(1.0)

    # -- launching (caller thread) ----------------------------------------------

    def _fail(self, reason: str) -> dict[str, Any]:
        with self._lock:
            if self._state == "launching":
                self._state = "error"
            self._reason = reason
        return {**self.status(), "ok": False, "reason": reason}

    @staticmethod
    def _start_browser(exe: Path, profile: str, url: str) -> bool:
        """Start the browser exe; a running browser opens the window in its own process.

        The browser must not belong to the app's job object: when the browser
        was not running yet, the started exe IS the browser, and closing the
        app must not take it down. Breakaway can be forbidden by the job, so a
        plain start is the fallback.
        """
        from dodaios.core.process_utils import NO_WINDOW_CREATIONFLAGS  # noqa: PLC0415

        argv = [str(exe), f"--profile-directory={profile}", "--new-window", url]
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
        except Exception:  # noqa: BLE001
            logger.debug("DPI awareness not set for the browser panel", exc_info=True)
        msg = api.wt.MSG()
        api.user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)  # creates the queue
        self._thread_id = int(api.kernel32.GetCurrentThreadId())
        self._register_class(api)
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

    def _register_class(self, api: _Api) -> None:
        user32 = api.user32
        self._wndproc = api.WNDPROC(lambda h, m, w, lp: user32.DefWindowProcW(h, m, w, lp))
        wc = api.WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(api.WNDCLASSEXW)
        wc.lpfnWndProc = self._wndproc
        wc.hInstance = api.kernel32.GetModuleHandleW(None)
        wc.hbrBackground = api.gdi32.GetStockObject(4)  # BLACK_BRUSH
        wc.lpszClassName = _CONTAINER_CLASS
        # A second embed in the same process finds the class already there: fine.
        user32.RegisterClassExW(ctypes.byref(wc))

    def _ensure_container(self, host: int) -> int:
        api = self._load_api()
        user32 = api.user32
        if self._container and user32.IsWindow(self._container):
            if self._host != host and host:
                user32.SetParent(self._container, host)
                self._host = host
            return self._container
        self._container = int(user32.CreateWindowExW(
            WS_EX_NOPARENTNOTIFY, _CONTAINER_CLASS, None,
            WS_CHILD | WS_CLIPCHILDREN | WS_CLIPSIBLINGS,
            0, 0, 0, 0, host, None, api.kernel32.GetModuleHandleW(None), None,
        ) or 0)
        if not self._container:
            raise RuntimeError(f"container window not created ({ctypes.get_last_error()})")
        self._host = host
        return self._container

    def _destroy_container(self) -> None:
        if self._container and self._api and self._api.user32.IsWindow(self._container):
            self._api.user32.DestroyWindow(self._container)
        self._container = 0
        self._host = 0

    # -- native work (runs on the embed thread) --------------------------------

    def _take(self, hwnd: int, host: int, generation: int) -> None:
        if not self._current(generation):
            raise RuntimeError("superseded")
        api = self._load_api()
        user32 = api.user32
        container = self._ensure_container(host)
        placement = api.WINDOWPLACEMENT()
        placement.length = ctypes.sizeof(api.WINDOWPLACEMENT)
        user32.GetWindowPlacement(hwnd, ctypes.byref(placement))
        style = int(user32.GetWindowLongPtrW(hwnd, GWL_STYLE))
        exstyle = int(user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE))
        self._saved = _Saved(style, exstyle, placement)
        if user32.IsZoomed(hwnd) or user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
        frame = WS_POPUP | WS_CAPTION | WS_THICKFRAME | WS_MINIMIZE | WS_MAXIMIZE
        frame |= WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX
        user32.SetWindowLongPtrW(hwnd, GWL_STYLE, (style & ~frame) | WS_CHILD | WS_VISIBLE)
        user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, exstyle & ~WS_EX_APPWINDOW)
        user32.SetParent(hwnd, container)
        with self._lock:
            self._chrome = hwnd
            self._state, self._reason = "embedded", ""
        self._fit()
        self._show_container(self._visible and self._client_rect is not None)
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
        if not request.visible or not request.host:
            self._show_container(False)
            return
        container = self._ensure_container(request.host)
        if request.rect is not None:
            origin = self._page_origin(request.host)
            self._client_rect = panel_to_client_rect(request.rect, request.dpr, origin)
        if self._client_rect is None:
            return
        x, y, w, h = self._client_rect
        self._load_api().user32.SetWindowPos(
            container, HWND_TOP, x, y, w, h, SWP_NOACTIVATE,
        )
        self._fit()
        self._show_container(bool(self._chrome) and w > 0 and h > 0)

    def _page_origin(self, host: int) -> tuple[int, int]:
        """Where the page (the WebView) starts inside the host's client area.

        The WebView is the host's largest visible child; the container itself
        is skipped. A host without children puts the page at the origin.
        """
        api = self._load_api()
        user32 = api.user32
        best, best_area = 0, -1
        child = user32.GetWindow(host, GW_CHILD)
        while child:
            if int(child) != self._container and user32.IsWindowVisible(child):
                _, _, w, h = api.rect(child)
                if w * h > best_area:
                    best, best_area = int(child), w * h
            child = user32.GetWindow(child, GW_HWNDNEXT)
        if not best:
            return 0, 0
        point = api.wt.POINT(0, 0)
        user32.MapWindowPoints(best, host, ctypes.byref(point), 1)
        return point.x, point.y

    def _show_container(self, show: bool) -> None:
        api = self._load_api()
        if not self._container:
            return
        if show:
            api.user32.SetWindowPos(
                self._container, HWND_TOP, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW,
            )
        else:
            api.user32.ShowWindow(self._container, SW_HIDE)

    def _fit(self) -> None:
        """Make the browser's page area fill the container exactly.

        The browser keeps an invisible resize border around its client area
        even as a child window (7 px left, right and bottom at 100 %). The
        window is made that much larger and shifted, so the border falls
        outside the container and is clipped instead of showing as a black
        frame.
        """
        target = self._fit_target()
        if target is None:
            return
        x, y, w, h = target
        self._load_api().user32.SetWindowPos(
            self._chrome, None, x, y, w, h,
            SWP_NOZORDER | SWP_NOACTIVATE | SWP_ASYNCWINDOWPOS,
        )

    def _fit_target(self) -> tuple[int, int, int, int] | None:
        """Where the browser window must sit inside the container, or None."""
        if not self._chrome or not self._container:
            return None
        api = self._load_api()
        _, _, cw, ch = api.rect(self._container, client=True)
        left, top, right, bottom = self._frame_insets()
        return -left, -top, cw + left + right, ch + top + bottom

    def _frame_insets(self) -> tuple[int, int, int, int]:
        """The browser window's border around its client area: left, top, right, bottom."""
        api = self._load_api()
        wx, wy, ww, wh = api.rect(self._chrome)
        _, _, cw, ch = api.rect(self._chrome, client=True)
        origin = api.wt.POINT(0, 0)
        api.user32.MapWindowPoints(self._chrome, None, ctypes.byref(origin), 1)
        left, top = origin.x - wx, origin.y - wy
        right, bottom = ww - cw - left, wh - ch - top
        insets = (left, top, right, bottom)
        # A border wider than 32 px is a reading taken mid-change: ignore it.
        return insets if all(0 <= v <= 32 for v in insets) else (0, 0, 0, 0)

    def _watch(self) -> None:
        """Keep the window in place and notice when it is gone. Runs on a timer."""
        hwnd = self._chrome
        if not hwnd:
            return
        api = self._load_api()
        user32 = api.user32
        if self._visible and time.monotonic() > self._lease_until:
            with self._lock:
                self._visible = False
            self._show_container(False)
        if user32.IsHungAppWindow(hwnd):
            return  # never wait on a browser that does not answer
        try:
            if not user32.IsWindow(hwnd) or int(user32.GetParent(hwnd) or 0) != self._container:
                with self._lock:
                    self._lost("closed")
                self._show_container(False)
                return
            if user32.IsIconic(hwnd) or user32.IsZoomed(hwnd):
                # The browser's own minimize / maximize buttons: stay in the panel.
                user32.ShowWindowAsync(hwnd, SW_RESTORE)
            target = self._fit_target()
            if target is not None:
                _, _, w, h = api.rect(hwnd)
                if (w, h) != target[2:]:
                    self._fit()
            if self._visible and user32.IsWindowVisible(self._container):
                top = int(user32.GetWindow(self._host, GW_CHILD) or 0)
                if top and top != self._container:
                    self._show_container(True)
        except Exception:  # noqa: BLE001 - a watchdog tick must never end the loop
            logger.debug("Browser panel watchdog tick failed", exc_info=True)

    def _lost(self, state: str) -> None:
        self._chrome = 0
        self._saved = None
        self._state = state

    def _give_back(self, *, close: bool, focus: bool) -> None:
        hwnd, saved = self._chrome, self._saved
        api = self._load_api()
        user32 = api.user32
        with self._lock:
            self._lost("released" if not close else "idle")
        self._show_container(False)
        if not hwnd or not user32.IsWindow(hwnd):
            return
        if user32.IsHungAppWindow(hwnd):
            # Every call below would wait on the frozen browser. Ask it to close
            # once it recovers; otherwise it goes down with the app window.
            logger.warning("Browser panel window does not answer; not handing it back")
            if close:
                user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            return
        if close:
            user32.ShowWindow(hwnd, SW_HIDE)
        user32.SetParent(hwnd, None)
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
        else:
            user32.ShowWindow(hwnd, SW_SHOW)
            if focus:
                user32.SetForegroundWindow(hwnd)


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

