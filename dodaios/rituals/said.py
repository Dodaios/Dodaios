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
* In a live call the provider's model hears the sentence itself, so it gets a
  tool that names the phrases to listen for (:func:`live_start`); the decision
  whether one starts stays the same words-and-clock check.
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


def live_phrases() -> list[str]:
    """The phrases of every ritual that is on, for a live voice model to listen for.

    Never raises: a store that cannot be read means there is nothing to listen for.
    """
    try:
        from . import service

        return [
            phrase
            for ritual in service.list_rituals()
            if ritual.enabled
            for phrase in ritual.phrases
        ]
    except Exception:  # noqa: BLE001 — the live call goes on without rituals
        log.debug("rituals: phrases unreadable for the live call", exc_info=True)
        return []


def live_tool_description(phrases: list[str]) -> str:
    """What a live voice model is told about the ``start_ritual`` tool."""
    quoted = ", ".join(f'"{phrase}"' for phrase in phrases[:40])
    return (
        "The user's rituals: sequences they set up to start with a short phrase. When the "
        "user says one of these phrases and nothing else (your name before or after it is "
        f"fine), call this with what they said BEFORE you answer: {quoted}. Then read the "
        "returned 'say' aloud as it is and add nothing. With started=false no ritual "
        "starts right now: answer the user as usual."
    )


async def live_start(phrase: str, *, language: str | None = None) -> dict[str, Any]:
    """The ``start_ritual`` tool of a live call: start it and hand back what to say."""
    spoken = await spoken_answer(phrase, language=language)
    if spoken is None:
        return {"success": True, "started": False}
    return {"success": True, "started": True, "say": spoken}


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


__all__ = [
    "announce_late",
    "install",
    "live_phrases",
    "live_start",
    "live_tool_description",
    "spoken_answer",
    "typed",
]
