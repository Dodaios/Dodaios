"""Import records, MI recipes and the grip reference from a `rig_fps.py` result.

Pure Python (no bpy): `scripts/verse/export_unreal.py characters` calls
`write_all` after the Blender run. Every record follows `verse.import/1`
(art-pipeline 10.3); a re-export rewrites a file only when its content
changed, so untouched assets keep their LFS objects (art-pipeline 10.2).
"""

from __future__ import annotations

import json
from pathlib import Path

from characters.fps import catalogue as K
from characters.fps import skeleton as S

#: SHA-256 of the CC0 human base mesh bundle row in art/verse/LICENSES.md.
BASE_MESH_LEDGER = "811f43accbb31a88266d932f8f5563b2d13586fca0ba2693aad1f5fe582b3515"
BUILDER = "art/verse/characters/rig_fps.py"
CHARACTER_MASTER = "/Game/Verse/Materials/Master/M_Verse_Character.M_Verse_Character"
LOD_SCREEN_SIZES = [1.0, 0.5, 0.25, 0.12]


def _dump(path: Path, doc: dict) -> bool:
    text = json.dumps(doc, indent=2, sort_keys=True) + "\n"
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))
    return True


def _export(entry: dict) -> dict:
    return {
        "format": "fbx",
        "settings_id": entry["settings_id"],
        "file": entry["file"],
        "sha256": entry["sha256"],
        "blender": entry["blender"],
    }


def mesh_record(entry: dict) -> dict:
    spec = next(m for m in K.MESHES if m.name == entry["name"])
    return {
        "schema": "verse.import/1",
        "name": spec.name,
        "asset_path": spec.asset_path,
        "kind": "skeletal_mesh",
        "source": {
            "builder": BUILDER,
            "function": "build_mesh",
            "args": {"uniform": spec.uniform, "variant": spec.variant},
        },
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
        "lod": {"mode": "auto", "screen_sizes": LOD_SCREEN_SIZES},
        "lightmap": "none",
        "license": {"kind": "ledger", "ledger_sha256": [BASE_MESH_LEDGER]},
        "owner": K.OWNER,
    }


def rig_record(entry: dict, name: str, kind: str, function: str) -> dict:
    return {
        "schema": "verse.import/1",
        "name": name,
        "asset_path": f"{S.RIG_FOLDER}/{name}.{name}",
        "kind": kind,
        "source": {"builder": BUILDER, "function": function, "args": {}},
        "export": _export(entry),
        "lightmap": "none",
        "license": {"kind": "ledger", "ledger_sha256": [BASE_MESH_LEDGER]},
        "owner": K.OWNER,
    }


def clip_record(entry: dict) -> dict:
    clip = K.BY_NAME[entry["name"]]
    return {
        "schema": "verse.import/1",
        "name": clip.name,
        "asset_path": clip.asset_path,
        "kind": "animation",
        "source": {
            "builder": "art/verse/characters/fps/clips.py",
            "function": "author",
            "args": {"fps": clip.fps, "loop": clip.loop},
        },
        "export": _export(entry),
        "lightmap": "none",
        "license": {"kind": "own"},
        "owner": K.OWNER,
    }


def mi_recipe(uniform: str, slot: dict) -> dict:
    name = slot["mi"].rsplit(".", 1)[1]
    return {
        "schema": "verse.mi/1",
        "name": name,
        "parent": CHARACTER_MASTER,
        "scalars": {"Roughness": slot["roughness"], "Metallic": slot["metallic"]},
        "vectors": {"BaseTint": slot["base_color"]},
        "textures": {},
        "switches": {},
        "owner": K.OWNER,
        "replaces": slot["slot"],
    }


def write_all(result: dict, project: Path, art: Path) -> list[str]:
    """Write every record and recipe; returns the paths that changed."""
    imports = project / "Art" / "Import"
    changed: list[str] = []

    def put(path: Path, doc: dict) -> None:
        if _dump(path, doc):
            changed.append(path.as_posix())

    by_name = {m["name"]: m for m in result["meshes"]}
    for entry in result["meshes"]:
        spec = next(m for m in K.MESHES if m.name == entry["name"])
        put(imports / "Characters" / spec.uniform / f"{spec.name}.import.json", mesh_record(entry))
        for slot in entry["material_slots"]:
            name = slot["mi"].rsplit(".", 1)[1]
            put(project / "Art" / "Materials" / f"{name}.mi.json", mi_recipe(spec.uniform, slot))
    source = by_name.get(K.SKELETON_SOURCE)
    if source is not None:
        put(
            imports / "Characters" / "Rig" / f"{S.SKELETON}.import.json",
            rig_record(source, S.SKELETON, "skeleton", "Variant"),
        )
        put(
            imports / "Characters" / "Rig" / f"{S.PHYSICS}.import.json",
            rig_record(source, S.PHYSICS, "physics_asset", "skeleton.HIT_BODIES"),
        )
    for entry in result["clips"]:
        clip = K.BY_NAME[entry["name"]]
        put(imports / "Animations" / clip.group / f"{clip.name}.import.json", clip_record(entry))
    if result.get("grips"):
        put(
            art / "characters" / "fps" / "grip_reference.json",
            {"schema": "verse.grips/1", "frame": "weapon Root, Unreal axes, cm", **result["grips"]},
        )
    return changed
