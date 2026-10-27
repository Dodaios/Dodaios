"""The Sovereign: the commander's default skin.

A hooded sovereign in a floor-length robe and a heavy open cloak, charcoal black
with gold piping, glowing amber eyes deep in the hood. Original design.

Pieces (all on the male skeleton):
- Garment: the base body as the inner robe (pale aged face and hands, bald scalp
  under the hood), legs kept slim inside the robe skirt.
- RobeSkirt: floor-length skirt from the waist with deep folds; follows the legs.
- Sleeves: bell sleeves from the elbow, gold cuff.
- Mantle: deep hood and shoulder capelet in one shell, gold rim.
- Cloak: open at the front, from the shoulders to the floor, gold front edges and
  hem. It hangs on six extra bones (Cloak_{L,C,R}{1,2}, children of Chest) that the
  game swings with a spring, so the cloak trails when the commander walks.
- Clasp, belt, boots, glowing eyes.

The extra bones live on the Sovereign's own copy of the skeleton: the shared clips
never animate them and the other characters never carry them.
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
from characters import paint as PT

# Materials of this skin (names are its own, so the rank tiers never repaint them).
O.MATERIALS.update(
    {
        # black velvet: a strong sheen gives the folds their highlights
        "M_SovRobe": ((0.014, 0.013, 0.016), 0.8, 0.0, {"sheen": 0.035}),
        "M_SovCloak": ((0.010, 0.009, 0.012), 0.62, 0.0, {"sheen": 0.05}),
        "M_SovLining": ((0.075, 0.008, 0.012), 0.48, 0.0, {"sheen": 0.06}),
        "M_SovTrim": ((0.66, 0.47, 0.17), 0.32, 1.0, {}),
        "M_SovEye": ((1.0, 0.52, 0.07), 0.4, 0.0, {"emit": 8.0}),
    }
)
PT.UNTEXTURED.add("M_SovEye")

CLOAK_COLUMNS = (("R", -1.0), ("C", 0.0), ("L", 1.0))
CLOAK_COLUMN_ANGLE = math.radians(98.0)
CLOAK_OPEN = math.radians(146.0)  # half the cloak's arc, measured from the back
EXTRA_BONES = [f"Cloak_{c}{k}" for c, _ in CLOAK_COLUMNS for k in (1, 2)]


def smoothstep(e0, e1, x):
    return C.smoothstep(e0, e1, x)


# --------------------------------------------------------------------- classifier


def gaunt(ctx: O.Ctx, p) -> float:
    """An old face: hollow cheeks and temples, a heavy brow, slack jowls (metres)."""
    e = ctx.eyes[0]
    ax, dz = abs(float(p[0])), float(p[2]) - e.z
    if float(p[1]) > e.y + 0.05:
        return 0.0

    def bump(cx, cz, sx, sz):
        return math.exp(-(((ax - cx) / sx) ** 2 + ((dz - cz) / sz) ** 2))

    return (
        -0.0055 * bump(0.046, -0.052, 0.017, 0.022)
        - 0.0035 * bump(0.066, 0.018, 0.012, 0.018)
        + 0.0028 * bump(0.03, 0.02, 0.022, 0.007)
        + 0.0022 * bump(0.042, -0.112, 0.016, 0.012)
    ) * ctx.s


def classify_sovereign(ctx: O.Ctx, boot_top: float, belt_z: float):
    V = ctx.V
    n = len(V)
    hands, fore, upper_arm, head, _thigh = O._limbs(ctx)
    t = ctx.tparam
    labels = ["M_SovRobe"] * n
    inflate = np.full(n, 0.007)
    smooth = np.full(n, 4.0)
    neck_z = ctx.L["neck"].z
    for i in range(n):
        z = V[i, 2]
        if z < boot_top - 0.03:
            labels[i] = "DELETE"
            continue
        if head[i] and z > neck_z + 0.03 * ctx.s:
            labels[i] = "M_Skin"
            inflate[i] = gaunt(ctx, V[i])
            smooth[i] = 0
            continue
        if hands[i] or (fore[i] and t[i] > 0.97):
            labels[i] = "M_Skin"
            inflate[i] = 0.0
            smooth[i] = 0
            continue
        if fore[i] or upper_arm[i]:
            inflate[i] = 0.006
            smooth[i] = 3
            continue
        if z < ctx.crotch:
            # legs inside the robe skirt: slim, so a stride never pushes them through it
            inflate[i] = -0.004
            smooth[i] = 6
            continue
        smooth[i] = 8
        inflate[i] = 0.008 if z > belt_z else 0.004
    return labels, inflate, smooth


# ------------------------------------------------------------------------ helpers


def grid(bm, rows, closed=False, mat_of=None):
    """Quads through rows of points (lists of Vectors, same length). Returns the verts."""
    vs = [[bm.verts.new(p) for p in row] for row in rows]
    n = len(rows[0])
    span = n if closed else n - 1
    for k in range(len(rows) - 1):
        a, b = vs[k], vs[k + 1]
        for j in range(span):
            j2 = (j + 1) % n
            f = bm.faces.new((a[j], a[j2], b[j2], b[j]))
            f.material_index = mat_of(k, j) if mat_of else 0
    return vs


def solidify(ob, thickness, offset=-1.0):
    m = ob.modifiers.new("solid", "SOLIDIFY")
    m.thickness = thickness
    m.offset = offset
    m.use_rim = True
    m.use_even_offset = False
    m.material_offset = 0
    m.material_offset_rim = 0
    O.apply_mod(ob, m)


def weights_from(ob, bones, fn):
    """Skin weights from `fn(co) -> dict bone -> weight` (top four kept, normalised)."""
    res = np.zeros((len(ob.data.vertices), len(bones)))
    idx = {b: k for k, b in enumerate(bones)}
    for v in ob.data.vertices:
        for b, w in fn(v.co).items():
            res[v.index, idx[b]] += w
    O.set_weights(ob, bones, res)


def transfer_rows(ctx: O.Ctx, ob) -> np.ndarray:
    """The naked body's barycentric weights at the nearest point, per vertex."""
    O.Ctx.transfer(ctx, ob)
    res = np.zeros((len(ob.data.vertices), len(ctx.bones)))
    gi = {vg.index: ctx.bones.index(vg.name) for vg in ob.vertex_groups}
    for v in ob.data.vertices:
        for g in v.groups:
            res[v.index, gi[g.group]] = g.weight
    return res


