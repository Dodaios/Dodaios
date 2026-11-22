"""``/clear`` in a coding thread starts its conversation over."""

from __future__ import annotations

import asyncio
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.agent_chat import send_queue, thread_clear
from dodaios.agent_chat.events import CLEARED_KIND, make_event
from dodaios.agent_chat.service import AgentChatService, SessionBusy, _Running
from dodaios.agent_chat.store import AgentChatStore
from dodaios.ui.web import agent_chat_routes

VENDOR = "11111111-2222-3333-4444-555555555555"


def _thread(store: AgentChatStore, *, surface: str = "agent", title: str = "") -> str:
    session = store.create_session(
        provider="claude-api", model="m", effort="", cwd="", title=title, surface=surface
    )
    return session.session_id


def _one_turn(store: AgentChatStore, sid: str, said: str, answer: str) -> None:
    for kind, payload in (
        ("user_message", {"text": said}),
        ("turn_started", {"turn_id": said}),
        ("assistant_text", {"turn_id": said, "text": answer}),
        ("turn_finished", {"turn_id": said, "status": "done"}),
    ):
        store.append_event(sid, make_event(kind, payload))
    store.update_session(sid, vendor_session=VENDOR)


def _kinds(store: AgentChatStore, sid: str, **how) -> list[str]:
    return [event["kind"] for event in store.list_events(sid, **how)]


@pytest.fixture
def store():
    store = AgentChatStore(":memory:")
    yield store
    store.close()


@pytest.fixture
def service(store):
    return AgentChatService(store)


# ------------------------------------------------------------------ the command


@pytest.mark.parametrize(
    ("text", "name"),
    [
        ("/clear", ""),
        ("  /clear  ", ""),
        ("/reset", ""),
        ("/new", ""),
        ("/clear login bug", "login bug"),
        ("/clear  two\nlines ", "two lines"),
    ],
)
def test_the_command_and_the_names_the_cli_lists_for_it(text, name):
    assert thread_clear.is_clear_command(text)
    assert thread_clear.clear_name(text) == name


@pytest.mark.parametrize(
    "text",
    ["clear", "/clearing", "/clear/all", "please /clear", "/context", "/usr/bin/clear", ""],
)
def test_other_words_are_messages(text):
    assert not thread_clear.is_clear_command(text)
    assert thread_clear.clear_name(text) is None


def test_only_a_bare_command_in_a_coding_thread_clears(store):
    thread = store.get_session(_thread(store))
    chat = store.get_session(_thread(store, surface="society"))
    assert thread_clear.wants_clear(thread, "/clear")
    assert not thread_clear.wants_clear(thread, "/clear", [{"name": "shot.png"}])
    assert not thread_clear.wants_clear(chat, "/clear")


def test_the_slash_list_says_what_the_thread_does_with_it(tmp_path):
    from dodaios.agent_chat import typeahead

    typeahead.remember_cli_commands("claude-cli", tmp_path, [
        {
            "name": "clear",
            "description": "Start a new session; the old one stays in /resume",
            "argumentHint": "[name]",
            "aliases": ["reset", "new"],
        },
        {"name": "deploy", "description": "Ship it"},
    ])

    def rows(surface: str) -> dict[str, dict]:
        listed = typeahead.suggest(
            runner="claude-cli", cwd=tmp_path, trigger="/", surface=surface, limit=1000
        )["items"]
        return {row["value"]: row for row in listed}

    in_thread = rows("agent")["clear"]
    assert in_thread["hint"] == "Clear this thread and start the agent with an empty context"
    assert in_thread["argument_hint"] == "[name]"
    assert in_thread["aliases"] == ["reset", "new"]
    assert rows("agent")["deploy"]["hint"] == "Ship it"
    # Any other chat on a Claude Code seat keeps the CLI's own line.
    assert rows("society")["clear"]["hint"].startswith("Start a new session")


# ------------------------------------------------------------------ the store


