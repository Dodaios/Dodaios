"""Voice-call chats: binding, history and turn import."""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Callable, Sequence
from typing import Any

from dodaios.agent_chat import service as _s
from dodaios.agent_chat.store import (
    AgentChatSession,
)


class VoiceMixin:
    """Voice-call chats: binding, history and turn import."""

    # ------------------------------------------------------------ voice chat

    @property
    def voice_chat_id(self) -> str | None:
        """The Jarvis chat the next voice call continues, if one is bound."""
        return self._voice_chat_id

    @property
    def voice_chat_fresh(self) -> bool:
        """True while a blank page is open: the next call opens a new chat."""
        return self._voice_chat_fresh

    @property
    def voice_session_continued(self) -> str | None:
        """The archived voice chat calls are recorded into, if one is on stage."""
        from dodaios.sessions.continuation import continued_voice_session

        return continued_voice_session()

    def bind_voice_chat(
        self,
        session_id: str | None,
        *,
        voice_session: str | None = None,
        voice_history: Callable[[], list[Any]] | None = None,
    ) -> str | None:
        """Make ``session_id`` the chat voice calls continue; ``None`` = a new one.

        ``voice_session`` puts an ARCHIVED voice chat on stage instead (a
        history row of ``sessions.db``): the recorder files the next calls
        into that row rather than a new one (dodaios/sessions/continuation.py),
        no typed chat receives the turns, and ``voice_history`` answers each
        call's starting context. Any other binding ends that continuation.

        The front page shows one Jarvis chat at a time. A call started there
        — the composer's voice button or the wake word — belongs to THAT
        chat: its turns are filed into it (voice_mirror) and it starts with
        that chat's history as context (``BrainManager.take_voice_history_seed``
        asks :meth:`voice_chat_history`). Binding a chat also drops an older
        explicit seed nobody consumed, which would otherwise hand the call
        another conversation's memory.
        """
        from dodaios.agent_chat import runner_brain
        from dodaios.sessions.continuation import continue_voice_session

        brain = runner_brain.brain_manager()
        archived = (voice_session or "").strip() or None
        continue_voice_session(archived if session_id is None else None)
        self._voice_archive_history = voice_history if archived and session_id is None else None
        if session_id is None and archived:
            self._voice_chat_id = None
            self._voice_chat_fresh = False
        else:
            if session_id is None:
                # No "blank page" any more: a call without a chosen chat
                # continues the lead's one conversation.
                from dodaios.agent_chat.lead import lead_session

                lead = lead_session(self)
                session_id = lead.session_id if lead is not None else None
        if session_id is None:
            self._voice_chat_id = None
        else:
            session = self.store.get_session(session_id)
            if session is None or session.surface != "jarvis":
                raise _s.NoSuchSession(session_id)
            self._voice_chat_id = session_id
            self._voice_chat_fresh = False
            drop = getattr(brain, "drop_voice_history_seed", None)
            if callable(drop):
                drop()
        attach = getattr(brain, "set_voice_history_source", None)
        if callable(attach):
            attach(self.voice_chat_history)
        return self._voice_chat_id

    def voice_chat_history(self) -> list[Any]:
        """The bound chat's turns as call context — empty when none is bound."""
        archive = self._voice_archive_history
        if archive is not None and self.voice_session_continued:
            return archive()
        from dodaios.agent_chat import lead

        session_id = self._voice_chat_id
        if not session_id or self.store.get_session(session_id) is None:
            # Nothing chosen on screen: the call continues the lead's conversation.
            current = lead.lead_session(self)
            session_id = current.session_id if current is not None else None
        if not session_id:
            return []
        events = self.store.list_events(session_id)
        if lead.is_lead(self, session_id):
            return lead.voice_history(session_id, events)
        return _s.brain_history_from_events(events)

    def lead_session(self) -> AgentChatSession | None:
        """The lead's one endless conversation (see ``agent_chat/lead.py``)."""
        from dodaios.agent_chat.lead import lead_session

        return lead_session(self)

    def voice_call_chat(self, call_id: str) -> str | None:
        """The chat a running call already files into, if its first turn landed."""
        return self._voice_call_chats.get(call_id) if call_id else None

    def pin_voice_call(self, call_id: str, session_id: str) -> None:
        """Keep every later turn of ``call_id`` in ``session_id``."""
        if not call_id:
            return
        if len(self._voice_call_chats) > 200:
            self._voice_call_chats.clear()
        self._voice_call_chats[call_id] = session_id

    def _claim_voice_turn(self, voice_turn_id: str, session_id: str) -> bool:
        """True the first time this voice turn is filed, also across restarts."""
        claim = getattr(self.store, "claim_voice_turn", None)
        if claim is not None:
            try:
                return bool(claim(voice_turn_id, session_id))
            except sqlite3.Error:
                _s.log.warning("agent chat: voice turn id not stored", exc_info=True)
        if voice_turn_id in self._mirrored_voice_turns:
            return False
        self._mirrored_voice_turns.add(voice_turn_id)
        if len(self._mirrored_voice_turns) > 2000:
            self._mirrored_voice_turns.clear()
        return True

    async def import_voice_turn(
        self,
        session_id: str,
        user_text: str,
        assistant_text: str,
        *,
        provider: str = "",
        model: str = "",
        voice_turn_id: str = "",
        tool_calls: Sequence[str | dict[str, Any]] = (),
    ) -> str | None:
        """File one SPOKEN turn into a session's timeline, without answering it.

        The voice paths (desktop pipeline, realtime, browser microphone) talk
        to the same assistant as this typed chat but keep their own history —
        so a spoken question and its spoken answer never appeared here, and
        reopening the chat after talking showed nothing of it. This writes the
        turn's two texts as ordinary timeline events (``user_message`` plus a
        finished voice turn), so the chat reads the same whether a turn was
        spoken or typed, and the next typed turn sees the spoken words in its
        history.

        Deliberately NOT a turn: no runner starts, nothing streams, and a
        session that is busy typing keeps running — the imported turn simply
        lands after it. ``runner`` is ``"voice"`` so a later reader can tell
        how the turn was said. Returns the imported turn id, or ``None`` when
        there was nothing worth keeping (both texts empty) or this voice turn
        was already imported.

        ``tool_calls`` are the tools the call ran (a name, or a dict with
        ``name`` and a short ``output``); they are filed as ``tool_call`` /
        ``tool_result`` pairs before the reply, so the next typed turn can tell
        a call that sent the mail from one that only talked about it. What the
        person said also feeds the proactive cues (open loops, check-ins) like
        a typed turn of the lead's conversation does.
        """
        user = (user_text or "").strip()
        reply = (assistant_text or "").strip()
        if not user and not reply:
            return None
        session = self.store.get_session(session_id)
        if session is None:
            raise _s.NoSuchSession(session_id)
        if voice_turn_id:
            if not self._claim_voice_turn(voice_turn_id, session_id):
                return None
        if user:
            await self._emit(session_id, _s.make_event("user_message", {"text": user}))
            if session.surface == "jarvis":
                await self._read_voice_cues(session_id, user, tool_calls)
        if not reply:
            return None
        turn_id = uuid.uuid4().hex
        message_id = uuid.uuid4().hex
        pick = (provider or session.provider or "").strip()
        if not _s.offers(session.surface, pick):
            pick = session.provider
        await self._emit(
            session_id,
            _s.make_event(
                "turn_started",
                {
                    "turn_id": turn_id,
                    "provider": pick,
                    "model": model or session.model,
                    "effort": _s.normalize_effort(session.provider, session.effort),
                    "runner": "voice",
                    "surface": session.surface,
                },
            ),
        )
        for name, output in _s._voice_tool_records(tool_calls):
            call_id = f"voice_{uuid.uuid4().hex[:12]}"
            await self._emit(
                session_id,
                _s.make_event(
                    "tool_call",
                    {"turn_id": turn_id, "call_id": call_id, "name": name, "input": {}},
                ),
            )
            await self._emit(
                session_id,
                _s.make_event(
                    "tool_result",
                    {
                        "turn_id": turn_id,
                        "call_id": call_id,
                        "name": name,
                        "output": output,
                        "is_error": False,
                        "duration_ms": 0,
                    },
                ),
            )
        await self._emit(
            session_id,
            _s.make_event(
                "assistant_text",
                {"turn_id": turn_id, "message_id": message_id, "text": reply},
            ),
        )
        await self._emit(
            session_id,
            _s.make_event(
                "turn_finished",
                {
                    "turn_id": turn_id,
                    "status": "done",
                    "duration_ms": 0,
                    "usage": {},
                    "error": None,
                },
            ),
        )
        return turn_id

    async def _read_voice_cues(
        self, session_id: str, user_text: str, tool_calls: Sequence[str | dict[str, Any]]
    ) -> None:
        """Open loops and check-ins from a spoken turn; never breaks the import."""
        try:
            from dodaios.agent_chat.surface_kits import read_proactive_cues

            names = tuple(name for name, _output in _s._voice_tool_records(tool_calls))
            await read_proactive_cues(session_id, user_text, names)
        except Exception:  # noqa: BLE001 — a missed cue is not worth a lost transcript
            _s.log.warning(
                "agent chat %s: cues not read from a voice turn", session_id, exc_info=True
            )
