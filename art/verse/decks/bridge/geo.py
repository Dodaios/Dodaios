"""Small geometry helpers for the bridge's bespoke pieces (runs in Blender).

Everything builds through ``lib.kit.MeshBuilder`` so materials, bevels and
custom properties follow the kit conventions.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from contextlib import contextmanager

from lib import kit
from mathutils import Matrix, Vector

from . import layout as L


@contextmanager
def xform(mb: kit.MeshBuilder, matrix: Matrix):
    """Build the block's geometry through an extra local transform."""
    old = mb.matrix
    mb.matrix = old @ matrix
    try:
        yield mb
    finally:
        mb.matrix = old


def tr(x=0.0, y=0.0, z=0.0, rz_deg=0.0, rx_deg=0.0) -> Matrix:
    """Translation, then rotation about Z, then about X (local)."""
    m = Matrix.Translation((x, y, z))
    if rz_deg:
        m = m @ Matrix.Rotation(math.radians(rz_deg), 4, "Z")
    if rx_deg:
        m = m @ Matrix.Rotation(math.radians(rx_deg), 4, "X")
    return m


def panel_frame(origin: Sequence[float], tilt_back_deg: float = 0.0) -> Matrix:
    """Frame of a panel facing -Y: X right, Y up the panel, Z out of it.

    ``tilt_back_deg`` 0 = vertical panel facing the camera, 90 = facing up.
    """
    base = Matrix(((1, 0, 0, 0), (0, 0, -1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))
    tilt = Matrix.Rotation(math.radians(-tilt_back_deg), 4, "X")
    return Matrix.Translation(Vector(origin)) @ tilt @ base


def segment_matrix(a_plan: Sequence[float], b_plan: Sequence[float]) -> tuple[Matrix, float]:
    """Wall frame for a plan segment a -> b with the room on the right.

    Local X runs from a to b, local -Y points into the room, origin at the
    midpoint on the floor. Returns (matrix, length).
    """
    a = Vector(L.XY(*a_plan))
    b = Vector(L.XY(*b_plan))
    d = b - a
    length = d.length
    x = d.normalized()
    y = Vector((-x.y, x.x))  # left of travel = into the wall
    mid = (a + b) / 2
    m = Matrix(
        (
            (x.x, y.x, 0.0, mid.x),
            (x.y, y.y, 0.0, mid.y),
            (0.0, 0.0, 1.0, 0.0),
            (0.0, 0.0, 0.0, 1.0),
        )
    )
    return m, length


def normal_frame(point_plan: Sequence[float], room_normal_plan: Sequence[float]) -> Matrix:
    """Frame at a plan point whose local -Y is the given room normal (plan x, z)."""
    nx, nz = room_normal_plan
    n = Vector((nx, -nz)).normalized()  # Blender XY
    y = -n
    x = Vector((y.y, -y.x))
    p = L.XY(*point_plan)
    return Matrix(
        (
            (x.x, y.x, 0.0, p[0]),
            (x.y, y.y, 0.0, p[1]),
            (0.0, 0.0, 1.0, 0.0),
            (0.0, 0.0, 0.0, 1.0),
        )
    )


def lean_matrix(base: Matrix, y0: float, z0: float, lean_deg: float) -> Matrix:
    """Local frame of a plane leaning back (toward +Y) by ``lean_deg``.

    In the returned frame local Z runs up the slope, local -Y is the slope's
    room-side normal, origin at (0, y0, z0) of ``base``.
    """
    return (
        base @ Matrix.Translation((0.0, y0, z0)) @ Matrix.Rotation(math.radians(-lean_deg), 4, "X")
    )


def prism_y(
    mb: kit.MeshBuilder,
    polygon_xz: Sequence[Sequence[float]],
    y0: float,
    y1: float,
    material: str,
    cap_material: str | None = None,
) -> None:
    """Extrude a closed XZ polygon along Y; the -Y face gets ``cap_material``."""
    n = len(polygon_xz)
    verts = [Vector((x, y0, z)) for x, z in polygon_xz] + [
        Vector((x, y1, z)) for x, z in polygon_xz
    ]
    sides = [(i, (i + 1) % n, n + (i + 1) % n, n + i) for i in range(n)]
    mb._add(verts, sides, material)  # noqa: SLF001 - kit helper used as intended
    mb._add(verts, [tuple(range(n, 2 * n))], material)  # noqa: SLF001
    mb._add(verts, [tuple(reversed(range(n)))], cap_material or material)  # noqa: SLF001


def fillet(
    corner, toward_a, toward_b, radius: float, segments: int = 6
) -> list[tuple[float, float]]:
    """2D fillet piece filling the inside of a corner (corner, arc...)."""
    c = Vector(corner)
    e1 = (Vector(toward_a) - c).normalized()
    e2 = (Vector(toward_b) - c).normalized()
    cos_t = max(-0.999, min(0.999, e1.dot(e2)))
    theta = math.acos(cos_t)
    t = radius / math.tan(theta / 2)
    p1, p2 = c + e1 * t, c + e2 * t
    bis = (e1 + e2).normalized()
    centre = c + bis * (radius / math.sin(theta / 2))
    a1 = math.atan2(p1.y - centre.y, p1.x - centre.x)
    a2 = math.atan2(p2.y - centre.y, p2.x - centre.x)
    span = (a2 - a1 + math.pi) % (2 * math.pi) - math.pi
    pts = [tuple(c)]
    for i in range(segments + 1):
        a = a1 + span * i / segments
        pts.append((centre.x + radius * math.cos(a), centre.y + radius * math.sin(a)))
    return pts


def offset_polygon(points: Sequence[Sequence[float]], inset: float) -> list[tuple[float, float]]:
    """Inset a convex CCW polygon by ``inset`` (positive = inward)."""
    pts = [Vector(p) for p in points]
    n = len(pts)
    area = 0.5 * sum(
        pts[i].x * pts[(i + 1) % n].y - pts[(i + 1) % n].x * pts[i].y for i in range(n)
    )
    sign = 1.0 if area > 0 else -1.0
    lines = []
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        d = (b - a).normalized()
        inward = Vector((-d.y, d.x)) * sign
        lines.append((a + inward * inset, d))
    out = []
    for i in range(n):
        (p1, d1), (p2, d2) = lines[i - 1], lines[i]
        den = d1.x * d2.y - d1.y * d2.x
        if abs(den) < 1e-9:
            out.append(tuple(p2))
            continue
        t = ((p2.x - p1.x) * d2.y - (p2.y - p1.y) * d2.x) / den
        q = p1 + d1 * t
        out.append((q.x, q.y))
    return out


def rounded_rect(cx, cy, w, h, r, seg=5) -> list[tuple[float, float]]:
    pts = []
    for qx, qy, a0 in ((1, 1, 0), (-1, 1, 90), (-1, -1, 180), (1, -1, 270)):
        ox, oy = cx + qx * (w / 2 - r), cy + qy * (h / 2 - r)
        for i in range(seg + 1):
            a = math.radians(a0 + 90 * i / seg)
            pts.append((ox + r * math.cos(a), oy + r * math.sin(a)))
    return pts


def ellipse(cx, cy, rx, ry, n=48) -> list[tuple[float, float]]:
    return [
        (cx + rx * math.cos(2 * math.pi * i / n), cy + ry * math.sin(2 * math.pi * i / n))
        for i in range(n)
    ]


def superellipse(cx, cy, rx, ry, p=3.0, n=64) -> list[tuple[float, float]]:
    pts = []
    for i in range(n):
        a = 2 * math.pi * i / n
        c, s = math.cos(a), math.sin(a)
        pts.append(
            (
                cx + rx * math.copysign(abs(c) ** (2 / p), c),
                cy + ry * math.copysign(abs(s) ** (2 / p), s),
            )
        )
    return pts


def box_ucx(name: str, lo, hi, **props):
    """World-space box occluder (UCX_)."""
    return kit.occluder((tuple(lo), tuple(hi)), name=f"UCX_{name}", **props)


def matrix_ucx(name: str, matrix: Matrix, lo, hi, **props):
    """Oriented box occluder: a local box transformed by ``matrix``."""
    from mathutils import Vector as V

    (x0, y0, z0), (x1, y1, z1) = lo, hi
    corners = [
        (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
        (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1),
    ]  # fmt: skip
    verts = [matrix @ V(c) for c in corners]
    faces = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    return kit._emit_ucx(f"UCX_{name}", verts, faces, **props)  # noqa: SLF001


def prism_ucx(name: str, polygon_xy, z0: float, z1: float, **props):
    """Prism occluder from a convex Blender-XY polygon."""
    n = len(polygon_xy)
    verts = [Vector((x, y, z0)) for x, y in polygon_xy] + [
        Vector((x, y, z1)) for x, y in polygon_xy
    ]
    faces = [tuple(reversed(range(n))), tuple(range(n, 2 * n))]
    faces += [(i, (i + 1) % n, n + (i + 1) % n, n + i) for i in range(n)]
    return kit._emit_ucx(f"UCX_{name}", verts, faces, **props)  # noqa: SLF001
