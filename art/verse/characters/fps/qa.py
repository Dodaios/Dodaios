"""Workbench contact sheets of the FPS meshes and clips (look checks, not shipped).

Runs inside Blender from `rig_fps.py --qa DIR`. Renders PNGs into DIR (an
ignored cache folder): a four-view turnaround per mesh and, per selected
clip, a strip of frames with a box standing in for the weapon on `Weapon_R`
(rifle and pistol clips) or `Weapon_L` (knife clips).
"""

from __future__ import annotations

import math
from pathlib import Path

import bmesh
import bpy
from mathutils import Euler, Vector

from characters import common as C

SIZE = (640, 900)


def _scene_setup() -> None:
    scene = bpy.context.scene
    try:
        scene.render.engine = "BLENDER_WORKBENCH"
    except TypeError:
        scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x, scene.render.resolution_y = SIZE
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    shading = scene.display.shading
    shading.light = "STUDIO"
    shading.color_type = "MATERIAL"
    shading.show_shadows = True
    shading.show_cavity = True
    scene.render.film_transparent = False
    world = scene.world or bpy.data.worlds.new("QA")
    scene.world = world
    world.color = (0.18, 0.18, 0.19)


def _camera(target: Vector, distance: float, yaw: float, height: float, ortho: float):
    cam = bpy.data.objects.get("QA_Camera")
    if cam is None:
        cam = bpy.data.objects.new("QA_Camera", bpy.data.cameras.new("QA_Camera"))
        C.link(cam)
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = ortho
    yaw_r = math.radians(yaw)
    pos = target + Vector((math.sin(yaw_r) * distance, -math.cos(yaw_r) * distance, height))
    cam.location = pos
    direction = target - pos
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.camera = cam
    return cam


def _floor() -> None:
    if bpy.data.objects.get("QA_Floor"):
        return
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=20, y_segments=20, size=3.0)
    me = bpy.data.meshes.new("QA_Floor")
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new("QA_Floor", me)
    C.link(ob)


def _weapon_box(name: str, length: float, height: float):
    ob = bpy.data.objects.get(name)
    if ob is not None:
        return ob
    bm = bmesh.new()
    geom = bmesh.ops.create_cube(bm, size=1.0)
    # Weapon frame: bone Y is up, bone Z the barrel; the grip sits at the origin.
    bmesh.ops.scale(bm, verts=geom["verts"], vec=(0.04, height, length))
    bmesh.ops.translate(bm, verts=geom["verts"], vec=(0.0, height * 0.35, length * 0.3))
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    C.link(ob)
    return ob


def render(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    bpy.context.scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


def turnaround(mesh_ob, out: Path, name: str) -> list[Path]:
    _scene_setup()
    _floor()
    mesh_ob.hide_set(False)
    mesh_ob.hide_render = False
    paths = []
    for yaw in (0, 90, 180, 270):
        _camera(Vector((0, 0, 0.9)), 6.0, yaw, 0.15, 2.2)
        p = out / f"{name}_turn_{yaw:03d}.png"
        render(p)
        paths.append(p)
    mesh_ob.hide_set(True)
    mesh_ob.hide_render = True
    return paths


def pose_strip(rig, mesh_ob, poses, clip, out: Path, frames: list[int], views=(30,)) -> list:
    """Render `frames` of `poses` posed on `rig` with `mesh_ob` (one PNG per frame)."""
    _scene_setup()
    _floor()
    mesh_ob.hide_set(False)
    mesh_ob.hide_render = False
    cls_bone = "Weapon_L" if "Knife" in clip.name or "Finisher" in clip.name else "Weapon_R"
    is_pistol = "Pistol" in clip.name
    box = _weapon_box(
        "QA_Weapon_" + ("P" if is_pistol else "R"),
        0.22 if is_pistol else 0.75,
        0.12 if is_pistol else 0.16,
    )
    knife = _weapon_box("QA_Knife", 0.20, 0.03)
    for b in (box, knife):
        b.hide_render = True
    shown = knife if cls_bone == "Weapon_L" else box
    shown.hide_render = False
    paths = []
    for f in frames:
        f = min(f, len(poses) - 1)
        rig.apply_static(poses[f])
        bpy.context.view_layer.update()
        pb = rig.ob.pose.bones[cls_bone]
        shown.matrix_world = rig.ob.matrix_world @ pb.matrix
        root = rig.ob.pose.bones["Root"].matrix.translation
        for yaw in views:
            _camera(Vector((root.x, root.y, 0.9 + root.z * 0.5)), 6.0, yaw, 0.6, 2.6)
            p = out / f"{clip.name}_f{f:03d}_y{yaw:03d}.png"
            render(p)
            paths.append(p)
    shown.hide_render = True
    mesh_ob.hide_set(True)
    mesh_ob.hide_render = True
    for pb in rig.ob.pose.bones:
        pb.location = (0, 0, 0)
        pb.rotation_quaternion = (1, 0, 0, 0)
    return paths


def first_person(rig, mesh_ob, poses, clip, out: Path) -> Path:
    """The owner's view from the Camera bone (perspective, 90 deg)."""
    _scene_setup()
    mesh_ob.hide_set(False)
    mesh_ob.hide_render = False
    box = _weapon_box(
        "QA_Weapon_" + ("P" if "Pistol" in clip.name else "R"),
        0.22 if "Pistol" in clip.name else 0.75,
        0.12 if "Pistol" in clip.name else 0.16,
    )
    box.hide_render = False
    rig.apply_static(poses[0])
    bpy.context.view_layer.update()
    box.matrix_world = rig.ob.matrix_world @ rig.ob.pose.bones["Weapon_R"].matrix
    cam_bone = rig.ob.pose.bones["Camera"].matrix
    cam = _camera(Vector((0, 0, 0)), 1.0, 0, 0, 1.0)
    cam.data.type = "PERSP"
    cam.data.lens_unit = "FOV"
    cam.data.angle = math.radians(90.0)
    cam.data.clip_start = 0.02
    eye = (rig.ob.matrix_world @ cam_bone).translation
    cam.location = eye
    cam.rotation_euler = Euler((math.radians(90.0), 0.0, math.radians(180.0)))
    # The owner never sees their own head (13.5: the engine hides the Head
    # bone); without this the camera looks at the inside of the skull.
    mask = mesh_ob.modifiers.new("QA_HideHead", "MASK")
    mask.vertex_group = "Head"
    mask.invert_vertex_group = True
    mask.threshold = 0.5
    p = out / f"{clip.name}_fp.png"
    render(p)
    mesh_ob.modifiers.remove(mask)
    box.hide_render = True
    mesh_ob.hide_set(True)
    mesh_ob.hide_render = True
    return p
