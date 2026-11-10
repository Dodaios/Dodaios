"""From the "needs you" list to the operating system.

:mod:`dodaios.agent_chat.attention` already decides which change in the list
of things waiting on the person is news (``needs_input``, ``done``) and
publishes :class:`AgentAttentionChanged`. The web app shows it as a badge and
an in-app toast. This bridge adds the part the window cannot do while it is in
the background: a desktop notification, through the notifier's gate (the
person's choice per kind, quiet hours, and "not while the app is in front").

Kinds: a waiting approval is ``approval``; a question, credential or proposal
is ``needs_you``; a finished job is ``finished``.
"""

from __future__ import annotations

import logging
from typing import Any

from dodaios.agent_chat.attention import AgentAttentionChanged
from dodaios.notify.notifier import Notifier
from dodaios.notify.reminders import notification_language, phrase

log = logging.getLogger(__name__)


def kind_of(note: Any) -> str | None:
    """The notification kind for an attention change, ``None`` when it is no news."""
    transition = str(getattr(note, "transition", "") or "")
    if transition == "done":
        return "finished"
    if transition == "needs_input":
        return "approval" if getattr(note, "kind", "") == "approval" else "needs_you"
    return None


def texts_of(note: Any, kind: str) -> tuple[str, str]:
    """``(title, body)`` in the person's language."""
    summary = str(getattr(note, "summary", "") or "").strip()
    agent = str(getattr(note, "agent_name", "") or "").strip()
    lang = notification_language(summary or agent)
    agent = agent or phrase("an_agent", lang)
    if kind == "finished":
        return phrase("finished_title", lang, agent=agent), phrase("finished_body", lang)
    if kind == "approval":
        return phrase("approval_title", lang, agent=agent), summary or phrase("approval_body", lang)
    return phrase("needs_you_title", lang, agent=agent), summary or phrase("needs_you_body", lang)


class AttentionBridge:
    def __init__(self, notifier: Notifier) -> None:
        self._notifier = notifier

    async def on_change(self, event: Any) -> None:
        try:
            kind = kind_of(event)
            if kind is None:
                return
            title, body = texts_of(event, kind)
            await self._notifier.notify(
                kind,
                title,
                body,
                session_id=str(getattr(event, "session_id", "") or ""),
                message_id="",
            )
        except Exception:  # noqa: BLE001 — a subscriber never raises into the bus
            log.warning("notify: attention change not forwarded", exc_info=True)


def install(bus: Any, notifier: Notifier) -> AttentionBridge:
    bridge = AttentionBridge(notifier)
    bus.subscribe(AgentAttentionChanged, bridge.on_change)
    return bridge


__all__ = ["AttentionBridge", "install", "kind_of", "texts_of"]
