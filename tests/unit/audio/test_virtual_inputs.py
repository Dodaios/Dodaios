"""The automatic microphone choice passes virtual inputs over, whatever their name.

A virtual microphone (a camera or meeting app's device, a loopback driver)
carries sound only while its app feeds it. The automatic choice knew such
inputs by a list of product names, and a list is always one product behind:
an unknown one with "Microphone" in its name ranked before a built-in
microphone whose name is localized ("MacBook Air-Mikrofon"), and an unknown one
that was the system default was taken first.

macOS knows the answer for every device (its transport type). Pinned here: the
device probe's own process reads it, the app keeps what the probe last said,
and the choice uses it next to the name list; on a system that does not tell,
and before the first probe answered, nothing changes.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from dodaios.audio import capture, device_probe, device_transport, topology
from dodaios.audio import devices as dv

BUILT_IN = "MacBook Air-Mikrofon"  # i18n-allow: a localized device name, as macOS lists it
UNKNOWN_VIRTUAL = "NoiseAway Microphone"


def _device(name: str, *, inputs: int = 1) -> dict:
    return {
        "name": name,
        "max_input_channels": inputs,
        "max_output_channels": 0 if inputs else 2,
        "hostapi": 0,
        "default_samplerate": 48_000,
    }


def _ranked(devices: list[dict], *, default: int) -> list[str]:
    capture.sd.default = SimpleNamespace(device=(default, 1))
    return [
        str(dev["name"])
        for _idx, dev in capture._rank_input_device_candidates(devices, [{"name": "Core Audio"}])
    ]


@pytest.fixture(autouse=True)
def _nothing_learned(monkeypatch: pytest.MonkeyPatch) -> None:
    dv._forget_virtual_devices()
    capture._forget_silent_inputs()
    monkeypatch.setattr(capture.sd, "default", SimpleNamespace(device=(0, 1)), raising=False)
    yield
    dv._forget_virtual_devices()
    capture._forget_silent_inputs()


# --------------------------------------------------------------------------
# What the operating system says
# --------------------------------------------------------------------------


def test_only_the_devices_the_system_calls_virtual_are_named() -> None:
    transports = {
        BUILT_IN: "bltn",
        "Camo Microphone": "virt",
        "AirPods Pro": "blue",
        "ZoomAudioDevice": "virt",
        "USB Audio Device": "usb ",
    }
    assert device_transport.virtual_device_names(transports) == [
        "Camo Microphone",
        "ZoomAudioDevice",
    ]


def test_a_code_reads_as_its_four_characters() -> None:
    assert device_transport.fourcc_text(0x76697274) == "virt"
    assert device_transport.fourcc_text(0x626C746E) == "bltn"


def test_a_system_that_does_not_tell_gives_no_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(device_transport.sys, "platform", "win32")
    assert device_transport.read_transports() == {}
    assert device_transport.virtual_device_names() == []


def test_a_read_that_fails_is_an_empty_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    def _broken() -> dict[str, str]:
        raise OSError("CoreAudio is not there")

    monkeypatch.setattr(device_transport.sys, "platform", "darwin")
    monkeypatch.setattr(device_transport, "_read_coreaudio", _broken)
    assert device_transport.read_transports() == {}


@pytest.mark.skipif(sys.platform != "darwin", reason="CoreAudio exists on macOS only")
def test_on_a_mac_the_real_read_answers_with_names_and_codes() -> None:
    """The real call, so a wrong signature fails here and not in the app."""
    transports = device_transport.read_transports()
    assert isinstance(transports, dict)
    for name, code in transports.items():
        assert isinstance(name, str) and name
        assert isinstance(code, str) and len(code) == 4


# --------------------------------------------------------------------------
# From the probe's process into the app
# --------------------------------------------------------------------------


def test_the_probe_snapshot_lists_the_virtual_devices(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_sd = SimpleNamespace(
        query_devices=lambda: [],
        query_hostapis=lambda: [],
        default=SimpleNamespace(device=(-1, -1)),
    )
    monkeypatch.setitem(sys.modules, "sounddevice", fake_sd)
    monkeypatch.setattr(device_probe, "_virtual_device_names", lambda: ["Camo Microphone"])

    assert device_probe.collect_snapshot()["virtual"] == ["Camo Microphone"]


def test_a_probe_without_the_reader_still_lists_the_devices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _broken() -> list[str]:
        raise RuntimeError("no reader")

    monkeypatch.setattr(device_transport, "virtual_device_names", _broken)
    assert device_probe._virtual_device_names() == []


def _answer_probe(monkeypatch: pytest.MonkeyPatch, payload: dict) -> None:
    def fake_run(command: list[str], **_kwargs: object) -> SimpleNamespace:
        Path(command[-1]).write_text(
            dv.SNAPSHOT_MARKER + json.dumps(payload) + "\n", encoding="utf-8"
        )
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(dv.subprocess, "run", fake_run)


def test_the_app_keeps_what_the_fresh_probe_said(monkeypatch: pytest.MonkeyPatch) -> None:
    assert dv.is_virtual_device("Camo Microphone") is False  # nothing learned yet
    _answer_probe(
        monkeypatch,
        {
            "ok": True,
            "devices": [_device(BUILT_IN), _device("Camo Microphone")],
            "hostapis": [{"name": "Core Audio", "devices": [0, 1]}],
            "default": [0, -1],
            "virtual": ["Camo  Microphone"],
        },
    )

    assert dv._query_tables_fresh() is not None

    assert dv.is_virtual_device("camo microphone") is True  # whatever case and spacing
    assert dv.is_virtual_device(BUILT_IN) is False


def test_a_probe_that_does_not_tell_changes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """An older worker, Windows, Linux: no list is not "no virtual devices"."""
    dv._remember_virtual_devices(["Camo Microphone"])
    _answer_probe(
        monkeypatch,
        {"ok": True, "devices": [], "hostapis": [], "default": [-1, -1]},
    )
    assert dv._query_tables_fresh() is not None
    assert dv.is_virtual_device("Camo Microphone") is True

    dv._remember_virtual_devices("Camo Microphone")  # malformed: not a list
    dv._remember_virtual_devices([1, 2])
    assert dv.is_virtual_device("Camo Microphone") is True


def test_a_device_that_went_real_again_is_forgotten() -> None:
    dv._remember_virtual_devices(["Camo Microphone"])
    dv._remember_virtual_devices([])
    assert dv.is_virtual_device("Camo Microphone") is False


# --------------------------------------------------------------------------
# The automatic choice
# --------------------------------------------------------------------------


def test_an_unknown_virtual_input_no_longer_ranks_before_a_localized_built_in() -> None:
    """ "Microphone" used to beat "Mikrofon" in the generic order."""
    devices = [_device(UNKNOWN_VIRTUAL), _device(BUILT_IN), _device("Speakers", inputs=0)]
    # The system default is an output-only slot: no default input to prefer.
    assert _ranked(devices, default=2) == [UNKNOWN_VIRTUAL, BUILT_IN]  # the old order

    dv._remember_virtual_devices([UNKNOWN_VIRTUAL])

    assert _ranked(devices, default=2) == [BUILT_IN, UNKNOWN_VIRTUAL]


def test_an_unknown_virtual_input_is_not_taken_because_it_is_the_system_default() -> None:
    devices = [_device(UNKNOWN_VIRTUAL), _device(BUILT_IN)]
    assert _ranked(devices, default=0)[0] == UNKNOWN_VIRTUAL  # before anything is known

    dv._remember_virtual_devices([UNKNOWN_VIRTUAL])

    assert _ranked(devices, default=0) == [BUILT_IN, UNKNOWN_VIRTUAL]
    assert capture._os_default_input_name(devices, [{"name": "Core Audio"}]) is None


def test_the_name_list_still_works_where_the_system_does_not_tell() -> None:
    devices = [_device("Camo Microphone"), _device("Microsoft Teams Audio"), _device(BUILT_IN)]
    assert _ranked(devices, default=0) == [BUILT_IN, "Camo Microphone", "Microsoft Teams Audio"]


def test_a_virtual_input_stays_the_last_resort_not_a_forbidden_one() -> None:
    """With nothing else to open it is still better than no microphone at all."""
    dv._remember_virtual_devices([UNKNOWN_VIRTUAL])
    assert _ranked([_device(UNKNOWN_VIRTUAL)], default=0) == [UNKNOWN_VIRTUAL]


def test_a_real_headset_keeps_its_place_before_the_built_in() -> None:
    dv._remember_virtual_devices([UNKNOWN_VIRTUAL])
    devices = [_device("AirPods Pro"), _device(UNKNOWN_VIRTUAL), _device(BUILT_IN)]
    assert _ranked(devices, default=0) == ["AirPods Pro", BUILT_IN, UNKNOWN_VIRTUAL]


# --------------------------------------------------------------------------
# Learned once at the start
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_real_watcher_asks_once_at_its_start(monkeypatch: pytest.MonkeyPatch) -> None:
    """Not one poll interval later: the first choices after a start need it."""
    asked: list[str] = []

    def _probe() -> str:
        asked.append("probe")
        return "sig"

    monkeypatch.setattr(topology, "_fresh_signature", _probe)
    task = asyncio.create_task(
        topology.watch_topology(player=None, poll_s=60.0, refresh=lambda: True)
    )
    try:
        for _ in range(100):
            if asked:
                break
            await asyncio.sleep(0.01)
        assert len(asked) == 1
        await asyncio.sleep(0.05)
        assert len(asked) == 1, "the watcher polled again before its interval"
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
