"""Grok realtime voice against a local fake of the xAI Voice Agent socket.

Nothing here reaches api.x.ai. A real ``websockets`` server on 127.0.0.1
plays the xAI side with the event names from the xAI Voice Agent docs
(read 2026-11-24), so the handshake, the JSON framing and the close paths
are the library's real ones.
"""

from __future__ import annotations

import asyncio
import base64
import json
from http import HTTPStatus
from types import SimpleNamespace
from typing import Any

import pytest

from dodaios.core.protocols import VoiceStartError
from dodaios.plugins.realtime import _live_transport, grok_realtime
from dodaios.plugins.realtime.grok_realtime import GrokRealtimeProvider, session_payload
from dodaios.realtime.protocol import RealtimeProvider, RealtimeSessionConfig


class FakeXai:
    """One scripted xAI server: records what the client sent, replies on cue."""

    def __init__(self, *, status: HTTPStatus | None = None, setup_reply: str = "ok") -> None:
        self.status = status
        self.setup_reply = setup_reply
        self.received: list[dict[str, Any]] = []
        self.authorization = ""
        self.path = ""
        self.socket: Any = None
        self.connected = asyncio.Event()
        self.message = asyncio.Event()

    async def process_request(self, connection: Any, request: Any) -> Any:
        self.authorization = str(request.headers.get("Authorization", ""))
        self.path = request.path
        if self.status is not None:
            return connection.respond(self.status, "refused\n")
        return None

    async def handler(self, socket: Any) -> None:
        self.socket = socket
        await socket.send(json.dumps({"type": "session.created", "session": {}}))
        self.connected.set()
        try:
            async for raw in socket:
                event = json.loads(raw)
                self.received.append(event)
                self.message.set()
                if event.get("type") == "session.update" and len(self.received) == 1:
                    if self.setup_reply == "ok":
                        await socket.send(json.dumps({"type": "session.updated", "session": {}}))
                    elif self.setup_reply == "error":
                        await socket.send(json.dumps({
                            "type": "error",
                            "error": {"code": "invalid_value", "message": "bad voice"},
                        }))
                    elif self.setup_reply == "close_policy":
                        await socket.close(code=1008, reason="unauthorized")
                        return
        except Exception:  # noqa: BLE001 - the client may drop the socket mid-test
            return

    async def emit(self, event: dict[str, Any]) -> None:
        await self.socket.send(json.dumps(event))

    async def wait_for(self, kind: str) -> dict[str, Any]:
        async with asyncio.timeout(2):
            while True:
                for event in self.received:
                    if event.get("type") == kind:
                        return event
                self.message.clear()
                await self.message.wait()


@pytest.fixture
async def xai(monkeypatch: pytest.MonkeyPatch):
    from websockets.asyncio.server import serve

    async def plain_options() -> dict[str, Any]:
        return {}  # ws:// on localhost takes no TLS context

    monkeypatch.setattr(_live_transport, "websocket_options", plain_options)

    servers: list[Any] = []

    async def start(**kwargs: Any) -> FakeXai:
        fake = FakeXai(**kwargs)
        server = await serve(fake.handler, "127.0.0.1", 0, process_request=fake.process_request)
        servers.append(server)
        port = server.sockets[0].getsockname()[1]
        monkeypatch.setattr(grok_realtime, "_ENDPOINT", f"ws://127.0.0.1:{port}/v1/realtime")
        return fake

    yield start
    for server in servers:
        server.close()
        await server.wait_closed()


def _cfg(**overrides: Any) -> RealtimeSessionConfig:
    values: dict[str, Any] = {
        "instructions": "You are Dodaios.",
        "input_language": "de",
        "tools": ({"name": "search_web", "description": "Search", "parameters": {
            "type": "object", "properties": {"q": {"type": "string"}}}},),
        "history": ({"role": "user", "text": "Hallo"}, {"role": "assistant", "text": "Hi!"}),
    }
    values.update(overrides)
    return RealtimeSessionConfig(**values)


async def _next(events: Any) -> Any:
    async with asyncio.timeout(2):
        return await anext(events)


def test_provider_is_structurally_conformant() -> None:
    provider = GrokRealtimeProvider(api_key="xai-test")
    assert isinstance(provider, RealtimeProvider)
    assert provider.name == "grok-realtime"
    assert provider.native_tool_orchestration is True
    assert provider.input_sample_rate == provider.output_sample_rate == 24_000
    assert provider.implicit_usage_fallback_allowed is False


