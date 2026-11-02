"""Solid geometry of the destructible pieces, pure Python (no bpy).

Everything here is in Blender piece space (metres, Z up, X centred, floor at
Z = 0; wall-like pieces have their room face on Y = 0 and their body toward
+Y; kit/README.md "Conventions"). The Blender builders in ``pieces.py`` turn
these meshes into objects; pytest and the builder validator check them
without Blender.

Rules (contracts/destruction.md 9, art-pipeline 13):

- Every piece is a solid, closed, manifold volume with the real thickness of
  its penetration material. Never double planes, never one-sided shells.
- Openings (Holed, Breached) are cut as real geometry: the face is split on a
  grid by the opening edges, the cells inside the opening are dropped and the
  opening gets its own inner walls, so the result stays one manifold shell.
- Fracture is Voronoi as code: seeded cell centres, each cell is the piece's
  convex parts clipped by the bisector half-spaces. Same seed, same chunks.
"""

from __future__ import annotations

import math
import random
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

Vec3 = tuple[float, float, float]

EPS = 1e-9


@dataclass
class Mesh:
    """Polygon mesh: shared vertices, faces as vertex index loops (outward, counter-clockwise)."""

    verts: list[Vec3] = field(default_factory=list)
    faces: list[tuple[int, ...]] = field(default_factory=list)

    def add(self, verts: Sequence[Vec3], faces: Iterable[Sequence[int]]) -> None:
        base = len(self.verts)
        self.verts.extend(tuple(float(c) for c in v) for v in verts)
        self.faces.extend(tuple(base + i for i in f) for f in faces)

    def extend(self, other: Mesh) -> None:
        self.add(other.verts, other.faces)

    def triangles(self) -> list[tuple[int, int, int]]:
        out = []
        for face in self.faces:
            for i in range(1, len(face) - 1):
                out.append((face[0], face[i], face[i + 1]))
        return out

    def bounds(self) -> tuple[Vec3, Vec3]:
        xs, ys, zs = zip(*self.verts, strict=True)
        return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


# --------------------------------------------------------------------------
# Vector helpers


def sub(a: Sequence[float], b: Sequence[float]) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def add(a: Sequence[float], b: Sequence[float]) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def scale(a: Sequence[float], s: float) -> Vec3:
    return (a[0] * s, a[1] * s, a[2] * s)


