"""Threads dragged into a coding thread's message reach its agent as cards."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from dodaios.agent_chat import thread_mentions
from dodaios.agent_chat.thread_mentions import expand_thread_mentions, mentioned_threads

OTHER = "3f9a2c11-aaaa-bbbb-cccc-000000000001"
OWN = "77aa0000-aaaa-bbbb-cccc-000000000002"


class _Store:
    def __init__(self, sessions: dict[str, Any], events: dict[str, list[dict[str, Any]]]):
        self.sessions = sessions
        self.events = events

    def get_session(self, session_id: str) -> Any:
        return self.sessions.get(session_id)

    def list_events(self, session_id: str, tail: int | None = None) -> list[dict[str, Any]]:
        return self.events.get(session_id, [])

    def title_is_automatic(self, session: Any) -> bool:
        return False


def _session(session_id: str, title: str = "Fix the login redirect") -> Any:
    return SimpleNamespace(
        session_id=session_id, surface="agent", title=title, preview="",
        provider="claude-api", model="opus", cwd="",
    )


def test_links_are_read_once_in_order() -> None:
    text = f"ask [Login](thread:{OTHER}) and [Login again](thread:{OTHER}) then [B](thread:{OWN})"
    assert mentioned_threads(text) == [("Login", OTHER), ("B", OWN)]
    assert mentioned_threads("no links, [file](notes.md)") == []


def test_plain_text_is_left_alone() -> None:
    store = _Store({}, {})
    out = expand_thread_mentions(store, "hello", own_session_id=OWN, is_running=lambda _: False)
    assert out is None


def test_card_names_the_thread_and_its_newest_messages(monkeypatch: Any) -> None:
    monkeypatch.setattr(thread_mentions, "_branch", lambda folder: "")
    events = [
        {"kind": "user_message", "seq": 1, "payload": {"text": "make login redirect work"}},
        {"kind": "tool_call", "seq": 2, "payload": {"name": "Edit", "summary": "auth.py"}},
        {"kind": "assistant_text", "seq": 3, "payload": {"text": "Changed auth.py."}},
    ]
    store = _Store({OTHER: _session(OTHER)}, {OTHER: events})
    text = f"Wait for [Login fix](thread:{OTHER}) before you touch auth."
    out = expand_thread_mentions(
        store, text, own_session_id=OWN, is_running=lambda sid: sid == OTHER
    )
    assert out is not None
    assert out.startswith(text)
    assert '"Login fix"' in out
    assert "Fix the login redirect" in out
    assert "working right now" in out and "not working" not in out
    assert "the person: make login redirect work" in out
    assert "coding agent: Changed auth.py." in out
    assert "Edit auth.py" not in out


def test_own_thread_alone_adds_nothing_and_a_gone_thread_says_so() -> None:
    store = _Store({OWN: _session(OWN)}, {})
    own = f"[me](thread:{OWN})"
    alone = expand_thread_mentions(store, own, own_session_id=OWN, is_running=lambda _: False)
    assert alone is None
    gone = expand_thread_mentions(
        store, f"[old](thread:{OTHER})", own_session_id=OWN, is_running=lambda _: False
    )
    assert gone is not None and "no longer exists" in gone
