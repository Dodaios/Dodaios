"""A finished dictation must reach the next provider when the one in front hangs.

Live bug 2026-10-20 17:35 (``data/jarvis_desktop.log``): the on-device final
pass hung on 1.9 s of audio. The dictation lane bounded the WHOLE provider chain
with one provider's worth of time (8 s), so the ceiling ran out while the chain
was still waiting on the local worker; the keyed cloud provider behind it never
got the audio, the ladder called our own timeout "not a failure a second attempt
survives", and the dictation ended with 0 characters. Three seconds later the
next press crossed to the cloud and was transcribed in 0.5 s.

These tests lock the three halves of the fix:

* the chain bounds every provider that has another one behind it and crosses
  when that deadline passes (``ProviderDeadlineExceeded``, crossable and
  retryable — never the lane's own ``TimeoutError``);
* the lane widens its own ceiling by the chain's crossing reserve, so the
  crossing does not eat the next provider's time;
* when every provider fails, the notice says the audio was kept for Restore.
"""

from __future__ import annotations

import asyncio
import contextlib
from types import SimpleNamespace
from typing import Any

import pytest

import dodaios.speech.pipeline as pipeline_module
import dodaios.speech.stt_fallback as fallback_module
from dodaios.core.config import DictationConfig
from dodaios.core.events import DictationCompleted
from dodaios.speech.pipeline import (
    SpeechPipeline,
    _dictation_retry_worthwhile,
    _stt_crossing_reserve_s,
)
from dodaios.speech.stt_failure import classify_stt_failure, is_crossable_failure
from dodaios.speech.stt_fallback import (
    FallbackSTT,
    ProviderDeadlineExceeded,
    audio_seconds,
    provider_deadline_s,
)
from tests.fakes.fake_stt_providers import (
    AnsweringSTT,
    FailingSTT,
    RecordingBuilder,
    SlowSTT,
    WedgedSTT,
)

BYTES_PER_SECOND = 16_000 * 2


def _chain(primary: Any, floor_s: float | None, **alternates: Any) -> FallbackSTT:
    return FallbackSTT(
        primary,
        list(alternates),
        RecordingBuilder(alternates),
        primary_name="faster-whisper",
        provider_deadline_floor_s=floor_s,
    )


# --------------------------------------------------------------------------
# The chain's own deadline
# --------------------------------------------------------------------------


async def test_a_wedged_provider_in_front_crosses_to_the_next_one() -> None:
    local = WedgedSTT()
    cloud = AnsweringSTT("the words")
    chain = _chain(local, 0.05, **{"groq-api": cloud})

    result = await asyncio.wait_for(
        chain.transcribe_pcm(b"\x00" * BYTES_PER_SECOND, language="auto"), timeout=5
    )

    assert result.text == "the words"
    assert chain.last_used_provider == "groq-api"
    assert local.cancelled == 1, "the wedged call must be cancelled, not left running"
    assert cloud.calls == 1


async def test_the_wedged_provider_is_skipped_on_the_next_call() -> None:
    """After a wedge the chain must not make the next press wait it out again."""
    local = WedgedSTT()
    cloud = AnsweringSTT("again")
    chain = _chain(local, 0.05, **{"groq-api": cloud})

    await chain.transcribe_pcm(b"\x00" * 3200)
    await asyncio.wait_for(chain.transcribe_pcm(b"\x00" * 3200), timeout=0.04)

    assert local.calls == 1
    assert cloud.calls == 2


async def test_the_last_provider_is_never_cut_short_by_the_chain() -> None:
    """With nowhere to cross, a deadline would only lose the words."""
    only = SlowSTT("slow but right", delay_s=0.1)
    chain = _chain(only, 0.01)

    result = await chain.transcribe_pcm(b"\x00" * 3200)

    assert result.text == "slow but right"


async def test_a_chain_without_deadlines_keeps_the_old_behaviour() -> None:
    slow = SlowSTT("primary", delay_s=0.1)
    cloud = AnsweringSTT("fallback")
    chain = _chain(slow, None, **{"groq-api": cloud})

    result = await chain.transcribe_pcm(b"\x00" * 3200)

    assert result.text == "primary"
    assert cloud.calls == 0
    assert chain.crossing_reserve_s(10.0) == 0.0


