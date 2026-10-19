"""Static persona prompt for the Pre-Thinking Ack Flash-Brain.

One English rule text plus a per-language "Write in ..." line (de / en / es /
pt). The prompt only says WHEN to speak; what the preamble may not say is
enforced in code by ``generator.py``: the self-answer post-filter (F10),
``has_unbacked_action_claim``, ``validate_output_language``, the word cap and
``scrub_for_voice(ack_mode=True)``. Few-shot examples were removed in v2
because they caused mode collapse; the persona stays name-neutral (the
assistant's name comes from the wake word) and free of em dashes (hard TTS
pauses).
"""
from __future__ import annotations

__all__ = [
    "PERSONA_PROMPT",
    "get_persona_prompt",
]

_LANGUAGE_NAMES = {
    "de": "German",
    "en": "English",
    "es": "Spanish (Spain)",
    "pt": "European Portuguese",
}

PERSONA_PROMPT = (
    "Say one short line before the main assistant answers, or output an empty string. Speak "
    "only when the request starts a longer task (research, a multi-step action, a lookup): "
    "one sentence of at most twelve words naming its concrete topic. Empty for small talk, "
    "quick facts, voice commands or when unsure. Never answer, promise or claim anything; no "
    "generic filler, honorifics or Markdown."
)


def _normalise_language(value: str | None) -> str:
    """Reduce any language hint to 'de', 'en', 'es' or 'pt'.

    Unknown / empty / None falls back to English (``DEFAULT_LOCALE``), the
    one fallback language of every system phrase.
    """
    from dodaios.core.turn_language import normalize_language_tag
    from dodaios.i18n import phrase_locale

    lang = phrase_locale(normalize_language_tag(value))
    return lang if lang in _LANGUAGE_NAMES else "en"


def get_persona_prompt(language: str | None) -> str:
    """Return the Flash-Brain persona prompt for the given language hint (de/en/es/pt)."""
    return f"{PERSONA_PROMPT} Write in {_LANGUAGE_NAMES[_normalise_language(language)]}."
