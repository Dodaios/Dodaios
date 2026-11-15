"""An open the audio system does not answer ends with a clear error, not a hang.

On 2026-11-15 the close of the wake microphone deadlocked inside CoreAudio.
The next open of that device then never returned. It was awaited without a
limit and held the lock every native open needs, so from that moment the app
heard nobody: the wake word was gone, every dictation "started" and never
ended, the next device change could not be applied, and nothing told the
person why. Only a restart of the app helped.

Pinned here: an open is given a limited time; after that the capture raises
``MicrophoneStuckError`` naming the input and tells the person once; while the
audio system still holds that open no further one is started; a stream that
arrives after nobody waits for it any more is closed; and the state clears by
itself when the audio system answers after all.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

import pytest

from dodaios.audio import capture, topology
from dodaios.audio.capture import MicrophoneCapture, MicrophoneStuckError
from dodaios.core.bus import get_default_bus, reset_default_bus
from dodaios.core.events import (
    MICROPHONE_TROUBLE_REASONS,
    Event,
    MicrophoneRecovered,
    MicrophoneTrouble,
)

BUILT_IN = "MacBook Air Microphone"


class _Stream:
    def __init__(self, **kwargs: Any) -> None:
        self.device = kwargs.get("device")
        self.calls: list[str] = []

    def start(self) -> None:
        self.calls.append("start")

    def abort(self) -> None:
        self.calls.append("abort")

    def close(self) -> None:
        self.calls.append("close")


class _AudioSystem:
    """A ``sounddevice.InputStream`` stand-in whose open can be held back."""

    def __init__(self) -> None:
        self.hold = threading.Event()
        self.hold.set()
        self.opens = 0
        self.streams: list[_Stream] = []

    def stop_answering(self) -> None:
        self.hold.clear()

    def answer(self) -> None:
        self.hold.set()

    def __call__(self, **kwargs: Any) -> _Stream:
        self.opens += 1
        self.hold.wait(timeout=10.0)
        stream = _Stream(**kwargs)
        self.streams.append(stream)
        return stream


def _query_devices(device: int | None = None, kind: str | None = None) -> Any:
    """Three outputs, then the one microphone at index 3."""
    speaker = {"name": "Speakers", "max_input_channels": 0, "max_output_channels": 2, "hostapi": 0}
    microphone = {
        "name": BUILT_IN,
        "max_input_channels": 1,
        "max_output_channels": 0,
        "hostapi": 0,
        "default_samplerate": 48_000,
    }
    devices = [speaker, speaker, speaker, microphone]
    return devices if device is None else devices[device]


@pytest.fixture
def audio(monkeypatch: pytest.MonkeyPatch) -> _AudioSystem:
    system = _AudioSystem()
    monkeypatch.setattr(capture, "_END_FROM_CALLBACK", False)
    monkeypatch.setattr(capture, "_OPEN_TIMEOUT_S", 0.15)
    monkeypatch.setattr(capture.sd, "InputStream", system)
    monkeypatch.setattr(capture.sd, "query_devices", _query_devices)
    monkeypatch.setattr(capture.sd, "query_hostapis", lambda: [{"name": "Core Audio"}])
    monkeypatch.setattr(topology, "_native_streams", {})
    yield system
    system.answer()


@pytest.fixture
def notices() -> list[Event]:
    reset_default_bus()
    seen: list[Event] = []

    async def _keep(event: Event) -> None:
        seen.append(event)

    bus = get_default_bus()
    bus.subscribe(MicrophoneTrouble, _keep)
    bus.subscribe(MicrophoneRecovered, _keep)
    yield seen
    reset_default_bus()


async def _until(condition) -> None:
    """Poll for a state another thread brings about (never a fixed sleep)."""
    deadline = asyncio.get_running_loop().time() + 3.0
    while not condition():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("the expected state was not reached in time")
        await asyncio.sleep(0.01)


async def _answer(audio: _AudioSystem) -> None:
    """Let the held open come back, so no worker thread outlives the test."""
    audio.answer()
    await _until(lambda: capture._UNANSWERED.oldest() is None)


def _mic() -> MicrophoneCapture:
    return MicrophoneCapture(device=3, access_gate=lambda: True, permission_feature="wake_word")


@pytest.mark.asyncio
async def test_an_open_that_does_not_come_back_raises_and_names_the_microphone(
    audio: _AudioSystem, notices: list[Event]
) -> None:
    audio.stop_answering()

    with pytest.raises(MicrophoneStuckError) as raised:
        async with _mic():
            pytest.fail("the capture was entered without a microphone")

    assert raised.value.device_name == BUILT_IN
    assert BUILT_IN in str(raised.value)
    assert capture.stuck_microphone() == BUILT_IN
    (trouble,) = notices
    assert isinstance(trouble, MicrophoneTrouble)
    assert trouble.reason == "not_answering"
    assert trouble.reason in MICROPHONE_TROUBLE_REASONS
    assert trouble.device == BUILT_IN
    assert trouble.feature == "wake_word"
    await _answer(audio)


@pytest.mark.asyncio
async def test_while_one_open_is_stuck_no_further_open_is_started(
    audio: _AudioSystem, notices: list[Event]
) -> None:
    """Each further open would park a thread for good and hold the open guard."""
    audio.stop_answering()
    with pytest.raises(MicrophoneStuckError):
        await _mic()._try_open_stream()
    assert audio.opens == 1

    for _ in range(3):
        with pytest.raises(MicrophoneStuckError):
            await _mic()._try_open_stream()

    assert audio.opens == 1, "another native open was started behind the stuck one"
    assert len(notices) == 1, "the person was told more than once about one episode"
    await _answer(audio)


@pytest.mark.asyncio
async def test_the_late_stream_is_closed_and_the_microphone_works_again(
    audio: _AudioSystem, notices: list[Event]
) -> None:
    audio.stop_answering()
    abandoned = _mic()
    with pytest.raises(MicrophoneStuckError):
        await abandoned._try_open_stream()

    audio.answer()
    await _until(lambda: capture.stuck_microphone() is None)
    await _until(lambda: len(notices) == 2)

    (late,) = audio.streams
    assert late.calls == ["start", "abort", "close"], "the stream nobody waited for was left open"
    assert abandoned._stream is None
    assert topology._native_streams == {}
    assert isinstance(notices[1], MicrophoneRecovered)
    assert notices[1].device == BUILT_IN

    mic = _mic()
    async with mic:
        assert mic._stream is audio.streams[1]
    assert audio.streams[1].calls == ["start", "abort", "close"]


@pytest.mark.asyncio
async def test_an_open_cancelled_half_way_leaves_no_stream_behind(
    audio: _AudioSystem, notices: list[Event]
) -> None:
    """A dictation taken back while its microphone opened used to leak the stream.

    The leaked stream stayed registered, and every device change after that
    was refused because "native streams remain open".
    """
    audio.stop_answering()
    mic = _mic()
    opening = asyncio.create_task(mic.__aenter__())
    await _until(lambda: audio.opens == 1)

    opening.cancel()
    with pytest.raises(asyncio.CancelledError):
        await opening
    audio.answer()
    await _until(lambda: bool(audio.streams) and audio.streams[0].calls[-1:] == ["close"])

    assert mic._stream is None
    assert topology._native_streams == {}
    assert capture.stuck_microphone() is None
    assert notices == [], "a cancelled open is not a microphone that stopped answering"


@pytest.mark.asyncio
async def test_an_ordinary_failure_of_the_open_is_raised_unchanged(
    audio: _AudioSystem, monkeypatch: pytest.MonkeyPatch, notices: list[Event]
) -> None:
    def _refuse(**_kwargs: Any) -> None:
        raise RuntimeError("Internal PortAudio error [PaErrorCode -9986]")

    monkeypatch.setattr(capture.sd, "InputStream", _refuse)

    with pytest.raises(RuntimeError, match="-9986"):
        await _mic()._try_open_stream()

    assert capture.stuck_microphone() is None
    assert notices == []


# --------------------------------------------------------------------------
# A close that does not come back
# --------------------------------------------------------------------------


class _WedgedClose(_Stream):
    def __init__(self, release: threading.Event) -> None:
        super().__init__(device=3)
        self._release = release

    def close(self) -> None:
        self._release.wait(timeout=10.0)
        super().close()


@pytest.mark.asyncio
async def test_on_macos_an_open_waits_for_the_close_that_holds_the_device(
    audio: _AudioSystem, monkeypatch: pytest.MonkeyPatch, notices: list[Event]
) -> None:
    """The open would only queue behind that close, holding the open guard."""
    monkeypatch.setattr(capture, "_CLOSE_HOLDS_DEVICE", True)
    monkeypatch.setattr(MicrophoneCapture, "_DISCARD_GRACE_S", 0.02)
    monkeypatch.setattr(capture, "_OPEN_TIMEOUT_S", 5.0)
    release = threading.Event()
    await MicrophoneCapture._discard_stream_off_loop(_WedgedClose(release))

    opening = asyncio.create_task(_mic()._try_open_stream())
    await asyncio.sleep(0.15)
    assert audio.opens == 0, "an open was started while a close still held the device"

    release.set()
    await asyncio.wait_for(opening, timeout=3.0)
    assert audio.opens == 1
    assert notices == [], "a close that came back in time is nothing to report"


@pytest.mark.asyncio
async def test_on_macos_a_close_that_never_comes_back_is_reported_and_no_open_starts(
    audio: _AudioSystem, monkeypatch: pytest.MonkeyPatch, notices: list[Event]
) -> None:
    monkeypatch.setattr(capture, "_CLOSE_HOLDS_DEVICE", True)
    monkeypatch.setattr(MicrophoneCapture, "_DISCARD_GRACE_S", 0.02)
    release = threading.Event()
    try:
        await MicrophoneCapture._discard_stream_off_loop(_WedgedClose(release))

        with pytest.raises(MicrophoneStuckError) as raised:
            await _mic()._try_open_stream()

        assert raised.value.device_name == BUILT_IN
        assert audio.opens == 0
        assert [type(n) for n in notices] == [MicrophoneTrouble]
    finally:
        release.set()
    await _until(lambda: capture.stuck_microphone() is None)
    await _until(lambda: len(notices) == 2)
    assert isinstance(notices[1], MicrophoneRecovered)


@pytest.mark.asyncio
async def test_elsewhere_a_slow_close_does_not_hold_the_next_open_back(
    audio: _AudioSystem, monkeypatch: pytest.MonkeyPatch, notices: list[Event]
) -> None:
    """On Windows a new stream opens fine beside a close that takes minutes."""
    monkeypatch.setattr(capture, "_CLOSE_HOLDS_DEVICE", False)
    monkeypatch.setattr(MicrophoneCapture, "_DISCARD_GRACE_S", 0.02)
    release = threading.Event()
    try:
        await MicrophoneCapture._discard_stream_off_loop(_WedgedClose(release))

        await asyncio.wait_for(_mic()._try_open_stream(), timeout=1.0)

        assert audio.opens == 1
        assert notices == []
    finally:
        release.set()
