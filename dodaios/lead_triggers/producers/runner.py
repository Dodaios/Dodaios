"""Runs the pollers: modest interval, incremental cursors, backoff, pauses.

Nothing here calls a model. A poller only asks its provider anything while the
owner has triggers on (accept mode not ``off``), the poller's toggle is on, its
source is a ``candidate`` source and no hold covers triggers. A paused poller
keeps its cursor, so it resumes where it stopped.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Final

from ..event import TriggerEvent
from ..service import MetaStore
from ..settings import TriggerSettings
from .base import AuthError, NotConnected, Producer, RateLimited

log = logging.getLogger(__name__)

META_PRODUCERS: Final[str] = "lead.triggers.producers"
MAX_BACKOFF_S: Final[float] = 1800.0
AUTH_RETRY_S: Final[float] = 900.0
TICK_S: Final[float] = 20.0


class ProducerRunner:
    def __init__(
        self,
        store: MetaStore,
        producers: Sequence[Producer],
        *,
        settings: Callable[[], Awaitable[TriggerSettings]],
        submit: Callable[[TriggerEvent], Awaitable[str]],
        paused: Callable[[], bool] = lambda: False,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._store = store
        self._producers = list(producers)
        self._settings, self._submit, self._paused, self._clock = settings, submit, paused, clock
        self._state: dict[str, dict[str, Any]] | None = None
        self._lock = asyncio.Lock()

    async def _load(self) -> dict[str, dict[str, Any]]:
        if self._state is None:
            try:
                raw = json.loads(await self._store.get_meta(META_PRODUCERS, ""))
            except ValueError:  # nothing saved yet
                log.debug("lead triggers: no saved poller state")
                raw = {}
            raw = raw if isinstance(raw, dict) else {}
            self._state = {k: dict(v) for k, v in raw.items() if isinstance(v, dict)}
        return self._state

    async def _save(self) -> None:
        if self._state is not None:
            await self._store.set_meta(META_PRODUCERS, json.dumps(self._state))

    @staticmethod
    def _gate(producer: Producer, settings: TriggerSettings, held: bool) -> str:
        """Why the poller must not ask its provider anything right now, or empty."""
        if not settings.producer_enabled(producer.id):
            return "off"
        if settings.accept == "off":
            return "paused"
        if held:
            return "held"
        mode = settings.rule(producer.source).mode
        if producer.id == "agentmail":
            if not settings.agent_address:
                return "no_address"
            return "idle" if mode == "ignore" else ""
        return "" if mode == "candidate" else "idle"

    async def tick(self) -> None:
        """Poll every poller that is due. One failing poller never stops the others."""
        settings = await self._settings()
        held = self._paused()
        async with self._lock:
            states = await self._load()
            for producer in self._producers:
                entry = states.setdefault(producer.id, {})
                reason = self._gate(producer, settings, held)
                if reason:
                    entry["state"] = reason
                    continue
                now = self._clock()
                if now < float(entry.get("next_at") or 0):
                    continue
                await self._poll(producer, entry, settings, now)
            await self._save()

    async def _poll(
        self, producer: Producer, entry: dict[str, Any], settings: TriggerSettings, now: float
    ) -> None:
        interval = float(settings.poll_interval_s)
        try:
            if not await producer.connected():
                entry["state"], entry["next_at"] = "not_connected", now + interval
                return
            poll = await producer.poll(dict(entry.get("cursor") or {}), now)
            for event in poll.events:
                await self._submit(event)
                entry["last_event_at"] = now
                entry["events"] = int(entry.get("events") or 0) + 1
            entry.update(
                cursor=poll.cursor, state="polling", errors=0, last_error="", last_poll=now,
                next_at=now + max(interval, poll.min_interval_s),
            )
        except NotConnected:
            log.debug("lead triggers: %s is not connected", producer.id)
            entry["state"], entry["next_at"] = "not_connected", now + interval
        except AuthError:
            log.info("lead triggers: %s needs a reconnect", producer.id)
            entry.update(state="error", last_error="reconnect", next_at=now + AUTH_RETRY_S)
        except RateLimited as exc:
            log.info("lead triggers: %s rate limited for %.0fs", producer.id, exc.retry_after_s)
            entry.update(
                state="backoff", last_error="rate_limited",
                next_at=now + max(exc.retry_after_s, interval),
            )
        except Exception as exc:  # noqa: BLE001 - a provider failure backs off, never raises out
            errors = int(entry.get("errors") or 0) + 1
            log.info("lead triggers: %s poll failed", producer.id, exc_info=True)
            entry.update(
                state="backoff", errors=errors, last_error=str(exc)[:200] or type(exc).__name__,
                next_at=now + min(interval * 2**errors, MAX_BACKOFF_S),
            )

    async def view(self) -> list[dict[str, Any]]:
        """Per poller: connected, state, last poll and event, and the last error."""
        async with self._lock:
            states = await self._load()
            snapshot = {p.id: dict(states.get(p.id) or {}) for p in self._producers}
        out = []
        for producer in self._producers:
            entry = snapshot[producer.id]
            try:
                connected = await producer.connected()
            except Exception:  # noqa: BLE001 - an unreadable store counts as not connected
                log.debug("lead triggers: connection check failed", exc_info=True)
                connected = False
            out.append({
                "id": producer.id, "source": producer.source, "connected": connected,
                "state": entry.get("state") or "waiting",
                "last_poll": entry.get("last_poll") or 0,
                "last_event_at": entry.get("last_event_at") or 0,
                "last_error": entry.get("last_error") or "",
                "events": int(entry.get("events") or 0),
            })
        return out

    async def run(self, every: float = TICK_S, first_delay: float = 30.0) -> None:
        await asyncio.sleep(first_delay)
        while True:
            try:
                await self.tick()
            except Exception:  # noqa: BLE001 - the loop outlives any single failure
                log.warning("lead triggers: poll tick failed", exc_info=True)
            await asyncio.sleep(every)
