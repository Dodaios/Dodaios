"""Technician (black work suit, glossy helmet, chest box) and trooper (white armour).

Built with the same garment-body + generated-pieces approach as outfits.py.
Original designs: helmets are grown from the measured skull, armour plates from
regions of the body surface.
"""

from __future__ import annotations

import math

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

from characters import common as C
from characters import outfits as O


def classify_suit(
    ctx, boot_top: float, suit="M_Uniform", glove="M_Gloves", inflate_body=0.008, head_skin=True
):
    """One-piece suit: everything cloth except gloves and (optionally) the face."""
    V = ctx.V
    n = len(V)
    hands, fore, upper_arm, head, thigh = O._limbs(ctx)
    t = ctx.tparam
    labels = [suit] * n
    inflate = np.full(n, inflate_body)
    smooth = np.full(n, 3.0)
    neck_z = ctx.L["neck"].z
    skin_z = neck_z + 0.03 * ctx.s + 0.012 * np.clip(V[:, 1] / 0.06, -1, 1)
    for i in range(n):
        z = V[i, 2]
        if z < boot_top - 0.035:
            labels[i] = "DELETE"
            continue
        if head[i] and z > skin_z[i]:
            labels[i] = "M_Skin" if head_skin else suit
            inflate[i] = 0.0
            smooth[i] = 0
            continue
        if hands[i] or (fore[i] and t[i] > 0.97):
            labels[i] = glove
            inflate[i] = 0.002
            smooth[i] = 0
            continue
        if fore[i] or upper_arm[i]:
            inflate[i] = inflate_body * 0.85
            continue
        if thigh[i] or z < ctx.crotch:
            bl = 0.007 * C.smoothstep(boot_top + 0.08, boot_top, z)
            inflate[i] = inflate_body + bl
            continue
        smooth[i] = 6 if z < ctx.crotch + 0.06 else 4
    return labels, inflate, smooth


def _skull_rings(ctx, z_rim, offset, n=32):
    """Rings following the skull from z_rim (per angle) up to the crown, plus a top point."""
    H = ctx.H
    headv = ctx.V[ctx.bone_mask("Head")]
    c = headv[np.abs(headv[:, 2] - (H - 0.08 * ctx.s)) < 0.01][:, :2].mean(axis=0)
    zmin = float(np.min(z_rim))
    rings = []
    ang = None
    for k in np.linspace(0.0, 1.0, 10)[:-1]:
        z = C.lerp(zmin, H - 0.012, k)
        sl = headv[np.abs(headv[:, 2] - z) < 0.008]
        ang, r = O.polar_radii(sl, c, n, smooth=3)
        zz = np.asarray(z_rim) * (1 - k) + (H - 0.012) * k
        rings.append(O.ring_points(c, ang, r + offset, zz + offset * 0.35 * k))
    top = Vector((c[0], c[1], H + offset * 0.8))
    return c, ang, rings, top