def torso_measure(ctx: O.Ctx, z: float, half=0.02, x_max=0.3):
    sel = (np.abs(ctx.V[:, 2] - z) < half) & (np.abs(ctx.V[:, 0]) < x_max)
    sel &= ~ctx.bone_mask("ForeArm_L", "ForeArm_R", "Hand_L", "Hand_R", "Fingers_L", "Fingers_R")
    return ctx.V[sel]


# ------------------------------------------------------------------------- pieces


def robe_skirt(ctx: O.Ctx, belt_z: float):
    """Floor-length skirt with deep folds; the hem clears the toes at the front."""
    s = ctx.s
    pelvis = ctx.bone_mask("Hips", "Spine") | (
        ctx.bone_mask("UpperLeg_L", "UpperLeg_R") & (ctx.V[:, 2] > ctx.crotch - 0.05)
    )
    Vg = ctx.V[pelvis] + ctx.N[pelvis] * 0.012
    c = Vg[:, :2].mean(axis=0)
    na = 48
    zs = [belt_z - 0.01]
    z_low = 0.03
    rows = 18
    for k in range(1, rows):
        u = k / (rows - 1)
        zs.append(belt_z - 0.01 - (belt_z - 0.01 - z_low) * u**0.9)
    rings = []
    prev = None
    for k, z in enumerate(zs):
        pts = Vg[np.abs(Vg[:, 2] - z) < 0.025]
        if len(pts) >= 24:
            ang, r = O.polar_radii(pts, c, na, smooth=4)
        elif prev is None:
            raise RuntimeError("robe skirt: no pelvis section at the waist")
        else:
            ang, r = prev
        prev = (ang, r)
        h = k / (len(zs) - 1)
        # flare, more to the sides and the back (room for the stride), deep folds below the knee
        fl = 0.14 * s * h**1.4
        folds = 0.028 * s * h**1.3 * (0.5 + 0.5 * np.sin(ang * 13 + 0.6)) ** 1.6
        rr = r + 0.014 + fl + folds
        # front clears the toes: the hem rises a little at the front (ang = -pi/2 is the front)
        front = np.clip(-np.sin(ang), 0, 1) ** 2
        zz = z + (0.035 * front + 0.006 * np.sin(ang * 13 + 0.6)) * h**2
        rings.append(
            [
                Vector((c[0] + rad * math.cos(a), c[1] + rad * math.sin(a), zr))
                for a, rad, zr in zip(ang, rr, zz, strict=True)
            ]
        )
    # a skirt never tucks in on the way down
    for k in range(1, len(rings)):
        for i, p in enumerate(rings[k]):
            q = rings[k - 1][i]
            dp = Vector((p.x - c[0], p.y - c[1], 0))
            dq = Vector((q.x - c[0], q.y - c[1], 0))
            if dp.length < dq.length + 0.001:
                dp = dp.normalized() * (dq.length + 0.001)
                p.x, p.y = c[0] + dp.x, c[1] + dp.y
    hem_in = [
        Vector((c[0] + (p.x - c[0]) * 0.965, c[1] + (p.y - c[1]) * 0.965, p.z + 0.012))
        for p in rings[-1]
    ]
    bm = bmesh.new()
    n_rows = len(rings) + 1
    grid(bm, rings + [hem_in], closed=True, mat_of=lambda k, j: 1 if k >= n_rows - 3 else 0)
    ob = O.new_obj("RobeSkirt", bm, ["M_SovRobe", "M_SovTrim"])
    # Skin: at the waist the body's own weights; below, a bell hung from the hips that
    # both thighs swing together (never one leg alone, which splits a robe into trousers).
    body = transfer_rows(ctx, ob)
    hi = ctx.bones.index("Hips")
    li = ctx.bones.index("UpperLeg_L")
    ri = ctx.bones.index("UpperLeg_R")
    z_waist = zs[0]
    res = np.zeros_like(body)
    for v in ob.data.vertices:
        co = v.co
        lam = smoothstep(z_waist - 0.03, ctx.crotch - 0.02, co.z)
        sx = C.clamp(co.x / (0.14 * s), -1.0, 1.0)
        legs = 0.5 * smoothstep(ctx.crotch, 0.3, co.z)
        row = np.zeros(len(ctx.bones))
        row[hi] = 1.0 - legs
        row[li] = legs * (0.5 + 0.35 * sx)
        row[ri] = legs * (0.5 - 0.35 * sx)
        res[v.index] = body[v.index] * (1 - lam) + row * lam
    O.set_weights(ob, ctx.bones, res)
    return ob


