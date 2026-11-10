"""POST /api/voice/warm and GET/PUT /api/voice/voices (the call window's picker)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.speech import call_warmup
from dodaios.ui.web import voice_call_routes as routes


class _Warmer:
    def __init__(self) -> None:
        self.kicks: list[tuple] = []

    async def kick(self, pipeline, config) -> bool:
        self.kicks.append((pipeline, config))
        return len(self.kicks) == 1


@pytest.fixture
def app(monkeypatch):
    application = FastAPI()
    application.include_router(routes.router)
    application.state.config = SimpleNamespace(
        voice=SimpleNamespace(mode="pipeline"),
        brain=SimpleNamespace(realtime=SimpleNamespace(provider="")),
        tts=SimpleNamespace(voice_de="Kore"),
    )
    monkeypatch.setattr(routes, "_pipeline", lambda: None)
    return application


def test_warm_answers_at_once_and_is_debounced(app) -> None:
    warmer = _Warmer()
    call_warmup.set_call_warmer(warmer)
    try:
        with TestClient(app) as client:
            assert client.post("/api/voice/warm").json() == {"warming": True}
            assert client.post("/api/voice/warm").json() == {"warming": False}
    finally:
        call_warmup.set_call_warmer(None)
    assert len(warmer.kicks) == 2
    assert warmer.kicks[0][1] is app.state.config


def test_voice_path_follows_a_running_session_then_the_configuration() -> None:
    cfg = SimpleNamespace(
        voice=SimpleNamespace(mode="realtime"),
        brain=SimpleNamespace(realtime=SimpleNamespace(provider="gemini-live")),
    )
    running = SimpleNamespace(voice_engine_status=lambda: {
        "session_active": True, "active_session_mode": "pipeline", "configured_mode": "realtime",
    })
    assert routes._voice_path(cfg, running) == ("tts", "")
    idle = SimpleNamespace(voice_engine_status=lambda: {
        "session_active": False, "configured_mode": "realtime",
    })
    assert routes._voice_path(cfg, idle) == ("realtime", "gemini-live")
    assert routes._voice_path(cfg, None) == ("realtime", "gemini-live")
    live_cfg = SimpleNamespace(
        voice=SimpleNamespace(mode="realtime"),
        brain=SimpleNamespace(realtime=SimpleNamespace(provider="openai-live")),
    )
    assert routes._voice_path(live_cfg, None) == ("live", "openai-live")
    classic = SimpleNamespace(voice=SimpleNamespace(mode="pipeline"), brain=SimpleNamespace())
    assert routes._voice_path(classic, None) == ("tts", "")


def test_tts_voices_come_from_the_active_tts_provider(app, monkeypatch) -> None:
    monkeypatch.setattr(
        "dodaios.ui.web.provider_routes._active_tts", lambda _request: "gemini-flash-tts"
    )
    entries = [{"id": "Kore", "language": "multi"}, {"id": "Puck", "language": "multi"}]
    monkeypatch.setattr(
        "dodaios.ui.web.provider_routes._tts_voice_entries",
        lambda provider, model: (entries, "m", "Puck"),
    )
    with TestClient(app) as client:
        body = client.get("/api/voice/voices").json()
    assert body["path"] == "tts"
    assert body["provider"] == "gemini-flash-tts"
    assert [v["id"] for v in body["voices"]] == ["Kore", "Puck"]
    assert body["current"] == "Kore"
    assert body["default"] == "Puck"
    assert body["applies"] == "now"


def test_realtime_voices_come_from_the_curated_catalog(app, monkeypatch) -> None:
    app.state.config.voice.mode = "realtime"
    app.state.config.brain.realtime.provider = "gemini-live"
    app.state.config.brain.providers = {"gemini-live": SimpleNamespace(model="", voice="Kore")}
    with TestClient(app) as client:
        body = client.get("/api/voice/voices").json()
    assert body["path"] == "realtime"
    assert body["provider"] == "gemini-live"
    assert body["current"] == "Kore"
    assert any(v["id"] == "Kore" for v in body["voices"])


def test_picking_a_tts_voice_uses_the_one_writer(app, monkeypatch) -> None:
    written: list[str] = []

    async def fake_set(body, request):
        written.append(body.voice)
        return {"ok": True}

    monkeypatch.setattr("dodaios.ui.web.provider_routes.set_tts_voice_selection", fake_set)
    monkeypatch.setattr(
        "dodaios.ui.web.provider_routes._active_tts", lambda _request: "gemini-flash-tts"
    )
    with TestClient(app) as client:
        body = client.put("/api/voice/voices", json={"voice": "Puck"}).json()
    assert written == ["Puck"]
    assert body["ok"] is True and body["voice"] == "Puck" and body["applies"] == "now"


def test_picking_a_live_voice_rewrites_the_profile(app, monkeypatch) -> None:
    saved: list = []

    async def fake_save(body, request):
        saved.append(body)
        return {"profile": body.model_dump(), "applies": "next_call"}

    from dodaios.live.config import LiveConfig

    app.state.config.voice.mode = "realtime"
    app.state.config.brain.realtime.provider = "openai-live"
    app.state.config.live = LiveConfig(voice="gleam", backend_model="m")
    monkeypatch.setattr("dodaios.ui.web.live_routes.save_live_profile", fake_save)
    with TestClient(app) as client:
        listed = client.get("/api/voice/voices").json()
        assert listed["path"] == "live" and listed["current"] == "gleam"
        assert "quartz" in {v["id"] for v in listed["voices"]}
        assert client.put("/api/voice/voices", json={"voice": "nobody"}).status_code == 422
        body = client.put("/api/voice/voices", json={"voice": "quartz"}).json()
    assert body["applies"] == "next_call"
    assert saved and saved[0].voice == "quartz"
