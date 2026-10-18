"""Incoming calls for the phone: Jarvis rings, the app long-polls for it.

There is no push service; the app keeps one ``GET /api/m/ring`` open at a
time and the server answers as soon as a ring is waiting (or after the wait
window with ``None``). Rings live in memory only and expire after a while, so
a phone that was offline does not ring for a question long gone.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from typing import Any

#: A ring older than this is dropped instead of delivered.
RING_TTL_S = 300.0
MAX_RING_TEXT = 300


@dataclass(frozen=True, slots=True)
class Ring:
    ring_id: str
    text: str
    created_at: float

    def to_payload(self) -> dict[str, Any]:
        return {"id": self.ring_id, "text": self.text, "created_at": int(self.created_at)}


class RingBoard:
    """The latest pending ring per device, with waiters woken on a new one."""

    def __init__(self, ttl_s: float = RING_TTL_S) -> None:
        self._ttl_s = ttl_s
        self._pending: dict[str, Ring] = {}
        self._signals: dict[str, asyncio.Event] = {}

    def ring(self, device_id: str, text: str) -> Ring:
        ring = Ring(uuid.uuid4().hex, text.strip()[:MAX_RING_TEXT], time.time())
        self._pending[device_id] = ring
        self._signal(device_id).set()
        return ring

    def take(self, device_id: str) -> Ring | None:
        ring = self._pending.pop(device_id, None)
        self._signal(device_id).clear()
        if ring is None or time.time() - ring.created_at > self._ttl_s:
            return None
        return ring

    async def wait(self, device_id: str, timeout_s: float) -> Ring | None:
        ring = self.take(device_id)
        if ring is not None:
            return ring
        try:
            await asyncio.wait_for(self._signal(device_id).wait(), timeout=timeout_s)
        except TimeoutError:  # the phone did not answer; None means unanswered
            return None
        return self.take(device_id)

    def _signal(self, device_id: str) -> asyncio.Event:
        signal = self._signals.get(device_id)
        if signal is None:
            signal = self._signals[device_id] = asyncio.Event()
        return signal
