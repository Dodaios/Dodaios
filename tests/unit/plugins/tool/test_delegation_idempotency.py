"""A repeated hand-off returns the first receipt and sends nothing twice."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from dodaios.plugins.tool.delegate_to_agent import DelegateToAgentTool
from dodaios.plugins.tool.message_agent import LeadMessageAgentTool
from dodaios.society.events import MsgType
from dodaios.society.idempotency import idempotency_key
from dodaios.society.runtime import SocietyRuntime
from tests.unit.plugins.tool.test_delegate_to_agent import FakeChat


def _ctx(trace: UUID | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        trace_id=trace or uuid4(), user_utterance="x", config={}, memory_read=None
    )


@pytest.fixture
async def runtime(tmp_path: Path):
    chat = FakeChat(tmp_path / "agent_chat.db")
    cfg = SimpleNamespace(memory=SimpleNamespace(data_dir=str(tmp_path / "data")))
    rt = SocietyRuntime(tmp_path, chat_service=lambda: chat, cfg=lambda: cfg)
    await rt.ensure_started()
    await rt.roster.create(name="Scout", provider="openai", model="gpt-5.2")
    try:
        yield rt, chat
    finally:
        await rt.close()


async def _assignments(rt) -> int:
    return sum(1 for e in await rt.store.events_since(0) if e.msg_type is MsgType.ASSIGN)


async def test_same_turn_repeat_returns_the_first_receipt(runtime) -> None:
    rt, chat = runtime
    tool = DelegateToAgentTool(runtime_resolver=lambda: rt)
    turn = uuid4()
    first = await tool.execute({"agent": "Scout", "task": "Audit the repo."}, _ctx(turn))
    # A retry spells the task with different whitespace: still the same call.
    again = await tool.execute({"agent": "Scout", "task": "Audit  the repo. "}, _ctx(turn))

    assert first.success and again.success
    assert again.output["job_id"] == first.output["job_id"]
    assert again.output["assignment_id"] == first.output["assignment_id"]
    assert again.output["idempotent_replay"] is True
    assert "idempotent_replay" not in first.output
    assert len(chat.sent) == 1
    assert await _assignments(rt) == 1


async def test_a_later_turn_or_other_text_is_a_new_assignment(runtime) -> None:
    rt, chat = runtime
    tool = DelegateToAgentTool(runtime_resolver=lambda: rt)
    await tool.execute({"agent": "Scout", "task": "Audit the repo."}, _ctx())
    await tool.execute({"agent": "Scout", "task": "Audit the repo."}, _ctx())
    await tool.execute({"agent": "Scout", "task": "Audit the docs."}, _ctx())
    assert await _assignments(rt) == 3


async def test_concurrent_retry_sends_once(runtime) -> None:
    import asyncio

    rt, chat = runtime
    tool = DelegateToAgentTool(runtime_resolver=lambda: rt)
    turn = uuid4()
    args = {"agent": "Scout", "task": "Audit the repo."}
    results = await asyncio.gather(
        tool.execute(dict(args), _ctx(turn)), tool.execute(dict(args), _ctx(turn))
    )
    assert all(r.success for r in results)
    assert await _assignments(rt) == 1


async def test_failed_first_attempt_can_be_retried(runtime) -> None:
    rt, _chat = runtime
    tool = DelegateToAgentTool(runtime_resolver=lambda: rt)
    turn = uuid4()
    bad = await tool.execute({"agent": "NoSuchAgent9", "task": "Audit."}, _ctx(turn))
    assert not bad.success
    ok = await tool.execute({"agent": "Scout", "task": "Audit."}, _ctx(turn))
    assert ok.success


async def test_message_agent_retry_sends_once(runtime) -> None:
    rt, _chat = runtime
    tool = LeadMessageAgentTool(runtime_resolver=lambda: rt)
    turn = uuid4()
    args = {"target": "Scout", "text": "The audit message.", "kind": "say", "reply_policy": "none"}
    first = await tool.execute(dict(args), _ctx(turn))
    second = await tool.execute(dict(args), _ctx(turn))
    assert first.success, first.error
    assert second.success
    assert isinstance(second.output, dict) and second.output.get("idempotent_replay") is True
    messages = [
        e for e in await rt.store.events_since(0) if "The audit message." in (e.text or "")
    ]
    assert len(messages) == 1


def test_key_ignores_whitespace_and_key_order() -> None:
    ctx = _ctx()
    a = idempotency_key(ctx, "delegate_to_agent", {"task": "a  b", "agent": "S"})
    b = idempotency_key(ctx, "delegate_to_agent", {"agent": "S", "task": " a b "})
    assert a == b
    assert a != idempotency_key(ctx, "message_agent", {"task": "a b", "agent": "S"})
