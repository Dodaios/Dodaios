"""Chat turns as agent runs: what the Record's Runs and Last active count.

Every turn of a society chat (``society:<agent>``, its conversations and its
routine runs) ends with one ``turn_finished`` in the agent chat service,
whatever runtime ran it: Jarvis' own brain, a CLI seat, Hermes or OpenClaw.
This ledger listens for that event and remembers the turn in the society
store (``society_agent_turns``), so ``SocietyStore.agent_stats`` counts it.

A board dispatch is a chat turn too, and it already sends a RESULT; the
stats count that run once (run_id ``turn:<turn_id>``). A routine run is one
turn in its own chat and sends no RESULT, so it counts once as well.

Turns that finished before this ledger existed are read back from the chat
store once (``_BACKFILL_KEY``).
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any, Final

log = logging.getLogger(__name__)

__all__ = ["ChatRunLedger"]

_PREFIX: Final[str] = "society:"
#: Set once the chat store's older turns were copied in.
_BACKFILL_KEY: Final[str] = "chat_turns_backfilled"


class ChatRunLedger:
    """Copies finished society chat turns into the society store."""

    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime
        self._service: Any = None
        self._attach_task: asyncio.Task[None] | None = None
        self._writes: set[asyncio.Task[Any]] = set()

    async def start(self) -> None:
        if await self._attach() is None:
            # The society can start before the chat service exists.
            self._attach_task = asyncio.create_task(self._attach_later(), name="chat-runs-attach")

    async def _attach_later(self) -> None:
        for _ in range(150):
            # Jitter only spreads the retries; nothing here is security relevant.
            await asyncio.sleep(2.0 + random.uniform(0, 1.0))  # noqa: S311
            if await self._attach() is not None:
                return
        log.info("chat runs: no chat service appeared; chat turns are not counted")

    async def _attach(self) -> Any:
        if self._service is not None:
            return self._service
        service = self.runtime.chat_service()
        if service is None or not hasattr(service, "add_event_listener"):
            return None
        service.add_event_listener(self.on_event)
        self._service = service
        await self._backfill(service)
        return service

    async def close(self) -> None:
        if self._service is not None:
            self._service.remove_event_listener(self.on_event)
            self._service = None
        if self._attach_task is not None:
            self._attach_task.cancel()
            await asyncio.gather(self._attach_task, return_exceptions=True)
            self._attach_task = None
        if self._writes:
            await asyncio.gather(*list(self._writes), return_exceptions=True)

    def on_event(self, session_id: str, event: dict[str, Any]) -> None:
        """The chat service's synchronous observer: a finished turn is a run."""
        if event.get("kind") != "turn_finished" or not session_id.startswith(_PREFIX):
            return
        row = _row(session_id, event)
        if row is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            log.debug("chat runs: turn %s finished off the event loop; not counted", row[0])
            return
        task = loop.create_task(self._record([row]))
        self._writes.add(task)
        task.add_done_callback(self._writes.discard)

    async def _record(self, rows: list[tuple[str, str, str, int, str]]) -> None:
        try:
            await self.runtime.store.record_chat_turns(rows)
        except Exception:  # noqa: BLE001 — a lost row only undercounts the Record
            log.warning("chat runs: a finished turn was not recorded", exc_info=True)

    async def _backfill(self, service: Any) -> None:
        store = self.runtime.store
        reader = getattr(service.store, "finished_turns", None)
        if reader is None:
            return
        try:
            if await store.get_meta(_BACKFILL_KEY) == "1":
                return
            found = await asyncio.to_thread(reader, _PREFIX)
            rows = [
                row for row in (
                    _row(sid, {"ts_ms": ts, "payload": {"turn_id": tid, "status": status}})
                    for sid, tid, ts, status in found
                ) if row is not None
            ]
            added = await store.record_chat_turns(rows)
            await store.set_meta(_BACKFILL_KEY, "1")
            if added:
                log.info("chat runs: counted %d earlier chat turns", added)
        except Exception:  # noqa: BLE001 — the next start tries again
            log.warning("chat runs: earlier chat turns were not counted", exc_info=True)


def _row(session_id: str, event: dict[str, Any]) -> tuple[str, str, str, int, str] | None:
    from .surface import agent_id_of

    payload = event.get("payload") or {}
    turn_id = str(payload.get("turn_id") or "")
    agent_id = agent_id_of(session_id)
    if not turn_id or not agent_id:
        return None
    ts_ms = int(event.get("ts_ms") or 0) or int(time.time() * 1000)
    return (turn_id, agent_id, session_id, ts_ms, str(payload.get("status") or ""))
