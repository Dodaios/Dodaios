"""The type editors' routes: ``PUT /api/nodes/{id}/spec`` and
``POST /api/nodes/{id}/preview`` (``dodaios/ui/web/nodes_routes.py``)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.nodes import refresh
from dodaios.nodes.store import NodeStore
from dodaios.ui.web import nodes_routes
from dodaios.ui.web.artifact_view import ARTIFACT_PAGE_CSP
from dodaios.ui.web.nodes_routes import MAX_SPEC_BODY, router

DOC = {"markdown": "# Plan\n\nFirst draft."}


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    def no_scheduler() -> Any:
        raise RuntimeError("The task scheduler is unavailable")

    monkeypatch.setattr(refresh, "_services", no_scheduler)
    nodes = NodeStore(root=tmp_path)
    nodes_routes.set_store(nodes)
    yield nodes
    nodes_routes.set_store(None)


@pytest.fixture
def client(store: NodeStore, tmp_path: Path) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.state.outputs_root = tmp_path
    return TestClient(app)


def _spec(text: str) -> dict[str, str]:
    return {"markdown": f"# Plan\n\n{text}"}


def test_a_save_answers_the_new_version_and_the_spec_as_kept(
    client: TestClient, store: NodeStore
) -> None:
    node = store.create(type="docs", title="Plan", spec=DOC)
    answer = client.put(
        f"/api/nodes/{node.id}/spec",
        json={"spec": {**_spec("Second."), "dropped": True}, "base_version": 1},
    )
    assert answer.status_code == 200
    body = answer.json()
    assert set(body) == {"version", "updated_at", "spec"}
    assert body["version"] == 2 and "dropped" not in body["spec"]
    assert "Second." in body["spec"]["markdown"]
    assert store.get(node.id).version == 2  # type: ignore[union-attr]


def test_a_save_behind_the_assistant_is_a_conflict_with_the_current_state(
    client: TestClient, store: NodeStore
) -> None:
    node = store.create(type="docs", title="Plan", spec=DOC)
    revised = store.update(node.id, spec=_spec("Theirs."))
    answer = client.put(
        f"/api/nodes/{node.id}/spec", json={"spec": _spec("Mine."), "base_version": 1}
    )
    assert answer.status_code == 409
    body = answer.json()
    assert body["version"] == 2 and body["updated_at"] == revised.updated_at
    assert "Theirs." in body["spec"]["markdown"] and body["detail"]
    # Keep mine: the same save from the version now seen goes through.
    again = client.put(
        f"/api/nodes/{node.id}/spec", json={"spec": _spec("Mine."), "base_version": 2}
    )
    assert again.status_code == 200 and again.json()["version"] == 3


@pytest.mark.parametrize(
    ("body", "said"),
    [
        ({"spec": {"markdown": 5}, "base_version": 1}, ""),
        ({"spec": "x", "base_version": 1}, "spec"),
        ({"base_version": 1}, "spec"),
        ({"spec": DOC, "base_version": -1}, "base_version"),
    ],
)
def test_a_spec_that_cannot_be_kept_is_422_with_the_reason(
    client: TestClient, store: NodeStore, body: dict, said: str
) -> None:
    node = store.create(type="docs", title="Plan", spec=DOC)
    answer = client.put(f"/api/nodes/{node.id}/spec", json=body)
    assert answer.status_code == 422
    assert said in answer.json()["detail"] and answer.json()["detail"]
    assert store.get(node.id).version == 1  # type: ignore[union-attr]


def test_a_whiteboard_is_not_saved_through_its_spec(client: TestClient, store: NodeStore) -> None:
    board = store.create(type="whiteboard", title="Board")
    answer = client.put(f"/api/nodes/{board.id}/spec", json={"spec": {"elements": []}})
    assert answer.status_code == 422 and "scene" in answer.json()["detail"]


def test_an_unknown_node_is_404(client: TestClient) -> None:
    assert client.put("/api/nodes/0123456789ab/spec", json={"spec": DOC}).status_code == 404
    assert client.post("/api/nodes/0123456789ab/preview", json={"spec": DOC}).status_code == 404


def test_a_body_over_the_ceiling_is_refused_before_it_is_read(
    client: TestClient, store: NodeStore
) -> None:
    node = store.create(type="docs", title="Plan", spec=DOC)
    answer = client.put(
        f"/api/nodes/{node.id}/spec",
        content=b"{" + b" " * MAX_SPEC_BODY + b"}",
        headers={"Content-Type": "application/json"},
    )
    assert answer.status_code == 413


def test_a_preview_is_the_page_of_the_unsaved_spec_served_like_the_node_page(
    client: TestClient, store: NodeStore
) -> None:
    node = store.create(type="docs", title="Plan", spec=DOC)
    answer = client.post(f"/api/nodes/{node.id}/preview", json={"spec": _spec("Draft only.")})
    assert answer.status_code == 200
    assert answer.headers["content-type"].startswith("text/html")
    assert answer.headers["content-security-policy"] == ARTIFACT_PAGE_CSP
    assert answer.headers["cache-control"] == "no-store"
    assert answer.headers["x-content-type-options"] == "nosniff"
    assert "Draft only." in answer.text and "<style" in answer.text
    assert store.get(node.id).version == 1  # type: ignore[union-attr]
    refused = client.post(f"/api/nodes/{node.id}/preview", json={"spec": {"markdown": 5}})
    assert refused.status_code == 422 and refused.json()["detail"]
