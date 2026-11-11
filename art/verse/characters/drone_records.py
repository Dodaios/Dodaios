"""Import records and MI recipes of the drones from a `drones_unreal.py` result.

Pure Python (no bpy): `scripts/verse/export_unreal.py drones` calls `write_all` after the
Blender run. Each drone has its own skeleton next to its mesh; clips go under
`/Game/Verse/Animations/Drones/`. The MIs follow the character recipes (`fps/records.py`).
"""

from __future__ import annotations

import colorsys
from pathlib import Path

from characters.fps import records as R

OWNER = "WP13"
BUILDER = "art/verse/characters/drones_unreal.py"
FOLDER = "/Game/Verse/Characters/Drones"
CLIP_FOLDER = "/Game/Verse/Animations/Drones"


def skeleton_name(mesh: str) -> str:
    """`SK_Drone_Companion` -> `SKEL_Drone_Companion`."""
    return "SKEL_" + mesh[len("SK_") :]


def texture_name(entry: dict, key: str) -> str:
    return f"T_Drone_{entry['kind']}_{R.ATLAS_SUFFIX[key]}"


def texture_path(entry: dict, key: str) -> str:
    name = texture_name(entry, key)
    return f"{FOLDER}/Textures/{name}.{name}"


def _export(entry: dict) -> dict:
    return R._export(entry)


def mesh_record(entry: dict) -> dict:
    return {
        "schema": "verse.import/1",
        "name": entry["name"],
        "asset_path": f"{FOLDER}/{entry['name']}.{entry['name']}",
        "kind": "skeletal_mesh",
        "source": {"builder": BUILDER, "function": "build_one", "args": {"kind": entry["kind"]}},
        "export": _export(entry),
        "mesh": {
            "triangles": entry["triangles"],
            "vertices": entry["vertices"],
            "bounds_cm": entry["bounds_cm"],
            "uv_sets": entry["uv_sets"],
            "material_slots": [{"slot": s["slot"], "mi": s["mi"]} for s in entry["material_slots"]],
            "bones": entry["bones"],
        },
        "nanite": {"enabled": False},
        "collision": {"profile": "Verse_NoCollision", "source": "none", "primitives": 0},
        "lod": {"mode": "single", "screen_sizes": [1.0]},
        "lightmap": "none",
        "license": {"kind": "own"},
        "owner": OWNER,
    }


def skeleton_record(entry: dict) -> dict:
    name = skeleton_name(entry["name"])
    return {
        "schema": "verse.import/1",
        "name": name,
        "asset_path": f"{FOLDER}/{name}.{name}",
        "kind": "skeleton",
        "source": {"builder": BUILDER, "function": "build_one", "args": {"kind": entry["kind"]}},
        "export": _export(entry),
        "lightmap": "none",
        "license": {"kind": "own"},
        "owner": OWNER,
    }


def clip_record(clip: dict) -> dict:
    return {
        "schema": "verse.import/1",
        "name": clip["name"],
        "asset_path": f"{CLIP_FOLDER}/{clip['name']}.{clip['name']}",
        "kind": "animation",
        "source": {
            "builder": "art/verse/characters/drones.py",
            "function": "companion_clips" if "_Companion_" in clip["name"] else "utility_clips",
            "args": {"fps": clip["fps"], "loop": clip["loop"]},
        },
        "export": _export(clip),
        "lightmap": "none",
        "license": {"kind": "own"},
        "owner": OWNER,
    }


def texture_record(entry: dict, key: str, export: dict) -> dict:
    settings = R.ATLAS_MAPS[key][1]
    return {
        "schema": "verse.import/1",
        "name": texture_name(entry, key),
        "asset_path": texture_path(entry, key),
        "kind": "texture",
        "source": {"builder": BUILDER, "function": "build_one", "args": {"kind": entry["kind"]}},
        "export": {
            "format": "png",
            "settings_id": "png-ue/1",
            "file": export["file"],
            "sha256": export["sha256"],
            "blender": "0.0.0",
        },
        "texture": {**settings, "max_size": 512, "never_stream": True, "channels": {}},
        "lightmap": "none",
        "license": {"kind": "own"},
        "owner": OWNER,
    }


#: Highest sRGB saturation of a glow colour (art-pipeline 8.3 bans cyan above 0.35).
GLOW_MAX_SATURATION = 0.33


def _srgb(c: float) -> float:
    c = max(0.0, min(1.0, c))
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def glow_colour(rgba: list[float]) -> list[float]:
    """The glow's linear colour, paled toward its own grey until its sRGB saturation is at most
    `GLOW_MAX_SATURATION`. The three.js glow (emission strength 6) already reads near white on
    screen; the paler colour keeps it that way through Unreal's tone curve."""
    rgb = list(rgba[:3])
    grey = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]
    for _ in range(100):
        if colorsys.rgb_to_hsv(*(_srgb(c) for c in rgb))[1] <= GLOW_MAX_SATURATION:
            break
        rgb = [grey + (c - grey) * 0.97 for c in rgb]
    return [round(c, 5) for c in rgb] + list(rgba[3:])


def mi_recipe(entry: dict, slot: dict) -> dict:
    doc = R.mi_recipe(entry["kind"], {k: v for k, v in slot.items() if k != "textures"})
    if slot.get("emit"):
        doc["vectors"]["EmissiveColor"] = glow_colour(slot["base_color"])
    if not slot.get("emit") and slot.get("textures"):
        doc["textures"] = {
            R.ATLAS_MAPS[key][0]: texture_path(entry, key) for key in slot["textures"]
        }
    doc["owner"] = OWNER
    return doc


def write_all(result: dict, project: Path) -> list[str]:
    """Write every record and recipe; returns the paths that changed."""
    imports = project / "Art" / "Import"
    changed: list[str] = []

    def put(path: Path, doc: dict) -> None:
        if R._dump(path, doc):
            changed.append(path.as_posix())

    for entry in result["drones"]:
        folder = imports / "Characters" / "Drones"
        put(folder / f"{entry['name']}.import.json", mesh_record(entry))
        put(folder / f"{skeleton_name(entry['name'])}.import.json", skeleton_record(entry))
        for key, export in entry["textures"].items():
            put(
                folder / f"{texture_name(entry, key)}.import.json",
                texture_record(entry, key, export),
            )
        for slot in entry["material_slots"]:
            name = slot["mi"].rsplit(".", 1)[1]
            put(project / "Art" / "Materials" / f"{name}.mi.json", mi_recipe(entry, slot))
        for clip in entry["clips"]:
            put(
                imports / "Animations" / "Drones" / f"{clip['name']}.import.json", clip_record(clip)
            )
    return changed
