"""Export both drones of `drones.py` to Unreal: meshes, own skeletons, clips and atlases (WP13).

Blender entry. Agents run it only through `python scripts/verse/export_unreal.py drones`,
which writes the import records from the result file (`drone_records.py`). Directly:

    python scripts/verse/blender.py run --no-lock art/verse/characters/drones_unreal.py \
        --out art/verse/.cache/unreal/drones --result <file.json>

The same builders as the three.js export (`build_drones.py`): parts, rig, clips and the
512 px painted atlas. Each drone is one skinned mesh on its own small skeleton
(`SKEL_Drone_<Kind>`) and each clip one FBX under `fbx-ue/1`. The three.js view multiplies
the baked per-vertex ambient occlusion (`COLOR_0`) into the base colour; the Unreal
character master has no vertex colour input, so it is multiplied into the base colour atlas
here, texel by texel.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import bpy
import numpy as np
from lib import unreal_export as UE

from characters import common as C
from characters import drones as D
from characters import looks_gear as LG
from characters import paint as PT
from characters.fps import export as EX

#: Drone mesh -> (kind in asset names, parts, rig, clips) of `drones.py`.
DRONES = {
    "SK_Drone_Companion": ("Companion", D.companion_parts, D.companion_rig, D.companion_clips),
    "SK_Drone_Utility": ("Utility", D.utility_parts, D.utility_rig, D.utility_clips),
}


def painter(name: str):
    if name == "SK_Drone_Companion":
        return LG.companion((0.0, 0.0, D.COMP_HOVER), D.COMP_RADII)
    return LG.utility()


def _strip(name: str) -> str:
    return name.split("@")[0].split(".")[0]


def loop_ao(mesh_ob) -> np.ndarray:
    """The baked ambient occlusion (`drones.bake_ao`) per loop triangle corner, (T, 3)."""
    me = mesh_ob.data
    me.calc_loop_triangles()
    attr = me.color_attributes["Col"]
    per_loop = np.array([attr.data[i].color[0] for i in range(len(me.loops))])
    loops = np.array([lt.loops[:] for lt in me.loop_triangles], dtype=np.int64)
    return per_loop[loops]


def bake_ao_into(base_png: Path, out_png: Path, mesh_ob, res: int) -> None:
    """Base colour atlas x the vertex AO, interpolated per texel, re-encoded as sRGB."""
    mesh = PT.Mesh([mesh_ob])
    tri, bary = PT.rasterize(mesh, res)
    ao_tri = loop_ao(mesh_ob)
    if len(ao_tri) != len(mesh.P):
        raise RuntimeError(f"{mesh_ob.name}: {len(ao_tri)} AO triangles, {len(mesh.P)} atlas")
    valid = tri >= 0
    ao = np.ones((res, res))
    t = tri[valid]
    ao[valid] = (ao_tri[t] * bary[valid]).sum(1)
    ao_img = PT.dilate(ao[..., None].repeat(3, 2), valid)[..., 0]
    img = bpy.data.images.load(str(base_png))
    px = np.array(img.pixels[:]).reshape(img.size[1], img.size[0], 4)
    bpy.data.images.remove(img)
    srgb = px[..., :3]
    linear = np.where(srgb <= 0.04045, srgb / 12.92, ((srgb + 0.055) / 1.055) ** 2.4)
    # Blender images are bottom-up; the atlas rows of `rasterize` are UV v up as well.
    linear *= ao_img[..., None]
    out = PT.srgb_encode(linear)
    image = PT.make_image(out_png.stem, out, False)
    image.filepath_raw = str(out_png)
    image.file_format = "PNG"
    image.save()


def slot_values(mat, kind: str, textures: dict | None) -> dict:
    base = _strip(mat.name)
    bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    textured = bsdf.inputs["Base Color"].is_linked
    source = PT.get_factor(mat) if textured else bsdf.inputs["Base Color"].default_value
    colour = list(source)[:3]
    mi = f"MI_Character_Drone{kind}_{base[2:]}"
    out = {
        "slot": base,
        "mi": f"/Game/Verse/Materials/Instances/Characters/{mi}.{mi}",
        "base_color": [round(float(c), 5) for c in colour] + [1.0],
        # a textured slot's roughness is the atlas's (glTF factor 1)
        "roughness": 1.0
        if bsdf.inputs["Roughness"].is_linked
        else round(float(bsdf.inputs["Roughness"].default_value), 4),
        "metallic": round(float(bsdf.inputs["Metallic"].default_value), 4),
    }
    emit = float(bsdf.inputs["Emission Strength"].default_value)
    if emit > 0.0:
        out["emit"] = round(emit, 4)
    elif textures and textured:
        out["textures"] = dict(textures)
    return out


def export_mesh(name: str, rig_ob, mesh_ob, out_dir: Path, slots: list[dict]) -> dict:
    col = UE._export_scene()
    arm = EX._copy_armature(rig_ob, col)
    me = mesh_ob.data.copy()
    body = bpy.data.objects.new(name, me)
    col.objects.link(body)
    for vg in mesh_ob.vertex_groups:
        body.vertex_groups.new(name=vg.name)
    body.parent = arm
    body.modifiers.new("Armature", "ARMATURE").object = arm
    worst, err = EX.influence_stats(body)
    box = UE.bounds_cm(me)
    tris = UE.triangle_count(me)
    path = out_dir / f"{name}.fbx"
    metres = EX._tallest_head(arm)
    EX._make_active(arm)
    digest = UE._write_fbx(col, [arm, body], path)
    EX.check_centimetres(arm, metres, path)
    return {
        "name": name,
        "file": path.relative_to(UE.REPO_ROOT).as_posix(),
        "sha256": digest,
        "triangles": tris,
        "vertices": len(me.vertices),
        "bounds_cm": box,
        "uv_sets": len(me.uv_layers),
        "material_slots": slots,
        "bones": [b.name for b in rig_ob.data.bones],
        "parents": {b.name: (b.parent.name if b.parent else None) for b in rig_ob.data.bones},
        "max_influences": worst,
        "weight_sum_error": round(err, 6),
        "settings_id": UE.SETTINGS_ID,
        "blender": bpy.app.version_string.split(" ")[0],
    }


def _write_anim(col, arm, path: Path, frames: int) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    scene = bpy.context.scene
    scene.render.fps = C.FPS
    scene.render.fps_base = 1.0
    scene.frame_start = 0
    scene.frame_end = max(1, frames - 1)
    view_layer = bpy.context.view_layer
    view_layer.update()
    metres = EX._tallest_head(arm)
    EX._make_active(arm)
    UE._to_centimetres([arm])
    EX.check_centimetres(arm, metres, path)
    units = scene.unit_settings
    units.scale_length = 1.0 / UE.CM
    for obj in view_layer.objects:
        obj.select_set(False)
    arm.select_set(True)
    view_layer.objects.active = arm
    try:
        with bpy.context.temp_override(active_object=arm, object=arm), UE._reproducible_fbx():
            result = bpy.ops.export_scene.fbx(filepath=str(path), **EX.FBX_UE_1_ANIM)
    finally:
        units.scale_length = 1.0
    if "FINISHED" not in result:
        raise UE.ExportError(f"FBX export failed for {path.name}: {result}")
    UE.check_fbx_names(path, {arm.name})
    return hashlib.sha256(path.read_bytes()).hexdigest()


def clip_name(kind: str, clip: str) -> str:
    """`A_Hover` of the companion -> `A_Drone_Companion_Hover`."""
    return f"A_Drone_{kind}_{clip[2:]}"


def export_clip(
    rig_ob, kind: str, clip: str, frames, loop: bool, seconds: float, out_dir: Path
) -> dict:
    col = UE._export_scene()
    arm = EX._copy_armature(rig_ob, col)
    act, slot = D._write_action(arm, clip_name(kind, clip), [dict(f) for f in frames])
    # locations to centimetres with the armature (`_to_centimetres` scales the bones only)
    for layer in act.layers:
        for strip in layer.strips:
            for bag in strip.channelbags:
                for fc in bag.fcurves:
                    if fc.data_path.endswith(".location"):
                        for kp in fc.keyframe_points:
                            kp.co[1] *= UE.CM
                        fc.update()
    arm.animation_data.action = act
    try:
        arm.animation_data.action_slot = slot
    except (AttributeError, TypeError):
        pass
    name = clip_name(kind, clip)
    path = out_dir / f"{name}.fbx"
    digest = _write_anim(col, arm, path, len(frames))
    arm.animation_data_clear()
    bpy.data.actions.remove(act)
    return {
        "name": name,
        "source": clip,
        "file": path.relative_to(UE.REPO_ROOT).as_posix(),
        "sha256": digest,
        "frames": len(frames),
        "fps": C.FPS,
        "seconds": round(seconds, 5),
        "loop": loop,
        "settings_id": UE.SETTINGS_ID,
        "blender": bpy.app.version_string.split(" ")[0],
    }


def build_one(name: str, out: Path) -> dict:
    kind, parts_fn, rig_fn, clips_fn = DRONES[name]
    rig = rig_fn()
    clips = clips_fn(rig)
    mesh_ob = D.assemble(f"{name}_Mesh", parts_fn(), rig)
    D.bake_ao(mesh_ob)
    tex_dir = out / "textures"
    PT.texture(name, [mesh_ob], painter(name), res=D.ATLAS, debug_dir=tex_dir)
    bc = tex_dir / f"T_{name}_BC.png"
    bake_ao_into(tex_dir / f"T_{name}_BaseColor.png", bc, mesh_ob, D.ATLAS)
    files = {
        "BaseColor": bc,
        "Normal": tex_dir / f"T_{name}_Normal.png",
        "ORM": tex_dir / f"T_{name}_ORM.png",
    }
    textures = {k: p.relative_to(UE.REPO_ROOT).as_posix() for k, p in files.items()}
    slots, seen = [], set()
    for m in mesh_ob.data.materials:
        if m is None or _strip(m.name) in seen:
            continue
        seen.add(_strip(m.name))
        slots.append(slot_values(m, kind, textures))
    with PT.export_names(name):
        entry = export_mesh(name, rig, mesh_ob, out / "meshes", slots)
    entry["kind"] = kind
    entry["textures"] = {
        k: {"file": rel, "sha256": hashlib.sha256((UE.REPO_ROOT / rel).read_bytes()).hexdigest()}
        for k, rel in textures.items()
    }
    entry["clips"] = [
        export_clip(rig, kind, cn, fr, loop, t, out / "clips")
        for cn, (fr, loop, t) in clips.items()
    ]
    mesh_ob.hide_set(True)
    rig.hide_set(True)
    return entry


def main(argv: list[str]) -> None:
    ap = argparse.ArgumentParser(prog="drones_unreal")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--result", type=Path, required=True)
    args = ap.parse_args(argv)
    C.reset_scene()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    result = {"drones": [build_one(name, out) for name in DRONES]}
    args.result.parent.mkdir(parents=True, exist_ok=True)
    args.result.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    for d in result["drones"]:
        print(f"[verse] {d['name']}: {d['triangles']} tris, {len(d['clips'])} clips")


main(sys.argv[1:])
