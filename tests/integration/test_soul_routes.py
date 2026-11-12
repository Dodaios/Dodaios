"""Integration tests for /api/soul — the assistant's profile page.

Real files under ``tmp_path``: SOUL.md in the data dir, the instructions file
next to it, and the notebooks in a throwaway vault. No provider, no mocks.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import dodaios.core.config as core_config
import dodaios.society.memory as society_memory
from dodaios.brain import agent_instructions, identity
from dodaios.core.bus import EventBus
from dodaios.core.config import JarvisConfig
from dodaios.memory.learning import notebook as notebook_module
from dodaios.memory.learning.notebook import JarvisNotebook
from dodaios.memory.soul import Soul
from dodaios.memory.templates import render_soul_md, render_user_md
from dodaios.memory.user_profile import UserProfile
from dodaios.memory.vault import runtime as vault_runtime
from dodaios.memory.vault.store import MemoryVault
from dodaios.ui.web.server import WebServer


@pytest.fixture(autouse=True)
def _isolate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(core_config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(society_memory, "resolve_society_vault", lambda cfg: tmp_path / "vault")
    notebook_module.set_active(None)
    vault_runtime.set_active(None)
    identity.invalidate_cache()
    yield
    notebook_module.set_active(None)
    vault_runtime.set_active(None)


@pytest.fixture
def server() -> WebServer:
    cfg = JarvisConfig()
    cfg.ui.dev_mode = True
    bus = EventBus()
    s = WebServer(cfg, bus=bus)
    s.app.state.config = cfg
    s.app.state.bus = bus
    return s


def _write_soul(text: str | None = None) -> Path:
    path = identity.soul_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text is not None else render_soul_md(), encoding="utf-8")
    return path


def _files(body: dict) -> dict[str, dict]:
    return {f["id"]: f for f in body["files"]}


def test_a_fresh_install_lists_every_file_as_missing_and_creates_none(
    server: WebServer, tmp_path: Path
) -> None:
    with TestClient(server.app) as client:
        body = client.get("/api/soul").json()
    files = _files(body)
    assert list(files) == ["soul", "instructions", "memory", "user"]
    assert all(not f["exists"] for f in files.values())
    assert files["soul"]["filename"] == "SOUL.md"
    assert files["instructions"]["filename"] == agent_instructions.instructions_filename(
        server.app.state.config
    )
    assert files["instructions"]["template"].strip()
    assert body["activity"] == []
    assert body["learning"] is False
    # A GET never seeds anything.
    assert not (tmp_path / "vault").exists()
    assert not identity.soul_path().exists()


def test_the_character_is_split_into_labelled_rows(server: WebServer) -> None:
    _write_soul()
    with TestClient(server.app) as client:
        soul = _files(client.get("/api/soul").json())["soul"]
    assert soul["exists"] is True and soul["editable"] is True
    who = {row["label"]: row["text"] for row in soul["character"]["who"]}
    assert "Role" in who and "Vibe" in who
    # The name line is managed by the wake word, so it is not a character row.
    assert "Name" not in who
    assert soul["character"]["tone"] and soul["character"]["limits"]
    assert "## Who I am" in soul["content"]
    assert not soul["content"].startswith("---")  # the frontmatter stays out of the editor


def test_saving_soul_md_keeps_the_frontmatter_and_the_learned_notes(server: WebServer) -> None:
    path = _write_soul()
    soul = Soul.load(path)
    soul.append_calibration("Answers in short spoken sentences.")
    soul.save()
    edited = Soul.load(path).body.replace(
        "Helpful but not obsequious.", "Calm, warm and to the point."
    )
    with TestClient(server.app) as client:
        resp = client.put("/api/soul/file", json={"content": edited})
        assert resp.status_code == 200
        saved = _files(resp.json())["soul"]
    assert "Calm, warm and to the point." in saved["content"]
    assert [e["text"] for e in saved["learned"]] == ["Answers in short spoken sentences."]
    raw = path.read_text(encoding="utf-8")
    assert raw.startswith("---") and "subject_type: agent" in raw
    # The prompt sees the edit on its next build.
    identity.invalidate_cache()
    assert "Calm, warm and to the point." in identity.character_block(path=path)


def test_saving_refuses_an_empty_or_missing_soul(server: WebServer) -> None:
    with TestClient(server.app) as client:
        assert client.put("/api/soul/file", json={"content": "x"}).status_code == 404
        _write_soul()
        assert client.put("/api/soul/file", json={"content": "   "}).status_code == 400


def test_notebooks_and_activity_come_from_the_vault(server: WebServer, tmp_path: Path) -> None:
    book = JarvisNotebook(tmp_path / "vault")
    book.keep_explicit("Ruben's sister is called Lena.", via_tool=True, evidence="merk dir das")
    book.apply(target="user", operation="add", text="The user prefers short answers.")
    with TestClient(server.app) as client:
        body = client.get("/api/soul").json()
    files = _files(body)
    memory = files["memory"]["entries"]
    assert len(memory) == 1 and memory[0]["explicit"] is True
    assert "Lena" in memory[0]["text"]
    assert [e["text"] for e in files["user"]["entries"]] == ["The user prefers short answers."]
    assert files["memory"]["editable"] is False
    # Newest first, with what the person said.
    assert [a["target"] for a in body["activity"]] == ["user", "memory"]
    assert body["activity"][1]["evidence"] == "merk dir das"


def test_forgetting_a_note_needs_the_running_loop_and_is_ledgered(
    server: WebServer, tmp_path: Path
) -> None:
    book = JarvisNotebook(tmp_path / "vault")
    book.apply(target="memory", operation="add", text="Builds Personal Jarvis.")
    entry_id = book.entries()["memory"][0].id
    with TestClient(server.app) as client:
        assert client.delete(f"/api/soul/entries/memory/{entry_id}").status_code == 503
        notebook_module.set_active(book)
        assert client.delete("/api/soul/entries/memory/nope").status_code == 404
        assert client.delete(f"/api/soul/entries/bogus/{entry_id}").status_code == 422
        resp = client.delete(f"/api/soul/entries/memory/{entry_id}")
        assert resp.status_code == 200
        assert _files(resp.json())["memory"]["entries"] == []
        assert resp.json()["activity"][0]["operation"] == "remove"
        assert resp.json()["activity"][0]["text"] == "Builds Personal Jarvis."
    ledger = (book.folder / notebook_module.LEDGER_NAME).read_text(encoding="utf-8")
    last = json.loads(ledger.strip().splitlines()[-1])
    assert last["source"] == "soul page: forgotten by the user"


def test_the_initiative_level_is_saved_applied_live_and_lists_dated_plans(
    server: WebServer, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import date, timedelta

    from dodaios.brain import proactivity
    from dodaios.core.config import load_config

    config_file = tmp_path / "jarvis.toml"
    config_file.write_text("[brain]\n", encoding="utf-8")
    monkeypatch.setattr(core_config, "resolve_config_path", lambda: config_file)
    proactivity.reset_applied_level()
    soon = (date.today() + timedelta(days=2)).isoformat()
    book = JarvisNotebook(tmp_path / "vault")
    book.apply(target="user", operation="add", text=f"The user's launch is on {soon}.")
    notebook_module.set_active(book)
    try:
        with TestClient(server.app) as client:
            initiative = client.get("/api/soul").json()["initiative"]
            assert initiative["level"] == "balanced"
            assert initiative["levels"] == ["off", "balanced", "high"]
            assert initiative["upcoming"] == [
                {"date": soon, "text": f"The user's launch is on {soon}."}
            ]
            assert client.put("/api/soul/initiative", json={"level": "loud"}).status_code == 422
            resp = client.put("/api/soul/initiative", json={"level": "off"})
            assert resp.status_code == 200
            # Off: nothing is pointed at, so the page lists nothing either.
            assert resp.json()["initiative"] == {
                "level": "off",
                "levels": ["off", "balanced", "high"],
                "upcoming": [],
            }
        assert load_config(config_file=config_file).brain.proactivity == "off"
        assert proactivity.current_level(server.app.state.config) == "off"
        assert server.app.state.config.brain.proactivity == "off"
    finally:
        proactivity.reset_applied_level()


# ---------------------------------------------------------------- memory vault
#
# Since ADR-0044 a review writes into the memory vault, not into the notebooks.
# Regression (2026-11-12): the page kept reading the notebooks alone and showed
# "0 notes" and "0 things remembered" on an install whose vault held what the
# assistant had learned that same day.


class _Seat:
    def ledger_fields(self) -> dict[str, str]:
        return {
            "seat": "claude-cli/claude-test",
            "seat_label": "Claude Code",
            "runner": "claude-cli",
            "billing": "subscription",
        }


class _ScriptedReviewer:
    """Stands in for the model: answers each review with the next scripted reply."""

    def __init__(self, *replies: list[dict]) -> None:
        self._replies = list(replies)
        self.calls = 0
        self.last_choice = _Seat()

    async def __call__(self, prompt: str) -> list[dict]:
        self.calls += 1
        return self._replies.pop(0) if self._replies else []


@pytest.fixture
def memory_vault(tmp_path: Path) -> Iterator[MemoryVault]:
    vault = MemoryVault(tmp_path / "data" / "memory" / "vault.db")
    vault_runtime.set_active(vault)
    yield vault
    vault_runtime.set_active(None)


def _write_profile(**fields: object) -> Path:
    path = identity.soul_path().parent / "USER.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_user_md(), encoding="utf-8")
    profile = UserProfile.load(path)
    for name, value in fields.items():
        profile.set("identity", name, value)
    profile.save()
    return path


SAID = "By the way, I live in Hamburg and I build the Dodaios project."


def test_a_reviewed_conversation_with_a_personal_fact_reaches_the_page(
    server: WebServer, tmp_path: Path, memory_vault: MemoryVault
) -> None:
    import asyncio

    from dodaios.memory.learning.loop import JarvisLearningLoop
    from dodaios.memory.learning.review import Turn
    from dodaios.memory.learning.signals import has_signal

    assert has_signal(SAID)
    book = JarvisNotebook(tmp_path / "vault")
    notebook_reviewer = _ScriptedReviewer()
    vault_reviewer = _ScriptedReviewer(
        [
            {
                "op": "add",
                "kind": "profile",
                "text": "The user lives in Hamburg.",
                "entities": ["Hamburg"],
                "evidence": "I live in Hamburg",
            },
            {
                "op": "add",
                "kind": "procedural",
                "text": "Reports for the Dodaios project come back as a short message.",
                "evidence": "I build the Dodaios project",
            },
        ]
    )
    loop = JarvisLearningLoop(book, notebook_reviewer, vault_reviewer=vault_reviewer)

    async def talk_and_review() -> int:
        loop.record("chat:a", Turn(user=SAID, channel="chat", session_id="a"))
        return await loop.review("chat:a", reason="quiet conversation")

    assert asyncio.run(talk_and_review()) == 2
    # The review asked the vault's reviewer and left the notebooks alone ...
    assert (vault_reviewer.calls, notebook_reviewer.calls) == (1, 0)
    assert not any(book.entries().values())

    with TestClient(server.app) as client:
        body = client.get("/api/soul").json()
    files = _files(body)
    # ... and the page shows what it learned, each note on its page.
    assert [e["text"] for e in files["user"]["entries"]] == ["The user lives in Hamburg."]
    assert [e["text"] for e in files["memory"]["entries"]] == [
        "Reports for the Dodaios project come back as a short message."
    ]
    learned = files["user"]["entries"][0]
    assert learned["store"] == "vault" and learned["explicit"] is False
    assert learned["at_ms"] and files["user"]["updated_ms"] == learned["at_ms"]
    assert files["user"]["exists"] is True and files["user"]["store"] == "vault"
    assert "source" not in learned
    # "Recently learned" names the change, the person's words and the seat.
    about_you = next(a for a in body["activity"] if a["target"] == "user")
    assert about_you["operation"] == "add"
    assert about_you["text"] == "The user lives in Hamburg."
    assert about_you["evidence"] == "I live in Hamburg"
    assert about_you["source"] == "review: quiet conversation"
    assert about_you["billing"] == "subscription"
    # The ledger line names the seat that answered: the vault reviewer's.
    assert body["last_review"]["outcome"] == "answered"
    assert body["last_review"]["changes"] == 2
    assert body["last_review"]["seat_label"] == "Claude Code"


def test_the_user_page_starts_with_the_profile_and_shows_its_imported_copy_once(
    server: WebServer, memory_vault: MemoryVault
) -> None:
    _write_profile(name="Ruben", about="Builds Dodaios.", timezone="Asia/Tokyo", languages=["en"])
    imported = {"via": "legacy-import", "from": "user-profile", "file": "workspace/USER.md"}
    memory_vault.remember(
        "The user's name is Ruben.", "profile", origin="imported", source=imported
    )
    # An imported line the profile no longer states is still what the vault
    # says, so it stays ("en" inside "Ben" is not the language "en").
    memory_vault.remember(
        "How the user wants to be addressed: Ben.", "profile", origin="imported", source=imported
    )
    memory_vault.remember("The user prefers short answers.", "preference", origin="inferred")
    with TestClient(server.app) as client:
        user = _files(client.get("/api/soul").json())["user"]
    lines = [(e["store"], e.get("field"), e["text"]) for e in user["entries"]]
    assert lines[:4] == [
        ("profile", "name", "Ruben"),
        ("profile", "about", "Builds Dodaios."),
        ("profile", "languages", "en"),
        ("profile", "timezone", "Asia/Tokyo"),
    ]
    # Both were recorded within the same second, so their order is not fixed.
    assert sorted(lines[4:]) == [
        ("vault", None, "How the user wants to be addressed: Ben."),
        ("vault", None, "The user prefers short answers."),
    ]
    assert user["entries"][0]["id"] == "profile:identity.name"
    assert user["entries"][2]["id"] == "profile:identity.languages:0"


def test_the_profile_shows_on_the_user_page_without_a_vault(server: WebServer) -> None:
    _write_profile(name="Ruben")
    with TestClient(server.app) as client:
        files = _files(client.get("/api/soul").json())
    assert [e["text"] for e in files["user"]["entries"]] == ["Ruben"]
    assert files["user"]["exists"] is True and files["user"]["store"] == "notebook"
    assert files["memory"]["exists"] is False


def test_a_notebook_note_the_vault_holds_is_shown_once_and_others_follow(
    server: WebServer, tmp_path: Path, memory_vault: MemoryVault
) -> None:
    book = JarvisNotebook(tmp_path / "vault")
    book.apply(target="user", operation="add", text="The user prefers short answers.")
    book.apply(target="user", operation="add", text="The user rides a bike to work.")
    memory_vault.remember("The user prefers short answers.", "preference", origin="imported")
    with TestClient(server.app) as client:
        user = _files(client.get("/api/soul").json())["user"]
    assert [(e["store"], e["text"]) for e in user["entries"]] == [
        ("vault", "The user prefers short answers."),
        ("notebook", "The user rides a bike to work."),
    ]


def test_forgetting_a_memory_on_the_page_erases_it_from_the_vault(
    server: WebServer, tmp_path: Path, memory_vault: MemoryVault
) -> None:
    _write_profile(name="Ruben")
    book = JarvisNotebook(tmp_path / "vault")
    book.apply(target="user", operation="add", text="The user lives in Hamburg.")
    notebook_module.set_active(book)
    kept = memory_vault.remember("The user has a dog.", "profile", origin="inferred").memory
    gone = memory_vault.remember("The user lives in Hamburg.", "profile", origin="imported").memory
    assert kept is not None and gone is not None
    with TestClient(server.app) as client:
        resp = client.delete(f"/api/soul/entries/user/{gone.id}")
        assert resp.status_code == 200
        texts = [e["text"] for e in _files(resp.json())["user"]["entries"]]
        # The profile line stays, and the notebook note the memory came from
        # does not come back in its place.
        assert texts == ["Ruben", "The user has a dog."]
        # A profile line is not a note: the Profile page edits it.
        assert client.delete("/api/soul/entries/user/profile:identity.name").status_code == 404
    assert [m.text for m in memory_vault.list()] == ["The user has a dog."]
    assert book.entries()["user"] == []


def test_recently_learned_leaves_out_what_was_only_imported(
    server: WebServer, memory_vault: MemoryVault
) -> None:
    memory_vault.remember("The user's name is Ruben.", "profile", origin="imported")
    learned = memory_vault.remember(
        "The user prefers short answers.",
        "preference",
        origin="inferred",
        source={"via": "review", "reason": "call ended", "evidence": "keep it short"},
    ).memory
    assert learned is not None
    memory_vault.pin(learned.id)
    with TestClient(server.app) as client:
        activity = client.get("/api/soul").json()["activity"]
    assert [(a["operation"], a["text"]) for a in activity] == [
        ("add", "The user prefers short answers.")
    ]
    assert activity[0]["source"] == "review: call ended"
