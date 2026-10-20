"""One headless coding run: a thread on the IDE's surface, in a worktree the loop made.

The run is an ordinary agent-chat thread (``docs/agentic-ide-threads.md``): the
coding CLI runs on its own subscription login, the thread shows up under its
project in the Agentic IDE, and the person can read every step and step in.
Unlike a thread a Jarvis agent opens, it never runs in the person's checkout:
the loop hands it a fresh worktree and branch (``builder``).

The run must finish on its own. A question or a plan card means the task was
not clear enough for unattended work: the turn is stopped and the build fails
with that lesson, rather than waiting on the person.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Final, Protocol

from loguru import logger

#: The thread's author line: who wrote the prompt.
AUTHOR: Final[dict[str, str]] = {"agent_id": "self_build", "name": "Dodaios"}
POLL_S: Final[float] = 5.0


@dataclass(frozen=True, slots=True)
class RunResult:
    ok: bool
    summary: str = ""
    error: str = ""
    session_id: str = ""


class Runner(Protocol):
    async def run(
        self,
        *,
        provider: str,
        folder: str,
        prompt: str,
        title: str,
        timeout_s: float,
        should_stop: Callable[[], bool],
        on_session: Callable[[str], Awaitable[None]] | None = None,
    ) -> RunResult: ...

    async def outcome(self, session_id: str) -> RunResult | None: ...


def _default_chat() -> Any:
    from dodaios.mcp.agents.context import chat_service

    return chat_service()


class ThreadRunner:
    """:class:`Runner` on the agent-chat service's coding threads."""

    def __init__(self, chat_service: Callable[[], Any] | None = None) -> None:
        self._chat = chat_service or _default_chat

    async def run(
        self,
        *,
        provider: str,
        folder: str,
        prompt: str,
        title: str,
        timeout_s: float,
        should_stop: Callable[[], bool],
        on_session: Callable[[str], Awaitable[None]] | None = None,
    ) -> RunResult:
        from dodaios.agent_chat.service import resolve_runner
        from dodaios.society.coding_threads import THREAD_SURFACE, access_mode

        service = self._chat()
        runner = resolve_runner(provider, surface=THREAD_SURFACE)
        session = service.create_session(
            provider=provider,
            cwd=folder,
            # A loop run cannot stop for approvals nobody is there to give; it
            # works in its own worktree, never in the person's checkout.
            permission_mode=access_mode(runner, "full"),
            title=title[:80],
            surface=THREAD_SURFACE,
        )
        sid = session.session_id
        if on_session is not None:
            await on_session(sid)
        turn_id = await service.send(sid, prompt, author=dict(AUTHOR))
        deadline = time.monotonic() + timeout_s
        while True:
            result = self._finished(service, sid, turn_id)
            if result is not None:
                if not result.ok and service.is_running(sid):
                    # A question or plan card holds the turn open: end it.
                    await self._stop(service, sid)
                return result
            if should_stop():
                await self._stop(service, sid)
                return RunResult(
                    False, error="stopped: the self-building loop was paused", session_id=sid
                )
            if time.monotonic() > deadline:
                await self._stop(service, sid)
                return RunResult(
                    False, error=f"did not finish within {int(timeout_s / 60)} min", session_id=sid
                )
            await asyncio.sleep(POLL_S)

    async def outcome(self, session_id: str) -> RunResult | None:
        """How an earlier run ended (after a restart), None while it still runs."""
        service = self._chat()
        if service.is_running(session_id):
            return None
        return self._finished(service, session_id, "") or RunResult(
            False, error="the run ended without an answer", session_id=session_id
        )

    async def stop(self, session_id: str) -> None:
        """Stop a run that is still working (an undo while it codes)."""
        service = self._chat()
        if service.is_running(session_id):
            await self._stop(service, session_id)

    @staticmethod
    def _finished(service: Any, sid: str, turn_id: str) -> RunResult | None:
        from dodaios.society.coding_threads import last_turn, open_plan, open_question

        events = service.store.list_events(sid, tail=400)
        if open_question(events) is not None:
            return RunResult(False, error="the coding agent asked a question", session_id=sid)
        if open_plan(events) is not None:
            return RunResult(False, error="the coding agent stopped at a plan", session_id=sid)
        done = [
            e
            for e in events
            if e["kind"] == "turn_finished"
            and (not turn_id or str((e.get("payload") or {}).get("turn_id") or "") == turn_id)
        ]
        if not done:
            return None
        status, text, error = last_turn(events)
        if status not in ("done", "complete", "completed", "ok", "success"):
            return RunResult(False, summary=text, error=error or status, session_id=sid)
        return RunResult(True, summary=text, session_id=sid)

    @staticmethod
    async def _stop(service: Any, sid: str) -> None:
        try:
            if not await service.cancel(sid):
                await service.seal_stopped_turn(sid)
        except Exception:  # noqa: BLE001 - the run is abandoned either way
            logger.opt(exception=True).warning("self-build code: could not stop thread {}", sid)
