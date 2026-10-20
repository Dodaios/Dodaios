"""What the crew atlases show: faces, hair, tailoring, boots, armour panelling.

Each painter writes into a `paint.Surface`: `albedo` multiplies the material's
own colour (keep tinted slots neutral grey, so the rank tier still sets the
colour), `height` (metres) becomes relief in the normal map. Positions are the
rest pose in Blender axes (X = the character's left, -Y = forward, Z = up).

Sizes are chosen for the close game camera (about 200 px per metre, 60 degrees
from above): a feature narrower than ~4 mm is a fraction of a pixel, so seams,
brows and lash lines are drawn a little bolder than life, as game characters are.
"""

from __future__ import annotations

import numpy as np

from characters import outfits as O
from characters.paint import band, fbm, groove, mul, rough, smooth

# Face landmarks relative to the eye centres (metres, measured on the base meshes).
FACE = {
    "M": {"nose_tip": -0.036, "nose_base": -0.054, "mouth": -0.076, "mouth_hw": 0.025,
          "chin": -0.118, "brow": 0.019, "iris": (0.20, 0.12, 0.07)},
    "F": {"nose_tip": -0.030, "nose_base": -0.050, "mouth": -0.071, "mouth_hw": 0.0225,
          "chin": -0.108, "brow": 0.020, "iris": (0.17, 0.20, 0.17)},
}


class Anatomy:
    """Measured landmarks of one body variant, in the units the painters need."""

    def __init__(self, ctx):
        self.ctx = ctx
        self.s = ctx.s
        e = max(ctx.eyes, key=lambda v: v.x)
        self.eyes = [np.array(v[:]) for v in ctx.eyes]
        self.ex, self.ey, self.ez = abs(e.x), e.y, e.z
        self.eye_r = ctx.eye_r
        self.face = FACE[ctx.variant]
        self.neck_z = ctx.L["neck"].z
        V = ctx.V
        torso = ctx.bone_mask("Hips", "Spine", "Chest", "Neck") & (np.abs(V[:, 0]) < 0.11)
        zs = np.linspace(V[:, 2].min(), V[:, 2].max(), 120)
        yc = np.full(len(zs), np.nan)
        for k, z in enumerate(zs):
            sl = V[torso & (np.abs(V[:, 2] - z) < 0.012)]
            if len(sl) > 6:
                yc[k] = 0.5 * (sl[:, 1].min() + sl[:, 1].max())
        good = ~np.isnan(yc)
        self._zs, self._yc = zs[good], yc[good]

    def torso_mid_y(self, z):
        return np.interp(z, self._zs, self._yc)

    def bone(self, name):
        h = np.array(self.ctx.rig.head(name)[:])
        t = np.array(self.ctx.rig.tail(name)[:])
        return h, t

    def along(self, P, name):
        """(t along the bone 0..1, radial distance, unit radial direction) for points P."""
        h, t = self.bone(name)
        d = t - h
        L2 = float(d @ d)
        tt = ((P - h) @ d) / L2
        foot = h + np.outer(tt, d)
        r = P - foot
        rl = np.linalg.norm(r, axis=1)
        return tt, rl, r / np.maximum(rl, 1e-9)[:, None]


# ---------------------------------------------------------------------------- face


