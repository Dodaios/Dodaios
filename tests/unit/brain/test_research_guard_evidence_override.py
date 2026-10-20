"""The research-intent guard must yield to an explicit evidence-gate mandate.

Bug (trace 5edf0245): "Vergleiche mir mal, was ich diesen Monat bei Google
Cloud ... verbraucht habe" fires BOTH the evidence gate (mandates cli_gcloud
for the `cloud` domain) AND the research guard (blocks any cli_* action tool
because "Vergleiche" is a research keyword). The two deterministic rules
collide; the only reachable outcome was the honesty fallback ("couldn't
retrieve it"). The more specific rule -- the evidence mandate, which named a
concrete tool for THIS turn -- must win over the generic keyword guard, but
ONLY for that exact tool (other action tools stay blocked under research).
"""
from __future__ import annotations

from dodaios.brain.tool_use_loop import _should_block_action_as_research

_RESEARCH = "Vergleiche mir mal, was ich bei Google Cloud verbraucht habe"


class _FakeTool:
    def __init__(self, name: str) -> None:
        self.name = name


def test_action_tool_blocked_under_research_without_mandate() -> None:
    # Baseline (unchanged behaviour): research keyword + cli_ tool, no mandate.
    tool = _FakeTool("cli_gcloud")
    assert _should_block_action_as_research(
        tool, "cli_gcloud", _RESEARCH, "deep", evidence_required_tool=""
    ) is True


def test_evidence_mandate_overrides_research_guard_for_that_tool() -> None:
    # The fix: the exact tool the evidence gate mandated is NOT blocked, even
    # though "Vergleiche" is a research keyword.
    tool = _FakeTool("cli_gcloud")
    assert _should_block_action_as_research(
        tool, "cli_gcloud", _RESEARCH, "deep", evidence_required_tool="cli_gcloud"
    ) is False


def test_override_is_tool_specific_other_tools_still_blocked() -> None:
    # A DIFFERENT cli tool stays blocked under research — the override is
    # scoped to the mandated tool only.
    tool = _FakeTool("cli_aws")
    assert _should_block_action_as_research(
        tool, "cli_aws", _RESEARCH, "deep", evidence_required_tool="cli_gcloud"
    ) is True


def test_non_research_utterance_not_blocked() -> None:
    tool = _FakeTool("cli_gcloud")
    assert _should_block_action_as_research(
        tool, "cli_gcloud", "liste meine Projekte", "fast", evidence_required_tool=""
    ) is False


def test_non_action_tool_never_blocked() -> None:
    # search_web is not an action tool (no cli_ prefix, no is_action_tool flag).
    tool = _FakeTool("search_web")
    assert _should_block_action_as_research(
        tool, "search_web", _RESEARCH, "deep", evidence_required_tool=""
    ) is False


class _FakeActionTool(_FakeTool):
    is_action_tool = True


def test_handoff_to_an_own_agent_is_never_blocked_as_research() -> None:
    # Live 2026-10-20: "Create an agent named Vega whose job is web research,
    # then ask Vega to introduce itself" had every message_agent /
    # delegate_to_agent call denied as research, and the lead then made up
    # the agent's answer. Handing work to one of the user's own agents is not a
    # query against a connected system.
    utterance = "Ask Vega, the web research agent, to introduce itself"
    for name in ("message_agent", "delegate_to_agent", "ask_agent"):
        assert _should_block_action_as_research(
            _FakeActionTool(name), name, utterance, "deep", evidence_required_tool=""
        ) is False
    assert _should_block_action_as_research(
        _FakeActionTool("cli_gcloud"), "cli_gcloud", utterance, "deep",
        evidence_required_tool="",
    ) is True
