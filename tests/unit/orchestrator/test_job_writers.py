"""Every async hand-off writes a ledger row, derives its state from evidence, and
names its job in the tool result."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from dodaios.agent_chat.team import SeatPick, TeamThreads, TeamThreadStore
from dodaios.agentic_ide import delegation_wait as ide_wait
from dodaios.core.bus import EventBus
from dodaios.core.delegated_work import collect_delegated_work
from dodaios.core.protocols import ChatTurn, ExecutionContext, current_chat_turn
from dodaios.missions.state_machine import MissionState
from dodaios.orchestrator import jobs
from dodaios.plugins.tool.create_artifact import CreateArtifactTool
from dodaios.plugins.tool.delegate_to_agent import DelegateToAgentTool
from dodaios.plugins.tool.job_tools import AwaitJobsTool
from dodaios.plugins.tool.spawn_worker import SpawnWorkerTool
from dodaios.society.delegation_wait import ledger_job_id
from dodaios.society.events import MsgType, SocietyEnvelope
from dodaios.society.runtime import SocietyRuntime
from tests.fakes.fake_team_turns import FakeTurns, FakeWorkspace
from tests.unit.society.test_lead_card import FakeChat

ORIGIN = ChatTurn("lead-1", "turn-1", "do it", True, "trace-1")


def _ctx(**config: Any) -> ExecutionContext:
    return ExecutionContext(
        trace_id=uuid4(),
        user_utterance="build me an artifact",
        config={"output_language": "en", **config},
        memory_read=None,
    )


class FakeMissions:
    """A mission manager whose mission states the test sets."""

    def __init__(self, state: MissionState = MissionState.RUNNING, *, fail: bool = False) -> None:
        self.state = state
        self.fail = fail
        self.dispatched: list[str] = []

    async def dispatch(self, *, prompt: str, language: str, source_actor: str) -> str:
        if self.fail:
            raise RuntimeError("store unavailable")
        self.dispatched.append(prompt)
        return f"mission-{len(self.dispatched)}"

    async def mission(self, mission_id: str):
        return SimpleNamespace(mission_id=mission_id, prompt="", state=self.state)


class FakeRunner:
    async def run_mission(self, mission_id: str) -> None:
        return None


class FakeAnnouncer:
    async def compose(self, **_: Any) -> str:
        return "On it."


async def _settle() -> None:
    for _ in range(10):
        await asyncio.sleep(0)



# -------------------------------------------------------------------- artifacts


async def test_create_artifact_writes_a_job_and_names_it_in_the_result(ledger) -> None:
    manager = FakeMissions()
    tool = CreateArtifactTool(EventBus(), manager=manager, kontrollierer=FakeRunner())
    accepted: list = []
    token = current_chat_turn.set(ORIGIN)
    try:
        with collect_delegated_work(accepted.append):
            result = await tool.execute(
                {"title": "Sales page", "request": "Sales per month as bars."},
                _ctx(tool_origin="agent-chat"),
            )
    finally:
        current_chat_turn.reset(token)
    await _settle()

    marker = result.artifacts[0]
    job_id = marker["job_id"]
    assert job_id in result.output  # the model reads the id in the text
    job = ledger.get(job_id)
    assert (job.kind, job.owner_session, job.owner_turn) == ("artifact", "lead-1", "turn-1")
    assert job.title == "Sales page"
    assert job.ref == "mission-1"  # linked once the dispatch has a mission
    # The turn that ordered it is held open for it.
    assert [w.name for w in accepted] == ["Sales page"]

    assert (await accepted[0].probe())["status"] == "running"
    assert ledger.get(job_id).state == "running"
    manager.state = MissionState.APPROVED
    reading = await accepted[0].probe()
    assert reading["status"] == "completed"
    done = ledger.get(job_id)
    assert (done.state, done.result_ref) == ("done", "mission:mission-1")
    assert "sales-page.html" in done.summary


async def test_a_classic_voice_ack_stays_spoken_text_but_the_marker_has_the_id(ledger) -> None:
    tool = CreateArtifactTool(EventBus(), manager=FakeMissions(), kontrollierer=FakeRunner())
    result = await tool.execute({"title": "Plan", "request": "A plan."}, _ctx())
    await _settle()
    assert "job_id" not in result.output
    assert result.artifacts[0]["job_id"].startswith("job_")


async def test_a_dispatch_that_dies_before_a_mission_exists_fails_the_job(ledger) -> None:
    tool = CreateArtifactTool(EventBus(), manager=FakeMissions(fail=True), kontrollierer=None)
    result = await tool.execute({"title": "Plan", "request": "A plan."}, _ctx())
    await _settle()
    job = ledger.get(result.artifacts[0]["job_id"])
    assert job.state == "failed"
    assert "store unavailable" in job.error


async def test_spawn_worker_writes_a_mission_job_and_follows_the_mission(ledger) -> None:
    manager = FakeMissions()
    tool = SpawnWorkerTool(
        bus=EventBus(),
        manager=manager,
        kontrollierer_resolver=lambda: FakeRunner(),
        announcer=FakeAnnouncer(),
    )
    accepted: list = []
    token = current_chat_turn.set(ORIGIN)
    try:
        with collect_delegated_work(accepted.append):
            result = await tool.execute(
                {"utterance": "Research the best CI cache.", "action": "researches CI caches"},
                _ctx(tool_origin="agent-chat"),
            )
    finally:
        current_chat_turn.reset(token)
    await _settle()
    job_id = result.artifacts[0]["job_id"]
    assert job_id in result.output
    job = ledger.get(job_id)
    assert (job.kind, job.ref) == ("mission", "mission-1")
    assert len(accepted) == 1

    manager.state = MissionState.FAILED
    assert (await accepted[0].probe())["status"] == "failed"
    assert ledger.get(job_id).state == "failed"

    waited = await AwaitJobsTool().execute({"ids": [job_id], "timeout_s": 5}, _ctx())
    assert waited.output["finished"][0]["state"] == "failed"


async def test_a_mission_job_of_an_earlier_boot_is_read_from_the_mission_store(
    ledger, monkeypatch
) -> None:
    ledger.create("mission", job_id="job_old", ref="mission-9")
    ledger._conn.execute("UPDATE jobs SET boot_id = 'previous' WHERE id = 'job_old'")
    manager = FakeMissions(MissionState.APPROVED)
    monkeypatch.setattr("dodaios.brain.factory._resolve_mission_manager", lambda: manager)
    job = await jobs.refresh(ledger.get("job_old"))
    assert (job.state, job.result_ref) == ("done", "mission:mission-9")


async def test_living_page_creation_is_a_finished_artifact_job(ledger, tmp_path: Path) -> None:
    from dodaios.artifacts import living_refresh
    from dodaios.artifacts.living import LivingPageStore
    from dodaios.plugins.tool import living_page as living_tool
    from dodaios.plugins.tool.living_page import LivingPageTool

    async def start(store, page_id):
        return store.set_refresh(page_id, refreshing=True, task_id="t")

    async def card(*_a, **_k):
        return True

    living_refresh.start_refresh, saved = start, living_refresh.start_refresh
    living_tool.post_card, saved_card = card, living_tool.post_card
    try:
        tool = LivingPageTool(store=LivingPageStore(root=tmp_path))
        result = await tool.execute(
            {"operation": "create", "title": "Parcels", "track": "my parcels",
             "columns": ["Item"], "rows": [{"Item": "A"}]},
            _ctx(approval_ref="agent-chat:lead-1", tool_origin="agent-chat"),
        )
    finally:
        living_refresh.start_refresh = saved
        living_tool.post_card = saved_card
    assert result.success
    (job,) = ledger.recent(owner_session="lead-1")
    assert (job.kind, job.state, job.title) == ("artifact", "done", "Parcels")
    assert job.result_ref.startswith("artifact:")
    assert job.id in result.output


# ------------------------------------------------------------------- society


@pytest.fixture
async def rt(tmp_path):
    chat = FakeChat(tmp_path / "chat.db")
    runtime = SocietyRuntime(tmp_path, seed_starter_team=False, chat_service=lambda: chat)
    runtime.chat = chat
    await runtime.ensure_started()
    try:
        yield runtime
    finally:
        await runtime.close()


async def test_an_assignment_is_a_job_that_finishes_with_the_agents_result(rt, ledger) -> None:
    rt.scheduler.detach()
    target, _ = await rt.roster.create(name="Scout", title="Research", description="Research")
    token = current_chat_turn.set(ORIGIN)
    try:
        request = await rt.say(
            from_agent="jarvis",
            to_agent=target.agent_id,
            text="Audit the repo",
            msg_type=MsgType.ASSIGN,
            payload={"reply_policy": "always"},
        )
    finally:
        current_chat_turn.reset(token)
    job_id = ledger_job_id(request)
    job = ledger.get(job_id)
    assert (job.kind, job.owner_session, job.state) == ("society_assignment", "lead-1", "running")
    assert job.target == target.agent_id
    assert "Audit the repo" in job.title

    waiting = await AwaitJobsTool().execute({"ids": [job_id], "timeout_s": 1}, _ctx())
    assert waiting.output["timed_out"] is True
    assert waiting.output["still_running"][0]["job_id"] == job_id

    await rt.store.append_and_publish(
        SocietyEnvelope(
            from_agent=target.agent_id,
            to_agent="jarvis",
            msg_type=MsgType.RESULT,
            trace_id=request.trace_id,
            parent_event_id=request.event_id,
            payload={"status": "done", "done": "Found 3 issues", "evidence": []},
        )
    )
    waited = await AwaitJobsTool().execute({"ids": [job_id], "timeout_s": 5}, _ctx())
    (row,) = waited.output["finished"]
    assert (row["state"], row["summary"]) == ("done", "Found 3 issues")
    assert row["result_ref"] == f"society:{request.event_id}"


async def test_a_refused_assignment_reads_as_blocked_not_lost(rt, ledger) -> None:
    rt.scheduler.detach()
    target, _ = await rt.roster.create(name="Scout", title="Research", description="Research")
    request = await rt.say(
        from_agent="jarvis", to_agent=target.agent_id, text="Task", msg_type=MsgType.ASSIGN
    )
    await rt.store.append_and_publish(
        SocietyEnvelope(
            from_agent="scheduler",
            to_agent="jarvis",
            msg_type=MsgType.VETO,
            trace_id=request.trace_id,
            parent_event_id=request.event_id,
            payload={"text": "Agent is paused"},
        )
    )
    waited = await AwaitJobsTool().execute(
        {"ids": [ledger_job_id(request)], "timeout_s": 5}, _ctx()
    )
    assert waited.output["finished"][0]["state"] == "blocked"


async def test_only_tracked_messages_are_jobs_and_a_quiet_assignment_is_not_waited_for(
    rt, ledger
) -> None:
    rt.scheduler.detach()
    target, _ = await rt.roster.create(name="Scout", title="Research", description="Research")
    accepted: list = []
    token = current_chat_turn.set(ORIGIN)
    try:
        with collect_delegated_work(accepted.append):
            note = await rt.say(
                from_agent="jarvis", to_agent=target.agent_id, text="FYI",
                msg_type=MsgType.SAY, payload={"reply_policy": "none"},
            )
            quiet = await rt.say(
                from_agent="jarvis", to_agent=target.agent_id, text="Do it quietly",
                msg_type=MsgType.ASSIGN, payload={"reply_policy": "on_error"},
            )
    finally:
        current_chat_turn.reset(token)
    assert ledger_job_id(note) is None
    assert ledger.get(ledger_job_id(quiet)) is not None
    assert accepted == []  # recorded, but the turn does not hold for it


async def test_delegate_to_agent_returns_the_job_id(rt, ledger) -> None:
    rt.scheduler.detach()
    target, _ = await rt.roster.create(name="Scout", title="Research", description="Research")
    tool = DelegateToAgentTool(runtime_resolver=lambda: rt)
    result = await tool.execute(
        {"agent": "Scout", "task": "Audit the repo", "reply_policy": "always"}, _ctx()
    )
    assert result.success
    job_id = result.output["job_id"]
    assert job_id == jobs.job_id_for("society_assignment", result.output["assignment_id"])
    assert ledger.get(job_id).target == target.agent_id


# ----------------------------------------------------------------------- IDE


def _pane():
    return SimpleNamespace(
        agent="codex", account=None, resume=None, process_generation=1, last_submit_at=100.0,
        last_prompt="Fix the bug", history_id="pane-1", submitted=True, name="Coder",
        status="running", last_job_id="stale",
    )


async def test_a_coding_submission_is_a_job_and_a_newer_one_supersedes_it(ledger) -> None:
    term = _pane()
    owner = SimpleNamespace(id="workspace")
    registry = SimpleNamespace(find_terminal=lambda *a: (owner, term))
    accepted: list = []
    token = current_chat_turn.set(ORIGIN)
    try:
        with collect_delegated_work(accepted.append):
            job_id = ide_wait.track_submission(registry, owner, term)
    finally:
        current_chat_turn.reset(token)
    assert job_id == term.last_job_id
    job = ledger.get(job_id)
    assert (job.kind, job.owner_session, job.target) == ("ide_submission", "lead-1", "pane:pane-1")
    assert "Fix the bug" in job.title
    assert len(accepted) == 1

    term.last_submit_at = 200.0  # another prompt reached the pane
    await accepted[0].probe()
    assert ledger.get(job_id).state == "cancelled"
    assert ledger.get(job_id).detail == "superseded"


async def test_an_undelivered_prompt_is_no_job_and_clears_the_stale_id(ledger) -> None:
    term = _pane()
    term.submitted = False
    assert ide_wait.track_submission(SimpleNamespace(), SimpleNamespace(id="w"), term) is None
    assert term.last_job_id == ""
    assert ledger.recent() == []


# ---------------------------------------------------------------- team threads


async def test_a_team_thread_is_a_job_that_follows_the_thread_row(
    ledger, tmp_path: Path
) -> None:
    seats = [
        SeatPick("claude", name="Claude", family="claude"),
        SeatPick("gpt", name="GPT", family="openai"),
    ]
    store = TeamThreadStore(":memory:")
    engine = TeamThreads(store, FakeTurns(), workspace=FakeWorkspace())
    accepted: list = []
    token = current_chat_turn.set(ORIGIN)
    try:
        with collect_delegated_work(accepted.append):
            started = await engine.start(task="Add a retry", cwd=str(tmp_path), seats=seats)
    finally:
        current_chat_turn.reset(token)
    job_id = started["job_id"]
    assert ledger.get(job_id).kind == "team_thread"
    assert ledger.get(job_id).owner_session == "lead-1"
    assert len(accepted) == 1
    await engine.settled(started["team_id"])

    waited = await AwaitJobsTool().execute({"ids": [job_id], "timeout_s": 5}, _ctx())
    (row,) = waited.output["finished"]
    assert row["state"] == "done"
    assert row["result_ref"] == f"team_thread:{started['team_id']}"


async def test_a_stopped_or_waiting_team_thread_is_cancelled_or_blocked(ledger) -> None:
    from dodaios.orchestrator.team_jobs import team_probe

    store = TeamThreadStore(":memory:")
    team_id = store.create(
        title="T", task="x", cwd=".", lang="", limits={}, members=[], mode="peers", work={}
    )
    probe = team_probe(store, team_id)
    ledger.create("team_thread", job_id=jobs.job_id_for("team_thread", team_id))
    store.update(team_id, state="stopped", reason="user", note="")
    assert (await probe())["status"] == "cancelled"
    store.update(team_id, state="paused", reason="interrupted", note="")
    assert (await probe())["status"] == "interrupted"
    store.update(team_id, state="needs_input", reason="limit_time", note="")
    assert (await probe())["status"] == "needs_input"
