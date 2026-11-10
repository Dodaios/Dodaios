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


# ------------------------------------------------------------- Grok Build
#
# Grok's stream-json has no task lines: its background work shows only as the
# tool result that started it and the words of a later one (grok 1.0.77).


def _grok_call(call_id: str, name: str, **args: Any) -> dict[str, Any]:
    return {
        "type": "assistant",
        "message": {
            "id": f"m-{call_id}",
            "content": [{"type": "tool_use", "id": call_id, "name": name, "input": args}],
        },
        "session_id": "g1",
    }


def _grok_result(call_id: str, text: str) -> dict[str, Any]:
    return {
        "type": "user",
        "message": {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": call_id, "content": text}],
        },
        "session_id": "g1",
    }


def _grok_state() -> _ClaudeState:
    return _ClaudeState(turn_id="t1", grok=True)


def test_grok_background_shell_monitor_and_subagent_are_open_tasks() -> None:
    st = _grok_state()
    lines = [
        _start("m1"),
        _grok_call("c1", "run_terminal_command", command="npm test", description="Run tests",
                   background=True),
        _grok_result("c1", "<task-id>01a0-b1</task-id>\n<task-type>bash</task-type>\n"),
        _grok_call("c2", "monitor", command="python watch.py", description="Watch CI"),
        _grok_result(
            "c2", "Monitor started (task 01a0-m1, timeout 36000000ms).\nYou will be notified."
        ),
        _grok_call("c3", "spawn_subagent", description="Review the diff", prompt="..."),
        _grok_result(
            "c3",
            "Subagent started in background.\nsubagent_id: 01a0-s1\ntype: code-reviewer\n"
            "description: Review the diff\n",
        ),
        _stop("end_turn"),
    ]
    assert _waits(lines, st) == [["Run tests", "Watch CI", "Review the diff"]]


def test_grok_task_end_reminders_close_tasks() -> None:
    st = _grok_state()
    lines = [
        _start("m1"),
        _grok_call("c1", "run_terminal_command", command="sleep 5", background=True),
        _grok_result("c1", "<task-id>01a0-b1</task-id>\n<task-type>bash</task-type>\n"),
        _grok_call("c2", "spawn_subagent", description="Run tests"),
        _grok_result("c2", "Subagent started in background.\nsubagent_id: 01a0-s1\n"),
        _stop("end_turn"),
        _start("m2"),
        _grok_call("c3", "run_terminal_command", command="git status"),
        _grok_result(
            "c3",
            "clean\n<system-reminder>\nBackground task \"01a0-b1\" completed (exit code: 0).\n"
            "</system-reminder>",
        ),
        _grok_call("c4", "get_command_or_subagent_output", task_ids=["01a0-s1"]),
        _grok_result(
            "c4", "=== Task 01a0-s1 ===\nCommand: [subagent] Run tests\nStatus: completed\n"
        ),
        _stop("end_turn"),
    ]
    assert _waits(lines, st) == [["sleep 5", "Run tests"], []]
    assert st.open_tasks == {}


def test_a_live_status_block_keeps_the_task_open() -> None:
    st = _grok_state()
    lines = [
        _grok_call("c1", "run_terminal_command", command="sleep 9", background=True),
        _grok_result("c1", "<task-id>01a0-b1</task-id>"),
        _grok_result("c2", "=== Task 01a0-b1 ===\nStatus: running\n"),
    ]
    _waits(lines, st)
    assert list(st.open_tasks) == ["01a0-b1"]


def test_grok_result_clears_whatever_is_left() -> None:
    """Grok prints its result only after every background task ended."""
    st = _grok_state()
    lines = [
        _grok_call("c1", "run_terminal_command", background=True),
        _grok_result("c1", "<task-id>01a0-b1</task-id>"),
        _stop("end_turn"),
        {"type": "result", "subtype": "success", "result": "Done.", "session_id": "g1"},
    ]
    assert _waits(lines, st) == [["background task"], []]
    assert st.open_tasks == {}


def test_claude_output_that_looks_like_grok_tasks_is_ignored() -> None:
    st = _ClaudeState(turn_id="t1")
    _waits([_grok_result("c1", "<task-id>x1</task-id>"), _stop("end_turn")], st)
    assert st.open_tasks == {}


def test_an_idle_grok_turn_without_named_tasks_gets_a_generic_wait() -> None:
    from dodaios.agent_chat.runner_cli import GROK_BACKGROUND_WORK, grok_idle_wait

    st = _grok_state()
    _waits([_start("m1"), _stop("end_turn")], st)
    events = grok_idle_wait(st)
    assert [e["payload"]["tasks"] for e in events] == [[GROK_BACKGROUND_WORK]]
    assert grok_idle_wait(st) == []  # said once
    # The agent wakes: the wait is taken back.
    assert _waits([_start("m2")], st) == [[]]


def test_no_generic_wait_for_claude_or_after_the_result() -> None:
    from dodaios.agent_chat.runner_cli import grok_idle_wait

    claude = _ClaudeState(turn_id="t1")
    _waits([_start("m1"), _stop("end_turn")], claude)
    assert grok_idle_wait(claude) == []
    st = _grok_state()
    _waits([_stop("end_turn"), {"type": "result", "result": "ok", "session_id": "g1"}], st)
    assert grok_idle_wait(st) == []


def test_a_file_that_mentions_a_task_id_opens_no_task() -> None:
    st = _grok_state()
    lines = [
        _grok_call("c1", "read_file", path="notes.md"),
        _grok_result("c1", "Example output: <task-id>01a0-x</task-id>"),
        _stop("end_turn"),
    ]
    assert _waits(lines, st) == []
    assert st.open_tasks == {}


def test_an_unknown_task_status_keeps_the_task_open() -> None:
    st = _ClaudeState(turn_id="t1")
    lines = [
        _task("task_started", "b1", task_type="local_bash", description="deploy"),
        _task("task_updated", "b1", patch={"status": "paused_for_input"}),
        _stop("end_turn"),
        _task("task_updated", "b1", patch={"status": "killed"}),
    ]
    assert _waits(lines, st) == [["deploy"], []]


def test_a_task_ending_after_the_result_means_the_agent_answers_again() -> None:
    from dodaios.agent_chat.runner_cli import _answer_settled

    st = _ClaudeState(turn_id="t1")
    result = {"type": "result", "subtype": "success", "result": "Started.", "session_id": "s1"}
    _waits([_task("task_started", "b1", task_type="local_bash", description="pytest"), result], st)
    assert not _answer_settled(st)  # a task is open
    _waits([_task("task_notification", "b1", status="completed")], st)
    assert not _answer_settled(st)  # Claude Code wakes with the task's outcome
    _waits([_start("m2")], st)
    assert not _answer_settled(st)  # it works on the late answer
    _waits([_stop("end_turn"), {**result, "result": "Tests pass."}], st)
    assert _answer_settled(st)


def test_grok_is_settled_on_its_result() -> None:
    from dodaios.agent_chat.runner_cli import _answer_settled

    st = _grok_state()
    _waits(
        [
            _start("m1"),
            _grok_call("c1", "monitor", description="Watch CI"),
            _grok_result("c1", "Monitor started (task 01a0-m1, timeout 1ms)."),
            _stop("end_turn"),
        ],
        st,
    )
    assert not _answer_settled(st)
    _waits([{"type": "result", "subtype": "success", "result": "Done.", "session_id": "g1"}], st)
    assert _answer_settled(st)
