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

from characters import body as B
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
    ctx.hi = {"Garment": O.keep_hi(garment, "Hi_Technician")}
    ctx.look = {"belt_z": belt_z, "boot_top": boot_top, "neck_z": neck_z, "female": False}
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


# ------------------------------------------------------------------ armour plates
#
# Every plate is a clean parametric sheet fitted over the body: a grid in the plate's
# own coordinates (around a limb axis, a dome over a joint, or a height field over the
# torso), smoothed into a hard-shell envelope that never touches the body, then given
# thickness and a bevelled rim. Each plate rides one bone rigidly, as a hard shell does.


def _region_bvh(ctx, bones):
    """BVH over the naked-body faces that touch vertices dominated by `bones`."""
    mask = ctx.bone_mask(*bones)
    bm = bmesh.new()
    bm.from_mesh(ctx.naked.data)
    bm.verts.ensure_lookup_table()
    dead = [f for f in bm.faces if not any(mask[v.index] for v in f.verts)]
    bmesh.ops.delete(bm, geom=dead, context="FACES")
    bvh = BVHTree.FromBMesh(bm)
    bm.free()
    return bvh


def _fill_nan(R):
    R = np.array(R, dtype=float)
    if np.isnan(R).all():
        raise RuntimeError("armour: no body surface under the plate")
    for _ in range(64):
        m = np.isnan(R)
        if not m.any():
            break
        P = np.pad(R, 1, mode="edge")
        nb = np.stack([P[:-2, 1:-1], P[2:, 1:-1], P[1:-1, :-2], P[1:-1, 2:]])
        cnt = (~np.isnan(nb)).sum(axis=0)
        tot = np.nansum(nb, axis=0)
        ok = m & (cnt > 0)
        R[ok] = tot[ok] / cnt[ok]
    return R


def _grid_filter(R, closed, op, passes):
    """max / mean filter over a (rows x cols) grid; cols wrap when closed."""
    for _ in range(passes):
        if closed:
            P = np.concatenate([R[:, -1:], R, R[:, :1]], axis=1)
            P = np.pad(P, ((1, 1), (0, 0)), mode="edge")
        else:
            P = np.pad(R, 1, mode="edge")
        c, up, dn = P[1:-1, 1:-1], P[:-2, 1:-1], P[2:, 1:-1]
        lf, rt = P[1:-1, :-2], P[1:-1, 2:]
        if op == "max":
            R = np.maximum.reduce([c, up, dn, lf, rt])
        else:
            R = (4 * c + up + dn + lf + rt) / 8.0
    return R


def _sheet(name, rows, closed, outward, mat, chamfer=True):
    """Quad sheet through `rows` (lists of Vectors); faces wound to point `outward(p)`."""
    bm = bmesh.new()
    if chamfer and not closed and len(rows) > 2 and len(rows[0]) > 2:
        # 45 degree corner cuts (the ship's shape grammar), never square corners
        for i, j, di, dj in ((0, 0, 1, 1), (0, -1, 1, -1), (-1, 0, -1, 1), (-1, -1, -1, -1)):
            p = rows[i][j]
            rows[i][j] = p * 0.3 + (rows[i + di][j] + rows[i][j + dj]) * 0.35
    vs = [[bm.verts.new(p) for p in row] for row in rows]
    n = len(rows[0])
    for a, b in zip(vs[:-1], vs[1:], strict=True):
        for j in range(n if closed else n - 1):
            k = (j + 1) % n
            bm.faces.new((a[j], a[k], b[k], b[j]))
    bm.normal_update()
    score = sum(f.normal.dot(outward(f.calc_center_median())) for f in bm.faces)
    if score < 0:
        bmesh.ops.reverse_faces(bm, faces=bm.faces[:])
    ob = C.mesh_object(name, bm)
    ob.data.materials.append(bpy.data.materials[mat])
    return ob


def _harden(ob, thick, bevel=0.0028, segments=2):
    """Thickness towards the body, a bevelled rim, crisp shading on the rim."""
    m = ob.modifiers.new("solid", "SOLIDIFY")
    m.thickness = thick
    m.offset = -1.0
    m.use_rim = True
    m.use_even_offset = True
    O.apply_mod(ob, m)
    m = ob.modifiers.new("bev", "BEVEL")
    m.width = min(bevel, thick * 0.45)
    m.segments = segments
    m.limit_method = "ANGLE"
    m.angle_limit = math.radians(40)
    O.apply_mod(ob, m)
    C.set_active(ob)
    bpy.ops.object.shade_smooth_by_angle(angle=math.radians(38))
    return ob


