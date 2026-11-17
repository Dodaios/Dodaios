"""Integration tests for /api/settings/agent-briefs.

Settings and the assistant (``agent-briefs-set``) store the person's standing
wishes for agent briefs through these endpoints; an empty list or a delete
goes back to the default, where the agent ships its own work.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

import dodaios.core.config as core_config
from dodaios.core import brief_wishes
from dodaios.core.agent_brief import REAL_LIMITS, SHIP_DEFAULT
from dodaios.core.bus import EventBus
from dodaios.core.config import JarvisConfig
from dodaios.ui.web.server import WebServer

URL = "/api/settings/agent-briefs"


@pytest.fixture(autouse=True)
def _isolate_data_dir(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(core_config, "DATA_DIR", tmp_path)


@pytest.fixture
def client() -> Iterator[TestClient]:
    cfg = JarvisConfig()
    cfg.ui.dev_mode = True
    bus = EventBus()
    server = WebServer(cfg, bus=bus)
    server.app.state.config = cfg
    server.app.state.bus = bus
    with TestClient(server.app) as test_client:
        yield test_client


def test_get_shows_the_default_and_the_limits_without_wishes(client: TestClient) -> None:
    body = client.get(URL).json()
    assert body["wishes"] == ""
    assert body["is_custom"] is False
    assert body["default"] == SHIP_DEFAULT
    assert body["limits"] == REAL_LIMITS
    assert body["max_chars"] == brief_wishes.MAX_WISHES_CHARS


def test_put_replaces_the_whole_list_and_the_next_brief_reads_it(client: TestClient) -> None:
    resp = client.put(URL, json={"wishes": "I approve every PR myself\nAlways with tests"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True and body["restart_required"] is False
    assert body["wishes"] == "I approve every PR myself\nAlways with tests"
    assert body["is_custom"] is True
    assert brief_wishes.read_wishes() == body["wishes"]

    again = client.put(URL, json={"wishes": "Write the prompts in English"}).json()
    assert again["wishes"] == "Write the prompts in English"


def test_an_empty_put_and_a_delete_go_back_to_the_default(client: TestClient) -> None:
    client.put(URL, json={"wishes": "Always with tests"})
    cleared = client.put(URL, json={"wishes": ""}).json()
    assert cleared["is_custom"] is False and cleared["wishes"] == ""

    client.put(URL, json={"wishes": "Always with tests"})
    deleted = client.delete(URL).json()
    assert deleted["removed"] is True
    assert deleted["is_custom"] is False


def test_a_list_past_the_limit_is_refused(client: TestClient) -> None:
    resp = client.put(URL, json={"wishes": "x" * (brief_wishes.MAX_WISHES_CHARS + 1)})
    assert resp.status_code == 400
    assert brief_wishes.read_wishes() == ""
