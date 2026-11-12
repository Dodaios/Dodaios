"""``/api/agent-chat/lead/standing*``: the owner's view onto standing tasks and their clicks."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.standing_tasks.models import StandingError, StandingRun
from dodaios.ui.web.agent_chat_routes import router
from tests.fakes.fake_standing_tasks import NOW_MS, FakeStandingService, install

BASE = "/api/agent-chat/lead/standing"


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> FakeStandingService:
    return install(monkeypatch)


def _client(lead_session: str = "") -> TestClient:
    app = FastAPI()
    app.include_router(router)
    if lead_session:
        # The lead conversation, as the chat service remembers it.
        session = SimpleNamespace(session_id=lead_session, surface="jarvis")
        store = SimpleNamespace(
            lead_session_id=lambda: lead_session,
            get_session=lambda session_id: session if session_id == lead_session else None,
        )
        app.state.agent_chat = SimpleNamespace(store=store)
    return TestClient(app)


def test_the_overview_lists_open_tasks_and_ended_ones_on_request(service) -> None:
    service.add("st_1")
    service.add("st_old", state="ended")
    with _client() as client:
        view = client.get(BASE).json()
        everything = client.get(BASE, params={"ended": 1}).json()
    assert view["available"] is True and view["autonomy"] == ["watch", "prepare", "act"]
    assert view["limits"]["max_open"] == 12
    assert [task["id"] for task in view["tasks"]] == ["st_1"]
    assert {task["id"] for task in everything["tasks"]} == {"st_1", "st_old"}
    assert everything["limits"] == view["limits"]
    assert service.called("list_tasks") == [{"include_ended": True}]


def test_one_task_comes_with_its_runs(service) -> None:
    service.add("st_1")
    service.runs["st_1"] = [
        StandingRun("sr_1", "st_1", NOW_MS, "prepared", "A draft is ready.", ("Drafted",), 120, "s")
    ]
    with _client() as client:
        found = client.get(f"{BASE}/st_1", params={"runs": 5})
        missing = client.get(f"{BASE}/st_nope")
    assert found.status_code == 200
    assert found.json()["task"]["id"] == "st_1"
    assert found.json()["runs"][0]["actions"] == ["Drafted"]
    assert service.called("runs_of") == [{"standing_id": "st_1", "limit": 5}]
    assert missing.status_code == 404


def test_the_owner_creates_one_by_hand(service) -> None:
    body = {
        "title": "Inbox", "goal": "Tell me when a customer writes.", "autonomy": "watch",
        "interval_min": 60, "timezone": "Europe/Berlin",
    }
    with _client() as client:
        created = client.post(BASE, json=body)
        defaults = client.post(BASE, json={"title": "Launch", "goal": "Keep the launch on track."})
        incomplete = client.post(BASE, json={"title": "No goal"})
    assert created.status_code == 201 and created.json()["task"]["state"] == "active"
    first, second = service.called("take_on")
    # Written in the panel, not said in a chat: no origin session.
    assert first == {
        "title": "Inbox", "goal": "Tell me when a customer writes.", "how": "",
        "autonomy": "watch", "limits": "", "interval_min": 60, "origin": "owner",
        "origin_session": "", "timezone": "Europe/Berlin",
    }
    # No pace given: the service's own default applies, not one copied into the route.
    assert second["interval_min"] == 180 and second["autonomy"] == "prepare"
    assert defaults.status_code == 201
    assert incomplete.status_code == 422


def test_a_patch_changes_only_what_was_sent(service) -> None:
    service.add("st_1", autonomy="act", limits="Pause ads above 4 EUR per lead.")
    with _client() as client:
        patched = client.patch(f"{BASE}/st_1", json={"interval_min": 30, "limits": "", "how": None})
        empty = client.patch(f"{BASE}/st_1", json={})
    assert patched.status_code == 200 and patched.json()["task"]["interval_min"] == 30
    # An empty text is the owner clearing the field; a null is a field left alone.
    assert service.called("update") == [{"standing_id": "st_1", "limits": "", "interval_min": 30}]
    assert empty.status_code == 422


def test_the_owners_clicks_reach_the_service(service) -> None:
    service.add("st_p", state="proposed", task_id="")
    service.add("st_1")
    with _client("lead-chat") as client:
        accepted = client.post(f"{BASE}/st_p/accept")
        steps = [client.post(f"{BASE}/st_1/{action}") for action in ("pause", "resume", "run")]
        ended = client.post(f"{BASE}/st_1/end")
        declined = client.post(f"{BASE}/st_p/decline")
        unknown = client.post(f"{BASE}/st_1/delete")
    assert accepted.status_code == 200 and accepted.json()["task"]["state"] == "active"
    # The card sits in the lead conversation: accepting it there is a yes said in that chat.
    assert service.called("accept") == [{"standing_id": "st_p", "origin_session": "lead-chat"}]
    assert [step.status_code for step in steps] == [200, 200, 200]
    # "Run now" is the owner's own start, the way it is on a routine.
    assert service.run_started_by_user is True
    assert ended.json()["task"]["state"] == "ended"
    assert declined.status_code == 200
    assert unknown.status_code == 404
    assert [name for name, _ in service.calls] == [
        "accept", "pause", "resume", "run_now", "end", "decline",
    ]


def test_an_accept_before_there_is_a_lead_conversation_still_counts(service) -> None:
    service.add("st_p", state="proposed", task_id="")
    with _client() as client:
        assert client.post(f"{BASE}/st_p/accept").status_code == 200
    assert service.called("accept") == [{"standing_id": "st_p", "origin_session": ""}]


@pytest.mark.parametrize(
    ("code", "status"),
    [("not_found", 404), ("invalid", 422), ("state", 409), ("limit", 409), ("unavailable", 503)],
)
def test_refusals_keep_their_sentence_and_map_to_a_status(service, code: str, status: int) -> None:
    service.add("st_1")
    calls = (
        lambda client: client.get(BASE),
        lambda client: client.get(f"{BASE}/st_1"),
        lambda client: client.post(BASE, json={"title": "t", "goal": "g"}),
        lambda client: client.patch(f"{BASE}/st_1", json={"title": "t"}),
        lambda client: client.post(f"{BASE}/st_1/pause"),
    )
    with _client() as client:
        for call in calls:
            service.fail = StandingError(code, "A sentence a person can read.")
            response = call(client)
            assert response.status_code == status
            assert response.json()["detail"] == "A sentence a person can read."