def test_session_payload_uses_server_owned_turns() -> None:
    payload = session_payload(_cfg(voice="rex"))
    assert payload["voice"] == "rex"
    assert payload["turn_detection"] == {"type": "server_vad"}
    assert payload["audio"]["input"]["format"] == {"type": "audio/pcm", "rate": 24_000}
    assert payload["audio"]["output"]["format"] == {"type": "audio/pcm", "rate": 24_000}
    assert payload["audio"]["input"]["transcription"] == {
        "model": "grok-transcribe", "language_hint": "de",
    }
    assert payload["tools"][0]["type"] == "function"
    assert payload["tools"][0]["name"] == "search_web"
    # The manual-response contract that wedged the July 2026 adapter.
    assert "create_response" not in json.dumps(payload)


def test_session_payload_defaults_voice_and_regional_hints() -> None:
    payload = session_payload(_cfg(voice="", input_language="es", tools=()))
    assert payload["voice"] == "eve"
    assert payload["audio"]["input"]["transcription"]["language_hint"] == "es-ES"
    assert "tools" not in payload
    auto = session_payload(_cfg(voice="auto", input_language="auto"))
    assert auto["voice"] == "eve"
    assert "language_hint" not in auto["audio"]["input"]["transcription"]


async def test_session_setup_sends_settings_then_history(xai) -> None:
    fake = await xai()
    provider = GrokRealtimeProvider(api_key="xai-secret")

    session = await provider.open_session(_cfg(model="grok-voice-3.0"))
    try:
        assert fake.authorization == "Bearer xai-secret"
        assert fake.path == "/v1/realtime?model=grok-voice-3.0"
        assert session.model == "grok-voice-3.0"
        await fake.wait_for("conversation.item.create")
        update = fake.received[0]
        assert update["type"] == "session.update"
        assert update["session"]["instructions"] == "You are Dodaios."
        async with asyncio.timeout(2):
            while len(fake.received) < 3:
                fake.message.clear()
                await fake.message.wait()
        history = [event["item"] for event in fake.received[1:3]]
        assert history[0]["role"] == "user"
        assert history[0]["content"] == [{"type": "input_text", "text": "Hallo"}]
        assert history[1]["role"] == "assistant"
        assert history[1]["content"] == [{"type": "output_text", "text": "Hi!"}]
    finally:
        await session.close()


async def test_default_model_when_card_pins_none(xai) -> None:
    fake = await xai()
    session = await GrokRealtimeProvider(api_key="k").open_session(_cfg(history=()))
    try:
        assert fake.path == "/v1/realtime?model=grok-voice-latest"
    finally:
        await session.close()


async def test_audio_in_is_base64_pcm_at_24k(xai) -> None:
    fake = await xai()
    session = await GrokRealtimeProvider(api_key="k").open_session(_cfg(history=()))
    try:
        await session.send_audio(SimpleNamespace(pcm=b"\x01\x02\x03\x04", sample_rate=24_000))
        append = await fake.wait_for("input_audio_buffer.append")
        assert base64.b64decode(append["audio"]) == b"\x01\x02\x03\x04"
        with pytest.raises(ValueError, match="24000 Hz"):
            await session.send_audio(SimpleNamespace(pcm=b"\x00\x00", sample_rate=16_000))
    finally:
        await session.close()


