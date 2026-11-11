"""The drones in Unreal: records, clips and MIs match the three.js drones (WP13)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "art" / "verse"))

from characters import drone_records as DR  # noqa: E402

PROJECT = REPO / "unreal" / "Verse"
IMPORTS = PROJECT / "Art" / "Import"
CHARACTERS = REPO / "dodaios" / "ui" / "web" / "frontend" / "public" / "verse" / "characters"
DRONES = ("SK_Drone_Companion", "SK_Drone_Utility")


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _three_models() -> dict:
    return {m["id"]: m for m in _load(CHARACTERS / "characters.json")["models"]}


def test_every_drone_has_mesh_skeleton_and_atlas_records():
    for name in DRONES:
        mesh = _load(IMPORTS / "Characters" / "Drones" / f"{name}.import.json")
        assert mesh["kind"] == "skeletal_mesh"
        assert mesh["asset_path"] == f"/Game/Verse/Characters/Drones/{name}.{name}"
        skel = _load(IMPORTS / "Characters" / "Drones" / f"{DR.skeleton_name(name)}.import.json")
        assert skel["kind"] == "skeleton"
        assert skel["export"]["sha256"] == mesh["export"]["sha256"]
        kind = name.rsplit("_", 1)[1]
        for suffix in ("BC", "N", "ORM"):
            tex = _load(IMPORTS / "Characters" / "Drones" / f"T_Drone_{kind}_{suffix}.import.json")
            assert tex["kind"] == "texture"
            assert tex["texture"]["srgb"] is (suffix == "BC")


def test_bones_and_materials_are_the_three_js_ones():
    three = _three_models()
    for name in DRONES:
        mesh = _load(IMPORTS / "Characters" / "Drones" / f"{name}.import.json")["mesh"]
        assert mesh["bones"] == three[name]["bones"]
        slots = [s["slot"] for s in mesh["material_slots"]]
        assert sorted(slots) == sorted(three[name]["materials"])
        # same build: the same triangle count as the three.js export
        assert mesh["triangles"] == three[name]["triangles"]


def test_every_three_js_clip_reached_unreal():
    three = _three_models()
    for name in DRONES:
        kind = name.rsplit("_", 1)[1]
        for clip, info in three[name]["clips"].items():
            record = _load(
                IMPORTS / "Animations" / "Drones" / f"A_Drone_{kind}_{clip[2:]}.import.json"
            )
            assert record["kind"] == "animation"
            assert record["source"]["args"]["loop"] is info["loop"]


def test_glow_is_emissive_and_textured_slots_read_the_atlas():
    for name in DRONES:
        kind = name.rsplit("_", 1)[1]
        mesh = _load(IMPORTS / "Characters" / "Drones" / f"{name}.import.json")["mesh"]
        for slot in mesh["material_slots"]:
            mi = slot["mi"].rsplit(".", 1)[1]
            recipe = _load(PROJECT / "Art" / "Materials" / f"{mi}.mi.json")
            if slot["slot"] == "M_Glow":
                assert recipe["parent"].endswith("M_Verse_Emissive")
                assert recipe["scalars"]["EmissiveNits"] > 0
            elif slot["slot"] != "M_Lens":
                assert recipe["textures"]["BaseColorMap"].endswith(f"T_Drone_{kind}_BC")
                # the atlas carries the roughness (glTF factor 1)
                assert recipe["scalars"]["Roughness"] == 1.0