async def test_a_slow_provider_inside_its_deadline_still_answers() -> None:
    """The deadline matches the lane's old ceiling: a call that used to succeed
    on the provider in front must not now be sent to a paid fallback."""
    slow = SlowSTT("local", delay_s=0.05)
    cloud = AnsweringSTT("cloud")
    chain = _chain(slow, 1.0, **{"groq-api": cloud})

    result = await chain.transcribe_pcm(b"\x00" * 3200)

    assert result.text == "local"
    assert cloud.calls == 0


async def test_the_deadline_scales_with_the_audio(monkeypatch: pytest.MonkeyPatch) -> None:
    assert provider_deadline_s(1.9, 8.0) == 8.0
    assert provider_deadline_s(25.0, 8.0) == pytest.approx(50.0)
    assert audio_seconds(b"\x00" * BYTES_PER_SECOND) == pytest.approx(1.0)
    assert audio_seconds(b"\x00" * 16_000, 8_000) == pytest.approx(1.0)
    assert audio_seconds("not audio") == 0.0

    chain = _chain(AnsweringSTT("x"), 8.0, **{"groq-api": AnsweringSTT("y")})
    assert chain.crossing_reserve_s(1.9) == pytest.approx(8.0)
    assert chain.crossing_reserve_s(25.0) == pytest.approx(50.0)
    two = _chain(
        AnsweringSTT("x"),
        8.0,
        **{"groq-api": AnsweringSTT("y"), "openai-api": AnsweringSTT("z")},
    )
    assert two.crossing_reserve_s(1.9) == pytest.approx(16.0)


async def test_every_provider_failing_surfaces_the_first_failure() -> None:
    local = WedgedSTT()
    cloud = FailingSTT(RuntimeError("HTTP 503 Service Unavailable"))
    chain = _chain(local, 0.05, **{"groq-api": cloud})

    with pytest.raises(ProviderDeadlineExceeded):
        await chain.transcribe_pcm(b"\x00" * 3200)
    assert cloud.calls == 1


def test_the_chain_deadline_is_crossable_and_worth_a_retry() -> None:
    """The crossing must never read as "not a failure a second attempt survives"."""
    exc = ProviderDeadlineExceeded("faster-whisper did not answer within 8s")

    assert classify_stt_failure(exc) == "unavailable"
    assert is_crossable_failure(classify_stt_failure(exc))
    assert _dictation_retry_worthwhile(exc) is True
    # The lane's OWN ceiling stays a wedge of the last provider: not retried.
    assert _dictation_retry_worthwhile(TimeoutError()) is False


def test_the_reserve_is_read_through_transparent_wrappers() -> None:
    chain = _chain(AnsweringSTT("x"), 8.0, **{"groq-api": AnsweringSTT("y")})

    class _Wrapper:
        def __init__(self, inner: Any) -> None:
            self._inner = inner

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

    assert _stt_crossing_reserve_s(_Wrapper(chain), 1.9) == pytest.approx(8.0)
    assert _stt_crossing_reserve_s(AnsweringSTT("plain"), 1.9) == 0.0


# --------------------------------------------------------------------------
# The whole lane — the 2026-10-20 17:35 dictation, replayed
# --------------------------------------------------------------------------


class _Chunk:
    def __init__(self, pcm: bytes) -> None:
        self.pcm = pcm
        self.timestamp_ns = 0


class _FakeMic:
    def __init__(self, seconds: float) -> None:
        self._pcm = b"\x11\x22" * int(16_000 * seconds)

    async def stream(self):  # noqa: ANN201 — an async generator of chunks
        yield _Chunk(self._pcm)
        await asyncio.sleep(3600)


class _NullCapture:
    def __init__(self, source: Any) -> None:
        self._source = source

    async def __aenter__(self) -> Any:
        return self._source

    async def __aexit__(self, *exc: object) -> bool:
        return False


