"""The lead conversation folded into the few row kinds a phone screen shows.

The desktop renders the full event log (tool calls, reasoning, sub-agents).
The phone shows what a person reads on the go: what was said, what waits for
them, and short status lines. Folding here keeps the phone bundle tiny and
gives the rows one shape to test.
"""

from __future__ import annotations

from typing import Any

#: Notice kinds that are plumbing, not news.
_SILENT_NOTICES = frozenset(
    {"chat_control", "approval_rule", "message_dequeued", "message_queued", "turn_host"}
)
_MAX_TEXT = 6000


def _text(value: Any, limit: int = _MAX_TEXT) -> str:
    return str(value or "").strip()[:limit]


def fold_events(events: list[dict[str, Any]], *, running: bool = False) -> dict[str, Any]:
    """Rows for the phone plus the open approvals and the last event seq."""
    rows: list[dict[str, Any]] = []
    open_approvals: dict[str, dict[str, Any]] = {}
    open_questions: dict[str, dict[str, Any]] = {}
    turn_text: dict[str, int] = {}  # turn_id -> index of its assistant row
    last_seq = 0

    for event in events:
        kind = str(event.get("kind") or "")
        payload = event.get("payload") or {}
        if not isinstance(payload, dict):
            payload = {}
        seq = int(event.get("seq") or 0)
        ts = int(event.get("ts_ms") or 0)
        last_seq = max(last_seq, seq)
        turn_id = str(payload.get("turn_id") or "")

        if kind == "user_message":
            text = _text(payload.get("text"))
            if text:
                rows.append({"id": f"u-{seq}", "kind": "user", "text": text, "ts_ms": ts})
        elif kind == "assistant_text":
            text = _text(payload.get("text"))
            if not text:
                continue
            index = turn_text.get(turn_id)
            if index is not None and turn_id:
                rows[index]["text"] = (rows[index]["text"] + "\n\n" + text)[:_MAX_TEXT]
            else:
                rows.append({"id": f"a-{seq}", "kind": "assistant", "text": text, "ts_ms": ts})
                if turn_id:
                    turn_text[turn_id] = len(rows) - 1
        elif kind == "approval_required":
            approval_id = str(payload.get("approval_id") or "")
            if not approval_id:
                continue
            row = {
                "id": f"ap-{approval_id}",
                "kind": "approval",
                "approval_id": approval_id,
                "name": _text(payload.get("name"), 120),
                "text": _text(payload.get("brief") or payload.get("summary"), 600),
                "ts_ms": ts,
                "decision": None,
            }
            open_approvals[approval_id] = row
            rows.append(row)
        elif kind == "approval_resolved":
            approval_id = str(payload.get("approval_id") or "")
            row = open_approvals.pop(approval_id, None)
            if row is not None:
                row["decision"] = str(payload.get("decision") or "decided")
        elif kind == "question_required":
            question_id = str(payload.get("question_id") or payload.get("ref_id") or "")
            questions = payload.get("questions")
            first = questions[0] if isinstance(questions, list) and questions else {}
            prompt = first.get("prompt") if isinstance(first, dict) else ""
            row = {
                "id": f"q-{question_id or seq}",
                "kind": "question",
                "text": _text(prompt or payload.get("summary") or payload.get("text"), 600),
                "ts_ms": ts,
                "answered": False,
            }
            if question_id:
                open_questions[question_id] = row
            rows.append(row)
        elif kind == "question_resolved":
            row = open_questions.pop(str(payload.get("question_id") or ""), None)
            if row is not None:
                row["answered"] = True
        elif kind == "notice":
            notice_kind = str(payload.get("kind") or "")
            text = _text(payload.get("text") or payload.get("report"), 1200)
            if notice_kind in _SILENT_NOTICES or not text:
                continue
            rows.append(
                {
                    "id": f"n-{seq}",
                    "kind": "notice",
                    "notice_kind": notice_kind,
                    "text": text,
                    "status": _text(payload.get("status"), 40),
                    "ts_ms": ts,
                }
            )
        elif kind == "error":
            text = _text(payload.get("message") or payload.get("text"), 600)
            if text:
                rows.append({"id": f"e-{seq}", "kind": "error", "text": text, "ts_ms": ts})

    return {
        "rows": rows,
        "pending_approvals": [row["approval_id"] for row in open_approvals.values()],
        "waiting": bool(open_approvals or open_questions),
        "running": running,
        "last_seq": last_seq,
    }


__all__ = ["fold_events"]
