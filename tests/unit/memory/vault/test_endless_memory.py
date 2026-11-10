"""Memory for the one endless conversation: due dates, the learning pause, pinned corrections."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.memory.learning import notebook as notebook_module
from dodaios.memory.learning.loop import JarvisLearningLoop
from dodaios.memory.learning.notebook import JarvisNotebook
from dodaios.memory.learning.review import Turn
from dodaios.memory.vault import reconcile
from dodaios.memory.vault import runtime as vault_runtime
from dodaios.memory.vault.store import MemoryVault
from dodaios.ui.web.personal_memory_routes import router


class Clock:
    def __init__(self, value: str = "2026-11-09T09:00:00+00:00") -> None:
        self.value = value

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


@pytest.fixture(autouse=True)
def _no_notebook():
    notebook_module.set_active(None)
    yield
    notebook_module.set_active(None)


def test_upcoming_lists_due_memories_overdue_first(vault):
    vault.remember("Dentist appointment.", "project", due_at="2026-11-12T09:00:00+00:00")
    vault.remember("Tax return deadline.", "project", due_at="2026-11-05T09:00:00+00:00")
    vault.remember("Trip to Taiwan.", "project", due_at="2027-03-01T09:00:00+00:00")
    vault.remember("Likes jazz.", "preference")
    assert [m.text for m in vault.upcoming(days=14)] == [
        "Tax return deadline.",
        "Dentist appointment.",
    ]
    notes = vault_runtime.dated_notes(days=14)
    assert [str(d) for d, _ in notes] == ["2026-11-05", "2026-11-12"]


def test_due_date_survives_an_update(vault, clock):
    old = vault.remember("Launch on Friday.", "project", due_at="2026-11-13T09:00:00+00:00").memory
    clock.value = "2026-11-10T09:00:00+00:00"
    new = vault.supersede(old.id, "Launch on Friday, with the press kit.").memory
    assert new.due_at == "2026-11-13T09:00:00+00:00"


def test_an_old_vault_file_gains_the_due_column(tmp_path):
    path = tmp_path / "old.db"
    db = sqlite3.connect(path)
    db.executescript(
        "CREATE TABLE memory (id TEXT PRIMARY KEY, content_hash TEXT NOT NULL, kind TEXT NOT NULL, "
        "text TEXT NOT NULL, scope TEXT NOT NULL DEFAULT 'global', valid_from TEXT, valid_to TEXT, "
        "recorded_at TEXT NOT NULL, expired_at TEXT, supersedes_id TEXT, origin TEXT NOT NULL, "
        "source TEXT NOT NULL DEFAULT '{}', confidence REAL NOT NULL DEFAULT 1.0, "
        "sensitivity TEXT NOT NULL DEFAULT 'normal', pinned INTEGER NOT NULL DEFAULT 0, "
        "use_count INTEGER NOT NULL DEFAULT 0, last_used_at TEXT);"
    )
    db.close()
    with MemoryVault(path) as v:
        assert v.remember("Still works.", "profile").action == "added"
        assert v.get_meta("schema_version") == "2"


def test_learning_pause_drops_reviews_but_keeps_explicit_saves(tmp_path, vault, clock):
    class Reviewer:
        calls = 0

        async def __call__(self, prompt: str) -> Any:
            Reviewer.calls += 1
            return []

    loop = JarvisLearningLoop(
        JarvisNotebook(tmp_path / "society", budgets={"user": 600, "memory": 600}),
        Reviewer(),
        vault_reviewer=Reviewer(),
    )
    vault.pause_learning("2026-11-09T10:00:00+00:00")
    assert vault_runtime.learning_paused()

    import asyncio

    loop.record(
        "chat:a", Turn(user="By the way, I live in Hamburg with my wife Lea.", channel="chat")
    )
    assert asyncio.run(loop.review("chat:a")) == 0
    assert Reviewer.calls == 0
    assert loop._keep_request("remember that I drink tea", "I drink tea.") == 1

    clock.value = "2026-11-09T10:00:01+00:00"
    assert not vault_runtime.learning_paused()


def test_corrections_pin_themselves_and_plans_get_a_date(vault):
    said = ["No, I meant: never send emails without asking me first. The launch is on 2026-11-20."]
    ops, rejected = reconcile.validate(
        [
            {
                "op": "add",
                "kind": "procedural",
                "text": "Never send emails without asking first.",
                "evidence": "never send emails without asking me first",
                "pin": True,
            },
            {
                "op": "add",
                "kind": "project",
                "text": "The launch is on 2026-11-20.",
                "evidence": "The launch is on 2026-11-20",
                "due": "2026-11-20",
                "pin": True,
            },
        ],
        user_texts=said,
        shown=[],
    )
    assert not rejected
    assert [o.pin for o in ops] == [True, False], "only a standing rule may pin itself"
    reconcile.apply(vault, ops, source={"via": "test"})
    rows = {m.text: m for m in vault.list()}
    assert rows["Never send emails without asking first."].pinned
    assert rows["The launch is on 2026-11-20."].due_at == "2026-11-20T09:00:00+00:00"
    assert "Never send emails" in vault.profile_block()


def test_pause_and_upcoming_routes(vault):
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    vault.remember("Dentist appointment.", "project", due_at="2026-11-12T09:00:00+00:00")
    assert [i["text"] for i in client.get("/api/memory/vault/upcoming").json()["items"]] == [
        "Dentist appointment."
    ]
    assert client.put("/api/memory/vault/pause", json={"minutes": 60}).json()["paused"] is True
    assert client.get("/api/memory/vault/pause").json()["until"] == "2026-11-09T10:00:00+00:00"
    assert (
        client.put("/api/memory/vault/pause", json={"forever": True}).json()["until"] == "forever"
    )
    assert client.put("/api/memory/vault/pause", json={}).json() == {"paused": False, "until": None}
    assert json.dumps(vault.audit_log()).count("pause") >= 2


def test_agents_read_only_preferences_and_rules(vault):
    vault.remember("Prefers short answers.", "preference")
    vault.remember("Never push to main without asking.", "procedural", pinned=True)
    vault.remember("Lives in Berlin.", "profile")
    vault.remember("Has a chronic illness.", "preference", sensitivity="sensitive")
    block = vault_runtime.agent_block()
    assert block.splitlines()[2] == "- Never push to main without asking."
    assert "Prefers short answers." in block
    assert "Berlin" not in block and "illness" not in block
    vault_runtime.set_active(None)
    assert vault_runtime.agent_block() == ""


def test_voice_recall_is_bounded_and_quiet_without_matches(vault, monkeypatch):
    import asyncio

    from dodaios.realtime import session as realtime_session

    vault.remember("We hiked the Zugspitze last summer.", "episode")
    assert "Zugspitze" in asyncio.run(realtime_session._voice_memory_recall("Zugspitze hike"))
    assert asyncio.run(realtime_session._voice_memory_recall("")) == ""

    def slow(_text: str, **_kw: Any) -> str:
        import time

        time.sleep(0.5)
        return "late"

    monkeypatch.setattr(vault_runtime, "turn_block", slow)
    assert asyncio.run(realtime_session._voice_memory_recall("anything")) == ""


def test_realtime_instructions_carry_the_recall_block():
    from dodaios.realtime import session as realtime_session

    text = realtime_session._session_instructions(
        "en", memory_recall="## Possibly relevant memories\n- Owns a beagle."
    )
    assert "Owns a beagle." in text