def sleeve(ctx: O.Ctx, side: str):
    """Bell sleeve from above the elbow to just past the wrist, gold cuff."""
    rig = ctx.rig
    e = Vector(rig.head(f"ForeArm_{side}"))
    w = Vector(rig.tail(f"ForeArm_{side}"))
    sh = Vector(rig.head(f"UpperArm_{side}"))
    d = (w - e).normalized()
    down = Vector((0, 0, -1))
    down = (down - d * down.dot(d)).normalized()
    x = d.cross(down).normalized()
    L = (w - e).length
    ts = [-0.22, -0.1, 0.05, 0.2, 0.36, 0.52, 0.68, 0.84, 0.96, 1.05, 1.1]
    na = 24
    rows = []
    for t in ts:
        if t < 0:
            # follow the upper arm back toward the shoulder
            base = e + (sh - e).normalized() * (-t * (sh - e).length * 0.8)
        else:
            base = e + d * (t * L)
        k = smoothstep(0.25, 1.1, t)
        r = (0.052 + 0.075 * k**1.4) * ctx.s
        if t < 0:
            r = 0.056 * ctx.s
        droop = 0.05 * k**1.6 * ctx.s
        ring = []
        for j in range(na):
            a = 2 * math.pi * j / na
            # the opening hangs: more cloth below the arm than above it
            sag = 1.0 + 0.25 * k * max(0.0, math.cos(a))
            fold = 1.0 + 0.06 * k * math.sin(a * 5 + 1.0)
            off = down * (droop + r * sag * fold * math.cos(a)) + x * (r * fold * math.sin(a))
            ring.append(base + off)
        rows.append(ring)
    bm = bmesh.new()
    nr = len(rows)
    grid(bm, rows, closed=True, mat_of=lambda k, j: 1 if k >= nr - 2 else 0)
    ob = O.new_obj(f"Sleeve_{side}", bm, ["M_SovRobe", "M_SovTrim"])
    solidify(ob, 0.006)
    # skin: the upper part follows the body, the bell rides the forearm
    rows_w = transfer_rows(ctx, ob)
    fi = ctx.bones.index(f"ForeArm_{side}")
    ui = ctx.bones.index(f"UpperArm_{side}")
    res = np.zeros_like(rows_w)
    for v in ob.data.vertices:
        t = (v.co - e).dot(d) / L
        lam = smoothstep(0.05, 0.4, t)
        lam_u = smoothstep(-0.05, -0.4, t)
        row = rows_w[v.index] * (1 - lam) * (1 - lam_u)
        row[fi] += lam
        row[ui] += lam_u * (1 - lam)
        res[v.index] = row
    O.set_weights(ob, ctx.bones, res)
    return ob


