"""Which calls of Dodaios' own tools a CLI seat may run without a card in Ask."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from dodaios.brain.standing_task_tool import StandingTaskTool
from dodaios.mcp.dodaios_tools_server import _read_only


def _entry(tier: str, *, action_tool: bool = False, hook: Any = None) -> Any:
    return SimpleNamespace(risk_tier=tier, is_action_tool=action_tool, risk_tier_for_args=hook)


def test_a_plain_tool_is_judged_by_its_own_tier() -> None:
    assert _read_only(_entry("safe"))
    assert _read_only(_entry("safe"), {"query": "x"})
    assert not _read_only(_entry("monitor"))
    assert not _read_only(_entry("monitor"), {"query": "x"})
    assert not _read_only(_entry("safe", action_tool=True), {})


def test_a_tool_with_several_actions_is_judged_by_the_call() -> None:
    def hook(args: dict[str, Any]) -> str:
        return "safe" if args.get("action") == "status" else "monitor"

    listed_strict = _entry("monitor", hook=hook)
    # Listed by its strictest action, so the listing never calls it read-only.
    assert not _read_only(listed_strict)
    assert _read_only(listed_strict, {"action": "status"})
    assert not _read_only(listed_strict, {"action": "close"})
    listed_safe = _entry("safe", hook=hook)
    assert _read_only(listed_safe, {"action": "status"})
    assert not _read_only(listed_safe, {"action": "close"})


def test_a_hook_that_fails_or_abstains_never_loosens() -> None:
    def broken(_args: dict[str, Any]) -> str:
        raise RuntimeError("no")

    assert not _read_only(_entry("safe", hook=broken), {"action": "status"})
    assert not _read_only(_entry("monitor", hook=lambda _a: None), {"action": "status"})
    assert _read_only(_entry("safe", hook=lambda _a: None), {"action": "status"})


def test_a_standing_task_run_reports_without_a_card() -> None:
    tool = StandingTaskTool()
    assert _read_only(tool, {"action": "report", "standing_id": "st_1", "outcome": "quiet"})
    assert _read_only(tool, {"action": "status", "standing_id": "st_1"})
    assert not _read_only(tool, {"action": "pause", "standing_id": "st_1"})
    assert not _read_only(tool, {"action": "take_on", "title": "t", "goal": "g"})
