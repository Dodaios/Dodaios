"""HTTP API of nodes (``dodaios/ui/web/nodes_routes.py``, docs/nodes.md)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.artifacts.living import LivingPageStore
from dodaios.artifacts.report import write_report
from dodaios.nodes import kinds as node_kinds
from dodaios.nodes import refresh, shell
from dodaios.nodes.kinds import NodeKind
from dodaios.nodes.model import Node
from dodaios.nodes.store import NodeStore
from dodaios.nodes.types import NODE_TYPES, NodeError
from dodaios.ui.web import living_pages_routes, nodes_routes
from dodaios.ui.web.nodes_routes import router

_UNKNOWN = "0123456789ab"
_CARD_FIELDS = [
    "key",
    "id",
    "type",
    "origin",
    "title",
    "slug",
    "path",
    "visual_kind",
    "created_at",
    "updated_at",
    "size",
    "version",
    "status",
    "kept_current",
    "refreshing",
    "every_minutes",
    "request",
    "preview",
]


def _kind(name: str) -> NodeKind:
    return NodeKind(
        type=name,
        normalize=lambda spec: spec,
        render=lambda node: shell.document(node, body="<main>x</main>"),
        preview=lambda spec: {"probe": 1},
        starter=lambda title, language: {"probe": True},
        guide=f"guide for {name}",
    )


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A node store in a temp archive, stand-in renderers, and no scheduler."""
    monkeypatch.setattr(node_kinds, "_KINDS", {name: _kind(name) for name in NODE_TYPES})

    def no_scheduler() -> Any:
        raise RuntimeError("The task scheduler is unavailable")

    # The real refresh code runs, as it does while the agent society is down:
    # a node's own record says whether it is refreshing.
    monkeypatch.setattr(refresh, "_services", no_scheduler)
    nodes = NodeStore(root=tmp_path)
    nodes_routes.set_store(nodes)
    living_pages_routes.set_store(LivingPageStore(root=tmp_path))
    yield nodes
    nodes_routes.set_store(None)
    living_pages_routes.set_store(None)


@pytest.fixture
def client(store: NodeStore, tmp_path: Path) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.state.outputs_root = tmp_path
    return TestClient(app)