def face(surf, an: Anatomy, beard: bool, mask=None):
    P, N = surf.P, surf.N
    sk = surf.m("M_Skin") & (P[:, 2] > an.neck_z + 0.01)
    if mask is not None:
        sk &= mask
    if not sk.any():
        return
    f = an.face
    X, Y, Z = P[:, 0], P[:, 1], P[:, 2] - an.ez
    ax = np.abs(X)
    front = smooth(-0.05, -0.35, N[:, 1]) * (Y < an.ey + 0.035)
    # skin: soft mottling, warmer cheeks, nose and ears
    mul(surf, sk, (0.97, 0.955, 0.95), fbm(P, 0.018, 3, 11))
    cheek = np.exp(-(((ax - 0.043) / 0.02) ** 2 + ((Z + 0.036) / 0.02) ** 2))
    mul(surf, sk, (1.0, 0.84, 0.82), 0.35 * cheek * front)
    nose = np.exp(-((X / 0.012) ** 2 + ((Z - f["nose_tip"]) / 0.014) ** 2))
    mul(surf, sk, (1.0, 0.88, 0.86), 0.3 * nose * front)
    tzone = np.exp(-((X / 0.02) ** 2 + ((Z - 0.035) / 0.03) ** 2)) + nose
    rough(surf, sk, 0.36, np.clip(tzone, 0, 1) * front * 0.8)
    ear = np.exp(-(((ax - 0.085) / 0.02) ** 2 + ((Z + 0.02) / 0.03) ** 2)) * (N[:, 1] > -0.4)
    mul(surf, sk, (1.0, 0.86, 0.84), 0.3 * ear)
    # eye sockets: a soft shadow round the eye, darker towards the nose
    sock = np.exp(-(((ax - an.ex + 0.002) / 0.019) ** 2 + ((Z - 0.002) / 0.014) ** 2))
    mul(surf, sk, (0.8, 0.72, 0.7), 0.55 * sock * front)
    # eyelids: the opening is an ellipse round each eye; a dark upper lash line with a
    # small outer flick, a lighter lower one
    ea, eb = 0.0165 * an.s, 0.0068 * an.s
    u = (ax - an.ex) / ea
    v = (Z - 0.0012) / eb
    r = np.sqrt(u * u + v * v)
    upper = band(r - 1.05, 0.16, 0.12) * (v > -0.25) * front
    flick = band(v - 0.35 - 0.6 * (u - 1.0), 0.18, 0.12) * (u > 0.8) * (u < 1.45) * front
    lower = band(r - 1.08, 0.12, 0.1) * (v < -0.2) * front
    mul(surf, sk, (0.16, 0.12, 0.11), np.clip(upper + flick, 0, 1))
    mul(surf, sk, (0.6, 0.5, 0.48), 0.8 * lower)
    surf.height += np.where(sk, 0.0006 * np.clip(upper, 0, 1), 0.0)
    # brows: bold arches over the eyes, thicker at the inner end, hair-coloured
    bx = (ax - (an.ex + 0.002)) / (0.022 * an.s)
    arch = f["brow"] + 0.0045 * (1.0 - bx * bx) - 0.002 * (bx > 0) * bx
    thick = (0.0034 if an.ctx.variant == "M" else 0.0026) * (1.0 - 0.35 * np.clip(bx, -1, 1))
    brow = band(Z - arch, thick, 0.0016) * (np.abs(bx) < 1.15) * front
    hairs = 0.75 + 0.25 * fbm(P * np.array([1.0, 1.0, 3.0]), 0.004, 2, 5)
    mul(surf, sk, (0.12, 0.10, 0.09), brow * hairs)
    surf.height += np.where(sk, 0.0005 * brow, 0.0)
    rough(surf, sk, 0.65, brow)
    # nostrils
    nos = np.exp(-(((ax - 0.0105) / 0.0045) ** 2 + ((Z - f["nose_base"] - 0.004) / 0.003) ** 2))
    mul(surf, sk, (0.35, 0.22, 0.2), 0.9 * nos * (N[:, 2] < 0.6))
    # lips and the mouth line
    hw = f["mouth_hw"] * an.s
    xm = np.clip(X / hw, -1.2, 1.2)
    zm = f["mouth"]
    lip_up = band(Z - (zm + 0.0052 * (1 - xm * xm)), 0.0052 * (1 - 0.6 * xm * xm), 0.0015)
    lip_lo = band(Z - (zm - 0.0062 * (1 - xm * xm)), 0.006 * (1 - 0.6 * xm * xm), 0.0015)
    inside = (np.abs(X) < hw * 1.05) * front
    rose = (0.86, 0.6, 0.58) if an.ctx.variant == "M" else (0.84, 0.5, 0.52)
    mul(surf, sk, rose, 0.85 * np.clip(lip_up + lip_lo, 0, 1) * inside)
    line = band(Z - zm + 0.0004 * xm * xm, 0.0011 + 0.0005 * (1 - xm * xm), 0.0009) * inside
    corner = np.exp(-(((ax - hw) / 0.004) ** 2 + ((Z - zm) / 0.004) ** 2)) * front
    mul(surf, sk, (0.32, 0.2, 0.19), np.clip(line + 0.6 * corner, 0, 1))
    surf.height += np.where(sk, -0.0009 * line + 0.0004 * np.clip(lip_up + lip_lo, 0, 1), 0.0)
    rough(surf, sk, 0.3, np.clip(lip_up + lip_lo, 0, 1) * inside)
    if beard:
        # close-shaven shadow on the jaw and upper lip
        jaw = smooth(f["nose_base"] - 0.004, f["nose_base"] - 0.014, Z) * smooth(
            f["chin"] - 0.035, f["chin"] - 0.005, Z
        )
        jaw *= 1.0 - np.clip(lip_up + lip_lo, 0, 1)
        jaw *= smooth(0.085, 0.06, ax) * (Y < an.ey + 0.07)
        stub = 0.6 + 0.4 * fbm(P, 0.0025, 2, 23)
        mul(surf, sk, (0.84, 0.8, 0.8), 0.7 * jaw * stub)


