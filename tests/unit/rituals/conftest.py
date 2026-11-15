"""A private ritual store, and small stand-ins for the society and the lead's chat."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest

from dodaios.agent_chat.service import SessionBusy
from dodaios.rituals import service
from dodaios.rituals.store import RitualStore, set_store

LEAD_SESSION = "lead-conversation"
WAKE_PHRASE = "Hey Nova"

#: A Monday morning on the person's clock.
MONDAY_0830 = datetime(2026, 3, 2, 8, 30).astimezone()

MORNING = {
    "name": "Good morning",
    "phrases": ["Good morning"],
    "steps": [
        {"when": "now", "text": "Play my favourite music."},
        {"when": "ahead", "text": "The most important AI news since yesterday."},
    ],
}


class Chat:
    """What the service asks of the chat service: the lead's conversation and its seat."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.running = False
        #: How many sends are refused because another turn took the seat first.
        self.refusals = 0
        session = SimpleNamespace(session_id=LEAD_SESSION, surface="jarvis")
        self.store = SimpleNamespace(
            lead_session_id=lambda: LEAD_SESSION,
            get_session=lambda session_id: session if session_id == LEAD_SESSION else None,
        )

    def is_running(self, session_id: str) -> bool:
        return self.running

    async def send(self, session_id: str, text: str, **options: Any) -> str:
        if self.refusals:
            self.refusals -= 1
            raise SessionBusy(session_id)
        self.sent.append({"session_id": session_id, "text": text, **options})
        return f"turn-{len(self.sent)}"


class Society:
    """What the service asks of the society runtime."""

    def __init__(self) -> None:
        self.chat = Chat()
        self.notices: list[dict[str, Any]] = []
        self.roster = SimpleNamespace(get=self._lead)
        self.wake_phrase = WAKE_PHRASE

    async def _lead(self, agent_id: str) -> Any:
        return SimpleNamespace(agent_id=agent_id, name="Dodaios")

    def config(self) -> Any:
        wake_word = SimpleNamespace(phrase=self.wake_phrase)
        return SimpleNamespace(trigger=SimpleNamespace(wake_word=wake_word))

    def chat_service(self) -> Any:
        return self.chat

    def display_name(self, agent: Any) -> str:
        return "Nova"

    async def post_chat_notice(self, agent: Any, payload: dict[str, Any]) -> None:
        self.notices.append(payload)


@pytest.fixture
def ritual_store():
    store = RitualStore(":memory:")
    set_store(store)
    try:
        yield store
    finally:
        set_store(None)
        store.close()


@pytest.fixture
async def society(ritual_store, monkeypatch: pytest.MonkeyPatch):
    world = Society()
    monkeypatch.setattr(service, "_runtime", lambda: world)
    monkeypatch.setattr(service, "_POLL_S", 0.01)
    try:
        yield world
    finally:
        await service.drain()
