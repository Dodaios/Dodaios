"""Integration tests for /api/settings/silence-window (the think-buffer slider)."""
from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from dodaios.core.bus import EventBus
from dodaios.core.config import JarvisConfig
from dodaios.ui.web.server import WebServer


@pytest.fixture
def server() -> Iterator[WebServer]:
    cfg = JarvisConfig()
    cfg.ui.dev_mode = True
    bus = EventBus()
    s = WebServer(cfg, bus=bus)
    s.app.state.config = cfg
    s.app.state.bus = bus
    yield s


@pytest.fixture(autouse=True)
def _no_toml_write(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    calls: list[int] = []
    from dodaios.core import config_writer

    monkeypatch.setattr(
        config_writer, "set_silence_window_ms", lambda ms, **kw: calls.append(ms)
    )
    return calls


def test_get_returns_current_and_bounds(server: WebServer) -> None:
    with TestClient(server.app) as client:
        body = client.get("/api/settings/silence-window").json()
        assert body == {
            "ms": 0,
            "default": 0,
            "min": 0,
            "max": 5000,
            "manual_min": 500,
            "automatic": True,
        }


def test_put_persists_and_applies_to_the_next_call(
    server: WebServer, _no_toml_write: list[int]
) -> None:
    with TestClient(server.app) as client:
        resp = client.put("/api/settings/silence-window", json={"ms": 2500})
        assert resp.status_code == 200
        body = resp.json()
        assert body["ms"] == 2500
        assert body["applied_live"] is True
        assert body["restart_required"] is False
        assert _no_toml_write == [2500]
        # in-memory cfg reflects it: the next realtime call reads it
        assert server.app.state.config.speech.vad_silence_ms == 2500


def test_put_out_of_range_is_rejected(server: WebServer) -> None:
    with TestClient(server.app) as client:
        # Body validation (Pydantic Field ge/le) → FastAPI 422; both 400 and 422
        # are correct "rejected" semantics.
        assert client.put(
            "/api/settings/silence-window", json={"ms": -1}
        ).status_code in (400, 422)
        assert client.put(
            "/api/settings/silence-window", json={"ms": 9000}
        ).status_code in (400, 422)


def test_put_snaps_the_gap_below_the_floor_up(server: WebServer) -> None:
    """100 ms is inside the dead gap a drag passes through, not a choice.

    It snaps up to the lowest real window instead of being rejected, so a
    slider release mid-gap can never fail the save.
    """
    with TestClient(server.app) as client:
        body = client.put("/api/settings/silence-window", json={"ms": 100}).json()
        assert body["ms"] == 500
        assert body["automatic"] is False


def test_put_automatic_is_accepted(server: WebServer) -> None:
    """0 means "let every engine use its own factory timing" — a valid save."""
    with TestClient(server.app) as client:
        body = client.put("/api/settings/silence-window", json={"ms": 0}).json()
        assert body["ms"] == 0
        assert body["automatic"] is True
        assert server.app.state.config.speech.vad_silence_ms == 0
