"""QA renders of the crew at the game camera (Cycles).

Orthographic camera pitched 60 degrees below the horizon (looking towards
Blender +Y = three.js -Z), glossy black deck, overhead white light panels.
Renders at the in-game density (96 px/m) and at 3x for detail, plus a walk
filmstrip. Output: art/verse/.cache/characters/qa/.
"""

from __future__ import annotations

import math

import bpy
from mathutils import Vector

from characters import anim as A
from characters import common as C
from characters import paint as PT
from characters import posing as P

QA_DIR = C.CACHE / "qa"


def _hex(h: str):
    h = h.lstrip("#")
    srgb = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    return tuple(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in srgb)


def stage():
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "GPU"
    sc.cycles.samples = 128
    sc.cycles.use_denoising = True
    sc.view_settings.view_transform = "AgX"
    sc.view_settings.look = "None"
    sc.render.film_transparent = False
    world = bpy.data.worlds.new("QAWorld")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.004, 0.005, 0.007, 1)
    sc.world = world
    floor_m = bpy.data.materials.new("QA_Floor")
    floor_m.use_nodes = True
    bsdf = floor_m.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.006, 0.006, 0.007, 1)
    bsdf.inputs["Roughness"].default_value = 0.14
    bpy.ops.mesh.primitive_plane_add(size=60, location=(0, 10, 0))
    floor = bpy.context.active_object
    floor.data.materials.append(floor_m)
    panel_m = bpy.data.materials.new("QA_Panel")
    panel_m.use_nodes = True
    nt = panel_m.node_tree
    nt.nodes.remove(nt.nodes["Principled BSDF"])
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs[0].default_value = (0.92, 0.96, 1.0, 1)
    em.inputs[1].default_value = 5.0
    nt.links.new(em.outputs[0], nt.nodes["Material Output"].inputs[0])
    for ix in range(-8, 18):
        for iy in range(-2, 5):
            x, y = ix * 1.2, iy * 1.8
            bpy.ops.mesh.primitive_plane_add(size=1, location=(x, y, 3.2))
            p = bpy.context.active_object
            p.scale = (1.0, 0.28, 1)
            p.rotation_euler = (math.pi, 0, 0)
            p.data.materials.append(panel_m)
            p.visible_camera = False
    for ix in range(-2, 8):
        for iy in (-1, 1):
            ld = bpy.data.lights.new("qa_area", "AREA")
            ld.shape = "RECTANGLE"
            ld.size, ld.size_y = 1.2, 0.3
            ld.energy = 42
            ld.color = (0.93, 0.96, 1.0)
            lo = bpy.data.objects.new("qa_area", ld)
            lo.location = (ix * 2.4, iy * 1.4, 3.1)
            C.link(lo)


def camera(cx: float, cz: float, width_m: float, height_m: float, ppm: int):
    sc = bpy.context.scene
    cd = bpy.data.cameras.new("qa_cam")
    cd.type = "ORTHO"
    cam = bpy.data.objects.get("qa_cam") or C.link(bpy.data.objects.new("qa_cam", cd))
    cam.data = cd
    cd.ortho_scale = max(width_m, height_m)
    cd.clip_end = 100
    sc.camera = cam
    d = Vector((0, math.cos(math.radians(60)), -math.sin(math.radians(60))))
    cam.location = Vector((cx, 0.0, cz)) - d * 20
    cam.rotation_euler = (math.radians(30), 0, 0)
    sc.render.resolution_x = int(round(width_m * ppm))
    sc.render.resolution_y = int(round(height_m * ppm))
    sc.render.resolution_percentage = 100
    return cam


def instance(cid, objs, ctx, x, tier=None, cap=True, pose=None):
    """Posed, tinted copy of a built character at x."""
    arm = ctx.arm.copy()
    C.link(arm)
    arm.location = (x, 0, 0)
    arm.animation_data_clear()
    out = [arm]
    for o in objs:
        short = o.name.split(":")[-1]
        if short == "Cap" and not cap:
            continue
        c = o.copy()
        c.data = o.data.copy()
        C.link(c)
        c.parent = arm
        c.matrix_parent_inverse.identity()
        c.location = (0, 0, 0)
        for mod in c.modifiers:
            if mod.type == "ARMATURE":
                mod.object = arm
        for i, m in enumerate(c.data.materials):
            if m is None:
                continue
            base = m.name.split("@")[0]
            col = None
            if tier and base in tier:
                col = tier[base]
            if tier and base.startswith("M_RankTile_"):
                col = None
            if col or (tier and base.startswith("M_RankTile_")):
                mm = m.copy()
                bsdf = mm.node_tree.nodes["Principled BSDF"]
                if col:
                    PT.set_factor(mm, (*_hex(col), 1))
                else:
                    k = int(base[-1])
                    lit = k <= tier.get("tiles", 0)
                    if lit:
                        PT.set_factor(mm, (*_hex(tier["tile"]), 1))
                        bsdf.inputs["Emission Color"].default_value = (*_hex(tier["tile"]), 1)
                        bsdf.inputs["Emission Strength"].default_value = 0.6
                c.data.materials[i] = mm
        out.append(c)
    if pose is not None:
        P.Rig(arm).apply_static(pose)
    return out


def render(path):
    sc = bpy.context.scene
    sc.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    print(f"[qa] {path}")


