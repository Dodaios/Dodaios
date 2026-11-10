"""The trust layer inside the executor: hard limits nothing lifts, the outbound
check, the undo ledger. Real bus, evaluator and workflow; no mocks."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from dodaios.core.bus import EventBus
from dodaios.core.config import SafetyConfig, SafetyWhitelistConfig
from dodaios.core.events import ActionApprovalRequired, ActionApproved, ActionDenied
from dodaios.core.protocols import ExecutionContext, ToolResult
from dodaios.safety.approval import ApprovalWorkflow
from dodaios.safety.risk_tier import RiskTierEvaluator
from dodaios.safety.tool_executor import (
    APPROVAL_DENIED_PREFIX,
    APPROVAL_UNAVAILABLE_PREFIX,
    ToolExecutor,
)
from dodaios.trust.recipients import known_recipients
from dodaios.trust.undo import undo_ledger


class _Tool:
    def __init__(self, name: str, *, risk_tier: str = "ask", output: Any = "ok") -> None:
        self.name = name
        self.risk_tier = risk_tier
        self.description = name
        self.schema = {
            "type": "object",
            "properties": {
                "action": {},
                "to": {},
                "body": {},
                "message_id": {},
                "remove_labels": {},
                "command": {},
            },
        }
        self.output = output
        self.calls: list[dict[str, Any]] = []

    async def execute(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        self.calls.append(dict(args))
        return ToolResult(success=True, output=self.output)


class _Shell(_Tool):
    whitelist_command_arg = "command"

    def intent_confirms_args(self, args: dict[str, Any], utterance: str) -> bool:
        return "delete" in utterance


def _stack(safety: SafetyConfig | None = None, *, timeout_s: float = 0.3):
    bus = EventBus()
    executor = ToolExecutor(
        bus,
        RiskTierEvaluator(safety or SafetyConfig()),
        ApprovalWorkflow(bus, timeout_s=timeout_s),
        default_timeout_s=timeout_s,
    )
    return bus, executor


def _collect(bus: EventBus, kind: type) -> list[Any]:
    seen: list[Any] = []

    async def on(event: Any) -> None:
        seen.append(event)

    bus.subscribe(kind, on)
    return seen


@pytest.mark.asyncio
async def test_bypass_never_answers_a_hard_limit() -> None:
    """Global bypass approves ask-tier calls — not one that touches a hard limit."""
    bus, executor = _stack(SafetyConfig(approval_mode="bypass"))
    denied = _collect(bus, ActionDenied)
    plain = _Tool("gmail", output={"id": "m"})
    ok = await executor.execute(
        plain,
        {"action": "send_message", "to": "ops@known.example", "body": "hi"},
        config_snapshot={"approval_surface": "unattended"},
    )
    assert ok.success is False, "a first mail to someone with nobody there cannot run"
    assert ok.error.startswith(APPROVAL_UNAVAILABLE_PREFIX)

    known_recipients().remember(["ops@known.example"])
    ok = await executor.execute(
        plain,
        {"action": "send_message", "to": "ops@known.example", "body": "hi"},
        config_snapshot={"approval_surface": "unattended"},
    )
    assert ok.success is True, "a known recipient runs under bypass as before"

    gone = await executor.execute(
        plain,
        {"action": "delete_message", "message_id": "m1"},
        config_snapshot={"approval_surface": "unattended"},
    )
    assert gone.success is False and gone.error.startswith(APPROVAL_UNAVAILABLE_PREFIX)
    assert any("approval_unavailable" in (d.reason or "") for d in denied)
    assert plain.calls == [{"action": "send_message", "to": "ops@known.example", "body": "hi"}]


@pytest.mark.asyncio
async def test_a_whitelist_never_downgrades_a_hard_limit() -> None:
    safety = SafetyConfig(whitelist=SafetyWhitelistConfig(commands=["git *", "rm *"]))
    bus, executor = _stack(safety)
    shell = _Shell("run_shell")
    fine = await executor.execute(
        shell, {"command": "git status"}, config_snapshot={"approval_surface": "unattended"}
    )
    assert fine.success is True, "the whitelist still covers a harmless command"
    hard = await executor.execute(
        shell,
        {"command": "git push --force origin main"},
        config_snapshot={"approval_surface": "unattended"},
    )
    assert hard.success is False and hard.error.startswith(APPROVAL_UNAVAILABLE_PREFIX)


@pytest.mark.asyncio
async def test_the_person_asking_by_name_still_counts_as_the_person() -> None:
    """The explicit-intent waiver (mandate 2026-08-08) survives: a deletion the
    person asked for by name runs; a hard limit needs a person, and that is one."""
    bus, executor = _stack()
    shell = _Shell("run_shell")
    result = await executor.execute(
        shell,
        {"command": "rm -rf build"},
        user_utterance="delete the build folder",
        config_snapshot={"approval_surface": "unattended"},
    )
    assert result.success is True
    silent = await executor.execute(
        shell,
        {"command": "rm -rf build"},
        user_utterance="tidy up",
        config_snapshot={"approval_surface": "unattended"},
    )
    assert silent.success is False


@pytest.mark.asyncio
async def test_a_person_can_still_allow_a_hard_limit_on_a_card() -> None:
    bus, executor = _stack(SafetyConfig(approval_mode="bypass"), timeout_s=2.0)
    required = _collect(bus, ActionApprovalRequired)

    async def click(event: ActionApprovalRequired) -> None:
        await bus.publish(
            ActionApproved(trace_id=event.trace_id, tool_name=event.tool_name, approved_by="user")
        )

    bus.subscribe(ActionApprovalRequired, click)
    # A monitor-tier send would run unprompted; the first mail to someone still
    # asks, and the card is told WHY ("trust", not the risk tier).
    plain = _Tool("gmail", risk_tier="monitor", output={"id": "m"})
    result = await executor.execute(
        plain,
        {"action": "send_message", "to": "new@person.example", "body": "hello"},
        config_snapshot={"approval_surface": "interactive"},
    )
    assert result.success is True
    assert required and required[0].reason == "trust"
    assert known_recipients().knows("new@person.example"), "a sent mail makes its recipient known"
    # The second mail to the same person runs without a card.
    again = await executor.execute(
        plain,
        {"action": "send_message", "to": "new@person.example", "body": "hello again"},
        config_snapshot={"approval_surface": "interactive"},
    )
    assert again.success is True and len(required) == 1


@pytest.mark.asyncio
async def test_a_secret_in_an_outbound_text_never_leaves() -> None:
    bus, executor = _stack(SafetyConfig(approval_mode="bypass"))
    denied = _collect(bus, ActionDenied)
    known_recipients().remember(["ops@known.example"])
    plain = _Tool("gmail")
    key = "sk-" + "b2" * 20
    result = await executor.execute(
        plain,
        {"action": "send_message", "to": "ops@known.example", "body": f"key: {key}"},
        config_snapshot={"approval_surface": "unattended"},
    )
    assert result.success is False and result.error.startswith(APPROVAL_DENIED_PREFIX)
    assert result.output["outcome"] == "outbound_blocked"
    assert [c["code"] for c in result.output["checks"]] == ["secret"]
    assert denied and denied[-1].reason == "outbound-check: secret"
    assert plain.calls == []


@pytest.mark.asyncio
async def test_a_reversible_action_leaves_its_undo_in_the_ledger() -> None:
    bus, executor = _stack(SafetyConfig(approval_mode="bypass"))
    heard: list[dict[str, Any]] = []
    undo_ledger().on_recorded(heard.append)
    gmail = _Tool("gmail", risk_tier="monitor", output={"id": "m1"})
    result = await executor.execute(
        gmail,
        {"action": "modify_message", "message_id": "m1", "remove_labels": ["INBOX"]},
        config_snapshot={"approval_ref": "agent-chat:sess-9"},
    )
    assert result.success is True
    assert (
        len(heard) == 1
        and heard[0]["session_id"] == "sess-9"
        and heard[0]["label"] == "Archived a mail"
    )

    ran: list[str] = []

    async def runner(tool: str, args: dict[str, Any], entry: dict[str, Any]) -> ToolResult:
        ran.append(tool)
        return await executor.execute(
            gmail, args, config_snapshot={"undo_of": entry["id"], "approval_surface": "unattended"}
        )

    undo_ledger().set_runner(runner)
    done = await undo_ledger().undo(heard[0]["id"])
    assert done["state"] == "undone" and ran == ["gmail"]
    assert gmail.calls[-1] == {
        "action": "modify_message",
        "message_id": "m1",
        "add_labels": ["INBOX"],
        "remove_labels": [],
    }
    assert len(heard) == 1, "the undo itself is not offered for undo"
    await asyncio.sleep(0)
