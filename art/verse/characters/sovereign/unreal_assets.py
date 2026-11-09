"""Editor step of the Sovereign asset build (stream S7): materials of the commander's powers.

Runs inside the headless Unreal editor (``-ExecutePythonScript``), started by
``art/verse/characters/sovereign/build.py`` under the machine lock. Inputs come
from the environment:

    VERSE_SOV_RESULT   JSON report path
    VERSE_SOV_QUIT     "1": quit the editor when done
    VERSE_SOV_ONLY     comma-separated asset names to rebuild; empty = all

Creates or replaces, under ``/Game/Verse/Characters/Sovereign``:

    M_Sov_ArcBolt   Arc Storm bolt: unlit, additive, for instanced cylinders. ``Color`` and
                    ``Intensity`` come from code (VerseArc::CoreColor / GlowColor), so the
                    palette lives in one place; the cylinder's rim fades out (1 - fresnel),
                    which reads as a soft glow around a hot core. The hoverboard's thrusters
                    use it too (amber).
    M_Sov_Board     the hoverboard's lit parts: ``Color``, ``Metallic``, ``Roughness`` and an
                    ``Emissive`` share of the colour, all set from code (deck, rim, grip).

Own work, built from text; nothing third-party.
"""

from __future__ import annotations

import json
import os
import traceback

import unreal

FOLDER = "/Game/Verse/Characters/Sovereign"
ASSETS = unreal.AssetToolsHelpers.get_asset_tools()
MEL = unreal.MaterialEditingLibrary
LIB = unreal.EditorAssetLibrary
REPORT: dict = {"ok": True, "assets": [], "warnings": []}


def warn(text: str) -> None:
    REPORT["warnings"].append(text)
    unreal.log_warning(f"[verse_sovereign] {text}")


def fresh(name: str, cls, factory):
    path = f"{FOLDER}/{name}"
    if LIB.does_asset_exist(path):
        LIB.delete_asset(path)
    asset = ASSETS.create_asset(name, FOLDER, cls, factory)
    REPORT["assets"].append(path)
    return asset


def set_prop(obj, name: str, value) -> None:
    try:
        obj.set_editor_property(name, value)
    except Exception as error:  # property names move between engine versions
        warn(f"{obj.get_name()}.{name}: {error}")


def node(material, cls, x: int, y: int, **props):
    expression = MEL.create_material_expression(material, cls, x, y)
    for key, value in props.items():
        set_prop(expression, key, value)
    return expression


def link(a, a_out: str, b, b_in: str) -> None:
    if not MEL.connect_material_expressions(a, a_out, b, b_in):
        warn(f"link {a.get_name()}.{a_out} -> {b.get_name()}.{b_in} failed")


