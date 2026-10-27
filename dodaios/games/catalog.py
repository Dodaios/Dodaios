"""The shipped game catalog: which settings each game has, and their ranges.

``catalog.json`` holds one entry per game: its sections (mouse, audio, video,
gameplay) of typed settings, its default PC keybinds, the mouse "yaw" used
for sensitivity conversion (``None`` when the game's sensitivity is not
linear) and where the game keeps its own config file. Defaults are ``None``
where they could not be verified; the UI then shows the field empty.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from dodaios.games.performance import performance_sections, presets

CATALOG_PATH = Path(__file__).with_name("catalog.json")

PERF_SECTION_IDS = (
    "perf_display",
    "perf_rendering",
    "perf_detail",
    "perf_raytracing",
    "perf_effects",
)
SECTION_IDS = (*PERF_SECTION_IDS, "mouse", "audio", "video", "gameplay")
SETTING_TYPES = ("slider", "number", "select", "toggle", "text")

# A game's own video settings that the shared performance block already
# covers better: the display mode, and resolution typed as free text.
_DISPLAY_MODE = re.compile(r"^(window|display|screen) mode$", re.I)


def _duplicate(setting: dict[str, Any]) -> bool:
    label = setting["label"]
    if _DISPLAY_MODE.match(label):
        return True
    return setting["type"] == "text" and "resolution" in label.lower()


def _compose(game: dict[str, Any]) -> dict[str, Any]:
    sections = []
    for section in game["sections"]:
        settings = section["settings"]
        if section["id"] == "video":
            settings = [s for s in settings if not _duplicate(s)]
        sections.append({**section, "settings": settings})
    return {**game, "sections": [*performance_sections(), *sections]}


@lru_cache(maxsize=1)
def load_catalog() -> dict[str, Any]:
    """The whole catalog, parsed once per process, with the performance block
    added to every game."""
    with CATALOG_PATH.open(encoding="utf-8") as fh:
        raw = json.load(fh)
    return {**raw, "games": [_compose(g) for g in raw["games"]], "presets": presets()}


def list_games() -> list[dict[str, Any]]:
    return list(load_catalog()["games"])


def get_game(game_id: str) -> dict[str, Any] | None:
    return next((g for g in load_catalog()["games"] if g["id"] == game_id), None)


def settings_by_key(game: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Every setting of a game, keyed by its ``key``, across all sections."""
    return {s["key"]: s for section in game["sections"] for s in section["settings"]}


def keybind_ids(game: dict[str, Any]) -> set[str]:
    return {k["id"] for k in game["keybinds"]}
