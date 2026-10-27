"""Imported agents use the same approval default as manually created agents."""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.society.runtime import SocietyRuntime
from dodaios.ui.web.society_routes import router


@pytest.mark.parametrize("wrapped", [False, True])
def test_import_uses_bypass_and_preserves_explicit_rules(tmp_path: Path, wrapped: bool):
    runtime = SocietyRuntime(tmp_path, seed_starter_team=False)
    app = FastAPI()
    app.include_router(router)
    app.state.society_factory = lambda: runtime
    template = {
        "schema": 1,
        "name": "Imported helper",
        "instructions": "Maintain the task list.",
        "require_approval": ["plugin:gmail:send"],
        "denies": ["core:shell"],
    }
    payload = {"kind": "agent", "agent": template} if wrapped else template
    with TestClient(app) as client:
        manual = client.post("/api/society/agents", json={"name": "Manual helper"})
        assert manual.status_code == 200, manual.text
        imported = client.post("/api/society/templates/install", json={"template": payload})
        assert imported.status_code == 200, imported.text
        agent = imported.json()["agent"]
        assert agent["approval_mode"] == manual.json()["agent"]["approval_mode"] == "bypass"
        assert agent["approval_rules"]["require_approval"] == ["plugin:gmail:send"]
        assert agent["denies"] == ["core:shell"]
        saved = client.get(f"/api/society/agents/{agent['agent_id']}").json()["agent"]
        assert saved["approval_mode"] == "bypass"


def test_imported_require_approval_still_queues_under_bypass(tmp_path: Path):
    """#387: the publisher's confirmations bind even though the mode is bypass."""
    from dodaios.society.approvals import Verdict, decide

    runtime = SocietyRuntime(tmp_path, seed_starter_team=False)
    app = FastAPI()
    app.include_router(router)
    app.state.society_factory = lambda: runtime
    template = {
        "schema": 1,
        "name": "Mail helper",
        "instructions": "Draft replies.",
        "require_approval": ["plugin:gmail:send"],
    }
    with TestClient(app) as client:
        imported = client.post("/api/society/templates/install", json={"template": template})
        assert imported.status_code == 200, imported.text
        agent_id = imported.json()["agent"]["agent_id"]
        agent = client.portal.call(runtime.roster.resolve, agent_id)
    assert agent is not None and str(agent.approval_mode) == "bypass"
    for tier in ("safe", "ask"):
        assert decide(agent, "plugin:gmail", tier, verb="send") is Verdict.QUEUE
    assert decide(agent, "plugin:gmail", "ask", verb="read") is Verdict.RUN


def test_unsupported_runner_refusal_is_not_retried_with_another_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """#387: a runner refusal surfaces; the install never retries in another mode."""
    import dodaios.agent_chat.permissions as permissions
    import dodaios.agent_chat.service as service

    seen: list[str] = []

    def refuse(_runner: str, mode: str) -> bool:
        seen.append(mode)
        return False

    monkeypatch.setattr(service, "resolve_runner", lambda *_a, **_k: "fake-runner")
    monkeypatch.setattr(permissions, "society_mode_supported", refuse)
    runtime = SocietyRuntime(tmp_path, seed_starter_team=False)
    app = FastAPI()
    app.include_router(router)
    app.state.society_factory = lambda: runtime
    template = {"schema": 1, "name": "Refused helper", "instructions": "Help."}
    with TestClient(app) as client:
        refused = client.post(
            "/api/society/starters/install",
            json={"template": template, "seat": {"provider": "fake-provider"}},
        )
        assert refused.status_code == 422, refused.text
        assert client.portal.call(runtime.roster.resolve, "Refused helper") is None
    assert seen == ["bypass"]
