"""Fold a lead session's event log into scoreable turns (read-only).

One :class:`Turn` is one owner message and everything the lead did until the
owner's next message: tool calls and results, approvals, the answer, and how
the turn ended. Only the ``jarvis`` surface (the lead's one conversation) is
read.
"""

from __future__ import annotations

import contextlib
import json
import logging
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

LEAD_SURFACE = "jarvis"


@dataclass(slots=True)
class Turn:
    session_id: str
    ts_ms: int
    text: str = ""
    turn_id: str = ""
    tools: list[str] = field(default_factory=list)
    tool_errors: int = 0
    tool_results: int = 0
    verdicts: list[str] = field(default_factory=list)  # verify_delegate verdicts
    answer: str = ""
    status: str = ""  # done | error | cancelled | "" (never finished)
    duration_ms: int = 0
    cost_usd: float = 0.0
    denied_approvals: int = 0
    undo_calls: int = 0
    # Gate evidence
    unauthorised_actions: int = 0
    calls_after_cancel: int = 0
    # The owner's next message in the same conversation (for follow-up signals)
    next_text: str = ""
    next_ts_ms: int = 0


def _loads(raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _verdict(output: Any) -> str:
    if isinstance(output, str):
        output = _loads(output)
    if isinstance(output, dict):
        verdict = str(output.get("verdict") or "")
        if verdict in {"verified", "unverified", "failed"}:
            return verdict
    return ""


@contextlib.contextmanager
def _open_ro(path: Path) -> Iterator[sqlite3.Connection | None]:
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True, timeout=5.0)
        conn.row_factory = sqlite3.Row
    except sqlite3.Error:
        log.warning("agent score: %s is not readable", path)
    try:
        yield conn
    finally:
        if conn is not None:
            with contextlib.suppress(sqlite3.Error):
                conn.close()


def fold_events(session_id: str, events: list[dict[str, Any]]) -> list[Turn]:
    """Turn one session's ordered events into owner-driven turns."""
    turns: list[Turn] = []
    cur: Turn | None = None
    call_names: dict[str, str] = {}
    denied_calls: set[str] = set()
    cancelled = False
    for ev in events:
        kind = ev["kind"]
        p = ev["payload"]
        if kind == "user_message":
            cur = Turn(session_id, int(ev["ts_ms"]), text=str(p.get("text") or ""))
            turns.append(cur)
            call_names.clear()
            denied_calls.clear()
            cancelled = False
            continue
        if cur is None:
            continue
        if kind == "turn_started":
            cur.turn_id = cur.turn_id or str(p.get("turn_id") or "")
        elif kind == "tool_call":
            if cancelled:
                cur.calls_after_cancel += 1
            call_names[str(p.get("call_id") or "")] = str(p.get("name") or "")
            cur.tools.append(str(p.get("name") or ""))
            args = p.get("input")
            if isinstance(args, dict) and "undo_of" in args:
                cur.undo_calls += 1
        elif kind == "tool_result":
            cur.tool_results += 1
            is_error = bool(p.get("is_error"))
            cur.tool_errors += int(is_error)
            call_id = str(p.get("call_id") or "")
            if call_id in denied_calls and not is_error:
                cur.unauthorised_actions += 1
            if call_names.get(call_id, "").endswith("verify_delegate"):
                verdict = _verdict(p.get("output"))
                if verdict:
                    cur.verdicts.append(verdict)
        elif kind == "approval_resolved":
            if str(p.get("decision") or "") in {"deny", "cancel", "expired"}:
                cur.denied_approvals += 1
                call_id = str(p.get("call_id") or "")
                if call_id:
                    denied_calls.add(call_id)
        elif kind == "assistant_text":
            cur.answer = (cur.answer + "\n" + str(p.get("text") or "")).strip()
        elif kind == "turn_finished":
            cur.status = str(p.get("status") or "")
            cur.duration_ms = int(p.get("duration_ms") or 0)
            try:
                cur.cost_usd = float(p.get("cost_usd") or 0.0)
            except (TypeError, ValueError):
                cur.cost_usd = 0.0
            cancelled = cur.status == "cancelled"
    return turns


def read_lead_turns(db_path: Path, since_ms: int = 0, until_ms: int | None = None) -> list[Turn]:
    """Every owner-driven lead turn in the window, oldest first. Missing DB -> []."""
    if not Path(db_path).is_file():
        return []
    out: list[Turn] = []
    with _open_ro(Path(db_path)) as conn:
        if conn is None:
            return []
        try:
            sessions = [
                r["session_id"]
                for r in conn.execute(
                    "SELECT session_id FROM agent_chat_sessions WHERE surface = ?", (LEAD_SURFACE,)
                )
            ]
            for sid in sessions:
                rows = conn.execute(
                    "SELECT seq, ts_ms, kind, payload FROM agent_chat_events "
                    "WHERE session_id = ? ORDER BY seq",
                    (sid,),
                ).fetchall()
                events = [
                    {
                        "seq": r["seq"],
                        "ts_ms": r["ts_ms"],
                        "kind": r["kind"],
                        "payload": _loads(r["payload"]),
                    }
                    for r in rows
                ]
                turns = fold_events(sid, events)
                for prev, nxt in zip(turns, turns[1:], strict=False):
                    prev.next_text, prev.next_ts_ms = nxt.text, nxt.ts_ms
                out.extend(turns)
        except sqlite3.Error as exc:
            log.warning("agent score: chat store read failed (%s)", exc)
            return []
    out = [t for t in out if t.ts_ms >= since_ms and (until_ms is None or t.ts_ms <= until_ms)]
    out.sort(key=lambda t: t.ts_ms)
    return out
