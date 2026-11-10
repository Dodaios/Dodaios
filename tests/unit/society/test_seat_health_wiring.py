"""Seat health at the edges: preflight, scheduler veto, routine wait, lead notice."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dodaios.agent_chat import seat_outcomes
from dodaios.brain import seat_health as sh
from dodaios.core.protocols import RoutineDeferred, current_started_by_user
from dodaios.society import routine_runner
from dodaios.society.events import MsgType, SocietyEnvelope, Tier
from dodaios.society.failure_reasons import FailureReason
from dodaios.society.roster import Roster
from dodaios.society.scheduler import SocietyScheduler
from dodaios.society.seat_preflight import preflight_seat
from dodaios.society.store import SocietyStore


def _catalog(ids: set[str] | None):
    return lambda _provider, _account: ids


# -- preflight ---------------------------------------------------------------
async def test_preflight_passes_a_healthy_seat() -> None:
    assert await preflight_seat("codex-cli", "gpt-5.5", catalog=_catalog({"gpt-5.5"})) is None
    assert await preflight_seat("", "x") is None


async def test_preflight_refuses_a_model_missing_from_the_live_catalog() -> None:
    problem = await preflight_seat("codex-cli", "gpt-9", catalog=_catalog({"gpt-5.5"}))
    assert problem is not None
    assert problem.cls == sh.CLASS_MODEL
    assert "gpt-9" in problem.text


async def test_preflight_treats_an_unknown_catalog_as_fine() -> None:
    assert await preflight_seat("codex-cli", "gpt-9", catalog=_catalog(None)) is None

    def boom(_provider: str, _account: str) -> set[str]:
        raise RuntimeError("cli missing")

    assert await preflight_seat("codex-cli", "gpt-9", catalog=boom) is None


async def test_preflight_refuses_a_signed_out_subscription(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("dodaios.brain.background_policy.subscription_capable", lambda _p: True)
    problem = await preflight_seat("codex-cli", "", login=lambda _p: False)
    assert problem is not None
    assert problem.reason is FailureReason.AUTH_FAILED
    assert await preflight_seat("codex-cli", "", login=lambda _p: None) is None


async def test_preflight_reads_the_health_verdict_without_calling_anything() -> None:
    sh.get_seat_health().record_failure("claude", "", "usage limit reached, try again in 2h")
    problem = await preflight_seat("claude", "opus")
    assert problem is not None
    assert problem.reason is FailureReason.PROVIDER_QUOTA_LIMIT
    assert "usable again" in problem.text


# -- the scheduler fails a doomed assignment fast ----------------------------
async def test_scheduler_vetoes_an_assignment_on_a_dead_seat(tmp_path: Path) -> None:
    store = SocietyStore(tmp_path / "society.db")
    await store.open()
    roster = Roster(store)
    await roster.create(name="Jarvis", tier=Tier.LEAD)
    await roster.create(name="Scout", provider="claude", model="opus")
    await roster.create(name="Plain")
    calls: list[str] = []

    async def dispatch(target: Any, _env: Any) -> str:
        calls.append(target.agent_id)
        return f"run-{len(calls)}"

    scheduler = SocietyScheduler(
        store, roster, dispatch=dispatch, preflight=preflight_seat
    ).attach()
    sh.get_seat_health().record_failure("claude", "", "401 invalid api key")

    def assign(to: str, trace: str) -> SocietyEnvelope:
        return SocietyEnvelope(
            msg_type=MsgType.ASSIGN, from_agent="jarvis", to_agent=to,
            trace_id=trace, payload={"text": "do it"},
        )

    await store.append_and_publish(assign("scout", "t1"))
    await store.append_and_publish(assign("plain", "t2"))  # no seat of its own: unaffected
    scheduler.detach()
    assert calls == ["plain"]
    vetoes = [
        e.payload["reason"]
        for e in await store.events_for_trace("t1")
        if e.msg_type is MsgType.VETO
    ]
    assert vetoes == [str(FailureReason.AUTH_FAILED)]
    await store.close()


# -- routines wait instead of burning attempts -------------------------------
async def test_an_unattended_routine_waits_on_a_cooling_seat() -> None:
    sh.get_seat_health().record_failure("claude", "", "usage limit reached, try again in 2h")
    with pytest.raises(routine_runner.SeatCooling) as raised:
        await routine_runner._gate_on_seat_health("claude", "opus", "", autonomous=False)
    assert raised.value.code == "seat_cooldown"
    assert raised.value.provider == "claude"
    with pytest.raises(RoutineDeferred):
        await routine_runner._gate_on_seat_health("claude", "opus", "", autonomous=True)


async def test_run_now_fails_fast_with_the_readable_cause() -> None:
    sh.get_seat_health().record_failure("claude", "", "usage limit reached, try again in 2h")
    token = current_started_by_user.set(True)
    try:
        with pytest.raises(RuntimeError, match="not usable"):
            await routine_runner._gate_on_seat_health("claude", "opus", "", autonomous=False)
    finally:
        current_started_by_user.reset(token)


async def test_a_healthy_seat_runs() -> None:
    await routine_runner._gate_on_seat_health("claude", "opus", "", autonomous=False)


# -- the lead notice ---------------------------------------------------------
class _Store:
    def __init__(self, session: Any) -> None:
        self._session = session

    def get_session(self, _session_id: str) -> Any:
        return self._session


def _service(provider: str = "codex-cli") -> Any:
    session = SimpleNamespace(provider=provider, model="m", account_id="")
    return SimpleNamespace(store=_Store(session))


def _finished(error: str | None, status: str = "error") -> dict[str, Any]:
    return {"kind": "turn_finished", "payload": {"turn_id": "t", "status": status, "error": error}}


async def test_three_same_class_failures_post_one_notice(monkeypatch: pytest.MonkeyPatch) -> None:
    posted: list[sh.SeatFailure] = []

    async def fake_post(_session_id: str, _provider: str, failure: sh.SeatFailure) -> None:
        posted.append(failure)

    monkeypatch.setattr(seat_outcomes, "_post_notice", fake_post)
    svc = _service()
    for _ in range(5):
        seat_outcomes.observe_turn_finished(svc, "society:scout", _finished("usage limit reached"))
    await asyncio.sleep(0)
    assert len(posted) == 1
    assert posted[0].cls == sh.CLASS_QUOTA and posted[0].streak == 3


async def test_other_chats_and_cancelled_turns_never_post(monkeypatch: pytest.MonkeyPatch) -> None:
    posted: list[Any] = []

    async def fake_post(*args: Any) -> None:
        posted.append(args)

    monkeypatch.setattr(seat_outcomes, "_post_notice", fake_post)
    svc = _service()
    for _ in range(4):
        seat_outcomes.observe_turn_finished(svc, "thread:1", _finished("usage limit reached"))
        seat_outcomes.observe_turn_finished(svc, "society:x", _finished(None, "cancelled"))
    await asyncio.sleep(0)
    assert posted == []
    # The seat still learned from the non-society chat.
    assert sh.get_seat_health().verdict("codex-cli", "") is not None


async def test_a_good_turn_clears_the_seat() -> None:
    svc = _service()
    seat_outcomes.observe_turn_finished(svc, "thread:1", _finished("usage limit reached"))
    seat_outcomes.observe_turn_finished(svc, "thread:1", _finished(None, "done"))
    assert sh.get_seat_health().verdict("codex-cli", "") is None


def test_the_notice_names_the_cause_and_the_fix_paths() -> None:
    failure = sh.SeatFailure(sh.CLASS_AUTH, 0.0, 3, True)
    payload = seat_outcomes.notice_payload("Scout", "a1", "codex-cli", failure)
    assert payload["kind"] == "seat_trouble"
    assert "login or key was rejected" in payload["text"]
    assert "Nothing was switched" in payload["text"]
    assert {f["section"] for f in payload["fixes"]} == {"apikeys", "agents"}
    quota = seat_outcomes.notice_payload(
        "Scout", "a1", "codex-cli", sh.SeatFailure(sh.CLASS_QUOTA, 1.0e9, 3, True)
    )
    assert "usable again around" in quota["text"]


async def test_the_notice_lands_in_the_lead_conversation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[tuple[Any, dict[str, Any]]] = []

    class Runtime:
        lead_id = "lead"
        roster = SimpleNamespace(
            snapshot=lambda: [
                SimpleNamespace(agent_id="lead", name="Jarvis", session_id="lead-s", tier="lead"),
                SimpleNamespace(agent_id="a1", name="Scout", session_id="society:scout",
                                tier="specialist"),
            ]
        )

        async def post_chat_notice(self, agent: Any, payload: dict[str, Any]) -> None:
            sent.append((agent, payload))

    monkeypatch.setattr("dodaios.society.runtime.current_runtime", lambda: Runtime())
    monkeypatch.setattr("dodaios.society.display_name.display_name", lambda a: a.name)
    await seat_outcomes._post_notice(
        "society:scout", "codex-cli", sh.SeatFailure(sh.CLASS_MODEL, 0.0, 3, True)
    )
    assert len(sent) == 1
    assert sent[0][0].agent_id == "lead"
    assert sent[0][1]["agent_name"] == "Scout"
