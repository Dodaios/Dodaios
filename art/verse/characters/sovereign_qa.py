"""Look-development renders of the Sovereign (Cycles, perspective).

    python scripts/verse/blender.py run art/verse/characters/sovereign_qa.py [--no-build]

Builds SK_Sovereign (no clips), then renders front three-quarter, back, side,
a walk frame and a close-up of the hood into art/verse/.cache/characters/qa/.
"""

from __future__ import annotations

import math
import sys

import bpy
from mathutils import Vector

from characters import anim as A
from characters import build
from characters import common as C

QA = C.CACHE / "qa"


def lights():
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "GPU"
    sc.cycles.samples = 96
    sc.cycles.use_denoising = True
    sc.view_settings.view_transform = "AgX"
    sc.view_settings.look = "AgX - Medium High Contrast"
    world = bpy.data.worlds.new("SovWorld")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.012, 0.014, 0.02, 1)
    sc.world = world
    fm = bpy.data.materials.new("SovFloor")
    fm.use_nodes = True
    b = fm.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (0.02, 0.021, 0.024, 1)
    b.inputs["Roughness"].default_value = 0.25
    bpy.ops.mesh.primitive_plane_add(size=40, location=(0, 0, 0))
    bpy.context.active_object.data.materials.append(fm)
    for name, loc, energy, col, size in (
        ("key", (-2.2, -2.6, 3.4), 300, (1.0, 0.93, 0.85), 1.6),
        ("rim", (2.4, 2.8, 2.6), 420, (0.75, 0.82, 1.0), 1.0),
        ("fill", (2.6, -2.2, 1.4), 120, (0.8, 0.85, 1.0), 2.5),
    ):
        ld = bpy.data.lights.new(f"sov_{name}", "AREA")
        ld.energy = energy
        ld.color = col
        ld.size = size
        lo = bpy.data.objects.new(f"sov_{name}", ld)
        lo.location = loc
        d = Vector((0, 0, 1.1)) - Vector(loc)
        lo.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
        C.link(lo)


def camera(target: Vector, yaw_deg: float, dist: float, lens=50.0, height=1.25, res=(900, 1200)):
    sc = bpy.context.scene
    cd = bpy.data.cameras.get("sov_cam") or bpy.data.cameras.new("sov_cam")
    cd.lens = lens
    cam = bpy.data.objects.get("sov_cam") or C.link(bpy.data.objects.new("sov_cam", cd))
    yaw = math.radians(yaw_deg)
    # yaw 0 = in front of the character (Blender -Y)
    cam.location = target + Vector((math.sin(yaw) * dist, -math.cos(yaw) * dist, height - target.z))
    cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
    sc.camera = cam
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.render.resolution_percentage = 100


def render(name):
    bpy.context.scene.render.filepath = str(QA / f"{name}.png")
    bpy.ops.render.render(write_still=True)
    print(f"[sovqa] {QA / f'{name}.png'}")


def main(argv):
    built = build.main(["--only", "SK_Sovereign", "--no-clips"])
    ctx, objs = built["SK_Sovereign"]
    arm = ctx.export_arm
    for o in bpy.context.scene.objects:
        if o.type == "MESH" and o not in objs:
            o.hide_render = True
    C.ensure_dir(QA)
    lights()
    body = A.Body(ctx.rig)
    rig = ctx.rig

    def pose(p):
        # the shared bones' pose from the shared rig, set on the Sovereign's own skeleton
        for n, m in rig.basis(rig.solve(p)).items():
            pb = arm.pose.bones[n]
            pb.rotation_mode = "QUATERNION"
            loc, q, _ = m.decompose()
            pb.location = loc if n == "Hips" else Vector()
            pb.rotation_quaternion = q

    which = argv[0] if argv else "all"
    if "nocloak" in argv:
        for o in objs:
            if o.name.endswith("Cloak"):
                o.hide_render = True
    pose(A.clip_idle(body)[40])
    bpy.context.view_layer.update()
    mid = Vector((0, 0, 1.0))
    if which in ("all", "views"):
        camera(mid, 25, 4.2)
        render("sov_front34")
        camera(mid, 180, 4.2)
        render("sov_back")
        camera(mid, 90, 4.2)
        render("sov_side")
    if which in ("all", "face"):
        camera(Vector((0, 0, 1.6)), 15, 1.3, lens=70, height=1.62, res=(900, 900))
        render("sov_face")
    if which in ("all", "walk"):
        walk = A.clip_walk(body)
        for f in (0, 8):
            pose(walk[f])
            bpy.context.view_layer.update()
            camera(mid, 60, 4.2)
            render(f"sov_walk{f}")


if __name__ == "__main__":
    main(sys.argv[1:])