def eyes(surf, an: Anatomy):
    em = surf.m("M_Eye")
    if not em.any():
        return
    P = surf.P
    iris_col = np.array(an.face["iris"])
    for c in an.eyes:
        side = (P[:, 0] > 0) == (c[0] > 0)
        sel = em & side
        d = P - c
        d /= np.maximum(np.linalg.norm(d, axis=1, keepdims=True), 1e-9)
        # look straight ahead, a touch down
        look = np.array([0.0, -0.99, -0.12])
        look /= np.linalg.norm(look)
        ang = np.arccos(np.clip(d @ look, -1, 1))
        iris = 1.0 - smooth(0.40, 0.46, ang)
        pupil = 1.0 - smooth(0.16, 0.21, ang)
        limbal = band(ang - 0.44, 0.03, 0.04)
        streak = 0.8 + 0.2 * np.sin(np.arctan2(d[:, 2], d[:, 0]) * 24)
        mul(surf, sel, (1.0, 0.97, 0.95))
        rough(surf, sel, 0.07)
        mul(surf, sel, iris_col[None, :] * streak[:, None], iris)
        mul(surf, sel, (0.25, 0.25, 0.25), limbal * 0.7)
        mul(surf, sel, (0.05, 0.05, 0.05), pupil)
        # the upper lid shades the top of the eyeball
        lid = smooth(0.25, 0.75, d[:, 2])
        mul(surf, sel, (0.55, 0.5, 0.5), lid)


# ---------------------------------------------------------------------------- hair


