"""A society agent's brief for a coding thread passes the same check as the lead's."""

# ruff: noqa: F811 - ``society`` is a fixture imported from the coding-thread tests
from __future__ import annotations

from pathlib import Path

from tests.unit.society.test_coding_threads import (  # noqa: F401 - ``society`` is a fixture
    Society,
    open_thread,
    settle,
    society,
    tool,
)

WEAK = "Make the login better somehow.\n1. Open login.py.\n2. Run `pytest`.\n3. Then commit."
STRONG = (
    "The login page accepts an empty password. Reject an empty password with the message "
    "'Enter your password'.\n\nDone when: a test that posts an empty password gets that "
    "message and passes."
)


async def test_a_weak_brief_goes_back_to_the_agent_and_opens_no_thread(
    society: Society, tmp_path: Path, briefs_on
):
    rt = society
    result = await tool(rt).execute(
        {"action": "open", "agent": "claude", "folder": str(tmp_path), "prompt": WEAK}, None
    )
    assert not result.success
    assert "The brief was not sent" in (result.error or "")
    assert "step_script" in (result.error or "") and "brief_kit" in (result.error or "")
    opened = [
        s for s in rt.service.store.list_sessions(surface="agent") if s.session_id != rt.owner
    ]
    assert opened == []


async def test_the_revised_brief_opens_the_thread_on_the_effort_the_job_calls_for(
    society: Society, tmp_path: Path, briefs_on
):
    rt = society
    await tool(rt).execute(
        {"action": "open", "agent": "claude", "folder": str(tmp_path), "prompt": WEAK}, None
    )
    thread = await open_thread(rt, tmp_path, STRONG)
    session = rt.service.store.get_session(thread)
    assert session.effort in ("high", "medium")
    first = rt.service.store.list_events(thread)[0]
    assert first["payload"]["text"].startswith("The login page accepts an empty password.")
    await settle(rt, thread)


async def test_a_follow_up_is_not_held_to_a_first_orders_rules(
    society: Society, tmp_path: Path, briefs_on
):
    rt = society
    thread = await open_thread(rt, tmp_path, STRONG)
    await settle(rt, thread)
    sent = await tool(rt).execute(
        {"action": "send", "thread_id": thread, "prompt": "Thanks. Now also land it."}, None
    )
    assert sent.success, sent.error
    await settle(rt, thread)


async def test_the_owner_is_woken_with_the_done_when_check_and_the_end_is_recorded(
    society: Society, tmp_path: Path, briefs_on
):
    import json

    from dodaios.agent_chat.events import make_event
    from dodaios.briefs import log as brief_log

    rt = society

    def ran(session_id: str) -> None:
        # Made when the turn starts: only what happens after the order counts.
        rt.service.steps[session_id] = [[
            make_event("tool_call", {"call_id": "c1", "name": "Bash",
                                     "input": {"command": "python -m pytest -q"}}),
            make_event("tool_result", {"call_id": "c1", "output": "3 passed in 0.1s"}),
            "Rejected the empty password. All tests pass.",
        ]]

    thread = await open_thread(rt, tmp_path, STRONG, steps=["placeholder"], setup=ran)
    await settle(rt, thread)

    owner_prompts = [p for sid, p in rt.service.prompts if sid == rt.owner]
    assert "Done-when check by Dodaios" in owner_prompts[-1]
    assert "1 of 1 confirmed" in owner_prompts[-1]
    state = rt.service.store.thread_owner(thread)["state"]
    delivery = brief_log.get_log().delivery(state["brief_job"])
    assert delivery["outcome"] == "completed"
    assert json.loads(delivery["acceptance"])[0]["verdict"] == "confirmed"


async def test_a_follow_up_without_points_is_checked_against_the_threads_order(
    society: Society, tmp_path: Path, briefs_on
):
    from dodaios.agent_chat.events import make_event

    rt = society
    thread = await open_thread(rt, tmp_path, STRONG, steps=["Which message text?"])
    await settle(rt, thread)
    rt.service.steps[thread] = [[
        make_event("tool_call", {"call_id": "c2", "name": "Bash",
                                 "input": {"command": "python -m pytest -q"}}),
        make_event("tool_result", {"call_id": "c2", "output": "4 passed in 0.1s"}),
        "Done.",
    ]]
    sent = await tool(rt).execute(
        {"action": "send", "thread_id": thread, "prompt": "Use 'Enter your password'."}, None
    )
    assert sent.success, sent.error
    await settle(rt, thread)
    owner_prompts = [p for sid, p in rt.service.prompts if sid == rt.owner]
    assert "1 of 1 confirmed" in owner_prompts[-1]
    assert "the order this turn continues" in owner_prompts[-1]


async def test_the_agents_answer_is_on_record_as_its_own(
    society: Society, tmp_path: Path, briefs_on
):
    from dodaios.agent_chat.events import make_event

    rt = society
    question = make_event("question_required", {
        "question_id": "q1", "deferred": True,
        "questions": [{"question": "Which message?", "options": [
            {"label": "Enter your password", "description": ""},
            {"label": "Password required", "description": ""},
        ], "recommended": 0, "recommendation_reason": "clearer"}],
    })
    thread = await open_thread(rt, tmp_path, STRONG, steps=[["Which message?", question]])
    await settle(rt, thread)
    result = await tool(rt).execute(
        {"action": "answer", "thread_id": thread, "answers": ["Enter your password"]}, None
    )
    assert result.success, result.error
    await settle(rt, thread)
    events = rt.service.store.list_events(thread)
    resolved = [e for e in events if e["kind"] == "question_resolved"][-1]["payload"]
    assert resolved["answers"][0]["source"] == "delegator"
    answer = [e for e in events if e["kind"] == "user_message"][-1]["payload"]["text"]
    assert "answered this on the person's behalf" in answer
