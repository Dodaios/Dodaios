"""Graphics & performance settings every game gets, plus one-click presets.

The per-game catalog lists each game's own video options under the names the
game prints. On top of that every game gets this one block: the target the
player tunes for (resolution up to 5K, FPS cap up to unlimited, upscaler,
frame generation, latency, every detail level), grouped so the page can draw
it as display / rendering / detail / effects, and four presets that fill it
in one click.

All keys start with ``perf_`` so they never collide with a game's own keys.
"""

from __future__ import annotations

import copy
from typing import Any

QUALITY = ["Low", "Medium", "High", "Ultra", "Epic"]

#: (width, height, short name) from HD to 5K, ultrawides included.
RESOLUTIONS: list[tuple[int, int, str]] = [
    (1280, 720, "HD"),
    (1600, 900, "HD+"),
    (1920, 1080, "Full HD"),
    (2560, 1080, "UW Full HD"),
    (2560, 1440, "QHD"),
    (3440, 1440, "UWQHD"),
    (3840, 1600, "UW4K"),
    (3840, 2160, "4K UHD"),
    (5120, 1440, "DQHD"),
    (5120, 2160, "5K2K"),
    (5120, 2880, "5K"),
]


def resolution_value(width: int, height: int) -> str:
    return f"{width}x{height}"


REFRESH_RATES = [
    "60 Hz",
    "75 Hz",
    "120 Hz",
    "144 Hz",
    "165 Hz",
    "180 Hz",
    "240 Hz",
    "280 Hz",
    "360 Hz",
    "480 Hz",
    "540 Hz",
]
FPS_CAPS = ["30", "60", "90", "120", "144", "165", "180", "240", "300", "360", "480", "Unlimited"]

UNLIMITED = "Unlimited"


def _select(
    key: str, label: str, options: list[str], default: str | None, note: str = ""
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "key": key,
        "label": label,
        "type": "select",
        "options": options,
        "default": default,
    }
    if note:
        out["note"] = note
    return out


