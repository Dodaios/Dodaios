"""A phone call bridged to a realtime voice session (``dodaios.telephony.call``).

The session is the scripted :class:`tests.fakes.fake_phone_session.FakePhoneSession`;
Twilio is a list of the messages the bridge sends. No socket, provider or key.
"""

from __future__ import annotations

import asyncio
import base64
import math
import struct
from typing import Any

import pytest

from dodaios.telephony import call as call_mod
from dodaios.telephony import decision_calls
from dodaios.telephony.audio import TWILIO_SAMPLE_RATE, pcm16_to_ulaw, ulaw_to_pcm16
from dodaios.telephony.call import PhoneCall
from dodaios.telephony.constants import CALL_COMPLETED, CALL_FAILED, CALL_NO_AUDIO
from tests.fakes.fake_phone_session import FakePhoneSession


def _tone(rate: int, ms: int, *, amp: int = 8000, freq: int = 440) -> bytes:
    n = rate * ms // 1000
    return b"".join(
        struct.pack("<h", int(amp * math.sin(2 * math.pi * freq * i / rate))) for i in range(n)
    )


def _media_b64(ms: int = 20) -> str:
    return base64.b64encode(pcm16_to_ulaw(_tone(TWILIO_SAMPLE_RATE, ms))).decode("ascii")


class Line:
    """Twilio's side of the media socket plus the session the call built."""

    def __init__(self, **session_options: Any) -> None:
        self.sent: list[dict[str, Any]] = []
        self.hung_up = 0
        self.session: FakePhoneSession | None = None
        self.briefs: list[str] = []
        self.build_returns_none = False
        self._session_options = session_options

    async def send(self, msg: dict[str, Any]) -> None:
        self.sent.append(msg)

    async def hang_up(self) -> None:
        self.hung_up += 1

    def build(self, *, send_binary: Any, send_json: Any, call_brief: str) -> Any:
        self.briefs.append(call_brief)
        if self.build_returns_none:
            return None
        self.session = FakePhoneSession(
            send_binary=send_binary,
            send_json=send_json,
            call_brief=call_brief,
            **self._session_options,
        )
        return self.session

    def events(self, kind: str) -> list[dict[str, Any]]:
        return [m for m in self.sent if m.get("event") == kind]


def _call(line: Line, **kw: Any) -> PhoneCall:
    options: dict[str, Any] = {
        "call_sid": "CA1",
        "stream_sid": "MZ1",
        "send": line.send,
        "hang_up": line.hang_up,
        "build_session": line.build,
        "from_number": "+4915100000001",
        "to_number": "+4930000000",
        "language_code": "en-US",
        "max_call_seconds": 0,  # no cap task unless a test asks for one
    }
    options.update(kw)
    return PhoneCall(**options)


async def _settle(call: PhoneCall) -> None:
    """Run every task the call spawned to completion."""
    for _ in range(50):
        await asyncio.sleep(0)
        pending = [t for t in call._tasks if not t.done()]
        if not pending:
            return
        await asyncio.gather(*pending, return_exceptions=True)


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(call_mod, "_LINE_RETRY_S", 0.001)
    monkeypatch.setattr(call_mod, "_REPLY_PLAYBACK_TIMEOUT_S", 0.05)
    monkeypatch.setattr(call_mod, "_ANSWER_QUIET_S", 0.01)
    decision_calls.clear()
    yield
    decision_calls.clear()


# -- start --------------------------------------------------------------------


async def test_start_opens_the_session_at_the_phone_rate_and_greets():
    line = Line()
    call = _call(line, greeting="Hello, this is the assistant.")
    assert await call.start() is True
    await _settle(call)
    assert line.session is not None
    assert line.session.controls[0] == {"type": "audio_start", "sample_rate": 8000}
    assert line.session.spoken == [("call_opening", "Hello, this is the assistant.")]


