"""A plan-seat primary is never stood in for by another account.

A signed-in subscription card without a key slot (``provider_billing`` ==
``subscription``) answers on the user's own plan. When it fails, the work
fails or waits: no other subscription CLI, gateway key or vendor key takes
over on its own: not in the resolver chain, not in the chat fallback chain,
not in background work. Keyless local runtimes may still follow it, and a
non-seat primary keeps its cross-family tail (AP-22).
"""

from __future__ import annotations

import pytest

import jarvis.core.config as cfg_mod
from jarvis.brain import background_policy, resolver
from jarvis.core.config import BrainConfig, BrainTierConfig, JarvisConfig
from jarvis.ui.web.provider_spec import PROVIDERS, provider_billing

KEYED = ("openrouter", "openai", "claude-api", "gemini")


def _seat_id() -> str:
    """A plan-seat card that can be the main brain, found by capability."""
    from jarvis.brain.manager import SUBAGENT_ONLY_BRAIN_PROVIDERS

    for spec in PROVIDERS:
        if (
            spec.tier == "brain"
            and provider_billing(spec) == "subscription"
            and spec.id not in SUBAGENT_ONLY_BRAIN_PROVIDERS
        ):
            return spec.id
    pytest.skip("no subscription-billed brain card ships")


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch):
    """Every keyed family holds a test key; every OAuth login is present."""
    resolver._reset_for_tests()
    background_policy.reset_for_tests()
    monkeypatch.setattr(
        cfg_mod, "get_provider_secret", lambda pid: "sk-test" if pid in KEYED else None
    )
    import jarvis.brain.manager as manager

    monkeypatch.setattr(manager, "_keyless_provider_is_rescued_by_oauth", lambda pid: True)
    yield
    resolver._reset_for_tests()
    background_policy.reset_for_tests()


def test_seat_bound_follows_the_card_billing() -> None:
    assert background_policy.seat_bound(_seat_id())
    for spec in PROVIDERS:
        if spec.tier == "brain" and provider_billing(spec) != "subscription":
            assert not background_policy.seat_bound(spec.id)
    assert not background_policy.seat_bound(None)
    assert not background_policy.seat_bound("no-such-provider")


def test_resolver_chain_keeps_only_the_seat_and_local_runtimes() -> None:
    seat = _seat_id()
    config = JarvisConfig(
        brain=BrainConfig(
            primary=seat,
            local_fallback="claude-api",
            worker=BrainTierConfig(
                provider="openai-codex", fallback_provider="claude-api"
            ),
        )
    )

    providers = [p for p, _ in resolver._resolve_chain(config)]

    assert providers[0] == seat
    assert all(p == seat or background_policy.keyless_local(p) for p in providers)
    assert "ollama" in providers
    assert providers.count(seat) == 1


def test_non_seat_primary_keeps_its_cross_family_tail() -> None:
    config = JarvisConfig(brain=BrainConfig(primary="gemini"))

    providers = [p for p, _ in resolver._resolve_chain(config)]

    assert providers[0] == "gemini"
    assert "openrouter" in providers


def test_power_user_override_survives_a_seat_primary() -> None:
    seat = _seat_id()
    config = JarvisConfig(brain=BrainConfig(primary=seat))
    config.board.bio.override_provider = "openrouter"

    providers = [p for p, _ in resolver._resolve_chain(config)]

    assert providers[0] == "openrouter"
    assert seat in providers
    assert "openai" not in providers


def test_background_work_never_moves_off_the_seat(monkeypatch) -> None:
    seat = _seat_id()
    background_policy._probe_override = lambda _pid: True
    monkeypatch.setattr(background_policy, "_read_markers", lambda: {})
    monkeypatch.setattr(background_policy, "_write_markers", lambda _m: None)
    subscription_or_api = [
        s.id for s in PROVIDERS
        if s.tier == "brain" and provider_billing(s) == "subscription_or_api"
    ]
    candidates = [seat, *subscription_or_api, *KEYED, "ollama"]

    decision = background_policy.background_providers(candidates, primary=seat)

    assert decision.allowed == (seat, "ollama")
    # Without a seat primary a signed-in subscription CLI stays allowed.
    open_decision = background_policy.background_providers(candidates)
    assert set(subscription_or_api) <= set(open_decision.allowed)


def test_chat_chain_has_no_foreign_lead_or_fallback(monkeypatch) -> None:
    from jarvis.brain.manager import BrainManager
    from jarvis.core.bus import EventBus
    from jarvis.core.config import load_config

    monkeypatch.setattr(cfg_mod, "get_secret_any", lambda _candidates: "test-key")
    seat = _seat_id()
    cfg = load_config()
    cfg.brain.primary = seat
    cfg.brain.router = BrainTierConfig(provider=seat, fallback_provider="claude-api")
    mgr = BrainManager.from_tier_config("router", cfg, EventBus(), provider_override=seat)
    mgr._turn_substantive = True
    mgr._turn_needs_tools = True

    for level in ("fast", "deep", "code"):
        chain = mgr._build_fallback_chain(level)
        names = [name for name, _ in chain]
        assert names and names[0] == seat, level
        assert all(n == seat or background_policy.keyless_local(n) for n in names), names
        assert mgr._router_lead_key is None
