"""Hangar floor: painted markings and grime as world-space masks, and the deck material.

The deck paint (landing ring, chevrons, hazard bands, lane lines, stencilled
words) and the grime (tyre tracks, oil, wall-base dirt, foot polish) are
rasterised here with numpy into two mask textures that cover the whole deck in
world space. The floor shader thresholds the bilinear mask with a little noise,
so paint edges stay crisp at any plate density and wear like real deck paint.

Masks (``.cache/hangar/``, RGBA 8 bit, Non-Color, 40 px/m):

* ``T_HangarPaint_M``  R white paint, G yellow paint, B red paint
* ``T_HangarGrime_M``  R dirt / tyre rubber, G oil, B foot-traffic polish

Everything is deterministic: shapes come from the layout, scatter from a
seeded numpy generator.
"""

from __future__ import annotations

import math
from pathlib import Path

import bpy
import hangar_layout as L
import numpy as np
from lib import materials

PPM = 40  # mask pixels per metre
EXTENT = (-1.0, -64.0, 101.0, 1.0)  # Blender x0, y0, x1, y1 covered by the masks
CACHE = Path(__file__).resolve().parents[2] / ".cache" / "hangar"
FONT_PATHS = ("C:/Windows/Fonts/ARIALNB.TTF", "C:/Windows/Fonts/arialbd.ttf")

WHITE, YELLOW, RED = 0, 1, 2
DIRT, OIL, POLISH = 0, 1, 2


# --------------------------------------------------------------------------
# Rasteriser
# --------------------------------------------------------------------------


