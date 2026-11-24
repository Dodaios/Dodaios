"""A cold local STT engine is warmed off the critical path, never inside a request.

Live failure (2026-11-08, RTX 4060, large-v3-turbo): the utterance engine was
never warmed, so its first build landed inside the first request that needed it
(~25 s). The warm-up now starts after readiness, is shared between callers,
reaches the engine through every wrapper and is cancelled on shutdown.
"""
from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest

from dodaios.core.protocols import Transcript
from dodaios.speech.pipeline import SpeechPipeline
from dodaios.speech.stt_dictionary import DictionaryCorrectingSTT
from dodaios.speech.stt_fallback import FallbackSTT
from dodaios.speech.usage_meter import MeteredSTT

_OK = Transcript(text="hello nova", language="en", confidence=0.9, is_partial=False)


class _LocalEngine:
    """Shape of ``FasterWhisperProvider``: warm-up in a thread, one decode."""

    supports_concurrent_transcription = False

    def __init__(
        self, *, warm: bool = True, decode_s: float = 0.0, error: Exception | None = None
    ) -> None:
        self.is_warm = warm
        self.decode_s = decode_s
        self.error = error
        self.load_gate = threading.Event()
        self.warm_calls = 0
        self.decode_calls = 0
        self.recover_calls = 0

    def warm_up(self) -> None:
        self.warm_calls += 1
        self.load_gate.wait(timeout=10)
        self.is_warm = True

    def recover(self) -> None:
        self.recover_calls += 1
        self.decode_s = 0.0

    async def transcribe_pcm(self, _pcm: bytes) -> Transcript:
        self.decode_calls += 1
        if self.error is not None:
            raise self.error
        await asyncio.sleep(self.decode_s)
        return _OK


def _make_pipe(stt: object, *, timeout_s: float = 0.05) -> SpeechPipeline:
    pipe = SpeechPipeline.__new__(SpeechPipeline)
    pipe._utterance_stt = stt
    pipe._stt_final_timeout_s = timeout_s
    pipe._hangup_event = asyncio.Event()
    return pipe


async def _release_load(engine: _LocalEngine, pipe: SpeechPipeline) -> None:
    engine.load_gate.set()
    await asyncio.wait_for(pipe._voice_stt_warmup_task, timeout=5)


@pytest.mark.asyncio
async def test_warm_up_is_skipped_for_providers_without_a_cold_engine() -> None:
    cloud = SimpleNamespace(transcribe_pcm=None)
    assert _make_pipe(cloud)._ensure_voice_stt_warmup() is None
    assert _make_pipe(_LocalEngine(warm=True))._ensure_voice_stt_warmup() is None


@pytest.mark.asyncio
async def test_real_wrapper_stack_exposes_the_cold_engine() -> None:
    """The live provider sits behind these; the probes must reach through them."""
    engine = _LocalEngine(warm=False)
    wrapped = MeteredSTT(
        DictionaryCorrectingSTT(FallbackSTT(engine, [], lambda _name: None, primary_name="x")),
        sink=None,
    )
    pipe = _make_pipe(wrapped)

    task = pipe._ensure_voice_stt_warmup()
    assert task is not None
    engine.load_gate.set()
    await asyncio.wait_for(task, timeout=5)
    assert engine.warm_calls == 1
    assert wrapped.supports_concurrent_transcription is False
    wrapped.recover()
    assert engine.recover_calls == 1


@pytest.mark.asyncio
async def test_boot_warms_the_utterance_engine_after_readiness() -> None:
    engine = _LocalEngine(warm=False)
    pipe = _make_pipe(engine)
    pipe._stt = None
    pipe._tts = SimpleNamespace(_ensure_client=lambda: None)
    pipe._audio_topology_task = object()
    pipe._schedule_dictation_warmup = lambda: None  # type: ignore[method-assign]
    pipe._log_warmup_ready_cue_done = lambda _t: None  # type: ignore[method-assign]
    ready: list[bool] = []

    async def _emit_boot_status(*, ready: bool, detail: str) -> None:
        readiness.append(ready)

    async def _play_ready_cue() -> None:
        return None

    readiness = ready
    pipe._emit_boot_status = _emit_boot_status  # type: ignore[method-assign]
    pipe._play_ready_cue = _play_ready_cue  # type: ignore[method-assign]

    await asyncio.wait_for(pipe._warmup_deferred_loaders(), timeout=5)

    assert readiness == [True], "the load must never gate readiness (AP-26)"
    assert pipe._voice_stt_warmup_task is not None
    await _release_load(engine, pipe)
    assert engine.is_warm is True


@pytest.mark.asyncio
async def test_warm_up_is_shared_and_cancelled_on_shutdown() -> None:
    engine = _LocalEngine(warm=False)
    pipe = _make_pipe(engine)

    first = pipe._ensure_voice_stt_warmup()
    assert first is not None and pipe._ensure_voice_stt_warmup() is first

    await pipe._cancel_warmup_background()
    assert first.cancelled()
    assert engine.is_warm is False
    assert pipe._ensure_voice_stt_warmup() is None, "no new load after shutdown"
    engine.load_gate.set()  # let the orphaned worker thread finish
