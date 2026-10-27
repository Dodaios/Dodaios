"""A runtime's own failure notice ends the turn as an error, never as the answer.

Live 2026-10-27: OpenClaw refused a thinking level and posted the refusal as
the assistant's reply ("Thinking level "medium" is not supported for
jarvis/gpt-6-luna. Use one of: off, ultra."); the chat showed it as an
ordinary answer bubble.
"""

from __future__ import annotations

import asyncio
from typing import Any

from dodaios.agent_runtimes.acp import AcpTurn
from dodaios.agent_runtimes.openclaw import FAILURE_REPLIES

_REFUSAL = (
    'Thinking level "medium" is not supported for jarvis/gpt-6-luna. Use one of: off, ultra.'
)


class _IO:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def write(self, frame: dict[str, Any]) -> None:
        pass

    async def emit(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    async def ask(self, call_id: str, name: str, args: dict[str, Any], summary: str) -> str:
        return "deny"


def _chunk(text: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "method": "session/update",
        "params": {
            "sessionId": "s",
            "update": {
                "sessionUpdate": "agent_message_chunk",
                "content": {"type": "text", "text": text},
            },
        },
    }


_RESULT = {"jsonrpc": "2.0", "id": 3, "result": {"stopReason": "end_turn"}}


def _run(*texts: str, patterns=FAILURE_REPLIES) -> tuple[AcpTurn, _IO]:
    turn = AcpTurn(turn_id="t", cwd=".", prompt_text="hi", failure_replies=patterns)
    io = _IO()

    async def go() -> None:
        for text in texts:
            await turn.on_message(_chunk(text), io)
        await turn.on_message(_RESULT, io)

    asyncio.run(go())
    return turn, io


def _texts(io: _IO) -> list[str]:
    return [
        str(e["payload"].get("text", ""))
        for e in io.events
        if e.get("kind") in {"text_delta", "assistant_text"}
    ]


def test_an_unsupported_thinking_level_reply_is_the_turns_error():
    turn, io = _run(_REFUSAL)
    assert turn.status == "error"
    assert turn.error == _REFUSAL
    assert not turn.emitted_text
    assert _texts(io) == []


def test_an_interruption_notice_is_an_error_and_keeps_the_partial_answer():
    turn, io = _run("Half an answer", "[OpenClaw interruption] The Gateway disconnected.")
    assert turn.status == "error"
    assert turn.error == "The Gateway disconnected."
    assert any("Half an answer" in text for text in _texts(io))
    assert not any("interruption" in text for text in _texts(io))


def test_an_answer_that_merely_mentions_thinking_levels_stays_an_answer():
    answer = 'You asked about the "medium" thinking level: it is supported here.'
    turn, io = _run(answer)
    assert turn.status == "done"
    assert turn.emitted_text


def test_a_runtime_without_failure_replies_shows_every_text():
    turn, io = _run(_REFUSAL, patterns=())
    assert turn.status == "done"
    assert turn.emitted_text


def test_a_failure_notice_split_over_chunks_never_leaks_into_the_answer():
    turn, io = _run("[OpenClaw interruption] The Gateway", " disconnected.")
    assert turn.status == "error"
    assert turn.error == "The Gateway disconnected."
    assert _texts(io) == []
