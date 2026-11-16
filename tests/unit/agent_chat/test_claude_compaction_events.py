"""A Claude Code turn whose agent compacts its own conversation.

Claude Code says ``status: "compacting"`` when it starts (and again every 30 s
while it runs), ``compact_boundary`` with the token counts once the summary
replaced the history, and a ``status`` line with ``compact_error`` when it
failed. The translator tells each compaction as ``compaction`` events with one
call id, so the thread draws one line where it happened.
"""

from __future__ import annotations

from typing import Any

from dodaios.agent_chat.runner_cli import _ClaudeState, translate_claude_line


def _status(status: str | None, **extra: Any) -> dict[str, Any]:
    return {"type": "system", "subtype": "status", "status": status, **extra}


def _boundary(**meta: Any) -> dict[str, Any]:
    return {"type": "system", "subtype": "compact_boundary", "compact_metadata": meta}


def _compactions(lines: list[dict[str, Any]], st: _ClaudeState) -> list[dict[str, Any]]:
    return [
        ev["payload"]
        for line in lines
        for ev in translate_claude_line(line, st)
        if ev["kind"] == "compaction"
    ]


def test_an_auto_compaction_is_one_start_and_one_end_with_its_counts() -> None:
    st = _ClaudeState(turn_id="t1")
    events = _compactions(
        [
            _status("compacting"),
            _status("compacting"),  # the 30 s heartbeat: still the same compaction
            _boundary(trigger="auto", pre_tokens=182_000, post_tokens=31_000, duration_ms=14_200),
            _status(None, compact_result="success"),
        ],
        st,
    )
    assert [e["phase"] for e in events] == ["started", "done"]
    assert events[0]["call_id"] == events[1]["call_id"] == "compact-t1-1"
    assert events[1]["trigger"] == "auto"
    assert events[1]["tokens_before"] == 182_000
    assert events[1]["tokens_after"] == 31_000
    assert events[1]["duration_ms"] == 14_200
    assert st.compaction_id == ""


def test_a_boundary_without_a_status_line_still_draws_the_line() -> None:
    st = _ClaudeState(turn_id="t1")
    events = _compactions([_boundary(trigger="manual", pre_tokens=90_000)], st)
    assert [e["phase"] for e in events] == ["started", "done"]
    assert events[1]["trigger"] == "manual"
    assert "tokens_after" not in events[1]


def test_a_failed_compaction_ends_failed_with_the_reason() -> None:
    events = _compactions(
        [_status("compacting"), _status(None, compact_result="failed", compact_error="Too big")],
        _ClaudeState(turn_id="t1"),
    )
    assert [e["phase"] for e in events] == ["started", "failed"]
    assert events[1]["error"] == "Too big"


def test_the_model_answering_again_closes_an_open_compaction() -> None:
    st = _ClaudeState(turn_id="t1")
    message = {"type": "stream_event", "event": {"type": "message_start", "message": {"id": "m1"}}}
    events = _compactions([_status("compacting"), message], st)
    assert [e["phase"] for e in events] == ["started", "done"]


def test_two_compactions_in_one_turn_have_their_own_ids() -> None:
    st = _ClaudeState(turn_id="t1")
    events = _compactions(
        [_status("compacting"), _boundary(pre_tokens=1), _status("compacting"), _boundary()],
        st,
    )
    assert [e["call_id"] for e in events] == [
        "compact-t1-1",
        "compact-t1-1",
        "compact-t1-2",
        "compact-t1-2",
    ]


def test_an_ordinary_status_line_tells_nothing() -> None:
    st = _ClaudeState(turn_id="t1")
    assert translate_claude_line(_status(None), st) == []
    assert translate_claude_line({"type": "system", "subtype": "init"}, st) == []
