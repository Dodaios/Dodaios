"""A phone call through the real ``NativeLiveVoiceSession`` on a fake native provider.

The session classes are shared by every voice surface; ``surface="phone"``
keeps a call apart from the desk: no shared voice slot, no desk conversation
as history, the call's brief in the instructions, and the provider's PCM on
the phone line as mu-law.
"""

from __future__ import annotations

import asyncio
import base64
import math
import struct
from types import SimpleNamespace
from typing import Any

import pytest

from dodaios.core.protocols import AudioChunk
from dodaios.live import native, runtime
from dodaios.live.native import NativeLiveVoiceSession
from dodaios.realtime.protocol import PHONE_SURFACE, RealtimeEvent
from dodaios.telephony import call as call_mod
from dodaios.telephony.audio import TWILIO_SAMPLE_RATE, pcm16_to_ulaw
from dodaios.telephony.call import PhoneCall
from tests.fakes.fake_native_voice import FakeToolGateway, gemini_like_provider


def _tone(rate: int, ms: int, *, amp: int = 8000) -> bytes:
    n = rate * ms // 1000
    return b"".join(
        struct.pack("<h", int(amp * math.sin(2 * math.pi * 440 * i / rate))) for i in range(n)
    )


class _Brain:
    """Holds a desk conversation the phone call must never take."""

    def __init__(self) -> None:
        self.seed_taken = 0

    def take_voice_history_seed(self) -> tuple[Any, ...]:
        self.seed_taken += 1
        return (SimpleNamespace(role="user", content="desk secret"),)


@pytest.fixture
def phone(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime, "_active", {})
    monkeypatch.setattr(runtime, "_opening", set())
    monkeypatch.setattr(native, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(native, "get_supervisor_tool_gateway", lambda: FakeToolGateway())
    monkeypatch.setattr(call_mod, "_LINE_RETRY_S", 0.001)
    provider = gemini_like_provider()
    brain = _Brain()
    sent: list[dict[str, Any]] = []
    built: list[NativeLiveVoiceSession] = []

    async def send(msg: dict[str, Any]) -> None:
        sent.append(msg)

    async def hang_up() -> None:
        return None

    def build(*, send_binary: Any, send_json: Any, call_brief: str) -> NativeLiveVoiceSession:
        session = NativeLiveVoiceSession(
            session_id="phone-CA9",
            send_binary=send_binary,
            send_json=send_json,
            providers=[provider],
            config=SimpleNamespace(
                brain=SimpleNamespace(reply_language="auto", providers={}, realtime=None),
                voice=SimpleNamespace(realtime_tool_declaration_budget_tokens=0),
            ),
            brain=brain,
            surface=PHONE_SURFACE,
            call_brief=call_brief,
        )
        built.append(session)
        return session

    call = PhoneCall(
        call_sid="CA9",
        stream_sid="MZ9",
        send=send,
        hang_up=hang_up,
        build_session=build,
        direction="outbound",
        opening="Hi Laura, are we still on for Friday?",
        language_code="en-US",
        max_call_seconds=0,
    )
    return SimpleNamespace(
        call=call, provider=provider, brain=brain, sent=sent, built=built
    )


async def _settle(call: PhoneCall) -> None:
    for _ in range(50):
        await asyncio.sleep(0)
        pending = [t for t in call._tasks if not t.done()]
        if not pending:
            return
        await asyncio.gather(*pending, return_exceptions=True)


async def test_phone_session_stays_apart_from_the_desk(phone):
    assert await phone.call.start() is True
    await _settle(phone.call)
    try:
        session = phone.built[0]
        # The call holds no desktop voice slot and took no desk conversation.
        assert runtime.active() == ()
        assert not runtime.owns_microphone()
        assert phone.brain.seed_taken == 0
        config = phone.provider.opened_with[0]
        assert config.history == ()
        assert config.instructions.rstrip().endswith(phone.call.call_brief())
        assert "Hi Laura, are we still on for Friday?" in config.instructions
        assert session.surface == PHONE_SURFACE
    finally:
        await phone.call.end(reason="test")


async def test_opening_is_spoken_through_the_model(phone):
    await phone.call.start()
    await _settle(phone.call)
    try:
        connection = phone.provider.connection
        texts = [arg for name, arg in connection.calls if name == "send_text"]
        assert len(texts) == 1
        assert "Hi Laura, are we still on for Friday?" in texts[0]
        assert texts[0].startswith("[Application event, not the user speaking]")
    finally:
        await phone.call.end(reason="test")


async def test_caller_audio_reaches_the_provider_at_its_own_rate(phone):
    await phone.call.start()
    await _settle(phone.call)
    try:
        payload = base64.b64encode(pcm16_to_ulaw(_tone(TWILIO_SAMPLE_RATE, 20))).decode()
        await phone.call.handle_media(payload)
        audio = [arg for name, arg in phone.provider.connection.calls if name == "send_audio"]
        assert len(audio) == 1
        assert audio[0].sample_rate == 16_000
        # 20 ms at 16 kHz, 16-bit (the streaming resampler may hold one sample back).
        assert abs(len(audio[0].pcm) - 640) <= 4
    finally:
        await phone.call.end(reason="test")


async def test_provider_speech_reaches_the_caller_as_mulaw(phone):
    await phone.call.start()
    await _settle(phone.call)
    try:
        session = phone.built[0]
        await session._native_event(
            RealtimeEvent(
                type="audio_delta",
                audio=AudioChunk(pcm=_tone(24_000, 100), sample_rate=24_000, timestamp_ns=0),
            )
        )
        media = [m for m in phone.sent if m.get("event") == "media"]
        assert len(media) == 1
        assert abs(len(base64.b64decode(media[0]["media"]["payload"])) - 800) <= 4
    finally:
        await phone.call.end(reason="test")


async def test_hanging_up_closes_the_provider_connection(phone):
    await phone.call.start()
    await _settle(phone.call)
    await phone.call.end(reason="twilio_stop")
    assert phone.provider.connection.closed
    assert phone.built[0].hangup_reason == "client_stop"