def _limb_frame(ctx, bone):
    h = ctx.rig.head(bone)
    tl = ctx.rig.tail(bone)
    d = tl - h
    dn = d.normalized()
    sx = 1.0 if (h.x + tl.x) >= 0 else -1.0
    fwd = Vector((0.0, -1.0, 0.0))
    e1 = (fwd - dn * fwd.dot(dn)).normalized()
    e2 = dn.cross(e1).normalized()
    if e2.x * sx < 0:
        e2 = -e2
    return h, d, e1, e2


def limb_shell(
    ctx,
    name,
    bone,
    t0,
    t1,
    th0,
    th1,
    nt,
    nth,
    gap,
    thick=0.005,
    flare=0.0,
    closed=False,
    mat="M_Armor",
    rigid=True,
    segments=1,
):
    """Shell around a limb bone: rows along the bone (t0..t1 of its length), columns
    around it (degrees from the front towards the outer side; closed = full ring)."""
    h, d, e1, e2 = _limb_frame(ctx, bone)
    bvh = _region_bvh(ctx, [bone])
    ts = np.linspace(t0, t1, nt)
    if closed:
        ths = np.linspace(0.0, 2 * math.pi, nth, endpoint=False)
    else:
        ths = np.radians(np.linspace(th0, th1, nth))
    U = [e1 * math.cos(a) + e2 * math.sin(a) for a in ths]
    A = [h + d * float(t) for t in ts]
    R = np.full((nt, nth), np.nan)
    for i, a in enumerate(A):
        for j, u in enumerate(U):
            hit = bvh.ray_cast(a, u, 0.25)
            if hit[0] is not None:
                R[i, j] = (hit[0] - a).length
    R = _fill_nan(R)
    R = _grid_filter(R, closed, "max", 1)
    R = _grid_filter(R, closed, "mean", 3)
    k = (ts - t0) / max(1e-6, t1 - t0)
    R = R + gap + flare * (k[:, None] ** 1.5)
    rows = [[A[i] + U[j] * float(R[i, j]) for j in range(nth)] for i in range(nt)]
    axis_pt = lambda p: h + d * ((p - h).dot(d) / d.length_squared)  # noqa: E731
    ob = _sheet(name, rows, closed, lambda p: p - axis_pt(p), mat)
    _harden(ob, thick, segments=segments)
    if rigid:
        ctx.rigid(ob, bone)
    return ob


def dome_plate(
    ctx,
    name,
    center,
    axis,
    radius,
    alpha_max,
    nphi,
    nalpha,
    bones,
    clear,
    flare=0.006,
    thick=0.005,
    mat="M_Armor",
):
    """Spherical-cap plate (a shoulder bell): apex on `axis`, rim at `alpha_max` degrees,
    a small flare at the rim, pushed out wherever the body would come through."""
    ax = axis.normalized()
    ref = Vector((0.0, -1.0, 0.0))
    b1 = (ref - ax * ref.dot(ax)).normalized()
    b2 = ax.cross(b1).normalized()
    bvh = _region_bvh(ctx, bones)
    alphas = np.radians(np.linspace(alpha_max / nalpha, alpha_max, nalpha))
    phis = np.linspace(0.0, 2 * math.pi, nphi, endpoint=False)
    dirs = [
        [ax * math.cos(a) + (b1 * math.cos(p) + b2 * math.sin(p)) * math.sin(a) for p in phis]
        for a in alphas
    ]
    R = np.full((nalpha, nphi), radius)
    for i in range(nalpha):
        for j in range(nphi):
            hit = bvh.ray_cast(center, dirs[i][j], 0.3)
            if hit[0] is not None:
                R[i, j] = max(radius, (hit[0] - center).length + clear)
    R = _grid_filter(R, True, "max", 1)
    R = _grid_filter(R, True, "mean", 2)
    R[-1] += flare
    apex_r = max(radius, float(R[0].mean()))
    bm = bmesh.new()
    apex = bm.verts.new(center + ax * apex_r)
    rings = [
        [bm.verts.new(center + dirs[i][j] * float(R[i, j])) for j in range(nphi)]
        for i in range(nalpha)
    ]
    for j in range(nphi):
        bm.faces.new((apex, rings[0][j], rings[0][(j + 1) % nphi]))
    for a, b in zip(rings[:-1], rings[1:], strict=True):
        for j in range(nphi):
            k = (j + 1) % nphi
            bm.faces.new((a[j], b[j], b[k], a[k]))
    bm.normal_update()
    if sum(f.normal.dot(f.calc_center_median() - center) for f in bm.faces) < 0:
        bmesh.ops.reverse_faces(bm, faces=bm.faces[:])
    ob = C.mesh_object(name, bm)
    ob.data.materials.append(bpy.data.materials[mat])
    _harden(ob, thick)
    return ob


