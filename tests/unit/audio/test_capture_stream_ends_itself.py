"""On macOS a microphone stream is ended by its own callback, never from outside.

PortAudio's CoreAudio backend (the build that ships with sounddevice) can
deadlock when a thread stops a stream whose I/O thread is running: the stopping
thread holds the AudioUnit's lock and waits for the device's I/O lock, the I/O
thread holds the I/O lock and waits for the AudioUnit's lock. Neither returns,
every later open of that device waits behind them, and the app hears nobody
until it is restarted. On 2026-11-15 that happened on the maintainer's Mac for
the fourth time in three days; a stress run on the built-in microphone showed
it twice in 1,272 open/start/abort/close cycles.

A stop that the stream's callback asks for is carried out by the I/O thread
itself and cannot meet that lock order. Pinned here: the close asks the
callback, waits for the stream to report that it finished, and only then
touches the handle; a stream whose callback no longer runs is stopped as
before; and the callback and the closing thread never both stop one stream.
"""

from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace
from typing import Any

import pytest

from dodaios.audio import capture
from dodaios.audio.capture import MicrophoneCapture, _StreamEnding

_LOUD_FRAME = b"\x10\x00" * capture.BLOCKSIZE


class _LiveStream:
    """A native stream stand-in with an I/O thread that calls back every few ms.

    It records whether anybody stopped it from another thread while that I/O
    thread was still running, which is the call that deadlocks on a real Mac.
    """

    period_s = 0.004

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.device = kwargs.get("device")
        self.callback = kwargs["callback"]
        self.finished_callback = kwargs.get("finished_callback")
        self.calls: list[str] = []
        self.io_running = threading.Event()
        self.stopped_from_outside_while_running = False
        self._halt = threading.Event()
        self._died = False
        self._io: threading.Thread | None = None

    def start(self) -> None:
        self.io_running.set()
        self._io = threading.Thread(target=self._run, daemon=True)
        self._io.start()

    def _run(self) -> None:
        while not self._halt.is_set():
            try:
                self.callback(_LOUD_FRAME, capture.BLOCKSIZE, None, None)
            except capture.sd.CallbackAbort:
                self.calls.append("ended itself")
                break
            time.sleep(self.period_s)
        self.io_running.clear()
        if self.finished_callback is not None and not self._died:
            self.finished_callback()

    def die(self) -> None:
        """The device went away: no more callbacks, and no word that it finished."""
        self._died = True
        self._halt.set()
        if self._io is not None:
            self._io.join(timeout=2.0)

    def abort(self) -> None:
        if self.io_running.is_set():
            self.stopped_from_outside_while_running = True
        self.calls.append("abort")
        self._halt.set()
        if self._io is not None:
            self._io.join(timeout=2.0)

    def close(self) -> None:
        self.calls.append("close")


