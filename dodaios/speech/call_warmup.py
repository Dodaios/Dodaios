"""Warm what a call needs the moment the person reaches for the call button.

The first sentence of a call pays for everything that is still cold: the
realtime stack's imports (``dodaios.realtime.*`` is kept out of boot on
purpose), the provider transport (a WebSocket or WebRTC sideband the
factory can pre-spawn), the TTS client and the local STT engine of the
classic path, and the barge-in detector's ONNX model. All of it can be
prepared while the pointer is still travelling to the button (issue #154).

``POST /api/voice/warm`` lands here. The work runs as a background task so
the route answers at once; a second request inside :data:`MIN_INTERVAL_S`
is a no-op, so a hovering pointer cannot start the work twice. Nothing here
bills a provider: the transport warm the factory offers is a connection, not
a session, and the TTS/STT steps only load clients and models. Every step
is optional and fails alone.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

log = logging.getLogger(__name__)

#: Two warms closer together than this are one warm.
MIN_INTERVAL_S = 30.0


def _warm_imports() -> None:
    """Import the realtime stack so the call's own lazy imports hit the cache."""
    import importlib

    for name in (
        "dodaios.realtime.desktop",
        "dodaios.realtime.factory",
        "dodaios.realtime.session",
    ):
        importlib.import_module(name)


def _warm_tts(pipeline: Any) -> bool:
    tts = getattr(pipeline, "_tts", None)
    if tts is None:
        return False
    for attr in ("warm_up", "_ensure_client"):
        hook = getattr(tts, attr, None)
        if callable(hook):
            hook()
            return True
    return False


def _warm_stt(pipeline: Any) -> bool:
    stt = getattr(pipeline, "_utterance_stt", None) or getattr(pipeline, "_stt", None)
    hook = getattr(stt, "warm_up", None)
    if callable(hook):
        hook()
        return True
    return False


def _warm_barge_detector() -> None:
    from dodaios.realtime.desktop import DesktopRealtimeBargeInDetector

    DesktopRealtimeBargeInDetector().warmup()


class CallWarmer:
    """Debounced, background warm-up of the next call's cold parts."""

    def __init__(
        self,
        *,
        min_interval_s: float = MIN_INTERVAL_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._min_interval_s = float(min_interval_s)
        self._clock = clock
        self._last_started = float("-inf")
        self._task: asyncio.Task[Any] | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def kick(self, pipeline: Any, config: Any) -> bool:
        """Start a warm unless one ran recently; ``True`` when one started."""
        now = self._clock()
        if self.running or now - self._last_started < self._min_interval_s:
            return False
        self._last_started = now
        self._task = asyncio.create_task(
            self.warm(pipeline, config), name="voice-call-warm"
        )
        return True

    async def warm(self, pipeline: Any, config: Any) -> dict[str, bool]:
        """Run every warm step, each on its own; returns what succeeded."""
        done: dict[str, bool] = {}
        started = time.monotonic()
        steps: list[tuple[str, Callable[[], Any]]] = [
            ("imports", _warm_imports),
            ("barge_detector", _warm_barge_detector),
        ]
        if pipeline is not None:
            steps.append(("tts", lambda: _warm_tts(pipeline)))
            steps.append(("stt", lambda: _warm_stt(pipeline)))
        for name, step in steps:
            try:
                result = await asyncio.to_thread(step)
                done[name] = result is not False
            except Exception as exc:  # noqa: BLE001 — a warm step must never cost the call
                log.debug("call warm step %s skipped: %s", name, exc)
                done[name] = False
        done["transports"] = await self._warm_transports(config)
        log.info(
            "Voice call warmed in %.0f ms: %s",
            (time.monotonic() - started) * 1000.0,
            ", ".join(k for k, v in done.items() if v) or "nothing to do",
        )
        return done

    @staticmethod
    async def _warm_transports(config: Any) -> bool:
        if config is None:
            return False
        try:
            from dodaios.realtime.factory import realtime_warm_selected_transports

            await realtime_warm_selected_transports(config)
            return True
        except Exception as exc:  # noqa: BLE001 — a cold transport is the status quo
            log.debug("realtime transport warm skipped: %s", exc)
            return False


_warmer: CallWarmer | None = None


def call_warmer() -> CallWarmer:
    """The process-wide warmer (one debounce window for every window)."""
    global _warmer
    if _warmer is None:
        _warmer = CallWarmer()
    return _warmer


def set_call_warmer(warmer: CallWarmer | None) -> None:
    """Replace the process-wide warmer (tests)."""
    global _warmer
    _warmer = warmer


__all__ = ["MIN_INTERVAL_S", "CallWarmer", "call_warmer", "set_call_warmer"]
