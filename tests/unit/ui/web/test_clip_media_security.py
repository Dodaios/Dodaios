"""The sandboxed clip page may read the clip's media files and nothing else."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from dodaios.core import control_key
from dodaios.core.bus import EventBus
from dodaios.core.config import JarvisConfig
from dodaios.ui.web.missions_auth import reset_tokens
from dodaios.ui.web.server import WebServer
from dodaios.ui.web.surface_security import _clip_media_request

pytestmark = pytest.mark.no_auto_web_auth

_BASE_URL = "http://127.0.0.1:47821"
# What a request from the sandboxed (opaque-origin) clip page looks like.
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


def test_only_reads_of_clip_media_pass() -> None:
    assert _clip_media_request("/clip-media/abc/f.mp4", "GET")
    assert _clip_media_request("/clip-media/abc/f.mp4", "HEAD")
    assert not _clip_media_request("/clip-media/abc/f.mp4", "POST")
    assert not _clip_media_request("/api/nodes/abc/clip/media", "GET")


def test_the_clip_page_reaches_the_media_route(client: TestClient) -> None:
    # An unknown node: the route itself answers (404), the boundary let it through.
    response = client.get("/clip-media/000000000000/" + "ab" * 12 + ".mp4", headers=_FRAME_HEADERS)
    assert response.status_code == 404
    assert response.json().get("detail") == "unknown file"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/config"),
        ("POST", "/api/nodes/000000000000/clip/media"),
        ("POST", "/clip-media/000000000000/" + "ab" * 12 + ".mp4"),
    ],
)
def test_the_clip_page_is_refused_everywhere_else(
    client: TestClient, method: str, path: str
) -> None:
    response = client.request(method, path, headers=_FRAME_HEADERS)
    assert response.status_code in {401, 403, 405}
