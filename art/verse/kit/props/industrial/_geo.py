"""Geometry helpers for the industrial props, on top of ``lib.kit.MeshBuilder``.

Everything adds faces to a MeshBuilder in its current local frame
(``mb.matrix``); :func:`xf` nests transforms. Angles are degrees in the public
helpers unless a name says ``_rad``.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from contextlib import contextmanager

import bpy
from lib import kit as K
from mathutils import Matrix, Vector

TAU = 2.0 * math.pi
# Arial Narrow Bold first: Bahnschrift is a variable font whose overlapping
# contours turn into holes in Blender text fills (H, R, A break).
FONT_CANDIDATES = ("C:/Windows/Fonts/ARIALNB.TTF", "C:/Windows/Fonts/arialbd.ttf")


# --------------------------------------------------------------------------
# Transforms and determinism
# --------------------------------------------------------------------------


def T(x: float = 0.0, y: float = 0.0, z: float = 0.0) -> Matrix:
    return Matrix.Translation((x, y, z))


def Rz(deg: float) -> Matrix:
    return Matrix.Rotation(math.radians(deg), 4, "Z")


def Rx(deg: float) -> Matrix:
    return Matrix.Rotation(math.radians(deg), 4, "X")


def Ry(deg: float) -> Matrix:
    return Matrix.Rotation(math.radians(deg), 4, "Y")


def S(x: float, y: float | None = None, z: float | None = None) -> Matrix:
    return Matrix.Diagonal((x, x if y is None else y, x if z is None else z, 1.0))


@contextmanager
def xf(mb: K.MeshBuilder, matrix: Matrix):
    """Add geometry in ``matrix`` relative to the builder's current frame."""
    old = mb.matrix
    mb.matrix = old @ matrix
    try:
        yield mb
    finally:
        mb.matrix = old


def rng(*parts) -> random.Random:
    return random.Random(K.seed_for("props-industrial", *parts))  # noqa: S311 - art seed


def polar(r: float, deg: float, z: float = 0.0) -> tuple[float, float, float]:
    a = math.radians(deg)
    return (r * math.cos(a), r * math.sin(a), z)


# --------------------------------------------------------------------------
# Solids of revolution
# --------------------------------------------------------------------------


def lathe(
    mb: K.MeshBuilder,
    profile: Sequence[Sequence[float]],
    material: str,
    segments: int = 48,
    a0: float = 0.0,
    a1: float = 360.0,
    closed: bool = False,
    smooth: bool = True,
    caps: bool = True,
):
    """Revolve an (r, z) profile around local Z from ``a0`` to ``a1`` degrees.

    ``closed`` joins the last profile point to the first (a solid section).
    Partial sweeps of closed profiles get flat end caps when ``caps``.
    Profile points on the axis (r = 0) become one shared pole vertex and
    their quads become triangles: coincident vertices and zero-area faces
    make the bevel modifier emit NaN coordinates.
    """
    full = abs((a1 - a0) - 360.0) < 1e-6
    n = len(profile)
    columns = segments if full else segments + 1
    verts: list[Vector] = []
    index: dict[tuple[int, int], int] = {}
    poles: dict[int, int] = {}
    for i in range(columns):
        a = math.radians(a0 + (a1 - a0) * i / segments)
        ca, sa = math.cos(a), math.sin(a)
        for j, (r, z) in enumerate(profile):
            if abs(r) < 1e-9:
                if j not in poles:
                    poles[j] = len(verts)
                    verts.append(Vector((0.0, 0.0, z)))
                index[i, j] = poles[j]
            else:
                index[i, j] = len(verts)
                verts.append(Vector((r * ca, r * sa, z)))
    faces = []
    rows = n if closed else n - 1
    for i in range(segments):
        i2 = (i + 1) % columns if full else i + 1
        for j in range(rows):
            j2 = (j + 1) % n
            _face(faces, (index[i, j], index[i2, j], index[i2, j2], index[i, j2]))
    if closed and caps and not full:
        _face(faces, tuple(index[0, j] for j in reversed(range(n))))
        _face(faces, tuple(index[columns - 1, j] for j in range(n)))
    mb._add(verts, faces, material, smooth=smooth)
    return mb


def _face(faces: list, idx) -> None:
    """Append ``idx`` without repeated vertices; drop it if fewer than 3 remain."""
    unique: list[int] = []
    for v in idx:
        if v not in unique:
            unique.append(v)
    if len(unique) >= 3:
        faces.append(tuple(unique))


