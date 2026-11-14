"""Config contract of the pets (docs/pets.md).

Pets live in the app only: the one key left is ``[ui] pet_id``, the active
pet. The keys of the removed desktop pet (``pet_scale``, ``pet_bubble``,
``pet_strip_always``, ``orb_mascot_path``, ``[trigger] hotkey_pet_toggle``)
must still load from an old ``jarvis.toml`` without effect, and an old
``orb_style`` of ``pet`` or ``mascot`` loads as the bar.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from dodaios.core import config_writer
from dodaios.core.config import JarvisConfig, TriggerConfig, UIConfig, normalize_pet_id
from dodaios.ui.pets.manifest import BUILTIN_ID_RE, USER_ID_RE
from dodaios.ui.pets.states import DEFAULT_PET_ID, NO_PET_ID


def test_default_pet() -> None:
    assert UIConfig().pet_id == DEFAULT_PET_ID


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("gigi", "gigi"),
        ("  Miso ", "miso"),
        ("none", NO_PET_ID),
        ("NONE", NO_PET_ID),
        ("u0123456789abcdef", "u0123456789abcdef"),
        # Anything that is not id-shaped falls back to the default pet: a
        # corrupt jarvis.toml must never brick the load.
        ("../../etc", DEFAULT_PET_ID),
        ("C:\\pets\\gigi", DEFAULT_PET_ID),
        ("", DEFAULT_PET_ID),
        ("a" * 33, DEFAULT_PET_ID),
        (7, DEFAULT_PET_ID),
        (None, DEFAULT_PET_ID),
    ],
)
def test_pet_id_is_sanitized_on_load(raw: object, expected: str) -> None:
    assert UIConfig(pet_id=raw).pet_id == expected


def test_pet_id_shape_matches_the_manifest_rules() -> None:
    """One id shape across the config, the loader and the routes (AP-4)."""
    for candidate in ("gigi", "bolt-2", "u0123456789abcdef", "none", "a" * 32):
        assert normalize_pet_id(candidate) == candidate
        assert BUILTIN_ID_RE.fullmatch(candidate)
    for candidate in ("-gigi", "gi gi", "gigi.png", "a" * 33, "../x", "Gigi/"):
        assert normalize_pet_id(candidate) is None
        assert not BUILTIN_ID_RE.fullmatch(candidate.lower())
    assert USER_ID_RE.fullmatch("u0123456789abcdef")


def _ui_table(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8")).get("ui", {})


def test_set_pet_id_persists_and_keeps_comments(tmp_path: Path) -> None:
    toml = tmp_path / "jarvis.toml"
    toml.write_text('[ui]\norb_style = "jarvis_bar"  # kept\n', encoding="utf-8")
    config_writer.set_pet_id("Miso", path=toml)
    assert _ui_table(toml)["pet_id"] == "miso"
    assert "# kept" in toml.read_text(encoding="utf-8")


def test_set_pet_id_refuses_a_value_that_is_not_an_id(tmp_path: Path) -> None:
    toml = tmp_path / "jarvis.toml"
    toml.write_text("", encoding="utf-8")
    with pytest.raises(ValueError):
        config_writer.set_pet_id("../../somewhere", path=toml)
    assert "pet_id" not in _ui_table(toml)


@pytest.mark.parametrize("old_style", ["pet", "mascot", "orb", "PET"])
def test_an_old_desktop_pet_style_loads_as_the_bar(old_style: str) -> None:
    assert UIConfig(orb_style=old_style).orb_style == "jarvis_bar"


def test_the_removed_desktop_pet_keys_still_load() -> None:
    """An old jarvis.toml with the desktop pet's keys loads and ignores them."""
    cfg = JarvisConfig.model_validate(
        {
            "ui": {
                "orb_style": "pet",
                "pet_id": "nox",
                "pet_scale": 1.5,
                "pet_bubble": False,
                "pet_strip_always": True,
                "orb_mascot_path": "me.png",
            },
            "trigger": {"hotkey_pet_toggle": "alt+win+p"},
        }
    )
    assert cfg.ui.orb_style == "jarvis_bar"
    assert cfg.ui.pet_id == "nox"
    assert "hotkey_pet_toggle" not in TriggerConfig.model_fields
    assert "pet_toggle" not in config_writer.KEYBIND_ACTIONS


def test_example_config_documents_only_the_active_pet() -> None:
    example = Path(__file__).resolve().parents[3] / "dodaios.toml.example"
    data = tomllib.loads(example.read_text(encoding="utf-8"))
    assert data["ui"]["pet_id"] == UIConfig().pet_id
    for gone in ("pet_scale", "pet_bubble", "pet_strip_always"):
        assert gone not in data["ui"]
    assert "hotkey_pet_toggle" not in data["trigger"]
