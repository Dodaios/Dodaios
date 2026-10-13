"""How the coordinator reaches a peer: one thread session per member.

``TurnPort`` is the narrow surface the engine needs; ``ChatTurns`` implements
it on the agent-chat service, so a member is an ordinary thread of the IDE
(its own CLI session, its own access mode) that the person can open and read.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Protocol

log = logging.getLogger(__name__)

__all__ = ["ChatTurns", "TurnPort", "TurnResult"]

#: Who the member's thread shows above the coordinator's messages.
_AUTHOR = {"agent_id": "team-thread", "name": "Team thread"}
_DONE = ("ok", "done", "completed")


@dataclass(frozen=True, slots=True)
class TurnResult:
    #: ``ok``, ``failed`` (the member leaves) or ``timeout`` (over its time, or
    #: stopped from outside: the thread waits and asks again).
    status: str
    text: str = ""
    error: str = ""
    #: ``None`` when the runner did not report a price (subscription seats).
    cost_usd: float | None = None
    duration_ms: int = 0


class TurnPort(Protocol):
    def open(self, *, provider: str, model: str, effort: str, cwd: str, title: str) -> str:
        """Create the member's session and return its id."""

    async def ask(
        self, session_id: str, prompt: str, *, display: str, language: str, timeout_s: float
    ) -> TurnResult:
        """Run one turn and return its final message. Cancelling the call stops the turn."""

    def waiting(self, session_id: str) -> bool:
        """Whether the member's turn waits for the person (an approval card)."""

    def discard(self, session_id: str) -> None:
        """Delete the member's session."""


class ChatTurns:
    def __init__(self, service: Any) -> None:
        self._svc = service

    def open(self, *, provider: str, model: str, effort: str, cwd: str, title: str) -> str:
        session = self._svc.create_session(
            provider=provider,
            model=model,
            effort=effort or None,
            cwd=cwd,
            # Empty = the runner's default access mode, the same a new thread gets.
            permission_mode="",
            title=title,
            surface="agent",
        )
        return str(session.session_id)

    async def ask(
        self, session_id: str, prompt: str, *, display: str, language: str, timeout_s: float
    ) -> TurnResult:
        svc = self._svc
        turn_id = ""
        # Do not interrupt the service between registering a turn and installing
        # its runner: reap the send first, then cancel the turn by its id.
        sending: asyncio.Task[str] = asyncio.create_task(
            svc.send(
                session_id,
                prompt,
                # The coordinator wrote this, not the person: no steering, no
                # end-of-turn question card.
                direct_user=False,
                display_text=display,
                output_language=language,
                author=_AUTHOR,
            )
        )
        try:
            turn_id = await asyncio.shield(sending)
            try:
                await asyncio.wait_for(svc.wait_turn(session_id), timeout=timeout_s)
            except TimeoutError:
                await svc.cancel(session_id, expected_turn_id=turn_id)
                return TurnResult("timeout", error="The turn did not finish in time.")
        except asyncio.CancelledError:
            try:
                if not turn_id:
                    turn_id = await asyncio.shield(sending)
                await asyncio.shield(svc.cancel(session_id, expected_turn_id=turn_id))
            except Exception:  # noqa: BLE001 - the stop itself must still propagate
                log.warning("team thread: stopping a member turn failed", exc_info=True)
            raise
        except Exception as exc:  # noqa: BLE001 - a seat that cannot start leaves the team
            return TurnResult("failed", error=str(exc) or type(exc).__name__)
        terminal = await asyncio.to_thread(svc.store.turn_terminal, session_id, turn_id)
        payload = (terminal or {}).get("payload") or {}
        cost = payload.get("cost_usd")
        base = {
            "cost_usd": float(cost) if isinstance(cost, int | float) else None,
            "duration_ms": int(payload.get("duration_ms") or 0),
        }
        if terminal is None or payload.get("status") == "cancelled":
            # Stopped from outside (the member's own thread, or the app going
            # down): the member stays in the team and is asked again on Resume.
            return TurnResult("timeout", error="The turn was stopped.", **base)
        if payload.get("status") not in _DONE:
            return TurnResult(
                "failed",
                error=str(payload.get("error") or payload.get("status") or "no result"),
                **base,
            )
        events = await asyncio.to_thread(svc.store.list_events, session_id, tail=400)
        text = next(
            (
                str(event["payload"].get("text") or "")
                for event in reversed(events)
                if event["kind"] == "assistant_text"
                and event["payload"].get("turn_id") == turn_id
                and str(event["payload"].get("text") or "").strip()
            ),
            "",
        )
        if not text:
            return TurnResult("failed", error="The turn ended without an answer.", **base)
        return TurnResult("ok", text=text, **base)

    def waiting(self, session_id: str) -> bool:
        return bool(self._svc.pending_approvals(session_id))

    def discard(self, session_id: str) -> None:
        self._svc.store.delete_session(session_id)
