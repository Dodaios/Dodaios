"""A ritual started by what was said or typed, and what the voice says for it.

Both ways in are decided by words alone (:func:`dodaios.rituals.service.find_match`):
no model reads the sentence. When it is a ritual's phrase and the ritual's
conditions hold, the ritual starts and the sentence is not answered as an
ordinary turn. Anything else is left to the assistant.

* Spoken (:func:`spoken_answer`): the voice says what was gathered ahead for
  the ritual, in the form made for the ear. With nothing gathered yet it says
  one short line, and what arrives later is said when the call is still open
  (:func:`announce_late`); the written card is in the conversation either way.
* Typed into the lead's conversation (:func:`typed`): the card is the answer.
"""

from __future__ import annotations

import logging
from typing import Any

from .models import Ritual, RitualDay, RitualError

log = logging.getLogger(__name__)

#: The app's event bus, set at start (:func:`install`); announcements go through it.
_bus: Any = None


def install(bus: Any) -> None:
    """Remember the app's bus, so what arrives late can be said in an open call."""
    global _bus
    _bus = bus


async def _start(text: str, *, via: str, wake_phrase: str | None) -> dict[str, Any] | None:
    """Start the ritual ``text`` names, or ``None`` when it is an ordinary sentence."""
    from . import service

    found = service.find_match(text, wake_phrase=wake_phrase)
    if found is None or not found.fires:
        return None
    try:
        return await service.fire(found.ritual.id, via=via, said=text)
    except RitualError as exc:
        # Somebody else's start won the day, or the assistant is not up yet:
        # the sentence is an ordinary one after all.
        log.info("rituals: %r did not start %s (%s)", text[:60], found.ritual.id, exc.message)
        return None


async def spoken_answer(
    text: str, *, language: str | None = None, wake_phrase: str | None = None
) -> str | None:
    """What to say when ``text`` starts a ritual; ``None`` when it starts none.

    Never raises: a sentence that cannot be looked at is an ordinary one.
    """
    try:
        started = await _start(text, via="voice", wake_phrase=wake_phrase)
    except Exception:  # noqa: BLE001 — the assistant answers the sentence instead
        log.warning("rituals: spoken phrase not looked at", exc_info=True)
        return None
    if started is None:
        return None
    spoken = str(started.get("spoken") or "").strip()
    if spoken:
        return spoken
    from dodaios.i18n import catalog

    key = "speech.ritual.pending" if started.get("pending") else "speech.ritual.started"
    return catalog.t(key, language)


async def typed(svc: Any, session_id: str, text: str, *, has_attachments: bool = False) -> str:
    """The id of the ritual a typed message started, ``""`` for an ordinary message.

    Only in the lead's own conversation, and only for a bare sentence: a
    message with a picture or a file is something to answer. Never raises.
    """
    if has_attachments or not str(text or "").strip():
        return ""
    try:
        from dodaios.agent_chat.lead import is_lead

        if not is_lead(svc, session_id):
            return ""
        started = await _start(text, via="chat", wake_phrase=None)
    except Exception:  # noqa: BLE001 — the assistant answers the message instead
        log.warning("rituals: typed phrase not looked at", exc_info=True)
        return ""
    return str(started["ritual"]["id"]) if started is not None else ""


async def announce_late(ritual: Ritual, day: RitualDay) -> None:
    """Say what was gathered once it is there, for a ritual that was started by voice.

    The voice speaks it only inside a call that is still open; otherwise the
    card in the conversation is what the person finds. Never raises.
    """
    if _bus is None or day.fired_via != "voice" or not day.spoken.strip():
        return
    try:
        from dodaios.core.events import AnnouncementRequested

        await _bus.publish(
            AnnouncementRequested(
                text=day.spoken.strip(),
                kind="completion",
                source_layer="rituals.service",
            )
        )
    except Exception:  # noqa: BLE001 — the written card already reached the conversation
        log.warning("rituals: late result of %s not announced", ritual.id, exc_info=True)


__all__ = ["announce_late", "install", "spoken_answer", "typed"]
