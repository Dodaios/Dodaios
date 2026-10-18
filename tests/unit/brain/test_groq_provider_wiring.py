"""Groq is a selectable brain provider, wired like NVIDIA NIM.

The Groq key already powered speech-to-text; without a brain plugin the same key
never showed up in the brain provider list. These guards pin the brain sites:
plugin + entry point, credential slot, UI spec, model catalog and tier defaults.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

from jarvis.brain.manager import (
    PROVIDER_ALIASES,
    TIER_DEFAULTS_BY_PROVIDER,
    get_tier_default_model,
)
from jarvis.brain.model_catalog import _ENDPOINTS, CATALOG_PROVIDERS, catalog_spec
from jarvis.core import config as cfg
from jarvis.plugins.brain.groq import BASE_URL, GroqBrain
from jarvis.ui.web.provider_spec import get_spec

_ROOT = Path(__file__).resolve().parents[3]


def test_groq_brain_is_an_entry_point() -> None:
    data = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    brains = data["project"]["entry-points"]["jarvis.brain"]
    assert brains["groq"] == "jarvis.plugins.brain.groq:GroqBrain"


def test_groq_brain_shape() -> None:
    brain = GroqBrain()
    assert brain.name == "groq"
    assert brain.can_call_tools() is True


def test_groq_shares_the_stt_credential_slot() -> None:
    assert cfg.PROVIDER_SECRET_CANDIDATES["groq"] == (("groq_api_key", "GROQ_API_KEY"),)
    ep = cfg.resolve_provider_endpoint("groq", vendor_default_base_url=BASE_URL)
    assert ep.base_url == "https://api.groq.com/openai/v1"


def test_groq_provider_spec_is_a_switchable_brain() -> None:
    spec = get_spec("groq")
    assert spec is not None
    assert spec.tier == "brain"
    assert spec.auth_mode == "api_key"
    assert spec.secret_keys == ("groq_api_key",)
    assert spec.dashboard_url
    assert spec.brain_switchable is True


def test_groq_has_a_model_catalog() -> None:
    spec = catalog_spec("groq")
    assert spec is not None
    assert spec.curated
    assert "groq" in CATALOG_PROVIDERS
    ep = _ENDPOINTS["groq"]
    assert ep.vendor_base + ep.path == "https://api.groq.com/openai/v1/models"


def test_groq_has_tier_defaults() -> None:
    assert get_tier_default_model("router", "groq")
    assert get_tier_default_model("deep", "groq")
    assert "groq" in TIER_DEFAULTS_BY_PROVIDER["router"]
    assert PROVIDER_ALIASES["groq"] == "groq"
