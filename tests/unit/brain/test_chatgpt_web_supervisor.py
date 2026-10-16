"""ChatGPT web bridge supervisor: a missing sign-in is login_required, not a crash."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from jarvis.plugins.brain import chatgpt_web_bridge
from jarvis.plugins.brain.chatgpt_web_bridge import BridgeSettings, BridgeSupervisor


class _DownClient:
    def get(self, url: str, **_: object) -> httpx.Response:
        raise httpx.ConnectError("down")


class _DownPool:
    def client(self) -> _DownClient:
        return _DownClient()


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "config.json").write_text(json.dumps({"apiToken": "t"}), encoding="utf-8")
    cli = tmp_path / "provider-cli.mjs"
    cli.write_text("", encoding="utf-8")
    s = BridgeSettings(
        base_url="http://127.0.0.1:17852",
        home=tmp_path,
        cli=cli,
        runtime="bun",
        log_dir=tmp_path / "logs",
    )
    monkeypatch.setattr(chatgpt_web_bridge, "settings", lambda: s)
    monkeypatch.setattr(chatgpt_web_bridge, "_probe_pool", _DownPool())
    monkeypatch.setattr(chatgpt_web_bridge.cfg, "get_secret", lambda *_: None)
    return tmp_path


def _spawn_forbidden(*_: object, **__: object) -> None:
    raise AssertionError("serve must not start without a saved login")


def test_no_login_reports_login_required_and_never_spawns(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(chatgpt_web_bridge.subprocess, "Popen", _spawn_forbidden)
    sup = BridgeSupervisor()
    for _ in range(10):
        assert sup.start().status == "login_required"
    assert sup.status().status == "login_required"


def test_saved_login_reads_offline(home: Path) -> None:
    marker = home / "browser" / "storage-state.json.verified.json"
    marker.parent.mkdir()
    marker.write_text(json.dumps({"version": 1, "authenticated": True}), encoding="utf-8")
    assert BridgeSupervisor().status().status == "offline"


def test_unauthenticated_marker_is_no_login(home: Path) -> None:
    marker = home / "browser" / "storage-state.json.verified.json"
    marker.parent.mkdir()
    marker.write_text(json.dumps({"authenticated": False}), encoding="utf-8")
    assert BridgeSupervisor().status().status == "login_required"
