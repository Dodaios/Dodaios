"""Autonomy by reversibility: classes, and what each origin may run unasked.

An owner-direct call keeps today's behaviour (no new asking). A call that runs
without the owner (routine, trigger, watchdog, agent) may run reversible
actions per tier and needs an approval for recoverable and irreversible ones
unless the owner's whitelist or a standing rule covers them.
"""
from __future__ import annotations

from typing import Any

import pytest

from dodaios.core.bus import EventBus
from dodaios.core.config import SafetyConfig
from dodaios.core.events import ActionApprovalRequired, ActionDenied
from dodaios.core.protocols import ExecutionContext, ToolResult
from dodaios.safety.approval import ApprovalWorkflow
from dodaios.safety.reversibility import (
    UNATTENDED_ORIGINS,
    autonomy_origin,
    reversibility_of,
    unattended_origin,
)
from dodaios.safety.risk_tier import RiskTierEvaluator
from dodaios.safety.stop_hold import stop_holds
from dodaios.safety.tool_executor import (
    APPROVAL_UNAVAILABLE_PREFIX,
    STOPPED_BY_OWNER_OUTCOME,
    STOPPED_BY_OWNER_PREFIX,
    ToolExecutor,
)
from dodaios.trust.rules import trust_rules

class _Tool:
    risk_tier = "monitor"
    schema: dict[str, Any] = {}

    def __init__(self, name: str, **attrs: Any) -> None:
        self.name = name
        self.calls = 0
        for key, value in attrs.items():
            setattr(self, key, value)

    async def execute(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        self.calls += 1
        return ToolResult(success=True, output="ok")


def _executor(*, whitelist: list[str] | None = None) -> tuple[ToolExecutor, EventBus]:
    bus = EventBus()
    config = SafetyConfig(approval_mode="bypass")  # the shipped default
    if whitelist:
        config.whitelist.commands = whitelist
    executor = ToolExecutor(bus, RiskTierEvaluator(config), ApprovalWorkflow(bus, timeout_s=1.0))
    return executor, bus


# ------------------------------------------------------------------- classes


def test_a_tool_can_declare_its_class() -> None:
    assert reversibility_of(_Tool("x", reversibility="irreversible"), {}) == "irreversible"
    hooked = _Tool("x", reversibility_for_args=lambda a: "reversible" if a.get("dry") else None)
    assert reversibility_of(hooked, {"dry": True}) == "reversible"


@pytest.mark.parametrize(
    ("tool", "args", "expected"),
    [
        ("gmail", {"action": "modify_message"}, "reversible"),
        ("gmail", {"action": "create_draft"}, "reversible"),
        ("gmail", {"action": "list_messages"}, "reversible"),
        ("google_calendar", {"action": "create_event"}, "reversible"),
        ("remember", {}, "reversible"),
        ("gmail", {"action": "trash_message"}, "recoverable"),
        ("google_calendar", {"action": "update_event"}, "recoverable"),
        ("run_shell", {"command": "touch a"}, "recoverable"),
        ("gmail", {"action": "send_message"}, "irreversible"),
        ("slack", {"action": "post_message"}, "irreversible"),
        ("google_drive", {"action": "share_file"}, "irreversible"),
        ("google_drive", {"action": "delete_file"}, "irreversible"),
    ],
)
def test_the_apps_own_tools_are_classified(tool: str, args: dict, expected: str) -> None:
    assert reversibility_of(_Tool(tool), args) == expected


@pytest.mark.parametrize("limit", ["money", "credentials", "permanent_delete", "new_recipient"])
def test_a_hard_limit_is_irreversible(limit: str) -> None:
    assert reversibility_of(_Tool("anything"), {}, hard_limit=limit) == "irreversible"


def test_an_unknown_tool_is_reversible_only_when_it_is_safe() -> None:
    assert reversibility_of(_Tool("mystery"), {}, tier="safe") == "reversible"
    assert reversibility_of(_Tool("mystery"), {}, tier="monitor") == "recoverable"


def test_origin_is_declared_by_the_layer_not_the_arguments() -> None:
    assert unattended_origin({}) == ""
    assert unattended_origin({"autonomy_origin": "bogus"}) == ""
    for kind in UNATTENDED_ORIGINS:
        assert unattended_origin({"autonomy_origin": kind}) == kind
    with autonomy_origin("watchdog"):
        assert unattended_origin({}) == "watchdog"
    assert unattended_origin({}) == ""


# ------------------------------------------------- the rule, per class and origin


async def _run(executor: ToolExecutor, tool: _Tool, args: dict, origin: str = "") -> ToolResult:
    snapshot = {"autonomy_origin": origin} if origin else {}
    return await executor.execute(tool, args, config_snapshot=snapshot)


@pytest.mark.parametrize("origin", sorted(UNATTENDED_ORIGINS))
async def test_unattended_reversible_runs_per_tier(origin: str) -> None:
    executor, _ = _executor()
    tool = _Tool("gmail", risk_tier="monitor")
    result = await _run(executor, tool, {"action": "modify_message"}, origin)
    assert result.success and tool.calls == 1


@pytest.mark.parametrize("origin", sorted(UNATTENDED_ORIGINS))
@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("gmail", {"action": "trash_message"}),  # recoverable
        ("slack", {"action": "post_message"}),  # irreversible
    ],
)
async def test_unattended_recoverable_and_irreversible_need_approval(
    origin: str, name: str, args: dict
) -> None:
    executor, bus = _executor()
    seen: list[ActionApprovalRequired] = []

    async def capture(event: ActionApprovalRequired) -> None:
        seen.append(event)

    bus.subscribe(ActionApprovalRequired, capture)
    tool = _Tool(name, risk_tier="monitor")
    result = await _run(executor, tool, args, origin)
    assert not result.success and tool.calls == 0
    assert str(result.error).startswith(APPROVAL_UNAVAILABLE_PREFIX)
    assert [e.reason for e in seen] == ["reversibility"], "bypass never answers for it"


