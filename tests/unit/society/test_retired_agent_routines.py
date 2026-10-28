"""A retired (archived) agent keeps no routine, webhook or trigger armed."""

from __future__ import annotations

from pathlib import Path

import pytest

from dodaios.core.bus import EventBus
from dodaios.society.routines import retire_agent_routines
from dodaios.tasks.scheduler import TaskScheduler
from dodaios.tasks.schema import (
    AgentAction,
    TaskSpec,
    TriggerAfterDelay,
    TriggerEvery,
    TriggerWebhook,
)
from dodaios.tasks.store import TaskStore


class _Runner:
    def __init__(self) -> None:
        self.ran: list[str] = []

    async def run(self, task_id: str, *_args, **_kwargs) -> None:
        self.ran.append(task_id)


@pytest.fixture
async def store(tmp_path: Path):
    s = TaskStore(tmp_path / "tasks.db")
    await s.init()
    try:
        yield s
    finally:
        await s.close()


def _spec(agent_id: str, trigger, title: str = "Brief") -> TaskSpec:
    return TaskSpec(
        title=f"[agent:{agent_id}] {title}",
        trigger=trigger,
        action=AgentAction(prompt="Do the work."),
        tags=("society", f"agent:{agent_id}"),
        created_by="society",
    )


async def test_retiring_pauses_recurring_and_webhook_and_cancels_one_shots(store) -> None:
    scheduler = TaskScheduler(store=store, bus=EventBus(), runner=_Runner())
    every = await scheduler.schedule(_spec("mailbox", TriggerEvery(interval_seconds=3600)))
    hook = await scheduler.schedule(_spec("mailbox", TriggerWebhook()))
    once = await scheduler.schedule(_spec("mailbox", TriggerAfterDelay(delay_seconds=600)))
    other = await scheduler.schedule(_spec("scout", TriggerEvery(interval_seconds=3600)))

    stopped = await retire_agent_routines(store, scheduler, "mailbox")

    assert stopped == 3
    assert (await store.get(every))["state"] == "paused"
    assert (await store.get(hook))["state"] == "paused"
    assert (await store.get(once))["state"] == "cancelled"
    # Another agent's routine is untouched.
    assert (await store.get(other))["state"] == "scheduled"
    # Nothing of the retired agent stays armed in the scheduler.
    assert {every, hook, once}.isdisjoint(scheduler._known)
    # Idempotent: a second retire finds nothing left to stop.
    assert await retire_agent_routines(store, scheduler, "mailbox") == 0


async def test_retiring_without_a_scheduler_writes_the_states(store) -> None:
    every = await store.insert(_spec("mailbox", TriggerEvery(interval_seconds=60)))
    once = await store.insert(_spec("mailbox", TriggerAfterDelay(delay_seconds=60)))
    assert await retire_agent_routines(store, None, "mailbox") == 2
    assert (await store.get(every))["state"] == "paused"
    assert (await store.get(once))["state"] == "cancelled"


async def test_scheduler_skips_a_routine_whose_owner_is_archived(store) -> None:
    runner = _Runner()
    scheduler = TaskScheduler(store=store, bus=EventBus(), runner=runner)
    retired = {"mailbox"}

    async def gate(tags: tuple[str, ...]) -> bool:
        return any(t == f"agent:{a}" for t in tags for a in retired)

    scheduler.attach_owner_gate(gate)
    every = await scheduler.schedule(_spec("mailbox", TriggerEvery(interval_seconds=3600)))
    live = await scheduler.schedule(_spec("scout", TriggerEvery(interval_seconds=3600)))

    await scheduler._safe_run(every)
    await scheduler._safe_run(live)

    assert runner.ran == [live]
    row = await store.get(every)
    assert row["state"] == "paused"
    assert row["last_error"] == "owner_archived"
    assert every not in scheduler._known
