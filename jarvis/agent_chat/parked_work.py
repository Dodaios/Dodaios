"""Delegated work that left its turn: the chat stays free, the result returns later.

"Brief the agent in terminal two" is answered in seconds, but the agent then
works for minutes. The turn used to stay open for all of that time, so the
next message ("and create an agent for the docs") waited behind it. Here the
waiting turn hands its seat over the moment the person sends something else:

* the turn closes with what it has said so far ("sent, it is working");
* its :class:`~jarvis.agent_chat.delegation_wait.DelegationWait` goes on
  outside the turn, reading the same local evidence, calling no model;
* when the delegates have reported, the earlier request is continued in a turn
  of its own, marked in the timeline as the result of that request;
* every turn started meanwhile is told what is still running, so it neither
  resends that work nor waits for it.

Parked work lives in memory, like the send queue: a restart forgets the wait,
never the delegated work itself, whose own report still reaches the chat.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Final

from jarvis.core.delegated_work import collect_delegated_work
from jarvis.core.protocols import current_chat_turn

from .delegation_wait import DelegationWait, continuation_prompt

log = logging.getLogger(__name__)

__all__ = ["BACKGROUND_ORIGIN", "ParkedWork", "ParkedWorkBoard"]

#: ``origin`` of the ``user_message`` that opens a parked request's result turn.
#: Mirrored in ``components/agentchat/reduce.ts`` (parity-tested).
BACKGROUND_ORIGIN: Final[str] = "background"
#: How long a new message waits for the waiting turn to close before it queues.
_RELEASE_TIMEOUT_S: Final[float] = 10.0
#: How often finished work checks whether the chat is free for its result.
_POLL_S: Final[float] = 0.5
_REQUEST_CHARS: Final[int] = 400


@dataclass(slots=True, eq=False)
class ParkedWork:
    """One request whose delegates are still working after its turn closed."""

    turn_id: str
    #: What the person typed, for the timeline and for the model's context.
    request: str
    #: The prompt the turn ran with; its continuation needs the whole of it.
    original: str
    gate: DelegationWait
    rows: list[dict[str, Any]] = field(default_factory=list)
    task: asyncio.Task[None] | None = None
    #: The delegates have reported; only the chat's seat is still awaited.
    reported: bool = False

    def names(self) -> list[str]:
        """Who is still working on it."""
        return [
            work.name for key, work in self.gate.work.items() if key not in self.gate.delivered
        ]


def _short(text: str) -> str:
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= _REQUEST_CHARS else flat[: _REQUEST_CHARS - 1] + "…"


class ParkedWorkBoard:
    """Which turns only wait, and which requests continue in the background."""

    def __init__(self, service: Any) -> None:
        self._service = service
        self._waiting: dict[str, DelegationWait] = {}
        self._parked: dict[str, list[ParkedWork]] = {}

    # -- a turn that only waits ------------------------------------------------

    @staticmethod
    def parks(session: Any) -> bool:
        """Dodaios' own chat takes several orders; an agent's one chat keeps its turn."""
        return getattr(session, "surface", "") == "jarvis"

    @contextmanager
    def waiting(self, handle: Any, gate: DelegationWait) -> Iterator[None]:
        """Mark ``handle``'s turn as only waiting for its delegates."""
        session_id = handle.session.session_id
        if not self.parks(handle.session):
            yield
            return
        self._waiting[session_id] = gate
        from .send_queue import has_waiting

        if has_waiting(self._service, session_id):
            # A message queued while the model was still answering.
            gate.yield_seat.set()
        try:
            yield
        finally:
            if self._waiting.get(session_id) is gate:
                del self._waiting[session_id]

    async def release(self, session_id: str) -> bool:
        """Free the chat for a new message if its running turn only waits.

        True once the seat is free. A turn that is still answering or running
        a tool is left alone, and the new message queues behind it as before.
        """
        gate = self._waiting.get(session_id)
        run = getattr(self._service, "_running", {}).get(session_id)
        task = getattr(run, "task", None)
        if gate is None or task is None:
            return False
        gate.yield_seat.set()
        # The seat is free as soon as the turn has let go of it; the turn's
        # own closing work may still run and is not waited for.
        deadline = asyncio.get_running_loop().time() + _RELEASE_TIMEOUT_S
        while self._service.is_running(session_id):
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return False
            await asyncio.wait({task}, timeout=min(0.02, remaining))
        return True

    # -- the wait outside its turn ----------------------------------------------

    def carry(
        self, handle: Any, gate: DelegationWait, original: str, rows: list[dict[str, Any]]
    ) -> ParkedWork:
        """Continue ``gate`` after its turn closed; called from inside that turn."""
        session_id = handle.session.session_id
        turn = current_chat_turn.get()
        parked = ParkedWork(
            turn_id=handle.turn_id,
            request=_short(turn.user_text if turn is not None else original),
            original=original,
            gate=gate,
            rows=list(rows),
        )
        self._parked.setdefault(session_id, []).append(parked)
        gate.detached = True
        # Started from the turn's own task, so the trusted turn identity that
        # late delegate registrations are checked against travels with it.
        parked.task = asyncio.create_task(
            self._carry(session_id, parked), name=f"chat-parked-{handle.turn_id[:8]}"
        )
        log.info(
            "agent chat %s: turn %s handed its seat over; %d delegate(s) continue",
            session_id, handle.turn_id, len(parked.names()),
        )
        return parked

    def running(self, session_id: str) -> list[ParkedWork]:
        return list(self._parked.get(session_id, ()))

    def stop(self, session_id: str) -> int:
        """Drop the chat's background waits; the delegated work itself runs on.

        Called when the chat is deleted, and for a stop pressed while no turn
        is running: then the waits are all there is to stop. A stop pressed
        during a turn stops that turn and leaves earlier requests alone.
        """
        parked = self._parked.pop(session_id, [])
        for item in parked:
            item.gate.stop.set()
        return len(parked)

    def context_note(self, session_id: str) -> str:
        """What a new turn must know about requests still running behind it."""
        lines = [
            f'- "{item.request}" (working on it: {", ".join(item.names()) or "being finished"})'
            for item in self.running(session_id)
            if not item.reported
        ]
        if not lines:
            return ""
        return (
            "[Background work of this chat, for your information only. These earlier "
            "requests were handed to agents that are still working; each result arrives "
            "in this chat on its own and is then answered separately. Do not send that "
            "work again, do not wait for it, and do not report it as finished. Answer "
            "the person's message.\n" + "\n".join(lines) + "]"
        )

    async def _carry(self, session_id: str, parked: ParkedWork) -> None:
        try:
            with collect_delegated_work(parked.gate.add):
                rows = [*parked.rows, *await parked.gate.collect()]
            parked.reported = True
            if rows and parked in self._parked.get(session_id, ()):
                await self._resume(session_id, parked, rows)
        except asyncio.CancelledError:
            log.info("agent chat %s: background wait of %s stopped", session_id, parked.turn_id)
            raise
        except Exception:
            log.exception("agent chat %s: background wait of %s failed", session_id, parked.turn_id)
            await self._lost(session_id, parked)
        finally:
            remaining = [item for item in self._parked.get(session_id, ()) if item is not parked]
            if remaining:
                self._parked[session_id] = remaining
            else:
                self._parked.pop(session_id, None)

    async def _resume(
        self, session_id: str, parked: ParkedWork, rows: list[dict[str, Any]]
    ) -> None:
        """Continue the earlier request once the chat has room for it."""
        from .send_queue import has_waiting
        from .service import NoSuchSession, SessionBusy

        prompt = continuation_prompt(rows, parked.original, later=True)
        while not parked.gate.stop.is_set():
            # The person's own waiting messages go first: they were typed
            # before this result existed.
            if not self._service.is_running(session_id) and not has_waiting(
                self._service, session_id
            ):
                try:
                    await self._service.send(
                        session_id, prompt, display_text=parked.request, background_result=True
                    )
                except SessionBusy:
                    pass  # Another turn took the seat first; try again shortly.
                except NoSuchSession:
                    log.info("agent chat %s was deleted before its result arrived", session_id)
                    return
                else:
                    return
            # Jitter only spreads the polls of several waiting results.
            await asyncio.sleep(_POLL_S + random.uniform(0, _POLL_S / 2))  # noqa: S311

    async def _lost(self, session_id: str, parked: ParkedWork) -> None:
        """Say so in the chat when a background result cannot be brought back."""
        try:
            await self._service.post_notice(session_id, {
                "kind": "background_result_lost",
                "turn_id": parked.turn_id,
                "text": parked.request,
            })
        except Exception:  # noqa: BLE001 — the failure above is already logged with its cause
            log.warning("agent chat %s: lost-result notice not posted", session_id, exc_info=True)
