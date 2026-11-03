"""HTTP API of the personal memory vault (``personal_memory_routes``)."""

from __future__ import annotations

import io
import zipfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.memory.vault import runtime as vault_runtime
from dodaios.memory.vault.store import MemoryVault
from dodaios.ui.web.personal_memory_routes import router


@pytest.fixture
def vault(tmp_path):
    v = MemoryVault(tmp_path / "vault.db")
    vault_runtime.set_active(v)
    yield v
    vault_runtime.set_active(None)


@pytest.fixture
def client(vault) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_without_a_vault_the_api_says_so():
    vault_runtime.set_active(None)
    app = FastAPI()
    app.include_router(router)
    assert TestClient(app).get("/api/memory/vault").status_code == 503


def test_add_edit_history_pin_end_forget(client, vault):
    added = client.post("/api/memory/vault/items", json={"text": "I prefer tea over coffee."})
    assert added.status_code == 200
    item = added.json()["item"]
    assert item["kind"] == "preference" and item["origin"] == "user"

    edited = client.put(f"/api/memory/vault/items/{item['id']}", json={"text": "I prefer coffee."})
    new_id = edited.json()["item"]["id"]
    versions = client.get(f"/api/memory/vault/items/{new_id}/history").json()["versions"]
    assert [v["text"] for v in versions] == ["I prefer tea over coffee.", "I prefer coffee."]
    assert [v["current"] for v in versions] == [False, True]

    assert client.post(f"/api/memory/vault/items/{new_id}/pin", json={"pinned": True}).json()
    overview = client.get("/api/memory/vault").json()
    assert overview["stats"]["current"] == 1
    assert "I prefer coffee." in overview["prompt_block"]

    assert client.post(f"/api/memory/vault/items/{new_id}/end").status_code == 200
    assert client.get("/api/memory/vault/items").json()["count"] == 0
    assert client.get("/api/memory/vault/items?history=true").json()["count"] == 2

    assert client.delete(f"/api/memory/vault/items/{new_id}").json() == {"forgotten": 2}
    assert client.delete(f"/api/memory/vault/items/{new_id}").status_code == 404
    actions = [e["action"] for e in client.get("/api/memory/vault/activity").json()["entries"]]
    assert "forget" in actions


def test_search_kind_filter_and_validation(client):
    client.post(
        "/api/memory/vault/items", json={"text": "Lea is my sister.", "kind": "relationship"}
    )
    client.post("/api/memory/vault/items", json={"text": "I live in Berlin.", "kind": "profile"})
    found = client.get("/api/memory/vault/items", params={"q": "sister"}).json()["items"]
    assert [i["text"] for i in found] == ["Lea is my sister."]
    only = client.get("/api/memory/vault/items", params={"kind": "profile"}).json()["items"]
    assert [i["text"] for i in only] == ["I live in Berlin."]
    bad = client.post("/api/memory/vault/items", json={"text": "x", "kind": "diary"})
    assert bad.status_code == 422
    secret = "sk-" + "proj-" + "abcdefghijklmnopqrstuvwxyz0123456789ABCD"
    assert client.post("/api/memory/vault/items", json={"text": secret}).status_code == 422


def test_export_and_reimport(client, tmp_path):
    client.post("/api/memory/vault/items", json={"text": "I was born in 1990.", "kind": "profile"})
    bundle = client.get("/api/memory/vault/export")
    assert bundle.headers["content-type"] == "application/zip"
    assert "attachment" in bundle.headers["content-disposition"]
    markdown = client.get("/api/memory/vault/export", params={"format": "markdown"})
    names = zipfile.ZipFile(io.BytesIO(markdown.content)).namelist()
    assert "my-memory/MEMORY.md" in names and "my-memory/profile.md" in names

    other = MemoryVault(tmp_path / "other.db")
    vault_runtime.set_active(other)
    report = client.post("/api/memory/vault/import", content=bundle.content).json()
    assert report["added"] == 1
    assert client.post("/api/memory/vault/import", content=b"junk").status_code == 422


def test_overview_names_what_is_in_mind_and_files_render(client, vault):
    client.post("/api/memory/vault/items", json={"text": "I live in Berlin.", "kind": "profile"})
    client.post("/api/memory/vault/items", json={"text": "We hiked on Sunday.", "kind": "episode"})
    overview = client.get("/api/memory/vault").json()
    in_mind = {m.text for m in vault.list() if m.id in overview["in_mind_ids"]}
    assert in_mind == {"I live in Berlin."}
    assert 0 < overview["used_chars"] <= overview["budget_chars"]
    files = client.get("/api/memory/vault/files").json()["files"]
    assert [f["name"] for f in files] == ["MEMORY.md", "profile.md", "episode.md"]
    assert "I live in Berlin." in files[1]["content"]
