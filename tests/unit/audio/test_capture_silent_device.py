"""An automatically chosen microphone that delivers nothing is left for the next.

The automatic selection takes the operating system's default input first. That
default can be an input with nothing behind it: a headphone jack without a
microphone, a virtual microphone whose app is closed. Such an input delivers
exact zeros, and the app then heard nobody: a dictation recorded silence while
every other program on the computer, which used the built-in microphone,
recorded the voice.

Pinned here: the capture leaves such an input after a second of exact zeros
from its first frame, the input is passed over by later selections until the
set of devices changes, and a microphone the person named or pinned is never
left.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from types import SimpleNamespace

import pytest

from dodaios.audio import capture
from tests.fakes.fake_tcc import (
    FakeAudioInput,
    TccService,
    install_port,
    make_darwin_port,
)

MIC = TccService.MICROPHONE
_ZERO_FRAME = b"\x00\x00" * capture.BLOCKSIZE
_LOUD_FRAME = b"\x10\x00" * capture.BLOCKSIZE

EXTERNAL = "External Microphone"
BUILT_IN = "MacBook Air Microphone"


def _device(name: str, *, inputs: int = 1) -> dict:
    return {
        "name": name,
        "max_input_channels": inputs,
        "max_output_channels": 0 if inputs else 2,
        "hostapi": 0,
        "default_samplerate": 48_000,
    }


def _laptop_with_headphones() -> list[dict]:
    """A laptop with headphones in the jack and the usual virtual microphones."""
    return [
        _device(EXTERNAL),
        _device("External Headphones", inputs=0),
        _device(BUILT_IN),
        _device("MacBook Air Speakers", inputs=0),
        _device("Camo Microphone", inputs=2),
        _device("Microsoft Teams Audio"),
        _device("EpocCam Microphone", inputs=2),
        _device("ZoomAudioDevice", inputs=2),
    ]


@pytest.fixture(autouse=True)
def _fresh_memory() -> None:
    capture._invalidate_resolve_cache()
    capture._forget_silent_inputs()
    yield
    capture._invalidate_resolve_cache()
    capture._forget_silent_inputs()


def _ranked_names(devices: list[dict], *, default: int = 0) -> list[str]:
    hostapis = [{"name": "Core Audio"}]
    capture.sd.default = SimpleNamespace(device=(default, 1))
    return [
        str(dev["name"])
        for _idx, dev in capture._rank_input_device_candidates(devices, hostapis)
    ]


@pytest.fixture
def os_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Let a test set the operating system's default input on a stand-in ``sd``."""
    monkeypatch.setattr(capture, "sd", SimpleNamespace(default=SimpleNamespace(device=(0, 1))))


# --------------------------------------------------------------------------
# Which microphone the automatic selection takes
# --------------------------------------------------------------------------


def test_the_os_default_input_is_the_first_choice(os_default: None) -> None:
    assert _ranked_names(_laptop_with_headphones())[0] == EXTERNAL


def test_an_input_known_to_be_silent_goes_last_and_the_built_in_one_leads(
    os_default: None,
) -> None:
    devices = _laptop_with_headphones()
    capture._remember_silent_input(EXTERNAL, devices)

    ranked = _ranked_names(devices)

    assert ranked[0] == BUILT_IN
    assert ranked[-1] == EXTERNAL


def test_microphones_of_camera_and_meeting_apps_stand_behind_a_real_one(
    os_default: None,
) -> None:
    """They carry audio only while their app feeds them, so none of them is
    chosen while a real microphone exists, even as the OS default."""
    devices = _laptop_with_headphones()
    capture._remember_silent_input(EXTERNAL, devices)

    ranked = _ranked_names(devices, default=4)  # the OS default is the Camo one

    assert ranked[0] == BUILT_IN
    assert set(ranked[1:4]) <= {
        "Camo Microphone",
        "Microsoft Teams Audio",
        "EpocCam Microphone",
        "ZoomAudioDevice",
    }


def test_a_silent_input_is_tried_again_when_the_devices_change(os_default: None) -> None:
    """Unplugging and plugging something is how a jack gets its microphone."""
    devices = _laptop_with_headphones()
    capture._remember_silent_input(EXTERNAL, devices)
    assert capture._input_known_silent(EXTERNAL, devices)

    replugged = [*devices, _device("USB Headset")]

    assert not capture._input_known_silent(EXTERNAL, replugged)
    assert _ranked_names(devices)[0] == EXTERNAL, "the memory must be gone for good"