def tech_helmet(ctx):
    """Gunner/technician helmet (style bible 7.3): black gloss rounded dome, flat 40 mm brim
    all round sloped 15 degrees down, smoked full-face visor to the chin, two raised
    ridges front to back 30 mm apart, a small white unit mark on the left side."""
    ez = ctx.eyes[0].z
    s = ctx.s
    n = 36
    ang = -math.pi + (np.arange(n) + 0.5) * 2 * math.pi / n
    back = np.clip(np.sin(ang), 0, 1)
    z_rim = ez + 0.045 * s - back * 0.03 * s
    c, ang, rings, top = _skull_rings(ctx, z_rim, 0.030 * s, n)
    cen = Vector((c[0], c[1], 0))
    rim = rings[0]
    dirs = [Vector((p.x - c[0], p.y - c[1], 0)) for p in rim]
    brim_r = 0.18 * s
    slope = math.tan(math.radians(15))
    brim_top, brim_out, brim_bot = [], [], []
    for p, d in zip(rim, dirs, strict=True):
        u = d.normalized()
        w = max(0.02, brim_r - d.length)
        o = cen + u * (d.length + w) + Vector((0, 0, p.z - w * slope))
        brim_top.append(o + Vector((0, 0, 0.0025)))
        brim_out.append(o - Vector((0, 0, 0.0025)))
        brim_bot.append(Vector((p.x, p.y, p.z - 0.006)) + u * 0.002)
    bm = bmesh.new()
    vs = O.tube(bm, [brim_bot, brim_out, brim_top] + rings, mat=0)
    tv = bm.verts.new(top)
    last = vs[-1]
    for i in range(n):
        bm.faces.new((last[i], last[(i + 1) % n], tv))
    # smoked full-face visor, from under the brim to the chin
    face = ctx.V[ctx.bone_mask("Head") & (np.abs(ctx.V[:, 2] - (ez - 0.03)) < 0.03)]
    vc = face[:, :2].mean(axis=0)
    va, vr = O.polar_radii(face, vc, 48, smooth=4)
    front = sorted(
        (i for i in range(48) if abs(va[i] + math.pi / 2) < math.radians(72)), key=lambda i: va[i]
    )
    rows = []
    for dz, dr in ((0.040, 0.030), (0.0, 0.034), (-0.05, 0.032), (-0.10, 0.024), (-0.125, 0.012)):
        rows.append(
            [
                Vector(
                    (
                        vc[0] + (vr[i] + dr * s) * math.cos(va[i]),
                        vc[1] + (vr[i] + dr * s) * math.sin(va[i]),
                        ez + dz * s,
                    )
                )
                for i in front
            ]
        )
    vv = [[bm.verts.new(p) for p in row] for row in rows]
    for a_, b_ in zip(vv[:-1], vv[1:], strict=True):
        for j in range(len(front) - 1):
            f = bm.faces.new((b_[j], b_[j + 1], a_[j + 1], a_[j]))
            f.material_index = 1
    # two raised ridges along the dome, front to back
    for sx in (-0.015 * s, 0.015 * s):
        path = []
        for ring in rings[1:] + [[top]]:
            pts = [p for p in ring if abs(p.x - c[0] - sx) < 0.03] or ring
            fr = min(pts, key=lambda p: p.y)
            bk = max(pts, key=lambda p: p.y)
            path.append((fr, bk))
        line = [p[0] for p in path] + [p[1] for p in reversed(path)]
        line = [Vector((c[0] + sx, p.y, p.z + 0.003)) for p in line]
        rr = []
        for i, p in enumerate(line):
            d = (line[min(i + 1, len(line) - 1)] - line[max(i - 1, 0)]).normalized()
            nrm = Vector((0, -d.z, d.y))
            if nrm.z < 0:
                nrm = -nrm
            rr.append(
                [
                    p + Vector((-0.003, 0, 0)),
                    p + nrm * 0.004 + Vector((-0.002, 0, 0)),
                    p + nrm * 0.004 + Vector((0.002, 0, 0)),
                    p + Vector((0.003, 0, 0)),
                ]
            )
        rv = [[bm.verts.new(q) for q in r] for r in rr]
        for a_, b_ in zip(rv[:-1], rv[1:], strict=True):
            for j in range(3):
                bm.faces.new((a_[j], a_[j + 1], b_[j + 1], b_[j]))
    # white unit mark on the left side
    side_pt = max(rings[3], key=lambda p: p.x)
    O.box(
        bm,
        side_pt + Vector((0.002, 0.0, 0.0)),
        Vector((0, 1, 0)),
        Vector((0, 0, 1)),
        Vector((1, 0, 0)),
        (0.030 * s, 0.012 * s, 0.003),
        mat=2,
    )
    ob = O.new_obj("Helmet", bm, ["M_Helmet", "M_Visor", "M_Mark"])
    ctx.rigid(ob, "Head")
    return ob


def chest_box(ctx, garment):
    bvh = BVHTree.FromObject(garment, bpy.context.evaluated_depsgraph_get())
    z = 0.715 * ctx.H
    hit, _n, _i, _d = bvh.ray_cast(Vector((0.0, -1.0, z)), Vector((0, 1, 0)))
    nz = Vector((0, -1, 0))
    up = Vector((0, 0, 1))
    side = Vector((1, 0, 0))
    bm = bmesh.new()
    s = ctx.s
    w, h, d = 0.15 * s, 0.10 * s, 0.035
    center = hit + nz * (d / 2 - 0.004)
    O.box(bm, center, side, up, -nz, (w, h, d), mat=0)
    front = center + nz * (d / 2)
    for k, x in enumerate((-0.045, -0.02, 0.005)):
        O.box(
            bm,
            front + side * x * s + up * 0.025 * s,
            side,
            up,
            -nz,
            (0.012 * s, 0.008 * s, 0.004),
            mat=2 if k < 2 else 1,
        )
    for row in (-0.012, -0.03):
        for x in (-0.04, -0.012, 0.016, 0.044):
            O.box(
                bm,
                front + side * x * s + up * row * s,
                side,
                up,
                -nz,
                (0.018 * s, 0.011 * s, 0.005),
                mat=1,
            )
    ob = O.new_obj("ChestBox", bm, ["M_ChestBox", "M_Trim", "M_Glow"])
    for p in ob.data.polygons:
        p.use_smooth = False
    ctx.rigid(ob, "Chest")
    return ob