def hair(surf, an: Anatomy, female: bool):
    hm = surf.m("M_Hair")
    if not hm.any():
        return
    P = surf.P
    bun = surf.p("Bun") if female else np.zeros(surf.n, bool)
    # Combed back: on top and over the sides the strands run from the hairline towards
    # the back of the head (round an axis pointing backwards), at the back they fall
    # straight down. `s` is the across-strand coordinate in metres.
    c = np.array([0.0, an.ey + 0.06, an.ez + 0.015])
    phi = np.arctan2(P[:, 2] - c[2], P[:, 0] - c[0])
    wb = smooth(0.25, 0.75, surf.N[:, 1]) * smooth(an.ez + 0.06, an.ez + 0.0, P[:, 2])
    s_ = (1 - wb) * phi * 0.09 + wb * P[:, 0]
    s_ = s_ + 0.006 * (fbm(P, 0.03, 2, 3) - 0.5)
    clump = 0.5 + 0.5 * np.sin(s_ / 0.011 * 2 * np.pi + 1.2 * np.sin(s_ / 0.031 * 2 * np.pi))
    fine = 0.5 + 0.5 * np.sin(s_ / 0.0032 * 2 * np.pi + 3 * fbm(P, 0.012, 2, 7))
    if bun.any():
        bc = P[bun].mean(axis=0)
        bphi = np.arctan2(P[:, 2] - bc[2], P[:, 0] - bc[0])
        brad = np.hypot(P[:, 2] - bc[2], P[:, 0] - bc[0])
        sw = bphi * 3 + brad * 180
        clump = np.where(bun, 0.5 + 0.5 * np.sin(sw * 3), clump)
        fine = np.where(bun, 0.5 + 0.5 * np.sin(sw * 11), fine)
    # the hair factor is twice the authored hair colour: locks catch light up to it
    shade = 0.36 + 0.42 * clump**1.5 + 0.22 * fine
    surf.albedo[hm] *= shade[hm, None]
    surf.height += np.where(hm, 0.0024 * clump + 0.0006 * fine, 0.0)
    rough(surf, hm, 0.3 + 0.3 * (1.0 - clump) + 0.08 * fine)
    # parting line
    if female:
        part = band(P[:, 0], 0.0016, 0.0012) * (P[:, 1] < an.ey + 0.1) * (P[:, 2] > an.ez + 0.06)
    else:
        part = band(P[:, 0] - 0.034 * an.s, 0.0016, 0.0012) * (P[:, 1] < an.ey + 0.09)
        part *= P[:, 2] > an.ez + 0.055
    mul(surf, hm, (0.55, 0.5, 0.5), part)
    surf.height += np.where(hm, -0.0012 * part, 0.0)
    # thinner, darker at the hairline edge
    hl = O.hairline(an.ctx, P, female)
    edge = smooth(0.012, 0.0, P[:, 2] - hl) * ~bun
    mul(surf, hm, (0.8, 0.78, 0.78), edge)


# ------------------------------------------------------------------------- clothes


# Seams are drawn bolder than life so they survive the game camera (1 px = 5 mm).
SEAM_WIDTH = 1.45
SEAM_DEPTH = 1.6
SEAM_DARK = 1.9


def seam(surf, mask, d, width=0.0026, depth=0.0009, dark=0.78, lap=0.0):
    """A sewn seam along the zero line of `d` (metres): groove, darker line, lapped side."""
    width *= SEAM_WIDTH
    depth *= SEAM_DEPTH
    dark = dark**SEAM_DARK
    g = groove(d, width)
    mul(surf, mask, (dark, dark, dark), g)
    rough(surf, mask, 0.9, 0.7 * g)
    h = -depth * g
    if lap:
        h = h + lap * smooth(0.0, width, d) * band(d, 3 * width, width)
    surf.height += np.where(mask, h, 0.0)


def folds(surf, mask, phase, env, amp=0.0016, sharp=1.6):
    """Cloth folds: ridges along `phase` (radians), strength `env` in [0, 1]."""
    w = 0.5 + 0.5 * np.sin(phase)
    ridge = np.power(w, sharp)
    surf.height += np.where(mask, amp * env * ridge, 0.0)
    mul(surf, mask, (0.86, 0.86, 0.86), env * (1.0 - ridge) * 0.6)


def fabric(surf, mask, scale=0.004, amount=0.035):
    n = fbm(surf.P, scale, 2, 31)
    surf.albedo[mask] *= (1.0 - amount + amount * n[mask])[:, None]
    surf.rough = np.where(mask, np.clip(surf.rough + 0.06 * (n - 0.5), 0.04, 1.0), surf.rough)
    surf.height += np.where(mask, 0.00012 * n, 0.0)


def armholes(surf, an, mask, at=0.012):
    for s in ("L", "R"):
        t, r, _u = an.along(surf.P, f"UpperArm_{s}")
        L = np.linalg.norm(np.subtract(*an.bone(f"UpperArm_{s}")))
        sel = mask & (r < 0.095 * an.s) & (t > -0.12) & (t < 0.25)
        seam(surf, sel, (t - at / L) * L, 0.0028, 0.0011, 0.74)