@pytest.fixture
def fast_ending(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(capture, "_CALLBACK_END_SETTLE_S", 0.0)


@pytest.fixture
def live_streams(monkeypatch: pytest.MonkeyPatch, fast_ending: None) -> list[_LiveStream]:
    """Open ``_LiveStream`` objects as if this were a Mac with real PortAudio."""
    opened: list[_LiveStream] = []

    def _input_stream(**kwargs: Any) -> _LiveStream:
        stream = _LiveStream(**kwargs)
        opened.append(stream)
        return stream

    monkeypatch.setattr(capture, "_END_FROM_CALLBACK", True)
    monkeypatch.setattr(capture, "_ends_from_callback", lambda _stream: True)
    monkeypatch.setattr(capture.sd, "InputStream", _input_stream)
    monkeypatch.setattr(capture.sd, "query_devices", lambda *_a, **_k: [])
    monkeypatch.setattr(capture.sd, "query_hostapis", lambda: [])
    return opened


async def _first_chunk(mic: MicrophoneCapture) -> None:
    async for _chunk in mic.stream():
        return


@pytest.mark.asyncio
async def test_a_running_stream_is_ended_by_its_own_callback(
    live_streams: list[_LiveStream],
) -> None:
    """The stop that deadlocks CoreAudio (from outside, while running) never happens."""
    mic = MicrophoneCapture(device=3, access_gate=lambda: True)
    async with mic:
        await asyncio.wait_for(_first_chunk(mic), timeout=2.0)

    (stream,) = live_streams
    assert stream.calls == ["ended itself", "abort", "close"]
    assert stream.stopped_from_outside_while_running is False
    assert capture._STREAM_ENDINGS == {}


@pytest.mark.asyncio
async def test_a_stream_closed_before_its_first_callback_still_ends_itself(
    live_streams: list[_LiveStream], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Right after the start is when the deadlock is likeliest: the close waits."""
    monkeypatch.setattr(_LiveStream, "period_s", 0.05)
    release = threading.Event()
    original = _LiveStream._run

    def _late_first_callback(self: _LiveStream) -> None:
        release.wait(2.0)
        original(self)

    monkeypatch.setattr(_LiveStream, "_run", _late_first_callback)
    mic = MicrophoneCapture(device=3, access_gate=lambda: True)
    async with mic:
        # The stream is started, its I/O thread has not called back yet.
        asyncio.get_running_loop().call_later(0.1, release.set)

    (stream,) = live_streams
    assert stream.calls == ["ended itself", "abort", "close"]
    assert stream.stopped_from_outside_while_running is False


@pytest.mark.asyncio
async def test_the_watchdog_restart_of_a_dead_stream_does_not_wait_for_a_callback(
    live_streams: list[_LiveStream], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stream whose callback stopped coming has no I/O thread to ask."""
    monkeypatch.setattr(capture, "_CALLBACK_ALIVE_S", 0.05)
    mic = MicrophoneCapture(device=3, access_gate=lambda: True)
    await mic._try_open_stream()
    (stream,) = live_streams
    stream.die()
    await asyncio.sleep(0.1)

    started = time.monotonic()
    await MicrophoneCapture._discard_stream_off_loop(stream)

    assert time.monotonic() - started < 0.5, "the close waited for a callback that cannot come"
    assert stream.calls == ["abort", "close"]


def test_without_the_platform_flag_the_stream_is_opened_exactly_as_before(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Windows and Linux keep the plain callback and no finished signal."""
    seen: dict[str, Any] = {}

    class _Plain:
        def __init__(self, **kwargs: Any) -> None:
            seen.update(kwargs)

        def start(self) -> None:
            pass

    monkeypatch.setattr(capture, "_END_FROM_CALLBACK", False)
    monkeypatch.setattr(capture, "sd", SimpleNamespace(InputStream=_Plain))
    mic = MicrophoneCapture(device=3, access_gate=lambda: True)

    mic._open_blocking(capture._NativeCall("mic"), 3, 16_000, 512)

    assert seen["callback"] == mic._callback
    assert "finished_callback" not in seen
    assert capture._STREAM_ENDINGS == {}


def test_a_test_double_is_never_asked_to_end_itself(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only a stream made by the PortAudio binding has an I/O thread to ask."""
    monkeypatch.setattr(capture, "_END_FROM_CALLBACK", True)

    class _Double:
        pass

    assert capture._ends_from_callback(_Double()) is False


# --------------------------------------------------------------------------
# The request itself
# --------------------------------------------------------------------------


def _pump(ending: _StreamEnding, stop: threading.Event, *, finish: bool = True) -> threading.Thread:
    """An I/O thread: calls ``in_callback`` until it is told to end the stream."""

    def _run() -> None:
        while not stop.is_set():
            if ending.in_callback():
                if finish:
                    ending.finished.set()
                return
            time.sleep(0.002)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return thread


def test_the_callback_takes_the_request_and_the_stream_reports_finished(
    fast_ending: None,
) -> None:
    ending = _StreamEnding()
    stop = threading.Event()
    thread = _pump(ending, stop)
    try:
        assert ending.end() is True
    finally:
        stop.set()
        thread.join(timeout=2.0)


def test_a_request_nobody_takes_is_withdrawn_so_only_one_side_stops_the_stream(
    monkeypatch: pytest.MonkeyPatch, fast_ending: None
) -> None:
    """A late callback must go on reading: the closing thread is stopping now."""
    monkeypatch.setattr(capture, "_CALLBACK_END_WAIT_S", 0.05)
    ending = _StreamEnding()
    ending.in_callback()  # alive a moment ago, then the callback stalls

    assert ending.end() is False
    assert ending.in_callback() is False, "the callback stopped the stream after the withdrawal"


def test_a_request_the_callback_took_is_waited_for(
    monkeypatch: pytest.MonkeyPatch, fast_ending: None
) -> None:
    """Once the I/O thread is stopping the stream, a stop from outside is the second one."""
    monkeypatch.setattr(capture, "_CALLBACK_END_WAIT_S", 0.05)
    monkeypatch.setattr(capture, "_CALLBACK_END_FINISH_S", 2.0)
    ending = _StreamEnding()
    stop = threading.Event()
    thread = _pump(ending, stop, finish=False)  # takes the request, reports late
    threading.Timer(0.2, ending.finished.set).start()
    try:
        started = time.monotonic()
        assert ending.end() is True
        assert time.monotonic() - started >= 0.15
    finally:
        stop.set()
        thread.join(timeout=2.0)


def test_a_stream_that_never_called_back_is_not_waited_for(
    monkeypatch: pytest.MonkeyPatch, fast_ending: None
) -> None:
    monkeypatch.setattr(capture, "_CALLBACK_ALIVE_S", 0.01)
    ending = _StreamEnding()
    time.sleep(0.03)

    started = time.monotonic()
    assert ending.end() is False
    assert time.monotonic() - started < 0.2


def test_a_stream_that_already_finished_needs_no_request(fast_ending: None) -> None:
    ending = _StreamEnding()
    ending.finished.set()  # the device stopped it

    assert ending.end() is True
    assert ending.in_callback() is False
