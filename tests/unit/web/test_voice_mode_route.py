"""The voice call status route, and an old ``[browser_voice]`` table still loading.

NOTE: the settings-route handler tests further down share this file — keep
additions here additive and self-contained.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.core import config as cfg_mod
from dodaios.ui.web.settings_routes import router


def test_an_old_browser_voice_table_still_loads(tmp_path: Path):
    # ``[browser_voice] enabled`` only gated the retired classic bridge; a
    # config that still carries it must boot unchanged.
    path = tmp_path / "jarvis.toml"
    path.write_text(
        '[browser_voice]\nenabled = false\n\n[integrations.twilio]\ngreeting = "Hi"\n',
        encoding="utf-8",
    )
    loaded = cfg_mod.load_config(path)
    assert loaded.integrations.twilio.greeting == "Hi"


# ---------------------------------------------------------------------------
# GET /api/settings/voice-mode: realtime provider and call status.
# ---------------------------------------------------------------------------


def _app():
    app = FastAPI()
    app.include_router(router)
    app.state.config = SimpleNamespace(voice=SimpleNamespace())
    return app


def test_get_voice_mode(monkeypatch):
    import dodaios.realtime.factory as rf

    def openai_only(candidates):
        keys = {c[0] for c in candidates}
        return "sk-x" if "openai_api_key" in keys else None

    monkeypatch.setattr(rf, "get_secret_any", openai_only)
    client = TestClient(_app())
    r = client.get("/api/settings/voice-mode")
    assert r.status_code == 200
    body = r.json()
    assert "mode" not in body
    assert body["realtime_available"] is True
    assert body["requires_webrtc_offer"] is False
    assert body["transport_offer_ready"] is None
    assert body["transport_offer_detail"] is None
    assert body["active_provider"] == "openai-live"
    # Sidebar display fields: registry label + the catalog-default model (no
    # pin configured in this app fixture).
    assert body["active_provider_label"] == "OpenAI GPT-Live"
    assert body["active_model"] == "gpt-live-1"
    assert body["active_model_label"] == "GPT-Live 1"
    assert body["session_active"] is False
    assert "active_session_mode" not in body


def test_get_voice_mode_reports_browser_offer_capability(monkeypatch):
    import dodaios.realtime.factory as rf
    from dodaios.ui.web import settings_routes

    # An offer-requiring transport without browser audio. Fixed here, because
    # without a pin the answer follows the host's real credentials.
    monkeypatch.setattr(rf, "realtime_browser_audio", lambda _cfg, **_kwargs: False)
    monkeypatch.setattr(
        settings_routes,
        "_realtime_available_provider",
        lambda _cfg: "openai-realtime",
    )
    monkeypatch.setattr(
        settings_routes,
        "_realtime_requires_webrtc_offer",
        lambda _cfg: True,
    )
    async def _offer_ready(_required: bool) -> bool:
        return True

    monkeypatch.setattr(
        settings_routes,
        "_realtime_transport_offer_ready",
        _offer_ready,
    )


    body = TestClient(_app()).get("/api/settings/voice-mode").json()

    assert body["active_provider"] == "openai-realtime"
    assert body["active_model"] == "gpt-realtime"
    assert body["active_model_label"] == "GPT Realtime (default)"
    assert body["requires_webrtc_offer"] is True
    assert body["transport_offer_ready"] is True
    assert body["transport_offer_detail"] == "Embedded desktop WebRTC offer is ready."


def test_get_voice_mode_scopes_renderer_audio_to_the_embedded_desktop(monkeypatch):
    import dodaios.realtime.factory as rf
    from dodaios.ui.web import settings_routes

    seen_renderers: list[str | None] = []

    def _browser_audio(_cfg, *, desktop_renderer=None):
        seen_renderers.append(desktop_renderer)
        return desktop_renderer != "gtkwebkit2"

    monkeypatch.setattr(rf, "realtime_browser_audio", _browser_audio)
    monkeypatch.setattr(settings_routes, "_realtime_available_provider", lambda _cfg: "gemini-live")
    monkeypatch.setattr(settings_routes, "_realtime_requires_webrtc_offer", lambda _cfg: False)
    app = _app()
    app.state.desktop_app = SimpleNamespace(
        realtime_audio_renderer=lambda: "gtkwebkit2",
    )
    client = TestClient(app)

    embedded = client.get("/api/settings/voice-mode?surface=desktop").json()
    browser = client.get("/api/settings/voice-mode").json()

    assert embedded["browser_audio"] is False
    assert browser["browser_audio"] is True
    assert seen_renderers == ["gtkwebkit2", None]


def test_get_voice_mode_cross_family_gemini_only(monkeypatch):
    """Feature A2: realtime_available must NOT be OpenAI-only — a user with
    only a Gemini key gets realtime_available=true, active_provider=gemini-live."""
    import dodaios.realtime.factory as rf

    def only_gemini(candidates: tuple[tuple[str, str | None], ...]) -> str | None:
        keys = {c[0] for c in candidates}
        return "sk-x" if "gemini_api_key" in keys else None

    monkeypatch.setattr(rf, "get_secret_any", only_gemini)
    client = TestClient(_app())
    r = client.get("/api/settings/voice-mode")
    assert r.status_code == 200
    body = r.json()
    assert body["realtime_available"] is True
    assert body["active_provider"] == "gemini-live"
    assert body["active_provider_label"] == "Gemini Live"
    assert body["active_model"] == "gemini-3.1-flash-live-preview"


def test_get_voice_mode_reports_browser_audio_of_the_automatic_provider(monkeypatch):
    """Issue #399: a Gemini-only install with no pinned realtime provider
    reported ``active_provider: gemini-live`` next to ``browser_audio: false``
    although Gemini Live declares browser audio."""
    import dodaios.realtime.factory as rf

    def only_gemini(candidates):
        keys = {c[0] for c in candidates}
        return "sk-x" if "gemini_api_key" in keys else None

    monkeypatch.setattr(rf, "get_secret_any", only_gemini)
    body = TestClient(_app()).get("/api/settings/voice-mode").json()
    assert body["active_provider"] == "gemini-live"
    assert body["browser_audio"] is True


def test_get_voice_mode_reports_pinned_realtime_model(monkeypatch):
    """A model pinned in [brain.providers.<id>].model outranks the catalog
    default in the sidebar display fields."""
    import dodaios.realtime.factory as rf

    def only_gemini(candidates):
        keys = {c[0] for c in candidates}
        return "sk-x" if "gemini_api_key" in keys else None

    monkeypatch.setattr(rf, "get_secret_any", only_gemini)
    app = _app()
    app.state.config.brain = SimpleNamespace(
        providers={
            "gemini-live": SimpleNamespace(
                model="gemini-2.5-flash-native-audio-latest", voice=""
            )
        }
    )
    body = TestClient(app).get("/api/settings/voice-mode").json()
    assert body["active_provider"] == "gemini-live"
    assert body["active_model"] == "gemini-2.5-flash-native-audio-latest"


def test_get_voice_mode_no_realtime_key_anywhere(monkeypatch):
    import dodaios.realtime.factory as rf
    monkeypatch.setattr(rf, "get_secret_any", lambda _candidates: None)
    client = TestClient(_app())
    r = client.get("/api/settings/voice-mode")
    body = r.json()
    assert body["realtime_available"] is False
    assert body["active_provider"] is None
    assert body["active_provider_label"] is None
    assert body["active_model"] is None


def test_the_engine_switch_is_gone():
    """Calls run only on realtime providers: there is nothing to switch."""
    r = TestClient(_app()).put("/api/settings/voice-mode", json={"mode": "pipeline"})
    assert r.status_code == 405


def test_get_voice_mode_reports_effective_active_engine(monkeypatch):
    import dodaios.realtime.factory as rf

    monkeypatch.setattr(rf, "get_secret_any", lambda _candidates: "sk-x")
    app = _app()
    app.state.speech_pipeline = SimpleNamespace(
        voice_engine_status=lambda: {
            "session_active": True,
            "active_session_provider": "openai-realtime",
            "active_session_model": "gpt-realtime-2.1",
            "transitioning": False,
        }
    )
    client = TestClient(app)

    body = client.get("/api/settings/voice-mode").json()

    assert "mode" not in body
    assert body["session_active"] is True
    assert body["active_session_provider"] == "openai-realtime"
    assert body["active_session_model"] == "gpt-realtime-2.1"
    assert body["active_session_model_label"] == "GPT Realtime 2.1"
    assert body["transitioning"] is False
