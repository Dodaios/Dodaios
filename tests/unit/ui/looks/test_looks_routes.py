"""REST contract of the looks (``dodaios/ui/web/looks_routes.py``, docs/looks.md)."""

from __future__ import annotations

import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.core import config as config_module
from dodaios.core.config import UIConfig
from dodaios.ui.web.looks_routes import frame_csp, frame_router, router


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(config_module, "DATA_DIR", data)
    toml = tmp_path / "jarvis.toml"
    toml.write_text("[ui]\n", encoding="utf-8")
    monkeypatch.setenv("JARVIS_CONFIG", str(toml))
    app = FastAPI()
    app.include_router(router)
    app.include_router(frame_router)
    app.state.config = SimpleNamespace(ui=UIConfig())
    return SimpleNamespace(client=TestClient(app), app=app, toml=toml)


def test_list_has_the_builtin_example_and_defaults_to_orb(env: SimpleNamespace) -> None:
    body = env.client.get("/api/looks").json()
    assert body["active"] == "orb"
    ring = next(look for look in body["looks"] if look["id"] == "pulse-ring")
    assert ring["frame_url"] == "/looks-frame/pulse-ring/index.html"
    assert ring["preview_url"] == "/api/looks/pulse-ring/preview"


def test_pick_saves_and_back_to_orb(env: SimpleNamespace) -> None:
    response = env.client.put("/api/looks/active", json={"id": "pulse-ring"})
    assert response.status_code == 200
    assert response.json()["active"] == "pulse-ring"
    saved = tomllib.loads(env.toml.read_text(encoding="utf-8"))["ui"]["look_id"]
    assert saved == "pulse-ring"

    assert env.client.put("/api/looks/active", json={"id": "orb"}).json()["active"] == "orb"


@pytest.mark.parametrize(("look_id", "status"), [("missing-look", 404), ("../x", 400)])
def test_pick_refuses_unknown_and_malformed(
    env: SimpleNamespace, look_id: str, status: int
) -> None:
    assert env.client.put("/api/looks/active", json={"id": look_id}).status_code == status


def test_frame_file_carries_the_sandbox_policy(env: SimpleNamespace) -> None:
    response = env.client.get("/looks-frame/pulse-ring/index.html")
    assert response.status_code == 200
    csp = response.headers["content-security-policy"]
    assert "sandbox allow-scripts" in csp
    assert "default-src 'none'" in csp
    assert "http://testserver/looks-frame/pulse-ring/" in csp
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize(
    "path",
    [
        "/looks-frame/pulse-ring/..%2F..%2Floader.py",
        "/looks-frame/pulse-ring/missing.js",
        "/looks-frame/no-such-look/index.html",
        "/looks-frame/pulse-ring/%2e%2e/x.html",
    ],
)
def test_frame_refuses_anything_outside_a_pack(env: SimpleNamespace, path: str) -> None:
    assert env.client.get(path).status_code == 404


def test_preview_is_served(env: SimpleNamespace) -> None:
    response = env.client.get("/api/looks/pulse-ring/preview")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")


def test_csp_limits_every_load_to_the_pack() -> None:
    csp = frame_csp("http://h/looks-frame/x/")
    for directive in ("script-src", "img-src", "connect-src", "style-src", "font-src"):
        part = next(p for p in csp.split("; ") if p.startswith(directive))
        assert "'self'" not in part and "*" not in part and "http://h/looks-frame/x/" in part


def test_bad_look_id_in_config_falls_back_to_orb() -> None:
    assert UIConfig(look_id="../evil").look_id == "orb"
    assert UIConfig(look_id="Pulse-Ring").look_id == "pulse-ring"