def elbow_folds(surf, an, mask):
    for s in ("L", "R"):
        h, _t = an.bone(f"ForeArm_{s}")
        d = surf.P - h
        dist = np.linalg.norm(d, axis=1)
        env = smooth(0.075, 0.02, dist)
        t, _r, u = an.along(surf.P, f"ForeArm_{s}")
        ang = np.arctan2(u[:, 2], u[:, 1])
        L = np.linalg.norm(np.subtract(*an.bone(f"ForeArm_{s}")))
        folds(surf, mask & (env > 0), t * L / 0.022 * 2 * np.pi + 2.2 * ang, env, 0.0032)


def tunic(surf, an, look):
    """Officer tunic: princess seams, side seams, set-in sleeves, centre back, welt chest
    slits, gathered folds at the belt, elbow folds, hem stitching."""
    P, N = surf.P, surf.N
    s = an.s
    um = surf.m("M_Uniform") & surf.p("Garment", "Skirt", "Collar")
    if not um.any():
        return
    fabric(surf, um)
    belt_z, neck_z = look["belt_z"], look["neck_z"]
    X, Z = P[:, 0], P[:, 2]
    ax = np.abs(X)
    torso = um & surf.p("Garment") & (Z > belt_z - 0.03) & (Z < neck_z + 0.01) & (ax < 0.2 * s)
    k = np.clip((Z - belt_z) / (neck_z - belt_z), 0, 1)
    ym = an.torso_mid_y(Z)
    fr = P[:, 1] < ym
    # princess seams, front and back
    xf = (0.072 + 0.028 * np.sin(np.pi * np.clip(k * 1.05, 0, 1)) + 0.018 * k**3) * s
    seam(surf, torso & fr & (k < 0.93), ax - xf, 0.0026, 0.001, 0.78, lap=0.0004)
    xb = (0.062 + 0.022 * np.sin(np.pi * np.clip(k, 0, 1)) + 0.02 * k**3) * s
    seam(surf, torso & ~fr & (k < 0.95), ax - xb, 0.0026, 0.001, 0.8, lap=0.0004)
    # centre back seam
    seam(surf, torso & ~fr, X, 0.0024, 0.0009, 0.8)
    # side seams (where the cloth turns from front to back)
    side = um & surf.p("Garment") & (Z > belt_z - 0.03) & (Z < neck_z - 0.06) & (ax > 0.09 * s)
    seam(surf, side & (np.abs(N[:, 0]) > 0.45), P[:, 1] - ym - 0.012, 0.0026, 0.001, 0.8)
    # set-in sleeves
    armholes(surf, an, um & surf.p("Garment") & (Z > belt_z))
    elbow_folds(surf, an, um)
    # welt chest slits (no flaps): a raised welt with a dark opening on top
    for sx in (1.0, -1.0):
        cx, cz = 0.093 * s * sx, 0.718 * an.ctx.H
        lx = (X - cx) * sx
        tilt = 0.12
        dz = Z - cz - tilt * lx
        within = band(lx, 0.048 * s, 0.002) * fr * (N[:, 1] < -0.3)
        welt = band(dz + 0.0068, 0.0066, 0.0014) * within
        slit = band(dz - 0.0006, 0.0021, 0.0012) * within
        surf.height += np.where(torso, 0.0014 * welt - 0.0018 * slit, 0.0)
        mul(surf, torso, (0.22, 0.22, 0.22), slit)
        mul(surf, torso, (0.86, 0.86, 0.86), welt * 0.6)
    # gathered folds just above and below the belt
    near = smooth(0.06, 0.012, np.abs(Z - belt_z))
    folds(surf, um & surf.p("Garment", "Skirt"), X / 0.03 * 2 * np.pi + 3 * fbm(P, 0.05, 1, 2),
          near * 0.8, 0.0024)
    # skirt hem stitching
    sk = um & surf.p("Skirt")
    if sk.any():
        z_hem = P[sk, 2].min()
        seam(surf, sk, Z - (z_hem + 0.014), 0.0016, 0.0006, 0.82)
        seam(surf, sk & ~fr, X, 0.0022, 0.0008, 0.82)  # back vent line
    # collar: top stitching
    cm = um & surf.p("Collar")
    if cm.any():
        z_top = P[cm, 2].max()
        seam(surf, cm, Z - (z_top - 0.007), 0.0016, 0.0006, 0.8)
        # the inside of the collar is in shadow
        cc = P[cm, :2].mean(axis=0)
        inward = ((P[:, :2] - cc) * N[:, :2]).sum(1) < 0
        mul(surf, cm & inward, (0.45, 0.45, 0.45))