def core_bvh(ctx: O.Ctx):
    """The naked body without its arms (rest pose): what garments must stay outside of."""
    if getattr(ctx, "_core", None) is None:
        limbs = ("UpperArm", "ForeArm", "Hand", "Fingers", "Thumb")
        names = [f"{b}_{sd}" for b in limbs for sd in "LR"]
        arms = ctx.bone_mask(*names)
        bm = bmesh.new()
        bm.from_mesh(ctx.naked.data)
        bm.verts.ensure_lookup_table()
        dead = [f for f in bm.faces if any(arms[v.index] for v in f.verts)]
        bmesh.ops.delete(bm, geom=dead, context="FACES")
        bm.normal_update()
        ctx._core = BVHTree.FromBMesh(bm)
        ctx._core_bm = bm
    return ctx._core


def push_out(ctx: O.Ctx, ob, margin: float, z_min=-1.0, z_max=9.0):
    """Move every vertex closer than `margin` to the body (arms aside) out to `margin`."""
    bvh = core_bvh(ctx)
    for v in ob.data.vertices:
        if v.co.z < z_min or v.co.z > z_max:
            continue
        loc, nrm, _i, _d = bvh.find_nearest(v.co)
        if loc is None:
            continue
        d = (v.co - loc).dot(nrm)
        if d < margin:
            v.co += nrm * (margin - d)


