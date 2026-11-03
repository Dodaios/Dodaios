"""Editor step of the gore asset build (WP05): textures, materials, instances.

Runs inside the headless Unreal editor (``-ExecutePythonScript``), started
by ``art/verse/gore/build.py`` under the machine lock. Inputs come from the
environment:

    VERSE_GORE_TEXTURES   folder with the baked ``T_Gore_*_M.png`` masks
    VERSE_GORE_RESULT     JSON report path
    VERSE_GORE_QUIT       "1": quit the editor when done
    VERSE_GORE_HERE       this folder (for ``spec.py``, the shared asset table)
    VERSE_GORE_ONLY       comma-separated asset names to rebuild; empty = all

Creates or replaces, under ``/Game/Verse/Gore`` (owned by WP05):

    T_Gore_Spatter_0..3_M, T_Gore_Drip_M, T_Gore_Pool_M   mask textures
    M_Gore_Decal            deferred decal master (mask, thickness, decal colour)
    MI_Gore_Spatter_0..3    wall and floor spatter
    MI_Gore_Drip            floor drip below a wound
    MI_Gore_Pool            pool under a body (glossier)
    M_Gore_Droplet          burst droplets (instanced static meshes, animated on the GPU)
    M_Gore_Flash            Reduced level: neutral impact flash (unlit, additive)
    MF_Gore_WoundMask       wound mask function for the character master (WP13)

and under ``/Game/Verse/Test/WP05``:

    M_Gore_TestBody         the WP13 fake: a body material with the wound mask

Colours are the dark, desaturated reds art-pipeline 8.1 leaves to VerseGore.
"""

from __future__ import annotations

import json
import os
import sys
import traceback

import unreal

sys.path.insert(0, os.environ.get("VERSE_GORE_HERE") or os.path.dirname(os.path.abspath(__file__)))

import spec  # noqa: E402

GORE = spec.GORE
TEST = spec.TEST
TEXTURES = list(spec.TEXTURES)
ONLY = {name for name in os.environ.get("VERSE_GORE_ONLY", "").split(",") if name}
# Linear colours: fresh blood is a dark red, thick blood near black-red.
BLOOD = unreal.LinearColor(0.115, 0.006, 0.004, 1.0)
BLOOD_THICK = unreal.LinearColor(0.032, 0.0015, 0.001, 1.0)
WOUND_SLOTS = 16

ASSETS = unreal.AssetToolsHelpers.get_asset_tools()
MEL = unreal.MaterialEditingLibrary
LIB = unreal.EditorAssetLibrary
REPORT: dict = {"ok": True, "assets": [], "warnings": []}


def warn(text: str) -> None:
    REPORT["warnings"].append(text)
    unreal.log_warning(f"[verse_gore] {text}")


def fresh(name: str, folder: str, cls, factory):
    path = f"{folder}/{name}"
    if LIB.does_asset_exist(path):
        LIB.delete_asset(path)
    asset = ASSETS.create_asset(name, folder, cls, factory)
    REPORT["assets"].append(path)
    return asset


def set_prop(obj, name: str, value) -> None:
    try:
        obj.set_editor_property(name, value)
    except Exception as error:  # property names move between engine versions
        warn(f"{obj.get_name()}.{name}: {error}")


def wanted(name: str) -> bool:
    return not ONLY or name in ONLY


def load_textures() -> dict:
    textures = {}
    for name in TEXTURES:
        texture = unreal.load_asset(f"{GORE}/{name}")
        if texture is None:
            raise RuntimeError(f"texture missing (build it first): {name}")
        textures[name] = texture
    return textures


