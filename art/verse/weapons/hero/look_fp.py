"""Render the hero weapon from the person's eye, hip and aim (bpy, Cycles).

    python scripts/verse/blender.py run art/verse/weapons/hero/look_fp.py -- <out_dir> [samples]

Camera and weapon poses match `UVerseViewmodelComponent` (field of view 74 deg,
hip offset 26/11/-17 cm, sight at 19 cm while aiming). The room is a plain
dark hangar bay lit by warm overhead strips and a cool fill, close to the duel
arena, so the result reads as it will in the game.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import bpy
from mathutils import Euler, Matrix, Vector

from weapons.hero import graveline

FOV_DEG = 74.0
HIP = (0.26, 0.11, -0.17)  # camera space: forward, right, up (metres)
HIP_ROT = (2.0, -4.0, 0.0)  # pitch, yaw, roll (degrees, Unreal order)
SIGHT_DISTANCE = 0.19


def _reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def _room():
    def plane(name, size, loc, rot, colour, rough=0.8):
        bpy.ops.mesh.primitive_plane_add(size=1.0, location=loc, rotation=rot)
        obj = bpy.context.active_object
        obj.name = name
        obj.scale = (*size, 1.0)
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
        bsdf.inputs["Base Color"].default_value = (*colour, 1.0)
        bsdf.inputs["Roughness"].default_value = rough
        obj.data.materials.append(mat)

    plane("Floor", (30, 30), (0, 0, -1.6), (0, 0, 0), (0.2, 0.2, 0.205), 0.55)
    plane("Ceiling", (30, 30), (0, 0, 3.2), (math.pi, 0, 0), (0.08, 0.08, 0.08))
    plane("WallFar", (30, 6), (6.0, 0, 0.8), (0, math.radians(90), 0), (0.12, 0.12, 0.125))
    plane("WallL", (30, 6), (0, 4.0, 0.8), (math.radians(90), 0, 0), (0.16, 0.16, 0.165))
    plane("WallR", (30, 6), (0, -4.0, 0.8), (math.radians(-90), 0, 0), (0.16, 0.16, 0.165))
    for i, x in enumerate((-2.0, 1.5, 5.0)):
        bpy.ops.object.light_add(type="AREA", location=(x, 0.6, 3.0))
        light = bpy.context.active_object
        light.data.shape = "RECTANGLE"
        light.data.size, light.data.size_y = 3.0, 0.4
        light.data.energy = 380
        light.data.color = (1.0, 0.82, 0.62)
    bpy.ops.object.light_add(
        type="AREA", location=(-1.0, -2.5, 1.0), rotation=(0, math.radians(70), math.radians(-60))
    )
    fill = bpy.context.active_object
    fill.data.size = 2.0
    fill.data.energy = 120
    fill.data.color = (0.75, 0.85, 1.0)
    world = bpy.data.worlds.new("World")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.02, 0.02, 0.022, 1)
    bpy.context.scene.world = world


def _camera():
    cam_data = bpy.data.cameras.new("Eye")
    cam_data.sensor_fit = "HORIZONTAL"
    cam_data.angle = math.radians(FOV_DEG)
    cam_data.clip_start = 0.005
    cam = bpy.data.objects.new("Eye", cam_data)
    bpy.context.scene.collection.objects.link(cam)
    # Blender camera looks down -Z; turn it to look along +X with +Z up.
    cam.rotation_euler = Euler((math.radians(90), 0, math.radians(-90)), "XYZ")
    cam.location = (0, 0, 0)
    bpy.context.scene.camera = cam
    return cam


def _weapon_root():
    root = bpy.data.objects.new("WeaponRoot", None)
    bpy.context.scene.collection.objects.link(root)
    for obj in bpy.data.collections[graveline.kit.COLLECTION].objects:
        obj.parent = root
    return root


def _pose(root, offset, rot):
    """Camera space (forward, right, up) and Unreal pitch/yaw/roll -> Blender (+X fwd, +Y left)."""
    fwd, right, up = offset
    pitch, yaw, roll = (math.radians(a) for a in rot)
    r = (
        Matrix.Rotation(-yaw, 4, "Z")
        @ Matrix.Rotation(-pitch, 4, "Y")
        @ Matrix.Rotation(roll, 4, "X")
    )
    root.matrix_world = Matrix.Translation((fwd, -right, up)) @ r


def main(out_dir: Path, samples: int) -> None:
    _reset()
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = samples
    scene.cycles.use_denoising = True
    scene.render.resolution_x, scene.render.resolution_y = 1920, 1080
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "AgX - Medium High Contrast"
    graveline.build()
    _room()
    _camera()
    root = _weapon_root()
    out_dir.mkdir(parents=True, exist_ok=True)

    _pose(root, HIP, HIP_ROT)
    scene.render.filepath = str(out_dir / "hip.png")
    bpy.ops.render.render(write_still=True)

    sx, sy, sz = graveline.SOCKETS["SOCKET_Sight"]
    _pose(root, (SIGHT_DISTANCE - sx, sy, -sz), (0, 0, 0))
    scene.render.filepath = str(out_dir / "ads.png")
    bpy.ops.render.render(write_still=True)

    # A three-quarter product shot to judge the model itself.
    root.matrix_world = Matrix.Identity(4)
    cam = scene.camera
    cam.data.angle = math.radians(30)
    cam.location = Vector((0.55, -0.95, 0.35))
    direction = Vector((0.22, 0.0, 0.02)) - cam.location
    cam.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    scene.render.filepath = str(out_dir / "product.png")
    bpy.ops.render.render(write_still=True)


if __name__ == "__main__":
    args = sys.argv[1:]
    main(Path(args[0]), int(args[1]) if len(args) > 1 else 64)
