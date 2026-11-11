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


@pytest.mark.parametrize(("kind", "ref"), [("trigger", "inv"), ("trigger", "*"), ("everything", "")])
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


# --- direct delivery to a subscribed job ------------------------------------------------------


def _owned_sub():
    from dodaios.lead_triggers.subscriptions import Subscription

    return Subscription(
        source="mail", thread_key="t1", job_id="job-1", kind="society_assignment",
        target="agent-1", mandate={"policy_id": "inv"},
    )


@pytest.mark.parametrize(
    ("kind", "ref", "blocked"),
    [
        ("everything", "", True),
        ("trigger", "inv", True),
        ("trigger", "*", True),
        ("job", "job-1", True),
        ("agent", "agent-1", True),
        ("job", "job-2", False),
        ("agent", "agent-2", False),
        ("trigger", "ci", False),
    ],
)
def test_delivery_hold_follows_the_stop_scopes(kind: str, ref: str, blocked: bool) -> None:
    from dodaios.lead_triggers.wiring import _delivery_held

    sub = _owned_sub()
    assert _delivery_held(sub) is False
    stop_holds().hold(kind, ref, reason="owner stopped it")
    assert _delivery_held(sub) is blocked
    stop_holds().release(kind, ref)
    assert _delivery_held(sub) is False


# --- pollers -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "ref", "paused"),
    [
        ("everything", "", True),
        ("trigger", "*", True),
        ("trigger", "inv", False),
        ("job", "job-1", False),
        ("agent", "agent-1", False),
        ("routine", "r1", False),
    ],
)
def test_pollers_pause_on_everything_or_trigger_and_resume_when_lifted(
    kind: str, ref: str, paused: bool
) -> None:
    from dodaios.lead_triggers import wiring

    assert wiring._held() is False
    stop_holds().hold(kind, ref, reason="owner stopped it")
    assert wiring._held() is paused
    stop_holds().release(kind, ref)
    assert wiring._held() is False
