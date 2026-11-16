"""A private ritual store, and small stand-ins for the society and the lead's chat."""

from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest

from dodaios.agent_chat.service import SessionBusy
from dodaios.core.bus import EventBus
from dodaios.rituals import prepare, service
from dodaios.rituals.store import RitualStore, set_store
from dodaios.tasks.scheduler import TaskScheduler
from dodaios.tasks.store import TaskStore

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
        self.filed: list[dict[str, Any]] = []
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

    async def import_voice_turn(self, session_id: str, user_text: str, assistant_text: str) -> None:
        # What the person said or typed, filed without a turn for it.
        self.filed.append({"session_id": session_id, "text": user_text, "reply": assistant_text})

    async def send(self, session_id: str, text: str, **options: Any) -> str:
        if self.refusals:
            self.refusals -= 1
            raise SessionBusy(session_id)
        self.sent.append({"session_id": session_id, "text": text, **options})
        return f"turn-{len(self.sent)}"


class Dispatched:
    """Stands in for the task runner: remembers what the scheduler started, and how."""

    def __init__(self) -> None:
        self.ran: list[str] = []
        #: Whether each run was one the person asked for.
        self.by_user: list[bool] = []

    async def run(self, task_id: str, token: Any, *, trigger_event: Any = None) -> None:
        from dodaios.core.protocols import current_started_by_user

        self.ran.append(task_id)
        self.by_user.append(bool(current_started_by_user.get()))


class Society:
    """What the service asks of the society runtime."""

    def __init__(self) -> None:
        self.chat = Chat()
        self.notices: list[dict[str, Any]] = []
        self.roster = SimpleNamespace(get=self._lead)
        self.wake_phrase = WAKE_PHRASE
        #: The real task store and scheduler, when a test gathers ahead.
        self.task_store: Any = None
        self.scheduler: Any = None
        self.runner: Dispatched | None = None

    async def _lead(self, agent_id: str) -> Any:
        return SimpleNamespace(
            agent_id=agent_id, name="Dodaios", title="", description="", focus=(),
            provider="openai", model="m", effort="low", account_id="", tier="lead",
        )

    def task_services(self) -> tuple[Any, Any]:
        return self.task_store, self.scheduler

    def cards(self) -> list[dict[str, Any]]:
        return [n for n in self.notices if n.get("source") == "ritual"]

    def start_cards(self) -> list[dict[str, Any]]:
        """The cards that answer a start, without the second ones that follow it.

        Without a scheduler (this world's default) nothing can be gathered, so
        a start that waits for its ``ahead`` steps hears that in a second card.
        """
        return [n for n in self.cards() if not n.get("late")]

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


async def settle(world: Any = None) -> None:
    """Wait for everything a start or a run left under way.

    With ``world``, also for the runs its scheduler handed to the task runner.
    """
    scheduler = getattr(world, "scheduler", None)
    for _ in range(3):
        await prepare.drain()
        await service.drain()
        handed = list(getattr(scheduler, "_runner_tasks", ()) or ())
        if handed:
            await asyncio.gather(*handed, return_exceptions=True)


@pytest.fixture
async def society(ritual_store, monkeypatch: pytest.MonkeyPatch):
    world = Society()
    monkeypatch.setattr(service, "_runtime", lambda: world)
    monkeypatch.setattr(prepare, "_runtime", lambda: world)
    monkeypatch.setattr(service, "_POLL_S", 0.01)
    # A test machine is awake; the real answer is the system's.
    monkeypatch.setattr(prepare, "fully_awake", lambda: True)
    try:
        yield world
    finally:
        await settle()
        prepare._runs.clear()
        prepare._tried_at.clear()
        prepare._starting.clear()


@pytest.fixture
async def scheduled(society, tmp_path, monkeypatch: pytest.MonkeyPatch):
    """The society with the real task store and scheduler behind it."""
    task_store = TaskStore(tmp_path / "tasks.db")
    await task_store.init()
    scheduler = TaskScheduler(store=task_store, bus=EventBus())
    runner = Dispatched()
    scheduler.attach_runner(runner)
    society.task_store, society.scheduler, society.runner = task_store, scheduler, runner

    async def no_subscription(_cfg: Any) -> None:
        return None

    # No subscription seat on this box: the routine stays on the lead's own seat.
    monkeypatch.setattr("dodaios.society.routine_runner._subscription_seat", no_subscription)
    try:
        yield society
    finally:
        await settle(society)
        await scheduler.shutdown()
        await task_store.close()
