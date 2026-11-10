"""Vault upkeep: daily consolidation and the one-time pass over old chats (ADR-0044)."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

import pytest

from dodaios.memory.vault import backfill, consolidate
from dodaios.memory.vault import runtime as vault_runtime
from dodaios.memory.vault.store import MemoryVault


class Clock:
    def __init__(self) -> None:
        self.value = "2026-11-09T09:00:00+00:00"

    def __call__(self) -> str:
        return self.value


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def vault(tmp_path: Path, clock: Clock):
    v = MemoryVault(tmp_path / "vault.db", clock=clock)
    vault_runtime.set_active(v)
    yield v
    vault_runtime.set_active(None)


class Scripted:
    def __init__(self, *replies: Any) -> None:
        self.replies = list(replies)
        self.prompts: list[dict[str, Any]] = []

    async def __call__(self, prompt: str) -> Any:
        self.prompts.append(json.loads(prompt))
        return self.replies.pop(0) if self.replies else []


def test_consolidation_merges_near_duplicates_and_keeps_history(vault, clock):
    a = vault.remember("The user drinks coffee black every morning.", "preference").memory
    clock.value = "2026-11-09T10:00:00+00:00"
    b = vault.remember("Every morning the user drinks black coffee.", "preference").memory
    vault.remember("The user lives in Berlin.", "profile")
    groups = consolidate.similar_groups(vault)
    assert [{m.id for m in g} for g in groups] == [{a.id, b.id}]

    reviewer = Scripted(
        [{"ids": [a.id, b.id], "text": "The user drinks black coffee every morning."}]
    )
    assert asyncio.run(consolidate.run_if_due(vault, reviewer)) == 1
    texts = [m.text for m in vault.list(kind="preference")]
    assert texts == ["The user drinks black coffee every morning."]
    assert len(vault.list(kind="preference", include_closed=True)) == 3

    # Not due again the same day.
    assert asyncio.run(consolidate.run_if_due(vault, Scripted())) == 0
    clock.value = "2026-11-10T08:00:00+00:00"
    assert consolidate.due(vault)


def test_consolidation_ignores_bad_merges(vault):
    a = vault.remember("The user drinks coffee black every morning.", "preference").memory
    b = vault.remember("Every morning the user drinks black coffee.", "preference").memory
    other = vault.remember("The user lives in Berlin.", "profile").memory
    groups = consolidate.similar_groups(vault)
    merges = [
        {"ids": [a.id], "text": "only one"},
        {"ids": [a.id, other.id], "text": "across groups"},
        {"ids": [a.id, b.id], "text": ""},
    ]
    assert consolidate.apply(vault, groups, merges) == 0
    assert len(vault.list()) == 3


def _old_chats(data_dir: Path) -> None:
    now_ms = int(time.time() * 1000)
    db = sqlite3.connect(data_dir / "agent_chat.db")
    db.executescript(
        "CREATE TABLE agent_chat_sessions (session_id TEXT PRIMARY KEY, surface TEXT);"
        "CREATE TABLE agent_chat_events (session_id TEXT, seq INTEGER, ts_ms INTEGER, "
        "kind TEXT, payload TEXT);"
    )
    db.execute("INSERT INTO agent_chat_sessions VALUES ('s1', 'jarvis'), ('s2', 'agent')")
    rows = [
        (
            "s1",
            1,
            now_ms - 1000,
            "user_message",
            {"text": "By the way, I live in Hamburg with my wife Lea."},
        ),
        ("s1", 2, now_ms - 900, "assistant_text", {"text": "Noted."}),
        ("s1", 3, now_ms - 800, "user_message", {"text": "what time is it"}),
        (
            "s2",
            1,
            now_ms - 700,
            "user_message",
            {"text": "I prefer tabs over spaces in this repo."},
        ),
    ]
    db.executemany(
        "INSERT INTO agent_chat_events VALUES (?, ?, ?, ?, ?)",
        [(s, q, t, k, json.dumps(p)) for s, q, t, k, p in rows],
    )
    db.commit()
    db.close()
    db = sqlite3.connect(data_dir / "chats.db")
    db.executescript(
        "CREATE TABLE chat_messages (message_id TEXT, thread_id TEXT, role TEXT, text TEXT, "
        "timestamp_ns INTEGER);"
    )
    db.execute(
        "INSERT INTO chat_messages VALUES ('m1', 't1', 'user', ?, ?)",
        ("I always want short answers from you.", (now_ms - 500) * 1_000_000),
    )
    db.commit()
    db.close()


def test_backfill_reads_only_the_users_personal_lead_turns(tmp_path, vault):
    _old_chats(tmp_path)
    turns = backfill.collect_user_turns(tmp_path)
    assert turns == [
        "By the way, I live in Hamburg with my wife Lea.",
        "I always want short answers from you.",
    ]


def test_backfill_runs_once_and_resumes(tmp_path, vault):
    _old_chats(tmp_path)
    reviewer = Scripted(
        [
            {
                "op": "add",
                "kind": "profile",
                "text": "The user lives in Hamburg.",
                "evidence": "I live in Hamburg",
            }
        ]
    )
    state = asyncio.run(backfill.run_once(vault, reviewer, tmp_path))
    assert state["done"] and state["written"] == 1 and state["calls"] == 1
    assert [m.text for m in vault.list()] == ["The user lives in Hamburg."]
    assert vault.list()[0].source["via"] == "chat-backfill"
    again = Scripted()
    asyncio.run(backfill.run_once(vault, again, tmp_path))
    assert again.prompts == []


def test_backfill_stops_on_a_failing_reviewer_and_while_paused(tmp_path, vault):
    _old_chats(tmp_path)

    class Failing:
        async def __call__(self, prompt: str) -> Any:
            return None

    state = asyncio.run(backfill.run_once(vault, Failing(), tmp_path))
    assert not state["done"] and state["offset"] == 0
    vault.pause_learning("forever")
    reviewer = Scripted()
    state = asyncio.run(backfill.run_once(vault, reviewer, tmp_path))
    assert reviewer.prompts == [] and not state["done"]


def test_a_reviewer_that_is_down_does_not_use_up_the_backfill(tmp_path, vault):
    """Thirty boots with a dead reviewer ended the pass as done with nothing read."""
    _old_chats(tmp_path)

    class Failing:
        async def __call__(self, prompt: str) -> Any:
            return None

    for _ in range(backfill.MAX_CALLS + 5):
        state = asyncio.run(backfill.run_once(vault, Failing(), tmp_path))
    assert not state["done"] and state["calls"] == 0 and state["offset"] == 0

    reviewer = Scripted(
        [
            {
                "op": "add",
                "kind": "profile",
                "text": "The user lives in Hamburg.",
                "evidence": "I live in Hamburg",
            }
        ]
    )
    state = asyncio.run(backfill.run_once(vault, reviewer, tmp_path))
    assert state["done"] and state["written"] == 1 and state["calls"] == 1
