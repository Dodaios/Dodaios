"""A thread's project with no open workspace is still readable by the side panel.

In the thread layout the IDE's side panel follows the open thread. Its
project may have no workspace open in the grid, so the panel names the folder
with a folder view id; the workspace routes read that folder, and only a
folder of a connected project.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.agentic_ide import folder_view, thread_folders
from dodaios.ui.web import agentic_ide_git_routes, agentic_ide_routes, agentic_ide_scm_routes


class _NoWorkspaces:
    """A registry with nothing open: every workspace id is unknown."""

    sessions: list[object] = []

    def get(self, workspace_id: str | None) -> None:
        return None


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    folder = tmp_path / "mit"
    folder.mkdir()
    _git(["init", "-q"], folder)
    _git(["config", "user.email", "test@example.com"], folder)
    _git(["config", "user.name", "Test"], folder)
    (folder / "notes.md").write_text("one\n", encoding="utf-8")
    _git(["add", "notes.md"], folder)
    _git(["commit", "-q", "-m", "init"], folder)
    return folder


@pytest.fixture
def client(project: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(thread_folders, "_known_roots", lambda: [project.resolve()])
    for module in (agentic_ide_routes, agentic_ide_git_routes, agentic_ide_scm_routes):
        monkeypatch.setattr(module, "get_registry", _NoWorkspaces)
    app = FastAPI()
    app.include_router(agentic_ide_routes.router)
    app.include_router(agentic_ide_git_routes.router)
    app.include_router(agentic_ide_scm_routes.router)
    return TestClient(app)


def test_a_view_id_round_trips_its_folder(project: Path, monkeypatch) -> None:
    monkeypatch.setattr(thread_folders, "_known_roots", lambda: [project.resolve()])
    view = folder_view.view_id(project)

    assert folder_view.is_view_id(view)
    assert not folder_view.is_view_id("ide_0b055b88ae87")
    assert folder_view.folder_of(view) == project.resolve()
    assert folder_view.folder_of("ide_0b055b88ae87") is None
    assert folder_view.folder_of("folder:%%%") is None


def test_a_folder_of_no_connected_project_is_refused(tmp_path: Path, monkeypatch) -> None:
    other = tmp_path / "elsewhere"
    other.mkdir()
    monkeypatch.setattr(thread_folders, "_known_roots", lambda: [])

    assert folder_view.folder_of(folder_view.view_id(other)) is None


def test_the_folder_tab_lists_the_thread_project(client: TestClient, project: Path) -> None:
    view = folder_view.view_id(project)

    listing = client.get(f"/api/agentic-ide/workspaces/{view}/files").json()

    assert listing["root_name"] == "mit"
    assert "notes.md" in [entry["name"] for entry in listing["entries"]]


def test_changes_search_and_the_editor_read_the_thread_project(
    client: TestClient, project: Path
) -> None:
    (project / "notes.md").write_text("one\ntwo\n", encoding="utf-8")
    view = folder_view.view_id(project)

    changes = client.get(f"/api/agentic-ide/workspaces/{view}/changes").json()
    assert [(item["path"], item["status"]) for item in changes["files"]] == [
        ("notes.md", "modified")
    ]
    text = client.get(f"/api/agentic-ide/workspaces/{view}/text-file", params={"path": "notes.md"})
    assert text.status_code == 200 and "two" in text.json()["text"]
    status = client.get("/api/agentic-ide/git/scm/status", params={"workspace_id": view})
    assert status.status_code == 200


def test_pane_routes_answer_empty_for_a_folder_view(client: TestClient, project: Path) -> None:
    view = folder_view.view_id(project)

    gate = client.get("/api/agentic-ide/git/done-gate", params={"workspace_id": view})
    github = client.get(
        "/api/agentic-ide/git/session-status", params={"workspace_id": view, "instant": True}
    )

    assert gate.json() == {"panes": {}}
    assert github.json()["panes"] == {}


def test_a_view_of_an_unconnected_folder_is_not_found(client: TestClient, tmp_path: Path) -> None:
    other = tmp_path / "secret"
    other.mkdir()
    (other / "key.txt").write_text("x", encoding="utf-8")
    view = folder_view.view_id(other)

    assert client.get(f"/api/agentic-ide/workspaces/{view}/files").status_code == 404
    assert (
        client.get("/api/agentic-ide/git/scm/status", params={"workspace_id": view}).status_code
        == 404
    )