def contact_sheet(built, ctxs, full=True):
    from characters.build import TIERS

    C.ensure_dir(QA_DIR)
    for o in bpy.context.scene.objects:
        o.hide_render = o.type == "MESH" or o.type == "ARMATURE"
    stage()
    lineup = []
    for cid, (ctx, objs) in built.items():
        if cid.startswith("SK_Officer"):
            tiers = ["deck", "line", "command", "flag"] if cid.endswith("_M") else ["line", "flag"]
            for t in tiers:
                tier = dict(TIERS[t])
                tier["tiles"] = {"deck": 2, "line": 3, "command": 5, "flag": 6}[t]
                lineup.append((cid, ctx, objs, tier, TIERS[t]["cap"]))
        else:
            lineup.append((cid, ctx, objs, None, True))
    x = 0.0
    xs = []
    for cid, ctx, objs, tier, cap in lineup:
        body = A.Body(ctx.rig)
        pose = A.clip_idle(body)[40]
        for o in instance(cid, objs, ctx, x, tier, cap, pose):
            o.hide_render = False
        xs.append(x)
        x += 0.95
    for name in ("SK_Drone_Companion", "SK_Drone_Utility"):
        path = C.OUT_DIR / f"{name}.glb"
        if not path.is_file():
            continue
        before = set(bpy.context.scene.objects)
        bpy.ops.import_scene.gltf(filepath=str(path))
        new = [o for o in bpy.context.scene.objects if o not in before]
        for o in new:
            if o.parent is None:
                o.location.x += x - 0.2
            o.hide_render = o.type not in ("MESH", "ARMATURE", "EMPTY")
        xs.append(x - 0.2)
        x += 0.55
    width = x + 0.4
    cx = (xs[0] + xs[-1]) / 2
    for ppm, tag in ((96, "1x"), (288, "3x")):
        camera(cx, 0.85, width, 2.0, ppm)
        bpy.context.scene.cycles.samples = 128 if ppm < 200 else 96
        render(QA_DIR / f"contact_{tag}.png")
    if not full:
        return
    # walk filmstrip (first built character), 10 frames, 3x
    cid, (ctx, objs) = next(iter(built.items()))
    body = A.Body(ctx.rig)
    walk = A.clip_walk(body)
    for o in bpy.context.scene.objects:
        if o.type in ("MESH", "ARMATURE") and not o.name.startswith(("Plane", "qa")):
            o.hide_render = True
    x0 = 0.0
    n = 10
    for k in range(n):
        f = k * A.WALK_FRAMES // n
        for o in instance(
            cid, objs, ctx, x0 + k * 0.8, dict(TIERS["line"], tiles=3), True, walk[f]
        ):
            o.hide_render = False
    camera(x0 + (n - 1) * 0.4, 0.85, n * 0.8 + 0.2, 2.0, 192)
    bpy.context.scene.cycles.samples = 96
    render(QA_DIR / "walk_filmstrip.png")
    poses_sheet(built)


def _proxy(name, loc, size, color=(0.05, 0.055, 0.06)):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=loc)
    ob = bpy.context.active_object
    ob.name = f"qa_{name}"
    ob.scale = size
    m = bpy.data.materials.new(f"qa_{name}")
    m.diffuse_color = (*color, 1)
    m.use_nodes = True
    m.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (*color, 1)
    m.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.4
    ob.data.materials.append(m)
    return ob


def poses_sheet(built):
    """Key frames of the clips on the line-tier officer, with seat/console/bunk proxies."""
    from characters.build import TIERS

    for o in bpy.context.scene.objects:
        if o.type in ("MESH", "ARMATURE", "EMPTY") and not o.name.startswith(("Plane", "qa")):
            o.hide_render = True
    cid = next((k for k in built if k.startswith("SK_Officer")), next(iter(built)))
    ctx, objs = built[cid]
    body = A.Body(ctx.rig)
    shots = [
        ("A_Sit_Type", 30),
        ("A_Sit_Idle", 60),
        ("A_Stand_Type", 30),
        ("A_Talk", 40),
        ("A_Listen", 50),
        ("A_Salute", 36),
        ("A_Wave", 15),
        ("A_Sleep", 30),
    ]
    tier = dict(TIERS["line"], tiles=3)
    x = 12.0
    xs = []
    for clip, fr in shots:
        poses = A.CLIPS[clip][0](body)
        if clip == "A_Sleep":
            x += 0.3
            _proxy("bunk", (x, 0.05, -0.1), (0.9, 2.0, 0.2), (0.16, 0.17, 0.19))
        for o in instance(cid, objs, ctx, x, tier, clip != "A_Sleep", poses[fr]):
            o.hide_render = False
        if clip.startswith("A_Sit"):
            _proxy("seat", (x, 0.0, C.SEAT_HEIGHT - 0.03), (0.46, 0.44, 0.06))
            _proxy("seatpost", (x, 0.0, 0.2), (0.06, 0.06, 0.4))
        if clip == "A_Sit_Type":
            _proxy("desk", (x, -0.55, C.DESK_HEIGHT - 0.02), (0.9, 0.36, 0.04))
        if clip == "A_Stand_Type":
            _proxy("console", (x, -0.52, C.STAND_DESK_HEIGHT / 2), (0.9, 0.3, C.STAND_DESK_HEIGHT))
        xs.append(x)
        x += 1.0 if clip != "A_Sleep" else 1.2
    for o in bpy.context.scene.objects:
        if o.name.startswith("qa_") and o.type == "MESH":
            o.hide_render = False
    # lights over the pose strip
    for i in range(6):
        ld = bpy.data.lights.new("qa_area2", "AREA")
        ld.shape = "RECTANGLE"
        ld.size, ld.size_y = 1.2, 0.3
        ld.energy = 42
        lo = bpy.data.objects.new("qa_area2", ld)
        lo.location = (12.0 + i * 1.6, 0.0, 3.1)
        C.link(lo)
    camera((xs[0] + xs[-1]) / 2, 0.75, x - xs[0] + 0.4, 2.4, 160)
    bpy.context.scene.cycles.samples = 96
    render(QA_DIR / "poses.png")