def torso_plate(
    ctx, name, bvh, facing, zb, zt, hw, nu, nv, gap, thick=0.006, clear=0.009, mat="M_Armor"
):
    """Plate over the front (facing -1) or back (+1) of the torso: a height field along Y,
    rows fitted to a symmetric curve so the shell is smooth and free of anatomy.

    zb(u), zt(u): bottom and top edge heights over u in [-1, 1]; hw(v): half width
    over v in [0, 1]. Returns the object and a function (u, v) -> point on its face."""
    us = np.linspace(-1.0, 1.0, nu)
    vs = np.linspace(0.0, 1.0, nv)
    X = np.zeros((nv, nu))
    Z = np.zeros((nv, nu))
    Yb = np.full((nv, nu), np.nan)
    for i, v in enumerate(vs):
        for j, u in enumerate(us):
            z = zb(u) + v * (zt(u) - zb(u))
            x = u * hw(v)
            X[i, j], Z[i, j] = x, z
            hit = bvh.ray_cast(Vector((x, facing * 1.0, z)), Vector((0.0, -facing, 0.0)), 2.0)
            # only the near (outward-facing) surface counts, never the far side
            if hit[0] is not None and hit[1].y * facing > 0.0:
                Yb[i, j] = hit[0].y
    Yb = _fill_nan(Yb)
    E = facing * Yb  # outwards distance of the body
    Env = _grid_filter(E, False, "max", 1)
    M = np.stack([np.ones_like(us), us**2, us**4], axis=1)
    for i in range(nv):
        coef, *_ = np.linalg.lstsq(M, Env[i], rcond=None)
        Env[i] = 0.7 * (M @ coef) + 0.3 * Env[i]
    Env = _grid_filter(Env, False, "mean", 2)
    Ep = np.maximum(Env + gap, E + clear + thick)
    Ep = np.maximum(_grid_filter(Ep, False, "mean", 2), E + clear + thick * 0.5)
    Y = facing * Ep
    rows = [[Vector((X[i, j], Y[i, j], Z[i, j])) for j in range(nu)] for i in range(nv)]
    ob = _sheet(name, rows, False, lambda p: Vector((0.0, facing, 0.0)), mat)
    _harden(ob, thick)

    def surf(u, v):
        fj = (u + 1.0) / 2.0 * (nu - 1)
        fi = v * (nv - 1)
        j0 = min(int(fj), nu - 2)
        i0 = min(int(fi), nv - 2)
        a, b = fj - j0, fi - i0

        def lerp2(G):
            return (G[i0, j0] * (1 - a) + G[i0, j0 + 1] * a) * (1 - b) + (
                G[i0 + 1, j0] * (1 - a) + G[i0 + 1, j0 + 1] * a
            ) * b

        return Vector((lerp2(X), lerp2(Y), lerp2(Z)))

    return ob, surf


def ribs(
    name, surf, facing, levels, u0=-0.74, u1=0.74, n=13, height=0.0045, width=0.009, mat="M_Armor"
):
    """Raised horizontal ribs following a plate face (trapezoid section, capped ends)."""
    bm = bmesh.new()
    out = Vector((0.0, facing, 0.0))
    up = Vector((0.0, 0.0, 1.0))
    sec = [(-0.5, -0.001), (-0.32, height), (0.32, height), (0.5, -0.001)]
    for v in levels:
        rows = []
        for u in np.linspace(u0, u1, n):
            p = surf(float(u), v)
            rows.append([bm.verts.new(p + up * (a * width) + out * h) for a, h in sec])
        for r0, r1 in zip(rows[:-1], rows[1:], strict=True):
            for k in range(3):
                bm.faces.new((r0[k], r0[k + 1], r1[k + 1], r1[k]))
        bm.faces.new(rows[0])
        bm.faces.new(list(reversed(rows[-1])))
    bm.normal_update()
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    ob = C.mesh_object(name, bm)
    ob.data.materials.append(bpy.data.materials[mat])
    C.set_active(ob)
    bpy.ops.object.shade_smooth_by_angle(angle=math.radians(38))
    return ob


