"""The gate between a thing worth telling and the operating system.

``Notifier.notify()`` checks the person's settings (the one switch, the
kind, quiet hours), stays quiet while the app window is in front (the
conversation already shows it), and otherwise hands the text to
:mod:`dodaios.notify.desktop`. Every decision is returned as a
:class:`Verdict`, so nothing fails silently.

A click brings the app window forward (the ``focus`` callable the app wires
in) and publishes :class:`NotificationOpened` on the app bus; the web app
opens the conversation at that message.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from dodaios.core.events import Event
from dodaios.notify import desktop
from dodaios.notify.settings import KINDS, NotifySettings, load_settings

log = logging.getLogger(__name__)

#: Verdict reasons a notification was held back.
HELD_OFF: Final[str] = "off"
HELD_KIND: Final[str] = "kind_off"
HELD_QUIET: Final[str] = "quiet_hours"
HELD_LOOKING: Final[str] = "looking"
HELD_UNKNOWN_KIND: Final[str] = "unknown_kind"


@dataclass(frozen=True, slots=True)
class NotificationOpened(Event):
    """The person clicked a desktop notification: open the conversation there."""

    kind: str = ""
    session_id: str = ""
    message_id: str = ""


@dataclass(frozen=True, slots=True)
class Verdict:
    """What ``notify()`` did: shown, or why not (``held``), and how (``how``)."""

    shown: bool
    held: str = ""
    how: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"shown": self.shown, "held": self.held, "how": self.how}


FocusFn = Callable[[], Any]
ShowFn = Callable[..., str]
BusGetter = Callable[[], Any | None]


class Notifier:
    def __init__(
        self,
        *,
        bus: BusGetter | None = None,
        focus: FocusFn | None = None,
        show: ShowFn = desktop.show,
        settings: Callable[[], NotifySettings] = load_settings,
        app_focused: Callable[[], bool] | None = None,
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._bus = bus or (lambda: None)
        self._focus = focus
        self._show = show
        self._settings = settings
        self._app_focused = app_focused or (lambda: False)
        self._clock = clock
        self._loop: asyncio.AbstractEventLoop | None = None
        self.last: Verdict | None = None

    # ------------------------------------------------------------- deciding

    def verdict(self, kind: str, *, ignore_focus: bool = False) -> str | None:
        """Why ``kind`` would be held right now, or ``None`` to let it through."""
        if kind not in KINDS:
            return HELD_UNKNOWN_KIND
        settings = self._settings()
        if not settings.enabled:
            return HELD_OFF
        if not settings.allows(kind):
            return HELD_KIND
        if settings.quiet_hours.covers(self._clock()):
            return HELD_QUIET
        if not ignore_focus and self._looking():
            return HELD_LOOKING
        return None

    def _looking(self) -> bool:
        try:
            return bool(self._app_focused())
        except Exception:  # noqa: BLE001 — an unreadable focus means "not looking": tell
            log.debug("notify: focus state unreadable", exc_info=True)
            return False

    # -------------------------------------------------------------- showing

    async def notify(
        self,
        kind: str,
        title: str,
        body: str,
        *,
        session_id: str = "",
        message_id: str = "",
        ignore_focus: bool = False,
    ) -> Verdict:
        """Show a notification of ``kind`` unless the settings or the focus hold it."""
        held = self.verdict(kind, ignore_focus=ignore_focus)
        if held is not None:
            self.last = Verdict(False, held=held)
            log.debug("notify: %s held (%s)", kind, held)
            return self.last
        self._loop = asyncio.get_running_loop()
        on_click = self._click_handler(kind, session_id, message_id)
        how = await asyncio.to_thread(self._show, title, body, on_click=on_click)
        self.last = Verdict(how in (desktop.SHOWN, desktop.SHOWN_NO_CLICK), how=how)
        if not self.last.shown:
            log.info("notify: %s not shown (%s)", kind, how)
        return self.last

    def _click_handler(self, kind: str, session_id: str, message_id: str) -> Callable[[], None]:
        def _clicked() -> None:
            self.opened(kind, session_id, message_id)

        return _clicked

    def opened(self, kind: str, session_id: str = "", message_id: str = "") -> None:
        """A click (from any thread): raise the window, then tell the web app."""
        if self._focus is not None:
            try:
                self._focus()
            except Exception:  # noqa: BLE001 — the window may be gone; the event still goes out
                log.warning("notify: could not raise the app window", exc_info=True)
        event = NotificationOpened(
            kind=kind, session_id=session_id, message_id=message_id, source_layer="notify"
        )
        loop = self._loop
        bus = self._bus()
        if bus is None or loop is None or loop.is_closed():
            log.debug("notify: no bus to announce the click on")
            return

        def _publish() -> None:
            task = loop.create_task(bus.publish(event), name="notify-opened")
            task.add_done_callback(_log_publish_failure)

        try:
            # The toast thread is never the loop's thread; thread-safe hand-over.
            loop.call_soon_threadsafe(_publish)
        except RuntimeError:  # the loop stopped meanwhile: nobody to tell
            log.debug("notify: loop gone before the click could be announced")


def _log_publish_failure(task: asyncio.Task[Any]) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        log.warning("notify: could not publish the click: %s", exc)


# ------------------------------------------------------------ the shared one

_current: Notifier | None = None


def set_current(notifier: Notifier | None) -> None:
    global _current
    _current = notifier


def current_notifier() -> Notifier | None:
    """The app's notifier, ``None`` in a bare runtime (tests, CLI)."""
    return _current


__all__ = [
    "HELD_KIND",
    "HELD_LOOKING",
    "HELD_OFF",
    "HELD_QUIET",
    "HELD_UNKNOWN_KIND",
    "NotificationOpened",
    "Notifier",
    "Verdict",
    "current_notifier",
    "set_current",
]
