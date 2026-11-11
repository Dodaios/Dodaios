"""A Claude turn's ``rate_limit_event`` feeds the plan meter and nothing else.

The event is the provider's own word on how much of the seat's plan is spent,
sent with every turn. It must reach :mod:`dodaios.agent_usage` for the seat the
turn ran on, must never show up in the timeline, and must be ignored where the
line came from a CLI that only borrows Claude's wire shape.
"""

from __future__ import annotations

from typing import Any

import pytest

from dodaios import agent_usage
from dodaios.agent_chat.runner_cli import _ClaudeState, translate_claude_line

EVENT = {
    "type": "rate_limit_event",
    "rate_limit_info": {
        "status": "allowed",
        "unifiedWindows": {"seven_day": {"utilization": 0.16, "resetsAt": 1794834000}},
    },
    "session_id": "s1",
}


@pytest.fixture
def noted(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Any]]:
    calls: list[tuple[str, Any]] = []
    monkeypatch.setattr(
        agent_usage, "note_claude_rate_limit", lambda home, info: calls.append((home, info))
    )
    return calls


def test_the_event_reaches_the_meter_for_the_turns_seat(noted: list[tuple[str, Any]]) -> None:
    st = _ClaudeState(turn_id="t1", usage_home="C:/seats/second")
    assert translate_claude_line(EVENT, st) == []
    assert noted == [("C:/seats/second", EVENT["rate_limit_info"])]


def test_the_built_in_seat_is_named_by_an_empty_home(noted: list[tuple[str, Any]]) -> None:
    translate_claude_line(EVENT, _ClaudeState(turn_id="t1", usage_home=""))
    assert noted == [("", EVENT["rate_limit_info"])]


def test_a_line_from_another_cli_is_not_counted(noted: list[tuple[str, Any]]) -> None:
    """Grok and the browser model speak Claude's shape; their state names no seat."""
    assert translate_claude_line(EVENT, _ClaudeState(turn_id="t1")) == []
    assert noted == []