def import_textures(folder: str) -> dict:
    tasks = []
    for name in [name for name in TEXTURES if wanted(name)]:
        task = unreal.AssetImportTask()
        task.filename = os.path.join(folder, f"{name}.png")
        task.destination_path = GORE
        task.destination_name = name
        task.automated = True
        task.replace_existing = True
        task.save = False
        tasks.append(task)
    if tasks:
        ASSETS.import_asset_tasks(tasks)
    textures = load_textures()
    for name in [name for name in TEXTURES if wanted(name)]:
        texture = textures[name]
        if texture is None:
            raise RuntimeError(f"texture import failed: {name}")
        set_prop(texture, "srgb", False)
        set_prop(texture, "compression_settings", unreal.TextureCompressionSettings.TC_MASKS)
        set_prop(texture, "lod_group", unreal.TextureGroup.TEXTUREGROUP_WORLD)
        # Gore appears the frame it is hit; a streaming mip would show a flat square first.
        set_prop(texture, "never_stream", True)
        REPORT["assets"].append(f"{GORE}/{name}")
    return textures


def node(material, cls, x: int, y: int, **props):
    expression = MEL.create_material_expression(material, cls, x, y)
    for key, value in props.items():
        set_prop(expression, key, value)
    return expression


def fnode(function, cls, x: int, y: int, **props):
    expression = MEL.create_material_expression_in_function(function, cls, x, y)
    for key, value in props.items():
        set_prop(expression, key, value)
    return expression


def link(a, a_out: str, b, b_in: str) -> None:
    if not MEL.connect_material_expressions(a, a_out, b, b_in):
        warn(f"link {a.get_name()}.{a_out} -> {b.get_name()}.{b_in} failed")


def mask(material, make, source, channels: str, x: int, y: int):
    flags = {c: c in channels for c in "rgba"}
    expression = make(material, unreal.MaterialExpressionComponentMask, x, y, **flags)
    link(source, "", expression, "")
    return expression


def build_decal_master(textures: dict):
    material = fresh("M_Gore_Decal", GORE, unreal.Material, unreal.MaterialFactoryNew())
    set_prop(material, "material_domain", unreal.MaterialDomain.MD_DEFERRED_DECAL)
    set_prop(material, "blend_mode", unreal.BlendMode.BLEND_TRANSLUCENT)
    sample = node(material, unreal.MaterialExpressionTextureSampleParameter2D, -900, 0,
                  parameter_name="Mask", texture=textures["T_Gore_Spatter_0_M"],
                  sampler_type=unreal.MaterialSamplerType.SAMPLERTYPE_MASKS)
    decal = node(material, unreal.MaterialExpressionDecalColor, -900, 300)
    # Decal colour (float3): R = opacity, G = darkening (VerseGore sets it per decal).
    decal_a = mask(material, node, decal, "r", -700, 300)
    decal_g = mask(material, node, decal, "g", -700, 400)
    opacity_scale = node(material, unreal.MaterialExpressionScalarParameter, -700, 200,
                         parameter_name="Opacity", default_value=1.0)
    opacity = node(material, unreal.MaterialExpressionMultiply, -450, 150)
    link(sample, "R", opacity, "A")
    link(decal_a, "", opacity, "B")
    opacity2 = node(material, unreal.MaterialExpressionMultiply, -250, 150)
    link(opacity, "", opacity2, "A")
    link(opacity_scale, "", opacity2, "B")
    MEL.connect_material_property(opacity2, "", unreal.MaterialProperty.MP_OPACITY)

    fresh_color = node(material, unreal.MaterialExpressionVectorParameter, -700, -300,
                       parameter_name="BloodColor", default_value=BLOOD)
    thick_color = node(material, unreal.MaterialExpressionVectorParameter, -700, -150,
                       parameter_name="BloodThickColor", default_value=BLOOD_THICK)
    color = node(material, unreal.MaterialExpressionLinearInterpolate, -450, -250)
    link(fresh_color, "", color, "A")
    link(thick_color, "", color, "B")
    link(sample, "G", color, "Alpha")
    shade = node(material, unreal.MaterialExpressionMultiply, -250, -250)
    link(color, "", shade, "A")
    link(decal_g, "", shade, "B")
    MEL.connect_material_property(shade, "", unreal.MaterialProperty.MP_BASE_COLOR)

    rough_thin = node(material, unreal.MaterialExpressionScalarParameter, -700, 500,
                      parameter_name="RoughnessThin", default_value=0.42)
    rough_thick = node(material, unreal.MaterialExpressionScalarParameter, -700, 600,
                       parameter_name="RoughnessThick", default_value=0.14)
    rough = node(material, unreal.MaterialExpressionLinearInterpolate, -450, 520)
    link(rough_thin, "", rough, "A")
    link(rough_thick, "", rough, "B")
    link(sample, "G", rough, "Alpha")
    MEL.connect_material_property(rough, "", unreal.MaterialProperty.MP_ROUGHNESS)
    MEL.recompile_material(material)
    return material