def mantle(ctx: O.Ctx):
    """Deep cowl: a hood with a drooping point that falls over the shoulders, gold rim."""
    s = ctx.s
    ez = ctx.eyes[0].z
    head = torso_measure(ctx, ez, 0.01, 0.12)
    hcy = float(0.5 * (head[:, 1].min() + head[:, 1].max()))
    fd = float(hcy - head[:, 1].min())  # head centre to the face
    H = ctx.H
    neck_z = ctx.L["neck"].z
    sh = ctx.L["shoulder"]
    chest = torso_measure(ctx, sh.z - 0.08, 0.02, 0.2)
    ccy = float(0.5 * (chest[:, 1].min() + chest[:, 1].max()))
    # (z, rx, ry back, ry front, centre y, half-opening at the front (deg), side drop)
    spec = [
        (H + 0.085 * s, 0.012, 0.012, 0.012, hcy + 0.085, 0.0, 0.0),
        (H + 0.072 * s, 0.050, 0.055, 0.050, hcy + 0.055, 0.0, 0.0),
        (H + 0.048 * s, 0.100, 0.110, 0.105, hcy + 0.030, 0.0, 0.0),
        (H + 0.012 * s, 0.140, 0.150, 0.150, hcy + 0.012, 0.0, 0.0),
        (ez + 0.068 * s, 0.160, 0.164, fd + 0.098, hcy, 0.0, 0.0),
        (ez + 0.044 * s, 0.163, 0.167, fd + 0.098, hcy, 22.0, 0.0),
        (ez + 0.010 * s, 0.165, 0.170, fd + 0.088, hcy, 33.0, 0.0),
        (ez - 0.050 * s, 0.165, 0.170, fd + 0.070, hcy, 38.0, 0.0),
        (ez - 0.118 * s, 0.162, 0.167, fd + 0.048, hcy - 0.004, 36.0, 0.0),
        (neck_z + 0.000 * s, 0.190, 0.172, 0.165, 0.5 * (hcy + ccy), 30.0, 0.012),
        (neck_z - 0.040 * s, 0.245, 0.197, 0.178, ccy, 25.0, 0.030),
        (neck_z - 0.090 * s, 0.295, 0.217, 0.192, ccy, 21.0, 0.060),
        (neck_z - 0.150 * s, 0.326, 0.230, 0.200, ccy, 19.0, 0.090),
        (neck_z - 0.215 * s, 0.342, 0.238, 0.206, ccy, 18.0, 0.110),
        (neck_z - 0.262 * s, 0.350, 0.242, 0.209, ccy, 18.0, 0.118),
        (neck_z - 0.278 * s, 0.352, 0.243, 0.210, ccy, 18.0, 0.120),
    ]
    na = 48
    rows = []
    rim_rows = []
    nlow = len(spec)
    for k, (z, rx, ryb, ryf, cy, op, drop) in enumerate(spec):
        half = math.pi - math.radians(max(op, 0.4))
        g = C.clamp((k - 8) / (nlow - 9), 0, 1)
        ring = []
        for j in range(na + 1):
            a = -half + 2 * half * j / na  # 0 = back (+Y), +-pi = front (-Y)
            ry = ryb if math.cos(a) > 0 else ryf
            wave = math.sin(a * 9 + 0.4)
            # soft folds where the cowl lies on the shoulders and the back
            fold = 1.0 + 0.05 * g * (0.5 + 0.5 * wave) ** 1.5
            # the cloth falls over the shoulders: lower at the sides than front and back
            zz = z - drop * s * abs(math.sin(a)) ** 1.4 - 0.012 * g * wave
            # the hood's brow sags a little forward and down over the eyes
            if k in (4, 5):
                zz -= 0.012 * s * max(0.0, -math.cos(a)) ** 4
            px = rx * fold * math.sin(a) * s
            ring.append(Vector((px, cy + ry * fold * math.cos(a) * s, zz)))
        rows.append(ring)
        rim_rows.append(op > 1.0)
    nr = len(rows)

    def mat_of(k, j):
        if k >= nr - 2:
            return 1  # cowl hem
        if (j == 0 or j == na - 1) and (rim_rows[k] or rim_rows[k + 1]):
            return 1  # face rim and the front edges
        return 0

    bm = bmesh.new()
    grid(bm, rows, closed=False, mat_of=mat_of)
    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=0.004)
    ob = O.new_obj("Mantle", bm, ["M_SovCloak", "M_SovTrim"])
    sub = ob.modifiers.new("sub", "SUBSURF")
    sub.levels = 1
    O.apply_mod(ob, sub)
    push_out(ctx, ob, 0.022, z_min=neck_z - 0.35)
    # relax the bumps the shoulders pushed into the cowl, then clear the body again
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    low = [v for v in bm.verts if v.co.z < neck_z - 0.02]
    for _ in range(8):
        bmesh.ops.smooth_vert(bm, verts=low, factor=0.5, use_axis_x=True, use_axis_y=True,
                              use_axis_z=True)
    bm.to_mesh(ob.data)
    bm.free()
    push_out(ctx, ob, 0.016, z_min=neck_z - 0.35)
    solidify(ob, 0.012, offset=0.0)
    # skin: the hood rides the head, the cowl the chest and the collarbones
    hz0, hz1 = neck_z - 0.01, neck_z + 0.06 * s

    def w(co):
        lam = smoothstep(hz0, hz1, co.z)
        lat = C.clamp(abs(co.x) / (0.3 * s), 0, 1)
        side = "L" if co.x > 0 else "R"
        out = {"Head": lam * 0.8, "Neck": lam * 0.2}
        rest = 1.0 - lam
        # over the shoulder tip the cloth rides the upper arm, so the deltoid never
        # pushes through it when the arm swings
        arm = 0.45 * smoothstep(0.13 * s, 0.24 * s, abs(co.x))
        out["Chest"] = rest * (1.0 - arm) * (1.0 - 0.45 * lat)
        out[f"Shoulder_{side}"] = rest * (1.0 - arm) * 0.45 * lat
        out[f"UpperArm_{side}"] = rest * arm
        return out

    weights_from(ob, ctx.bones, w)
    return ob


