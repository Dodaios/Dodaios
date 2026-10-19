"""The semantic search switch over REST, and its effect on the wiki search route."""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.core import config_writer
from dodaios.memory.wiki import fts_index, semantic_model, semantic_search, semantic_setup
from dodaios.memory.wiki.db_path import resolve_wiki_db_path
from dodaios.ui.web.wiki_routes import router as wiki_router
from tests.fakes.fake_semantic_encoder import FakeSemanticEncoder


@pytest.fixture(autouse=True)
def _fresh_state(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(semantic_setup, "_run", semantic_setup._Run())
    semantic_search.deactivate()
    yield
    semantic_search.deactivate()


@pytest.fixture()
def saved(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    """Record what the route persists instead of touching a real config file."""
    writes: list[bool] = []
    monkeypatch.setattr(config_writer, "set_wiki_semantic_search", writes.append)
    return writes


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    vault = tmp_path / "vault"
    (vault / "entities").mkdir(parents=True)
    (vault / "entities" / "anna.md").write_text(
        "---\ntype: entity\n---\n# Anna\n\n- Meine Schwester\n- Geburtstag am 4. Mai\n",
        encoding="utf-8",
    )
    data_dir = tmp_path / "data"
    db_path = resolve_wiki_db_path(data_dir)
    db_path.parent.mkdir(parents=True)
    import sqlite3

    conn = sqlite3.connect(str(db_path))
    try:
        fts_index.rebuild_index(vault, conn)
    finally:
        conn.close()

    encoder = FakeSemanticEncoder()
    real_activate = semantic_search.activate

    def activate(vault_root: Path, **kwargs: Any) -> Any:
        return real_activate(vault_root, **{**kwargs, "encoder": encoder})

    # The search route opens the word index from the default database path.
    monkeypatch.setattr("dodaios.memory.wiki.search._default_db_path", lambda: db_path)
    monkeypatch.setattr(semantic_model, "runtime_available", lambda: True)
    monkeypatch.setattr(semantic_model, "model_present", lambda _d=None: True)
    monkeypatch.setattr(semantic_search, "activate", activate)

    app = FastAPI()
    app.include_router(wiki_router)
    app.state.config = SimpleNamespace(
        wiki_context=SimpleNamespace(semantic_search=False),
        wiki_integration=SimpleNamespace(vault_root=vault),
        memory=SimpleNamespace(data_dir=data_dir),
    )
    return TestClient(app)


def _finish() -> None:
    thread = semantic_setup._run.thread
    assert thread is not None
    thread.join(timeout=10)


def test_the_switch_is_off_on_a_fresh_install(client: TestClient) -> None:
    body = client.get("/api/wiki/semantic-search").json()
    assert body["enabled"] is False
    assert body["state"] == "off"
    assert body["download_bytes"] == semantic_model.DOWNLOAD_BYTES


def test_switching_it_on_persists_the_choice_and_reports_progress(
    client: TestClient, saved: list[bool]
) -> None:
    body = client.put("/api/wiki/semantic-search", json={"enabled": True}).json()
    assert body["enabled"] is True
    assert body["state"] in {"downloading", "indexing", "ready"}
    assert saved == [True]

    _finish()
    body = client.get("/api/wiki/semantic-search").json()
    assert body["state"] == "ready"
    assert (body["pages"], body["passages"]) == (1, 2)


def test_the_wiki_search_gains_pages_found_by_meaning(
    client: TestClient, saved: list[bool]
) -> None:
    question = "when is my sister's birthday"
    before = client.get("/api/wiki/search", params={"q": question}).json()
    assert before["hits"] == [], "no word of the question is in the German note"

    client.put("/api/wiki/semantic-search", json={"enabled": True})
    _finish()

    after = client.get("/api/wiki/search", params={"q": question}).json()
    assert [(hit["slug"], hit["by_meaning"]) for hit in after["hits"]] == [("anna", True)]


def test_word_hits_are_marked_as_such(client: TestClient, saved: list[bool]) -> None:
    client.put("/api/wiki/semantic-search", json={"enabled": True})
    _finish()

    body = client.get("/api/wiki/search", params={"q": "Schwester"}).json()

    assert [(hit["slug"], hit["by_meaning"]) for hit in body["hits"]] == [("anna", False)]


def test_switching_it_off_stops_the_engine_and_persists_the_choice(
    client: TestClient, saved: list[bool]
) -> None:
    client.put("/api/wiki/semantic-search", json={"enabled": True})
    _finish()

    body = client.put("/api/wiki/semantic-search", json={"enabled": False}).json()

    assert body["enabled"] is False
    assert body["state"] == "off"
    assert saved == [True, False]
    assert semantic_search.get_active() is None
    assert client.app.state.config.wiki_context.semantic_search is False  # type: ignore[attr-defined]


def test_a_setting_that_cannot_be_saved_changes_nothing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(_enabled: bool) -> None:
        raise OSError("disk is read-only")

    monkeypatch.setattr(config_writer, "set_wiki_semantic_search", refuse)

    response = client.put("/api/wiki/semantic-search", json={"enabled": True})

    assert response.status_code == 500
    assert semantic_search.get_active() is None
    assert client.app.state.config.wiki_context.semantic_search is False  # type: ignore[attr-defined]


def test_the_body_must_be_a_boolean(client: TestClient) -> None:
    assert client.put("/api/wiki/semantic-search", json={"enabled": "maybe"}).status_code == 422


def test_a_busy_model_does_not_hold_the_word_hits_back(
    client: TestClient, saved: list[bool], monkeypatch: pytest.MonkeyPatch
) -> None:
    import time

    from dodaios.memory.wiki.search import SearchHit
    from dodaios.ui.web import wiki_routes

    client.put("/api/wiki/semantic-search", json={"enabled": True})
    _finish()

    def slow(hits: list[Any], _query: str, **_kwargs: Any) -> list[Any]:
        time.sleep(0.5)
        late = SearchHit(title="Late", path=Path("late.md"), snippet="", score=0.9)
        return [*hits, late]

    monkeypatch.setattr(wiki_routes, "with_semantic_hits", slow)
    monkeypatch.setattr(wiki_routes, "_SEMANTIC_SEARCH_TIMEOUT_S", 0.05)

    body = client.get("/api/wiki/search", params={"q": "Schwester"}).json()

    # The answer went out with the word hits alone; had the route waited for
    # the model, the late hit would be in it.
    assert [(hit["slug"], hit["by_meaning"]) for hit in body["hits"]] == [("anna", False)]


def test_a_failing_semantic_engine_leaves_the_word_hits_standing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dodaios.ui.web import wiki_routes

    def broken(*_args: Any, **_kwargs: Any) -> list[Any]:
        raise RuntimeError("native session died")

    monkeypatch.setattr(wiki_routes, "with_semantic_hits", broken)

    body = client.get("/api/wiki/search", params={"q": "Schwester"}).json()

    assert body["ok"] is True
    assert [hit["slug"] for hit in body["hits"]] == ["anna"]