def build_technician(ctx):
    s = ctx.s
    boot_top = 0.30 * s
    belt_z = 0.585 * ctx.H
    neck_z = ctx.L["neck"].z
    garment = O.garment_body(ctx, lambda c: classify_suit(c, boot_top), name="Garment")
    O.decimate(garment, 8000 / C.tri_count(garment))
    parts = [garment]
    parts.append(O.boots(ctx, boot_top, flare=0.004, inflate=0.008))
    parts.append(O.belt(ctx, belt_z, height=0.05, buckle=True, buckle_mat="M_ChestBox"))
    parts.append(O.collar(ctx, neck_z - 0.004, neck_z + 0.03 * s, out=0.009, piping=None))
    parts.append(O.eyes(ctx))
    parts.append(chest_box(ctx, garment))
    parts.append(tech_helmet(ctx))
    return [O.finish(ctx, parts, "Body")]


# ------------------------------------------------------------------------ trooper


def shell_from_region(
    ctx, vmask, gap: float, thick: float, name: str, mat="M_Armor", smooth_edges=4
):
    """Armour shell: body faces inside `vmask`, offset outwards, given depth and bevels."""
    bm = bmesh.new()
    bm.from_mesh(ctx.naked.data)
    bm.verts.ensure_lookup_table()
    dead = [f for f in bm.faces if not all(vmask[v.index] for v in f.verts)]
    bmesh.ops.delete(bm, geom=dead, context="FACES")
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    if not bm.faces:
        bm.free()
        return None
    bm.normal_update()
    for v in bm.verts:
        v.co += v.normal * gap
    for _ in range(smooth_edges):
        edge_v = [v for v in bm.verts if v.is_boundary]
        bmesh.ops.smooth_vert(
            bm, verts=edge_v, factor=0.5, use_axis_x=True, use_axis_y=True, use_axis_z=True
        )
    for _ in range(2):
        bmesh.ops.smooth_laplacian_vert(
            bm,
            verts=bm.verts[:],
            lambda_factor=0.5,
            lambda_border=0.0,
            use_x=True,
            use_y=True,
            use_z=True,
            preserve_volume=False,
        )
    ob = O.new_obj(name, bm, [mat])
    m = ob.modifiers.new("solid", "SOLIDIFY")
    m.thickness = thick
    m.offset = 1.0
    m.use_rim = True
    m.use_even_offset = True
    O.apply_mod(ob, m)
    m = ob.modifiers.new("bev", "BEVEL")
    m.width = 0.0022
    m.segments = 1
    m.limit_method = "ANGLE"
    m.angle_limit = math.radians(50)
    O.apply_mod(ob, m)
    return ob


