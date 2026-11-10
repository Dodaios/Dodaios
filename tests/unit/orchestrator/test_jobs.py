"""The jobs ledger, state derivation from evidence, and the two job tools."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest

from dodaios.core.protocols import ChatTurn, current_chat_turn
from dodaios.orchestrator import jobs
from dodaios.plugins.tool import job_tools
from dodaios.plugins.tool.job_tools import AwaitJobsTool, JobStatusTool


def _ctx(session: str = "lead-1") -> SimpleNamespace:
    return SimpleNamespace(
        trace_id=uuid4(),
        user_utterance="",
        config={"approval_ref": f"agent-chat:{session}", "tool_origin": "agent-chat"},
        memory_read=None,
    )


class Evidence:
    """A probe whose reading the test controls; counts how often it was read."""

    def __init__(self) -> None:
        self.result: dict | None = None
        self.reads = 0

    async def __call__(self) -> dict | None:
        self.reads += 1
        return self.result


def test_ledger_row_has_the_fields_the_lead_reads(ledger):
    job = ledger.create(
        "mission", job_id="job_a", owner_session="s1", owner_turn="t1", target="x", title="Build"
    )
    assert (job.kind, job.state, job.owner_session, job.owner_turn) == (
        "mission",
        "running",
        "s1",
        "t1",
    )
    assert job.created_ms == job.updated_ms
    assert job.to_dict()["job_id"] == "job_a"
    with pytest.raises(ValueError):
        ledger.create("nonsense", job_id="job_b")


def test_create_is_idempotent_and_a_finished_job_keeps_its_ending(ledger):
    ledger.create("mission", job_id="job_a", title="first")
    again = ledger.create("mission", job_id="job_a", title="second")
    assert again.title == "first"
    ledger.update("job_a", state="done", summary="shipped")
    late = ledger.update("job_a", state="running", summary="oops", result_ref="mission:m1")
    assert late.state == "done"
    assert late.summary == "shipped"
    # Late evidence can still supply the missing reference.
    assert late.result_ref == "mission:m1"


def test_blocked_and_interrupted_jobs_can_move_again(ledger):
    ledger.create("team_thread", job_id="job_a")
    assert ledger.update("job_a", state="blocked").state == "blocked"
    assert ledger.update("job_a", state="running").state == "running"
    assert ledger.update("job_a", state="interrupted").state == "interrupted"
    assert ledger.update("job_a", state="done").state == "done"


@pytest.mark.parametrize(
    ("status", "state"),
    [
        ("completed", "done"),
        ("done", "done"),
        ("running", "running"),
        ("failed", "failed"),
        ("error", "failed"),
        ("exited", "failed"),
        ("cancelled", "cancelled"),
        ("stopped", "cancelled"),
        ("superseded", "cancelled"),
        ("interrupted", "interrupted"),
        ("needs_input", "blocked"),
        ("unverified", "blocked"),
        ("blocked", "blocked"),
        ("something-new", "blocked"),
    ],
)
def test_probe_status_words_map_to_ledger_states(ledger, status, state):
    ledger.create("ide_submission", job_id="job_a")
    row = jobs.apply_result("job_a", {"status": status, "report": "r"})
    assert row.state == state


def test_no_evidence_leaves_the_state_alone(ledger):
    ledger.create("mission", job_id="job_a")
    assert jobs.apply_result("job_a", None).state == "running"


def test_recent_lists_open_jobs_first_for_one_owner(ledger):
    ledger.create("mission", job_id="old_done", owner_session="s1", state="done")
    time.sleep(0.002)
    ledger.create("mission", job_id="open", owner_session="s1")
    time.sleep(0.002)
    ledger.create("mission", job_id="newer_done", owner_session="s1", state="done")
    ledger.create("mission", job_id="other", owner_session="s2")
    ids = [j.id for j in ledger.recent(owner_session="s1")]
    assert ids == ["open", "newer_done", "old_done"]
    assert [j.id for j in ledger.recent(owner_session="s1", open_only=True)] == ["open"]


def test_job_id_for_is_stable_and_kind_scoped():
    first = jobs.job_id_for("society_assignment", "e1")
    assert first == jobs.job_id_for("society_assignment", "e1")
    assert first != jobs.job_id_for("ide_submission", "e1")


def test_owner_comes_from_the_trusted_turn_else_the_approval_ref():
    assert jobs.owner_of(_ctx("chat-9")) == ("chat-9", "")
    token = current_chat_turn.set(ChatTurn("turn-session", "turn-1", "hi", True, "trace"))
    try:
        assert jobs.owner_of(_ctx("chat-9")) == ("turn-session", "turn-1")
    finally:
        current_chat_turn.reset(token)
    assert jobs.owner_of(None) == ("", "")


def test_with_job_id_reaches_text_for_a_model_but_not_a_spoken_ack():
    assert "job_x" in jobs.with_job_id("Building.", "job_x", _ctx())
    bare = SimpleNamespace(config={})
    assert jobs.with_job_id("Building.", "job_x", bare) == "Building."
    assert jobs.with_job_id({"a": 1}, "job_x", bare) == {"a": 1, "job_id": "job_x"}
    assert jobs.with_job_id("Building.", None, _ctx()) == "Building."


async def test_refresh_derives_state_from_the_probe_and_records_it(ledger):
    evidence = Evidence()
    jid = jobs.start("ide_submission", ctx=_ctx(), title="Pane", probe=evidence)
    job = await jobs.refresh(ledger.get(jid))
    assert job.state == "running"
    evidence.result = {"status": "completed", "report": "All green", "result_ref": "pane:p1"}
    job = await jobs.refresh(ledger.get(jid))
    assert (job.state, job.summary, job.result_ref) == ("done", "All green", "pane:p1")
    reads = evidence.reads
    await jobs.refresh(ledger.get(jid))
    assert evidence.reads == reads  # a finished job is not read again


async def test_an_open_job_of_an_earlier_boot_without_evidence_is_interrupted(ledger):
    ledger.create("society_assignment", job_id="job_old", owner_session="s1")
    ledger._conn.execute("UPDATE jobs SET boot_id = 'previous' WHERE id = 'job_old'")
    job = await jobs.refresh(ledger.get("job_old"))
    assert job.state == "interrupted"
    assert "restarted" in job.summary


async def test_job_status_lists_this_chats_jobs_open_first_and_is_summary_first(ledger):
    running = jobs.start("mission", ctx=_ctx("lead-1"), title="Slow", probe=Evidence())
    finished = Evidence()
    finished.result = {"status": "completed", "report": "R" * 2000, "result_ref": "mission:m"}
    done = jobs.start("artifact", ctx=_ctx("lead-1"), title="Page", probe=finished)
    jobs.start("mission", ctx=_ctx("someone-else"), title="Not mine", probe=Evidence())
    result = await JobStatusTool().execute({}, _ctx("lead-1"))
    assert result.success
    rows = result.output["jobs"]
    assert [r["job_id"] for r in rows] == [running, done]
    assert result.output["open"] == 1
    assert result.output["settled"] == 1
    assert rows[1]["state"] == "done"
    assert rows[1]["result_ref"] == "mission:m"
    assert len(rows[1]["summary"]) <= 600


async def test_job_status_by_id_reports_unknown_ids_and_validates_input(ledger):
    jid = jobs.start("mission", ctx=_ctx(), title="A", probe=Evidence())
    result = await JobStatusTool().execute({"ids": [jid, "job_missing"]}, _ctx())
    assert [r["job_id"] for r in result.output["jobs"]] == [jid]
    assert result.output["unknown_ids"] == ["job_missing"]
    assert not (await JobStatusTool().execute({"ids": {"a": 1}}, _ctx())).success


async def test_await_returns_at_once_when_every_job_is_settled(ledger):
    evidence = Evidence()
    evidence.result = {"status": "completed", "report": "ok", "result_ref": "r:1"}
    jid = jobs.start("ide_submission", ctx=_ctx(), title="A", probe=evidence)
    began = time.monotonic()
    result = await AwaitJobsTool().execute({"ids": [jid], "timeout_s": 30}, _ctx())
    assert time.monotonic() - began < 2
    assert result.output["timed_out"] is False
    assert [r["job_id"] for r in result.output["finished"]] == [jid]
    assert result.output["still_running"] == []


async def test_await_times_out_with_partial_completion_and_never_pretends_done(
    ledger, monkeypatch
):
    monkeypatch.setattr(job_tools, "POLL_S", 0.05)
    finished, slow = Evidence(), Evidence()
    finished.result = {"status": "completed", "report": "fine"}
    a = jobs.start("mission", ctx=_ctx(), title="Fast", probe=finished)
    b = jobs.start("mission", ctx=_ctx(), title="Slow", probe=slow)
    result = await AwaitJobsTool().execute({"ids": [a, b], "timeout_s": 1}, _ctx())
    out = result.output
    assert out["timed_out"] is True
    assert [r["job_id"] for r in out["finished"]] == [a]
    assert [r["job_id"] for r in out["still_running"]] == [b]
    assert out["still_running"][0]["state"] == "running"
    assert "not done" in out["note"]
    assert 0.9 <= out["waited_s"] < 3


async def test_await_picks_up_a_job_that_finishes_while_waiting(ledger, monkeypatch):
    monkeypatch.setattr(job_tools, "POLL_S", 0.05)
    evidence = Evidence()
    jid = jobs.start("society_assignment", ctx=_ctx(), title="Task", probe=evidence)

    async def finish_soon():
        await asyncio.sleep(0.2)
        evidence.result = {"status": "completed", "report": "reported", "result_ref": "s:1"}

    task = asyncio.create_task(finish_soon())
    result = await AwaitJobsTool().execute({"ids": [jid], "timeout_s": 20}, _ctx())
    await task
    assert result.output["timed_out"] is False
    assert result.output["finished"][0]["result_ref"] == "s:1"


async def test_await_any_returns_on_the_first_and_blocked_needs_attention(ledger, monkeypatch):
    monkeypatch.setattr(job_tools, "POLL_S", 0.05)
    asks, slow = Evidence(), Evidence()
    asks.result = {"status": "needs_input", "report": "Which branch?"}
    a = jobs.start("ide_submission", ctx=_ctx(), title="Asks", probe=asks)
    b = jobs.start("ide_submission", ctx=_ctx(), title="Slow", probe=slow)
    result = await AwaitJobsTool().execute({"ids": [a, b], "timeout_s": 5, "mode": "any"}, _ctx())
    assert result.output["timed_out"] is False
    row = result.output["finished"][0]
    assert row["state"] == "blocked"
    assert row["needs_attention"] is True
    assert [r["job_id"] for r in result.output["still_running"]] == [b]


async def test_await_validates_its_arguments(ledger):
    tool = AwaitJobsTool()
    assert not (await tool.execute({"ids": []}, _ctx())).success
    assert not (await tool.execute({"ids": ["a"], "timeout_s": "soon"}, _ctx())).success
    assert not (await tool.execute({"ids": ["a"], "mode": "some"}, _ctx())).success
    unknown = await tool.execute({"ids": ["job_nope"], "timeout_s": 5}, _ctx())
    assert unknown.success
    assert unknown.output["unknown_ids"] == ["job_nope"]


def test_the_wait_limit_stays_under_the_chat_cli_tool_timeout():
    assert job_tools.MAX_AWAIT_S < 600
