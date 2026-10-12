"""Team leads: leadership, the goal loop, waiting, stopping, recovery, the tools."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import aiosqlite
import pytest

from jarvis.agent_chat.store import AgentChatStore
from jarvis.society.events import MsgType, SocietyEnvelope, TeamGoalState, TeamTaskState, Tier
from jarvis.society.lead_card import render_lead_card
from jarvis.society.runtime import SocietyRuntime
from jarvis.society.store import SocietyStore
from jarvis.society.team_lead import (
    MAX_LEAD_TURNS,
    TRACE_PREFIX,
    TeamLeadError,
    goal_title,
)
from jarvis.society.team_tools import (
    TEAM_ASSIGN_TOOL_NAME,
    TEAM_BOARD_TOOL_NAME,
    TEAM_REPORT_TOOL_NAME,
    TeamAssignTool,
    TeamReportTool,
    team_lead_tools,
)
from tests.fakes.team_chat import TeamChatFake

LEAD = "society:boss"
SCOUT = "society:scout"
WRITER = "society:writer"


async def until(predicate: Callable[[], Any], *, within: float = 5.0) -> None:
    """Poll an awaitable-or-plain predicate until it holds."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + within
    while True:
        value = predicate()
        if asyncio.iscoroutine(value):
            value = await value
        if value:
            return
        if loop.time() > deadline:
            raise AssertionError("condition was not reached in time")
        await asyncio.sleep(0.01)


def _runtime(tmp_path: Path, svc: TeamChatFake) -> SocietyRuntime:
    cfg = SimpleNamespace(memory=SimpleNamespace(data_dir=str(tmp_path)))
    rt = SocietyRuntime(tmp_path, chat_service=lambda: svc, cfg=lambda: cfg)
    leads = rt.team_leads
    leads._retry_delay = 0.02  # noqa: SLF001 — tests do not wait fifteen seconds
    leads._review_delay = 0.0  # noqa: SLF001
    leads._lead_retry = 0.02  # noqa: SLF001
    return rt


@pytest.fixture
async def team(tmp_path: Path):
    svc = TeamChatFake(AgentChatStore(tmp_path / "chat.db"))
    rt = _runtime(tmp_path, svc)
    await rt.ensure_started()
    for name in ("Boss", "Scout", "Writer"):
        await rt.roster.create(name=name, provider="ollama", model="fake")
    await rt.store.create_chat_group("team", "Launch", ["boss", "scout", "writer"])
    await rt.team_leads.set_lead("team", "boss")
    try:
        yield rt, svc
    finally:
        await svc.close()
        await rt.close()
        svc.store.close()


async def _goal(rt: SocietyRuntime, goal_id: str):
    goal = await rt.team_leads.get_goal(goal_id)
    assert goal is not None
    return goal


def _state_is(rt: SocietyRuntime, goal_id: str, state: TeamGoalState) -> Callable[[], Any]:
    async def check() -> bool:
        return (await _goal(rt, goal_id)).state is state

    return check


# ------------------------------------------------------------- leadership


def test_goal_title_is_the_first_line_trimmed():
    assert goal_title("Launch the page\nby Friday") == "Launch the page"
    assert goal_title("x" * 200).endswith("…")
    assert goal_title("anything", "Given") == "Given"
    assert goal_title("  ") == "Goal"


async def test_naming_a_lead_promotes_it_and_clearing_restores_it(team):
    rt, _ = team
    boss = await rt.roster.get("boss")
    assert boss.tier is Tier.ORCHESTRATOR and boss.may_assign
    assert boss.max_concurrent_runs == 3
    assert rt.team_leads.group_led_by("boss") == "team"
    snapshot = await rt.team_leads.snapshot("team")
    assert snapshot["lead_agent_id"] == "boss" and snapshot["lead_available"]

    await rt.team_leads.set_lead("team", None)
    boss = await rt.roster.get("boss")
    assert boss.tier is Tier.SPECIALIST and boss.max_concurrent_runs == 1
    assert rt.team_leads.group_led_by("boss") is None


