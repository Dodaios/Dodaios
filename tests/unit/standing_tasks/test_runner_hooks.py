"""A standing task's run through the real routine runner, chat service and society.

The run gets the task's work order, a chat in the mode its level allows, and
its own run log; what it wrote for the owner lands in the conversation.
"""

from __future__ import annotations

import asyncio

import pytest

from dodaios.agent_chat.lead import lead_session
from dodaios.agent_chat.proactive_checks import NOTHING
from dodaios.brain.background_policy import BackgroundDeferred
from dodaios.core.bus import EventBus
from dodaios.society import routine_runner
from dodaios.society.roster import LEAD_AGENT_ID
from dodaios.society.routine_runner import run_owned_routine
from dodaios.standing_tasks import service
from dodaios.standing_tasks.store import StandingStore, set_store
from dodaios.tasks.scheduler import TaskScheduler
from dodaios.tasks.store import TaskStore
from tests.contract.test_society_continuity import world as world  # noqa: F401

ADS = {"title": "Meta ads campaign", "goal": "Keep cost per lead under 12 EUR."}


@pytest.fixture
async def lead_world(world, tmp_path, monkeypatch):  # noqa: F811
    runtime, svc, _, brain = world
    tasks = TaskStore(tmp_path / "tasks.db")
    await tasks.init()
    scheduler = TaskScheduler(store=tasks, bus=EventBus())
    runtime.task_services = lambda: (tasks, scheduler)
    # The lead runs on a named seat here, like the mailbox agent of ``world``.
    await runtime.roster.update(LEAD_AGENT_ID, {"provider": "openai"})
    conversation = lead_session(svc)
    assert conversation is not None
    standing = StandingStore(":memory:")
    set_store(standing)
    monkeypatch.setattr(service, "_GRACE_S", 0.0)
    monkeypatch.setattr(service, "_POLL_S", 0.01)
    try:
        yield runtime, svc, tasks, conversation, brain
    finally:
        await service.drain()
        service._started.clear()
        set_store(None)
        standing.close()
        await scheduler.shutdown()
        await tasks.close()


def _notices(svc, session_id: str) -> list[dict]:
    return [e["payload"] for e in svc.store.list_events(session_id) if e["kind"] == "notice"]


async def _run(runtime, tasks, task) -> str | None:
    spec = await tasks.get_spec(task.task_id)
    return await run_owned_routine(runtime, task.task_id, spec.tags, spec.action.prompt)


async def _run_chat(svc, tasks, task):
    row = await tasks.get(task.task_id)
    links = [
        step["payload"]["session_id"]
        for step in row["steps"]
        if step["payload"].get("event") == "routine_chat"
    ]
    return svc.store.get_session(links[-1]) if links else None


async def test_a_run_gets_the_work_order_an_asking_chat_and_its_result_reaches_the_owner(
    lead_world,
) -> None:
    runtime, svc, tasks, conversation, brain = lead_world
    task = await service.take_on(**ADS, origin_session=conversation.session_id)
    brain.reply = "CPL is at 14 EUR, above your 12 EUR. I drafted two new ads for you."
    answer = await _run(runtime, tasks, task)
    assert answer == brain.reply
    prompt = brain.calls[-1][0]
    assert 'This is your standing task "Meta ads campaign"' in prompt
    assert "Goal:\nKeep cost per lead under 12 EUR." in prompt and "Level: prepare." in prompt
    chat = await _run_chat(svc, tasks, task)
    assert chat.permission_mode == "ask", "a prepare run never gets a bypass chat"
    # The run did not report through the tool, so a run is written for it.
    runs = await service.runs_of(task.id)
    assert [(r.outcome, r.session_id) for r in runs] == [("reported", chat.session_id)]
    assert runs[0].summary == brain.reply
    # Quiet routine: no start card. The answer itself is posted, labelled with the task.
    posted = _notices(svc, conversation.session_id)
    assert [n["kind"] for n in posted] == ["society_result"]
    assert posted[0]["text"] == brain.reply and posted[0]["source"] == "routine"
    assert posted[0]["standing_id"] == task.id
    assert posted[0]["standing_title"] == "Meta ads campaign"
    assert posted[0]["task_id"] == task.task_id and posted[0]["session_id"] == chat.session_id