def test_a_cleared_conversation_starts_at_its_clear(store):
    sid = _thread(store)
    _one_turn(store, sid, "first topic", "an answer")
    cleared = store.append_event(sid, make_event(CLEARED_KIND, {}))

    session = store.get_session(sid)
    assert session.cleared_seq == cleared["seq"] == 5
    # The CLI's own conversation is left behind: the next turn opens a new one.
    assert not session.vendor_session
    assert session.preview == ""
    assert _kinds(store, sid) == [CLEARED_KIND]
    # A reader that still holds events from before gets the clear and drops them.
    assert _kinds(store, sid, after_seq=2) == [CLEARED_KIND]
    assert _kinds(store, sid, after_seq=5) == []
    # Nothing was deleted.
    assert _kinds(store, sid, include_cleared=True) == [
        "user_message", "turn_started", "assistant_text", "turn_finished", CLEARED_KIND,
    ]

    _one_turn(store, sid, "second topic", "another answer")
    assert _kinds(store, sid)[:2] == [CLEARED_KIND, "user_message"]
    assert _kinds(store, sid, tail=1) == ["turn_finished"]


def test_the_first_message_after_a_clear_names_the_thread(store):
    sid = _thread(store)
    _one_turn(store, sid, "first topic", "an answer")
    assert store.get_session(sid).title == "first topic"
    store.append_event(sid, make_event(CLEARED_KIND, {}))
    assert store.get_session(sid).title == ""
    store.append_event(sid, make_event("user_message", {"text": "second topic"}))
    session = store.get_session(sid)
    assert session.title == "second topic"
    assert store.title_is_automatic(session)


def test_a_typed_title_outlives_a_clear_and_a_second_one(store):
    sid = _thread(store)
    _one_turn(store, sid, "first topic", "an answer")
    store.update_session(sid, title="Login work")
    store.append_event(sid, make_event(CLEARED_KIND, {}))
    # Nothing was said in between: there is no message to compare the title with.
    store.append_event(sid, make_event(CLEARED_KIND, {}))
    assert store.get_session(sid).title == "Login work"
    store.append_event(sid, make_event("user_message", {"text": "second topic"}))
    session = store.get_session(sid)
    assert session.title == "Login work"
    assert not store.title_is_automatic(session)


def test_search_finds_only_what_was_said_since_the_clear(store):
    sid = _thread(store, title="Kept name")
    _one_turn(store, sid, "the old pineapple question", "pineapple answer")
    store.append_event(sid, make_event(CLEARED_KIND, {}))
    assert store.search_sessions("pineapple") == []
    store.append_event(sid, make_event("user_message", {"text": "a new mango question"}))
    hits = store.search_sessions("mango")
    assert [hit["session_id"] for hit in hits] == [sid]


def test_a_database_from_before_the_column_gets_it(tmp_path):
    path = tmp_path / "chat.db"
    first = AgentChatStore(path)
    sid = _thread(first)
    first.close()
    raw = sqlite3.connect(path)
    raw.execute("ALTER TABLE agent_chat_sessions DROP COLUMN cleared_seq")
    raw.commit()
    raw.close()

    again = AgentChatStore(path)
    try:
        assert again.get_session(sid).cleared_seq == 0
        again.append_event(sid, make_event(CLEARED_KIND, {}))
        assert again.get_session(sid).cleared_seq == 1
    finally:
        again.close()


# ------------------------------------------------------------------ the service


async def test_slash_clear_empties_the_thread_and_runs_no_turn(service, store):
    sid = _thread(store)
    _one_turn(store, sid, "first topic", "an answer")
    live = service.subscribe(sid)

    assert await service.send(sid, "/clear") == ""

    assert not service.is_running(sid)
    events = store.list_events(sid)
    # No message is written for the command, and no turn started.
    assert [event["kind"] for event in events] == [CLEARED_KIND, "session_updated"]
    assert events[1]["payload"] == {"title": "", "vendor_session": "", "cleared_seq": 5}
    assert not store.get_session(sid).vendor_session
    # The open windows hear of it at once.
    assert [live.get_nowait()["kind"] for _ in range(2)] == [CLEARED_KIND, "session_updated"]


async def test_a_name_after_the_command_becomes_the_title(service, store):
    sid = _thread(store)
    _one_turn(store, sid, "first topic", "an answer")
    await service.send(sid, "/clear login bug")
    assert store.get_session(sid).title == "login bug"
    assert store.list_events(sid)[-1]["payload"]["title"] == "login bug"


async def test_a_working_thread_is_not_cleared_under_its_turn(service, store):
    sid = _thread(store)
    _one_turn(store, sid, "first topic", "an answer")
    run = _Running("turn-1", asyncio.Event())
    run.task = asyncio.create_task(asyncio.sleep(5))
    service._running[sid] = run
    try:
        with pytest.raises(SessionBusy):
            await service.send(sid, "/clear")
        assert CLEARED_KIND not in _kinds(store, sid)
        assert store.get_session(sid).vendor_session == VENDOR
    finally:
        run.task.cancel()