@pytest.mark.parametrize(
    "args",
    [{"action": "modify_message"}, {"action": "trash_message"}, {"action": "send_message"}],
)
async def test_owner_direct_calls_keep_todays_behaviour(args: dict) -> None:
    """No origin declared: the tier decides, bypass applies, nothing new is asked."""
    executor, bus = _executor()
    asked: list[ActionApprovalRequired] = []

    async def capture(event: ActionApprovalRequired) -> None:
        asked.append(event)

    bus.subscribe(ActionApprovalRequired, capture)
    tool = _Tool("gmail", risk_tier="monitor")
    result = await _run(executor, tool, args)
    assert result.success and tool.calls == 1
    assert asked == []


async def test_a_whitelist_entry_is_an_explicit_owner_rule() -> None:
    executor, _ = _executor(whitelist=["slack *"])
    tool = _Tool("slack", risk_tier="monitor", schema={"properties": {"action": {}}})
    result = await _run(executor, tool, {"action": "post_message"}, "routine")
    assert result.success and tool.calls == 1


async def test_a_standing_rule_covers_a_recoverable_action_but_not_a_hard_limit() -> None:
    executor, _ = _executor()
    trust_rules().add(tool="gmail", kind="action", target="trash_message")
    tool = _Tool("gmail", risk_tier="monitor")
    assert (await _run(executor, tool, {"action": "trash_message"}, "trigger")).success
    # Sending to a new recipient is a hard limit: no rule covers it.
    trust_rules().add(tool="gmail", kind="action", target="send_message")
    tool2 = _Tool("gmail", risk_tier="monitor")
    result = await _run(
        executor, tool2, {"action": "send_message", "to": "new@person.example"}, "trigger"
    )
    assert not result.success and tool2.calls == 0


# ------------------------------------------------------------------- stop holds


@pytest.mark.parametrize("origin", sorted(UNATTENDED_ORIGINS))
async def test_a_stop_hold_refuses_unattended_calls_even_reversible_ones(origin: str) -> None:
    executor, bus = _executor()
    denied: list[ActionDenied] = []

    async def capture(event: ActionDenied) -> None:
        denied.append(event)

    bus.subscribe(ActionDenied, capture)
    stop_holds().hold("everything", reason="owner said stop", source="telegram")
    tool = _Tool("search_web", risk_tier="safe")
    result = await _run(executor, tool, {}, origin)
    assert not result.success and tool.calls == 0
    assert str(result.error).startswith(STOPPED_BY_OWNER_PREFIX)
    assert result.output["outcome"] == STOPPED_BY_OWNER_OUTCOME
    assert denied and "stop-hold" in denied[0].reason


async def test_a_stop_hold_never_blocks_the_owner() -> None:
    executor, _ = _executor()
    stop_holds().hold("everything", reason="r")
    tool = _Tool("search_web", risk_tier="safe")
    assert (await _run(executor, tool, {})).success


async def test_a_scoped_hold_stops_only_that_routine() -> None:
    executor, _ = _executor()
    stop_holds().hold("routine", "t1", reason="r")
    tool = _Tool("search_web", risk_tier="safe")
    held = await executor.execute(
        tool, {}, config_snapshot={"autonomy_origin": "routine", "task_id": "t1"}
    )
    free = await executor.execute(
        tool, {}, config_snapshot={"autonomy_origin": "routine", "task_id": "t2"}
    )
    assert not held.success and free.success


async def test_the_block_marker_carries_hold_references() -> None:
    executor, _ = _executor()
    stop_holds().hold("agent", "ada", reason="r")
    tool = _Tool("search_web", risk_tier="safe")
    with autonomy_origin("routine", agent_id="ada"):
        assert not (await executor.execute(tool, {})).success
    with autonomy_origin("routine", agent_id="bob"):
        assert (await executor.execute(tool, {})).success


# ------------------------------------------------------------------- audit


async def test_held_and_unavailable_outcomes_still_write_an_audit_row() -> None:
    from dodaios.trust.audit import audit_log

    executor, _ = _executor()
    slack = _Tool("slack", risk_tier="monitor")
    await _run(executor, slack, {"action": "post_message"}, "routine")  # approval unavailable
    stop_holds().hold("everything", reason="r")
    await _run(executor, _Tool("search_web", risk_tier="safe"), {}, "routine")  # held
    rows = audit_log().query(limit=20)["entries"]
    assert {r["tool"] for r in rows} >= {"slack", "search_web"}
