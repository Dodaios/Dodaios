"""Modular kit registry, placement and geometry helpers for the Verse decks.

Runs inside Blender (bpy). Every deck builder and every kit module uses this
file; it is the one place that knows how a piece becomes objects in a scene.

Conventions (see BRIEF.md sections 4, 5 and 9):

* Blender axes: X = bow, Z = up, -Y = toward the plate camera (three.js +Z).
* A piece is built once into its own collection under the hidden collection
  ``KIT_MASTERS`` and placed as collection instances. Pieces are modelled in
  piece-local space, centred on X, floor level at Z = 0. Wall-like pieces have
  their room face at local Y = 0 facing -Y; the wall body extends toward +Y.
* ``SOCKET_`` empties and ``UCX_`` occluders are always real world-space
  objects. Inside a piece builder, :func:`socket` and :func:`occluder` only
  record local specs; :func:`place` emits them with the placement transform.
* Custom properties used by the cook: ``room``, ``nav`` ("walk", "block",
  "none"), ``station``, ``station_kind``, plus ``piece`` and ``owner``.
"""

from __future__ import annotations

import math
import zlib
from collections.abc import Callable, Iterable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field

import bmesh
import bpy
from mathutils import Matrix, Vector

from . import naming

MASTER_ROOT = "KIT_MASTERS"
NAV_VALUES = naming.NAV_VALUES
MODULE = 1.2  # metres; every panel, seam and light rhythm sits on this grid.

Vec3 = Sequence[float]


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------


@dataclass
class SocketSpec:
    kind: str
    local_id: str
    matrix: Matrix
    props: dict


@dataclass
class OccluderSpec:
    verts: list[Vector]
    faces: list[tuple[int, ...]]
    props: dict


@dataclass
class PieceDef:
    name: str
    builder: Callable[..., None]
    params: dict
    dims: tuple[float, float, float] | None
    nav: str
    doc: str
    master: bpy.types.Collection | None = None
    sockets: list[SocketSpec] = field(default_factory=list)
    occluders: list[OccluderSpec] = field(default_factory=list)


_REGISTRY: dict[str, PieceDef] = {}
_ACTIVE: list[PieceDef] = []
_COLLECTIONS: list[bpy.types.Collection] = []
_GHOST: list[float] = []  # clip heights of active ghost builds
_COUNTERS: dict[str, int] = {}


def piece(name: str, *, dims: Vec3 | None = None, nav: str = "block", **params):
    """Register a builder function as kit piece ``name``.

    ``dims`` is the nominal (X, Y, Z) footprint in metres, used by the kit
    sheet and validators. Extra keyword arguments are passed to the builder,
    so one function can register several sized variants.
    """
    if nav not in NAV_VALUES:
        raise ValueError(f"nav must be one of {NAV_VALUES}, got {nav!r}")

    def register(fn: Callable[..., None]) -> Callable[..., None]:
        _REGISTRY[name] = PieceDef(
            name=name,
            builder=fn,
            params=dict(params),
            dims=tuple(dims) if dims else None,
            nav=nav,
            doc=(fn.__doc__ or "").strip().splitlines()[0] if fn.__doc__ else "",
        )
        return fn

    return register


def register_variant(name: str, fn: Callable[..., None], *, dims=None, nav="block", **params):
    """Register ``fn`` under ``name`` with fixed builder parameters."""
    return piece(name, dims=dims, nav=nav, **params)(fn)


def registry() -> dict[str, PieceDef]:
    return dict(_REGISTRY)


def seed_for(*parts) -> int:
    """Stable seed from any parts (Python's hash() is randomised per run)."""
    return zlib.crc32("|".join(str(p) for p in parts).encode("utf-8"))


# --------------------------------------------------------------------------
# Collections
# --------------------------------------------------------------------------


def ensure_collection(
    name: str, parent: bpy.types.Collection | None = None
) -> bpy.types.Collection:
    col = bpy.data.collections.get(name)
    if col is None:
        col = bpy.data.collections.new(name)
    parent = parent or bpy.context.scene.collection
    if col.name not in parent.children:
        parent.children.link(col)
    return col


