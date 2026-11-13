"""Who opened a thread: the author of its first message, kept on the session."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from dodaios.agent_chat import store as store_mod
from dodaios.agent_chat.store import AgentChatStore

LEAD = {"agent_id": "jarvis", "name": "Nova"}


def _message(ts_ms: int, text: str, author: dict[str, str] | None = None) -> dict[str, object]:
    payload: dict[str, object] = {"text": text}
    if author:
        payload["author"] = author
    return {"kind": "user_message", "ts_ms": ts_ms, "payload": payload}


def test_a_thread_dodaios_opened_names_dodaios() -> None:
    store = AgentChatStore(":memory:")
    session = store.create_session(provider="claude-code", model="m", effort="", cwd=".")
    assert session.started_by == ""

    store.append_event(session.session_id, _message(1_000, "fix the bug", LEAD))
    store.append_event(session.session_id, _message(2_000, "and add a test"))

    after = store.get_session(session.session_id)
    assert after is not None
    assert after.started_by == "jarvis"
    assert after.to_dict()["started_by"] == "jarvis"


def test_a_thread_the_person_opened_stays_theirs_when_dodaios_writes_later() -> None:
    store = AgentChatStore(":memory:")
    session = store.create_session(provider="codex", model="m", effort="", cwd=".")

    store.append_event(session.session_id, _message(1_000, "fix the bug"))
    store.append_event(session.session_id, _message(2_000, "status?", LEAD))

    after = store.get_session(session.session_id)
    assert after is not None and after.started_by == ""


def test_an_old_database_takes_the_author_of_each_first_message(tmp_path: Path) -> None:
    db = tmp_path / "agent_chat.db"
    column = ",\n    started_by       TEXT NOT NULL DEFAULT ''"
    old_schema = store_mod._SCHEMA.replace(column, "")
    assert "started_by" not in old_schema, "the old schema must not know the column"
    conn = sqlite3.connect(db)
    conn.executescript(old_schema)
    conn.executemany(
        "INSERT INTO agent_chat_sessions (session_id, provider, created_ms, updated_ms) "
        "VALUES (?, 'claude-code', ?, ?)",
        [("by-lead", 100, 900), ("by-person", 200, 800), ("empty", 300, 300)],
    )
    conn.executemany(
        "INSERT INTO agent_chat_events (session_id, seq, ts_ms, kind, payload) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            ("by-lead", 1, 400, "user_message", json.dumps({"text": "go", "author": LEAD})),
            ("by-person", 1, 500, "user_message", json.dumps({"text": "go"})),
            ("by-person", 2, 600, "user_message", json.dumps({"text": "ok", "author": LEAD})),
        ],
    )
    conn.commit()
    conn.close()

    store = AgentChatStore(db)
    started = {
        sid: session.started_by
        for sid in ("by-lead", "by-person", "empty")
        if (session := store.get_session(sid)) is not None
    }
    assert started == {"by-lead": "jarvis", "by-person": "", "empty": ""}
    store.close()
    again = AgentChatStore(db)
    assert again.get_session("by-lead") is not None
    again.close()
