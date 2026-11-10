"""Memory trust: where a memory came from, scopes, imports from elsewhere, export.

The learning loop records the message a memory was learned from; a memory can
be marked work or private; another assistant's export becomes a review list;
one download holds everything.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.core.chat_turn import ChatCompletion, ChatTurn, current_chat_turn
from dodaios.memory.learning import notebook as notebook_module
from dodaios.memory.learning.loop import JarvisLearningLoop
from dodaios.memory.learning.notebook import JarvisNotebook
from dodaios.memory.learning.review import Turn
from dodaios.memory.vault import foreign_import, portable, reconcile
from dodaios.memory.vault import runtime as vault_runtime
from dodaios.memory.vault.store import MemoryVault
from dodaios.ui.web import personal_memory_routes
from dodaios.ui.web.personal_memory_routes import router


class ScriptedReviewer:
    def __init__(self, *replies: Any) -> None:
        self._replies = list(replies)
        self.prompts: list[str] = []

    async def __call__(self, prompt: str) -> Any:
        self.prompts.append(prompt)
        return self._replies.pop(0) if self._replies else []


@pytest.fixture
def vault(tmp_path: Path):
    v = MemoryVault(tmp_path / "vault.db")
    vault_runtime.set_active(v)
    yield v
    vault_runtime.set_active(None)


@pytest.fixture(autouse=True)
def _no_active_notebook():
    notebook_module.set_active(None)
    yield
    notebook_module.set_active(None)


@pytest.fixture
def client(vault) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _loop(tmp_path: Path, reviewer: ScriptedReviewer) -> JarvisLearningLoop:
    book = JarvisNotebook(tmp_path / "society", budgets={"user": 600, "memory": 600})
    return JarvisLearningLoop(book, ScriptedReviewer(), vault_reviewer=reviewer)


# -- where it came from ---------------------------------------------------------


def test_anchor_for_picks_the_line_the_evidence_quotes():
    anchors = [
        {"user": "My sister Mia lives in Rome.", "session_id": "s1", "message_seq": 4},
        {"user": "I work as a nurse at night.", "session_id": "s1", "message_seq": 9},
    ]
    assert reconcile.anchor_for("work as a nurse", anchors) == {
        "session_id": "s1",
        "message_seq": 9,
    }
    assert reconcile.anchor_for("not said anywhere", anchors) == {}
    assert reconcile.anchor_for("", anchors) == {}


@pytest.mark.asyncio
async def test_a_reviewed_memory_records_the_message_it_came_from(tmp_path, vault, monkeypatch):
    posted: list[list[dict[str, Any]]] = []

    async def fake_post(receipts):
        posted.append(receipts)

    monkeypatch.setattr("dodaios.agent_chat.lead.post_learned", fake_post)
    reviewer = ScriptedReviewer(
        [
            {
                "op": "add",
                "kind": "profile",
                "text": "The user lives in Hamburg.",
                "evidence": "I live in Hamburg",
            }
        ]
    )
    loop = _loop(tmp_path, reviewer)
    said = "By the way, I live in Hamburg with my wife Lea."
    events = [
        {"seq": 41, "kind": "user_message", "payload": {"text": said}},
        {"seq": 42, "kind": "assistant_text", "payload": {"text": "Nice."}},
    ]
    session = SimpleNamespace(session_id="lead-1")
    turn = ChatTurn("lead-1", "turn-7", said, True, "trace")
    await loop.chat_turn_completed(session, ChatCompletion(turn, json.dumps(events)))
    assert await loop.review("chat:lead-1") == 1

    memory = vault.list()[0]
    assert memory.source["session_id"] == "lead-1"
    assert memory.source["turn_id"] == "turn-7"
    assert memory.source["message_seq"] == 41
    assert memory.source["channel"] == "chat"
    assert memory.source["via"] == "review"
    # The conversation notice carries the same link.
    assert posted[0][0]["message_seq"] == 41
    assert posted[0][0]["turn_id"] == "turn-7"
    assert posted[0][0]["evidence"] == "I live in Hamburg"


def test_explicit_request_records_its_anchor(tmp_path, vault):
    loop = _loop(tmp_path, ScriptedReviewer())
    anchor = Turn(user="x", channel="chat", session_id="lead-1", turn_id="t3", seq=12).anchor()
    assert loop._keep_request("remember that I drink tea", "I prefer tea.", anchor)
    source = vault.list()[0].source
    assert source["message_seq"] == 12 and source["turn_id"] == "t3"
    assert source["via"] == "explicit request"


def test_remember_tool_inside_a_chat_turn_links_to_that_turn(vault):
    token = current_chat_turn.set(ChatTurn("lead-1", "turn-9", "note that", True, "tr"))
    try:
        vault_runtime.remember_explicitly("The user's sister is called Mia.", evidence="Mia")
    finally:
        current_chat_turn.reset(token)
    source = vault.list()[0].source
    assert source["session_id"] == "lead-1" and source["turn_id"] == "turn-9"


def test_turn_anchor_leaves_out_empty_values():
    assert Turn(user="hi").anchor() == {"channel": "voice"}


# -- scope -------------------------------------------------------------------------


def test_scope_marks_filters_and_keeps_private_from_agents(client, vault):
    work = vault.remember("I prefer short status updates.", "preference").memory
    private = vault.remember("I prefer calls after 8 pm.", "preference").memory
    assert client.put(f"/api/memory/vault/items/{work.id}/scope", json={"scope": "work"}).json()[
        "ok"
    ]
    assert client.put(
        f"/api/memory/vault/items/{private.id}/scope", json={"scope": "private"}
    ).json()["ok"]
    rows = {r["text"]: r["scope"] for r in client.get("/api/memory/vault/items").json()["items"]}
    assert rows == {
        "I prefer short status updates.": "work",
        "I prefer calls after 8 pm.": "private",
    }
    assert (
        client.put(f"/api/memory/vault/items/{work.id}/scope", json={"scope": "x"}).status_code
        == 422
    )
    assert (
        client.put("/api/memory/vault/items/nope/scope", json={"scope": "work"}).status_code == 404
    )

    # The lead reads all of it; the user's agents never see a private memory.
    block = vault_runtime.prompt_block()
    assert "short status updates" in block and "calls after 8 pm" in block
    agents = vault_runtime.agent_block()
    assert "short status updates" in agents and "calls after 8 pm" not in agents


def test_scope_survives_an_edit_and_blocks_a_duplicate(vault):
    memory = vault.remember("I work at Acme.", "profile").memory
    assert vault.set_scope(memory.id, "work")
    again = vault.remember("I work at Acme.", "profile")
    assert again.action == "existing" and again.memory.id == memory.id
    newer = vault.supersede(memory.id, "I work at Acme as a designer.").memory
    assert newer.scope == "work"
    with pytest.raises(ValueError):
        vault.set_scope(newer.id, "elsewhere")


# -- importing from another assistant -------------------------------------------


def test_parse_a_markdown_memory_list():
    text = (
        "# Saved memories\n\n"
        "- Prefers dark mode in every app.\n"
        "* Has a dog called Bruno.\n"
        "1. Lives in Lisbon.\n"
        "\n- ok\n"
    )
    parsed = foreign_import.parse_upload("memories.md", text)
    assert parsed.facts == [
        "Prefers dark mode in every app.",
        "Has a dog called Bruno.",
        "Lives in Lisbon.",
    ]
    assert parsed.said == [] and parsed.shape == "list"


def test_parse_skips_html_comments_across_lines():
    text = "- Likes jazz.\n<!-- a note\nthat spans lines -->\n- Owns a bike. <!-- id --!>\n"
    assert foreign_import.parse_upload("m.md", text).facts == ["Likes jazz.", "Owns a bike."]


def test_parse_json_lists_and_objects():
    assert foreign_import.parse_upload("m.json", '["Likes jazz.", "Owns a bike."]').facts == [
        "Likes jazz.",
        "Owns a bike.",
    ]
    data = {"memories": [{"memory": "Speaks Portuguese."}, {"content": "Runs on Sundays."}]}
    assert foreign_import.parse_upload("export.json", json.dumps(data)).facts == [
        "Speaks Portuguese.",
        "Runs on Sundays.",
    ]


def test_parse_a_chat_export_keeps_only_the_persons_messages():
    data = [
        {
            "title": "Trip",
            "messages": [
                {"role": "user", "content": "My daughter Ana turns 7 in May."},
                {"role": "assistant", "content": "Lovely! Any plans?"},
                {"author": {"role": "user"}, "content": {"parts": ["I work as a nurse."]}},
            ],
        },
        {
            "mapping": {
                "a": {"message": {"author": {"role": "user"}, "content": {"parts": ["Hi"]}}},
                "b": {"message": {"author": {"role": "assistant"}, "content": {"parts": ["Yo"]}}},
            }
        },
    ]
    parsed = foreign_import.parse_upload("conversations.json", json.dumps(data))
    assert parsed.facts == []
    assert parsed.said == ["My daughter Ana turns 7 in May.", "I work as a nurse.", "Hi"]
    assert parsed.shape == "conversations"


def test_parse_a_plain_text_transcript():
    text = "User: I live in Porto with my partner.\nAssistant: Nice city.\nUser: thanks\n"
    parsed = foreign_import.parse_upload("chat.txt", text)
    assert parsed.said == ["I live in Porto with my partner.", "thanks"]
    assert parsed.facts == []


def test_our_own_export_reads_back_as_a_list(vault):
    vault.remember("I prefer tea.", "preference")
    md = portable.markdown_files(vault)["preference.md"]
    assert foreign_import.parse_upload("preference.md", md).facts == ["I prefer tea."]


@pytest.mark.asyncio
async def test_extract_reads_only_signal_messages_in_chunks():
    ask = ScriptedReviewer([{"text": "The user works as a nurse.", "kind": "profile"}])
    said = ["What's the weather?", "I work as a nurse at the city hospital."]
    facts, answered = await foreign_import.extract(said, ask)
    assert answered and facts == [{"text": "The user works as a nurse.", "kind": "profile"}]
    assert len(ask.prompts) == 1
    assert "weather" not in ask.prompts[0]


def test_parse_extracted_drops_bad_rows():
    reply = json.dumps(
        {
            "facts": [
                {"text": "Likes tea.", "kind": "preference"},
                {"text": ""},
                "x",
                {"text": "A" * 400},
            ]
        }
    )
    assert foreign_import.parse_extracted(reply) == [{"text": "Likes tea.", "kind": "preference"}]
    with pytest.raises(ValueError):
        foreign_import.parse_extracted("no json")


def test_import_read_and_save_a_list(client, vault):
    vault.remember("Lives in Lisbon.", "profile")
    text = "- Lives in Lisbon.\n- Has a dog called Bruno.\n- Has a dog called Bruno.\n"
    read = client.post("/api/memory/vault/import/read", json={"name": "m.txt", "text": text})
    assert read.status_code == 200
    body = read.json()
    assert body["shape"] == "list" and body["model_missing"] is False
    assert [(c["text"], c["exists"]) for c in body["candidates"]] == [
        ("Lives in Lisbon.", True),
        ("Has a dog called Bruno.", False),
    ]
    saved = client.post(
        "/api/memory/vault/import/save",
        json={
            "name": "m.txt",
            "scope": "private",
            "items": [{"text": "Has a dog called Bruno.", "kind": "relationship"}],
        },
    ).json()
    assert saved == {"added": 1, "existing": 0, "refused": 0, "failed": 0}
    memory = next(m for m in vault.list() if "Bruno" in m.text)
    assert memory.origin == "imported" and memory.scope == "private"
    assert memory.source == {"via": "import", "file": "m.txt"}
    assert (
        client.post(
            "/api/memory/vault/import/save", json={"items": [], "scope": "nowhere"}
        ).status_code
        == 422
    )


def test_import_read_a_chat_export_uses_the_extractor(client, vault, monkeypatch):
    ask = ScriptedReviewer([{"text": "The user works as a nurse.", "kind": "profile"}])
    monkeypatch.setattr(personal_memory_routes, "_extractor", lambda: ask)
    data = {"messages": [{"role": "user", "content": "I work as a nurse at the city hospital."}]}
    body = client.post(
        "/api/memory/vault/import/read", json={"name": "c.json", "text": json.dumps(data)}
    ).json()
    assert body["shape"] == "conversations" and body["messages"] == 1
    assert [(c["text"], c["extracted"]) for c in body["candidates"]] == [
        ("The user works as a nurse.", True)
    ]


def test_import_read_without_a_model_says_so(client, vault, monkeypatch):
    monkeypatch.setattr(personal_memory_routes, "_extractor", lambda: None)
    data = {"messages": [{"role": "user", "content": "I work as a nurse at the city hospital."}]}
    body = client.post(
        "/api/memory/vault/import/read", json={"name": "c.json", "text": json.dumps(data)}
    ).json()
    assert body["candidates"] == [] and body["model_missing"] is True


# -- export everything -------------------------------------------------------------


def test_export_all_holds_json_markdown_and_a_reimportable_bundle(client, vault, tmp_path):
    vault.remember("I prefer tea.", "preference")
    response = client.get("/api/memory/vault/export?format=all")
    assert response.status_code == 200
    assert "-all.zip" in response.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        names = set(zf.namelist())
        listed = json.loads(zf.read("memories.json"))
    assert {
        "manifest.json",
        "memories.json",
        "readable/MEMORY.md",
        "readable/preference.md",
    } <= names
    assert listed["memories"][0]["text"] == "I prefer tea."

    other = MemoryVault(tmp_path / "other.db")
    report = portable.import_bundle(other, response.content)
    assert report.added == 1 and not report.errors
