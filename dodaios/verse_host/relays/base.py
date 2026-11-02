"""Shared plumbing of the relays: bus subscriptions, coalesced re-reads, row diffs."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable, Iterable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..bridge import BridgeSession
    from ..ports import BackendPort

log = logging.getLogger(__name__)


class RelayBase:
    """A topic producer bound to one session; subclasses set ``topics``."""

    topics: tuple[str, ...] = ()

    def __init__(self, session: BridgeSession, backend: BackendPort) -> None:
        self.session = session
        self.backend = backend
        self._subs: list[tuple[Any, Any]] = []
        self._tasks: set[asyncio.Task[Any]] = set()
        self.stopped = False

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        self.stopped = True
        bus = self.backend.bus
        for event_type, handler in self._subs:
            with contextlib.suppress(Exception):
                bus.unsubscribe(event_type, handler)
        self._subs.clear()
        for task in list(self._tasks):
            task.cancel()
        for task in list(self._tasks):
            with contextlib.suppress(BaseException):
                await task
        self._tasks.clear()

    async def subscribe(self, topic: str) -> None:
        return None

    async def unsubscribe(self, topic: str) -> None:
        return None

    async def resync(self, topic: str, data: dict[str, Any]) -> None:
        await self.subscribe(topic)

    # ------------------------------------------------------------------ helpers
    def listen(
        self, event_types: Iterable[type], handler: Callable[[Any], Awaitable[None]]
    ) -> None:
        bus = self.backend.bus
        if bus is None:
            return
        for event_type in event_types:
            bus.subscribe(event_type, handler)
            self._subs.append((event_type, handler))

    def spawn(self, coro: Awaitable[Any], name: str = "verse-relay") -> asyncio.Task[Any]:
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._done)
        return task

    def _done(self, task: asyncio.Task[Any]) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            log.warning("verse relay task failed", exc_info=task.exception())

    def every(self, seconds: float, fn: Callable[[], Awaitable[None]]) -> None:
        async def loop() -> None:
            while not self.stopped:
                await asyncio.sleep(seconds)
                try:
                    await fn()
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001
                    log.warning("verse relay: periodic read failed", exc_info=True)

        self.spawn(loop())

    @property
    def subscribed(self) -> set[str]:
        return self.session.subscribed


class Coalescer:
    """Run ``fn`` at most once per ``interval`` s however often it is asked for."""

    def __init__(
        self, relay: RelayBase, fn: Callable[[], Awaitable[None]], interval: float
    ) -> None:
        self._relay = relay
        self._fn = fn
        self._interval = interval
        self._scheduled = False
        self._last = 0.0

    def poke(self) -> None:
        if self._scheduled or self._relay.stopped:
            return
        self._scheduled = True
        loop = asyncio.get_running_loop()
        delay = max(0.0, self._last + self._interval - loop.time())

        async def run() -> None:
            try:
                if delay:
                    await asyncio.sleep(delay)
                self._last = asyncio.get_running_loop().time()
                self._scheduled = False
                await self._fn()
            finally:
                self._scheduled = False

        self._relay.spawn(run())


def diff_rows(
    old: dict[str, dict[str, Any]], new: dict[str, dict[str, Any]], id_field: str
) -> tuple[list[dict[str, Any]], list[str]]:
    """Partial upserts (id plus changed fields; new ids complete) and removed ids."""
    upserts: list[dict[str, Any]] = []
    for key, row in new.items():
        before = old.get(key)
        if before is None:
            upserts.append(dict(row))
            continue
        changed = {k: v for k, v in row.items() if before.get(k) != v}
        if changed:
            upserts.append({id_field: key, **changed})
    removed = [key for key in old if key not in new]
    return upserts, removed
