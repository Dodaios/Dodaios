"""Characterization of the desktop realtime session phases.

These pin the behaviour of ``RealtimeSessionRunner`` (the body of
``VoicePipeline._active_realtime_session``) that the larger duplex tests do not
reach directly: cancellation, the provider event table, refusal bookkeeping and
the classic-fallback decisions.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

import dodaios.speech.pipeline as pipeline_mod
from dodaios.core.protocols import AudioChunk
from dodaios.sessions.constants import HANGUP_DESKTOP_FALLBACK
from dodaios.speech import provider_refusal
from dodaios.speech.realtime_session_runner import RealtimeSessionRunner
from tests.unit.speech.test_realtime_mode import (
    _FakeRealtimeSession,
    _HandshakeOnlyRealtimeSession,
    _pipe,
    _SilentMic,
)


def _buffer() -> pipeline_mod._SessionInputBuffer:
    return pipeline_mod._SessionInputBuffer(  # noqa: SLF001
        initial=(AudioChunk(pcm=b"command", sample_rate=16_000, timestamp_ns=1),)
    )


@pytest.mark.asyncio
async def test_app_cancel_ends_the_session_with_shutdown_and_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipe = _pipe()
    built: dict[str, _HandshakeOnlyRealtimeSession] = {}
    built_ready = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _build(**kwargs: Any) -> _HandshakeOnlyRealtimeSession:
        session = _HandshakeOnlyRealtimeSession(kwargs["send_binary"], kwargs["send_json"])
        built["session"] = session
        loop.call_soon_threadsafe(built_ready.set)
        return session

    monkeypatch.setattr("dodaios.realtime.factory.build_realtime_session", _build)
    monkeypatch.setattr(pipeline_mod, "MicrophoneCapture", lambda **_kw: _SilentMic())
    task = asyncio.create_task(pipe._active_realtime_session())
    await asyncio.wait_for(built_ready.wait(), timeout=1.0)
    await asyncio.wait_for(built["session"].ready.wait(), timeout=1.0)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=1.0)

    assert built["session"].end_reason == "shutdown"
    assert pipe._active_realtime_handle is None


@pytest.mark.asyncio
async def test_failing_handshake_before_any_turn_continues_on_the_classic_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipe = _pipe()
    built: dict[str, _FakeRealtimeSession] = {}

    class _Broken(_FakeRealtimeSession):
        async def handle_control(self, message: Any) -> None:
            raise RuntimeError("handshake exploded")

    def _build(**kwargs: Any) -> _Broken:
        session = _Broken(kwargs["send_binary"], kwargs["send_json"])
        built["session"] = session
        return session

    monkeypatch.setattr("dodaios.realtime.factory.build_realtime_session", _build)
    monkeypatch.setattr(
        "dodaios.realtime.factory.realtime_implicit_usage_fallback_allowed",
        lambda _cfg: True,
    )

    reason = await asyncio.wait_for(
        pipe._active_realtime_session(input_buffer=_buffer()), timeout=2.0
    )

    assert reason is None
    assert built["session"].end_reason == HANGUP_DESKTOP_FALLBACK


@pytest.mark.asyncio
async def test_unbuildable_session_with_fallback_allowed_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipe = _pipe()
    monkeypatch.setattr(
        "dodaios.realtime.factory.build_realtime_session", lambda **_kw: None
    )
    monkeypatch.setattr(
        "dodaios.realtime.factory.realtime_implicit_usage_fallback_allowed",
        lambda _cfg: True,
    )
    monkeypatch.setattr(provider_refusal, "fresh_refusal", lambda _name: None)

    reason = await asyncio.wait_for(
        pipe._active_realtime_session(input_buffer=_buffer()), timeout=2.0
    )

    assert reason is None


def _runner() -> RealtimeSessionRunner:
    runner = RealtimeSessionRunner(_pipe(), None)
    runner.session_id = "s-test"
    return runner


def test_event_table_names_every_provider_frame_kind() -> None:
    runner = _runner()
    assert set(runner._event_handlers) == {  # noqa: SLF001
        "audio_starting",
        "language",
        "audio_ready",
        "transcript",
        "thinking",
        "provider_fallback",
        "audio_failed",
        "tts_cancel",
        "hangup",
        "output_recover",
        "turn_complete",
        "error_spoken",
        "provider_error",
        "provider_warning",
    }


@pytest.mark.asyncio
async def test_unknown_and_diagnostic_frames_change_nothing() -> None:
    runner = _runner()
    for message in (
        {"type": "no_such_frame"},
        {"type": ""},
        {},
        {"type": "provider_error", "error": "boom"},
        {"type": "provider_warning", "error": "careful"},
    ):
        await runner._send_json(message)  # noqa: SLF001
    assert runner.semantic_turn_committed is False
    assert runner.speaking is False
    assert runner.last_refusal is None


@pytest.mark.asyncio
async def test_transcripts_commit_the_turn_and_collect_assistant_text() -> None:
    runner = _runner()
    await runner._send_json(  # noqa: SLF001
        {"type": "transcript", "role": "user", "is_final": False, "text": "he"}
    )
    assert runner.semantic_turn_committed is False
    await runner._send_json(  # noqa: SLF001
        {"type": "transcript", "role": "assistant", "text": "Hello"}
    )
    assert runner.semantic_turn_committed is True
    assert runner.assistant_transcript_parts == ["Hello"]


@pytest.mark.asyncio
async def test_a_refused_provider_is_remembered_and_announced_per_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _runner()
    announced: list[str] = []
    remembered: list[str] = []
    refusal = provider_refusal.describe("401 unauthorized: invalid api key")
    assert refusal is not None

    async def _announce(_bus: Any, **kwargs: Any) -> str:
        announced.append(kwargs["continued_on"])
        return "notice"

    monkeypatch.setattr(provider_refusal, "announce", _announce)
    monkeypatch.setattr(
        provider_refusal, "remember", lambda name, _r: remembered.append(name)
    )

    frame = {
        "type": "provider_fallback",
        "provider": "acme",
        "error": "401 unauthorized: invalid api key",
    }
    await runner._send_json(frame)  # noqa: SLF001
    await runner._send_json(frame)  # noqa: SLF001

    assert remembered == ["acme", "acme"]
    assert announced == [provider_refusal.CONTINUED_REALTIME] * 2
    assert runner.last_refused_provider == "acme"
    assert runner.pipe._last_realtime_start_error["provider"] == "acme"  # noqa: SLF001


@pytest.mark.asyncio
async def test_hangup_and_tts_cancel_frames_close_the_output_segment() -> None:
    runner = _runner()
    from dodaios.realtime.desktop import (
        DesktopRealtimeBargeInDetector,
        DesktopRealtimePlayback,
    )

    runner.playback = DesktopRealtimePlayback(runner.pipe._player)  # noqa: SLF001
    runner.barge_detector = DesktopRealtimeBargeInDetector(output_active=None)
    runner.speaking = True
    runner.assistant_transcript_parts.append("partial")
    await runner._send_json({"type": "hangup"})  # noqa: SLF001
    assert runner.speaking is False
    assert runner.semantic_turn_committed is True
    assert runner.assistant_transcript_parts == []
