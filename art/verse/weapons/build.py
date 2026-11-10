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


def _segment(
    b: Builder,
    start: Vec3,
    tilt: float,
    length: float,
    width: float,
    depth: float,
    slot: str,
    bone: str,
    chamfer: float,
) -> Vec3:
    """A box hanging down from `start`, tilted `tilt` degrees (negative leans its foot forward).

    Returns the centre of its bottom face, where the next segment starts.
    """
    a = math.radians(tilt)
    down = (-math.sin(a), 0.0, -math.cos(a))
    centre = (start[0] + down[0] * length / 2, start[1], start[2] + down[2] * length / 2)
    b.box((depth, width, length), centre, slot, bone=bone, rot=(0.0, tilt, 0.0), chamfer=chamfer)
    return (start[0] + down[0] * length, start[1], start[2] + down[2] * length)


#: The lit dot of the Graveline's reflex sight; `specs.GRAVELINE` puts `SOCKET_Sight` here.
GRAVELINE_DOT: Vec3 = (0.1255, 0.0, 0.1475)


def _reflex_sight(b: Builder, dot: Vec3) -> None:
    """A low open reflex sight on a short riser: thin frame, wide glass, small amber dot.

    The window is 34 x 24 mm inside 3 mm posts, so aiming through it hides almost nothing.
    """
    x, _, z = dot
    inner_y, inner_z, post, depth = 0.034, 0.024, 0.003, 0.014
    frame_x = x - 0.0035
    base_top = z - inner_z / 2
    # Rail clamp with its knob, riser, housing base and the emitter at its rear.
    b.box((0.052, 0.030, 0.008), (x - 0.012, 0.0, 0.0995), S, chamfer=0.002)
    b.prism(
        0.0045, 0.008, (x - 0.012, 0.019, 0.0995), sides=6, slot=S, rot=(0, 0, 90), chamfer=0.001
    )
    riser_top = base_top - 0.008
    riser = riser_top - 0.1035
    # Open riser: two angled legs and a rear brace, so the rail shows through the tunnel.
    for side in (1.0, -1.0):
        b.box(
            (0.042, 0.005, riser),
            (x - 0.012, side * 0.0105, 0.1035 + riser / 2),
            S,
            chamfer=0.0018,
            taper=(0.8, 0.0),
        )
    b.box((0.006, 0.026, riser * 0.6), (x - 0.030, 0.0, 0.1035 + riser * 0.3), S, chamfer=0.0015)
    b.box((0.040, inner_y + 2 * post, 0.008), (x - 0.010, 0.0, base_top - 0.004), S, chamfer=0.0025)
    b.box((0.010, 0.012, 0.004), (x - 0.025, 0.0, base_top + 0.0005), P, chamfer=0.0015)
    # Window frame: two posts with gussets at their feet and a hood reaching a little forward.
    for side in (1.0, -1.0):
        y = side * (inner_y / 2 + post / 2)
        b.box((depth, post, inner_z + post), (frame_x, y, z + post / 2), S, chamfer=0.001)
        b.box(
            (depth, 0.005, 0.007),
            (frame_x, side * (inner_y / 2 + 0.0005), base_top + 0.0025),
            S,
            chamfer=0.0015,
            taper=(0.6, -0.002),
        )
    b.box(
        (depth + 0.006, inner_y + 2 * post, post),
        (frame_x + 0.003, 0.0, z + inner_z / 2 + post / 2),
        S,
        chamfer=0.001,
    )
    for dx in (-0.008, 0.004):  # brightness buttons on the right of the housing
        b.box(
            (0.007, 0.004, 0.005),
            (x - 0.010 + dx, -(inner_y / 2 + post + 0.0015), base_top - 0.004),
            P,
            chamfer=0.001,
        )
    glass_x = frame_x + depth / 2 - 0.001
    b.box((0.0015, inner_y, inner_z), (glass_x, 0.0, z), specs.SLOT_OPTIC, chamfer=0.0)
    b.box((0.001, 0.0018, 0.0018), dot, specs.SLOT_RETICLE, chamfer=0.0)


# --------------------------------------------------------------------------
# Weapons
# --------------------------------------------------------------------------


