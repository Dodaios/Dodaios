"""HTTP API of nodes (``dodaios/ui/web/nodes_routes.py``, docs/nodes.md)."""

from __future__ import annotations

import base64
import sys
import types
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.artifacts.living import LivingPageStore
from dodaios.artifacts.report import write_report
from dodaios.nodes import comments, refresh, shell
from dodaios.nodes import kinds as node_kinds
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


# -------------------------------------------------------------------- comments


def test_comments_go_out_together_in_the_background(
    client: TestClient, store: NodeStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    node = store.create(type="docs", title="Brief", spec={})
    seen: list[tuple[str, list[comments.NodeComment]]] = []

    async def send(nodes: NodeStore, node_id: str, batch: list[comments.NodeComment]) -> str:
        seen.append((node_id, batch))
        return "task-9"

    monkeypatch.setattr(comments, "send_comments", send)
    body = {
        "comments": [
            {"text": "shorter", "quote": "Our goals", "where": "§ Goals"},
            {"text": "brighter"},
        ]
    }
    sent = client.post(f"/api/nodes/{node.id}/comments", json=body)
    assert sent.status_code == 202
    assert sent.json() == {"task_id": "task-9", "count": 2}
    assert seen == [
        (
            node.id,
            [
                comments.NodeComment("shorter", "Our goals", "§ Goals"),
                comments.NodeComment("brighter", "", ""),
            ],
        )
    ]


def test_comments_are_refused_for_an_unknown_node_none_at_all_or_no_scheduler(
    client: TestClient, store: NodeStore
) -> None:
    node = store.create(type="docs", title="Brief", spec={})
    one = {"comments": [{"text": "x"}]}
    assert client.post(f"/api/nodes/{_UNKNOWN}/comments", json=one).status_code == 404
    assert client.post(f"/api/nodes/{node.id}/comments", json={"comments": []}).status_code == 422
    down = client.post(f"/api/nodes/{node.id}/comments", json=one)
    assert down.status_code == 503
    assert down.json() == {"detail": "The task scheduler is unavailable"}


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


def test_one_typed_value_is_saved_into_the_spec(client: TestClient, store: NodeStore) -> None:
    node = store.create(
        type="sheets",
        title="Costs",
        spec={"rows": [{"item": "Flight", "price": 40.62, "booked": False}], "note": "draft"},
    )

    answer = client.post(f"/api/nodes/{node.id}/edit", json={"path": "/note", "value": "final"})
    assert answer.status_code == 200
    state = answer.json()
    assert state["version"] == 2 and "spec" not in state
    assert store.get(node.id).spec["note"] == "final"

    # A number in the reader's notation, a yes/no, and an empty cell of a row.
    url = f"/api/nodes/{node.id}/edit"
    client.post(url, json={"path": "/rows/0/price", "value": "1.234,5", "as": "number"})
    client.post(url, json={"path": "/rows/0/booked", "value": True, "as": "toggle"})
    client.post(url, json={"path": "/rows/0/due", "value": "2026-12-01"})
    row = store.get(node.id).spec["rows"][0]
    assert row == {"item": "Flight", "price": 1234.5, "booked": True, "due": "2026-12-01"}

    # The node's own name is a field too.
    client.post(f"/api/nodes/{node.id}/edit", json={"path": "@title", "value": "  Trip costs "})
    assert store.get(node.id).title == "Trip costs"


def test_an_edit_that_changes_nothing_writes_nothing(client: TestClient, store: NodeStore) -> None:
    node = store.create(type="docs", title="Plan", spec={"summary": "same"})

    answer = client.post(f"/api/nodes/{node.id}/edit", json={"path": "/summary", "value": "same"})
    assert answer.status_code == 200
    assert answer.json()["version"] == 1


@pytest.mark.parametrize(
    ("body", "said"),
    [
        ({"path": "/rows/3/item", "value": "x"}, "Nothing at"),
        ({"path": "/rows", "value": "x"}, "more than one value"),
        ({"path": "/rows/0/price", "value": "twelve", "as": "number"}, "not a number"),
        ({"path": "/rows/0/price", "value": "1", "as": "colour"}, "'as' must be"),
        ({"path": "summary", "value": "x"}, "not a place"),
        ({"path": "@title", "value": "   "}, "needs a name"),
    ],
)
def test_an_edit_the_node_cannot_take_is_refused_with_the_reason(
    client: TestClient, store: NodeStore, body: dict, said: str
) -> None:
    node = store.create(type="sheets", title="Costs", spec={"rows": [{"item": "a", "price": 1}]})

    answer = client.post(f"/api/nodes/{node.id}/edit", json=body)
    assert answer.status_code == 400
    assert said in answer.json()["detail"]
    assert store.get(node.id).version == 1


def test_an_edit_of_an_unknown_node_is_a_404(client: TestClient) -> None:
    answer = client.post("/api/nodes/0123456789ab/edit", json={"path": "/a", "value": "x"})
    assert answer.status_code == 404


# ----------------------------------------------------------------- whiteboards

_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d4944415478da63fcff9f010005fe02fea7d6a4b90000000049454e44ae426082"
)
_PNG_URL = "data:image/png;base64," + base64.b64encode(_PNG).decode()