def _session_pipeline(stt: Any, *, seconds: float, history_enabled: bool = False):
    pipe = SpeechPipeline.__new__(SpeechPipeline)
    pipe._dictation_cfg = DictationConfig(
        history_enabled=history_enabled,
        segment_seconds=0.0,
        partial_interval_s=0.0,
        polish=False,
    )
    pipe._dictation_target = "chat"
    pipe._dictation_completion_published = False
    pipe._dictation_max_s = 30.0
    pipe._dictation_stt_instance = stt
    pipe._stt_final_timeout_s = 0.3
    pipe._hangup_event = asyncio.Event()
    pipe._dictation_stop_event = asyncio.Event()
    events: list[object] = []
    recorded: list[dict[str, Any]] = []

    async def _publish(event: object) -> None:
        events.append(event)

    def _publish_soon(event: object) -> None:
        events.append(event)

    async def _record(**kwargs: Any) -> None:
        # Stands in for the history store: the test must never write a real
        # history row or audio sidecar.
        recorded.append(kwargs)

    pipe._publish_event = _publish  # type: ignore[assignment]
    pipe._publish_event_soon = _publish_soon  # type: ignore[assignment]
    pipe._record_dictation = _record  # type: ignore[assignment]
    pipe._capture_dictation_input = lambda: _NullCapture(_FakeMic(seconds))  # type: ignore[assignment]
    pipe._insert_dictation = lambda text: SimpleNamespace(  # type: ignore[assignment]
        status="inserted", detail="", method="clipboard+ctrl_v"
    )

    async def _stop_live(task, **_kwargs):  # noqa: ANN001, ANN202
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task

    pipe._stop_ptt_live_transcription = _stop_live  # type: ignore[assignment]
    return pipe, events, recorded


async def _run_session(pipe: Any) -> None:
    task = asyncio.create_task(pipe._dictation_session())
    await asyncio.sleep(0)
    pipe._dictation_stop_event.set()
    await asyncio.wait_for(task, timeout=30)


def _completed(events: list[object]) -> DictationCompleted:
    return next(e for e in events if isinstance(e, DictationCompleted))


@pytest.fixture
def short_ceilings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Production's formulas with small multipliers, so a wedge costs ~0.3 s."""
    monkeypatch.setattr(pipeline_module, "_DICTATION_TRANSCRIBE_TIMEOUT_PER_AUDIO_S", 0.1)
    monkeypatch.setattr(fallback_module, "PROVIDER_DEADLINE_PER_AUDIO_S", 0.1)


@pytest.mark.usefixtures("short_ceilings")
async def test_a_hung_local_pass_no_longer_loses_the_dictation() -> None:
    """REGRESSION 2026-10-20 17:35: 0 characters although the cloud was keyed."""
    local = WedgedSTT()
    cloud = AnsweringSTT("Bitte die Bugs auf PyPI fixen")  # i18n-allow: German fixture
    # Same floor the lane arms its own chain with (``_stt_final_timeout_s``).
    chain = _chain(local, 0.3, **{"groq-api": cloud})
    pipe, events, _recorded = _session_pipeline(chain, seconds=1.0)

    await _run_session(pipe)

    completed = _completed(events)
    assert completed.text == "Bitte die Bugs auf PyPI fixen"  # i18n-allow: German fixture
    assert completed.outcome != "failed"
    assert local.cancelled == 1
    assert cloud.calls >= 1


@pytest.mark.usefixtures("short_ceilings")
async def test_every_provider_failing_says_the_audio_was_kept() -> None:
    local = WedgedSTT()
    cloud = FailingSTT(RuntimeError("HTTP 503 Service Unavailable"))
    chain = _chain(local, 0.3, **{"groq-api": cloud})
    pipe, events, recorded = _session_pipeline(chain, seconds=1.0, history_enabled=True)

    await _run_session(pipe)

    completed = _completed(events)
    assert completed.outcome == "failed"
    assert completed.error == "unavailable"
    assert "Restore" in completed.detail
    assert recorded, "a failed dictation must reach the history (Restore starts there)"
    assert recorded[-1]["outcome_name"] == "failed"
    assert recorded[-1]["audio"], "the captured audio must be handed over to be kept"


@pytest.mark.usefixtures("short_ceilings")
async def test_no_restore_promise_when_nothing_is_kept() -> None:
    cloud = FailingSTT(RuntimeError("HTTP 503 Service Unavailable"))
    chain = _chain(WedgedSTT(), 0.3, **{"groq-api": cloud})
    pipe, events, _recorded = _session_pipeline(chain, seconds=1.0, history_enabled=False)

    await _run_session(pipe)

    completed = _completed(events)
    assert completed.outcome == "failed"
    assert "Restore" not in completed.detail
