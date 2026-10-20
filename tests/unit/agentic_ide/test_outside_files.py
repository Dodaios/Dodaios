"""Files outside a workspace open in its code editor after a Ctrl+click.

Terminal output is untrusted, so an absolute path reaches the editor's file
routes only after the person clicked it (the grant), and only on the computer
running Dodaios. Everything else about editing (versions, conflicts, .git)
works as for a workspace file.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from dodaios.agentic_ide import editor_backups, outside_files
from dodaios.agentic_ide.file_editing import EditError, is_outside_key
from dodaios.ui.web import agentic_ide_routes as routes


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(editor_backups, "_store_root", lambda: tmp_path / "store")
    root = tmp_path / "project"
    root.mkdir()
    session = SimpleNamespace(folder=str(root))
    registry = SimpleNamespace(get=lambda wid: session if wid == "w1" else None)
    monkeypatch.setattr(routes, "get_registry", lambda: registry)
    monkeypatch.setattr(routes, "is_loopback_request", lambda _scope: True)
    return root


@pytest.fixture
def downloads(tmp_path: Path) -> Path:
    folder = tmp_path / "Downloads"
    folder.mkdir()
    note = folder / "TODO.md"
    note.write_bytes(b"# todo\n")
    return note


def _grant(path: str) -> dict[str, object]:
    import asyncio

    return asyncio.run(
        routes.grant_outside_file(
            SimpleNamespace(scope={}), "w1", routes.GrantOutsideFileRequest(path=path)
        )
    )


def test_editor_keys_tell_outside_files_apart() -> None:
    assert is_outside_key("C:/Users/me/Downloads/a.md")
    assert is_outside_key("C:\\Users\\me\\a.md")
    assert is_outside_key("/home/me/a.md")
    assert not is_outside_key("src/a.md")
    assert not is_outside_key("a.md")


def test_a_clicked_outside_file_loads_and_saves(workspace: Path, downloads: Path) -> None:
    import asyncio

    key = _grant(f"{downloads}:3")["path"]
    assert key == str(downloads.resolve()).replace("\\", "/")

    loaded = asyncio.run(routes.get_workspace_text_file("w1", key))
    assert loaded["path"] == key
    assert loaded["text"] == "# todo\n"

    saved = asyncio.run(
        routes.save_workspace_text_file(
            "w1",
            routes.SaveWorkspaceFileRequest(
                path=key, text="# done\n", expected_version=loaded["version"]
            ),
        )
    )
    assert saved["path"] == key
    assert downloads.read_bytes() == b"# done\n"
    version = asyncio.run(routes.get_workspace_text_file_version("w1", key))
    assert version["version"] == saved["version"]
    head = asyncio.run(routes.get_workspace_head_text("w1", key))
    assert head["text"] is None


def test_an_unclicked_absolute_path_is_refused(workspace: Path, downloads: Path) -> None:
    import asyncio

    with pytest.raises(HTTPException) as caught:
        asyncio.run(routes.get_workspace_text_file("w1", str(downloads).replace("\\", "/")))
    assert caught.value.status_code == 404
    with pytest.raises(HTTPException):
        asyncio.run(
            routes.save_workspace_text_file(
                "w1",
                routes.SaveWorkspaceFileRequest(
                    path=str(downloads), text="x", expected_version=None, create=True
                ),
            )
        )
    assert downloads.read_bytes() == b"# todo\n"


def test_a_grant_is_one_file_not_its_folder(workspace: Path, downloads: Path) -> None:
    import asyncio

    sibling = downloads.parent / "secret.txt"
    sibling.write_text("s", encoding="utf-8")
    _grant(str(downloads))
    with pytest.raises(HTTPException):
        asyncio.run(routes.get_workspace_text_file("w1", str(sibling).replace("\\", "/")))
    dotted = str(downloads.parent / ".." / "Downloads" / "secret.txt").replace("\\", "/")
    with pytest.raises(HTTPException):
        asyncio.run(routes.get_workspace_text_file("w1", dotted))


def test_folders_missing_files_and_remote_callers_are_refused(
    workspace: Path, downloads: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(HTTPException) as caught:
        _grant(str(downloads.parent))
    assert caught.value.status_code == 404
    with pytest.raises(HTTPException):
        _grant(str(downloads.parent / "missing.md"))
    monkeypatch.setattr(routes, "is_loopback_request", lambda _scope: False)
    with pytest.raises(HTTPException) as remote:
        _grant(str(downloads))
    assert remote.value.status_code == 403


def test_a_file_inside_the_workspace_answers_its_relative_path(workspace: Path) -> None:
    inner = workspace / "src" / "app.py"
    inner.parent.mkdir()
    inner.write_text("x = 1\n", encoding="utf-8")
    assert _grant(str(inner)) == {"workspace_id": "w1", "path": "src/app.py", "kind": "file"}
    # A folder inside the workspace is named for the Folder tab, not granted.
    assert _grant("src/")["kind"] == "directory"
    assert _grant("src")["path"] == "src"
    # The workspace root itself is not a target.
    with pytest.raises(HTTPException):
        _grant(".")


def test_a_home_relative_path_finds_the_file_in_the_home_folder(
    workspace: Path, downloads: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: downloads.parent.parent))
    printed = "Downloads\\TODO.md" if os.name == "nt" else "Downloads/TODO.md"
    key = _grant(printed)["path"]
    assert key == str(downloads.resolve()).replace("\\", "/")
    # A workspace file of the same name wins.
    (workspace / "Downloads").mkdir()
    (workspace / "Downloads" / "TODO.md").write_bytes(b"inner")
    assert _grant("Downloads/TODO.md")["path"] == "Downloads/TODO.md"


def test_git_internals_are_never_granted(workspace: Path, tmp_path: Path) -> None:
    hook = tmp_path / "other" / ".git" / "config"
    hook.parent.mkdir(parents=True)
    hook.write_text("[core]\n", encoding="utf-8")
    with pytest.raises(EditError):
        outside_files.grant(str(workspace), hook.resolve())


def test_outside_tabs_survive_a_restart(workspace: Path, downloads: Path) -> None:
    key = _grant(str(downloads))["path"]
    editor_backups.save_tabs(
        workspace, [{"path": key, "mode": "edit"}, {"path": "a.md", "mode": "edit"}], key
    )
    editor_backups.save_backup(workspace, key, "draft", base_version="v", encoding="utf-8")
    state = editor_backups.load_state(workspace)
    assert [tab["path"] for tab in state["tabs"]] == [key, "a.md"]
    assert state["active"] == key
    assert state["backups"][0]["path"] == key
    assert outside_files.granted_target(str(workspace), str(key)) == Path(str(key))