async def test_an_agent_that_was_an_orchestrator_before_stays_one(team):
    rt, _ = team
    await rt.roster.create(name="Chief", tier=Tier.ORCHESTRATOR, provider="ollama", model="fake")
    await rt.team_leads.set_lead("team", None)
    await rt.team_leads.set_lead("team", "chief")
    assert "chief" in (await rt.store.get_chat_group("team"))["members"]
    await rt.team_leads.set_lead("team", None)
    assert (await rt.roster.get("chief")).tier is Tier.ORCHESTRATOR


async def test_jarvis_and_a_lead_of_another_team_are_refused(team):
    rt, _ = team
    with pytest.raises(TeamLeadError, match="Jarvis"):
        await rt.team_leads.set_lead("team", "jarvis")
    await rt.store.create_chat_group("other", "Other", ["boss", "scout"])
    with pytest.raises(TeamLeadError, match="another team"):
        await rt.team_leads.set_lead("other", "boss")
    with pytest.raises(TeamLeadError) as missing:
        await rt.team_leads.set_lead("nope", "scout")
    assert missing.value.status == 404


async def test_create_lead_makes_a_new_orchestrator_with_a_free_name(team):
    rt, _ = team
    await rt.store.create_chat_group("ops", "Ops", ["scout", "writer"])
    group, agent = await rt.team_leads.create_lead(
        "ops", fields={"provider": "ollama", "model": "fake"}
    )
    assert agent.name == "Ops Lead" and agent.tier is Tier.ORCHESTRATOR
    assert group["lead_agent_id"] == agent.agent_id and agent.agent_id in group["members"]
    assert "manage a team" in agent.description
    await rt.store.create_chat_group("ops2", "Ops", ["scout", "writer"])
    _, second = await rt.team_leads.create_lead("ops2")
    assert second.name == "Ops Lead 2"


async def test_a_lead_leaving_the_team_stops_leading_it(team):
    rt, _ = team
    await rt.team_leads.members_changed("team", ["scout", "writer"])
    assert (await rt.store.get_chat_group("team"))["lead_agent_id"] is None
    assert rt.team_leads.group_led_by("boss") is None


# ------------------------------------------------------------ the goal loop


async def test_a_goal_is_planned_worked_reviewed_and_reported(team):
    rt, svc = team
    leads = rt.team_leads
    svc.replies[SCOUT] = "Three competitors found: A, B, C."
    svc.replies[WRITER] = "Draft is in draft.md."
    seen: list[str] = []

    async def boss(text: str, kwargs: dict[str, Any]) -> str:
        seen.append(text)
        if text.startswith("[team goal for"):
            await leads.assign("boss", member="Scout", title="Research", brief="Find competitors.")
            await leads.assign("boss", member="writer", title="Draft", brief="Write the page.")
            return "Two tasks are running."
        board = await leads.board("boss")
        tasks = board["goals"][0]["tasks"]
        if all(task["state"] == "done" for task in tasks):
            await leads.report("boss", status="done", summary="Launch page is ready.")
        return "Reviewed."

    svc.scripts[LEAD] = boss
    await rt.store.set_chat_group_mission("team", "Ship the launch.")
    goal = await leads.start_goal("team", "Launch the page\nby Friday", lang="en")
    await until(_state_is(rt, goal.goal_id, TeamGoalState.DONE))

    done = await _goal(rt, goal.goal_id)
    assert done.report == "Launch page is ready." and done.title == "Launch the page"
    tasks = await leads.tasks(goal.goal_id)
    assert [(t.agent_id, t.state) for t in tasks] == [
        ("scout", TeamTaskState.DONE),
        ("writer", TeamTaskState.DONE),
    ]
    assert all(t.reviewed and t.trace_id.startswith(TRACE_PREFIX) for t in tasks)
    assert tasks[0].result == "Three competitors found: A, B, C."

    assert "Team mission: Ship the launch." in seen[0]
    assert "- Scout" in seen[0] and "- Writer" in seen[0] and "Boss" not in seen[0]
    reviews = "\n".join(seen[1:])
    assert "[team update for team Launch]" in reviews
    assert "Three competitors found" in reviews and "Draft is in draft.md." in reviews
    # The lead's turns are not messages the person typed into its chat.
    lead_calls = [call for call in svc.sent if call[0] == LEAD]
    assert all(call[2]["direct_user"] is False for call in lead_calls)
    assert lead_calls[0][2]["output_language"] == "en"
    assert lead_calls[0][2]["display_text"] == "Launch the page\nby Friday"
    # Members got a framed assignment from the lead, on the board.
    assert svc.prompts(SCOUT)[0].startswith("[assignment from boss]")
    assert not rt.scheduler.running