def slab_between(mb, inner_xy, outer_xy, z0, z1, material):
    """Closed slab between two loops of equal length (a floor with a hole).

    The result is a closed solid, so MeshBuilder's normal recalculation turns
    the top faces up: the nav cook only accepts up-facing walk surfaces.
    """
    n = len(inner_xy)
    verts = []
    for (xi, yi), (xo, yo) in zip(inner_xy, outer_xy, strict=True):
        verts += [
            Vector((xi, yi, z1)),
            Vector((xo, yo, z1)),
            Vector((xo, yo, z0)),
            Vector((xi, yi, z0)),
        ]
    faces = []
    for i in range(n):
        j = (i + 1) % n
        for k in range(4):
            k2 = (k + 1) % 4
            faces.append((4 * i + k, 4 * i + k2, 4 * j + k2, 4 * j + k))
    mb._add(verts, faces, material)
    return mb


def lathe_y(mb, x, z, y0, profile, material, segments=24):
    """Revolve an (r, d) profile around an axis parallel to Y through (x, z);
    ``d`` is the distance from ``y0`` toward -Y (aft, toward the camera)."""
    with xf(mb, T(x, y0, z) @ Rx(90.0)):
        lathe(mb, profile, material, segments)
    return mb


def ring(mb, r0, r1, z0, z1, material, segments=64, a0=0.0, a1=360.0):
    """Annular solid between radii r0 < r1 and heights z0 < z1."""
    return lathe(
        mb, [(r0, z0), (r1, z0), (r1, z1), (r0, z1)], material, segments, a0, a1, closed=True
    )


def tube_z(mb, r, z0, z1, material, segments=24, x=0.0, y=0.0):
    return mb.tube((x, y, z0), (x, y, z1), r, material, segments)


def annulus(mb, r0, r1, z, material, segments=64, a0=0.0, a1=360.0, up=True):
    """Flat annulus (or sector) facing +Z (or -Z); r0 = 0 gives a disc (fan)."""
    full = abs((a1 - a0) - 360.0) < 1e-6
    cols = segments if full else segments + 1
    verts: list[Vector] = []
    centre = None
    if r0 < 1e-9:
        centre = len(verts)
        verts.append(Vector((0.0, 0.0, z)))
    inner, outer = [], []
    for i in range(cols):
        a = math.radians(a0 + (a1 - a0) * i / segments)
        if centre is None:
            inner.append(len(verts))
            verts.append(Vector((r0 * math.cos(a), r0 * math.sin(a), z)))
        else:
            inner.append(centre)
        outer.append(len(verts))
        verts.append(Vector((r1 * math.cos(a), r1 * math.sin(a), z)))
    faces: list = []
    for i in range(segments):
        i2 = (i + 1) % cols if full else i + 1
        f = (inner[i], outer[i], outer[i2], inner[i2])
        _face(faces, f if up else tuple(reversed(f)))
    mb._add(verts, faces, material)
    return mb


# --------------------------------------------------------------------------
# Hard-surface primitives
# --------------------------------------------------------------------------


def chamfer_box(mb, lo, hi, chamfer, material, cap_material=None):
    """Box with 45-degree chamfered vertical edges (an octagonal prism)."""
    x0, y0, z0 = lo
    x1, y1, z1 = hi
    c = min(chamfer, (x1 - x0) * 0.49, (y1 - y0) * 0.49)
    poly = [
        (x0 + c, y0),
        (x1 - c, y0),
        (x1, y0 + c),
        (x1, y1 - c),
        (x1 - c, y1),
        (x0 + c, y1),
        (x0, y1 - c),
        (x0, y0 + c),
    ]
    return mb.prism_z(poly, z0, z1, material, cap_material)


def wedge_x(mb, profile_yz, x0, x1, material, cap=None):
    """Alias of ``prism_x`` that tolerates clockwise profiles."""
    if _signed_area(profile_yz) < 0:
        profile_yz = list(reversed(profile_yz))
    return mb.prism_x(profile_yz, x0, x1, material, cap)


def prism_z_any(mb, poly_xy, z0, z1, material, cap=None):
    if _signed_area(poly_xy) < 0:
        poly_xy = list(reversed(poly_xy))
    return mb.prism_z(poly_xy, z0, z1, material, cap)


def _signed_area(poly) -> float:
    return 0.5 * sum(
        poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1]
        for i in range(len(poly))
    )


