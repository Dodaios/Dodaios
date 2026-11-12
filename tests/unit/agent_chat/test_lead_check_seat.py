"""The seat unattended lead routines are pinned to when no global model pick exists."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from dodaios.agent_chat import proactive_checks
from dodaios.society import routine_runner


def _runtime(session: Any) -> Any:
    service = SimpleNamespace(store=SimpleNamespace())
    return SimpleNamespace(config=lambda: object(), chat_service=lambda: service), service


@pytest.fixture
def no_global_pick(monkeypatch: pytest.MonkeyPatch) -> None:
    async def none(_cfg: Any) -> None:
        return None

    monkeypatch.setattr(routine_runner, "_subscription_seat", none)


def _conversation(monkeypatch: pytest.MonkeyPatch, session: Any) -> None:
    from dodaios.agent_chat import lead

    monkeypatch.setattr(lead, "lead_session", lambda _svc, **_kw: session)


def _seats(monkeypatch: pytest.MonkeyPatch, *, mapped: Any, billed: bool) -> None:
    from dodaios.core import task_agent

    async def seat(_provider: str) -> Any:
        return mapped

    monkeypatch.setattr(task_agent, "subscription_seat_off_loop", seat)
    monkeypatch.setattr(routine_runner, "_billed_via_api", lambda *_a, **_kw: billed)


async def test_the_global_subscription_seat_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    async def picked(_cfg: Any) -> tuple[str, str, str]:
        return "claude-api", "fable", "high"

    monkeypatch.setattr(routine_runner, "_subscription_seat", picked)
    runtime, _ = _runtime(None)
    lead = SimpleNamespace(provider="")
    assert await proactive_checks._seat_for_checks(runtime, lead) == {
        "provider": "claude-api", "model": "fable", "effort": "high",
    }


async def test_without_a_pick_the_conversations_subscription_seat_is_used(
    monkeypatch: pytest.MonkeyPatch, no_global_pick: None
) -> None:
    session = SimpleNamespace(provider="claude-api", model="", effort="high", account_id="")
    _conversation(monkeypatch, session)
    _seats(monkeypatch, mapped=("claude-api", "claude-cli"), billed=False)
    runtime, _ = _runtime(session)
    seat = await proactive_checks._seat_for_checks(runtime, SimpleNamespace(provider=""))
    assert seat == {"provider": "claude-api", "model": "", "effort": "high"}


async def test_a_conversation_on_an_api_key_is_not_used(
    monkeypatch: pytest.MonkeyPatch, no_global_pick: None
) -> None:
    session = SimpleNamespace(provider="openai", model="gpt", effort="", account_id="")
    _conversation(monkeypatch, session)
    _seats(monkeypatch, mapped=None, billed=True)
    runtime, _ = _runtime(session)
    assert await proactive_checks._seat_for_checks(runtime, SimpleNamespace(provider="")) == {}


async def test_a_lead_with_its_own_provider_keeps_it(
    monkeypatch: pytest.MonkeyPatch, no_global_pick: None
) -> None:
    session = SimpleNamespace(provider="claude-api", model="", effort="", account_id="")
    _conversation(monkeypatch, session)
    _seats(monkeypatch, mapped=("claude-api", "claude-cli"), billed=False)
    runtime, _ = _runtime(session)
    assert await proactive_checks._seat_for_checks(runtime, SimpleNamespace(provider="codex")) == {}


async def test_no_conversation_and_an_unreadable_one_mean_no_seat(
    monkeypatch: pytest.MonkeyPatch, no_global_pick: None
) -> None:
    _conversation(monkeypatch, None)
    runtime, _ = _runtime(None)
    lead = SimpleNamespace(provider="")
    assert await proactive_checks._seat_for_checks(runtime, lead) == {}
    broken = SimpleNamespace(config=lambda: object())  # no chat service at all
    assert await proactive_checks._seat_for_checks(broken, lead) == {}
