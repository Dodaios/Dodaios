"""Session creation, steering and the running-turn queries."""

from __future__ import annotations

import asyncio
import sqlite3
import time
from collections.abc import Awaitable, Callable
from typing import Any

from dodaios.agent_chat import service as _s
from dodaios.agent_chat.approval_bridge import ChatApprovalBridge
from dodaios.agent_chat.approval_defer import DeferredApprovals
from dodaios.agent_chat.parked_work import ParkedWorkBoard
from dodaios.agent_chat.store import (
    DEFAULT_SURFACE,
    AgentChatSession,
)


class SessionsMixin:
    """Session creation, steering and the running-turn queries."""

    # ------------------------------------------------------------ sessions

    def default_cwd(self, surface: str = DEFAULT_SURFACE) -> str:
        """Where a new ``surface`` session starts when nobody picked a folder.

        A surface that brings its own workspace (the Jarvis chat) gets that
        directory, created on first use. One that cannot be created — a
        read-only install, no writable app data — falls back to the service
        default rather than handing a chat a folder it cannot work in.
        """
        workspace = _s.kit_for(surface).workspace_dir
        if workspace is None:
            return self._default_cwd()
        folder = workspace()
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            _s.log.warning(
                "chat workspace %s could not be created (%s) — starting in the "
                "fallback folder instead",
                folder,
                exc,
            )
            return self._default_cwd()
        return str(folder)

    def _bridge_for(self, bus: Any | None) -> ChatApprovalBridge | None:
        """The approval bridge, built on the first Jarvis turn that has a bus."""
        if bus is None:
            return None
        if self._bridge is None:
            self._bridge = _s.ChatApprovalBridge(bus)
            self._bridge.chat_keeps_always = self._chat_keeps_always
            self._bridge.deny_reason = self.take_deny_feedback
        return self._bridge

    def _chat_keeps_always(self, session_id: str, tool_name: str) -> bool:
        """False once for a tool whose "always" the card saved as an agent rule."""
        from dodaios.agent_chat.approval_bridge import _bare

        ruled = self._ruled_on_agent.get(session_id)
        bare = _bare(tool_name)
        if ruled and bare in ruled:
            ruled.discard(bare)
            return False
        return True

    def create_session(
        self,
        *,
        provider: str,
        model: str = "",
        effort: str | None = None,
        cwd: str | None = None,
        permission_mode: str = "",
        title: str = "",
        surface: str = DEFAULT_SURFACE,
        account_id: str = "",
        computer_id: str = "",
        speed: str = "",
        build_mode: str = "",
    ) -> AgentChatSession:
        row = _s.provider_row(provider)
        if row is None and not _s.supports_api_runner(provider):
            raise ValueError(f"Unknown agent-chat provider: {provider!r}")
        if row is not None and not _s.offers(surface, provider):
            raise ValueError(
                f"Provider {provider!r} is not offered on the {surface!r} chat. "
                "That chat runs on a provider API behind a key, not on a vendor CLI."
            )
        runner = _s.resolve_runner(provider, surface=surface, account_id=account_id)
        ladder = _s.ladder_key(surface, runner)
        permission_mode = _s.normalize_permission(ladder, permission_mode)
        # A thread that starts in Plan: the mode its permission pill showed, so
        # an approved plan builds in the mode the person picked.
        build = _s.normalize_permission(ladder, build_mode) if build_mode.strip() else ""
        if permission_mode not in _s.PLAN_MODES or build in _s.PLAN_MODES:
            build = ""
        eff = _s.normalize_effort(provider, effort) if effort is not None else ""
        if effort is None and surface != "agent":
            # A coding thread keeps "" until the person picks a level: the CLI
            # then runs on its own default, as in a grid pane.
            from dodaios.agent_chat.effort import default_effort

            eff = default_effort(provider)
        return self.store.create_session(
            provider=provider,
            model=model or (row.default_model if row else ""),
            effort=eff,
            cwd=cwd or self.default_cwd(surface),
            permission_mode=permission_mode,
            title=title,
            surface=surface,
            account_id=account_id,
            computer_id=computer_id,
            speed=_s.normalize_speed(speed),
            build_mode=build,
        )

    def _keep_conversation(self, session_id: str, vendor: str) -> None:
        """Write a CLI's conversation id to its session while the turn still runs.

        The turn's return value carries the id too, but only a turn that
        reaches its end returns. One cut off by a reboot or a crash left a new
        thread without its conversation, so the next message started a CLI
        that knew nothing of the work so far.
        """
        try:
            self.store.update_session(session_id, vendor_session=vendor)
        except sqlite3.Error:
            # The turn's end writes it again; the turn itself must go on.
            _s.log.warning(
                "agent chat %s: conversation id not saved yet", session_id, exc_info=True
            )

    def _set_steerer(
        self, session_id: str, turn_id: str, writer: Callable[..., Awaitable[bool]] | None
    ) -> None:
        if writer is not None:
            self._steerers[session_id] = (turn_id, writer)
        elif self._steerers.get(session_id, ("",))[0] == turn_id:
            self._steerers.pop(session_id, None)

    def can_steer(self, session_id: str) -> bool:
        return session_id in self._steerers and self.is_running(session_id)

    async def steer(
        self,
        session_id: str,
        text: str,
        attachments: list[dict[str, Any]] | None = None,
    ) -> bool:
        """Hand a message to the CLI of the running turn; False when it cannot take one.

        On success the message is a ``user_message`` of that turn (``steered``),
        so the transcript shows it where the agent received it. Files go along
        the way they do on a new turn: each by its path in the text, pictures
        also as image blocks. Only Claude Code and GLM read those mid-turn; on
        any other seat a message with files is not taken here and starts the
        next turn instead.
        """
        entry = self._steerers.get(session_id)
        body = text.strip()
        attached = _s.chat_attachments.to_analysis(attachments)
        if entry is None or not (body or attached) or not self.is_running(session_id):
            return False
        turn_id, writer = entry
        if not attached:
            if not await writer(body):
                return False
            await self._emit(
                session_id,
                _s.make_event("user_message", {"text": body, "turn_id": turn_id, "steered": True}),
            )
            return True
        from dodaios.agent_chat import plain_chat

        session = self.store.get_session(session_id)
        if session is None or _s.session_runner(session) not in _s._STEER_FILE_RUNNERS:
            return False
        found = await asyncio.to_thread(plain_chat.image_paths, session.cwd, attached, limit=None)
        images = tuple(str(path) for path in found)
        attached = _s._seen_directly(session.cwd, attached, images)
        prompt = _s.chat_attachments.compose(body, attached)
        if self._steerers.get(session_id) is not entry or not await writer(prompt, images):
            return False
        await self._emit(
            session_id,
            _s.make_event(
                "user_message",
                {
                    "text": prompt,
                    "typed": body,
                    "attachments": _s._attachment_receipts(attached),
                    "turn_id": turn_id,
                    "steered": True,
                },
            ),
        )
        return True

    def is_running(self, session_id: str) -> bool:
        preparing = self._preparing.get(session_id)
        if preparing is not None and preparing.setup_task is not _s._current_task():
            return True
        run = self._running.get(session_id)
        return bool(run and (run.task is None or not run.task.done()))

    def reports_running(self, session_id: str) -> bool:
        """``running`` as the UI reads it: false from the turn's ``turn_finished`` on.

        The task still runs its cleanup for a moment after that event; a
        session list fetched because of the event must not call it running.
        """
        if not self.is_running(session_id):
            return False
        run = self._running.get(session_id)
        return not (run is not None and run.finished and session_id not in self._preparing)

    async def _await_finishing(self, session_id: str) -> None:
        """A turn that published its end and only cleans up: a send waits for it."""
        run = self._running.get(session_id)
        if run is None or not run.finished or run.task is None or run.task.done():
            return
        await asyncio.wait({run.task}, timeout=_s._FINISHING_WAIT_S)

    @property
    def parked_work(self) -> ParkedWorkBoard:
        """Requests whose delegates still work after their turn closed."""
        board = getattr(self, "_parked_work", None)
        if board is None:  # a service built without __init__ (test doubles)
            board = self._parked_work = _s.ParkedWorkBoard(self)
        return board

    def delegate_wait(self, handle: Any, gate: Any) -> Any:
        """Mark a turn as only waiting for its delegates (a context manager)."""
        return self.parked_work.waiting(handle, gate)

    def carry_delegation(
        self, handle: Any, gate: Any, original: str, rows: list[dict[str, Any]]
    ) -> None:
        """Continue a wait whose turn handed its seat to the next message."""
        self.parked_work.carry(handle, gate, original, rows)

    async def release_waiting_turn(self, session_id: str) -> bool:
        """Free the chat for a new message when its running turn only waits.

        A turn that waits on an approval card sets the card aside instead
        (approval_defer.py): the card stays open, the call is refused with the
        reason, and the chat answers the new message at once.
        """
        session = self.store.get_session(session_id)
        if (
            session is not None
            and _s.ParkedWorkBoard.parks(session)
            and self.is_running(session_id)
            and self.defer_open_approvals(session_id)
        ):
            run = self._running.get(session_id)
            task = getattr(run, "task", None)
            deadline = asyncio.get_running_loop().time() + 10.0
            while self.is_running(session_id) and task is not None:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    return False
                await asyncio.wait({task}, timeout=min(0.05, remaining))
            return not self.is_running(session_id)
        return await self.parked_work.release(session_id)

    def running_session_ids(self) -> list[str]:
        """Sessions occupying a chat seat, including pre-admission setup."""
        return [
            *[sid for sid in list(self._running) if self.is_running(sid)],
            *list(self._preparing),
        ]

    def turns_a_restart_would_end(self) -> list[str]:
        """Sessions whose running turn dies with this process.

        A thread turn's CLI runs in the turn host, and the next process
        carries it on. Every other chat (the front page's, a created agent's)
        runs its turn in this process: a restart closes it as failed, and the
        person has to send the message again.
        """
        from dodaios.agent_chat import turn_host_client

        hosted = turn_host_client.host_available()
        return [
            sid
            for sid in dict.fromkeys(self.running_session_ids())
            if not (hosted and self._may_be_hosted(sid))
        ]

    async def seal_stopped_turn(self, session_id: str) -> bool:
        """Close a turn the stop button can still see after its runner is gone.

        A restart keeps the transcript and drops the in-memory task. The CLI
        can still be working. Stop has to end that turn, or the button does
        nothing and the chat stays on Working.
        """
        if self.is_running(session_id):
            return False
        events = self.store.list_events(session_id)
        turn_id = ""
        started_ms = 0
        for event in reversed(events):
            kind = event["kind"]
            payload = event.get("payload") or {}
            if kind == "turn_finished":
                return False
            if kind == "turn_started":
                turn_id = str(payload.get("turn_id") or "")
                started_ms = int(event.get("ts_ms") or 0)
                break
        if not turn_id:
            return False
        now_ms = int(time.time() * 1000)
        await self._emit(
            session_id,
            _s.make_event(
                "turn_finished",
                {
                    "turn_id": turn_id,
                    "status": "cancelled",
                    "duration_ms": max(0, now_ms - started_ms) if started_ms else 0,
                    "usage": {},
                    "error": None,
                },
            ),
        )
        session = self.store.get_session(session_id)
        # The turn host knows which CLI is this thread's; the folder match is
        # only for a CLI the app started itself before a restart.
        from dodaios.agent_chat.turn_host_client import kill_session_turns

        stopped = await kill_session_turns(session_id)
        if not stopped and session is not None and session.cwd:
            await asyncio.to_thread(_s.stop_cli_at_cwd, session.cwd)
        if session is not None and session.surface in ("jarvis", "society"):
            from dodaios.society.browser.tool import stop_chat_browser

            await stop_chat_browser(session_id)
        return True

    @property
    def deferred_approvals(self) -> DeferredApprovals:
        """Cards set aside because the person moved on (approval_defer.py)."""
        board = getattr(self, "_deferred", None)
        if board is None:
            board = self._deferred = _s.DeferredApprovals(self)
        return board

    def pending_approvals(self, session_id: str) -> list[str]:
        waiting = [aid for aid, sid in self._approval_session.items() if sid == session_id]
        return [*waiting, *self.deferred_approvals.pending(session_id)]
