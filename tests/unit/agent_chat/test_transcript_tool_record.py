"""The replayed CLI transcript records tool calls as labelled data (#978).

A bare "[used tool X]" line with no result taught smaller models to type that
line instead of calling the tool. The transcript a CLI seat reads on a fresh
conversation now carries the same tool record the in-process brain replays.
"""

from __future__ import annotations

from typing import Any

from dodaios.agent_chat.dodaios_harness import render_transcript
from dodaios.agent_chat.events import make_event


def _ev(seq: int, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    event = make_event(kind, payload)
    event["seq"] = seq
    return event


def _history() -> list[dict[str, Any]]:
    return [
        _ev(1, "user_message", {"text": "What is in notes.txt?"}),
        _ev(
            2,
            "tool_call",
            {"turn_id": "t", "call_id": "c0", "name": "Read", "input": {"file_path": "notes.txt"}},
        ),
        _ev(
            3,
            "tool_result",
            {"turn_id": "t", "call_id": "c0", "output": "buy milk", "is_error": False},
        ),
        _ev(
            4,
            "tool_call",
            {
                "turn_id": "t",
                "call_id": "c1",
                "name": "Bash",
                "input": {"command": "cat missing.txt"},
            },
        ),
        _ev(
            5,
            "tool_result",
            {"turn_id": "t", "call_id": "c1", "output": "no such file", "is_error": True},
        ),
        _ev(6, "assistant_text", {"turn_id": "t", "text": "It says: buy milk."}),
        _ev(7, "turn_finished", {"turn_id": "t", "status": "done"}),
        _ev(8, "user_message", {"text": "Thanks"}),
    ]


def test_the_transcript_carries_the_tool_record_not_a_bare_marker() -> None:
    out = render_transcript(_history())
    assert "[used tool" not in out
    assert "Tool record of this turn" in out
    assert "returned: buy milk" in out
    assert "failed: no such file" in out


def test_one_turn_is_one_line_of_the_second_speaker() -> None:
    out = render_transcript(_history())
    blocks = out.split("\n\n")
    assert blocks[0] == "Person: What is in notes.txt?"
    assert blocks[1].startswith("You: Tool record of this turn")
    assert blocks[1].endswith("It says: buy milk.")
    assert blocks[2] == "Person: Thanks"


def test_a_typed_marker_in_a_reply_is_not_replayed_as_a_call() -> None:
    history = [
        _ev(1, "user_message", {"text": "play music"}),
        _ev(2, "assistant_text", {"turn_id": "t", "text": "[used tool play_music] Playing now."}),
        _ev(3, "turn_finished", {"turn_id": "t", "status": "done"}),
    ]
    assert "[used tool play_music]" not in render_transcript(history)


def test_the_transcript_is_cut_from_the_front() -> None:
    history = [_ev(1, "user_message", {"text": "x" * 500})]
    out = render_transcript(history, max_chars=100)
    assert out.startswith("…") and len(out) == 101