def breeches(surf, an, look):
    tm = surf.m("M_Trousers")
    if not tm.any():
        return
    fabric(surf, tm)
    P = surf.P
    for s in ("L", "R"):
        for bone in (f"UpperLeg_{s}", f"LowerLeg_{s}"):
            t, r, u = an.along(P, bone)
            sel = tm & (t > -0.05) & (t < 1.05) & (r < 0.2)
            sel &= (P[:, 0] > 0) == (s == "L")
            out = u[:, 0] * (1 if s == "L" else -1)
            # outer seam: where the radial direction points straight outwards
            seam(surf, sel & (out > 0.2), u[:, 1] * 0.06, 0.0028, 0.001, 0.8)
            seam(surf, sel & (out < -0.2), u[:, 1] * 0.05, 0.0024, 0.0008, 0.84)  # inseam
        # folds where the breeches narrow to the knee and blouse over the boot
        kt = look["boot_top"]
        env = smooth(0.1, 0.0, np.abs(P[:, 2] - (kt + 0.06))) * ((P[:, 0] > 0) == (s == "L"))
        t, r, u = an.along(P, f"LowerLeg_{s}")
        ang = np.arctan2(u[:, 1], u[:, 0])
        folds(surf, tm, P[:, 2] / 0.026 * 2 * np.pi + 1.6 * np.sin(ang * 2), env, 0.0032)
    # seat seam
    seam(surf, tm & (P[:, 1] > an.torso_mid_y(P[:, 2])) & (P[:, 2] > an.ctx.crotch - 0.02),
         P[:, 0], 0.0024, 0.0008, 0.84)


def cuffs(surf, an):
    tm = surf.m("M_Trim") & surf.p("Garment")
    if not tm.any():
        return
    for s in ("L", "R"):
        t, _r, _u = an.along(surf.P, f"ForeArm_{s}")
        L = np.linalg.norm(np.subtract(*an.bone(f"ForeArm_{s}")))
        sel = tm & ((surf.P[:, 0] > 0) == (s == "L"))
        seam(surf, sel, (t - 0.955) * L, 0.0016, 0.0006, 0.75)
        seam(surf, sel, (t - 0.885) * L, 0.0016, 0.0006, 0.75)