def cloak(ctx: O.Ctx, belt_z: float):
    """Open cloak from under the cowl to the floor, on the six cloak bones."""
    s = ctx.s
    sh = ctx.L["shoulder"]
    neck_z = ctx.L["neck"].z
    chest = torso_measure(ctx, sh.z - 0.08, 0.02, 0.2)
    cy = float(0.5 * (chest[:, 1].min() + chest[:, 1].max()))
    back = float(chest[:, 1].max())
    z_top = neck_z - 0.13 * s
    z_hem = 0.006
    rows_n = 26
    na = 56
    rows = []
    for k in range(rows_n):
        u = k / (rows_n - 1)
        z = z_top - (z_top - z_hem) * u
        g = u**0.75
        rx = (0.275 + 0.12 * g) * s
        ryb = max(back - cy + 0.045, (0.19 + 0.17 * g) * s)
        ryf = (0.18 + 0.07 * g) * s
        half = CLOAK_OPEN - math.radians(6) * (1 - g)
        ring = []
        for j in range(na + 1):
            # inset edge columns make a crisp gold strip along the front edges
            if j == 0:
                a = -half
            elif j == na:
                a = half
            else:
                a = -half + 0.04 + (2 * half - 0.08) * (j - 1) / (na - 2)
            ry = ryb if math.cos(a) > 0 else ryf
            wave = math.sin(a * 12 + 0.9 + 0.6 * math.sin(a * 5))
            fold = 1.0 + (0.02 + 0.13 * g**1.1) * (0.5 + 0.5 * wave) ** 1.8
            # the top edge follows the shoulder slope, well inside the cowl
            zz = z - 0.07 * s * abs(math.sin(a)) ** 2 * (1.0 - u) ** 3
            if k == rows_n - 1:
                # the hem rises to the front edges and trails on the floor at the back
                zz = z_hem + 0.055 * (abs(a) / half) ** 3 + 0.008 * wave
            ring.append(Vector((rx * fold * math.sin(a), cy + ry * fold * math.cos(a), zz)))
        rows.append(ring)
    # a gold band just above the hem
    last = rows[-1]
    prev = rows[-2]
    band = [p.lerp(q, 0.3) for p, q in zip(last, prev, strict=True)]
    rows = rows[:-1] + [band, last]
    nr = len(rows)

    def mat_of(k, j):
        if k >= nr - 2:
            return 1
        if j == 0 or j == na - 1:
            return 1
        return 0

    bm = bmesh.new()
    grid(bm, rows, closed=False, mat_of=mat_of)
    ob = O.new_obj("Cloak", bm, ["M_SovCloak", "M_SovTrim"])
    push_out(ctx, ob, 0.03, z_min=0.5, z_max=z_top - 0.12)
    solidify(ob, 0.009, offset=0.0)
    # inner face gets the deep red lining
    _line_inside(ob, cy)
    return ob, cy, z_top, z_hem, back