@pytest.fixture
def scheduler(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """A running scheduler's two entry points; returns the calls it saw."""
    calls: list[tuple[str, str]] = []

    async def start(
        store: NodeStore, node_id: str, *, track: str | None = None, every_minutes: Any = None
    ) -> Node:
        node = store.get(node_id)
        if node is None:
            raise NodeError(f"No node with id {node_id!r}.")
        if not (track or node.track):
            raise NodeError("'track' must say what the node keeps current and where to read it.")
        calls.append(("start", node_id))
        store.set_upkeep(node_id, track=track, every_minutes=every_minutes)
        return store.set_upkeep(node_id, refreshing=True, task_id="task-1")

    async def stop(store: NodeStore, node_id: str) -> Node:
        calls.append(("stop", node_id))
        return store.set_upkeep(node_id, refreshing=False, task_id="")

    monkeypatch.setattr(refresh, "start_refresh", start)
    monkeypatch.setattr(refresh, "stop_refresh", stop)
    return calls


def _worker_run(root: Path, slug: str, files: dict[str, str]) -> None:
    for name, text in files.items():
        target = root / slug / "tasks" / "t1" / "artifacts" / "files" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")


# --------------------------------------------------------------------- library


def test_the_library_lists_typed_nodes_and_what_older_runs_left(
    client: TestClient, store: NodeStore, tmp_path: Path
) -> None:
    node = store.create(type="sheets", title="Open orders", spec={"rows": []})
    living = LivingPageStore(root=tmp_path).create(title="Parcels", track="x", columns=["Parcel"])
    report = write_report(title="Market report", markdown="Text.", root=tmp_path)
    _worker_run(
        tmp_path,
        "mission_aaaaaaaa0001",
        {"board.html": "<title>Board</title>", "chart.svg": "<svg/>"},
    )
    _worker_run(tmp_path, "mission_aaaaaaaa0002", {"answer.md": "The answer is short."})

    response = client.get("/api/nodes")
    assert response.status_code == 200
    body = response.json()
    assert (body["scanned_runs"], body["skipped_runs"]) == (4, 0)
    cards = {card["key"]: card for card in body["nodes"]}
    assert len(cards) == len(body["nodes"]) == 6
    assert all(list(card) == _CARD_FIELDS for card in cards.values())

    assert cards[node.visual_id]["origin"] == "node"
    assert cards[node.visual_id]["preview"] == {"probe": 1}
    assert cards[living.visual_id]["origin"] == "living"
    assert cards[living.visual_id]["type"] == "sheets"
    assert cards[f"{report.slug}::{report.page_path}"]["origin"] == "report"
    files = "mission_aaaaaaaa0001::tasks/t1/artifacts/files"
    assert (cards[f"{files}/board.html"]["origin"], cards[f"{files}/board.html"]["title"]) == (
        "page",
        "Board",
    )
    assert cards[f"{files}/chart.svg"]["visual_kind"] == "vector"
    answer = cards["run:mission_aaaaaaaa0002"]
    assert (answer["type"], answer["preview"]) == ("output", {"text": "The answer is short."})


def test_the_run_window_is_set_with_scan_and_stays_in_bounds(
    client: TestClient, tmp_path: Path
) -> None:
    for index in range(3):
        _worker_run(tmp_path, f"mission_aaaaaaaa000{index}", {"p.html": f"<title>{index}</title>"})

    narrow = client.get("/api/nodes", params={"scan": 1}).json()
    assert (narrow["scanned_runs"], narrow["skipped_runs"]) == (1, 2)
    assert sorted(card["origin"] for card in narrow["nodes"]) == ["page", "run", "run"]
    assert client.get("/api/nodes", params={"scan": 0}).json()["scanned_runs"] == 1
    assert client.get("/api/nodes", params={"scan": -5}).json()["scanned_runs"] == 1
    assert client.get("/api/nodes", params={"scan": 10**6}).json()["scanned_runs"] == 3
    assert client.get("/api/nodes", params={"scan": "many"}).status_code == 422


def test_refreshing_is_what_the_scheduler_says_not_what_the_node_recorded(
    client: TestClient, store: NodeStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    node = store.create(type="data", title="Numbers", spec={})
    store.set_upkeep(node.id, track="this week's numbers", every_minutes=60, refreshing=True)
    asked: list[str] = []

    async def routine_is_gone(checked: Node) -> bool:
        asked.append(checked.id)
        return False

    (card,) = client.get("/api/nodes").json()["nodes"]
    assert (card["kept_current"], card["refreshing"], card["every_minutes"]) == (True, True, 60)

    monkeypatch.setattr(refresh, "refresh_live", routine_is_gone)
    (card,) = client.get("/api/nodes").json()["nodes"]
    assert (card["kept_current"], card["refreshing"], card["every_minutes"]) == (True, False, 60)
    assert client.get(f"/api/nodes/{node.id}").json()["refreshing"] is False
    assert asked == [node.id, node.id]


def test_types_lists_every_type_that_can_be_made(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    listed = client.get("/api/nodes/types").json()["types"]
    assert [entry["type"] for entry in listed] == list(NODE_TYPES)
    assert listed[0] == {"type": "docs", "guide": "guide for docs"}

    def kind_of(name: str) -> NodeKind:
        if name == "motion":
            raise ImportError("No module named 'dodaios.nodes.kinds.motion'")
        return _kind(name)

    monkeypatch.setattr(nodes_routes, "kind_of", kind_of)
    listed = client.get("/api/nodes/types").json()["types"]
    assert [entry["type"] for entry in listed] == [name for name in NODE_TYPES if name != "motion"]


# ------------------------------------------------------------------- one node


def test_a_node_is_read_by_id_and_by_slug_with_its_spec(
    client: TestClient, store: NodeStore
) -> None:
    node = store.create(type="slides", title="Kickoff", spec={"slides": [{"title": "One"}]})

    by_id = client.get(f"/api/nodes/{node.id}").json()
    assert by_id == client.get(f"/api/nodes/by-slug/{node.slug}").json()
    assert by_id["spec"] == {"slides": [{"title": "One"}]}
    assert (by_id["id"], by_id["type"], by_id["title"]) == (node.id, "slides", "Kickoff")
    assert by_id["visual_id"] == node.visual_id
    assert by_id["page_url"] == f"/api/outputs/{node.slug}/files/{node.page_path}/page"
    assert by_id["refreshing"] is False and by_id["version"] == 1
    assert "extra" not in by_id and "rendered" not in by_id


def test_unknown_nodes_are_not_found(client: TestClient, store: NodeStore) -> None:
    report_slug = "20260101T000000__report__0123456789ab"
    for method, path, body in (
        ("get", f"/api/nodes/{_UNKNOWN}", None),
        ("get", "/api/nodes/not-an-id", None),
        ("get", f"/api/nodes/by-slug/{report_slug}", None),
        ("get", f"/api/nodes/by-slug/20260101T000000__node__{_UNKNOWN}", None),
        ("patch", f"/api/nodes/{_UNKNOWN}", {"title": "X"}),
        ("post", f"/api/nodes/{_UNKNOWN}/duplicate", None),
        ("post", f"/api/nodes/{_UNKNOWN}/revert", None),
        ("post", f"/api/nodes/{_UNKNOWN}/upkeep/stop", None),
        ("post", f"/api/nodes/{_UNKNOWN}/upkeep/resume", None),
        ("delete", f"/api/nodes/{_UNKNOWN}", None),
    ):
        response = client.request(method, path, json=body)
        assert response.status_code == 404, (method, path)
        assert response.json() == {"detail": "unknown node"}


# ------------------------------------------------------ create, rename, copy


def test_create_makes_a_node_from_the_types_starter(client: TestClient, store: NodeStore) -> None:
    response = client.post("/api/nodes", json={"type": "sheet"})
    assert response.status_code == 200
    card = response.json()
    assert list(card) == _CARD_FIELDS
    assert (card["type"], card["origin"], card["title"]) == ("sheets", "node", "Untitled sheet")
    assert (card["version"], card["status"], card["visual_kind"]) == (1, "ready", "page")
    assert card["preview"] == {"probe": 1} and card["size"] > 0

    node = store.get(card["id"])
    assert node is not None and node.spec == {"probe": True} and node.language == "en"
    assert card["key"] == node.visual_id and card["path"] == node.page_path
    # The card a route answers with is the card the library lists.
    assert client.get("/api/nodes").json()["nodes"] == [card]

    named = client.post(
        "/api/nodes", json={"type": "docs", "title": "  Plan 2027 ", "language": "de"}
    ).json()
    assert named["title"] == "Plan 2027"
    assert store.get(named["id"]).language == "de"  # type: ignore[union-attr]
    assert sorted(nodes_routes.DEFAULT_TITLES) == sorted(NODE_TYPES)


def test_create_refuses_a_type_that_does_not_exist(client: TestClient, store: NodeStore) -> None:
    response = client.post("/api/nodes", json={"type": "poem"})
    assert response.status_code == 400
    assert response.json() == {
        "detail": "'type' must be one of: docs, slides, sheets, design, data, whiteboard, motion."
    }
    assert client.post("/api/nodes", json={}).status_code == 422
    assert store.list_nodes() == []


def test_rename_changes_the_title_and_nothing_else(client: TestClient, store: NodeStore) -> None:
    node = store.create(type="docs", title="Plan", spec={"text": "body"})

    card = client.patch(f"/api/nodes/{node.id}", json={"title": "Budget"}).json()
    assert (card["title"], card["version"], card["path"]) == ("Budget", 2, node.page_path)
    assert store.get(node.id).spec == {"text": "body"}  # type: ignore[union-attr]

    # The name it already has: done, and not a new version.
    same = client.patch(f"/api/nodes/{node.id}", json={"title": " Budget "})
    assert same.status_code == 200 and same.json()["version"] == 2

    empty = client.patch(f"/api/nodes/{node.id}", json={"title": "   "})
    assert empty.status_code == 400
    assert empty.json() == {"detail": "'title' must name the node."}
    assert client.patch(f"/api/nodes/{node.id}", json={}).status_code == 422


def test_duplicate_answers_with_the_copys_card(client: TestClient, store: NodeStore) -> None:
    node = store.create(type="whiteboard", title="Ideas", spec={"notes": ["a"]})

    copy = client.post(f"/api/nodes/{node.id}/duplicate").json()
    assert copy["id"] != node.id and copy["title"] == "Ideas" and copy["type"] == "whiteboard"
    named = client.post(f"/api/nodes/{node.id}/duplicate", json={"title": "Ideas (copy)"}).json()
    assert named["title"] == "Ideas (copy)"
    assert store.get(named["id"]).spec == {"notes": ["a"]}  # type: ignore[union-attr]
    assert len(store.list_nodes()) == 3


def test_revert_puts_the_previous_version_back(client: TestClient, store: NodeStore) -> None:
    node = store.create(type="docs", title="Plan", spec={"text": "draft one"})

    nothing = client.post(f"/api/nodes/{node.id}/revert")
    assert nothing.status_code == 400
    assert nothing.json() == {"detail": "This node has no earlier version to go back to."}

    store.update(node.id, spec={"text": "draft two"}, title="Plan B")
    card = client.post(f"/api/nodes/{node.id}/revert").json()
    assert (card["title"], card["version"]) == ("Plan", 3)
    assert store.get(node.id).spec == {"text": "draft one"}  # type: ignore[union-attr]


# ---------------------------------------------------------------------- upkeep


def test_upkeep_is_stopped_and_resumed(
    client: TestClient, store: NodeStore, scheduler: list[tuple[str, str]]
) -> None:
    node = store.create(type="sheets", title="Orders", spec={})
    store.set_upkeep(node.id, track="open orders in the shop", every_minutes=30, refreshing=True)

    stopped = client.post(f"/api/nodes/{node.id}/upkeep/stop").json()
    assert stopped["refreshing"] is False and stopped["track"] == "open orders in the shop"
    assert "spec" not in stopped

    resumed = client.post(f"/api/nodes/{node.id}/upkeep/resume", json={"every_minutes": 45})
    assert resumed.status_code == 200
    assert (resumed.json()["refreshing"], resumed.json()["every_minutes"]) == (True, 45)
    again = client.post(f"/api/nodes/{node.id}/upkeep/resume").json()
    assert (again["refreshing"], again["every_minutes"]) == (True, 45)
    assert scheduler == [("stop", node.id), ("start", node.id), ("start", node.id)]


def test_resume_needs_something_to_keep_current_and_a_sane_cadence(
    client: TestClient, store: NodeStore, scheduler: list[tuple[str, str]]
) -> None:
    node = store.create(type="sheets", title="Orders", spec={})

    untracked = client.post(f"/api/nodes/{node.id}/upkeep/resume")
    assert untracked.status_code == 400
    assert untracked.json() == {
        "detail": "'track' must say what the node keeps current and where to read it."
    }
    for minutes in (1, 10**6):
        body = {"every_minutes": minutes}
        assert client.post(f"/api/nodes/{node.id}/upkeep/resume", json=body).status_code == 422
    assert scheduler == []


def test_upkeep_without_a_scheduler(client: TestClient, store: NodeStore) -> None:
    node = store.create(type="sheets", title="Orders", spec={})
    store.set_upkeep(node.id, track="open orders", refreshing=True, task_id="task-1")

    # Stopping works without it: the person asked for the refresh to end.
    stopped = client.post(f"/api/nodes/{node.id}/upkeep/stop")
    assert stopped.status_code == 200 and stopped.json()["refreshing"] is False
    assert store.get(node.id).task_id == ""  # type: ignore[union-attr]

    down = client.post(f"/api/nodes/{node.id}/upkeep/resume")
    assert down.status_code == 503
    assert down.json() == {"detail": "The task scheduler is unavailable"}
    assert store.get(node.id).refreshing is False  # type: ignore[union-attr]


# ---------------------------------------------------------------------- delete


def test_delete_stops_the_refresh_and_removes_the_node(
    client: TestClient, store: NodeStore, scheduler: list[tuple[str, str]], tmp_path: Path
) -> None:
    node = store.create(type="docs", title="Plan", spec={})
    kept = store.create(type="docs", title="Kept", spec={})

    response = client.delete(f"/api/nodes/{node.id}")
    assert response.status_code == 200 and response.json() == {"deleted": True}
    assert scheduler == [("stop", node.id)]
    assert not (tmp_path / node.slug).exists()
    assert [n.id for n in store.list_nodes()] == [kept.id]
    assert client.delete(f"/api/nodes/{node.id}").status_code == 404


def test_delete_goes_through_when_the_routine_cannot_be_removed(
    client: TestClient, store: NodeStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    node = store.create(type="docs", title="Plan", spec={})

    async def broken(store: NodeStore, node_id: str) -> Node:
        raise ConnectionError("task database is locked")

    monkeypatch.setattr(refresh, "stop_refresh", broken)
    assert client.delete(f"/api/nodes/{node.id}").json() == {"deleted": True}
    assert store.get(node.id) is None


def test_a_node_can_be_read_without_its_spec(client: TestClient, store: NodeStore) -> None:
    node = store.create(type="docs", title="Plan", spec={"probe": 1})

    for url in (f"/api/nodes/{node.id}", f"/api/nodes/by-slug/{node.slug}"):
        with_spec = client.get(url).json()
        without = client.get(f"{url}?spec=0").json()
        assert "spec" in with_spec
        assert "spec" not in without
        assert without["updated_at"] == with_spec["updated_at"]
