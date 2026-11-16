"""An ACP agent's ``plan`` update reaches the thread as a list call.

ACP agents report their to-do list as a session update (``sessionUpdate:
"plan"`` with all ``entries``) instead of a tool call. The thread draws the
list as a checklist from a call's input, so each changed list is told as one.
"""

from __future__ import annotations

import asyncio
from typing import Any

from dodaios.agent_chat.events import PLAN_TOOL
from dodaios.agent_runtimes.acp import AcpTurn


class _IO:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def write(self, frame: dict[str, Any]) -> None:
        pass

    async def emit(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    async def ask(self, call_id: str, name: str, args: dict[str, Any], summary: str) -> str:
        return "deny"


def _update(update: dict[str, Any]) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "method": "session/update",
        "params": {"sessionId": "s", "update": update},
    }


def _plan(*entries: tuple[str, str]) -> dict[str, Any]:
    return _update(
        {
            "sessionUpdate": "plan",
            "entries": [
                {"content": content, "priority": "medium", "status": status}
                for content, status in entries
            ],
        }
    )


def _text(text: str) -> dict[str, Any]:
    return _update(
        {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": text}}
    )


def _run(*frames: dict[str, Any]) -> list[dict[str, Any]]:
    turn = AcpTurn(turn_id="t7", cwd=".", prompt_text="hi")
    io = _IO()

    async def go() -> None:
        for frame in frames:
            await turn.on_message(frame, io)

    asyncio.run(go())
    return io.events


def test_a_plan_update_is_told_as_a_list_call():
    events = _run(_plan(("Read the code", "in_progress"), ("Fix the bug", "pending")))
    assert [event["kind"] for event in events] == ["tool_call", "tool_result"]
    call = events[0]["payload"]
    assert call["name"] == PLAN_TOOL
    assert call["call_id"] == "plan-t7-1"
    assert call["input"] == {
        "plan": [
            {"step": "Read the code", "status": "in_progress"},
            {"step": "Fix the bug", "status": "pending"},
        ]
    }
    assert events[1]["payload"]["call_id"] == "plan-t7-1"
    assert not events[1]["payload"]["is_error"]


def test_only_a_changed_list_is_told_again():
    events = _run(
        _plan(("Read the code", "in_progress")),
        _plan(("Read the code", "in_progress")),
        _plan(("Read the code", "completed")),
        _plan(),
    )
    calls = [event["payload"] for event in events if event["kind"] == "tool_call"]
    assert [call["call_id"] for call in calls] == ["plan-t7-1", "plan-t7-2"]
    assert calls[1]["input"]["plan"] == [{"step": "Read the code", "status": "completed"}]


def test_words_written_before_the_list_stay_before_it():
    events = _run(_text("I will plan this first."), _plan(("Read the code", "pending")))
    kinds = [event["kind"] for event in events if event["kind"] != "text_delta"]
    assert kinds == ["assistant_text", "tool_call", "tool_result"]


def test_a_turn_run_twice_tells_its_lists_under_new_ids():
    # The same turn on a second process (a model switch, a recovery) counted
    # its lists from 1 again; the thread kept the first run's checklist.
    ids = []
    for tag in ("aaaaaa", "bbbbbb"):
        turn = AcpTurn(turn_id="t7", cwd=".", prompt_text="hi")
        turn.run = tag
        io = _IO()
        asyncio.run(turn.on_message(_plan(("Read the code", "pending")), io))
        ids += [e["payload"]["call_id"] for e in io.events if e["kind"] == "tool_call"]
    assert ids == ["plan-t7-aaaaaa-1", "plan-t7-bbbbbb-1"]
