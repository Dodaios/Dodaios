"""The Windows folder window, shown by a short-lived Python process.

Run as a file, never imported by the app::

    python -I -S folder_dialog_win.py <owner hwnd or 0> [start folder]

It shows the Common Item Dialog (``IFileOpenDialog`` with the pick-folders
option) — the window Explorer and every modern app use, with the sidebar, the
address bar and search — and prints the chosen path between two markers.
Exit code 0 with a path is an answer, exit code 1 is a cancelled window, and
anything else is a failure the caller answers with its PowerShell fallback.

**Why not PowerShell.** The first version compiled a C# declaration of the same
COM interface in PowerShell on every click. Measured on a fast machine, the
window appeared 2.4 to 3.3 seconds after the click, which reads as "Browse does
nothing". This file talks to the same interface through ``ctypes`` and needs
only the standard library, so the window is there in a fraction of a second.

**Why it has an owner.** The window is owned by the app window the click came
from. Windows then keeps it in front of the app, centres it there, and gives it
back the focus when it closes, the way an Open dialog behaves in any program.
Without an owner the window was held in front by an always-on-top helper form,
so it also covered every other program and had no place in the taskbar.

Standard library only, and no import from ``dodaios``: importing the package
would cost more time than the window itself.
"""

from __future__ import annotations

import ctypes
import sys
import threading
import time
from ctypes import POINTER, byref, c_int, c_uint, c_void_p, c_wchar_p, wintypes

BEGIN = "<<<JARVIS-FOLDER>>>"
END = "<<<END-JARVIS-FOLDER>>>"
TITLE = "Choose the folder the agents should work in"

EXIT_PICKED = 0
EXIT_CANCELLED = 1
EXIT_FAILED = 3

_FOS_PICKFOLDERS = 0x00000020
_FOS_FORCEFILESYSTEM = 0x00000040
_FOS_PATHMUSTEXIST = 0x00000800
_SIGDN_FILESYSPATH = 0x80058000
_CLSCTX_INPROC_SERVER = 0x1
_COINIT_APARTMENTTHREADED = 0x2
_HRESULT_CANCELLED = 0x800704C7  # HRESULT_FROM_WIN32(ERROR_CANCELLED)

# Positions in the COM method tables. The order is the binary contract:
# IUnknown (0-2), IModalWindow.Show (3), then IFileDialog in declaration order.
_RELEASE = 2
_SHOW = 3
_SET_OPTIONS = 9
_SET_FOLDER = 12
_SET_TITLE = 17
_SET_OK_LABEL = 18
_GET_RESULT = 20
_ITEM_GET_DISPLAY_NAME = 5


class _Guid(ctypes.Structure):
    _fields_ = [
        ("data1", wintypes.DWORD),
        ("data2", wintypes.WORD),
        ("data3", wintypes.WORD),
        ("data4", ctypes.c_ubyte * 8),
    ]


def _guid(text: str) -> _Guid:
    out = _Guid()
    ctypes.oledll.ole32.CLSIDFromString(c_wchar_p(text), byref(out))
    return out


def _method(pointer: c_void_p, index: int, *argtypes: object) -> object:
    """One method of a COM object, called through its method table."""
    table = ctypes.cast(pointer, POINTER(POINTER(c_void_p))).contents
    prototype = ctypes.WINFUNCTYPE(ctypes.c_long, c_void_p, *argtypes)
    return prototype(table[index])


def _check(result: int) -> None:
    if result < 0:
        raise OSError(f"COM call failed: 0x{result & 0xFFFFFFFF:08X}")


class _MonitorInfo(ctypes.Structure):
    _fields_ = [
        ("size", wintypes.DWORD),
        ("monitor", wintypes.RECT),
        ("work", wintypes.RECT),
        ("flags", wintypes.DWORD),
    ]


def _centre_over(window: int, owner: int) -> None:
    """Put the folder window in the middle of the window that owns it.

    Windows remembers where this dialog last stood for each program, and for a
    helper process that place is the top-left corner of the screen: far from
    the app on a wide monitor, and on the wrong screen with two. Its size is
    left alone, because that part of the memory is the person's own choice.
    """
    user32 = ctypes.windll.user32
    own, over = wintypes.RECT(), wintypes.RECT()
    if not user32.GetWindowRect(window, byref(own)) or not user32.GetWindowRect(owner, byref(over)):
        return
    width, height = own.right - own.left, own.bottom - own.top
    left = (over.left + over.right - width) // 2
    top = (over.top + over.bottom - height) // 2
    info = _MonitorInfo()
    info.size = ctypes.sizeof(_MonitorInfo)
    monitor = user32.MonitorFromWindow(wintypes.HWND(owner), 2)  # nearest monitor
    if monitor and user32.GetMonitorInfoW(wintypes.HANDLE(monitor), byref(info)):
        work = info.work
        left = max(work.left, min(left, work.right - width))
        top = max(work.top, min(top, work.bottom - height))
    # No size change, no z-order change, no activation: position only.
    user32.SetWindowPos(wintypes.HWND(window), None, left, top, 0, 0, 0x0001 | 0x0004 | 0x0010)