def _toggle(key: str, label: str, default: bool, note: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {"key": key, "label": label, "type": "toggle", "default": default}
    if note:
        out["note"] = note
    return out


def _slider(
    key: str, label: str, low: float, high: float, step: float, default: float, note: str = ""
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "key": key,
        "label": label,
        "type": "slider",
        "min": low,
        "max": high,
        "step": step,
        "default": default,
    }
    if note:
        out["note"] = note
    return out


def _quality(key: str, label: str, note: str = "") -> dict[str, Any]:
    return _select(key, label, QUALITY, "High", note)


#: The block, in display order. ``group`` is what the page draws a card for.
PERFORMANCE_GROUPS: list[dict[str, Any]] = [
    {
        "id": "display",
        "settings": [
            _select(
                "perf_resolution",
                "Resolution",
                [resolution_value(w, h) for w, h, _ in RESOLUTIONS],
                "1920x1080",
            ),
            _select(
                "perf_display_mode",
                "Display Mode",
                ["Fullscreen", "Borderless", "Windowed"],
                "Fullscreen",
                "Fullscreen gives the lowest input latency on most PCs.",
            ),
            _select(
                "perf_refresh_rate", "Refresh Rate", REFRESH_RATES, None, "Match your monitor."
            ),
            _select(
                "perf_fps_cap",
                "FPS Limit",
                FPS_CAPS,
                None,
                "Unlimited lets the game render as many frames as your PC can.",
            ),
            _select(
                "perf_vsync",
                "V-Sync",
                ["Off", "On", "Adaptive"],
                "Off",
                "Off for the lowest latency.",
            ),
            _toggle("perf_vrr", "G-Sync / FreeSync", True),
            _toggle("perf_hdr", "HDR", False),
            _slider("perf_brightness", "Brightness", 0, 100, 1, 50),
        ],
    },
    {
        "id": "rendering",
        "settings": [
            _select("perf_preset", "Quality Preset", [*QUALITY, "Custom"], "High"),
            _slider(
                "perf_render_scale",
                "Render Scale",
                50,
                200,
                5,
                100,
                "Percent of your resolution the game renders at. Above 100 % supersamples.",
            ),
            _select(
                "perf_upscaler",
                "Upscaler",
                ["Off", "DLSS", "FSR", "XeSS", "TSR"],
                "Off",
                "DLSS needs an NVIDIA RTX card; FSR and XeSS run on any GPU.",
            ),
            _select(
                "perf_upscaler_mode",
                "Upscaler Mode",
                ["Native AA", "Quality", "Balanced", "Performance", "Ultra Performance"],
                "Quality",
            ),
            _slider("perf_sharpening", "Sharpening", 0, 100, 1, 50),
            _toggle(
                "perf_frame_gen",
                "Frame Generation",
                False,
                "More frames on screen, slightly more latency. Not for competitive play.",
            ),
            _select(
                "perf_low_latency",
                "Low Latency (Reflex / Anti-Lag)",
                ["Off", "On", "On + Boost"],
                "On",
            ),
            _select(
                "perf_gpu_priority",
                "Prioritize",
                ["Balanced", "Frame Rate", "Image Quality"],
                "Balanced",
            ),
        ],
    },
    {
        "id": "detail",
        "settings": [
            _quality(
                "perf_textures", "Texture Quality", "Uses VRAM, barely affects FPS when it fits."
            ),
            _quality("perf_shadows", "Shadow Quality"),
            _quality("perf_effects", "Effects Quality"),
            _quality("perf_post", "Post-Processing"),
            _quality("perf_view_distance", "View Distance"),
            _quality("perf_foliage", "Foliage / Vegetation"),
            _quality("perf_geometry", "Mesh / Model Detail"),
            _quality("perf_volumetrics", "Volumetric Fog & Clouds"),
            _select(
                "perf_aa",
                "Anti-Aliasing",
                ["Off", "FXAA", "SMAA", "TAA", "MSAA 2x", "MSAA 4x", "MSAA 8x"],
                "TAA",
            ),
            _select("perf_af", "Anisotropic Filtering", ["Off", "2x", "4x", "8x", "16x"], "16x"),
            _select("perf_ao", "Ambient Occlusion", ["Off", "SSAO", "HBAO+", "Ray Traced"], "SSAO"),
        ],
    },
    {
        "id": "raytracing",
        "settings": [
            _select(
                "perf_rt",
                "Ray Tracing",
                ["Off", "Low", "Medium", "High", "Ultra", "Path Tracing"],
                "Off",
            ),
            _select(
                "perf_rt_reflections", "RT Reflections", ["Off", "Low", "Medium", "High"], "Off"
            ),
            _select(
                "perf_rt_gi", "RT Global Illumination", ["Off", "Low", "Medium", "High"], "Off"
            ),
            _toggle("perf_ray_reconstruction", "Ray Reconstruction", False, "DLSS 3.5+ only."),
        ],
    },
    {
        "id": "effects",
        "settings": [
            _toggle("perf_motion_blur", "Motion Blur", False),
            _toggle("perf_dof", "Depth of Field", False),
            _toggle("perf_film_grain", "Film Grain", False),
            _toggle("perf_chromatic", "Chromatic Aberration", False),
            _toggle("perf_lens_flare", "Lens Flare", False),
            _toggle("perf_bloom", "Bloom", True),
            _toggle("perf_vignette", "Vignette", False),
        ],
    },
]

_DETAIL_KEYS = [
    "perf_textures",
    "perf_shadows",
    "perf_effects",
    "perf_post",
    "perf_view_distance",
    "perf_foliage",
    "perf_geometry",
    "perf_volumetrics",
]
_EFFECT_KEYS = [
    "perf_motion_blur",
    "perf_dof",
    "perf_film_grain",
    "perf_chromatic",
    "perf_lens_flare",
    "perf_vignette",
]


def _details(level: str, **overrides: str) -> dict[str, Any]:
    out: dict[str, Any] = {key: level for key in _DETAIL_KEYS}
    out.update(overrides)
    return out


def _effects(on: bool) -> dict[str, Any]:
    return {key: on for key in _EFFECT_KEYS}


#: One-click bundles. Resolution, refresh rate and the FPS cap of a preset
#: that says "native"/"monitor" are filled from the detected monitor by the page.
PRESETS: list[dict[str, Any]] = [
    {
        "id": "competitive",
        "values": {
            "perf_preset": "Custom",
            "perf_display_mode": "Fullscreen",
            "perf_fps_cap": UNLIMITED,
            "perf_vsync": "Off",
            "perf_vrr": False,
            "perf_render_scale": 100,
            "perf_upscaler": "Off",
            "perf_frame_gen": False,
            "perf_low_latency": "On + Boost",
            "perf_gpu_priority": "Frame Rate",
            **_details("Low", perf_textures="Medium", perf_view_distance="High"),
            "perf_aa": "FXAA",
            "perf_af": "8x",
            "perf_ao": "Off",
            "perf_rt": "Off",
            "perf_rt_reflections": "Off",
            "perf_rt_gi": "Off",
            "perf_ray_reconstruction": False,
            **_effects(False),
            "perf_bloom": False,
            "perf_sharpening": 60,
        },
    },
    {
        "id": "balanced",
        "values": {
            "perf_preset": "High",
            "perf_display_mode": "Fullscreen",
            "perf_fps_cap": "monitor",
            "perf_vsync": "Off",
            "perf_vrr": True,
            "perf_render_scale": 100,
            "perf_upscaler": "DLSS",
            "perf_upscaler_mode": "Quality",
            "perf_frame_gen": False,
            "perf_low_latency": "On",
            "perf_gpu_priority": "Balanced",
            **_details("High", perf_shadows="Medium", perf_volumetrics="Medium"),
            "perf_aa": "TAA",
            "perf_af": "16x",
            "perf_ao": "SSAO",
            "perf_rt": "Off",
            "perf_rt_reflections": "Off",
            "perf_rt_gi": "Off",
            **_effects(False),
            "perf_bloom": True,
            "perf_sharpening": 50,
        },
    },
    {
        "id": "quality",
        "values": {
            "perf_preset": "Ultra",
            "perf_display_mode": "Fullscreen",
            "perf_fps_cap": "monitor",
            "perf_vsync": "Off",
            "perf_vrr": True,
            "perf_render_scale": 100,
            "perf_upscaler": "DLSS",
            "perf_upscaler_mode": "Native AA",
            "perf_frame_gen": False,
            "perf_low_latency": "On",
            "perf_gpu_priority": "Image Quality",
            **_details("Ultra"),
            "perf_aa": "TAA",
            "perf_af": "16x",
            "perf_ao": "HBAO+",
            "perf_rt": "Medium",
            "perf_rt_reflections": "Medium",
            "perf_rt_gi": "Medium",
            "perf_ray_reconstruction": True,
            **_effects(False),
            "perf_bloom": True,
            "perf_dof": True,
            "perf_sharpening": 40,
        },
    },
    {
        "id": "epic",
        "values": {
            "perf_preset": "Epic",
            "perf_display_mode": "Fullscreen",
            "perf_fps_cap": UNLIMITED,
            "perf_vsync": "Off",
            "perf_vrr": True,
            "perf_render_scale": 100,
            "perf_upscaler": "DLSS",
            "perf_upscaler_mode": "Quality",
            "perf_frame_gen": True,
            "perf_low_latency": "On + Boost",
            "perf_gpu_priority": "Image Quality",
            **_details("Epic"),
            "perf_aa": "TAA",
            "perf_af": "16x",
            "perf_ao": "Ray Traced",
            "perf_rt": "Path Tracing",
            "perf_rt_reflections": "High",
            "perf_rt_gi": "High",
            "perf_ray_reconstruction": True,
            **_effects(False),
            "perf_bloom": True,
            "perf_dof": True,
            "perf_lens_flare": True,
            "perf_hdr": True,
            "perf_sharpening": 35,
        },
    },
]


def performance_sections() -> list[dict[str, Any]]:
    """A fresh copy of the block as catalog sections (``perf_<group>``)."""
    return [
        {"id": f"perf_{group['id']}", "settings": copy.deepcopy(group["settings"])}
        for group in PERFORMANCE_GROUPS
    ]


def presets() -> list[dict[str, Any]]:
    return copy.deepcopy(PRESETS)