async def test_outbound_call_says_its_opening_and_carries_its_purpose():
    line = Line()
    call = _call(line, direction="outbound", opening="Hi Laura, are we still on for Friday?")
    await call.start()
    await _settle(call)
    assert line.session is not None
    assert line.session.spoken == [("call_opening", "Hi Laura, are we still on for Friday?")]
    brief = line.briefs[0]
    assert "PHONE CALL" in brief
    assert "Hi Laura, are we still on for Friday?" in brief
    assert "not the owner" in brief


def test_inbound_brief_names_the_owner_and_the_call_language():
    line = Line()
    brief = _call(line, language_code="de-DE").call_brief()
    assert "The owner called you" in brief
    assert "de-DE" in brief


async def test_opening_waits_until_the_model_is_free():
    line = Line(lines_accepted_after=3)
    call = _call(line, greeting="Hello.")
    await call.start()
    await _settle(call)
    assert line.session is not None
    assert len(line.session.line_offers) == 4
    assert line.session.spoken == [("call_opening", "Hello.")]


async def test_opening_is_dropped_once_the_model_already_spoke():
    line = Line(lines_accepted_after=1_000)
    call = _call(line, greeting="Hello.")
    await call.start()
    for _ in range(3):
        await asyncio.sleep(0)
    assert line.session is not None
    await line.session.answer(_tone(24_000, 20))
    await _settle(call)
    assert line.session.spoken == []
    assert len(line.session.line_offers) < call_mod._LINE_ATTEMPTS


# -- refusal ------------------------------------------------------------------


async def test_no_realtime_session_refuses_the_call():
    line = Line()
    line.build_returns_none = True
    call = _call(line)
    assert await call.start() is False
    assert call.ended and call.status == CALL_FAILED
    assert call.end_reason == "realtime_unavailable"
    assert line.events("media") == []


async def test_a_session_that_cannot_start_ends_the_call_and_hangs_up():
    line = Line(start_error=RuntimeError("provider refused"))
    call = _call(line)
    assert await call.start() is True  # the handshake runs in the background
    await _settle(call)
    assert call.ended and call.status == CALL_FAILED
    assert line.hung_up == 1
    assert line.session is not None and line.session.ended_with == "error"


# -- audio both ways ------------------------------------------------------------


async def test_caller_audio_reaches_the_session_as_8k_pcm():
    line = Line()
    call = _call(line)
    await call.start()
    await _settle(call)
    payload = _media_b64(20)
    await call.handle_media(payload)
    assert line.session is not None
    assert line.session.audio_in == [ulaw_to_pcm16(base64.b64decode(payload))]
    assert len(line.session.audio_in[0]) == 160 * 2  # 20 ms at 8 kHz, 16-bit


async def test_caller_audio_before_the_session_is_ready_is_held_back():
    line = Line()
    call = _call(line)
    await call.start()  # handshake task not run yet
    await call.handle_media(_media_b64())
    assert line.session is not None and line.session.audio_in == []
    await _settle(call)


async def test_malformed_media_is_dropped():
    line = Line()
    call = _call(line)
    await call.start()
    await _settle(call)
    await call.handle_media("not base64!!")
    assert line.session is not None and line.session.audio_in == []
    assert not call.ended


async def test_session_audio_goes_to_twilio_as_8k_mulaw_media_with_a_mark():
    line = Line(output_sample_rate=24_000)
    call = _call(line)
    await call.start()
    await _settle(call)
    assert line.session is not None
    await line.session.answer(_tone(24_000, 100))
    media = line.events("media")
    assert len(media) == 1
    assert media[0]["streamSid"] == "MZ1"
    ulaw = base64.b64decode(media[0]["media"]["payload"])
    assert abs(len(ulaw) - 800) <= 4  # 100 ms at 8 kHz, one mu-law byte per sample
    marks = line.events("mark")
    assert marks and marks[-1]["mark"]["name"] == "out-1"
    assert call.playing
    call.handle_mark("out-1")
    assert not call.playing