def build_instance(name: str, parent, texture, scalars: dict | None = None):
    instance = fresh(name, GORE, unreal.MaterialInstanceConstant,
                     unreal.MaterialInstanceConstantFactoryNew())
    MEL.set_material_instance_parent(instance, parent)
    MEL.set_material_instance_texture_parameter_value(instance, "Mask", texture)
    for key, value in (scalars or {}).items():
        MEL.set_material_instance_scalar_parameter_value(instance, key, value)
    MEL.update_material_instance(instance)
    return instance


# World position offset of one droplet instance (HLSL of a Custom node). The instance sits at the
# burst origin; custom data carries spawn time, velocity, life, drag and gravity, and the motion is
# the exact solution of gravity plus linear drag, the same as UVerseGoreSubsystem::DropletOffset.
# A droplet stretches along its velocity, shrinks over its life and collapses to its pivot after.
DROPLET_WPO = """
float age = max(Now - Spawn, 0.0);
float k = max(Drag, 0.01);
float e = exp(-k * age);
float3 terminal = float3(0.0, 0.0, Gravity / k);
float3 velocity = float3(VX, VY, VZ);
float3 travel = (velocity + terminal) * ((1.0 - e) / k) - terminal * age;
float3 current = (velocity + terminal) * e - terminal;
float speed = length(current);
float3 dir = speed > 0.001 ? current / speed : float3(0.0, 0.0, 1.0);
float alive = age < Life ? 1.0 : 0.0;
float shrink = (1.0 - 0.6 * saturate(age / max(Life, 0.01))) * alive;
float3 shaped = (Offset + dir * dot(Offset, dir) * (speed / 400.0)) * shrink;
return travel * alive + shaped - Offset;
"""
DROPLET_INPUTS = ["Offset", "Now", "Spawn", "VX", "VY", "VZ", "Life", "Drag", "Gravity"]


def build_droplet():
    material = fresh("M_Gore_Droplet", GORE, unreal.Material, unreal.MaterialFactoryNew())
    set_prop(material, "used_with_instanced_static_meshes", True)
    # Droplets fly up to ~4 m from their instance; culling bounds must cover the offset.
    set_prop(material, "max_world_position_offset_displacement", 450.0)
    color = node(material, unreal.MaterialExpressionVectorParameter, -500, -100,
                 parameter_name="BloodColor", default_value=BLOOD)
    MEL.connect_material_property(color, "", unreal.MaterialProperty.MP_BASE_COLOR)
    rough = node(material, unreal.MaterialExpressionConstant, -500, 100, r=0.12)
    MEL.connect_material_property(rough, "", unreal.MaterialProperty.MP_ROUGHNESS)
    spec_node = node(material, unreal.MaterialExpressionConstant, -500, 200, r=0.65)
    MEL.connect_material_property(spec_node, "", unreal.MaterialProperty.MP_SPECULAR)

    inputs = []
    for name in DROPLET_INPUTS:
        item = unreal.CustomInput()
        item.set_editor_property("input_name", name)
        inputs.append(item)
    custom = node(material, unreal.MaterialExpressionCustom, -300, 400,
                  code=DROPLET_WPO.strip(), description="VerseGoreDroplet",
                  output_type=unreal.CustomMaterialOutputType.CMOT_FLOAT3)
    set_prop(custom, "inputs", inputs)
    # Vertex offset from the instance pivot in world space (local = instance space for an ISM).
    local = node(material, unreal.MaterialExpressionLocalPosition, -1100, 300,
                 included_offsets=unreal.PositionIncludedOffsets.EXCLUDE_OFFSETS)
    to_world = node(material, unreal.MaterialExpressionTransform, -900, 300,
                    transform_source_type=unreal.MaterialVectorCoordTransformSource.TRANSFORMSOURCE_LOCAL,
                    transform_type=unreal.MaterialVectorCoordTransform.TRANSFORM_WORLD)
    link(local, "", to_world, "")
    link(to_world, "", custom, "Offset")
    now = node(material, unreal.MaterialExpressionTime, -900, 400)
    link(now, "", custom, "Now")
    for index, name in enumerate(["Spawn", "VX", "VY", "VZ", "Life", "Drag", "Gravity"]):
        data = node(material, unreal.MaterialExpressionPerInstanceCustomData,
                    -900, 480 + 80 * index, data_index=index)
        link(data, "", custom, name)
    MEL.connect_material_property(custom, "", unreal.MaterialProperty.MP_WORLD_POSITION_OFFSET)
    MEL.recompile_material(material)
    return material