class Canvas:
    """Float mask over the deck; shapes are given in plan (x, z) metres."""

    def __init__(self, channels: int = 3):
        x0, y0, x1, y1 = EXTENT
        self.x0, self.y0 = x0, y0
        self.w = int(round((x1 - x0) * PPM))
        self.h = int(round((y1 - y0) * PPM))
        self.data = np.zeros((self.h, self.w, channels), dtype=np.float32)

    # -- windows -------------------------------------------------------

    def _window(self, xs, ys, pad: float):
        """Pixel window around Blender-space extents, with sample coordinates."""
        c0 = max(0, int((min(xs) - pad - self.x0) * PPM))
        c1 = min(self.w, int((max(xs) + pad - self.x0) * PPM) + 2)
        r0 = max(0, int((min(ys) - pad - self.y0) * PPM))
        r1 = min(self.h, int((max(ys) + pad - self.y0) * PPM) + 2)
        if c1 <= c0 or r1 <= r0:
            return None
        px = self.x0 + (np.arange(c0, c1, dtype=np.float64) + 0.5) / PPM
        py = self.y0 + (np.arange(r0, r1, dtype=np.float64) + 0.5) / PPM
        gx, gy = np.meshgrid(px, py)
        return (slice(r0, r1), slice(c0, c1)), gx, gy

    def _apply(self, window, cov, channel: int, value: float, mode: str) -> None:
        target = self.data[window[0], window[1], channel]
        if mode == "max":
            np.maximum(target, cov * value, out=target)
        elif mode == "add":
            target += cov * value
            np.clip(target, 0.0, 1.0, out=target)
        elif mode == "erase":
            target *= 1.0 - cov
        else:
            raise ValueError(mode)

    @staticmethod
    def _cov(sd, soft: float):
        """Coverage from a signed distance (metres, negative inside)."""
        width = max(soft, 1.0 / PPM)
        return np.clip(0.5 - sd / width, 0.0, 1.0).astype(np.float32)

    # -- shapes (plan coordinates) --------------------------------------

    def polygon(self, pts, channel, value=1.0, soft=0.0, mode="max", pattern=None):
        """Any simple polygon (plan points, any winding)."""
        bp = [(x, -z) for x, z in pts]
        found = self._window([p[0] for p in bp], [p[1] for p in bp], soft + 2.0 / PPM)
        if found is None:
            return
        window, gx, gy = found
        sd = _polygon_sdf(gx, gy, bp)
        cov = self._cov(sd, soft)
        if pattern is not None:
            cov = cov * pattern(gx, -gy)
        self._apply(window, cov, channel, value, mode)

    def rect(self, x0, x1, z0, z1, channel, value=1.0, soft=0.0, mode="max", pattern=None):
        self.polygon([(x0, z0), (x1, z0), (x1, z1), (x0, z1)], channel, value, soft, mode, pattern)

    def outline(self, x0, x1, z0, z1, width, channel, value=1.0):
        h = width / 2
        self.rect(x0 - h, x1 + h, z0 - h, z0 + h, channel, value)
        self.rect(x0 - h, x1 + h, z1 - h, z1 + h, channel, value)
        self.rect(x0 - h, x0 + h, z0 - h, z1 + h, channel, value)
        self.rect(x1 - h, x1 + h, z0 - h, z1 + h, channel, value)

    def bar(self, a, b, width, channel, value=1.0, soft=0.0, mode="max"):
        """Straight painted bar from plan point a to b (square ends)."""
        (ax, az), (bx, bz) = a, b
        length = math.hypot(bx - ax, bz - az)
        if length < 1e-6:
            return
        nx, nz = -(bz - az) / length * width / 2, (bx - ax) / length * width / 2
        self.polygon(
            [(ax + nx, az + nz), (bx + nx, bz + nz), (bx - nx, bz - nz), (ax - nx, az - nz)],
            channel,
            value,
            soft,
            mode,
        )

    def ring(self, cx, cz, r, width, channel, value=1.0, soft=0.0, a0=None, a1=None):
        reach = r + width
        found = self._window([cx - reach, cx + reach], [-cz - reach, -cz + reach], soft)
        if found is None:
            return
        window, gx, gy = found
        dist = np.hypot(gx - cx, gy + cz)
        sd = np.abs(dist - r) - width / 2
        cov = self._cov(sd, soft)
        if a0 is not None:
            ang = np.degrees(np.arctan2(-(gy + cz), gx - cx)) % 360.0
            cov = cov * (((ang - a0) % 360.0) <= ((a1 - a0) % 360.0))
        self._apply(window, cov, channel, value, "max")

    def disc(self, cx, cz, r, channel, value=1.0, soft=0.0, mode="max"):
        found = self._window([cx - r, cx + r], [-cz - r, -cz + r], soft + 2.0 / PPM)
        if found is None:
            return
        window, gx, gy = found
        sd = np.hypot(gx - cx, gy + cz) - r
        self._apply(window, self._cov(sd, soft), channel, value, mode)

    def blob(self, cx, cz, rx, rz, channel, value=1.0, angle=0.0, mode="max"):
        """Soft gaussian stain."""
        found = self._window(
            [cx - 2.2 * max(rx, rz), cx + 2.2 * max(rx, rz)],
            [-cz - 2.2 * max(rx, rz), -cz + 2.2 * max(rx, rz)],
            0.0,
        )
        if found is None:
            return
        window, gx, gy = found
        ca, sa = math.cos(math.radians(angle)), math.sin(math.radians(angle))
        dx, dz = gx - cx, -gy - cz
        u, v = dx * ca + dz * sa, -dx * sa + dz * ca
        cov = np.exp(-0.5 * ((u / rx) ** 2 + (v / rz) ** 2)).astype(np.float32)
        self._apply(window, cov, channel, value, mode)

    def track(self, points, width, channel, value=1.0, soft=0.15):
        """Soft stroke along a plan polyline (tyre rubber, foot traffic)."""
        for a, b in zip(points[:-1], points[1:], strict=False):
            self.bar(a, b, width, channel, value, soft)

    def text(self, body, x, z, height, channel, value=1.0, align="center", rot=0.0):
        """Stencil a word on the deck: glyph tops point away from the camera."""
        tris = _text_triangles(body)
        if not tris:
            return
        xs = [p[0] for t in tris for p in t]
        ys = [p[1] for t in tris for p in t]
        gx0, gx1, gy0, gy1 = min(xs), max(xs), min(ys), max(ys)
        scale = height / max(gy1 - gy0, 1e-6)
        ox = {"center": (gx0 + gx1) / 2, "left": gx0, "right": gx1}[align]
        oy = (gy0 + gy1) / 2
        ca, sa = math.cos(math.radians(rot)), math.sin(math.radians(rot))
        placed = []
        for tri in tris:
            pts = []
            for px, py in tri:
                u, v = (px - ox) * scale, (py - oy) * scale
                # glyph +y points toward the far wall (plan -z)
                pts.append((x + u * ca - v * sa, z - (u * sa + v * ca)))
            placed.append(pts)
        # Sum the triangle coverages of one word so shared edges do not seam.
        bx = [p[0] for t in placed for p in t]
        by = [-p[1] for t in placed for p in t]
        found = self._window(bx, by, 2.0 / PPM)
        if found is None:
            return
        window, gx, gy = found
        acc = np.zeros(gx.shape, dtype=np.float32)
        for tri in placed:
            bp = [(px, -pz) for px, pz in tri]
            tx = [p[0] for p in bp]
            ty = [p[1] for p in bp]
            sub = (
                (gx[0] >= min(tx) - 0.1) & (gx[0] <= max(tx) + 0.1),
                (gy[:, 0] >= min(ty) - 0.1) & (gy[:, 0] <= max(ty) + 0.1),
            )
            cols = np.nonzero(sub[0])[0]
            rows = np.nonzero(sub[1])[0]
            if not len(cols) or not len(rows):
                continue
            rs, cs = slice(rows[0], rows[-1] + 1), slice(cols[0], cols[-1] + 1)
            sd = _polygon_sdf(gx[rs, cs], gy[rs, cs], bp)
            acc[rs, cs] += self._cov(sd, 0.0)
        np.clip(acc, 0.0, 1.0, out=acc)
        self._apply(window, acc, channel, value, "max")

    # -- output ----------------------------------------------------------

    def to_image(self, name: str) -> bpy.types.Image:
        CACHE.mkdir(parents=True, exist_ok=True)
        rgba = np.ones((self.h, self.w, 4), dtype=np.float32)
        rgba[:, :, : self.data.shape[2]] = np.clip(self.data, 0.0, 1.0)
        image = bpy.data.images.get(name)
        if image is not None:
            bpy.data.images.remove(image)
        image = bpy.data.images.new(name, self.w, self.h, alpha=True, float_buffer=False)
        image.colorspace_settings.name = "Non-Color"
        image.pixels.foreach_set(rgba.ravel())
        image.filepath_raw = str(CACHE / f"{name}.png")
        image.file_format = "PNG"
        image.save()
        image.colorspace_settings.name = "Non-Color"
        return image


