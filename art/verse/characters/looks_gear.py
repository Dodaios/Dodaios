"""Atlas painters for the technician's work suit and the marine's armour.

Same conventions as `looks.py`: albedo multiplies the material colour, height is
relief in metres, positions are the rest pose in Blender axes.
"""

from __future__ import annotations

import numpy as np

from characters.looks import (
    Anatomy,
    armholes,
    belt,
    boots,
    elbow_folds,
    eyes,
    fabric,
    face,
    folds,
    seam,
)
from characters.paint import band, fbm, mul, rough, smooth


def raised_rect(surf, mask, u, v, hu, hv, height, dark=1.0, corner=0.01, rim=0.0024):
    """A raised (or, with negative height, sunk) rounded rectangle in local coordinates
    (u, v) metres, half sizes hu, hv; a stitched groove follows its outline."""
    du = np.maximum(np.abs(u) - (hu - corner), 0.0)
    dv = np.maximum(np.abs(v) - (hv - corner), 0.0)
    d = np.hypot(du, dv) - corner  # < 0 inside
    inside = smooth(0.0015, -0.0015, d)
    surf.height += np.where(mask, height * inside, 0.0)
    if dark != 1.0:
        mul(surf, mask, (dark, dark, dark), inside)
    seam(surf, mask, d + rim, 0.0012, 0.0006, 0.75)
    return inside


def bone_len(an, name):
    return float(np.linalg.norm(np.subtract(*an.bone(name))))


def suit_seams(surf, an, look, mat):
    """Seams of a one-piece suit: yoke, side seams, set-in sleeves, outer leg seams,
    folds at the waist, elbows and over the boots."""
    P, N = surf.P, surf.N
    um = surf.m(mat) & surf.p("Garment")
    if not um.any():
        return um
    fabric(surf, um)
    belt_z, neck_z = look["belt_z"], look["neck_z"]
    Z = P[:, 2]
    ym = an.torso_mid_y(Z)
    torso = um & (Z > an.ctx.crotch) & (Z < neck_z + 0.01) & (np.abs(P[:, 0]) < 0.2 * an.s)
    seam(surf, torso, Z - (neck_z - 0.075 * an.s), 0.0026, 0.001, 0.75, lap=0.0005)  # yoke
    side = torso & (np.abs(N[:, 0]) > 0.45) & (Z < neck_z - 0.06)
    seam(surf, side, P[:, 1] - ym - 0.012, 0.0026, 0.001, 0.8)
    armholes(surf, an, um & (Z > belt_z))
    elbow_folds(surf, an, um)
    near = smooth(0.06, 0.012, np.abs(Z - belt_z))
    folds(surf, um, P[:, 0] / 0.03 * 2 * np.pi + 3 * fbm(P, 0.05, 1, 2), near * 0.8, 0.0024)
    kt = look["boot_top"]
    env = smooth(0.09, 0.0, np.abs(Z - (kt + 0.05)))
    folds(surf, um, Z / 0.026 * 2 * np.pi + 1.4 * np.sin(P[:, 0] * 40), env, 0.003)
    for s in ("L", "R"):
        for bone in (f"UpperLeg_{s}", f"LowerLeg_{s}"):
            t, r, u = an.along(P, bone)
            sel = um & (t > -0.05) & (t < 1.05) & (r < 0.2) & ((P[:, 0] > 0) == (s == "L"))
            out = u[:, 0] * (1 if s == "L" else -1)
            seam(surf, sel & (out > 0.2), u[:, 1] * 0.06, 0.0028, 0.001, 0.8)
    return um


def knee_pads(surf, an, mask, dark=0.7):
    for s in ("L", "R"):
        t, _r, u = an.along(surf.P, f"LowerLeg_{s}")
        L = bone_len(an, f"LowerLeg_{s}")
        sel = mask & ((surf.P[:, 0] > 0) == (s == "L")) & (-u[:, 1] > 0.0)
        ang = np.arctan2(u[:, 0], -u[:, 1])
        pad = raised_rect(surf, sel, ang * 0.06, (t - 0.06) * L, 0.045, 0.055, 0.0026, dark, 0.02)
        rough(surf, sel, 0.42, pad)