async def test_a_run_with_nothing_to_say_is_a_quiet_line_in_the_log_and_posts_nothing(
    lead_world,
) -> None:
    runtime, svc, tasks, conversation, brain = lead_world
    task = await service.take_on(**ADS, autonomy="watch")
    brain.reply = NOTHING
    await _run(runtime, tasks, task)
    assert [r.outcome for r in await service.runs_of(task.id)] == ["quiet"]
    assert _notices(svc, conversation.session_id) == []
    assert (await _run_chat(svc, tasks, task)).permission_mode == "ask"


async def test_a_run_that_reported_is_not_logged_twice(lead_world, monkeypatch) -> None:
    runtime, svc, tasks, conversation, brain = lead_world
    task = await service.take_on(**ADS, interval_min=180)
    brain.reply = "I prepared the weekly numbers."
    generate = brain.generate

    async def reporting(text: str, **kwargs):
        # What the standing_task tool does when the model calls it in the run.
        await service.report(
            task.id, outcome="prepared", summary="Weekly numbers are ready.",
            notes="Week 46: CPL 11 EUR.", next_check_min=60,
        )
        return await generate(text, **kwargs)

    monkeypatch.setattr(brain, "generate", reporting)
    await _run(runtime, tasks, task)
    seen = await service.get_task(task.id)
    assert seen.runs == 1 and seen.last_outcome == "prepared"
    assert seen.notes == "Week 46: CPL 11 EUR." and seen.interval_min == 60
    assert [r.outcome for r in await service.runs_of(task.id)] == ["prepared"]
    # The routine follows the new pace once the run is over.
    await service.drain()
    assert (await tasks.get_spec(task.task_id)).trigger.interval_seconds == 3600
    # The next run reads the notes and the log.
    await _run(runtime, tasks, task)
    assert "Your notes from last time:\nWeek 46: CPL 11 EUR." in brain.calls[-1][0]
    assert "prepared: Weekly numbers are ready." in brain.calls[-1][0]


async def test_an_act_run_gets_at_most_the_mode_of_the_chat_it_was_accepted_in(
    lead_world,
) -> None:
    runtime, svc, tasks, conversation, brain = lead_world
    limits = {"autonomy": "act", "limits": "Pause ad sets with CPL over 20 EUR."}
    here = {"origin_session": conversation.session_id}
    svc.store.update_session(conversation.session_id, permission_mode="bypass")
    free = await service.take_on(title="Ads", goal="g", **limits, **here)
    svc.store.update_session(conversation.session_id, permission_mode="ask")
    held = await service.take_on(title="Shop", goal="g", **limits, **here)
    svc.store.update_session(conversation.session_id, permission_mode="bypass")
    await _run(runtime, tasks, held)
    assert (await _run_chat(svc, tasks, held)).permission_mode == "ask"
    assert "Pause ad sets with CPL over 20 EUR." in brain.calls[-1][0]
    await _run(runtime, tasks, free)
    assert (await _run_chat(svc, tasks, free)).permission_mode == "bypass"
    # The owner narrows the chat: the task's runs follow.
    svc.store.update_session(conversation.session_id, permission_mode="ask")
    await _run(runtime, tasks, free)
    assert (await _run_chat(svc, tasks, free)).permission_mode == "ask"


