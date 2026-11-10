"""``/api/agent-chat/lead/proactive*``: the panel's view onto the checks and check-ins."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.ui.web.agent_chat_routes import router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_get_put_and_checkin_pass_through_their_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    async def state() -> dict[str, Any]:
        return {"available": True, "settings": {"level": "off"}, "checks": {"enabled": False}}

    async def apply(settings: Any) -> dict[str, Any]:
        seen["settings"] = settings
        return {"available": True, "settings": settings.to_dict(), "checks": {"enabled": True}}

    async def checkin(request: Any) -> dict[str, Any]:
        seen["checkin"] = request
        return {"task_id": "t1", "minutes": request.minutes, "doing": request.doing}

    monkeypatch.setattr("dodaios.agent_chat.proactive_checks.checks_state", state)
    monkeypatch.setattr("dodaios.agent_chat.proactive_checks.apply_settings", apply)
    monkeypatch.setattr("dodaios.agent_chat.checkins.schedule_checkin", checkin)
    with _client() as client:
        assert client.get("/api/agent-chat/lead/proactive").json()["settings"]["level"] == "off"
        body = {
            "level": "important", "topics": ["mail", "weather"], "interval_hours": 6,
            "timezone": "Europe/Berlin",
        }
        response = client.put("/api/agent-chat/lead/proactive", json=body)
        assert response.status_code == 200
        assert seen["settings"].level == "important"
        assert seen["settings"].topics == ("mail",)  # unknown topics are dropped
        assert seen["settings"].interval_hours == 6
        assert seen["settings"].timezone == "Europe/Berlin"
        response = client.post(
            "/api/agent-chat/lead/proactive/checkin", json={"minutes": 25, "doing": "the report"}
        )
        assert response.status_code == 201 and response.json()["task_id"] == "t1"
        assert (seen["checkin"].minutes, seen["checkin"].doing) == (25, "the report")
        too_short = client.post("/api/agent-chat/lead/proactive/checkin", json={"minutes": 0})
        assert too_short.status_code == 422


def test_errors_map_to_400_and_503(monkeypatch: pytest.MonkeyPatch) -> None:
    async def bad_zone(settings: Any) -> dict[str, Any]:
        raise ValueError("timezone must be an IANA zone")

    async def no_society(request: Any) -> dict[str, Any]:
        raise RuntimeError("The agent society is not running")

    monkeypatch.setattr("dodaios.agent_chat.proactive_checks.apply_settings", bad_zone)
    monkeypatch.setattr("dodaios.agent_chat.checkins.schedule_checkin", no_society)
    with _client() as client:
        put = client.put("/api/agent-chat/lead/proactive", json={"level": "important"})
        assert put.status_code == 400
        post = client.post("/api/agent-chat/lead/proactive/checkin", json={"minutes": 5})
        assert post.status_code == 503