async def test_output_rate_follows_the_sessions_audio_ready():
    line = Line(output_sample_rate=16_000)
    call = _call(line)
    await call.start()
    await _settle(call)
    assert line.session is not None
    await line.session.answer(_tone(16_000, 100))
    ulaw = base64.b64decode(line.events("media")[0]["media"]["payload"])
    assert abs(len(ulaw) - 800) <= 4


async def test_barge_in_clears_twilios_playback():
    line = Line()
    call = _call(line)
    await call.start()
    await _settle(call)
    assert line.session is not None
    await line.session.answer(_tone(24_000, 40))
    await line.session.emit({"type": "tts_cancel"})
    assert line.events("clear") == [{"event": "clear", "streamSid": "MZ1"}]


async def test_turns_are_counted_from_the_session():
    line = Line()
    call = _call(line)
    await call.start()
    await _settle(call)
    assert line.session is not None
    await line.session.emit({"type": "turn_complete"})
    await line.session.emit({"type": "turn_complete"})
    assert call.turns == 2


# -- the end, from either side --------------------------------------------------


async def test_twilio_hangup_ends_the_session():
    line = Line()
    call = _call(line)
    await call.start()
    await _settle(call)
    await call.handle_media(_media_b64())
    await call.end(reason="twilio_stop", status=CALL_COMPLETED)
    assert line.session is not None and line.session.ended_with == "client_stop"
    assert call.status == CALL_COMPLETED
    assert line.hung_up == 0  # Twilio already hung up; nothing to close


async def test_a_call_without_caller_audio_is_recorded_as_no_audio():
    line = Line()
    call = _call(line)
    await call.start()
    await _settle(call)
    await call.end(reason="twilio_stop", status=CALL_COMPLETED)
    assert call.status == CALL_NO_AUDIO


async def test_session_hangup_ends_the_twilio_call():
    line = Line()
    call = _call(line)
    await call.start()
    await _settle(call)
    assert line.session is not None
    await line.session.emit({"type": "hangup", "reason": "voice_pattern"})
    await _settle(call)
    assert call.ended and call.end_reason == "session_ended"
    assert line.hung_up == 1


async def test_session_hangup_lets_twilio_play_the_goodbye_first(monkeypatch):
    monkeypatch.setattr(call_mod, "_REPLY_PLAYBACK_TIMEOUT_S", 5.0)
    line = Line()
    call = _call(line)
    await call.start()
    await _settle(call)
    assert line.session is not None
    await line.session.answer(_tone(24_000, 40))  # the goodbye, still queued at Twilio
    await line.session.emit({"type": "audio_closed"})
    await asyncio.sleep(0.05)
    assert line.hung_up == 0  # Twilio has not played it yet
    call.handle_mark(line.events("mark")[-1]["mark"]["name"])
    await _settle(call)
    assert call.ended and line.hung_up == 1


async def test_session_failure_ends_the_call_as_failed():
    line = Line()
    call = _call(line)
    await call.start()
    await _settle(call)
    assert line.session is not None
    line.session.failed = True
    await line.session.emit({"type": "provider_error", "error": "Voice connection lost"})
    await _settle(call)
    assert call.status == CALL_FAILED and line.hung_up == 1


async def test_time_cap_hangs_up():
    line = Line()
    call = _call(line, max_call_seconds=0.01)
    await call.start()
    await asyncio.sleep(0.05)
    await _settle(call)
    assert call.ended and call.end_reason == "max_call_seconds"
    assert line.hung_up == 1


async def test_end_publishes_the_call_end_on_the_bus():
    published: list[Any] = []

    class Bus:
        async def publish(self, event: Any) -> None:
            published.append(event)

    line = Line()
    call = _call(line, bus=Bus())
    await call.start()
    await _settle(call)
    await call.handle_media(_media_b64())
    await call.end(reason="twilio_stop", status=CALL_COMPLETED)
    for _ in range(5):
        await asyncio.sleep(0)
    ends = [e for e in published if type(e).__name__ == "TelephonyCallEnded"]
    assert len(ends) == 1 and ends[0].status == CALL_COMPLETED


