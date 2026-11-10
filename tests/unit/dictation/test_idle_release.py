"""An unused local dictation engine gives its memory back and starts again on the next press.

Measured 2026-11-10: the two engine workers held 3.4 GB of committed memory
through a night without a single dictation. No subprocess and no model here;
the workers are fakes.
"""

from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

import dodaios.dictation.local_preview as preview_mod
from dodaios.dictation.idle_release import IdleRelease
from dodaios.dictation.local_final import LocalEngineUnavailable, LocalFinalSTT
from dodaios.dictation.local_preview import (
    LocalPreviewTranscriber,
    dictation_starting,
    reset_local_preview_for_tests,
)


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class _FakeWorker:
    device = "cuda"
    compute = "int8_float16"

    def __init__(self) -> None:
        self.calls = 0
        self.closed = False

    def transcribe(self, samples: Any, language: str | None = None, **_: Any) -> Any:
        self.calls += 1
        info = SimpleNamespace(language="de", language_probability=0.9)
        return [SimpleNamespace(start=0.0, end=1.0, text=" Hallo")], info

    def close(self) -> None:
        self.closed = True


def _pcm(seconds: float = 1.0) -> bytes:
    return (np.zeros(int(16_000 * seconds), dtype="<i2") + 1000).tobytes()


@pytest.fixture
def spawned(monkeypatch: pytest.MonkeyPatch) -> list[_FakeWorker]:
    """faster-whisper present, room on the card, a fake worker per spawn."""
    import dodaios.hardware.detection as detection

    workers: list[_FakeWorker] = []

    def _spawn(model_name: str, *, compute: str | None = None) -> _FakeWorker:
        workers.append(_FakeWorker())
        return workers[-1]

    monkeypatch.setattr(preview_mod, "faster_whisper_available", lambda: True)
    monkeypatch.setattr(preview_mod, "_spawn_worker_model", _spawn)
    monkeypatch.setattr(detection, "free_accelerator_gb", lambda: (6.0, "nvml"))
    reset_local_preview_for_tests()
    yield workers
    reset_local_preview_for_tests()


def _make_idle(stt_or_engine: Any) -> None:
    """Pretend the engine was last used long ago."""
    stt_or_engine._idle._last_used -= 100_000.0


# ---------------------------------------------------------------- the clock


def test_nothing_is_released_before_the_idle_time_is_over() -> None:
    clock = _Clock()
    released: list[int] = []
    watch = IdleRelease(600.0, lambda: released.append(1) or True, name="t", clock=clock)
    watch.touch()

    clock.now += 599.0
    assert watch.check() == pytest.approx(1.0)
    assert released == []

    clock.now += 2.0
    assert watch.check() is None
    assert released == [1]


def test_use_moves_the_deadline() -> None:
    clock = _Clock()
    released: list[int] = []
    watch = IdleRelease(600.0, lambda: released.append(1) or True, name="t", clock=clock)
    clock.now += 500.0
    watch.touch()
    clock.now += 500.0
    assert watch.check() == pytest.approx(100.0)
    assert released == []


def test_a_busy_engine_is_asked_again_and_zero_switches_the_watch_off() -> None:
    clock = _Clock()
    watch = IdleRelease(60.0, lambda: False, name="t", clock=clock)
    clock.now += 61.0
    retry = watch.check()
    assert retry is not None and 0 < retry < 60.0

    off = IdleRelease(0.0, lambda: pytest.fail("must never release"), name="t", clock=clock)
    clock.now += 1e6
    assert off.check() is None
    off.arm()
    assert not off.watching


def test_the_watch_thread_releases_and_ends() -> None:
    done = threading.Event()
    watch = IdleRelease(0.05, lambda: done.set() or True, name="idle-test")
    watch.arm()
    assert done.wait(5.0)
    deadline = time.monotonic() + 5.0
    while watch.watching and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not watch.watching


# ------------------------------------------------------------ the final pass


def test_an_idle_final_engine_is_released_and_the_next_dictation_starts_it_again(
    spawned: list[_FakeWorker],
) -> None:
    stt = LocalFinalSTT("large-v3-turbo")
    asyncio.run(stt.transcribe_pcm(_pcm()))
    first = spawned[0]
    assert stt.is_warm and not stt.is_resting

    _make_idle(stt)
    assert stt._idle.check() is None

    assert first.closed
    assert not stt.is_warm
    assert stt.is_resting  # in front, only not started
    assert stt.unavailable_reason == ""

    transcript = asyncio.run(stt.transcribe_pcm(_pcm()))
    assert transcript.text == "Hallo"
    assert len(spawned) == 2 and spawned[1].calls == 1
    assert stt.is_warm and not stt.is_resting


