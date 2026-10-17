"""ChatGPT web brain: conversation ids, route parsing, error typing, SSE."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from jarvis.plugins.brain import chatgpt_web
from jarvis.plugins.brain.chatgpt_web import (
    ChatGPTWebBrain,
    conversation_id,
    idempotency_key,
    parse_route_decision,
)
from jarvis.plugins.brain.chatgpt_web_bridge import ChatGPTWebError


def test_conversation_id_is_stable_and_namespaced() -> None:
    assert conversation_id("abc-1") == "dodaios:abc-1"
    assert conversation_id("abc-1") == conversation_id("abc-1")
    assert conversation_id("a b/c") == "dodaios:a-b-c"
    assert len(conversation_id("x" * 400)) == 128


def test_new_chats_get_distinct_ids() -> None:
    assert conversation_id(None) != conversation_id(None)


def test_idempotency_key_depends_on_turn_and_body() -> None:
    body = {"input": "hi"}
    assert idempotency_key("t1", body) == idempotency_key("t1", body)
    assert idempotency_key("t1", body) != idempotency_key("t2", body)
    assert 8 <= len(idempotency_key("t1", body)) <= 200


@pytest.mark.parametrize(
    "reply",
    [
        "plain prose",
        "{broken json",
        '{"route": "delegate", "target": "ollama", "task": "x"}',
        '{"route": "delegate", "target": "codex", "task": ""}',
        '{"route": "launch", "text": "x"}',
        "[1, 2]",
    ],
)
def test_invalid_route_falls_back_to_self_and_never_delegates(reply: str) -> None:
    decision = parse_route_decision(reply)
    assert decision.kind == "self"
    assert decision.text == reply


def test_valid_delegate_and_clarify() -> None:
    d = parse_route_decision(
        '```json\n{"route": "delegate", "target": "claude", "task": " fix "}\n```'
    )
    assert (d.kind, d.target, d.text) == ("delegate", "claude", "fix")
    c = parse_route_decision('{"route": "clarify", "text": "Which file?"}')
    assert (c.kind, c.text) == ("clarify", "Which file?")


def test_error_mapping() -> None:
    assert chatgpt_web._error_from_body(503, None).code == "login_required"
    rejected = chatgpt_web._error_from_body(401, {"error": {"code": "invalid_api_key"}})
    assert rejected.code == "bridge_unavailable"
    assert chatgpt_web._error_from_body(500, {}).code == "failed"


async def _collect(body: bytes) -> list:
    transport = httpx.MockTransport(lambda _req: httpx.Response(200, content=body))
    async with httpx.AsyncClient(transport=transport) as client:
        async with client.stream("POST", "http://127.0.0.1/v1/responses") as resp:
            return [d async for d in ChatGPTWebBrain()._events(resp)]


def test_sse_stream_yields_text_then_stop() -> None:
    body = (
        b"event: response.output_text.delta\n"
        b'data: {"type":"response.output_text.delta","delta":"Hel"}\n\n'
        b'data: {"type":"response.heartbeat"}\n\n'
        b'data: {"type":"response.output_text.delta","delta":"lo"}\n\n'
        b'data: {"type":"response.completed"}\n\n'
    )
    deltas = asyncio.run(_collect(body))
    assert "".join(d.content or "" for d in deltas) == "Hello"
    assert deltas[-1].finish_reason == "stop"


def test_sse_failure_is_typed() -> None:
    body = b'data: {"type":"response.failed","response":{"error":{"code":"boom"}}}\n\n'
    with pytest.raises(ChatGPTWebError) as info:
        asyncio.run(_collect(body))
    assert info.value.code == "failed"


def test_input_items_are_typed_messages() -> None:
    # The bridge only replays a turn whose latest user item is type "message".
    from jarvis.core.protocols import BrainMessage, BrainRequest

    req = BrainRequest(system="sys", messages=[BrainMessage(role="user", content="Hallo")])
    items = chatgpt_web._input_items(req)
    assert [i["type"] for i in items] == ["message", "message"]
    assert items[-1]["role"] == "user"


def test_sse_commentary_notes_are_not_shown() -> None:
    body = (
        b'data: {"type":"response.output_item.added","item":'
        b'{"type":"message","id":"msg_c","phase":"commentary"}}\n\n'
        b'data: {"type":"response.output_text.delta","item_id":"msg_c","delta":"note"}\n\n'
        b'data: {"type":"response.output_item.added","item":'
        b'{"type":"message","id":"msg_a","phase":"final_answer"}}\n\n'
        b'data: {"type":"response.output_text.delta","item_id":"msg_a","delta":"Hallo"}\n\n'
        b'data: {"type":"response.completed"}\n\n'
    )
    deltas = asyncio.run(_collect(body))
    assert "".join(d.content or "" for d in deltas) == "Hallo"