def build_flash():
    material = fresh("M_Gore_Flash", GORE, unreal.Material, unreal.MaterialFactoryNew())
    set_prop(material, "used_with_instanced_static_meshes", True)
    set_prop(material, "blend_mode", unreal.BlendMode.BLEND_ADDITIVE)
    set_prop(material, "shading_model", unreal.MaterialShadingModel.MSM_UNLIT)
    # Neutral: warm-white, never red (no blood) and never cyan or violet (art-pipeline 8.3).
    color = node(material, unreal.MaterialExpressionConstant3Vector, -700, 0,
                 constant=unreal.LinearColor(0.9, 0.86, 0.78, 1.0))
    fresnel = node(material, unreal.MaterialExpressionFresnel, -700, 200)
    inverse = node(material, unreal.MaterialExpressionOneMinus, -500, 200)
    link(fresnel, "", inverse, "")
    glow = node(material, unreal.MaterialExpressionMultiply, -350, 50)
    link(color, "", glow, "A")
    link(inverse, "", glow, "B")
    strength = node(material, unreal.MaterialExpressionScalarParameter, -350, 250,
                    parameter_name="Strength", default_value=3.0)
    out = node(material, unreal.MaterialExpressionMultiply, -150, 100)
    link(glow, "", out, "A")
    link(strength, "", out, "B")
    MEL.connect_material_property(out, "", unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    MEL.recompile_material(material)
    return material


def build_wound_mask(owner, make, x0: int, y0: int):
    """Wound mask: max over 16 slots of saturate((radius - |p - centre|) / soft).

    ``p`` is the pre-skinned (reference pose) local position, so a wound sits
    on the same spot of the body whatever the animation does. Returns the node
    whose single output is the 0..1 mask.
    """
    position = make(owner, unreal.MaterialExpressionPreSkinnedPosition, x0, y0)
    interp = make(owner, unreal.MaterialExpressionVertexInterpolator, x0 + 200, y0)
    link(position, "", interp, "")
    count = make(owner, unreal.MaterialExpressionScalarParameter, x0 + 200, y0 - 200,
                 parameter_name="Verse_WoundCount", default_value=0.0)
    total = None
    for index in range(WOUND_SLOTS):
        y = y0 + 150 * (index + 1)
        slot = make(owner, unreal.MaterialExpressionVectorParameter, x0, y,
                    parameter_name=f"Verse_Wound_{index:02d}",
                    default_value=unreal.LinearColor(0.0, 0.0, 0.0, 0.0))
        centre = mask(owner, make, slot, "rgb", x0 + 200, y)
        distance = make(owner, unreal.MaterialExpressionDistance, x0 + 400, y)
        link(interp, "", distance, "A")
        link(centre, "", distance, "B")
        # A vector parameter's default output is RGB; the radius is its "A" output.
        inside = make(owner, unreal.MaterialExpressionSubtract, x0 + 600, y)
        link(slot, "A", inside, "A")
        link(distance, "", inside, "B")
        soft = make(owner, unreal.MaterialExpressionMultiply, x0 + 600, y + 60, const_b=0.4)
        link(slot, "A", soft, "A")
        soft_min = make(owner, unreal.MaterialExpressionMax, x0 + 750, y + 60, const_b=0.05)
        link(soft, "", soft_min, "A")
        ratio = make(owner, unreal.MaterialExpressionDivide, x0 + 900, y)
        link(inside, "", ratio, "A")
        link(soft_min, "", ratio, "B")
        clamp = make(owner, unreal.MaterialExpressionSaturate, x0 + 1050, y)
        link(ratio, "", clamp, "")
        if total is None:
            total = clamp
        else:
            merged = make(owner, unreal.MaterialExpressionMax, x0 + 1200, y)
            link(total, "", merged, "A")
            link(clamp, "", merged, "B")
            total = merged
    gate = make(owner, unreal.MaterialExpressionSaturate, x0 + 400, y0 - 200)
    link(count, "", gate, "")
    gated = make(owner, unreal.MaterialExpressionMultiply, x0 + 1400, y0)
    link(total, "", gated, "A")
    link(gate, "", gated, "B")
    return gated


def build_wound_function():
    function = fresh("MF_Gore_WoundMask", GORE, unreal.MaterialFunction,
                     unreal.MaterialFunctionFactoryNew())
    set_prop(function, "description",
             "Verse wound mask (WP05). 0..1 mask from Verse_WoundCount and Verse_Wound_00..15 "
             "(xyz: reference-pose component space cm, w: radius cm). Needs a skeletal mesh.")
    gated = build_wound_mask(function, fnode, -1800, -1400)
    output = fnode(function, unreal.MaterialExpressionFunctionOutput, 0, 0, output_name="Mask")
    link(gated, "", output, "")
    MEL.update_material_function(function)
    return function


def build_test_body():
    material = fresh("M_Gore_TestBody", TEST, unreal.Material, unreal.MaterialFactoryNew())
    set_prop(material, "used_with_skeletal_mesh", True)
    wound = build_wound_mask(material, node, -2200, -1400)
    skin = node(material, unreal.MaterialExpressionConstant3Vector, -500, -300,
                constant=unreal.LinearColor(0.21, 0.19, 0.17, 1.0))
    blood = node(material, unreal.MaterialExpressionConstant3Vector, -500, -150, constant=BLOOD)
    color = node(material, unreal.MaterialExpressionLinearInterpolate, -250, -250)
    link(skin, "", color, "A")
    link(blood, "", color, "B")
    link(wound, "", color, "Alpha")
    MEL.connect_material_property(color, "", unreal.MaterialProperty.MP_BASE_COLOR)
    rough = node(material, unreal.MaterialExpressionLinearInterpolate, -250, 50,
                 const_a=0.75, const_b=0.2)
    link(wound, "", rough, "Alpha")
    MEL.connect_material_property(rough, "", unreal.MaterialProperty.MP_ROUGHNESS)
    MEL.recompile_material(material)
    return material


def main() -> None:
    folder = os.environ["VERSE_GORE_TEXTURES"]
    textures = import_textures(folder)
    if wanted("M_Gore_Decal"):
        master = build_decal_master(textures)
    else:
        master = unreal.load_asset(f"{GORE}/M_Gore_Decal")
    for name, (texture, scalars) in spec.INSTANCES.items():
        if wanted(name):
            build_instance(name, master, textures[texture], scalars)
    builders = {
        "M_Gore_Droplet": build_droplet,
        "M_Gore_Flash": build_flash,
        "MF_Gore_WoundMask": build_wound_function,
        "M_Gore_TestBody": build_test_body,
    }
    for name, build in builders.items():
        if wanted(name):
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
    result = os.environ.get("VERSE_GORE_RESULT")
    if result:
        with open(result, "w", encoding="utf-8") as handle:
            json.dump(REPORT, handle, indent=2, sort_keys=True)
    unreal.log(f"[verse_gore] ok={REPORT['ok']} assets={len(REPORT['assets'])} "
               f"warnings={len(REPORT['warnings'])}")
    if os.environ.get("VERSE_GORE_QUIT") == "1":
        unreal.SystemLibrary.quit_editor()