def _polygon_sdf(gx, gy, pts):
    """Signed distance to a simple polygon (Blender XY points), negative inside."""
    best = np.full(gx.shape, np.inf)
    inside = np.zeros(gx.shape, dtype=bool)
    n = len(pts)
    for i in range(n):
        ax, ay = pts[i]
        bx, by = pts[(i + 1) % n]
        ex, ey = bx - ax, by - ay
        wx, wy = gx - ax, gy - ay
        denom = ex * ex + ey * ey
        t = np.clip((wx * ex + wy * ey) / denom, 0.0, 1.0) if denom > 0 else 0.0
        dx, dy = wx - ex * t, wy - ey * t
        np.minimum(best, dx * dx + dy * dy, out=best)
        if ay != by:
            crosses = ((ay > gy) != (by > gy)) & (gx < ax + (gy - ay) * ex / ey)
            inside ^= crosses
    return np.sqrt(best) * np.where(inside, -1.0, 1.0)


def _text_triangles(body: str) -> list[list[tuple[float, float]]]:
    """Triangles of a word set in the stencil font (font units, y up)."""
    font = None
    for path in FONT_PATHS:
        if Path(path).is_file():
            font = bpy.data.fonts.load(path, check_existing=True)
            break
    curve = bpy.data.curves.new("TMP_hangar_text", "FONT")
    curve.body = body
    if font is not None:
        curve.font = font
    curve.align_x = "LEFT"
    curve.space_character = 1.06
    obj = bpy.data.objects.new("TMP_hangar_text", curve)
    bpy.context.scene.collection.objects.link(obj)
    try:
        depsgraph = bpy.context.evaluated_depsgraph_get()
        evaluated = obj.evaluated_get(depsgraph)
        mesh = evaluated.to_mesh()
        mesh.calc_loop_triangles()
        tris = [
            [(mesh.vertices[i].co.x, mesh.vertices[i].co.y) for i in tri.vertices]
            for tri in mesh.loop_triangles
        ]
        evaluated.to_mesh_clear()
    finally:
        bpy.data.objects.remove(obj)
        bpy.data.curves.remove(curve)
    return tris