def dot(a: Sequence[float], b: Sequence[float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def cross(a: Sequence[float], b: Sequence[float]) -> Vec3:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def length(a: Sequence[float]) -> float:
    return math.sqrt(dot(a, a))


# --------------------------------------------------------------------------
# Primitive solids


def box(lo: Vec3, hi: Vec3) -> Mesh:
    """Closed box, outward winding."""
    (x0, y0, z0), (x1, y1, z1) = lo, hi
    verts = [
        (x0, y0, z0),
        (x1, y0, z0),
        (x1, y1, z0),
        (x0, y1, z0),
        (x0, y0, z1),
        (x1, y0, z1),
        (x1, y1, z1),
        (x0, y1, z1),
    ]
    faces = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (2, 3, 7, 6), (1, 2, 6, 5), (3, 0, 4, 7)]
    mesh = Mesh()
    mesh.add(verts, faces)
    return mesh


def slab_with_openings(
    width: float,
    height: float,
    y0: float,
    y1: float,
    openings: Sequence[tuple[float, float, float, float]],
    *,
    z0: float = 0.0,
) -> Mesh:
    """A wall slab X in [-w/2, w/2], Z in [z0, z0 + h], Y in [y0, y1] with rectangular openings.

    ``openings`` are (x_min, z_min, x_max, z_max) in piece space; they may touch
    each other (an irregular hole is a union of rectangles) but must stay inside
    the slab. The face is split on the grid of all opening edges, cells inside
    any opening are dropped, and every boundary edge gets a side quad, so the
    result is one closed manifold shell with real inner walls.
    """
    xs = sorted({-width / 2, width / 2, *(o[0] for o in openings), *(o[2] for o in openings)})
    zs = sorted({z0, z0 + height, *(o[1] for o in openings), *(o[3] for o in openings)})
    for x_min, z_min, x_max, z_max in openings:
        if not (-width / 2 <= x_min < x_max <= width / 2 and z0 <= z_min < z_max <= z0 + height):
            raise ValueError(f"opening {(x_min, z_min, x_max, z_max)} leaves the slab")

    def solid(i: int, k: int) -> bool:
        if i < 0 or k < 0 or i >= len(xs) - 1 or k >= len(zs) - 1:
            return False
        cx, cz = (xs[i] + xs[i + 1]) / 2, (zs[k] + zs[k + 1]) / 2
        return not any(o[0] < cx < o[2] and o[1] < cz < o[3] for o in openings)

    index: dict[tuple[int, int, int], int] = {}
    mesh = Mesh()

    def vert(i: int, k: int, side: int) -> int:
        key = (i, k, side)
        if key not in index:
            index[key] = len(mesh.verts)
            mesh.verts.append((xs[i], y0 if side == 0 else y1, zs[k]))
        return index[key]

    for i in range(len(xs) - 1):
        for k in range(len(zs) - 1):
            if not solid(i, k):
                continue
            # Front (-Y): ccw seen from -Y is (x0,z0) (x1,z0) (x1,z1) (x0,z1).
            mesh.faces.append(
                (vert(i, k, 0), vert(i + 1, k, 0), vert(i + 1, k + 1, 0), vert(i, k + 1, 0))
            )
            mesh.faces.append(
                (vert(i, k, 1), vert(i, k + 1, 1), vert(i + 1, k + 1, 1), vert(i + 1, k, 1))
            )
            # Boundary walls toward empty neighbours.
            if not solid(i, k - 1):  # bottom, normal -Z
                mesh.faces.append(
                    (vert(i, k, 0), vert(i, k, 1), vert(i + 1, k, 1), vert(i + 1, k, 0))
                )
            if not solid(i, k + 1):  # top, normal +Z
                mesh.faces.append(
                    (
                        vert(i, k + 1, 0),
                        vert(i + 1, k + 1, 0),
                        vert(i + 1, k + 1, 1),
                        vert(i, k + 1, 1),
                    )
                )
            if not solid(i - 1, k):  # left, normal -X
                mesh.faces.append(
                    (vert(i, k, 0), vert(i, k + 1, 0), vert(i, k + 1, 1), vert(i, k, 1))
                )
            if not solid(i + 1, k):  # right, normal +X
                mesh.faces.append(
                    (
                        vert(i + 1, k, 0),
                        vert(i + 1, k, 1),
                        vert(i + 1, k + 1, 1),
                        vert(i + 1, k + 1, 0),
                    )
                )
    return mesh


def corrugated(width: float, height: float, sheet: float, depth: float, ribs: int) -> list[Mesh]:
    """A corrugated container wall as convex strips (each a closed prism, sheet thick).

    Trapezoid ribs: flat, rise, crest, fall. Each straight run of the profile is
    one convex parallelogram prism; neighbouring strips share their end faces'
    planes only along an edge line, never a face (they meet at a corner).
    """
    pitch = width / ribs
    pts: list[tuple[float, float]] = []
    for rib in range(ribs):
        x = -width / 2 + rib * pitch
        pts += [
            (x, 0.0),
            (x + pitch * 0.25, 0.0),
            (x + pitch * 0.375, depth),
            (x + pitch * 0.875, depth),
        ]
    pts.append((width / 2, 0.0))
    strips = []
    for (xa, ya), (xb, yb) in zip(pts, pts[1:], strict=False):
        if abs(xb - xa) < EPS and abs(yb - ya) < EPS:
            continue
        # Parallelogram in XY: the run plus the run offset by the sheet along +Y, extruded in Z.
        quad = [(xa, ya), (xb, yb), (xb, yb + sheet), (xa, ya + sheet)]
        strips.append(_extrude_xy(quad, 0.0, height))
    return strips


def corrugated_solid(width: float, height: float, sheet: float, depth: float, ribs: int) -> Mesh:
    """The same wall as one closed shell (render mesh and proxy)."""
    pitch = width / ribs
    outer: list[tuple[float, float]] = []
    for rib in range(ribs):
        x = -width / 2 + rib * pitch
        outer += [
            (x, 0.0),
            (x + pitch * 0.25, 0.0),
            (x + pitch * 0.375, depth),
            (x + pitch * 0.875, depth),
        ]
    outer.append((width / 2, 0.0))
    inner = [(x, y + sheet) for x, y in outer]
    m = len(outer)
    verts = [(x, y, 0.0) for x, y in outer] + [(x, y, 0.0) for x, y in inner]
    verts += [(x, y, height) for x, y in outer] + [(x, y, height) for x, y in inner]
    top = 2 * m
    faces: list[tuple[int, ...]] = []
    for i in range(m - 1):
        o0, o1, i0, i1 = i, i + 1, m + i, m + i + 1
        faces.append((o0, i0, i1, o1))  # bottom strip, normal -Z
        faces.append((top + o0, top + o1, top + i1, top + i0))  # top strip, normal +Z
        faces.append((o0, o1, top + o1, top + o0))  # outer face
        faces.append((i1, i0, top + i0, top + i1))  # inner face
    faces.append((m + 0, 0, top + 0, top + m))  # left end
    faces.append((m - 1, 2 * m - 1, top + 2 * m - 1, top + m - 1))  # right end
    mesh = Mesh()
    mesh.add(verts, faces)
    return mesh


def _extrude_xy(poly_xy: Sequence[tuple[float, float]], z0: float, z1: float) -> Mesh:
    n = len(poly_xy)
    area = sum(
        x0 * y1 - x1 * y0
        for (x0, y0), (x1, y1) in zip(poly_xy, [*poly_xy[1:], poly_xy[0]], strict=True)
    )
    loop = list(range(n)) if area > 0 else list(reversed(range(n)))  # ccw seen from +Z
    verts = [(x, y, z0) for x, y in poly_xy] + [(x, y, z1) for x, y in poly_xy]
    faces = [tuple(reversed(loop)), tuple(n + i for i in loop)]
    for k in range(n):
        a, b = loop[k], loop[(k + 1) % n]
        faces.append((a, b, n + b, n + a))
    mesh = Mesh()
    mesh.add(verts, faces)
    return mesh


def grating(
    length_x: float, width_y: float, height: float, bar: float, spacing: float, frame: float
) -> list[Mesh]:
    """Bar grating as separate closed bars between two closed side frames (no shared faces)."""
    parts = [
        box((-length_x / 2, -width_y / 2, 0.0), (length_x / 2, -width_y / 2 + frame, height)),
        box((-length_x / 2, width_y / 2 - frame, 0.0), (length_x / 2, width_y / 2, height)),
    ]
    inner = width_y - 2 * frame
    count = max(1, int((inner - bar) // spacing))
    gap = (inner - count * bar) / (count + 1)
    y = -width_y / 2 + frame + gap
    for _ in range(count):
        parts.append(box((-length_x / 2 + frame, y, 0.0), (length_x / 2 - frame, y + bar, height)))
        y += bar + gap
    # End frames close the grating without touching the bars.
    parts.append(
        box(
            (-length_x / 2, -width_y / 2 + frame + gap / 2, 0.0),
            (-length_x / 2 + frame * 0.9, width_y / 2 - frame - gap / 2, height),
        )
    )
    parts.append(
        box(
            (length_x / 2 - frame * 0.9, -width_y / 2 + frame + gap / 2, 0.0),
            (length_x / 2, width_y / 2 - frame - gap / 2, height),
        )
    )
    return parts


def merge(parts: Iterable[Mesh]) -> Mesh:
    out = Mesh()
    for part in parts:
        out.extend(part)
    return out


# --------------------------------------------------------------------------
# Convex clipping and Voronoi fracture


@dataclass
class Convex:
    """Convex polyhedron as outward face polygons (each a list of points)."""

    faces: list[list[Vec3]]

    @staticmethod
    def from_mesh(mesh: Mesh) -> Convex:
        return Convex([[mesh.verts[i] for i in face] for face in mesh.faces])

    def clip(self, normal: Vec3, offset: float) -> Convex | None:
        """Keep the part with dot(n, p) <= offset; caps the cut with a new face."""
        out_faces: list[list[Vec3]] = []
        cut_points: list[Vec3] = []
        for face in self.faces:
            kept: list[Vec3] = []
            for a, b in zip(face, [*face[1:], face[0]], strict=True):
                da, db = dot(normal, a) - offset, dot(normal, b) - offset
                if da <= 1e-12:
                    kept.append(a)
                if (da < -1e-12 < db) or (db < -1e-12 < da):
                    t = da / (da - db)
                    p = add(a, scale(sub(b, a), t))
                    kept.append(p)
                    cut_points.append(p)
                elif abs(da) <= 1e-12:
                    cut_points.append(a)
            kept = _dedupe_loop(kept)
            if len(kept) >= 3:
                out_faces.append(kept)
        if not out_faces:
            return None
        # A face already lying in the cut plane is the cap; never add it twice.
        on_plane = any(
            all(abs(dot(normal, p) - offset) <= 1e-9 for p in face) for face in out_faces
        )
        cap = _order_on_plane(_dedupe_points(cut_points), normal)
        if len(cap) >= 3 and not on_plane:
            out_faces.append(cap)
        result = Convex(out_faces)
        return result if result.volume() > 1e-12 else None

    def volume(self) -> float:
        origin = self.faces[0][0]
        vol = 0.0
        for face in self.faces:
            for i in range(1, len(face) - 1):
                vol += (
                    dot(sub(face[0], origin), cross(sub(face[i], origin), sub(face[i + 1], origin)))
                    / 6.0
                )
        return abs(vol)

    def centroid(self) -> Vec3:
        pts = [p for face in self.faces for p in face]
        return scale(
            (sum(p[0] for p in pts), sum(p[1] for p in pts), sum(p[2] for p in pts)), 1.0 / len(pts)
        )

    def to_mesh(self) -> Mesh:
        mesh = Mesh()
        index: dict[tuple, int] = {}
        for face in self.faces:
            loop = []
            for p in face:
                key = tuple(round(c, 7) for c in p)
                if key not in index:
                    index[key] = len(mesh.verts)
                    mesh.verts.append(tuple(p))
                loop.append(index[key])
            loop = [v for k, v in enumerate(loop) if v != loop[k - 1]]
            loop = _drop_collinear(loop, mesh.verts)
            if len(loop) >= 3:
                mesh.faces.append(tuple(loop))
        return mesh


def _drop_collinear(loop: list[int], verts: list[Vec3]) -> list[int]:
    """In a convex polyhedron every true vertex is a corner of each face it is on; points in
    the middle of an edge are clipping leftovers and would make T-junctions."""
    changed = True
    while changed and len(loop) > 3:
        changed = False
        for k in range(len(loop)):
            a, b, c = verts[loop[k - 1]], verts[loop[k]], verts[loop[(k + 1) % len(loop)]]
            if length(cross(sub(b, a), sub(c, b))) < 1e-10 * max(1e-9, length(sub(c, a))):
                del loop[k]
                changed = True
                break
    return loop


def _dedupe_loop(points: list[Vec3]) -> list[Vec3]:
    out: list[Vec3] = []
    for p in points:
        if not out or length(sub(p, out[-1])) > 1e-9:
            out.append(p)
    if len(out) > 1 and length(sub(out[0], out[-1])) <= 1e-9:
        out.pop()
    return out


def _dedupe_points(points: list[Vec3]) -> list[Vec3]:
    out: list[Vec3] = []
    for p in points:
        if all(length(sub(p, q)) > 1e-9 for q in out):
            out.append(p)
    return out


def _order_on_plane(points: list[Vec3], normal: Vec3) -> list[Vec3]:
    """Order a convex polygon counter-clockwise around ``normal`` (the outward cap normal)."""
    if len(points) < 3:
        return points
    c = scale(tuple(map(sum, zip(*points, strict=True))), 1.0 / len(points))
    ref = sub(points[0], c)
    if length(ref) < EPS:
        ref = sub(points[1], c)
    u = scale(ref, 1.0 / length(ref))
    v = cross(normal, u)
    return sorted(points, key=lambda p: math.atan2(dot(sub(p, c), v), dot(sub(p, c), u)))


@dataclass
class Chunk:
    """One fracture chunk: the convex parts of one Voronoi cell."""

    cell: int
    seed_point: Vec3
    parts: list[Convex]

    def volume(self) -> float:
        return sum(p.volume() for p in self.parts)

    def to_mesh(self) -> Mesh:
        return merge(p.to_mesh() for p in self.parts)

    def size(self) -> float:
        """Longest bounding-box edge, metres."""
        lo, hi = self.to_mesh().bounds()
        return max(hi[i] - lo[i] for i in range(3))


def voronoi_points(
    lo: Vec3, hi: Vec3, count: int, seed: int, *, focus: Vec3 | None = None, spread: float = 0.0
) -> list[Vec3]:
    """Seeded cell centres in a box; with ``focus`` half of them cluster around the impact."""
    rng = random.Random(seed)  # noqa: S311 - deterministic art seed, not security
    points = []
    for k in range(count):
        if focus is not None and k % 2 == 0:
            p = tuple(
                min(max(focus[i] + rng.uniform(-spread, spread), lo[i]), hi[i]) for i in range(3)
            )
        else:
            p = tuple(rng.uniform(lo[i], hi[i]) for i in range(3))
        points.append(p)
    return points


def fracture(parts: Sequence[Mesh], points: Sequence[Vec3]) -> list[Chunk]:
    """Voronoi fracture of convex solid parts by seeded cell centres."""
    convex_parts = [Convex.from_mesh(p) for p in parts]
    chunks = []
    for ci, c in enumerate(points):
        cell_parts = []
        for part in convex_parts:
            piece: Convex | None = part
            for oi, o in enumerate(points):
                if oi == ci or piece is None:
                    continue
                n = sub(o, c)
                if length(n) < EPS:
                    continue
                mid = scale(add(o, c), 0.5)
                piece = piece.clip(n, dot(n, mid))
            if piece is not None:
                cell_parts.append(piece)
        if cell_parts:
            chunks.append(Chunk(ci, tuple(c), cell_parts))
    return chunks