def test_a_final_engine_in_use_is_not_released(spawned: list[_FakeWorker]) -> None:
    stt = LocalFinalSTT("large-v3-turbo")
    stt.warm_up()
    _make_idle(stt)

    assert stt._call_lock.acquire(blocking=False)  # a decode is in flight
    try:
        assert stt._idle.check() is not None
    finally:
        stt._call_lock.release()
    assert stt.is_warm and not spawned[0].closed

    stt.warm_up()  # a key press: use, even without a decode
    assert stt._idle.due_in() > 0


def test_idle_minutes_zero_keeps_the_final_engine(spawned: list[_FakeWorker]) -> None:
    stt = LocalFinalSTT("large-v3-turbo", idle_release_s=0.0)
    stt.warm_up()
    _make_idle(stt)
    assert stt._idle.check() is None
    assert stt.is_warm and not spawned[0].closed


def test_a_press_waits_for_an_engine_that_is_starting_again(
    spawned: list[_FakeWorker], monkeypatch: pytest.MonkeyPatch
) -> None:
    """After an idle release the start is seconds long: wait, do not go to the cloud."""
    stt = LocalFinalSTT("large-v3-turbo")
    stt.warm_up()
    _make_idle(stt)
    assert stt._idle.check() is None and stt.is_resting

    spawning = threading.Event()
    real_spawn = preview_mod._spawn_worker_model

    def _slow_spawn(model_name: str, *, compute: str | None = None) -> Any:
        spawning.set()
        time.sleep(0.3)
        return real_spawn(model_name, compute=compute)

    monkeypatch.setattr(preview_mod, "_spawn_worker_model", _slow_spawn)
    warm = threading.Thread(target=stt.warm_up)  # the key went down
    warm.start()
    assert spawning.wait(5.0)

    transcript = asyncio.run(stt.transcribe_pcm(_pcm()))  # released before it is up

    warm.join(5.0)
    assert transcript.text == "Hallo"
    assert len(spawned) == 2  # one restart, not two


def test_a_first_start_is_still_not_waited_for(
    spawned: list[_FakeWorker], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A start after boot can take minutes; that press crosses as before."""
    stt = LocalFinalSTT("large-v3-turbo")
    assert stt._spawn_lock.acquire(blocking=False)  # a first start is in flight
    try:
        started = time.monotonic()
        with pytest.raises(LocalEngineUnavailable, match="still starting"):
            stt._ensure_worker(blocking=False)
        assert time.monotonic() - started < 1.0
    finally:
        stt._spawn_lock.release()


def test_an_abandoned_call_does_not_decode(spawned: list[_FakeWorker]) -> None:
    stt = LocalFinalSTT("large-v3-turbo")
    stt.warm_up()
    abandoned = threading.Event()
    abandoned.set()
    with pytest.raises(LocalEngineUnavailable, match="stopped waiting"):
        stt._transcribe_blocking(_pcm(), None, abandoned=abandoned)
    assert spawned[0].calls == 0 and not spawned[0].closed


# --------------------------------------------------------------- the preview


def test_an_idle_preview_engine_is_released_and_comes_back_on_the_next_dictation(
    spawned: list[_FakeWorker],
) -> None:
    engine = LocalPreviewTranscriber(prefer_worker=True)
    engine._loading = True
    engine._load_model()
    assert engine.ready and engine._idle.watching

    _make_idle(engine)
    assert engine._idle.check() is None
    assert spawned[0].closed and not engine.ready
    assert engine.available  # released, not broken

    engine.restart_if_released()  # no running loop: loads on a thread
    deadline = time.monotonic() + 5.0
    while not engine.ready and time.monotonic() < deadline:
        time.sleep(0.01)
    assert engine.ready and len(spawned) == 2


def test_a_preview_engine_that_is_decoding_is_not_released(spawned: list[_FakeWorker]) -> None:
    engine = LocalPreviewTranscriber(prefer_worker=True)
    engine._loading = True
    engine._load_model()
    _make_idle(engine)
    assert engine._busy.acquire(blocking=False)
    try:
        assert engine._idle.check() is not None
    finally:
        engine._busy.release()
    assert engine.ready and not spawned[0].closed


def test_a_starting_dictation_builds_no_first_preview_engine(spawned: list[_FakeWorker]) -> None:
    dictation_starting(120.0)
    assert preview_mod._INSTANCE is None and spawned == []

    engine = preview_mod.local_preview()
    assert engine is not None
    assert engine._idle.idle_s == 120.0  # the setting reached the engine built later
    dictation_starting(0.0)
    assert engine._idle.idle_s == 0.0
    assert spawned == []  # never ran, so nothing to restart
