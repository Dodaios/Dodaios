"""A turn answered by an on-device model costs nothing and says nothing.

Local providers (``auth_mode == "none"``: local-openai, ollama) have no price
list. Pricing them used to log "No pricing for model …" on every turn and
spend up to three seconds of the first turn refreshing a remote catalogue.
Cloud models keep the warning: an unpriced cloud model is a billing gap.
"""

from __future__ import annotations

import logging

import pytest

from dodaios.brain import cost
from dodaios.brain.manager import _turn_cost_usd


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    looked_up: list[str] = []

    async def _ensure(model: str | None, **_kwargs: object) -> bool:
        looked_up.append(str(model))
        return False

    monkeypatch.setattr(cost, "ensure_pricing_for", _ensure)
    return looked_up


@pytest.mark.parametrize("provider", ["local-openai", "ollama"])
async def test_a_local_turn_is_free_without_a_lookup_or_a_warning(
    provider: str, no_network: list[str], caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="dodaios.brain.manager"):
        usd = await _turn_cost_usd(provider, "ggml-org/Qwen3-1.7B-GGUF:Q4_K_M", 7391, 707, 0)

    assert usd == 0.0
    assert no_network == []
    assert "No pricing" not in caplog.text


async def test_an_unpriced_cloud_model_still_warns(
    no_network: list[str], caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="dodaios.brain.manager"):
        usd = await _turn_cost_usd("openrouter", "vendor/never-heard-of-it", 1000, 10, 0)

    assert usd == 0.0
    assert no_network == ["vendor/never-heard-of-it"]
    assert "No pricing for model 'vendor/never-heard-of-it'" in caplog.text


async def test_a_priced_cloud_model_is_billed(no_network: list[str]) -> None:
    model = next(iter(cost.PRICING_USD_PER_MTOK))

    usd = await _turn_cost_usd("openai", model, 1_000_000, 0, 0)

    assert usd == cost.calculate_cost_usd(model, 1_000_000, 0, 0)
    assert usd > 0.0