async def test_audio_and_transcripts_out(xai) -> None:
    fake = await xai()
    session = await GrokRealtimeProvider(api_key="k").open_session(_cfg(history=()))
    events = session.receive().__aiter__()
    try:
        await fake.emit({"type": "input_audio_buffer.speech_started"})
        await fake.emit({
            "type": "conversation.item.input_audio_transcription.updated",
            "item_id": "u1", "transcript": "What time",
        })
        await fake.emit({
            "type": "conversation.item.input_audio_transcription.completed",
            "item_id": "u1", "transcript": "What time is it?",
        })
        await fake.emit({"type": "response.created", "response": {"id": "r1"}})
        await fake.emit({
            "type": "response.output_audio.delta",
            "delta": base64.b64encode(b"\x10\x00\x20\x00").decode(),
        })
        await fake.emit({"type": "response.output_audio_transcript.delta", "delta": "Es ist "})
        await fake.emit({"type": "response.output_audio_transcript.delta", "delta": "zehn."})
        await fake.emit({
            "type": "response.output_audio_transcript.done", "transcript": "Es ist zehn.",
        })
        await fake.emit({"type": "response.done", "response": {
            "id": "r1", "status": "completed",
            "usage": {"input_tokens": 12, "output_tokens": 30,
                      "input_token_details": {"audio_tokens": 10, "text_tokens": 2},
                      "output_token_details": {"audio_tokens": 25, "text_tokens": 5}},
        }})

        kinds = []
        first = await _next(events)
        kinds.append(first.type)
        partial = await _next(events)
        final = await _next(events)
        audio = await _next(events)
        out1 = await _next(events)
        out2 = await _next(events)
        usage = await _next(events)
        done = await _next(events)
        assert first.type == "speech_started"
        assert (partial.type, partial.text, partial.is_final) == (
            "input_transcript", "What time", False,
        )
        assert (final.type, final.text, final.is_final) == (
            "input_transcript", "What time is it?", True,
        )
        assert audio.type == "audio_delta"
        assert audio.audio.pcm == b"\x10\x00\x20\x00"
        assert audio.audio.sample_rate == 24_000
        # The .done line is not repeated after streamed deltas.
        assert [out1.text, out2.text] == ["Es ist ", "zehn."]
        assert usage.type == "usage"
        assert usage.usage["input_total"] == 12
        assert usage.usage["output_audio"] == 25
        assert done.type == "turn_complete"
    finally:
        await session.close()


async def test_transcript_done_only_line_is_delivered(xai) -> None:
    fake = await xai()
    session = await GrokRealtimeProvider(api_key="k").open_session(_cfg(history=()))
    events = session.receive().__aiter__()
    try:
        await fake.emit({"type": "response.created", "response": {"id": "r1"}})
        await fake.emit({"type": "response.output_audio_transcript.done", "transcript": "Ja."})
        event = await _next(events)
        assert (event.type, event.text) == ("output_transcript_delta", "Ja.")
    finally:
        await session.close()


async def test_tool_call_result_then_one_continuation(xai) -> None:
    fake = await xai()
    session = await GrokRealtimeProvider(api_key="k").open_session(_cfg(history=()))
    events = session.receive().__aiter__()
    try:
        await fake.emit({"type": "response.created", "response": {"id": "r1"}})
        await fake.emit({
            "type": "response.function_call_arguments.done",
            "call_id": "c1", "name": "search_web", "arguments": '{"q": "Wetter"}',
        })
        await fake.emit({"type": "response.done", "response": {"id": "r1", "status": "completed"}})
        call = await _next(events)
        assert (call.type, call.call_id, call.tool_name, call.tool_args) == (
            "tool_call", "c1", "search_web", {"q": "Wetter"},
        )
        # The tool response is not a finished turn; the answer comes next.
        reader = asyncio.ensure_future(_next(events))
        await asyncio.sleep(0.05)
        assert not reader.done()
        assert not any(e["type"] == "response.create" for e in fake.received)

        await session.send_tool_result("c1", "search_web", {"success": True, "text": "Sonne"})
        output = await fake.wait_for("conversation.item.create")
        assert output["item"]["type"] == "function_call_output"
        assert output["item"]["call_id"] == "c1"
        assert json.loads(output["item"]["output"]) == {"success": True, "text": "Sonne"}
        await fake.wait_for("response.create")
        assert sum(e["type"] == "response.create" for e in fake.received) == 1
        reader.cancel()
    finally:
        await session.close()


async def test_malformed_tool_arguments_count_as_none(xai) -> None:
    fake = await xai()
    session = await GrokRealtimeProvider(api_key="k").open_session(_cfg(history=()))
    events = session.receive().__aiter__()
    try:
        await fake.emit({
            "type": "response.function_call_arguments.done",
            "call_id": "c2", "name": "search_web", "arguments": "{not json",
        })
        call = await _next(events)
        assert call.tool_args == {}
    finally:
        await session.close()


async def test_barge_in_leaves_cancel_to_the_server(xai) -> None:
    """The client never cancels a reply the server already interrupted."""
    fake = await xai()
    session = await GrokRealtimeProvider(api_key="k").open_session(_cfg(history=()))
    events = session.receive().__aiter__()
    try:
        await fake.emit({"type": "response.created", "response": {"id": "r1"}})
        await fake.emit({"type": "input_audio_buffer.speech_started"})
        assert (await _next(events)).type == "speech_started"
        await session.interrupt()
        await fake.emit({"type": "response.done", "response": {"id": "r1", "status": "cancelled"}})
        assert (await _next(events)).type == "turn_complete"
        await asyncio.sleep(0.05)
        assert not any(e["type"] == "response.cancel" for e in fake.received)
    finally:
        await session.close()


