"""What keeps the store fast and complete.

The index reader answers a poll from memory, opens the store from an expired
cache without waiting on the registry, and leaves the network alone right
after a failure. The routes read an entry's files out of the feed instead of
downloading them again, list a skill under its own frontmatter description
when the listing text is unusable, and remove an installed entry by name.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from dodaios.marketplace import catalog_data, community_source
from dodaios.marketplace.agent_plugins_loader import EXTENSION_NAMESPACE
from dodaios.ui.web import marketplace_routes
from dodaios.ui.web.marketplace_routes import router

SKILL_MD = (
    "---\n"
    "name: humanizer\n"
    "description: |\n"
    "  Rewrite AI-sounding text so it reads naturally.\n"
    "  Use when editing prose.\n"
    "license: MIT\n"
    "---\n\n# Humanizer\n\nRewrite the text.\n"
)


def _payload(revision: int = 1) -> dict[str, Any]:
    return {
        "revision": revision,
        "generated_at": "2026-11-10T09:00:00Z",
        "plugins": [
            {
                "name": "todo-fox",
                "publisher": "octocat",
                "publisher_id": 583231,
                "featured": True,
                "version": "1.2.0",
                "plugin_json": {
                    "name": "todo-fox",
                    "description": "Tasks and reminders from TodoFox",
                    "version": "1.2.0",
                    "license": "MIT",
                    "extensions": {
                        EXTENSION_NAMESPACE: {
                            "display_name": "TodoFox",
                            "category": "Lists & Tasks",
                            "auth": {
                                "mode": "pat_paste",
                                "token_creation_url": "https://todofox.example/settings/tokens",
                                "token_prefix": "tfx_",
                                "validation_endpoint": "https://api.todofox.example/v1/me",
                                "instruction_md": "Create a token in Settings.",
                            },
                        }
                    },
                },
                "mcp_json": {
                    "mcpServers": {
                        "todo-fox": {
                            "type": "streamable-http",
                            "url": "https://mcp.todofox.example/mcp",
                        }
                    }
                },
            }
        ],
        "skills": [
            {
                "name": "humanizer",
                "title": "Humanizer",
                # What the registry has really served for a block-scalar
                # description: the YAML marker, not the text.
                "description": "|",
                "publisher": "octocat",
                "publisher_id": 583231,
                "raw_url": "https://raw.example/skills/humanizer/SKILL.md",
                "skill_md": SKILL_MD,
                "files": [
                    {"path": "SKILL.md", "size": len(SKILL_MD.encode()), "text": SKILL_MD},
                    {"path": "references/tone.md", "size": 6, "text": "# Tone"},
                    {"path": "logo.png", "size": 2048, "text": None},
                    {"path": "../escape.md", "size": 1, "text": "x"},
                ],
            }
        ],
        "agents": [
            {
                "name": "release-captain",
                "title": "Release Captain",
                "description": "Cuts a release.",
                "publisher": "octocat",
                "agent": {"schema": 1, "name": "Release Captain"},
            }
        ],
    }


@pytest.fixture()
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    cache = tmp_path / "marketplace_index.json"
    monkeypatch.setattr(community_source, "_CACHE_PATH", cache)
    monkeypatch.setattr(community_source, "index_url", lambda: "https://reg.example/index.json")
    monkeypatch.setattr(catalog_data, "_DEFAULT_CATALOG_PATH", tmp_path / "plugin_catalog.json")
    monkeypatch.setattr("dodaios.core.paths.user_skills_dir", lambda: tmp_path / "skills")
    marketplace_routes._content_cache.clear()
    catalog_data.clear_cache()
    yield cache
    marketplace_routes._content_cache.clear()
    catalog_data.clear_cache()


def _seed(cache: Path, *, age: float = 0.0, revision: int = 1) -> None:
    cache.write_text(
        json.dumps({"fetched_at": time.time() - age, "index": _payload(revision)}),
        encoding="utf-8",
    )


def _client() -> httpx.AsyncClient:
    app = FastAPI()
    app.include_router(router)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


# --- the index reader -------------------------------------------------------


async def test_a_second_read_reuses_the_parsed_index(store: Path) -> None:
    _seed(store)
    first, _ = await community_source.get_index()
    second, _ = await community_source.get_index()
    # The same object: nothing was read from disk or validated again.
    assert first is second


async def test_a_changed_cache_file_is_read_again(store: Path) -> None:
    _seed(store, revision=1)
    first, _ = await community_source.get_index()
    _seed(store, revision=2)
    second, _ = await community_source.get_index()
    assert first is not None and second is not None
    assert (first.revision, second.revision) == (1, 2)


async def test_browsing_an_expired_cache_answers_at_once_and_revalidates(store: Path) -> None:
    _seed(store, age=3600, revision=1)
    asked = asyncio.Event()

    def handler(request: httpx.Request) -> httpx.Response:
        asked.set()
        return httpx.Response(200, json=_payload(revision=2))

    index, status = await community_source.get_index(
        background=True, transport=httpx.MockTransport(handler)
    )
    # The old index is on screen before the registry was even asked.
    assert status == "revalidating"
    assert index is not None and index.revision == 1

    task = community_source._revalidation
    assert task is not None
    await task
    assert asked.is_set()
    fresh, status = await community_source.get_index(background=True)
    assert status == "fresh"
    assert fresh is not None and fresh.revision == 2


async def test_acting_on_an_expired_cache_still_asks_the_registry_first(store: Path) -> None:
    _seed(store, age=3600, revision=1)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_payload(revision=2))

    # No ``background``: this is the path an install takes.
    index, status = await community_source.get_index(transport=httpx.MockTransport(handler))
    assert status == "fetched"
    assert index is not None and index.revision == 2


async def test_after_a_failure_browsing_does_not_try_the_network_again(store: Path) -> None:
    _seed(store, age=3600)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("offline")

    transport = httpx.MockTransport(handler)
    _, status = await community_source.get_index(background=True, transport=transport)
    assert status == "revalidating"
    task = community_source._revalidation
    assert task is not None
    await task
    assert calls == 1

    for _ in range(3):
        index, status = await community_source.get_index(background=True, transport=transport)
        assert status == "stale"
        assert index is not None
    assert calls == 1  # answered from the cache, the network left alone


async def test_refresh_ignores_the_backoff(store: Path) -> None:
    _seed(store, age=3600, revision=1)
    online = False

    def handler(request: httpx.Request) -> httpx.Response:
        if not online:
            raise httpx.ConnectError("offline")
        return httpx.Response(200, json=_payload(revision=2))

    transport = httpx.MockTransport(handler)
    _, status = await community_source.get_index(transport=transport)
    assert status == "stale"
    online = True
    index, status = await community_source.get_index(force=True, transport=transport)
    assert status == "fetched"
    assert index is not None and index.revision == 2


# --- descriptions -----------------------------------------------------------


def test_a_leaked_yaml_marker_falls_back_to_the_frontmatter() -> None:
    entry = community_source.CommunitySkillEntry.model_validate(_payload()["skills"][0])
    assert community_source.skill_description(entry) == (
        "Rewrite AI-sounding text so it reads naturally. Use when editing prose."
    )


def test_a_real_listing_text_is_kept() -> None:
    raw = {**_payload()["skills"][0], "description": "Makes text read naturally."}
    entry = community_source.CommunitySkillEntry.model_validate(raw)
    assert community_source.skill_description(entry) == "Makes text read naturally."


def test_no_usable_text_anywhere_is_an_empty_description() -> None:
    raw = {**_payload()["skills"][0], "skill_md": "no frontmatter here"}
    entry = community_source.CommunitySkillEntry.model_validate(raw)
    assert community_source.skill_description(entry) == ""


def test_a_long_frontmatter_description_is_cut_at_a_sentence() -> None:
    long = "First sentence is short. " + "Then it goes on and on. " * 30
    raw = {
        **_payload()["skills"][0],
        "skill_md": f"---\nname: x\ndescription: >-\n  {long}\n---\nbody",
    }
    entry = community_source.CommunitySkillEntry.model_validate(raw)
    text = community_source.skill_description(entry)
    assert len(text) <= 280
    assert text.endswith(".")


# --- routes -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_browse_lists_the_derived_description_and_the_publisher_id(store: Path) -> None:
    _seed(store)
    async with _client() as client:
        data = (await client.get("/api/marketplace/community")).json()
    skill = data["skills"][0]
    assert skill["description"].startswith("Rewrite AI-sounding text")
    assert skill["publisher_id"] == 583231
    plugin = data["plugins"][0]
    assert plugin["valid"] is True
    assert plugin["publisher_id"] == 583231
    assert plugin["featured"] is True
    assert plugin["installed"] is False


@pytest.mark.asyncio
async def test_browse_does_not_convert_the_same_index_twice(
    store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dodaios.marketplace import agent_plugins_loader

    _seed(store)
    calls = 0
    real = agent_plugins_loader.convert_manifest

    def counting(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(agent_plugins_loader, "convert_manifest", counting)
    monkeypatch.setattr(marketplace_routes, "_converted_cache", None)
    async with _client() as client:
        first = (await client.get("/api/marketplace/community")).json()
        second = (await client.get("/api/marketplace/community")).json()
    assert calls == 1
    assert first["plugins"] == second["plugins"]


@pytest.mark.asyncio
async def test_contents_come_out_of_the_feed_without_a_download(
    store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(store)

    async def no_download(*args: Any, **kwargs: Any) -> Any:  # pragma: no cover
        raise AssertionError("the feed embeds the files; nothing may be downloaded")

    monkeypatch.setattr(marketplace_routes, "_download_text", no_download)
    async with _client() as client:
        data = (await client.get("/api/marketplace/community/humanizer/contents")).json()
    assert data["kind"] == "skill"
    paths = [f["path"] for f in data["files"]]
    # The whole folder, and never a path that climbs out of it.
    assert paths == ["SKILL.md", "references/tone.md", "logo.png"]
    assert data["files"][0]["text"] == SKILL_MD
    assert data["files"][2]["truncated"] is True


@pytest.mark.asyncio
async def test_an_agent_has_contents_too(store: Path) -> None:
    _seed(store)
    async with _client() as client:
        res = await client.get("/api/marketplace/community/release-captain/contents")
    assert res.status_code == 200
    data = res.json()
    assert data["kind"] == "agent"
    assert data["files"][0]["path"] == "agent.json"
    assert json.loads(data["files"][0]["text"])["name"] == "Release Captain"


@pytest.mark.asyncio
async def test_remove_by_name_uninstalls_a_plugin(store: Path) -> None:
    _seed(store)
    async with _client() as client:
        installed = await client.post("/api/marketplace/community/install/todo-fox")
        assert installed.status_code == 200
        removed = await client.delete("/api/marketplace/community/install/todo-fox")
        assert removed.status_code == 200
        assert removed.json()["kind"] == "plugin"
        data = (await client.get("/api/marketplace/community")).json()
    assert data["plugins"][0]["installed"] is False


@pytest.mark.asyncio
async def test_remove_by_name_says_where_an_agent_is_removed(store: Path) -> None:
    _seed(store)
    async with _client() as client:
        res = await client.delete("/api/marketplace/community/install/release-captain")
    assert res.status_code == 409
    assert "Agents" in res.json()["detail"]


@pytest.mark.asyncio
async def test_remove_by_name_of_something_not_installed_is_a_404(store: Path) -> None:
    _seed(store)
    async with _client() as client:
        res = await client.delete("/api/marketplace/community/install/humanizer")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_remove_by_name_deletes_an_installed_skill(
    store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed(store)
    skills = store.parent / "skills"
    (skills / "humanizer").mkdir(parents=True)
    (skills / "humanizer" / "SKILL.md").write_text(SKILL_MD, encoding="utf-8")
    deleted: list[str] = []
    monkeypatch.setattr(
        "dodaios.ui.web.skills_routes.delete_skill",
        lambda name, request: deleted.append(name),
    )
    async with _client() as client:
        res = await client.delete("/api/marketplace/community/install/humanizer")
    assert res.status_code == 200
    assert res.json() == {"ok": True, "removed": True, "kind": "skill", "id": "humanizer"}
    assert deleted == ["humanizer"]


def test_a_name_that_climbs_out_of_the_skills_folder_matches_nothing(
    store: Path,
) -> None:
    outside = store.parent / "outside"
    outside.mkdir()
    (outside / "SKILL.md").write_text("x", encoding="utf-8")
    (store.parent / "skills").mkdir()
    assert marketplace_routes._installed_user_skill("../outside") is None
    assert marketplace_routes._installed_user_skill("") is None
