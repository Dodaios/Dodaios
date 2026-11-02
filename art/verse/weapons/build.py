"""Blender builders of the WP14 weapons, gadgets and weapon VFX meshes (bpy).

Every asset is built from code out of chamfered hard-surface primitives
(style bible "bevel everything", 45 degree chamfers). The geometry is our
own and copies no real firearm (design sheet: `art/verse/style-unreal.md`).

Each part names a material slot (`specs.SLOT_*`) and, for skeletal assets,
the bone that carries it rigidly (`Magazine`, `Bolt`/`Slide`, `Trigger`,
otherwise `Root`). Vertex colour R marks the middle of every chamfer (edge
wear of `M_Verse_Weapon`), G marks concave seams (grime).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field

import bmesh
import bpy
from mathutils import Euler, Matrix, Vector

from . import specs

Vec3 = tuple[float, float, float]


@dataclass
class Part:
    bm: bmesh.types.BMesh
    slot: str
    bone: str
    bevel_faces: set = field(default_factory=set)


class Builder:
    """Collects parts; `mesh()` returns one Blender mesh with slots, groups and colours."""

    def __init__(self, name: str):
        self.name = name
        self.parts: list[Part] = []

    # -- primitives ----------------------------------------------------

    def _finish(
        self, bm, slot: str, bone: str, center: Vec3, rot: Vec3, chamfer: float, segments: int = 2
    ) -> Part:
        bevel_faces: set = set()
        if chamfer > 0:
            result = bmesh.ops.bevel(
                bm,
                geom=list(bm.verts) + list(bm.edges),
                offset=chamfer,
                offset_type="OFFSET",
                segments=segments,
                profile=0.5,
                affect="EDGES",
                clamp_overlap=True,
            )
            bevel_faces = {f.index for f in result["faces"]}
            bm.faces.index_update()
            bevel_faces = {f for f in bm.faces if f in set(result["faces"])}
        matrix = (
            Matrix.Translation(Vector(center))
            @ Euler(tuple(math.radians(a) for a in rot), "XYZ").to_matrix().to_4x4()
        )
        bmesh.ops.transform(bm, matrix=matrix, verts=list(bm.verts))
        part = Part(bm, slot, bone, bevel_faces)
        self.parts.append(part)
        return part

    def box(
        self,
        size: Vec3,
        center: Vec3,
        slot: str = specs.SLOT_STEEL,
        bone: str = "Root",
        rot: Vec3 = (0.0, 0.0, 0.0),
        chamfer: float = 0.003,
        taper: tuple[float, float] | None = None,
    ) -> Part:
        """A chamfered box. `taper=(top_x_scale, top_x_shift)` narrows the top face along X."""
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=1.0)
        for v in bm.verts:
            v.co = Vector((v.co.x * size[0], v.co.y * size[1], v.co.z * size[2]))
            if taper and v.co.z > 0:
                v.co.x = v.co.x * taper[0] + taper[1]
        chamfer = min(chamfer, 0.45 * min(size))
        return self._finish(bm, slot, bone, center, rot, chamfer)

    def prism(
        self,
        radius: float,
        length: float,
        center: Vec3,
        sides: int = 6,
        slot: str = specs.SLOT_STEEL,
        bone: str = "Root",
        rot: Vec3 = (0.0, 0.0, 0.0),
        chamfer: float = 0.002,
        radius2: float | None = None,
    ) -> Part:
        """A chamfered prism along +X (`sides` 6 or 8 for the faceted look, 12+ for barrels)."""
        bm = bmesh.new()
        bmesh.ops.create_cone(
            bm,
            cap_ends=True,
            cap_tris=False,
            segments=sides,
            radius1=radius,
            radius2=radius if radius2 is None else radius2,
            depth=length,
            matrix=Matrix.Rotation(math.radians(90.0), 4, "Y")
            @ Matrix.Rotation(math.pi / sides, 4, "Z"),
        )
        chamfer = min(chamfer, 0.3 * radius, 0.3 * length)
        return self._finish(bm, slot, bone, center, rot, chamfer, segments=1)

    def profile(
        self,
        top: list[tuple[float, float]],
        bottom: list[tuple[float, float]],
        half_top: float,
        half_bottom: float,
        slot: str,
        bone: str = "Root",
    ) -> Part:
        """A closed solid between two XZ polylines with their own half thickness in Y.

        Used for blades: the spine polyline is thick, the edge polyline thin.
        """
        if len(top) != len(bottom):
            raise ValueError("profile polylines need the same point count")
        bm = bmesh.new()
        n = len(top)
        tl = [bm.verts.new((x, half_top, z)) for x, z in top]
        tr = [bm.verts.new((x, -half_top, z)) for x, z in top]
        bl = [bm.verts.new((x, half_bottom, z)) for x, z in bottom]
        br = [bm.verts.new((x, -half_bottom, z)) for x, z in bottom]
        for i in range(n - 1):
            bm.faces.new((tl[i], bl[i], bl[i + 1], tl[i + 1]))
            bm.faces.new((tr[i], tr[i + 1], br[i + 1], br[i]))
            bm.faces.new((tl[i], tl[i + 1], tr[i + 1], tr[i]))
            bm.faces.new((bl[i], br[i], br[i + 1], bl[i + 1]))
        bm.faces.new((tl[0], tr[0], br[0], bl[0]))
        bm.faces.new((tl[-1], bl[-1], br[-1], tr[-1]))
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        part = Part(bm, slot, bone, set())
        part.edge_verts = {v for v in bl + br}
        self.parts.append(part)
        return part

    def tiles(
        self,
        count: tuple[int, int],
        tile: Vec3,
        gap: float,
        center: Vec3,
        slot: str,
        chamfer: float = 0.004,
    ) -> None:
        """A grid of chamfered tiles in the YZ plane (energy field panel)."""
        ny, nz = count
        w = ny * tile[1] + (ny - 1) * gap
        h = nz * tile[2] + (nz - 1) * gap
        for iy in range(ny):
            for iz in range(nz):
                y = center[1] - w / 2 + tile[1] / 2 + iy * (tile[1] + gap)
                z = center[2] - h / 2 + tile[2] / 2 + iz * (tile[2] + gap)
                self.box(tile, (center[0], y, z), slot=slot, chamfer=chamfer)

    # -- assembly ------------------------------------------------------

    def mesh(self, bone_order: list[str] | None = None) -> tuple[bpy.types.Mesh, list[str]]:
        """Merge the parts; return the mesh and its vertex group names (bone order)."""
        bones = list(bone_order or [])
        for part in self.parts:
            if part.bone not in bones:
                bones.append(part.bone)
        slots: list[str] = []
        for part in self.parts:
            if part.slot not in slots:
                slots.append(part.slot)
        out = bmesh.new()
        deform = out.verts.layers.deform.verify()
        colour = out.verts.layers.float_color.new("Col")
        for part in self.parts:
            src = part.bm
            convex_mid = _wear_verts(src, part)
            concave = _seam_verts(src)
            vmap = {}
            group = bones.index(part.bone)
            for v in src.verts:
                nv = out.verts.new(v.co)
                nv[deform][group] = 1.0
                nv[colour] = (
                    1.0 if v in convex_mid else 0.0,
                    1.0 if v in concave else 0.0,
                    0.0,
                    1.0,
                )
                vmap[v] = nv
            index = slots.index(part.slot)
            for f in src.faces:
                nf = out.faces.new([vmap[v] for v in f.verts])
                nf.material_index = index
                nf.smooth = False
            src.free()
        mesh = bpy.data.meshes.new(self.name)
        out.to_mesh(mesh)
        out.free()
        for slot in slots:
            material = bpy.data.materials.get(slot) or bpy.data.materials.new(slot)
            mesh.materials.append(material)
        if mesh.color_attributes:
            mesh.color_attributes.active_color = mesh.color_attributes[0]
        mesh.validate()
        return mesh, bones


def _wear_verts(bm, part: Part) -> set:
    """Vertices in the middle of a chamfer (not on any flat face): edge wear R = 1."""
    explicit = getattr(part, "edge_verts", None)
    if explicit is not None:
        return set(explicit)
    if not part.bevel_faces:
        return set()
    flat = [f for f in bm.faces if f not in part.bevel_faces]
    on_flat = {v for f in flat for v in f.verts}
    return {v for v in bm.verts if v not in on_flat}


def _seam_verts(bm) -> set:
    """Vertices on concave edges (grime G = 1)."""
    out = set()
    for edge in bm.edges:
        if len(edge.link_faces) == 2 and not edge.is_convex and edge.calc_face_angle(0.0) > 0.3:
            out.update(edge.verts)
    return out


# --------------------------------------------------------------------------
# Shared firearm parts
# --------------------------------------------------------------------------

S, P, G = specs.SLOT_STEEL, specs.SLOT_POLYMER, specs.SLOT_GRIP


def _tilted(x: float, z: float, tilt: float, ox: float = 0.0) -> Vec3:
    """Point at depth `z` below the pivot `(x, 0)` on an axis tilted `tilt` degrees back."""
    a = math.radians(tilt)
    return (x + ox * math.cos(a) + z * math.sin(a), 0.0, z * math.cos(a) - ox * math.sin(a))


def _grip(b: Builder, x: float = -0.01, height: float = 0.11, tilt: float = 15.0) -> None:
    rot = (0.0, tilt, 0.0)
    b.box((0.034, 0.030, height), _tilted(x, -height / 2 + 0.005, tilt), G, rot=rot, chamfer=0.006)
    for i in range(3):  # finger steps on the front strap
        b.box((0.006, 0.026, 0.012), _tilted(x, -0.025 - i * 0.025, tilt, 0.018), G, rot=rot)
    b.box((0.04, 0.034, 0.008), _tilted(x, -height + 0.004, tilt), S, rot=rot)


def _trigger_group(b: Builder, x: float = 0.035) -> None:
    b.box((0.08, 0.009, 0.006), (x, 0.0, -0.046), S, chamfer=0.002)
    b.box((0.007, 0.009, 0.044), (x + 0.038, 0.0, -0.026), S, rot=(0, -25, 0), chamfer=0.002)
    b.box(
        (0.006, 0.006, 0.026), (x, 0.0, -0.016), S, bone="Trigger", rot=(0, -12, 0), chamfer=0.0015
    )


def _magazine(
    b: Builder,
    x: float,
    length: float,
    width: float = 0.026,
    depth: float = 0.04,
    tilt: float = -8.0,
) -> None:
    rot = (0.0, tilt, 0.0)
    body = _tilted(x, -length / 2 + 0.005, tilt)
    b.box((depth, width, length), body, P, bone="Magazine", rot=rot, chamfer=0.004)
    base = _tilted(x, -length + 0.002, tilt)
    plate = (depth + 0.012, width + 0.006, 0.012)
    b.box(plate, base, S, bone="Magazine", rot=rot, chamfer=0.003)
    for i in range(3):  # ribs on the front face
        rib = _tilted(x, -0.03 - i * 0.025, tilt, depth / 2)
        b.box((0.004, width + 0.003, 0.012), rib, P, bone="Magazine", rot=rot, chamfer=0.001)


def _reticle_sight(
    b: Builder, x: float, z: float, length: float = 0.10, inner: float = 0.024
) -> None:
    """An open box sight: four plates around a glass front lens and an amber reticle dot."""
    wall = 0.006
    half = inner / 2 + wall / 2
    b.box((length, inner + 2 * wall, wall), (x, 0.0, z + half), S, chamfer=0.003)
    b.box((length, inner + 2 * wall, wall), (x, 0.0, z - half), S, chamfer=0.003)
    b.box((length, wall, inner), (x, half, z), S, chamfer=0.002)
    b.box((length, wall, inner), (x, -half, z), S, chamfer=0.002)
    b.box((0.003, inner, inner), (x + length / 2 - 0.006, 0.0, z), specs.SLOT_OPTIC, chamfer=0.0)
    b.box((0.002, 0.003, 0.003), (x + length / 2 - 0.009, 0.0, z), specs.SLOT_RETICLE, chamfer=0.0)
    b.box((0.08, 0.030, 0.014), (x, 0.0, z - half - 0.01), S, chamfer=0.003)  # mount


# --------------------------------------------------------------------------
# Weapons
# --------------------------------------------------------------------------


def build_graveline(b: Builder) -> None:
    b.box((0.30, 0.048, 0.05), (0.07, 0.0, 0.025), S, chamfer=0.005)
    b.box((0.34, 0.044, 0.04), (0.09, 0.0, 0.07), S, chamfer=0.009)
    b.box((0.28, 0.018, 0.012), (0.10, 0.0, 0.094), P, chamfer=0.004)
    b.prism(0.034, 0.26, (0.37, 0.0, 0.045), sides=6, slot=P, chamfer=0.004)
    for x in (0.30, 0.36, 0.42):
        for y in (0.030, -0.030):
            b.box((0.04, 0.006, 0.012), (x, y, 0.050), S, chamfer=0.002)
    b.prism(0.011, 0.20, (0.58, 0.0, 0.035), sides=12, slot=S, chamfer=0.001)
    b.prism(0.019, 0.065, (0.70, 0.0, 0.035), sides=6, slot=S, chamfer=0.003)
    for x in (0.69, 0.71):
        b.box((0.008, 0.042, 0.006), (x, 0.0, 0.035), P, chamfer=0.001)
    _grip(b)
    _trigger_group(b)
    _magazine(b, 0.085, 0.13)
    # stock: two struts closing on a rubber block
    b.box((0.05, 0.040, 0.07), (-0.07, 0.0, 0.04), S, chamfer=0.006)
    b.box((0.24, 0.020, 0.020), (-0.17, 0.0, 0.065), P, chamfer=0.005)
    b.box((0.26, 0.020, 0.020), (-0.16, 0.0, 0.002), P, rot=(0, -9, 0), chamfer=0.005)
    b.box((0.035, 0.036, 0.13), (-0.30, 0.0, 0.03), G, chamfer=0.008)
    _reticle_sight(b, 0.12, 0.115)
    b.box((0.03, 0.012, 0.012), (0.14, -0.03, 0.058), S, bone="Bolt", chamfer=0.003)
    b.box((0.05, 0.002, 0.018), (0.15, -0.0245, 0.045), P, chamfer=0.0)


def build_tallow(b: Builder) -> None:
    b.box((0.13, 0.026, 0.032), (0.015, 0.0, 0.055), S, bone="Slide", chamfer=0.004)
    b.box((0.07, 0.024, 0.026), (0.115, 0.0, 0.052), S, bone="Slide", chamfer=0.006)
    for z in (0.048, 0.055, 0.062):
        b.box((0.035, 0.0275, 0.002), (-0.035, 0.0, z), P, bone="Slide", chamfer=0.0)
    b.box((0.012, 0.002, 0.014), (0.06, -0.0125, 0.062), P, bone="Slide", chamfer=0.0)
    b.box((0.15, 0.024, 0.022), (0.05, 0.0, 0.028), P, chamfer=0.004)
    b.prism(0.006, 0.012, (0.152, 0.0, 0.052), sides=12, slot=S, bone="Slide", chamfer=0.0)
    b.box((0.032, 0.028, 0.10), (-0.015, 0.0, -0.035), G, rot=(0, 18, 0), chamfer=0.006)
    b.box((0.012, 0.030, 0.05), (-0.04, 0.0, -0.005), G, rot=(0, 18, 0), chamfer=0.004)
    b.box(
        (0.026, 0.020, 0.08),
        (-0.015, 0.0, -0.04),
        P,
        bone="Magazine",
        rot=(0, 18, 0),
        chamfer=0.002,
    )
    b.box(
        (0.036, 0.030, 0.010),
        (-0.03, 0.0, -0.088),
        S,
        bone="Magazine",
        rot=(0, 18, 0),
        chamfer=0.003,
    )
    b.box((0.055, 0.006, 0.005), (0.04, 0.0, -0.012), S, chamfer=0.0015)
    b.box((0.005, 0.006, 0.03), (0.068, 0.0, 0.003), S, rot=(0, -30, 0), chamfer=0.0015)
    b.box(
        (0.005, 0.005, 0.02), (0.03, 0.0, 0.002), S, bone="Trigger", rot=(0, -10, 0), chamfer=0.001
    )
    b.box((0.008, 0.022, 0.008), (-0.035, 0.0, 0.075), S, bone="Slide", chamfer=0.002)
    b.box((0.006, 0.004, 0.007), (0.135, 0.0, 0.0685), S, bone="Slide", chamfer=0.001)


def build_hookbill(b: Builder) -> None:
    for i, x in enumerate((-0.045, -0.018, 0.009, 0.036)):
        b.box((0.025, 0.022 + 0.002 * (i % 2), 0.028), (x, 0.0, 0.0), G, chamfer=0.005)
    b.prism(0.016, 0.012, (-0.066, 0.0, 0.0), sides=6, slot=S, chamfer=0.003)
    b.box((0.006, 0.026, 0.05), (0.058, 0.0, 0.0), S, chamfer=0.002)
    top = [(0.061, 0.013), (0.15, 0.013), (0.20, 0.013), (0.235, 0.005), (0.255, -0.004)]
    bottom = [(0.061, -0.016), (0.15, -0.0155), (0.20, -0.014), (0.235, -0.010), (0.255, -0.005)]
    b.profile(top, bottom, 0.00225, 0.0004, S)


def build_skitter(b: Builder) -> None:
    b.box((0.26, 0.046, 0.075), (0.07, 0.0, 0.035), S, chamfer=0.007)
    b.box((0.20, 0.030, 0.012), (0.07, 0.0, 0.077), P, chamfer=0.003)
    b.prism(0.020, 0.10, (0.25, 0.0, 0.03), sides=8, slot=P, chamfer=0.003)
    b.prism(0.008, 0.05, (0.32, 0.0, 0.03), sides=12, slot=S, chamfer=0.001)
    b.box((0.04, 0.030, 0.030), (0.375, 0.0, 0.03), S, chamfer=0.005)
    _grip(b)
    _trigger_group(b)
    _magazine(b, 0.11, 0.16, width=0.024, depth=0.032, tilt=0.0)
    b.box((0.14, 0.012, 0.030), (-0.12, 0.0, 0.04), S, chamfer=0.004)
    b.box((0.012, 0.030, 0.07), (-0.19, 0.0, 0.035), G, chamfer=0.004)
    b.box((0.015, 0.030, 0.012), (0.0, 0.0, 0.082), S, chamfer=0.002)
    for y in (0.008, -0.008):
        b.box((0.015, 0.006, 0.016), (0.0, y, 0.095), S, chamfer=0.0015)
    b.box((0.012, 0.012, 0.016), (0.17, 0.0, 0.084), S, chamfer=0.002)
    b.box((0.006, 0.004, 0.02), (0.17, 0.0, 0.095), S, chamfer=0.001)
    b.box((0.06, 0.002, 0.008), (0.09, 0.0235, 0.05), P, chamfer=0.0)
    b.box((0.012, 0.012, 0.010), (0.09, 0.03, 0.05), S, bone="Bolt", chamfer=0.002)
    b.box((0.04, 0.002, 0.016), (0.12, -0.0235, 0.045), P, chamfer=0.0)


def build_longsight(b: Builder) -> None:
    b.box((0.32, 0.050, 0.055), (0.07, 0.0, 0.025), S, chamfer=0.006)
    b.box((0.36, 0.046, 0.045), (0.10, 0.0, 0.07), S, chamfer=0.009)
    b.prism(0.034, 0.36, (0.43, 0.0, 0.045), sides=8, slot=P, chamfer=0.004)
    for x in (0.33, 0.40, 0.47, 0.54):
        b.box((0.045, 0.072, 0.008), (x, 0.0, 0.045), S, chamfer=0.002)
    b.prism(0.012, 0.28, (0.72, 0.0, 0.04), sides=12, slot=S, chamfer=0.001)
    b.box((0.06, 0.034, 0.034), (0.89, 0.0, 0.04), S, chamfer=0.008)
    # tube sight on two stand-offs
    b.prism(0.022, 0.30, (0.11, 0.0, 0.15), sides=8, slot=S, chamfer=0.003)
    b.prism(0.028, 0.07, (0.28, 0.0, 0.15), sides=8, slot=S, chamfer=0.004)
    b.prism(0.025, 0.05, (-0.055, 0.0, 0.15), sides=8, slot=S, chamfer=0.004)
    b.prism(0.024, 0.003, (0.3165, 0.0, 0.15), sides=16, slot=specs.SLOT_OPTIC, chamfer=0.0)
    b.prism(0.021, 0.003, (-0.0815, 0.0, 0.15), sides=16, slot=specs.SLOT_OPTIC, chamfer=0.0)
    b.box((0.002, 0.003, 0.003), (-0.084, 0.0, 0.15), specs.SLOT_RETICLE, chamfer=0.0)
    for x in (0.05, 0.17):
        b.box((0.02, 0.020, 0.04), (x, 0.0, 0.11), S, chamfer=0.003)
    _grip(b)
    _trigger_group(b)
    _magazine(b, 0.10, 0.09, width=0.028, depth=0.045, tilt=0.0)
    b.box((0.26, 0.040, 0.09), (-0.18, 0.0, 0.03), P, chamfer=0.010)
    b.box((0.14, 0.030, 0.025), (-0.17, 0.0, 0.085), P, chamfer=0.006)
    b.box((0.025, 0.042, 0.12), (-0.32, 0.0, 0.02), G, chamfer=0.006)
    b.box((0.04, 0.012, 0.012), (0.16, -0.032, 0.06), S, bone="Bolt", chamfer=0.003)
    b.box((0.05, 0.002, 0.018), (0.17, -0.0255, 0.05), P, chamfer=0.0)


def build_bulwark(b: Builder) -> None:
    b.box((0.18, 0.90, 0.08), (0.0, 0.0, 0.04), S, chamfer=0.02)
    b.box((0.05, 0.86, 0.04), (0.0, 0.0, 0.10), P, chamfer=0.01)
    for y in (-0.36, 0.36):
        b.box((0.30, 0.08, 0.02), (0.0, y, 0.01), G, chamfer=0.006)
    for y in (-0.42, -0.14, 0.14, 0.42):
        b.box((0.03, 0.02, 0.03), (0.0, y, 0.135), S, chamfer=0.006)
    b.box((0.01, 0.03, 0.015), (-0.091, -0.30, 0.06), specs.SLOT_INDICATOR, chamfer=0.0)


def build_bulwark_field(b: Builder) -> None:
    b.tiles((6, 7), (0.01, 0.142, 0.150), 0.006, (0.0, 0.0, 0.70), specs.SLOT_FIELD)


def build_breach_charge(b: Builder) -> None:
    b.box((0.03, 0.30, 0.20), (0.015, 0.0, 0.0), P, chamfer=0.006)
    for y in (-0.155, 0.155):
        b.box((0.036, 0.012, 0.21), (0.018, y, 0.0), S, chamfer=0.003)
    for z in (-0.105, 0.105):
        b.box((0.036, 0.32, 0.012), (0.018, 0.0, z), S, chamfer=0.003)
    for y in (-0.13, 0.13):
        for z in (-0.08, 0.08):
            b.box((0.006, 0.04, 0.04), (0.003, y, z), G, chamfer=0.002)
    b.box((0.03, 0.08, 0.06), (0.045, 0.0, 0.0), S, chamfer=0.006)
    b.box((0.004, 0.012, 0.012), (0.062, 0.0, 0.015), specs.SLOT_INDICATOR, chamfer=0.0)


BUILDERS: dict[str, Callable[[Builder], None]] = {
    "SK_Weapon_Graveline": build_graveline,
    "SK_Weapon_Tallow": build_tallow,
    "SK_Weapon_Hookbill": build_hookbill,
    "SK_Weapon_Skitter": build_skitter,
    "SK_Weapon_Longsight": build_longsight,
    "SM_Weapon_Bulwark": build_bulwark,
    "SM_Weapon_BulwarkField": build_bulwark_field,
    "SM_Weapon_BreachCharge": build_breach_charge,
}

#: Authored collision boxes of the static gadgets: (size, center), metres.
#: Empty: the gadgets use one auto box (record `auto_box`), added on import.
GADGET_COLLISION: dict[str, tuple[tuple[Vec3, Vec3], ...]] = {
    "SM_Weapon_Bulwark": (),
    "SM_Weapon_BulwarkField": (),
    "SM_Weapon_BreachCharge": (),
}


# --------------------------------------------------------------------------
# VFX meshes
# --------------------------------------------------------------------------


def build_vfx_bolt(b: Builder) -> None:
    """A tapered emissive rod, head at +X 0, tail at -0.6 m."""
    b.prism(0.008, 0.52, (-0.30, 0.0, 0.0), sides=8, slot="M_Weapon_Vfx_BoltOwn", chamfer=0.0)
    b.prism(
        0.008,
        0.04,
        (-0.02, 0.0, 0.0),
        sides=8,
        slot="M_Weapon_Vfx_BoltOwn",
        chamfer=0.0,
        radius2=0.001,
    )
    b.prism(
        0.001,
        0.04,
        (-0.58, 0.0, 0.0),
        sides=8,
        slot="M_Weapon_Vfx_BoltOwn",
        chamfer=0.0,
        radius2=0.008,
    )


def _card(b: Builder, slot: str, points: list[tuple[float, float]], plane: str) -> None:
    """A flat polygon card (two-sided material) in the XY or XZ plane."""
    bm = bmesh.new()
    verts = []
    for u, v in points:
        co = (u, v, 0.0) if plane == "XY" else (u, 0.0, v)
        verts.append(bm.verts.new(co))
    centre = bm.verts.new((sum(p[0] for p in points) / len(points), 0.0, 0.0))
    for i in range(len(verts)):
        bm.faces.new((centre, verts[i], verts[(i + 1) % len(verts)]))
    part = Part(bm, slot, "Root", set())
    part.edge_verts = {centre}  # R = 1 at the hot centre, fades to the tips
    b.parts.append(part)


def build_vfx_muzzle(b: Builder) -> None:
    star = []
    for i in range(10):
        angle = 2 * math.pi * i / 10
        r = 0.06 if i % 2 == 0 else 0.022
        star.append((0.05 + 0.6 * r * math.cos(angle) + 0.05, r * math.sin(angle)))
    for plane in ("XY", "XZ"):
        _card(b, "M_Weapon_Vfx_MuzzleOwn", star, plane)
    b.prism(
        0.02,
        0.06,
        (0.03, 0.0, 0.0),
        sides=8,
        slot="M_Weapon_Vfx_MuzzleOwn",
        chamfer=0.0,
        radius2=0.004,
    )


def build_vfx_sparks(b: Builder) -> None:
    """Twelve thin streaks in a 50 degree cone around +X, fixed seed (golden angle)."""
    golden = math.pi * (3.0 - math.sqrt(5.0))
    for i in range(12):
        t = (i + 0.5) / 12
        polar = math.radians(50.0) * math.sqrt(t)
        azimuth = i * golden
        length = 0.08 + 0.12 * ((i * 7) % 12) / 11
        direction = Vector(
            (
                math.cos(polar),
                math.sin(polar) * math.cos(azimuth),
                math.sin(polar) * math.sin(azimuth),
            )
        )
        b.prism(
            0.0025,
            length,
            tuple(direction * (length / 2 + 0.01)),
            sides=4,
            slot="M_Weapon_Vfx_Sparks",
            chamfer=0.0,
            radius2=0.0006,
            rot=_rot_to(direction),
        )


def _rot_to(direction: Vector) -> Vec3:
    """Euler XYZ degrees that turn +X onto `direction`."""
    quat = Vector((1.0, 0.0, 0.0)).rotation_difference(direction)
    euler = quat.to_euler("XYZ")
    return tuple(math.degrees(a) for a in euler)


VFX_BUILDERS: dict[str, Callable[[Builder], None]] = {
    "SM_Vfx_Bolt": build_vfx_bolt,
    "SM_Vfx_MuzzleFlash": build_vfx_muzzle,
    "SM_Vfx_ImpactSparks": build_vfx_sparks,
}
