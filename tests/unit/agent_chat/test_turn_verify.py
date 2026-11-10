"""The lead's deterministic answer-vs-tool-log check."""

from __future__ import annotations

import pytest

from dodaios.agent_chat.turn_verify import claimed_actions, lead_loop_control, verify_answer
from dodaios.brain.loop_control import ToolRecord, VerifyRequest


def _req(answer: str, *log: ToolRecord) -> VerifyRequest:
    return VerifyRequest(user_text="do it", answer=answer, tool_log=tuple(log))


async def _ask(_system: str, _user: str) -> str:  # never called: no model is asked
    raise AssertionError("the check must not call a model")


async def test_a_claim_without_any_tool_is_sent_back_once() -> None:
    out = await verify_answer(_req("I sent the email to Laura."), _ask)
    assert not out.accepted and "sent" in out.detail
    assert "run the missing tool" in out.instruction


async def test_a_claim_backed_by_a_matching_successful_tool_is_accepted() -> None:
    out = await verify_answer(
        _req("I sent the email.", ToolRecord("gmail_send_message", ok=True)), _ask
    )
    assert out.accepted


async def test_a_failed_or_blocked_tool_does_not_back_a_claim() -> None:
    out = await verify_answer(
        _req(
            "I sent the email.",
            ToolRecord("gmail_send_message", ok=False),
            ToolRecord("slack_post", ok=True, blocked=True),
        ),
        _ask,
    )
    assert not out.accepted and "gmail_send_message" in out.instruction


async def test_german_claims_are_caught() -> None:
    out = await verify_answer(_req("Ich habe die Datei gelöscht."), _ask)  # i18n-allow
    assert not out.accepted


@pytest.mark.parametrize(
    "answer",
    [
        "Here is what I found: the report is ready for you.",
        "Should I send it to Laura?",
        "The email was not sent because the tool failed.",
        "",
    ],
)
async def test_plain_answers_are_accepted(answer: str) -> None:
    assert (await verify_answer(_req(answer), _ask)).accepted


def test_claim_families() -> None:
    assert claimed_actions("I have deleted it and I started the build") == ["deleted", "started"]


def test_the_lead_control_asks_for_one_revision_and_carries_the_inbox() -> None:
    control = lead_loop_control(lambda: ["x"])
    assert control.max_verify == 1 and control.verify is verify_answer
    assert list(control.drain_steer()) == ["x"]
