"""The operating system's own notification: a Windows toast first.

``show()`` is synchronous and may block for a moment (a subprocess spawn,
a window class registration); callers on the event loop run it in a thread.
It never raises: the result says what happened.

* Windows: ``win10toast-click`` (a desktop dependency already shipped with the
  app) draws the toast and calls back on a click. Without it, PowerShell
  shows a plain toast through the Windows runtime; a click then only
  dismisses it.
* macOS: ``osascript`` ``display notification``; no click callback.
* Linux: ``notify-send`` when installed; no click callback.
* Anything else, or a headless machine: ``unsupported``.

The text is the whole notification: nothing here plays a sound of its own or
speaks (the assistant never speaks uncalled).
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import threading
import types
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

log = logging.getLogger(__name__)

#: Longest title and body the system is handed; the rest stays in the app.
TITLE_CHARS: Final[int] = 64
BODY_CHARS: Final[int] = 240
#: Seconds a Windows toast stays before it closes on its own.
TOAST_SECONDS: Final[int] = 8

#: ``show()`` results.
SHOWN: Final[str] = "shown"
SHOWN_NO_CLICK: Final[str] = "shown_no_click"
UNSUPPORTED: Final[str] = "unsupported"
FAILED: Final[str] = "failed"

ClickFn = Callable[[], None]


def _trim(text: str, limit: int) -> str:
    one_line = " ".join(str(text or "").split())
    return one_line if len(one_line) <= limit else one_line[: limit - 1] + "…"


def app_icon() -> Path | None:
    """The app's ``.ico`` for the toast, when the repo or bundle ships one."""
    try:
        from dodaios.ui.icon_utils import project_icon_path

        path = Path(project_icon_path())
        return path if path.is_file() and path.suffix.lower() == ".ico" else None
    except Exception:  # noqa: BLE001 — the icon is cosmetic; the toast shows without it
        return None


def show(title: str, body: str, *, on_click: ClickFn | None = None) -> str:
    """Show one notification; returns one of the result constants."""
    title, body = _trim(title, TITLE_CHARS), _trim(body, BODY_CHARS)
    if not title and not body:
        return FAILED
    platform = sys.platform
    try:
        if platform == "win32":
            return _windows(title, body, on_click)
        if platform == "darwin":
            return _macos(title, body)
        return _linux(title, body)
    except Exception:  # noqa: BLE001 — a notification must never take the caller down
        log.warning("notify: desktop notification failed", exc_info=True)
        return FAILED


# ----------------------------------------------------------------- windows

_toaster: Any | None = None
_toaster_lock = threading.Lock()


def _windows(title: str, body: str, on_click: ClickFn | None) -> str:
    result = _windows_toast_library(title, body, on_click)
    if result is not None:
        return result
    return _windows_powershell(title, body)


def _pkg_resources_stand_in() -> types.ModuleType:
    """What ``win10toast-click`` imports for its default icon path.

    The library still imports the retired ``pkg_resources`` (setuptools) at
    import time, only to find its own icon file. The app always passes its own
    icon, so a stand-in that answers those two names is all the library needs
    on an installation without setuptools.
    """
    module = types.ModuleType("pkg_resources")

    class Requirement:
        @staticmethod
        def parse(name: str) -> str:
            return name

    def resource_filename(_requirement: Any, path: str) -> str:
        icon = app_icon()
        return str(icon) if icon else path

    module.Requirement = Requirement  # type: ignore[attr-defined]
    module.resource_filename = resource_filename  # type: ignore[attr-defined]
    return module


def _toaster_factory() -> Any | None:
    """The ``win10toast-click`` notifier, ``None`` when the library is missing."""
    try:
        import pkg_resources  # noqa: F401
    except ImportError:  # the stand-in above covers the library's one use of it
        sys.modules.setdefault("pkg_resources", _pkg_resources_stand_in())
    try:
        from win10toast_click import ToastNotifier
    except Exception:  # noqa: BLE001 — optional desktop dependency; PowerShell takes over
        log.info("notify: win10toast-click unavailable; PowerShell toasts without a click")
        return None
    return ToastNotifier()


def _windows_toast_library(title: str, body: str, on_click: ClickFn | None) -> str | None:
    """``win10toast-click``: a toast with a click callback. ``None`` when unavailable."""
    global _toaster
    with _toaster_lock:
        if _toaster is None:
            _toaster = _toaster_factory()
        toaster = _toaster
    if toaster is None:
        return None
    try:
        if toaster.notification_active():
            # The library shows one toast at a time; a second one would be
            # dropped on the floor. PowerShell shows it instead.
            return None
    except Exception:  # noqa: BLE001 — an unreadable state is treated as free
        log.debug("notify: toast state unreadable", exc_info=True)

    def _clicked() -> None:
        if on_click is None:
            return
        try:
            on_click()
        except Exception:  # noqa: BLE001 — a click handler fault must not kill the toast thread
            log.warning("notify: click handler failed", exc_info=True)

    icon = app_icon()
    shown = toaster.show_toast(
        title or " ",
        body or " ",
        icon_path=str(icon) if icon else None,
        duration=TOAST_SECONDS,
        threaded=True,
        callback_on_click=_clicked if on_click else None,
    )
    if shown is False:
        return None
    return SHOWN if on_click else SHOWN_NO_CLICK


def _ps_quote(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("'", "''")


def powershell_toast_script(title: str, body: str) -> str:
    """The PowerShell that shows a plain Windows toast (no click action)."""
    return (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
        "ContentType = WindowsRuntime] | Out-Null; "
        "$xml = New-Object Windows.Data.Xml.Dom.XmlDocument; "
        '$xml.LoadXml(\'<toast><visual><binding template="ToastGeneric">'
        f"<text>{_ps_quote(title)}</text><text>{_ps_quote(body)}</text>"
        '</binding></visual><audio silent="true"/></toast>\'); '
        "$toast = New-Object Windows.UI.Notifications.ToastNotification $xml; "
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("
        "'Dodaios').Show($toast)"
    )


def _windows_powershell(title: str, body: str) -> str:
    exe = shutil.which("powershell") or shutil.which("pwsh")
    if not exe:
        return UNSUPPORTED
    creation = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(  # noqa: S603 — fixed executable, text passed as one argument
        [
            exe,
            "-NoProfile",
            "-NonInteractive",
            "-WindowStyle",
            "Hidden",
            "-Command",
            powershell_toast_script(title, body),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creation,
    )
    return SHOWN_NO_CLICK


# ------------------------------------------------------------- macos, linux


def _osa_quote(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _macos(title: str, body: str) -> str:
    exe = shutil.which("osascript")
    if not exe:
        return UNSUPPORTED
    script = f'display notification "{_osa_quote(body)}" with title "{_osa_quote(title)}"'
    subprocess.Popen(  # noqa: S603 — fixed executable, text passed as one argument
        [exe, "-e", script],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return SHOWN_NO_CLICK


def _linux(title: str, body: str) -> str:
    exe = shutil.which("notify-send")
    if not exe:
        return UNSUPPORTED
    subprocess.Popen(  # noqa: S603 — fixed executable, text passed as arguments
        [exe, "--app-name=Dodaios", "--", title, body],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return SHOWN_NO_CLICK


__all__ = [
    "BODY_CHARS",
    "FAILED",
    "SHOWN",
    "SHOWN_NO_CLICK",
    "TITLE_CHARS",
    "UNSUPPORTED",
    "app_icon",
    "powershell_toast_script",
    "show",
]
