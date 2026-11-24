"""Characterization of the desktop realtime session phases.

These pin the behaviour of ``RealtimeSessionRunner`` (the body of
``VoicePipeline._active_realtime_session``) that the larger duplex tests do not
reach directly: cancellation, the provider event table, refusal bookkeeping and
how a call ends when no session can run. There is no second voice path: every
failure ends the call with ``HANGUP_ERROR`` and tells the person why.
"""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace
from typing import Any

import pytest

import dodaios.speech.pipeline as pipeline_mod
from dodaios.core.events import MessageSent
from dodaios.core.protocols import AudioChunk
from dodaios.sessions.constants import HANGUP_ERROR
from dodaios.speech import provider_refusal
from dodaios.speech.pipeline import SPOKEN_KIND_UNAVAILABLE
from dodaios.speech.realtime_session_runner import RealtimeSessionRunner
from tests.unit.speech.test_realtime_mode import (
    _FakeRealtimeSession,
    _HandshakeOnlyRealtimeSession,
    _pipe,
    _RecordingBus,
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


def _record_notices(pipe: Any) -> list[tuple[str, bool]]:
    """Replace the end-of-call notice with a recorder."""
    notices: list[tuple[str, bool]] = []

    async def _notify(text: str, *, spoken: bool) -> None:
        notices.append((text, spoken))

    pipe._notify_voice_unavailable = _notify  # type: ignore[method-assign]
    return notices


@pytest.mark.asyncio
async def test_failing_handshake_ends_the_call_with_error_and_a_visible_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipe = _pipe()
    notices = _record_notices(pipe)
    built: dict[str, _FakeRealtimeSession] = {}

    class _Broken(_FakeRealtimeSession):
        async def handle_control(self, message: Any) -> None:
            raise RuntimeError("handshake exploded")

    def _build(**kwargs: Any) -> _Broken:
        session = _Broken(kwargs["send_binary"], kwargs["send_json"])
        built["session"] = session
        return session

    monkeypatch.setattr("dodaios.realtime.factory.build_realtime_session", _build)
    monkeypatch.setattr(provider_refusal, "fresh_refusal", lambda _name: None)

    reason = await asyncio.wait_for(
        pipe._active_realtime_session(input_buffer=_buffer()), timeout=2.0
    )

    assert reason == HANGUP_ERROR
    assert built["session"].end_reason == HANGUP_ERROR
    # A capture buffer means a live microphone: the notice is shown, not spoken.
    assert notices == [("", False)]


@pytest.mark.asyncio
async def test_unbuildable_session_without_capture_ends_with_a_spoken_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipe = _pipe()
    notices = _record_notices(pipe)
    monkeypatch.setattr(
        "dodaios.realtime.factory.build_realtime_session", lambda **_kw: None
    )
    monkeypatch.setattr(provider_refusal, "fresh_refusal", lambda _name: None)
    monkeypatch.setattr(pipeline_mod, "MicrophoneCapture", lambda **_kw: _SilentMic())

    reason = await asyncio.wait_for(pipe._active_realtime_session(), timeout=2.0)

    assert reason == HANGUP_ERROR
    assert notices == [("", True)]


@pytest.mark.asyncio
async def test_unbuildable_session_with_capture_ends_with_a_visible_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipe = _pipe()
    notices = _record_notices(pipe)
    monkeypatch.setattr(
        "dodaios.realtime.factory.build_realtime_session", lambda **_kw: None
    )
    monkeypatch.setattr(provider_refusal, "fresh_refusal", lambda _name: None)

    reason = await asyncio.wait_for(
        pipe._active_realtime_session(input_buffer=_buffer()), timeout=2.0
    )

    assert reason == HANGUP_ERROR
    assert notices == [("", False)]


@pytest.mark.asyncio
async def test_missing_realtime_stack_ends_the_call_with_a_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipe = _pipe()
    notices = _record_notices(pipe)
    # ``None`` in sys.modules makes the lazy import raise ImportError.
    monkeypatch.setitem(sys.modules, "dodaios.realtime.desktop", None)

    reason = await asyncio.wait_for(pipe._active_realtime_session(), timeout=2.0)

    assert reason == HANGUP_ERROR
    assert notices == [("", True)]


@pytest.mark.asyncio
async def test_a_refused_primary_is_announced_as_ending_the_call_and_is_the_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipe = _pipe()
    pipe._config.brain.realtime = SimpleNamespace(provider="acme")
    notices = _record_notices(pipe)
    refusal = provider_refusal.describe("401 unauthorized: invalid api key")
    assert refusal is not None
    announced: list[dict[str, Any]] = []

    async def _announce(_bus: Any, **kwargs: Any) -> str:
        announced.append(kwargs)
        return "Acme refused the key."

    monkeypatch.setattr(
        "dodaios.realtime.factory.build_realtime_session", lambda **_kw: None
    )
    monkeypatch.setattr(
        provider_refusal, "fresh_refusal", lambda name: refusal if name == "acme" else None
    )
    monkeypatch.setattr(provider_refusal, "announce", _announce)
    monkeypatch.setattr(pipeline_mod, "MicrophoneCapture", lambda **_kw: _SilentMic())

    reason = await asyncio.wait_for(pipe._active_realtime_session(), timeout=2.0)

    assert reason == HANGUP_ERROR
    assert len(announced) == 1
    assert announced[0]["continued_on"] == provider_refusal.CONTINUED_NONE
    assert announced[0]["provider"] == "acme"
    assert announced[0]["refusal"] is refusal
    assert notices == [("Acme refused the key.", True)]


@pytest.mark.asyncio
async def test_a_provider_failure_after_start_ends_the_call_with_error_never_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipe = _pipe()
    notices = _record_notices(pipe)
    built: dict[str, _HandshakeOnlyRealtimeSession] = {}

    class _DiesAfterStart(_HandshakeOnlyRealtimeSession):
        async def wait_finished(self) -> None:
            raise RuntimeError("provider socket closed")

    def _build(**kwargs: Any) -> _DiesAfterStart:
        session = _DiesAfterStart(kwargs["send_binary"], kwargs["send_json"])
        built["session"] = session
        return session

    monkeypatch.setattr("dodaios.realtime.factory.build_realtime_session", _build)
    monkeypatch.setattr(provider_refusal, "fresh_refusal", lambda _name: None)
    monkeypatch.setattr(pipeline_mod, "MicrophoneCapture", lambda **_kw: _SilentMic())

    reason = await asyncio.wait_for(pipe._active_realtime_session(), timeout=2.0)

    assert reason == HANGUP_ERROR
    assert built["session"].end_reason == HANGUP_ERROR
    assert notices == [("", True)]


@pytest.mark.asyncio
async def test_spoken_notice_uses_the_unavailable_voice_line() -> None:
    pipe = _pipe()
    spoken: list[tuple[str, str | None, str]] = []

    async def _speak(text: str, language: str | None = None, *, kind: str = "reply") -> bool:
        spoken.append((text, language, kind))
        return False

    pipe._speak = _speak  # type: ignore[method-assign]
    pipe._brain = SimpleNamespace(conversation_language="")

    await pipe._notify_voice_unavailable("", spoken=True)
    await pipe._notify_voice_unavailable("Acme refused the key.", spoken=True)

    assert spoken == [
        (pipeline_mod._REALTIME_UNAVAILABLE_PHRASE["en"], "en", SPOKEN_KIND_UNAVAILABLE),
        ("Acme refused the key.", "en", SPOKEN_KIND_UNAVAILABLE),
    ]


@pytest.mark.asyncio
async def test_visible_notice_is_a_system_message_and_never_speaks() -> None:
    pipe = _pipe()
    bus = _RecordingBus()

    async def _publish(event: object) -> None:
        await bus.publish(event)

    async def _must_not_speak(*_args: Any, **_kwargs: Any) -> bool:
        pytest.fail("a capture-first call must not speak into its live microphone")

    pipe._publish_event = _publish  # type: ignore[method-assign]
    pipe._speak = _must_not_speak  # type: ignore[method-assign]
    pipe._brain = SimpleNamespace(conversation_language="")

    await pipe._notify_voice_unavailable("", spoken=False)
    await pipe._notify_voice_unavailable("Acme refused the key.", spoken=False)

    messages = [event for event in bus.events if isinstance(event, MessageSent)]
    assert [message.role for message in messages] == ["system", "system"]
    assert [message.text for message in messages] == [
        pipeline_mod._REALTIME_UNAVAILABLE_PHRASE["en"],
        "Acme refused the key.",
    ]


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
    assert runner.speaking is False
    assert runner.last_refusal is None


@pytest.mark.asyncio
async def test_assistant_transcripts_are_collected_for_the_echo_guard() -> None:
    runner = _runner()
    await runner._send_json(  # noqa: SLF001
        {"type": "transcript", "role": "user", "is_final": False, "text": "he"}
    )
    assert runner.assistant_transcript_parts == []
    await runner._send_json(  # noqa: SLF001
        {"type": "transcript", "role": "assistant", "text": "Hello"}
    )
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
    assert runner.assistant_transcript_parts == []
