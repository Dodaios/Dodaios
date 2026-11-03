"""The gore asset list (WP05): one table read by the editor step and the record writer.

Pure data, no ``unreal`` or ``bpy`` import, so ``unreal_assets.py`` (inside the
editor) and ``records.py`` (plain Python) describe the same assets.
"""

from __future__ import annotations

OWNER = "WP05"
GORE = "/Game/Verse/Gore"
TEST = "/Game/Verse/Test/WP05"

# Mask textures: name -> (max size, channel meaning). Built by textures.py.
TEXTURES: dict[str, int] = {
    "T_Gore_Spatter_0_M": 512,
    "T_Gore_Spatter_1_M": 512,
    "T_Gore_Spatter_2_M": 512,
    "T_Gore_Spatter_3_M": 512,
    "T_Gore_Drip_M": 512,
    "T_Gore_Pool_M": 1024,
}
TEXTURE_CHANNELS = {
    "r": "coverage (decal opacity)",
    "g": "thickness (darker and glossier where blood is thick)",
    "b": "unused, 0",
}

# Decal instances of M_Gore_Decal: name -> (mask texture, scalar overrides).
INSTANCES: dict[str, tuple[str, dict[str, float]]] = {
    "MI_Gore_Spatter_0": ("T_Gore_Spatter_0_M", {}),
    "MI_Gore_Spatter_1": ("T_Gore_Spatter_1_M", {}),
    "MI_Gore_Spatter_2": ("T_Gore_Spatter_2_M", {}),
    "MI_Gore_Spatter_3": ("T_Gore_Spatter_3_M", {}),
    "MI_Gore_Drip": ("T_Gore_Drip_M", {"RoughnessThick": 0.1}),
    "MI_Gore_Pool": ("T_Gore_Pool_M", {"RoughnessThick": 0.05, "RoughnessThin": 0.2}),
}

# Masters, the material function and the test material:
# name -> (folder, kind, builder function, use).
MATERIALS: dict[str, tuple[str, str, str, str]] = {
    "M_Gore_Decal": (GORE, "material", "build_decal_master",
                     "deferred decal master: Mask texture, decal colour R = opacity, "
                     "G = darkening"),
    "M_Gore_Droplet": (GORE, "material", "build_droplet",
                       "burst droplets on an instanced static mesh; world position offset animates "
                       "each instance from 7 custom data floats (spawn time, velocity xyz, life, "
                       "drag, gravity)"),
    "M_Gore_Flash": (GORE, "material", "build_flash",
                     "Reduced level: neutral, unlit, additive impact flash"),
    "MF_Gore_WoundMask": (GORE, "material_function", "build_wound_function",
                          "wound mask for the character master: Verse_WoundCount and "
                          "Verse_Wound_00..15 (xyz reference-pose component space cm, w radius cm) "
                          "against the pre-skinned position"),
    "M_Gore_TestBody": (TEST, "material", "build_test_body",
                        "WP13 fake: a body material using the wound mask (test only)"),
}


def asset_path(folder: str, name: str) -> str:
    return f"{folder}/{name}.{name}"