async def test_an_answer_without_open_work_is_the_report(team):
    rt, svc = team
    svc.replies[LEAD] = "It is 42."
    goal = await rt.team_leads.start_goal("team", "What is the answer?")
    await until(_state_is(rt, goal.goal_id, TeamGoalState.DONE))
    assert (await _goal(rt, goal.goal_id)).report == "It is 42."
    assert len(svc.prompts(LEAD)) == 1


async def test_results_arriving_during_a_lead_turn_reach_the_next_one(team):
    rt, svc = team
    leads = rt.team_leads
    release = asyncio.Event()
    seen: list[str] = []

    async def boss(text: str, kwargs: dict[str, Any]) -> str:
        seen.append(text)
        if len(seen) == 1:
            await leads.assign("boss", member="scout", title="Research", brief="Look it up.")
            await release.wait()  # the member finishes while this turn is still open
            return "Assigned."
        await leads.report("boss", status="done", summary="All in.")
        return "Closed."

    svc.scripts[LEAD] = boss
    goal = await leads.start_goal("team", "Find it")

    async def scout_done() -> bool:
        tasks = await leads.tasks(goal.goal_id)
        return bool(tasks) and tasks[0].state is TeamTaskState.DONE

    await until(scout_done)
    assert len(seen) == 1
    release.set()
    await until(_state_is(rt, goal.goal_id, TeamGoalState.DONE))
    assert len(seen) == 2 and "New results:" in seen[1]


async def test_a_busy_member_is_knocked_on_again_instead_of_failing(team):
    rt, svc = team
    leads = rt.team_leads
    svc.busy.add(SCOUT)
    receipts: list[dict[str, Any]] = []

    async def boss(text: str, kwargs: dict[str, Any]) -> str:
        if text.startswith("[team goal for"):
            receipts.append(
                await leads.assign("boss", member="scout", title="Research", brief="Go.")
            )
            return "Waiting on Scout."
        await leads.report("boss", status="done", summary="Done.")
        return "Closed."

    svc.scripts[LEAD] = boss
    goal = await leads.start_goal("team", "Research it")

    async def waiting() -> bool:
        tasks = await leads.tasks(goal.goal_id)
        return bool(tasks) and tasks[0].state is TeamTaskState.WAITING and tasks[0].attempts >= 2

    await until(waiting)
    assert (await _goal(rt, goal.goal_id)).state is TeamGoalState.RUNNING
    svc.busy.discard(SCOUT)
    await until(_state_is(rt, goal.goal_id, TeamGoalState.DONE))
    assert (await leads.tasks(goal.goal_id))[0].state is TeamTaskState.DONE


