"""Language resolution + name-neutrality for the Flash-Brain preamble persona.

Guards that the preamble resolves de/en/es/pt natively, never bakes in a
product name, and carries no em dashes (which render as hard TTS pauses).
"""
from __future__ import annotations

from dodaios.brain.ack_brain.persona_prompt import PERSONA_PROMPT, get_persona_prompt

_EXPECTED = {
    "de": "Write in German.",
    "en": "Write in English.",
    "es": "Write in Spanish (Spain).",
    "pt": "Write in European Portuguese.",
}


def test_get_persona_prompt_resolves_each_language() -> None:
    for lang, tail in _EXPECTED.items():
        prompt = get_persona_prompt(lang)
        assert prompt.startswith(PERSONA_PROMPT)
        assert prompt.endswith(tail)


def test_get_persona_prompt_normalises_tags_and_falls_back_to_en() -> None:
    assert get_persona_prompt("en-US").endswith(_EXPECTED["en"])
    assert get_persona_prompt("es-ES").endswith(_EXPECTED["es"])
    assert get_persona_prompt("pt-PT").endswith(_EXPECTED["pt"])
    assert get_persona_prompt("de-DE").endswith(_EXPECTED["de"])
    assert get_persona_prompt("german").endswith(_EXPECTED["de"])
    # Unknown / empty / None falls back to English (DEFAULT_LOCALE), never German.
    for value in ("fr", "", None):
        assert get_persona_prompt(value) == get_persona_prompt("en")


def test_preamble_personas_are_name_neutral() -> None:
    # No baked-in product name: the assistant's name is runtime-derived from the
    # wake word and owned by the deep brain.
    for lang in _EXPECTED:
        prompt = get_persona_prompt(lang)
        assert "JARVIS" not in prompt
        assert "Jarvis" not in prompt


def test_preamble_personas_have_no_em_dash() -> None:
    for lang in _EXPECTED:
        prompt = get_persona_prompt(lang)
        assert "—" not in prompt  # em dash
        assert "–" not in prompt  # en dash
