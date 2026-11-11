"""An owner stop on a trigger policy, or on everything, keeps triggers from acting."""

from __future__ import annotations

import pytest

from dodaios.safety.stop_hold import stop_holds
from tests.unit.lead_triggers.test_service import Harness, answer, mail

ACT = {"event": 1, "action": "act", "policy": "inv", "reason": "invoice"}


async def _decide(h: Harness) -> dict:
    h.answers.append(answer(ACT))
    await h.service.submit(mail(1))
    await h.service.process()
    return (await h.service.view())["log"][-1]


async def test_without_a_hold_the_policy_acts() -> None:
    h = Harness()
    await h.configure("auto")
    record = await _decide(h)
    assert record["outcome"] == "started" and len(h.started) == 1


@pytest.mark.parametrize(("kind", "ref"), [("trigger", "inv"), ("everything", "")])
async def test_a_hold_keeps_the_trigger_from_starting_a_job(kind: str, ref: str) -> None:
    h = Harness()
    await h.configure("auto")
    stop_holds().hold(kind, ref, reason="owner stopped it")
    record = await _decide(h)
    assert record["outcome"] == "held_by_owner"
    assert h.started == []


async def test_a_hold_on_another_policy_does_not_stop_this_one() -> None:
    h = Harness()
    await h.configure("auto")
    stop_holds().hold("trigger", "ci", reason="r")
    assert (await _decide(h))["outcome"] == "started"
