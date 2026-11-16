"""A coding agent's own to-do list reaches the thread as list calls.

The thread draws the list as a checklist from the calls' inputs
(``src/components/agentchat/agentPlan.ts``). Claude Code has tools for it,
which the host has to ask for on its newer models; Codex reports its list as a
``todo_list`` item instead of a call.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

from dodaios.agent_chat import dodaios_harness, runner_cli
from dodaios.agent_chat.events import PLAN_TOOL, plan_steps, plan_update_events
from dodaios.agent_chat.runner_cli import (
    _ClaudeState,
    _CodexState,
    plan_claude,
    translate_claude_line,
    translate_codex_line,
)


def _plan_args(tmp_path: Path) -> dict:
    return dict(
        prompt="hi", cwd=tmp_path, model="", effort="", permission_mode="default", resume=None
    )


def test_a_coding_thread_gets_claude_codes_list_tools(monkeypatch, tmp_path: Path):
    """Claude Code withholds its list tools from its newer models unless the host asks."""
    monkeypatch.setattr(runner_cli, "claude_argv_prefix", lambda: ["claude"])
    monkeypatch.setattr(runner_cli, "_registry_env", lambda _name, env: env)
    monkeypatch.delenv(runner_cli.TODO_TOOLS_ENV, raising=False)
    for plan in (plan_claude, runner_cli.plan_glm):
        assert plan(**_plan_args(tmp_path)).env[runner_cli.TODO_TOOLS_ENV] == "true"


def test_an_assistants_chat_keeps_claude_codes_default(monkeypatch, tmp_path: Path):
    """The lead and a society seat answer in a chat; only a coding thread plans with a list."""
    monkeypatch.setattr(runner_cli, "claude_argv_prefix", lambda: ["claude"])
    monkeypatch.setattr(runner_cli, "_registry_env", lambda _name, env: env)
    monkeypatch.delenv(runner_cli.TODO_TOOLS_ENV, raising=False)
    identity = dodaios_harness.Identity(session_id="s", text="x", compact="x", path=None)
    for plan in (plan_claude, runner_cli.plan_glm):
        assert runner_cli.TODO_TOOLS_ENV not in plan(**_plan_args(tmp_path), identity=identity).env


def test_a_person_who_set_the_switch_keeps_their_choice(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(runner_cli, "claude_argv_prefix", lambda: ["claude"])
    monkeypatch.setenv(runner_cli.TODO_TOOLS_ENV, "false")
    assert plan_claude(**_plan_args(tmp_path)).env[runner_cli.TODO_TOOLS_ENV] == "false"


def test_claude_codes_task_calls_pass_through_with_their_input_and_answer():
    """The shapes Claude Code 2.1.325 sent in a real run: the thread folds them into the list."""
    st = _ClaudeState(turn_id="t")
    lines = [
        {
            "type": "assistant",
            "message": {
                "id": "m1",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "TaskCreate",
                        "input": {
                            "subject": "Collect facts",
                            "description": "Gather the facts.",
                            "activeForm": "Collecting facts",
                        },
                    }
                ],
            },
        },
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_1",
                        "content": "Task #1 created successfully: Collect facts",
                    }
                ]
            },
        },
    ]
    events = [ev for obj in lines for ev in translate_claude_line(obj, st)]
    call = next(ev["payload"] for ev in events if ev["kind"] == "tool_call")
    result = next(ev["payload"] for ev in events if ev["kind"] == "tool_result")
    assert call["name"] == "TaskCreate"
    assert call["input"]["subject"] == "Collect facts"
    assert result["output"] == "Task #1 created successfully: Collect facts"
    assert not result["is_error"]


def _codex_list(phase: str, *items: tuple[str, bool]) -> dict:
    return {
        "type": f"item.{phase}",
        "item": {
            "id": "item_2",
            "type": "todo_list",
            "items": [{"text": text, "completed": done} for text, done in items],
        },
    }


def test_codex_plan_is_told_as_a_list_call_on_every_change():
    st = _CodexState(turn_id="turn9")
    lines = [
        _codex_list("started", ("Read the code", False), ("Fix the bug", False)),
        {"type": "item.completed", "item": {"id": "item_3", "type": "reasoning", "text": "ok"}},
        _codex_list("updated", ("Read the code", True), ("Fix the bug", False)),
        _codex_list("updated", ("Read the code", True), ("Fix the bug", True)),
        # The turn's end repeats the last list: nothing new to tell.
        _codex_list("completed", ("Read the code", True), ("Fix the bug", True)),
    ]
    events = [ev for obj in lines for ev in translate_codex_line(obj, st)]
    assert [ev["kind"] for ev in events] == [
        "tool_call",
        "tool_result",
        "reasoning",
        "tool_call",
        "tool_result",
        "tool_call",
        "tool_result",
    ]
    calls = [ev["payload"] for ev in events if ev["kind"] == "tool_call"]
    assert {call["name"] for call in calls} == {PLAN_TOOL}
    # One call id per change, unique across the conversation's turns.
    assert [call["call_id"] for call in calls] == [
        "plan-turn9-1",
        "plan-turn9-2",
        "plan-turn9-3",
    ]
    assert calls[0]["input"] == {
        "plan": [
            {"step": "Read the code", "status": "pending"},
            {"step": "Fix the bug", "status": "pending"},
        ]
    }
    assert [step["status"] for step in calls[1]["input"]["plan"]] == ["completed", "pending"]
    results = [ev["payload"] for ev in events if ev["kind"] == "tool_result"]
    assert all(not result["is_error"] for result in results)
    assert [result["call_id"] for result in results] == [call["call_id"] for call in calls]


def test_an_empty_codex_list_tells_nothing():
    st = _CodexState(turn_id="t")
    assert translate_codex_line(_codex_list("started"), st) == []
    assert translate_codex_line({"type": "item.started", "item": {"type": "todo_list"}}, st) == []


def test_plan_steps_reads_each_runtimes_entries():
    assert plan_steps(
        [
            {"text": "  Read   the code ", "completed": True},
            {"content": "Fix the bug", "status": "in_progress", "priority": "high"},
            {"step": "Test it", "status": "pending"},
            {"content": "Ship it", "status": "something new"},
            {"content": "   "},
            "not an entry",
        ]
    ) == [
        {"step": "Read the code", "status": "completed"},
        {"step": "Fix the bug", "status": "in_progress"},
        {"step": "Test it", "status": "pending"},
        {"step": "Ship it", "status": "pending"},
    ]
    assert plan_steps(None) == []
    assert plan_steps({"text": "x"}) == []


def test_a_plan_update_is_one_finished_call():
    steps = [{"step": "One", "status": "pending"}]
    call, result = plan_update_events("t", "plan-t-1", steps)
    assert (call["kind"], result["kind"]) == ("tool_call", "tool_result")
    assert call["payload"]["input"] == {"plan": steps}
    assert result["payload"]["call_id"] == call["payload"]["call_id"] == "plan-t-1"


def _codex_ids(st: _CodexState, *lines: dict) -> list[str]:
    return [
        str(ev["payload"].get("call_id") or ev["payload"].get("message_id"))
        for obj in lines
        for ev in translate_codex_line(obj, st)
        if ev["kind"] in {"tool_call", "assistant_text"}
    ]


def test_a_turn_codex_runs_twice_never_reuses_its_first_runs_ids():
    # After a limit, a recovery or a model switch the same turn runs Codex
    # again, which counts its items from item_0 and its lists from 1 anew.
    # The chat kept the first run's checklist, messages and tool rows: the
    # second run's updates were dropped as repeats.
    first = _CodexState(turn_id="T", run=runner_cli.run_tag(SimpleNamespace(pid=101)))
    second = _CodexState(turn_id="T", run=runner_cli.run_tag(SimpleNamespace(pid=202)))
    said = {
        "type": "item.completed",
        "item": {"id": "item_0", "type": "agent_message", "text": "hi"},
    }
    lines = (_codex_list("started", ("A", False)), said)
    ids_first = _codex_ids(first, *lines)
    ids_second = _codex_ids(second, *lines)
    assert len(ids_first) == len(ids_second) == 2
    assert not set(ids_first) & set(ids_second)


def test_a_run_keeps_its_ids_when_the_app_reattaches_to_it():
    # A hosted CLI read again after an app restart replays its lines: they
    # must rebuild the ids the thread already shows.
    host = SimpleNamespace(host_id="h-42", pid=7)
    assert runner_cli.run_tag(host) == runner_cli.run_tag(SimpleNamespace(host_id="h-42", pid=8))
    assert runner_cli.run_tag(host) != runner_cli.run_tag(SimpleNamespace(host_id="h-43"))


def test_each_codex_process_of_a_turn_gets_its_own_list_ids(monkeypatch, tmp_path: Path):
    from tests.unit.agent_chat.test_ide_cli_seats import _fake_cli, _turn

    lines = [
        {"type": "thread.started", "thread_id": "th-1"},
        _codex_list("started", ("Read the code", False)),
        {"type": "turn.completed", "usage": {}},
    ]
    seen: list[str] = []
    for _ in range(2):
        plan = runner_cli.CliPlan(_fake_cli(lines), dict(os.environ), None, "codex", None)
        _vendor, events = _turn(monkeypatch, tmp_path, "codex-cli", plan, "openai-codex")
        seen += [ev["payload"]["call_id"] for ev in events if ev["kind"] == "tool_call"]
    assert len(seen) == 2 and seen[0] != seen[1]
    assert all(call.startswith("plan-t1-") for call in seen)