def _box(ident: str, **fields: Any) -> dict[str, Any]:
    return {"id": ident, "type": "rectangle", "x": 0, "y": 0, "width": 80, "height": 40, **fields}


@pytest.fixture
def boards(store: NodeStore, monkeypatch: pytest.MonkeyPatch) -> NodeStore:
    """The store, with the real whiteboard type (the others stay stand-ins)."""
    kinds = dict(node_kinds._KINDS)
    kinds.pop("whiteboard")
    monkeypatch.setattr(node_kinds, "_KINDS", kinds)
    return store


def test_a_board_scene_is_read_and_saved_with_its_version(
    client: TestClient, boards: NodeStore
) -> None:
    node = boards.create(type="whiteboard", title="Board")
    answer = client.get(f"/api/nodes/{node.id}/scene")
    assert answer.status_code == 200
    assert answer.json() == {
        "version": 1,
        "updated_at": node.updated_at,
        "scene": {
            "format": "scene",
            "elements": [],
            "appState": {"viewBackgroundColor": "#ffffff", "gridModeEnabled": False},
            "files": {},
        },
    }
    saved = client.put(f"/api/nodes/{node.id}/scene", json={"scene": {"elements": [_box("a")]}})
    assert saved.status_code == 200
    body = saved.json()
    assert body["version"] == 2 and body["merged"] is False and "scene" not in body
    assert [element["id"] for element in boards.get(node.id).spec["elements"]] == ["a"]


def test_a_save_behind_the_assistant_gets_the_merged_scene_back(
    client: TestClient, boards: NodeStore
) -> None:
    node = boards.create(type="whiteboard", title="Board")
    client.put(f"/api/nodes/{node.id}/scene", json={"scene": {"elements": [_box("a")]}})
    boards.update(node.id, spec={"elements": [_box("a"), _box("drawn-by-assistant", x=300)]})
    answer = client.put(
        f"/api/nodes/{node.id}/scene",
        json={"scene": {"elements": [_box("a", x=5, version=2)]}},
    ).json()
    assert answer["merged"] is True and answer["version"] == 4
    assert [element["id"] for element in answer["scene"]["elements"]] == [
        "a",
        "drawn-by-assistant",
    ]
    assert answer["scene"]["elements"][0]["x"] == 5


@pytest.mark.parametrize(
    ("body", "status", "said"),
    [
        ({"scene": {"elements": [{"id": "a", "type": "box"}]}}, 400, "types"),
        ({"scene": "x"}, 422, "scene"),
        ({}, 422, "scene"),
    ],
)
def test_a_scene_the_board_cannot_take_is_refused(
    client: TestClient, boards: NodeStore, body: dict, status: int, said: str
) -> None:
    node = boards.create(type="whiteboard", title="Board")
    answer = client.put(f"/api/nodes/{node.id}/scene", json=body)
    assert answer.status_code == status
    assert said in answer.json()["detail"]
    assert boards.get(node.id).version == 1


