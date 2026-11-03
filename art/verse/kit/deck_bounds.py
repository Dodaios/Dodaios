"""Deck bounds: simple collision for a deck's bespoke geometry, from today's nav (WP12.4-12.7).

Pure Python (numpy, Pillow), no bpy. The zone shells are joined bespoke meshes (hull,
walls, bulkheads, glazing, floors); their own collision would be the triangles, which
art-pipeline 5 forbids for pawns. Instead every zone gets a set of boxes that make the
commander walk exactly where today's three.js deck lets them: today's cooked nav grid
(`public/verse/decks/<deck>/nav.png`, `manifest.nav`, 0.2 m cells, 0 = blocked, else the
floor height) is the reference.

* Floors: per zone and floor height band (0.1 m), the walkable cells are covered by
  axis-aligned rectangles, each a 0.2 m slab under the floor. A rectangle may run over
  blocked cells of its own rooms (props and walls stand there anyway) but never over a
  walkable cell of another height, so pits, steps and the reactor ring keep their levels.
  Cells under a kit piece with its own walkable collision (the stairs) are left to it.
* Walls: every edge between a walkable cell and a cell the commander cannot step to
  (blocked, or a drop deeper than `max_step`) becomes part of a wall line, except next to
  a prop that blocks on its own. Lines are simplified (Douglas-Peucker, 0.25 m) and each
  segment becomes a 0.3 m thick box on the blocked side, from 1.5 m below to 3 m above
  the floor (art-pipeline 5: at least 20 cm thick). Doorways stay open: walkable cells on
  both sides of a doorway share no edge.

`deck_import.py` puts the boxes into the zone spec; `deck_export_blender.py` turns each
group of at most 16 (`unreal_export.MAX_PRIMITIVES`) into one hidden proxy mesh
`SM_<Deck>_<Zone>_Bounds[<n>]` with profile `Verse_ProxyOnly`; the deck subsystem hides
those actors in game.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

#: Floor height bands, m.
BAND_M = 0.1
#: Slab thickness under a floor, m.
FLOOR_THICKNESS_M = 0.2
#: Wall box thickness (art-pipeline 5: at least 0.2 m), height above and depth below the floor.
WALL_THICKNESS_M = 0.3
WALL_ABOVE_M = 3.0
WALL_BELOW_M = 1.5
#: Line simplification tolerance and the shortest wall segment kept, m.
SIMPLIFY_M = 0.25
MIN_SEGMENT_M = 0.4
#: Wall segments this close to a grid axis are snapped onto it, degrees.
SNAP_DEG = 4.0
#: Closed wall loops shorter than this (thin poles with today's clearance) are dropped, m.
MIN_LOOP_M = 2.4
#: Walls this many cells around a blocking prop are left to the prop's own collision.
PROP_MARGIN_CELLS = 2
#: Floor bands smaller than this many cells are ignored.
MIN_BAND_CELLS = 3


@dataclass(frozen=True)
class Nav:
    """Today's nav grid of one deck: `walk[row, col]`, `height[row, col]` (three.js metres)."""

    walk: np.ndarray
    height: np.ndarray
    cell: float
    origin_x: float
    origin_z: float
    max_step: float

    @property
    def shape(self) -> tuple[int, int]:
        return self.walk.shape

    def centre(self, row: float, col: float) -> tuple[float, float]:
        """three.js (x, z) of a cell centre (or of any fractional cell position)."""
        return (self.origin_x + (col + 0.5) * self.cell, self.origin_z + (row + 0.5) * self.cell)

    def corner(self, row: float, col: float) -> tuple[float, float]:
        """three.js (x, z) of a grid vertex."""
        return (self.origin_x + col * self.cell, self.origin_z + row * self.cell)


