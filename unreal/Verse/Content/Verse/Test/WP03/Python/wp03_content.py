"""Create and verify the WP03 content (editor Python, ``pythonscript`` commandlet).

Run headless under the machine lock, from the worktree root::

    python scripts/unreal/with_lock.py --label wp03-content -- \
        "C:/Program Files/Epic Games/UE_5.7/Engine/Binaries/Win64/UnrealEditor-Cmd.exe" \
        unreal/Verse/Verse.uproject -run=pythonscript \
        -script=unreal/Verse/Content/Verse/Test/WP03/Python/wp03_content.py \
        -nullrhi -unattended -nosplash -NoSound -abslog=unreal/Verse/Saved/wp03_content.log

What it makes (all own work, no engine sample content):

* ``/Game/Verse/Destruction/_Holes/DA_PenetrationTable``: the rows of
  ``Data/destruction/penetration.json`` through the WP03.2 importer (frozen
  wire order check). Re-run after every retune of the JSON; the game loads
  the asset, so a retune reaches cooked and dedicated-server builds.
* The three WP03.7 world-surface physical materials (``PM_Verse_HallFloor``,
  ``PM_Verse_StructuralWall``, ``PM_Verse_StructuralBeam``) are made only with
  ``VERSE_WP03_PHYSMATS=1``: art-pipeline section 3 has no physical material
  prefix yet (request #1161), so they cannot be committed until it does.
* ``/Game/Verse/Destruction/_Holes/M_HoleRim_Decal``: the rim decal of
  WP03.6 (deferred decal, translucent), scalar ``RimGlow``, vector
  ``RimGlowColor``, a charred base.
* Placeholder geometry is the engine's built-in ``/Engine/BasicShapes/Cube``
  (100 cm, box collision; engine primitives, not a sample content pack). An
  own ``SM_`` mesh would need an art-pipeline import record (art-pipeline 9).
* ``/Game/Verse/Test/WP03/M_WP03_HoleSurface``: a test surface master with
  the ``HoleMask`` texture parameter (masked, two-sided, emissive ``Tint``),
  standing in for the WP14.1 masters in WP03 tests and the fixture map.
* ``/Game/Verse/Test/WP03/LV_WP03_Penetration``: the WP03.8 fixture map.

Idempotent: an asset that already matches is not saved again, so a rerun does
not churn LFS objects. Every result line starts with ``VERSE_WP03``; the last
one is ``VERSE_WP03 OK`` or ``VERSE_WP03 FAIL``.
"""

from __future__ import annotations

import json
import os
import traceback

import unreal

HOLES = "/Game/Verse/Destruction/_Holes"
PHYS = HOLES + "/PhysicalMaterials"
TEST = "/Game/Verse/Test/WP03"
BOX = "/Engine/BasicShapes/Cube"
MAP = TEST + "/LV_WP03_Penetration"
SURFACES = ("HallFloor", "StructuralWall", "StructuralBeam")
FACTORS = (0.5, 1.0, 3.0)
CHARRED = (0.018, 0.014, 0.011)

ASSETS = unreal.AssetToolsHelpers.get_asset_tools()
EAL = unreal.EditorAssetLibrary
MEL = unreal.MaterialEditingLibrary


def log(text: str) -> None:
    unreal.log("VERSE_WP03 " + text)


def project_dir() -> str:
    return unreal.Paths.convert_relative_path_to_full(unreal.Paths.project_dir())


def table_rows() -> list[dict]:
    path = os.path.join(project_dir(), "Data", "destruction", "penetration.json")
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)["materials"]


def existing(path: str):
    return EAL.load_asset(path) if EAL.does_asset_exist(path) else None


def save(asset) -> None:
    if not EAL.save_loaded_asset(asset, only_if_is_dirty=False):
        raise RuntimeError(f"could not save {asset.get_path_name()}")
    log(f"saved {asset.get_path_name()}")


def make_table() -> None:
    path = HOLES + "/DA_PenetrationTable"
    table = existing(path)
    library = unreal.VersePenetrationTableLibrary
    if table is not None and not library.diff_penetration_json(table, ""):
        log("DA_PenetrationTable matches penetration.json")
        return
    if table is None:
        factory = unreal.DataAssetFactory()
        factory.set_editor_property("data_asset_class", unreal.VersePenetrationTable)
        table = ASSETS.create_asset(
            "DA_PenetrationTable", HOLES, unreal.VersePenetrationTable, factory
        )
    # A bool UFUNCTION with an out parameter returns the out value on success and None on failure.
    if library.import_penetration_json(table, "") is None:
        raise RuntimeError(
            "penetration.json rejected; Verse.Destruction.Penetration.Import says why"
        )
    save(table)


