"""Geometry helpers for the Operations deck builder (runs inside Blender).

The deck is laid out in three.js metres, exactly like LEVELS.md: ``x`` grows to
screen right, ``z`` grows toward the camera (screen bottom), ``h`` is height
above the deck. Blender axes are ``(x, -z, h)``. Everything here converts at
the last moment so the layout code reads like the level table.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import bpy
from lib import kit, scene
from mathutils import Matrix, Vector

CUT_H = 1.1  # section plane of every wall with walkable space behind it


def P(x: float, z: float, h: float = 0.0) -> tuple[float, float, float]:
    """three.js axes (x, z, h) -> Blender (x, y, z)."""
    return (x, -z, h)


def collection(name: str) -> bpy.types.Collection:
    return scene.collection(name)


class Mesh:
    """A kit.MeshBuilder that speaks deck coordinates (x, z, h)."""

    def __init__(self) -> None:
        self.mb = kit.MeshBuilder()

    # -- primitives ---------------------------------------------------------

    def box(self, x0, x1, z0, z1, h0, h1, mat: str) -> Mesh:
        """Axis-aligned box spanning x0..x1, z0..z1, h0..h1."""
        if x1 - x0 < 1e-5 or z1 - z0 < 1e-5 or h1 - h0 < 1e-5:
            return self
        self.mb.box((x0, -z1, h0), (x1, -z0, h1), mat)
        return self

    def boxc(self, cx, cz, h0, sx, sz, sh, mat: str) -> Mesh:
        """Box centred on (cx, cz) in plan, from h0 up by sh."""
        return self.box(cx - sx / 2, cx + sx / 2, cz - sz / 2, cz + sz / 2, h0, h0 + sh, mat)

    def prism_x(
        self,
        profile_zh: Sequence[tuple[float, float]],
        x0: float,
        x1: float,
        mat: str,
        side_mats: dict[int, str] | None = None,
        cap_mat: str | None = None,
    ) -> Mesh:
        """Extrude a closed (z, h) profile along x. ``side_mats`` maps the
        index of a profile edge (i -> i+1) to its own material (e.g. a cut cap)."""
        pts = [(-z, h) for z, h in profile_zh]
        if _area(pts) < 0:
            pts = pts[::-1]
            n = len(pts)
            # edge i of the reversed loop is edge (n - 2 - i) % n of the original
            remap = {(n - 2 - i) % n: i for i in range(n)}
            side_mats = {remap[k]: v for k, v in (side_mats or {}).items()}
        n = len(pts)
        verts = [Vector((x0, y, z)) for y, z in pts] + [Vector((x1, y, z)) for y, z in pts]
        mb = self.mb
        for i in range(n):
            face = [(i, (i + 1) % n, n + (i + 1) % n, n + i)]
            mb._add(verts, face, (side_mats or {}).get(i, mat))
        cap = cap_mat or mat
        mb._add(verts, [tuple(reversed(range(n))), tuple(range(n, 2 * n))], cap)
        return self

    def prism_z(
        self,
        profile_xh: Sequence[tuple[float, float]],
        z0: float,
        z1: float,
        mat: str,
        side_mats: dict[int, str] | None = None,
        cap_mat: str | None = None,
    ) -> Mesh:
        """Extrude a closed (x, h) profile along z (three.js), i.e. along -Y."""
        pts = list(profile_xh)
        if _area(pts) < 0:
            pts = pts[::-1]
            n = len(pts)
            remap = {(n - 2 - i) % n: i for i in range(n)}
            side_mats = {remap[k]: v for k, v in (side_mats or {}).items()}
        n = len(pts)
        # Profile in the XZ plane (Blender), extruded from y=-z0 to y=-z1.
        verts = [Vector((x, -z0, h)) for x, h in pts] + [Vector((x, -z1, h)) for x, h in pts]
        mb = self.mb
        for i in range(n):
            face = [(i, (i + 1) % n, n + (i + 1) % n, n + i)]
            mb._add(verts, face, (side_mats or {}).get(i, mat))
        cap = cap_mat or mat
        mb._add(verts, [tuple(reversed(range(n))), tuple(range(n, 2 * n))], cap)
        return self

    def cyl(self, cx, cz, r, h0, h1, mat: str, segments: int = 24) -> Mesh:
        self.mb.tube((cx, -cz, h0), (cx, -cz, h1), r, mat, segments)
        return self

    def tube(self, p0, p1, r, mat: str, segments: int = 12) -> Mesh:
        """Tube between two (x, z, h) points."""
        self.mb.tube(P(*p0), P(*p1), r, mat, segments)
        return self

    def quad_h(self, x0, x1, z0, z1, h, mat: str, up: bool = True) -> Mesh:
        """Horizontal quad (decal, emitter) at height h, normal up or down."""
        c = [(x0, -z1, h), (x1, -z1, h), (x1, -z0, h), (x0, -z0, h)]
        if not up:
            c = c[::-1]
        self.mb._add([Vector(v) for v in c], [(0, 1, 2, 3)], mat)
        return self

    def quad_v(self, x0, x1, z, h0, h1, mat: str, toward_camera: bool = True) -> Mesh:
        """Vertical quad in the plane z = const, normal toward +z (camera) or -z."""
        c = [(x0, -z, h0), (x1, -z, h0), (x1, -z, h1), (x0, -z, h1)]
        if not toward_camera:
            c = c[::-1]
        self.mb._add([Vector(v) for v in c], [(0, 1, 2, 3)], mat)
        return self

    def quad(self, corners_xzh, mat: str) -> Mesh:
        self.mb._add([Vector(P(*c)) for c in corners_xzh], [(0, 1, 2, 3)], mat)
        return self

    def poly(self, points_xzh, mat: str) -> Mesh:
        """One flat n-gon through (x, z, h) points."""
        self.mb._add([Vector(P(*c)) for c in points_xzh], [tuple(range(len(points_xzh)))], mat)
        return self

    # -- output -------------------------------------------------------------

    def build(
        self,
        name: str,
        coll: str = "Architecture",
        *,
        bevel: float = 0.008,
        segments: int = 2,
        camera: bool = True,
        keep_normals: bool = False,
        shadow: bool = True,
        **props,
    ) -> bpy.types.Object | None:
        with kit.into(collection(coll)):
            if keep_normals:
                obj = self._build_as_wound(name, bevel, segments, **props)
            else:
                obj = self.mb.build(name, bevel_width=bevel, segments=segments, **props)
        if obj is None:
            return None
        obj.visible_camera = camera
        obj.visible_shadow = shadow
        return obj

    def _build_as_wound(self, name, bevel, segments, **props):
        """Like MeshBuilder.build but keeps the face winding as authored: a lone
        emitter quad has no inside, so recalculated normals flip at random."""
        from lib import materials

        mb = self.mb
        if mb.is_empty():
            mb.bm.free()
            return None
        mesh = bpy.data.meshes.new(name)
        mb.bm.to_mesh(mesh)
        mb.bm.free()
        for mat_name in mb.materials:
            mesh.materials.append(materials.get(mat_name))
        obj = bpy.data.objects.new(name, mesh)
        kit.link(obj)
        if bevel > 0:
            kit.bevel(obj, bevel, segments)
        kit.tag(obj, **props)
        return obj


def _area(pts) -> float:
    return 0.5 * sum(
        x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1], strict=True)
    )


def emitter_h(name, x0, x1, z0, z1, h, mat, coll="Ceiling", down=True, camera=False):
    """Flat emitter quad facing down (ceiling diffuser) or up."""
    m = Mesh()
    m.quad_h(x0, x1, z0, z1, h, mat, up=not down)
    obj = m.build(name, coll, bevel=0.0, camera=camera, keep_normals=True)
    obj.visible_shadow = False
    return obj


def area_light(name, x, z, h, size_x, size_z, power_w, kelvin=6000.0, spread_deg=150.0):
    """Downward area light (scene.add_area_light) in deck coordinates; never
    seen by the camera or in reflections (the fixture mesh is what you see)."""
    obj = scene.add_area_light(
        name, P(x, z, h), (size_x, size_z), power_w, kelvin, spread_deg=spread_deg
    )
    obj.visible_camera = False
    obj.visible_glossy = False
    return obj


def point_light(name, x, z, h, power_w, kelvin=3200.0, radius=0.05, color=None):
    data = bpy.data.lights.new(name, "POINT")
    data.energy = power_w
    data.shadow_soft_size = radius
    if color is None:
        data.use_temperature = True
        data.temperature = kelvin
    else:
        data.color = color
    obj = bpy.data.objects.new(name, data)
    obj.location = Vector(P(x, z, h))
    obj.visible_camera = False
    obj.visible_glossy = False
    collection("Lights").objects.link(obj)
    return obj


def spot_light(
    name,
    x,
    z,
    h,
    power_w,
    kelvin=3000.0,
    angle_deg=70.0,
    blend=0.6,
    radius=0.04,
    aim=(0.0, 0.0, -1.0),
):
    data = bpy.data.lights.new(name, "SPOT")
    data.energy = power_w
    data.spot_size = math.radians(angle_deg)
    data.spot_blend = blend
    data.shadow_soft_size = radius
    data.use_temperature = True
    data.temperature = kelvin
    obj = bpy.data.objects.new(name, data)
    obj.location = Vector(P(x, z, h))
    d = Vector(P(*aim)).normalized()
    obj.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    obj.visible_camera = False
    obj.visible_glossy = False
    collection("Lights").objects.link(obj)
    return obj


# ---------------------------------------------------------------- sockets


def sock(kind: str, sid: str, x, z, h=0.0, yaw_deg=0.0, **props):
    """SOCKET_<kind>_<sid>; yaw 0 faces the camera (+z), 180 faces the far wall."""
    return scene.add_socket(kind, sid, P(x, z, h), yaw_deg, **props)


def screen(sid: str, cx, cz, ch, w, hgt, tilt_deg=0.0, **props):
    """Screen socket facing the camera, centred at (cx, cz, ch)."""
    return scene.add_screen(sid, P(cx, cz, ch), w, hgt, yaw_deg=0.0, tilt_deg=tilt_deg, **props)


def ucx(oid: str, x0, x1, z0, z1, h0, h1):
    return scene.add_ucx_box(oid, P(x0, z1, h0), P(x1, z0, h1))


def room(rid: str, name: str, rect_or_poly, main=False, **props):
    """ROOM_<id> from a rect (x0, x1, z0, z1) or a polygon of (x, z)."""
    if len(rect_or_poly) == 4 and not isinstance(rect_or_poly[0], (tuple, list)):
        x0, x1, z0, z1 = rect_or_poly
        poly = [(x0, z0), (x0, z1), (x1, z1), (x1, z0)]
    else:
        poly = list(rect_or_poly)
    bl = [(x, -z) for x, z in poly]
    if _area(bl) < 0:
        bl = bl[::-1]
    obj = scene.add_room(rid, name, bl, main=main, **props)
    obj["room"] = rid
    return obj


def tag(obj, **props):
    if obj is None:
        return None
    return scene.tag(obj, **props)


def matrix_identity() -> Matrix:
    return Matrix.Identity(4)
