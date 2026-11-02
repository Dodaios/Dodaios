"""WP14 weapon art, materials and look: the pure parts (no Blender, no editor)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "art" / "verse"))
sys.path.insert(0, str(REPO / "unreal" / "Verse" / "Content" / "Python"))
sys.path.insert(0, str(REPO / "scripts" / "unreal"))

from verse_pipeline import masters, materials, validate_assets, weapons  # noqa: E402
from weapons import specs  # noqa: E402
from weapons.look import agx, palette  # noqa: E402

RECORDS = REPO / "unreal" / "Verse" / "Art" / "Import"
RECIPES = REPO / "unreal" / "Verse" / "Art" / "Materials" / "Weapons"
STYLE = REPO / "art" / "verse" / "style-unreal.md"


def _record(spec: specs.WeaponSpec) -> dict:
    folder = spec.folder.removeprefix("/Game/Verse/")
    return json.loads((RECORDS / folder / f"{spec.asset}.import.json").read_text("utf-8"))


# -- A14.1 budgets and skeletons --------------------------------------------


@pytest.mark.parametrize("spec", specs.ARSENAL, ids=lambda s: s.asset)
def test_record_within_budget(spec):
    record = _record(spec)
    assert record["owner"] == "WP14"
    assert record["asset_path"] == spec.object_path
    assert record["mesh"]["triangles"] <= spec.triangle_cap
    assert record["license"] == {"kind": "own"}
    if spec.kind == "skeletal":
        assert record["kind"] == "skeletal_mesh"
        bones = record["mesh"]["bones"]
        assert len(bones) <= specs.MAX_WEAPON_BONES
        assert bones[0] == "Root"
        assert set(specs.required_bones(spec)) <= set(bones)
        assert set(specs.required_sockets(spec)) <= set(record["mesh"]["sockets"])
        assert record["mesh"]["triangles"] <= specs.MAX_FIRST_PERSON_TRIANGLES
        assert record["nanite"]["enabled"] is False


@pytest.mark.parametrize(
    "spec", [s for s in specs.ARSENAL if s.kind == "skeletal"], ids=lambda s: s.asset
)
def test_skeleton_record_beside_mesh(spec):
    folder = spec.folder.removeprefix("/Game/Verse/")
    skel = json.loads((RECORDS / folder / f"{spec.skeleton}.import.json").read_text("utf-8"))
    assert skel["kind"] == "skeleton"
    assert skel["asset_path"] == spec.skeleton_path
    assert skel["export"] == _record(spec)["export"]


def test_every_firearm_has_the_contract_sockets():
    for spec in (specs.GRAVELINE, specs.TALLOW, specs.SKITTER, specs.LONGSIGHT):
        assert spec.socket_names() == specs.FIREARM_SOCKETS
    assert specs.HOOKBILL.socket_names() == ("SOCKET_Tip",)
    assert "Slide" in specs.required_bones(specs.TALLOW)


def test_sockets_lie_inside_the_mesh_bounds():
    for spec in specs.ARSENAL:
        if spec.kind != "skeletal":
            continue
        box = _record(spec)["mesh"]["bounds_cm"]
        for socket in spec.sockets:
            loc = specs.socket_to_ue_cm(socket.location)
            for axis in range(3):
                assert box["min"][axis] - 2.0 <= loc[axis] <= box["max"][axis] + 2.0, (
                    spec.asset,
                    socket.name,
                )


def test_muzzle_is_the_most_forward_socket():
    for spec in (specs.GRAVELINE, specs.TALLOW, specs.SKITTER, specs.LONGSIGHT):
        xs = {s.name: s.location[0] for s in spec.sockets}
        assert xs["SOCKET_Muzzle"] == max(xs.values())


def test_editor_check_catches_missing_socket_and_bone_cap():
    spec = specs.GRAVELINE
    record = _record(spec)
    good = {
        "exists": True,
        "skeleton": spec.skeleton_path,
        "bones": ["Root", "Magazine", "Bolt", "Trigger"],
        "sockets": list(specs.FIREARM_SOCKETS),
        "slots": ["M_Weapon_Steel"],
        "materials": ["/Game/Verse/Materials/Instances/Weapons/MI_Weapon_Steel.MI_Weapon_Steel"],
    }
    assert weapons.check(record, good) == []
    bad = dict(good, sockets=["SOCKET_Muzzle"], bones=["Root"] + [f"B{i}" for i in range(30)])
    errors = weapons.check(record, bad)
    assert any("cap 24" in e for e in errors)
    assert any("SOCKET_Eject" in e for e in errors)
    assert any("Magazine" in e for e in errors)


# -- A14.2 black only --------------------------------------------------------


def _recipes() -> list[dict]:
    return [json.loads(p.read_text("utf-8")) for p in sorted(RECIPES.glob("*.mi.json"))]


def test_every_slot_of_every_weapon_has_a_recipe():
    names = {r["name"] for r in _recipes()}
    for spec in specs.ARSENAL:
        for slot in _record(spec)["mesh"]["material_slots"]:
            assert slot["mi"].rsplit(".", 1)[1] in names, (spec.asset, slot)
    for vfx in specs.VFX:
        folder = vfx.object_path.rsplit("/", 1)[0].removeprefix("/Game/Verse/")
        rec = json.loads((RECORDS / folder / f"{vfx.asset}.import.json").read_text("utf-8"))
        for slot in rec["mesh"]["material_slots"]:
            assert slot["mi"].rsplit(".", 1)[1] in names
    for mi, _master, _use in specs.VFX_MATERIALS:
        assert mi in names


@pytest.mark.parametrize("recipe", _recipes(), ids=lambda r: r["name"])
def test_weapon_material_base_colour_is_black(recipe):
    assert recipe["owner"] == "WP14"
    assert materials.instance_path(recipe).startswith("/Game/Verse/Materials/Instances/Weapons/")
    assert (
        validate_assets.weapon_colour_errors(recipe["name"], recipe["parent"], recipe["vectors"])
        == []
    )
    for key, rgb in validate_assets.weapon_base_colours(
        recipe["parent"], recipe["vectors"]
    ).items():
        assert validate_assets.luminance(rgb) <= 0.06, key


@pytest.mark.parametrize("recipe", _recipes(), ids=lambda r: r["name"])
def test_recipe_parameters_exist_on_the_master(recipe):
    table = masters.parameter_table()
    master = recipe["parent"].rsplit(".", 1)[1]
    names = {row["name"] for row in table if row["master"] == master}
    for group in ("scalars", "vectors", "textures", "switches"):
        assert set(recipe[group]) <= names, (recipe["name"], group)


def test_weapon_master_clamps_any_tint_to_black():
    lighter = {"BaseTint": (0.5, 0.5, 0.5, 1.0), "EdgeTint": (0.9, 0.9, 0.9, 1.0)}
    colours = validate_assets.weapon_base_colours(
        "/Game/Verse/Materials/Master/M_Verse_Weapon.M_Verse_Weapon", lighter
    )
    assert validate_assets.luminance(colours["BaseTint"]) <= 0.0105
    assert validate_assets.luminance(colours["EdgeTint"]) <= 0.06
    assert "1A1A1B" not in masters.WEAPON_COLOUR  # caps are baked as numbers
    assert str(masters.WEAPON_BASE_CAP[0]) in masters.WEAPON_COLOUR


def test_gold_or_coloured_trim_fails():
    gold = (0.578, 0.366, 0.0685, 1.0)
    errors = validate_assets.weapon_colour_errors(
        "MI_X", "/Game/Verse/Materials/Master/M_Verse_Glass.M_Verse_Glass", {"BaseTint": gold}
    )
    assert errors


def test_recipes_pass_the_palette_bans():
    import check_art_text

    for recipe in _recipes():
        for param, value in recipe["vectors"].items():
            assert check_art_text.colour_bans(param, value, gold_allowed=False) == [], recipe[
                "name"
            ]


def test_bolts_are_amber_own_and_red_foe():
    by = {r["name"]: r for r in _recipes()}
    own = by["MI_Weapon_Vfx_BoltOwn"]["vectors"]["EmissiveColor"]
    foe = by["MI_Weapon_Vfx_BoltFoe"]["vectors"]["EmissiveColor"]
    assert [round(agx.linear_to_srgb(c) * 255) for c in own[:3]] == [0xF2, 0xA3, 0x3A]
    assert [round(agx.linear_to_srgb(c) * 255) for c in foe[:3]] == [0xE3, 0x24, 0x2B]


# -- Masters -----------------------------------------------------------------


def test_masters_are_the_contract_set():
    names = [m.name for m in masters.MASTERS]
    assert names == [
        "M_Verse_Surface",
        "M_Verse_Floor",
        "M_Verse_Emissive",
        "M_Verse_Glass",
        "M_Verse_Screen",
        "M_Verse_Character",
        "M_Verse_Weapon",
        "M_Verse_Decal",
    ]
    surface = {p.name for p in masters.MASTERS[0].params}
    assert {"UseTriplanar", "BaseTint", "RoughnessMin", "RoughnessMax", "Metallic"} <= surface
    for master in masters.MASTERS[:2]:
        assert {"UseHoleMask", "HoleMask", "HoleMaskUV"} <= {p.name for p in master.params}


def test_every_master_parameter_is_documented_in_the_style_sheet():
    text = STYLE.read_text("utf-8")
    for row in masters.parameter_table():
        assert f"`{row['name']}`" in text, row


def test_post_shader_uses_the_lattice_of_the_lut():
    code = masters.post_code(agx.EV_MIN, agx.EV_MAX)
    assert repr(agx.EV_MIN) in code
    assert repr(agx.EV_MAX - agx.EV_MIN) in code


# -- A14.3 / A14.4 helpers ---------------------------------------------------


def test_rendered_pixel_rule():
    assert palette.is_banned(0, 200, 220)  # cyan
    assert palette.is_banned(150, 40, 200)  # violet
    assert not palette.is_banned(242, 163, 58)  # amber
    assert not palette.is_banned(227, 36, 43)  # signal red
    assert not palette.is_banned(8, 9, 12)  # dark, below value 0.08
    assert palette.is_banned(20, 22, 30)  # a lifted blue-grey is already banned
    assert not palette.is_banned(110, 115, 125)  # grey, low saturation


def test_banned_image_counter_matches_pixel_rule(tmp_path):
    pil = pytest.importorskip("PIL.Image")
    img = pil.new("RGB", (4, 1))
    pixels = [(0, 200, 220), (242, 163, 58), (150, 40, 200), (8, 9, 12)]
    for i, p in enumerate(pixels):
        img.putpixel((i, 0), p)
    path = tmp_path / "frame.png"
    img.save(path)
    assert palette.count_banned_image(path) == (2, 4)
    assert palette.count_banned(pixels) == 2


def test_lut_lattice_round_trip():
    for i in range(agx.SIZE):
        assert agx.encode(agx.lattice_value(i)) == pytest.approx(i / (agx.SIZE - 1))
    assert agx.strip_texel(33, 5) == (1, 5, 1)


def test_identity_strip_samples_back_its_input():
    strip = [[None] * agx.STRIP_WIDTH for _ in range(agx.STRIP_HEIGHT)]
    for y in range(agx.STRIP_HEIGHT):
        for x in range(agx.STRIP_WIDTH):
            r, g, b = agx.strip_texel(x, y)
            strip[y][x] = (r / (agx.SIZE - 1), g / (agx.SIZE - 1), b / (agx.SIZE - 1))
    for rgb in ((0.18, 0.18, 0.18), (0.9, 0.05, 0.3), (2.0, 0.5, 0.01)):
        got = agx.sample(strip, rgb)
        assert got == pytest.approx(tuple(agx.encode(c) for c in rgb), abs=1e-9)


def test_ciede2000_reference_pairs():
    # Published test pairs of the CIEDE2000 formula (Sharma et al. 2005).
    assert agx.ciede2000((50.0, 2.6772, -79.7751), (50.0, 0.0, -82.7485)) == pytest.approx(
        2.0425, abs=1e-4
    )
    assert agx.ciede2000((50.0, 2.5, 0.0), (73.0, 25.0, -18.0)) == pytest.approx(27.1492, abs=1e-4)
    assert agx.delta_e((0.5, 0.5, 0.5), (0.5, 0.5, 0.5)) == 0.0


def test_chart_has_24_patches_and_six_greys():
    assert len(agx.CHART_SRGB8) == 24
    for r, g, b in agx.CHART_SRGB8[18:]:
        assert max(r, g, b) - min(r, g, b) <= 1


def test_lut_record():
    record = json.loads(
        (RECORDS / "PostProcess" / "T_Verse_Grade_LUT_M.import.json").read_text("utf-8")
    )
    assert record["kind"] == "texture"
    assert record["texture"]["srgb"] is False
    assert record["texture"]["channels"]["lut"] == str(agx.SIZE)
    assert record["asset_path"].startswith("/Game/Verse/PostProcess/")


# -- A14.6 names and design sheet ---------------------------------------------


def test_names_are_the_fictional_ones():
    assert [s.display_name for s in specs.ARSENAL] == [
        "Graveline",
        "Tallow",
        "Hookbill",
        "Bulwark",
        "Bulwark",
        "BreachCharge",
        "Skitter",
        "Longsight",
    ]


def test_design_sheet_lists_every_weapon_and_the_checklist():
    text = STYLE.read_text("utf-8")
    for spec in specs.ARSENAL:
        assert spec.display_name in text.replace(" ", "")
    assert "No-copy checklist" in text


# -- A14.5 bolt cost --------------------------------------------------------


class _FakeUnreal:
    """Just enough of `unreal` for `measure_bolt_cost` (no editor)."""

    class RenderingLibrary:
        @staticmethod
        def read_render_target_pixel(*_args):
            return None


class _FakeScene:
    def __init__(self):
        self.world = None
        self.visible: dict[str, bool] = {}

    def show(self, group: str, visible: bool) -> None:
        self.visible[group] = visible


class _FakeCapture:
    rt = None

    def __init__(self, scene: _FakeScene, clock: list[float]):
        scene_ref, clock_ref = scene, clock

        class Comp:
            def capture_scene(self_inner):
                cost = 5.0
                cost += 0.02 if scene_ref.visible.get("cost_64") else 0.0
                cost += 0.30 if scene_ref.visible.get("cost_960") else 0.0
                clock_ref[0] += cost / 1000.0

        self.comp = Comp()


def test_bolt_cost_measures_the_difference_of_medians(monkeypatch):
    from verse_pipeline import lookdev

    clock = [0.0]
    monkeypatch.setattr(lookdev.time, "perf_counter", lambda: clock[0])
    scene = _FakeScene()
    result = lookdev.measure_bolt_cost(_FakeUnreal, scene, _FakeCapture(scene, clock), {})
    assert result["resolution"] == [2560, 1440]
    assert result["delta_64_ms"] == pytest.approx(0.02, abs=1e-6)
    assert result["delta_1024_ms"] == pytest.approx(0.32, abs=1e-6)
    assert result["per_64_from_1024_ms"] == pytest.approx(0.02, abs=1e-6)
    assert result["bound_ms"] == pytest.approx(0.02, abs=1e-6)
    assert scene.visible == {"cost_64": False, "cost_960": False}


def test_bolt_cost_verdict_uses_the_bound():
    sys.path.insert(0, str(REPO / "art" / "verse" / "weapons" / "look"))
    import evaluate

    base = {
        "median_ms": {},
        "delta_64_ms": 0.01,
        "per_64_from_1024_ms": 0.04,
        "method": "x",
    }
    assert evaluate.vfx_cost({"vfx_cost": {**base, "bound_ms": 0.04}})["pass"]
    assert not evaluate.vfx_cost({"vfx_cost": {**base, "bound_ms": 0.2}})["pass"]
    assert not evaluate.vfx_cost({})["pass"]
