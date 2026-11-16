"""A ritual's phrase typed into the assistant's conversation, through the real chat route."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.agent_chat import service as service_mod
from dodaios.agent_chat.events import make_event
from dodaios.agent_chat.service import AgentChatService
from dodaios.agent_chat.store import AgentChatStore
from dodaios.rituals import prepare, service
from dodaios.rituals.store import RitualStore, set_store
from dodaios.ui.web.agent_chat_routes import router

MORNING = {
    "name": "Good morning",
    "phrases": ["Good morning"],
    "steps": [{"when": "ahead", "text": "The most important AI news since yesterday."}],
}


class Society:
    """What the rituals ask of the society, with the real chat service behind it."""

    def __init__(self, chat: AgentChatService, lead_session: str) -> None:
        self._chat = chat
        self._lead_session = lead_session
        self.roster = SimpleNamespace(get=self._lead)

    async def _lead(self, agent_id: str) -> Any:
        return SimpleNamespace(agent_id=agent_id, name="Dodaios")

    def config(self) -> Any:
        wake_word = SimpleNamespace(phrase="Hey Nova")
        return SimpleNamespace(trigger=SimpleNamespace(wake_word=wake_word))

    def chat_service(self) -> Any:
        return self._chat

    def task_services(self) -> tuple[Any, Any]:
        return None, None

    def display_name(self, agent: Any) -> str:
        return "Nova"

    async def post_chat_notice(self, agent: Any, payload: dict[str, Any]) -> None:
        await self._chat.post_notice(self._lead_session, payload)


@pytest.fixture
def chat(tmp_path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(service_mod, "resolve_runner", lambda *a, **kw: "brain")

    async def model(handle, prompt, *args, **kwargs) -> None:
        await handle.emit(make_event(
            "assistant_text", {"turn_id": handle.turn_id, "text": f"Answer to: {prompt}"},
        ))
        await handle.emit(make_event(
            "turn_finished", {"turn_id": handle.turn_id, "status": "done", "usage": {}},
        ))

    monkeypatch.setattr(service_mod, "run_brain_turn", model)
    store = AgentChatStore(tmp_path / "chat.db")
    lead = store.create_session(
        provider="openai", model="", effort="", surface="jarvis", cwd=str(tmp_path)
    ).session_id
    store.set_lead_session_id(lead)
    other = store.create_session(
        provider="openai", model="", effort="", surface="jarvis", cwd=str(tmp_path)
    ).session_id
    svc = AgentChatService(store)
    world = Society(svc, lead)
    monkeypatch.setattr(service, "_runtime", lambda: world)
    monkeypatch.setattr(prepare, "_runtime", lambda: world)
    rituals = RitualStore(":memory:")
    set_store(rituals)
    app = FastAPI()
    app.include_router(router)
    app.state.agent_chat = svc
    try:
        yield app, store, lead, other
    finally:
        set_store(None)
        rituals.close()
        prepare._runs.clear()
        prepare._tried_at.clear()


def _kinds(store: AgentChatStore, session_id: str) -> list[str]:
    return [event["kind"] for event in store.list_events(session_id)]


def test_the_phrase_starts_the_ritual_and_its_card_is_the_answer(chat) -> None:
    app, store, lead, _other = chat
    url = f"/api/agent-chat/sessions/{lead}/messages"
    ritual = asyncio.run(service.create(**MORNING))
    with TestClient(app) as client:
        sent = client.post(url, json={"text": "Good morning"})
    body = sent.json()
    assert sent.status_code == 202
    assert body == {"turn_id": "", "session_id": lead, "ritual": ritual.id}
    events = store.list_events(lead)
    # What was typed stands in the conversation, then the card. No turn ran.
    assert [event["kind"] for event in events] == ["user_message", "notice", "notice"]
    assert events[0]["payload"]["text"] == "Good morning"
    card = events[1]["payload"]
    assert card["kind"] == "society_result" and card["source"] == "ritual"
    assert card["via"] == "chat" and card["ritual_id"] == ritual.id
    # Nothing was gathered: it says more follows.
    assert card["pending"] is True
    # No scheduler is behind this society, so nothing can be gathered: the
    # second card says so at once instead of the first one waiting for good.
    late = events[2]["payload"]
    assert late["late"] is True and late["status"] == "failed"


def test_any_other_message_is_answered_as_a_turn(chat) -> None:
    app, store, lead, other = chat
    ritual = asyncio.run(service.create(**MORNING))
    with TestClient(app) as client:
        question = client.post(
            f"/api/agent-chat/sessions/{lead}/messages",
            json={"text": "Good morning, what is on today?"},
        )
        elsewhere = client.post(
            f"/api/agent-chat/sessions/{other}/messages", json={"text": "Good morning"}
        )
    assert question.status_code == 202 and question.json()["turn_id"]
    assert "ritual" not in question.json()
    # The phrase in another chat is a message for that chat.
    assert elsewhere.status_code == 202 and elsewhere.json()["turn_id"]
    assert "notice" not in _kinds(store, other)
    # Nothing started: the phrase keeps its start of the day.
    assert service.today_of(ritual.id) is None