def load_nav(deck_dir: Path, meta: Mapping) -> Nav:
    codes = np.array(Image.open(deck_dir / meta["url"]).convert("L"), dtype=np.int32)
    if codes.shape != (meta["h"], meta["w"]):
        size = f"{meta['h']}x{meta['w']}"
        raise ValueError(f"{deck_dir.name}: nav.png is {codes.shape}, manifest says {size}")
    walk = codes > 0
    height = (codes - meta["height_zero"]) * meta["height_step"]
    return Nav(
        walk=walk,
        height=np.where(walk, height, np.nan),
        cell=float(meta["cell"]),
        origin_x=float(meta["origin_x"]),
        origin_z=float(meta["origin_z"]),
        max_step=float(meta["max_step"]),
    )


# --------------------------------------------------------------------------
# Rasters
# --------------------------------------------------------------------------


def polygon_mask(nav: Nav, polygon: Sequence[Sequence[float]]) -> np.ndarray:
    """Cells whose centre lies inside a three.js [x, z] polygon (even-odd rule)."""
    rows, cols = nav.shape
    xs = nav.origin_x + (np.arange(cols) + 0.5) * nav.cell
    zs = nav.origin_z + (np.arange(rows) + 0.5) * nav.cell
    px, pz = np.meshgrid(xs, zs)
    inside = np.zeros(nav.shape, dtype=bool)
    points = [(float(x), float(z)) for x, z in polygon]
    j = len(points) - 1
    for i in range(len(points)):
        xi, zi = points[i]
        xj, zj = points[j]
        if zi != zj:
            crosses = (zi > pz) != (zj > pz)
            at = (xj - xi) * (pz - zi) / (zj - zi) + xi
            inside ^= crosses & (px < at)
        j = i
    return inside


def dilate(mask: np.ndarray, cells: int) -> np.ndarray:
    out = mask.copy()
    for _ in range(cells):
        grown = out.copy()
        grown[1:, :] |= out[:-1, :]
        grown[:-1, :] |= out[1:, :]
        grown[:, 1:] |= out[:, :-1]
        grown[:, :-1] |= out[:, 1:]
        out = grown
    return out


def footprint_mask(
    nav: Nav, corners_xz: Iterable[Sequence[float]], inset: float = 0.1
) -> np.ndarray:
    """Cells under the axis-aligned box around some three.js (x, z) points, inset a little."""
    pts = np.array(list(corners_xz), dtype=float)
    lo = pts.min(axis=0) + inset
    hi = pts.max(axis=0) - inset
    mask = np.zeros(nav.shape, dtype=bool)
    rows, cols = nav.shape
    c0 = max(0, int(math.floor((lo[0] - nav.origin_x) / nav.cell)))
    c1 = min(cols, int(math.ceil((hi[0] - nav.origin_x) / nav.cell)))
    r0 = max(0, int(math.floor((lo[1] - nav.origin_z) / nav.cell)))
    r1 = min(rows, int(math.ceil((hi[1] - nav.origin_z) / nav.cell)))
    if c1 > c0 and r1 > r0:
        mask[r0:r1, c0:c1] = True
    return mask


# --------------------------------------------------------------------------
# Floors: rectangles over the walkable cells of a band
# --------------------------------------------------------------------------


