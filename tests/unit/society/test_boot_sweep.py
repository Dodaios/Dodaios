"""A task claimed before a restart and never reported is closed as interrupted."""

from __future__ import annotations

import pytest

from dodaios.orchestrator import jobs
from dodaios.society.boot_sweep import sweep_interrupted_runs, sweep_open_jobs
from dodaios.society.delegation_wait import result_for
from dodaios.society.events import MsgType, SocietyEnvelope
from dodaios.society.roster import conversation_session_id
from dodaios.society.runtime import SocietyRuntime
from tests.unit.society.test_lead_card import FakeChat


class LiveChat(FakeChat):
    live: set[str]

    def is_running(self, session_id: str) -> bool:
        return session_id in self.live


@pytest.fixture(autouse=True)
def ledger():
    store = jobs.JobLedger(":memory:")
    jobs.set_ledger(store)
    try:
        yield store
    finally:
        jobs.set_ledger(None)
        store.close()


@pytest.fixture
async def rt(tmp_path):
    chat = LiveChat(tmp_path / "agent_chat.db")
    chat.live = set()
    lead = chat.store.create_session(
        provider="openai", model="", effort="", surface="jarvis", cwd="."
    )
    chat.store.set_lead_session_id(lead.session_id)
    runtime = SocietyRuntime(tmp_path, seed_starter_team=False, chat_service=lambda: chat)
    runtime.chat = chat
    runtime.lead_chat_id = lead.session_id
    await runtime.ensure_started()
    runtime.scheduler.detach()
    try:
        yield runtime
    finally:
        await runtime.close()


async def _assign_and_claim(rt, target, *, run_id: str):
    assign = await rt.say(
        from_agent="jarvis", to_agent=target.agent_id, text="Audit the repo",
        msg_type=MsgType.ASSIGN, payload={"reply_policy": "always"},
    )
    claim = await rt.store.append_and_publish(SocietyEnvelope(
        msg_type=MsgType.CLAIM, from_agent=target.agent_id, to_agent="jarvis",
        trace_id=assign.trace_id, parent_event_id=assign.event_id,
        payload={"run_id": run_id, "text": "took the task"},
    ))
    return assign, claim


async def test_claim_without_result_gets_interrupted_result_and_one_notice(rt):
    target, _ = await rt.roster.create(name="Scout", title="Research", description="Research")
    assign, _ = await _assign_and_claim(rt, target, run_id="turn:abc")

    assert await sweep_interrupted_runs(rt) == 1

    results = [
        e for e in await rt.store.events_for_trace(assign.trace_id)
        if e.msg_type is MsgType.RESULT
    ]
    assert len(results) == 1
    assert results[0].payload["status"] == "interrupted"
    assert results[0].payload["run_id"] == "turn:abc"
    assert results[0].parent_event_id == assign.event_id
    [(session_id, notice)] = rt.chat.notices
    assert session_id == rt.lead_chat_id
    assert notice["kind"] == "agent_task_interrupted"
    assert "Scout" in notice["text"] and "restarted" in notice["text"]
    # The wait of the delegating turn reads the same result.
    done = await result_for(rt.store, assign)
    assert done is not None and done["status"] == "interrupted"
    # Idempotent: the next boot finds nothing open.
    assert await sweep_interrupted_runs(rt) == 0
    assert len(rt.chat.notices) == 1


async def test_a_claim_with_a_live_turn_or_a_result_is_left_alone(rt):
    target, _ = await rt.roster.create(name="Scout", title="Research", description="Research")
    _assign, _ = await _assign_and_claim(rt, target, run_id="turn:live")
    rt.chat.live.add(conversation_session_id(target.agent_id, "jarvis"))
    assert await sweep_interrupted_runs(rt) == 0
    rt.chat.live.clear()

    other, _ = await rt.roster.create(name="Pilot", title="Ops", description="Ops")
    assign2, claim2 = await _assign_and_claim(rt, other, run_id="turn:done")
    await rt.store.append_and_publish(SocietyEnvelope(
        msg_type=MsgType.RESULT, from_agent=other.agent_id, to_agent="jarvis",
        trace_id=assign2.trace_id, parent_event_id=assign2.event_id,
        payload={"run_id": "turn:done", "status": "done", "done": "ok", "output": ["x"]},
    ))
    assert claim2 is not None
    assert await sweep_interrupted_runs(rt) == 1  # only the first (no longer live)
    assert len(rt.chat.notices) == 1


async def test_a_mission_run_claim_is_not_swept(rt):
    target, _ = await rt.roster.create(name="Scout", title="Research", description="Research")
    await _assign_and_claim(rt, target, run_id="mission-7")
    assert await sweep_interrupted_runs(rt) == 0


async def test_a_job_of_the_last_boot_is_read_again_from_the_board(rt, monkeypatch):
    target, _ = await rt.roster.create(name="Scout", title="Research", description="Research")
    assign, _ = await _assign_and_claim(rt, target, run_id="turn:abc")
    job_id = jobs.job_id_for("society_assignment", assign.event_id)
    jobs.start(
        "society_assignment", job_id=job_id, target=target.agent_id, title="Scout: audit",
        owner=("lead-chat", "t1"), meta={"event_id": assign.event_id, "trace_id": assign.trace_id},
    )
    monkeypatch.setattr(jobs, "BOOT_ID", "the-next-boot")  # the app restarted

    async def society():
        return rt

    monkeypatch.setattr("dodaios.mcp.agents.context.society", society)
    assert await sweep_interrupted_runs(rt) == 1  # the RESULT the dead watcher never wrote
    assert await sweep_open_jobs() == 1
    job = jobs.get_ledger().get(job_id)
    assert job is not None and job.state == "interrupted"
    assert "restarted" in job.summary


async def test_a_job_with_no_durable_evidence_is_interrupted_not_done(rt, monkeypatch):
    job_id = jobs.start("ide_submission", title="pane work", owner=("lead-chat", "t1"))
    monkeypatch.setattr(jobs, "BOOT_ID", "the-next-boot")
    assert await sweep_open_jobs() == 1
    assert jobs.get_ledger().get(job_id).state == "interrupted"
    assert await sweep_open_jobs() == 0  # settled once, not again
