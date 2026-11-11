"""The sidebar's order key: only a message moves a thread, never its own work."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from dodaios.agent_chat import store as store_mod
from dodaios.agent_chat.store import AgentChatStore


def _event(kind: str, ts_ms: int, **payload: object) -> dict[str, object]:
    return {"kind": kind, "ts_ms": ts_ms, "payload": payload}


def test_tool_calls_and_answers_leave_the_order_key_alone() -> None:
    store = AgentChatStore(":memory:")
    session = store.create_session(provider="openai", model="m", effort="", cwd=".")
    assert session.last_message_ms == session.created_ms

    store.append_event(session.session_id, _event("user_message", 1_000, text="fix the bug"))
    store.append_event(session.session_id, _event("tool_call", 2_000, name="read_file"))
    store.append_event(session.session_id, _event("assistant_text", 3_000, text="done"))

    after = store.get_session(session.session_id)
    assert after is not None
    assert after.last_message_ms == 1_000
    assert after.updated_ms == 3_000
    assert after.to_dict()["last_message_ms"] == 1_000

    store.append_event(session.session_id, _event("agent_message", 4_000, text="from a peer"))
    peer = store.get_session(session.session_id)
    assert peer is not None and peer.last_message_ms == 4_000


def test_an_old_database_takes_each_thread_s_newest_message(tmp_path: Path) -> None:
    db = tmp_path / "agent_chat.db"
    column = ",\n    last_message_ms  INTEGER NOT NULL DEFAULT 0"
    old_schema = store_mod._SCHEMA.replace(column, "")
    assert "last_message_ms" not in old_schema, "the old schema must not know the column"
    conn = sqlite3.connect(db)
    conn.executescript(old_schema)
    conn.executemany(
        "INSERT INTO agent_chat_sessions (session_id, provider, created_ms, updated_ms) "
        "VALUES (?, 'openai', ?, ?)",
        [("talked", 100, 900), ("silent", 200, 800)],
    )
    conn.executemany(
        "INSERT INTO agent_chat_events (session_id, seq, ts_ms, kind, payload) "
        "VALUES (?, ?, ?, ?, '{}')",
        [("talked", 1, 300, "user_message"), ("talked", 2, 900, "tool_call")],
    )
    conn.commit()
    conn.close()

    store = AgentChatStore(db)
    talked = store.get_session("talked")
    silent = store.get_session("silent")
    assert talked is not None and talked.last_message_ms == 300
    assert silent is not None and silent.last_message_ms == 200
    store.close()
    again = AgentChatStore(db)
    assert again.get_session("talked") is not None
    again.close()
