"""The thread lists tell the sidebar which coding agent waits on the person.

An open question card counts like an open approval: the IDE sidebar draws a
mark on the thread, and the home page's lead threads say it is waiting.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.agent_chat.events import make_event
from dodaios.agent_chat.service import AgentChatService
from dodaios.agent_chat.store import AgentChatStore
from dodaios.ui.web.agent_chat_routes import router

_LEAD = {"agent_id": "jarvis", "name": "Dodaios"}


def _client(store: AgentChatStore, asking: str) -> TestClient:
    svc = AgentChatService(store)
    # Stands in for a question card the coding agent opened in ``asking``.
    svc.pending_questions = lambda sid: ["q1"] if sid == asking else []  # type: ignore[method-assign]
    app = FastAPI()
    app.include_router(router)
    app.state.agent_chat = svc
    return TestClient(app)


def _thread(store: AgentChatStore, tmp_path: Path, title: str) -> str:
    return store.create_session(
        provider="claude", model="m", effort="", cwd=str(tmp_path), title=title, surface="agent"
    ).session_id


def test_the_ide_thread_list_names_open_questions(tmp_path: Path) -> None:
    store = AgentChatStore(":memory:")
    asking = _thread(store, tmp_path, "Asks a question")
    quiet = _thread(store, tmp_path, "Works alone")

    with _client(store, asking) as client:
        rows = client.get("/api/agent-chat/sessions", params={"surface": "agent"}).json()["sessions"]

    questions = {row["session_id"]: row["pending_questions"] for row in rows}
    assert questions == {asking: ["q1"], quiet: []}


def test_a_lead_thread_with_an_open_question_is_waiting(tmp_path: Path) -> None:
    store = AgentChatStore(":memory:")
    asking = _thread(store, tmp_path, "Asks a question")
    quiet = _thread(store, tmp_path, "Works alone")
    for sid in (asking, quiet):
        event = make_event("user_message", {"text": "do it", "author": _LEAD})
        store.append_event(sid, event)

    with _client(store, asking) as client:
        rows = client.get("/api/agent-chat/lead/threads").json()["threads"]

    assert {row["session_id"]: row["waiting"] for row in rows} == {asking: True, quiet: False}
