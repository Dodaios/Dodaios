"""``ensure_normal_process_priority`` — the BUG-204-amplifier repair.

The old autostart Scheduled Task registered without ``-Priority`` and Task
Scheduler's default (7) started the whole tree BelowNormal. The repair must
only ever RAISE BelowNormal/Idle to Normal, never demote, and must be a quiet
no-op off Windows (macOS/Linux login launches already start at normal
priority).
"""

from __future__ import annotations

import sys

import pytest

from dodaios.core import process_utils


class _FakeKernel32:
    """Capability fake for the two Win32 calls the repair makes."""

    def __init__(self, current_class: int, set_ok: bool = True) -> None:
        self.current_class = current_class
        self.set_ok = set_ok
        self.set_calls: list[int] = []

    def GetCurrentProcess(self) -> int:  # noqa: N802 — Win32 spelling
        return -1

    def GetPriorityClass(self, _handle: int) -> int:  # noqa: N802
        return self.current_class

    def SetPriorityClass(self, _handle: int, new_class: int) -> int:  # noqa: N802
        self.set_calls.append(new_class)
        return 1 if self.set_ok else 0


class _FakeCtypes:
    def __init__(self, kernel32: _FakeKernel32) -> None:
        self.windll = type("windll", (), {"kernel32": kernel32})()


def _run_with(monkeypatch: pytest.MonkeyPatch, kernel32: _FakeKernel32) -> str | None:
    monkeypatch.setattr(process_utils.sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "ctypes", _FakeCtypes(kernel32))
    return process_utils.ensure_normal_process_priority()


def test_off_windows_is_a_quiet_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(process_utils.sys, "platform", "linux")
    assert process_utils.ensure_normal_process_priority() is None


def test_raises_below_normal_to_normal(monkeypatch: pytest.MonkeyPatch) -> None:
    kernel32 = _FakeKernel32(current_class=0x00004000)  # BELOW_NORMAL
    detail = _run_with(monkeypatch, kernel32)
    assert detail == "BelowNormal -> Normal"
    assert kernel32.set_calls == [0x00000020]  # NORMAL


def test_raises_idle_to_normal(monkeypatch: pytest.MonkeyPatch) -> None:
    kernel32 = _FakeKernel32(current_class=0x00000040)  # IDLE
    detail = _run_with(monkeypatch, kernel32)
    assert detail == "Idle -> Normal"
    assert kernel32.set_calls == [0x00000020]


def test_never_touches_a_normal_or_higher_class(monkeypatch: pytest.MonkeyPatch) -> None:
    for cls in (0x00000020, 0x00008000, 0x00000080):  # NORMAL, ABOVE_NORMAL, HIGH
        kernel32 = _FakeKernel32(current_class=cls)
        assert _run_with(monkeypatch, kernel32) is None
        assert kernel32.set_calls == []


def test_failed_set_is_reported_as_nothing_done(monkeypatch: pytest.MonkeyPatch) -> None:
    kernel32 = _FakeKernel32(current_class=0x00004000, set_ok=False)
    assert _run_with(monkeypatch, kernel32) is None


# ---------------------------------------------------------------------------
# ``prefer_child_process``: a helper somebody waits on runs ahead of builds
# ---------------------------------------------------------------------------


class _ChildKernel32:
    """Capability fake for the three Win32 calls the preference makes."""

    def __init__(self, handle: int = 77, set_ok: bool = True) -> None:
        self.handle = handle
        self.set_ok = set_ok
        self.opened: list[tuple[int, int]] = []
        self.set_calls: list[int] = []
        self.closed = 0
        # A function object, so the call under test can set ``restype`` on it
        # the way it does on the real foreign function.
        self.OpenProcess = lambda access, _inherit, pid: self._open(access, pid)  # noqa: N815

    def _open(self, access: int, pid: int) -> int:
        self.opened.append((access, pid))
        return self.handle

    def SetPriorityClass(self, _handle: object, new_class: int) -> int:  # noqa: N802
        self.set_calls.append(new_class)
        return 1 if self.set_ok else 0

    def CloseHandle(self, _handle: object) -> int:  # noqa: N802
        self.closed += 1
        return 1


class _ChildCtypes:
    c_void_p = staticmethod(lambda value=None: value)

    def __init__(self, kernel32: _ChildKernel32) -> None:
        self.windll = type("windll", (), {"kernel32": kernel32})()


def test_a_child_is_put_one_class_above_normal(monkeypatch: pytest.MonkeyPatch) -> None:
    kernel32 = _ChildKernel32()
    monkeypatch.setattr(process_utils.sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "ctypes", _ChildCtypes(kernel32))

    assert process_utils.prefer_child_process(4242) is True

    assert kernel32.opened == [(0x0200, 4242)]  # PROCESS_SET_INFORMATION only
    assert kernel32.set_calls == [0x00008000]  # ABOVE_NORMAL, never HIGH
    assert kernel32.closed == 1


def test_a_child_that_cannot_be_opened_is_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    kernel32 = _ChildKernel32(handle=0)
    monkeypatch.setattr(process_utils.sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "ctypes", _ChildCtypes(kernel32))

    assert process_utils.prefer_child_process(4242) is False
    assert kernel32.set_calls == []
    assert kernel32.closed == 0


def test_preferring_a_child_is_a_quiet_noop_off_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    for platform in ("linux", "darwin"):
        monkeypatch.setattr(process_utils.sys, "platform", platform)
        assert process_utils.prefer_child_process(4242) is False


@pytest.mark.skipif(sys.platform != "win32", reason="priority classes are a Windows concept")
def test_a_real_child_really_runs_one_class_above_normal() -> None:
    import subprocess

    import psutil

    child = subprocess.Popen(  # noqa: S603 — our own interpreter, a fixed script
        [sys.executable, "-c", "import time; time.sleep(30)"],
        creationflags=process_utils.NO_WINDOW_CREATIONFLAGS,
    )
    try:
        assert process_utils.prefer_child_process(child.pid) is True
        assert psutil.Process(child.pid).nice() == psutil.ABOVE_NORMAL_PRIORITY_CLASS
    finally:
        child.kill()
        child.wait(timeout=10)
