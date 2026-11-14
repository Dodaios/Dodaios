"""The designs Dodaios ships, as starting points and examples.

Each one sets both appearances, so it works whether the app is dark or light,
and shows one of the animated backgrounds. They are read-only; asking Dodaios
to change one saves a copy of the person's own.
"""

from __future__ import annotations

import copy
from typing import Any

_PRESETS: tuple[dict[str, Any], ...] = (
    {
        "id": "deep-sea",
        "name": "Deep Sea",
        "description": "Cool blue-green room with a slow glow drifting through it.",
        "dark": {"background": "#07131c", "foreground": "#e6f1f5", "accent": "#2fb8c9"},
        "light": {"background": "#f2f8fa", "foreground": "#0d2230", "accent": "#0f7f90"},
        "background": {
            "style": "glow",
            "colors": ["#0e5c73", "#1f3f8f", "#3a2a7a"],
            "speed": "slow",
            "strength": 0.55,
        },
    },
    {
        "id": "ember",
        "name": "Ember",
        "description": "Warm dark brown with orange light, like a fire burning low.",
        "dark": {"background": "#140c09", "foreground": "#f6ebe4", "accent": "#ff7a3d"},
        "light": {"background": "#fbf5f0", "foreground": "#2a1710", "accent": "#c4501a"},
        "background": {
            "style": "glow",
            "colors": ["#7a2410", "#b5541a", "#5a1630"],
            "speed": "slow",
            "strength": 0.5,
        },
    },
    {
        "id": "forest",
        "name": "Forest",
        "description": "Deep green with soft bands of light moving across.",
        "dark": {"background": "#0a120d", "foreground": "#e7f0e8", "accent": "#5fcf8a"},
        "light": {"background": "#f3f7f2", "foreground": "#14261a", "accent": "#2f8a52"},
        "background": {
            "style": "waves",
            "colors": ["#174a2c", "#2d6b3c", "#0f3a3a"],
            "speed": "slow",
            "strength": 0.5,
        },
    },
    {
        "id": "night-sky",
        "name": "Night Sky",
        "description": "Ink blue with small stars that twinkle.",
        "dark": {"background": "#070815", "foreground": "#e8e9f7", "accent": "#8b8cff"},
        "light": {"background": "#f4f4fb", "foreground": "#15162e", "accent": "#5153d6"},
        "background": {
            "style": "stars",
            "colors": ["#ffffff", "#c9d2ff", "#ffd9a8"],
            "speed": "medium",
            "strength": 0.7,
        },
    },
    {
        "id": "dusk",
        "name": "Dusk",
        "description": "Violet and rose in a gradient that turns slowly.",
        "dark": {"background": "#120d1a", "foreground": "#f1eaf6", "accent": "#e28bd0"},
        "light": {"background": "#faf5fb", "foreground": "#24162c", "accent": "#a8448f"},
        "background": {
            "style": "gradient",
            "colors": ["#3b1f5c", "#7a2e5a", "#1f3b6b"],
            "speed": "medium",
            "strength": 0.45,
        },
    },
    {
        "id": "paper",
        "name": "Paper",
        "description": "Warm cream paper with brown ink and no animation.",
        "dark": {"background": "#1a1712", "foreground": "#efe7da", "accent": "#e08a5a"},
        "light": {
            "background": "#f7f2e8",
            "foreground": "#2b241b",
            "accent": "#b5562b",
            "card": "#fffdf8",
            "sidebar": "#f0e9dc",
        },
        "background": {"style": "none", "colors": [], "speed": "slow", "strength": 0.5},
    },
)


def builtin_designs() -> list[dict[str, Any]]:
    """The shipped designs, each a fresh copy marked ``builtin``."""
    out: list[dict[str, Any]] = []
    for preset in _PRESETS:
        design = copy.deepcopy(preset)
        design.update({"builtin": True, "created_at": 0.0, "updated_at": 0.0})
        out.append(design)
    return out