def build_graveline(b: Builder) -> None:
    """Assault rifle: split upper over a lower with a flared magwell, vented handguard, top rail,
    slotted muzzle device, skeleton stock on a tube and a low reflex sight."""
    # -- upper receiver: two blocks with a panel break over a core that darkens the seam --
    b.box((0.30, 0.038, 0.038), (0.10, 0.0, 0.064), P, chamfer=0.004)
    b.box((0.145, 0.042, 0.044), (0.0175, 0.0, 0.064), S, chamfer=0.004)
    b.box((0.161, 0.042, 0.044), (0.1745, 0.0, 0.064), S, chamfer=0.004)
    for y in (0.0225, -0.0225):  # raised side panels on the rear block
        b.box((0.09, 0.003, 0.022), (0.005, y, 0.062), S, chamfer=0.001)
    b.box((0.06, 0.003, 0.020), (0.205, 0.0225, 0.062), S, chamfer=0.001)
    # Ejection port on the right: a dark recess in a raised frame.
    b.box((0.060, 0.002, 0.018), (0.152, -0.0215, 0.056), P, chamfer=0.0)
    for dz in (0.0105, -0.0105):
        b.box((0.066, 0.003, 0.003), (0.152, -0.0225, 0.056 + dz), S, chamfer=0.001)
    for dx in (0.0315, -0.0315):
        b.box((0.003, 0.003, 0.024), (0.152 + dx, -0.0225, 0.056), S, chamfer=0.001)
    # End plate and the T charging handle at the rear of the upper.
    b.box((0.012, 0.046, 0.050), (-0.061, 0.0, 0.060), S, chamfer=0.003)
    b.box((0.016, 0.012, 0.008), (-0.072, 0.0, 0.082), S, chamfer=0.002)
    b.box((0.010, 0.048, 0.008), (-0.082, 0.0, 0.082), S, chamfer=0.003)
    # Side charging knob on the bolt, so it cycles with every shot.
    b.box((0.022, 0.010, 0.010), (0.13, -0.027, 0.070), S, bone="Bolt", chamfer=0.002)
    b.prism(
        0.006,
        0.010,
        (0.13, -0.036, 0.070),
        sides=8,
        slot=S,
        bone="Bolt",
        rot=(0, 0, 90),
        chamfer=0.0015,
    )

    # -- top rail from the end plate to the front of the handguard ------------------------
    b.box((0.585, 0.020, 0.006), (0.2225, 0.0, 0.089), S, chamfer=0.0015)
    for i in range(51):
        b.box((0.006, 0.026, 0.0045), (-0.05 + 0.011 * i, 0.0, 0.0935), S, chamfer=0.0012)

    # -- lower receiver, flared magwell, controls -----------------------------------------
    b.box((0.25, 0.044, 0.040), (0.07, 0.0, 0.023), S, chamfer=0.005)
    b.box(
        (0.060, 0.048, 0.034),
        (0.088, 0.0, 0.002),
        S,
        rot=(0, -8, 0),
        chamfer=0.005,
        taper=(0.85, 0.0),
    )
    b.box((0.050, 0.052, 0.008), (0.091, 0.0, -0.014), S, rot=(0, -8, 0), chamfer=0.003)
    for px, pz in ((0.012, 0.028), (0.050, 0.030)):  # cross pins
        b.prism(0.0035, 0.047, (px, 0.0, pz), sides=8, slot=S, rot=(0, 0, 90), chamfer=0.0008)
    b.box((0.020, 0.003, 0.006), (0.004, 0.0235, 0.034), S, rot=(0, -20, 0), chamfer=0.001)
    b.box((0.012, 0.003, 0.022), (0.118, 0.0255, 0.012), S, chamfer=0.001)  # magazine release

    # -- handguard: bands and ribs around a dark core, so the vents are real openings ------
    hx0, hx1 = 0.255, 0.53
    hcx, hlen = (hx0 + hx1) / 2, hx1 - hx0
    b.box((hlen - 0.004, 0.040, 0.064), (hcx, 0.0, 0.047), P, chamfer=0.006)
    b.box((hlen, 0.050, 0.016), (hcx, 0.0, 0.078), P, chamfer=0.004)
    b.box((hlen, 0.050, 0.020), (hcx, 0.0, 0.017), P, chamfer=0.007)
    b.box((hlen - 0.04, 0.050, 0.007), (hcx, 0.0, 0.0485), P, chamfer=0.002)
    b.box((0.020, 0.052, 0.074), (hx0 + 0.010, 0.0, 0.046), P, chamfer=0.005)
    b.box((0.020, 0.052, 0.074), (hx1 - 0.010, 0.0, 0.046), P, chamfer=0.005)
    vents, rib = 6, 0.0134
    vent = (hlen - 0.04 - (vents - 1) * rib) / vents
    for i in range(1, vents):
        rx = hx0 + 0.02 + i * vent + (i - 0.5) * rib
        b.box((rib, 0.050, 0.044), (rx, 0.0, 0.048), P, chamfer=0.002)
    for sx in (0.30, 0.39, 0.48):  # screws through the top band
        b.prism(0.0028, 0.053, (sx, 0.0, 0.079), sides=6, slot=S, rot=(0, 0, 90), chamfer=0.0006)
    b.box((0.030, 0.034, 0.026), (0.503, 0.0, -0.004), P, chamfer=0.006, taper=(0.7, 0.004))
    b.prism(0.006, 0.006, (0.47, 0.027, 0.03), sides=8, slot=S, rot=(0, 0, 90), chamfer=0.001)

    # -- barrel, gas block, slotted muzzle device ----------------------------------------
    b.prism(0.0105, 0.17, (0.585, 0.0, 0.035), sides=16, slot=S, chamfer=0.001)
    b.box((0.024, 0.028, 0.034), (0.552, 0.0, 0.042), S, chamfer=0.004)
    b.prism(0.016, 0.012, (0.666, 0.0, 0.035), sides=8, slot=S, chamfer=0.002)
    b.prism(0.0125, 0.068, (0.705, 0.0, 0.035), sides=8, slot=P, chamfer=0.001)
    for rx in (0.684, 0.700, 0.716):
        b.prism(0.0175, 0.008, (rx, 0.0, 0.035), sides=8, slot=S, chamfer=0.0015)
    b.prism(0.0165, 0.014, (0.737, 0.0, 0.035), sides=8, slot=S, chamfer=0.003, radius2=0.0145)

    # -- pistol grip and trigger group ----------------------------------------------------
    tilt = 18.0
    rot = (0.0, tilt, 0.0)
    b.box((0.036, 0.030, 0.105), _tilted(-0.012, -0.050, tilt), G, rot=rot, chamfer=0.007)
    b.box((0.030, 0.032, 0.020), (-0.040, 0.0, 0.004), G, rot=(0, 30, 0), chamfer=0.006)
    for i in range(3):  # finger ridges on the front strap
        ridge = _tilted(-0.012, -0.028 - i * 0.025, tilt, 0.019)
        b.box((0.006, 0.026, 0.012), ridge, G, rot=rot, chamfer=0.002)
    panel = _tilted(-0.012, -0.055, tilt)
    for y in (0.0158, -0.0158):  # textured side panels
        b.box((0.022, 0.002, 0.062), (panel[0], y, panel[2]), P, rot=rot, chamfer=0.0006)
    b.box((0.044, 0.034, 0.009), _tilted(-0.012, -0.104, tilt), S, rot=rot, chamfer=0.003)
    b.box((0.072, 0.012, 0.007), (0.024, 0.0, -0.044), S, chamfer=0.0022)
    b.box((0.014, 0.014, 0.012), (-0.010, 0.0, -0.042), S, chamfer=0.003)  # guard foot on the grip
    b.box((0.009, 0.012, 0.044), (0.060, 0.0, -0.024), S, rot=(0, -20, 0), chamfer=0.0022)
    b.box(
        (0.006, 0.006, 0.026),
        (0.033, 0.0, -0.016),
        S,
        bone="Trigger",
        rot=(0, -12, 0),
        chamfer=0.0015,
    )

    # -- curved magazine on its bone ------------------------------------------------------
    top = (0.086, 0.0, -0.006)
    joint = _segment(b, top, -8.0, 0.075, 0.026, 0.042, P, "Magazine", 0.004)
    foot = _segment(b, joint, -18.0, 0.060, 0.026, 0.041, P, "Magazine", 0.004)
    b.box((0.054, 0.032, 0.012), foot, S, bone="Magazine", rot=(0, -18, 0), chamfer=0.003)
    lean = math.sin(math.radians(8.0))
    for i in range(4):  # ribs on the side faces
        cz = top[2] - 0.016 - i * 0.015
        cx = top[0] + lean * (top[2] - cz)
        for y in (0.0135, -0.0135):
            b.box(
                (0.030, 0.002, 0.004),
                (cx, y, cz),
                P,
                bone="Magazine",
                rot=(0, -8, 0),
                chamfer=0.0007,
            )

    # -- stock: tube, collar, cheek riser, lower strut, butt block with a rubber pad -------
    b.prism(0.015, 0.18, (-0.15, 0.0, 0.058), sides=8, slot=S, chamfer=0.002)
    b.box((0.024, 0.034, 0.050), (-0.135, 0.0, 0.050), P, chamfer=0.005)
    b.box((0.010, 0.006, 0.020), (-0.135, 0.0, 0.020), S, chamfer=0.0015)
    b.box((0.17, 0.036, 0.022), (-0.225, 0.0, 0.080), P, chamfer=0.007, taper=(0.92, -0.005))
    b.box((0.13, 0.024, 0.018), (-0.225, 0.0, 0.066), P, chamfer=0.004)  # cheek riser saddle
    b.box((0.17, 0.022, 0.016), (-0.215, 0.0, 0.010), P, rot=(0, -17, 0), chamfer=0.005)
    b.box((0.032, 0.040, 0.135), (-0.298, 0.0, 0.032), P, chamfer=0.008)
    b.box((0.012, 0.042, 0.142), (-0.319, 0.0, 0.032), G, chamfer=0.004)
    b.box((0.012, 0.006, 0.020), (-0.285, 0.023, -0.010), S, chamfer=0.0015)

    _reflex_sight(b, GRAVELINE_DOT)


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
