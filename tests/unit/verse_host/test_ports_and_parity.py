"""BW3 / BW5 parity: the duty and chat-line ports match the shared parity table.

The same table is asserted against the TypeScript originals by
``frontend/src/components/verseHost/__tests__/dutyParity.test.ts``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dodaios.verse_host.chat_lines import chat_lines, clean
from dodaios.verse_host.duty import dot_kind_for, duty_of, duty_of_pane, state_key_for

CASES = json.loads((Path(__file__).parent / "parity" / "duty_cases.json").read_text("utf-8"))


@pytest.mark.parametrize("case", CASES["agents"])
def test_agent_duty(case: dict) -> None:
    got = duty_of(case["state"], case["lifecycle"], asking=case["asking"], error=case["error"])
    assert got == case["duty"]


@pytest.mark.parametrize("case", CASES["panes"])
def test_pane_duty(case: dict) -> None:
    dot = dot_kind_for(case["pane"])
    key = state_key_for(case["pane"], dot)
    assert (dot, key, duty_of_pane(dot, key)) == (case["dot"], case["state_key"], case["duty"])


def test_precedence_rules() -> None:
    assert duty_of("working", "paused") == "paused"
    assert duty_of("working", asking=True) == "waiting"
    assert duty_of("working", error=True) == "working"
    assert duty_of("idle", error=True) == "error"


@pytest.mark.parametrize("case", CASES["chat"])
def test_chat_lines(case: dict) -> None:
    assert chat_lines(case["events"]) == case["lines"]


def test_chat_line_limits() -> None:
    long = "word " * 80
    cut = clean(long, 160)
    assert len(cut) <= 160 and cut.endswith("…") and not cut[:-1].endswith(" ")
    assert clean("x" * 300, 80) == "x" * 79 + "…"
    events = [{"kind": "user_message", "payload": {"text": f"line {i}"}} for i in range(30)]
    lines = chat_lines(events)
    assert len(lines) == 12 and lines[-1]["text"] == "line 29"
    tool = chat_lines([{"kind": "tool_call", "payload": {"summary": "y " * 100}}])[0]
    assert len(tool["text"]) <= 80
