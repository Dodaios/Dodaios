"""Restart the app when the audio system no longer answers for the microphone.

A native audio call that never returns holds locks inside the operating
system's audio client of this process. Nothing in the process can take them
back: every later open of that input waits behind the first one, so the wake
word and dictation stay deaf until a new process starts. On 2026-11-15 the
maintainer's app sat in that state for sixteen minutes, until it was restarted
by hand.

``dodaios.audio.capture`` keeps the rest of the app working in that state (no
further native call is started, the person is told which microphone it is) and
names the stuck input through ``stuck_microphone()``. This module is the cure:
once the input has been stuck for a while and nothing is running that a
restart would end, it asks the app to restart, exactly as the app does after
an update of its own code. The notice in the window says so beforehand and
offers the same restart at once.

A restart that does not help must not repeat for ever, so the restarts made
here are counted across restarts of the process and stop after a few per hour.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from pathlib import Path

from loguru import logger

#: How long the input must have been reported stuck before a restart is due.
#: The report itself comes ten seconds after the audio system stopped answering.
STUCK_FOR_S = 20.0
#: How often the state is looked at.
POLL_S = 5.0
#: No more than this many rescue restarts within ``WINDOW_S``. A restart that
#: does not free the microphone (a broken audio driver) would otherwise loop.
MAX_RESTARTS = 3
WINDOW_S = 3600.0

_STATE_FILE = "microphone_rescue.json"


class MicrophoneRescue:
    """Decides when a stuck microphone is worth a restart of the app.

    ``stuck`` returns the name of the stuck input or ``None``; ``idle`` says
    whether nothing is running that a restart would end; ``restart`` asks the
    app to restart and returns whether it will. ``tick`` is the whole decision
    and takes no time, so it is what the tests call.
    """

    def __init__(
        self,
        *,
        stuck: Callable[[], str | None],
        idle: Callable[[], bool],
        restart: Callable[[], bool],
        data_dir: Path,
        clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._stuck = stuck
        self._idle = idle
        self._restart = restart
        self._state_path = Path(data_dir) / _STATE_FILE
        self._clock = clock
        self._monotonic = monotonic
        self._since: float | None = None
        self._asked = False
        self._said_why_not = False

    def tick(self) -> bool:
        """Look once. ``True`` when a restart was asked for in this call."""
        name = self._stuck()
        if name is None:
            self._since = None
            self._asked = False
            self._said_why_not = False
            return False
        now = self._monotonic()
        if self._since is None:
            self._since = now
        if self._asked or now - self._since < STUCK_FOR_S:
            return False
        if not self._idle():
            return False
        recent = self._recent_restarts()
        if len(recent) >= MAX_RESTARTS:
            self._say_once(
                "The microphone '{}' is stuck again and {} restarts within the "
                "last hour did not help; not restarting by itself any more.",
                name,
                len(recent),
            )
            return False
        self._write_restarts([*recent, self._clock()])
        if not self._restart():
            self._write_restarts(recent)  # nothing was restarted
            self._say_once(
                "The microphone '{}' is stuck and this app cannot restart itself.", name
            )
            return False
        self._asked = True
        logger.warning(
            "Restarting to free the microphone: the audio system has not answered "
            "for '{}' for {:.0f}s.",
            name,
            now - self._since,
        )
        return True

    async def run(self) -> None:
        """Look every ``POLL_S`` until cancelled. A failed look never ends it."""
        while True:
            await asyncio.sleep(POLL_S)
            try:
                self.tick()
            except Exception:  # noqa: BLE001 - a rescue that crashed rescues nothing later
                logger.opt(exception=True).debug("Microphone rescue look failed.")

    def _say_once(self, message: str, *args: object) -> None:
        if self._said_why_not:
            return
        self._said_why_not = True
        logger.warning(message, *args)

    def _recent_restarts(self) -> list[float]:
        try:
            raw = json.loads(self._state_path.read_text(encoding="utf-8"))
            stamps = [float(value) for value in raw.get("restarts", [])]
        except (OSError, ValueError, TypeError, AttributeError):
            # No file yet, or one that is not ours: nothing was restarted.
            return []
        now = self._clock()
        return [stamp for stamp in stamps if 0.0 <= now - stamp < WINDOW_S]

    def _write_restarts(self, stamps: list[float]) -> None:
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(json.dumps({"restarts": stamps}), encoding="utf-8")
        except OSError as exc:
            # Without the count a loop could not be seen: better no restart.
            raise RuntimeError("The rescue restart could not be recorded.") from exc


__all__ = ["MAX_RESTARTS", "POLL_S", "STUCK_FOR_S", "WINDOW_S", "MicrophoneRescue"]