def trooper_helmet(ctx):
    """Marine helmet (style bible 7.4): smooth ovoid shell, 35 mm smoked visor band
    wrapping 180 degrees at eye level, vertical chin ridge with two grille slots."""
    s = ctx.s
    ez = ctx.eyes[0].z
    ey = ctx.eyes[0].y
    neck_z = ctx.L["neck"].z
    bm = bmesh.new()
    bm.from_mesh(ctx.naked.data)
    bm.verts.ensure_lookup_table()
    hm = ctx.bone_mask("Head") | (ctx.bone_mask("Neck") & (ctx.V[:, 2] > neck_z + 0.045 * s))
    dead = [f for f in bm.faces if not all(hm[v.index] for v in f.verts)]
    bmesh.ops.delete(bm, geom=dead, context="FACES")
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    bmesh.ops.holes_fill(bm, edges=bm.edges[:], sides=0)
    bm.normal_update()
    for v in bm.verts:
        v.co += v.normal * 0.03 * s
    chin = Vector((0.0, ey - 0.045 * s, ez - 0.085 * s))
    bmesh.ops.create_cube(
        bm,
        size=1.0,
        matrix=Matrix.Translation(chin) @ Matrix.Diagonal((0.034 * s, 0.05 * s, 0.075 * s, 1.0)),
    )
    ob = O.new_obj("Helmet", bm, ["M_Armor"])
    O.remesh(ob, 0.0055 * s, smooth_iter=16)
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    zmin = min(v.co.z for v in bm.verts)
    cx = sum((v.co.x for v in bm.verts), 0.0) / len(bm.verts)
    cy = sum((v.co.y for v in bm.verts), 0.0) / len(bm.verts)
    for v in bm.verts:
        k = C.smoothstep(zmin + 0.05 * s, zmin, v.co.z)
        d = Vector((v.co.x - cx, v.co.y - cy, 0))
        if d.length > 1e-6:
            v.co += d.normalized() * 0.010 * k * s
    bm.to_mesh(ob.data)
    bm.free()
    O.decimate(ob, 1700 / C.tri_count(ob))
    bvh = BVHTree.FromObject(ob, bpy.context.evaluated_depsgraph_get())
    bm = bmesh.new()
    rows = []
    for dz in (-0.0175, 0.0175):
        row = []
        for a in np.linspace(-math.radians(90), math.radians(90), 21):
            d = Vector((math.sin(a), -math.cos(a), 0.0))
            o = Vector((0.0, ey + 0.07 * s, ez + dz * s + 0.004)) + d * 0.5
            hit = bvh.ray_cast(o, -d)
            if hit[0] is not None:
                row.append(hit[0] + hit[1] * 0.0018)
        rows.append(row)
    k = min(len(rows[0]), len(rows[1]))
    vv = [[bm.verts.new(p) for p in row[:k]] for row in rows]
    for j in range(k - 1):
        bm.faces.new((vv[0][j], vv[0][j + 1], vv[1][j + 1], vv[1][j]))
    for dz in (-0.07, -0.088):
        o = Vector((0.0, -0.6, ez + dz * s))
        hit = bvh.ray_cast(o, Vector((0, 1, 0)))
        if hit[0] is not None:
            nn = hit[1]
            up = (Vector((0, 0, 1)) - nn * nn.z).normalized()
            O.box(
                bm, hit[0], up.cross(nn).normalized(), up, nn, (0.022 * s, 0.005 * s, 0.004), mat=0
            )
    visor = O.new_obj("Visor", bm, ["M_Visor"])
    for p in visor.data.polygons:
        p.use_smooth = False
    ctx.rigid(ob, "Head")
    ctx.rigid(visor, "Head")
    return [ob, visor]


def back_pack(ctx):
    s = ctx.s
    z = 0.745 * ctx.H
    back = ctx.V[
        ctx.bone_mask("Chest", "Spine")
        & (np.abs(ctx.V[:, 2] - z) < 0.01)
        & (np.abs(ctx.V[:, 0]) < 0.08)
    ]
    y = float(back[:, 1].max()) + 0.022 * s + 0.006 + 0.04
    bm = bmesh.new()
    O.box(
        bm,
        Vector((0.0, y, z)),
        Vector((1, 0, 0)),
        Vector((0, 0, 1)),
        Vector((0, 1, 0)),
        (0.30 * s, 0.20 * s, 0.08),
        mat=0,
    )
    ob = O.new_obj("Pack", bm, ["M_Armor"])
    m = ob.modifiers.new("bev", "BEVEL")
    m.width = 0.008
    m.segments = 2
    O.apply_mod(ob, m)
    ctx.rigid(ob, "Chest")
    return ob


def pouches(ctx, belt_z, out):
    s = ctx.s
    torso = ctx.V[
        (np.abs(ctx.V[:, 2] - belt_z) < 0.02) & (np.abs(ctx.V[:, 0]) < 0.25) & ~O._limbs(ctx)[0]
    ]
    c = torso[:, :2].mean(axis=0)
    ang, r = O.polar_radii(torso, c, 36, smooth=3)
    bm = bmesh.new()
    for a in (-math.pi / 2 - 0.55, -math.pi / 2 + 0.55, math.pi / 2 - 0.5, math.pi / 2 + 0.5):
        i = int(np.argmin(np.abs(((ang - a) + math.pi) % (2 * math.pi) - math.pi)))
        d = Vector((math.cos(ang[i]), math.sin(ang[i]), 0))
        p = Vector((c[0], c[1], belt_z - 0.006)) + d * (r[i] + out + 0.02)
        O.box(
            bm,
            p,
            d.cross(Vector((0, 0, 1))).normalized(),
            Vector((0, 0, 1)),
            d,
            (0.08 * s, 0.06 * s, 0.04),
            mat=0,
        )
    ob = O.new_obj("Pouches", bm, ["M_Belt"])
    m = ob.modifiers.new("bev", "BEVEL")
    m.width = 0.004
    m.segments = 1
    O.apply_mod(ob, m)
    ctx.transfer(ob)
    return ob