def build_arc_bolt():
    material = fresh("M_Sov_ArcBolt", unreal.Material, unreal.MaterialFactoryNew())
    set_prop(material, "used_with_instanced_static_meshes", True)
    set_prop(material, "blend_mode", unreal.BlendMode.BLEND_ADDITIVE)
    set_prop(material, "shading_model", unreal.MaterialShadingModel.MSM_UNLIT)
    set_prop(material, "two_sided", True)
    color = node(material, unreal.MaterialExpressionVectorParameter, -900, 0,
                 parameter_name="Color", default_value=unreal.LinearColor(0.86, 0.92, 1.0, 1.0))
    intensity = node(material, unreal.MaterialExpressionScalarParameter, -900, 220,
                     parameter_name="Intensity", default_value=10.0)
    fresnel = node(material, unreal.MaterialExpressionFresnel, -900, 400, exponent=1.5)
    core = node(material, unreal.MaterialExpressionOneMinus, -700, 400)
    link(fresnel, "", core, "")
    soft = node(material, unreal.MaterialExpressionMultiply, -550, 400)
    link(core, "", soft, "A")
    link(core, "", soft, "B")
    # The cylinder's end caps face the camera along the bolt and would light up as discs at
    # every joint: in instance space the caps face +-Z, so 1 - |n.z| hides them, keeps the sides.
    normal = node(material, unreal.MaterialExpressionVertexNormalWS, -1300, 600)
    world = unreal.MaterialVectorCoordTransformSource.TRANSFORMSOURCE_WORLD
    local = node(material, unreal.MaterialExpressionTransform, -1100, 600,
                 transform_source_type=world,
                 transform_type=unreal.MaterialVectorCoordTransform.TRANSFORM_INSTANCE)
    link(normal, "", local, "")
    axis = node(material, unreal.MaterialExpressionComponentMask, -900, 600,
                r=False, g=False, b=True, a=False)
    link(local, "", axis, "")
    along = node(material, unreal.MaterialExpressionAbs, -750, 600)
    link(axis, "", along, "")
    side = node(material, unreal.MaterialExpressionOneMinus, -600, 600)
    link(along, "", side, "")
    capless = node(material, unreal.MaterialExpressionMultiply, -450, 500)
    link(soft, "", capless, "A")
    link(side, "", capless, "B")
    soft = capless
    lit = node(material, unreal.MaterialExpressionMultiply, -500, 80)
    link(color, "", lit, "A")
    link(intensity, "", lit, "B")
    out = node(material, unreal.MaterialExpressionMultiply, -300, 200)
    link(lit, "", out, "A")
    link(soft, "", out, "B")
    MEL.connect_material_property(out, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    MEL.recompile_material(material)
    return material


def build_board():
    material = fresh("M_Sov_Board", unreal.Material, unreal.MaterialFactoryNew())
    color = node(material, unreal.MaterialExpressionVectorParameter, -700, 0,
                 parameter_name="Color", default_value=unreal.LinearColor(0.01, 0.01, 0.012, 1.0))
    metallic = node(material, unreal.MaterialExpressionScalarParameter, -700, 200,
                    parameter_name="Metallic", default_value=0.75)
    rough = node(material, unreal.MaterialExpressionScalarParameter, -700, 300,
                 parameter_name="Roughness", default_value=0.32)
    emissive = node(material, unreal.MaterialExpressionScalarParameter, -700, 400,
                    parameter_name="Emissive", default_value=0.0)
    glow = node(material, unreal.MaterialExpressionMultiply, -450, 400)
    link(color, "", glow, "A")
    link(emissive, "", glow, "B")
    MEL.connect_material_property(color, "", unreal.MaterialProperty.MP_BASE_COLOR)
    MEL.connect_material_property(metallic, "", unreal.MaterialProperty.MP_METALLIC)
    MEL.connect_material_property(rough, "", unreal.MaterialProperty.MP_ROUGHNESS)
    MEL.connect_material_property(glow, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    MEL.recompile_material(material)
    return material


BUILDERS = {
    "M_Sov_ArcBolt": build_arc_bolt,
    "M_Sov_Board": build_board,
}


def main() -> None:
    only = {name for name in os.environ.get("VERSE_SOV_ONLY", "").split(",") if name}
    for name, build in BUILDERS.items():
        if not only or name in only:
            build()
    for path in REPORT["assets"]:
        if not LIB.save_asset(path, only_if_is_dirty=False):
            warn(f"save failed: {path}")


try:
    main()
except Exception as error:  # the host must see every failure in the report
    REPORT["ok"] = False
    REPORT["error"] = f"{type(error).__name__}: {error}"
    REPORT["traceback"] = traceback.format_exc()
finally:
    result = os.environ.get("VERSE_SOV_RESULT")
    if result:
        with open(result, "w", encoding="utf-8") as handle:
            json.dump(REPORT, handle, indent=2, sort_keys=True)
    unreal.log(f"[verse_sovereign] ok={REPORT['ok']} assets={len(REPORT['assets'])} "
               f"warnings={len(REPORT['warnings'])}")
    if os.environ.get("VERSE_SOV_QUIT") == "1":
        unreal.SystemLibrary.quit_editor()
