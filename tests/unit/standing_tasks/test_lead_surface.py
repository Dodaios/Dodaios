"""The lead's tool and the UI's routes against the real service, store and scheduler.

Their own tests fake the service (``tests/fakes/fake_standing_tasks.py``). These few go the
whole way once, so a change in the service's behaviour shows on the surfaces that call it.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import httpx
from fastapi import FastAPI

from dodaios.brain.standing_task_tool import StandingTaskTool
from dodaios.core.protocols import ChatTurn, current_chat_turn
from dodaios.standing_tasks import service
from dodaios.standing_tasks.models import MAX_OPEN
from dodaios.ui.web.agent_chat_routes import router

LEAD = "lead-chat"
BASE = "/api/agent-chat/lead/standing"


@contextmanager
def _turn(text: str, *, session: str = LEAD, direct: bool = True) -> Iterator[None]:
    origin = "chat" if direct else "routine"
    token = current_chat_turn.set(ChatTurn(session, "turn-1", text, direct, "trace", origin=origin))
    try:
        yield
    finally:
        current_chat_turn.reset(token)


async def _call(tool: StandingTaskTool, **args: Any) -> Any:
    ctx = SimpleNamespace(trace_id=uuid4(), user_utterance="", config={}, memory_read=None)
    return await tool.execute(args, ctx)


def _tool() -> StandingTaskTool:
    return StandingTaskTool(lead_session=lambda session_id: session_id == LEAD)


async def test_a_task_is_taken_on_worked_and_handed_back_through_the_tool(society) -> None:
    tool = _tool()
    said = "Please look after my Meta ads campaign from now on."
    with _turn(said):
        taken = await _call(
            tool, action="take_on", title="Meta ads campaign",
            goal="Keep the cost per lead under 4 EUR.", check_every_min=240,
            request_quote="look after my Meta ads campaign",
        )
    assert taken.success, taken.error
    task = taken.output
    assert task["state"] == "active" and task["origin"] == "owner"
    assert task["pace"] == "every 4 hours" and task["next_run"] and task["task_id"]
    sid = task["id"]

    # The run reports from its own routine chat, and only from there.
    run_chat = f"society:jarvis:routine:{task['task_id']}:0123abcd"
    report = {
        "action": "report", "standing_id": sid, "outcome": "prepared",
        "summary": "Cost per lead is 4.60 EUR; a new creative is drafted.",
        "notes": "CPL 4.60. Creative B is tiring.", "actions": ["Drafted creative C"],
        "next_check_min": 60,
    }
    with _turn(said):
        refused = await _call(tool, **report)
    with _turn("Scheduled routine", session=run_chat, direct=False):
        reported = await _call(tool, **report)
    assert not refused.success and refused.output == {"code": "state"}
    assert reported.success, reported.error
    assert reported.output["last_outcome"] == "prepared"
    assert reported.output["notes"] == "CPL 4.60. Creative B is tiring."
    assert reported.output["pace"] == "every hour"

    status = await _call(tool, action="status", standing_id=sid)
    (run,) = status.output["runs"]
    assert run["outcome"] == "prepared" and run["session_id"] == run_chat
    assert run["actions"] == ["Drafted creative C"] and run["next_interval_min"] == 60

    with _turn("Scheduled routine", session=run_chat, direct=False):
        wider = await _call(tool, action="update", standing_id=sid, autonomy="act", limits="x")
        resumed = await _call(tool, action="resume", standing_id=sid)
        paused = await _call(tool, action="pause", standing_id=sid)
    assert not wider.success and not resumed.success
    assert paused.success and paused.output["state"] == "paused"
    assert paused.output["next_run"] is None
    with _turn("carry on with the campaign"):
        back = await _call(tool, action="resume", standing_id=sid)
        ended = await _call(tool, action="end", standing_id=sid)
    assert back.output["state"] == "active" and ended.output["state"] == "ended"
    listed = await _call(tool, action="list")
    assert listed.output == {"tasks": []}


async def test_a_run_proposes_and_the_owners_yes_starts_it(society) -> None:
    tool = _tool()
    fields = {"title": "Support inbox", "goal": "Tell me when a customer writes."}
    with _turn("Scheduled routine", session="society:jarvis:routine:needs-you:ff", direct=False):
        proposed = await _call(tool, action="take_on", **fields, request_quote="Scheduled")
    assert proposed.success and proposed.output["state"] == "proposed"
    assert proposed.output["task_id"] == "" and "proposal" in proposed.output["note"]
    assert society.kinds() == ["standing_proposal"]
    sid = proposed.output["id"]

    with _turn("What would that involve?"):
        too_early = await _call(tool, action="accept", standing_id=sid, request_quote="yes")
    with _turn("ja"):
        accepted = await _call(tool, action="accept", standing_id=sid, request_quote="ja")
        twice = await _call(tool, action="accept", standing_id=sid, request_quote="ja")
    assert not too_early.success
    assert accepted.success and accepted.output["state"] == "active" and accepted.output["task_id"]
    # Suggesting what is already looked after stores nothing and says so.
    again = await _call(tool, action="propose", **fields)
    assert again.output["id"] == sid and again.output["state"] == "active"
    assert "already exists" in again.output["note"]
    # The service's own refusal reads through: only a proposal is accepted.
    assert not twice.success and twice.output == {"code": "state"}
    assert "not a proposal" in twice.error


async def test_the_routes_carry_a_task_from_the_form_to_its_end(society) -> None:
    app = FastAPI()
    app.include_router(router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            BASE, json={"title": "Launch", "goal": "Keep the launch on track.", "interval_min": 5}
        )
        assert created.status_code == 201
        task = created.json()["task"]
        assert task["state"] == "active" and task["interval_min"] == 15  # clamped by the service
        url = f"{BASE}/{task['id']}"

        overview = (await client.get(BASE)).json()
        assert overview["available"] is True
        assert [t["id"] for t in overview["tasks"]] == [task["id"]]
        assert (await client.get(url)).json() == {"task": overview["tasks"][0], "runs": []}

        patched = await client.patch(url, json={"autonomy": "watch", "interval_min": 120})
        assert patched.json()["task"]["autonomy"] == "watch"
        assert patched.json()["task"]["interval_min"] == 120

        # What the service refuses, with its own sentence.
        twin = await client.post(BASE, json={"title": "launch", "goal": "Again."})
        acting = await client.patch(url, json={"autonomy": "act"})
        missing = await client.post(f"{BASE}/st_nope/pause")
        not_paused = await client.post(f"{url}/resume")
        assert (twin.status_code, acting.status_code) == (409, 422)
        assert (missing.status_code, not_paused.status_code) == (404, 409)
        for refusal in (twin, acting, missing, not_paused):
            assert isinstance(refusal.json()["detail"], str) and refusal.json()["detail"]

        assert (await client.post(f"{url}/run")).status_code == 200
        assert (await client.post(f"{url}/pause")).json()["task"]["state"] == "paused"
        assert (await client.post(f"{url}/resume")).json()["task"]["state"] == "active"
        assert (await client.post(f"{url}/end")).json()["task"]["state"] == "ended"
        assert (await client.get(BASE)).json()["tasks"] == []
        with_ended = (await client.get(BASE, params={"ended": "1"})).json()
        assert [t["state"] for t in with_ended["tasks"]] == ["ended"]

        society.up = False  # the scheduler is not running
        down = await client.post(BASE, json={"title": "Later", "goal": "g"})
        assert down.status_code == 503 and down.json()["detail"]
        assert (await client.get(BASE)).json()["available"] is False
        society.up = True

        for index in range(MAX_OPEN):
            made = await client.post(BASE, json={"title": f"Task {index}", "goal": "g"})
            assert made.status_code == 201
        full = await client.post(BASE, json={"title": "One too many", "goal": "g"})
        assert full.status_code == 409
    assert len(await service.list_tasks()) == MAX_OPEN
