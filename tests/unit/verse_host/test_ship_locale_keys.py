"""The ship locale chunk carries every Verse UI string id (parity N-02, N-03).

Verse resolves its strings from ``welcome.locale.strings`` first and keeps
``unreal/Verse/Data/ui/strings.<lang>.json`` only as a fallback, so every id
the Unreal UI uses must be in the ship chunk of every language, translated.
Change requests #1159 (stations) and #1166 (HUD, menus, settings, armoury,
end screen).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dodaios.verse_host.relays.settings import SETTINGS_DIR, SHIP_DIR, locale_strings

REPO = Path(__file__).resolve().parents[3]
UNREAL_UI = REPO / "unreal" / "Verse" / "Data" / "ui"
LANGS = sorted(p.name.split(".")[1] for p in SHIP_DIR.glob("verse.*.json"))

STATION_KEYS = (
    "verse.station.close",
    "verse.station.armoury.name",
    "verse.station.armoury.action",
    *(
        f"verse.station.error.{code}"
        for code in (
            "bad_request", "not_found", "conflict", "busy",
            "unavailable", "rate_limited", "internal",
        )
    ),
)
PROGRAMMES = (
    "asteroid_run", "neon_snake", "brick_breaker", "paddle_duel", "block_drop",
    "maze_muncher", "desert_dash", "pixel_raiders", "road_hopper", "city_defense",
)
WEAPON_CLASS_KEYS = tuple(
    f"verse.item.{item}.short"
    for item in ("breach_charge", "graveline", "hookbill", "longsight", "skitter", "tallow")
)


def _unreal_ids() -> list[str]:
    data = json.loads((UNREAL_UI / "strings.en.json").read_text(encoding="utf-8"))
    return sorted(data["strings"])


def _own_chunk(lang: str) -> dict[str, str]:
    """The language's own files only, without the English fallback."""
    out: dict[str, str] = {}

    def walk(prefix: str, node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                walk(f"{prefix}.{key}" if prefix else key, value)
        elif isinstance(node, str):
            out[prefix] = node

    for path in sorted(SHIP_DIR.glob(f"*.{lang}.json")):
        walk("", json.loads(path.read_text(encoding="utf-8")))
    # The in-game settings menu reads the app's own settings page chunk (verse_settings.*).
    walk("", json.loads((SETTINGS_DIR / f"{lang}.json").read_text(encoding="utf-8")))
    return out


def test_all_five_languages_have_a_verse_file() -> None:
    assert LANGS == ["de", "en", "es", "pt", "zh"]


@pytest.mark.parametrize("lang", LANGS)
def test_every_unreal_ui_string_id_is_in_the_ship_chunk(lang: str) -> None:
    own = _own_chunk(lang)
    missing = [key for key in _unreal_ids() if key not in own]
    assert not missing, f"{lang}: {len(missing)} Unreal UI ids missing, first {missing[:5]}"


@pytest.mark.parametrize("lang", LANGS)
def test_station_and_programme_keys_are_in_every_language(lang: str) -> None:
    own = _own_chunk(lang)
    keys = (*STATION_KEYS, *(f"verse.games.programme.{p}" for p in PROGRAMMES))
    missing = [key for key in keys if not own.get(key)]
    assert not missing, f"{lang}: {missing}"


@pytest.mark.parametrize("lang", [lang for lang in LANGS if lang != "en"])
def test_station_words_and_weapon_classes_are_translated(lang: str) -> None:
    english, own = _own_chunk("en"), _own_chunk(lang)
    copies = [key for key in (*STATION_KEYS, *WEAPON_CLASS_KEYS) if own[key] == english[key]]
    assert not copies, f"{lang}: English copies {copies}"


def test_welcome_locale_resolves_dotted_keys_under_a_leaf() -> None:
    # `verse.settings.quality` is a word of its own and the parent of the quality levels.
    strings = locale_strings("de")
    assert strings["verse.settings.quality"] == "Grafikqualität"  # i18n-allow
    assert strings["verse.settings.quality.high"] == "Hoch"
    assert strings["verse.tier.adaptive.desc"].startswith("Beginnt")


@pytest.mark.parametrize("lang", LANGS)
def test_unreal_fallback_carries_the_settings_menu_chunk(lang: str) -> None:
    """strings.<lang>.json repeats the verse_settings chunk, so the menu reads well offline."""
    unreal = json.loads((UNREAL_UI / f"strings.{lang}.json").read_text(encoding="utf-8"))["strings"]
    chunk = {k: v for k, v in _own_chunk(lang).items() if k.startswith("verse_settings.")}
    assert chunk
    assert {k: unreal.get(k) for k in chunk} == chunk


def test_welcome_locale_carries_the_settings_menu_labels() -> None:
    strings = locale_strings("de")
    assert strings["verse_settings.s.graphics.shadows.label"] == "Schatten"
    assert strings["verse_settings.tabs.keybinds"]
