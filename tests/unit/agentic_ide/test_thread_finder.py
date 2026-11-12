"""Finding a coding thread again: its code, a search over every thread, its link."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.agent_chat.events import make_event
from dodaios.agent_chat.service import AgentChatService
from dodaios.agent_chat.store import AgentChatStore
from dodaios.agentic_ide import thread_finder
from dodaios.ui.web.agent_chat_routes import router

A = "3f9a2c41d0aa4b7e9c1f2a3b4c5d6e7f"
B = "3f9a2c99ffaa4b7e9c1f2a3b4c5d6e70"
C = "77b1e0c2d0aa4b7e9c1f2a3b4c5d6e71"


def _thread(
    store: AgentChatStore, folder: Path, sid: str, title: str, *, surface: str = "agent"
) -> str:
    store.create_session(
        provider="claude-api", model="m", effort="", cwd=str(folder), title=title,
        session_id=sid, surface=surface,
    )
    return sid


def _say(store: AgentChatStore, sid: str, text: str, kind: str = "user_message") -> None:
    store.append_event(sid, make_event(kind, {"text": text}))


def _found(result: dict) -> list[str]:
    return [session.session_id for session, _hit in result["sessions"]]


def test_the_code_is_the_start_of_the_id_however_it_is_written() -> None:
    assert thread_finder.thread_code(A) == "3f9a2c"
    for written in ("#3f9a2c", "3F9A2C", "3f9a 2c", "thread:3f9a2c", "# 3f9a-2c", A):
        assert thread_finder.code_key(written).startswith("3f9a2c"), written
    assert thread_finder.code_key("what was that thread?") == ""
    assert thread_finder.code_key("") == ""


def test_a_short_reference_is_a_code_and_a_whole_id_is_not() -> None:
    assert thread_finder.is_short_ref("#3f9a2c")
    assert thread_finder.is_short_ref("thread:3f9a2c")
    assert not thread_finder.is_short_ref(f"thread:{A}")
    assert not thread_finder.is_short_ref("pane:abc123")
    assert not thread_finder.is_short_ref("Alex")
    assert not thread_finder.is_short_ref("#ab")


def test_a_code_names_its_thread_and_only_a_coding_thread(tmp_path: Path) -> None:
    store = AgentChatStore(":memory:")
    _thread(store, tmp_path, A, "Fix the login")
    _thread(store, tmp_path, C, "Write the docs")
    _thread(store, tmp_path, "3f9a2c00000000000000000000000000", "Front page", surface="jarvis")

    assert [s.session_id for s in thread_finder.sessions_for_code(store, "#3f9a2c")] == [A]
    assert [s.session_id for s in thread_finder.sessions_for_code(store, "77B1")] == [C]
    assert thread_finder.sessions_for_code(store, "#3f9") == []  # too short to be a code
    assert thread_finder.sessions_for_code(store, "#000000") == []
    # Cut so short that two threads answer: both come back, the caller asks.
    _thread(store, tmp_path, B, "Another one")
    assert {s.session_id for s in thread_finder.sessions_for_code(store, "3f9a2c")} == {A, B}
    assert [s.session_id for s in thread_finder.sessions_for_code(store, "3f9a2c4")] == [A]


def test_words_find_a_thread_by_its_title_or_by_what_was_said(tmp_path: Path) -> None:
    store = AgentChatStore(":memory:")
    _thread(store, tmp_path, A, "Fix the login")
    _thread(store, tmp_path, C, "Write the docs")
    _say(store, A, "The session cookie expires too early on Safari")
    _say(store, C, "Describe the login flow in the README", "assistant_text")

    assert _found(thread_finder.find(store, query="cookie safari")) == [A]
    # Both hold "login"; the one that holds every word comes first.
    both = thread_finder.find(store, query="login README")
    assert _found(both) == [C, A]
    hit = both["sessions"][0][1]
    assert (hit["words"], hit["of"]) == (2, 2)
    assert "README" in hit["snippet"]
    assert thread_finder.find(store, query="kubernetes")["sessions"] == []
    assert both["by"] == "words"


def test_no_words_lists_the_newest_threads_whatever_their_age(tmp_path: Path) -> None:
    store = AgentChatStore(":memory:")
    _thread(store, tmp_path, A, "Fix the login")
    _thread(store, tmp_path, C, "Write the docs")
    store._conn.execute(  # a thread nobody touched for a year
        "UPDATE agent_chat_sessions SET updated_ms = 1000 WHERE session_id = ?", (A,)
    )

    result = thread_finder.find(store)

    assert result["by"] == "recent" and _found(result) == [C, A]
    assert thread_finder.find(store, limit=1)["more"] == 1


def test_a_code_typed_where_the_words_go_is_still_a_code(tmp_path: Path) -> None:
    store = AgentChatStore(":memory:")
    _thread(store, tmp_path, A, "Fix the login")
    _thread(store, tmp_path, C, "Write the docs")

    by_query = thread_finder.find(store, query="#3f9a2c")
    assert by_query["by"] == "code" and _found(by_query) == [A]
    assert thread_finder.find(store, code="77b1e0")["by"] == "code"
    # A word that only looks like hex and names no thread is searched as a word.
    _say(store, C, "Remove the dead code in cafe.py")
    assert _found(thread_finder.find(store, query="cafe")) == [C]


def test_a_folder_narrows_the_search(tmp_path: Path) -> None:
    store = AgentChatStore(":memory:")
    site, app = tmp_path / "site", tmp_path / "app"
    _thread(store, site, A, "Fix the login")
    _thread(store, app / "worktrees" / "x", C, "Fix the login too")

    assert _found(thread_finder.find(store, query="login", folders=[str(app)])) == [C]
    assert set(_found(thread_finder.find(store, query="login"))) == {A, C}


def test_the_shown_title_is_the_persons_own_when_they_renamed_it(tmp_path: Path) -> None:
    store = AgentChatStore(":memory:")
    _thread(store, tmp_path, A, "")
    _say(store, A, "Please fix the login form")
    session = store.get_session(A)
    assert thread_finder.shown_title(store, session) == "Please fix the login form"
    store.update_session(A, title="Login rework")
    assert thread_finder.shown_title(store, store.get_session(A)) == "Login rework"


def test_the_link_is_markdown_that_names_the_thread() -> None:
    assert thread_finder.thread_link(A, "Fix the login") == f"[Fix the login](thread:{A})"
    assert thread_finder.thread_link(A, "Fix [urgent] bug") == f"[Fix (urgent) bug](thread:{A})"
    assert thread_finder.thread_link(A, "") == f"[Coding agent](thread:{A})"


def test_when_reads_as_a_date_and_an_age() -> None:
    now = 1_800_000_000.0
    assert thread_finder.when(0) == ""
    assert thread_finder.when(int((now - 30) * 1000), now=now).endswith("(just now)")
    assert thread_finder.when(int((now - 9 * 86400) * 1000), now=now).endswith("(9 days ago)")


def test_the_session_list_carries_the_code_and_a_link_resolves(tmp_path: Path) -> None:
    store = AgentChatStore(":memory:")
    _thread(store, tmp_path, A, "Fix the login")
    _thread(store, tmp_path, "aaaa1111000000000000000000000000", "Front page", surface="jarvis")
    app = FastAPI()
    app.include_router(router)
    app.state.agent_chat = AgentChatService(store)
    with TestClient(app) as client:
        rows = client.get("/api/agent-chat/sessions?surface=agent").json()["sessions"]
        assert [row["code"] for row in rows] == ["3f9a2c"]

        by_id = client.get(f"/api/agent-chat/thread-links/{A}").json()
        assert by_id["found"] is True and by_id["session_id"] == A
        assert by_id["title"] == "Fix the login" and by_id["code"] == "3f9a2c"
        assert by_id["agent"] == "claude" and by_id["agent_label"]
        by_code = client.get("/api/agent-chat/thread-links/3f9a2c").json()
        assert by_code["session_id"] == A

        # A front-page chat is not a coding thread, and a code nobody carries names none.
        assert client.get("/api/agent-chat/thread-links/aaaa11").json()["found"] is False
        assert client.get("/api/agent-chat/thread-links/000000").json()["found"] is False
