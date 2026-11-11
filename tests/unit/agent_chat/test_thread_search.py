"""The thread search: which chats a text finds, and what each hit shows."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.agent_chat.service import AgentChatService
from dodaios.agent_chat.store import AgentChatStore
from dodaios.ui.web.agent_chat_routes import router


def _session(store: AgentChatStore, title: str = "", surface: str = "agent") -> str:
    return store.create_session(
        provider="claude", model="", effort="", cwd="C:/repo", title=title, surface=surface
    ).session_id


def _say(store: AgentChatStore, session_id: str, kind: str, text: str, ts_ms: int) -> None:
    store.append_event(session_id, {"kind": kind, "payload": {"text": text}, "ts_ms": ts_ms})


def test_search_finds_messages_and_titles_caselessly_newest_first():
    store = AgentChatStore()
    old = _session(store)
    _say(store, old, "user_message", "Fix the Café-Button in the header", 1_000)
    new = _session(store)
    _say(store, new, "user_message", "Something else", 2_000)
    _say(store, new, "assistant_text", "The café button now has its own icon.", 3_000)
    titled = _session(store, title="Café menu")
    _say(store, titled, "user_message", "no match in here", 500)

    hits = store.search_sessions("CAFÉ")

    assert [hit["session_id"] for hit in hits] == [new, old, titled]
    assert hits[0]["snippet"] == "The café button now has its own icon."
    assert hits[0]["kind"] == "assistant_text"
    assert hits[0]["matches"] == 1
    assert hits[2]["title_match"] is True
    assert hits[2]["snippet"] == ""


def test_search_counts_matches_and_shows_the_latest_one():
    store = AgentChatStore()
    sid = _session(store)
    _say(store, sid, "user_message", "first deploy", 1_000)
    _say(store, sid, "assistant_text", "second deploy done", 2_000)

    [hit] = store.search_sessions("deploy")

    assert hit["matches"] == 2
    assert hit["snippet"] == "second deploy done"


def test_search_stays_on_its_surface_and_ignores_json_keys():
    store = AgentChatStore()
    _say(store, _session(store, surface="jarvis"), "user_message", "deploy", 1_000)
    _say(store, _session(store), "user_message", "hello", 1_000)

    assert store.search_sessions("deploy") == []
    # "text" is the payload's key, not anything anybody wrote.
    assert store.search_sessions("text") == []
    assert store.search_sessions("   ") == []


def test_snippet_is_cut_around_the_match():
    store = AgentChatStore()
    sid = _session(store)
    _say(store, sid, "user_message", "a " * 200 + "needle" + " b" * 200, 1_000)

    [hit] = store.search_sessions("needle")

    assert "needle" in hit["snippet"]
    assert hit["snippet"].startswith("…") and hit["snippet"].endswith("…")


def test_search_route(tmp_path: Path):
    app = FastAPI()
    app.include_router(router)
    store = AgentChatStore(tmp_path / "db.sqlite")
    app.state.agent_chat = AgentChatService(store, default_cwd=lambda: str(tmp_path))
    sid = _session(store)
    _say(store, sid, "user_message", "Make the search find threads", 1_000)

    with TestClient(app) as client:
        found = client.get("/api/agent-chat/sessions/search", params={"q": "search"}).json()
        hidden = client.get(
            "/api/agent-chat/sessions/search", params={"q": "search", "surface": "side"}
        ).json()

    assert [hit["session_id"] for hit in found["hits"]] == [sid]
    assert hidden == {"hits": []}
