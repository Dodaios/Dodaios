"""The permission messages name the app the way macOS lists it.

A permission toast tells the user to find the app in System Settings > Privacy
& Security, where macOS lists it under its bundle name. Every locale therefore
spells ``MACOS_APP_NAME`` and never a name the bundle had before. The locale
files are found by listing the directory, so a new language is covered without
touching this test.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from dodaios.core.branding import LEGACY_MACOS_APP_NAMES, MACOS_APP_NAME

_LOCALES_DIR = (
    Path(__file__).resolve().parents[4]
    / "dodaios"
    / "ui"
    / "web"
    / "frontend"
    / "src"
    / "i18n"
    / "locales"
)
_LOCALE_FILES = sorted(_LOCALES_DIR.glob("*.json"))
# The messages that name the app, as the English reference has them.
_NAMING_KEYS = frozenset(
    {
        "restart_failed",
        "toast.microphone",
        "toast.screen_recording",
        "toast.accessibility",
        "toast.input_monitoring",
        "toast.automation",
        "toast.generic",
        "toast.restricted",
        "toast.restart",
        "toast.outside",
        "toast.wake_word",
    }
)


def _strings(node: object, prefix: str = "") -> Iterator[tuple[str, str]]:
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _strings(value, f"{prefix}.{key}" if prefix else key)
    elif isinstance(node, str):
        yield prefix, node


def _permission_strings(path: Path) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return dict(_strings(data.get("permissions", {})))


def test_every_language_is_found() -> None:
    assert {path.stem for path in _LOCALE_FILES} >= {"en", "de", "es", "pt", "zh"}


def test_the_english_reference_names_the_app_where_expected() -> None:
    english = _permission_strings(_LOCALES_DIR / "en.json")
    naming = {key for key, text in english.items() if MACOS_APP_NAME in text}
    assert naming == _NAMING_KEYS


@pytest.mark.parametrize("path", _LOCALE_FILES, ids=lambda path: path.stem)
def test_each_locale_names_the_app_as_macos_lists_it(path: Path) -> None:
    strings = _permission_strings(path)
    for key in sorted(_NAMING_KEYS):
        assert MACOS_APP_NAME in strings.get(key, ""), f"{path.name}: permissions.{key}"
    for key, text in strings.items():
        for legacy in LEGACY_MACOS_APP_NAMES:
            assert legacy not in text, f"{path.name}: permissions.{key} says {legacy!r}"
