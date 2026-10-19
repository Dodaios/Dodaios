"""System phrases, one JSON file per language, English as the safety net.

``dodaios/i18n/locales/<code>.json`` holds the translated system phrases
(errors, failure notices, fallbacks) under dotted keys. ``en.json`` is the
master: every key exists there, and any key missing from another file, or
any language without a file, reads the English text. Nothing ever falls back
to German or to a "nearest" language.

A value is either one string or a list of variants (rotated by the caller so
a repeated failure does not sound robotic).

Adding a language to the system phrases: copy ``en.json`` to ``<code>.json``,
translate it, and add the code to ``SUPPORTED_LOCALES`` in
``dodaios.i18n.locales``. No module that uses the phrases changes.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from functools import cache
from pathlib import Path
from typing import Any, TypeVar

from dodaios.i18n.locales import DEFAULT_LOCALE, SUPPORTED_LOCALES, phrase_locale

_LOCALES_DIR = Path(__file__).with_name("locales")
log = logging.getLogger(__name__)

_T = TypeVar("_T")


@cache
def _catalog(code: str) -> dict[str, Any]:
    path = _LOCALES_DIR / f"{code}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        # A language without a catalog reads English through the caller.
        log.warning("i18n: no phrase catalog for %r at %s; using English", code, path)
        return {}
    return _flatten(data)


def _flatten(data: Mapping[str, Any], prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in data.items():
        full = f"{prefix}{key}"
        if isinstance(value, Mapping):
            out.update(_flatten(value, full + "."))
        else:
            out[full] = value
    return out


def keys() -> frozenset[str]:
    """Every phrase key the English master catalog defines."""
    return frozenset(_catalog(DEFAULT_LOCALE))


def _raw(key: str, lang: object) -> Any:
    value = _catalog(phrase_locale(lang)).get(key)
    if value is None:
        value = _catalog(DEFAULT_LOCALE).get(key)
    if value is None:
        raise KeyError(f"unknown phrase key {key!r}")
    return value


def variants(key: str, lang: object) -> tuple[str, ...]:
    """All variants of *key* in *lang* (English when it has none)."""
    value = _raw(key, lang)
    return tuple(value) if isinstance(value, list) else (str(value),)


def t(key: str, lang: object, /, index: int = 0, **fields: object) -> str:
    """The phrase *key* in *lang*, falling back to English.

    ``index`` picks a variant (modulo their count); ``fields`` fill
    ``{placeholders}`` with ``str.format``.
    """
    options = variants(key, lang)
    text = options[index % len(options)]
    return text.format(**fields) if fields else text


def table(key: str) -> dict[str, str]:
    """``{code: phrase}`` for every supported language: a drop-in for the old
    per-module dicts. Missing translations hold the English text."""
    return {code: t(key, code) for code in SUPPORTED_LOCALES}


def variant_table(key: str) -> dict[str, tuple[str, ...]]:
    """``{code: (variant, ...)}`` for every supported language."""
    return {code: variants(key, code) for code in SUPPORTED_LOCALES}


def subkeys(key: str) -> tuple[str, ...]:
    """The names directly under *key* in the English master, in file order."""
    prefix = key + "."
    seen: dict[str, None] = {}
    for full in _catalog(DEFAULT_LOCALE):
        if full.startswith(prefix):
            seen.setdefault(full[len(prefix):].split(".", 1)[0], None)
    return tuple(seen)


def nested_table(key: str) -> dict[str, dict[str, str]]:
    """``{name: {code: phrase}}`` for a group of phrases (one per cause, ...)."""
    return {name: table(f"{key}.{name}") for name in subkeys(key)}


def locale_maps(key: str) -> dict[str, dict[str, str]]:
    """``{code: {name: phrase}}`` for a group of phrases, language first."""
    names = subkeys(key)
    return {
        code: {name: t(f"{key}.{name}", code) for name in names}
        for code in SUPPORTED_LOCALES
    }


def pick(phrases: Mapping[str, _T], lang: object) -> _T:
    """``phrases[lang]`` for a supported language, else the English entry.

    The one lookup for a module that still keeps its own ``{code: text}``
    table: an unsupported or unknown language reads English, never German.
    """
    value = phrases.get(phrase_locale(lang))
    if value is None:
        value = phrases[DEFAULT_LOCALE]
    return value