async def test_a_failed_run_is_logged_and_three_of_them_pause_the_task(lead_world) -> None:
    runtime, svc, tasks, conversation, brain = lead_world
    task = await service.take_on(**ADS)
    brain.fail = RuntimeError("provider exploded")
    for _ in range(3):
        with pytest.raises(RuntimeError, match="The routine chat failed"):
            await _run(runtime, tasks, task)
    runs = await service.runs_of(task.id)
    assert [r.outcome for r in runs] == ["failed"] * 3 and runs[0].summary
    paused = await service.get_task(task.id)
    assert paused.state == "paused"
    await service.drain()
    assert (await tasks.get(task.task_id))["state"] == "paused"
    kinds = [n["kind"] for n in _notices(svc, conversation.session_id)]
    assert kinds == ["standing_paused"]
    # A paused task's routine starts no model call any more.
    calls = len(brain.calls)
    assert await _run(runtime, tasks, task) == NOTHING and len(brain.calls) == calls


async def test_a_run_the_billing_rule_holds_back_is_a_skipped_line_and_opens_no_chat(
    lead_world, monkeypatch
) -> None:
    runtime, svc, tasks, conversation, brain = lead_world
    task = await service.take_on(**ADS)

    async def held(provider, account_id, tags=()):
        raise BackgroundDeferred("A subscription is connected; the API-key seat was not billed.")

    monkeypatch.setattr(routine_runner, "_hold_unattended_run_off_keys", held)
    for _ in range(2):
        with pytest.raises(BackgroundDeferred):
            await _run(runtime, tasks, task)
    runs = await service.runs_of(task.id)
    assert [(r.outcome, r.summary) for r in runs] == [
        ("skipped", "A subscription is connected; the API-key seat was not billed.")
    ]
    assert brain.calls == [] and await _run_chat(svc, tasks, task) is None
    assert (await service.get_task(task.id)).state == "active"


async def test_a_run_that_must_ask_does_not_start_on_a_seat_that_cannot_ask(
    lead_world, monkeypatch
) -> None:
    runtime, svc, tasks, conversation, brain = lead_world
    task = await service.take_on(**ADS, autonomy="watch")
    monkeypatch.setattr(service, "_can_ask", lambda provider, account_id: False)
    with pytest.raises(RuntimeError, match="cannot ask for an approval"):
        await _run(runtime, tasks, task)
    assert brain.calls == []
    assert [r.outcome for r in await service.runs_of(task.id)] == ["failed"]


async def test_a_stopped_run_is_logged_as_skipped(lead_world) -> None:
    runtime, svc, tasks, conversation, brain = lead_world
    task = await service.take_on(**ADS)
    brain.hold = asyncio.Event()
    spec = await tasks.get_spec(task.task_id)
    job = asyncio.create_task(
        run_owned_routine(runtime, task.task_id, spec.tags, spec.action.prompt)
    )
    for _ in range(200):
        if brain.calls:
            break
        await asyncio.sleep(0.01)
    job.cancel()
    with pytest.raises(asyncio.CancelledError):
        await job
    brain.hold.set()
    assert [r.outcome for r in await service.runs_of(task.id)] == ["skipped"]
    assert (await service.get_task(task.id)).state == "active"


async def test_other_routines_run_as_before(lead_world) -> None:
    from dodaios.society.routines import build_task_spec

    runtime, svc, tasks, conversation, brain = lead_world
    lead = await runtime.roster.get(LEAD_AGENT_ID)
    spec = build_task_spec(lead, title="Brief", prompt="Brief.", schedule={"kind": "every"})
    task_id = str(await tasks.insert(spec))
    await run_owned_routine(runtime, task_id, spec.tags, spec.action.prompt)
    row = await tasks.get(task_id)
    link = next(
        s["payload"]["session_id"] for s in row["steps"]
        if s["payload"].get("event") == "routine_chat"
    )
    assert svc.store.get_session(link).permission_mode == "bypass"
    assert [n["kind"] for n in _notices(svc, conversation.session_id)] == ["routine_run"]
    assert "standing task" not in brain.calls[-1][0]
