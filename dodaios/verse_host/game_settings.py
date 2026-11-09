"""The Verse game settings catalogue: every option of the in-game settings menu.

One list drives three readers: the backend validates ``settings.game`` with it,
``GET /api/verse/settings/catalogue`` hands it to the app's Verse settings page,
and Verse applies the values it receives in ``welcome.settings.game`` and
``settings.changed`` (bridge-protocol 3.2, 12, 14; additive in ``verse.bridge/1``,
announced as the ``game_settings`` feature).

Values live flat in ``settings.game`` under the setting id (``"graphics.shadows":
"high"``). A few settings existed before the catalogue and keep their old place
in ``welcome.settings`` (``gore``, ``reduced_motion``, ``return_key``,
``ui_sound``, ``level_sound``, ``view.*``); their entries carry that ``path``
and are written there instead.

Only options Unreal can apply without extra plugins are listed: the engine's
own anti-aliasing and Temporal Super Resolution, the scalability groups, the
user settings for window, resolution, frame limit and V-Sync.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

QUALITY: Final = ("low", "medium", "high", "epic", "cinematic")
RESOLUTIONS: Final = (
    "native",
    "1280x720",
    "1600x900",
    "1920x1080",
    "2560x1080",
    "2560x1440",
    "3440x1440",
    "3840x1600",
    "3840x2160",
    "5120x1440",
    "5120x2160",
)
FRAME_LIMITS: Final = (
    "30",
    "60",
    "90",
    "120",
    "144",
    "165",
    "180",
    "240",
    "300",
    "360",
    "480",
    "unlimited",
)
KEY_NAME: Final = re.compile(r"^[A-Za-z0-9_+\-]{1,24}$")
# Keys a binding may never take (VerseUI FVerseKeyMap::IsReserved).
RESERVED_KEYS: Final = frozenset(
    {"Escape", "LeftCommand", "RightCommand", "LeftWindows", "RightWindows"}
)


@dataclass(frozen=True)
class Setting:
    id: str
    tab: str
    section: str
    kind: str  # "choice" | "toggle" | "range" | "key"
    default: Any
    options: tuple[str, ...] = ()
    min: float = 0.0
    max: float = 0.0
    step: float = 1.0
    unit: str = ""  # "%", "°", "x", "" (display hint only)
    path: str | None = None  # legacy place in welcome.settings
    restart: bool = False
    advanced: bool = False
    impact: str = ""  # performance cost shown in the menu: "low" | "medium" | "high"
    tags: tuple[str, ...] = field(default=())

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "tab": self.tab,
            "section": self.section,
            "kind": self.kind,
            "default": self.default,
        }
        if self.options:
            out["options"] = list(self.options)
        if self.kind == "range":
            out.update(min=self.min, max=self.max, step=self.step)
        if self.unit:
            out["unit"] = self.unit
        if self.path:
            out["path"] = self.path
        if self.restart:
            out["restart"] = True
        if self.advanced:
            out["advanced"] = True
        if self.impact:
            out["impact"] = self.impact
        if self.tags:
            out["tags"] = list(self.tags)
        return out


def _choice(
    sid: str, tab: str, section: str, options: tuple[str, ...], default: str, **kw: Any
) -> Setting:
    return Setting(sid, tab, section, "choice", default, options=options, **kw)


def _toggle(sid: str, tab: str, section: str, default: bool, **kw: Any) -> Setting:
    return Setting(sid, tab, section, "toggle", default, **kw)


def _range(
    sid: str, tab: str, section: str, lo: float, hi: float, step: float, default: float, **kw: Any
) -> Setting:
    return Setting(sid, tab, section, "range", default, min=lo, max=hi, step=step, **kw)


def _quality(sid: str, default: str = "high", **kw: Any) -> Setting:
    return _choice(sid, "graphics", "quality", QUALITY, default, tags=("preset",), **kw)


# Bindable actions and default keys; mirrors unreal/Verse/Data/ui/keys.json
# (a unit test keeps the two in step). Section = keybind group.
KEYBINDS: Final[tuple[tuple[str, str, str], ...]] = (
    ("move_forward", "W", "movement"),
    ("move_back", "S", "movement"),
    ("move_left", "A", "movement"),
    ("move_right", "D", "movement"),
    ("sprint", "LeftShift", "movement"),
    ("walk", "LeftAlt", "movement"),
    ("crouch", "LeftControl", "movement"),
    ("prone", "Z", "movement"),
    ("jump", "SpaceBar", "movement"),
    ("lean_left", "Q", "movement"),
    ("lean_right", "E", "movement"),
    ("fire", "LeftMouseButton", "combat"),
    ("ads", "RightMouseButton", "combat"),
    ("reload", "R", "combat"),
    ("melee", "V", "combat"),
    ("slot_primary", "One", "combat"),
    ("slot_secondary", "Two", "combat"),
    ("slot_melee", "Three", "combat"),
    ("gadget_a", "G", "equipment"),
    ("gadget_b", "T", "equipment"),
    ("interact", "F", "equipment"),
    ("verse_bar", "Tab", "interface"),
    ("skip_kill_cam", "Enter", "interface"),
    ("return_to_app", "F10", "interface"),
)

CATALOGUE: Final[tuple[Setting, ...]] = (
    # ---------------------------------------------------------------- graphics: display
    _choice(
        "display.window_mode",
        "graphics",
        "display",
        ("fullscreen", "borderless", "windowed"),
        "borderless",
    ),
    _choice("display.resolution", "graphics", "display", RESOLUTIONS, "native", impact="high"),
    _choice("display.frame_limit", "graphics", "display", FRAME_LIMITS, "unlimited", impact="high"),
    _toggle("display.vsync", "graphics", "display", False, impact="low"),
    _range("display.brightness", "graphics", "display", 0, 100, 1, 50),
    _toggle("display.hdr", "graphics", "display", False, restart=True),
    # ---------------------------------------------------------------- graphics: rendering
    _choice(
        "graphics.anti_aliasing",
        "graphics",
        "rendering",
        ("off", "fxaa", "taa", "tsr"),
        "tsr",
        impact="medium",
    ),
    _range(
        "graphics.resolution_scale",
        "graphics",
        "rendering",
        50,
        100,
        1,
        100,
        unit="%",
        impact="high",
    ),
    _range("graphics.sharpening", "graphics", "rendering", 0, 100, 1, 20, unit="%", impact="low"),
    # ---------------------------------------------------------------- graphics: quality
    _choice(
        "graphics.preset",
        "graphics",
        "quality",
        ("auto", *QUALITY, "custom"),
        "auto",
    ),
    _quality("graphics.view_distance", "epic", impact="medium"),
    _quality("graphics.shadows", impact="high"),
    _quality("graphics.global_illumination", impact="high"),
    _quality("graphics.reflections", impact="high"),
    _quality("graphics.textures", "epic", impact="low"),
    _quality("graphics.effects", impact="medium"),
    _quality("graphics.post_processing", impact="medium"),
    _quality("graphics.foliage", impact="low"),
    _quality("graphics.shading", impact="medium"),
    # ---------------------------------------------------------------- graphics: camera effects
    _toggle("graphics.motion_blur", "graphics", "effects", False, impact="low"),
    _toggle("graphics.depth_of_field", "graphics", "effects", True, impact="low"),
    _toggle("graphics.film_grain", "graphics", "effects", False, impact="low"),
    _toggle("graphics.chromatic_aberration", "graphics", "effects", False, impact="low"),
    _toggle("graphics.lens_flares", "graphics", "effects", True, impact="low"),
    _toggle("graphics.bloom", "graphics", "effects", True, impact="low"),
    # ---------------------------------------------------------------- audio
    _range("audio.master", "audio", "volume", 0, 1, 0.01, 0.7, unit="%", path="view.volume"),
    _range("audio.music", "audio", "volume", 0, 1, 0.01, 0.6, unit="%"),
    _range("audio.effects", "audio", "volume", 0, 1, 0.01, 1.0, unit="%"),
    _range("audio.voice", "audio", "volume", 0, 1, 0.01, 1.0, unit="%"),
    _range("audio.ambience", "audio", "volume", 0, 1, 0.01, 0.8, unit="%"),
    _choice("audio.mix", "audio", "output", ("headphones", "speakers", "night"), "headphones"),
    _toggle("audio.mute_unfocused", "audio", "output", True),
    _toggle("audio.hit_sound", "audio", "feedback", True),
    _toggle("audio.ui_sound", "audio", "feedback", True, path="ui_sound"),
    _toggle("audio.level_sound", "audio", "feedback", True, path="level_sound"),
    # ---------------------------------------------------------------- controls: mouse
    _range(
        "controls.sensitivity",
        "controls",
        "mouse",
        0.1,
        10,
        0.05,
        1.0,
        unit="x",
        path="view.sensitivity",
    ),
    _range("controls.ads_multiplier", "controls", "mouse", 0.1, 2, 0.05, 1.0, unit="x"),
    _range("controls.hoverboard_sensitivity", "controls", "mouse", 0.1, 10, 0.05, 1.0, unit="x"),
    _toggle("controls.invert_y", "controls", "mouse", False, path="view.invert_y"),
    _toggle("controls.raw_input", "controls", "mouse", True),
    _toggle("controls.mouse_smoothing", "controls", "mouse", False),
    # ---------------------------------------------------------------- controls: behaviour
    _choice("controls.aim_mode", "controls", "behaviour", ("hold", "toggle"), "hold"),
    _choice("controls.crouch_mode", "controls", "behaviour", ("hold", "toggle"), "toggle"),
    _choice("controls.sprint_mode", "controls", "behaviour", ("hold", "toggle", "auto"), "hold"),
    _choice("controls.lean_mode", "controls", "behaviour", ("hold", "toggle"), "hold"),
    # ---------------------------------------------------------------- controls: camera
    _range("controls.fov_duel", "controls", "camera", 80, 110, 1, 100, unit="°"),
    _range(
        "controls.fov_first", "controls", "camera", 60, 120, 1, 85, unit="°", path="view.fov_first"
    ),
    _range(
        "controls.fov_third", "controls", "camera", 50, 110, 1, 70, unit="°", path="view.fov_third"
    ),
    _choice(
        "controls.view_mode",
        "controls",
        "camera",
        ("third", "first", "overview"),
        "third",
        path="view.mode",
    ),
    _choice("controls.shoulder", "controls", "camera", ("right", "left"), "right"),
    _range("controls.view_bob", "controls", "camera", 0, 100, 1, 60, unit="%"),
    # ---------------------------------------------------------------- gameplay
    _choice("gameplay.gore", "gameplay", "combat", ("full", "reduced"), "full", path="gore"),
    _toggle("gameplay.kill_cam", "gameplay", "combat", True),
    _toggle("gameplay.auto_reload", "gameplay", "combat", True),
    _choice(
        "gameplay.bot_tier", "gameplay", "duel", ("normal", "hard", "elite", "adaptive"), "hard"
    ),
    _toggle("gameplay.show_duel_stats", "gameplay", "duel", True),
    # ---------------------------------------------------------------- interface
    _range("hud.scale", "interface", "hud", 0.5, 1.5, 0.05, 1.0, unit="%"),
    _range("hud.opacity", "interface", "hud", 0.2, 1, 0.05, 1.0, unit="%"),
    _toggle("hud.hit_markers", "interface", "hud", True),
    _toggle("hud.damage_numbers", "interface", "hud", False),
    _toggle("hud.damage_direction", "interface", "hud", True),
    _choice("hud.performance_stats", "interface", "hud", ("off", "fps", "full"), "off"),
    _choice(
        "hud.crosshair_style",
        "interface",
        "crosshair",
        ("cross", "dot", "cross_dot", "circle"),
        "cross_dot",
    ),
    _choice(
        "hud.crosshair_color",
        "interface",
        "crosshair",
        ("amber", "white", "green", "cyan", "magenta"),
        "amber",
    ),
    _range("hud.crosshair_size", "interface", "crosshair", 1, 10, 1, 4),
    _range("hud.crosshair_thickness", "interface", "crosshair", 1, 4, 1, 2),
    _range("hud.crosshair_gap", "interface", "crosshair", 0, 10, 1, 3),
    _toggle("hud.crosshair_outline", "interface", "crosshair", True),
    _toggle("hud.crosshair_dynamic", "interface", "crosshair", True),
    # ---------------------------------------------------------------- accessibility
    _choice(
        "access.colorblind",
        "accessibility",
        "vision",
        ("off", "protanopia", "deuteranopia", "tritanopia"),
        "off",
    ),
    _range("access.colorblind_strength", "accessibility", "vision", 0, 10, 1, 5),
    _range("access.text_scale", "accessibility", "vision", 0.8, 1.6, 0.05, 1.0, unit="%"),
    _toggle("access.high_contrast", "accessibility", "vision", False),
    _toggle("access.reduced_motion", "accessibility", "motion", False, path="reduced_motion"),
    _range("access.camera_shake", "accessibility", "motion", 0, 1, 0.05, 1.0, unit="%"),
    _toggle("access.flash_reduction", "accessibility", "motion", False),
    _toggle("access.subtitles", "accessibility", "hearing", True),
    _toggle("access.sound_visualizer", "accessibility", "hearing", False),
    # ---------------------------------------------------------------- keybinds
    *(
        Setting(
            f"keybinds.{action}",
            "keybinds",
            group,
            "key",
            key,
            path="return_key" if action == "return_to_app" else None,
        )
        for action, key, group in KEYBINDS
    ),
)

TABS: Final = (
    "graphics",
    "audio",
    "controls",
    "keybinds",
    "gameplay",
    "interface",
    "accessibility",
)
BY_ID: Final[dict[str, Setting]] = {s.id: s for s in CATALOGUE}
# The quality groups a preset sets at once.
PRESET_GROUPS: Final = tuple(s.id for s in CATALOGUE if "preset" in s.tags)


class GameSettingsError(ValueError):
    """A ``settings.game`` key or value the catalogue does not allow."""


def game_defaults() -> dict[str, Any]:
    """Defaults of every setting stored in ``settings.game`` (no legacy paths)."""
    return {s.id: s.default for s in CATALOGUE if s.path is None}


def _is_number(v: Any) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool)


def check_value(setting: Setting, value: Any) -> Any:
    """``value`` checked against one setting; returns it normalised."""
    if setting.kind == "toggle":
        if not isinstance(value, bool):
            raise GameSettingsError(f"{setting.id} must be true or false")
        return value
    if setting.kind == "choice":
        if value not in setting.options:
            raise GameSettingsError(
                f"{setting.id} {value!r} is not one of {', '.join(setting.options)}"
            )
        return value
    if setting.kind == "range":
        if not _is_number(value) or not setting.min <= value <= setting.max:
            raise GameSettingsError(f"{setting.id} must be {setting.min:g}..{setting.max:g}")
        return value
    if setting.kind == "key":
        if not isinstance(value, str) or not KEY_NAME.match(value) or value in RESERVED_KEYS:
            raise GameSettingsError(f"{setting.id} must be a key name other than Escape")
        return value
    raise GameSettingsError(f"{setting.id} has an unknown kind")


def validate_game(patch: Any) -> dict[str, Any]:
    """A ``settings.game`` patch checked key by key; unknown or legacy keys raise."""
    if not isinstance(patch, dict) or not patch:
        raise GameSettingsError("game must be a non-empty object")
    out: dict[str, Any] = {}
    for key, value in patch.items():
        setting = BY_ID.get(key)
        if setting is None:
            raise GameSettingsError(f"unknown setting game.{key}")
        if setting.path is not None:
            raise GameSettingsError(f"game.{key} is stored at {setting.path}")
        out[key] = check_value(setting, value)
    return out


def duplicate_keys(bindings: dict[str, str]) -> list[str]:
    """Keys bound to more than one action (the movement axes are separate keys too)."""
    seen: dict[str, str] = {}
    dupes: list[str] = []
    for action, key in bindings.items():
        if key in seen:
            dupes.append(key)
        seen[key] = action
    return dupes


def catalogue_json() -> dict[str, Any]:
    """The catalogue for the app's Verse settings page."""
    return {
        "schema": "verse.settings.catalogue/1",
        "tabs": list(TABS),
        "preset_groups": list(PRESET_GROUPS),
        "settings": [s.to_json() for s in CATALOGUE],
    }


# The Unreal Verse reads the catalogue from this file (VerseUI FVerseGameSettingsCatalogue); a unit
# test keeps it equal to catalogue_json(). Rewrite it with
# ``python -m dodaios.verse_host.game_settings``.
UNREAL_CATALOGUE: Final = Path("unreal") / "Verse" / "Data" / "ui" / "game_settings.json"


def unreal_catalogue_text() -> str:
    """The catalogue file the Unreal Verse ships, byte for byte."""
    return json.dumps(catalogue_json(), indent=2, ensure_ascii=False) + "\n"


def main() -> None:
    """Writes the Unreal copy of the catalogue (run from the repository root)."""
    UNREAL_CATALOGUE.write_text(unreal_catalogue_text(), encoding="utf-8", newline="\n")
    print(f"wrote {UNREAL_CATALOGUE}")


if __name__ == "__main__":
    main()