def harness(surf, an, look, mask, x=0.082):
    """Two webbing straps over the shoulders, down the chest and the back to the belt."""
    P = surf.P
    Z = P[:, 2]
    sel = mask & (Z > look["belt_z"]) & (Z < look["neck_z"] + 0.04)
    k = np.clip((Z - look["belt_z"]) / (look["neck_z"] - look["belt_z"]), 0, 1)
    d = np.abs(P[:, 0]) - (x + 0.012 * k) * an.s
    strap = band(d, 0.017 * an.s, 0.0015)
    surf.height += np.where(sel, 0.0022 * strap, 0.0)
    mul(surf, sel, (0.5, 0.5, 0.52), strap)
    rough(surf, sel, 0.5, strap)
    for e in (-0.013, 0.013):
        seam(surf, sel & (strap > 0.5), d - e * an.s, 0.0008, 0.0004, 0.7)


def cargo_pockets(surf, an, mask):
    for s in ("L", "R"):
        t, _r, u = an.along(surf.P, f"UpperLeg_{s}")
        L = bone_len(an, f"UpperLeg_{s}")
        sg = 1.0 if s == "L" else -1.0
        sel = mask & ((surf.P[:, 0] > 0) == (s == "L")) & (u[:, 0] * sg > -0.1)
        ang = np.arctan2(-u[:, 1], u[:, 0] * sg)  # 0 = outer side, + = towards the front
        uu = (ang - 0.25) * 0.075
        vv = (t - 0.55) * L
        raised_rect(surf, sel, uu, vv, 0.06, 0.075, 0.0024, 0.9, 0.008)
        flap = band(vv - 0.05, 0.025, 0.002) * band(uu, 0.062, 0.002)
        surf.height += np.where(sel, 0.0012 * flap, 0.0)
        seam(surf, sel & (np.abs(uu) < 0.062), vv - 0.025, 0.0014, 0.0008, 0.6)


def gloves(surf, an, mat="M_Gloves"):
    gm = surf.m(mat)
    if not gm.any():
        return
    P = surf.P
    for s in ("L", "R"):
        t, _r, u = an.along(P, f"Hand_{s}")
        sel = gm & ((P[:, 0] > 0) == (s == "L"))
        back = u[:, 0] * (1 if s == "L" else -1)
        knuckle = band(t - 0.95, 0.12, 0.05) * smooth(0.0, 0.5, back)
        surf.height += np.where(sel, 0.0018 * knuckle, 0.0)
        mul(surf, sel, (0.7, 0.7, 0.72), knuckle)
        rough(surf, sel, 0.3, knuckle)
        seam(surf, sel, (t - 0.15) * 0.1, 0.0012, 0.0006, 0.7)  # cuff line
    surf.albedo[gm] *= (0.9 + 0.1 * fbm(P[gm], 0.006, 2, 91))[:, None]


def technician(ctx):
    an = Anatomy(ctx)
    look = ctx.look

    def paint(surf):
        P = surf.P
        face(surf, an, beard=True)
        eyes(surf, an)
        um = suit_seams(surf, an, look, "M_Uniform")
        # centre-front zip below the chest box: a raised tape with a dark track
        zipm = um & (P[:, 1] < an.torso_mid_y(P[:, 2])) & (P[:, 2] > an.ctx.crotch)
        zipm &= P[:, 2] < 0.69 * an.ctx.H
        surf.height += np.where(zipm, 0.0012 * band(P[:, 0], 0.006, 0.0012), 0.0)
        seam(surf, zipm, P[:, 0], 0.0012, 0.0008, 0.45)
        harness(surf, an, look, um)
        knee_pads(surf, an, um, 0.75)
        cargo_pockets(surf, an, um)
        # branch patch on the left upper arm
        t, _r, u = an.along(P, "UpperArm_L")
        ang = np.arctan2(-u[:, 1], u[:, 0])
        raised_rect(surf, um & (P[:, 0] > 0) & (u[:, 0] > -0.2), ang * 0.05,
                    (t - 0.38) * bone_len(an, "UpperArm_L"), 0.025, 0.025, 0.0012, 0.8, 0.004)
        gloves(surf, an)
        boots(surf, an, look)
        belt(surf, buckle="M_ChestBox", grooves=2)
        hm = surf.p("Helmet") & surf.m("M_Helmet")
        if hm.any():
            zmin = P[hm, 2].min()
            seam(surf, hm, P[:, 2] - (zmin + 0.03), 0.0018, 0.0008, 0.7)
        cb = surf.p("ChestBox") & surf.m("M_ChestBox")
        if cb.any():
            c = P[cb].mean(axis=0)
            for k in range(5):
                seam(surf, cb & (P[:, 1] < c[1]), P[:, 2] - c[2] + 0.034 - k * 0.005, 0.0008,
                     0.0005, 0.6)
            surf.albedo[cb] *= (0.85 + 0.15 * fbm(P[cb], 0.004, 2, 93))[:, None]

    return paint


