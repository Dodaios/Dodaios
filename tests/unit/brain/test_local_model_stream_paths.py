"""Local models end to end through the OpenAI-compatible streamer.

A user running Dodaios on local models only (a Qwen-based coder via Ollama /
LM Studio / llama.cpp) hit three failures at once:

1. Tool calls the server returned as ``<tool_call>`` text never ran — the
   person got an empty reply.
2. ``<think>`` reasoning was shown in the chat and read aloud.
3. A server started without tool support (llama.cpp without ``--jinja``,
   vLLM without ``--enable-auto-tool-choice``) failed every turn.

These tests drive the real ``stream_complete`` with a fake SDK client, and the
real ``ToolUseLoop`` on top of it, so the recovered call is proven to EXECUTE.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest

from dodaios.agent_runtimes.provider_errors import classify
from dodaios.brain import stream_markup
from dodaios.brain.tool_use_loop import ToolUseLoop
from dodaios.brain.tools_rejection import tools_rejection_hint
from dodaios.core.protocols import BrainDelta, BrainMessage, BrainRequest, ToolResult
from dodaios.plugins.brain import _openai_base
from dodaios.plugins.brain._openai_base import stream_complete

_LLAMA_CPP_NO_JINJA = "Error code: 500 - {'error': {'code': 500, 'message': 'tools param requires --jinja flag', 'type': 'server_error'}}"  # noqa: E501
_VLLM_NO_AUTO = (
    "Error code: 400 - {'object': 'error', 'message': '\"auto\" tool choice requires "
    "--enable-auto-tool-choice and --tool-call-parser to be set', 'type': 'BadRequestError'}"
)
_OLLAMA_NO_TOOLS = (
    "Error code: 400 - {'error': {'message': 'registry.ollama.ai/library/gemma3:4b does "
    "not support tools', 'type': 'api_error'}}"
)


@pytest.fixture(autouse=True)
def _fresh_process_state(monkeypatch):
    stream_markup.reset_think_habits()
    monkeypatch.setattr(_openai_base, "_TOOLS_REFUSED_CACHE", set())
    monkeypatch.setattr(_openai_base, "_PARAM_ADAPTATION_CACHE", {})
    yield
    stream_markup.reset_think_habits()


def _chunk(content: str | None = None, *, finish: str | None = None,
           tool_calls: list[Any] | None = None, **extra: Any) -> Any:
    delta = SimpleNamespace(content=content, tool_calls=tool_calls, **extra)
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=delta, finish_reason=finish)], usage=None
    )


def _fragment(*, index: Any = None, call_id: str | None = None, name: str | None = None,
              arguments: str | None = None) -> Any:
    return SimpleNamespace(
        index=index, id=call_id, function=SimpleNamespace(name=name, arguments=arguments)
    )


class _Stream:
    def __init__(self, chunks: list[Any]) -> None:
        self._chunks = list(chunks)

    def __aiter__(self) -> _Stream:
        return self

    async def __anext__(self) -> Any:
        if not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop(0)


class _Client:
    """``client.chat.completions.create`` raising queued errors, then streaming."""

    base_url = "http://localhost:8080/v1/"

    def __init__(self, rounds: list[list[Any]], errors: list[Exception] | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._rounds = list(rounds)
        self._errors = list(errors or [])
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs: Any) -> _Stream:
        self.calls.append(kwargs)
        if self._errors:
            raise self._errors.pop(0)
        return _Stream(self._rounds.pop(0) if self._rounds else [])


_OPEN_APP = {
    "name": "open_app",
    "description": "Open an application.",
    "input_schema": {"type": "object", "properties": {"app": {"type": "string"}}},
}


def _req(tools: tuple[dict[str, Any], ...] = (_OPEN_APP,)) -> BrainRequest:
    return BrainRequest(messages=(BrainMessage(role="user", content="open spotify"),),
                        tools=tools)


async def _collect(client: _Client, req: BrainRequest | None = None, **kw: Any) -> list[BrainDelta]:
    return [d async for d in stream_complete(client, "qwen", req or _req(), **kw)]


def _text(deltas: list[BrainDelta]) -> str:
    return "".join(d.content or "" for d in deltas)


def _calls(deltas: list[BrainDelta]) -> list[dict[str, Any]]:
    return [d.tool_call for d in deltas if d.tool_call]


# ── 1. text-format tool calls become real calls ─────────────────────────────


async def test_qwen_tool_call_text_becomes_a_structured_call() -> None:
    client = _Client([[
        _chunk("<think>The user wants Spotify.</think>\n"),
        _chunk('<tool_call>\n{"name": "open_app", "arguments": '),
        _chunk('"{\\"app\\": \\"spotify\\"}"}\n</tool_call>'),
        _chunk(finish="stop"),
    ]])
    deltas = await _collect(client)
    assert _text(deltas) == ""
    assert [(c["name"], c["input"]) for c in _calls(deltas)] == [("open_app", {"app": "spotify"})]
    assert deltas[-1].finish_reason == "tool_calls"


async def test_unknown_tool_in_text_never_becomes_a_call() -> None:
    client = _Client([[
        _chunk('<tool_call>{"name": "format_disk", "arguments": {}}</tool_call>'),
        _chunk(finish="stop"),
    ]])
    deltas = await _collect(client)
    assert _calls(deltas) == []
    assert deltas[-1].finish_reason == "stop"


class _Executor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, tool: Any, args: dict[str, Any], **_: Any) -> ToolResult:
        self.calls.append((tool.name, args))
        return ToolResult(success=True, output="Spotify is open.")


class _OpenApp:
    name = "open_app"
    description = "Open an application."
    schema: dict[str, Any] = {"type": "object", "properties": {"app": {"type": "string"}}}


class _StreamerBrain:
    """A brain whose rounds run through the real OpenAI-compatible streamer."""

    def __init__(self, client: _Client) -> None:
        self._client = client

    async def complete(self, req: BrainRequest) -> AsyncIterator[BrainDelta]:
        async for delta in stream_complete(
            self._client, "qwen", req, tools_fallback=True, hold_think_prefix=True
        ):
            yield delta


async def test_recovered_call_is_executed_by_the_tool_loop() -> None:
    client = _Client([
        [
            _chunk("Okay, Spotify.</think>"),
            _chunk('<tool_call>{"name": "open_app", "arguments": {"app": "spotify"}}'),
            _chunk("</tool_call>", finish="stop"),
        ],
        [_chunk("<think>done</think>Spotify is open now.", finish="stop")],
    ])
    executor = _Executor()
    loop = ToolUseLoop(_StreamerBrain(client), {"open_app": _OpenApp()}, executor)  # type: ignore[arg-type]

    result = await loop.run([], user_utterance="open spotify")

    assert executor.calls == [("open_app", {"app": "spotify"})]
    assert result.text == "Spotify is open now."
    assert "<" not in result.text


class _RawTextBrain:
    """A transport that hands raw template text through (no streamer filter)."""

    def __init__(self) -> None:
        self.rounds = 0

    async def complete(self, req: BrainRequest) -> AsyncIterator[BrainDelta]:
        self.rounds += 1
        if self.rounds == 1:
            yield BrainDelta(
                content='[TOOL_CALLS][{"name": "open_app", "arguments": {"app": "x"}}]'
            )
        else:
            yield BrainDelta(content="Done.")
        yield BrainDelta(finish_reason="stop")


async def test_loop_recovers_mistral_text_from_any_transport() -> None:
    executor = _Executor()
    loop = ToolUseLoop(_RawTextBrain(), {"open_app": _OpenApp()}, executor)  # type: ignore[arg-type]
    result = await loop.run([], user_utterance="open x")
    assert executor.calls == [("open_app", {"app": "x"})]
    assert result.text == "Done."


# ── 2. reasoning is never streamed ──────────────────────────────────────────


async def test_reasoning_fields_and_think_blocks_never_reach_the_caller() -> None:
    client = _Client([[
        _chunk(None, reasoning_content="private thought"),
        _chunk(None, reasoning="more private thought"),
        _chunk("<thi"),
        _chunk("nk>inline thought</th"),
        _chunk("ink>\n\nHello!"),
        _chunk(finish="stop"),
    ]])
    assert _text(await _collect(client, _req(tools=()))) == "Hello!"


# ── stream ends without finish_reason; fragments without an index ──────────


async def test_tool_fragments_are_finalized_when_the_stream_just_ends() -> None:
    client = _Client([[
        _chunk(tool_calls=[_fragment(index=0, call_id="c1", name="open_app", arguments='{"app"')]),
        _chunk(tool_calls=[_fragment(index=0, arguments=': "spotify"}')]),
    ]])
    deltas = await _collect(client)
    assert _calls(deltas) == [{"id": "c1", "name": "open_app", "input": {"app": "spotify"}}]
    assert deltas[-1].finish_reason == "tool_calls"


async def test_fragments_without_index_are_keyed_by_id() -> None:
    client = _Client([[
        _chunk(tool_calls=[_fragment(call_id="a", name="open_app", arguments='{"app": ')]),
        _chunk(tool_calls=[_fragment(arguments='"one"}')]),
        _chunk(tool_calls=[_fragment(call_id="b", name="open_app", arguments='{"app": "two"}')]),
        _chunk(finish="tool_calls"),
    ]])
    calls = _calls(await _collect(client))
    assert [(c["id"], c["input"]) for c in calls] == [("a", {"app": "one"}), ("b", {"app": "two"})]


async def test_a_stream_cut_inside_arguments_runs_nothing() -> None:
    client = _Client([[
        _chunk(tool_calls=[
            _fragment(index=0, call_id="c1", name="open_app", arguments='{"app": "sp'),
        ]),
    ]])
    deltas = await _collect(client)
    assert _calls(deltas) == []
    assert deltas[-1].finish_reason == "length"


async def test_held_back_partial_tag_is_flushed_when_the_stream_just_ends() -> None:
    client = _Client([[_chunk("a < b and c <")]])
    assert _text(await _collect(client, _req(tools=()))) == "a < b and c <"


# ── 3. servers that refuse tools ────────────────────────────────────────────


@pytest.mark.parametrize(
    ("error", "flag"),
    [
        (_LLAMA_CPP_NO_JINJA, "--jinja"),
        (_VLLM_NO_AUTO, "--enable-auto-tool-choice"),
        (_OLLAMA_NO_TOOLS, "tool support"),
    ],
)
async def test_a_tools_refusal_is_retried_once_without_tools(
    error: str, flag: str, caplog: pytest.LogCaptureFixture
) -> None:
    client = _Client([[_chunk("Hi.", finish="stop")], [_chunk("Again.", finish="stop")]],
                     errors=[RuntimeError(error)])
    with caplog.at_level(logging.WARNING):
        deltas = await _collect(client, tools_fallback=True)
    assert _text(deltas) == "Hi."
    assert "tools" in client.calls[0] and "tools" not in client.calls[1]
    assert flag in caplog.text
    # Remembered: the next turn does not pay the refusal again.
    await _collect(client, tools_fallback=True)
    assert len(client.calls) == 3 and "tools" not in client.calls[2]


async def test_cloud_callers_keep_the_refusal() -> None:
    client = _Client([[_chunk("Hi.", finish="stop")]], errors=[RuntimeError(_LLAMA_CPP_NO_JINJA)])
    with pytest.raises(RuntimeError, match="--jinja"):
        await _collect(client)


async def test_other_errors_are_not_mistaken_for_a_tools_refusal() -> None:
    client = _Client([[_chunk("Hi.", finish="stop")]], errors=[RuntimeError("model crashed")])
    with pytest.raises(RuntimeError, match="model crashed"):
        await _collect(client, tools_fallback=True)
    assert len(client.calls) == 1


class _StatusError(Exception):
    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.status_code = status


@pytest.mark.parametrize(
    ("error", "status"),
    [(_LLAMA_CPP_NO_JINJA, 500), (_VLLM_NO_AUTO, 400), (_OLLAMA_NO_TOOLS, 400)],
)
def test_agent_gateway_explains_the_refusal_with_the_server_flag(error: str, status: int) -> None:
    refusal = classify("local-openai", _StatusError(error, status), "qwen")
    assert refusal is not None and refusal.code == "tools_unsupported"
    assert tools_rejection_hint(error) in refusal.message


def test_hint_names_the_flag() -> None:
    assert "--jinja" in (tools_rejection_hint(_LLAMA_CPP_NO_JINJA) or "")
    assert "--enable-auto-tool-choice" in (tools_rejection_hint(_VLLM_NO_AUTO) or "")
    assert tools_rejection_hint("Error code: 400 - context length exceeded") is None
