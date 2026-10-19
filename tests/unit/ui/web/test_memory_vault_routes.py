"""The path-addressed Memory section API (``memory_vault_routes``).

Real files in ``tmp_path`` and a real ``WikiCurator`` + ``AtomicWriter`` for
the write routes, so every write goes through the same guarded pipeline the
app uses. The society runtime is absent here, so every agent folder reads
as an orphan.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.memory.wiki import integration
from dodaios.memory.wiki.atomic_writer import AtomicWriter
from dodaios.memory.wiki.curator import WikiCurator
from dodaios.memory.wiki.curator_llm import WikiCuratorLLM
from dodaios.memory.wiki.log_writer import LogWriter
from dodaios.memory.wiki.page import MarkdownPageRepository
from dodaios.memory.wiki.vault_index import VaultIndex
from dodaios.ui.web.memory_vault_routes import router as memory_router
from dodaios.ui.web.wiki_routes import invalidate_visible_page_cache

_OLD = time.time() - 3_600


def _write(vault: Path, rel: str, text: str) -> Path:
    path = vault / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    # Older than the writer's 30 s concurrent-edit window.
    os.utime(path, (_OLD, _OLD))
    return path


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    _write(
        root,
        "entities/ruben.md",
        "---\ntype: entity\nslug: ruben\naliases:\n- the user\n---\n\n# Ruben\n\n"
        "Owns [[projects/magenta]].\n",
    )
    _write(
        root,
        "projects/magenta.md",
        "---\ntype: project\nslug: magenta\nstatus: active\n---\n\n"
        "# Magenta\n\nBuilt by [[ruben]].\n",
    )
    _write(
        root,
        "society/ada/MEMORY.md",
        '---\ntype: society\ntitle: "Ada — memory"\n---\n\n'
        '<!-- memory-entry: {"id": "a1", "importance": 8, "origin": "tool"} -->\n'
        "Ruben deploys on Fridays.\n",
    )
    _write(root, "society/ada/USER.md", '---\ntype: society\ntitle: "Ada — user profile"\n---\n')
    _write(root, "society/vega/MEMORY.md", '---\ntype: society\ntitle: "Vega — memory"\n---\n')
    _write(root, "society/vega/USER.md", '---\ntype: society\ntitle: "Vega — user profile"\n---\n')
    _write(
        root,
        "log.md",
        "# Wiki Log\n\n## [2026-10-01 10:00] create | journal-batch:1\n\n"
        "- pages touched: [[entities/ruben]]\n- summary: Applied 1 create.\n\n"
        "## [2026-10-02 10:00] update | self-doc:memory.md\n\n"
        "- pages touched: [[memory]]\n- summary: Applied 1 update.\n",
    )
    invalidate_visible_page_cache()
    return root


class _EmptyRoster:
    async def list(self, *, include_archived: bool = False) -> list[object]:  # noqa: A003
        return []


class _EmptySociety:
    roster = _EmptyRoster()

    async def ensure_started(self) -> None:
        return None


@pytest.fixture
def client(vault: Path, tmp_path: Path) -> Iterator[TestClient]:
    app = FastAPI()
    app.include_router(memory_router)
    app.state.config = SimpleNamespace(
        wiki_integration=SimpleNamespace(vault_root=vault),
        memory=SimpleNamespace(data_dir=tmp_path / "data"),
    )
    # A roster that answers and knows none of the vault's agent folders.
    app.state.society = _EmptySociety()
    repo = MarkdownPageRepository()
    curator = WikiCurator(
        repo=repo,
        vault=VaultIndex(repo=repo),
        writer=AtomicWriter(vault_root=vault, backup_dir=tmp_path / "backups"),
        llm=WikiCuratorLLM.__new__(WikiCuratorLLM),
        log_writer=LogWriter(log_path=vault / "log.md"),
        vault_root=vault,
    )
    integration._set_running_curator(curator)
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        integration._set_running_curator(None)
        invalidate_visible_page_cache()


def test_index_lists_every_notebook_once_and_flags_empty_pages(client: TestClient) -> None:
    body = client.get("/api/wiki/index").json()

    paths = {page["path"]: page for page in body["pages"]}
    assert "society/ada/MEMORY.md" in paths and "society/vega/MEMORY.md" in paths
    assert paths["society/ada/MEMORY.md"]["empty"] is False
    assert paths["society/vega/MEMORY.md"]["empty"] is True
    assert paths["log.md"]["group"] == "system"
    assert {agent["agent_id"]: agent["state"] for agent in body["agents"]} == {
        "ada": "orphan",
        "vega": "orphan",
    }
    assert body["stats"]["links"] == 2
    assert body["writable"] is True


def test_read_returns_the_requested_notebook_not_the_first_with_that_name(
    client: TestClient,
) -> None:
    vega = client.get("/api/wiki/read", params={"path": "society/vega/MEMORY.md"}).json()
    ada = client.get("/api/wiki/read", params={"path": "society/ada/MEMORY.md"}).json()

    assert vega["path"] == "society/vega/MEMORY.md"
    assert vega["empty"] is True and vega["entries"] == []
    assert ada["entries"] == [
        {"id": "a1", "text": "Ruben deploys on Fridays.", "importance": 8, "origin": "tool"}
    ]
    assert ada["editable"] is False
    assert [item["path"] for item in ada["mentions"]] == ["entities/ruben.md"]


def test_read_links_both_ways(client: TestClient) -> None:
    ruben = client.get("/api/wiki/read", params={"path": "entities/ruben.md"}).json()
    assert [item["path"] for item in ruben["outgoing"]] == ["projects/magenta.md"]
    assert [item["path"] for item in ruben["backlinks"]] == ["projects/magenta.md"]
    assert [item["path"] for item in ruben["mentioned_in"]] == ["society/ada/MEMORY.md"]
    assert ruben["properties"]["aliases"] == ["the user"]


def test_unknown_path_is_404(client: TestClient) -> None:
    response = client.get("/api/wiki/read", params={"path": "../secrets.md"})
    assert response.status_code == 404


def test_map_has_content_pages_only(client: TestClient) -> None:
    body = client.get("/api/wiki/map").json()
    ids = {node["id"] for node in body["nodes"]}
    assert ids == {"entities/ruben.md", "projects/magenta.md", "society/ada/MEMORY.md"}
    without_agents = client.get("/api/wiki/map", params={"agents": "false"}).json()
    assert {node["id"] for node in without_agents["nodes"]} == {
        "entities/ruben.md",
        "projects/magenta.md",
    }


def test_activity_skips_self_doc_refreshes(client: TestClient) -> None:
    items = client.get("/api/wiki/activity").json()["items"]
    assert [(item["verb"], [p["path"] for p in item["pages"]]) for item in items] == [
        ("create", ["entities/ruben.md"])
    ]


def test_create_save_rename_and_archive_round_trip(client: TestClient, vault: Path) -> None:
    created = client.post(
        "/api/wiki/pages", json={"kind": "entity", "title": "Maria Weber", "body_md": ""}
    )
    assert created.status_code == 200, created.text
    assert created.json()["path"] == "entities/maria-weber.md"
    text = (vault / "entities/maria-weber.md").read_text(encoding="utf-8")
    assert "slug: maria-weber" in text and "# Maria Weber" in text

    duplicate = client.post("/api/wiki/pages", json={"kind": "entity", "title": "Maria Weber"})
    assert duplicate.status_code == 409

    ruben = client.get("/api/wiki/read", params={"path": "entities/ruben.md"}).json()
    saved = client.put(
        "/api/wiki/pages",
        json={
            "path": "entities/ruben.md",
            "body_md": "# Ruben\n\nWorks with [[Someone New]] on [[projects/magenta]].",
            "base_mtime": ruben["mtime"],
        },
    )
    assert saved.status_code == 200, saved.text
    on_disk = (vault / "entities/ruben.md").read_text(encoding="utf-8")
    assert on_disk.startswith("---\ntype: entity\nslug: ruben\n")
    # A person's link to a page that does not exist yet is kept, not demoted.
    assert "[[Someone New]]" in on_disk

    renamed = client.post(
        "/api/wiki/pages/rename", json={"path": "projects/magenta.md", "title": "Magenta IDE"}
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json() == {
        "ok": True,
        "path": "projects/magenta-ide.md",
        "links_rewritten": 1,
        "links_unrewritten": 0,
    }
    assert not (vault / "projects/magenta.md").exists()
    assert "[[projects/magenta-ide]]" in (vault / "entities/ruben.md").read_text(encoding="utf-8")
    assert "slug: magenta-ide" in (vault / "projects/magenta-ide.md").read_text(encoding="utf-8")

    archived = client.post("/api/wiki/pages/archive", json={"path": "entities/maria-weber.md"})
    assert archived.status_code == 200, archived.text
    assert not (vault / "entities/maria-weber.md").exists()
    assert list((vault / "_archive").rglob("maria-weber*.md"))


def test_save_refuses_a_stale_editor_and_agent_notebooks(client: TestClient) -> None:
    stale = client.put(
        "/api/wiki/pages",
        json={"path": "entities/ruben.md", "body_md": "x", "base_mtime": _OLD - 100},
    )
    assert stale.status_code == 409

    notebook = client.put(
        "/api/wiki/pages",
        json={"path": "society/ada/MEMORY.md", "body_md": "x", "base_mtime": time.time()},
    )
    assert notebook.status_code == 403
    # Without the editor's base version there is no stale-write guard.
    unguarded = client.put("/api/wiki/pages", json={"path": "entities/ruben.md", "body_md": "x"})
    assert unguarded.status_code == 422


def test_tidy_previews_then_archives_only_empty_notebooks(client: TestClient, vault: Path) -> None:
    preview = client.post("/api/wiki/tidy", json={"dry_run": True}).json()
    assert preview["paths"] == [
        "society/ada/USER.md",
        "society/vega/MEMORY.md",
        "society/vega/USER.md",
    ]
    assert (vault / "society/vega/MEMORY.md").exists()

    done = client.post("/api/wiki/tidy", json={"dry_run": False}).json()
    assert done["count"] == 3
    assert not (vault / "society/vega/MEMORY.md").exists()
    assert (vault / "society/ada/MEMORY.md").exists()


def test_tidy_refuses_when_the_roster_does_not_answer(client: TestClient, vault: Path) -> None:
    # Without the roster every folder would look orphaned, live agents too.
    client.app.state.society = None  # type: ignore[attr-defined]
    response = client.post("/api/wiki/tidy", json={"dry_run": False})
    assert response.status_code == 503
    assert (vault / "society/vega/MEMORY.md").exists()
    # Reading still works; agents just fall back to their folder names.
    assert client.get("/api/wiki/index").status_code == 200


def test_writes_without_a_running_curator_say_why(client: TestClient) -> None:
    integration._set_running_curator(None)
    response = client.post("/api/wiki/pages", json={"kind": "concept", "title": "Idea"})
    assert response.status_code == 503
    assert "memory writer" in response.json()["detail"]
    assert client.get("/api/wiki/index").json()["writable"] is False