def back_pack(ctx, y_back: float, z: float):
    s = ctx.s
    bm = bmesh.new()
    d = 0.08
    O.box(
        bm,
        Vector((0.0, y_back + d / 2 + 0.002, z)),
        Vector((1, 0, 0)),
        Vector((0, 0, 1)),
        Vector((0, 1, 0)),
        (0.30 * s, 0.20 * s, d),
        mat=0,
    )
    ob = O.new_obj("Pack", bm, ["M_Armor"])
    m = ob.modifiers.new("bev", "BEVEL")
    m.width = 0.008
    m.segments = 2
    O.apply_mod(ob, m)
    C.set_active(ob)
    bpy.ops.object.shade_smooth_by_angle(angle=math.radians(38))
    ctx.rigid(ob, "Chest")
    return ob


def pouches(ctx, belt_z, out, src):
    """Six small utility pouches on the belt (bevelled boxes, graphite)."""
    s = ctx.s
    torso = src[(np.abs(src[:, 2] - belt_z) < 0.02) & (np.abs(src[:, 0]) < 0.25)]
    c = torso[:, :2].mean(axis=0)
    ang, r = O.polar_radii(torso, c, 36, smooth=3)
    bm = bmesh.new()
    front = -math.pi / 2
    for a, w in (
        (front - 0.48, 0.056),
        (front + 0.48, 0.056),
        (front - 0.98, 0.05),
        (front + 0.98, 0.05),
        (math.pi / 2 - 0.42, 0.06),
        (math.pi / 2 + 0.42, 0.06),
    ):
        i = int(np.argmin(np.abs(((ang - a) + math.pi) % (2 * math.pi) - math.pi)))
        d = Vector((math.cos(ang[i]), math.sin(ang[i]), 0))
        dep = 0.028
        p = Vector((c[0], c[1], belt_z - 0.004)) + d * (r[i] + out + dep / 2 - 0.004)
        O.box(
            bm,
            p,
            d.cross(Vector((0, 0, 1))).normalized(),
            Vector((0, 0, 1)),
            d,
            (w * s, 0.046 * s, dep),
            mat=0,
        )
    ob = O.new_obj("Pouches", bm, ["M_Belt"])
    m = ob.modifiers.new("bev", "BEVEL")
    m.width = 0.005
    m.segments = 1
    O.apply_mod(ob, m)
    C.set_active(ob)
    bpy.ops.object.shade_smooth_by_angle(angle=math.radians(38))
    ctx.transfer(ob)
    return ob