def _line_inside(ob, cy):
    """Faces pointing inwards (toward the body axis) wear the lining."""
    me = ob.data
    mats = [m.name for m in me.materials]
    if "M_SovLining" not in mats:
        me.materials.append(bpy.data.materials["M_SovLining"])
    li = len(me.materials) - 1
    trim = mats.index("M_SovTrim")
    for p in me.polygons:
        if p.material_index == trim:
            continue
        c = p.center
        radial = Vector((c.x, c.y - cy, 0.0))
        if radial.length > 1e-6 and p.normal.dot(radial.normalized()) < -0.2:
            p.material_index = li


def add_cloak_bones(arm_ob, cy, z_top, z_hem, belt_z, s):
    """Six bones the cloak hangs on: three columns (right, centre, left) of two segments."""
    C.set_active(arm_ob)
    bpy.ops.object.mode_set(mode="EDIT")
    eb = arm_ob.data.edit_bones
    heads = {}
    for col, sx in CLOAK_COLUMNS:
        a = sx * CLOAK_COLUMN_ANGLE
        rx, ry = 0.3 * s, 0.22 * s
        x = rx * math.sin(a)
        y = cy + ry * math.cos(a)
        top = Vector((x * 0.85, y, z_top - 0.02))
        mid = Vector((x, y + 0.03, belt_z))
        low = Vector((x * 1.15, y + 0.07, z_hem + 0.05))
        b1 = eb.new(f"Cloak_{col}1")
        b1.head, b1.tail = top, mid
        b1.align_roll(Vector((0, -1, 0)))
        b1.parent = eb["Chest"]
        b2 = eb.new(f"Cloak_{col}2")
        b2.head, b2.tail = mid, low
        b2.align_roll(Vector((0, -1, 0)))
        b2.parent = b1
        b2.use_connect = True
        heads[col] = (top, mid, low)
    bpy.ops.object.mode_set(mode="OBJECT")
    for b in arm_ob.data.bones:
        b.use_deform = True
    return heads


def skin_cloak(ob, bones, sh_z, belt_z, s):
    top0, top1 = sh_z - 0.15, sh_z - 0.01
    ca = CLOAK_COLUMN_ANGLE

    def w(co):
        a = math.atan2(co.x, co.y)  # 0 = back, + = left
        lam_top = smoothstep(top0, top1, co.z)
        seg2 = smoothstep(belt_z + 0.1, belt_z - 0.12, co.z)
        out = {}
        side = "L" if a > 0 else "R"
        k = C.clamp(abs(a) / ca, 0, 1)
        cols = {"C": 1.0 - k, side: k}
        body = 1.0 - lam_top
        for col, cw in cols.items():
            if cw <= 0:
                continue
            out[f"Cloak_{col}1"] = out.get(f"Cloak_{col}1", 0) + body * cw * (1 - seg2)
            out[f"Cloak_{col}2"] = out.get(f"Cloak_{col}2", 0) + body * cw * seg2
        lat = C.clamp(abs(co.x) / (0.3 * s), 0, 1)
        out["Chest"] = lam_top * (1.0 - 0.45 * lat)
        out[f"Shoulder_{side}"] = lam_top * 0.45 * lat
        return out

    weights_from(ob, bones, w)


def clasp(ctx: O.Ctx, edge_ob, z: float):
    """Two gold discs on the cowl's front edges at the upper chest, joined by a chain."""
    s = ctx.s
    me = edge_ob.data
    pts = [v.co.copy() for v in me.vertices if abs(v.co.z - z) < 0.03]
    if not pts:
        return None
    left = max(pts, key=lambda p: (-p.y if p.x > 0 else -9))
    right = Vector((-left.x, left.y, left.z))
    bm = bmesh.new()
    for p in (left, right):
        m = Matrix.Translation(p + Vector((0, -0.012, 0))) @ Matrix.Rotation(math.pi / 2, 4, "X")
        bmesh.ops.create_cone(bm, cap_ends=True, segments=20, radius1=0.026 * s, radius2=0.022 * s,
                              depth=0.012, matrix=m)
        m2 = Matrix.Translation(p + Vector((0, -0.019, 0))) @ Matrix.Rotation(math.pi / 2, 4, "X")
        bmesh.ops.create_cone(bm, cap_ends=True, segments=6, radius1=0.011 * s, radius2=0.004 * s,
                              depth=0.008, matrix=m2)
    # the chain: a slight sag between the discs
    links = 9
    for i in range(links):
        u = (i + 0.5) / links
        x = right.x + (left.x - right.x) * u
        sag = 0.035 * s * math.sin(math.pi * u)
        p = Vector((x, left.y - 0.012 - 0.01 * math.sin(math.pi * u), z - sag))
        m = Matrix.Translation(p) @ Matrix.Rotation(math.pi / 2 * (i % 2), 4, "X")
        m = m @ Matrix.Diagonal((1.6, 1.0, 0.7, 1.0))
        bmesh.ops.create_uvsphere(bm, u_segments=8, v_segments=4, radius=0.0075 * s, matrix=m)
    ob = O.new_obj("Clasp", bm, ["M_SovTrim"])
    ctx.rigid(ob, "Chest")
    return ob


