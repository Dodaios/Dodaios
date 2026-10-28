"""Opening a brand-new agent's chat: catalog and warm-up answer at once.

Live finding 2026-10-28: the panel asks for the catalog and the warm-up in the
same moment it binds the chat, so both answered 404 for a new agent, and the
catalog then refused the agent's seat pin ``subscription`` (a way of paying,
not a login) with 400 "Unknown subscription account".
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.unit.agent_chat.test_agent_chat_service import _app, scripted  # noqa: F401


@pytest.fixture
def quiet_catalog(monkeypatch: pytest.MonkeyPatch):
    import dodaios.ui.web.agent_chat_routes as routes

    async def no_live_models() -> dict[str, Any]:
        return {}

    monkeypatch.setattr(routes, "_live_cli_models", no_live_models)
    monkeypatch.setattr(routes, "_cli_installed", lambda runner: False)


def _fake_society(
    monkeypatch: pytest.MonkeyPatch, *, agent_id: str, runtime: str = "", killed: bool = False
) -> list[str]:
    """A society runtime with one active agent; binding creates its chat."""
    bound: list[str] = []
    agent = SimpleNamespace(
        agent_id=agent_id, session_id=f"society:{agent_id}", state="active", name="QA"
    )

    class Roster:
        async def get(self, wanted: str) -> Any:
            return agent if wanted == agent_id else None

    class Store:
        async def kill_switch(self) -> bool:
            return killed

    fake = SimpleNamespace(roster=Roster(), store=Store(), config=lambda: None)

    def ensure_session(svc: Any, _cfg: Any, row: Any) -> Any:
        bound.append(row.agent_id)
        existing = svc.store.get_session(row.session_id)
        if existing is not None:
            return existing
        return svc.store.create_session(
            provider="claude-api",
            model="claude-sonnet-5-5",
            effort="",
            cwd=str(Path.cwd()),
            permission_mode="ask",
            title=row.name,
            session_id=row.session_id,
            surface="society",
            account_id="subscription",
            runtime=runtime,
        )

    monkeypatch.setattr("dodaios.society.runtime.current_runtime", lambda: fake)
    monkeypatch.setattr("dodaios.society.chat_binding.ensure_session", ensure_session)
    return bound


def test_the_catalog_binds_a_new_agents_chat_and_accepts_the_subscription_pin(
    tmp_path: Path, monkeypatch, quiet_catalog
):
    bound = _fake_society(monkeypatch, agent_id="qa-starter")
    with TestClient(_app(tmp_path)) as client:
        res = client.get("/api/agent-chat/catalog?surface=society&session_id=society:qa-starter")
        assert res.status_code == 200, res.text
        assert res.json()["providers"]
        # The bound chat stays; a second read does not bind again.
        again = client.get("/api/agent-chat/catalog?surface=society&session_id=society:qa-starter")
        assert again.status_code == 200
    assert bound == ["qa-starter"]


@pytest.mark.parametrize("pin", ["subscription", "api-key"])
def test_the_catalog_reads_access_pins_as_ways_of_paying(
    tmp_path: Path, monkeypatch, quiet_catalog, pin: str
):
    with TestClient(_app(tmp_path)) as client:
        res = client.get(f"/api/agent-chat/catalog?surface=society&account_id={pin}")
        assert res.status_code == 200, res.text
        unknown = client.get("/api/agent-chat/catalog?surface=society&account_id=nobody-here")
        assert unknown.status_code == 400


def test_unknown_or_nested_society_ids_are_still_not_found(
    tmp_path: Path, monkeypatch, quiet_catalog
):
    bound = _fake_society(monkeypatch, agent_id="qa-starter")
    with TestClient(_app(tmp_path)) as client:
        for sid in ("society:ghost", "society:qa-starter:routine:1", "plain-id"):
            res = client.get(f"/api/agent-chat/catalog?surface=society&session_id={sid}")
            assert res.status_code == 404, sid
            assert client.post(f"/api/agent-chat/sessions/{sid}/warm").status_code == 404
    assert bound == []


def test_warm_binds_a_new_runtime_agents_chat(tmp_path: Path, monkeypatch):
    from dodaios.agent_chat import runner_acp

    warmed: list[str] = []

    async def fake_warm(session: Any, store: Any = None) -> bool:
        warmed.append(session.session_id)
        return True

    monkeypatch.setattr(runner_acp, "warm_session", fake_warm)
    bound = _fake_society(monkeypatch, agent_id="hermit", runtime="hermes")
    with TestClient(_app(tmp_path)) as client:
        res = client.post("/api/agent-chat/sessions/society:hermit/warm")
        assert res.status_code == 200, res.text
        assert res.json() == {"warming": True, "session_id": "society:hermit"}
    assert bound == ["hermit"]
    assert warmed == ["society:hermit"]


@pytest.mark.usefixtures("scripted")
async def test_the_next_message_carries_the_decisions_once(tmp_path: Path, monkeypatch):
    """The decided proposals ride in front of the agent's next message, once;
    the person's bubble keeps only what they typed."""
    from dodaios.agent_chat.events import make_event
    from dodaios.agent_chat.service import AgentChatService
    from dodaios.agent_chat.store import AgentChatStore

    svc = AgentChatService(
        AgentChatStore(tmp_path / "db.sqlite"), default_cwd=lambda: str(tmp_path)
    )
    session = svc.store.create_session(
        provider="fakeprov", model="m", effort="", cwd=str(tmp_path),
        session_id="society:writer", surface="society", permission_mode="ask",
    )

    async def bind(_sid: str, **_: Any) -> Any:
        return svc.store.get_session(session.session_id)

    monkeypatch.setattr(svc, "bind_society_session", bind)
    await svc.post_notice(
        session.session_id,
        {
            "kind": "proposal_resolved",
            "proposal_id": "01a18010-70bf-70d5-957a-57ba4d79b664",
            "status": "rejected",
            "summary": "Add a standing rule: Keep every answer under three sentences.",
        },
    )
    note_events = svc.store.list_events(session.session_id)
    assert [e["kind"] for e in note_events] == ["notice"]
    await svc.send(session.session_id, "Hello again")
    await svc.wait_turn(session.session_id)
    user = [e for e in svc.store.list_events(session.session_id) if e["kind"] == "user_message"]
    assert len(user) == 1
    sent = user[0]["payload"]
    assert sent["typed"] == "Hello again"
    assert sent["text"].startswith("[System note, not from the person")
    assert "three sentences.: rejected; nothing changed" in sent["text"]
    assert "01a18010" not in sent["text"]
    assert sent["text"].endswith("Hello again")
    # After that turn started, the same decision is not repeated.
    svc.store.append_event(session.session_id, make_event("turn_started", {"turn_id": "x"}))
    from dodaios.society.proposals import decision_context

    assert decision_context(svc.store.list_events(session.session_id)) == ""


def test_the_kill_switch_keeps_a_new_agents_chat_unbound(
    tmp_path: Path, monkeypatch, quiet_catalog
):
    bound = _fake_society(monkeypatch, agent_id="qa-starter", killed=True)
    with TestClient(_app(tmp_path)) as client:
        sid = "society:qa-starter"
        res = client.get(f"/api/agent-chat/catalog?surface=society&session_id={sid}")
        assert res.status_code == 404
        assert client.post(f"/api/agent-chat/sessions/{sid}/warm").status_code == 404
    assert bound == []
