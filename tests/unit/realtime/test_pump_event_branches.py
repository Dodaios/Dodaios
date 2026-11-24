"""Characterization of the realtime receive loop's rarely exercised branches.

``_pump_transport_once`` is the voice event loop. These tests drive it with a
scripted transport and pin what each of its less common exits does: usage
metering, a refused stale handoff, a terminal provider error, a stream that
dies mid-turn, a speaker failure, and the return value that asks for a rebuild.
"""

from __future__ import annotations

import asyncio

import pytest

from dodaios.core.protocols import AudioChunk
from dodaios.realtime.protocol import RealtimeEvent
from dodaios.realtime.session import RealtimeVoiceSession
from tests.unit.realtime.test_session import FakeProvider, _cfg


class _Scripted:
    """A transport whose ``receive`` replays events, then ends or raises."""

    creates_responses_automatically = False

    def __init__(self, events, *, raises: Exception | None = None):
        self._events = list(events)
        self._raises = raises
        self.interrupted = 0

    async def receive(self):
        for event in self._events:
            yield event
            await asyncio.sleep(0)
        if self._raises is not None:
            raise self._raises

    async def interrupt(self):
        self.interrupted += 1

    async def close(self):  # pragma: no cover - never reached by these tests
        return None


def _session(transport):
    jsons: list[dict] = []

    async def send_json(message):
        jsons.append(message)

    async def send_binary(_data):
        return None

    sess = RealtimeVoiceSession(
        session_id="pump-branches",
        send_binary=send_binary,
        send_json=send_json,
        provider=FakeProvider([]),
        config=_cfg(),
        bus=None,
    )
    sess._session = transport
    return sess, jsons


@pytest.mark.asyncio
async def test_usage_events_accumulate_per_key():
    sess, _ = _session(
        _Scripted(
            [
                RealtimeEvent(type="usage", usage={"input_tokens": 3, "output_tokens": 2}),
                RealtimeEvent(type="usage", usage={"input_tokens": 4, "ignored": "x", "zero": 0}),
            ]
        )
    )
    assert await sess._pump_transport_once() is None
    assert sess._turn_usage == {"input_tokens": 7, "output_tokens": 2}


@pytest.mark.asyncio
async def test_audio_delta_without_audio_is_ignored():
    sess, jsons = _session(_Scripted([RealtimeEvent(type="audio_delta", audio=None)]))
    assert await sess._pump_transport_once() is None
    assert jsons == []


@pytest.mark.asyncio
async def test_unknown_event_type_is_ignored():
    sess, jsons = _session(_Scripted([RealtimeEvent(type="something_new")]))
    assert await sess._pump_transport_once() is None
    assert jsons == []


@pytest.mark.asyncio
async def test_stale_handoff_is_refused_without_a_turn(monkeypatch):
    sess, _ = _session(_Scripted([RealtimeEvent(type="handoff_requested", text="do it")]))
    monkeypatch.setattr(sess, "_stale_generation_drop_active", lambda: True)
    assert await sess._pump_transport_once() is None
    assert sess._delegate_required_for_turn is False
    assert not sess._last_user_text


@pytest.mark.asyncio
async def test_stale_tool_call_is_rejected_not_run(monkeypatch):
    rejected = []
    sess, _ = _session(_Scripted([RealtimeEvent(type="tool_call", tool_name="anything")]))
    monkeypatch.setattr(sess, "_stale_generation_drop_active", lambda: True)

    async def reject(event):
        rejected.append(event.tool_name)

    monkeypatch.setattr(sess, "_reject_stale_generation_tool_call", reject)
    assert await sess._pump_transport_once() is None
    assert rejected == ["anything"]


@pytest.mark.asyncio
async def test_terminal_provider_error_fails_the_call():
    sess, jsons = _session(
        _Scripted(
            [
                RealtimeEvent(type="error", error="boom", recoverable=False),
                RealtimeEvent(type="output_transcript_delta", text="never seen"),
            ]
        )
    )
    assert await sess._pump_transport_once() is None
    assert sess._failed.is_set()
    assert sess._failure_detail == "boom"
    assert jsons == [{"type": "provider_error", "error": "boom"}]
    assert not any(m.get("text") == "never seen" for m in jsons)


@pytest.mark.asyncio
async def test_recoverable_provider_error_keeps_the_loop_alive():
    sess, jsons = _session(
        _Scripted(
            [
                RealtimeEvent(type="error", error="hiccup", recoverable=True),
                RealtimeEvent(type="usage", usage={"input_tokens": 1}),
            ]
        )
    )
    assert await sess._pump_transport_once() is None
    assert {"type": "provider_warning", "error": "hiccup"} in jsons
    assert sess._turn_usage == {"input_tokens": 1}
    assert not sess._failed.is_set()


@pytest.mark.asyncio
async def test_receive_exception_ends_the_pump_as_a_failure():
    sess, jsons = _session(_Scripted([], raises=RuntimeError("socket died")))
    assert await sess._pump_transport_once() is None
    assert sess._failed.is_set()
    assert sess._failure_detail == "socket died"
    assert jsons == [{"type": "provider_error", "error": "socket died"}]


@pytest.mark.asyncio
async def test_pump_without_a_session_returns_none():
    sess, _ = _session(None)
    assert await sess._pump_transport_once() is None


@pytest.mark.asyncio
async def test_cancellation_is_never_swallowed():
    class _Hang(_Scripted):
        async def receive(self):
            await asyncio.sleep(30)
            yield RealtimeEvent(type="usage", usage={})

    sess, _ = _session(_Hang([]))
    task = asyncio.ensure_future(sess._pump_transport_once())
    await asyncio.sleep(0.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_audio_without_user_turn_is_withheld_or_gated():
    """Audio arriving first goes through the scrub gate, never straight out."""
    sess, _ = _session(
        _Scripted(
            [
                RealtimeEvent(
                    type="audio_delta",
                    audio=AudioChunk(pcm=b"\x01\x02" * 8, sample_rate=24_000, timestamp_ns=0),
                )
            ]
        )
    )
    sent: list[bytes] = []

    async def send_binary(data):
        sent.append(data)

    sess._send_binary = send_binary
    assert await sess._pump_transport_once() is None
    assert sent == []