def _stripes(period: float, duty: float = 0.5, angle_deg: float = 45.0):
    """Diagonal hazard stripe pattern (1 on the painted stripe)."""
    ca, sa = math.cos(math.radians(angle_deg)), math.sin(math.radians(angle_deg))

    def pattern(x, z):
        t = (x * ca + z * sa) / period
        f = t - np.floor(t)
        return (f < duty).astype(np.float32)

    return pattern


# --------------------------------------------------------------------------
# The deck's markings
# --------------------------------------------------------------------------


def paint_markings() -> Canvas:
    """Deck paint, kept sparse: one bay number, thin worn edge bands, one pad ring.

    Art direction: large painted words read as game UI; hazard stripes only as
    thin worn bands on edges. Values below 1 leave the paint thinner.
    """
    c = Canvas(3)
    dx0, dx1 = L.DOOR_X
    # Door threshold: one thin worn hazard band and a hold line.
    c.rect(dx0 - 0.6, dx1 + 0.6, 3.3, 3.72, YELLOW, 0.9, pattern=_stripes(0.5, 0.5, 45.0))
    c.rect(dx0 - 0.6, dx1 + 0.6, 4.45, 4.57, WHITE, 0.85)
    # The one bay number of the hall.
    c.text("04", 9.6, 5.4, 0.9, WHITE, 0.6)
    _paint_well(c)
    _paint_pad(c)
    _paint_walkway(c)
    _paint_cargo(c)
    _paint_stores(c)
    # Transverse vehicle lane: one dashed edge line.
    for x in np.arange(4.0, 96.0, 3.6):
        c.rect(x, x + 1.8, 45.5, 45.62, YELLOW, 0.85)
    return c


def _paint_well(c: Canvas) -> None:
    x0, x1, z0, z1 = L.WELL
    k = 0.45  # kerb width
    band = 0.16
    stripes = _stripes(0.5, 0.5, 45.0)
    for a, b, za, zb in (
        (x0 - k - band, x1 + k + band, z0 - k - band, z0 - k),
        (x0 - k - band, x1 + k + band, z1 + k, z1 + k + band),
    ):
        c.rect(a, b, za, zb, YELLOW, 0.6, pattern=stripes)
    for a, b in ((x0 - k - band, x0 - k), (x1 + k, x1 + k + band)):
        c.rect(a, b, z0 - k, z1 + k, YELLOW, 0.6, pattern=stripes)
    # Small corner brackets a pace outside the band.
    for cx, cz, sx, sz in (
        (x0 - 1.6, z0 - 1.6, 1, 1),
        (x1 + 1.6, z0 - 1.6, -1, 1),
        (x0 - 1.6, z1 + 1.6, 1, -1),
        (x1 + 1.6, z1 + 1.6, -1, -1),
    ):
        c.bar((cx, cz), (cx + 1.2 * sx, cz), 0.14, WHITE, 0.85)
        c.bar((cx, cz), (cx, cz + 1.2 * sz), 0.14, WHITE, 0.85)


def _paint_pad(c: Canvas) -> None:
    """One clean landing ring and four corner marks."""
    cx, cz = L.PAD_C
    r = L.PAD_R
    c.ring(cx, cz, r, 0.3, WHITE, 0.9)
    s = r + 1.6
    for sx in (-1, 1):
        for sz in (-1, 1):
            px, pz = cx + sx * s, cz + sz * s
            c.bar((px, pz), (px - sx * 1.6, pz), 0.18, WHITE, 0.85)
            c.bar((px, pz), (px, pz - sz * 1.6), 0.18, WHITE, 0.85)
    # Fuel hydrant no-stand squares: thin red outlines only.
    for hx in (cx - 9.6, cx + 9.6):
        c.outline(hx - 0.9, hx + 0.9, 26.7, 28.5, 0.06, RED, 0.85)


def _paint_walkway(c: Canvas) -> None:
    x0, x1 = L.WALKWAY_X
    z0, z1 = L.WALKWAY_Z
    c.rect(x0 - 0.1, x0, z0, z1, WHITE, 0.85)
    c.rect(x1, x1 + 0.1, z0, z1, WHITE, 0.85)
    c.rect(x0, x1, z0, z0 + 0.12, WHITE, 0.85)


def _paint_cargo(c: Canvas) -> None:
    x0, x1, z0, z1 = L.CARGO
    for row, cx in enumerate(cargo_row_centres()):
        for sz0, sz1 in cargo_slots():
            c.outline(cx - 1.35, cx + 1.35, sz0, sz1, 0.05, YELLOW, 0.75)
        c.text(f"C{row + 1}", cx, z1 - 0.7, 0.4, WHITE, 0.75)