# -- one-decision calls ---------------------------------------------------------


def _decision(resolved: list[str], *, accepts_yes: bool = True) -> decision_calls.DecisionCall:
    async def resolve(answer: str) -> str:
        resolved.append(answer)
        return f"Done: {answer}."

    return decision_calls.DecisionCall(
        resolve=resolve,
        reprompt="Yes, no or later?",
        later_reply="It stays open.",
        accepts_yes=accepts_yes,
    )


async def _say_to_call(line: Line, text: str) -> None:
    assert line.session is not None
    await line.session.emit({"type": "transcript", "role": "user", "text": text, "is_final": True})


async def test_decision_brief_forbids_claiming_the_result():
    decision_calls.register("CA1", _decision([]))
    brief = _call(Line(), direction="outbound", opening="May I send the mail?").call_brief()
    assert "exactly one decision" in brief
    assert "Never say yourself" in brief


@pytest.mark.parametrize(("said", "answer"), [("Yes, go ahead", "yes"), ("No", "no")])
async def test_spoken_answer_settles_the_decision_and_hangs_up(said, answer):
    resolved: list[str] = []
    decision_calls.register("CA1", _decision(resolved))
    line = Line()
    call = _call(line, direction="outbound", opening="May I send the mail?")
    await call.start()
    await _settle(call)
    await _say_to_call(line, said)
    await _settle(call)
    assert resolved == [answer]
    assert line.session is not None
    assert ("call_decision", f"Done: {answer}.") in line.session.spoken
    assert call.ended and call.end_reason == f"decision_{answer}"
    assert line.hung_up == 1
    assert decision_calls.get("CA1") is None


async def test_an_unclear_answer_is_asked_once_more_then_left_open():
    resolved: list[str] = []
    decision_calls.register("CA1", _decision(resolved))
    line = Line()
    call = _call(line, direction="outbound", opening="May I send the mail?")
    await call.start()
    await _settle(call)
    await _say_to_call(line, "blorp")
    await _settle(call)
    assert not call.ended
    assert line.session is not None
    assert ("call_decision", "Yes, no or later?") in line.session.spoken
    await _say_to_call(line, "blorp")
    await _settle(call)
    assert resolved == []
    assert ("call_decision", "It stays open.") in line.session.spoken
    assert call.ended and call.end_reason == "decision_later"


async def test_a_yes_that_cannot_be_taken_counts_as_later():
    resolved: list[str] = []
    decision_calls.register("CA1", _decision(resolved, accepts_yes=False))
    line = Line()
    call = _call(line, direction="outbound", opening="Which name?")
    await call.start()
    await _settle(call)
    await _say_to_call(line, "yes")
    await _settle(call)
    assert resolved == [] and call.end_reason == "decision_later"


async def test_a_decision_that_fails_to_apply_says_it_stays_open():
    async def resolve(_answer: str) -> str:
        raise RuntimeError("card gone")

    decision_calls.register(
        "CA1", decision_calls.DecisionCall(resolve=resolve, later_reply="It stays open.")
    )
    line = Line()
    call = _call(line, direction="outbound", opening="May I?")
    await call.start()
    await _settle(call)
    await _say_to_call(line, "yes")
    await _settle(call)
    assert line.session is not None
    assert ("call_decision", "It stays open.") in line.session.spoken
    assert call.end_reason == "decision_yes"


async def test_without_a_decision_the_transcript_only_feeds_the_record():
    line = Line()
    call = _call(line)
    await call.start()
    await _settle(call)
    await _say_to_call(line, "yes")
    await _settle(call)
    assert not call.ended
