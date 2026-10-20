"""When the person last did something in Dodaios itself.

The operating system's input idle time says whether anyone is at the
computer; it cannot say whether the person is in the middle of talking to
Dodaios. Someone working all day in other programs moves the mouse every
second, and background work that waits for "no input for 90 seconds" would
never run. This module records the person's own activity in Dodaios instead:

* a turn the person spoke or typed (voice, the Jarvis chat, an agent chat, a
  prompt typed to a coding pane through the app), noted by whoever observes
  it (the self-building loop);
* keys the person typed into a pane's terminal in the app (the pane's own
  viewer, never a prompt Jarvis or an agent wrote into it);
* a voice call that is open: the person is talking to Dodaios until it ends.

Plain in-memory stamps, one dict write per event; nothing is stored.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterable
from typing import Final

#: Sources this module knows. ``pane`` is typing in a pane's terminal.
TURN: Final[str] = "turn"
PANE: Final[str] = "pane"

_lock = threading.Lock()
_last: dict[str, float] = {}
_calls: set[str] = set()


def note(source: str, *, at: float | None = None) -> None:
    """The person did something in Dodaios (``at``: epoch seconds, default now)."""
    stamp = time.time() if at is None else float(at)
    with _lock:
        if stamp > _last.get(source, 0.0):
            _last[source] = stamp


def call_started(session_id: str) -> None:
    with _lock:
        _calls.add(session_id or "call")


def call_ended(session_id: str) -> None:
    note(TURN)
    with _lock:
        _calls.discard(session_id or "call")
        if not session_id:
            _calls.clear()


def in_call() -> bool:
    with _lock:
        return bool(_calls)


def idle_s(*, sources: Iterable[str] | None = None, now: float | None = None) -> float | None:
    """Seconds since the person's last activity in Dodaios; ``0`` during a call.

    ``None`` when nothing was noted since the app started (and no call is open).
    ``sources`` limits the reading (e.g. ``[PANE]``); a call counts for every
    reading but a pane-only one.
    """
    wanted = None if sources is None else set(sources)
    with _lock:
        if _calls and (wanted is None or TURN in wanted):
            return 0.0
        stamps = [t for s, t in _last.items() if wanted is None or s in wanted]
    if not stamps:
        return None
    return max(0.0, (time.time() if now is None else now) - max(stamps))


def reset_for_tests() -> None:
    with _lock:
        _last.clear()
        _calls.clear()


__all__ = ["PANE", "TURN", "call_ended", "call_started", "idle_s", "in_call", "note"]
