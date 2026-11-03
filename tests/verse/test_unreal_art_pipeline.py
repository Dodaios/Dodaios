"""Art pipeline entry points of the Unreal Verse (G0.7, contracts/art-pipeline.md).

No Blender and no Unreal: the pure parts of the export, the placement format,
the static check and the editor-side `verse_pipeline` package. The engine
part of the `fbx-ue/1` calibration runs with `python scripts/unreal/import_art.py
calib --export` on a machine with Blender and the editor.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import math
import random
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ART = REPO_ROOT / "art" / "verse"
PIPELINE = REPO_ROOT / "unreal" / "Verse" / "Content" / "Python"
VECTORS = REPO_ROOT / "unreal" / "Verse" / "Art" / "space_vectors.json"

for _path in (ART, PIPELINE):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from lib import placement, ue_space, unreal_materials  # noqa: E402
from verse_pipeline import (  # noqa: E402
    calib,
    import_assets,
    records,
    sync_placements,
    validate_assets,  # noqa: E402
)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


check_art_text = _load("check_art_text", REPO_ROOT / "scripts" / "unreal" / "check_art_text.py")


def _close(a, b, tol=1e-9):
    return all(abs(p - q) <= tol for p, q in zip(a, b, strict=True))


# --- Space (art-pipeline 4.1) -------------------------------------------------


def test_location_is_mirrored_across_xz_and_scaled_to_centimetres():
    assert ue_space.location_to_ue((1.0, 2.0, 3.0)) == [100.0, -200.0, 300.0]
    assert ue_space.location_from_ue([100.0, -200.0, 300.0]) == [1.0, 2.0, 3.0]
    assert ue_space.three_to_ue((1.0, 2.0, 3.0)) == [100.0, 300.0, 200.0]


def test_three_and_blender_paths_agree():
    # three.js (x, y, z) is Blender (x, -z, y).
    for x, y, z in [(1.0, 2.0, 3.0), (-4.5, 0.25, 7.0)]:
        assert _close(ue_space.three_to_ue((x, y, z)), ue_space.location_to_ue((x, -z, y)))


def test_blender_yaw_90_turns_bow_to_port_which_is_unreal_minus_y():
    quat = ue_space.quat_to_ue(ue_space.yaw_quat_wxyz(90.0))
    assert _close(ue_space.rotate_vector_xyzw(quat, [1.0, 0.0, 0.0]), [0.0, -1.0, 0.0])
    assert ue_space.yaw_to_ue(90.0) == -90.0


def test_quaternion_conversion_commutes_with_the_mirror():
    rng = random.Random(7)  # noqa: S311 - deterministic test vectors
    for _ in range(500):
        q = [rng.uniform(-1, 1) for _ in range(4)]
        norm = math.sqrt(sum(c * c for c in q))
        q = [c / norm for c in q]
        v = [rng.uniform(-5, 5) for _ in range(3)]
        blender_rotated = ue_space.rotate_vector_wxyz(q, v)
        unreal_rotated = ue_space.rotate_vector_xyzw(
            ue_space.quat_to_ue(q), ue_space.direction_to_ue(v)
        )
        assert _close(ue_space.direction_to_ue(blender_rotated), unreal_rotated, 1e-9)
        assert ue_space.quat_to_ue(q)[3] >= 0.0


def test_space_vectors_file_matches_the_python_conversion():
    checker = check_art_text.Checker(REPO_ROOT)
    checker.space_vectors()
    assert checker.errors == []
    doc = json.loads(VECTORS.read_text(encoding="utf-8"))
    assert doc["calibration"]["settings_id"] == "fbx-ue/1"
    assert doc["calibration"]["SM_Calib_Axes"]["bounds_cm"] == {
        "min": [-10.0, -50.0, 0.0],
        "max": [100.0, 10.0, 80.0],
    }


def test_calibration_numbers_match_the_kit_builder_source():
    """kit/calib.py needs bpy; read its constants as text so the two cannot drift."""
    text = (ART / "kit" / "calib.py").read_text(encoding="utf-8")
    consts = {
        name: float(value)
        for name, value in (
            line.split("#")[0].replace(" ", "").split("=")
            for line in text.splitlines()
            if line[:1].isupper() and "=" in line and "(" not in line and '"' not in line
        )
    }
    spec = json.loads(VECTORS.read_text(encoding="utf-8"))["calibration"]["SM_Calib_Axes"]
    lo, hi = ue_space.bounds_to_ue(
        (-consts["HUB"], -consts["HUB"], 0.0), (consts["X_TIP"], consts["Y_TIP"], consts["Z_TIP"])
    )
    assert _close(lo, spec["bounds_cm"]["min"]) and _close(hi, spec["bounds_cm"]["max"])
    top_at_tip = (consts["HUB"] + consts["ARM"] - consts["CHAMFER"]) * 100.0
    assert math.isclose(top_at_tip, spec["x_tip"]["max_z_cm"])


# --- Materials mapping (art-pipeline 7) ----------------------------------------


def test_blender_materials_map_to_instances_in_owned_groups():
    assert unreal_materials.instance_name("M_Wall_Charcoal.001") == "MI_Wall_Charcoal"
    assert (
        unreal_materials.instance_path("M_Struct_Gunmetal")
        == "/Game/Verse/Materials/Instances/Metal/MI_Struct_Gunmetal.MI_Struct_Gunmetal"
    )
    assert unreal_materials.group_for("M_Crate_Paint") == "Props"
    with pytest.raises(ValueError):
        unreal_materials.instance_name("Material.001")


# --- Placement JSON (art-pipeline 4) --------------------------------------------


def _placement_doc() -> dict:
    return {
        "schema": "verse.placement/1",
        "deck": "hangar",
        "zone": "arena_canyon",
        "bounds_cm": {"min": [-5000.0, -3100.0, 0.0], "max": [5000.0, 3100.0, 2000.0]},
        "level": "/Game/Verse/Decks/Hangar/LV_Hangar",
        "source": {"builder": "art/verse/decks/hangar/zones/arena_canyon.py", "sha256": "a" * 64},
        "generator": {"script": "export_unreal.py", "version": "1", "blender": "5.0.1"},
        "placements": [
            {
                "id": "container_wall_a",
                "piece": "GC_ContainerWall_240",
                "asset": "/Game/Verse/Destruction/GC_ContainerWall_240.GC_ContainerWall_240",
                "location": [120.0, -240.0, 0.0],
                "rotation": [0.0, 0.0, -0.7071068, 0.7071068],
                "scale": [1.0, 1.0, 1.0],
                "room": "canyon",
                "nav": "block",
                "mobility": "movable",
                "data_layer": "DL_Hangar_Arena",
                "collision": "Verse_Destructible",
                "destructible": {
                    "actor_class": "/Script/VerseDestruction.VerseContainerWall",
                    "penetration_material": "ContainerSteel",
                    "health": 600,
                    "states": ["Intact", "Damaged", "Holed", "Breached", "Destroyed"],
                    "proxies": {
                        s: f"/Game/Verse/Destruction/SM_ContainerWall_240_Proxy_{s}"
                        f".SM_ContainerWall_240_Proxy_{s}"
                        for s in ("Intact", "Holed", "Breached", "Destroyed")
                    },
                    "repair_s": 30,
                },
                "station": None,
                "owner": "WP11",
            },
            {
                "id": "floor_a",
                "piece": "SM_Floor_480",
                "asset": "/Game/Verse/Kit/Architecture/SM_Floor_480.SM_Floor_480",
                "location": [0.0, 0.0, 0.0],
                "rotation": [0.0, 0.0, 0.0, 1.0],
                "scale": [1.0, 1.0, 1.0],
                "room": None,
                "nav": "walk",
                "mobility": "static",
                "data_layer": "DL_Hangar_Base",
                "collision": "Verse_Architecture",
                "destructible": None,
                "station": None,
                "owner": "WP11",
                "tags": ["Verse.Arena.Cover"],
            },
        ],
        "sockets": [
            {
                "id": "floor_a__spawn_1",
                "kind": "spawn",
                "location": [100.0, 100.0, 0.0],
                "rotation": [0.0, 0.0, 0.0, 1.0],
                "room": "canyon",
                "station": None,
                "spawn": {"team": "a", "duel": True},
            },
            {
                "id": "floor_a__screen_1",
                "kind": "screen",
                "location": [100.0, 100.0, 150.0],
                "rotation": [0.0, 0.0, 0.0, 1.0],
                "room": None,
                "station": {"id": "arm_1", "kind": "armoury"},
                "size_cm": [120.0, 70.0],
            },
        ],
        "rooms": [
            {
                "id": "canyon",
                "name": "Canyon",
                "polygon_cm": [[-1000, -1000], [1000, -1000], [1000, 1000]],
                "z_cm": 0,
                "main": True,
            }
        ],
    }


def test_a_complete_placement_document_is_valid():
    assert placement.validate(_placement_doc()) == []


@pytest.mark.parametrize(
    ("mutate", "needle"),
    [
        (lambda d: d["placements"][1].update(location=[9000.0, 0.0, 0.0]), "outside bounds_cm"),
        (lambda d: d["placements"][1].update(id="container_wall_a"), "duplicate id"),
        (lambda d: d["placements"][1].update(rotation=[0.0, 0.0, 0.5, 0.5]), "unit quaternion"),
        (lambda d: d["placements"][1].update(room="nowhere"), "not in rooms"),
        (lambda d: d["placements"][1].update(data_layer="DL_Bridge_Base"), "data_layer"),
        (lambda d: d["placements"][0].update(mobility="static"), "must be movable"),
        (lambda d: d["placements"][0]["destructible"]["proxies"].pop("Holed"), "proxies missing"),
        (lambda d: d["placements"][1].update(piece="SM_Floor_240"), "is not the piece"),
        (lambda d: d.update(level="/Game/Verse/Decks/Bridge/LV_Bridge"), "level must be"),
        (lambda d: d["placements"][1].update(owner="Team"), "owner"),
        (lambda d: d["sockets"][1].pop("size_cm"), "size_cm"),
        (lambda d: d["sockets"][0].update(size_cm=[1, 1]), "size_cm"),
        (lambda d: d["placements"][1].update(tags=["Game.Cover"]), "tags"),
        (lambda d: d["placements"][1].update(collision="BlockAll"), "collision"),
        (lambda d: d.update(schema="verse.placement/2"), "schema"),
    ],
)
def test_placement_rules_reject_broken_documents(mutate, needle):
    doc = copy.deepcopy(_placement_doc())
    mutate(doc)
    errors = placement.validate(doc)
    assert errors, f"expected an error about {needle}"
    assert any(needle in e for e in errors), errors


def test_placement_assets_must_have_records_when_known_assets_are_given():
    errors = placement.validate(_placement_doc(), known_assets=set())
    assert any("no import record" in e for e in errors)


def test_canonical_form_is_stable_sorted_and_lf(tmp_path):
    doc = _placement_doc()
    doc["placements"].reverse()
    doc["placements"][0]["location"] = [0.00000001, -0.0, 0.0]
    path = tmp_path / "hangar" / "arena_canyon.placement.json"
    assert placement.write(path, doc) is True
    assert placement.write(path, json.loads(path.read_text(encoding="utf-8"))) is False
    raw = path.read_bytes()
    assert b"\r\n" not in raw and raw.endswith(b"\n")
    written = json.loads(raw)
    assert [p["id"] for p in written["placements"]] == ["container_wall_a", "floor_a"]
    assert written["placements"][1]["location"] == [0.0, 0.0, 0.0]
    assert placement.validate_file(path) == []


def test_validate_file_flags_non_canonical_text(tmp_path):
    path = tmp_path / "hangar" / "arena_canyon.placement.json"
    path.parent.mkdir()
    path.write_text(json.dumps(_placement_doc()), encoding="utf-8")
    assert any("canonical" in e for e in placement.validate_file(path))


def test_auto_ids_snap_to_15_cm_and_one_degree_and_deduplicate():
    auto = placement.auto_id("SM_Wall_480", [107.0, -52.0, 0.0], -90.4)
    assert auto == "sm_wall_480_105_m45_0_270"
    assert placement.unique_ids(["a", "b", "a", "a"]) == ["a", "b", "a_2", "a_3"]
    assert placement.sanitize_id("Pit-P.1") == "pit_p_1"


def test_level_and_layer_names_follow_the_deck():
    assert placement.level_path("engineering") == "/Game/Verse/Decks/Engineering/LV_Engineering"
    assert placement.base_layer("ops") == "DL_Ops_Base"


# --- Static check (art-pipeline 10.3, 14) ---------------------------------------


def _scratch_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    shutil.copytree(ART / "schema", root / "art" / "verse" / "schema")
    shutil.copy(ART / "LICENSES.md", root / "art" / "verse" / "LICENSES.md")
    (root / "art" / "verse" / "lib").mkdir(parents=True)
    art = root / "unreal" / "Verse" / "Art"
    art.mkdir(parents=True)
    shutil.copy(VECTORS, art / "space_vectors.json")
    return root


def _record(name="SM_Wall_480", folder="/Game/Verse/Kit/Architecture") -> dict:
    return {
        "schema": "verse.import/1",
        "name": name,
        "asset_path": f"{folder}/{name}.{name}",
        "kind": "static_mesh",
        "source": {
            "builder": "art/verse/kit/architecture/walls.py",
            "function": "wall",
            "args": {},
        },
        "export": {
            "format": "fbx",
            "settings_id": "fbx-ue/1",
            "file": f"art/verse/.cache/unreal/kit/{name}.fbx",
            "sha256": "b" * 64,
            "blender": "5.0.1",
        },
        "mesh": {
            "triangles": 1200,
            "vertices": 900,
            "bounds_cm": {"min": [-240.0, -30.0, 0.0], "max": [240.0, 0.0, 450.0]},
            "uv_sets": 1,
            "material_slots": [
                {
                    "slot": "M_Wall_Charcoal",
                    "mi": "/Game/Verse/Materials/Instances/Walls/MI_Wall_Charcoal.MI_Wall_Charcoal",
                }
            ],
        },
        "nanite": {"enabled": True},
        "collision": {"profile": "Verse_Architecture", "source": "auto_box", "primitives": 0},
        "lod": {"mode": "nanite"},
        "lightmap": "none",
        "license": {"kind": "own"},
        "owner": "WP12",
    }


def _write(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = payload if isinstance(payload, str) else json.dumps(payload, indent=2)
    path.write_bytes(text.encode("utf-8"))
    return path


def _with_asset(root: Path, record: dict) -> None:
    folder = record["asset_path"].split(".")[0].replace("/Game/Verse/", "")
    _write(root / "unreal" / "Verse" / "Content" / "Verse" / f"{folder}.uasset", "pointer")
    group = record["asset_path"].split("/")[4]
    records_dir = root / "unreal" / "Verse" / "Art" / "Import" / "Kit" / group
    _write(records_dir / f"{record['name']}.import.json", record)


def _errors(root: Path) -> list[str]:
    return check_art_text.Checker(root).run()


def test_the_repository_art_text_is_clean():
    assert check_art_text.main([]) == 0


def test_an_imported_asset_with_its_record_passes(tmp_path):
    root = _scratch_root(tmp_path)
    _with_asset(root, _record())
    assert _errors(root) == []


def test_a_record_without_asset_and_an_asset_without_record_fail(tmp_path):
    root = _scratch_root(tmp_path)
    record = _record()
    _write(root / "unreal/Verse/Art/Import/Kit/Architecture/SM_Wall_480.import.json", record)
    _write(root / "unreal/Verse/Content/Verse/Kit/Architecture/SM_Lonely_120.uasset", "pointer")
    errors = _errors(root)
    assert any("record has no asset" in e for e in errors)
    assert any("SM_Lonely_120.uasset: no import record" in e for e in errors)


@pytest.mark.parametrize(
    ("mutate", "needle"),
    [
        (lambda r: r.update(owner="WP14"), "belongs to WP12"),
        (lambda r: r["mesh"].update(triangles=600_000), "cap 500000"),
        (
            lambda r: r.update(license={"kind": "ledger", "ledger_sha256": ["c" * 64]}),
            "ledger row",
        ),
        (lambda r: r.update(lightmap="generated"), "lightmap"),
        (lambda r: r["export"].update(file="C:/tmp/x.fbx"), "export/file"),
        (lambda r: r.update(kind="skeletal_mesh"), "does not fit the name"),
    ],
)
def test_record_rules(tmp_path, mutate, needle):
    root = _scratch_root(tmp_path)
    record = _record()
    mutate(record)
    _with_asset(root, record)
    errors = _errors(root)
    assert any(needle in e for e in errors), errors


def test_ledger_rows_that_exist_pass(tmp_path):
    root = _scratch_root(tmp_path)
    record = _record()
    row = "1da6ddb0f455d53636754b3b629942e6aec2f77fafaf6a53cee102ec107854c1"
    record["license"] = {"kind": "ledger", "ledger_sha256": [row]}
    _with_asset(root, record)
    assert _errors(root) == []


def test_texture_records_follow_the_texture_rules(tmp_path):
    root = _scratch_root(tmp_path)
    record = _record("T_Hull_N", "/Game/Verse/Textures/Hull")
    record.update(kind="texture", owner="WP12")
    record["export"].update(format="png", file="art/verse/.cache/unreal/tex/T_Hull_N.png")
    del record["mesh"], record["nanite"], record["collision"], record["lod"]
    record["texture"] = {
        "group": "WorldNormalMap",
        "max_size": 4096,
        "srgb": True,
        "compression": "Normalmap",
        "flip_green": False,
    }
    _with_asset(root, record)
    errors = "\n".join(_errors(root))
    assert "max_size 4096 > 2048" in errors
    assert "flip green" in errors
    assert "linear" in errors


def test_banned_names_folders_and_engine_content(tmp_path):
    root = _scratch_root(tmp_path)
    _write(root / "unreal/Verse/Content/Verse/Kit/Thing.uasset", "pointer")
    _write(root / "unreal/Verse/Content/Verse/Kit/SKM_Manny_Simple.uasset", "pointer")
    _write(root / "art/verse/Renders/a.txt", "x")
    _write(root / "unreal/Verse/Build/Windows/icon.txt", "allowed")
    errors = "\n".join(_errors(root))
    assert "Thing: prefix not in art-pipeline section 3" in errors
    assert "engine sample content" in errors
    assert "folder name 'Renders' is banned" in errors
    assert "Build" not in errors


def test_material_recipes_reject_banned_colours(tmp_path):
    root = _scratch_root(tmp_path)
    recipe = {
        "schema": "verse.mi/1",
        "name": "MI_Light_Panel",
        "parent": "/Game/Verse/Materials/Master/M_Verse_Emissive.M_Verse_Emissive",
        "scalars": {"EmissiveNits": 40.0},
        "vectors": {
            "BaseTint": [0.02, 0.02, 0.022, 1.0],
            "EmissiveColor": [0.0, 0.6, 0.6, 1.0],
        },
        "textures": {},
        "switches": {"UseTriplanar": False},
        "owner": "WP12",
        "replaces": "M_Light_CeilingPanel",
    }
    path = _write(root / "unreal/Verse/Art/Materials/MI_Light_Panel.mi.json", recipe)
    errors = "\n".join(_errors(root))
    assert "EmissiveColor: banned colour (cyan" in errors
    recipe["vectors"]["EmissiveColor"] = [1.0, 0.36, 0.04, 1.0]  # amber
    _write(path, recipe)
    assert _errors(root) == []


def test_gold_is_banned_outside_the_allowlist():
    def linear(c):
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    rgba = [linear(0xC8), linear(0xA2), linear(0x4A), 1.0]
    assert check_art_text.colour_bans("BaseTint", rgba, gold_allowed=False)
    assert not check_art_text.colour_bans("BaseTint", rgba, gold_allowed=True)


def test_placements_in_the_tree_are_checked_against_records(tmp_path):
    root = _scratch_root(tmp_path)
    doc = _placement_doc()
    doc["placements"] = [doc["placements"][1]]
    doc["sockets"] = []
    _write(
        root / "unreal/Verse/Art/Placements/hangar/arena_canyon.placement.json",
        placement.dumps(doc),
    )
    assert any("no import record" in e for e in _errors(root))
    _with_asset(root, _record("SM_Floor_480"))
    assert _errors(root) == []


# --- verse_pipeline pure parts ------------------------------------------------


def test_object_paths_split_into_folder_and_name():
    split = records.split_object_path("/Game/Verse/Kit/A/SM_X.SM_X")
    assert split == ("/Game/Verse/Kit/A", "SM_X")
    with pytest.raises(records.RecordError):
        records.split_object_path("/Game/Verse/Kit/A/SM_X.SM_Y")


def test_import_plan_skips_unchanged_exports():
    rec = _record()
    other = _record("SM_Wall_240")
    tex = dict(_record("T_A_BC"), kind="texture")
    steps = import_assets.plan([rec, other, tex], {rec["asset_path"]: rec["export"]["sha256"]})
    assert [(r["name"], a) for r, a in steps] == [
        ("SM_Wall_480", "skip"),
        ("SM_Wall_240", "import"),
        ("T_A_BC", "unsupported"),
    ]


def test_sync_plan_updates_in_place_creates_deletes_and_ignores_manual_actors():
    doc = _placement_doc()
    actors = [
        {"key": "a", "tags": ["verse.zone:arena_canyon", "verse.pid:floor_a"]},
        {"key": "b", "tags": ["verse.zone:arena_canyon", "verse.pid:gone"]},
        {"key": "c", "tags": ["verse.zone:arena_canyon", "verse.manual"]},
        {"key": "d", "tags": ["verse.zone:shell", "verse.pid:floor_a"]},
        {"key": "e", "tags": ["verse.zone:arena_canyon", "verse.pid:floor_a"]},
    ]
    steps = sync_placements.plan(doc, actors)
    assert [k for k, _ in steps["update"]] == ["a"]
    assert sorted(steps["delete"]) == ["b", "e"]
    assert steps["duplicates"] == ["e"]
    assert [p["id"] for p in steps["create"]] == ["container_wall_a"]
    assert sync_placements.actor_tags("z", "p") == ["verse.zone:z", "verse.pid:p"]


def test_validate_assets_compares_records_with_asset_facts():
    rec = _record()
    assert validate_assets.compare(rec, {"exists": False})[0].endswith("does not exist")
    facts = {"exists": True, "nanite": True, "lightmap_uvs": False, "slots": ["M_Wall_Charcoal"]}
    assert validate_assets.compare(rec, facts) == []
    facts.update(nanite=False, lightmap_uvs=True, slots=["Other"])
    assert len(validate_assets.compare(rec, facts)) == 3


def _cube():
    v = [[x, y, z] for x in (0, 1) for y in (0, 1) for z in (0, 1)]
    # Faces wound counter-clockwise seen from outside (right-handed convention).
    quads = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    tris = []
    for a, b, c, d in quads:
        tris += [a, b, c, a, c, d]
    centre = [0.5, 0.5, 0.5]
    normals = [[p[i] - centre[i] for i in range(3)] for p in v]
    return v, tris, normals


def test_winding_sign_detects_inside_out_meshes():
    v, tris, normals = _cube()
    sign = calib.winding_sign(v, tris, normals)
    assert sign in (1, -1)
    flipped = [tris[i + k] for i in range(0, len(tris), 3) for k in (0, 2, 1)]
    assert calib.winding_sign(v, flipped, normals) == -sign
    mixed = flipped[:6] + tris[6:]
    assert calib.winding_sign(v, mixed, normals) == 0


def test_calibration_checks_catch_wrong_units_mirror_and_chamfer():
    spec = calib.load_spec(VECTORS)
    axes = spec["SM_Calib_Axes"]
    tol = spec["tolerance_cm"]
    assert calib.check_bounds([-10, -50, 0], [100, 10, 80], axes["bounds_cm"], tol) == []
    assert calib.check_bounds([-0.1, -0.5, 0], [1, 0.1, 0.8], axes["bounds_cm"], tol)  # metres
    assert calib.check_bounds([-10, -10, 0], [100, 50, 80], axes["bounds_cm"], tol)  # no mirror
    good_tip = [[100.0, 0.0, 5.0], [100.0, 0.0, 10.0], [95.0, 0.0, 15.0]]
    assert calib.check_x_tip(good_tip, axes["x_tip"], tol) == []
    assert calib.check_x_tip([[100.0, 0.0, 15.0]], axes["x_tip"], tol)  # flipped upside down


def test_calibration_bone_check():
    spec = calib.load_spec(VECTORS)["SK_Calib_Rig"]
    pose = {
        "names": [b["name"] for b in spec["bones"]],
        "locations": {b["name"]: b["component_location_cm"] for b in spec["bones"]},
        "root_scale": [1.0, 1.0, 1.0],
    }
    assert calib.check_bones(pose, "Root", spec, 0.05) == []
    pose["root_rotation"] = [0.0, 0.0, 0.0, -1.0]  # -q is the same rotation
    assert calib.check_bones(pose, "Root", spec, 0.05) == []
    pose["root_rotation"] = [0.7071068, 0.0, 0.0, -0.7071068]  # Y-up bone axis leaked in
    pose["locations"]["Calib_SideEnd"] = [0.0, 25.0, 50.0]  # not mirrored
    pose["root_scale"] = [100.0, 100.0, 100.0]
    pose["names"] = ["Armature", *pose["names"]]
    assert len(calib.check_bones(pose, "Root", spec, 0.05)) == 5


# --- Export entry (host side) -------------------------------------------------


export_unreal = _load("export_unreal", REPO_ROOT / "scripts" / "verse" / "export_unreal.py")


def _exported(**overrides) -> dict:
    asset = {
        "name": "SM_Crate_60",
        "file": "art/verse/.cache/unreal/kit/SM_Crate_60.fbx",
        "sha256": "d" * 64,
        "triangles": 120,
        "vertices": 96,
        "bounds_cm": {"min": [-30.0, -20.0, 0.0], "max": [30.0, 20.0, 25.0]},
        "uv_sets": 1,
        "material_slots": [
            {"slot": "M_Crate_Paint", "mi": unreal_materials.instance_path("M_Crate_Paint")}
        ],
        "collision_primitives": 0,
        "sockets": [],
        "bones": [],
        "settings_id": "fbx-ue/1",
        "blender": "5.0.1",
        "source": {
            "builder": "art/verse/kit/props/fitout.py",
            "function": "crate",
            "module": "kit.props.fitout",
            "args": {"w": 0.6},
        },
    }
    asset.update(overrides)
    return asset


def test_export_records_follow_the_kit_rules(tmp_path):
    record = export_unreal.build_record(_exported(), None)
    assert record["asset_path"] == "/Game/Verse/Kit/Props/SM_Crate_60.SM_Crate_60"
    assert record["collision"]["profile"] == "Verse_Prop"
    assert record["nanite"] == {"enabled": False} and record["lod"] == {"mode": "single"}
    big = export_unreal.build_record(_exported(triangles=5000), None)
    assert big["nanite"]["enabled"] is True
    tiny = _exported(bounds_cm={"min": [-5.0, -5.0, 0.0], "max": [5.0, 5.0, 10.0]})
    assert export_unreal.build_record(tiny, None)["collision"]["profile"] == "Verse_PropSmall"
    tuned = dict(record, nanite={"enabled": True, "fallback_relative_error": 0.2})
    kept = export_unreal.build_record(_exported(), tuned)["nanite"]
    assert kept["fallback_relative_error"] == 0.2
    # The record passes the static check's schema and rules.
    root = _scratch_root(tmp_path)
    folder = root / "unreal/Verse/Content/Verse/Kit/Props"
    _write(folder / "SM_Crate_60.uasset", "pointer")
    _write(root / "unreal/Verse/Art/Import/Kit/Props/SM_Crate_60.import.json", record)
    assert _errors(root) == []


def test_reserved_export_modes_exit_2(capsys):
    assert export_unreal.main(["weapons"]) == 2
    assert "WP14" in capsys.readouterr().err
