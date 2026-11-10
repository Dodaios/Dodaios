"""The lead log folds into the few rows a phone shows; cards track their answers."""

from __future__ import annotations

from dodaios.mobile.timeline import fold_events


def _ev(seq: int, event_kind: str, **payload: object) -> dict:
    return {"seq": seq, "ts_ms": 1_700_000_000_000 + seq, "kind": event_kind, "payload": payload}


def test_messages_fold_into_user_and_assistant_rows_per_turn() -> None:
    folded = fold_events(
        [
            _ev(1, "user_message", text="Hello"),
            _ev(2, "turn_started", turn_id="t1"),
            _ev(3, "text_delta", turn_id="t1", text="He"),
            _ev(4, "assistant_text", turn_id="t1", text="Hi there."),
            _ev(5, "tool_call", turn_id="t1", name="web_search"),
            _ev(6, "assistant_text", turn_id="t1", text="Found it."),
            _ev(7, "turn_finished", turn_id="t1"),
        ],
        running=False,
    )
    assert [r["kind"] for r in folded["rows"]] == ["user", "assistant"]
    assert folded["rows"][1]["text"] == "Hi there.\n\nFound it."
    assert folded["last_seq"] == 7 and folded["running"] is False and folded["waiting"] is False


def test_approval_card_opens_and_settles() -> None:
    events = [
        _ev(1, "approval_required", approval_id="ap1", name="run_command", summary="rm -rf build",
            brief="Remove the build folder"),
    ]
    folded = fold_events(events, running=True)
    row = folded["rows"][0]
    assert row["kind"] == "approval" and row["decision"] is None
    assert row["text"] == "Remove the build folder"
    assert folded["pending_approvals"] == ["ap1"] and folded["waiting"] is True
    events.append(_ev(2, "approval_resolved", approval_id="ap1", decision="allow"))
    settled = fold_events(events)
    assert settled["rows"][0]["decision"] == "allow"
    assert settled["pending_approvals"] == [] and settled["waiting"] is False


def test_questions_notices_and_errors() -> None:
    folded = fold_events(
        [
            _ev(1, "question_required", question_id="q1",
                questions=[{"prompt": "Which folder?"}]),
            _ev(2, "notice", kind="chat_control", state={"mode": "x"}),
            _ev(3, "notice", kind="society_result", text="The report is ready.", status="done"),
            _ev(4, "notice", kind="approval_rule", text="hidden plumbing"),
            _ev(5, "error", message="The provider timed out."),
            _ev(6, "question_resolved", question_id="q1"),
        ]
    )
    kinds = [r["kind"] for r in folded["rows"]]
    assert kinds == ["question", "notice", "error"]
    assert folded["rows"][0]["text"] == "Which folder?" and folded["rows"][0]["answered"] is True
    assert folded["rows"][1]["notice_kind"] == "society_result"
    assert folded["waiting"] is False


def test_empty_and_malformed_events_are_tolerated() -> None:
    assert fold_events([]) == {
        "rows": [], "pending_approvals": [], "waiting": False, "running": False, "last_seq": 0,
    }
    folded = fold_events([{"kind": "user_message", "payload": "not a dict"}, {"kind": None}])
    assert folded["rows"] == []
