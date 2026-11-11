"""Slow tools as background jobs: hand-off, result, failure, cancel, restart."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest

from dodaios.core.chat_turn import ChatTurn, current_chat_turn
from dodaios.core.delegated_work import DelegatedWork, collect_delegated_work
from dodaios.core.protocols import ToolResult
from dodaios.orchestrator import async_tools, jobs
from dodaios.plugins.tool.job_tools import JobStatusTool, JobStopTool

SESSION, TURN = "lead-1", "turn-1"


def _ctx() -> SimpleNamespace:
    return SimpleNamespace(
        trace_id=uuid4(),
        user_utterance="",
        config={"approval_ref": f"agent-chat:{SESSION}", "tool_origin": "agent-chat"},
        memory_read=None,
    )


class SlowTool:
    """A shell-like tool the test finishes (or fails) by hand."""

    name = "run_shell"

    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.outcome: ToolResult | Exception = ToolResult(True, {"stdout": "built"})
        self.cancelled = False

    async def execute(self, args, ctx):
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


@pytest.fixture
def turn(monkeypatch):
    monkeypatch.setenv("DODAIOS_ASYNC_TOOL_BUDGET_S", "0.05")
    monkeypatch.setattr(async_tools, "_running", {})
    registered: list[DelegatedWork] = []
    token = current_chat_turn.set(ChatTurn(SESSION, TURN, "build it", True, "trace"))
    with collect_delegated_work(registered.append):
        yield registered
    current_chat_turn.reset(token)


async def test_a_call_that_ends_inside_the_budget_is_synchronous(turn):
    tool = SlowTool()
    tool.release.set()
    result = await async_tools.run_tool(tool, {"command": "git status"}, _ctx())
    assert result.output == {"stdout": "built"}
    assert turn == []
    assert jobs.get_ledger().recent(owner_session=SESSION, limit=5) == []


async def test_a_tool_outside_the_list_is_never_wrapped(turn):
    tool = SlowTool()
    tool.name = "search_web"
    task = asyncio.ensure_future(async_tools.run_tool(tool, {}, _ctx()))
    await asyncio.sleep(0.15)
    assert not task.done()  # still the caller's own call, waiting as before
    tool.release.set()
    assert (await task).success


async def test_a_declared_long_running_tool_is_wrapped(turn):
    tool = SlowTool()
    tool.name = "convert_video"
    tool.long_running = True
    result = await async_tools.run_tool(tool, {}, _ctx())
    assert result.output["started"] is True
    tool.release.set()


async def test_a_slow_call_returns_started_and_its_result_arrives_as_the_job_result(turn):
    tool = SlowTool()
    result = await async_tools.run_tool(tool, {"command": "npm run build"}, _ctx())

    assert result.success and result.output["started"] is True
    job_id = result.output["job_id"]
    assert job_id in result.output["note"]
    job = jobs.get_ledger().get(job_id)
    assert (job.kind, job.state, job.owner_session, job.owner_turn) == (
        "async_tool", "running", SESSION, TURN,
    )
    (work,) = turn
    assert work.key == f"async:{job_id}"
    assert (await work.probe())["status"] == "running"

    tool.release.set()
    await asyncio.sleep(0.02)
    row = await work.probe()
    assert row["status"] == "done"
    assert "built" in row["report"] and job_id in row["report"]
    assert row["result_ref"] == f"async_tool:{job_id}"
    full = await JobStatusTool().execute({"ids": [job_id], "full": True}, _ctx())
    assert full.output["jobs"][0]["result"]["output"] == {"stdout": "built"}


async def test_a_failing_tool_reports_a_readable_failure(turn):
    tool = SlowTool()
    tool.outcome = ToolResult(False, None, "exit 2")
    started = await async_tools.run_tool(tool, {"command": "make"}, _ctx())
    job_id = started.output["job_id"]
    tool.release.set()
    await asyncio.sleep(0.02)
    job = jobs.get_ledger().get(job_id)
    assert job.state == "failed" and job.error == "exit 2"
    assert "failed: exit 2" in (await turn[0].probe())["report"]


async def test_a_tool_that_raises_fails_the_job_not_the_chat(turn):
    tool = SlowTool()
    tool.outcome = RuntimeError("disk full")
    started = await async_tools.run_tool(tool, {"command": "make"}, _ctx())
    tool.release.set()
    await asyncio.sleep(0.02)
    job = jobs.get_ledger().get(started.output["job_id"])
    assert job.state == "failed" and "RuntimeError: disk full" in job.error


async def test_job_stop_cancels_the_work_and_the_job_ends_cancelled(turn):
    tool = SlowTool()
    started = await async_tools.run_tool(tool, {"command": "sleep 900"}, _ctx())
    job_id = started.output["job_id"]

    stopped = await JobStopTool().execute({"job_id": job_id}, _ctx())
    assert stopped.output["outcome"] == "stopped"
    await asyncio.sleep(0.02)
    assert tool.cancelled
    assert jobs.get_ledger().get(job_id).state == "cancelled"
    assert (await turn[0].probe())["status"] == "cancelled"
    again = await JobStopTool().execute({"job_id": job_id}, _ctx())
    assert again.output["outcome"] == "finished"
    unknown = await JobStopTool().execute({"job_id": "job_nope"}, _ctx())
    assert not unknown.success


async def test_a_stopped_turn_ends_the_call_that_was_still_its_own(turn):
    tool = SlowTool()
    caller = asyncio.ensure_future(async_tools.run_tool(tool, {"command": "x"}, _ctx()))
    await asyncio.sleep(0.01)
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    await asyncio.sleep(0.01)
    assert tool.cancelled


def _reopen(tmp_path, job_id: str, state: str) -> jobs.JobLedger:
    """A new process: a fresh ledger handle, the row as another boot left it."""
    jobs.set_ledger(None)
    reopened = jobs.JobLedger(tmp_path / "jobs.db")
    jobs.set_ledger(reopened)
    reopened._conn.execute(
        "UPDATE jobs SET state = ?, boot_id = 'old' WHERE id = ?", (state, job_id)
    )
    reopened._conn.commit()
    async_tools._running.clear()
    async_tools._memory_results.clear()
    return reopened


async def test_a_result_saved_before_a_restart_is_still_delivered(turn, tmp_path):
    store = jobs.JobLedger(tmp_path / "jobs.db")
    jobs.set_ledger(store)
    try:
        tool = SlowTool()
        started = await async_tools.run_tool(tool, {"command": "make"}, _ctx())
        job_id = started.output["job_id"]
        tool.release.set()
        await asyncio.sleep(0.02)
        assert (tmp_path / "async_tool_results" / f"{job_id}.json").exists()

        # The app died after the result was saved but before the row closed.
        reopened = _reopen(tmp_path, job_id, "running")
        job = await jobs.refresh(reopened.get(job_id))
        assert job.state == "done"
        assert "built" in async_tools.report_for(job)
    finally:
        jobs.set_ledger(None)
        store.close()


async def test_work_that_died_with_the_app_is_interrupted_never_done(turn, tmp_path):
    store = jobs.JobLedger(tmp_path / "jobs.db")
    jobs.set_ledger(store)
    try:
        tool = SlowTool()
        started = await async_tools.run_tool(tool, {"command": "make"}, _ctx())
        job_id = started.output["job_id"]
        # The process ends here: no result file, the row says running from another boot.
        reopened = _reopen(tmp_path, job_id, "running")
        jobs._probes.clear()
        job = await jobs.refresh(reopened.get(job_id))
        assert job.state == "interrupted"
        tool.release.set()
    finally:
        jobs.set_ledger(None)
        store.close()


def test_the_list_is_configurable(monkeypatch):
    assert async_tools.configured_tools() == async_tools.DEFAULT_TOOLS
    monkeypatch.setenv("DODAIOS_ASYNC_TOOLS", "foo-bar, run_shell")
    assert async_tools.configured_tools() == {"foo_bar", "run_shell"}
    monkeypatch.setenv("DODAIOS_ASYNC_TOOLS", "off")
    assert async_tools.configured_tools() == frozenset()
    assert not async_tools.is_long_running(SimpleNamespace(name="run_shell"))
    # Job tools and tools that return a job id themselves are never wrapped.
    monkeypatch.setenv("DODAIOS_ASYNC_TOOLS", "await_jobs,spawn_worker")
    assert not async_tools.is_long_running(SimpleNamespace(name="await_jobs"))
    assert not async_tools.is_long_running(SimpleNamespace(name="spawn_worker", long_running=True))


async def test_without_a_chat_turn_to_receive_the_result_the_call_stays_synchronous():
    tool = SlowTool()
    tool.release.set()
    result = await async_tools.run_tool(tool, {"command": "x"}, _ctx())
    assert result.output == {"stdout": "built"}


async def test_the_executor_hands_a_slow_call_off_after_its_approval(turn):
    from dodaios.core.bus import EventBus
    from dodaios.core.config import SafetyConfig
    from dodaios.safety.approval import ApprovalWorkflow
    from dodaios.safety.risk_tier import RiskTierEvaluator
    from dodaios.safety.tool_executor import ToolExecutor

    bus = EventBus()
    executor = ToolExecutor(
        bus, RiskTierEvaluator(SafetyConfig()), ApprovalWorkflow(bus, timeout_s=5.0),
        default_timeout_s=5.0,
    )
    tool = SlowTool()
    tool.risk_tier = "safe"
    tool.schema = {"type": "object", "properties": {}}
    tool.description = "slow"
    result = await executor.execute(
        tool, {"command": "ls"}, config_snapshot=_ctx().config, trace_id=uuid4()
    )
    assert result.success and result.output["started"] is True
    tool.release.set()


async def test_stopping_a_shell_job_kills_the_command(turn):
    import sys

    from dodaios.plugins.tool.run_shell import RunShellTool

    command = "Start-Sleep -Seconds 60" if sys.platform == "win32" else "sleep 60"
    tool = RunShellTool()
    started = await async_tools.run_tool(tool, {"command": command, "timeout_s": 120}, _ctx())
    job_id = started.output["job_id"]
    entry = async_tools._running[job_id]
    assert (await JobStopTool().execute({"job_id": job_id}, _ctx())).output["outcome"] == "stopped"
    await asyncio.wait({entry.task}, timeout=5)
    assert entry.task.cancelled()
    assert jobs.get_ledger().get(job_id).state == "cancelled"