async def test_a_blocked_member_reaches_the_lead_as_blocked(team):
    rt, svc = team
    leads = rt.team_leads
    svc.failing.add(SCOUT)
    seen: list[str] = []

    async def boss(text: str, kwargs: dict[str, Any]) -> str:
        seen.append(text)
        if len(seen) == 1:
            await leads.assign("boss", member="scout", title="Research", brief="Go.")
            return "Assigned."
        await leads.report("boss", status="failed", summary="Scout cannot reach the source.")
        return "Closed."

    svc.scripts[LEAD] = boss
    goal = await leads.start_goal("team", "Research it")
    await until(_state_is(rt, goal.goal_id, TeamGoalState.FAILED))
    assert '"Research": blocked' in seen[1]
    assert (await _goal(rt, goal.goal_id)).report == "Scout cannot reach the source."


async def test_a_question_waits_for_the_person_and_their_answer_continues(team):
    rt, svc = team
    leads = rt.team_leads
    seen: list[str] = []

    async def boss(text: str, kwargs: dict[str, Any]) -> str:
        seen.append(text)
        if len(seen) == 1:
            await leads.report("boss", status="needs_input", summary="Which market?")
            return "I need one answer."
        await leads.report("boss", status="done", summary="Planned for Germany.")
        return "Closed."

    svc.scripts[LEAD] = boss
    goal = await leads.start_goal("team", "Plan the launch")
    await until(_state_is(rt, goal.goal_id, TeamGoalState.NEEDS_INPUT))
    await until(svc.idle)
    waiting = await _goal(rt, goal.goal_id)
    assert waiting.report == "Which market?" and waiting.note == "question"
    assert len(seen) == 1

    await leads.tell(goal.goal_id, "Germany")
    await until(_state_is(rt, goal.goal_id, TeamGoalState.DONE))
    assert "The person says about this goal:" in seen[1] and "Germany" in seen[1]
    with pytest.raises(TeamLeadError, match="not in progress"):
        await leads.tell(goal.goal_id, "More")


async def test_goals_queue_and_start_one_after_another(team):
    rt, svc = team
    leads = rt.team_leads
    gate = asyncio.Event()
    svc.gates[LEAD] = gate
    first = await leads.start_goal("team", "First")
    second = await leads.start_goal("team", "Second")
    await until(lambda: len(svc.prompts(LEAD)) == 1)
    assert (await _goal(rt, second.goal_id)).state is TeamGoalState.QUEUED
    gate.set()
    await until(_state_is(rt, second.goal_id, TeamGoalState.DONE))
    assert (await _goal(rt, first.goal_id)).state is TeamGoalState.DONE
    prompts = svc.prompts(LEAD)
    assert "First" in prompts[0] and "Second" in prompts[1]


async def test_the_lead_busy_in_its_own_chat_is_retried(team):
    rt, svc = team
    svc.busy.add(LEAD)
    goal = await rt.team_leads.start_goal("team", "Do it")
    await asyncio.sleep(0.1)
    assert svc.prompts(LEAD) == []
    assert (await _goal(rt, goal.goal_id)).state is TeamGoalState.RUNNING
    svc.busy.discard(LEAD)
    await until(_state_is(rt, goal.goal_id, TeamGoalState.DONE))


# ------------------------------------------------------ stopping and bounds


async def test_cancel_stops_the_member_turn_and_closes_the_tasks(team):
    rt, svc = team
    leads = rt.team_leads
    svc.gates[SCOUT] = asyncio.Event()

    async def boss(text: str, kwargs: dict[str, Any]) -> str:
        await leads.assign("boss", member="scout", title="Research", brief="Go.")
        return "Assigned."

    svc.scripts[LEAD] = boss
    goal = await leads.start_goal("team", "Research it")

    async def running() -> bool:
        tasks = await leads.tasks(goal.goal_id)
        return bool(tasks) and tasks[0].state is TeamTaskState.RUNNING and svc.idle() is False

    await until(running)
    await until(lambda: LEAD not in svc.busy)
    cancelled = await leads.cancel(goal.goal_id)
    assert cancelled.state is TeamGoalState.CANCELLED
    assert (await leads.tasks(goal.goal_id))[0].state is TeamTaskState.CANCELLED
    assert (SCOUT, svc.sent[-1][3]) in svc.cancelled
    assert not rt.scheduler.running
    await until(svc.idle)
    # The stopped turn's late RESULT changes nothing.
    await asyncio.sleep(0.05)
    assert (await _goal(rt, goal.goal_id)).state is TeamGoalState.CANCELLED