def build_trooper(ctx):
    s = ctx.s
    V, N = ctx.V, ctx.N
    t = ctx.tparam
    boot_top = 0.24 * s
    belt_z = 0.575 * ctx.H
    neck_z = ctx.L["neck"].z
    garment = O.garment_body(
        ctx,
        lambda c: classify_suit(
            c, boot_top, suit="M_Undersuit", head_skin=False, inflate_body=0.004
        ),
        name="Garment",
    )
    O.decimate(garment, 5200 / C.tri_count(garment))
    parts = [garment]
    z = V[:, 2]
    torso = ctx.bone_mask("Spine", "Chest", "Shoulder_L", "Shoulder_R", "Hips")
    narrow = np.abs(V[:, 0]) < 0.17 * s
    chest = torso & (z > 0.665 * ctx.H) & (z < neck_z - 0.005) & (N[:, 1] < 0.05) & narrow
    backp = torso & (z > 0.64 * ctx.H) & (z < neck_z - 0.01) & (N[:, 1] > 0.05) & narrow
    abdomen = (
        torso
        & (z > belt_z + 0.04 * s)
        & (z < 0.65 * ctx.H)
        & (N[:, 1] < -0.15)
        & (np.abs(V[:, 0]) < 0.12 * s)
    )
    ua = ctx.bone_mask("UpperArm_L")
    pauldron = (ua & (t < 0.38)) | (ctx.bone_mask("Shoulder_L") & (V[:, 0] > 0.15 * s))
    band = ua & (t > 0.50) & (t < 0.62)
    fa = ctx.bone_mask("ForeArm_L", "ForeArm_R")
    ul = ctx.bone_mask("UpperLeg_L", "UpperLeg_R")
    ll = ctx.bone_mask("LowerLeg_L", "LowerLeg_R")
    regions = [
        ("ChestPlate", chest, 0.022, 0.006, "M_Armor"),
        ("BackPlate", backp, 0.02, 0.006, "M_Armor"),
        ("Abdomen", abdomen, 0.016, 0.005, "M_Armor"),
        ("Pauldron", pauldron, 0.024, 0.006, "M_Armor"),
        ("UnitBand", band, 0.006, 0.003, "M_Accent"),
        ("BracerF", fa & (t > 0.18) & (t < 0.82), 0.012, 0.004, "M_Armor"),
        ("Thighs", ul & (t > 0.18) & (t < 0.78) & (N[:, 1] < 0.35), 0.014, 0.005, "M_Armor"),
        (
            "Shins",
            ll & (t > 0.12) & (t < 0.72) & (N[:, 1] < 0.25) & (z > boot_top + 0.01),
            0.012,
            0.005,
            "M_Armor",
        ),
    ]
    for name, mask, gap, thick, mat in regions:
        sh = shell_from_region(ctx, mask, gap * s, thick, name, mat=mat)
        if sh is None:
            continue
        O.decimate(sh, min(1.0, 650 / max(1, C.tri_count(sh))))
        ctx.transfer(sh)
        parts.append(sh)
    parts.append(back_pack(ctx))
    parts.append(O.boots(ctx, boot_top, flare=0.008, inflate=0.012, mat="M_Armor"))
    parts.append(
        O.belt(ctx, belt_z, height=0.05, out=0.022, buckle=True, mat="M_Belt", buckle_mat="M_Armor")
    )
    parts.append(pouches(ctx, belt_z, 0.022))
    parts.extend(trooper_helmet(ctx))
    parts.append(
        O.collar(ctx, neck_z - 0.006, neck_z + 0.03 * s, out=0.012, mat="M_Undersuit", piping=None)
    )
    return [O.finish(ctx, parts, "Body")]
