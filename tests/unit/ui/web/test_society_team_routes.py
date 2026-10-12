"""/api/society/chat-groups/{id}/team…: a team's lead, mission, goals and tasks."""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from jarvis.agent_chat.store import AgentChatStore
from jarvis.society.runtime import SocietyRuntime
from jarvis.ui.web.society_routes import router
from tests.fakes.team_chat import TeamChatFake


@pytest.fixture
def client(tmp_path: Path):
    svc = TeamChatFake(AgentChatStore(tmp_path / "chat.db"))
    cfg = SimpleNamespace(memory=SimpleNamespace(data_dir=str(tmp_path)))
    runtime = SocietyRuntime(
        tmp_path, seed_starter_team=False, chat_service=lambda: svc, cfg=lambda: cfg
    )
    runtime.team_leads._review_delay = 0.0  # noqa: SLF001 — no debounce wait in tests
    app = FastAPI()
    app.include_router(router)
    app.state.society = None
    app.state.society_factory = lambda: runtime
    with TestClient(app) as c:
        try:
            yield c, runtime, svc
        finally:
            assert c.portal is not None
            c.portal.call(svc.close)
            c.portal.call(runtime.close)
            svc.store.close()


def _team(c: TestClient) -> str:
    for name in ("Scout", "Writer"):
        created = c.post(
            "/api/society/agents", json={"name": name, "provider": "ollama", "model": "fake"}
        )
        assert created.status_code == 200, created.text
    group = c.post(
        "/api/society/chat-groups", json={"name": "Launch", "members": ["scout", "writer"]}
    ).json()["group"]
    assert group["lead_agent_id"] is None and group["mission"] == ""
    return str(group["group_id"])


def _wait(c: TestClient, url: str, done: Any, *, seconds: float = 5.0) -> dict[str, Any]:
    deadline = time.monotonic() + seconds
    while True:
        body = c.get(url).json()
        if done(body):
            return body
        assert time.monotonic() < deadline, body
        time.sleep(0.02)


def test_a_team_without_a_lead_reads_empty_and_refuses_goals(client):
    c, _, _ = client
    group_id = _team(c)
    url = f"/api/society/chat-groups/{group_id}"
    team = c.get(f"{url}/team").json()
    assert team["lead_agent_id"] is None and team["goals"] == []
    assert team["checkin_minutes"] == 0 and not team["working"]
    refused = c.post(f"{url}/goals", json={"text": "Launch it"})
    assert refused.status_code == 409 and "no lead" in refused.json()["detail"]
    assert c.get("/api/society/chat-groups/nope/team").status_code == 404
    missing = c.put("/api/society/chat-groups/nope/lead", json={"agent_id": "scout"})
    assert missing.status_code == 404


def test_naming_and_creating_a_lead(client):
    c, _, _ = client
    group_id = _team(c)
    url = f"/api/society/chat-groups/{group_id}"

    named = c.put(f"{url}/lead", json={"agent_id": "scout"})
    assert named.status_code == 200, named.text
    assert named.json()["lead_agent_id"] == "scout" and named.json()["lead_available"]
    agents = {a["agent_id"]: a for a in c.get("/api/society/agents").json()["agents"]}
    assert agents["scout"]["tier"] == "orchestrator"
    assert c.get("/api/society/chat-groups").json()["groups"][0]["lead_agent_id"] == "scout"
    assert c.put(f"{url}/lead", json={"agent_id": "jarvis"}).status_code == 422
    assert c.put(f"{url}/lead", json={"agent_id": "ghost"}).status_code == 404

    cleared = c.put(f"{url}/lead", json={"agent_id": None})
    assert cleared.status_code == 200 and cleared.json()["lead_agent_id"] is None
    agents = {a["agent_id"]: a for a in c.get("/api/society/agents").json()["agents"]}
    assert agents["scout"]["tier"] == "specialist"

    created = c.post(f"{url}/lead", json={})
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["agent"]["name"] == "Launch Lead" and body["agent"]["tier"] == "orchestrator"
    assert body["lead_agent_id"] == body["agent"]["agent_id"]
    members = c.get("/api/society/chat-groups").json()["groups"][0]["members"]
    assert body["agent"]["agent_id"] in members


def test_mission_is_saved_and_shown(client):
    c, _, _ = client
    group_id = _team(c)
    url = f"/api/society/chat-groups/{group_id}"
    saved = c.put(f"{url}/mission", json={"mission": "  Ship the launch.  "})
    assert saved.status_code == 200 and saved.json()["mission"] == "Ship the launch."
    assert c.get("/api/society/chat-groups").json()["groups"][0]["mission"] == "Ship the launch."
    assert c.put(f"{url}/mission", json={"mission": "x" * 4001}).status_code == 422


