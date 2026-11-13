"""``/api/agent-chat/lead/threads``: the IDE threads the assistant wrote a task into."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.agent_chat.events import make_event
from dodaios.agent_chat.service import AgentChatService
from dodaios.agent_chat.store import AgentChatStore
from dodaios.ui.web.agent_chat_routes import router

_LEAD = {"agent_id": "jarvis", "name": "Dodaios"}


def _thread(
    store: AgentChatStore,
    tmp_path: Path,
    title: str,
    surface: str = "agent",
    provider: str = "claude",
) -> str:
    return store.create_session(
        provider=provider, model="m", effort="", cwd=str(tmp_path), title=title, surface=surface
    ).session_id


def _say(
    store: AgentChatStore, sid: str, text: str, ts_ms: int, author: dict | None = None
) -> None:
    event = make_event("user_message", {"text": text, **({"author": author} if author else {})})
    event["ts_ms"] = ts_ms
    store.append_event(sid, event)


def test_only_threads_the_assistant_wrote_into_are_listed_newest_task_first(
    tmp_path: Path,
) -> None:
    store = AgentChatStore(":memory:")
    older = _thread(store, tmp_path, "Fix the login")
    newer = _thread(store, tmp_path, "Write the docs")
    own = _thread(store, tmp_path, "The person's own thread")
    scout = _thread(store, tmp_path, "Another agent's thread")
    front = _thread(store, tmp_path, "A front-page chat", surface="jarvis")
    _say(store, older, "Fix the login form", 1_000, _LEAD)
    _say(store, older, "and add a test", 3_000)  # the person joined in later
    _say(store, newer, "Write the docs", 2_000, _LEAD)
    _say(store, own, "hello", 4_000)
    _say(store, scout, "research this", 5_000, {"agent_id": "scout", "name": "Scout"})
    _say(store, front, "not an IDE thread", 6_000, _LEAD)

    hits = store.sessions_briefed_by("jarvis")
    assert [(s.session_id, ms) for s, ms in hits] == [(newer, 2_000), (older, 1_000)]
    assert [s.session_id for s, _ in store.sessions_briefed_by("jarvis", limit=1)] == [newer]

    app = FastAPI()
    app.include_router(router)
    app.state.agent_chat = AgentChatService(store)
    with TestClient(app) as client:
        rows = client.get("/api/agent-chat/lead/threads").json()["threads"]
    assert [row["session_id"] for row in rows] == [newer, older]
    assert rows[0]["title"] == "Write the docs"
    assert rows[0]["briefed_ms"] == 2_000
    assert (rows[0]["running"], rows[0]["waiting"]) == (False, False)
    assert rows[0]["cwd"] == str(tmp_path)


def test_a_row_names_the_coding_agent_so_the_sidebar_can_draw_its_logo(tmp_path: Path) -> None:
    store = AgentChatStore(":memory:")
    codex = _thread(store, tmp_path, "Port the parser", provider="openai-codex")
    kimi = _thread(store, tmp_path, "Write the tests", provider="kimi")
    plain = _thread(store, tmp_path, "Answer a question", provider="openai")
    for at, sid in enumerate((codex, kimi, plain), start=1):
        _say(store, sid, "do it", at * 1_000, _LEAD)

    app = FastAPI()
    app.include_router(router)
    app.state.agent_chat = AgentChatService(store)
    with TestClient(app) as client:
        rows = client.get("/api/agent-chat/lead/threads").json()["threads"]
    agents = {row["session_id"]: (row["agent"], bool(row["agent_label"])) for row in rows}
    # A provider without a coding CLI behind it has no agent, and no logo.
    assert agents == {codex: ("codex", True), kimi: ("kimi", True), plain: ("", True)}
