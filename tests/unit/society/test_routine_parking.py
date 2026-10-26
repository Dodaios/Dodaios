"""Away-parking pauses only routines whose results nobody opens, and unparks them."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dodaios.core.protocols import started_by_user
from dodaios.society import routine_parking
from dodaios.society.roster import Roster
from dodaios.society.routine_parking import (
    DAY_MS,
    RoutineActivity,
    RoutineParked,
    apply_choice,
    load_state,
    mark_seen,
    maybe_park,
    parking_candidates,
    save_days,
)
from dodaios.society.routines import build_task_spec
from dodaios.society.store import SocietyStore
from dodaios.tasks.store import TaskStore

NOW = 1_800_000_000_000


def _activity(task_id: str = "a", **overrides: Any) -> RoutineActivity:
    values: dict[str, Any] = {
        "task_id": task_id,
        "state": "scheduled",
        "trigger_type": "calendar",
        "result_ms": tuple(NOW - d * DAY_MS for d in (6, 4, 1)),
    }
    values.update(overrides)
    return RoutineActivity(**values)


# ── the pure decision ────────────────────────────────────────────────────────


def test_unread_results_over_the_window_park_the_routine() -> None:
    chosen, unread = parking_candidates([_activity()], seen_ms=NOW - 8 * DAY_MS, now_ms=NOW, days=7)
    assert chosen == ["a"] and unread == 3


def test_a_recent_look_keeps_routines_running() -> None:
    assert parking_candidates([_activity()], seen_ms=NOW - 2 * DAY_MS, now_ms=NOW, days=7) == (
        [],
        0,
    )


def test_too_few_unread_results_is_not_wasted_spend() -> None:
    item = _activity(result_ms=(NOW - DAY_MS,))
    assert parking_candidates([item], seen_ms=NOW - 9 * DAY_MS, now_ms=NOW, days=7)[0] == []


def test_routines_that_stopped_producing_are_left_alone() -> None:
    item = _activity(result_ms=tuple(NOW - d * DAY_MS for d in (20, 15, 9)))
    assert parking_candidates([item], seen_ms=NOW - 30 * DAY_MS, now_ms=NOW, days=7)[0] == []


@pytest.mark.parametrize(
    "overrides",
    [
        {"trigger_type": "webhook"},
        {"trigger_type": "source"},
        {"trigger_type": "on_event"},
        {"last_manual_ms": NOW - DAY_MS},
        {"autonomous": True},
        {"announces": True},
        {"state": "paused"},
    ],
)
def test_user_facing_and_already_quiet_routines_are_never_parked(
    overrides: dict[str, Any],
) -> None:
    chosen, _ = parking_candidates(
        [_activity(**overrides)], seen_ms=NOW - 8 * DAY_MS, now_ms=NOW, days=7
    )
    assert chosen == []


def test_parking_off_or_opted_out_changes_nothing() -> None:
    seen = NOW - 30 * DAY_MS
    assert parking_candidates([_activity()], seen_ms=seen, now_ms=NOW, days=0)[0] == []
    assert (
        parking_candidates([_activity()], seen_ms=seen, now_ms=NOW, days=7, never_ask=True)[0] == []
    )


def test_without_any_look_the_oldest_unread_result_starts_the_window() -> None:
    young = _activity(result_ms=tuple(NOW - d * DAY_MS for d in (3, 2, 1)))
    assert parking_candidates([young], seen_ms=0, now_ms=NOW, days=7)[0] == []
    old = _activity(result_ms=tuple(NOW - d * DAY_MS for d in (8, 5, 1)))
    assert parking_candidates([old], seen_ms=0, now_ms=NOW, days=7)[0] == ["a"]


# ── the run-time check against real stores ───────────────────────────────────


class _Scheduler:
    def __init__(self, store: TaskStore) -> None:
        self.store = store

    async def pause(self, task_id: str) -> None:
        row = await self.store.get(task_id)
        if row and row["state"] == "running":
            raise RuntimeError("task is running")
        await self.store.update_state(task_id, "paused")

    async def resume(self, task_id: str) -> None:
        await self.store.update_state(task_id, "scheduled")


@pytest.fixture
async def world(tmp_path: Path):
    society = SocietyStore(tmp_path / "society.db")
    await society.open()
    tasks = TaskStore(tmp_path / "tasks.db")
    await tasks.init()
    agent, _ = await Roster(society).create(name="Scout", title="Researcher")
    scheduler = _Scheduler(tasks)
    chat_events: list[dict[str, Any]] = []
    chat = SimpleNamespace(
        store=SimpleNamespace(list_events=lambda session_id, tail=None: list(chat_events))
    )
    runtime = SimpleNamespace(
        store=society,
        task_services=lambda: (tasks, scheduler),
        chat_service=lambda: chat,
    )
    try:
        yield SimpleNamespace(
            society=society,
            tasks=tasks,
            agent=agent,
            scheduler=scheduler,
            runtime=runtime,
            chat_events=chat_events,
        )
    finally:
        await tasks.close()
        await society.close()


async def _routine(
    world: Any, schedule: dict[str, Any], *, results: int = 3, manual: bool = False
) -> str:
    spec = build_task_spec(world.agent, title="Digest", prompt="Summarize.", schedule=schedule)
    task_id = await world.tasks.insert(spec)
    for _ in range(results):
        if manual:
            await world.tasks.append_step(task_id, "log", {"event": "run_now"})
        await world.tasks.append_step(task_id, "log", {"event": "run_started"})
        await world.tasks.append_step(task_id, "log", {"event": "run_completed"})
    return task_id


def _now() -> int:
    return int(time.time() * 1000)


async def _settle() -> None:
    for task in list(routine_parking._PENDING.values()):
        await asyncio.wait_for(task, timeout=5)


async def test_a_firing_routine_parks_the_agents_unread_routines(world: Any) -> None:
    daily = {"kind": "calendar", "local_time": "08:00", "timezone": "Europe/Berlin"}
    firing = await _routine(world, daily)
    sibling = await _routine(world, {"kind": "every", "interval_seconds": 3600})
    hook = await _routine(world, {"kind": "webhook"})
    await mark_seen(world.society, world.agent.agent_id, now_ms=_now() - 8 * DAY_MS)
    await world.tasks.update_state(firing, "running")

    with pytest.raises(RoutineParked) as caught:
        await maybe_park(world.runtime, world.agent, firing, now_ms=_now() + 1000)
    assert caught.value.code == "away_parked"

    assert (await world.tasks.get(sibling))["state"] == "paused"
    assert (await world.tasks.get(hook))["state"] == "scheduled"
    # The firing routine pauses once its skipped run has settled.
    await world.tasks.update_state(firing, "scheduled")
    await _settle()
    assert (await world.tasks.get(firing))["state"] == "paused"
    steps = [s["payload"] for s in (await world.tasks.get(sibling))["steps"]]
    assert {"event": "parked", "reason": "away", "days": 7, "unread": 6} in steps

    state = await load_state(world.society, world.agent.agent_id)
    assert state.banner and sorted(state.parked_ids) == sorted([firing, sibling])

    # Keep running: both come back, a new away period starts, the banner closes.
    await apply_choice(
        world.society, world.tasks, world.scheduler, world.agent.agent_id, "keep_running"
    )
    assert (await world.tasks.get(firing))["state"] == "scheduled"
    assert (await world.tasks.get(sibling))["state"] == "scheduled"
    after = await load_state(world.society, world.agent.agent_id)
    assert not after.banner and after.parked_ids == [] and after.seen_ms > 0


async def test_a_run_the_person_started_is_never_parked(world: Any) -> None:
    task = await _routine(world, {"kind": "every", "interval_seconds": 3600})
    await mark_seen(world.society, world.agent.agent_id, now_ms=_now() - 8 * DAY_MS)
    with started_by_user():
        await maybe_park(world.runtime, world.agent, task, now_ms=_now() + 1000)
    assert (await world.tasks.get(task))["state"] == "scheduled"


async def test_a_routine_the_person_just_ran_by_hand_keeps_running(world: Any) -> None:
    task = await _routine(world, {"kind": "every", "interval_seconds": 3600})
    await world.tasks.append_step(task, "log", {"event": "run_now"})
    await world.tasks.append_step(task, "log", {"event": "run_started"})
    await world.tasks.append_step(task, "log", {"event": "run_completed"})
    await mark_seen(world.society, world.agent.agent_id, now_ms=_now() - 8 * DAY_MS)
    await maybe_park(world.runtime, world.agent, task, now_ms=_now() + 1000)
    assert (await world.tasks.get(task))["state"] == "scheduled"


async def test_writing_to_the_agent_counts_as_looking(world: Any) -> None:
    task = await _routine(world, {"kind": "every", "interval_seconds": 3600})
    await mark_seen(world.society, world.agent.agent_id, now_ms=_now() - 8 * DAY_MS)
    # A teammate's message does not count; the person's own does.
    world.chat_events.append(
        {"kind": "user_message", "ts_ms": _now(), "payload": {"text": "hi", "author": {"id": "x"}}}
    )
    with pytest.raises(RoutineParked):
        await maybe_park(world.runtime, world.agent, task, now_ms=_now() + 1000)
    await apply_choice(
        world.society, world.tasks, world.scheduler, world.agent.agent_id, "keep_running"
    )
    state = await load_state(world.society, world.agent.agent_id)
    state.seen_ms = _now() - 8 * DAY_MS
    await routine_parking.save_state(world.society, world.agent.agent_id, state)
    world.chat_events.append({"kind": "user_message", "ts_ms": _now(), "payload": {"text": "hi"}})
    await maybe_park(world.runtime, world.agent, task, now_ms=_now() + 1000)
    assert (await world.tasks.get(task))["state"] == "scheduled"


async def test_never_ask_and_the_off_setting_stop_parking(world: Any) -> None:
    task = await _routine(world, {"kind": "every", "interval_seconds": 3600})
    await apply_choice(
        world.society, world.tasks, world.scheduler, world.agent.agent_id, "never_ask"
    )
    state = await load_state(world.society, world.agent.agent_id)
    state.seen_ms = _now() - 8 * DAY_MS
    await routine_parking.save_state(world.society, world.agent.agent_id, state)
    await maybe_park(world.runtime, world.agent, task, now_ms=_now() + 1000)
    assert (await world.tasks.get(task))["state"] == "scheduled"

    await apply_choice(
        world.society, world.tasks, world.scheduler, world.agent.agent_id, "ask_again"
    )
    await save_days(world.society, 0)
    await maybe_park(world.runtime, world.agent, task, now_ms=_now() + 1000)
    assert (await world.tasks.get(task))["state"] == "scheduled"


async def test_keep_paused_closes_the_banner_and_one_park_per_away_period(world: Any) -> None:
    task = await _routine(world, {"kind": "every", "interval_seconds": 3600})
    other = await _routine(world, {"kind": "every", "interval_seconds": 7200})
    await mark_seen(world.society, world.agent.agent_id, now_ms=_now() - 8 * DAY_MS)
    await world.tasks.update_state(task, "running")
    with pytest.raises(RoutineParked):
        await maybe_park(world.runtime, world.agent, task, now_ms=_now() + 1000)
    await world.tasks.update_state(task, "scheduled")
    await _settle()
    # The person resumes one routine by hand; the open banner prevents a re-park.
    await world.scheduler.resume(other)
    await maybe_park(world.runtime, world.agent, other, now_ms=_now() + 2000)
    assert (await world.tasks.get(other))["state"] == "scheduled"

    state = await apply_choice(
        world.society, world.tasks, world.scheduler, world.agent.agent_id, "keep_paused"
    )
    assert not state.banner
    assert (await world.tasks.get(task))["state"] == "paused"


async def test_a_broken_check_never_stops_the_run(world: Any) -> None:
    async def broken(*_: Any, **__: Any) -> int:
        raise RuntimeError("store gone")

    world.runtime.store = SimpleNamespace(get_meta=broken)
    await maybe_park(world.runtime, world.agent, "missing")


async def test_an_unknown_choice_is_refused(world: Any) -> None:
    with pytest.raises(ValueError):
        await apply_choice(
            world.society, world.tasks, world.scheduler, world.agent.agent_id, "explode"
        )
