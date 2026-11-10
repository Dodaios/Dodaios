"""Mirror completed voice turns into the Jarvis agent-chat history.

Spoken and typed conversations reach the same assistant through different
stacks with different stores: a voice turn lands in ``sessions.db`` (and on
the voice stage's live transcript), a typed turn in ``agent_chat.db``. The
Jarvis agent card shows one of the two at a time (``Voice | Chat``), so a
spoken question and its spoken answer never appeared in the chat — switching
back from voice to chat showed nothing of what was just said.

This bridge closes that gap at the turn boundary, off the voice hot path
(AP-9): it subscribes to :class:`VoiceTurnCompleted` on the app bus and files
each turn's two texts into the lead's one conversation (``lead.py``) via
:meth:`AgentChatService.import_voice_turn` — no runner starts, nothing
re-answers, and a session that is busy typing keeps running. When the front
page bound a chat (``AgentChatService.bind_voice_chat``) the turn goes there
instead, and every turn of one call stays in the chat its first turn chose.
The imported turn also becomes context for the next typed turn, because the
API runner rebuilds its history from the same event log.

Only the lead's chat (surface ``jarvis``) is mirrored: the other society
agents have no microphone.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Final

log = logging.getLogger(__name__)

#: The one chat surface a voice turn belongs in (see module docstring).
SURFACE: Final[str] = "jarvis"


class VoiceChatMirror:
    """Bus subscriber that files voice turns into the Jarvis chat."""

    def __init__(self, get_service: Callable[[], Any | None]) -> None:
        self._get_service = get_service
        self._attached = False

    def attach(self, bus: Any) -> None:
        """Subscribe to completed voice turns. Idempotent."""
        if self._attached:
            return
        try:
            from dodaios.core.events import VoiceTurnCompleted

            bus.subscribe(VoiceTurnCompleted, self._on_turn)
        except Exception as exc:  # noqa: BLE001 — mirroring must never break boot
            log.warning("voice chat mirror could not attach: %s", exc)
            return
        self._attached = True
        log.info("VoiceChatMirror attached to bus")

    async def _on_turn(self, event: Any) -> None:
        """File one turn's texts into the conversation the call belongs to."""
        try:
            user_text = str(getattr(event, "user_text", "") or "")
            jarvis_text = str(getattr(event, "jarvis_text", "") or "")
            if not user_text.strip() and not jarvis_text.strip():
                return
            svc = self._get_service()
            if svc is None:
                return
            if getattr(svc, "voice_session_continued", None):
                # An archived voice chat is on stage: the recorder files this
                # turn into that row, and a typed copy would be a second chat.
                return
            call_id = str(getattr(event, "session_id", "") or "")
            session = self._target_session(svc, call_id, event)
            if session is None:
                return
            pin = getattr(svc, "pin_voice_call", None)
            if callable(pin):
                pin(call_id, session.session_id)
            await svc.import_voice_turn(
                session.session_id,
                user_text,
                jarvis_text,
                provider=str(getattr(event, "provider", "") or ""),
                model=str(getattr(event, "model", "") or ""),
                voice_turn_id=str(getattr(event, "turn_id", "") or ""),
            )
        except Exception as exc:  # noqa: BLE001 — an observer must never break a turn
            log.warning("voice chat mirror skipped a turn: %s", exc)

    @staticmethod
    def _target_session(svc: Any, call_id: str = "", event: Any = None) -> Any | None:
        """The chat this turn belongs in.

        In order: the chat this call already files into, the chat the front
        page bound (``AgentChatService.bind_voice_chat``), and otherwise the
        lead's one conversation (``agent_chat/lead.py``), created on first use.
        """
        try:
            for chat_id in (
                getattr(svc, "voice_call_chat", lambda _c: None)(call_id),
                getattr(svc, "voice_chat_id", None),
            ):
                if not chat_id:
                    continue
                session = svc.store.get_session(chat_id)
                if session is not None and session.surface == SURFACE:
                    return session
            from dodaios.agent_chat.lead import lead_session

            hint = str(getattr(event, "provider", "") or "") if event is not None else ""
            return lead_session(svc, provider_hint=hint)
        except Exception as exc:  # noqa: BLE001
            log.warning("voice chat mirror could not find the conversation: %s", exc)
            return None


__all__ = ["SURFACE", "VoiceChatMirror"]