def current_collection() -> bpy.types.Collection:
    return _COLLECTIONS[-1] if _COLLECTIONS else bpy.context.scene.collection


@contextmanager
def into(collection: bpy.types.Collection | str):
    """Create every new object of the block inside ``collection``."""
    if isinstance(collection, str):
        collection = ensure_collection(collection)
    _COLLECTIONS.append(collection)
    try:
        yield collection
    finally:
        _COLLECTIONS.pop()


@contextmanager
def ghost(clip_z: float):
    """Build the cut-away upper part of a sectioned piece (above ``clip_z``).

    Everything built inside the block is clipped below ``clip_z`` and made
    invisible to the camera and to shadow rays, tagged ``ceiling_ghost``. It
    still mirrors in the black floor, emits light where it has fixtures and
    closes the room for environment/probe renders (BRIEF section 5; contract
    agreed with the pipeline). Sockets and occluders are not emitted.
    """
    _GHOST.append(clip_z)
    try:
        yield
    finally:
        _GHOST.pop()


def link(obj: bpy.types.Object) -> bpy.types.Object:
    current_collection().objects.link(obj)
    return obj


def _deck_collection(child: str) -> bpy.types.Collection:
    """The deck's ``Sockets``/``Occluders``/``NavOnly`` collection when the
    scene was made by ``lib.scene.new_deck``; else the current collection."""
    scene = bpy.context.scene
    if "verse" in scene:
        level = bpy.data.collections.get(naming.level_name(scene["verse"]["deck_id"]))
        if level is not None and child in level.children:
            return level.children[child]
    return current_collection()


def _masters_root() -> bpy.types.Collection:
    root = ensure_collection(MASTER_ROOT)
    for layer in bpy.context.scene.view_layers:
        lc = _find_layer_collection(layer.layer_collection, root.name)
        if lc is not None:
            lc.exclude = True
    return root


def _find_layer_collection(lc, name):
    if lc.collection.name == name:
        return lc
    for child in lc.children:
        found = _find_layer_collection(child, name)
        if found is not None:
            return found
    return None