def build_trooper(ctx):
    s = ctx.s
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
    ctx.hi = {"Garment": O.keep_hi(garment, "Hi_Trooper")}
    ctx.look = {"belt_z": belt_z, "boot_top": boot_top, "neck_z": neck_z, "female": False}
    O.decimate(garment, 4000 / C.tri_count(garment))
    parts = [garment]
    torso_bvh = _region_bvh(ctx, ["Spine", "Chest", "Hips", "Neck", "Shoulder_L", "Shoulder_R"])
    # Chest plate: neckline scoop at the top, a shallow V at the bottom, three ribs.
    chest_b = 0.668 * ctx.H
    chest, chest_surf = torso_plate(
        ctx,
        "ChestPlate",
        torso_bvh,
        -1.0,
        zb=lambda u: chest_b + 0.012 * s * abs(u) ** 1.5,
        zt=lambda u: neck_z - 0.052 * s + 0.036 * s * abs(u) ** 1.6,
        hw=lambda v: (0.116 + 0.012 * v) * s,
        nu=13,
        nv=9,
        gap=0.020,
        thick=0.006,
    )
    ctx.rigid(chest, "Chest")
    parts.append(chest)
    rb = ribs("ChestRibs", chest_surf, -1.0, (0.16, 0.30, 0.44))
    ctx.rigid(rb, "Chest")
    parts.append(rb)
    # Abdomen: two articulated bands between the chest plate and the belt.
    ab_lo, ab_hi = belt_z + 0.034 * s, chest_b - 0.012 * s
    mid = (ab_lo + ab_hi) / 2
    for k, (z0, z1) in enumerate(((ab_lo, mid - 0.006 * s), (mid + 0.006 * s, ab_hi))):
        band, _ = torso_plate(
            ctx,
            f"Abdomen{k}",
            torso_bvh,
            -1.0,
            zb=lambda u, z0=z0: z0 + 0.006 * s * abs(u) ** 2,
            zt=lambda u, z1=z1: z1 + 0.006 * s * abs(u) ** 2,
            hw=lambda v, k=k: (0.092 + 0.01 * k + 0.006 * v) * s,
            nu=11,
            nv=3,
            gap=0.016,
            thick=0.005,
        )
        ctx.rigid(band, "Spine")
        parts.append(band)
    # Back plate with the flat pack.
    back, back_surf = torso_plate(
        ctx,
        "BackPlate",
        torso_bvh,
        1.0,
        zb=lambda u: 0.640 * ctx.H + 0.01 * s * abs(u) ** 2,
        zt=lambda u: neck_z - 0.028 * s + 0.02 * s * abs(u) ** 1.6,
        hw=lambda v: (0.122 + 0.01 * v) * s,
        nu=11,
        nv=8,
        gap=0.020,
        thick=0.006,
    )
    ctx.rigid(back, "Chest")
    parts.append(back)
    pack_z = 0.745 * ctx.H
    v_pack = (pack_z - 0.640 * ctx.H) / (neck_z - 0.028 * s - 0.640 * ctx.H)
    parts.append(back_pack(ctx, back_surf(0.0, v_pack).y, pack_z))
    # Shoulder bells over both deltoids.
    for side in ("L", "R"):
        j = ctx.rig.head(f"UpperArm_{side}")
        h, d, e1, e2 = _limb_frame(ctx, f"UpperArm_{side}")
        axis = (e2 * 0.78 - d.normalized() * 0.42).normalized()
        bell = dome_plate(
            ctx,
            f"Bell{side}",
            j + d.normalized() * 0.03 * s,
            axis,
            0.076 * s,
            70,
            18,
            5,
            [f"UpperArm_{side}", f"Shoulder_{side}"],
            0.012,
            flare=0.007,
        )
        res = np.zeros((len(bell.data.vertices), len(ctx.bones)))
        res[:, ctx.bones.index(f"UpperArm_{side}")] = 0.7
        res[:, ctx.bones.index(f"Shoulder_{side}")] = 0.3
        O.set_weights(bell, ctx.bones, res)
        parts.append(bell)
    # Unit band (accent colour) round the left upper arm.
    parts.append(
        limb_shell(
            ctx,
            "UnitBand",
            "UpperArm_L",
            0.52,
            0.62,
            0,
            0,
            2,
            12,
            0.008,
            thick=0.003,
            closed=True,
            mat="M_Accent",
        )
    )
    for side in ("L", "R"):
        parts.append(
            limb_shell(
                ctx,
                f"Bracer{side}",
                f"ForeArm_{side}",
                0.2,
                0.84,
                -150,
                150,
                5,
                11,
                0.013,
                thick=0.005,
                flare=0.004,
            )
        )
        parts.append(
            limb_shell(
                ctx,
                f"Thigh{side}",
                f"UpperLeg_{side}",
                0.24,
                0.84,
                -50,
                120,
                6,
                11,
                0.012,
                thick=0.005,
            )
        )
        ll = f"LowerLeg_{side}"
        hz, tz = ctx.rig.head(ll).z, ctx.rig.tail(ll).z
        t_end = (boot_top + 0.006 - hz) / (tz - hz)
        parts.append(
            limb_shell(
                ctx,
                f"Shin{side}",
                ll,
                0.08,
                t_end,
                -118,
                118,
                6,
                12,
                0.016,
                thick=0.005,
                flare=0.003,
            )
        )
    parts.append(O.boots(ctx, boot_top, flare=0.008, inflate=0.012, mat="M_Armor"))
    gv = B.verts_np(garment)
    parts.append(
        O.belt(
            ctx,
            belt_z,
            height=0.05,
            out=0.018,
            buckle=True,
            mat="M_Belt",
            buckle_mat="M_Armor",
            pts=gv,
        )
    )
    parts.append(pouches(ctx, belt_z, 0.018, gv))
    parts.extend(trooper_helmet(ctx))
    parts.append(
        O.collar(ctx, neck_z - 0.006, neck_z + 0.03 * s, out=0.012, mat="M_Undersuit", piping=None)
    )
    return [O.finish(ctx, parts, "Body")]
