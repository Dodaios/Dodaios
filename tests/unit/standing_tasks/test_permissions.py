"""What a standing task run may do, checked against the real executor, bridge and chat.

No mocks: a real ``EventBus``, ``ToolExecutor``, ``ChatApprovalBridge`` and
``AgentChatService``. The run's chat is in the mode
``standing_tasks.service.permission_mode`` gives it, its calls carry the
unattended origin the routine runner sets, and the runner's refusal of open
cards (``refuse_open_cards``) answers the card nobody is there to click.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from dodaios.agent_chat.approval_bridge import ChatApprovalBridge, ChatGrant, approval_ref
from dodaios.agent_chat.service import AgentChatService
from dodaios.agent_chat.store import AgentChatStore
from dodaios.core.bus import EventBus
from dodaios.core.config import SafetyConfig
from dodaios.core.protocols import ExecutionContext, ToolResult
from dodaios.safety.approval import ApprovalWorkflow
from dodaios.safety.reversibility import autonomy_origin
from dodaios.safety.risk_tier import RiskTierEvaluator
from dodaios.safety.tool_executor import APPROVAL_DENIED_PREFIX, ToolExecutor
from dodaios.standing_tasks import service

SESSION = "society:jarvis:routine:task-1:run-1"
REF = approval_ref(SESSION)


class _Tool:
    schema: dict[str, Any] = {}

    def __init__(self, name: str, risk_tier: str) -> None:
        self.name = name
        self.risk_tier = risk_tier
        self.calls = 0

    async def execute(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        self.calls += 1
        return ToolResult(success=True, output="ok")


@pytest.fixture
def run_chat(tmp_path):
    """A routine run's chat with the real approval path behind it."""
    chat = AgentChatService(AgentChatStore(tmp_path / "chat.db"))
    chat.store.create_session(
        session_id=SESSION, surface="society", provider="openai", model="m", effort="low",
        cwd=str(tmp_path), permission_mode="ask", title="run",
    )
    bus = EventBus()
    executor = ToolExecutor(
        bus,
        RiskTierEvaluator(SafetyConfig(approval_mode="bypass")),  # the shipped default
        ApprovalWorkflow(bus, timeout_s=5.0),
        default_timeout_s=5.0,
    )
    bridge = ChatApprovalBridge(bus)
    bridge.deny_reason = chat.take_deny_feedback
    try:
        yield chat, executor, bridge
    finally:
        chat.store.close()


def _arm(chat: AgentChatService, bridge: ChatApprovalBridge, stance: str) -> None:
    async def card(call_id: str, name: str, args: dict[str, Any], summary: str) -> str:
        return await chat._ask(SESSION, "turn-1", call_id, name, args, summary)

    bridge.arm(
        REF,
        ChatGrant(
            session_id=SESSION, turn_id="turn-1", stance=stance, always_allowed=set(),
            ask=card, call_id_for=lambda name: f"row-{name}",
        ),
    )


async def _call(chat: AgentChatService, executor: ToolExecutor, tool: _Tool, args: dict) -> Any:
    """One tool call of the run, with the runner refusing open cards beside it."""
    snapshot = {
        "approval_surface": "interactive", "approval_ref": REF, "approval_timeout_s": 5.0,
    }
    with autonomy_origin("routine", task_id="task-1", agent_id="jarvis"):
        job = asyncio.create_task(executor.execute(tool, args, config_snapshot=snapshot))
    refused = 0
    while not job.done():
        refused += service.refuse_open_cards(chat, SESSION)
        await asyncio.sleep(0.01)
    return await job, refused


@pytest.mark.parametrize(
    ("name", "args", "tier"),
    [
        ("gmail", {"action": "send_message"}, "ask"),  # an ask-tier action
        ("gmail", {"action": "trash_message"}, "monitor"),  # recoverable
        ("slack", {"action": "post_message"}, "monitor"),  # irreversible
    ],
)
async def test_in_an_ask_run_a_changing_call_is_refused_at_once_and_does_not_run(
    run_chat, name: str, args: dict, tier: str
) -> None:
    chat, executor, bridge = run_chat
    _arm(chat, bridge, await service.permission_mode(("lead-standing:st_missing0",)))
    tool = _Tool(name, tier)
    result, refused = await asyncio.wait_for(_call(chat, executor, tool, args), timeout=3.0)
    assert refused == 1, "a card was raised and the runner refused it"
    assert tool.calls == 0 and not result.success
    assert str(result.error).startswith(APPROVAL_DENIED_PREFIX)
    assert "Nobody is here to approve this" in str(result.error)
    assert chat.pending_approvals(SESSION) == []


@pytest.mark.parametrize(
    ("name", "args", "tier"),
    [
        ("search_web", {"query": "cpl benchmark"}, "safe"),
        ("gmail", {"action": "create_draft"}, "monitor"),  # reversible: a draft
    ],
)
async def test_in_an_ask_run_looking_and_reversible_preparing_need_no_card(
    run_chat, name: str, args: dict, tier: str
) -> None:
    chat, executor, bridge = run_chat
    _arm(chat, bridge, "ask")
    tool = _Tool(name, tier)
    result, refused = await asyncio.wait_for(_call(chat, executor, tool, args), timeout=3.0)
    assert result.success and tool.calls == 1 and refused == 0


async def test_a_bypass_run_is_held_by_no_card_which_is_why_only_act_may_get_one(
    run_chat,
) -> None:
    """What an ordinary lead routine gets: the chat's bypass answers the gate,
    reversibility included. An ``act`` task's limits are therefore the model's
    to keep; ``watch`` and ``prepare`` never run in this mode."""
    chat, executor, bridge = run_chat
    _arm(chat, bridge, "bypass")
    for name, args, tier in (
        ("gmail", {"action": "trash_message"}, "monitor"),
        ("slack", {"action": "post_message"}, "monitor"),
    ):
        tool = _Tool(name, tier)
        result, refused = await asyncio.wait_for(_call(chat, executor, tool, args), timeout=3.0)
        assert result.success and tool.calls == 1 and refused == 0