async def test_manual_stop_cancels_a_running_reply_once(xai) -> None:
    fake = await xai()
    session = await GrokRealtimeProvider(api_key="k").open_session(_cfg(history=()))
    events = session.receive().__aiter__()
    try:
        await fake.emit({"type": "response.created", "response": {"id": "r1"}})
        await fake.emit({"type": "response.output_audio_transcript.delta", "delta": "Also"})
        await _next(events)
        await session.interrupt()
        await session.interrupt()
        await fake.wait_for("response.cancel")
        await asyncio.sleep(0.05)
        assert sum(e["type"] == "response.cancel" for e in fake.received) == 1
    finally:
        await session.close()


async def test_typed_text_waits_for_the_running_reply(xai) -> None:
    fake = await xai()
    session = await GrokRealtimeProvider(api_key="k").open_session(_cfg(history=()))
    events = session.receive().__aiter__()
    try:
        await fake.emit({"type": "response.created", "response": {"id": "r1"}})
        await fake.emit({"type": "response.output_audio_transcript.delta", "delta": "x"})
        await _next(events)
        await session.send_text("Und morgen?")
        item = await fake.wait_for("conversation.item.create")
        assert item["item"]["content"] == [{"type": "input_text", "text": "Und morgen?"}]
        await asyncio.sleep(0.05)
        assert not any(e["type"] == "response.create" for e in fake.received)
        await fake.emit({"type": "response.done", "response": {"id": "r1", "status": "completed"}})
        assert (await _next(events)).type == "turn_complete"
        await fake.wait_for("response.create")
    finally:
        await session.close()


async def test_server_error_event_is_recoverable(xai) -> None:
    fake = await xai()
    session = await GrokRealtimeProvider(api_key="k").open_session(_cfg(history=()))
    events = session.receive().__aiter__()
    try:
        await fake.emit({"type": "error", "error": {"code": "rate_limit", "message": "slow"}})
        event = await _next(events)
        assert event.type == "error"
        assert event.recoverable is True
        assert event.error == "rate_limit: slow"
    finally:
        await session.close()


async def test_dropped_connection_raises_for_recovery(xai) -> None:
    fake = await xai()
    session = await GrokRealtimeProvider(api_key="k").open_session(_cfg(history=()))
    events = session.receive().__aiter__()
    try:
        # An abrupt drop: the TCP transport dies without a close handshake.
        fake.socket.transport.abort()
        with pytest.raises(ConnectionError, match="connection lost"):
            await _next(events)
    finally:
        await session.close()


async def test_clean_close_by_us_ends_the_stream(xai) -> None:
    await xai()
    session = await GrokRealtimeProvider(api_key="k").open_session(_cfg(history=()))
    events = session.receive().__aiter__()
    await session.close()
    with pytest.raises(StopAsyncIteration):
        await _next(events)


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (HTTPStatus.UNAUTHORIZED, "bad_key"),
        (HTTPStatus.FORBIDDEN, "access_denied"),
        (HTTPStatus.TOO_MANY_REQUESTS, "rate_limited"),
        (HTTPStatus.SERVICE_UNAVAILABLE, "unreachable"),
    ],
)
async def test_refused_handshake_names_the_cause(xai, status, code) -> None:
    await xai(status=status)
    with pytest.raises(VoiceStartError) as caught:
        await GrokRealtimeProvider(api_key="xai-wrong").open_session(_cfg())
    assert caught.value.code == code
    assert "xai-wrong" not in caught.value.user_message
    assert "xai-wrong" not in str(caught.value)


async def test_bad_key_closed_after_upgrade(xai) -> None:
    await xai(setup_reply="close_policy")
    with pytest.raises(VoiceStartError) as caught:
        await GrokRealtimeProvider(api_key="xai-wrong").open_session(_cfg())
    assert caught.value.code == "bad_key"


async def test_rejected_settings_refuse_the_call(xai) -> None:
    await xai(setup_reply="error")
    with pytest.raises(VoiceStartError) as caught:
        await GrokRealtimeProvider(api_key="k").open_session(_cfg())
    assert caught.value.code == "invalid_configuration"


