"""Subscribers, notices and the persist-then-fan-out event path."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from dodaios.agent_chat import service as _s
from dodaios.agent_chat.credential_requests import (
    CredentialSpec,
)

if TYPE_CHECKING:
    from dodaios.agent_chat.service import Subscriber


if TYPE_CHECKING:
    from dodaios.agent_chat.service_parts._host_state import AgentChatHostState as _HostBase
else:
    _HostBase = object


class EventsMixin(_HostBase):
    """Subscribers, notices and the persist-then-fan-out event path."""

    # ----------------------------------------------------------- subscribe

    def _drop_subscriber(self, session_id: str, q: Subscriber) -> None:
        """A reader that stopped draining: told so, then dropped.

        What it missed is in the store; the sentinel lets its handler close
        the socket so the client reconnects and re-syncs from its last seq,
        instead of waiting on a queue nothing feeds any more.
        """
        while not q.empty():
            q.get_nowait()
        q.put_nowait(_s.SUBSCRIBER_DROPPED)
        self.unsubscribe(session_id, q)

    def subscribe(self, session_id: str) -> Subscriber:
        q: Subscriber = asyncio.Queue(maxsize=4096)
        self._subscribers.setdefault(session_id, set()).add(q)
        return q

    def unsubscribe(self, session_id: str, q: Subscriber) -> None:
        subs = self._subscribers.get(session_id)
        if subs is None:
            return
        subs.discard(q)
        if not subs:
            self._subscribers.pop(session_id, None)

    def add_event_listener(self, listener: Callable[[str, dict[str, Any]], None]) -> None:
        """Call ``listener(session_id, stored_event)`` after every stored event.

        For coordinators that react to another chat's progress (an agent
        steering a coding thread). The listener runs inline on the emitting
        path, so it must only record and schedule — never await or do I/O.
        """
        listeners = getattr(self, "_event_listeners", None)
        if listeners is None:  # a service built without __init__ (test doubles)
            listeners = self._event_listeners = []
        if listener not in listeners:
            listeners.append(listener)

    def remove_event_listener(self, listener: Callable[[str, dict[str, Any]], None]) -> None:
        listeners = getattr(self, "_event_listeners", [])
        if listener in listeners:
            listeners.remove(listener)

    async def post_notice(self, session_id: str, payload: dict[str, Any]) -> None:
        """A system line in a session's timeline that is not a turn: the agent
        society posts learned skills, login requests and queued approvals here.
        Stored like any event (kind ``notice``) so a reopened chat still shows it.

        A notice the assistant tells on its own in its conversation (a
        reminder coming due, the memory tidy-up) is worded first, as the
        message the assistant sends (``proactive_voice``)."""
        from dodaios.agent_chat import proactive_voice

        payload = dict(payload)
        if not proactive_voice.wants_voice(payload) or not self._is_lead_chat(session_id):
            payload.pop(proactive_voice.CONTEXT_KEY, None)
            await self._emit(session_id, _s.make_event("notice", payload))
            return

        async def store(worded: dict[str, Any]) -> None:
            await self._emit(session_id, _s.make_event("notice", worded))

        await proactive_voice.desk().tell(self, session_id, payload, store)

    def _is_lead_chat(self, session_id: str) -> bool:
        try:
            from dodaios.agent_chat.lead import SURFACE

            session = self.store.get_session(session_id)
        except Exception:  # noqa: BLE001 - an unreadable chat gets its notice unworded
            _s.log.debug("agent chat: no session for a worded notice", exc_info=True)
            return False
        return session is not None and str(getattr(session, "surface", "") or "") == SURFACE

    def _refresh_picture_handoffs(self, session: Any) -> None:
        """Register the Dodaios chat's earlier pictures again (off the event loop)."""
        try:
            events = self.store.list_events(
                session.session_id, tail=_s.chat_attachments.EARLIER_PICTURES_EVENTS
            )
            _s.chat_attachments.refresh_handoffs(session.cwd, events, session_id=session.session_id)
        except Exception:  # noqa: BLE001 - only the earlier pictures go unoffered; the turn runs
            _s.log.warning("chat: earlier pictures not re-registered", exc_info=True)

    def _restore_field_save(self, session_id: str, spec: CredentialSpec) -> Callable | None:
        return self._restore_credential_save(session_id, spec, self._vault_owner(session_id))

    def _vault_owner(self, session_id: str) -> str | None:
        """Whose credential vault masks this chat's events, or ``None``.

        A society seat's chat masks its agent's secrets; the lead's own chat
        (surface ``jarvis``) masks the owner's vault, which the lead keeps. A
        coding thread holds no vault. The surface is read once per chat: this
        runs for every streamed token.
        """
        if session_id.startswith("society:"):
            from dodaios.society.surface import agent_id_of

            return agent_id_of(session_id)
        owners: dict[str, str | None] | None = getattr(self, "_vault_owners", None)
        if owners is None:
            owners = self._vault_owners = {}
        if session_id in owners:
            return owners[session_id]
        try:
            session = self.store.get_session(session_id)
        except Exception:  # noqa: BLE001 - an unreadable chat is asked again next event
            _s.log.debug("agent chat: no session for vault lookup", exc_info=True)
            return None
        if session is None:
            return None
        owner: str | None = None
        if str(getattr(session, "surface", "") or "") == "jarvis":
            from dodaios.society.roster import LEAD_AGENT_ID

            owner = LEAD_AGENT_ID
        if len(owners) > 4096:
            owners.clear()
        owners[session_id] = owner
        return owner

    async def _emit(self, session_id: str, event: dict[str, Any]) -> None:
        # One delivery path for every runner. Normalize only finished receipts;
        # token deltas and voice-critical streaming never perform file I/O.
        owner = self._vault_owner(session_id)
        if owner is not None:
            event = await _s._redact_credentials(session_id, event, owner)
        payload = event.get("payload") or {}
        call_key = (session_id, str(payload.get("call_id") or ""))
        if not hasattr(self, "_tool_call_names"):
            self._tool_call_names: dict[tuple[str, str], str] = {}
        if event.get("kind") == "tool_call" and call_key[1]:
            # Media delivery needs to know which tool a result came from: what
            # a Read or a web search merely saw is not a picture for the chat.
            if len(self._tool_call_names) > 4096:
                self._tool_call_names.clear()
            self._tool_call_names[call_key] = str(payload.get("name") or "")
        if event.get("kind") in {"assistant_text", "tool_result", "user_message"}:
            from dodaios.agent_chat.media import normalize_media_event, temp_roots

            tool_name = (
                self._tool_call_names.pop(call_key, "")
                if event.get("kind") == "tool_result"
                else ""
            )
            from dodaios.core.paths import repo_root
            from dodaios.missions.isolation.worktree import resolve_outputs_root

            session = self.store.get_session(session_id)
            if session is not None:
                try:
                    expanded = await asyncio.to_thread(
                        normalize_media_event,
                        event,
                        cwd=_s.Path(session.cwd),
                        outputs_root=resolve_outputs_root(repo_root()),
                        scope=session_id,
                        tool_name=tool_name,
                        # A coding agent saves what it only wants to show
                        # outside the person's repository.
                        extra_roots=temp_roots() if session.surface == "agent" else (),
                    )
                except (OSError, ValueError):
                    _s.log.warning("agent chat: media normalization failed", exc_info=True)
                    expanded = [
                        event,
                        _s.make_event(
                            "error",
                            {
                                "turn_id": (event.get("payload") or {}).get("turn_id"),
                                "message": "Media could not be added to the chat.",
                            },
                        ),
                    ]
                for item in expanded:
                    await self._publish_event_off_loop(session_id, item)
                return
        await self._publish_event_off_loop(session_id, event)

    async def _publish_event_off_loop(self, session_id: str, event: dict[str, Any]) -> None:
        """``_publish_event`` with the database write on a worker thread.

        Every streamed event of every running turn passes through here, and
        ``append_event`` ends in an SQLite commit. On the event loop, one slow
        commit (a full disk, a paging system) froze the whole app for 15 s at a
        time: the Dodaios Bar stopped mid-dictation, the key release waited and
        nothing was pasted. The write now runs beside the loop; a lock per
        session keeps the events of a chat in the order they were sent.
        Transient events (no write) and the rare end-of-turn and error events
        (they read the store to dedupe and word the error) keep the inline path.
        """
        if _s.is_transient(event) or event.get("kind") in {"turn_finished", "error"}:
            async with self._publish_lock(session_id):
                self._publish_event(session_id, event)
            return
        async with self._publish_lock(session_id):
            stored = await asyncio.to_thread(self.store.append_event, session_id, event)
            self._deliver_event(session_id, stored)

    def _publish_lock(self, session_id: str) -> asyncio.Lock:
        """The lock that keeps one chat's events in order, for the running loop."""
        locks: dict[tuple[int, str], asyncio.Lock] = self.__dict__.setdefault("_publish_locks", {})
        key = (id(asyncio.get_running_loop()), session_id)
        lock = locks.get(key)
        if lock is None:
            if len(locks) > 4096:
                for stale in [k for k, held in locks.items() if not held.locked()]:
                    del locks[stale]
            lock = locks[key] = asyncio.Lock()
        return lock

    def _publish_event(self, session_id: str, event: dict[str, Any]) -> None:
        if event.get("kind") == "turn_finished":
            turn_id = str((event.get("payload") or {}).get("turn_id") or "")
            if turn_id and self.store.turn_terminal(session_id, turn_id) is not None:
                _s.log.warning("agent chat: ignored duplicate completion for turn %s", turn_id)
                return
        if event.get("kind") == "turn_finished":
            # The raw error, before it is made readable: seat health reads its words.
            _s.seat_outcomes.observe_turn_finished(self, session_id, event)
            event = _s.token_efficiency.annotate_turn_finished(self.store, session_id, event)
        if event.get("kind") in {"turn_finished", "error"}:
            event = self._readable_error(session_id, event)
        stored = self.store.append_event(session_id, event)
        if event.get("kind") == "turn_finished":
            from dodaios.orchestrator import traces

            traces.close_turn(
                str((event.get("payload") or {}).get("turn_id") or ""), event.get("payload") or {}
            )
            # Before anyone hears of it: a session list fetched on this event
            # must already read the turn as over (``reports_running``).
            run = self._running.get(session_id)
            finished_id = str((event.get("payload") or {}).get("turn_id") or "")
            if run is not None and run.turn_id == finished_id:
                run.finished = True
        self._deliver_event(session_id, stored)

    def _deliver_event(self, session_id: str, stored: dict[str, Any]) -> None:
        """Hand a stored event to the listeners and the open chat sockets (on the loop)."""
        for listener in list(getattr(self, "_event_listeners", ())):
            try:
                listener(session_id, stored)
            except Exception:  # noqa: BLE001 — an observer never breaks the chat it watches
                _s.log.warning(
                    "agent chat: event listener failed for %s", session_id, exc_info=True
                )
        for q in list(self._subscribers.get(session_id, ())):
            try:
                q.put_nowait(stored)
            except asyncio.QueueFull:
                # A reader that stopped draining is dropped: the WS handler
                # re-syncs from the store when it reconnects.
                _s.log.info("agent chat: subscriber queue full for %s — dropping it", session_id)
                self._drop_subscriber(session_id, q)

    def _readable_error(self, session_id: str, event: dict[str, Any]) -> dict[str, Any]:
        """``event`` with its error as a short reason; a raw dump moves to ``error_details``.

        One place for every runner: a stderr dump, prompt text, an internal
        URL or a bare "Internal error" never reaches the failed-turn card
        (``turn_errors.readable_turn_error``).
        """
        payload = event.get("payload") or {}
        field = "error" if event.get("kind") == "turn_finished" else "message"
        raw = payload.get(field)
        if not isinstance(raw, str) or not raw.strip():
            return event
        session = self.store.get_session(session_id)
        runtime = session.runtime if session is not None else ""
        provider = session.provider if session is not None else ""
        runner = _s.EXTERNAL_RUNTIME_RUNNERS.get(runtime, "")
        if not runner and provider:
            row = _s.provider_row(provider)
            runner = row.runner if row is not None else ""
        reason, details = _s.turn_errors.readable_turn_error(raw, runner=runner, provider=provider)
        if reason == raw and details is None:
            return event
        if details:
            _s.log.warning("agent chat %s: turn failed; details: %s", session_id, details)
        new_payload = {**payload, field: reason}
        if details:
            new_payload["error_details"] = details
        return {**event, "payload": new_payload}
