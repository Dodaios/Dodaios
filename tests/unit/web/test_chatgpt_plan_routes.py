"""Sign in with ChatGPT routes and card health, against a fake plan auth."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from fastapi import HTTPException

from jarvis.plugins.brain import chatgpt_plan_auth
from jarvis.plugins.brain.chatgpt_plan_auth import ChatGPTPlanError
from jarvis.ui.web import provider_routes


class FakePlan:
    def __init__(self, **status: Any) -> None:
        self.state: dict[str, Any] = {
            "signed_in": False,
            "account": "",
            "plan_enabled": False,
            "model": "",
            "registered": False,
            "notice_seen": False,
            "login": "idle",
            "error": "",
            "usage_url": chatgpt_plan_auth.USAGE_URL,
            **status,
        }
        self.catalog: list[dict[str, str]] | ChatGPTPlanError = [
            {"slug": "gpt-a", "display_name": "GPT A"}
        ]
        self.calls: list[str] = []

    def status(self) -> dict[str, Any]:
        return dict(self.state)

    def start_login(self, *, reauth: bool = False) -> str:
        self.calls.append(f"start:{reauth}")
        self.state["login"] = "pending"
        return "https://auth.openai.com/api/accounts/authorize?client_id=x"

    def logout(self) -> bool:
        self.calls.append("logout")
        self.state.update(signed_in=False, plan_enabled=False, account="")
        return True

    def models(self) -> list[dict[str, str]]:
        if isinstance(self.catalog, ChatGPTPlanError):
            raise self.catalog
        return self.catalog

    def update_meta(self, **fields: Any) -> None:
        self.state.update(fields)


def _use(monkeypatch: pytest.MonkeyPatch, **status: Any) -> FakePlan:
    fake = FakePlan(**status)
    monkeypatch.setattr(chatgpt_plan_auth, "_auth", fake)
    return fake


@pytest.mark.parametrize(
    ("status", "expected", "reason"),
    [
        ({}, "needs_setup", "not_signed_in"),
        ({"signed_in": True}, "needs_setup", "plan_scope_missing"),
        ({"signed_in": True, "plan_enabled": True}, "ok", "connected"),
        ({"error": "nonce_mismatch"}, "error", "nonce_mismatch"),
    ],
)
def test_card_health_follows_local_state(monkeypatch, status, expected, reason) -> None:
    _use(monkeypatch, **status)
    health = asyncio.run(provider_routes._chatgpt_plan_health())
    assert str(getattr(health.status, "value", health.status)).lower() == expected
    assert health.reason == reason


def test_login_and_reauth_start_the_browser_flow(monkeypatch) -> None:
    fake = _use(monkeypatch)
    assert asyncio.run(provider_routes.chatgpt_plan_login())["login"] == "pending"
    asyncio.run(provider_routes.chatgpt_plan_reauth())
    assert fake.calls == ["start:False", "start:True"]


def test_logout_reports_revocation(monkeypatch) -> None:
    _use(monkeypatch, signed_in=True, plan_enabled=True, account="a@example.com")
    payload = asyncio.run(provider_routes.chatgpt_plan_logout())
    assert payload["revoked"] is True and not payload["signed_in"]


def test_model_must_be_listed(monkeypatch) -> None:
    fake = _use(monkeypatch, signed_in=True, plan_enabled=True)
    body = provider_routes.PlanModelBody(slug="gpt-a")
    assert asyncio.run(provider_routes.chatgpt_plan_model(body))["model"] == "gpt-a"
    with pytest.raises(HTTPException) as exc:
        asyncio.run(provider_routes.chatgpt_plan_model(provider_routes.PlanModelBody(slug="nope")))
    assert exc.value.status_code == 422
    assert fake.state["model"] == "gpt-a"


@pytest.mark.parametrize(
    ("code", "status_code"), [("reauthorization_required", 409), ("models_failed", 502)]
)
def test_models_errors_map_to_http(monkeypatch, code, status_code) -> None:
    fake = _use(monkeypatch, signed_in=True, plan_enabled=True)
    fake.catalog = ChatGPTPlanError(code, "x")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(provider_routes.chatgpt_plan_models())
    assert exc.value.status_code == status_code


def test_notice_is_remembered(monkeypatch) -> None:
    _use(monkeypatch, signed_in=True, plan_enabled=True)
    assert asyncio.run(provider_routes.chatgpt_plan_notice())["notice_seen"] is True


def test_status_payload_has_no_token_fields(monkeypatch) -> None:
    _use(monkeypatch, signed_in=True, plan_enabled=True)
    text = json.dumps(asyncio.run(provider_routes.chatgpt_plan_status())).lower()
    assert "token" not in text
