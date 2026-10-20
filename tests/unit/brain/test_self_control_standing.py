"""The self-control facts in the core contract must reach EVERY system prompt.

A keyword-free self-control request once got no self-control guidance, and the
router LLM claimed a wake-word change without any tool call. The standing core
contract closes that hole without keyword matching; these tests pin it.
"""
from __future__ import annotations

from dodaios.brain.manager import (
    _CORE_CONTRACT,
    BrainManager,
)
from dodaios.core.config import load_config


def _manager() -> BrainManager:
    """A BrainManager with __init__ bypassed — only the attrs the prompt needs."""
    m = BrainManager.__new__(BrainManager)
    m._soul = None
    m._user_profile = None
    m._people = None
    m._core_memory = None
    m._system_prompt_extra = ""
    m._wiki_context_suffix = ""
    m._reply_language = "auto"
    m._active_turn_identity = None
    cfg = load_config()
    cfg.performance.cache_optimized_prompt = False
    m._config = cfg
    return m


def test_core_contract_is_in_every_prompt() -> None:
    prompt = _manager()._build_system_prompt()
    assert _CORE_CONTRACT in prompt


def test_core_contract_names_the_structured_path_and_forbids_claiming() -> None:
    # The line must name real callable tool names.
    assert "brain-switch" in _CORE_CONTRACT
    assert "wake-word-set" in _CORE_CONTRACT
    low = _CORE_CONTRACT.lower()
    # The anti-"said it, did nothing" rule, in plain words.
    assert "never" in low
    assert "tool call" in low
    # Wake-phrase renames are the reproduced failure — must be named so a
    # keyword-free phrasing still maps.
    assert "wake" in low