def cargo_row_centres() -> list[float]:
    """Plan x of each container row (aisles 3.6 m between double rows)."""
    return [70.6, 73.2, 79.2, 81.8, 87.6, 90.2]


def cargo_slots() -> list[tuple[float, float]]:
    """Plan z spans of the container slots in every row."""
    return [(6.6, 12.8), (13.6, 19.8), (20.6, 26.8), (27.6, 33.8), (34.6, 40.8)]


def _paint_stores(c: Canvas) -> None:
    x0, _, z0, _ = L.STORES
    for i in range(6):
        bx = x0 + 1.2 + i * 4.6
        c.outline(bx, bx + 3.6, z0 + 5.4, z0 + 9.0, 0.05, YELLOW, 0.75)
        c.outline(bx, bx + 3.6, z0 + 10.8, z0 + 14.4, 0.05, YELLOW, 0.75)


# --------------------------------------------------------------------------
# Grime
# --------------------------------------------------------------------------


def paint_grime() -> Canvas:
    c = Canvas(3)
    rng = np.random.default_rng(4041)
    # Dirt collects at the foot of every wall and in the corners.
    c.rect(2.5, 97.5, L.WALL_FACE_Z, L.PIER_FRONT_Z + 0.4, DIRT, 0.45, soft=0.8)
    for x0, x1 in ((2.5, 3.4), (96.6, 97.5)):
        c.rect(x0, x1, 1.5, 46.0, DIRT, 0.5, soft=0.6)
    # Tyre rubber along the vehicle routes (pairs of tracks).
    routes = [
        [(4.0, 45.0), (30.0, 45.0), (60.0, 45.0), (96.0, 45.0)],
        [(64.6, 44.6), (64.6, 34.0), (62.0, 29.0), (57.0, 27.6)],
        [(34.0, 40.0), (37.0, 33.0), (42.0, 28.4), (43.6, 27.6)],
        [(39.0, 14.0), (42.0, 16.0), (45.0, 17.0)],
        [(77.0, 44.0), (76.4, 26.0), (76.4, 6.0)],
        [(86.0, 44.0), (86.0, 6.0)],
    ]
    for route in routes:
        for _ in range(rng.integers(3, 6)):
            offset = rng.normal(0.0, 0.25)
            gauge = 0.95 + rng.normal(0.0, 0.05)
            for side in (-1, 1):
                pts = [_offset_point(route, i, offset + side * gauge) for i in range(len(route))]
                c.track(pts, 0.28, DIRT, float(rng.uniform(0.12, 0.26)), soft=0.2)
    # Oil: under the shuttle's gear and engines, at hydrants, under the tug park.
    cx, cz = L.SHUTTLE_C
    for gx, gz in ((cx - 3.0, cz - 6.0), (cx + 3.0, cz - 6.0), (cx, cz + 6.5)):
        for _ in range(4):
            c.blob(
                gx + rng.normal(0, 0.6),
                gz + rng.normal(0, 0.6),
                rng.uniform(0.3, 0.9),
                rng.uniform(0.25, 0.7),
                OIL,
                float(rng.uniform(0.4, 0.8)),
                rng.uniform(0, 180),
            )
    for hx in (cx - 9.6, cx + 9.6):
        c.blob(hx, 27.6, 0.9, 0.6, OIL, 0.6)
    for _ in range(26):
        x = rng.uniform(4.0, 96.0)
        z = rng.uniform(4.0, 44.0)
        c.blob(
            x,
            z,
            rng.uniform(0.15, 0.6),
            rng.uniform(0.1, 0.4),
            OIL,
            float(rng.uniform(0.2, 0.55)),
            rng.uniform(0, 180),
        )
    # Exhaust scorch behind the shuttle and at the well rim.
    c.blob(cx, cz - 11.0, 3.0, 2.2, DIRT, 0.45)
    x0, x1, z0, z1 = L.WELL
    c.rect(x0 - 1.4, x1 + 1.4, z0 - 1.4, z1 + 1.4, DIRT, 0.22, soft=1.2)
    # Foot traffic polishes the walkway and the formation fields.
    c.rect(L.WALKWAY_X[0], L.WALKWAY_X[1], L.WALKWAY_Z[0], L.WALKWAY_Z[1], POLISH, 0.7, soft=0.5)
    for fx0, fx1, fz0, fz1 in (L.FORMATION_L, L.FORMATION_R):
        c.rect(fx0, fx1, fz0, fz1, POLISH, 0.35, soft=0.8)
    return c


