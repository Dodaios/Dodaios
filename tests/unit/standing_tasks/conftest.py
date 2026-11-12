"""A private standing-task store, the real task store and scheduler, and a small society."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from dodaios.core.bus import EventBus
from dodaios.standing_tasks import service
from dodaios.standing_tasks.store import StandingStore, set_store
from dodaios.tasks.scheduler import TaskScheduler
from dodaios.tasks.store import TaskStore


class Roster:
    async def get(self, agent_id: str) -> Any:
        return SimpleNamespace(
            agent_id=agent_id, name="Dodaios", title="", description="", focus=(),
            provider="openai", model="m", effort="low", account_id="", tier="lead",
        )


class Dispatched:
    """Stands in for the task runner: remembers what the scheduler started."""

    def __init__(self) -> None:
        self.ran: list[str] = []

    async def run(self, task_id: str, token: Any, *, trigger_event: Any = None) -> None:
        self.ran.append(task_id)


class Society:
    """What the service asks of the society runtime, with the real scheduler behind it."""

    def __init__(self, task_store: TaskStore, scheduler: TaskScheduler) -> None:
        self.task_store = task_store
        self.scheduler = scheduler
        self.roster = Roster()
        self.notices: list[dict[str, Any]] = []
        self.halted = False
        #: Chat sessions by id, as the chat store would return them.
        self.sessions: dict[str, Any] = {}
        self.store = SimpleNamespace(kill_switch=self._kill_switch)
        self.up = True

    async def _kill_switch(self) -> bool:
        return self.halted

    def task_services(self) -> tuple[Any, Any]:
        return (self.task_store, self.scheduler) if self.up else (None, None)

    def config(self) -> Any:
        return None

    def chat_service(self) -> Any:
        return SimpleNamespace(store=SimpleNamespace(get_session=self.sessions.get))

    async def post_chat_notice(self, agent: Any, payload: dict[str, Any]) -> None:
        self.notices.append(payload)

    def kinds(self) -> list[str]:
        return [str(n.get("kind")) for n in self.notices]


@pytest.fixture
def standing_store():
    store = StandingStore(":memory:")
    set_store(store)
    try:
        yield store
    finally:
        set_store(None)
        store.close()


@pytest.fixture
async def society(standing_store, tmp_path, monkeypatch: pytest.MonkeyPatch):
    task_store = TaskStore(tmp_path / "tasks.db")
    await task_store.init()
    scheduler = TaskScheduler(store=task_store, bus=EventBus())
    scheduler.attach_runner(Dispatched())
    world = Society(task_store, scheduler)
    monkeypatch.setattr(service, "_runtime", lambda: world)
    # The upkeep after a run waits for the task runner's last writes; not here.
    monkeypatch.setattr(service, "_GRACE_S", 0.0)
    monkeypatch.setattr(service, "_POLL_S", 0.01)
    monkeypatch.setattr(service, "_UNWIND_S", 0.0)

    async def no_subscription(_cfg: Any) -> None:
        return None

    # No subscription seat on this box: the routine stays on the lead's own seat.
    monkeypatch.setattr("dodaios.society.routine_runner._subscription_seat", no_subscription)
    try:
        yield world
    finally:
        await service.drain()
        service._started.clear()
        await scheduler.shutdown()
        await task_store.close()


async def routine_row(world: Society, task_id: str) -> dict[str, Any] | None:
    return await world.task_store.get(task_id)


async def routine_spec(world: Society, task_id: str) -> Any:
    return await world.task_store.get_spec(task_id)