# -------------------------------------------------------------------------- build


def dull_specular():
    """Black cloth reads black: a weak, broad specular on the fabrics."""
    for name, level in (("M_SovRobe", 0.22), ("M_SovCloak", 0.3), ("M_SovLining", 0.35)):
        bsdf = bpy.data.materials[name].node_tree.nodes["Principled BSDF"]
        bsdf.inputs["Specular IOR Level"].default_value = level


def build_sovereign(ctx: O.Ctx):
    s = ctx.s
    dull_specular()
    boot_top = 0.13 * s
    belt_z = 0.585 * ctx.H
    neck_z = ctx.L["neck"].z
    cut = classify_sovereign(ctx, boot_top, belt_z)
    garment = O.garment_body(ctx, lambda c: cut, name="Garment")
    ctx.hi = {"Garment": O.keep_hi(garment, "Hi_Sovereign")}
    ctx.look = {"belt_z": belt_z, "boot_top": boot_top, "neck_z": neck_z, "female": False}
    O.decimate_head_aware(garment, ctx, 7000, 2900)
    parts = [garment]
    parts.append(O.boots(ctx, boot_top, flare=0.004, inflate=0.006))
    parts.append(robe_skirt(ctx, belt_z))
    parts.append(O.belt(ctx, belt_z, height=0.05, out=0.012, buckle=True, mat="M_Belt",
                        buckle_mat="M_SovTrim", pts=B.verts_np(garment)))
    parts.append(sleeve(ctx, "L"))
    parts.append(sleeve(ctx, "R"))
    col = O.collar(ctx, neck_z - 0.004, neck_z + 0.05 * s, out=0.008, mat="M_SovRobe",
                   piping="M_SovTrim")
    parts.append(col)
    parts.append(O.eyes(ctx, mat="M_SovEye"))
    mantle_ob = mantle(ctx)
    parts.append(mantle_ob)
    cls = clasp(ctx, mantle_ob, neck_z - 0.14 * s)
    if cls is not None:
        parts.append(cls)
    body = O.finish(ctx, parts, "Body")

    # the Sovereign's own skeleton: the shared one plus the cloak bones
    arm = ctx.arm.copy()
    arm.data = ctx.arm.data.copy()
    arm.name = "SK_Sovereign_Rig"
    arm.data.name = "SK_Sovereign_Rig"
    C.link(arm)
    cl, cy, z_top, z_hem, _back = cloak(ctx, belt_z)
    add_cloak_bones(arm, cy, z_top, z_hem, belt_z, s)
    bones = [b.name for b in arm.data.bones]
    skin_cloak(cl, bones, ctx.L["shoulder"].z, belt_z, s)
    extra = [cl]
    for o in extra:
        O.bake_vertex_ao(o)
    for o in [body] + extra:
        o.parent = arm
        o.matrix_parent_inverse.identity()
        mod = next((m for m in o.modifiers if m.type == "ARMATURE"), None)
        mod = mod or o.modifiers.new("Armature", "ARMATURE")
        mod.object = arm
    ctx.export_arm = arm
    return [body] + extra