# --------------------------------------------------------------------------- armour

LINE = {"width": 0.0016, "depth": 0.0011, "dark": 0.58}


def vents(surf, mask, along, across, n, pitch, half_len, slot=0.0022):
    """`n` dark sunk slots across `along` (metres), each 2*`half_len` long in `across`."""
    for k in range(n):
        v = band(along - (k - (n - 1) / 2) * pitch, slot, 0.0008) * band(across, half_len, 0.001)
        mul(surf, mask, (0.18, 0.18, 0.19), v)
        rough(surf, mask, 0.85, v)
        surf.height += np.where(mask, -0.0012 * v, 0.0)


def armour(surf, an, look):
    """Panel lines, vents and wear on the marine's plates (each plate in its own frame)."""
    P, N = surf.P, surf.N
    s = an.s
    am = surf.m("M_Armor")
    if not am.any():
        return
    X, Z = P[:, 0], P[:, 2]
    g = fbm(P, 0.02, 3, 101)
    surf.albedo[am] *= (0.9 + 0.1 * g[am])[:, None]
    rough(surf, am, 0.45, 0.5 * (1.0 - g))
    ch = am & surf.p("ChestPlate")
    if ch.any():
        top, bot = P[ch, 2].max(), P[ch, 2].min()
        seam(surf, ch & (Z > bot + 0.45 * (top - bot)), X, **LINE)
        for sx in (1, -1):
            d = (X * sx - 0.045 * s) - (top - Z) * 0.55
            seam(surf, ch & (Z > bot + 0.55 * (top - bot)) & (X * sx > 0.03), d * 0.85, **LINE)
            vents(surf, ch, Z - (top - 0.049), X * sx - 0.085 * s, 3, 0.009, 0.014)
    for k in (0, 1):
        ab = am & surf.p(f"Abdomen{k}")
        if ab.any():
            seam(surf, ab, X, **LINE)
            for sx in (1, -1):
                seam(surf, ab, X * sx - 0.058 * s, **LINE)
    bk = am & surf.p("BackPlate")
    if bk.any():
        top = P[bk, 2].max()
        seam(surf, bk & (Z > top - 0.06), X, **LINE)
        seam(surf, bk, Z - (top - 0.045), **LINE)
    pk = am & surf.p("Pack")
    if pk.any():
        lo, hi = P[pk].min(axis=0), P[pk].max(axis=0)
        c = 0.5 * (lo + hi)
        hu, hv = 0.5 * (hi[0] - lo[0]), 0.5 * (hi[2] - lo[2])
        back = pk & (N[:, 1] > 0.6)
        raised_rect(surf, back, X - c[0], Z - c[2], hu - 0.018, hv - 0.018, -0.0012, 0.92, 0.01)
        vents(surf, back, X - c[0], Z - c[2], 5, 0.026, 0.045, 0.0035)
        seam(surf, pk & (N[:, 2] > 0.6), X - c[0], **LINE)
    for side in ("L", "R"):
        sg = 1.0 if side == "L" else -1.0
        bl = am & surf.p(f"Bell{side}")
        if bl.any():
            apex = P[bl][np.argmax(P[bl] @ np.array([sg * 0.8, 0.0, 0.6]))]
            d = np.linalg.norm(P - apex, axis=1)
            seam(surf, bl, d - 0.06 * s, **LINE)
            seam(surf, bl, d - 0.075 * s, **LINE)
        br = am & surf.p(f"Bracer{side}")
        if br.any():
            t, _r, u = an.along(P, f"ForeArm_{side}")
            L = bone_len(an, f"ForeArm_{side}")
            seam(surf, br, (t - 0.5) * L, **LINE)
            top_ = smooth(0.2, 0.6, u[:, 0] * sg)
            ins = band((t - 0.68) * L, 0.025, 0.002) * band(u[:, 1] * 0.04, 0.012, 0.002) * top_
            surf.height += np.where(br, -0.0012 * ins, 0.0)
            mul(surf, br, (0.55, 0.55, 0.56), ins)
        th = am & surf.p(f"Thigh{side}")
        if th.any():
            t, _r, u = an.along(P, f"UpperLeg_{side}")
            ang = np.arctan2(u[:, 0] * sg, -u[:, 1])
            raised_rect(surf, th, ang * 0.07, (t - 0.55) * bone_len(an, f"UpperLeg_{side}"),
                        0.035, 0.07, -0.001, 0.9, 0.012)
        sh = am & surf.p(f"Shin{side}")
        if sh.any():
            t, _r, u = an.along(P, f"LowerLeg_{side}")
            L = bone_len(an, f"LowerLeg_{side}")
            seam(surf, sh, (t - 0.2) * L, **LINE)
            seam(surf, sh & (t > 0.2) & (-u[:, 1] > 0.5), u[:, 0] * 0.07, **LINE)
            vents(surf, sh & (np.abs(u[:, 0]) > 0.6), (t - 0.36) * L, np.abs(u[:, 0]) - 0.8,
                  3, 0.012, 0.15)
    bt = am & surf.p("Boots")
    if bt.any():
        mul(surf, bt, (0.32, 0.32, 0.33), smooth(0.02, 0.014, Z))
        rough(surf, bt, 0.8, smooth(0.02, 0.014, Z))
        seam(surf, bt, Z - 0.021, **LINE)
        seam(surf, bt & (Z > 0.06), Z - 0.11, **LINE)
        for c in (1.0, -1.0):
            ball = np.array(an.ctx.L["ball"][:]) * np.array([c, 1, 1])
            dtoe = P[:, 1] - (ball[1] + 0.004) - 0.25 * np.abs(X - ball[0])
            seam(surf, bt & (Z < 0.08) & ((X > 0) == (c > 0)), dtoe, **LINE)
    hm = am & surf.p("Helmet")
    if hm.any():
        ez, ey = an.ez, an.ey
        front = P[:, 1] < ey + 0.05
        seam(surf, hm & front, Z - (ez + 0.0175 * s + 0.014), **LINE)  # brow line
        seam(surf, hm & (Z > ez + 0.05), X, **LINE)  # crest
        for sx in (1, -1):
            hx = P[hm, 0].max() if sx > 0 else P[hm, 0].min()
            ec = np.array([hx, ey + 0.065, ez - 0.012])
            d = np.linalg.norm((P - ec) * np.array([0.0, 1.0, 1.0]), axis=1)
            disc = hm & (X * sx > 0.06)
            seam(surf, disc, d - 0.024 * s, **LINE)
            seam(surf, disc, d - 0.012 * s, **LINE)
            cheek = hm & (X * sx > 0.02) & (Z < ez - 0.02) & (P[:, 1] < ey + 0.06)
            seam(surf, cheek, (X * sx - 0.03) + (Z - (ez - 0.02)) * 0.6, **LINE)
        seam(surf, hm & ~front, Z - (ez - 0.04), **LINE)  # back neck rim
        mul(surf, hm & (Z < ez - 0.06) & (np.abs(X) < 0.03) & (P[:, 1] < ey), (0.5, 0.5, 0.52))


