"""One definition of the lead's seat, and a loud (but single) configuration failure.

The learning review runs on the seat the lead conversation answers on. A spent
usage limit, a rejected key or a signed-out login is a configuration fault: the
turns stay pending and ONE written notice tells the person which seat stopped.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from dodaios.agent_chat.service import AgentChatService
from dodaios.agent_chat.store import AgentChatStore, ChatSelection
from dodaios.brain import background_policy
from dodaios.memory.learning import loop as loop_module
from dodaios.memory.learning.loop import JarvisLearningLoop
from dodaios.memory.learning.notebook import JarvisNotebook
from dodaios.memory.learning.review import (
    BILLING_SUBSCRIPTION,
    CAUSE_AUTH,
    CAUSE_BILLING,
    CAUSE_LOGGED_OUT,
    CAUSE_TRANSIENT,
    CAUSE_USAGE_LIMIT,
    ReviewFailure,
    SeatChoice,
    Turn,
    classify_failure,
    health_sentence,
    seat_choices,
)
from dodaios.society.seat_brain import Seat, jarvis_seat

_FACT = "My daughter is called Mila and she is seven"
_SEAT = Seat("openai-codex", "gpt-5.5", "codex-cli")
_CHOICE = SeatChoice(_SEAT, BILLING_SUBSCRIPTION, "subscription")


def _config(worker: str = "openai-codex"):
    return SimpleNamespace(
        brain=SimpleNamespace(
            worker=SimpleNamespace(provider=worker, model="", reasoning_effort=""),
            providers={},
        ),
        memory=SimpleNamespace(learning=SimpleNamespace(provider="", model="", timeout_s=5.0)),
    )


# -- one definition of the lead's seat ------------------------------------


def test_the_review_seat_is_the_lead_chat_seat(tmp_path: Path, monkeypatch) -> None:
    from dodaios.agent_chat import lead
    from dodaios.society import runtime

    svc = AgentChatService(
        AgentChatStore(":memory:"),
        assistant_name=lambda: "Dodaios",
        default_cwd=lambda: str(tmp_path),
    )
    svc.store.save_chat_selection(ChatSelection("openai", "gpt-lead", "high"))
    assert svc.lead_session() is not None
    monkeypatch.setattr(
        runtime, "current_runtime", lambda: SimpleNamespace(chat_service=lambda: svc)
    )
    monkeypatch.setattr(background_policy, "_probe_override", {}.get)

    chat = lead.lead_seat(svc)
    assert chat is not None
    assert (chat["provider"], chat["model"], chat["effort"]) == ("openai", "gpt-lead", "high")
    # [brain.worker] sits on another provider; the lead conversation wins.
    seat = jarvis_seat(_config(worker="openai-codex"))
    assert (seat.provider, seat.model, seat.runner, seat.effort) == (
        chat["provider"],
        chat["model"],
        chat["runner"],
        "high",
    )
    assert seat_choices(_config(worker="openai-codex"))[-1].seat == seat
    assert not hasattr(lead, "chat_seat")


def test_without_a_lead_session_the_agents_selection_is_the_fallback(monkeypatch) -> None:
    from dodaios.society import runtime

    monkeypatch.setattr(runtime, "current_runtime", lambda: None)
    assert jarvis_seat(_config(worker="openai")).provider == "openai"


# -- classifying failures --------------------------------------------------


@pytest.mark.parametrize(
    ("exc", "cause"),
    [
        (
            RuntimeError(
                "Codex (ChatGPT login) returned no answer: You have hit your usage limit. "
                "Upgrade to Plus"
            ),
            CAUSE_USAGE_LIMIT,
        ),
        (RuntimeError("HTTP 401 Unauthorized"), CAUSE_AUTH),
        (RuntimeError("Incorrect API key provided"), CAUSE_AUTH),
        (RuntimeError("no api key configured for this seat"), CAUSE_AUTH),
        (RuntimeError("Not logged in. Please run /login"), CAUSE_LOGGED_OUT),
        (RuntimeError("You exceeded your current quota, insufficient_quota"), CAUSE_BILLING),
        (TimeoutError(), CAUSE_TRANSIENT),
        (RuntimeError("overloaded, try again"), CAUSE_TRANSIENT),
    ],
)
def test_failures_are_sorted_into_configuration_and_transient(exc, cause) -> None:
    failure = classify_failure(exc, _CHOICE)
    assert failure.cause == cause
    assert failure.configuration == (cause != CAUSE_TRANSIENT)
    assert (failure.provider, failure.model) == ("openai-codex", "gpt-5.5")


def test_the_notice_names_the_seat_and_the_fix() -> None:
    text = health_sentence(ReviewFailure(CAUSE_USAGE_LIMIT, "openai-codex", "gpt-5.5"))
    assert "gpt-5.5" in text and "allowance" in text and "[memory.learning]" in text
    signed_out = health_sentence(ReviewFailure(CAUSE_LOGGED_OUT, "claude-api", ""))
    assert "signed out" in signed_out and "Sign in again" in signed_out


# -- the loop --------------------------------------------------------------


class _Reviewer:
    """Fails with ``failure`` until told to answer."""

    def __init__(self, failure: ReviewFailure | None) -> None:
        self.failure = failure
        self.last_choice = _CHOICE
        self.last_failure: ReviewFailure | None = None
        self.answer = False

    async def __call__(self, prompt: str):
        if self.answer:
            self.last_failure = None
            return []
        self.last_failure = self.failure
        return None


@pytest.fixture
def notices(monkeypatch) -> list[dict[str, str]]:
    posted: list[dict[str, str]] = []

    async def fake_post(text: str, *, provider: str = "", cause: str = "") -> bool:
        posted.append({"text": text, "provider": provider, "cause": cause})
        return True

    from dodaios.agent_chat import lead

    monkeypatch.setattr(lead, "post_memory_health", fake_post)
    return posted


@pytest.fixture
def book(tmp_path: Path) -> JarvisNotebook:
    return JarvisNotebook(tmp_path / "vault")


async def test_a_configuration_fault_keeps_the_turns_and_posts_one_notice(book, notices) -> None:
    reviewer = _Reviewer(ReviewFailure(CAUSE_USAGE_LIMIT, "openai-codex", "gpt-5.5"))
    loop = JarvisLearningLoop(book, reviewer)
    loop.record("chat:1", Turn(user=_FACT))
    for _ in range(loop_module._MAX_FAILURES + 3):
        await loop.review("chat:1")
    assert loop.pending() == {"chat:1": 1}  # never dropped while the cause is configuration
    assert len(notices) == 1
    assert notices[0]["cause"] == CAUSE_USAGE_LIMIT and "gpt-5.5" in notices[0]["text"]


async def test_a_new_cause_posts_again_and_recovery_rearms(book, notices) -> None:
    reviewer = _Reviewer(ReviewFailure(CAUSE_USAGE_LIMIT, "openai-codex", "gpt-5.5"))
    loop = JarvisLearningLoop(book, reviewer)
    loop.record("chat:1", Turn(user=_FACT))
    await loop.review("chat:1")
    await loop.review("chat:1")
    reviewer.failure = ReviewFailure(CAUSE_AUTH, "openai-codex", "gpt-5.5")
    await loop.review("chat:1")
    assert [n["cause"] for n in notices] == [CAUSE_USAGE_LIMIT, CAUSE_AUTH]
    reviewer.answer = True
    await loop.review("chat:1")
    assert loop.pending() == {}
    reviewer.answer = False
    loop.record("chat:1", Turn(user=_FACT))
    await loop.review("chat:1")
    assert [n["cause"] for n in notices] == [CAUSE_USAGE_LIMIT, CAUSE_AUTH, CAUSE_AUTH]


async def test_transient_failures_keep_the_old_retry_and_drop(book, notices) -> None:
    reviewer = _Reviewer(ReviewFailure(CAUSE_TRANSIENT, "openai-codex", "gpt-5.5"))
    loop = JarvisLearningLoop(book, reviewer)
    loop.record("chat:1", Turn(user=_FACT))
    for _ in range(loop_module._MAX_FAILURES):
        await loop.review("chat:1")
    assert loop.pending() == {}
    assert notices == []


async def test_a_failed_post_is_retried_on_the_next_failure(book, monkeypatch) -> None:
    from dodaios.agent_chat import lead

    calls: list[str] = []

    async def no_conversation(text: str, **kwargs) -> bool:
        calls.append(text)
        return False

    monkeypatch.setattr(lead, "post_memory_health", no_conversation)
    reviewer = _Reviewer(ReviewFailure(CAUSE_AUTH, "openai-codex", "gpt-5.5"))
    loop = JarvisLearningLoop(book, reviewer)
    loop.record("chat:1", Turn(user=_FACT))
    await loop.review("chat:1")
    await loop.review("chat:1")
    assert len(calls) == 2
