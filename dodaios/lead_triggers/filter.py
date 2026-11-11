"""Stage 1: the code filter. No model is ever asked here.

Cheap, deterministic admission checks decide whether an event may even reach
the policies: the source's mode, allow-lists, bot and self filtering, a rate
limit and thread dedupe. Every drop is counted by reason.
"""

from __future__ import annotations

import fnmatch
from collections import deque
from collections.abc import Callable
from typing import Final

from .event import TriggerEvent
from .settings import TriggerSettings

CANDIDATE: Final[str] = "candidate"
_REMEMBERED: Final[int] = 4096


def _listed(value: str, entries: tuple[str, ...]) -> bool:
    value = value.strip().lower()
    for entry in entries:
        if entry.startswith("@") and value.endswith(entry):
            return True
        if fnmatch.fnmatchcase(value, entry):
            return True
    return False


class Stage1:
    """Holds the short memory the checks need (rates, seen ids, open threads)."""

    def __init__(self, clock: Callable[[], float]) -> None:
        self._clock = clock
        self._rates: dict[str, deque[float]] = {}
        self._seen_ids: dict[str, None] = {}
        self._threads: dict[tuple[str, str], float] = {}

    def verdict(
        self, event: TriggerEvent, settings: TriggerSettings, *, thread_owned: bool = False
    ) -> str:
        """``candidate`` or the reason the event is dropped.

        ``thread_owned``: a job subscribes to the event's thread, so quick follow-ups on it
        are not collapsed by the thread dedupe; every other check still applies.
        """
        rule = settings.rule(event.source)
        if rule.mode == "ignore":
            return "ignored_source"
        if rule.mode != "candidate":
            return "explicit_only"
        if event.sender and _listed(event.sender, settings.self_senders):
            return "self"
        if rule.senders and not (event.sender and _listed(event.sender, rule.senders)):
            return "sender_not_allowed"
        # An allow-listed sender passes even when it is a machine (CI, a service).
        if event.is_bot and not rule.senders:
            return "bot"
        if rule.scopes and not (event.scope and _listed(event.scope, rule.scopes)):
            return "scope_not_allowed"
        event_id = event.event_id
        if event_id in self._seen_ids:
            return "duplicate"
        now = self._clock()
        if event.thread_key:
            last = self._threads.get((event.source, event.thread_key))
            if not thread_owned and last is not None and now - last < settings.dedupe_window_s:
                return "duplicate_thread"
        window = self._rates.setdefault(event.source, deque())
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= settings.rate_per_minute:
            return "rate_limited"
        window.append(now)
        self._seen_ids[event_id] = None
        if len(self._seen_ids) > _REMEMBERED:
            self._seen_ids.pop(next(iter(self._seen_ids)))
        if event.thread_key:
            self._threads[(event.source, event.thread_key)] = now
            if len(self._threads) > _REMEMBERED:
                self._threads.pop(next(iter(self._threads)))
        return CANDIDATE