async def test_unconfirmed_settings_time_out(xai, monkeypatch) -> None:
    monkeypatch.setattr(grok_realtime, "_SESSION_READY_TIMEOUT_S", 0.2)
    await xai(setup_reply="silent")
    with pytest.raises(VoiceStartError) as caught:
        await GrokRealtimeProvider(api_key="k").open_session(_cfg())
    assert caught.value.code == "unreachable"


async def test_unreachable_host(monkeypatch) -> None:
    async def plain_options() -> dict[str, Any]:
        return {}

    monkeypatch.setattr(_live_transport, "websocket_options", plain_options)
    monkeypatch.setattr(grok_realtime, "_ENDPOINT", "ws://127.0.0.1:9/v1/realtime")
    with pytest.raises(VoiceStartError) as caught:
        await GrokRealtimeProvider(api_key="k").open_session(_cfg())
    assert caught.value.code == "unreachable"


async def test_missing_key_never_connects() -> None:
    provider = GrokRealtimeProvider()
    assert await provider.can_open_duplex_session() is False
    assert "xAI" in provider.duplex_unavailable_reason
    with pytest.raises(VoiceStartError) as caught:
        await provider.open_session(_cfg())
    assert caught.value.code == "bad_key"


def test_entry_point_is_declared() -> None:
    import tomllib
    from pathlib import Path

    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    group = data["project"]["entry-points"]["jarvis.realtime"]
    assert group["grok-realtime"] == (
        "dodaios.plugins.realtime.grok_realtime:GrokRealtimeProvider"
    )


async def test_native_live_session_runs_a_grok_call(xai, monkeypatch, tmp_path) -> None:
    """Start, speak, call a tool and answer, through the real native session."""
    from dodaios.live import native, runtime
    from tests.fakes.fake_native_voice import FakeToolGateway

    monkeypatch.setattr(runtime, "_active", {})
    monkeypatch.setattr(runtime, "_opening", set())
    monkeypatch.setattr(native, "user_data_dir", lambda: tmp_path)
    gateway = FakeToolGateway()
    monkeypatch.setattr(native, "get_supervisor_tool_gateway", lambda: gateway)
    fake = await xai()
    frames: list[dict[str, Any]] = []
    played: list[bytes] = []
    audio_played = asyncio.Event()

    async def send_json(frame: dict[str, Any]) -> None:
        frames.append(frame)

    async def send_binary(data: bytes) -> None:
        played.append(data)
        audio_played.set()

    config = SimpleNamespace(
        brain=SimpleNamespace(reply_language="auto", providers={}, realtime=None),
        voice=SimpleNamespace(realtime_tool_declaration_budget_tokens=0),
    )
    session = native.NativeLiveVoiceSession(
        session_id="grok-call", send_json=send_json, send_binary=send_binary,
        providers=[GrokRealtimeProvider(api_key="k")], config=config,
    )
    try:
        await session.handle_control({"type": "audio_start", "sample_rate": 24000})
        ready = [f for f in frames if f.get("type") == "audio_ready"]
        assert ready and ready[0]["provider"] == "grok-realtime"
        update = await fake.wait_for("session.update")
        assert any(
            t["name"] == "search_web" or t["description"].startswith("search_web")
            for t in update["session"]["tools"]
        )

        await session.handle_audio_frame(b"\x00\x01" * 240)
        await fake.wait_for("input_audio_buffer.append")

        await fake.emit({
            "type": "conversation.item.input_audio_transcription.completed",
            "item_id": "u1", "transcript": "Search the weather",
        })
        await fake.emit({"type": "response.created", "response": {"id": "r1"}})
        await fake.emit({
            "type": "response.function_call_arguments.done",
            "call_id": "c1", "name": "search_web", "arguments": '{"query": "weather"}',
        })
        await fake.emit({"type": "response.done", "response": {"id": "r1", "status": "completed"}})
        output = await fake.wait_for("conversation.item.create")
        assert output["item"]["type"] == "function_call_output"
        assert gateway.calls == [("search_web", {"query": "weather"})]
        await fake.wait_for("response.create")
        # The server never had to be asked for the answer to the spoken turn.
        assert sum(e["type"] == "response.create" for e in fake.received) == 1

        await fake.emit({"type": "response.created", "response": {"id": "r2"}})
        await fake.emit({
            "type": "response.output_audio.delta",
            "delta": base64.b64encode(b"\x05\x00" * 4).decode(),
        })
        async with asyncio.timeout(2):
            await audio_played.wait()
        assert played[0] == b"\x05\x00" * 4
    finally:
        await session.end(reason="client_stop")
