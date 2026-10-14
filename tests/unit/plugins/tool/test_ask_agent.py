"""Asking a named agent waits for its answer, so a call can relay a conversation."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from jarvis.core.events import AnnouncementRequested
from jarvis.plugins.tool import ask_agent
from jarvis.plugins.tool.ask_agent import AskAgentTool
from jarvis.society.events import MsgType, SocietyEnvelope
from jarvis.society.runtime import SocietyRuntime
from tests.unit.plugins.tool.test_delegate_to_agent import FakeChat


def _ctx() -> SimpleNamespace:
    return SimpleNamespace(
        trace_id=uuid4(), user_utterance="ask scout", config={"output_language": "en"},
        memory_read=None,
    )


@pytest.fixture
async def team(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(ask_agent, "_POLL_S", 0.01)
    spoken: list[object] = []
    chat = FakeChat(tmp_path / "agent_chat.db")
    cfg = SimpleNamespace(memory=SimpleNamespace(data_dir=str(tmp_path / "data")))
    rt = SocietyRuntime(
        tmp_path, chat_service=lambda: chat, cfg=lambda: cfg, event_publish=spoken.append
    )
    await rt.ensure_started()
    await rt.roster.create(name="Scout", provider="openai", model="gpt-5.2")
    try:
        yield rt, spoken
    finally:
        await rt.close()


async def _question(rt: SocietyRuntime) -> SocietyEnvelope:
    """The newest question the lead put to an agent."""
    for _ in range(200):
        scout = await rt.roster.resolve("Scout")
        events = await rt.store.events_for_agent(scout.agent_id, limit=10)
        asked = [e for e in events if e.msg_type is MsgType.QUERY and e.from_agent == rt.lead_id]
        if asked:
            return asked[-1]
        await asyncio.sleep(0.01)
    raise AssertionError("the question never reached the agent")


async def _answer(rt: SocietyRuntime, text: str, *, status: str = "done") -> None:
    request = await _question(rt)
    await rt.say(
        from_agent=request.to_agent, to_agent=rt.lead_id, text=text,
        trace_id=request.trace_id, msg_type=MsgType.ANSWER,
        payload={"reply_status": status}, parent_event_id=request.event_id,
    )


async def test_the_answer_comes_back_in_the_same_call_and_is_not_announced_twice(team):
    rt, spoken = team
    tool = AskAgentTool(runtime_resolver=lambda: rt)
    asking = asyncio.create_task(
        tool.execute({"agent": "scout", "question": "Which VPS did you pick?"}, _ctx())
    )
    await _answer(rt, "Hetzner, because of the price.")
    result = await asyncio.wait_for(asking, 10)
    assert result.success and result.output["answered"] is True
    assert result.output["agent"] == "Scout"
    assert result.output["answer"] == "Hetzner, because of the price."
    request = await _question(rt)
    assert request.text == "Which VPS did you pick?" and request.payload["reply_policy"] == "always"
    await asyncio.sleep(0.05)
    assert not [e for e in spoken if isinstance(e, AnnouncementRequested)]


async def test_a_late_answer_is_handed_to_the_conversation_instead(team, monkeypatch):
    rt, spoken = team
    # The wait runs out at once: only this tool's clock jumps, not the loop's.
    clock = iter([0.0, 0.0])
    monkeypatch.setattr(ask_agent, "_now", lambda: next(clock, 1000.0))
    tool = AskAgentTool(runtime_resolver=lambda: rt)
    result = await tool.execute({"agent": "Scout", "question": "Summarise the inbox."}, _ctx())
    assert result.success and result.output["answered"] is False
    assert result.output["status"] == "pending" and "still thinking" in result.output["note"]
    await _answer(rt, "Three mails need you.")
    for _ in range(200):
        if any(isinstance(e, AnnouncementRequested) for e in spoken):
            break
        await asyncio.sleep(0.01)
    announced = [e for e in spoken if isinstance(e, AnnouncementRequested)]
    assert len(announced) == 1 and "Three mails need you." in (announced[0].report or "")


async def test_a_blocked_answer_keeps_its_status(team):
    rt, _spoken = team
    tool = AskAgentTool(runtime_resolver=lambda: rt)
    asking = asyncio.create_task(tool.execute({"agent": "Scout", "question": "Send it."}, _ctx()))
    await _answer(rt, "I have no mail access.", status="blocked")
    result = await asyncio.wait_for(asking, 10)
    assert result.output["answered"] is True and result.output["status"] == "blocked"


async def test_an_unknown_agent_or_a_missing_team_is_refused_without_waiting(team):
    rt, _spoken = team
    unknown = await AskAgentTool(runtime_resolver=lambda: rt).execute(
        {"agent": "Ghost", "question": "Anyone there?"}, _ctx()
    )
    assert unknown.success is False and "Scout" in unknown.output["available"]
    absent = await AskAgentTool(runtime_resolver=lambda: None).execute(
        {"agent": "Scout", "question": "Anyone there?"}, _ctx()
    )
    assert absent.success is False and absent.error == "society unavailable"


def test_the_wait_is_bounded_and_the_tool_is_offered_only_with_a_team():
    from jarvis.brain.tool_gateway import BrainSupervisorToolGateway

    wait = AskAgentTool.schema["properties"]["wait_seconds"]
    assert (wait["minimum"], wait["maximum"]) == (5, ask_agent.MAX_WAIT_S)

    def names(tools: dict) -> set[str]:
        manager = SimpleNamespace(_tools=tools, _config=SimpleNamespace(computer_use=None))
        return {d.name for d in BrainSupervisorToolGateway(manager).voice_catalog()}

    stub = SimpleNamespace(
        description="", schema={"type": "object"}, risk_tier="safe", execute=lambda *a: None
    )
    assert "ask_agent" in names({"message_agent": stub})
    assert "ask_agent" not in names({})


async def test_a_send_that_reports_failure_leaves_nothing_marked(team, monkeypatch):
    rt, spoken = team

    async def failed(_event_id):
        return "failed"

    monkeypatch.setattr(rt.store, "delivery_status", failed)
    result = await AskAgentTool(runtime_resolver=lambda: rt).execute(
        {"agent": "Scout", "question": "Are you there?"}, _ctx()
    )
    assert result.success is False
    assert rt._awaited_inline == set()
    # The message may have gone out all the same: its answer is announced as usual.
    await _answer(rt, "Yes.")
    for _ in range(200):
        if any(isinstance(e, AnnouncementRequested) for e in spoken):
            break
        await asyncio.sleep(0.01)
    assert [e for e in spoken if isinstance(e, AnnouncementRequested)]


async def test_only_the_one_question_is_marked_never_later_traffic(team):
    from jarvis.society.runtime import reply_awaited_inline

    rt, _spoken = team
    scout = await rt.roster.resolve("Scout")
    used: list[str] = []
    token = reply_awaited_inline.set(used)
    try:
        first = await rt.say(
            from_agent=rt.lead_id, to_agent=scout.agent_id, text="one", msg_type=MsgType.QUERY
        )
        # A task that inherited the context sends more: none of it is marked.
        second = await asyncio.create_task(
            rt.say(from_agent=rt.lead_id, to_agent=scout.agent_id, text="two",
                   msg_type=MsgType.QUERY)
        )
        note = await rt.say(
            from_agent=scout.agent_id, to_agent=rt.lead_id, text="fyi", msg_type=MsgType.SAY
        )
    finally:
        reply_awaited_inline.reset(token)
    assert used == [first.event_id]
    assert rt._awaited_inline == {first.event_id}
    assert second.event_id not in rt._awaited_inline and note.event_id not in rt._awaited_inline
    rt.stop_awaiting_inline(first.event_id)
    assert rt._awaited_inline == set()


async def test_after_every_way_out_nothing_stays_marked(team):
    rt, _spoken = team
    tool = AskAgentTool(runtime_resolver=lambda: rt)
    asking = asyncio.create_task(tool.execute({"agent": "Scout", "question": "Status?"}, _ctx()))
    await _question(rt)
    asking.cancel()
    await asyncio.gather(asking, return_exceptions=True)
    assert rt._awaited_inline == set()
