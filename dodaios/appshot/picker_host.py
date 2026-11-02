"""A warm, pixel-free picker runtime; one visible selection at a time.

Qt lives in a child process. Only an explicit pick command takes a fresh
desktop image; standby imports the GUI without opening a window. Readers are
joined before reuse and a cancelled or timed-out request discards its process,
so a late result can never complete the next request.

A shortcut press opens the warm picker straight from the listener's thread
(:meth:`PickerHost.open_now`), before the event loop, the config and the
screen freeze have had their turn: the overlay is up in a frame, like a
native screenshot tool. Until the parent has frozen the screens, the overlay
is hidden from screen captures, so the appshot never contains it.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import logging
import subprocess
import sys
import threading
import time
from typing import Any

from dodaios.appshot import picker as wire
from dodaios.appshot import region

log = logging.getLogger(__name__)
_START_TIMEOUT_S = 5.0
#: Opening on the press needs the overlay hidden from captures meanwhile.
FAST_OPEN = sys.platform == "win32"


class PickerHost:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._proc: subprocess.Popen[str] | None = None
        self._active: asyncio.Task | None = None
        #: Guards the picker's stdin and the fast-open state across threads.
        self._io = threading.RLock()
        self._picking = False
        #: Wall clock of a press that already opened the picker, not yet picked.
        self._opened_at: float | None = None
        self._shielded = False
        self._language = "en"
        self._keep_area = False

    def configure(self, language: str, keep_area: bool) -> None:
        """What the next press opens with, before the config is read again."""
        with self._io:
            self._language = language or "en"
            self._keep_area = bool(keep_area)

    def open_now(self) -> bool:
        """Show the warm picker at once. Safe from any thread; never blocks.

        ``False`` when it cannot (no warm picker, one already open, not
        Windows): the normal path then opens it as before.
        """
        if not FAST_OPEN:
            return False
        with self._io:
            proc = self._proc
            if self._picking or self._opened_at is not None:
                return False
            if proc is None or proc.poll() is not None:
                return False
            try:
                self._send(
                    proc,
                    {
                        "cmd": wire.CMD_START,
                        "language": self._language,
                        "keep_area": self._keep_area,
                        "shield": True,
                    },
                )
            except (OSError, ValueError, region.RegionUnavailable):
                log.debug("appshot: fast open skipped; the take opens the picker", exc_info=True)
                return False
            self._opened_at = time.time()
            self._shielded = True
            return True

    async def discard_opened(self) -> None:
        """Close a picker a press opened when no selection followed (a refusal)."""
        with self._io:
            if self._opened_at is None or self._picking:
                return
            self._opened_at = None
            self._shielded = False
        log.info("appshot: closing the picker the press opened; nothing was selected")
        async with self._lock:
            # Its "ready" and the cancel's answer are still in the pipe: a fresh
            # process is the only way the next pick cannot read them.
            await self._dispose()
            try:
                await self._ensure()
            except Exception:  # noqa: BLE001 - the next press retries
                log.debug("appshot: picker re-warm failed", exc_info=True)

    async def prewarm(self) -> None:
        if not region.picker_capability()[0]:
            return
        async with self._lock:
            await self._ensure()

    @staticmethod
    def _standby(proc: subprocess.Popen[str]) -> bool:
        assert proc.stdout is not None
        for line in proc.stdout:
            payload = wire.decode(line)
            if payload and payload.get("event") == wire.EVENT_STANDBY:
                return True
        return False

    @staticmethod
    def _send(proc: subprocess.Popen[str], payload: dict) -> None:
        if proc.stdin is None or proc.poll() is not None:
            raise region.RegionUnavailable("The selection overlay stopped unexpectedly.")
        proc.stdin.write(wire.encode(payload))
        proc.stdin.flush()

    def _write(self, proc: subprocess.Popen[str], payload: dict) -> None:
        with self._io:
            self._send(proc, payload)

    async def _dispose(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            await asyncio.to_thread(self._write, proc, {"cmd": wire.CMD_QUIT})
        except (OSError, ValueError, region.RegionUnavailable):
            log.debug("appshot: picker pipe already closed during shutdown")
        await asyncio.to_thread(region._reap, proc)

    async def _ensure(self) -> subprocess.Popen[str]:
        if self._proc is not None and self._proc.poll() is None:
            return self._proc
        await self._dispose()
        spawn = asyncio.create_task(asyncio.to_thread(region._spawn, resident=True))
        reader = None
        try:
            try:
                self._proc = await asyncio.shield(spawn)
            except asyncio.CancelledError:
                # to_thread cannot cancel Popen: acquire the late child first.
                self._proc = await spawn
                raise
            reader = asyncio.create_task(asyncio.to_thread(self._standby, self._proc))
            ready = await asyncio.wait_for(asyncio.shield(reader), _START_TIMEOUT_S)
            if not ready:
                code = self._proc.poll()
                raise region.RegionUnavailable(region._exit_message(code or 1))
            return self._proc
        except BaseException:
            await self._dispose()
            if reader is not None:
                await reader  # reap closes stdout, including a stuck startup
            raise

    async def pick(
        self, timeout_s: float, language: str, *, keep_area: bool = False
    ) -> tuple[Any, int | None, bool]:
        async with self._lock:
            self._active = asyncio.current_task()
            self.configure(language, keep_area)
            with self._io:
                self._picking = True
                opened_at, self._opened_at = self._opened_at, None
                opened_proc = self._proc if opened_at is not None else None
            try:
                return await self._pick(timeout_s, language, keep_area, opened_at, opened_proc)
            finally:
                with self._io:
                    self._picking = False
                    self._shielded = False
                self._active = None

    async def _pick(
        self,
        timeout_s: float,
        language: str,
        keep_area: bool,
        opened_at: float | None = None,
        opened_proc: subprocess.Popen[str] | None = None,
    ) -> tuple[Any, int | None, bool]:
        started = time.time()
        proc = await self._ensure()
        # The press opened this very process; a replaced one never saw it.
        preopened = opened_at is not None and opened_proc is proc
        if preopened and self._shielded:
            # The caller froze the screens before picking: captures may see it.
            with self._io:
                self._shielded = False
            await asyncio.to_thread(self._write, proc, {"cmd": wire.CMD_UNSHIELD})
        try:
            # Up already, the overlay must not become a snap target itself.
            read = functools.partial(region.snap_layout, skip_pid=proc.pid)
            layout = await asyncio.to_thread(read if preopened else region.snap_layout)
        except Exception:
            log.debug("appshot: snap layout unavailable", exc_info=True)
            layout = {}
        escape = None
        reader = None
        payload = None
        timed_out = False
        try:
            if preopened:
                await asyncio.to_thread(self._write, proc, {"cmd": wire.CMD_LAYOUT, **layout})
            else:
                start = {"cmd": wire.CMD_START, "language": language, "keep_area": keep_area}
                await asyncio.to_thread(self._write, proc, {**start, **layout})
            loop = asyncio.get_running_loop()
            escape = loop.create_task(region._escape_cancels(proc), name="appshot-region-esc")

            def marking() -> None:
                loop.call_soon_threadsafe(escape.cancel)

            def ready(event: dict[str, Any]) -> None:
                at = event.get("at")
                shown = float(at) if isinstance(at, (int, float)) else time.time()
                since = opened_at if preopened and opened_at is not None else started
                log.info(
                    "appshot: picker visible %.1f ms after the %s",
                    (shown - since) * 1000,
                    "press" if preopened else "request",
                )

            def option(payload: dict[str, Any]) -> None:
                if isinstance(payload.get("keep_area"), bool):
                    self.configure(language, payload["keep_area"])
                    loop.call_soon_threadsafe(_remember_keep_area, payload["keep_area"])

            reader = asyncio.create_task(
                asyncio.to_thread(region._read_result, proc, marking, ready, option)
            )
            try:
                payload = await asyncio.wait_for(asyncio.shield(reader), timeout_s)
            except TimeoutError:
                log.info("appshot: selection timed out; closing the picker")
                timed_out = True
        finally:
            if escape is not None:
                escape.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await escape
            if payload is None:
                await self._dispose()
            if reader is not None:
                await reader
        return payload, proc.poll(), timed_out

    async def close(self) -> None:
        active = self._active
        if active is not None and active is not asyncio.current_task():
            active.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await active
        async with self._lock:
            await self._dispose()


#: Saves of the "adjust before taking" switch still being written.
_saving: set[asyncio.Task] = set()


def _remember_keep_area(keep: bool) -> None:
    """Write the switch into ``[appshot].region_keep_area`` off the event loop."""

    def write() -> None:
        from dodaios.core.config_writer import set_appshot_settings  # noqa: PLC0415

        set_appshot_settings({"region_keep_area": keep})

    async def save() -> None:
        try:
            await asyncio.to_thread(write)
        except Exception:  # noqa: BLE001 - the switch still holds for this selection
            log.warning("appshot: could not remember the area switch", exc_info=True)

    task = asyncio.get_running_loop().create_task(save(), name="appshot-keep-area")
    _saving.add(task)
    task.add_done_callback(_saving.discard)


_host: PickerHost | None = None


def get_picker_host() -> PickerHost:
    global _host
    if _host is None:
        _host = PickerHost()
    return _host


async def close_picker_host() -> None:
    global _host
    host, _host = _host, None
    if host is not None:
        await host.close()
