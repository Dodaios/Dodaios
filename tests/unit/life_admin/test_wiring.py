"""Where life admin plugs in: the routes, the routine context and the trigger intake."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.agent_chat import proactive_checks as pc
from dodaios.life_admin import service as life
from dodaios.life_admin.settings import LifeAdminSettings
from dodaios.ui.web.agent_chat_routes import router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_routes_pass_through_and_map_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    async def state() -> dict[str, Any]:
        return {"available": True, "settings": {"enabled": False}, "items": []}

    async def apply(settings: LifeAdminSettings) -> dict[str, Any]:
        seen["settings"] = settings
        return {"available": True, "settings": settings.to_dict(), "items": []}

    async def dismiss(item_id: str) -> bool:
        return item_id == "known"

    async def prepare(item_id: str) -> dict[str, Any] | None:
        return {"id": item_id} if item_id == "known" else None

    monkeypatch.setattr(life, "state", state)
    monkeypatch.setattr(life, "apply_settings", apply)
    monkeypatch.setattr(life, "dismiss_item", dismiss)
    monkeypatch.setattr(life, "prepare_item", prepare)
    with _client() as client:
        assert client.get("/api/agent-chat/lead/life-admin").json()["settings"]["enabled"] is False
        body = {
            "enabled": True, "digest_day": "fri", "digest_time": "18:30",
            "timezone": "Europe/Berlin",
            "categories": {"bill": False, "nonsense": True},
        }
        response = client.put("/api/agent-chat/lead/life-admin", json=body)
        assert response.status_code == 200
        saved = seen["settings"]
        assert saved.enabled and saved.digest_day == "fri" and saved.digest_time == "18:30"
        assert saved.categories["bill"] is False and "nonsense" not in saved.categories
        assert client.post("/api/agent-chat/lead/life-admin/items/known/dismiss").status_code == 200
        assert client.post("/api/agent-chat/lead/life-admin/items/x/dismiss").status_code == 404
        assert client.post("/api/agent-chat/lead/life-admin/items/known/prepare").status_code == 200
        assert client.post("/api/agent-chat/lead/life-admin/items/x/prepare").status_code == 404


def test_bad_settings_fall_back_to_off() -> None:
    cfg = LifeAdminSettings.from_dict(
        {"enabled": "yes", "digest_day": "someday", "digest_time": "9am"}
    )
    assert cfg.enabled is False and cfg.digest_day == "off" and cfg.digest_time == "09:00"
    assert LifeAdminSettings.from_dict(None).enabled is False


async def test_routine_context_carries_the_life_admin_text(monkeypatch: pytest.MonkeyPatch) -> None:
    async def digest() -> str:
        return "DIGEST"

    async def urgent() -> str:
        return "URGENT"

    async def brief() -> str:
        return "BRIEF"

    monkeypatch.setattr(life, "digest_context", digest)
    monkeypatch.setattr(life, "urgent_context", urgent)
    monkeypatch.setattr(life, "brief_context", brief)
    assert await pc._life_admin_parts((life.DIGEST_TAG,)) == ["DIGEST"]
    assert await pc._life_admin_parts((pc.CHECK_TAG,)) == ["URGENT"]
    assert await pc._life_admin_parts(("lead-brief:morning",)) == ["BRIEF"]
    assert await pc._life_admin_parts(("other",)) == []


async def test_a_failing_reader_never_breaks_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    async def broken() -> str:
        raise RuntimeError("ledger locked")

    monkeypatch.setattr(life, "urgent_context", broken)
    assert await pc._life_admin_parts((pc.CHECK_TAG,)) == []


async def test_the_digest_precheck_follows_the_ledger(monkeypatch: pytest.MonkeyPatch) -> None:
    async def reason() -> str:
        return "quiet hours"

    monkeypatch.setattr(life, "digest_skip_reason", reason)
    assert await pc.precheck_skip(None, None, (life.DIGEST_TAG,)) == "quiet hours"
    assert await pc.precheck_skip(None, None, ("unrelated",)) == ""


def test_urgent_life_admin_keeps_the_needs_you_check_running() -> None:
    quiet = dict(due_loops=0, due_deadlines=0, waiting_agents=0, agent_turns_since=0,
                 external_sources=0)
    assert pc.skip_reason(pc.ProactiveSettings(level="important"), **quiet)
    settings = pc.ProactiveSettings(level="important")
    assert pc.skip_reason(settings, **quiet, life_admin_urgent=1) == ""


async def test_the_trigger_intake_feeds_life_admin_and_survives_its_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dodaios.lead_triggers import wiring

    seen: list[tuple[str, str]] = []

    async def ingest(event: Any) -> int:
        seen.append((event.source, event.ids[0]))
        raise RuntimeError("boom")

    class Service:
        async def submit(self, event: Any) -> str:
            return "dropped_test"

    monkeypatch.setattr(life, "ingest_trigger_event", ingest)
    monkeypatch.setattr(wiring, "get_service", lambda: Service())
    assert await wiring.submit_payload("mail", {"id": "m9", "subject": "Invoice"}) == "dropped_test"
    assert await wiring.submit_payload("github", {"id": "g1"}) == "dropped_test"
    assert seen == [("mail", "m9")]  # only mail and calendar reach life admin


def test_producer_events_become_the_records_the_extractors_read() -> None:
    from dodaios.lead_triggers.event import TriggerEvent

    mail = TriggerEvent(
        source="mail", sender="Power <b@p.example>", ids=("m1",),
        summary="Invoice 77: please pay by 2026-11-12",
    )
    assert life.payload_of_event(mail)["subject"] == "Invoice 77"
    assert life.payload_of_event(mail)["snippet"] == "please pay by 2026-11-12"
    cal = TriggerEvent(
        source="calendar", ids=("e1",), summary="Updated: Tax return deadline (2026-11-30)"
    )
    assert life.payload_of_event(cal) == {
        "id": "e1", "title": "Tax return deadline", "start": "2026-11-30",
    }
