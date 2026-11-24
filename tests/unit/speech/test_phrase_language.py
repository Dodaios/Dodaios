"""Canned-phrase language picking must survive full Whisper language NAMES.

Live bug 2026-06-09: the utterance language can arrive as a full lowercased
language NAME (``"german"`` from Groq Whisper) while the canned-phrase pickers
tested ``lang.startswith("de")``, so every spoken notice came out in English
to a German speaker. The shared normalizer ``_phrase_lang`` maps language
names AND BCP-47-ish codes onto the canned-phrase keys; the spoken notices
left in a realtime-only voice (the "voice unavailable" notice, background
readbacks) must cover every supported locale.
"""

from __future__ import annotations

import pytest

from dodaios.speech import pipeline as pipeline_mod
from dodaios.speech.pipeline import _REALTIME_UNAVAILABLE_PHRASE

# --------------------------------------------------------------------------- #
# The shared normalizer                                                        #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("lang", "expected"),
    [
        # Live Whisper value (the bug): full lowercased language name.
        ("german", "de"),
        ("German", "de"),
        # German's own name for itself (defensive; startswith already covers it).
        ("deutsch", "de"),
        # BCP-47-ish codes (config pins, announcements).
        ("de", "de"),
        ("de-DE", "de"),
        # English in all shapes stays English.
        ("english", "en"),
        ("en", "en"),
        ("en-US", "en"),
        # Spanish is a first-class supported language (Runtime Output Language
        # doctrine): names AND codes map to "es", not the English fallback.
        ("spanish", "es"),
        ("es", "es"),
        ("es-ES", "es"),
        # European Portuguese, same contract.
        ("portuguese", "pt"),
        ("pt", "pt"),
        ("pt-PT", "pt"),
        # Unknown / missing → DEFAULT_LOCALE fallback.
        ("", "en"),
        (None, "en"),
        ("klingon", "en"),
    ],
)
def test_phrase_lang_maps_names_and_codes(lang: str | None, expected: str) -> None:
    phrase_lang = getattr(pipeline_mod, "_phrase_lang", None)
    assert phrase_lang is not None, "_phrase_lang normalizer is missing"
    assert phrase_lang(lang) == expected


def test_all_canned_phrase_tables_cover_de_en_es() -> None:
    # "Works for every configured language": no spoken canned table may be
    # de/en-only — an es speaker must never fall back to the wrong language.
    for table in (
        _REALTIME_UNAVAILABLE_PHRASE,
        pipeline_mod.SpeechPipeline._BG_READBACK_PHRASES,
    ):
        assert {"de", "en", "es", "pt"} <= set(table), table


def test_bcp47_maps_portuguese_to_portugal() -> None:
    assert pipeline_mod.SpeechPipeline._bcp47("pt") == "pt-PT"
    assert set(pipeline_mod.SpeechPipeline._BG_READBACK_PHRASES["pt"]) == set(
        pipeline_mod.SpeechPipeline._BG_READBACK_PHRASES["en"]
    )