def trooper(ctx):
    an = Anatomy(ctx)
    look = ctx.look

    def paint(surf):
        P = surf.P
        armour(surf, an, look)
        us = surf.m("M_Undersuit")
        fabric(surf, us)
        # ribbed undersuit
        rib = 0.5 + 0.5 * np.sin(P[:, 2] / 0.012 * 2 * np.pi)
        surf.height += np.where(us, 0.0011 * rib, 0.0)
        rough(surf, us, 0.55, rib)
        mul(surf, us, (0.82, 0.82, 0.84), 1.0 - rib)
        elbow_folds(surf, an, us)
        gloves(surf, an)
        belt(surf, buckle="M_Armor", grooves=3)
        pm = surf.p("Pouches") & surf.m("M_Belt")
        if pm.any():
            top = P[pm, 2].max()
            seam(surf, pm, P[:, 2] - (top - 0.016), 0.0016, 0.0009, 0.5)
            surf.albedo[pm] *= (0.88 + 0.12 * fbm(P[pm], 0.008, 2, 111))[:, None]

    return paint


# --------------------------------------------------------------------------- drones


def hexbar(u, v, w, h):
    """Coverage of the ship's hex-bar mark (style bible 7.6): an elongated hexagon outline
    with 45 degree ends, half width w, half height h, and a bar through its centre; the
    line weight is 1/8 of the height."""
    t = h / 4.0
    d = np.maximum(np.abs(v) - h, (np.abs(u) + np.abs(v) - w) / np.sqrt(2.0))
    outline = band(d + t / 2, t / 2, t * 0.35)
    bar = band(v, t / 2, t * 0.35) * (d < -t * 0.5)
    return np.clip(outline + bar, 0.0, 1.0)


