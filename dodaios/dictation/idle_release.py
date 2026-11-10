"""Give an unused dictation engine's memory back to the machine.

Each on-device dictation engine lives in a worker process of its own
(:mod:`dodaios.dictation.preview_worker`). A worker on a CUDA card holds 1.3 to
2.1 GB of committed memory and several hundred MB of accelerator memory for as
long as it runs, and it used to run from the app's start to its end: measured
on 2026-11-10, the two workers held 3.4 GB of the app's 6 GB through a night in
which nobody dictated.

A worker comes back in about two seconds (the preview engine) to five (the
final pass), and a dictation starts both again the moment the key goes down.
So an engine nobody has used for a while is released, and the next press pays
that start once.

:class:`IdleRelease` is the clock for it. The owner calls :meth:`IdleRelease.arm`
when it has an engine, :meth:`IdleRelease.touch` whenever the engine is used,
and hands in the callable that puts the engine down. One daemon thread watches
per armed engine and ends with the release, so an app that never dictates
runs no thread at all.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

log = logging.getLogger(__name__)

#: Minutes without a dictation after which an engine is released, unless the
#: settings say otherwise (``[dictation].local_idle_minutes``).
DEFAULT_IDLE_MINUTES = 10.0

#: How soon the watch looks again when the engine was busy at its deadline.
_BUSY_RETRY_S = 15.0


class IdleRelease:
    """Call ``release`` once ``idle_s`` pass without a :meth:`touch`.

    ``release`` answers ``True`` when the engine is gone (released now, or
    dropped by somebody else meanwhile) and ``False`` when it was busy; a busy
    engine is asked again shortly. ``idle_s <= 0`` switches the watch off.
    """

    def __init__(
        self,
        idle_s: float,
        release: Callable[[], bool],
        *,
        name: str,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.idle_s = float(idle_s)
        self._release = release
        self._name = name
        self._clock = clock
        self._last_used = clock()
        self._lock = threading.Lock()
        self._stop: threading.Event | None = None

    def touch(self) -> None:
        """The engine was used just now."""
        self._last_used = self._clock()

    @property
    def watching(self) -> bool:
        return self._stop is not None

    def arm(self) -> None:
        """Start watching a freshly built engine.

        A watch that is still running belongs to the engine before this one
        (it may be on its way out after a release), so it is replaced rather
        than trusted to cover the new engine.
        """
        self.touch()
        stop = threading.Event()
        with self._lock:
            previous, self._stop = self._stop, (stop if self.idle_s > 0 else None)
        if previous is not None:
            previous.set()
        if self.idle_s <= 0:
            return
        threading.Thread(target=self._watch, args=(stop,), name=self._name, daemon=True).start()

    def disarm(self) -> None:
        """Stop watching: the owner dropped the engine itself."""
        with self._lock:
            stop, self._stop = self._stop, None
        if stop is not None:
            stop.set()

    def due_in(self) -> float:
        """Seconds until the engine counts as idle; ``<= 0`` means now."""
        return self._last_used + self.idle_s - self._clock()

    def check(self) -> float | None:
        """Release when due. Seconds until the next look, ``None`` when done."""
        if self.idle_s <= 0:
            return None
        remaining = self.due_in()
        if remaining > 0:
            return remaining
        try:
            released = self._release()
        except Exception:  # noqa: BLE001 - a failed release must not end the watch silently
            log.exception("%s: releasing the idle engine failed", self._name)
            return _BUSY_RETRY_S
        return None if released else _BUSY_RETRY_S

    def _watch(self, stop: threading.Event) -> None:
        while not stop.is_set():
            wait = self.check()
            if wait is None:
                break
            if stop.wait(wait):
                return
        with self._lock:
            if self._stop is stop:
                self._stop = None


__all__ = ["DEFAULT_IDLE_MINUTES", "IdleRelease"]