def boots(surf, an, look, part="Boots", glossy=True):
    bm = surf.p(part)
    if not bm.any():
        return
    P = surf.P
    Z = P[:, 2]
    top = P[bm, 2].max()
    # sole and welt
    sole = smooth(0.016, 0.012, Z)
    mul(surf, bm, (0.55, 0.55, 0.55), sole)
    rough(surf, bm, 0.78, sole)
    seam(surf, bm, Z - 0.017, 0.0022, 0.0012, 0.6)
    # heel block (back of the foot below 30 mm)
    for c in (1.0, -1.0):
        ank = np.array(an.ctx.L["ankle"][:]) * np.array([c, 1, 1])
        heel = (P[:, 1] > ank[1] - 0.02) & (Z < 0.032) & ((P[:, 0] > 0) == (c > 0))
        seam(surf, bm & heel, Z - 0.03, 0.0018, 0.0009, 0.6)
        # toe cap line across the foot
        ball = np.array(an.ctx.L["ball"][:]) * np.array([c, 1, 1])
        dtoe = P[:, 1] - (ball[1] + 0.004) - 0.25 * np.abs(P[:, 0] - ball[0])
        sel = bm & (Z < 0.075) & ((P[:, 0] > 0) == (c > 0)) & (P[:, 1] < ball[1] + 0.03)
        seam(surf, sel, dtoe, 0.0018, 0.0008, 0.7)
        # ankle creases on the front
        front = P[:, 1] < ank[1] - 0.02
        env = smooth(0.06, 0.0, np.abs(Z - 0.13)) * front * ((P[:, 0] > 0) == (c > 0))
        folds(surf, bm, Z / 0.016 * 2 * np.pi + 2 * np.sin(P[:, 0] * 60), env, 0.0012, 2.5)
        # back seam of the shaft
        back = bm & (Z > 0.09) & (P[:, 1] > ank[1]) & ((P[:, 0] > 0) == (c > 0))
        seam(surf, back, P[:, 0] - ank[0], 0.0018, 0.0008, 0.7)
    # stitched band at the top of the shaft
    rim = band(Z - (top - 0.012), 0.009, 0.002)
    surf.height += np.where(bm, 0.0006 * rim, 0.0)
    rough(surf, bm, 0.32, rim)
    seam(surf, bm, Z - (top - 0.022), 0.0014, 0.0006, 0.7)
    if glossy:
        # polish: faint mottling only
        surf.albedo[bm] *= (0.9 + 0.1 * fbm(P[bm], 0.02, 2, 41))[:, None]


def belt(surf, part="Belt", leather="M_Belt", buckle="M_RankPlate", grooves=2):
    pm = surf.p(part)
    if not pm.any():
        return
    P = surf.P
    lm = pm & surf.m(leather)
    if lm.any():
        z0, z1 = P[lm, 2].min(), P[lm, 2].max()
        zc = 0.5 * (z0 + z1)
        hw = 0.5 * (z1 - z0)
        for sgn in (1, -1):
            seam(surf, lm, P[:, 2] - zc - sgn * (hw - 0.005), 0.0011, 0.0005, 0.55)
        surf.albedo[lm] *= (0.9 + 0.1 * fbm(P[lm], 0.006, 2, 51))[:, None]
        rough(surf, lm, 0.5, 0.5 * fbm(P, 0.01, 2, 52))
    bk = pm & surf.m(buckle)
    if bk.any():
        c = P[bk].mean(axis=0)
        dz = P[:, 2] - c[2]
        h = 0.5 * (P[bk, 2].max() - P[bk, 2].min())
        for k in range(grooves):
            off = (k - (grooves - 1) / 2) * (2 * h / (grooves + 1))
            seam(surf, bk, dz - off, 0.0022, 0.0009, 0.55)
        # brushed horizontally
        surf.albedo[bk] *= (0.88 + 0.12 * fbm(P[bk] * np.array([0.1, 1, 6.0]), 0.002, 2, 61))[
            :, None
        ]


