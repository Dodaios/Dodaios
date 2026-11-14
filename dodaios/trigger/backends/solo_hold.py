"""A modifier-only hold key that fires only while it is held ALONE.

A hold-to-dictate key made of modifiers only (a bare ``cmd`` on macOS, the
key offered there) is also the first half of every shortcut that uses it:
``cmd+c``, ``cmd+tab``, ``cmd+shift+4``, a Command-click. The chord matchers
compare the held set as a SUPERSET, so each of those shortcuts used to start a
dictation on the Command key-down: the microphone opened, the Dodaios Bar
sprang into its level bars, and the empty recording ended on a "nothing was
heard" mark. Seen live on 2026-11-14, where it read as "the wake word keeps
firing although nobody said it".

``SoloHold`` is the gate in front of such a chord's push-to-talk callbacks:

- the press fires only after the chord has been held alone for
  ``SOLO_HOLD_S``; a key (or click) that joins before then turns the hold
  into a shortcut and nothing fires, not even on release;
- a key that joins after the press fired cancels the recording
  (``on_cancel``), and the release that follows fires nothing;
- a release after a clean press fires ``on_release`` as before.

The backends feed it chord-down / foreign-input / chord-up edges from their
own listener thread; the press itself fires from a timer thread. All state
changes happen under one lock, and the callbacks run outside it.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)

#: How long a modifier-only hold key must be held alone before it fires.
#: Long enough that the second key of an ordinary shortcut lands first (people
#: press ``c`` of ``cmd+c`` well inside this), short enough that a deliberate
#: hold-and-speak loses no more than a breath.
SOLO_HOLD_S = 0.3

#: Builds the one-shot timer behind a pending press (``threading.Timer``'s
#: signature). A module attribute so tests can drive time by hand.
_timer_factory: Callable[..., Any] = threading.Timer

_UP = "up"
_PENDING = "pending"
_ACTIVE = "active"
_SPOILED = "spoiled"

Callback = Callable[[], None] | None


class SoloHold:
    """Push-to-talk gate for one modifier-only chord (see module docstring)."""

    def __init__(
        self,
        on_press: Callback,
        on_release: Callback,
        on_cancel: Callback,
        *,
        delay_s: float | None = None,
        timer_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._on_press = on_press
        self._on_release = on_release
        self._on_cancel = on_cancel
        # Read when the gate is built, not when this module is imported, so a
        # test can swap the clock for every gate a backend creates.
        self._delay_s = SOLO_HOLD_S if delay_s is None else delay_s
        self._timer_factory = timer_factory or _timer_factory
        self._lock = threading.Lock()
        self._state = _UP
        self._timer: Any = None
        # Bumped on every edge, so a timer that fires after the hold it was
        # started for has ended can tell and do nothing.
        self._generation = 0

    @property
    def state(self) -> str:
        return self._state

    def down(self, *, alone: bool) -> None:
        """The chord went down; ``alone`` is false when other input is held too."""
        with self._lock:
            self._cancel_timer_locked()
            self._generation += 1
            if not alone:
                self._state = _SPOILED
                return
            self._state = _PENDING
            generation = self._generation
            timer = self._timer_factory(self._delay_s, self._fire, args=(generation,))
            timer.daemon = True
            self._timer = timer
        timer.start()

    def spoil(self) -> None:
        """Other input joined while the chord is down: it is a shortcut."""
        cancel = False
        with self._lock:
            if self._state == _PENDING:
                self._cancel_timer_locked()
                self._state = _SPOILED
            elif self._state == _ACTIVE:
                self._state = _SPOILED
                cancel = True
        if cancel:
            _call(self._on_cancel, "cancel")

    def up(self) -> None:
        """The chord went up."""
        with self._lock:
            previous = self._state
            self._cancel_timer_locked()
            self._generation += 1
            self._state = _UP
        if previous == _ACTIVE:
            _call(self._on_release, "release")

    def reset(self) -> None:
        """Forget the hold without firing anything (listener stop, grant lost)."""
        with self._lock:
            self._cancel_timer_locked()
            self._generation += 1
            self._state = _UP

    def _fire(self, generation: int) -> None:
        with self._lock:
            if generation != self._generation or self._state != _PENDING:
                return
            self._state = _ACTIVE
            self._timer = None
        _call(self._on_press, "press")

    def _cancel_timer_locked(self) -> None:
        timer = self._timer
        self._timer = None
        if timer is not None:
            try:
                timer.cancel()
            except Exception:  # noqa: BLE001 - a stale timer is checked by generation
                log.debug("solo-hold timer cancel failed", exc_info=True)


def _call(callback: Callback, edge: str) -> None:
    if callback is None:
        return
    try:
        callback()
    except Exception:  # noqa: BLE001 - a handler error must not kill the listener
        log.exception("solo-hold %s handler failed (edge dropped)", edge)
