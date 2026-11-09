"""The grade LUT that carries the AgX view transform into Unreal (pure Python).

`M_Verse_PostTonemap` (replacing the tonemapper) encodes scene-linear colour
per channel as `u = (log2(c / 0.18) - EV_MIN) / (EV_MAX - EV_MIN)`, clamped
to 0..1, and samples `T_Verse_Grade_LUT_M`: a 32^3 lattice laid out as a
1024 x 32 strip of 32 slices (slice = blue, x in a slice = red, y = green).
Each texel holds the AgX output of Blender itself (sRGB display, base look)
for the lattice point, so the LUT is AgX by construction; only the lattice
interpolation and 8-bit storage differ (A14.4 measures the error).
"""

from __future__ import annotations

import math
from collections.abc import Sequence

SIZE = 32
EV_MIN = -12.47393
EV_MAX = 6.0
MIDDLE_GREY = 0.18
STRIP_WIDTH = SIZE * SIZE
STRIP_HEIGHT = SIZE

#: A 24-patch reflectance chart, sRGB 8-bit (18 colours, then 6 greys).
CHART_SRGB8: tuple[tuple[int, int, int], ...] = (
    (115, 82, 68), (194, 150, 130), (98, 122, 157), (87, 108, 67), (133, 128, 177),
    (103, 189, 170), (214, 126, 44), (80, 91, 166), (193, 90, 99), (94, 60, 108),
    (157, 188, 64), (224, 163, 46), (56, 61, 150), (70, 148, 73), (175, 54, 60),
    (231, 199, 31), (187, 86, 149), (8, 133, 161), (243, 243, 242), (200, 200, 200),
    (160, 160, 160), (122, 122, 121), (85, 85, 85), (52, 52, 52),
)  # fmt: skip


def srgb_to_linear(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def linear_to_srgb(c: float) -> float:
    c = max(0.0, c)
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def chart_linear(exposure: float = 1.0) -> list[tuple[float, float, float]]:
    """Scene-linear values of the chart patches (reflectance times `exposure`)."""
    return [tuple(exposure * srgb_to_linear(v / 255.0) for v in p) for p in CHART_SRGB8]


def encode(c: float) -> float:
    """Scene-linear channel -> lattice coordinate 0..1 (log2 around middle grey)."""
    ev = math.log2(max(c, 1e-10) / MIDDLE_GREY)
    return min(1.0, max(0.0, (ev - EV_MIN) / (EV_MAX - EV_MIN)))


def decode(u: float) -> float:
    return MIDDLE_GREY * 2.0 ** (EV_MIN + u * (EV_MAX - EV_MIN))


def lattice_value(i: int) -> float:
    return decode(i / (SIZE - 1))


def strip_texel(x: int, y: int) -> tuple[int, int, int]:
    """Strip pixel (x, y counted from the top row) -> lattice indices (r, g, b)."""
    return x % SIZE, y, x // SIZE


def sample(strip: Sequence[Sequence[Sequence[float]]], rgb: Sequence[float]) -> tuple:
    """Trilinear lookup in `strip[y][x] = (r, g, b)` (display 0..1), as the shader does it."""
    coords = [encode(c) * (SIZE - 1) for c in rgb]
    lo = [min(int(math.floor(c)), SIZE - 2) for c in coords]
    t = [c - i for c, i in zip(coords, lo, strict=True)]
    out = [0.0, 0.0, 0.0]
    for dr in (0, 1):
        for dg in (0, 1):
            for db in (0, 1):
                w = (
                    (t[0] if dr else 1 - t[0])
                    * (t[1] if dg else 1 - t[1])
                    * (t[2] if db else 1 - t[2])
                )
                r, g, b = lo[0] + dr, lo[1] + dg, lo[2] + db
                px = strip[g][b * SIZE + r]
                for k in range(3):
                    out[k] += w * px[k]
    return tuple(out)


# --------------------------------------------------------------------------
# Colour difference (CIEDE2000) of sRGB display values
# --------------------------------------------------------------------------


def srgb_to_lab(rgb: Sequence[float]) -> tuple[float, float, float]:
    r, g, b = (srgb_to_linear(min(1.0, max(0.0, c))) for c in rgb)
    x = (0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / 0.95047
    y = 0.2126729 * r + 0.7151522 * g + 0.0721750 * b
    z = (0.0193339 * r + 0.1191920 * g + 0.9503041 * b) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 216 / 24389 else (24389 / 27 * t + 16) / 116

    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def ciede2000(lab1: Sequence[float], lab2: Sequence[float]) -> float:
    l1, a1, b1 = lab1
    l2, a2, b2 = lab2
    c1, c2 = math.hypot(a1, b1), math.hypot(a2, b2)
    cbar = (c1 + c2) / 2
    g = 0.5 * (1 - math.sqrt(cbar**7 / (cbar**7 + 25**7)))
    a1p, a2p = (1 + g) * a1, (1 + g) * a2
    c1p, c2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360 if c1p else 0.0
    h2p = math.degrees(math.atan2(b2, a2p)) % 360 if c2p else 0.0
    dlp = l2 - l1
    dcp = c2p - c1p
    if c1p * c2p == 0:
        dhp = 0.0
    elif abs(h2p - h1p) <= 180:
        dhp = h2p - h1p
    elif h2p - h1p > 180:
        dhp = h2p - h1p - 360
    else:
        dhp = h2p - h1p + 360
    big_dh = 2 * math.sqrt(c1p * c2p) * math.sin(math.radians(dhp / 2))
    lbar = (l1 + l2) / 2
    cbarp = (c1p + c2p) / 2
    if c1p * c2p == 0:
        hbarp = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        hbarp = (h1p + h2p) / 2
    elif h1p + h2p < 360:
        hbarp = (h1p + h2p + 360) / 2
    else:
        hbarp = (h1p + h2p - 360) / 2
    t = (
        1
        - 0.17 * math.cos(math.radians(hbarp - 30))
        + 0.24 * math.cos(math.radians(2 * hbarp))
        + 0.32 * math.cos(math.radians(3 * hbarp + 6))
        - 0.20 * math.cos(math.radians(4 * hbarp - 63))
    )
    dtheta = 30 * math.exp(-(((hbarp - 275) / 25) ** 2))
    rc = 2 * math.sqrt(cbarp**7 / (cbarp**7 + 25**7))
    sl = 1 + 0.015 * (lbar - 50) ** 2 / math.sqrt(20 + (lbar - 50) ** 2)
    sc = 1 + 0.045 * cbarp
    sh = 1 + 0.015 * cbarp * t
    rt = -math.sin(math.radians(2 * dtheta)) * rc
    return math.sqrt(
        (dlp / sl) ** 2 + (dcp / sc) ** 2 + (big_dh / sh) ** 2 + rt * (dcp / sc) * (big_dh / sh)
    )


def delta_e(rgb1: Sequence[float], rgb2: Sequence[float]) -> float:
    return ciede2000(srgb_to_lab(rgb1), srgb_to_lab(rgb2))