def _offset_point(route, i, offset):
    """Point i of a polyline moved sideways by `offset` metres."""
    x, z = route[i]
    a = route[max(i - 1, 0)]
    b = route[min(i + 1, len(route) - 1)]
    dx, dz = b[0] - a[0], b[1] - a[1]
    n = math.hypot(dx, dz) or 1.0
    return (x - dz / n * offset, z + dx / n * offset)


# --------------------------------------------------------------------------
# Floor material
# --------------------------------------------------------------------------

_IMAGES: dict[str, bpy.types.Image] = {}

PLATE = 2.4
PLATE_COL = (0.03, 0.031, 0.033)
WHITE_PAINT = (0.48, 0.48, 0.465)
YELLOW_PAINT = (0.42, 0.28, 0.025)
RED_PAINT = (0.3, 0.035, 0.02)
OIL_COL = (0.008, 0.0075, 0.007)


def build_masks() -> None:
    _IMAGES["paint"] = paint_markings().to_image("T_HangarPaint_M")
    _IMAGES["grime"] = paint_grime().to_image("T_HangarGrime_M")


def _mask(g, key: str, uv):
    node = g.new(
        "ShaderNodeTexImage", image=_IMAGES[key], interpolation="Linear", extension="EXTEND"
    )
    g.set(node.inputs["Vector"], uv)
    return g.separate(node.outputs["Color"])


def _deck_plates(g):
    """2.4 m hangar plates: welded grooves that still read at plate density, four
    countersunk fasteners per corner and a per-plate random."""
    pos = g.coord("world", per_instance=False)
    x, y, _ = g.separate(pos)
    u, v = g.math("DIVIDE", x, PLATE), g.math("DIVIDE", y, PLATE)
    fu, fv = g.math("FRACT", u), g.math("FRACT", v)
    du = g.mul(g.math("MINIMUM", fu, g.math("SUBTRACT", 1.0, fu)), PLATE)
    dv = g.mul(g.math("MINIMUM", fv, g.math("SUBTRACT", 1.0, fv)), PLATE)
    seam_d = g.math("MINIMUM", du, dv)
    seam = g.remap(seam_d, 0.005, 0.009, 1.0, 0.0, smooth=True)
    bevel_band = g.remap(seam_d, 0.008, 0.016, 1.0, 0.0, smooth=True)
    bolts = None
    for off in (0.07, 0.15):
        bx = g.math("ABSOLUTE", g.math("SUBTRACT", du, off))
        by = g.math("ABSOLUTE", g.math("SUBTRACT", dv, 0.07))
        r = g.vmath("LENGTH", g.combine(bx, by, 0.0), out="Value")
        b = g.remap(r, 0.012, 0.016, 1.0, 0.0, smooth=True)
        bolts = b if bolts is None else g.math("MAXIMUM", bolts, b)
    cell = g.combine(g.math("FLOOR", u), g.math("FLOOR", v), 0.0)
    rnd = g.white(cell)
    return pos, seam, bevel_band, bolts, rnd


