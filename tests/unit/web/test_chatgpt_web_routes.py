"""ChatGPT web bridge routes and card health, against a fake supervisor."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from jarvis.plugins.brain import chatgpt_web_bridge
from jarvis.plugins.brain.chatgpt_web_bridge import BridgeState
from jarvis.ui.web import provider_routes


class FakeSupervisor:
    def __init__(self, status: str) -> None:
        self.state = BridgeState(status, f"bridge is {status}")  # type: ignore[arg-type]
        self.calls: list[str] = []

    def status(self) -> BridgeState:
        self.calls.append("status")
        return self.state

    def start(self) -> BridgeState:
        self.calls.append("start")
        self.state = BridgeState("login_required", "sign in")
        return self.state

    def ensure_running(self) -> BridgeState:
        self.calls.append("ensure_running")
        return self.state

    def login(self) -> BridgeState:
        self.calls.append("login")
        return self.state

    def restart(self) -> BridgeState:
        self.calls.append("restart")
        return BridgeState("starting", "restarting")


def _use(monkeypatch: pytest.MonkeyPatch, status: str) -> FakeSupervisor:
    fake = FakeSupervisor(status)
    monkeypatch.setattr(chatgpt_web_bridge, "supervisor", fake)
    return fake


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("ready", "ok"),
        ("login_required", "needs_setup"),
        ("offline", "error"),
        ("session_invalid", "error"),
    ],
)
def test_card_health_follows_the_bridge(
    monkeypatch: pytest.MonkeyPatch, status: str, expected: str
) -> None:
    _use(monkeypatch, status)
    health = asyncio.run(provider_routes._chatgpt_web_health())
    assert str(getattr(health.status, "value", health.status)).lower() == expected
    assert health.reason == status


def test_status_starts_an_offline_bridge(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _use(monkeypatch, "offline")
    payload = asyncio.run(provider_routes.chatgpt_web_status())
    assert fake.calls == ["status", "start"]
    assert payload["status"] == "login_required"


def test_status_does_not_restart_a_running_bridge(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _use(monkeypatch, "ready")
    assert asyncio.run(provider_routes.chatgpt_web_status())["status"] == "ready"
    assert fake.calls == ["status"]


def test_login_refuses_an_uninstalled_bridge(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _use(monkeypatch, "not_installed")
    with pytest.raises(HTTPException) as info:
        asyncio.run(provider_routes.chatgpt_web_login())
    assert info.value.status_code == 409
    assert "login" not in fake.calls


def test_login_opens_the_bridge_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _use(monkeypatch, "login_required")
    asyncio.run(provider_routes.chatgpt_web_login())
    assert fake.calls == ["ensure_running", "login"]