async def test_only_the_persons_own_command_clears(service, store, monkeypatch):
    """A ``/clear`` another agent wrote into the thread stays a message of that agent."""
    sid = _thread(store)
    _one_turn(store, sid, "first topic", "an answer")
    cleared: list[str] = []

    async def clear(session_id: str, *, name: str = "") -> dict:
        cleared.append(session_id)
        return {}

    monkeypatch.setattr(service, "clear_conversation", clear)

    async def stop_here(session_id: str) -> None:
        raise RuntimeError("past the clear")

    monkeypatch.setattr(service, "_await_finishing", stop_here)
    with pytest.raises(RuntimeError, match="past the clear"):
        await service.send(sid, "/clear", author={"agent_id": "jarvis", "name": "Nova"})
    with pytest.raises(RuntimeError, match="past the clear"):
        await service.send(sid, "/clear", [{"name": "shot.png", "kind": "image"}])
    assert cleared == []
    await service.send(sid, "/clear")
    assert cleared == [sid]


async def test_other_chats_are_not_cleared_this_way(service, store):
    sid = _thread(store, surface="society")
    with pytest.raises(ValueError, match="coding thread"):
        await service.clear_conversation(sid)


# ------------------------------------------------------------------ while the agent works


class _Thread:
    """Just enough of the chat service for the queue: one running flag."""

    def __init__(self) -> None:
        self.running = True
        self.started = asyncio.Event()
        self.sent: list[str] = []
        self.steered: list[str] = []
        self.notices: list[dict] = []
        self.store = type("Store", (), {
            "get_session": staticmethod(
                lambda sid: type("Session", (), {"session_id": sid, "surface": "agent"})()
            ),
        })()

    def is_running(self, session_id: str) -> bool:
        return self.running

    async def steer(self, session_id: str, text: str, attachments=None) -> bool:
        self.steered.append(text)
        return True

    async def send(self, session_id, text, attachments=None, *, tool_choices=None) -> str:
        if self.running:
            raise SessionBusy(session_id)
        self.sent.append(text)
        self.started.set()
        return ""

    async def post_notice(self, session_id: str, payload: dict) -> None:
        self.notices.append(dict(payload))


async def test_the_command_is_never_typed_into_the_running_turn(monkeypatch):
    monkeypatch.setattr(send_queue, "_POLL_S", 0.01)
    thread = _Thread()
    assert not await send_queue.try_steer(thread, "t1", "/clear")
    assert await send_queue.try_steer(thread, "t1", "go left")

    # It waits like any message typed meanwhile, and clears once the turn is over.
    turn_id, queue_id = await send_queue.send_or_queue(thread, "t1", "/clear")
    assert turn_id == "" and queue_id
    assert not await send_queue.steer_waiting(thread, "t1", queue_id)
    assert thread.steered == ["go left"] and thread.sent == []

    thread.running = False
    await asyncio.wait_for(thread.started.wait(), timeout=2)
    assert thread.sent == ["/clear"]


# ------------------------------------------------------------------ the route


def test_the_message_route_says_the_thread_was_cleared(tmp_path):
    store = AgentChatStore(tmp_path / "chat.db")
    svc = AgentChatService(store)
    sid = _thread(store)
    _one_turn(store, sid, "first topic", "an answer")
    app = FastAPI()
    app.include_router(agent_chat_routes.router)
    app.state.agent_chat = svc
    try:
        with TestClient(app) as client:
            sent = client.post(f"/api/agent-chat/sessions/{sid}/messages", json={"text": "/clear"})
            assert sent.status_code == 202
            assert sent.json() == {"turn_id": "", "session_id": sid, "cleared": True}
            read = client.get(f"/api/agent-chat/sessions/{sid}").json()
            assert [event["kind"] for event in read["events"]] == [CLEARED_KIND, "session_updated"]
            assert read["session"]["cleared_seq"] == 5
            assert not read["session"]["vendor_session"]
            # A window that reconnects with what it had before the clear gets the clear.
            with client.websocket_connect(f"/api/agent-chat/sessions/{sid}/ws?after=3") as ws:
                snapshot = ws.receive_json()
            assert [event["kind"] for event in snapshot["events"]][0] == CLEARED_KIND
    finally:
        store.close()
