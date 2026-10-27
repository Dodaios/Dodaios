"""History replay renders tool rounds as labelled data, never as a call marker (#978)."""

from __future__ import annotations

from typing import Any

from dodaios.agent_chat.events import make_event
from dodaios.agent_chat.runner_brain import brain_history_from_events


def _ev(seq: int, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    event = make_event(kind, payload)
    event["seq"] = seq
    return event


def _turn(calls: list[tuple[str, dict[str, Any], str | None, bool]]) -> list[dict[str, Any]]:
    events = [_ev(1, "user_message", {"text": "do it"})]
    seq = 2
    for index, (name, args, output, is_error) in enumerate(calls):
        call_id = f"c{index}"
        events.append(
            _ev(seq, "tool_call", {"turn_id": "t", "call_id": call_id, "name": name, "input": args})
        )
        seq += 1
        if output is not None:
            events.append(
                _ev(
                    seq,
                    "tool_result",
                    {"turn_id": "t", "call_id": call_id, "output": output, "is_error": is_error},
                )
            )
            seq += 1
    events.append(_ev(seq, "assistant_text", {"turn_id": "t", "text": "Done."}))
    events.append(_ev(seq + 1, "turn_finished", {"turn_id": "t", "status": "done"}))
    events.append(_ev(seq + 2, "user_message", {"text": "next"}))
    return events


def test_errors_are_kept_and_results_are_bounded() -> None:
    history = brain_history_from_events(
        _turn(
            [
                ("Bash", {"command": "ls"}, "x" * 2000, False),
                ("Read", {"file_path": "b.py"}, "no such file", True),
            ]
        )
    )
    assert [m.role for m in history] == ["user", "assistant", "user"]
    text = history[1].content
    assert isinstance(text, str)
    assert "[used tool" not in text
    assert "failed: no such file" in text
    assert "x" * 300 + "…" in text and "x" * 301 not in text
    assert text.endswith("Done.")


def test_a_cancelled_call_reads_as_cancelled_not_as_a_new_call() -> None:
    events = _turn([("Read", {"file_path": "a.py"}, None, False)])
    # Drop the closing turn so the call stays open, like a cancelled turn.
    history = brain_history_from_events([e for e in events if e["kind"] != "turn_finished"])
    assert "cancelled before it ran" in history[1].content


def test_the_record_lists_at_most_eight_calls() -> None:
    calls = [("Read", {"file_path": f"f{i}.py"}, "ok", False) for i in range(11)]
    text = brain_history_from_events(_turn(calls))[1].content
    assert text.count("\n- Read") == 8
    assert "and 3 more calls" in text


def test_no_provider_tool_ids_reach_the_history() -> None:
    history = brain_history_from_events(_turn([("Read", {"file_path": "a.py"}, "ok", False)]))
    assert all(isinstance(m.content, str) and m.tool_call_id is None for m in history)
    assert all(m.role in {"user", "assistant"} for m in history)