def companion(center, radii):
    c = np.asarray(center, float)

    def paint(surf):
        P = surf.P - c
        th = np.arctan2(P[:, 0], -P[:, 1])
        ph = np.arctan2(P[:, 2], np.hypot(P[:, 0], P[:, 1]))
        r = radii[0]
        sh = surf.m("M_Shell")
        g = fbm(surf.P, 0.015, 3, 121)
        surf.albedo[sh] *= (0.94 + 0.06 * g[sh])[:, None]
        rough(surf, sh, 0.45, 0.4 * (1 - g))
        # the hex-bar mark on the top cap, just behind the beacon (seen from above at any
        # heading), and again on the back panel (the companion follows the commander)
        top = sh & (ph > np.radians(55))
        mark = hexbar(P[:, 0], P[:, 1] - 0.056, 0.032, 0.0135)
        mul(surf, top, (0.24, 0.25, 0.26), mark)
        surf.height += np.where(top, -0.0008 * mark, 0.0)
        # upper side panels: an inset line inside each panel and four screw heads
        up = sh & (ph > np.radians(5)) & (ph < np.radians(57))
        for k in range(4):
            tc = np.radians(90 * k)
            dth = np.angle(np.exp(1j * (th - tc)))
            inp = up & (np.abs(dth) < np.radians(45))
            if not inp.any():
                continue
            if k == 2:
                mark = hexbar(dth * r * np.cos(ph), (ph - np.radians(31)) * r, 0.032, 0.0135)
                mul(surf, inp, (0.26, 0.27, 0.28), mark)
                surf.height += np.where(inp, -0.0007 * mark, 0.0)
            for e in (np.radians(36), -np.radians(36)):
                seam(surf, inp & (np.abs(dth) < np.radians(40)), (dth - e) * r * np.cos(ph),
                     0.0013, 0.0007, 0.62)
            for pe in (np.radians(13), np.radians(49)):
                seam(surf, inp & (np.abs(dth) < np.radians(36)), (ph - pe) * r, 0.0013, 0.0007,
                     0.62)
            for sa in (np.radians(40), -np.radians(40)):
                for pe in (np.radians(10), np.radians(52)):
                    dist = np.hypot((dth - sa) * r * np.cos(ph), (ph - pe) * r)
                    head = band(dist, 0.0028, 0.0009)
                    mul(surf, inp, (0.35, 0.36, 0.38), head)
                    surf.height += np.where(inp, 0.0005 * head, 0.0)
        # brushed ring
        rg = surf.m("M_Ring")
        brush = fbm(np.stack([th * 0.2, P[:, 2] * 8.0, np.zeros(len(th))], 1), 0.004, 2, 131)
        surf.albedo[rg] *= (0.85 + 0.15 * brush[rg])[:, None]
        rough(surf, rg, 0.25, 0.6 * brush)

    return paint


def utility():
    def paint(surf):
        P, N = surf.P, surf.N
        ch = surf.m("M_Chassis")
        g = fbm(P, 0.02, 3, 141)
        surf.albedo[ch] *= (0.86 + 0.14 * g[ch])[:, None]
        rough(surf, ch, 0.6, 0.5 * (1 - g))
        # scuffs low on the flanks and the nose
        low = smooth(0.11, 0.06, P[:, 2]) * smooth(0.6, 0.85, fbm(P, 0.008, 2, 143))
        mul(surf, ch, (1.25, 1.25, 1.25), 0.5 * low)
        # the hex-bar mark on the front deck plate (the chassis factor is twice the
        # authored colour, so the mark can be lighter than the paint)
        top = ch & (N[:, 2] > 0.8) & (P[:, 2] > 0.185)
        mark = hexbar(P[:, 0], P[:, 1] + 0.0825, 0.042, 0.015)
        mul(surf, ch, (0.5, 0.5, 0.5))
        mul(surf, top, (2.0, 2.0, 2.0), mark * 0.9)
        surf.height += np.where(top, -0.0006 * mark, 0.0)
        tr = surf.m("M_Trim")
        surf.albedo[tr] *= (0.9 + 0.1 * fbm(P[tr], 0.006, 2, 151))[:, None]

    return paint