def loft(mb, sections, material, closed_ends=True, smooth=False):
    """Skin a list of equal-length 3D loops (each a list of points)."""
    n = len(sections[0])
    verts = [Vector(p) for sec in sections for p in sec]
    faces = []
    for s in range(len(sections) - 1):
        for j in range(n):
            j2 = (j + 1) % n
            faces.append((s * n + j, s * n + j2, (s + 1) * n + j2, (s + 1) * n + j))
    if closed_ends:
        faces.append(tuple(reversed(range(n))))
        last = (len(sections) - 1) * n
        faces.append(tuple(range(last, last + n)))
    mb._add(verts, faces, material, smooth=smooth)
    return mb


def beam(mb, p0, p1, w, h, material, up=(0, 0, 1)):
    """Rectangular beam of width ``w`` and height ``h`` from p0 to p1."""
    p0, p1 = Vector(p0), Vector(p1)
    d = p1 - p0
    if d.length < 1e-6:
        return mb
    x = d.normalized()
    upv = Vector(up)
    if abs(x.dot(upv.normalized())) > 0.99:
        upv = Vector((1, 0, 0)) if abs(x.x) < 0.9 else Vector((0, 1, 0))
    y = upv.cross(x).normalized()
    z = x.cross(y).normalized()
    frame = Matrix((x, y, z)).transposed().to_4x4()
    frame.translation = p0
    with xf(mb, frame):
        mb.box((0, -w / 2, -h / 2), (d.length, w / 2, h / 2), material)
    return mb


def ibeam(mb, p0, p1, depth, flange, material, up=(0, 0, 1), tf=None, tw=None):
    """I-section beam from p0 to p1; ``depth`` along ``up``, ``flange`` across."""
    tf = tf or max(0.02, depth * 0.09)
    tw = tw or max(0.015, flange * 0.12)
    p0, p1 = Vector(p0), Vector(p1)
    d = p1 - p0
    x = d.normalized()
    upv = Vector(up)
    y = upv.cross(x).normalized()
    z = x.cross(y).normalized()
    frame = Matrix((x, y, z)).transposed().to_4x4()
    frame.translation = p0
    L = d.length
    with xf(mb, frame):
        mb.box((0, -flange / 2, depth / 2 - tf), (L, flange / 2, depth / 2), material)
        mb.box((0, -flange / 2, -depth / 2), (L, flange / 2, -depth / 2 + tf), material)
        mb.box((0, -tw / 2, -depth / 2 + tf), (L, tw / 2, depth / 2 - tf), material)
    return mb


def sweep(mb, points, radius, material, segments=12, caps=True):
    """Continuous tube through ``points`` (parallel-transport frames)."""
    pts = [Vector(p) for p in points]
    if len(pts) < 2:
        return mb
    tangents = []
    for i in range(len(pts)):
        a = pts[max(i - 1, 0)]
        b = pts[min(i + 1, len(pts) - 1)]
        tangents.append((b - a).normalized())
    ref = Vector((0, 0, 1)) if abs(tangents[0].z) < 0.9 else Vector((1, 0, 0))
    normal = ref.cross(tangents[0]).normalized()
    rings = []
    for i, (p, t) in enumerate(zip(pts, tangents, strict=True)):
        if i > 0:
            prev = tangents[i - 1]
            axis = prev.cross(t)
            if axis.length > 1e-8:
                angle = prev.angle(t)
                normal = (Matrix.Rotation(angle, 3, axis.normalized()) @ normal).normalized()
        binormal = t.cross(normal).normalized()
        rings.append(
            [
                p + (normal * math.cos(a) + binormal * math.sin(a)) * radius
                for a in (TAU * k / segments for k in range(segments))
            ]
        )
    loft(mb, rings, material, closed_ends=caps, smooth=True)
    return mb


def catmull_rom(points, samples_per_span=8):
    pts = [Vector(p) for p in points]
    if len(pts) < 3:
        return pts
    ext = [pts[0] * 2 - pts[1], *pts, pts[-1] * 2 - pts[-2]]
    out = []
    for i in range(1, len(ext) - 2):
        p0, p1, p2, p3 = ext[i - 1], ext[i], ext[i + 1], ext[i + 2]
        for s in range(samples_per_span):
            t = s / samples_per_span
            t2, t3 = t * t, t * t * t
            out.append(
                0.5
                * (
                    (2 * p1)
                    + (-p0 + p2) * t
                    + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2
                    + (-p0 + 3 * p1 - 3 * p2 + p3) * t3
                )
            )
    out.append(pts[-1])
    return out


