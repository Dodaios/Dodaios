"""Independent reads of one round run together; actions keep model order."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest

from dodaios.brain.tool_use_loop import ToolUseLoop
from dodaios.core.protocols import BrainDelta, BrainRequest, ToolResult


class _Read:
    risk_tier = "safe"
    read_only = True
    schema: dict[str, Any] = {}

    def __init__(self, name: str) -> None:
        self.name = name


class _Action:
    risk_tier = "safe"
    schema: dict[str, Any] = {}

    def __init__(self, name: str) -> None:
        self.name = name
        self.is_action_tool = True


class _Executor:
    """Records start/finish order; each tool waits for ``gates[name]`` if set."""

    def __init__(self, delays: dict[str, float]) -> None:
        self.delays = delays
        self.events: list[str] = []
        self.running = 0
        self.peak = 0

    async def execute(self, tool: Any, args: dict[str, Any], **_: Any) -> ToolResult:
        self.events.append(f"start:{tool.name}")
        self.running += 1
        self.peak = max(self.peak, self.running)
        await asyncio.sleep(self.delays.get(tool.name, 0.0))
        self.running -= 1
        self.events.append(f"end:{tool.name}")
        return ToolResult(success=True, output={"who": tool.name})


class _Brain:
    def __init__(self, names: list[str]) -> None:
        self.names = names
        self.requests: list[BrainRequest] = []

    async def complete(self, req: BrainRequest) -> AsyncIterator[BrainDelta]:
        self.requests.append(req)
        if len(self.requests) == 1:
            for i, name in enumerate(self.names):
                yield BrainDelta(tool_call={"id": f"c{i}", "name": name, "input": {"n": i}})
            yield BrainDelta(finish_reason="tool_use")
            return
        yield BrainDelta(content="done")
        yield BrainDelta(finish_reason="stop")


def _result_ids(brain: _Brain) -> list[str]:
    return [
        m.tool_call_id
        for m in brain.requests[1].messages
        if getattr(m, "role", None) == "tool"
    ]


@pytest.mark.asyncio
async def test_reads_overlap_and_results_keep_call_order() -> None:
    names = ["read_a", "read_b", "read_c"]
    # The first read is the slowest: it must not make the others wait.
    executor = _Executor({"read_a": 0.15, "read_b": 0.05, "read_c": 0.01})
    brain = _Brain(names)
    loop = ToolUseLoop(brain, {n: _Read(n) for n in names}, executor)  # type: ignore[arg-type]

    await loop.run([], user_utterance="status please")

    assert executor.peak == 3
    assert _result_ids(brain) == ["c0", "c1", "c2"]


@pytest.mark.asyncio
async def test_action_is_never_overlapped_and_later_reads_wait_for_it() -> None:
    names = ["read_a", "read_b", "do_it", "read_c", "read_d"]
    tools: dict[str, Any] = {n: _Read(n) for n in names}
    tools["do_it"] = _Action("do_it")
    executor = _Executor({"read_a": 0.05, "read_b": 0.05, "do_it": 0.03})
    brain = _Brain(names)
    loop = ToolUseLoop(brain, tools, executor)  # type: ignore[arg-type]

    await loop.run([], user_utterance="status please")

    ev = executor.events
    # Reads before the action finish before it starts ...
    assert ev.index("end:read_a") < ev.index("start:do_it")
    assert ev.index("end:read_b") < ev.index("start:do_it")
    # ... and reads after it start only once it is done.
    assert ev.index("end:do_it") < ev.index("start:read_c")
    assert ev.index("end:do_it") < ev.index("start:read_d")
    assert _result_ids(brain) == ["c0", "c1", "c2", "c3", "c4"]


@pytest.mark.asyncio
async def test_a_single_read_takes_the_plain_path() -> None:
    executor = _Executor({})
    brain = _Brain(["read_a"])
    loop = ToolUseLoop(brain, {"read_a": _Read("read_a")}, executor)  # type: ignore[arg-type]

    await loop.run([], user_utterance="status please")

    assert executor.events == ["start:read_a", "end:read_a"]


@pytest.mark.asyncio
async def test_a_hung_read_is_abandoned_without_holding_the_round(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import dodaios.brain.tool_use_loop as mod

    monkeypatch.setattr(mod, "_PARALLEL_READ_TIMEOUT_S", 0.05)
    executor = _Executor({"read_a": 5.0})
    brain = _Brain(["read_a", "read_b"])
    loop = ToolUseLoop(
        brain, {"read_a": _Read("read_a"), "read_b": _Read("read_b")}, executor  # type: ignore[arg-type]
    )

    await loop.run([], user_utterance="status please")

    payloads = [
        m.content[0]["content"]
        for m in brain.requests[1].messages
        if getattr(m, "role", None) == "tool"
    ]
    assert "abandoned" in payloads[0]
    assert '"who":"read_b"' in payloads[1]