def make_physical_materials() -> None:
    for surface in SURFACES:
        name = f"PM_Verse_{surface}"
        if existing(f"{PHYS}/{name}") is not None:
            continue
        asset = ASSETS.create_asset(
            name, PHYS, unreal.PhysicalMaterial, unreal.PhysicalMaterialFactoryNew()
        )
        save(asset)


def expression(material, cls, x: int, y: int):
    return MEL.create_material_expression(material, cls, x, y)


def connect(a, b, b_input: str, a_output: str = "") -> None:
    if not MEL.connect_material_expressions(a, a_output, b, b_input):
        raise RuntimeError(f"cannot connect {a.get_name()} to {b.get_name()}.{b_input}")


def to_property(node, prop, output: str = "") -> None:
    if not MEL.connect_material_property(node, output, prop):
        raise RuntimeError(f"cannot connect {node.get_name()} to {prop}")


def make_rim_decal() -> None:
    path = HOLES + "/M_HoleRim_Decal"
    if existing(path) is not None:
        return
    material = ASSETS.create_asset(
        "M_HoleRim_Decal", HOLES, unreal.Material, unreal.MaterialFactoryNew()
    )
    material.set_editor_property("material_domain", unreal.MaterialDomain.MD_DEFERRED_DECAL)
    material.set_editor_property("blend_mode", unreal.BlendMode.BLEND_TRANSLUCENT)

    glow = expression(material, unreal.MaterialExpressionScalarParameter, -900, -200)
    glow.set_editor_property("parameter_name", "RimGlow")
    glow.set_editor_property("default_value", 0.0)
    color = expression(material, unreal.MaterialExpressionVectorParameter, -900, -50)
    color.set_editor_property("parameter_name", "RimGlowColor")
    color.set_editor_property("default_value", unreal.LinearColor(*CHARRED, 1.0))

    # Ring mask over the decal footprint: 1 at the opening, fading out to the footprint edge.
    uv = expression(material, unreal.MaterialExpressionTextureCoordinate, -1200, 200)
    centre = expression(material, unreal.MaterialExpressionConstant2Vector, -1200, 320)
    centre.set_editor_property("r", 0.5)
    centre.set_editor_property("g", 0.5)
    dist = expression(material, unreal.MaterialExpressionDistance, -1000, 250)
    connect(uv, dist, "A")
    connect(centre, dist, "B")
    edge = expression(material, unreal.MaterialExpressionConstant, -1000, 400)
    edge.set_editor_property("r", 0.5)
    inside = expression(material, unreal.MaterialExpressionSubtract, -820, 300)
    connect(edge, inside, "A")
    connect(dist, inside, "B")
    gain = expression(material, unreal.MaterialExpressionConstant, -820, 450)
    gain.set_editor_property("r", 4.0)
    scaled = expression(material, unreal.MaterialExpressionMultiply, -660, 320)
    connect(inside, scaled, "A")
    connect(gain, scaled, "B")
    ring = expression(material, unreal.MaterialExpressionSaturate, -500, 320)
    connect(scaled, ring, "")

    hot = expression(material, unreal.MaterialExpressionMultiply, -600, -120)
    connect(color, hot, "A")
    connect(glow, hot, "B")
    emissive = expression(material, unreal.MaterialExpressionMultiply, -380, -60)
    connect(hot, emissive, "A")
    connect(ring, emissive, "B")
    base = expression(material, unreal.MaterialExpressionConstant3Vector, -380, 120)
    base.set_editor_property("constant", unreal.LinearColor(*CHARRED, 1.0))

    to_property(emissive, unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    to_property(base, unreal.MaterialProperty.MP_BASE_COLOR)
    to_property(ring, unreal.MaterialProperty.MP_OPACITY)
    MEL.recompile_material(material)
    save(material)


def make_surface() -> None:
    path = TEST + "/M_WP03_HoleSurface"
    if existing(path) is not None:
        return
    material = ASSETS.create_asset(
        "M_WP03_HoleSurface", TEST, unreal.Material, unreal.MaterialFactoryNew()
    )
    material.set_editor_property("blend_mode", unreal.BlendMode.BLEND_MASKED)
    material.set_editor_property("two_sided", True)
    tint = expression(material, unreal.MaterialExpressionVectorParameter, -600, 0)
    tint.set_editor_property("parameter_name", "Tint")
    tint.set_editor_property("default_value", unreal.LinearColor(0.3, 0.3, 0.3, 1.0))
    black = expression(material, unreal.MaterialExpressionConstant3Vector, -600, -150)
    black.set_editor_property("constant", unreal.LinearColor(0.0, 0.0, 0.0, 1.0))
    mask = expression(material, unreal.MaterialExpressionTextureSampleParameter2D, -600, 200)
    mask.set_editor_property("parameter_name", "HoleMask")
    mask.set_editor_property(
        "texture", unreal.load_asset("/Engine/EngineResources/WhiteSquareTexture")
    )
    to_property(black, unreal.MaterialProperty.MP_BASE_COLOR)
    to_property(tint, unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    to_property(mask, unreal.MaterialProperty.MP_OPACITY_MASK, "R")
    MEL.recompile_material(material)
    save(material)


def spawn_piece(
    box,
    material_id: str,
    wire: int,
    thickness_cm: float,
    location,
    rotation=None,
    label: str = "",
    role: str = "grid",
):
    # The editor actor subsystem places through the level viewport, which a commandlet lacks;
    # the WP03 library spawns straight into the editor world.
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    transform = unreal.Transform(
        location, rotation or unreal.Rotator(0, 0, 0), unreal.Vector(thickness_cm / 100.0, 1.0, 1.0)
    )
    profile = "Verse_Glass" if material_id == "glass" else "Verse_Destructible"
    tags = [
        f"verse.wp03.material:{material_id}",
        f"verse.wp03.wire:{wire}",
        f"verse.wp03.thickness_cm:{thickness_cm:g}",
        "verse.wp03.role:" + role,
    ]
    surface = unreal.load_asset(TEST + "/M_WP03_HoleSurface")
    actor = unreal.VersePenetrationTableLibrary.spawn_fixture_piece(
        world,
        box,
        surface,
        transform,
        profile,
        tags,
        label or f"WP03_{material_id}_{thickness_cm:g}cm",
    )
    if actor is None:
        raise RuntimeError(f"could not spawn {material_id} {thickness_cm:g} cm")
    return actor


def make_map() -> None:
    if EAL.does_asset_exist(MAP):
        return
    levels = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if not levels.new_level(MAP, False):
        raise RuntimeError(f"could not create {MAP}")
    box = unreal.load_asset(BOX)
    rows = table_rows()
    # Grid: one row per material (X), one column per thickness factor (Y), 1.5 m apart.
    for row in rows:
        for column, factor in enumerate(FACTORS):
            thickness = row["ref_thickness_cm"] * factor
            location = unreal.Vector(300.0 + 150.0 * row["wire"], 150.0 * column, 100.0)
            spawn_piece(box, row["id"], row["wire"], thickness, location)
    # Hole angle rig (A3.3): a 0.3 cm sheet and a 4 cm panel, each at 30 deg to the ray.
    sheet = next(r for r in rows if r["id"] == "sheet_metal")
    panel = next(r for r in rows if r["id"] == "cladding_panel")
    rig = unreal.Rotator(0.0, 0.0, 30.0)
    spawn_piece(
        box,
        sheet["id"],
        sheet["wire"],
        0.3,
        unreal.Vector(300.0, 600.0, 100.0),
        rig,
        "WP03_HoleRig_Sheet",
        "hole_rig",
    )
    spawn_piece(
        box,
        panel["id"],
        panel["wire"],
        4.0,
        unreal.Vector(300.0, 750.0, 100.0),
        rig,
        "WP03_HoleRig_Panel",
        "hole_rig",
    )
    # A container row: three walls one metre apart (rifle through two walls keeps 0.5625).
    wall = next(r for r in rows if r["id"] == "container_wall")
    for index in range(3):
        spawn_piece(
            box,
            wall["id"],
            wall["wire"],
            wall["ref_thickness_cm"],
            unreal.Vector(300.0 + 100.0 * index, 900.0, 100.0),
            None,
            f"WP03_ContainerRow_{index}",
            "container_row",
        )
    if not levels.save_current_level():
        raise RuntimeError(f"could not save {MAP}")
    log(f"saved {MAP}")


def verify() -> list[str]:
    problems = []
    table = existing(HOLES + "/DA_PenetrationTable")
    if table is None:
        problems.append("DA_PenetrationTable missing")
    elif unreal.VersePenetrationTableLibrary.diff_penetration_json(table, ""):
        problems.append("DA_PenetrationTable differs from penetration.json")
    for path in (
        HOLES + "/M_HoleRim_Decal",
        TEST + "/M_WP03_HoleSurface",
        MAP,
    ):
        if not EAL.does_asset_exist(path):
            problems.append(f"{path} missing")
    return problems


def main() -> None:
    try:
        make_table()
        if os.environ.get("VERSE_WP03_PHYSMATS") == "1":
            make_physical_materials()
        make_rim_decal()
        make_surface()
        make_map()
        problems = verify()
        for problem in problems:
            log("problem: " + problem)
        log("FAIL" if problems else "OK")
    except Exception:  # noqa: BLE001 - every failure must reach the log marker
        for line in traceback.format_exc().splitlines():
            log(line)
        log("FAIL")


main()
