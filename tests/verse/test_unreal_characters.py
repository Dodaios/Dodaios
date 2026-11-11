"""WP13 characters: skeleton table, clip catalogue, records and the C++ twins.

Pure Python, no Blender or Unreal: the frozen bone names of art-pipeline
12.1 (A13.1), the finisher phase times of combat-state 7.4 (A13.2), the
licence of every imported mesh (A13.7), and that the C++ tables in
`VerseMovement/Private/Anim/VerseHumanSkeleton.cpp` match the Python ones.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "art" / "verse"))

from characters.fps import catalogue as K  # noqa: E402
from characters.fps import records as R  # noqa: E402
from characters.fps import skeleton as S  # noqa: E402

CPP = REPO / "unreal/Verse/Source/VerseMovement/Private/Anim/VerseHumanSkeleton.cpp"
IMPORTS = REPO / "unreal/Verse/Art/Import"
MATERIALS = REPO / "unreal/Verse/Art/Materials"
GRIPS = REPO / "art/verse/characters/fps/grip_reference.json"

#: art-pipeline 12.1 spelled out once more, independent of skeleton.py.
SPEC_CENTRE = ["Root", "Hips", "Spine_01", "Spine_02", "Spine_03", "Neck", "Head", "Camera"]
SPEC_SIDE = [
    "Clavicle", "UpperArm", "LowerArm", "Hand", "UpperArm_Twist", "LowerArm_Twist",
    *[f"{f}_0{j}" for f in ("Thumb", "Index", "Middle", "Ring", "Pinky") for j in (1, 2, 3)],
    "Thigh", "Calf", "Foot", "Ball", "Thigh_Twist", "Calf_Twist", "Weapon",
]  # fmt: skip
SPEC_IK = ["IK_Foot_Root", "IK_Foot_L", "IK_Foot_R", "IK_Hand_Root", "IK_Hand_Gun",
           "IK_Hand_L", "IK_Hand_R"]  # fmt: skip


def spec_names() -> set[str]:
    side = {f"{b}_{s}" for b in SPEC_SIDE for s in ("L", "R")}
    return set(SPEC_CENTRE) | side | set(SPEC_IK)


def test_bone_names_match_art_pipeline_12_1():
    assert set(S.NAMES) == spec_names()
    assert len(S.NAMES) == len(set(S.NAMES))
    assert len(S.NAMES) <= S.MAX_BONES
    assert S.check_names(S.NAMES) == []


def test_hierarchy_follows_12_1():
    p = S.PARENT
    assert p["Root"] is None and p["Hips"] == "Root"
    assert [p["Spine_01"], p["Spine_02"], p["Spine_03"]] == ["Hips", "Spine_01", "Spine_02"]
    assert p["Camera"] == "Head"
    for s in ("L", "R"):
        assert p[f"Weapon_{s}"] == f"Hand_{s}"
        assert p[f"IK_Foot_{s}"] == "IK_Foot_Root"
        assert p[f"IK_Hand_{s}"] == "IK_Hand_Gun"
        assert p[f"Thumb_03_{s}"] == f"Thumb_02_{s}"
    assert p["IK_Hand_Gun"] == "IK_Hand_Root" and p["IK_Foot_Root"] == "Root"
    order = list(S.NAMES)
    for bone, parent in S.BONES:
        if parent:
            assert order.index(parent) < order.index(bone)


def test_check_names_reports_problems():
    assert S.check_names(list(S.NAMES) + ["Extra"])
    assert S.check_names([n for n in S.NAMES if n != "Camera"])


def test_spine_shares_sum_to_one():
    assert sum(s for _, s in S.SPINE_SHARE) == pytest.approx(1.0)
    assert [b for b, _ in S.SPINE_SHARE] == ["Spine_01", "Spine_02", "Spine_03"]


def test_hit_bodies_cover_every_zone():
    zones = {z for *_, z in S.HIT_BODIES}
    assert zones == {"Head", "Neck", "UpperTorso", "LowerTorso", "Arm", "Leg"}
    for bone, end, radius, _ in S.HIT_BODIES:
        assert bone in S.PARENT and (end is None or end in S.PARENT) and radius > 0


def test_catalogue_contract_numbers():
    assert K.problems() == []
    markers = dict(K.FINISHER_MARKERS)
    assert markers == {"Takedown": 0.25, "Struggle": 0.9, "Kill": 1.8, "Recover": 2.1,
                       "Release": 2.5}  # fmt: skip
    rifle, pistol = K.WEAPON_CLASSES["Rifle"], K.WEAPON_CLASSES["Pistol"]
    assert (rifle["tactical"], rifle["empty"]) == (2.1, 2.8)
    assert (pistol["tactical"], pistol["empty"]) == (1.5, 1.9)
    assert K.BY_NAME["A_Rifle_Reload_Tactical"].seconds == 2.1
    assert K.BY_NAME["A_Pistol_Reload_Empty"].seconds == 1.9
    assert K.BY_NAME["A_Mantle_Low"].seconds == 0.45
    assert K.BY_NAME["A_Mantle_High"].seconds == 0.85
    assert K.SPEEDS == {"Stand": 4.5, "Crouch": 2.2, "Prone": 0.9, "Sprint": 6.5}


def test_catalogue_covers_every_sub_task():
    names = set(K.BY_NAME)
    for stance in ("Stand", "Crouch", "Prone"):
        assert f"A_{stance}_Idle" in names
        for heading in K.HEADINGS:
            assert f"A_{stance}_Move_{heading}" in names
    for must in ("A_Sprint_F", "A_Jump_Start", "A_Fall_Loop", "A_Land", "A_Slide",
                 "A_Mantle_Low", "A_Mantle_High", "A_Stand_Lean_L", "A_Crouch_Lean_R",
                 "A_Knife_Strike", "A_Finisher_Attacker", "A_Finisher_Victim",
                 "A_Death_Front", "A_Hit_Head", "A_KillCam_Rifle_Fire"):  # fmt: skip
        assert must in names
    for cls in K.WEAPON_CLASSES:
        for what in ("Idle", "ADS", "Fire", "Reload_Tactical", "Reload_Empty", "Equip", "Holster"):
            assert f"A_{cls}_{what}" in names
    crew = {c.name for c in K.CLIPS if c.group == "Crew"}
    for activity in ("Sit_Idle", "Sit_Type", "Stand", "Walk", "Talk", "Bunk"):
        assert f"A_Crew_{activity}" in crew


def _cpp_list(begin: str, end: str) -> list[str]:
    text = CPP.read_text(encoding="utf-8")
    block = text.split(f"// {begin}")[1].split(f"// {end}")[0]
    return re.findall(r'TEXT\("([^"]+)"\)', block)


def test_cpp_bone_table_matches_python():
    text = CPP.read_text(encoding="utf-8")
    block = text.split("// BONES-BEGIN")[1].split("// BONES-END")[0]
    pairs = re.findall(r'B\(TEXT\("([^"]+)"\), (?:TEXT\("([^"]+)"\)|nullptr)\)', block)
    assert [(b, p or None) for b, p in pairs] == list(S.BONES)


def test_cpp_optional_bones_match_python():
    text = CPP.read_text(encoding="utf-8")
    block = text.split("// OPTIONAL-BONES-BEGIN")[1].split("// OPTIONAL-BONES-END")[0]
    pairs = re.findall(r'B\(TEXT\("([^"]+)"\), TEXT\("([^"]+)"\)\)', block)
    assert pairs == list(S.CLOAK_BONES)


def test_check_names_accepts_the_optional_cloak_bones():
    assert S.check_names(list(S.NAMES) + [b for b, _ in S.CLOAK_BONES]) == []
    assert S.check_hierarchy(dict(S.BONES) | dict(S.CLOAK_BONES)) == []


def test_cpp_hit_zone_table_matches_hit_bodies():
    """combat-state 5: the bone -> EVerseHitZone table ships with PHYS_Verse_Human."""
    text = CPP.read_text(encoding="utf-8")
    block = text.split("// HITZONES-BEGIN")[1].split("// HITZONES-END")[0]
    rows = re.findall(r'Z\(TEXT\("([^"]+)"\), EVerseHitZone::(\w+)\)', block)
    assert rows == [(bone, zone) for bone, _, _, zone in S.HIT_BODIES]


def test_cpp_clip_and_mesh_tables_match_python():
    assert _cpp_list("CLIPS-BEGIN", "CLIPS-END") == [c.name for c in K.CLIPS]
    assert _cpp_list("MESHES-BEGIN", "MESHES-END") == [m.asset_path for m in K.MESHES]


def test_cpp_grip_reference_matches_json():
    grips = json.loads(GRIPS.read_text(encoding="utf-8"))
    text = CPP.read_text(encoding="utf-8")
    for cls in ("Rifle", "Pistol"):
        m = re.search(rf"FVector {cls}\(([^)]+)\)", text)
        values = [float(v.strip().rstrip("f")) for v in m.group(1).split(",")]
        assert values == pytest.approx(grips[cls]["support_cm"], abs=1e-3)


def _records() -> list[tuple[Path, dict]]:
    out = []
    for folder in ("Characters", "Animations"):
        for path in sorted((IMPORTS / folder).rglob("*.import.json")):
            out.append((path, json.loads(path.read_text(encoding="utf-8"))))
    return out


def test_every_catalogue_asset_has_a_record():
    names = {doc["name"] for _, doc in _records()}
    assert {m.name for m in K.MESHES} <= names
    assert {c.name for c in K.CLIPS} <= names
    assert {S.SKELETON, S.PHYSICS} <= names


def test_records_follow_the_schema():
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((REPO / "art/verse/schema/import.schema.json").read_text(encoding="utf-8"))
    for path, doc in _records():
        jsonschema.validate(doc, schema)
        assert doc["owner"] == "WP13", path
        assert path.name == f"{doc['name']}.import.json"


def test_every_mesh_cites_a_ledger_row_or_own():
    ledger = (REPO / "art/verse/LICENSES.md").read_text(encoding="utf-8")
    for path, doc in _records():
        lic = doc["license"]
        assert lic["kind"] in ("own", "ledger"), path
        if lic["kind"] == "ledger":
            for sha in lic["ledger_sha256"]:
                assert sha in ledger, (path, sha)
        if doc["kind"] == "skeletal_mesh":
            assert lic == {"kind": "ledger", "ledger_sha256": [R.BASE_MESH_LEDGER]}
            assert doc["mesh"]["triangles"] <= 80_000
            assert S.check_names(doc["mesh"]["bones"]) == []


def test_mi_recipes_follow_the_schema():
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads((REPO / "art/verse/schema/mi.schema.json").read_text(encoding="utf-8"))
    recipes = sorted(MATERIALS.glob("MI_Character_*.mi.json"))
    assert recipes
    for path in recipes:
        doc = json.loads(path.read_text(encoding="utf-8"))
        jsonschema.validate(doc, schema)
        # glowing slots (the Sovereign's eyes) sit on the emissive master
        assert doc["parent"] in (R.CHARACTER_MASTER, R.EMISSIVE_MASTER)


def test_write_all_is_stable(tmp_path):
    mesh = {
        "name": "SK_Crew_M", "file": "art/verse/.cache/unreal/characters/meshes/SK_Crew_M.fbx",
        "sha256": "0" * 64, "settings_id": "fbx-ue/1", "blender": "5.0.1", "triangles": 10,
        "vertices": 12, "bounds_cm": {"min": [0, 0, 0], "max": [1, 1, 1]}, "uv_sets": 1,
        "bones": list(S.NAMES),
        "material_slots": [{"slot": "M_Uniform", "mi": "/Game/Verse/Materials/Instances/"
                            "Characters/MI_Character_Crew_Uniform.MI_Character_Crew_Uniform",
                            "base_color": [0.1, 0.1, 0.1, 1.0], "roughness": 0.7,
                            "metallic": 0.0}],
    }  # fmt: skip
    result = {"meshes": [mesh], "clips": [], "grips": {}}
    first = R.write_all(result, tmp_path / "Verse", tmp_path / "art")
    assert len(first) == 2
    assert R.write_all(result, tmp_path / "Verse", tmp_path / "art") == []