def test_a_silent_input_is_tried_again_after_a_while(
    os_default: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    devices = _laptop_with_headphones()
    now = [1_000.0]
    monkeypatch.setattr(capture.time, "monotonic", lambda: now[0])
    capture._remember_silent_input(EXTERNAL, devices)

    now[0] += capture._SILENT_INPUT_MEMORY_S - 1
    assert capture._input_known_silent(EXTERNAL, devices)
    now[0] += 2
    assert not capture._input_known_silent(EXTERNAL, devices)


def test_the_name_is_matched_whatever_its_case_and_spacing(os_default: None) -> None:
    devices = _laptop_with_headphones()
    capture._remember_silent_input("  external   MICROPHONE ", devices)

    assert capture._input_known_silent(EXTERNAL, devices)
    assert not capture._input_known_silent(BUILT_IN, devices)


# --------------------------------------------------------------------------
# A running capture leaves the silent input
# --------------------------------------------------------------------------


def _granted_mac(
    monkeypatch: pytest.MonkeyPatch, devices: list[dict]
) -> FakeAudioInput:
    """A Mac that granted the microphone, with ``devices`` as its audio hardware."""
    port, tcc = make_darwin_port(granted=[MIC])
    install_port(monkeypatch, port)
    audio = FakeAudioInput(tcc)

    def query_devices(device: int | None = None, kind: str | None = None):
        return devices if device is None else devices[device]

    monkeypatch.setattr(
        capture,
        "sd",
        SimpleNamespace(
            InputStream=audio,
            query_devices=query_devices,
            query_hostapis=lambda: [{"name": "Core Audio"}],
            default=SimpleNamespace(device=(0, 1)),
        ),
    )
    monkeypatch.setattr(capture.MicrophoneCapture, "_WATCHDOG_TICK_S", 0.01)
    monkeypatch.setattr(capture, "_SILENCE_SWITCH_AFTER_S", 0.05)
    return audio


async def _wait_for(predicate: Callable[[], bool], *, timeout_s: float = 3.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_s
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not reached in time")
        await asyncio.sleep(0.01)


async def _pump(stream, frame: bytes, *, frames: int) -> None:
    for _ in range(frames):
        stream.callback(frame, capture.BLOCKSIZE, None, None)
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_a_capture_leaves_an_input_that_delivers_only_zeros(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    devices = _laptop_with_headphones()
    audio = _granted_mac(monkeypatch, devices)

    mic = capture.MicrophoneCapture(device="auto-headset")
    assert mic._device == 0
    async with mic:
        (first,) = audio.starts
        assert first.kwargs["device"] == 0

        async def _zeros_until_left() -> None:
            while len(audio.starts) < 2:
                await _pump(first, _ZERO_FRAME, frames=1)

        await asyncio.wait_for(_zeros_until_left(), timeout=3.0)
        second = audio.starts[1]

        assert second.kwargs["device"] == 2, "the built-in microphone comes next"
        assert first.closed
        assert mic._device == 2

        # What the next microphone hears reaches the consumer.
        frames = mic.stream()
        await _pump(second, _LOUD_FRAME, frames=3)

        async def _first_audible() -> bytes:
            async for chunk in frames:
                if chunk.pcm.strip(b"\x00"):
                    return chunk.pcm
            return b""

        assert await asyncio.wait_for(_first_audible(), timeout=2.0)
        await frames.aclose()

    assert capture._input_known_silent(EXTERNAL, devices)
    # The next capture starts on the microphone that works.
    assert capture.MicrophoneCapture(device="auto-headset")._device == 2


@pytest.mark.asyncio
async def test_silence_after_real_sound_is_a_quiet_room_not_a_dead_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    devices = _laptop_with_headphones()
    audio = _granted_mac(monkeypatch, devices)

    async with capture.MicrophoneCapture(device="auto-headset"):
        (stream,) = audio.starts
        await _pump(stream, _LOUD_FRAME, frames=3)
        await _pump(stream, _ZERO_FRAME, frames=30)

        assert len(audio.starts) == 1
        assert not stream.closed

    assert not capture._input_known_silent(EXTERNAL, devices)


@pytest.mark.asyncio
async def test_a_pinned_microphone_is_never_left(monkeypatch: pytest.MonkeyPatch) -> None:
    """A device chosen by number is the person's own decision."""
    devices = _laptop_with_headphones()
    audio = _granted_mac(monkeypatch, devices)

    async with capture.MicrophoneCapture(device=0):
        (stream,) = audio.starts
        await _pump(stream, _ZERO_FRAME, frames=30)

        assert len(audio.starts) == 1
        assert not stream.closed

    assert not capture._input_known_silent(EXTERNAL, devices)


@pytest.mark.asyncio
async def test_with_no_other_input_the_capture_stays_where_it_is(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    devices = [_device(EXTERNAL), _device("Speakers", inputs=0)]
    audio = _granted_mac(monkeypatch, devices)

    mic = capture.MicrophoneCapture(device="auto-headset")
    async with mic:
        (stream,) = audio.starts
        await _pump(stream, _ZERO_FRAME, frames=30)
        await _wait_for(lambda: mic._silence_switch_task is None)

        assert len(audio.starts) == 1
        assert not stream.closed
        assert mic._device == 0


@pytest.mark.asyncio
async def test_every_silent_input_is_passed_until_one_delivers_sound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two dead inputs in a row cost two short waits, not the dictation."""
    devices = [_device(EXTERNAL), _device("USB Headset"), _device(BUILT_IN)]
    audio = _granted_mac(monkeypatch, devices)

    mic = capture.MicrophoneCapture(device="auto-headset")
    async with mic:

        async def _zeros_until(count: int) -> None:
            while len(audio.starts) < count:
                await _pump(audio.starts[-1], _ZERO_FRAME, frames=1)

        await asyncio.wait_for(_zeros_until(2), timeout=3.0)
        await asyncio.wait_for(_zeros_until(3), timeout=3.0)

        assert [s.kwargs["device"] for s in audio.starts] == [0, 1, 2]
        await _pump(audio.starts[2], _LOUD_FRAME, frames=3)
        assert mic._device == 2
        assert len(audio.starts) == 3

    assert capture._input_known_silent(EXTERNAL, devices)
    assert capture._input_known_silent("USB Headset", devices)
    assert not capture._input_known_silent(BUILT_IN, devices)


def test_the_wait_before_leaving_outlasts_a_wireless_headsets_start() -> None:
    # A wireless headset delivers zeros for a moment while its link comes up.
    # The real value is part of the contract; the tests above shorten it.
    assert capture._SILENCE_SWITCH_AFTER_S == 1.0
