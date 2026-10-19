"""The one list of languages the backend speaks, and the names of the rest.

Two different questions, kept apart on purpose:

* **Which languages have translated system phrases?** ``SUPPORTED_LOCALES``.
  Every canned status, error and fallback sentence exists in these, and a
  JSON catalog under ``dodaios/i18n/locales/`` holds them. Adding a language
  to the canned phrases means adding one catalog file and one code here.
* **Which language is the person speaking?** Any language at all. The model
  answers in it; only the canned phrases are limited to the list above, and
  for every other language they fall back to English (``DEFAULT_LOCALE``),
  never to whichever supported language happens to look closest.

Forensic 2026-10-19: a person chatting in Turkish got errors in German, then
Portuguese, then English, because Turkish ö/ü scored as German and ç as
Portuguese, and every failure path picked its own fallback.
"""

from __future__ import annotations

#: Languages with a full set of translated system phrases (the catalog files).
SUPPORTED_LOCALES: tuple[str, ...] = ("de", "en", "es", "pt")

#: The language of every system phrase when the person's language has no
#: translation or cannot be told. One constant for every layer.
DEFAULT_LOCALE = "en"

#: English names of the supported languages, as the model is told them.
SUPPORTED_LANGUAGE_NAMES: dict[str, str] = {
    "de": "German",
    "en": "English",
    "es": "Spanish",
    "pt": "European Portuguese",
}

#: English names of languages the detector can recognise but that have no
#: translated system phrases. The model is still told to answer in them.
OTHER_LANGUAGE_NAMES: dict[str, str] = {
    "ar": "Arabic",
    "cs": "Czech",
    "el": "Greek",
    "fa": "Persian",
    "fr": "French",
    "he": "Hebrew",
    "hi": "Hindi",
    "hu": "Hungarian",
    "it": "Italian",
    "ja": "Japanese",
    "ko": "Korean",
    "nl": "Dutch",
    "pl": "Polish",
    "ro": "Romanian",
    "ru": "Russian",
    "th": "Thai",
    "tr": "Turkish",
    "uk": "Ukrainian",
    "vi": "Vietnamese",
    "zh": "Chinese",
}

LANGUAGE_NAMES: dict[str, str] = {**SUPPORTED_LANGUAGE_NAMES, **OTHER_LANGUAGE_NAMES}


def is_supported_locale(code: object) -> bool:
    """True when *code* has translated system phrases."""
    return isinstance(code, str) and code in SUPPORTED_LOCALES


def is_known_language(code: object) -> bool:
    """True when *code* names a language the model can be told to answer in."""
    return isinstance(code, str) and code in LANGUAGE_NAMES


def phrase_locale(code: object) -> str:
    """The catalog language for a person's language: itself, else English."""
    value = str(code or "").strip().lower()
    return value if value in SUPPORTED_LOCALES else DEFAULT_LOCALE


def language_name(code: object) -> str | None:
    """The English name of a known language code, or None."""
    return LANGUAGE_NAMES.get(str(code or "").strip().lower())
