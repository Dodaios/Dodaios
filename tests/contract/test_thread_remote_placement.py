"""A coding thread can run on a connected computer (per-thread placement)."""

from __future__ import annotations

import asyncio
import sqlite3

from dodaios.agent_chat.store import AgentChatStore
from dodaios.society.remote import placement_for_session, thread_agent_id


def _make(store: AgentChatStore, **kw):
    return store.create_session(provider="claude-code", model="", effort="", cwd="/w", **kw)


def test_thread_placement_round_trips_and_defaults_local() -> None:
    store = AgentChatStore(":memory:")
    local = _make(store)
    assert local.computer_id == ""
    placed = _make(store, computer_id="vps-1")
    assert store.get_session(placed.session_id).computer_id == "vps-1"
    store.update_session(placed.session_id, computer_id="")
    # an empty string is a real value ("this computer"), not "unset"
    assert store.get_session(placed.session_id).computer_id == ""


def test_old_database_gains_the_column(tmp_path) -> None:
    path = tmp_path / "chat.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE agent_chat_sessions (session_id TEXT PRIMARY KEY, title TEXT NOT NULL "
        "DEFAULT '', provider TEXT NOT NULL DEFAULT '', model TEXT NOT NULL DEFAULT '', "
        "effort TEXT NOT NULL DEFAULT '', cwd TEXT NOT NULL DEFAULT '', permission_mode TEXT "
        "NOT NULL DEFAULT 'bypass', vendor_session TEXT, created_ms INTEGER NOT NULL, "
        "updated_ms INTEGER NOT NULL, message_count INTEGER NOT NULL DEFAULT 0, "
        "preview TEXT NOT NULL DEFAULT '')"
    )
    conn.commit()
    conn.close()
    store = AgentChatStore(path)
    assert _make(store, computer_id="c").computer_id == "c"


def test_placement_for_a_thread_session() -> None:
    store = AgentChatStore(":memory:")
    placed = _make(store, computer_id="vps-1")
    local = _make(store)
    assert asyncio.run(placement_for_session(local)) is None
    got = asyncio.run(placement_for_session(placed))
    assert got == ("vps-1", thread_agent_id(placed.session_id))
    assert got[1].startswith("thread-")


def test_thread_agent_id_is_shell_safe() -> None:
    assert thread_agent_id("ab/../c d;e") == "thread-abcde"
    assert thread_agent_id("") == "thread-thread"
