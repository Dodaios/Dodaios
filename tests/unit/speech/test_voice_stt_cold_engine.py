"""Voice turns on a local engine: cold load, timeouts, Cancel, repeated sessions.

Live failure (2026-11-08, RTX 4060, large-v3-turbo): the utterance engine was
never warmed, so its first build landed inside the first turn. All three 8 s
"attempts" queued behind one ~25 s load, the turn died, and a Cancel pressed
meanwhile sat latched until the ladder ran out.
"""
from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace

import pytest

from dodaios.core.bus import EventBus
from dodaios.core.protocols import Transcript
from dodaios.speech.pipeline import SpeechPipeline, TurnTakingState
from dodaios.speech.stt_dictionary import DictionaryCorrectingSTT
from dodaios.speech.stt_fallback import FallbackSTT
from dodaios.speech.usage_meter import MeteredSTT

_OK = Transcript(text="hello nova", language="en", confidence=0.9, is_partial=False)
_PCM = b"\x00\x00" * 256
_PROMPT_S = 1.0


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


def _make_turn_pipe(stt: object) -> tuple[SpeechPipeline, list[TurnTakingState], list[str]]:
    """A pipeline able to run ``_handle_utterance`` up to the brain boundary."""
    pipe = _make_pipe(stt)
    pipe._config = SimpleNamespace(latency=SimpleNamespace(enabled=False))
    pipe._bus = EventBus()
    pipe._latency_first_audio_marked = False
    pipe._latency_tracker = None
    pipe._last_endpoint_reason = None
    pipe._carry_pcm = bytearray()
    pipe._carry_started_monotonic = None
    states: list[TurnTakingState] = []
    apologies: list[str] = []

    async def _set_turn_state(state: TurnTakingState) -> None:
        states.append(state)

    async def _publish_event(_event: object) -> None:
        return None

    async def _speak_stt_unavailable() -> None:
        apologies.append("spoken")

    pipe._set_turn_state = _set_turn_state  # type: ignore[method-assign]
    pipe._publish_event = _publish_event  # type: ignore[method-assign]
    pipe._speak_stt_unavailable = _speak_stt_unavailable  # type: ignore[method-assign]
    return pipe, states, apologies


def _voice_tasks() -> list[asyncio.Task]:
    return [t for t in asyncio.all_tasks() if t.get_name().startswith("stt-final")]


async def _release_load(engine: _LocalEngine, pipe: SpeechPipeline) -> None:
    engine.load_gate.set()
    await asyncio.wait_for(pipe._voice_stt_warmup_task, timeout=5)


@pytest.mark.asyncio
async def test_cold_load_does_not_consume_the_inference_budget() -> None:
    engine = _LocalEngine(warm=False)
    pipe = _make_pipe(engine)  # 50 ms budget, far shorter than this load

    turn = asyncio.create_task(pipe._transcribe_final(_PCM))
    await asyncio.sleep(0.25)
    assert not turn.done(), "the turn must hold for the build, not time out on it"
    assert engine.decode_calls == 0, "no decode may be queued behind the build"

    engine.load_gate.set()
    assert await asyncio.wait_for(turn, timeout=5) is _OK
    assert engine.decode_calls == 1
    assert engine.warm_calls == 1
    assert engine.recover_calls == 0
    assert _voice_tasks() == []


@pytest.mark.asyncio
async def test_cancel_during_cold_load_is_prompt_and_keeps_the_load() -> None:
    engine = _LocalEngine(warm=False)
    pipe = _make_pipe(engine)

    turn = asyncio.create_task(pipe._transcribe_final(_PCM))
    await asyncio.sleep(0.05)
    started = time.monotonic()
    pipe._hangup_event.set()
    assert await asyncio.wait_for(turn, timeout=_PROMPT_S) is None
    assert time.monotonic() - started < _PROMPT_S
    assert _voice_tasks() == []

    # A later session joins the build already running instead of restarting it.
    pipe._hangup_event.clear()
    next_turn = asyncio.create_task(pipe._transcribe_final(_PCM))
    await asyncio.sleep(0.05)
    assert engine.warm_calls == 1
    await _release_load(engine, pipe)
    assert await asyncio.wait_for(next_turn, timeout=5) is _OK
    assert engine.warm_calls == 1


