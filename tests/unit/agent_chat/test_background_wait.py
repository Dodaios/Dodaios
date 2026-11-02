"""A Claude Code turn that ended its message but still runs background tasks.

The CLI stays alive and wakes the agent again once its background shells or
agents finish. Until then the answer reads finished while the turn is not, so
the translator says what the turn waits for (``background_wait``).
"""

from __future__ import annotations

from typing import Any

from dodaios.agent_chat.runner_cli import _ClaudeState, translate_claude_line


def _stream(event: dict[str, Any]) -> dict[str, Any]:
    return {"type": "stream_event", "event": event, "session_id": "s1"}


def _start(mid: str) -> dict[str, Any]:
    return _stream({"type": "message_start", "message": {"id": mid}})


def _stop(reason: str) -> dict[str, Any]:
    return _stream({"type": "message_delta", "delta": {"stop_reason": reason}, "usage": {}})


def _task(subtype: str, task_id: str, **extra: Any) -> dict[str, Any]:
    return {"type": "system", "subtype": subtype, "task_id": task_id, **extra}


def _waits(lines: list[dict[str, Any]], st: _ClaudeState | None = None) -> list[list[str]]:
    st = st or _ClaudeState(turn_id="t1")
    return [
        ev["payload"]["tasks"]
        for line in lines
        for ev in translate_claude_line(line, st)
        if ev["kind"] == "background_wait"
    ]


def test_an_ended_message_with_open_shells_waits_on_them() -> None:
    lines = [
        _start("m1"),
        _task("task_started", "b1", task_type="local_bash", description="Run the full test suite"),
        _task("task_started", "b2", task_type="local_bash", description="git push\nmore"),
        _stop("tool_use"),
        _start("m2"),
        _stop("end_turn"),
        _task("task_notification", "b2", status="completed"),
        _task("task_notification", "b1", status="completed"),
        _start("m3"),
        _stop("end_turn"),
    ]
    assert _waits(lines) == [
        ["Run the full test suite", "git push"],
        ["Run the full test suite"],
        [],
    ]


def test_the_agent_waking_up_clears_the_wait() -> None:
    lines = [
        _start("m1"),
        _task("task_started", "b1", task_type="local_bash", description="sleep 600"),
        _stop("end_turn"),
        _start("m2"),
    ]
    assert _waits(lines) == [["sleep 600"], []]


def test_a_result_line_with_open_tasks_waits_too() -> None:
    lines = [
        _task("task_started", "b1", task_type="local_bash", description="pytest"),
        {"type": "result", "subtype": "success", "result": "Done.", "session_id": "s1"},
    ]
    assert _waits(lines) == [["pytest"]]


def test_no_wait_without_open_tasks_or_while_the_agent_works() -> None:
    lines = [
        _start("m1"),
        _task("task_started", "b1", task_type="local_bash", description="sleep 8"),
        _stop("tool_use"),
        _task("task_notification", "b1", status="completed"),
        _start("m2"),
        _stop("end_turn"),
        {"type": "result", "subtype": "success", "result": "Done.", "session_id": "s1"},
    ]
    assert _waits(lines) == []


def test_a_task_patched_to_a_final_status_is_no_longer_open() -> None:
    lines = [
        _task("task_started", "a1", task_type="local_agent", description="Review the diff",
              tool_use_id="toolu_a", subagent_type="general-purpose", is_backgrounded=True),
        _task("task_updated", "a1", patch={"status": "running"}),
        _stop("end_turn"),
        _task("task_updated", "a1", patch={"status": "completed"}),
    ]
    assert _waits(lines) == [["Review the diff"], []]