async def test_the_kill_switch_pauses_goals_and_resume_continues(team):
    rt, svc = team
    leads = rt.team_leads
    svc.gates[SCOUT] = asyncio.Event()
    seen: list[str] = []

    async def boss(text: str, kwargs: dict[str, Any]) -> str:
        seen.append(text)
        if len(seen) == 1:
            await leads.assign("boss", member="scout", title="Research", brief="Go.")
            return "Assigned."
        await leads.report("boss", status="done", summary="Finished after the pause.")
        return "Closed."

    svc.scripts[LEAD] = boss
    goal = await leads.start_goal("team", "Research it")
    await until(lambda: SCOUT in svc.busy and LEAD not in svc.busy)
    result = await rt.engage_kill_switch()
    assert result["team_goals_paused"] == 1
    paused = await _goal(rt, goal.goal_id)
    assert paused.state is TeamGoalState.PAUSED and paused.note == "society_paused"
    with pytest.raises(TeamLeadError, match="paused"):
        await leads.start_goal("team", "Another")
    with pytest.raises(TeamLeadError, match="paused"):
        await leads.resume(goal.goal_id)

    # The real switch stops every society chat; the stopped task is on the board.
    await svc.cancel(SCOUT)
    await until(lambda: not rt.scheduler.running)
    assert len(seen) == 1  # a paused goal does not wake its lead

    await rt.release_kill_switch()
    await leads.resume(goal.goal_id)
    await until(_state_is(rt, goal.goal_id, TeamGoalState.DONE))
    assert "[team goal resumed for team Launch]" in seen[1]
    assert '"Research": blocked' in seen[1]


async def test_the_turn_budget_pauses_a_goal_until_the_person_resumes(team):
    rt, svc = team
    leads = rt.team_leads
    goal = await leads.start_goal("team", "Endless")
    await until(_state_is(rt, goal.goal_id, TeamGoalState.DONE))
    await rt.store.update_team_goal(
        goal.goal_id, {"state": "running", "lead_turns": MAX_LEAD_TURNS, "done_ms": None}
    )
    leads._resumed.add(goal.goal_id)  # noqa: SLF001 — something to say, so the budget is what stops it
    await leads._lead_turn(goal.goal_id)  # noqa: SLF001
    parked = await _goal(rt, goal.goal_id)
    assert parked.state is TeamGoalState.PAUSED and parked.note == "turn_budget"
    await leads.resume(goal.goal_id)
    await until(_state_is(rt, goal.goal_id, TeamGoalState.DONE))


async def test_a_failed_lead_turn_pauses_the_goal_with_the_reason(team):
    rt, svc = team
    svc.failing.add(LEAD)
    goal = await rt.team_leads.start_goal("team", "Do it")
    await until(_state_is(rt, goal.goal_id, TeamGoalState.PAUSED))
    assert (await _goal(rt, goal.goal_id)).note == "error:provider unavailable"


