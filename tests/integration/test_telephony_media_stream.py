"""Integration test: drive the media WebSocket with synthetic Twilio frames.

This is the in-repo proof of a simulated call. It connects to
``/api/telephony/media`` through Starlette's TestClient WS support, sends the
``connected`` / ``start`` / ``media`` / ``mark`` / ``stop`` JSON frames Twilio
would send, and asserts that the handler:

  * bridges the call to a realtime session (an injected fake session from
    ``tests/fakes/fake_phone_session.py``, built with the call's brief),
  * hands the caller's audio to the session and the session's audio back to
    Twilio as mu-law ``media`` frames,
  * ends the session when Twilio hangs up, hangs up when the session ends,
    and refuses the call when no realtime session can hold it,
  * records the finished call in the ring buffer.

No real socket, no provider, no API key. Signature/secret checks are disabled
with ``app.state.telephony_skip_signature``.
"""

from __future__ import annotations

import base64
import math
import struct
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from dodaios.telephony import call as call_mod
from dodaios.telephony.audio import TWILIO_SAMPLE_RATE, pcm16_to_ulaw
from dodaios.telephony.status import TelephonyManager
from dodaios.ui.web.telephony_routes import router as telephony_router
from tests.fakes.fake_phone_session import FakePhoneSession


def _tone(rate: int, ms: int, amp: int = 8000) -> bytes:
    n = rate * ms // 1000
    return b"".join(
        struct.pack("<h", int(amp * math.sin(2 * math.pi * 300 * i / rate))) for i in range(n)
    )


def _ulaw_frame_b64(ms: int = 20) -> str:
    return base64.b64encode(pcm16_to_ulaw(_tone(TWILIO_SAMPLE_RATE, ms))).decode("ascii")


def _start(call_sid: str = "CA123", **custom: str) -> dict[str, Any]:
    return {
        "event": "start",
        "streamSid": "MZ123",
        "start": {
            "streamSid": "MZ123",
            "callSid": call_sid,
            "customParameters": {"secret": "x", "call_sid": call_sid, **custom},
            "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000, "channels": 1},
        },
    }


class _Sessions:
    """Builds the fake realtime session; the test plays the provider's side."""

    def __init__(self) -> None:
        self.built: list[FakePhoneSession] = []
        self.refuse = False

    def __call__(self, *, send_binary: Any, send_json: Any, call_brief: str) -> Any:
        if self.refuse:
            return None
        session = _AnsweringSession(
            send_binary=send_binary, send_json=send_json, call_brief=call_brief
        )
        self.built.append(session)
        return session


class _AnsweringSession(FakePhoneSession):
    """Answers every caller frame with 20 ms of 24 kHz speech, as a model would."""

    async def handle_audio_frame(self, pcm: bytes) -> None:
        await super().handle_audio_frame(pcm)
        await self.answer(_tone(24_000, 20))


@pytest.fixture(autouse=True)
def _short_goodbye(monkeypatch):
    """The fake Twilio never echoes marks: keep the goodbye wait short."""
    monkeypatch.setattr(call_mod, "_REPLY_PLAYBACK_TIMEOUT_S", 0.2)
    monkeypatch.setattr(call_mod, "_ANSWER_QUIET_S", 0.01)


@pytest.fixture
def sessions() -> _Sessions:
    return _Sessions()


@pytest.fixture
def app(sessions: _Sessions) -> FastAPI:
    application = FastAPI()
    application.include_router(telephony_router)
    application.state.telephony_manager = TelephonyManager()
    application.state.bus = None
    application.state.telephony_skip_signature = True
    application.state.telephony_realtime_session_factory = sessions
    return application


def _await_media(ws: Any, budget: int = 40) -> dict[str, Any]:
    for _ in range(budget):
        msg = ws.receive_json()
        if msg.get("event") == "media":
            return msg
    raise AssertionError("no outbound media")


def test_simulated_call_bridges_audio_both_ways_and_records_call(app, sessions):
    with TestClient(app) as client:
        with client.websocket_connect("/api/telephony/media") as ws:
            ws.send_json({"event": "connected", "protocol": "Call"})
            ws.send_json(_start(language="de-DE"))
            for _ in range(5):
                ws.send_json({"event": "media", "media": {"payload": _ulaw_frame_b64()}})
            media = _await_media(ws)
            assert media["streamSid"] == "MZ123"
            assert base64.b64decode(media["media"]["payload"])  # mu-law bytes
            ws.send_json({"event": "mark", "mark": {"name": "out-1"}})
            ws.send_json({"event": "stop", "stop": {"callSid": "CA123"}})

    (session,) = sessions.built
    assert session.controls[0] == {"type": "audio_start", "sample_rate": 8000}
    assert session.audio_in and all(len(pcm) == 320 for pcm in session.audio_in)
    assert "de-DE" in session.call_brief
    assert session.ended_with == "client_stop"
    calls = app.state.telephony_manager.recent_calls()
    assert len(calls) == 1
    assert calls[0]["call_sid"] == "CA123"
    assert calls[0]["status"] == "completed"


def test_outbound_call_carries_its_opening_into_the_session(app, sessions):
    with TestClient(app) as client:
        with client.websocket_connect("/api/telephony/media") as ws:
            ws.send_json(_start("CA77", direction="outbound", opening="Servus, hier ist Dodaios."))
            ws.send_json({"event": "media", "media": {"payload": _ulaw_frame_b64()}})
            _await_media(ws)
            ws.send_json({"event": "stop"})
    (session,) = sessions.built
    assert "Servus, hier ist Dodaios." in session.call_brief
    assert ("call_opening", "Servus, hier ist Dodaios.") in session.spoken


def test_media_socket_records_no_audio_when_silent(app, sessions):
    with TestClient(app) as client:
        with client.websocket_connect("/api/telephony/media") as ws:
            ws.send_json({"event": "connected"})
            ws.send_json(_start("CA9"))
            ws.send_json({"event": "stop"})

    calls = app.state.telephony_manager.recent_calls()
    assert len(calls) == 1
    assert calls[0]["call_sid"] == "CA9"
    # No inbound caller audio ever arrived -> the call is flagged no_audio.
    assert calls[0]["status"] == "no_audio"


def test_session_hangup_closes_the_twilio_stream(app, sessions):
    with TestClient(app) as client:
        with client.websocket_connect("/api/telephony/media") as ws:
            ws.send_json(_start("CA5"))
            ws.send_json({"event": "media", "media": {"payload": _ulaw_frame_b64()}})
            _await_media(ws)
            (session,) = sessions.built
            # The model ended the call (the end_call tool / a confirmed hang-up).
            client.portal.call(session.emit, {"type": "hangup", "reason": "voice_pattern"})
            with pytest.raises(WebSocketDisconnect):
                for _ in range(50):
                    ws.receive_json()
    calls = app.state.telephony_manager.recent_calls()
    assert [c["call_sid"] for c in calls] == ["CA5"]
    assert calls[0]["status"] == "completed"


def test_call_is_refused_when_no_realtime_session_can_hold_it(app, sessions):
    sessions.refuse = True
    with TestClient(app) as client:
        with client.websocket_connect("/api/telephony/media") as ws:
            ws.send_json(_start("CA404"))
            message = ws.receive()
            assert message["type"] == "websocket.close"
            assert message["code"] == 1011
    calls = app.state.telephony_manager.recent_calls()
    assert [c["call_sid"] for c in calls] == ["CA404"]
    assert calls[0]["status"] == "failed"
    assert app.state.telephony_manager.active_calls == 0

