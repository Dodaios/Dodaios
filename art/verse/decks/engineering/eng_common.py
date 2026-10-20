"""Shared layout constants and geometry helpers of the engineering deck.

Layout numbers are written in three.js metres as in LEVELS.md (x = screen
right, z = toward the camera, y = up, z = 0 at the far hull wall). Geometry is
emitted in Blender axes through ``b()`` / ``Geo``: Blender (x, y, z) =
three (x, -z, y).
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import bpy
from lib import kit, scene
from mathutils import Vector

# Kit availability, decided once per build by build.py.
KIT_REACTOR = False  # props-industrial reactor assembly (place_reactor)
KIT_COMMAND = False  # props-command terminal modules and master desk
KIT_ARCH = False  # kit-artist walls, doors, ceilings
COLLAR_HALF = 15.6  # half side of the reactor collar square left open in the deck

# ---------------------------------------------------------------- deck size
DECK_W = 84.0
DECK_D = 54.0
MODULE = kit.MODULE
CUT_H = 1.1

# ---------------------------------------------------------------- heights
HALL_H = 12.0  # reactor hall ceiling and the far hull wall
CONTROL_H = 4.5  # engineering control room ceiling (kit wall height)
GALLERY_H = 4.8
LOBBY_H = 4.2
BAY_H = 4.8
SLAB_T = 0.4  # deck slab thickness under the walking surface
HULL_BOTTOM = -3.0  # under-deck structure seen at the near edge

# ---------------------------------------------------------------- reactor
SHAFT_C = (54.0, 22.0)  # three (x, z)
SHAFT_R = 13.0  # inner rim radius (edge of the drop)
SHAFT_WALL_R = 13.8  # outer radius of the shaft wall
SHAFT_DEPTH = 52.0  # visible depth below the deck
KERB_R = (13.0, 13.4)
KERB_H = 0.25
HAZARD_R = (13.4, 14.2)
RING_R = (5.0, 6.5)
CORE_R = 3.0
CATWALK_W = 1.2
CATWALK_GAP = 1.6  # kerb gap at a catwalk entry
CATWALK_ANGLES = (90.0, 0.0, 270.0, 180.0)  # N, E, S, W in Blender polar degrees

# ---------------------------------------------------------------- rooms (three x0, x1, z0, z1)
CONTROL = (2.0, 32.0, 2.0, 40.6)
HALL = (33.0, 82.0, 2.0, 38.1)
GALLERY = (34.0, 82.0, 38.4, 52.0)
LOBBY = (2.0, 14.6, 41.4, 52.0)
BAY = (15.4, 32.0, 41.4, 52.0)

# walls (three)
FAR_WALL_Z = 2.0  # room face of the far hull wall
PARTITION_X = (32.0, 33.0)  # glass partition control room | reactor hall
CONTROL_SOUTH_Z = (41.1, 41.4)  # cut wall control room | lobby + bay
GALLERY_NORTH_Z = (38.1, 38.4)  # cut wall reactor hall | gallery
SOUTH_HULL_Z = (52.0, 54.0)  # near hull wall (cut)
LOBBY_BAY_X = (14.6, 15.4)
BAY_GALLERY_X = (32.0, 34.0)
EAST_HULL_X = (82.0, 84.0)
WEST_HULL_X = (0.0, 2.0)

# doors: (wall, centre, width) in three metres along the wall
DOOR_CONTROL_LOBBY = 12.2  # x on CONTROL_SOUTH_Z (1.2 m grid from x 2.0)
DOOR_CONTROL_BAY = 23.0
DOOR_PARTITION = 22.0  # z on PARTITION_X, on the west catwalk's axis
DOOR_LOBBY_BAY = 47.0  # z on LOBBY_BAY_X
DOOR_BAY_GALLERY = 46.4  # z on BAY_GALLERY_X
GALLERY_OPENINGS = (39.6, 54.0, 72.0)  # x on GALLERY_NORTH_Z
DOOR_W = 2.4

# terminals: screen-line z of the three rows, x of the four columns
TERM_ROWS_Z = (14.4, 22.8, 31.2)
TERM_COLS_X = (7.4, 12.2, 21.8, 26.6)
MASTER_X = 17.0
MASTER_Z = 4.6  # front edge of the master systems console

# lift
LIFT_X = 4.4
LIFT_CORE_Z = (40.0, 41.4)  # full-height lift core north of the lobby wall face
LIFT_CORE_X = (2.0, 6.8)  # lift door module flanked by full-height modules


def kit_module(name: str) -> bool:
    """Import a kit props package (registers its pieces); False when missing."""
    import importlib

    try:
        importlib.import_module(name)
    except ImportError as error:
        print(f"[verse] engineering: {name} unavailable, using deck blockout ({error})")
        return False
    return True


def b(x: float, z: float, y: float = 0.0) -> tuple[float, float, float]:
    """three.js (x, z) on the floor plus height y -> Blender (x, y, z)."""
    return (x, -z, y)


def shaft_point(radius: float, angle_deg: float, y: float = 0.0) -> tuple[float, float, float]:
    """Blender point at polar (radius, angle) around the shaft axis; angle 90 = north."""
    cx, cz = SHAFT_C
    a = math.radians(angle_deg)
    return (cx + radius * math.cos(a), -cz + radius * math.sin(a), y)


class Geo(kit.MeshBuilder):
    """MeshBuilder with three.js-layout helpers."""

    def box3(self, x0: float, x1: float, z0: float, z1: float, y0: float, y1: float, mat: str):
        """Axis-aligned box from three.js ranges."""
        return self.box((x0, -z1, y0), (x1, -z0, y1), mat)

    def slab3(
        self,
        x0: float,
        x1: float,
        z0: float,
        z1: float,
        y0: float,
        y1: float,
        mat: str,
        cap: str | None = None,
    ):
        """Box whose top face gets `cap` (section cap of a cut wall, floor top...)."""
        poly = [(x0, -z1), (x1, -z1), (x1, -z0), (x0, -z0)]
        return self.prism_z(poly, y0, y1, mat, cap)

    def sector(
        self,
        r0: float,
        r1: float,
        y0: float,
        y1: float,
        mat: str,
        a0: float = 0.0,
        a1: float = 360.0,
        segments: int | None = None,
        centre: Sequence[float] | None = None,
        top: str | None = None,
        inner: str | None = None,
    ):
        """Closed annulus sector around the shaft axis (or `centre`, Blender XY)."""
        cx, cy = centre if centre is not None else (SHAFT_C[0], -SHAFT_C[1])
        span = a1 - a0
        full = abs(span) >= 359.999
        n = segments or max(4, int(abs(span) / 360.0 * 160))
        if r0 <= 1e-6 and full:
            return self._disc(cx, cy, r1, y0, y1, n, mat, top or mat)
        angles = [math.radians(a0 + span * i / n) for i in range(n + (0 if full else 1))]
        rings = []
        for r, z in ((r0, y0), (r1, y0), (r1, y1), (r0, y1)):
            rings.append(
                [
                    self.bm.verts.new(
                        self.matrix @ Vector((cx + r * math.cos(a), cy + r * math.sin(a), z))
                    )
                    for a in angles
                ]
            )
        count = len(angles)
        steps = count if full else count - 1
        mats = {
            "bottom": self._mat_index(mat),
            "outer": self._mat_index(mat),
            "top": self._mat_index(top or mat),
            "inner": self._mat_index(inner or mat),
        }
        sides = (("bottom", 0, 1), ("outer", 1, 2), ("top", 2, 3), ("inner", 3, 0))
        for i in range(steps):
            j = (i + 1) % count
            for key, ra, rb in sides:
                face = self.bm.faces.new((rings[ra][i], rings[ra][j], rings[rb][j], rings[rb][i]))
                face.material_index = mats[key]
                face.smooth = key in ("outer", "inner")
        if not full:
            for idx in (0, count - 1):
                face = self.bm.faces.new([rings[k][idx] for k in range(4)])
                face.material_index = mats["bottom"]
        return self

    def _disc(self, cx, cy, radius, y0, y1, n, mat, top):
        """Closed vertical cylinder as n-gon caps plus a smooth side."""
        steps = [2 * math.pi * i / n for i in range(n)]
        ring = [(cx + radius * math.cos(a), cy + radius * math.sin(a)) for a in steps]
        low = [self.bm.verts.new(self.matrix @ Vector((x, y, y0))) for x, y in ring]
        high = [self.bm.verts.new(self.matrix @ Vector((x, y, y1))) for x, y in ring]
        m_side, m_top = self._mat_index(mat), self._mat_index(top)
        self.bm.faces.new(list(reversed(low))).material_index = m_side
        self.bm.faces.new(high).material_index = m_top
        for i in range(n):
            j = (i + 1) % n
            face = self.bm.faces.new((low[i], low[j], high[j], high[i]))
            face.material_index = m_side
            face.smooth = True
        return self

    def plate_with_hole(
        self,
        x0: float,
        x1: float,
        z0: float,
        z1: float,
        y0: float,
        y1: float,
        radius: float,
        mat: str,
        top: str | None = None,
        half: float = 14.0,
    ):
        """Rectangular slab with the circular shaft hole cut out of it.

        The square of side 2*half around the shaft is an annulus from the hole
        to the square; the rest of the rectangle is plain boxes.
        """
        cx, cz = SHAFT_C
        sx0, sx1, sz0, sz1 = cx - half, cx + half, cz - half, cz + half
        self._square_annulus(radius, half, y0, y1, mat, top or mat)
        for bx0, bx1, bz0, bz1 in (
            (x0, x1, z0, sz0),
            (x0, x1, sz1, z1),
            (x0, sx0, sz0, sz1),
            (sx1, x1, sz0, sz1),
        ):
            if bx1 - bx0 > 1e-6 and bz1 - bz0 > 1e-6:
                self.slab3(bx0, bx1, bz0, bz1, y0, y1, mat, top)
        return self

    def plate_with_square_hole(
        self, x0: float, x1: float, z0: float, z1: float, y0: float, y1: float, half: float,
        mat: str, top: str | None = None,
    ):  # fmt: skip
        """Rectangular slab minus the square of side 2*half around the shaft."""
        cx, cz = SHAFT_C
        sx0, sx1, sz0, sz1 = cx - half, cx + half, cz - half, cz + half
        for bx0, bx1, bz0, bz1 in (
            (x0, x1, z0, max(z0, sz0)),
            (x0, x1, min(z1, sz1), z1),
            (x0, max(x0, sx0), max(z0, sz0), min(z1, sz1)),
            (min(x1, sx1), x1, max(z0, sz0), min(z1, sz1)),
        ):
            if bx1 - bx0 > 1e-6 and bz1 - bz0 > 1e-6:
                self.slab3(bx0, bx1, bz0, bz1, y0, y1, mat, top)
        return self

    def _square_annulus(self, radius: float, half: float, y0: float, y1: float, mat: str, top: str):
        cx, cy = SHAFT_C[0], -SHAFT_C[1]
        n = 160
        angles = sorted({i * 360.0 / n for i in range(n)} | {45.0, 135.0, 225.0, 315.0})
        inner, outer = [], []
        for a in angles:
            r = math.radians(a)
            c, s = math.cos(r), math.sin(r)
            inner.append((cx + radius * c, cy + radius * s))
            k = half / max(abs(c), abs(s))
            outer.append((cx + k * c, cy + k * s))
        rings = []
        for pts, z in ((inner, y0), (outer, y0), (outer, y1), (inner, y1)):
            rings.append([self.bm.verts.new(self.matrix @ Vector((x, y, z))) for x, y in pts])
        m_side = self._mat_index(mat)
        m_top = self._mat_index(top)
        count = len(angles)
        for i in range(count):
            j = (i + 1) % count
            for ra, rb, mi in ((0, 1, m_side), (1, 2, m_side), (2, 3, m_top), (3, 0, m_side)):
                face = self.bm.faces.new((rings[ra][i], rings[ra][j], rings[rb][j], rings[rb][i]))
                face.material_index = mi

    def cylinder(
        self,
        x: float,
        z: float,
        radius: float,
        y0: float,
        y1: float,
        mat: str,
        segments: int = 32,
    ):
        """Vertical cylinder at three (x, z)."""
        return self.tube((x, -z, y0), (x, -z, y1), radius, mat, segments)

    def pipe3(
        self, points3: Sequence[Sequence[float]], radius: float, mat: str, segments: int = 16
    ):
        """Polyline pipe through three-space points (x, y, z) with joint spheres omitted."""
        pts = [(p[0], -p[2], p[1]) for p in points3]
        return self.polyline_tube(pts, radius, mat, segments)


def build_into(
    collection_name: str, geo: Geo, name: str, **build_kwargs
) -> bpy.types.Object | None:
    """Build `geo` as object `name` into one deck collection."""
    with kit.into(scene.collection(collection_name)):
        return geo.build(name, **build_kwargs)


def deck_material(name: str, viewport=(0.5, 0.5, 0.5)):
    """Register a deck-local material builder in the shared library (by name)."""
    from lib import materials

    return materials.material(name, viewport)


# ---------------------------------------------------------------- occluders


def ucx3(occluder_id: str, x0: float, x1: float, z0: float, z1: float, y0: float, y1: float):
    """Axis-aligned UCX_ occluder from three.js ranges."""
    return scene.add_ucx_box(occluder_id, (x0, -z1, y0), (x1, -z0, y1))


def ucx_cylinder(
    occluder_id: str, x: float, z: float, radius: float, y0: float, y1: float, sides: int = 16
):
    """Vertical prism occluder circumscribing a cylinder at three (x, z)."""
    r = radius / math.cos(math.pi / sides)
    ring = [
        (x + r * math.cos(2 * math.pi * i / sides), -z + r * math.sin(2 * math.pi * i / sides))
        for i in range(sides)
    ]
    verts = [(px, py, y0) for px, py in ring] + [(px, py, y1) for px, py in ring]
    faces = [tuple(reversed(range(sides))), tuple(range(sides, 2 * sides))]
    faces += [(i, (i + 1) % sides, sides + (i + 1) % sides, sides + i) for i in range(sides)]
    name = f"UCX_{occluder_id}"
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    obj = bpy.data.objects.new(name, mesh)
    obj.display_type = "WIRE"
    scene.collection("Occluders").objects.link(obj)
    return obj
