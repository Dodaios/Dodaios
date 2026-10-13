"""REST surface of the person's task list, and how the assistant may reach it."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from jarvis.app_actions.catalog import build_catalog, default_tier
from jarvis.today.store import TaskStore
from jarvis.ui.web import today_routes

TODAY = date.today()


@pytest.fixture
def app(tmp_path: Path) -> FastAPI:
    app = FastAPI()
    app.include_router(today_routes.router)
    app.state.config = SimpleNamespace(memory=SimpleNamespace(data_dir=str(tmp_path)))
    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def add(client: TestClient, **body) -> dict:
    response = client.post("/api/today/tasks", json=body)
    assert response.status_code == 201, response.text
    return response.json()


# -- the life of a task --------------------------------------------------------------


def test_add_list_update_complete_reopen_delete(client: TestClient) -> None:
    task = add(client, title="Send the offer", priority="high", due_date=TODAY.isoformat())
    assert task["status"] == "open" and task["priority"] == "high"

    listed = client.get("/api/today/tasks").json()
    assert listed["view"] == "today" and listed["today"] == TODAY.isoformat()
    assert [t["id"] for t in listed["tasks"]] == [task["id"]]

    changed = client.patch(
        f"/api/today/tasks/{task['id']}", json={"title": "Send the final offer", "notes": "v2"}
    ).json()
    assert (changed["title"], changed["notes"], changed["priority"]) == (
        "Send the final offer",
        "v2",
        "high",
    )

    done = client.post(f"/api/today/tasks/{task['id']}/complete").json()
    assert done["status"] == "done" and done["completed_at"]
    assert client.get("/api/today/tasks").json()["tasks"] == []
    assert [t["id"] for t in client.get("/api/today/tasks?view=done").json()["tasks"]] == [
        task["id"]
    ]

    reopened = client.post(f"/api/today/tasks/{task['id']}/reopen").json()
    assert reopened["status"] == "open" and reopened["completed_at"] is None

    deleted = client.delete(f"/api/today/tasks/{task['id']}")
    assert deleted.json() == {"id": task["id"], "deleted": True}
    assert client.get(f"/api/today/tasks/{task['id']}").status_code == 404


def test_views_follow_the_store_order(client: TestClient) -> None:
    add(client, title="later normal", due_date=(TODAY + timedelta(days=5)).isoformat())
    add(client, title="overdue", due_date=(TODAY - timedelta(days=1)).isoformat())
    add(client, title="important", priority="high")
    today = [t["title"] for t in client.get("/api/today/tasks?view=today").json()["tasks"]]
    assert today == ["overdue", "important"]
    open_ = [t["title"] for t in client.get("/api/today/tasks?view=open").json()["tasks"]]
    assert open_ == ["overdue", "important", "later normal"]


def test_patch_null_clears_the_due_date_and_omitted_fields_stay(client: TestClient) -> None:
    task = add(client, title="Dated", notes="keep", due_date=TODAY.isoformat())
    changed = client.patch(f"/api/today/tasks/{task['id']}", json={"due_date": None}).json()
    assert changed["due_date"] is None and changed["notes"] == "keep"


def test_the_store_file_is_created_on_first_use_in_its_own_folder(
    client: TestClient, app: FastAPI, tmp_path: Path
) -> None:
    assert not (tmp_path / "today").exists()
    add(client, title="first")
    assert (tmp_path / "today" / "tasks.db").is_file()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["today"]  # touches nothing else
    assert isinstance(app.state.today_store, TaskStore)


# -- refusals -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"title": ""},
        {"title": "x" * 201},
        {"title": "ok", "priority": "urgent"},
        {"title": "ok", "due_date": "tomorrow"},
        {"title": "ok", "status": "done"},  # status is not set on create
        {"title": "ok", "id": "chosen"},
        {"title": "   "},
    ],
)
def test_invalid_create_bodies_are_refused(client: TestClient, body: dict) -> None:
    assert client.post("/api/today/tasks", json=body).status_code == 422
    assert client.get("/api/today/tasks?view=all").json()["tasks"] == []


@pytest.mark.parametrize(
    "body",
    [
        {"title": None},
        {"title": ""},
        {"priority": None},
        {"priority": "urgent"},
        {"status": "done"},
    ],
)
def test_invalid_updates_are_refused_and_change_nothing(client: TestClient, body: dict) -> None:
    task = add(client, title="Stable")
    assert client.patch(f"/api/today/tasks/{task['id']}", json=body).status_code == 422
    assert client.get(f"/api/today/tasks/{task['id']}").json() == task


def test_an_unknown_view_is_refused(client: TestClient) -> None:
    assert client.get("/api/today/tasks?view=tomorrow").status_code == 422


@pytest.mark.parametrize(
    ("method", "suffix"),
    [("get", ""), ("patch", ""), ("post", "/complete"), ("post", "/reopen"), ("delete", "")],
)
def test_an_unknown_task_is_404(client: TestClient, method: str, suffix: str) -> None:
    kwargs = {"json": {"title": "x"}} if method == "patch" else {}
    response = getattr(client, method)(f"/api/today/tasks/{'0' * 32}{suffix}", **kwargs)
    assert response.status_code == 404


def test_without_a_data_directory_the_list_is_unavailable_not_a_crash() -> None:
    app = FastAPI()
    app.include_router(today_routes.router)
    assert TestClient(app).get("/api/today/tasks").status_code == 503


# -- reachable by the assistant, under the person's policy ------------------------------


def test_every_route_is_an_app_action_with_the_expected_default_tier(app: FastAPI) -> None:
    catalog = build_catalog(app.openapi())
    tiers = {(entry.method, entry.path): default_tier(entry) for entry in catalog.values()}
    assert tiers == {
        ("GET", "/api/today/tasks"): "safe",
        ("POST", "/api/today/tasks"): "monitor",
        ("GET", "/api/today/tasks/{task_id}"): "safe",
        ("PATCH", "/api/today/tasks/{task_id}"): "monitor",
        ("POST", "/api/today/tasks/{task_id}/complete"): "monitor",
        ("POST", "/api/today/tasks/{task_id}/reopen"): "monitor",
        ("DELETE", "/api/today/tasks/{task_id}"): "ask",
    }
    for entry in catalog.values():
        assert entry.title and entry.description, entry.id  # what find-app-action searches
