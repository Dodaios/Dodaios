"""The state a benchmark run computes under, instead of the live one.

To tell whether a change is better, the same task runs twice: once as the
assistant is now, once with the change (or with everything learned taken
away). Neither run may touch the live assistant. An :class:`Overlay` says what
is different for a run, and every reader of learned state asks
:func:`current` before it reads:

* ``params`` replaces the values of parameters (:mod:`dodaios.rsi.params`);
* ``factory`` counts every learned change as rolled back: the assistant as
  it ships;
* ``without`` counts single changes as rolled back (is the assistant worse
  without this one?);
* ``now_ms`` is the clock the run sees, so both runs of a pair score recency
  alike.

While any overlay is active the run is a replay: it writes nothing into live
stores (no use counter, no cache entry). :func:`replaying` is the one question
writers ask.

Two ways to activate one. :func:`active` covers code that runs in this task
and its children. A coding CLI calls tools back through the gateway in another
task, so such a run is also registered by its session id with
:func:`for_session`, and the gateway asks :func:`current` with that id.
"""

from __future__ import annotations

import contextlib
import contextvars
import threading
import time
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Final

__all__ = ["FACTORY", "Overlay", "active", "current", "for_session", "now_ms", "replaying"]

_EMPTY: Final[Mapping[str, Any]] = MappingProxyType({})


@dataclass(frozen=True, slots=True)
class Overlay:
    """What is different from the live assistant during one benchmark run."""

    #: A name for logs and results ("factory", "candidate:<change id>").
    label: str = ""
    #: Parameter values that replace the live ones.
    params: Mapping[str, Any] = field(default_factory=lambda: _EMPTY)
    #: Every learned change counts as rolled back.
    factory: bool = False
    #: Ids of learned changes that count as rolled back.
    without: frozenset[str] = frozenset()
    #: The clock the run sees; ``None`` is the real one.
    now_ms: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "params", MappingProxyType(dict(self.params)))
        object.__setattr__(self, "without", frozenset(self.without))

    def excludes(self, change_id: str) -> bool:
        """True when this run must not see the learned change ``change_id``."""
        return self.factory or change_id in self.without


#: The assistant as it ships: nothing learned applies.
FACTORY: Final[Overlay] = Overlay(label="factory", factory=True)

_task: contextvars.ContextVar[Overlay | None] = contextvars.ContextVar("rsi_overlay", default=None)
_sessions: dict[str, Overlay] = {}
_sessions_lock = threading.Lock()


def current(session_id: str = "") -> Overlay | None:
    """The overlay of the running task, else the one registered for ``session_id``."""
    found = _task.get()
    if found is not None or not session_id:
        return found
    with _sessions_lock:
        return _sessions.get(session_id)


def replaying(session_id: str = "") -> bool:
    """True inside a benchmark run: nothing may be written into live state."""
    return current(session_id) is not None


def now_ms(session_id: str = "") -> int:
    """The time a reader should use: the overlay's clock in a run, else the real one."""
    found = current(session_id)
    if found is not None and found.now_ms is not None:
        return found.now_ms
    return int(time.time() * 1000)


@contextlib.contextmanager
def active(overlay: Overlay) -> Iterator[Overlay]:
    """Run the enclosed code, and the tasks it starts, under ``overlay``."""
    token = _task.set(overlay)
    try:
        yield overlay
    finally:
        _task.reset(token)


@contextlib.contextmanager
def for_session(session_id: str, overlay: Overlay) -> Iterator[Overlay]:
    """Also register ``overlay`` under a session id, for calls that arrive in another task."""
    if not session_id:
        raise ValueError("a session overlay needs a session id")
    with _sessions_lock:
        if session_id in _sessions:
            raise RuntimeError(f"session {session_id!r} already runs under an overlay")
        _sessions[session_id] = overlay
    try:
        with active(overlay):
            yield overlay
    finally:
        with _sessions_lock:
            _sessions.pop(session_id, None)
