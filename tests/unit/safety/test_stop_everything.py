"""Stop everything: one off-switch, bounded, kept until the owner resumes."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

import pytest

from dodaios.core.bus import EventBus
from dodaios.core.events import KillRequested
from dodaios.orchestrator import jobs
from dodaios.safety.stop_everything import (
    is_resume_everything,
    is_stop_everything,
    resume_everything,
    stop_everything,
)
from dodaios.safety.stop_hold import stop_holds
from dodaios.tasks.runner import TaskRunner
from dodaios.tasks.scheduler import TaskScheduler, TaskStateConflict
from dodaios.tasks.schema import AgentAction, TaskSpec, TriggerAfterDelay, TriggerEvery
from dodaios.tasks.store import TaskStore


class _Chat:
    """Chat service double: turns that stop when cancelled, a bit slowly."""

    def __init__(self, sessions: list[str], stop_after_s: float = 0.05) -> None:
        self.running = list(sessions)
        self.cancelled: list[str] = []
        self._delay = stop_after_s
        self._send_queues: dict[str, Any] = {}

    def running_session_ids(self) -> list[str]:
        return list(self.running)

    async def cancel(self, sid: str) -> bool:
        await asyncio.sleep(self._delay)
        self.cancelled.append(sid)
        self.running.remove(sid)
        return True


class _Brain:
    async def run_task(self, *, prompt: str, **_: Any) -> str:
        return "done"


@pytest.fixture(autouse=True)
def _ledger():
    ledger = jobs.JobLedger(":memory:")
    jobs.set_ledger(ledger)
    yield ledger
    jobs.set_ledger(None)
    ledger.close()


@pytest.fixture
async def store(tmp_path: Path):
    s = TaskStore(tmp_path / "t.db")
    await s.init()
    try:
        yield s
    finally:
        await s.close()


def _every(prompt: str = "brief") -> TaskSpec:
    return TaskSpec(
        title="recurring",
        trigger=TriggerEvery(interval_seconds=3600.0),
        action=AgentAction(prompt=prompt),
    )


def _once() -> TaskSpec:
    return TaskSpec(
        title="once",
        trigger=TriggerAfterDelay(delay_seconds=3600.0),
        action=AgentAction(prompt="x"),
    )


async def test_stop_halts_turns_routines_and_jobs_within_a_bound(store: TaskStore) -> None:
    bus = EventBus()
    kills: list[KillRequested] = []

    async def on_kill(event: KillRequested) -> None:
        kills.append(event)

    bus.subscribe(KillRequested, on_kill)
    scheduler = TaskScheduler(store=store, bus=bus, runner=TaskRunner(store=store, bus=bus, agent_brain=_Brain()))
    recurring = await scheduler.schedule(_every())
    one_shot = await scheduler.schedule(_once())
    ledger = jobs.get_ledger()
    ledger.create("mission", job_id="j1", title="m", state="running")
    ledger.create("artifact", job_id="j2", title="a", state="queued")
    chat = _Chat([f"s{i}" for i in range(6)], stop_after_s=0.2)

    started = time.monotonic()
    report = await stop_everything(
        chat_service=chat, scheduler=scheduler, ledger=ledger, bus=bus,
        reason="owner said stop", source="telegram", deadline_s=5.0,
    )
    elapsed = time.monotonic() - started

    # Measure: the six turns stopped concurrently, not one after another.
    assert elapsed < 1.0, f"stop took {elapsed:.2f}s"
    assert report.elapsed_ms < 1000 and report.errors == []
    assert chat.running == [] and len(chat.cancelled) == 6
    assert (report.turns, report.routines, report.jobs) == (6, 2, 2)
    for tid in (recurring, one_shot):
        row = await store.get(tid)
        assert row is not None and row["state"] == "paused"
    assert {j.state for j in ledger.recent()} == {"cancelled"}
    assert [k.source for k in kills] == ["telegram"]
    hold = stop_holds().get("everything")
    assert hold is not None and hold.source == "telegram" and hold.reason == "owner said stop"


async def test_a_stuck_step_cannot_hold_the_stop_past_the_deadline(store: TaskStore) -> None:
    class _Stuck(_Chat):
        async def cancel(self, sid: str) -> bool:
            await asyncio.sleep(60)
            return True

    report = await stop_everything(
        chat_service=_Stuck(["s1"]), ledger=jobs.get_ledger(), deadline_s=0.3, source="desk"
    )
    assert report.elapsed_ms < 2000
    assert any(e.startswith("turns") for e in report.errors)
    assert stop_holds().get("everything") is not None, "the hold is written before anything else"


async def test_held_routines_never_run_and_stay_paused_after_a_restart(
    store: TaskStore, tmp_path: Path
) -> None:
    bus = EventBus()
    ran: list[str] = []

    class _Runner:
        async def run(self, task_id: str, *_a: Any, **_k: Any) -> None:
            ran.append(task_id)

    scheduler = TaskScheduler(store=store, bus=bus, runner=_Runner())
    tid = await scheduler.schedule(_every())
    await stop_everything(scheduler=scheduler, ledger=jobs.get_ledger(), source="desk")

    # A new process (restart): the hold file is read again, hydration skips paused rows.
    again = TaskScheduler(store=store, bus=bus, runner=_Runner())
    await again.hydrate()
    assert tid not in {t for _, t in again._heap}
    # Every automatic way to start it is refused.
    await again._safe_run(tid)
    assert ran == []
    with pytest.raises(TaskStateConflict):
        await again.resume(tid)  # an automatic resumer (parking, self-build)
    with pytest.raises(TaskStateConflict):
        await again.resume(tid, owner=True)  # even the owner's single resume: the stop is global
    assert (await store.get(tid))["state"] == "paused"


async def test_resume_brings_back_only_what_the_stop_paused(store: TaskStore) -> None:
    bus = EventBus()
    scheduler = TaskScheduler(store=store, bus=bus, runner=TaskRunner(store=store, bus=bus, agent_brain=_Brain()))
    stopped_by_all = await scheduler.schedule(_every("a"))
    own_pause = await scheduler.schedule(_every("b"))
    await scheduler.pause(own_pause, owner_reason="Paused by the owner")

    await stop_everything(scheduler=scheduler, ledger=jobs.get_ledger(), source="desk")
    report = await resume_everything(scheduler=scheduler, source="desk")

    assert report.was_held and report.routines == 1
    assert (await store.get(stopped_by_all))["state"] == "scheduled"
    assert (await store.get(own_pause))["state"] == "paused", "the owner's own pause stays"
    assert stop_holds().get("everything") is None
    again = await resume_everything(scheduler=scheduler)
    assert not again.was_held


async def test_an_owner_pause_on_one_routine_holds_against_automatic_resume(
    store: TaskStore,
) -> None:
    scheduler = TaskScheduler(store=store, bus=EventBus(), runner=None)
    tid = await scheduler.schedule(_every())
    await scheduler.pause(tid, owner_reason="Paused by the owner")
    assert stop_holds().get("routine", tid) is not None
    with pytest.raises(TaskStateConflict):
        await scheduler.resume(tid)  # automatic feedback never resumes it
    await scheduler.resume(tid, owner=True)
    assert (await store.get(tid))["state"] == "scheduled"
    assert stop_holds().get("routine", tid) is None


async def test_a_running_routine_is_interrupted_and_parked_as_paused(store: TaskStore) -> None:
    bus = EventBus()
    started = asyncio.Event()

    class _Slow:
        async def run(self, task_id: str, token: Any, **_k: Any) -> None:
            await store.update_state(task_id, "running")
            started.set()
            await token.wait_until_cancelled()
            await store.update_state(task_id, "cancelled", error="owner_stop")

    scheduler = TaskScheduler(store=store, bus=bus, runner=_Slow())
    tid = await scheduler.schedule(_every())
    task = asyncio.create_task(scheduler._safe_run(tid))
    await started.wait()
    report = await stop_everything(scheduler=scheduler, ledger=jobs.get_ledger(), source="desk")
    await asyncio.wait_for(task, timeout=2.0)
    assert report.routines == 1
    assert (await store.get(tid))["state"] == "paused", "resumable, not ended as cancelled"


def test_the_stop_and_resume_words_are_whole_messages_only() -> None:
    words = ("stop", "Stop everything!", "STOPP", "alles stoppen", "para tudo", "alto")  # i18n-allow
    for word in words:
        assert is_stop_everything(word), word
    for sentence in ("please stop the music", "stop by the shop", "don't stop", "stoppen"):
        assert not is_stop_everything(sentence), sentence
    assert is_resume_everything("Resume") and is_resume_everything("resume everything")
    assert not is_resume_everything("resume the music")


async def test_one_written_confirmation_in_the_owners_language() -> None:
    report = await stop_everything(ledger=jobs.get_ledger(), source="telegram")
    assert "Stopped." in report.message("en")
    assert report.message("de").startswith("Gestoppt.")  # i18n-allow
    again = await stop_everything(ledger=jobs.get_ledger(), source="telegram")
    assert again.already_held and "already stopped" in again.message("en")
    assert "not stopped" not in (await resume_everything()).message("en")
    assert "nothing to resume" in (await resume_everything()).message("en")
