"""The backend system-phrase catalog: one file per language, English as the net."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from dodaios.i18n import (
    DEFAULT_LOCALE,
    SUPPORTED_LOCALES,
    phrase_locale,
    pick,
    t,
    table,
    variants,
)
from dodaios.i18n.catalog import keys

_REPO = Path(__file__).resolve().parents[3]
_LOCALES = _REPO / "dodaios" / "i18n" / "locales"
_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _flat(code: str) -> dict[str, object]:
    out: dict[str, object] = {}

    def walk(node: dict, prefix: str) -> None:
        for key, value in node.items():
            if isinstance(value, dict):
                walk(value, f"{prefix}{key}.")
            else:
                out[prefix + key] = value

    walk(json.loads((_LOCALES / f"{code}.json").read_text(encoding="utf-8")), "")
    return out


def test_every_supported_language_has_a_catalog_and_nothing_else_does() -> None:
    files = {path.stem for path in _LOCALES.glob("*.json")}
    assert files == set(SUPPORTED_LOCALES)


#: Keys whose placeholders differ by design. English reads the engine's own
#: English sentence; the other languages rebuild it from permission + pane
#: (dodaios/voice/action_phrases.py, cu_blocked_permission_readback).
_PLACEHOLDER_EXCEPTIONS = frozenset({"voice.action.phrases.cu_blocked_permission"})


@pytest.mark.parametrize("code", [c for c in SUPPORTED_LOCALES if c != DEFAULT_LOCALE])
def test_catalogs_have_the_same_keys_shapes_and_placeholders(code: str) -> None:
    master, other = _flat(DEFAULT_LOCALE), _flat(code)
    assert set(other) == set(master)
    for key, value in master.items():
        theirs = other[key]
        assert type(theirs) is type(value), key
        if isinstance(value, list):
            assert len(theirs) == len(value), key
            pairs = zip(value, theirs, strict=True)
        else:
            pairs = [(value, theirs)]
        if key in _PLACEHOLDER_EXCEPTIONS:
            continue
        for mine, translated in pairs:
            assert set(_PLACEHOLDER.findall(mine)) == set(_PLACEHOLDER.findall(translated)), key


@pytest.mark.parametrize("lang", ["tr", "fr", "", None, "auto", "xx-YY"])
def test_a_language_without_translations_reads_english(lang: object) -> None:
    assert phrase_locale(lang) == "en"
    for key in keys():
        assert variants(key, lang) == variants(key, "en")


def test_lookup_helpers() -> None:
    assert t("brain.cli_failure.code", "de", code=3).endswith("3 fehlgeschlagen.")  # i18n-allow
    assert t("brain.provider_down", "en", index=4) == variants("brain.provider_down", "en")[1]
    assert set(table("brain.cancel_none")) == set(SUPPORTED_LOCALES)
    assert pick({"en": "x", "de": "y"}, "tr") == "x"
    assert pick({"en": "x", "de": "y"}, "de") == "y"
    with pytest.raises(KeyError):
        t("no.such.key", "en")


def test_reply_and_mission_languages_come_from_the_central_list() -> None:
    from dodaios.brain.manager import SUPPORTED_REPLY_LANGUAGES
    from dodaios.commands.registry import REPLY_LANGUAGES
    from dodaios.core.turn_language import _REPLY_PINS
    from dodaios.missions.events import MISSION_LANGUAGES

    assert SUPPORTED_REPLY_LANGUAGES == REPLY_LANGUAGES == ("auto", *SUPPORTED_LOCALES)
    assert _REPLY_PINS == frozenset(SUPPORTED_LOCALES)
    assert MISSION_LANGUAGES == SUPPORTED_LOCALES


# Phrase lookups that fall back to German. Every system phrase falls back to
# English (DEFAULT_LOCALE); German is only ever the answer when the person's
# language is German (forensic 2026-10-19).
_GERMAN_FALLBACK = re.compile(
    r"""\.get\([^)]*\[\s*["']de["']\s*\]\s*\)"""
    r"""|default\s*=\s*["']de["']"""
    r"""|_DEFAULT(?:_LANG)?\s*=\s*["']de["']"""
    r"""|else\s+["']de["']\s*$"""
    r"""|or\s+["']de["']\s*\)"""
    r"""|language:\s*str\s*=\s*["']de["']"""
)
# Input-side vocabulary, not output: which word lists to MATCH against.
_INPUT_SIDE = {
    "dodaios/agentic_ide/clarify.py",
    "dodaios/speech/completion.py",
}


def test_no_backend_phrase_falls_back_to_german() -> None:
    offenders = []
    for path in sorted((_REPO / "dodaios").rglob("*.py")):
        rel = path.relative_to(_REPO).as_posix()
        if rel in _INPUT_SIDE:
            continue
        for number, line in enumerate(
            path.read_text(encoding="utf-8-sig").splitlines(), start=1
        ):
            if _GERMAN_FALLBACK.search(line) and "input language, not output" not in line:
                offenders.append(f"{rel}:{number}: {line.strip()}")
    assert not offenders, "\n".join(offenders)
