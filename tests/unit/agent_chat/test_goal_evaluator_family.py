"""/goal's evaluator runs on another model family than the worker when one is connected."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from dodaios.agent_chat import control_eval
from dodaios.agent_chat.control_types import GoalVerdict
from dodaios.brain import background_policy


@pytest.fixture(autouse=True)
def _policy():
    background_policy.reset_for_tests()
    yield
    background_policy.reset_for_tests()


@dataclass
class _Session:
    provider: str
    model: str = "m"
    vendor_session: str | None = "v"
    session_id: str = "s1"
    surface: str = "jarvis"


def _session(provider: str = "claude-api") -> Any:
    return _Session(provider)


def test_a_connected_key_of_another_family_is_picked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(background_policy, "_probe_override", lambda _p: None)
    monkeypatch.setattr(
        "dodaios.core.config.get_jarvis_agent_secret",
        lambda provider: "key" if provider == "openai" else None,
    )
    pick = control_eval.pick_evaluator(_session("claude-api"))
    assert pick is not None and pick[0] == "openai"


def test_the_workers_own_family_is_never_picked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(background_policy, "_probe_override", lambda _p: None)
    monkeypatch.setattr(
        "dodaios.core.config.get_jarvis_agent_secret",
        lambda provider: "key" if provider == "claude-api" else None,
    )
    assert control_eval.pick_evaluator(_session("claude-api")) is None


def test_a_subscription_install_never_bills_another_familys_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A subscription is connected: background work must not fall onto a key.
    monkeypatch.setattr(background_policy, "_probe_override", lambda p: p == "claude-cli")
    background_policy.note_connected("claude-cli")
    monkeypatch.setattr("dodaios.core.config.get_jarvis_agent_secret", lambda _p: "key")
    pick = control_eval.pick_evaluator(_session("gemini"))
    assert pick is None or pick[0] != "openai"


async def test_the_evaluation_uses_the_other_family_and_falls_back_with_a_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[str] = []

    async def fake(session: Any, *_a: Any, **_k: Any) -> GoalVerdict:
        seen.append(session.provider)
        if session.provider == "openai":
            raise RuntimeError("provider down")
        return GoalVerdict(status="continue", reason="more work")

    monkeypatch.setattr(control_eval, "_evaluate", fake)
    monkeypatch.setattr(control_eval, "pick_evaluator", lambda _s: ("openai", ""))
    verdict = await control_eval.evaluate_goal(_session("claude-api"), "goal", [])
    assert seen == ["openai", "claude-api"]
    assert "same model family" in verdict.reason

    seen.clear()

    async def ok(session: Any, *_a: Any, **_k: Any) -> GoalVerdict:
        seen.append(session.provider)
        return GoalVerdict(status="complete", reason="done", evidence=["1"])

    monkeypatch.setattr(control_eval, "_evaluate", ok)
    verdict = await control_eval.evaluate_goal(_session("claude-api"), "goal", [])
    assert seen == ["openai"] and "same model family" not in verdict.reason


async def test_no_other_family_means_the_same_family_with_a_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def ok(session: Any, *_a: Any, **_k: Any) -> GoalVerdict:
        return GoalVerdict(status="continue", reason="more")

    monkeypatch.setattr(control_eval, "_evaluate", ok)
    monkeypatch.setattr(control_eval, "pick_evaluator", lambda _s: None)
    verdict = await control_eval.evaluate_goal(_session(), "goal", [])
    assert "no other family is connected" in verdict.reason
