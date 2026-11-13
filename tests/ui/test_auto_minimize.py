"""Windows focus-loss minimization tests using a fake user32 API."""

from __future__ import annotations

import ctypes
import os
import threading
from unittest.mock import Mock

from dodaios.ui import auto_minimize


def test_minimizes_only_after_assistant_loses_foreground(monkeypatch) -> None:
    minimized = threading.Event()
    foreground = [100, 200]
    iconic = False

    def is_iconic(_hwnd: int) -> bool:
        return iconic

    def show_window_async(_hwnd: int, _command: int) -> bool:
        nonlocal iconic
        iconic = True
        minimized.set()
        # Windows returns the previous visibility state, which can be false
        # even when the minimize request succeeded.
        return False

    def process_id(hwnd: int, result) -> int:
        result._obj.value = os.getpid() if hwnd == 100 else os.getpid() + 1
        return 1

    user32 = Mock()
    user32.FindWindowW = Mock(return_value=100)
    user32.GetForegroundWindow = Mock(
        side_effect=lambda: foreground.pop(0) if foreground else 200
    )
    user32.GetWindowThreadProcessId = Mock(side_effect=process_id)
    user32.GetAncestor = Mock(side_effect=lambda hwnd, _kind: hwnd)
    user32.IsWindowVisible = Mock(return_value=True)
    user32.IsIconic = Mock(side_effect=is_iconic)
    user32.ShowWindowAsync = Mock(side_effect=show_window_async)

    monkeypatch.setattr(auto_minimize.sys, "platform", "win32")
    monkeypatch.setattr(ctypes, "WinDLL", Mock(return_value=user32), raising=False)

    callbacks: list[str] = []
    watcher = auto_minimize.AutoMinimizeOnFocusLoss(
        "Dodaios",
        on_minimized=lambda: callbacks.append("minimized"),
        enabled=lambda: True,
        poll_interval_s=0.05,
        grace_s=0,
    )
    watcher.start()
    try:
        assert minimized.wait(timeout=1)
    finally:
        watcher.stop()

    user32.ShowWindowAsync.assert_called_once_with(100, auto_minimize._SW_MINIMIZE)
    assert callbacks == ["minimized"]


def test_non_windows_start_is_a_noop(monkeypatch) -> None:
    monkeypatch.setattr(auto_minimize.sys, "platform", "linux")
    watcher = auto_minimize.AutoMinimizeOnFocusLoss(
        "Dodaios",
        on_minimized=lambda: None,
        enabled=lambda: True,
    )

    watcher.start()

    assert watcher._thread is None


def test_uses_native_handle_and_waits_for_async_minimize(monkeypatch) -> None:
    minimized = threading.Event()
    foreground = [100, 200, 200]
    iconic_checks = 0

    def is_iconic(_hwnd: int) -> bool:
        nonlocal iconic_checks
        iconic_checks += 1
        # The native GUI thread applies ShowWindowAsync on a later poll.
        return iconic_checks >= 5

    def process_id(hwnd: int, result) -> int:
        result._obj.value = os.getpid() if hwnd == 100 else os.getpid() + 1
        return 1

    user32 = Mock()
    user32.FindWindowW = Mock(return_value=0)
    user32.GetForegroundWindow = Mock(
        side_effect=lambda: foreground.pop(0) if foreground else 200
    )
    user32.GetWindowThreadProcessId = Mock(side_effect=process_id)
    user32.GetAncestor = Mock(side_effect=lambda hwnd, _kind: hwnd)
    user32.IsWindowVisible = Mock(return_value=True)
    user32.IsIconic = Mock(side_effect=is_iconic)
    user32.ShowWindowAsync = Mock(return_value=True)

    monkeypatch.setattr(auto_minimize.sys, "platform", "win32")
    monkeypatch.setattr(ctypes, "WinDLL", Mock(return_value=user32), raising=False)

    watcher = auto_minimize.AutoMinimizeOnFocusLoss(
        "Dodaios",
        window_handle=lambda: 100,
        on_minimized=minimized.set,
        enabled=lambda: True,
        poll_interval_s=0.05,
        grace_s=0,
    )
    watcher.start()
    try:
        assert minimized.wait(timeout=1)
    finally:
        watcher.stop()

    user32.FindWindowW.assert_not_called()
    user32.ShowWindowAsync.assert_called_once_with(100, auto_minimize._SW_MINIMIZE)
