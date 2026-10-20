"""Jarvis' learning loop bills the default provider's subscription whenever it can.

Maintainer decision (2026-10-20): the loop may cost money, but when the
provider the person uses by default is signed in through its subscription,
the review runs there and not on the per-token key. Without such a login it
still reviews, on the key. Another family's subscription is never picked on
the person's behalf, and an explicit ``[memory.learning]`` provider wins.
Every call names its seat and billing mode in the learning ledger.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from dodaios.brain import background_policy
from dodaios.memory.learning import compact
from dodaios.memory.learning.loop import JarvisLearningLoop
from dodaios.memory.learning.notebook import LEDGER_NAME, JarvisNotebook
from dodaios.memory.learning.review import (
    BILLING_LOCAL,
    BILLING_METERED,
    BILLING_SUBSCRIPTION,
    ModelReviewer,
    SeatChoice,
    Turn,
)
from dodaios.society.seat_brain import Seat
from tests.fakes.fake_seat_registry import RecordingRegistry

ALL = ["openai", "gemini", "claude-api", "claude-cli", "codex", "antigravity", "ollama"]
CHANGES = '{"changes": []}'


@pytest.fixture
def registry(monkeypatch) -> RecordingRegistry:
    from dodaios.brain import resolver
    from dodaios.core import config, runtime_refs

    reg = RecordingRegistry(ALL, replies={name: CHANGES for name in ALL})
    monkeypatch.setattr(resolver, "_get_registry", lambda: reg)
    monkeypatch.setattr(config, "get_jarvis_agent_secret", lambda provider: f"agent-key-{provider}")
    monkeypatch.setattr(runtime_refs, "get_brain_manager", lambda: None)
    return reg


@pytest.fixture
def logins(monkeypatch) -> dict[str, bool]:
    """Subscription logins by provider card; anything unlisted is unknown."""
    states: dict[str, bool] = {}
    monkeypatch.setattr(background_policy, "_probe_override", states.get)
    return states


def _config(*, worker: str = "", model: str = "", provider: str = "", pinned_model: str = ""):
    return SimpleNamespace(
        brain=SimpleNamespace(
            worker=SimpleNamespace(provider=worker, model=model, reasoning_effort="")
            if worker
            else None,
            providers={},
        ),
        memory=SimpleNamespace(
            learning=SimpleNamespace(provider=provider, model=pinned_model, timeout_s=5.0)
        ),
    )


async def test_a_key_seat_reviews_on_the_same_providers_signed_in_subscription(registry, logins):
    logins["codex"] = True
    reviewer = ModelReviewer(_config(worker="openai", model="gpt-5.5"))
    assert await reviewer("{}") == []
    [built] = registry.built
    assert built.name == "codex"
    # The subscription offers the chat's model, so it is kept.
    assert built.kwargs["model"] == "gpt-5.5"
    # No key is in scope for the subscription call.
    assert registry.answered[0].secrets == {}
    assert reviewer.last_choice is not None
    assert reviewer.last_choice.billing == BILLING_SUBSCRIPTION
    assert reviewer.last_choice.ledger_fields()["runner"] == "codex-cli"


async def test_a_model_the_subscription_does_not_offer_falls_to_its_default(registry, logins):
    logins["codex"] = True
    await ModelReviewer(_config(worker="openai", model="gpt-api-only"))("{}")
    [built] = registry.built
    assert built.name == "codex"
    assert "model" not in built.kwargs


@pytest.mark.parametrize("login", [None, False])
async def test_without_a_subscription_the_review_still_runs_on_the_key(registry, logins, login):
    if login is not None:
        logins["codex"] = login
    reviewer = ModelReviewer(_config(worker="openai", model="gpt-chosen"))
    assert await reviewer("{}") == []
    assert [(b.name, b.kwargs) for b in registry.built] == [("openai", {"model": "gpt-chosen"})]
    assert registry.answered[0].secrets == {"openai": "agent-key-openai"}
    assert reviewer.last_choice.billing == BILLING_METERED


async def test_a_failing_subscription_hands_the_review_to_the_key(registry, logins):
    logins["codex"] = True
    registry.failing = frozenset({"codex"})
    reviewer = ModelReviewer(_config(worker="openai", model="gpt-5.5"))
    assert await reviewer("{}") == []
    assert registry.built_names() == ["codex", "openai"]
    assert reviewer.last_choice.billing == BILLING_METERED


async def test_a_subscription_that_cannot_be_built_hands_the_review_to_the_key(monkeypatch, logins):
    from dodaios.brain import resolver
    from dodaios.core import config, runtime_refs

    reg = RecordingRegistry(["openai"], replies={"openai": CHANGES})
    monkeypatch.setattr(resolver, "_get_registry", lambda: reg)
    monkeypatch.setattr(config, "get_jarvis_agent_secret", lambda provider: "k")
    monkeypatch.setattr(runtime_refs, "get_brain_manager", lambda: None)
    logins["codex"] = True
    assert await ModelReviewer(_config(worker="openai", model="gpt-5.5"))("{}") == []
    assert reg.built_names() == ["openai"]


async def test_another_familys_subscription_is_not_picked(registry, logins):
    logins.update({"codex": True, "claude-cli": True, "antigravity": True})
    reviewer = ModelReviewer(_config(worker="gemini", model="g-chosen"))
    await reviewer("{}")
    assert registry.built_names() == ["gemini"]
    assert reviewer.last_choice.billing == BILLING_METERED


async def test_an_explicit_learning_provider_keeps_winning(registry, logins):
    logins["codex"] = True
    cfg = _config(worker="openai", model="gpt-5.5", provider="openai", pinned_model="gpt-pin")
    reviewer = ModelReviewer(cfg)
    await reviewer("{}")
    assert [(b.name, b.kwargs) for b in registry.built] == [("openai", {"model": "gpt-pin"})]
    assert reviewer.last_choice.why == "the [memory.learning] provider"


async def test_a_subscription_seat_is_used_as_it_is(registry, logins):
    reviewer = ModelReviewer(_config(worker="codex", model="gpt-5.5"))
    await reviewer("{}")
    assert registry.built_names() == ["codex"]
    assert reviewer.last_choice.billing == BILLING_SUBSCRIPTION


async def test_a_keyless_local_seat_bills_nothing(registry, logins):
    reviewer = ModelReviewer(_config(worker="ollama", model="llama"))
    await reviewer("{}")
    assert registry.built_names() == ["ollama"]
    assert reviewer.last_choice.billing == BILLING_LOCAL


async def test_the_claude_key_tier_moves_onto_the_claude_login(registry, logins, monkeypatch):
    """The Agents tier on the Jarvis surface runs Claude on its key; the login wins."""
    from dodaios.local_models import assistant_session

    tier = SimpleNamespace(provider="claude-api", model="claude-sonnet-5-5", ready=True, reason="")
    monkeypatch.setattr(assistant_session, "agents_tier", lambda cfg: tier)
    logins["claude-cli"] = True
    reviewer = ModelReviewer(_config())
    await reviewer("{}")
    [built] = registry.built
    assert (built.name, built.kwargs["model"]) == ("claude-cli", "claude-sonnet-5-5")
    assert reviewer.last_choice.billing == BILLING_SUBSCRIPTION


async def test_compaction_follows_the_same_rule(registry, logins):
    logins["codex"] = True
    registry.replies["codex"] = '{"merged": [], "outdated": []}'
    compactor = ModelReviewer(
        _config(worker="openai", model="gpt-5.5"),
        system=compact.system_prompt,
        parser=compact.parse,
        max_tokens=compact.COMPACT_MAX_TOKENS,
        caller="learning-compaction",
    )
    assert await compactor("{}") == {"merged": [], "outdated": []}
    assert registry.built_names() == ["codex"]
    assert registry.answered[0].caller == "learning-compaction"


# ── the ledger names the seat and billing mode ─────────────────────────────


class _FakeReviewer:
    """Answers with ``replies`` in turn (``None`` = a failed review)."""

    def __init__(self, replies: list[object], choice: SeatChoice) -> None:
        self._replies = list(replies)
        self.last_choice = choice

    async def __call__(self, prompt: str) -> object:
        return self._replies.pop(0)


_SUBSCRIPTION = SeatChoice(
    Seat("openai-codex", "gpt-5.5", "codex-cli"), BILLING_SUBSCRIPTION, "subscription"
)
_FACT = "My daughter is called Mila and she is seven"


def _ledger(book: JarvisNotebook) -> list[dict[str, object]]:
    path = book.folder / LEDGER_NAME
    return [json.loads(line) for line in path.read_text("utf-8").splitlines()]


@pytest.fixture
def book(tmp_path: Path) -> JarvisNotebook:
    return JarvisNotebook(tmp_path / "vault")


async def test_a_review_ledgers_its_seat_and_billing(book):
    proposal = {
        "target": "user",
        "operation": "add",
        "text": "The user's daughter Mila is seven.",
        "evidence": _FACT,
        "importance": 8,
    }
    loop = JarvisLearningLoop(book, _FakeReviewer([[proposal]], _SUBSCRIPTION))
    loop.record("chat:1", Turn(user=_FACT))
    assert await loop.review("chat:1") == 1
    change, call = _ledger(book)
    assert change["operation"] == "add" and change["billing"] == BILLING_SUBSCRIPTION
    assert call["operation"] == "review" and call["outcome"] == "answered"
    assert call["seat"] == "openai-codex/gpt-5.5" and call["runner"] == "codex-cli"
    assert call["seat_label"] == "OpenAI Codex" and call["changes"] == 1


async def test_failed_and_dropped_reviews_are_ledgered(book):
    loop = JarvisLearningLoop(book, _FakeReviewer([None] * 4, _SUBSCRIPTION))
    loop.record("chat:1", Turn(user=_FACT))
    for _ in range(4):
        await loop.review("chat:1")
    outcomes = [row["outcome"] for row in _ledger(book)]
    assert outcomes == ["failed", "failed", "failed", "dropped"]
    assert loop.pending() == {}


def test_the_profile_shows_the_last_review_and_keeps_calls_out_of_the_list(book):
    from dodaios.ui.web import soul_routes

    book.apply(target="user", operation="add", text="The user likes tea.", evidence="I like tea")
    book.note_review(
        source="review: call ended",
        outcome="answered",
        changes=0,
        seat=_SUBSCRIPTION.ledger_fields(),
    )
    records = soul_routes._ledger_lines(book.folder)
    assert [row["operation"] for row in soul_routes._activity(records)] == ["add"]
    last = soul_routes._last_review(records)
    assert last is not None
    assert (last["outcome"], last["billing"], last["seat_label"]) == (
        "answered",
        BILLING_SUBSCRIPTION,
        "OpenAI Codex",
    )
