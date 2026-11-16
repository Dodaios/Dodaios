"""A round that only thought must not end the turn empty (Ollama, Qwen 3.5).

Live 2026-11-16: the lead conversation on ``qwen3.5:9b`` read four meeting
notes, then Ollama's ``/v1`` stream put the model's whole final answer into
``delta.reasoning``. ``content`` stayed empty, no tool call came, the finish
was ``stop``. The streamer never reads reasoning, so the turn ended with
nothing and the chat showed "Finished without an answer". The same request
with ``reasoning_effort="none"`` wrote the file and answered.

These tests run the real ``OllamaBrain.complete`` over the real
OpenAI-compatible streamer with a fake SDK client, and the real tool loop on
top, so the retried round is proven to reach the executor.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from dodaios.brain import stream_markup
from dodaios.brain.tool_use_loop import ToolUseLoop
from dodaios.core.protocols import BrainDelta, BrainMessage, BrainRequest, ToolResult
from dodaios.plugins.brain import _openai_base
from dodaios.plugins.brain import ollama as plugin
from dodaios.plugins.brain.ollama import OllamaBrain

_ANSWER = "Your action items, sorted by due date:\n\n1. Nov 16: approve the onboarding email"


@pytest.fixture(autouse=True)
def _offline_brain(monkeypatch):
    stream_markup.reset_think_habits()
    monkeypatch.setattr(_openai_base, "_TOOLS_REFUSED_CACHE", set())
    monkeypatch.setattr(_openai_base, "_PARAM_ADAPTATION_CACHE", {})

    async def _model(self: OllamaBrain, **_: Any) -> str:
        return "qwen3.5:9b"

    async def _prepared(self: OllamaBrain, model: str, req: BrainRequest) -> Any:
        return plugin._PreparedCall(
            run_model="qwen3.5-9b-jarvis-ca776b6b", req=req, planned=None, confirmed=False
        )

    async def _nothing(self: OllamaBrain, *args: Any) -> None:
        return None

    monkeypatch.setattr(OllamaBrain, "_resolve_model", _model)
    monkeypatch.setattr(OllamaBrain, "_prepare_call", _prepared)
    monkeypatch.setattr(OllamaBrain, "_verify_running_context", _nothing)
    monkeypatch.setattr(OllamaBrain, "_effective_window", lambda self, call, root: None)
    monkeypatch.setattr(OllamaBrain, "_judge_reported_prompt", lambda self, *a: None)
    monkeypatch.setattr(OllamaBrain, "_model_options", lambda self, model: None)
    yield
    stream_markup.reset_think_habits()


def _chunk(
    content: str | None = "",
    *,
    reasoning: str | None = None,
    finish: str | None = None,
    tool_calls: list[Any] | None = None,
) -> Any:
    delta = SimpleNamespace(content=content, reasoning=reasoning, tool_calls=tool_calls)
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=delta, finish_reason=finish)], usage=None
    )


def _usage(prompt: int, completion: int) -> Any:
    return SimpleNamespace(
        choices=[],
        usage=SimpleNamespace(
            prompt_tokens=prompt, completion_tokens=completion, prompt_tokens_details=None
        ),
    )


def _write_call() -> Any:
    fn = SimpleNamespace(name="Write", arguments='{"path": "todo.md", "content": "- [ ] email"}')
    return [SimpleNamespace(index=0, id="call_w", function=fn)]


def _reasoning_only_round() -> list[Any]:
    """What Ollama streamed in the live repro (``019_resp.txt``), shortened."""
    return [
        _chunk(reasoning="Your action items,"),
        _chunk(reasoning=" sorted by due date:\n\n1. Nov 16: approve the onboarding email"),
        _chunk(None, finish="stop"),
        _usage(24313, 132),
    ]


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
    base_url = "http://127.0.0.1:11434/v1/"

    def __init__(self, rounds: list[list[Any]]) -> None:
        self.calls: list[dict[str, Any]] = []
        self._rounds = list(rounds)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs: Any) -> _Stream:
        self.calls.append(kwargs)
        return _Stream(self._rounds.pop(0) if self._rounds else [])


def _brain(client: _Client) -> OllamaBrain:
    brain = OllamaBrain(model="qwen3.5:9b")
    brain._client = client
    return brain


def _req(**kwargs: Any) -> BrainRequest:
    return BrainRequest(
        messages=(BrainMessage(role="user", content="write my todo.md"),), **kwargs
    )


async def _collect(brain: OllamaBrain, req: BrainRequest) -> list[BrainDelta]:
    return [delta async for delta in brain.complete(req)]


async def test_a_reasoning_only_round_is_asked_again_without_thinking() -> None:
    client = _Client([
        _reasoning_only_round(),
        [_chunk("Done, todo.md is written."), _chunk(None, finish="stop"), _usage(24313, 20)],
    ])
    deltas = await _collect(_brain(client), _req())

    assert [call.get("reasoning_effort") for call in client.calls] == [None, "none"]
    assert "".join(d.content or "" for d in deltas) == "Done, todo.md is written."
    assert [d.finish_reason for d in deltas if d.finish_reason] == ["stop"]
    # Both rounds were really run, so both are counted.
    assert sum((d.usage or {}).get("output_tokens", 0) for d in deltas) == 152


async def test_the_thoughts_stand_in_when_the_second_round_is_empty_too() -> None:
    client = _Client([_reasoning_only_round(), [_chunk(None, finish="stop")]])
    deltas = await _collect(_brain(client), _req())

    assert len(client.calls) == 2
    assert "".join(d.content or "" for d in deltas) == _ANSWER
    assert deltas[-1].finish_reason == "stop"


async def test_a_round_that_answers_is_never_asked_twice() -> None:
    client = _Client([[
        _chunk(reasoning="the user wants a greeting"),
        _chunk("Hello!"),
        _chunk(None, finish="stop"),
    ]])
    deltas = await _collect(_brain(client), _req())

    assert len(client.calls) == 1
    assert "".join(d.content or "" for d in deltas) == "Hello!"


async def test_thinking_already_off_is_not_retried() -> None:
    client = _Client([_reasoning_only_round()])
    deltas = await _collect(_brain(client), _req(reasoning_effort="none"))

    assert len(client.calls) == 1
    assert [d.finish_reason for d in deltas if d.finish_reason] == ["stop"]


class _Write:
    name = "Write"
    description = "Write a file."
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
    }


class _Executor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, tool: Any, args: dict[str, Any], **_: Any) -> ToolResult:
        self.calls.append((tool.name, args))
        return ToolResult(success=True, output="Wrote todo.md")


async def test_the_tool_call_of_the_retried_round_runs_and_the_turn_answers() -> None:
    client = _Client([
        _reasoning_only_round(),
        [_chunk(None, tool_calls=_write_call()), _chunk(None, finish="tool_calls")],
        [_chunk("todo.md is written, five items."), _chunk(None, finish="stop")],
    ])
    executor = _Executor()
    loop = ToolUseLoop(_brain(client), {"Write": _Write()}, executor)  # type: ignore[arg-type]

    result = await loop.run([], user_utterance="write my todo.md")

    assert executor.calls == [("Write", {"path": "todo.md", "content": "- [ ] email"})]
    assert result.text == "todo.md is written, five items."
