"""What the Sovereign's atlas shows: an aged pale face, black velvet, embroidered gold."""

from __future__ import annotations

import numpy as np

from characters import looks as LK
from characters.paint import band, fbm, groove, mul, rough, smooth


def aged_face(surf, an):
    """Deep lines on a pale face: forehead, crow's feet, nasolabial folds, sunken eyes."""
    P, N = surf.P, surf.N
    sk = surf.m("M_Skin") & (P[:, 2] > an.neck_z + 0.01)
    if not sk.any():
        return
    f = an.face
    X, Z = P[:, 0], P[:, 2] - an.ez
    ax = np.abs(X)
    front = smooth(-0.05, -0.35, N[:, 1])
    # pallor: cool, slightly grey, blotchy
    mul(surf, sk, (0.92, 0.9, 0.92), 0.6 * fbm(P, 0.012, 3, 41))
    # brows: thin and grey, not the painted dark arches of the young crew
    bx = (ax - (an.ex + 0.002)) / (0.022 * an.s)
    arch = f["brow"] + 0.0045 * (1.0 - bx * bx)
    brow = band(Z - arch, 0.005, 0.002) * (np.abs(bx) < 1.25) * front
    grey = np.array([0.5, 0.48, 0.47])
    a = np.where(sk, brow, 0.0)[:, None]
    surf.albedo = surf.albedo * (1 - a) + a * grey * (0.8 + 0.2 * fbm(P, 0.003, 2, 7))[:, None]
    # forehead: four long furrows
    for k in range(4):
        zc = 0.032 + 0.011 * k + 0.002 * np.sin(X * 60 + k)
        g = groove(Z - zc, 0.0016) * smooth(0.055, 0.03, ax) * front
        mul(surf, sk, (0.5, 0.44, 0.45), 0.85 * g)
        surf.height += np.where(sk, -0.0016 * g, 0.0)
    # crow's feet: short rays from the outer eye corner
    u = ax - (an.ex + 0.017)
    for k in range(3):
        ray = groove(Z - (k - 1) * 0.006 - 0.25 * u * (k - 1), 0.0011)
        g = ray * (u > 0) * (u < 0.018) * front
        mul(surf, sk, (0.66, 0.6, 0.6), 0.7 * g)
        surf.height += np.where(sk, -0.0011 * g, 0.0)
    # sunken eyes and bags under them
    sock = np.exp(-(((ax - an.ex) / 0.022) ** 2 + ((Z + 0.004) / 0.016) ** 2))
    mul(surf, sk, (0.55, 0.47, 0.5), 0.7 * sock * front)
    bag = band(Z + 0.016 + 0.08 * (ax - an.ex) ** 2 * 50, 0.002, 0.002)
    bag *= np.abs(ax - an.ex) < 0.016
    surf.height += np.where(sk, -0.0006 * bag * front, 0.0)
    # nasolabial folds: from beside the nose to past the mouth corners
    zz = np.clip((Z - f["nose_base"]) / (f["mouth"] - 0.02 - f["nose_base"]), 0, 1)
    xf = 0.019 + 0.012 * zz
    nl = groove(ax - xf, 0.0025) * (Z < f["nose_base"] + 0.004) * (Z > f["mouth"] - 0.02) * front
    mul(surf, sk, (0.6, 0.52, 0.52), 0.85 * nl)
    surf.height += np.where(sk, -0.0022 * nl, 0.0)
    # age spots on the temples and the scalp line
    spots = np.clip((fbm(P, 0.006, 2, 17) - 0.62) * 6, 0, 1) * smooth(0.04, 0.07, ax)
    mul(surf, sk, (0.72, 0.62, 0.55), 0.6 * spots)
    # thin, bloodless lips
    lips = band(Z - f["mouth"], 0.006, 0.002) * (ax < f["mouth_hw"] * an.s)
    mul(surf, sk, (0.82, 0.78, 0.8), 0.6 * lips * front)
    rough(surf, sk, 0.6, 0.5 * front)


def velvet(surf, mask, seed=0):
    """Black velvet: soft pile noise, rubbed highlights on the fold crests."""
    if not mask.any():
        return
    n = fbm(surf.P, 0.003, 2, 61 + seed)
    surf.albedo[mask] *= (0.9 + 0.2 * n[mask])[:, None]
    big = fbm(surf.P, 0.09, 2, 71 + seed)
    surf.albedo[mask] *= (0.85 + 0.3 * big[mask])[:, None]
    surf.height += np.where(mask, 0.00015 * n, 0.0)


def embroidery(surf, mask):
    """Gold embroidery: a raised diamond lattice with dark gaps, worn bright on the ridges."""
    if not mask.any():
        return
    P = surf.P
    a = (P[:, 0] + P[:, 2]) / 0.018
    b = (P[:, 1] - P[:, 2] + P[:, 0] * 0.3) / 0.018
    da = np.abs(a - np.round(a))
    db = np.abs(b - np.round(b))
    line = np.clip(1.0 - np.minimum(da, db) / 0.12, 0, 1)
    dots = np.exp(-((da - 0.5) ** 2 + (db - 0.5) ** 2) / 0.01)
    relief = np.clip(line + 0.8 * dots, 0, 1)
    surf.height += np.where(mask, 0.0007 * relief, 0.0)
    mul(surf, mask, (0.45, 0.4, 0.34), 1.0 - relief)
    rough(surf, mask, 0.22, relief)
    rough(surf, mask, 0.55, 1.0 - relief)
    wear = fbm(P, 0.02, 2, 91)
    mul(surf, mask, (1.08, 1.04, 0.96), 0.4 * wear)


def sovereign(ctx):
    an = LK.Anatomy(ctx)
    look = ctx.look

    def paint(surf):
        LK.face(surf, an, beard=False)
        aged_face(surf, an)
        LK.hands(surf, an)
        velvet(surf, surf.m("M_SovRobe"), 0)
        velvet(surf, surf.m("M_SovCloak"), 1)
        velvet(surf, surf.m("M_SovLining"), 2)
        embroidery(surf, surf.m("M_SovTrim") & ~surf.p("Clasp", "Belt"))
        LK.boots(surf, an, look)
        LK.belt(surf, buckle="M_SovTrim")

    return paint
