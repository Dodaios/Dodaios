"""POST /api/tts/read-aloud: the read-aloud button under an agent's answer."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from dodaios.core.bus import EventBus
from dodaios.core.config import JarvisConfig
from dodaios.core.protocols import AudioChunk
from dodaios.ui.web.server import WebServer


@pytest.fixture
def server() -> Iterator[WebServer]:
    cfg = JarvisConfig()
    cfg.ui.dev_mode = True
    srv = WebServer(cfg, bus=EventBus())
    srv.app.state.config = cfg
    yield srv


class _FakeTTS:
    def __init__(self, captured: dict[str, object], *, fail: bool = False) -> None:
        self.captured = captured
        self.fail = fail

    async def synthesize(self, text, voice=None, language_code=None):
        self.captured["text"] = text
        self.captured["language_code"] = language_code
        if self.fail:
            raise RuntimeError("No API key found")
        yield AudioChunk(pcm=b"\x01\x02" * 240, sample_rate=24_000, timestamp_ns=0, channels=1)

    async def aclose(self) -> None:
        self.captured["closed"] = True


def _use(monkeypatch: pytest.MonkeyPatch, tts: _FakeTTS) -> None:
    monkeypatch.setattr("dodaios.plugins.tts.build_tts_from_config", lambda _cfg: tts)


def test_read_aloud_returns_wav_in_the_texts_language(
    server: WebServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}
    _use(monkeypatch, _FakeTTS(captured))
    # i18n-allow: German input under test
    german = "Ich habe die Datei geändert und die Tests sind jetzt grün."  # i18n-allow
    with TestClient(server.app) as client:
        resp = client.post("/api/tts/read-aloud", json={"text": german})
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "audio/wav"
    assert resp.headers["x-read-language"] == "de"
    assert resp.content[:4] == b"RIFF"
    assert captured["language_code"] == "de-DE"
    assert captured.get("closed") is True


def test_read_aloud_keeps_the_language_it_is_given(
    server: WebServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}
    _use(monkeypatch, _FakeTTS(captured))
    with TestClient(server.app) as client:
        resp = client.post("/api/tts/read-aloud", json={"text": "OK.", "language": "en"})
    assert resp.status_code == 200
    assert resp.headers["x-read-language"] == "en"
    assert captured["language_code"] == "en-US"


def test_read_aloud_rejects_empty_text(server: WebServer) -> None:
    with TestClient(server.app) as client:
        assert client.post("/api/tts/read-aloud", json={"text": "  "}).status_code == 400


def test_read_aloud_maps_a_provider_error_to_502(
    server: WebServer, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use(monkeypatch, _FakeTTS({}, fail=True))
    with TestClient(server.app) as client:
        resp = client.post("/api/tts/read-aloud", json={"text": "Hello there, how are you?"})
    assert resp.status_code == 502
    assert "API key" in resp.json()["detail"]