@materials.material("M_Hangar_Deck", viewport=(0.02, 0.02, 0.022))
def _hangar_deck(g) -> None:
    """Hangar deck: black lacquered steel plates that mirror the high bays.

    One hard clear coat carries crisp reflections; they break at the welded
    seams, wander slightly with each plate's flatness and are dulled by smudges,
    wipe marks, worn paint, tyre rubber and dirt. Oil stays glossy.
    """
    pos, seam, bevel_band, bolt, rnd = _deck_plates(g)
    x, y, _ = g.separate(pos)
    x0, y0, x1, y1 = EXTENT
    uv = g.combine(
        g.math("DIVIDE", g.math("SUBTRACT", x, x0), x1 - x0),
        g.math("DIVIDE", g.math("SUBTRACT", y, y0), y1 - y0),
        0.0,
    )
    white, yellow, red = _mask(g, "paint", uv)
    dirt, oil, polish = _mask(g, "grime", uv)

    # Ragged, crisp paint edges and worn-through chips (crisp at 192 px/m).
    jitter = g.mul(g.math("SUBTRACT", g.noise(pos, 30.0, detail=4, rough=0.7), 0.5), 0.5)
    keep, scuff, _ = materials.paint_wear(g, pos)

    def crisp(mask):
        return g.mul(g.remap(g.add(mask, jitter), 0.4, 0.6, smooth=True), g.mul(keep, mask))

    pw, py_, pr = crisp(white), crisp(yellow), crisp(red)
    paint_any = g.math("MAXIMUM", pw, g.math("MAXIMUM", py_, pr))

    macro = g.noise(pos, 0.07, detail=3, rough=0.55)
    smudge = g.remap(g.noise(pos, 0.55, detail=5, rough=0.62), 0.4, 0.8, smooth=True)
    wipe_co = g.vmath("MULTIPLY", pos, (0.35, 3.2, 1.0))
    wipe = g.remap(g.noise(wipe_co, 1.1, detail=3, rough=0.5), 0.5, 0.72, smooth=True)
    dirt_n = g.mul(dirt, g.remap(g.noise(pos, 3.0, detail=6, rough=0.7), 0.25, 0.75, 0.35, 1.0))
    oil_n = g.mul(oil, g.remap(g.noise(pos, 4.5, detail=5, rough=0.6), 0.3, 0.7, 0.5, 1.0))

    tint = g.add(0.72, g.mul(rnd, 0.6), g.mul(g.math("SUBTRACT", macro, 0.5), 0.3))
    base = g.mix_color(tint, (0, 0, 0), PLATE_COL)
    base = g.mix_color(g.mul(scuff, 0.25), base, (0.05, 0.05, 0.052))
    base = g.mix_color(pw, base, WHITE_PAINT)
    base = g.mix_color(py_, base, YELLOW_PAINT)
    base = g.mix_color(pr, base, RED_PAINT)
    base = g.mix_color(seam, base, (0.003, 0.003, 0.003))
    base = g.mix_color(bolt, base, (0.07, 0.07, 0.072))
    base = g.mix_color(g.mul(dirt_n, 0.7), base, (0.02, 0.019, 0.017))
    base = g.mix_color(g.mul(oil_n, 0.85), base, OIL_COL)

    rough = g.add(0.42, g.mul(paint_any, 0.15), g.mul(dirt_n, 0.2), g.mul(seam, 0.3))
    coat = g.math(
        "SUBTRACT",
        1.0,
        g.add(g.mul(paint_any, 0.55), g.mul(seam, 1.0), g.mul(dirt_n, 0.55)),
        clamp=True,
    )
    # A dulling film over the lacquer: reflections dim and brighten across the deck.
    film = g.remap(g.noise(pos, 0.25, detail=4, rough=0.6), 0.3, 0.7, 0.55, 1.0)
    coat = g.mul(coat, film)
    coat_rough = g.add(
        0.004,
        g.mul(rnd, 0.006),
        g.mul(smudge, 0.012),
        g.mul(wipe, 0.005),
        g.mul(scuff, 0.025),
        g.mul(dirt_n, 0.3),
        g.mul(oil_n, -0.002),
        g.mul(polish, -0.002),
    )
    height = g.add(
        g.mul(bevel_band, -1.0),
        g.mul(bolt, 0.4),
        g.mul(paint_any, 0.05),
        g.mul(g.noise(pos, 70.0, detail=2), 0.03),
        g.mul(scuff, -0.06),
    )
    # Each plate lies a hair off flat, so reflections step at the seams.
    tilt = g.add(
        g.mul(
            g.math("SUBTRACT", rnd, 0.5),
            g.math("SUBTRACT", g.math("FRACT", g.math("DIVIDE", x, PLATE)), 0.5),
        ),
        g.mul(g.noise(pos, 0.35, detail=2), 0.3),
    )
    bsdf = g.principled(
        Base_Color=base,
        Roughness=rough,
        Metallic=g.mul(bolt, 1.0),
        Specular_IOR_Level=0.25,
        Normal=g.bump(height, 0.35, 0.003),
        Coat_Weight=coat,
        Coat_IOR=1.55,
        Coat_Roughness=coat_rough,
        Coat_Normal=g.bump(tilt, 0.008, 0.05),
    )
    g.output(bsdf.outputs[0])
