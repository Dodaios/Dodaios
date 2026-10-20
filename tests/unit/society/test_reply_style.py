"""Agent-specific API and CLI briefings retain conversational reply guidance."""

import pytest

from dodaios.agent_chat.dodaios_harness import Identity, compact_identity, identity_prompt
from dodaios.agent_chat.runner_cli import _with_identity
from dodaios.core.response_style import (
    CONVERSATIONAL_RESPONSE_STYLE,
    CONVERSATIONAL_TURN_REMINDER,
    KEEP_GOING_ON_TOOL_FAILURE,
)
from dodaios.society.roster import AgentRecord
from dodaios.society.surface import build_briefing


def _briefing(extra: str = "") -> str:
    agent = AgentRecord.from_row(
        {
            "agent_id": "reply-style-test",
            "name": "Research assistant",
            "tier": "specialist",
            "description": "Explain findings simply. Ask before publishing anything." + extra,
        }
    )
    return build_briefing(agent, [], [agent])


def test_agent_briefing_includes_reply_style_without_replacing_its_instructions() -> None:
    briefing = _briefing()
    assert CONVERSATIONAL_RESPONSE_STYLE in briefing
    assert KEEP_GOING_ON_TOOL_FAILURE in briefing
    assert "Ask before publishing anything." in briefing
    assert "You are Research assistant" in briefing
    assert "end with a handoff" not in briefing


async def test_cli_identity_sends_the_reply_policy_once() -> None:
    for resume in (None, "existing-vendor-session"):
        identity = await identity_prompt(
            user_text="Explain the result.", history=[], resume=resume, prompt_override=_briefing()
        )
        assert CONVERSATIONAL_RESPONSE_STYLE in identity
        assert CONVERSATIONAL_RESPONSE_STYLE in compact_identity(identity)
        seat = Identity(
            session_id="society:reply-style-test",
            text=identity + "\nStored credentials: none.",
            compact=compact_identity(identity),
        )
        delivered = _with_identity("Explain the result.", seat, resume)
        if resume:
            # The resumed vendor conversation already holds the fresh identity.
            assert CONVERSATIONAL_TURN_REMINDER not in delivered
            assert KEEP_GOING_ON_TOOL_FAILURE not in delivered
            assert "Stored credentials: none.\n</jarvis_turn_context>" in delivered
        else:
            assert CONVERSATIONAL_RESPONSE_STYLE in delivered
            assert KEEP_GOING_ON_TOOL_FAILURE in delivered
        assert delivered.endswith("Explain the result.")


async def test_reply_policy_survives_long_instructions_in_a_compact_cli_identity() -> None:
    identity = await identity_prompt(
        user_text="Explain the result.",
        history=[],
        resume=None,
        prompt_override=_briefing("\nDetailed domain context." * 1000),
    )
    compact = compact_identity(identity)
    assert len(compact) < len(identity)
    assert CONVERSATIONAL_RESPONSE_STYLE in compact
    assert KEEP_GOING_ON_TOOL_FAILURE in compact


@pytest.mark.parametrize("resume", [None, "existing-vendor-session"])
@pytest.mark.parametrize("compact", [False, True])
async def test_cli_keeps_explicit_detail_requests_with_the_shared_default(resume, compact) -> None:
    request = "Explain each step in detail, include the full code, and answer in Spanish."
    prompt = await identity_prompt(
        user_text=request, history=[], resume=resume, prompt_override=_briefing()
    )
    seat = Identity(
        session_id="society:reply-style-test", text=prompt, compact=compact_identity(prompt)
    )
    delivered = _with_identity(request, seat, resume, compact=compact)
    if resume is None:
        assert CONVERSATIONAL_TURN_REMINDER in delivered
    assert delivered.endswith(request)
    assert "think longer and go deeper" not in delivered
