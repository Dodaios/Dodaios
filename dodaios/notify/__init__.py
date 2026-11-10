"""Reaching the person when the app is in the background.

The package has three parts, each small and testable on its own:

* :mod:`settings` — what the person allowed: the one switch, a choice per
  kind, quiet hours and whether approvals also go to their Telegram.
* :mod:`desktop` — the operating system's own notification (a Windows
  toast first; macOS and Linux fall back to their notification commands,
  anything else is a no-op). Silent text only: nothing here speaks.
* :mod:`notifier` — the gate between the two plus the click: a notification
  the person clicks brings the app window forward and opens the conversation
  at the message it is about (:class:`notifier.NotificationOpened`).

:mod:`reminders` turns plain speech ("remind me Friday at 9 about the taxes")
into memories with a due time in the personal memory vault and delivers them
on time as a notice in the lead conversation plus a desktop notification.
:mod:`attention_bridge` forwards "needs you", waiting approvals and finished
agents from the attention list to the notifier.
"""

from __future__ import annotations

from dodaios.notify.notifier import NotificationOpened, Notifier, Verdict, current_notifier
from dodaios.notify.settings import KINDS, NotifySettings, load_settings, save_settings

__all__ = [
    "KINDS",
    "NotificationOpened",
    "Notifier",
    "NotifySettings",
    "Verdict",
    "current_notifier",
    "load_settings",
    "save_settings",
]