def test_a_goal_runs_from_the_board_to_its_report(client):
    c, rt, svc = client
    group_id = _team(c)
    url = f"/api/society/chat-groups/{group_id}"
    assert c.put(f"{url}/lead", json={"agent_id": "scout"}).status_code == 200
    svc.replies["society:writer"] = "Draft is in draft.md."

    async def lead(text: str, kwargs: dict[str, Any]) -> str:
        if text.startswith("[team goal for"):
            await rt.team_leads.assign("scout", member="Writer", title="Draft", brief="Write it.")
            return "Writer is on it."
        await rt.team_leads.report("scout", status="done", summary="The page is written.")
        return "Closed."

    svc.scripts["society:scout"] = lead
    started = c.post(f"{url}/goals", json={"text": "Write the launch page", "lang": "en"})
    assert started.status_code == 200, started.text
    goal_id = started.json()["goal_id"]

    team = _wait(c, f"{url}/team", lambda body: body["goals"][0]["state"] == "done")
    goal = team["goals"][0]
    assert goal["goal_id"] == goal_id and goal["report"] == "The page is written."
    assert goal["source"] == "board" and goal["title"] == "Write the launch page"
    assert [(t["agent_id"], t["state"]) for t in goal["tasks"]] == [("writer", "done")]
    assert goal["tasks"][0]["result"] == "Draft is in draft.md."

    # A finished goal takes no message, and another team's goal id is unknown here.
    assert c.post(f"{url}/goals/{goal_id}/message", json={"text": "More"}).status_code == 409
    assert c.post(f"{url}/goals/unknown/cancel").status_code == 404
    assert c.post(f"{url}/goals/{goal_id}/cancel").json()["goals"][0]["state"] == "done"


def test_a_question_is_answered_and_a_goal_is_stopped_over_http(client):
    c, rt, svc = client
    group_id = _team(c)
    url = f"/api/society/chat-groups/{group_id}"
    c.put(f"{url}/lead", json={"agent_id": "scout"})
    turns: list[str] = []

    async def lead(text: str, kwargs: dict[str, Any]) -> str:
        turns.append(text)
        if len(turns) == 1:
            await rt.team_leads.report("scout", status="needs_input", summary="Which market?")
            return "One question."
        await rt.team_leads.report("scout", status="done", summary="Planned for Germany.")
        return "Closed."

    svc.scripts["society:scout"] = lead
    goal_id = c.post(f"{url}/goals", json={"text": "Plan the launch"}).json()["goal_id"]
    team = _wait(c, f"{url}/team", lambda body: body["goals"][0]["state"] == "needs_input")
    assert team["goals"][0]["report"] == "Which market?"
    assert c.post(f"{url}/goals/{goal_id}/message", json={"text": "Germany"}).status_code == 200
    _wait(c, f"{url}/team", lambda body: body["goals"][0]["state"] == "done")
    assert "Germany" in turns[1]

    svc.scripts.pop("society:scout")
    import asyncio

    gate = asyncio.Event()
    svc.gates["society:scout"] = gate
    second = c.post(f"{url}/goals", json={"text": "Second goal"}).json()["goal_id"]
    _wait(c, f"{url}/team", lambda body: body["working"])
    # A lead cannot be swapped out under a goal it is running.
    busy = c.put(f"{url}/lead", json={"agent_id": "writer"})
    assert busy.status_code == 409 and "current goal" in busy.json()["detail"]
    stopped = c.post(f"{url}/goals/{second}/cancel")
    assert stopped.status_code == 200
    states = {g["goal_id"]: g["state"] for g in stopped.json()["goals"]}
    assert states[second] == "cancelled"
    assert c.post(f"{url}/goals/{second}/resume").status_code == 409


def test_editing_and_deleting_the_group_keeps_leadership_consistent(client):
    c, _, _ = client
    group_id = _team(c)
    c.post("/api/society/agents", json={"name": "Planner", "provider": "ollama", "model": "fake"})
    url = f"/api/society/chat-groups/{group_id}"
    c.put(f"{url}/lead", json={"agent_id": "scout"})
    edited = c.patch(url, json={"name": "Launch", "members": ["writer", "planner"]})
    assert edited.status_code == 200 and edited.json()["group"]["lead_agent_id"] is None
    agents = {a["agent_id"]: a for a in c.get("/api/society/agents").json()["agents"]}
    assert agents["scout"]["tier"] == "specialist"

    c.put(f"{url}/lead", json={"agent_id": "writer"})
    assert c.delete(url).status_code == 200
    agents = {a["agent_id"]: a for a in c.get("/api/society/agents").json()["agents"]}
    assert agents["writer"]["tier"] == "specialist"
    assert c.get(f"{url}/team").status_code == 404