def grille(mb, lo, hi, material, slats=8, axis="Z", depth=0.02, frame_material=None):
    """Vent grille on a face lying in XZ (facing -Y): frame + horizontal slats."""
    x0, y0, z0 = lo
    x1, y1, z1 = hi
    fm = frame_material or material
    t = 0.03
    mb.box((x0, y0, z0), (x1, y1, z0 + t), fm)
    mb.box((x0, y0, z1 - t), (x1, y1, z1), fm)
    mb.box((x0, y0, z0), (x0 + t, y1, z1), fm)
    mb.box((x1 - t, y0, z0), (x1, y1, z1), fm)
    if axis == "Z":
        step = (z1 - z0 - 2 * t) / slats
        for i in range(slats):
            zc = z0 + t + step * (i + 0.5)
            mb.box(
                (x0 + t, y0 + depth * 0.3, zc - step * 0.22),
                (x1 - t, y1, zc + step * 0.22),
                material,
            )
    else:
        step = (x1 - x0 - 2 * t) / slats
        for i in range(slats):
            xc = x0 + t + step * (i + 0.5)
            mb.box(
                (xc - step * 0.22, y0 + depth * 0.3, z0 + t),
                (xc + step * 0.22, y1, z1 - t),
                material,
            )
    return mb


# --------------------------------------------------------------------------
# Stencils and markings
# --------------------------------------------------------------------------


def font() -> bpy.types.VectorFont | None:
    for path in FONT_CANDIDATES:
        try:
            return bpy.data.fonts.load(path, check_existing=True)
        except (RuntimeError, OSError):
            continue
    return None


def text(
    mb,
    body: str,
    size: float,
    material: str,
    matrix: Matrix | None = None,
    align_x: str = "CENTER",
    align_y: str = "CENTER",
    spacing: float = 1.0,
):
    """Add flat text (lying in local XY, reading along +X, facing +Z)."""
    cu = bpy.data.curves.new("_tmp_text", "FONT")
    cu.body = body
    cu.size = size
    cu.align_x = align_x
    cu.align_y = align_y
    cu.space_character = spacing
    f = font()
    if f is not None:
        cu.font = f
    ob = bpy.data.objects.new("_tmp_text", cu)
    bpy.context.scene.collection.objects.link(ob)
    deps = bpy.context.evaluated_depsgraph_get()
    deps.update()
    me = bpy.data.meshes.new_from_object(ob.evaluated_get(deps))
    verts = [v.co.copy() for v in me.vertices]
    faces = [tuple(p.vertices) for p in me.polygons]
    bpy.data.objects.remove(ob, do_unlink=True)
    bpy.data.curves.remove(cu)
    bpy.data.meshes.remove(me)
    with xf(mb, matrix or Matrix.Identity(4)):
        mb._add(verts, faces, material)
    return mb


def on_face(origin, normal: str, up: str = "Z") -> Matrix:
    """Frame for flat decals: text +X reads right, +Z of the frame = ``normal``.

    ``normal`` in {"-Y", "+Y", "+X", "-X", "+Z"}; decals sit on that face.
    """
    o = Vector(origin)
    table = {
        "-Y": ((1, 0, 0), (0, 0, 1), (0, -1, 0)),
        "+Y": ((-1, 0, 0), (0, 0, 1), (0, 1, 0)),
        "+X": ((0, 1, 0), (0, 0, 1), (1, 0, 0)),
        "-X": ((0, -1, 0), (0, 0, 1), (-1, 0, 0)),
        "+Z": ((1, 0, 0), (0, 1, 0), (0, 0, 1)),
    }
    x, y, z = (Vector(v) for v in table[normal])
    m = Matrix((x, y, z)).transposed().to_4x4()
    m.translation = o
    return m


def stripe_quad(mb, p0, p1, width, z, material):
    """Flat painted stripe on the floor from p0 to p1 (XY) at height z."""
    a, b = Vector((*p0[:2], 0)), Vector((*p1[:2], 0))
    d = b - a
    if d.length < 1e-6:
        return mb
    n = Vector((-d.y, d.x, 0)).normalized() * (width / 2)
    corners = [a - n, b - n, b + n, a + n]
    mb.quad([(c.x, c.y, z) for c in corners], material)
    return mb
