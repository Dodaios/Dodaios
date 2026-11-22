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
