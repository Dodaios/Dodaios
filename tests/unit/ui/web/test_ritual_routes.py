"""``/api/agent-chat/lead/rituals``: the person's view onto their rituals and their clicks."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.rituals import prepare, service
from dodaios.rituals.store import RitualStore, get_store, set_store
from dodaios.ui.web.ritual_routes import router
from tests.unit.rituals.conftest import MORNING, Society

BASE = "/api/agent-chat/lead/rituals"


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch):
    store = RitualStore(":memory:")
    set_store(store)
    society = Society()
    monkeypatch.setattr(service, "_runtime", lambda: society)
    monkeypatch.setattr(prepare, "_runtime", lambda: society)
    monkeypatch.setattr(service, "_POLL_S", 0.01)
    try:
        yield society
    finally:
        set_store(None)
        store.close()
        prepare._runs.clear()
        prepare._tried_at.clear()


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_the_list_is_empty_at_first_and_names_the_limits(world) -> None:
    with _client() as client:
        view = client.get(BASE).json()
    assert view["available"] is True and view["rituals"] == []
    assert view["limits"]["max_steps"] == 12 and view["limits"]["when"] == ["now", "ahead"]


def test_the_person_writes_one_by_hand_and_reads_it_back(world) -> None:
    with _client() as client:
        made = client.post(BASE, json={**MORNING, "window_from": "05:00", "window_to": "11:00"})
        assert made.status_code == 201
        ritual = made.json()["ritual"]
        assert ritual["origin"] == "owner" and ritual["window_to"] == "11:00"
        assert made.json()["today"] is None
        listed = client.get(BASE).json()["rituals"]
        one = client.get(f"{BASE}/{ritual['id']}")
        missing = client.get(f"{BASE}/rit_missing")
    assert [row["id"] for row in listed] == [ritual["id"]]
    assert one.status_code == 200 and one.json()["ritual"] == ritual
    assert missing.status_code == 404


def test_what_the_service_refuses_comes_back_with_its_reason(world) -> None:
    with _client() as client:
        assert client.post(BASE, json=MORNING).status_code == 201
        clash = client.post(BASE, json={**MORNING, "name": "Another"})
        no_phrase = client.post(BASE, json={**MORNING, "name": "Empty", "phrases": []})
        unknown_field = client.post(BASE, json={**MORNING, "name": "Extra", "colour": "blue"})
    assert clash.status_code == 409 and "Good morning" in clash.json()["detail"]
    assert no_phrase.status_code == 422 and "phrase" in no_phrase.json()["detail"]
    assert unknown_field.status_code == 422


def test_a_change_sends_only_what_changes(world) -> None:
    with _client() as client:
        ritual = client.post(BASE, json=MORNING).json()["ritual"]
        off = client.patch(f"{BASE}/{ritual['id']}", json={"enabled": False})
        nothing = client.patch(f"{BASE}/{ritual['id']}", json={})
        bad = client.patch(f"{BASE}/{ritual['id']}", json={"window_from": "25:00"})
        missing = client.patch(f"{BASE}/rit_missing", json={"enabled": True})
    assert off.status_code == 200 and off.json()["ritual"]["enabled"] is False
    assert off.json()["ritual"]["steps"] == ritual["steps"]
    assert nothing.status_code == 422 and bad.status_code == 422 and missing.status_code == 404


def test_would_this_sentence_start_one(world) -> None:
    with _client() as client:
        ritual = client.post(BASE, json=MORNING).json()["ritual"]
        hit = client.get(f"{BASE}/match", params={"text": "Hey Nova, good morning"}).json()
        miss = client.get(f"{BASE}/match", params={"text": "Good morning, any news?"}).json()
        client.patch(f"{BASE}/{ritual['id']}", json={"enabled": False})
        held = client.get(f"{BASE}/match", params={"text": "Good morning"}).json()
        empty = client.get(f"{BASE}/match", params={"text": ""})
    assert hit["matched"] and hit["fires"] and hit["ritual"]["id"] == ritual["id"]
    assert hit["phrase"] == "Good morning" and hit["blocked"] == ""
    assert miss == {"matched": False, "fires": False, "blocked": "", "ritual": None, "phrase": ""}
    assert held["matched"] and not held["fires"] and held["blocked"] == "off"
    assert empty.status_code == 422
    # Asking started nothing.
    assert world.notices == [] and get_store().days("2026-03-02") == []


def test_run_now_starts_it_whatever_the_clock_says(world) -> None:
    body = {**MORNING, "window_from": "03:00", "window_to": "03:01", "enabled": False}
    with _client() as client:
        ritual = client.post(BASE, json=body).json()["ritual"]
        first = client.post(f"{BASE}/{ritual['id']}/run")
        second = client.post(f"{BASE}/{ritual['id']}/run")
        shown = client.get(f"{BASE}/{ritual['id']}").json()
        missing = client.post(f"{BASE}/rit_missing/run")
    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["today"]["fired_via"] == "button"
    assert [card["ritual_id"] for card in world.notices] == [ritual["id"]] * 2
    # One ritual's page carries what was gathered for today as well.
    assert shown["today"]["fired_via"] == "button" and shown["today"]["written"] == ""
    assert missing.status_code == 404


def test_a_start_without_the_assistant_is_refused(world, monkeypatch: pytest.MonkeyPatch) -> None:
    with _client() as client:
        ritual = client.post(BASE, json=MORNING).json()["ritual"]
        monkeypatch.setattr(service, "_runtime", lambda: None)
        refused = client.post(f"{BASE}/{ritual['id']}/run")
    assert refused.status_code == 503


def test_the_assistant_asks_before_it_writes_or_starts_one_through_the_raw_routes() -> None:
    """A ritual's steps later run with the person's standing: no silent planting."""
    from dodaios.app_actions.catalog import build_catalog, default_tier

    app = FastAPI()
    app.include_router(router)
    tiers = {
        (entry.method, entry.path): default_tier(entry)
        for entry in build_catalog(app.openapi()).values()
    }
    assert tiers == {
        ("GET", BASE): "safe",
        ("GET", f"{BASE}/match"): "safe",
        ("GET", f"{BASE}/{{ritual_id}}"): "safe",
        ("POST", BASE): "ask",
        ("PATCH", f"{BASE}/{{ritual_id}}"): "ask",
        ("DELETE", f"{BASE}/{{ritual_id}}"): "ask",
        ("POST", f"{BASE}/{{ritual_id}}/run"): "ask",
        # Gathering only looks: it is logged, not asked about.
        ("POST", f"{BASE}/{{ritual_id}}/prepare"): "monitor",
    }


def test_gather_now_starts_the_run_and_says_where_the_day_stands(
    world, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict] = []

    async def start(ritual_id: str, **options) -> bool:
        calls.append({"ritual_id": ritual_id, **options})
        today = service.day_of(service._moment(None))
        get_store().patch_day(ritual_id, today, prep_state="running")
        return True

    monkeypatch.setattr(prepare, "start", start)
    with _client() as client:
        ritual = client.post(BASE, json=MORNING).json()["ritual"]
        body = client.post(f"{BASE}/{ritual['id']}/prepare").json()
    assert body["started"] is True and body["ritual"]["id"] == ritual["id"]
    assert body["today"]["prep_state"] == "running"
    # The person's own click: on their seat, and anew although a result may be there.
    assert calls == [{"ritual_id": ritual["id"], "by_user": True, "again": True}]


def test_gather_now_says_why_it_cannot(world) -> None:
    only_now = {**MORNING, "steps": [{"when": "now", "text": "Play my favourite music."}]}
    with _client() as client:
        nothing_ahead = client.post(BASE, json=only_now).json()["ritual"]
        refused = client.post(f"{BASE}/{nothing_ahead['id']}/prepare")
        missing = client.post(f"{BASE}/rit_missing/prepare")
        client.delete(f"{BASE}/{nothing_ahead['id']}")
        ritual = client.post(BASE, json=MORNING).json()["ritual"]
        # No scheduler behind this society: the run cannot be set up.
        unavailable = client.post(f"{BASE}/{ritual['id']}/prepare")
    assert refused.status_code == 409 and "nothing to gather" in refused.json()["detail"]
    assert missing.status_code == 404
    assert unavailable.status_code == 503


def test_removing_one(world) -> None:
    with _client() as client:
        ritual = client.post(BASE, json=MORNING).json()["ritual"]
        gone = client.delete(f"{BASE}/{ritual['id']}")
        again = client.delete(f"{BASE}/{ritual['id']}")
        listed = client.get(BASE).json()["rituals"]
    assert gone.status_code == 200 and gone.json() == {"ok": True, "id": ritual["id"]}
    assert again.status_code == 404 and listed == []
