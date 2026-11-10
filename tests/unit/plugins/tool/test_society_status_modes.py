"""society_status: summary first, the deep views only behind explicit modes."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from dodaios.core.bounded_json import bound_json
from dodaios.plugins.tool.delegate_to_agent import DelegateToAgentTool, SocietyStatusTool
from dodaios.society.runtime import SocietyRuntime
from tests.unit.plugins.tool.test_delegate_to_agent import FakeChat


def _ctx() -> SimpleNamespace:
    return SimpleNamespace(trace_id=uuid4(), user_utterance="", config={}, memory_read=None)


@pytest.fixture
async def runtime(tmp_path: Path):
    chat = FakeChat(tmp_path / "agent_chat.db")
    cfg = SimpleNamespace(memory=SimpleNamespace(data_dir=str(tmp_path / "data")))
    rt = SocietyRuntime(tmp_path, chat_service=lambda: chat, cfg=lambda: cfg)
    await rt.ensure_started()
    for index in range(40):
        await rt.roster.create(name=f"Agent{index}", provider="openai", model="gpt-5.2")
    try:
        yield rt
    finally:
        await rt.close()


async def test_default_is_one_line_per_agent_and_small(runtime):
    status = SocietyStatusTool(runtime_resolver=lambda: runtime)
    result = await status.execute({}, _ctx())
    rows = result.output["agents"]
    assert result.output["total"] == len(rows) == 40
    assert set(rows[0]) >= {"id", "name", "seat", "state", "last_result"}
    assert rows[0]["seat"] == "openai/gpt-5.2" and rows[0]["state"] == "idle"
    assert len(json.dumps(result.output)) < 20_000


async def test_details_without_an_agent_is_the_summary_not_a_dump(runtime):
    status = SocietyStatusTool(runtime_resolver=lambda: runtime)
    result = await status.execute({"details": True}, _ctx())
    assert "recent_events" not in json.dumps(result.output)
    assert result.output["total"] == 40


async def test_agent_mode_gives_one_agent_in_detail(runtime):
    status = SocietyStatusTool(runtime_resolver=lambda: runtime)
    result = await status.execute({"mode": "agent", "agent": "Agent3"}, _ctx())
    assert result.success
    (row,) = result.output["agents"]
    assert row["agent"]["name"] == "Agent3" and "stats" in row
    missing = await status.execute({"mode": "agent"}, _ctx())
    assert missing.success is False


async def test_last_result_state_shows_in_the_summary_and_events_page_with_a_cursor(runtime):
    delegate = DelegateToAgentTool(runtime_resolver=lambda: runtime)
    status = SocietyStatusTool(runtime_resolver=lambda: runtime)
    for index in range(3):
        await delegate.execute({"agent": "Agent1", "task": f"Task number {index}."}, _ctx())
    first = await status.execute({"mode": "events", "agent": "Agent1", "limit": 2}, _ctx())
    assert first.success and len(first.output["events"]) == 2
    seqs = [row["seq"] for row in first.output["events"]]
    assert seqs == sorted(seqs, reverse=True)
    assert first.output["next_cursor"] == str(seqs[-1])
    second = await status.execute(
        {"mode": "events", "agent": "Agent1", "limit": 50, "cursor": first.output["next_cursor"]},
        _ctx(),
    )
    older = [row["seq"] for row in second.output["events"]]
    assert older and max(older) < seqs[-1]
    assert second.output["next_cursor"] is None
    bad = await status.execute({"mode": "events", "cursor": "x"}, _ctx())
    assert bad.success is False


async def test_assignment_mode_still_reads_one_assignment(runtime):
    delegate = DelegateToAgentTool(runtime_resolver=lambda: runtime)
    status = SocietyStatusTool(runtime_resolver=lambda: runtime)
    sent = await delegate.execute({"agent": "Agent2", "task": "Look into it."}, _ctx())
    result = await status.execute(
        {"mode": "assignment", "assignment_id": sent.output["assignment_id"]}, _ctx()
    )
    assert result.success and result.output["assignment_id"] == sent.output["assignment_id"]
    assert (await status.execute({"mode": "assignment"}, _ctx())).success is False
    assert (await status.execute({"mode": "nope"}, _ctx())).success is False


async def test_every_status_mode_stays_valid_json_inside_the_bound(runtime):
    status = SocietyStatusTool(runtime_resolver=lambda: runtime)
    for args in ({}, {"board": True}, {"mode": "events", "limit": 100}):
        result = await status.execute(args, _ctx())
        text = bound_json(result.output, 100_000)
        assert len(text) <= 100_000
        json.loads(text)
