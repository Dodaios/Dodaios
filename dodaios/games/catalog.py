"""The shipped game catalog: which settings each game has, and their ranges.

``catalog.json`` holds one entry per game: its sections (mouse, audio, video,
gameplay) of typed settings, its default PC keybinds, the mouse "yaw" used
for sensitivity conversion (``None`` when the game's sensitivity is not
linear) and where the game keeps its own config file. Defaults are ``None``
where they could not be verified; the UI then shows the field empty.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

CATALOG_PATH = Path(__file__).with_name("catalog.json")

SECTION_IDS = ("mouse", "audio", "video", "gameplay")
SETTING_TYPES = ("slider", "number", "select", "toggle", "text")


@lru_cache(maxsize=1)
def load_catalog() -> dict[str, Any]:
    """The whole catalog, parsed once per process."""
    with CATALOG_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def list_games() -> list[dict[str, Any]]:
    return list(load_catalog()["games"])


def get_game(game_id: str) -> dict[str, Any] | None:
    return next((g for g in load_catalog()["games"] if g["id"] == game_id), None)


def settings_by_key(game: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Every setting of a game, keyed by its ``key``, across all sections."""
    return {s["key"]: s for section in game["sections"] for s in section["settings"]}


def keybind_ids(game: dict[str, Any]) -> set[str]:
    return {k["id"] for k in game["keybinds"]}
