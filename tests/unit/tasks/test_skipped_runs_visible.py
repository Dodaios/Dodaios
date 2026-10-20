"""A skipped unattended run is recorded as a skip, with a reason the UI can word.

Background work never bills a per-token key once a subscription is connected
(``dodaios.brain.background_policy``). When a scheduled, triggered or webhook
run is held back for that, the run history shows one ``skipped`` entry with a
stable reason code (not a "failed" run), the owner's chat gets a ``skipped``
notice with the same code, and a webhook delivery is settled as ``skipped``:
not left pending (that would retry every 2 s) and not replayed later.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import aiosqlite
import pytest

from dodaios.brain.background_policy import BackgroundDeferred
from dodaios.control.cancel import CancelToken
from dodaios.core.bus import EventBus
from dodaios.tasks.runner import TaskRunner, routine_skip_sentence
from dodaios.tasks.scheduler import TaskScheduler
from dodaios.tasks.schema import AgentAction, TaskSpec, TriggerEvery, TriggerWebhook
from dodaios.tasks.store import TaskStore

_KEY_SEAT = (
    "A subscription is connected, so this scheduled run did not bill the routine's "
    "API-key seat (gemini)."
)


@pytest.fixture
async def store(tmp_path: Path):
    s = TaskStore(tmp_path / "tasks.db")
    await s.init()
    try:
        yield s
    finally:
        await s.close()


def _events(row: dict[str, Any]) -> list[dict[str, Any]]:
    return [step["payload"] for step in row["steps"]]


async def _held_back(task_id: str, tags: tuple[str, ...], prompt: str, cancel: Any) -> str:
    raise BackgroundDeferred(_KEY_SEAT, code="api_key_seat", provider="gemini")


async def test_a_held_back_routine_run_is_one_skip_with_its_reason_code(
    store: TaskStore,
) -> None:
    delivered: list[tuple[tuple[str, ...], str, str, dict[str, str] | None]] = []

    async def sink(
        tags: tuple[str, ...], text: str, status: str, *, details: dict[str, str] | None = None
    ) -> None:
        delivered.append((tags, text, status, details))

    runner = TaskRunner(store, EventBus(), owned_agent_runner=_held_back, result_sink=sink)
    task_id = await store.insert(
        TaskSpec(
            title="[agent:Scout] Inbox sweep",
            trigger=TriggerEvery(interval_seconds=86400),
            action=AgentAction(prompt="Sort the inbox."),
            tags=("society", "agent:scout"),
        )
    )
    await asyncio.wait_for(runner.run(task_id, CancelToken()), timeout=2.0)

    row = await store.get(task_id)
    assert row is not None and row["state"] == "scheduled"
    events = _events(row)
    skipped = [e for e in events if e.get("event") == "skipped"]
    assert skipped == [
        {
            "event": "skipped",
            "reason": "waiting_capacity",
            "code": "api_key_seat",
            "provider": "gemini",
            "message": _KEY_SEAT,
        }
    ]
    # The skip ends the run: no second "error" entry reads as a failure.
    assert not any(e.get("event") == "error" for e in events)
    assert await store.last_log_event(task_id) == "skipped"
    assert delivered == [
        (
            ("society", "agent:scout"),
            routine_skip_sentence("[agent:Scout] Inbox sweep", _KEY_SEAT),
            "skipped",
            {"reason_code": "api_key_seat", "provider": "gemini", "routine": "Inbox sweep"},
        )
    ]
    assert delivered[0][1].startswith('The routine "Inbox sweep" was skipped: ')


async def test_a_capacity_wait_without_a_code_is_the_generic_skip(store: TaskStore) -> None:
    async def no_capacity(task_id: str, tags: tuple[str, ...], prompt: str, cancel: Any) -> str:
        raise BackgroundDeferred("No subscription or local model is available.")

    runner = TaskRunner(store, EventBus(), owned_agent_runner=no_capacity)
    task_id = await store.insert(
        TaskSpec(
            title="[agent:Scout] Digest",
            trigger=TriggerEvery(interval_seconds=86400),
            action=AgentAction(prompt="Summarise."),
            tags=("society", "agent:scout"),
        )
    )
    await asyncio.wait_for(runner.run(task_id, CancelToken()), timeout=2.0)
    row = await store.get(task_id)
    assert row is not None
    skipped = [e for e in _events(row) if e.get("event") == "skipped"]
    assert skipped and skipped[0]["code"] == "no_capacity" and skipped[0]["provider"] == ""


async def test_a_plain_failure_still_reads_as_failed(store: TaskStore) -> None:
    async def broken(task_id: str, tags: tuple[str, ...], prompt: str, cancel: Any) -> str:
        raise RuntimeError("the provider answered 500")

    statuses: list[str] = []

    async def sink(tags: tuple[str, ...], text: str, status: str) -> None:
        statuses.append(status)

    runner = TaskRunner(store, EventBus(), owned_agent_runner=broken, result_sink=sink)
    task_id = await store.insert(
        TaskSpec(
            title="[agent:Scout] Digest",
            trigger=TriggerEvery(interval_seconds=86400),
            action=AgentAction(prompt="Summarise."),
            tags=("society", "agent:scout"),
        )
    )
    await asyncio.wait_for(runner.run(task_id, CancelToken()), timeout=2.0)
    row = await store.get(task_id)
    assert row is not None
    assert not any(e.get("event") == "skipped" for e in _events(row))
    assert await store.last_log_event(task_id) == "error"
    assert statuses == ["failed"]


async def _delivery_status(store: TaskStore, task_id: str) -> list[str]:
    conn = store._require_conn()
    async with conn.execute(
        "SELECT status FROM task_hook_deliveries WHERE task_id=? ORDER BY received_ns", (task_id,)
    ) as cursor:
        return [str(row[0]) for row in await cursor.fetchall()]


async def test_a_held_back_webhook_delivery_is_settled_as_skipped_not_replayed(
    store: TaskStore,
) -> None:
    calls: list[str] = []

    async def held_back(task_id: str, tags: tuple[str, ...], prompt: str, cancel: Any) -> str:
        calls.append(task_id)
        return await _held_back(task_id, tags, prompt, cancel)

    bus = EventBus()
    runner = TaskRunner(store, bus, owned_agent_runner=held_back)
    scheduler = TaskScheduler(store, bus, runner)
    try:
        task_id = await scheduler.schedule(
            TaskSpec(
                title="[agent:Scout] On push",
                trigger=TriggerWebhook(),
                action=AgentAction(prompt="Summarise the push."),
                tags=("society", "agent:scout"),
            )
        )
        assert await scheduler.receive_hook(task_id, {"ref": "main"}, "d-1") == "queued"
        await scheduler._drain_hooks()
        await asyncio.gather(*list(scheduler._runner_tasks))

        assert await _delivery_status(store, task_id) == ["skipped"]
        assert await store.hooks.pending() == []  # nothing left to retry every 2 s
        row = await store.get(task_id)
        assert row is not None and row["state"] == "scheduled"  # the next delivery runs
        assert [e["code"] for e in _events(row) if e.get("event") == "skipped"] == [
            "api_key_seat"
        ]
        # A later drain does not replay the skipped delivery.
        await scheduler._drain_hooks()
        await asyncio.gather(*list(scheduler._runner_tasks))
        assert calls == [task_id]
    finally:
        await scheduler.shutdown()


async def test_an_old_deliveries_table_gains_the_skipped_status(tmp_path: Path) -> None:
    """A database created before ``skipped`` keeps its deliveries and counter."""
    path = tmp_path / "old.db"
    first = TaskStore(path)
    await first.init()
    task_id = await first.insert(
        TaskSpec(
            title="Hook",
            trigger=TriggerWebhook(),
            action=AgentAction(prompt="Go."),
        )
    )
    await first.close()
    async with aiosqlite.connect(path) as conn:
        await conn.executescript(
            """
            DROP TRIGGER count_task_hook_delivery;
            DROP TABLE task_hook_deliveries;
            CREATE TABLE task_hook_deliveries (
                task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                delivery_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                lineage_json TEXT NOT NULL DEFAULT '[]',
                received_ns INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending','running','done','failed','interrupted')),
                PRIMARY KEY(task_id, delivery_id)
            );
            """
        )
        await conn.execute(
            "INSERT INTO task_hook_deliveries(task_id,delivery_id,payload_json,received_ns,status)"
            " VALUES(?,?,?,?,?)",
            (task_id, "old-1", "{}", 1, "done"),
        )
        await conn.execute(
            "INSERT INTO task_hook_state(task_id,accepted_count,last_received_ns) VALUES(?,?,?)",
            (task_id, 1, 1),
        )
        await conn.commit()

    second = TaskStore(path)
    await second.init()
    try:
        await second.hooks.mark(task_id, "old-1", "skipped")
        assert await _delivery_status(second, task_id) == ["skipped"]
        spec = await second.get_spec(task_id)
        assert spec is not None
        assert await second.hooks.accept(task_id, "new-1", {}, spec.trigger) == "queued"
        assert (await second.hooks.counts(task_id))[0] == 2  # the counter trigger is back
    finally:
        await second.close()


async def test_an_unknown_delivery_status_is_refused(store: TaskStore) -> None:
    with pytest.raises(ValueError):
        await store.hooks.mark("t", "d", "lost")
