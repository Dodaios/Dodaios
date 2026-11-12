"""The lead doctrine: short, constant, and only on the lead conversation (both runners)."""

from __future__ import annotations

from dodaios.brain.lead_doctrine import (
    LEAD_DOCTRINE,
    LEAD_DOCTRINE_MAX_CHARS,
    LEAD_TURN,
    lead_prompt_blocks,
)
from dodaios.brain.manager import _TURN_OVERRIDE, BrainManager
from dodaios.brain.turn_override import TurnOverride


def _manager() -> BrainManager:
    from dodaios.core.config import load_config

    m = BrainManager.__new__(BrainManager)
    m._soul = None
    m._user_profile = None
    m._people = None
    m._core_memory = None
    m._system_prompt_extra = ""
    m._memory_context_suffix = ""
    m._reply_language = "auto"
    m._active_turn_identity = None
    cfg = load_config()
    cfg.performance.cache_optimized_prompt = False
    m._config = cfg
    return m


def _prompt(m: BrainManager, override: TurnOverride | None = None) -> str:
    token = _TURN_OVERRIDE.set(override)
    try:
        return m._build_system_prompt()
    finally:
        _TURN_OVERRIDE.reset(token)


def test_the_doctrine_is_short_and_says_what_the_lead_must_do() -> None:
    assert len(LEAD_DOCTRINE) <= LEAD_DOCTRINE_MAX_CHARS
    text = LEAD_DOCTRINE.lower()
    for needle in (
        "coordinator",
        "job id",
        "job_status",
        "await_jobs",
        "verify_delegate",
        "memory before you ask",
        "one question at a time",
        "evidence",
        "never speak uncalled",
    ):
        assert needle in text, needle
    assert "voice companion" not in text


def test_the_lead_conversation_gets_the_doctrine_after_the_persona_and_the_map() -> None:
    m = _manager()
    plain = _prompt(m)
    lead = _prompt(m, TurnOverride(provider="x", lead=True))
    doctrine, ecosystem = lead_prompt_blocks()
    assert doctrine not in plain and "ECOSYSTEM MAP" not in plain
    assert doctrine in lead and ecosystem in lead
    persona_end = lead.index("ENDING THE CALL")
    assert lead.index(doctrine) > persona_end
    assert lead.index(ecosystem) > lead.index(doctrine)


def test_a_non_lead_override_and_a_society_turn_stay_byte_identical() -> None:
    m = _manager()
    plain = _prompt(m)
    assert _prompt(m, TurnOverride(provider="x")) == plain
    society = TurnOverride(
        provider="x", system_extra="You are Scout.", tool_context={"tool_origin": "society"},
        lead=True,
    )
    assert LEAD_DOCTRINE not in _prompt(m, society)


def test_the_lead_block_is_byte_stable_between_builds() -> None:
    m = _manager()
    lead = TurnOverride(provider="x", lead=True)
    assert _prompt(m, lead) == _prompt(m, lead)


def test_the_cli_identity_path_marks_the_lead_turn_with_the_context_variable() -> None:
    m = _manager()
    token = LEAD_TURN.set(True)
    try:
        assert LEAD_DOCTRINE in m._build_system_prompt()
    finally:
        LEAD_TURN.reset(token)
    assert LEAD_DOCTRINE not in m._build_system_prompt()


async def test_render_surface_prompt_adds_the_doctrine_only_for_the_lead() -> None:
    m = _manager()

    async def no_recall(_text: str) -> str:
        return ""

    m._vault_recall = no_recall  # type: ignore[method-assign]
    m._build_turn_context = lambda: ""  # type: ignore[method-assign]
    lead, _ = await m.render_surface_prompt(user_text="hi", lead=True)
    other, _ = await m.render_surface_prompt(user_text="hi")
    assert LEAD_DOCTRINE in lead and "ECOSYSTEM MAP" in lead
    assert LEAD_DOCTRINE not in other
    assert LEAD_TURN.get() is False, "the marker never leaks out of the prompt build"