def _bring_forward(stop: threading.Event, owner: int) -> None:
    """Centre the folder window and give it the keyboard as soon as it exists.

    A window opened by a background process is shown but not always focused.
    The app passed its foreground right on before it started this process, so
    the request is honoured here; where it is not, the window is still in front
    of its owner and only waits for a click.
    """
    user32 = ctypes.windll.user32
    user32.FindWindowW.restype = wintypes.HWND
    own = ctypes.windll.kernel32.GetCurrentProcessId()
    deadline = time.monotonic() + 5.0
    while not stop.is_set() and time.monotonic() < deadline:
        window = user32.FindWindowW("#32770", TITLE)
        if window:
            process = wintypes.DWORD()
            user32.GetWindowThreadProcessId(wintypes.HWND(window), byref(process))
            if process.value == own and user32.IsWindowVisible(wintypes.HWND(window)):
                if owner:
                    _centre_over(window, owner)
                user32.SetForegroundWindow(wintypes.HWND(window))
                return
        time.sleep(0.01)


def choose(owner: int, start: str) -> str | None:
    """Show the window. The chosen folder, or None when it was closed."""
    ole32 = ctypes.oledll.ole32
    ole32.CoInitializeEx(None, _COINIT_APARTMENTTHREADED)
    dialog = c_void_p()
    _check(
        ctypes.windll.ole32.CoCreateInstance(
            byref(_guid("{DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7}")),
            None,
            _CLSCTX_INPROC_SERVER,
            byref(_guid("{42F85136-DB7E-439C-85F1-E4075D135FC8}")),
            byref(dialog),
        )
    )
    item_iid = _guid("{43826D1E-E718-42EE-BC55-A1E261C37BFE}")
    try:
        _check(
            _method(dialog, _SET_OPTIONS, c_uint)(
                dialog, _FOS_PICKFOLDERS | _FOS_FORCEFILESYSTEM | _FOS_PATHMUSTEXIST
            )
        )
        _method(dialog, _SET_TITLE, c_wchar_p)(dialog, TITLE)
        _method(dialog, _SET_OK_LABEL, c_wchar_p)(dialog, "Use this folder")
        if start:
            # A start folder is a nicety, never a reason to fail.
            folder = c_void_p()
            made = ctypes.windll.shell32.SHCreateItemFromParsingName(
                c_wchar_p(start), None, byref(item_iid), byref(folder)
            )
            if made >= 0 and folder:
                _method(dialog, _SET_FOLDER, c_void_p)(dialog, folder)
                _method(folder, _RELEASE)(folder)

        stop = threading.Event()
        threading.Thread(target=_bring_forward, args=(stop, owner), daemon=True).start()
        try:
            shown = _method(dialog, _SHOW, wintypes.HWND)(dialog, owner or None)
        finally:
            stop.set()
        if shown & 0xFFFFFFFF == _HRESULT_CANCELLED:
            return None
        _check(shown)

        result = c_void_p()
        _check(_method(dialog, _GET_RESULT, POINTER(c_void_p))(dialog, byref(result)))
        try:
            name = c_wchar_p()
            _check(
                _method(result, _ITEM_GET_DISPLAY_NAME, c_int, POINTER(c_wchar_p))(
                    result, c_int(_SIGDN_FILESYSPATH - 0x100000000), byref(name)
                )
            )
            path = name.value
            ctypes.windll.ole32.CoTaskMemFree(name)
            return path or None
        finally:
            _method(result, _RELEASE)(result)
    finally:
        _method(dialog, _RELEASE)(dialog)
        ole32.CoUninitialize()


def main(argv: list[str]) -> int:
    try:
        owner = int(argv[1]) if len(argv) > 1 else 0
    except ValueError:  # no usable owner: the window opens unowned
        owner = 0
    start = argv[2] if len(argv) > 2 else ""
    try:
        picked = choose(owner, start)
    except Exception as exc:  # noqa: BLE001 - the caller falls back on any failure
        sys.stderr.write(f"{type(exc).__name__}: {exc}\n")
        return EXIT_FAILED
    if not picked:
        return EXIT_CANCELLED
    # The answer is a PATH, so the bytes are pinned to UTF-8: the console
    # codepage would mangle every folder with an umlaut in its name.
    sys.stdout.buffer.write(f"{BEGIN}\n{picked}\n{END}\n".encode())
    sys.stdout.flush()
    return EXIT_PICKED


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
