"""``delegate``: one typed front door over the specialised hand-off tools."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from dodaios.brain.delegate_tool import DelegateTool, parse_target
from dodaios.brain.spawn_gate import is_spawn_vehicle_call
from dodaios.core.protocols import ExecutionContext, ToolResult
from dodaios.orchestrator import jobs


@pytest.fixture(autouse=True)
def _ledger():
    ledger = jobs.JobLedger(":memory:")
    jobs.set_ledger(ledger)
    yield ledger
    jobs.set_ledger(None)


def _ctx(utterance: str = "hand this off") -> ExecutionContext:
    return ExecutionContext(
        trace_id=uuid4(), user_utterance=utterance, config={}, memory_read=None
    )


class Fake:
    """A stand-in for one specialised tool; records what it was called with."""

    def __init__(self, name: str, replies: list[ToolResult] | ToolResult) -> None:
        self.name = name
        self.calls: list[dict[str, Any]] = []
        self._replies = replies if isinstance(replies, list) else [replies]

    async def execute(self, args: dict[str, Any], ctx: Any) -> ToolResult:
        self.calls.append(args)
        index = min(len(self.calls) - 1, len(self._replies) - 1)
        return self._replies[index]


def _tool(*fakes: Fake, store: Any = None) -> DelegateTool:
    tools = {f.name: f for f in fakes}
    return DelegateTool(lambda: tools, store_resolver=(lambda: store) if store else None)


# ---- target parsing -----------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("agent:Scout", ("agent", "Scout")),
        ("Agent: Scout ", ("agent", "Scout")),
        ("agent", ("agent", "")),
        ("pane:T2", ("pane", "T2")),
        ("team_thread", ("team_thread", "")),
        ("team-thread", ("team_thread", "")),
        ("mission", ("mission", "")),
        ("routine", ("routine", "")),
        ("skill:daily-standup", ("skill", "daily-standup")),
    ],
)
def test_parse_target_accepts_every_typed_target(raw, expected) -> None:
    assert parse_target(raw) == expected


@pytest.mark.parametrize(
    "raw", ["", None, "pane", "pane:", "skill:", "skill:../x", "mission:now", "robot:R2", "T2"]
)
def test_parse_target_rejects_what_is_not_a_target(raw) -> None:
    assert isinstance(parse_target(raw), str)


async def test_invalid_arguments_are_rejected_before_anything_runs() -> None:
    agent = Fake("delegate_to_agent", ToolResult(True, {"job_id": "job_a"}))
    tool = _tool(agent)
    for args in (
        {"target": "robot:R2", "task": "x"},
        {"target": "agent:Scout", "task": "  "},
        {"target": "agent:Scout", "task": "x", "wait": "forever"},
        {"target": "agent:Scout", "task": "x", "wait_timeout_s": "soon"},
        {"target": "agent:Scout", "task": "x", "options": "nope"},
    ):
        result = await tool.execute(args, _ctx())
        assert not result.success and result.error
    assert agent.calls == []


# ---- routing to each implementation ------------------------------------------------


async def test_agent_target_routes_to_delegate_to_agent_with_the_reply_policy() -> None:
    agent = Fake(
        "delegate_to_agent",
        ToolResult(True, {"job_id": "job_agent1", "state": "running", "agent_name": "Scout"}),
    )
    result = await _tool(agent).execute(
        {
            "target": "agent:Scout",
            "task": "compare note apps",
            "reply": "always",
            "context": "for the Q3 review",
            "completion_criteria": "a table",
            "options": {"refs": ["notes.md"]},
        },
        _ctx(),
    )
    assert result.success
    assert result.output["job_id"] == "job_agent1"
    assert result.output["target"] == "agent:Scout"
    assert result.output["state"] == "running"
    assert agent.calls == [
        {
            "agent": "Scout",
            "task": "compare note apps",
            "context": "for the Q3 review",
            "completion_criteria": "a table",
            "reply_policy": "always",
            "refs": ["notes.md"],
        }
    ]


async def test_agent_name_clarification_is_passed_through_without_a_job() -> None:
    question = {"status": "needs_clarification", "question": "Scout or Scott?"}
    agent = Fake("delegate_to_agent", ToolResult(False, question, "target_ambiguous"))
    result = await _tool(agent).execute({"target": "agent:Skaut", "task": "x"}, _ctx())
    assert not result.success
    assert result.output["state"] == "needs_clarification"
    assert result.output["job_id"] is None
    assert result.output["detail"]["question"] == "Scout or Scott?"


async def test_bare_agent_target_lets_the_lead_pick() -> None:
    agent = Fake("delegate_to_agent", ToolResult(True, {"job_id": "job_pick"}))
    result = await _tool(agent).execute({"target": "agent", "task": "research espresso"}, _ctx())
    assert result.output["job_id"] == "job_pick"
    assert agent.calls[0]["agent"] == ""


async def test_pane_target_resolves_then_sends_under_the_request_id() -> None:
    pane = Fake(
        "workspace-orchestrate",
        [
            ToolResult(
                True,
                {
                    "status": "resolved",
                    "request_id": "11111111-1111-1111-1111-111111111111",
                    "target": {"project_id": "p", "workspace_id": "w", "terminal_id": "T2"},
                },
            ),
            ToolResult(True, {"status": "accepted", "results": [{"job_id": "job_pane1"}]}),
        ],
    )
    result = await _tool(pane).execute(
        {"target": "pane:T2", "task": "rebase", "completion_criteria": "tests green"}, _ctx()
    )
    assert result.output["job_id"] == "job_pane1"
    assert result.output["target"] == "pane:T2"
    resolve, send = pane.calls
    assert resolve["action"] == "resolve" and resolve["terminal_id"] == "T2"
    assert send["action"] == "send"
    assert send["terminal_id"] == "T2" and send["workspace_id"] == "w"
    assert send["request_id"] == "11111111-1111-1111-1111-111111111111"
    assert "rebase" in send["prompt"] and "tests green" in send["prompt"]


async def test_unknown_pane_returns_the_clarification_and_sends_nothing() -> None:
    pane = Fake(
        "workspace-orchestrate",
        ToolResult(True, {"status": "needs_clarification", "reason": "No such agent."}),
    )
    result = await _tool(pane).execute({"target": "pane:T9", "task": "x"}, _ctx())
    assert not result.success
    assert result.output["state"] == "needs_clarification"
    assert result.output["job_id"] is None
    assert [c["action"] for c in pane.calls] == ["resolve"]


async def test_team_thread_target_starts_a_thread_and_asks_first() -> None:
    team = Fake("team_thread", ToolResult(True, {"team_id": "t1", "job_id": "job_team1"}))
    tool = _tool(team)
    args = {
        "target": "team_thread",
        "task": "plan the billing module",
        "options": {"cwd": "C:/repo", "mode": "peers", "ignored": 1},
    }
    result = await tool.execute(args, _ctx())
    assert result.output["job_id"] == "job_team1"
    assert team.calls == [
        {"action": "start", "task": "plan the billing module", "cwd": "C:/repo", "mode": "peers"}
    ]
    assert tool.risk_tier_for_args(args) == "ask"
    assert tool.risk_tier_for_args({"target": "agent:Scout"}) == "monitor"


async def test_mission_target_routes_to_spawn_worker_and_reads_the_job_from_artifacts() -> None:
    worker = Fake(
        "spawn_worker",
        ToolResult(
            True,
            "On it.",
            artifacts=({"background_task": True, "job_id": "job_mission1"},),  # type: ignore[arg-type]
        ),
    )
    result = await _tool(worker).execute(
        {"target": "mission", "task": "build a photo renamer", "context": "python"}, _ctx()
    )
    assert result.output["job_id"] == "job_mission1"
    assert worker.calls[0]["utterance"] == "build a photo renamer"
    assert worker.calls[0]["context_hints"] == ["python"]


async def test_mission_job_id_is_read_from_the_text_result_too() -> None:
    worker = Fake("spawn_worker", ToolResult(True, "On it.\n(job_id: job_abc123; check it)"))
    result = await _tool(worker).execute({"target": "mission", "task": "x"}, _ctx())
    assert result.output["job_id"] == "job_abc123"


async def test_routine_target_needs_an_agent_and_a_schedule() -> None:
    routine = Fake("society-create-routine", ToolResult(True, {"next_run": "tomorrow"}))
    tool = _tool(routine)
    result = await tool.execute({"target": "routine", "task": "weekly report"}, _ctx())
    assert result.output["state"] == "needs_clarification"
    assert result.output["job_id"] is None
    assert routine.calls == []
    schedule = {"kind": "calendar", "local_time": "08:00"}
    result = await tool.execute(
        {
            "target": "routine",
            "task": "weekly report",
            "options": {"agent": "Scout", "schedule": schedule, "title": "Weekly"},
        },
        _ctx(),
    )
    assert result.success and result.output["job_id"]
    assert result.output["state"] == "done"
    assert routine.calls[0]["agent_id"] == "Scout"
    assert routine.calls[0]["schedule"] == schedule


async def test_skill_target_loads_the_skill_by_slug() -> None:
    skill = Fake("run-skill", ToolResult(True, "instructions"))
    result = await _tool(skill).execute({"target": "skill:daily-standup", "task": "go"}, _ctx())
    assert skill.calls[0]["skill_name"] == "daily-standup"
    assert result.success and result.output["job_id"]


# ---- the job id is always there ------------------------------------------------------


@pytest.mark.parametrize(
    ("target", "fake_name"),
    [
        ("agent:Scout", "delegate_to_agent"),
        ("mission", "spawn_worker"),
        ("team_thread", "team_thread"),
        ("skill:x", "run-skill"),
    ],
)
async def test_a_hand_off_without_its_own_job_gets_a_ledger_row(
    target, fake_name, _ledger
) -> None:
    fake = Fake(fake_name, ToolResult(True, {"acknowledged": True}))
    result = await _tool(fake).execute({"target": target, "task": "do it"}, _ctx())
    assert result.success
    job_id = result.output["job_id"]
    assert job_id and _ledger.get(job_id) is not None
    assert result.output["target"] == target


async def test_a_pane_send_without_a_job_is_recorded_as_blocked_not_done(_ledger) -> None:
    resolved = {"status": "resolved", "request_id": "r", "target": {"terminal_id": "T1"}}
    pane = Fake(
        "workspace-orchestrate",
        [ToolResult(True, resolved), ToolResult(True, {"status": "accepted"})],
    )
    result = await _tool(pane).execute({"target": "pane:T1", "task": "x"}, _ctx())
    job = _ledger.get(result.output["job_id"])
    assert job is not None and job.state == "blocked"


async def test_a_missing_implementation_is_a_failed_result_with_the_shape() -> None:
    result = await _tool().execute({"target": "mission", "task": "x"}, _ctx())
    assert not result.success
    assert set(result.output) >= {"job_id", "target", "state"}
    assert result.output["state"] == "failed" and result.output["job_id"] is None


async def test_an_implementation_that_raises_is_a_failed_result() -> None:
    class Boom(Fake):
        async def execute(self, args: dict[str, Any], ctx: Any) -> ToolResult:
            raise RuntimeError("no runner")

    result = await _tool(Boom("spawn_worker", ToolResult(True, ""))).execute(
        {"target": "mission", "task": "x"}, _ctx()
    )
    assert not result.success and result.output["state"] == "failed"
    assert "no runner" in result.output["error"]


# ---- idempotency is preserved -----------------------------------------------------------


class MemoryStore:
    def __init__(self) -> None:
        self.meta: dict[str, str] = {}
        self.conn = SimpleNamespace(commit=self._commit)

    async def _commit(self) -> None:
        return None

    async def get_meta(self, key: str) -> str:
        return self.meta.get(key, "")

    async def set_meta(self, key: str, value: str) -> None:
        self.meta[key] = value


async def test_the_same_hand_off_twice_in_one_turn_sends_once() -> None:
    worker = Fake("spawn_worker", ToolResult(True, {"job_id": "job_once"}))
    tool = _tool(worker, store=MemoryStore())
    ctx = _ctx()
    args = {"target": "mission", "task": "build it"}
    first = await tool.execute(args, ctx)
    second = await tool.execute(dict(args), ctx)
    assert len(worker.calls) == 1
    assert first.output["job_id"] == second.output["job_id"] == "job_once"
    assert second.output["idempotent_replay"] is True


async def test_a_failed_first_attempt_can_be_retried() -> None:
    worker = Fake(
        "spawn_worker",
        [ToolResult(False, None, "no runner"), ToolResult(True, {"job_id": "job_retry"})],
    )
    tool = _tool(worker, store=MemoryStore())
    ctx = _ctx()
    args = {"target": "mission", "task": "build it"}
    assert not (await tool.execute(args, ctx)).success
    assert (await tool.execute(args, ctx)).output["job_id"] == "job_retry"


# ---- wait: until_done uses await_jobs --------------------------------------------------------


async def test_wait_until_done_reports_the_job_record(_ledger) -> None:
    job_id = jobs.start("mission", target="mission", title="t", state="running")
    jobs.finish(job_id, "done", summary="built it")
    worker = Fake("spawn_worker", ToolResult(True, {"job_id": job_id}))
    result = await _tool(worker).execute(
        {"target": "mission", "task": "x", "wait": "until_done", "wait_timeout_s": 5}, _ctx()
    )
    assert result.output["state"] == "done"
    assert result.output["summary"] == "built it"
    assert result.output["wait"]["timed_out"] is False


async def test_a_wait_that_runs_out_says_still_running(_ledger) -> None:
    job_id = jobs.start("mission", target="mission", title="t", state="running")
    worker = Fake("spawn_worker", ToolResult(True, {"job_id": job_id}))
    result = await _tool(worker).execute(
        {"target": "mission", "task": "x", "wait": "until_done", "wait_timeout_s": 1}, _ctx()
    )
    assert result.output["state"] == "running"
    assert result.output["wait"]["timed_out"] is True


# ---- the spawn gate follows the target -------------------------------------------------------


def test_only_the_mission_target_is_a_spawn_vehicle() -> None:
    assert is_spawn_vehicle_call("spawn_worker", {})
    assert is_spawn_vehicle_call("delegate", {"target": "mission"})
    assert not is_spawn_vehicle_call("delegate", {"target": "agent:Scout"})
    assert not is_spawn_vehicle_call("delegate", {"target": "pane:T2"})
    assert not is_spawn_vehicle_call("delegate", {})
    assert is_spawn_vehicle_call("multi_spawn", {})
