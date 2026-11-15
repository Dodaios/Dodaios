"""A ritual's gathering run through the real routine runner, chat service and society.

The run gets the ritual's work order and a chat that may only look. What it
answers is kept back: the conversation sees nothing until the ritual starts.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from dodaios.agent_chat.lead import lead_session
from dodaios.agent_chat.proactive_checks import NOTHING, quiet_routine
from dodaios.core.bus import EventBus
from dodaios.rituals import prepare, service
from dodaios.rituals.store import RitualStore, get_store, set_store
from dodaios.society.roster import LEAD_AGENT_ID
from dodaios.society.routine_runner import run_owned_routine
from dodaios.society.routines import list_routines
from dodaios.tasks.scheduler import TaskScheduler
from dodaios.tasks.store import TaskStore
from tests.contract.test_society_continuity import world as world  # noqa: F401

MORNING = {
    "name": "Good morning",
    "phrases": ["Good morning"],
    "steps": [
        {"when": "now", "text": "Play my favourite music."},
        {"when": "ahead", "text": "The most important AI news since yesterday."},
    ],
}
ANSWER = (
    "SPOKEN:\nGood morning. A new model came out overnight.\n\n"
    "WRITTEN:\n## News\n- A new model came out overnight."
)


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
    rituals = RitualStore(":memory:")
    set_store(rituals)
    monkeypatch.setattr(service, "_POLL_S", 0.01)
    try:
        yield runtime, svc, tasks, conversation, brain
    finally:
        await prepare.drain()
        await service.drain()
        prepare._runs.clear()
        prepare._tried_at.clear()
        set_store(None)
        rituals.close()
        await scheduler.shutdown()
        await tasks.close()


def _today() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d")


def _notices(svc, session_id: str) -> list[dict]:
    return [e["payload"] for e in svc.store.list_events(session_id) if e["kind"] == "notice"]


async def _with_routine(runtime, tasks):
    """A ritual and its backing routine, as the first gathering sets it up."""
    ritual = await service.create(**MORNING)
    services = (runtime, tasks, runtime.task_services()[1], await runtime.roster.get(LEAD_AGENT_ID))
    ritual = await prepare.ensure_routine(ritual, services)
    return ritual, await tasks.get_spec(ritual.task_id)


async def _run(runtime, ritual, spec) -> str | None:
    return await run_owned_routine(runtime, ritual.task_id, spec.tags, spec.action.prompt)


async def _run_chat(svc, tasks, ritual):
    row = await tasks.get(ritual.task_id)
    links = [
        step["payload"]["session_id"]
        for step in row["steps"]
        if step["payload"].get("event") == "routine_chat"
    ]
    return svc.store.get_session(links[-1]) if links else None


async def test_the_run_gets_the_work_order_and_a_chat_that_may_only_look(lead_world) -> None:
    runtime, svc, tasks, conversation, brain = lead_world
    ritual, spec = await _with_routine(runtime, tasks)
    assert quiet_routine(spec.tags), "no start card for a run the person did not ask for"
    brain.reply = ANSWER
    answer = await _run(runtime, ritual, spec)
    assert answer == ANSWER
    prompt = brain.calls[-1][0]
    assert 'Gather what the person wants ready when they start their ritual "Good morning"' in (
        prompt
    )
    assert "1. The most important AI news since yesterday." in prompt
    assert "Only look." in prompt and "favourite music" not in prompt
    chat = await _run_chat(svc, tasks, ritual)
    assert chat.permission_mode == "ask", "a gathering run never gets a bypass chat"


async def test_what_was_gathered_is_kept_back_until_the_ritual_starts(lead_world) -> None:
    runtime, svc, tasks, conversation, brain = lead_world
    ritual, spec = await _with_routine(runtime, tasks)
    brain.reply = ANSWER
    await _run(runtime, ritual, spec)

    row = get_store().day(ritual.id, _today())
    assert row.prep_state == "ready" and row.written == "## News\n- A new model came out overnight."
    assert row.spoken == "Good morning. A new model came out overnight."
    chat = await _run_chat(svc, tasks, ritual)
    assert row.prep_session == chat.session_id
    # Nothing reached the conversation, and no routine list shows the run.
    assert _notices(svc, conversation.session_id) == []
    assert await list_routines(tasks, LEAD_AGENT_ID) == []

    result = await service.fire(ritual.id, via="button", force=True)
    await service.drain()
    assert result["pending"] is False
    (card,) = _notices(svc, conversation.session_id)
    assert card["kind"] == "society_result" and card["source"] == "ritual"
    assert card["ritual_title"] == "Good morning"
    assert card["text"].startswith("## News\n- A new model came out overnight.")


async def test_a_run_that_fails_leaves_its_reason_on_the_day(lead_world, monkeypatch) -> None:
    runtime, svc, tasks, conversation, brain = lead_world
    ritual, spec = await _with_routine(runtime, tasks)

    async def broken(text: str, **kwargs):
        raise RuntimeError("the model is unreachable")

    monkeypatch.setattr(brain, "generate", broken)
    with pytest.raises(RuntimeError):
        await _run(runtime, ritual, spec)
    row = get_store().day(ritual.id, _today())
    assert row.prep_state == "failed" and row.prep_error
    assert _notices(svc, conversation.session_id) == []


async def test_a_run_for_a_ritual_with_nothing_to_gather_calls_no_model(lead_world) -> None:
    runtime, svc, tasks, conversation, brain = lead_world
    ritual, spec = await _with_routine(runtime, tasks)
    await service.update(ritual.id, steps=[{"when": "now", "text": "Play my favourite music."}])
    before = len(brain.calls)
    assert await _run(runtime, ritual, spec) == NOTHING
    assert len(brain.calls) == before
