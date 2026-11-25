"""Fork a thread, and continue an existing CLI session in a thread."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.agent_chat import runner_cli, thread_sessions
from dodaios.agent_chat.events import make_event
from dodaios.agent_chat.service import AgentChatService
from dodaios.agent_chat.store import AgentChatStore
from dodaios.ui.web import agent_chat_routes

UUID = "11111111-2222-3333-4444-555555555555"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("dodaios.agent_chat.service._claude_cli_installed", lambda: True)
    app = FastAPI()
    app.include_router(agent_chat_routes.router)
    app.state.agent_chat = AgentChatService(AgentChatStore(tmp_path / "chat.db"))
    return TestClient(app), app.state.agent_chat


def test_create_thread_on_an_existing_session(client):
    http, svc = client
    ok = http.post("/api/agent-chat/sessions", json={"provider": "claude-api", "vendor_session": UUID})
    assert ok.status_code == 201
    assert svc.store.get_session(ok.json()["session_id"]).vendor_session == UUID
    bad = http.post("/api/agent-chat/sessions", json={"provider": "claude-api", "vendor_session": "x"})
    assert bad.status_code == 400
    other = http.post("/api/agent-chat/sessions", json={"provider": "kimi", "vendor_session": UUID})
    assert other.status_code == 400


def test_fork_copies_whole_turns_and_marks_the_claude_conversation(client):
    http, svc = client
    src = svc.store.create_session(
        provider="claude-api", model="m", effort="", cwd="", title="Plan", surface="agent"
    )
    svc.store.update_session(src.session_id, vendor_session=UUID)
    for kind, payload in (
        ("user_message", {"text": "hi"}),
        ("turn_started", {"turn_id": "t1"}),
        ("assistant_text", {"turn_id": "t1", "text": "hello"}),
        ("turn_finished", {"turn_id": "t1", "status": "done"}),
        ("user_message", {"text": "unfinished"}),
    ):
        svc.store.append_event(src.session_id, make_event(kind, payload))
    res = http.post(f"/api/agent-chat/sessions/{src.session_id}/fork", json={"title": "Copy"})
    assert res.status_code == 201
    copy = svc.store.get_session(res.json()["session_id"])
    assert copy.title == "Copy"
    assert copy.vendor_session == thread_sessions.FORK_PREFIX + UUID
    kinds = [e["kind"] for e in svc.store.list_events(copy.session_id)]
    assert kinds == ["user_message", "turn_started", "assistant_text", "turn_finished"]
    # A fork of a pending fork still points at the real conversation.
    again = http.post(f"/api/agent-chat/sessions/{copy.session_id}/fork", json={})
    assert svc.store.get_session(again.json()["session_id"]).vendor_session == copy.vendor_session


def test_codex_fork_starts_a_fresh_cli_conversation(client):
    http, svc = client
    src = svc.store.create_session(
        provider="openai-codex", model="", effort="", cwd="", surface="agent"
    )
    svc.store.update_session(src.session_id, vendor_session=UUID)
    res = http.post(f"/api/agent-chat/sessions/{src.session_id}/fork", json={})
    assert not svc.store.get_session(res.json()["session_id"]).vendor_session


def test_claude_planner_forks_a_pending_fork_and_resumes_a_plain_id(monkeypatch):
    monkeypatch.setattr(runner_cli, "claude_argv_prefix", lambda: ["claude"])

    def argv(resume):
        return runner_cli.plan_claude(
            prompt="x", cwd=__import__("pathlib").Path("."), model="", effort="",
            permission_mode="", resume=resume,
        ).argv

    forked = argv("fork:" + UUID)
    assert forked[forked.index("--resume") + 1] == UUID
    assert "--fork-session" in forked and "--session-id" in forked
    plain = argv(UUID)
    assert "--fork-session" not in plain and plain[plain.index("--resume") + 1] == UUID
