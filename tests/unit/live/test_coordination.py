"""Every live engine gets the same rules for talking, looking and handing over."""

from __future__ import annotations

import inspect
import re

from dodaios.core.agent_brief import AGENT_BRIEF_RULE
from dodaios.live import native
from dodaios.live.config import LiveConfig
from dodaios.live.coordination import (
    NAMED_TOOLS,
    ON_SCREEN_RULE,
    TEAM_TALK_RULE,
    WORK_STATUS_RULE,
    conversation_rules,
)

_RULES = WORK_STATUS_RULE + ON_SCREEN_RULE + TEAM_TALK_RULE + conversation_rules("your tools")
# Hyphenated or underscored words in the rules that are plain English, not tools.
_NOT_TOOLS = {"multi-step", "trade-offs", "mission_id"}


def test_every_tool_the_rules_name_is_listed_and_every_listed_tool_is_named():
    named_in_text = set(re.findall(r"\b[a-z]+(?:[-_][a-z]+)+\b", _RULES)) - _NOT_TOOLS
    assert named_in_text <= set(NAMED_TOOLS)
    for name in NAMED_TOOLS:
        assert re.search(rf"\b{re.escape(name)}\b", _RULES), name


def test_the_rules_spell_out_the_argument_a_small_model_has_to_pass():
    # "workspace-orchestrate status" read as an argument named status (live 2026-10-14).
    assert "workspace-orchestrate with action status" in WORK_STATUS_RULE
    assert "workspace-orchestrate with action watch" in WORK_STATUS_RULE
    assert "workspace-git, with op state" in WORK_STATUS_RULE


def _wire(**profile) -> dict:
    return LiveConfig(configured=True, backend_model="chosen-model", **profile).session_config(
        language="en", tools=[]
    )


def test_speaking_model_is_told_how_to_handle_a_request():
    rules = conversation_rules("the backend")
    spoken = _wire()["instructions"]
    assert rules in spoken
    for behaviour in (
        "Talk it through",
        "Take a quick look",
        "Hand it over",
        "start no implementation until they approve",
        "preferences for the whole task",
        "Never read out tables, lists, diffs, code or logs",
        "never say it cannot be changed",
    ):
        assert behaviour in rules, behaviour


def test_a_clear_order_is_not_held_back_as_planning():
    assert "A clear request to do something now is not planning" in conversation_rules("x")


def test_rules_name_whatever_carries_out_the_work():
    assert "the backend" in conversation_rules("the backend")
    assert "the backend" not in conversation_rules("your tools")
    assert "your tools" in conversation_rules("your tools")


def test_subscription_calls_speak_under_the_same_rules():
    wire = _wire(auth_mode="chatgpt_subscription", subscription_backend_model="chosen-model")
    assert conversation_rules("the backend") in wire["instructions"]


def test_the_executing_model_knows_the_status_board_on_every_engine():
    assert WORK_STATUS_RULE in _wire()["delegation"]["responses"]["instructions"]
    source = inspect.getsource(native.NativeLiveVoiceSession)
    assert "WORK_STATUS_RULE" in source
    assert 'conversation_rules("your tools")' in source


def test_a_brief_asks_the_agent_to_report_status_decisions_and_blockers():
    rule = AGENT_BRIEF_RULE.lower()
    assert "report back what changed" in rule
    assert "any decision the user has to make" in rule
    assert "when blocked, report that too" in rule


def test_the_prompts_leave_room_for_tools_and_history_on_small_wires():
    # One session.started message carries both prompts, the tool declarations
    # (24 kB budget) and the history seed inside a 64 KiB limit.
    wire = _wire()
    prompts = wire["instructions"] + wire["delegation"]["responses"]["instructions"]
    assert len(prompts.encode("utf-8")) < 20_000