async def test_a_running_goal_comes_back_paused_after_a_restart(tmp_path: Path):
    svc = TeamChatFake(AgentChatStore(tmp_path / "chat.db"))
    rt = _runtime(tmp_path, svc)
    await rt.ensure_started()
    for name in ("Boss", "Scout"):
        await rt.roster.create(name=name, provider="ollama", model="fake")
    await rt.store.create_chat_group("team", "Launch", ["boss", "scout"])
    await rt.team_leads.set_lead("team", "boss")
    svc.gates[SCOUT] = asyncio.Event()

    async def boss(text: str, kwargs: dict[str, Any]) -> str:
        await rt.team_leads.assign("boss", member="scout", title="Research", brief="Go.")
        return "Assigned."

    svc.scripts[LEAD] = boss
    goal = await rt.team_leads.start_goal("team", "Research it")
    await until(lambda: SCOUT in svc.busy and LEAD not in svc.busy)
    await rt.close()  # the app closes mid-task; the member's turn dies with it
    await svc.close()

    again = _runtime(tmp_path, svc)
    await again.ensure_started()
    try:
        back = await again.team_leads.get_goal(goal.goal_id)
        assert back.state is TeamGoalState.PAUSED and back.note == "interrupted"
        task = (await again.team_leads.tasks(goal.goal_id))[0]
        assert task.state is TeamTaskState.BLOCKED and "Interrupted" in task.result
        assert not task.reviewed
        assert again.team_leads.group_led_by("boss") == "team"
        # Reading the board resumes nothing.
        await again.team_leads.snapshot("team")
        assert len(svc.prompts(LEAD)) == 1
    finally:
        await again.close()
        svc.store.close()


async def test_the_sweep_reports_a_run_that_died_silently(team):
    rt, svc = team
    leads = rt.team_leads
    svc.gates[SCOUT] = asyncio.Event()
    seen: list[str] = []

    async def boss(text: str, kwargs: dict[str, Any]) -> str:
        seen.append(text)
        if len(seen) == 1:
            await leads.assign("boss", member="scout", title="Research", brief="Go.")
            return "Assigned."
        await leads.report("boss", status="failed", summary="Scout went silent.")
        return "Closed."

    svc.scripts[LEAD] = boss
    goal = await leads.start_goal("team", "Research it")
    await until(lambda: SCOUT in svc.busy and LEAD not in svc.busy)
    task = (await leads.tasks(goal.goal_id))[0]
    await leads.sweep()  # fresh work is left alone
    assert (await leads.tasks(goal.goal_id))[0].state is TeamTaskState.RUNNING
    # The run vanished from the scheduler and the task shows no sign of life.
    rt.scheduler.note_run_ended(task.run_id)
    await rt.store.update_team_task(task.task_id, {"updated_ms": 1})
    await leads.sweep()
    await until(_state_is(rt, goal.goal_id, TeamGoalState.FAILED))
    assert "The run ended without a result." in seen[1]


# ------------------------------------------------- assignments from the board


async def test_work_handed_to_a_lead_becomes_a_goal_and_answers_its_origin(team):
    rt, svc = team
    leads = rt.team_leads

    async def boss(text: str, kwargs: dict[str, Any]) -> str:
        if text.startswith("[team goal for"):
            await leads.assign("boss", member="scout", title="Research", brief="Go.")
            return "Assigned."
        await leads.report("boss", status="done", summary="Researched and summarized.")
        return "Closed."

    svc.scripts[LEAD] = boss
    env = await rt.store.append_and_publish(
        SocietyEnvelope(
            msg_type=MsgType.ASSIGN,
            from_agent="jarvis",
            to_agent="boss",
            trace_id="voice:abc",
            payload={"text": "Research the market", "reply_policy": "always", "lang": "de"},
        )
    )
    events = await rt.store.events_for_trace("voice:abc")
    claim = next(e for e in events if e.msg_type is MsgType.CLAIM)
    run_id = claim.payload["run_id"]
    assert run_id.startswith("goal:") and rt.scheduler.running == {run_id: "boss"}
    goal_id = run_id.removeprefix("goal:")
    assert (await _goal(rt, goal_id)).lang == "de"

    await until(_state_is(rt, goal_id, TeamGoalState.DONE))
    await until(lambda: not rt.scheduler.running)
    result = next(
        e for e in await rt.store.events_for_trace("voice:abc") if e.msg_type is MsgType.RESULT
    )
    assert result.parent_event_id == env.event_id and result.from_agent == "boss"
    assert result.payload["status"] == "done"
    assert result.payload["done"] == "Researched and summarized."
    assert not rt.scheduler.running
    # The lead's own chat never ran the raw assignment as a second turn.
    assert all(not text.startswith("[assignment from") for text in svc.prompts(LEAD))


