"""Quiet lead routines: no start card, nothing posted when there is nothing to say,
and the next run of an adaptive routine sees the previous result."""

from __future__ import annotations

import pytest

from dodaios.agent_chat.lead import lead_session
from dodaios.agent_chat.proactive_checks import ADAPTIVE_TAG, NOTHING, QUIET_TAG
from dodaios.society.roster import LEAD_AGENT_ID
from dodaios.society.routine_runner import run_owned_routine
from dodaios.society.routines import build_task_spec
from dodaios.tasks.store import TaskStore
from tests.contract.test_society_continuity import world as world  # noqa: F401


def _notices(svc, session_id: str) -> list[dict]:
    return [
        e["payload"] for e in svc.store.list_events(session_id) if e["kind"] == "notice"
    ]


@pytest.fixture
async def lead_world(world, tmp_path):  # noqa: F811
    runtime, svc, _, brain = world
    store = TaskStore(tmp_path / "tasks.db")
    await store.init()
    runtime.task_services = lambda: (store, None)
    # The lead runs on a named seat here, like the mailbox agent of ``world``.
    lead = await runtime.roster.update(LEAD_AGENT_ID, {"provider": "openai"})
    conversation = lead_session(svc)
    assert conversation is not None
    try:
        yield runtime, svc, store, lead, conversation, brain
    finally:
        await store.close()


async def test_a_quiet_routine_posts_no_start_card_and_a_loud_one_does(lead_world):
    runtime, svc, store, lead, conversation, _ = lead_world
    quiet = build_task_spec(lead, title="Needs you", prompt="Check.", schedule={"kind": "every"})
    quiet = quiet.model_copy(update={"tags": (*quiet.tags, QUIET_TAG)})
    loud = build_task_spec(lead, title="Brief", prompt="Brief.", schedule={"kind": "every"})
    quiet_id = str(await store.insert(quiet))
    loud_id = str(await store.insert(loud))
    await run_owned_routine(runtime, quiet_id, quiet.tags, quiet.action.prompt)
    assert [n["kind"] for n in _notices(svc, conversation.session_id)] == []
    await run_owned_routine(runtime, loud_id, loud.tags, loud.action.prompt)
    cards = _notices(svc, conversation.session_id)
    assert [c["kind"] for c in cards] == ["routine_run"] and cards[0]["task_id"] == loud_id


async def test_nothing_to_report_is_not_posted_but_a_finding_is(lead_world):
    runtime, svc, _, lead, conversation, _ = lead_world
    result = {
        "kind": "society_result", "status": "done", "source": "routine",
        "agent_id": lead.agent_id, "agent_name": lead.name,
    }
    await runtime.post_chat_notice(lead, {**result, "text": NOTHING})
    await runtime.post_chat_notice(lead, {**result, "text": ""})
    assert _notices(svc, conversation.session_id) == []
    await runtime.post_chat_notice(lead, {**result, "text": "Max asks for the slides by noon."})
    await runtime.post_chat_notice(lead, {**result, "status": "failed", "text": "The run failed."})
    posted = _notices(svc, conversation.session_id)
    assert [n["text"] for n in posted] == ["Max asks for the slides by noon.", "The run failed."]


async def test_an_adaptive_routine_sees_its_previous_result(lead_world):
    runtime, _, store, lead, _, brain = lead_world
    spec = build_task_spec(lead, title="Brief", prompt="Write it.", schedule={"kind": "every"})
    spec = spec.model_copy(update={"tags": (*spec.tags, ADAPTIVE_TAG, QUIET_TAG)})
    task_id = str(await store.insert(spec))
    brain.reply = "Yesterday: two mails from Max wait for a reply."
    await run_owned_routine(runtime, task_id, spec.tags, spec.action.prompt)
    await store.append_step(task_id, "log", {"event": "agent_result", "text": brain.reply})
    first = brain.calls[-1][0]
    assert "previous result" not in first
    await run_owned_routine(runtime, task_id, spec.tags, spec.action.prompt)
    second = brain.calls[-1][0]
    assert "Your previous result" in second and "two mails from Max" in second
