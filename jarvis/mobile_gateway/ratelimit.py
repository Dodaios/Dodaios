"""Per-client sliding-window request limit for the public gateway port."""

from __future__ import annotations

import time
from collections import deque


class RateLimiter:
    def __init__(self, per_minute: int, *, max_clients: int = 4096) -> None:
        self._limit = per_minute
        self._max_clients = max_clients
        self._hits: dict[str, deque[float]] = {}

    def allow(self, client: str, *, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        window_start = now - 60.0
        hits = self._hits.get(client)
        if hits is None:
            if len(self._hits) >= self._max_clients:
                self._prune(window_start)
            hits = self._hits.setdefault(client, deque())
        while hits and hits[0] <= window_start:
            hits.popleft()
        if len(hits) >= self._limit:
            return False
        hits.append(now)
        return True

    def _prune(self, window_start: float) -> None:
        stale = [k for k, v in self._hits.items() if not v or v[-1] <= window_start]
        for key in stale:
            del self._hits[key]
        if len(self._hits) >= self._max_clients:
            self._hits.clear()
