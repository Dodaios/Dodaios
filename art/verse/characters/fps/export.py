"""FBX export of the FPS characters and clips under `fbx-ue/1` (art-pipeline 6.1).

Runs inside Blender. Meshes go through `lib.unreal_export._write_fbx` (the
frozen settings, centimetre data, reproducible bytes). Clips use the same
settings with only the animation bake switched on (`FBX_UE_1_ANIM`): one FBX
per clip holding the armature and its one action, sampled once per frame.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import bpy
import numpy as np
from lib import unreal_export as UE

from characters.fps import skeleton as S
from characters.fps import solver as SV

#: `fbx-ue/1` with the animation bake on; every other key is the frozen set.
FBX_UE_1_ANIM: dict = {
    **UE.FBX_UE_1,
    "object_types": {"ARMATURE"},
    "bake_anim": True,
    "bake_anim_use_all_bones": True,
    "bake_anim_use_nla_strips": False,
    "bake_anim_use_all_actions": False,
    "bake_anim_force_startend_keying": True,
    "bake_anim_step": 1.0,
    "bake_anim_simplify_factor": 0.0,
}


def _copy_armature(arm_ob, col) -> bpy.types.Object:
    data = arm_ob.data.copy()
    ob = bpy.data.objects.new("Armature", data)
    col.objects.link(ob)
    ob.matrix_world = arm_ob.matrix_world.copy()
    bpy.context.view_layer.update()  # creates the pose
    return ob


def influence_stats(mesh_ob) -> tuple[int, float]:
    """(largest influence count, largest |sum - 1|) over the mesh's vertices."""
    worst, err = 0, 0.0
    for v in mesh_ob.data.vertices:
        ws = [g.weight for g in v.groups if g.weight > 0.0]
        worst = max(worst, len(ws))
        err = max(err, abs(sum(ws) - 1.0))
    return worst, err


def export_mesh(name: str, arm_ob, mesh_ob, out_dir: Path, slots: list[dict]) -> dict:
    """Export one skinned character mesh with its armature; returns the result entry."""
    col = UE._export_scene()
    arm = _copy_armature(arm_ob, col)
    me = mesh_ob.data.copy()
    body = bpy.data.objects.new(name, me)
    col.objects.link(body)
    for vg in mesh_ob.vertex_groups:
        body.vertex_groups.new(name=vg.name)
    # Vertex group weights live on the mesh data, which was copied with them.
    body.parent = arm
    mod = body.modifiers.new("Armature", "ARMATURE")
    mod.object = arm
    worst, err = influence_stats(body)
    box = UE.bounds_cm(me)
    tris = UE.triangle_count(me)
    path = out_dir / f"{name}.fbx"
    digest = UE._write_fbx(col, [arm, body], path)
    return {
        "name": name,
        "file": path.relative_to(UE.REPO_ROOT).as_posix(),
        "sha256": digest,
        "triangles": tris,
        "vertices": len(me.vertices),
        "bounds_cm": box,
        "uv_sets": len(me.uv_layers),
        "material_slots": slots,
        "bones": [b.name for b in arm_ob.data.bones],
        "parents": {b.name: (b.parent.name if b.parent else None) for b in arm_ob.data.bones},
        "max_influences": worst,
        "weight_sum_error": round(err, 6),
        "settings_id": UE.SETTINGS_ID,
        "blender": bpy.app.version_string.split(" ")[0],
    }


def _write_anim_fbx(col, arm, path: Path, frames: int, fps: int) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    scene = bpy.context.scene
    scene.render.fps = fps
    scene.render.fps_base = 1.0
    scene.frame_start = 0
    scene.frame_end = max(1, frames - 1)
    view_layer = bpy.context.view_layer
    view_layer.update()
    UE._to_centimetres([arm])
    units = scene.unit_settings
    units.scale_length = 1.0 / UE.CM
    for obj in view_layer.objects:
        obj.select_set(False)
    arm.select_set(True)
    view_layer.objects.active = arm
    try:
        override = bpy.context.temp_override(active_object=arm, object=arm)
        with override, UE._reproducible_fbx():
            result = bpy.ops.export_scene.fbx(filepath=str(path), **FBX_UE_1_ANIM)
    finally:
        units.scale_length = 1.0
    if "FINISHED" not in result:
        raise UE.ExportError(f"FBX export failed for {path.name}: {result}")
    UE.check_fbx_names(path, {arm.name})
    return hashlib.sha256(path.read_bytes()).hexdigest()


def export_clip(rig: SV.FpsRig, clip, poses: list[dict], curves: dict, out_dir: Path) -> dict:
    col = UE._export_scene()
    arm = _copy_armature(rig.ob, col)
    # The copy is scaled to centimetres at write time; locations follow.
    SV.write_action(rig, arm, clip.name, poses, scale=UE.CM)
    path = out_dir / f"{clip.name}.fbx"
    digest = _write_anim_fbx(col, arm, path, len(poses), clip.fps)
    act = arm.animation_data.action if arm.animation_data else None
    arm.animation_data_clear()
    if act is not None:
        bpy.data.actions.remove(act)
    root = [rig.solve(poses[i])["Root"].translation for i in (0, -1)]
    return {
        "name": clip.name,
        "file": path.relative_to(UE.REPO_ROOT).as_posix(),
        "sha256": digest,
        "frames": len(poses),
        "fps": clip.fps,
        "seconds": round((len(poses) - 1) / clip.fps, 5),
        "loop": clip.loop,
        "root_motion": clip.root_motion,
        "root_travel_cm": [round(float(x) * 100.0, 3) for x in (root[1] - root[0])],
        "markers": [list(m) for m in clip.markers],
        "curves": {k: [list(p) for p in v] for k, v in curves.items()},
        "settings_id": UE.SETTINGS_ID,
        "blender": bpy.app.version_string.split(" ")[0],
    }


def offhand_error_cm(rig: SV.FpsRig, fps, poses: list[dict], cls: str) -> float:
    """Largest distance (cm) between Hand_L and the support grip on Weapon_R in `poses`."""
    worst = 0.0
    for p in poses:
        W = rig.solve(p)
        want = (W["Weapon_R"] @ fps.support[cls]).translation
        worst = max(worst, float((want - W["Hand_L"].translation).length) * 100.0)
    return worst


def bone_check(arm_ob) -> list[str]:
    names = [b.name for b in arm_ob.data.bones]
    problems = S.check_names(names)
    problems += S.check_hierarchy(
        {b.name: b.parent.name if b.parent else None for b in arm_ob.data.bones}
    )
    return problems


def weights_array(mesh_ob) -> np.ndarray:
    n = len(mesh_ob.data.vertices)
    out = np.zeros(n)
    for v in mesh_ob.data.vertices:
        out[v.index] = len([g for g in v.groups if g.weight > 0])
    return out