@pytest.mark.asyncio
async def test_cancel_during_decode_is_prompt() -> None:
    engine = _LocalEngine(decode_s=30.0)
    pipe = _make_pipe(engine, timeout_s=10.0)

    turn = asyncio.create_task(pipe._transcribe_final(_PCM))
    await asyncio.sleep(0.02)
    pipe._hangup_event.set()

    assert await asyncio.wait_for(turn, timeout=_PROMPT_S) is None
    assert engine.recover_calls == 0, "a Cancel is not evidence of a wedge"
    assert _voice_tasks() == []


@pytest.mark.asyncio
async def test_slow_local_decode_is_never_sent_twice() -> None:
    """The later windows wait on the running decode (the TranscribeBusy path)."""
    engine = _LocalEngine(decode_s=0.12)
    pipe = _make_pipe(engine, timeout_s=0.05)

    assert await pipe._transcribe_final(_PCM) is _OK
    assert engine.decode_calls == 1
    assert engine.recover_calls == 0


@pytest.mark.asyncio
async def test_wedged_decode_recovers_so_the_next_session_works() -> None:
    engine = _LocalEngine(decode_s=30.0)
    pipe = _make_pipe(engine, timeout_s=0.02)

    assert await asyncio.wait_for(pipe._transcribe_final(_PCM), timeout=5) is None
    assert engine.decode_calls == 1
    assert engine.recover_calls == 1
    assert _voice_tasks() == []

    assert await pipe._transcribe_final(_PCM) is _OK


@pytest.mark.asyncio
async def test_worker_failure_apologises_and_keeps_listening() -> None:
    pipe, states, apologies = _make_turn_pipe(_LocalEngine(error=RuntimeError("worker died")))

    assert await pipe._handle_utterance(_PCM) is True
    assert apologies == ["spoken"]
    assert states[-1] is TurnTakingState.LISTENING


@pytest.mark.asyncio
async def test_timeout_apologises_and_keeps_listening() -> None:
    pipe, states, apologies = _make_turn_pipe(_LocalEngine(decode_s=30.0))
    pipe._stt_final_timeout_s = 0.02

    assert await pipe._handle_utterance(_PCM) is True
    assert apologies == ["spoken"]
    assert states[-1] is TurnTakingState.LISTENING


@pytest.mark.asyncio
async def test_hangup_during_stt_ends_the_turn_without_an_apology() -> None:
    pipe, _states, apologies = _make_turn_pipe(_LocalEngine(decode_s=30.0))
    pipe._stt_final_timeout_s = 10.0

    turn = asyncio.create_task(pipe._handle_utterance(_PCM))
    await asyncio.sleep(0.02)
    pipe._hangup_event.set()

    assert await asyncio.wait_for(turn, timeout=_PROMPT_S) is True
    assert apologies == [], "nobody is left to hear it (the abort that leaked TTS tasks)"


@pytest.mark.asyncio
async def test_repeated_sessions_recover_from_every_failure_mode() -> None:
    engine = _LocalEngine()
    pipe, states, apologies = _make_turn_pipe(engine)
    pipe._stt_final_timeout_s = 0.02

    for _ in range(3):
        engine.decode_s = 30.0
        await pipe._handle_utterance(_PCM)  # wedge -> recover
        engine.error = RuntimeError("worker died")
        await pipe._handle_utterance(_PCM)  # hard failure
        engine.error = None

    assert len(apologies) == 6
    assert states[-1] is TurnTakingState.LISTENING
    assert _voice_tasks() == []
    assert await pipe._transcribe_final(_PCM) is _OK


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
    pipe._vad = SimpleNamespace(_ensure_model=lambda: None)
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