def cover(target: np.ndarray, allowed: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Rectangles (r0, c0, r1, c1), inclusive, inside `allowed | target`, covering `target`.

    Greedy: each step grows a rectangle from the first uncovered target cell, first
    along rows then columns and the other way round, and keeps the one that covers
    more uncovered target cells. Deterministic.
    """
    allowed = allowed | target
    rows, cols = target.shape
    acc = np.zeros((rows + 1, cols + 1), dtype=np.int64)
    acc[1:, 1:] = allowed.astype(np.int64).cumsum(0).cumsum(1)

    def full(r0: int, c0: int, r1: int, c1: int) -> bool:
        total = acc[r1 + 1, c1 + 1] - acc[r0, c1 + 1] - acc[r1 + 1, c0] + acc[r0, c0]
        return total == (r1 - r0 + 1) * (c1 - c0 + 1)

    todo = target.copy()
    out = []
    for r, c in zip(*np.nonzero(target), strict=True):
        if not todo[r, c]:
            continue
        best = None
        for order in ("rc", "cr"):
            r0, c0, r1, c1 = r, c, r, c
            for axis in order:
                if axis == "c":
                    while c0 > 0 and full(r0, c0 - 1, r1, c0 - 1):
                        c0 -= 1
                    while c1 < cols - 1 and full(r0, c1 + 1, r1, c1 + 1):
                        c1 += 1
                else:
                    while r0 > 0 and full(r0 - 1, c0, r0 - 1, c1):
                        r0 -= 1
                    while r1 < rows - 1 and full(r1 + 1, c0, r1 + 1, c1):
                        r1 += 1
            gain = int(todo[r0 : r1 + 1, c0 : c1 + 1].sum())
            if best is None or gain > best[0]:
                best = (gain, (int(r0), int(c0), int(r1), int(c1)))
        r0, c0, r1, c1 = best[1]
        todo[r0 : r1 + 1, c0 : c1 + 1] = False
        out.append(best[1])
    return out


def bands(nav: Nav, cells: np.ndarray) -> dict[int, np.ndarray]:
    """Band index (height / BAND_M, rounded) -> its walkable cells within `cells`."""
    index = np.where(nav.walk, np.round(np.nan_to_num(nav.height) / BAND_M), 0).astype(np.int64)
    out = {}
    for band in sorted(set(index[cells & nav.walk].tolist())):
        sel = cells & nav.walk & (index == band)
        if int(sel.sum()) >= MIN_BAND_CELLS:
            out[band] = sel
    return out


# --------------------------------------------------------------------------
# Walls: lines along the walkable boundary
# --------------------------------------------------------------------------

_DIRS = ((1, 0), (-1, 0), (0, 1), (0, -1))


def boundary_edges(nav: Nav, cells: np.ndarray, skip: np.ndarray):
    """Unit edges (vertex a, vertex b, band, outward (dx, dz)) of the walkable cells in `cells`.

    Vertices are (row, col) grid corners. An edge separates a walkable cell from a
    neighbour the commander cannot step to; edges whose neighbour is in `skip` are left out.
    """
    rows, cols = nav.shape
    edges = []
    for r, c in zip(*np.nonzero(cells & nav.walk), strict=True):
        h = nav.height[r, c]
        band = int(round(h / BAND_M))
        for dr, dc in _DIRS:
            rr, cc = r + dr, c + dc
            inside = 0 <= rr < rows and 0 <= cc < cols
            if inside and nav.walk[rr, cc] and abs(nav.height[rr, cc] - h) <= nav.max_step:
                continue
            if inside and skip[rr, cc]:
                continue
            if dr == 1:
                a, b = (r + 1, c), (r + 1, c + 1)
            elif dr == -1:
                a, b = (r, c), (r, c + 1)
            elif dc == 1:
                a, b = (r, c + 1), (r + 1, c + 1)
            else:
                a, b = (r, c), (r + 1, c)
            edges.append((a, b, band, (dc, dr)))
    return edges


def chains(edges):
    """Join unit edges into polylines: [(points, normals, band, closed)], in grid corners."""
    by_vertex: dict[tuple, list[int]] = {}
    for i, (a, b, band, _n) in enumerate(edges):
        by_vertex.setdefault((a, band), []).append(i)
        by_vertex.setdefault((b, band), []).append(i)
    used = [False] * len(edges)
    out = []

    def walk_from(start: int, vertex, band):
        points = [vertex]
        normals = []
        current = start
        while True:
            used[current] = True
            a, b, _band, normal = edges[current]
            vertex = b if a == vertex else a
            points.append(vertex)
            normals.append(normal)
            nxt = [j for j in by_vertex[(vertex, band)] if not used[j]]
            if len(by_vertex[(vertex, band)]) != 2 or not nxt:
                return points, normals
            current = nxt[0]

    # Open chains start at vertices that do not have exactly two edges.
    for (vertex, band), ids in sorted(by_vertex.items()):
        if len(ids) == 2:
            continue
        for i in ids:
            if not used[i]:
                points, normals = walk_from(i, vertex, band)
                out.append((points, normals, band, False))
    for i, (a, _b, band, _n) in enumerate(edges):
        if not used[i]:
            points, normals = walk_from(i, a, band)
            out.append((points, normals, band, points[0] == points[-1]))
    return out


def simplify(points: Sequence[tuple[float, float]], tol: float) -> list[int]:
    """Indices kept by Douglas-Peucker."""
    if len(points) < 3:
        return list(range(len(points)))
    keep = {0, len(points) - 1}
    stack = [(0, len(points) - 1)]
    pts = np.asarray(points, dtype=float)
    while stack:
        i0, i1 = stack.pop()
        if i1 - i0 < 2:
            continue
        a, b = pts[i0], pts[i1]
        d = b - a
        length = math.hypot(d[0], d[1])
        seg = pts[i0 + 1 : i1]
        if length < 1e-12:
            dist = np.hypot(seg[:, 0] - a[0], seg[:, 1] - a[1])
        else:
            dist = np.abs(d[0] * (seg[:, 1] - a[1]) - d[1] * (seg[:, 0] - a[0])) / length
        k = int(np.argmax(dist))
        if dist[k] > tol:
            mid = i0 + 1 + k
            keep.add(mid)
            stack += [(i0, mid), (mid, i1)]
    return sorted(keep)


# --------------------------------------------------------------------------
# Boxes
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Box:
    """A collision box in three.js space: centre (x, y up, z), size along its own axes, yaw.

    `yaw` turns the box's length axis from three.js +X toward +Z, radians.
    """

    kind: str  # "floor" or "wall"
    centre: tuple[float, float, float]
    size: tuple[float, float, float]  # length (along yaw), height, width
    yaw: float = 0.0


def floor_boxes(
    nav: Nav, zone_cells: np.ndarray, room_cells: np.ndarray, own: np.ndarray
) -> list[Box]:
    out = []
    for band, target in bands(nav, zone_cells & ~own).items():
        level = band * BAND_M
        # A band's slab may run over blocked cells of the zone's rooms, never over other walk.
        allowed = room_cells & ~nav.walk
        for r0, c0, r1, c1 in cover(target, allowed):
            x0, z0 = nav.corner(r0, c0)
            x1, z1 = nav.corner(r1 + 1, c1 + 1)
            out.append(
                Box(
                    "floor",
                    ((x0 + x1) / 2, level - FLOOR_THICKNESS_M / 2, (z0 + z1) / 2),
                    (x1 - x0, FLOOR_THICKNESS_M, z1 - z0),
                )
            )
    return out


def wall_boxes(nav: Nav, zone_cells: np.ndarray, skip: np.ndarray) -> list[Box]:
    out = []
    for corners, normals, band, closed in chains(boundary_edges(nav, zone_cells, skip)):
        points = [nav.corner(r, c) for r, c in corners]
        lengths = [math.dist(points[i], points[i + 1]) for i in range(len(points) - 1)]
        if closed and sum(lengths) < MIN_LOOP_M:
            continue
        level = band * BAND_M
        kept = simplify(points, SIMPLIFY_M)
        for i0, i1 in zip(kept, kept[1:], strict=False):
            a, b = np.array(points[i0]), np.array(points[i1])
            length = float(np.hypot(*(b - a)))
            if length < MIN_SEGMENT_M:
                continue
            outward = np.array(normals[i0:i1], dtype=float).sum(axis=0)
            direction = (b - a) / length
            yaw = math.atan2(direction[1], direction[0])
            # A segment within SNAP_DEG of a grid axis is a grid wall the simplification
            # bent by a cell: keep it on the axis.
            snapped = round(yaw / (math.pi / 2)) * (math.pi / 2)
            if abs(yaw - snapped) <= math.radians(SNAP_DEG):
                yaw = snapped
                direction = np.array([math.cos(yaw), math.sin(yaw)])
            normal = np.array([-direction[1], direction[0]])
            if float(normal @ outward) < 0:
                normal = -normal
            centre = (a + b) / 2 + normal * (WALL_THICKNESS_M / 2)
            low, high = level - WALL_BELOW_M, level + WALL_ABOVE_M
            out.append(
                Box(
                    "wall",
                    (float(centre[0]), (low + high) / 2, float(centre[1])),
                    (length + WALL_THICKNESS_M, high - low, WALL_THICKNESS_M),
                    yaw,
                )
            )
    return out


def deck_boxes(
    nav: Nav,
    zones: Mapping[str, Sequence[Sequence[Sequence[float]]]],
    props_xz: Iterable[Sequence[Sequence[float]]],
    own_walk_xz: Iterable[Sequence[Sequence[float]]],
    *,
    strict: bool = False,
) -> dict[str, list[Box]]:
    """Zone id -> floor and wall boxes.

    `zones` maps each zone to its room polygons (three.js [x, z]); `props_xz` are the
    footprint corners of the props that block on their own; `own_walk_xz` those of the kit
    pieces with their own walkable collision (stairs). Walkable cells outside every room
    go to the nearest zone within 1 m, unless `strict`.
    """
    rooms = {zone: [polygon_mask(nav, p) for p in polygons] for zone, polygons in zones.items()}
    room_cells = {
        zone: np.logical_or.reduce(masks) if masks else np.zeros(nav.shape, bool)
        for zone, masks in rooms.items()
    }
    owner = np.full(nav.shape, -1, dtype=np.int64)
    names = sorted(zones)
    for index, zone in enumerate(names):
        owner[room_cells[zone] & (owner < 0)] = index
    if not strict:
        for _ in range(5):  # 1 m of 0.2 m cells
            grown = owner.copy()
            for dr, dc in _DIRS:
                shifted = np.full(nav.shape, -1, dtype=np.int64)
                rs = slice(max(dr, 0), nav.shape[0] + min(dr, 0))
                rd = slice(max(-dr, 0), nav.shape[0] + min(-dr, 0))
                cs = slice(max(dc, 0), nav.shape[1] + min(dc, 0))
                cd = slice(max(-dc, 0), nav.shape[1] + min(-dc, 0))
                shifted[rd, cd] = owner[rs, cs]
                grown = np.where((grown < 0) & (shifted >= 0), shifted, grown)
            owner = grown
    props = np.zeros(nav.shape, dtype=bool)
    for corners in props_xz:
        props |= footprint_mask(nav, corners)
    own = np.zeros(nav.shape, dtype=bool)
    for corners in own_walk_xz:
        own |= footprint_mask(nav, corners, inset=0.0)
    skip = dilate(props, PROP_MARGIN_CELLS)
    out = {}
    for index, zone in enumerate(names):
        cells = owner == index
        floors = floor_boxes(nav, cells, room_cells[zone] | cells, own)
        out[zone] = floors + wall_boxes(nav, cells, skip)
    return out


def to_blender(box: Box) -> dict:
    """A box in Blender metres: centre, size (x, y, z) and yaw about +Z in degrees."""
    x, y, z = box.centre
    length, height, width = box.size
    # three.js (x, y, z) -> Blender (x, -z, y); a yaw from +X toward three.js +Z turns toward -Y.
    return {
        "kind": box.kind,
        "centre": [round(x, 4), round(-z, 4), round(y, 4)],
        "size": [round(length, 4), round(width, 4), round(height, 4)],
        "yaw_deg": round(-math.degrees(box.yaw), 4),
    }


def dumps(boxes: Mapping[str, list[Box]]) -> str:
    return json.dumps({z: [to_blender(b) for b in bs] for z, bs in sorted(boxes.items())}, indent=1)
