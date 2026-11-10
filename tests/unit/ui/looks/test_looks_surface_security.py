"""The sandboxed look frame may read its own files and nothing else."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from dodaios.core import control_key
from dodaios.core.bus import EventBus
from dodaios.core.config import JarvisConfig
from dodaios.ui.web.missions_auth import reset_tokens
from dodaios.ui.web.server import WebServer

pytestmark = pytest.mark.no_auto_web_auth

_BASE_URL = "http://127.0.0.1:47821"
# What a request from the sandboxed (opaque-origin) frame looks like.
_FRAME_HEADERS = {
    "Host": "127.0.0.1:47821",
    "Origin": "null",
    "Sec-Fetch-Site": "cross-site",
}


@pytest.fixture(params=[True, False], ids=["locked", "open"])
def client(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    reset_tokens()
    cfg = JarvisConfig()
    cfg.ui.require_browser_login = request.param
    monkeypatch.setattr(control_key, "get_control_key", lambda: "jctl_test_key")
    server = WebServer(cfg, bus=EventBus())
    try:
        yield TestClient(server.app, base_url=_BASE_URL, client=("127.0.0.1", 50_000))
    finally:
        reset_tokens()


def test_frame_reads_its_own_files(client: TestClient) -> None:
    response = client.get("/looks-frame/pulse-ring/index.html", headers=_FRAME_HEADERS)
    assert response.status_code == 200
    assert "sandbox allow-scripts" in response.headers["content-security-policy"]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/config"),
        ("GET", "/api/looks"),
        ("PUT", "/api/looks/active"),
        ("POST", "/looks-frame/pulse-ring/index.html"),
    ],
)
def test_frame_is_refused_everywhere_else(client: TestClient, method: str, path: str) -> None:
    response = client.request(method, path, headers=_FRAME_HEADERS, json={"id": "orb"})
    assert response.status_code in {401, 403, 405}