async def test_a_lead_assigning_from_its_own_chat_opens_a_goal(team):
    rt, svc = team
    leads = rt.team_leads
    receipt = await leads.assign("boss", member="scout", title="Check the logs", brief="Go.")
    goal = await _goal(rt, receipt["goal_id"])
    assert goal.title == "Check the logs" and goal.origin == {"kind": "lead"}
    svc.replies[LEAD] = "Logs are clean."
    await until(_state_is(rt, goal.goal_id, TeamGoalState.DONE))
    assert "[team update for team Launch]" in svc.prompts(LEAD)[0]


# ---------------------------------------------------------------- the tools


async def test_only_a_lead_holds_the_team_tools(team):
    rt, _ = team
    assert set(team_lead_tools(rt, "boss")) == {
        TEAM_ASSIGN_TOOL_NAME,
        TEAM_BOARD_TOOL_NAME,
        TEAM_REPORT_TOOL_NAME,
    }
    assert team_lead_tools(rt, "scout") == {}

    from jarvis.society.surface import society_tools

    lead_session = SimpleNamespace(session_id=LEAD, cwd="", permission_mode="")
    member_session = SimpleNamespace(session_id=SCOUT, cwd="", permission_mode="")
    cfg = rt.config()
    assert TEAM_ASSIGN_TOOL_NAME in society_tools(cfg, None, lead_session)
    assert TEAM_ASSIGN_TOOL_NAME not in society_tools(cfg, None, member_session)


async def test_the_assign_tool_composes_a_brief_and_refuses_strangers(team):
    rt, svc = team
    svc.gates[SCOUT] = asyncio.Event()
    tool = TeamAssignTool(rt, "boss")
    await rt.roster.create(name="Outsider", provider="ollama", model="fake")
    refused = await tool.execute({"member": "Outsider", "title": "X", "task": "Y"}, None)
    assert not refused.success and "not a member of your team" in refused.error
    assert "Scout" in refused.error and "Boss" not in refused.error
    own = await tool.execute({"member": "Boss", "title": "X", "task": "Y"}, None)
    assert not own.success

    ok = await tool.execute(
        {
            "member": "Scout",
            "title": "Research",
            "task": "Find three competitors.",
            "context": "We sell bikes.",
            "completion_criteria": "A list with links.",
        },
        None,
    )
    assert ok.success and ok.output["state"] == "running" and ok.output["member"] == "Scout"
    task = (await rt.team_leads.tasks(ok.output["goal_id"]))[0]
    assert "Relevant context:\nWe sell bikes." in task.brief
    assert "Completion criteria:\nA list with links." in task.brief
    prompt = svc.prompts(SCOUT)[0]
    assert "Research\n\nFind three competitors." in prompt
    svc.gates[SCOUT].set()

    report = TeamReportTool(rt, "boss")
    bad = await report.execute({"status": "maybe", "summary": "x"}, None)
    assert not bad.success
    stranger = await TeamReportTool(rt, "scout").execute(
        {"status": "done", "summary": "x"}, None
    )
    assert not stranger.success and "do not lead" in stranger.error


async def test_briefings_tell_the_lead_and_its_members_about_the_team(team):
    rt, _ = team
    await rt.team_leads.set_mission("team", "Ship the launch.")
    lead = rt.team_leads.briefing("boss")
    assert '## You lead the team "Launch"' in lead
    assert "Members you manage: Scout; Writer." in lead
    assert "Team mission: Ship the launch." in lead and "society_team_assign" in lead
    member = rt.team_leads.briefing("scout")
    assert 'member of the team "Launch", led by Boss' in member
    assert rt.team_leads.briefing("jarvis") == ""
    # Stable between team edits: the provider prompt cache holds.
    assert rt.team_leads.briefing("boss") == lead


