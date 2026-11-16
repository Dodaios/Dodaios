"""Parallel calls of one tool show their own results in the chat trace.

Live 2026-11-16: the lead read four meeting notes with four parallel ``Read``
calls. They finished out of order, and the step mirror paired each
``ActionExecuted`` with the oldest open ``Read`` row, so the design-review
row showed the call-with-lena file. The executor now gives each call an id
that its ``ActionProposed`` and its result share, and the mirror pairs on it.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from dodaios.agent_chat import runner_brain
from dodaios.core.bus import EventBus
from dodaios.core.config import SafetyConfig
from dodaios.core.events import ActionDenied, ActionExecuted, ActionProposed
from dodaios.core.protocols import ExecutionContext, ToolResult
from dodaios.safety.approval import ApprovalWorkflow
from dodaios.safety.risk_tier import RiskTierEvaluator
from dodaios.safety.tool_executor import ToolExecutor

#: Each file answers after its own delay: the first asked is the last done.
_DELAYS = {"weekly-sync.md": 0.08, "design-review.md": 0.06, "call-with-lena.md": 0.04,
           "standup.md": 0.02}


class _Read:
    name = "Read"
    risk_tier = "safe"
    schema: dict[str, Any] = {}

    async def execute(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        path = args["file_path"]
        await asyncio.sleep(_DELAYS[path])
        return ToolResult(success=True, output=f"contents of {path}")


def _mirror(bus: EventBus, trace: Any) -> tuple[runner_brain._StepMirror, list[tuple[str, dict]]]:
    rows: list[tuple[str, dict[str, Any]]] = []

    async def emit(kind: str, payload: dict[str, Any]) -> None:
        rows.append((kind, payload))

    return runner_brain._StepMirror(emit, "turn-1", bus, trace), rows


def _results_by_input(rows: list[tuple[str, dict[str, Any]]]) -> dict[str, str]:
    inputs = {p["call_id"]: p["input"]["file_path"] for k, p in rows if k == "tool_call"}
    return {inputs[p["call_id"]]: p["output"] for k, p in rows if k == "tool_result"}


async def test_parallel_reads_finishing_out_of_order_keep_their_own_results() -> None:
    bus = EventBus()
    trace = uuid4()
    mirror, rows = _mirror(bus, trace)
    mirror.start()
    executor = ToolExecutor(
        bus=bus, evaluator=RiskTierEvaluator(SafetyConfig()), approval=ApprovalWorkflow(bus)
    )
    await asyncio.gather(*(
        executor.execute(_Read(), {"file_path": path}, trace_id=trace) for path in _DELAYS
    ))
    await asyncio.sleep(0)
    mirror.stop()

    assert _results_by_input(rows) == {path: f"contents of {path}" for path in _DELAYS}


async def test_the_executor_names_each_call_on_its_proposal_and_its_result() -> None:
    bus = EventBus()
    proposed: list[ActionProposed] = []
    executed: list[ActionExecuted] = []

    async def _proposed(event: ActionProposed) -> None:
        proposed.append(event)

    async def _executed(event: ActionExecuted) -> None:
        executed.append(event)

    bus.subscribe(ActionProposed, _proposed)  # type: ignore[arg-type]
    bus.subscribe(ActionExecuted, _executed)  # type: ignore[arg-type]
    executor = ToolExecutor(
        bus=bus, evaluator=RiskTierEvaluator(SafetyConfig()), approval=ApprovalWorkflow(bus)
    )
    trace = uuid4()
    await executor.execute(_Read(), {"file_path": "standup.md"}, trace_id=trace)
    await executor.execute(_Read(), {"file_path": "standup.md"}, trace_id=trace)
    await asyncio.sleep(0)

    assert [e.call_id for e in proposed] == [e.call_id for e in executed]
    assert all(proposed[i].call_id for i in range(2))
    assert proposed[0].call_id != proposed[1].call_id


async def test_events_without_a_call_id_still_pair_by_tool_name() -> None:
    bus = EventBus()
    trace = uuid4()
    mirror, rows = _mirror(bus, trace)
    mirror.start()
    await bus.publish(ActionProposed(trace_id=trace, tool_name="Read", args={"file_path": "a"}))
    await bus.publish(ActionProposed(trace_id=trace, tool_name="Grep", args={"file_path": "b"}))
    await bus.publish(ActionExecuted(trace_id=trace, tool_name="Grep", success=True,
                                     output_preview="from grep"))
    await bus.publish(ActionDenied(trace_id=trace, tool_name="Read", reason="no"))
    await asyncio.sleep(0)
    mirror.stop()

    assert _results_by_input(rows) == {"a": "no", "b": "from grep"}


async def test_a_result_with_an_id_never_takes_another_calls_row() -> None:
    bus = EventBus()
    trace = uuid4()
    mirror, rows = _mirror(bus, trace)
    mirror.start()
    await bus.publish(ActionProposed(trace_id=trace, tool_name="Read", args={"file_path": "a"},
                                     call_id="c-a"))
    await bus.publish(ActionExecuted(trace_id=trace, tool_name="Read", success=True,
                                     output_preview="from b", call_id="c-b"))
    await asyncio.sleep(0)
    mirror.stop()

    assert [k for k, _ in rows] == ["tool_call"]