def _remove_collection_tree(col: bpy.types.Collection) -> None:
    for child in list(col.children):
        _remove_collection_tree(child)
    for obj in list(col.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.collections.remove(col)


# --------------------------------------------------------------------------
# Masters and placement
# --------------------------------------------------------------------------


def build_master(name: str) -> bpy.types.Collection:
    """Build piece ``name`` once into its hidden master collection."""
    pdef = _REGISTRY.get(name)
    if pdef is None:
        raise KeyError(f"unknown kit piece {name!r}; import its kit module first")
    if pdef.master is not None:
        try:
            if pdef.master.name in bpy.data.collections:
                return pdef.master
        except ReferenceError:  # the file was reset (e.g. lib.scene.new_deck)
            pass
        pdef.master = None
    stale = bpy.data.collections.get(name)
    if stale is not None:  # left over from an earlier Python session
        _remove_collection_tree(stale)
    root = _masters_root()
    col = bpy.data.collections.new(name)
    root.children.link(col)
    pdef.sockets.clear()
    pdef.occluders.clear()
    _ACTIVE.append(pdef)
    try:
        with into(col):
            pdef.builder(**pdef.params)
    finally:
        _ACTIVE.pop()
    pdef.master = col
    return col


def _auto_id(name: str) -> str:
    base = name[3:] if name.startswith("SM_") else name
    while True:
        _COUNTERS[name] = _COUNTERS.get(name, 0) + 1
        candidate = f"{base}_{_COUNTERS[name]:03d}"
        if candidate not in bpy.data.objects:
            return candidate


def placement_matrix(
    location: Vec3 = (0, 0, 0), rot_z_deg: float = 0.0, scale: Vec3 | None = None
) -> Matrix:
    m = Matrix.Translation(Vector(location)) @ Matrix.Rotation(math.radians(rot_z_deg), 4, "Z")
    if scale is not None:
        m = m @ Matrix.Diagonal((*scale, 1.0))
    return m


def place(
    name: str,
    location: Vec3 = (0.0, 0.0, 0.0),
    rot_z_deg: float = 0.0,
    room: str | None = None,
    *,
    id: str | None = None,  # noqa: A002 - public API name from the brief
    scale: Vec3 | None = None,
    realize: bool = False,
    collection: bpy.types.Collection | None = None,
    nav: str | None = None,
    station: str | None = None,
    station_kind: str | None = None,
    **props,
) -> bpy.types.Object:
    """Place kit piece ``name`` and emit its sockets and occluders.

    Returns the placement object: a collection-instance empty, or (with
    ``realize=True``) an empty that parents real linked duplicates.

    Socket ids are ``<id>__<local id>``. Inside a piece builder an ``id``
    starting with "_" is anonymous: the nested piece's sockets keep their own
    local ids, so a station built from a console reports ``SOCKET_screen_<station id>``.
    """
    pdef = _REGISTRY.get(name)
    if pdef is None:
        raise KeyError(f"unknown kit piece {name!r}")
    if _GHOST:
        raise RuntimeError(
            "kit.place() inside kit.ghost() is not supported; build geometry directly"
        )
    master = build_master(name)
    place_id = id or _auto_id(name)
    matrix = placement_matrix(location, rot_z_deg, scale)
    target = collection or current_collection()

    root = bpy.data.objects.new(place_id, None)
    root.empty_display_size = 0.3
    root.matrix_world = matrix
    target.objects.link(root)
    if realize:
        for src in master.all_objects:
            dup = src.copy()  # shares mesh data, keeps modifiers
            target.objects.link(dup)
            dup.parent = root
            dup.matrix_parent_inverse = Matrix.Identity(4)
            dup.matrix_basis = src.matrix_world.copy()
    else:
        root.instance_type = "COLLECTION"
        root.instance_collection = master
    tag(
        root,
        room=room,
        nav=nav or pdef.nav,
        station=station,
        station_kind=station_kind,
        piece=name,
        **props,
    )

    shared = {
        k: v
        for k, v in dict(room=room, station=station, station_kind=station_kind).items()
        if v is not None
    }
    with into(target):
        for spec in pdef.sockets:
            sprops = {**spec.props, **shared, **props}
            sprops.pop("owner", None)  # the outermost placement owns nested sockets
            prefix = "" if place_id.startswith("_") else place_id
            sid = "__".join(part for part in (prefix, spec.local_id) if part)
            socket(spec.kind, sid, matrix @ spec.matrix, owner=place_id, **sprops)
        for n, spec in enumerate(pdef.occluders):
            verts = [matrix @ v for v in spec.verts]
            if _ACTIVE:  # nested placement inside another piece's builder
                _ACTIVE[-1].occluders.append(OccluderSpec(verts, spec.faces, dict(spec.props)))
                continue
            _emit_ucx(
                f"UCX_{place_id}__{n:02d}",
                verts,
                spec.faces,
                owner=place_id,
                room=room,
                **spec.props,
            )
    return root


def tag(
    obj: bpy.types.Object, room=None, nav=None, station=None, station_kind=None, **extra
) -> bpy.types.Object:
    """Set the cook's custom properties; ``None`` values are skipped."""
    if nav is not None and nav not in NAV_VALUES:
        raise ValueError(f"nav must be one of {NAV_VALUES}, got {nav!r}")
    for key, value in dict(
        room=room, nav=nav, station=station, station_kind=station_kind, **extra
    ).items():
        if value is not None:
            obj[key] = value
    return obj


# --------------------------------------------------------------------------
# Sockets, occluders, rooms
# --------------------------------------------------------------------------


def socket(kind: str, id: str, matrix_world: Matrix, **props) -> bpy.types.Object | None:  # noqa: A002
    """Create ``SOCKET_<kind>_<id>``: an empty whose local XY is the socket
    plane and +Z its normal (a screen's facing direction).

    Screens carry ``size_w``/``size_h`` in metres. Inside a piece builder this
    only records the socket; :func:`place` emits it per placement.
    """
    if _GHOST:
        return None
    if _ACTIVE:
        _ACTIVE[-1].sockets.append(SocketSpec(kind, id, matrix_world.copy(), dict(props)))
        return None
    if kind not in naming.SOCKET_KINDS:
        raise ValueError(f"unknown socket kind {kind!r}; expected one of {naming.SOCKET_KINDS}")
    name = naming.socket_name(kind, id)
    if len(name) > 63:
        raise ValueError(f"socket name too long for Blender (63 chars): {name}")
    obj = bpy.data.objects.new(name, None)
    obj.empty_display_type = "ARROWS"
    obj.empty_display_size = 0.25
    obj.matrix_world = matrix_world
    obj["socket_kind"] = kind
    tag(obj, **props)
    _deck_collection("Sockets").objects.link(obj)
    return obj


def socket_matrix(location: Vec3, normal: Vec3 = (0, 0, 1), up: Vec3 = (0, 0, 1)) -> Matrix:
    """Matrix whose +Z points along ``normal`` and +Y as close to ``up`` as possible."""
    z = Vector(normal).normalized()
    upv = Vector(up)
    if abs(z.dot(upv.normalized())) > 0.999:
        upv = Vector((0, 1, 0)) if abs(z.y) < 0.9 else Vector((1, 0, 0))
    x = upv.cross(z).normalized()
    y = z.cross(x).normalized()
    m = Matrix((x, y, z)).transposed().to_4x4()
    m.translation = Vector(location)
    return m


def facing_matrix(location: Vec3, facing_deg: float = 0.0) -> Matrix:
    """Seat, stand and spawn sockets: the character faces the empty's local -Y.

    ``facing_deg`` is a rotation about +Z: 0 faces the camera (Blender -Y),
    180 faces away from it (toward Blender +Y, e.g. a seated console crew),
    90 faces the bow (+X). Same convention as ``lib.scene.add_socket``.
    """
    m = Matrix.Rotation(math.radians(facing_deg), 4, "Z")
    m.translation = Vector(location)
    return m


def screen_matrix(center: Vec3, tilt_deg: float = 0.0, yaw_deg: float = 0.0) -> Matrix:
    """Screen sockets: local XY = screen plane, +Z = screen normal.

    yaw 0 faces the camera (normal -Y); ``tilt_deg`` leans the top away from
    the viewer, as on a console desk. Same convention as ``lib.scene.add_screen``.
    """
    rot = Matrix.Rotation(math.radians(yaw_deg), 4, "Z") @ Matrix.Rotation(
        math.radians(90.0 - tilt_deg), 4, "X"
    )
    rot.translation = Vector(center)
    return rot


def occluder(source, *, name: str | None = None, **props) -> bpy.types.Object | None:
    """Create a ``UCX_`` depth-only proxy from an object or a bbox.

    ``source`` is either a mesh object (its undeformed mesh is copied) or a
    bbox ``((min_x, min_y, min_z), (max_x, max_y, max_z))``.
    """
    if _GHOST:
        return None
    if isinstance(source, bpy.types.Object):
        mw = source.matrix_world if not _ACTIVE else source.matrix_basis
        verts = [mw @ v.co for v in source.data.vertices]
        faces = [tuple(p.vertices) for p in source.data.polygons]
    else:
        verts, faces = _box_verts_faces(Vector(source[0]), Vector(source[1]))
    if _ACTIVE:
        _ACTIVE[-1].occluders.append(OccluderSpec(verts, faces, dict(props)))
        return None
    n = len([o for o in bpy.data.objects if o.name.startswith("UCX_")])
    return _emit_ucx(name or f"UCX_free_{n:04d}", verts, faces, **props)


def _emit_ucx(name: str, verts, faces, **props) -> bpy.types.Object:
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata([tuple(v) for v in verts], [], [tuple(f) for f in faces])
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    obj.hide_render = True
    obj.visible_camera = False
    obj.display_type = "WIRE"
    obj["ucx"] = True
    props.setdefault("nav", "block")
    tag(obj, **props)
    _deck_collection("Occluders").objects.link(obj)
    return obj


def room(
    id: str,  # noqa: A002 - public API name from the brief
    name: str,
    polygon: Iterable[Sequence[float]],
    z: float = 0.0,
    **props,
) -> bpy.types.Object:
    """Create ``ROOM_<id>``: a flat, unrendered ngon of the room's floor."""
    pts = [Vector((p[0], p[1], z)) for p in polygon]
    mesh = bpy.data.meshes.new(f"ROOM_{id}")
    mesh.from_pydata([tuple(p) for p in pts], [], [tuple(range(len(pts)))])
    mesh.update()
    obj = bpy.data.objects.new(f"ROOM_{id}", mesh)
    obj.hide_render = True
    obj.display_type = "WIRE"
    obj["name"] = name
    tag(obj, room=id, nav="walk", **props)
    _deck_collection("NavOnly").objects.link(obj)
    return obj


# --------------------------------------------------------------------------
# Bevel and shading
# --------------------------------------------------------------------------


def bevel(
    obj: bpy.types.Object,
    width: float = 0.006,
    segments: int = 2,
    angle_deg: float = 30.0,
    harden: bool = True,
):
    """Bevel every hard edge (angle limited) and harden the normals so the
    flat faces stay flat while the edges catch a crisp highlight."""
    if width <= 0:
        return None
    mod = obj.modifiers.new("Bevel", "BEVEL")
    mod.width = width
    mod.segments = segments
    mod.limit_method = "ANGLE"
    mod.angle_limit = math.radians(angle_deg)
    mod.use_clamp_overlap = True
    mod.miter_outer = "MITER_ARC"
    mod.harden_normals = harden
    obj.data.shade_smooth()
    return mod


# --------------------------------------------------------------------------
# Mesh building
# --------------------------------------------------------------------------


def _box_verts_faces(lo: Vector, hi: Vector):
    x0, y0, z0 = lo
    x1, y1, z1 = hi
    verts = [
        Vector(v)
        for v in (
            (x0, y0, z0),
            (x1, y0, z0),
            (x1, y1, z0),
            (x0, y1, z0),
            (x0, y0, z1),
            (x1, y0, z1),
            (x1, y1, z1),
            (x0, y1, z1),
        )
    ]
    faces = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    return verts, faces


class MeshBuilder:
    """Accumulates boxes, prisms and tubes per material into one mesh.

    Usage::

        mb = MeshBuilder()
        mb.box((-0.6, 0, 0), (0.6, 0.3, 1.1), "M_Wall_PaintedLight")
        obj = mb.build("SM_X_body", bevel_width=0.004)
    """

    def __init__(self, matrix: Matrix | None = None):
        self.bm = bmesh.new()
        self.materials: list[str] = []
        self.matrix = matrix or Matrix.Identity(4)

    def _mat_index(self, material: str) -> int:
        if material not in self.materials:
            self.materials.append(material)
        return self.materials.index(material)

    def _add(
        self, verts: list[Vector], faces: list[Sequence[int]], material: str, smooth: bool = False
    ):
        idx = self._mat_index(material)
        bv = [self.bm.verts.new(self.matrix @ Vector(v)) for v in verts]
        for f in faces:
            try:
                face = self.bm.faces.new([bv[i] for i in f])
            except ValueError:
                continue
            face.material_index = idx
            face.smooth = smooth
        return bv

    def box(self, lo: Vec3, hi: Vec3, material: str):
        lo, hi = Vector(lo), Vector(hi)
        a = Vector((min(lo.x, hi.x), min(lo.y, hi.y), min(lo.z, hi.z)))
        b = Vector((max(lo.x, hi.x), max(lo.y, hi.y), max(lo.z, hi.z)))
        verts, faces = _box_verts_faces(a, b)
        self._add(verts, faces, material)
        return self

    def box_c(self, center: Vec3, size: Vec3, material: str):
        c, s = Vector(center), Vector(size) * 0.5
        return self.box(c - s, c + s, material)

    def prism_x(
        self,
        profile_yz: Sequence[Sequence[float]],
        x0: float,
        x1: float,
        material: str,
        cap_material: str | None = None,
    ):
        """Extrude a closed YZ profile (counter-clockwise seen from +X) along X."""
        n = len(profile_yz)
        verts = [Vector((x0, y, z)) for y, z in profile_yz] + [
            Vector((x1, y, z)) for y, z in profile_yz
        ]
        sides = [(i, (i + 1) % n, n + (i + 1) % n, n + i) for i in range(n)]
        self._add(verts, sides, material)
        cap = cap_material or material
        self._add(verts, [tuple(reversed(range(n))), tuple(range(n, 2 * n))], cap)
        return self

    def prism_y(
        self,
        profile_xz: Sequence[Sequence[float]],
        y0: float,
        y1: float,
        material: str,
    ):
        """Extrude a closed XZ profile along Y (one solid, e.g. a stair flight)."""
        n = len(profile_xz)
        verts = [Vector((x, y0, z)) for x, z in profile_xz] + [
            Vector((x, y1, z)) for x, z in profile_xz
        ]
        sides = [(i, (i + 1) % n, n + (i + 1) % n, n + i) for i in range(n)]
        self._add(verts, sides, material)
        self._add(verts, [tuple(reversed(range(n))), tuple(range(n, 2 * n))], material)
        return self

    def prism_z(
        self,
        polygon_xy: Sequence[Sequence[float]],
        z0: float,
        z1: float,
        material: str,
        cap_material: str | None = None,
    ):
        """Extrude a closed XY polygon (counter-clockwise from above) along Z."""
        n = len(polygon_xy)
        verts = [Vector((x, y, z0)) for x, y in polygon_xy] + [
            Vector((x, y, z1)) for x, y in polygon_xy
        ]
        sides = [(i, (i + 1) % n, n + (i + 1) % n, n + i) for i in range(n)]
        self._add(verts, sides, material)
        self._add(verts, [tuple(reversed(range(n)))], material)
        self._add(verts, [tuple(range(n, 2 * n))], cap_material or material)
        return self

    def tube(
        self,
        p0: Vec3,
        p1: Vec3,
        radius: float,
        material: str,
        segments: int = 12,
        caps: bool = True,
    ):
        """Cylinder from ``p0`` to ``p1`` (smooth shaded)."""
        p0, p1 = Vector(p0), Vector(p1)
        axis = p1 - p0
        length = axis.length
        if length < 1e-6:
            return self
        z = axis.normalized()
        ref = Vector((0, 0, 1)) if abs(z.z) < 0.9 else Vector((1, 0, 0))
        x = ref.cross(z).normalized()
        y = z.cross(x)
        ring0, ring1 = [], []
        for i in range(segments):
            a = 2 * math.pi * i / segments
            off = (x * math.cos(a) + y * math.sin(a)) * radius
            ring0.append(p0 + off)
            ring1.append(p1 + off)
        verts = ring0 + ring1
        faces = [
            (i, (i + 1) % segments, segments + (i + 1) % segments, segments + i)
            for i in range(segments)
        ]
        bv = self._add(verts, faces, material, smooth=True)
        if caps:
            idx = self._mat_index(material)
            for ring in (bv[:segments][::-1], bv[segments:]):
                f = self.bm.faces.new(ring)
                f.material_index = idx
        return self

    def polyline_tube(
        self, points: Sequence[Vec3], radius: float, material: str, segments: int = 12
    ):
        for a, b in zip(points[:-1], points[1:], strict=True):
            self.tube(a, b, radius, material, segments)
        return self

    def quad(self, corners: Sequence[Vec3], material: str):
        self._add([Vector(c) for c in corners], [(0, 1, 2, 3)], material)
        return self

    def is_empty(self) -> bool:
        return len(self.bm.verts) == 0

    def build(
        self,
        name: str,
        *,
        bevel_width: float = 0.006,
        segments: int = 2,
        angle_deg: float = 30.0,
        recalc_normals: bool = True,
        **props,
    ) -> bpy.types.Object | None:
        if self.is_empty():
            self.bm.free()
            return None
        from . import materials  # local import: materials imports nothing from kit

        if _GHOST:
            geom = [*self.bm.verts, *self.bm.edges, *self.bm.faces]
            bmesh.ops.bisect_plane(
                self.bm,
                geom=geom,
                plane_co=(0.0, 0.0, _GHOST[-1]),
                plane_no=(0.0, 0.0, 1.0),
                clear_inner=True,
            )
            if self.is_empty():
                self.bm.free()
                return None
        if recalc_normals:
            bmesh.ops.recalc_face_normals(self.bm, faces=list(self.bm.faces))
        mesh = bpy.data.meshes.new(name)
        self.bm.to_mesh(mesh)
        self.bm.free()
        for mat_name in self.materials:
            mesh.materials.append(materials.get(mat_name))
        obj = bpy.data.objects.new(name, mesh)
        link(obj)
        if bevel_width > 0:
            bevel(obj, bevel_width, segments, angle_deg)
        tag(obj, **props)
        if _GHOST:
            obj.visible_camera = False
            obj.visible_shadow = False
            obj["ceiling_ghost"] = True
            obj["nav"] = "none"
        return obj


def mesh_object(
    name: str, verts, faces, material: str, *, bevel_width: float = 0.0, **props
) -> bpy.types.Object:
    mb = MeshBuilder()
    mb._add([Vector(v) for v in verts], faces, material)
    return mb.build(name, bevel_width=bevel_width, recalc_normals=False, **props)


def emissive_panel(
    name: str,
    center: Vec3,
    size_xy: Sequence[float],
    material: str,
    *,
    normal: str = "-Z",
    camera_visible: bool = True,
    **props,
) -> bpy.types.Object:
    """Flat emitter quad (a light fixture's diffuser face).

    ``normal`` is the axis the light faces ("-Z" for ceiling panels, "-Y" for
    walls facing the camera, and so on).
    """
    c = Vector(center)
    w, h = size_xy[0] * 0.5, size_xy[1] * 0.5
    axis = normal[-1]
    sign = -1.0 if normal.startswith("-") else 1.0
    if axis == "Z":
        corners = [(-w, -h, 0), (w, -h, 0), (w, h, 0), (-w, h, 0)]
    elif axis == "Y":
        corners = [(-w, 0, -h), (w, 0, -h), (w, 0, h), (-w, 0, h)]
    else:
        corners = [(0, -w, -h), (0, w, -h), (0, w, h), (0, -w, h)]
    corners = [c + Vector(v) for v in corners]
    face_normal = (corners[1] - corners[0]).cross(corners[2] - corners[1]).normalized()
    want = Vector({"X": (sign, 0, 0), "Y": (0, sign, 0), "Z": (0, 0, sign)}[axis])
    if face_normal.dot(want) < 0:
        corners.reverse()
    obj = mesh_object(name, corners, [(0, 1, 2, 3)], material, **props)
    if obj is not None and not obj.get("ceiling_ghost"):
        obj.visible_camera = camera_visible
    return obj


def hide_from_camera(obj: bpy.types.Object) -> bpy.types.Object:
    """Ceilings and their fixtures: still light the room and mirror in the
    floor, never seen directly by the plate camera (BRIEF section 5)."""
    obj.visible_camera = False
    return obj