async def test_jarvis_card_names_the_teams_that_have_a_lead(team):
    rt, _ = team
    card = render_lead_card(
        rt.roster.snapshot(), rt.catalog(), teams=rt.team_leads.teams_snapshot()
    )
    assert "- Launch — lead: Boss · members: Scout, Writer" in card
    assert "goes to its LEAD with delegate_to_agent" in card
    assert "Teams with their own lead" not in render_lead_card(rt.roster.snapshot(), rt.catalog())


# ------------------------------------------------------- check-ins, storage


class FakeTasks:
    """The slice of the task store and scheduler a routine needs."""

    def __init__(self) -> None:
        self.specs: dict[str, Any] = {}
        self.cancelled: list[str] = []

    async def schedule(self, spec: Any, **_: Any) -> str:
        self.specs[str(spec.id)] = spec
        return str(spec.id)

    async def cancel_task(self, task_id: str) -> None:
        self.cancelled.append(task_id)

    async def delete(self, task_id: str) -> None:
        self.specs.pop(task_id, None)

    async def list(self, limit: int = 1000) -> list[dict[str, Any]]:
        return [
            {"id": task_id, "title": spec.title, "state": "scheduled",
             "spec_json": spec.model_dump_json()}
            for task_id, spec in self.specs.items()
        ]


async def test_a_check_in_is_an_agent_routine_the_person_switches_on(team):
    rt, _ = team
    fake = FakeTasks()
    rt.task_services = lambda: (fake, fake)
    leads = rt.team_leads
    assert (await leads.snapshot("team"))["checkin_minutes"] == 0
    with pytest.raises(TeamLeadError):
        await leads.set_checkin("team", 7)

    assert await leads.set_checkin("team", 60) == 60
    (spec,) = fake.specs.values()
    assert "team-checkin:team" in spec.tags and "agent:boss" in spec.tags
    assert spec.trigger.interval_seconds == 3600
    assert "society_team_board" in spec.action.prompt
    assert (await leads.snapshot("team"))["checkin_minutes"] == 60

    await leads.set_checkin("team", 240)
    assert len(fake.specs) == 1 and len(fake.cancelled) == 1
    await leads.set_lead("team", None)
    assert fake.specs == {}


async def test_an_older_database_gains_the_lead_columns(tmp_path: Path):
    path = tmp_path / "society.db"
    conn = await aiosqlite.connect(path)
    await conn.execute(
        "CREATE TABLE society_chat_groups (group_id TEXT PRIMARY KEY, name TEXT NOT NULL, "
        "members_json TEXT NOT NULL, created_ms INTEGER NOT NULL, updated_ms INTEGER NOT NULL)"
    )
    await conn.execute(
        "INSERT INTO society_chat_groups VALUES (?, ?, ?, 1, 1)", ("old", "Old team", '["a", "b"]')
    )
    await conn.commit()
    await conn.close()

    store = SocietyStore(path)
    await store.open()
    try:
        group = await store.get_chat_group("old")
        assert group["members"] == ["a", "b"]
        assert group["lead_agent_id"] is None and group["mission"] == ""
        assert (await store.set_chat_group_lead("old", "a"))["lead_agent_id"] == "a"
        created = await store.create_chat_group("new", "New", ["a", "b"])
        assert created["lead_agent_id"] is None
    finally:
        await store.close()


async def test_deleting_a_team_stops_its_goals_and_frees_its_lead(team):
    rt, svc = team
    svc.gates[LEAD] = asyncio.Event()
    goal = await rt.team_leads.start_goal("team", "Do it")
    await until(lambda: LEAD in svc.busy)
    await rt.team_leads.group_deleted("team")
    await rt.store.delete_chat_group("team")
    await rt.team_leads.refresh()
    assert await rt.team_leads.get_goal(goal.goal_id) is None
    assert (await rt.roster.get("boss")).tier is Tier.SPECIALIST
    assert rt.team_leads.group_led_by("boss") is None
    assert (LEAD, svc.sent[0][3]) in svc.cancelled