def cap(surf, an):
    cm = surf.p("Cap") & surf.m("M_Cap")
    if not cm.any():
        return
    P, N = surf.P, surf.N
    fabric(surf, cm)
    z_top = P[cm, 2].max()
    c = P[cm].mean(axis=0)
    zb = P[cm, 2].min()
    # piping round the crown edge, seams of the crown panels
    rim = band(P[:, 2] - (z_top - 0.006), 0.0028, 0.0015) * (N[:, 2] < 0.85)
    surf.height += np.where(cm, 0.0012 * rim, 0.0)
    mul(surf, cm, (0.8, 0.8, 0.8), rim)
    # side seams of the crown wall
    ang = np.arctan2(P[:, 1] - c[1], P[:, 0] - c[0])
    wall = cm & (N[:, 2] < 0.85) & (P[:, 2] > zb + 0.045 * an.s)
    for a0 in (0.0, np.pi):
        seam(surf, wall, np.sin(ang - a0) * 0.1, 0.0016, 0.0006, 0.84)
    # the band: a little darker, stitched at its top; a chin strap across the front
    band_z = zb + 0.042 * an.s
    in_band = cm & (P[:, 2] < band_z) & (N[:, 2] < 0.6)
    mul(surf, in_band, (0.82, 0.82, 0.82))
    seam(surf, cm & (N[:, 2] < 0.6), P[:, 2] - band_z, 0.0018, 0.0008, 0.75)
    front = P[:, 1] < c[1] - 0.05
    strap = band(P[:, 2] - (zb + 0.017 * an.s), 0.0035, 0.001) * front * (N[:, 2] < 0.6)
    surf.height += np.where(cm, 0.0009 * strap, 0.0)
    mul(surf, cm, (0.22, 0.22, 0.22), strap)
    rough(surf, cm, 0.28, strap)
    # visor: the faces below the band's bottom edge in front, a stiffer, darker finish
    visor = cm & (P[:, 2] < zb + 0.006) & (P[:, 1] < c[1] - 0.06)
    mul(surf, visor, (0.7, 0.7, 0.7))
    rough(surf, visor, 0.3)
    # badge bar
    bd = surf.p("Cap") & surf.m("M_RankPlate")
    if bd.any():
        bc = P[bd].mean(axis=0)
        seam(surf, bd, P[:, 2] - bc[2] - 0.0025, 0.0009, 0.0005, 0.6)
        seam(surf, bd, P[:, 2] - bc[2] + 0.0025, 0.0009, 0.0005, 0.6)


def rank_plate(surf):
    pm = surf.p("RankPlate") & surf.m("M_RankPlate")
    if not pm.any():
        return
    P = surf.P
    rough(surf, pm, 0.42, fbm(P * np.array([0.08, 1, 6.0]), 0.0015, 2, 72))
    surf.albedo[pm] *= (0.86 + 0.14 * fbm(P[pm] * np.array([0.08, 1, 6.0]), 0.0015, 2, 71))[
        :, None
    ]


def hands(surf, an, mat="M_Skin"):
    hm = surf.m(mat) & (surf.P[:, 2] < an.neck_z - 0.1)
    if not hm.any():
        return
    P = surf.P
    for s in ("L", "R"):
        t, _r, u = an.along(P, f"Fingers_{s}")
        sel = hm & ((P[:, 0] > 0) == (s == "L"))
        # knuckles a touch redder
        kn = smooth(0.25, 0.0, np.abs(t)) * (u[:, 2] > 0.2)
        mul(surf, sel, (1.0, 0.86, 0.84), 0.35 * kn)
        rough(surf, sel, 0.6, kn)
    mul(surf, hm, (0.97, 0.96, 0.95), fbm(P, 0.01, 2, 81))


# -------------------------------------------------------------------- characters


def officer(ctx):
    an = Anatomy(ctx)
    look = ctx.look
    female = look["female"]

    def paint(surf):
        face(surf, an, beard=not female)
        eyes(surf, an)
        hair(surf, an, female)
        hands(surf, an)
        tunic(surf, an, look)
        breeches(surf, an, look)
        cuffs(surf, an)
        boots(surf, an, look)
        belt(surf)
        cap(surf, an)
        rank_plate(surf)

    return paint


def density(ctx):
    """Texel density per face: the face and hair get the most, soles the least."""
    head_z = ctx.L["neck"].z + 0.03 * ctx.s

    def w(o, f, part):
        z = f.calc_center_median().z
        n = f.normal
        k = 1.0
        if part in ("Eyes",):
            k = 3.0
        elif z > head_z or part in ("Cap", "Bun", "Helmet", "Visor"):
            k = 2.3
        elif part in ("RankPlate", "CollarPin", "ChestBox"):
            k = 2.0
        elif part in ("Belt",):
            k = 1.3
        elif z < 0.06:
            k = 0.7
        if n.z < -0.6:
            k *= 0.35
        return k

    return w
