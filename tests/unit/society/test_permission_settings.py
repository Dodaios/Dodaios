"""Settings -> Permissions and an agent's mode choice reaching its chat.

Bug (2026-11-09): an agent set to "Bypass permissions" kept showing approval
cards because a stricter stance once picked in its chat (the permission
override) survived the change and outranked it.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.agent_chat.store import AgentChatStore
from dodaios.society.chat_binding import ensure_session
from dodaios.society.runtime import SocietyRuntime
from tests.unit.society.test_chat_binding import FakeService


@pytest.fixture
async def world(tmp_path: Path):
    safety = SimpleNamespace(approval_mode="bypass", agent_approval_mode="bypass")
    cfg = SimpleNamespace(memory=SimpleNamespace(data_dir=str(tmp_path / "data")), safety=safety)
    svc = FakeService(AgentChatStore(tmp_path / "agent_chat.db"))
    runtime = SocietyRuntime(
        tmp_path, seed_starter_team=False, cfg=lambda: cfg, chat_service=lambda: svc
    )
    await runtime.ensure_started()
    try:
        yield runtime, svc, cfg
    finally:
        await runtime.close()


def _society_app(rt: SocietyRuntime) -> FastAPI:
    from dodaios.ui.web.society_routes import router

    app = FastAPI()
    app.include_router(router)
    app.state.society = rt
    return app


async def test_choosing_bypass_on_the_agent_replaces_an_older_chat_stance(world):
    rt, svc, cfg = world
    agent, _ = await rt.roster.create(name="Marketer", provider="openai", approval_mode="ask")
    session = ensure_session(svc, cfg, agent)
    svc.store.set_permission_override(session.session_id, "ask")
    assert ensure_session(svc, cfg, agent).permission_mode == "ask"

    with TestClient(_society_app(rt)) as client:
        response = client.patch(
            f"/api/society/agents/{agent.agent_id}", json={"approval_mode": "bypass"}
        )
    assert response.status_code == 200, response.text
    assert svc.store.permission_override(session.session_id) == ""
    assert svc.store.get_session(session.session_id).permission_mode == "bypass"


async def test_a_plan_switch_survives_an_agent_mode_change(world):
    rt, svc, cfg = world
    agent, _ = await rt.roster.create(name="Planner", provider="openai", approval_mode="ask")
    session = ensure_session(svc, cfg, agent)
    svc.store.set_permission_override(session.session_id, "plan")

    with TestClient(_society_app(rt)) as client:
        response = client.patch(
            f"/api/society/agents/{agent.agent_id}", json={"approval_mode": "bypass"}
        )
    assert response.status_code == 200, response.text
    assert svc.store.permission_override(session.session_id) == "plan"


@pytest.mark.parametrize("mode", ["bypass", "ask", "always_ask"])
async def test_a_new_agent_starts_with_the_configured_default(world, mode):
    rt, _svc, cfg = world
    cfg.safety.agent_approval_mode = mode
    agent, _ = await rt.roster.create(name=f"Helper {mode}", provider="openai")
    assert str(agent.approval_mode) == mode


async def test_an_unreadable_default_falls_back_to_bypass(world):
    rt, _svc, cfg = world
    cfg.safety.agent_approval_mode = "nonsense"
    agent, _ = await rt.roster.create(name="Fallback", provider="openai")
    assert str(agent.approval_mode) == "bypass"


async def test_apply_to_all_agents_sets_every_agent_but_the_lead(world):
    rt, svc, cfg = world
    first, _ = await rt.roster.create(name="One", provider="openai")
    second, _ = await rt.roster.create(name="Two", provider="openai", approval_mode="always_ask")
    session = ensure_session(svc, cfg, second)
    svc.store.set_permission_override(session.session_id, "always_ask")

    with TestClient(_society_app(rt)) as client:
        response = client.put("/api/society/approval-mode", json={"mode": "ask"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body["changed"]) == {first.agent_id, second.agent_id}
    assert str((await rt.roster.get(first.agent_id)).approval_mode) == "ask"
    assert str((await rt.roster.get(second.agent_id)).approval_mode) == "ask"
    assert svc.store.permission_override(session.session_id) == ""
    lead = await rt.roster.get(rt.lead_id)
    assert lead is None or lead.approval_mode is None


def test_settings_route_saves_and_applies_both_modes(tmp_path: Path, monkeypatch):
    from dodaios.core import config_writer
    from dodaios.ui.web.settings_routes import router

    toml = tmp_path / "jarvis.toml"
    toml.write_text("[safety]\napproval_mode = \"bypass\"\n", encoding="utf-8")
    real = config_writer.set_approval_modes
    monkeypatch.setattr(
        config_writer, "set_approval_modes", lambda **kw: real(**kw, path=toml)
    )
    safety = SimpleNamespace(approval_mode="bypass", agent_approval_mode="bypass")
    app = FastAPI()
    app.include_router(router)
    app.state.config = SimpleNamespace(safety=safety)

    with TestClient(app) as client:
        assert client.get("/api/settings/approval-modes").json() == {
            "app_mode": "bypass", "agent_mode": "bypass",
        }
        response = client.put(
            "/api/settings/approval-modes", json={"app_mode": "ask", "agent_mode": "always_ask"}
        )
        assert response.status_code == 200, response.text
        bad = client.put("/api/settings/approval-modes", json={"app_mode": "always_ask"})
        assert bad.status_code == 422

    assert safety.approval_mode == "ask" and safety.agent_approval_mode == "always_ask"
    import tomllib

    saved = tomllib.loads(toml.read_text(encoding="utf-8"))["safety"]
    assert saved == {"approval_mode": "ask", "agent_approval_mode": "always_ask"}
