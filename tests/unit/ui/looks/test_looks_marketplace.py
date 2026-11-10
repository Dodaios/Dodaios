"""Looks in the community feed: listed, installed by name, removed by name.

A pre-seeded index cache and a fake download: the network is never touched.
"""

from __future__ import annotations

import hashlib
import io
import json
import time
import tomllib
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.core import config as config_module
from dodaios.core.config import UIConfig
from dodaios.marketplace import catalog_data, community_source
from dodaios.ui.looks import install
from dodaios.ui.web.marketplace_routes import router as market_router

LOOK_ID = "neat-ring"


def _archive() -> bytes:
    manifest = {
        "format": "dodaios-look/1",
        "id": LOOK_ID,
        "name": "Neat Ring",
        "author": "Someone",
        "version": "1.0.0",
        "license": "MIT",
        "preview": "preview.png",
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("look.json", json.dumps(manifest))
        archive.writestr("index.html", "<!doctype html>")
        archive.writestr("preview.png", b"\x89PNG\r\n\x1a\n")
    return buf.getvalue()


ARCHIVE = _archive()


def _index(sha: str) -> dict[str, Any]:
    return {
        "revision": 1,
        "looks": [
            {
                "name": LOOK_ID,
                "title": "Neat Ring",
                "publisher": "octocat",
                "version": "1.0.0",
                "license": "MIT",
                "archive_url": "https://github.com/o/r/releases/download/v1/neat-ring.zip",
                "sha256": sha,
                "size_bytes": len(ARCHIVE),
            },
            {"name": "../../evil", "archive_url": "https://github.com/x.zip"},
        ],
    }


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    community_source.reset_runtime_state()
    cache = tmp_path / "marketplace_index.json"
    sha = hashlib.sha256(ARCHIVE).hexdigest()
    cache.write_text(
        json.dumps({"fetched_at": time.time(), "index": _index(sha)}), encoding="utf-8"
    )
    monkeypatch.setattr(community_source, "_CACHE_PATH", cache)
    monkeypatch.setattr(community_source, "index_url", lambda: "https://reg.example/index.json")
    monkeypatch.setattr(catalog_data, "_DEFAULT_CATALOG_PATH", tmp_path / "plugin_catalog.json")
    catalog_data.clear_cache()
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(config_module, "DATA_DIR", data)
    toml = tmp_path / "jarvis.toml"
    toml.write_text("[ui]\n", encoding="utf-8")
    monkeypatch.setenv("JARVIS_CONFIG", str(toml))

    downloads: list[str] = []

    async def fake_download(url: str, *, max_bytes: int) -> bytes:
        downloads.append(url)
        return ARCHIVE

    monkeypatch.setattr(install, "download", fake_download)
    app = FastAPI()
    app.include_router(market_router)
    app.state.config = SimpleNamespace(ui=UIConfig(look_id=LOOK_ID))
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, data=data, toml=toml, downloads=downloads, app=app)
    community_source.reset_runtime_state()


def test_feed_lists_the_valid_look_only(env: SimpleNamespace) -> None:
    looks = env.client.get("/api/marketplace/community").json()["looks"]
    assert [look["name"] for look in looks] == [LOOK_ID]
    assert looks[0]["installed"] is False


def test_install_and_remove_by_name(env: SimpleNamespace) -> None:
    response = env.client.post(f"/api/marketplace/community/install/{LOOK_ID}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == "look" and body["ready"] is True
    assert (env.data / "looks" / LOOK_ID / "look.json").is_file()
    assert env.client.get("/api/marketplace/community").json()["looks"][0]["installed"] is True

    removed = env.client.delete(f"/api/marketplace/community/install/{LOOK_ID}")
    assert removed.json() == {"ok": True, "removed": True, "kind": "look", "id": LOOK_ID}
    assert not (env.data / "looks" / LOOK_ID).exists()
    # It was the active look, so the orb takes its place again.
    assert env.app.state.config.ui.look_id == "orb"
    assert tomllib.loads(env.toml.read_text(encoding="utf-8"))["ui"]["look_id"] == "orb"


def test_a_tampered_download_is_refused(
    env: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def tampered(url: str, *, max_bytes: int) -> bytes:
        return ARCHIVE + b"x"

    monkeypatch.setattr(install, "download", tampered)
    response = env.client.post(f"/api/marketplace/community/install/{LOOK_ID}")
    assert response.status_code == 422
    assert "checksum" in response.json()["detail"]
    assert not (env.data / "looks" / LOOK_ID).exists()