def test_a_body_that_is_not_json_or_too_large_is_refused(
    client: TestClient, boards: NodeStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    node = boards.create(type="whiteboard", title="Board")
    answer = client.put(
        f"/api/nodes/{node.id}/scene",
        content=b"{not json",
        headers={"content-type": "application/json"},
    )
    assert answer.status_code == 422
    monkeypatch.setattr(nodes_routes, "MAX_SCENE_BODY", 50)
    answer = client.put(
        f"/api/nodes/{node.id}/scene", json={"scene": {"elements": [_box("a")] * 3}}
    )
    assert answer.status_code == 413


def test_the_board_routes_reach_only_whiteboards(client: TestClient, boards: NodeStore) -> None:
    sheet = boards.create(type="sheets", title="Sheet", spec={"rows": []})
    for method, path, body in (
        ("get", "scene", None),
        ("put", "scene", {"scene": {"elements": []}}),
        ("post", "files", {"dataURL": _PNG_URL}),
        ("get", "files/abc", None),
        ("post", "whiteboard", {"actions": [{"do": "clear"}]}),
    ):
        wrong = client.request(method, f"/api/nodes/{sheet.id}/{path}", json=body)
        assert wrong.status_code == 422 and "not a whiteboard" in wrong.json()["detail"]
        missing = client.request(method, f"/api/nodes/{_UNKNOWN}/{path}", json=body)
        assert missing.status_code == 404


def test_a_picture_is_kept_and_served_with_its_own_type(
    client: TestClient, boards: NodeStore
) -> None:
    node = boards.create(type="whiteboard", title="Board")
    answer = client.post(
        f"/api/nodes/{node.id}/files",
        json={"dataURL": _PNG_URL.replace("image/png", "image/svg+xml")},
    )
    assert answer.status_code == 200
    file_id = answer.json()["id"]
    assert answer.json() == {"id": file_id, "mimeType": "image/png"}
    served = client.get(f"/api/nodes/{node.id}/files/{file_id}")
    assert served.status_code == 200 and served.content == _PNG
    assert served.headers["content-type"] == "image/png"
    assert served.headers["cache-control"] == "private, max-age=31536000, immutable"
    assert served.headers["content-security-policy"] == "default-src 'none'"
    assert served.headers["x-content-type-options"] == "nosniff"
    assert client.get(f"/api/nodes/{node.id}/files/nope").status_code == 404
    assert client.get(f"/api/nodes/{node.id}/files/..%2F..%2Fnode.json").status_code == 404


def test_a_picture_that_is_none_or_takes_a_used_id_is_refused(
    client: TestClient, boards: NodeStore
) -> None:
    node = boards.create(type="whiteboard", title="Board")
    svg = "data:image/svg+xml;base64," + base64.b64encode(b"<svg><script/></svg>").decode()
    answer = client.post(f"/api/nodes/{node.id}/files", json={"dataURL": svg})
    assert answer.status_code == 400 and "PNG, JPEG, GIF and WebP" in answer.json()["detail"]
    client.post(f"/api/nodes/{node.id}/files", json={"dataURL": _PNG_URL, "id": "pic"})
    gif = "data:image/gif;base64," + base64.b64encode(b"GIF89a" + b"\x00" * 20).decode()
    taken = client.post(f"/api/nodes/{node.id}/files", json={"dataURL": gif, "id": "pic"})
    assert taken.status_code == 409
    bad_id = client.post(f"/api/nodes/{node.id}/files", json={"dataURL": _PNG_URL, "id": "../x"})
    assert bad_id.status_code == 400
    assert client.post(f"/api/nodes/{node.id}/files", json={}).status_code == 422


def test_actions_run_on_the_board_and_save_one_revision(
    client: TestClient, boards: NodeStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[Any] = []

    def apply_actions(scene: dict, actions: list, *, now_ms: Any = None) -> tuple[dict, list]:
        seen.append((scene, actions))
        if actions[0].get("do") == "fail":
            raise NodeError("actions[0]: 'fail' is no action.")
        return {**scene, "elements": [_box("new", x=10, y=20)]}, ["added new"]

    module = types.ModuleType("dodaios.nodes.board.ops")
    module.apply_actions = apply_actions  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "dodaios.nodes.board.ops", module)
    node = boards.create(type="whiteboard", title="Board")

    answer = client.post(f"/api/nodes/{node.id}/whiteboard", json={"actions": [{"do": "add"}]})
    assert answer.status_code == 200
    assert answer.json() == {
        "version": 2,
        "report": ["added new"],
        "summary": {"elements": 1, "bounds": [10, 20, 90, 60]},
    }
    assert seen[0][1] == [{"do": "add"}] and seen[0][0]["format"] == "scene"
    run_dir = boards.dir_of(node.id)
    assert run_dir is not None
    assert len(list((run_dir / "history").iterdir())) == 1  # an ordinary revision

    failed = client.post(f"/api/nodes/{node.id}/whiteboard", json={"actions": [{"do": "fail"}]})
    assert failed.status_code == 400 and "actions[0]" in failed.json()["detail"]
    assert boards.get(node.id).version == 2
    assert client.post(f"/api/nodes/{node.id}/whiteboard", json={"actions": []}).status_code == 422
