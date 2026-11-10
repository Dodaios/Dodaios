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

    assert client.delete(f"/api/memory/vault/items/{new_id}").json()["forgotten"] == 2
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


def _add(client, text, **extra):
    return client.post("/api/memory/vault/items", json={"text": text, **extra}).json()["item"]


def test_items_filter_by_origin_date_sort_and_page(client, vault):
    for n in range(5):
        _add(client, f"Fact number {n} about my garden.")
    vault.remember("Imported fact about boats.", "reference", origin="imported")
    body = client.get("/api/memory/vault/items?origin=imported").json()
    assert [i["text"] for i in body["items"]] == ["Imported fact about boats."]
    assert body["total"] == 1 and body["has_more"] is False

    page = client.get("/api/memory/vault/items?sort=newest&limit=4").json()
    assert page["count"] == 4 and page["total"] == 6 and page["has_more"] is True
    rest = client.get("/api/memory/vault/items?sort=newest&limit=4&offset=4").json()
    assert rest["count"] == 2 and rest["has_more"] is False
    stamps = [i["recorded_at"] for i in page["items"]]
    assert stamps == sorted(stamps, reverse=True)

    today = vault.now()[:10]
    assert client.get(f"/api/memory/vault/items?since={today}").json()["total"] == 6
    assert client.get("/api/memory/vault/items?until=2000-01-01").json()["total"] == 0
    assert client.get("/api/memory/vault/items?origin=bogus").status_code == 422


def test_bulk_forget_and_undo(client, vault):
    a = _add(client, "I keep bees on the roof.")
    b = _add(client, "My bike is blue.")
    keep = _add(client, "I like quiet mornings.")
    done = client.post("/api/memory/vault/forget", json={"ids": [a["id"], b["id"]]}).json()
    assert done["forgotten"] == 2 and done["undo_token"]
    assert vault.get(a["id"]) is None
    texts = [i["text"] for i in client.get("/api/memory/vault/items").json()["items"]]
    assert texts == [keep["text"]]

    back = client.post(f"/api/memory/vault/undo/{done['undo_token']}").json()
    assert back["restored"] == 2
    assert vault.get(a["id"]).text == "I keep bees on the roof."
    assert client.post(f"/api/memory/vault/undo/{done['undo_token']}").status_code == 410
    assert client.post("/api/memory/vault/forget", json={"ids": ["nope"]}).status_code == 404


def test_single_forget_undo_restores_the_whole_chain(client, vault):
    first = _add(client, "I live in Hamburg.")
    new_id = client.put(
        f"/api/memory/vault/items/{first['id']}", json={"text": "I live in Berlin."}
    ).json()["item"]["id"]
    done = client.delete(f"/api/memory/vault/items/{new_id}").json()
    assert done["forgotten"] == 2 and done["undo_seconds"] == 60
    assert client.get("/api/memory/vault/items?history=true").json()["total"] == 0
    client.post(f"/api/memory/vault/undo/{done['undo_token']}")
    versions = client.get(f"/api/memory/vault/items/{new_id}/history").json()["versions"]
    assert [v["text"] for v in versions] == ["I live in Hamburg.", "I live in Berlin."]


def test_undo_window_expires(client, vault, monkeypatch):
    from dodaios.ui.web import personal_memory_routes as routes

    item = _add(client, "I own a red kayak.")
    done = client.post("/api/memory/vault/forget", json={"ids": [item["id"]]}).json()
    real = routes.time.monotonic
    monkeypatch.setattr(routes.time, "monotonic", lambda: real() + routes.UNDO_WINDOW_SECONDS + 1)
    assert client.post(f"/api/memory/vault/undo/{done['undo_token']}").status_code == 410
    assert vault.get(item["id"]) is None
