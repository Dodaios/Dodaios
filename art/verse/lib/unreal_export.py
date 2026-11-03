"""Export kit pieces and calibration assets to FBX for Unreal (art-pipeline 6.1).

Runs inside Blender (bpy). The host entry is `scripts/verse/export_unreal.py`,
which starts Blender through `scripts/verse/blender.py` under the machine-wide
lock; nothing else calls this module.

One FBX per asset, in piece space as authored. Every export uses the frozen
settings set `fbx-ue/1` (`FBX_UE_1`), proven by the calibration assets of
`kit/calib.py` and `python scripts/unreal/import_art.py calib`. Any change to
`FBX_UE_1` is a contract change (`fbx-ue/2`) and reruns the calibration.

Name rules (art-pipeline 3.1):

* `UCX_*` objects and the `Occluders` collection are Blender depth proxies and
  are never exported.
* Kit sockets (`SOCKET_<kind>_<id>`) are world sockets; they go to the
  placement JSON, never into a mesh.
* `UECOL_<Box|Sphere|Capsule|Convex>_<nn>` meshes become Unreal collision
  primitives `UBX_/USP_/UCP_/UCX_<SM_Name>_<nn>`.
* `UESOCKET_<name>` empties become mesh sockets `SOCKET_<name>`.

Any other object whose name starts with a reserved Unreal prefix fails the
export.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Vector

from . import ue_space, unreal_materials

SETTINGS_ID = "fbx-ue/1"
GENERATOR_VERSION = "1"

#: The frozen `fbx-ue/1` settings of `bpy.ops.export_scene.fbx`.
FBX_UE_1: dict = {
    "use_selection": True,
    "use_visible": False,
    "use_active_collection": False,
    "global_scale": 1.0,
    "apply_unit_scale": True,
    "apply_scale_options": "FBX_SCALE_NONE",
    "use_space_transform": True,
    "bake_space_transform": False,
    "axis_forward": "-Z",
    "axis_up": "Y",
    "object_types": {"MESH", "EMPTY", "ARMATURE"},
    "use_mesh_modifiers": True,
    "use_mesh_modifiers_render": True,
    "mesh_smooth_type": "FACE",
    "use_subsurf": False,
    "use_mesh_edges": False,
    "use_tspace": True,
    "use_triangles": True,
    "use_custom_props": False,
    "add_leaf_bones": False,
    "primary_bone_axis": "Y",
    "secondary_bone_axis": "X",
    "use_armature_deform_only": True,
    "armature_nodetype": "NULL",
    "bake_anim": False,
    "path_mode": "STRIP",
    "embed_textures": False,
    "batch_mode": "OFF",
}

#: Names the Unreal importer reads as collision or sockets (art-pipeline 3.1).
RESERVED_PREFIXES = ("UCX_", "UBX_", "USP_", "UCP_", "SOCKET_")
_COLLISION_RE = re.compile(r"^UECOL_(?P<type>Box|Sphere|Capsule|Convex)_(?P<nn>\d{2})(?:[._].*)?$")
_MESH_SOCKET_RE = re.compile(r"^UESOCKET_(?P<name>[A-Za-z][A-Za-z0-9_]*?)(?:\.\d{3})?$")
_COLLISION_PREFIX = {"Box": "UBX_", "Sphere": "USP_", "Capsule": "UCP_", "Convex": "UCX_"}
MAX_PRIMITIVES = 16
MAX_HULL_VERTS = 32

REPO_ROOT = Path(__file__).resolve().parents[3]
CACHE_ROOT = REPO_ROOT / "art" / "verse" / ".cache" / "unreal"


class ExportError(RuntimeError):
    """The asset cannot be exported under `fbx-ue/1`."""


@dataclass
class ExportResult:
    name: str
    file: Path
    sha256: str
    triangles: int
    vertices: int
    bounds_cm: dict
    uv_sets: int
    material_slots: list[dict]
    collision_primitives: int
    sockets: list[str] = field(default_factory=list)
    bones: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "file": self.file.relative_to(REPO_ROOT).as_posix(),
            "sha256": self.sha256,
            "triangles": self.triangles,
            "vertices": self.vertices,
            "bounds_cm": self.bounds_cm,
            "uv_sets": self.uv_sets,
            "material_slots": self.material_slots,
            "collision_primitives": self.collision_primitives,
            "sockets": self.sockets,
            "bones": self.bones,
            "settings_id": SETTINGS_ID,
            "blender": bpy.app.version_string.split(" ")[0],
        }


def strip_suffix(name: str) -> str:
    return re.sub(r"\.\d{3}$", "", name)


# --------------------------------------------------------------------------
# Collecting a piece
# --------------------------------------------------------------------------


def _walk(
    collection: bpy.types.Collection, matrix: Matrix, depth: int = 0
) -> Iterator[tuple[bpy.types.Object, Matrix]]:
    """Yield (object, matrix in piece space), recursing into collection instances."""
    if depth > 16:
        raise ExportError(f"collection instances nested too deep in {collection.name}")
    for obj in collection.all_objects:
        world = matrix @ obj.matrix_world
        yield obj, world
        if obj.instance_type == "COLLECTION" and obj.instance_collection is not None:
            inst = obj.instance_collection
            offset = Matrix.Translation(-Vector(inst.instance_offset))
            yield from _walk(inst, world @ offset, depth + 1)


def _is_ghost(obj: bpy.types.Object) -> bool:
    return bool(obj.get("ceiling_ghost"))


def _in_occluders(obj: bpy.types.Object) -> bool:
    return any(strip_suffix(col.name) == "Occluders" for col in obj.users_collection)


def _evaluated_mesh(obj: bpy.types.Object, depsgraph, matrix: Matrix) -> bpy.types.Mesh:
    """Mesh with modifiers applied, transformed into piece space."""
    evaluated = obj.evaluated_get(depsgraph)
    mesh = bpy.data.meshes.new_from_object(
        evaluated, preserve_all_data_layers=True, depsgraph=depsgraph
    )
    mesh.transform(matrix)
    if matrix.determinant() < 0:
        mesh.flip_normals()
    return mesh


@dataclass
class _Parts:
    meshes: list[tuple[bpy.types.Mesh, str]] = field(default_factory=list)  # (mesh, source)
    collision: list[tuple[bpy.types.Mesh, str, str]] = field(default_factory=list)
    sockets: list[tuple[str, Matrix]] = field(default_factory=list)


def collect(collection: bpy.types.Collection, root_name: str = "") -> _Parts:
    """Split a piece collection into render meshes, collision and mesh sockets."""
    parts = _Parts()
    # Masters live in the excluded KIT_MASTERS tree; link the piece into the
    # scene for a moment so its modifiers are evaluated.
    scene_root = bpy.context.scene.collection
    linked = collection.name not in scene_root.children
    if linked:
        scene_root.children.link(collection)
    try:
        bpy.context.view_layer.update()
        depsgraph = bpy.context.evaluated_depsgraph_get()
        for obj, matrix in _walk(collection, Matrix.Identity(4)):
            name = strip_suffix(obj.name)
            if _is_ghost(obj) or _in_occluders(obj) or name.startswith("UCX_"):
                continue
            collision = _COLLISION_RE.match(obj.name)
            if collision:
                if obj.type != "MESH":
                    raise ExportError(f"{obj.name}: collision primitives must be meshes")
                parts.collision.append(
                    (_evaluated_mesh(obj, depsgraph, matrix), collision["type"], collision["nn"])
                )
                continue
            socket = _MESH_SOCKET_RE.match(obj.name)
            if socket:
                parts.sockets.append((socket["name"], matrix.copy()))
                continue
            if name.startswith("SOCKET_") or name.startswith("ROOM_"):
                continue  # world sockets and rooms belong to the placement JSON
            if name.startswith(RESERVED_PREFIXES):
                raise ExportError(f"{obj.name}: reserved Unreal prefix (art-pipeline 3.1)")
            if obj.type != "MESH":
                continue
            parts.meshes.append((_evaluated_mesh(obj, depsgraph, matrix), obj.name))
    finally:
        if linked:
            scene_root.children.unlink(collection)
    if not parts.meshes:
        raise ExportError(f"{collection.name}: nothing to export")
    return parts


# --------------------------------------------------------------------------
# Building the export objects
# --------------------------------------------------------------------------


def _join(meshes: list[bpy.types.Mesh], name: str) -> bpy.types.Mesh:
    """Join meshes into one, with one material slot per distinct material name."""
    slots: list[bpy.types.Material] = []
    slot_names: list[str] = []
    bm = bmesh.new()
    for mesh in meshes:
        remap = []
        for material in mesh.materials:
            key = strip_suffix(material.name) if material else "M_Default"
            if key not in slot_names:
                slot_names.append(key)
                slots.append(material)
            remap.append(slot_names.index(key))
        for poly in mesh.polygons:
            poly.material_index = remap[poly.material_index] if remap else 0
        bm.from_mesh(mesh)
    out = bpy.data.meshes.new(name)
    bm.to_mesh(out)
    bm.free()
    for material in slots:
        out.materials.append(material)
    return out


def box_project_uv(mesh: bpy.types.Mesh) -> None:
    """UV0 in real metres, projected along each face's dominant axis (art-pipeline 6.1)."""
    layer = mesh.uv_layers.new(name="UVMap")
    for poly in mesh.polygons:
        n = poly.normal
        axis = max(range(3), key=lambda i: abs(n[i]))
        for li in poly.loop_indices:
            co = mesh.vertices[mesh.loops[li].vertex_index].co
            if axis == 0:
                u, v = (co.y if n.x >= 0 else -co.y), co.z
            elif axis == 1:
                u, v = (-co.x if n.y >= 0 else co.x), co.z
            else:
                u, v = co.x, (co.y if n.z >= 0 else -co.y)
            layer.data[li].uv = (u, v)


def check_hygiene(mesh: bpy.types.Mesh, name: str) -> None:
    """Fail on zero-area faces; the rest of the hygiene list is the builder's job."""
    degenerate = sum(1 for poly in mesh.polygons if poly.area < 1e-10)
    if degenerate:
        raise ExportError(f"{name}: {degenerate} zero-area faces")


def triangle_count(mesh: bpy.types.Mesh) -> int:
    return sum(len(poly.vertices) - 2 for poly in mesh.polygons)


def bounds_cm(mesh: bpy.types.Mesh) -> dict:
    xs = [v.co.x for v in mesh.vertices]
    ys = [v.co.y for v in mesh.vertices]
    zs = [v.co.z for v in mesh.vertices]
    lo, hi = ue_space.bounds_to_ue((min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs)))
    return {"min": [round(v, 3) for v in lo], "max": [round(v, 3) for v in hi]}


EXPORT_COLLECTION = "VERSE_UE_EXPORT"


def _export_scene() -> bpy.types.Collection:
    """An emptied collection in the current scene that holds one asset's export objects.

    Exporting from the current scene avoids overriding the context scene,
    which crashes Blender 5.0 in background mode.
    """
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0
    col = bpy.data.collections.get(EXPORT_COLLECTION)
    if col is None:
        col = bpy.data.collections.new(EXPORT_COLLECTION)
        scene.collection.children.link(col)
    for obj in list(col.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    return col


#: Export data in centimetres with a scene unit scale of 0.01. With metres the
#: FBX armature node carries a scale of 100 that the importer bakes into the
#: first bone (found by the SK_Calib_Rig calibration); in centimetres every
#: node keeps scale 1. Part of `fbx-ue/1`.
CM = 100.0


def _to_centimetres(objects: list[bpy.types.Object]) -> None:
    """Scale the export copies' data (never object scale) from metres to centimetres."""
    scale = Matrix.Scale(CM, 4)
    for obj in objects:
        if obj.type == "ARMATURE":
            with bpy.context.temp_override(active_object=obj, object=obj):
                bpy.ops.object.mode_set(mode="EDIT")
                for bone in obj.data.edit_bones:
                    bone.head = bone.head * CM
                    bone.tail = bone.tail * CM
                bpy.ops.object.mode_set(mode="OBJECT")
        elif obj.type == "MESH":
            obj.data.transform(scale)
        if obj.parent is None or obj.parent not in objects:
            obj.matrix_world.translation = obj.matrix_world.translation * CM
        elif obj.type == "EMPTY":
            obj.matrix_parent_inverse = Matrix.Identity(4)
            obj.matrix_basis.translation = obj.matrix_basis.translation * CM


class _FixedClock(datetime.datetime):
    """`datetime.now()` pinned, so the FBX header time and the file hash are stable."""

    @classmethod
    def now(cls, tz=None):  # noqa: ARG003 - same signature as datetime.now
        return cls(2000, 1, 1, 0, 0, 0)


def _stable_hash(key) -> int:
    """Process-independent stand-in for `hash()` (string hashing is salted per run)."""
    return int.from_bytes(hashlib.sha256(repr(key).encode("utf-8")).digest()[:8], "little")


@contextmanager
def _reproducible_fbx():
    """Pin the two run-dependent inputs of Blender's FBX writer: the header time
    and the object ids (derived from `hash()` of names). Same scene, same bytes,
    so `export.sha256` only changes when the art does (art-pipeline 10.2)."""
    from io_scene_fbx import export_fbx_bin, fbx_utils

    original = export_fbx_bin.datetime
    export_fbx_bin.datetime = type("datetime_module", (), {"datetime": _FixedClock})
    fbx_utils.hash = _stable_hash
    try:
        yield
    finally:
        export_fbx_bin.datetime = original
        del fbx_utils.hash


def _write_fbx(col: bpy.types.Collection, objects: list[bpy.types.Object], path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    view_layer = bpy.context.view_layer
    view_layer.update()
    _to_centimetres(objects)
    units = bpy.context.scene.unit_settings
    units.scale_length = 1.0 / CM
    for obj in view_layer.objects:
        obj.select_set(False)
    for obj in objects:
        obj.select_set(True)
    view_layer.objects.active = objects[0]
    try:
        override = bpy.context.temp_override(active_object=objects[0], object=objects[0])
        with override, _reproducible_fbx():
            result = bpy.ops.export_scene.fbx(filepath=str(path), **FBX_UE_1)
    finally:
        units.scale_length = 1.0
    if "FINISHED" not in result:
        raise ExportError(f"FBX export failed for {path.name}: {result}")
    check_fbx_names(path, {obj.name for obj in objects})
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_fbx_names(path: Path, allowed: set[str]) -> None:
    """Fail when a reserved Unreal name reached the FBX by any other route."""
    data = path.read_bytes()
    for prefix in RESERVED_PREFIXES:
        for match in re.finditer(re.escape(prefix.encode()) + rb"[A-Za-z0-9_]+", data):
            found = match.group(0).decode("ascii", "replace")
            if found not in allowed:
                raise ExportError(f"{path.name}: reserved name {found} reached the FBX")


def export_static_mesh(
    name: str, collection: bpy.types.Collection, out_dir: Path, *, root_name: str = ""
) -> ExportResult:
    """Export the objects of `collection` as static mesh `name` (one FBX)."""
    if not re.match(r"^SM_[A-Za-z0-9][A-Za-z0-9_]{0,60}$", name):
        raise ExportError(f"{name}: static mesh names are SM_<PascalCase> (art-pipeline 3)")
    parts = collect(collection, root_name)
    if len(parts.collision) > MAX_PRIMITIVES:
        count = len(parts.collision)
        raise ExportError(f"{name}: {count} collision primitives, cap {MAX_PRIMITIVES}")
    scene = _export_scene()
    mesh = _join([m for m, _ in parts.meshes], name)
    check_hygiene(mesh, name)
    if not mesh.uv_layers:
        box_project_uv(mesh)
    body = bpy.data.objects.new(name, mesh)
    scene.objects.link(body)
    objects = [body]
    for col_mesh, kind, nn in parts.collision:
        if kind == "Convex" and len(col_mesh.vertices) > MAX_HULL_VERTS:
            raise ExportError(f"{name}: convex hull {nn} has {len(col_mesh.vertices)} vertices")
        col_obj = bpy.data.objects.new(f"{_COLLISION_PREFIX[kind]}{name}_{nn}", col_mesh)
        scene.objects.link(col_obj)
        objects.append(col_obj)
    socket_names = []
    for socket_name, matrix in parts.sockets:
        empty = bpy.data.objects.new(f"SOCKET_{socket_name}", None)
        scene.objects.link(empty)
        empty.parent = body
        empty.matrix_world = matrix
        objects.append(empty)
        socket_names.append(f"SOCKET_{socket_name}")
    path = out_dir / f"{name}.fbx"
    box = bounds_cm(mesh)  # metres -> cm before the export scales the copies
    digest = _write_fbx(scene, objects, path)
    slots = [
        {"slot": strip_suffix(m.name) if m else "M_Default", "mi": _mi_path(m)}
        for m in mesh.materials
    ]
    result = ExportResult(
        name=name,
        file=path,
        sha256=digest,
        triangles=triangle_count(mesh),
        vertices=len(mesh.vertices),
        bounds_cm=box,
        uv_sets=len(mesh.uv_layers),
        material_slots=slots,
        collision_primitives=len(parts.collision),
        sockets=sorted(socket_names),
    )
    for m, _ in parts.meshes:
        bpy.data.meshes.remove(m)
    return result


def _mi_path(material) -> str:
    name = strip_suffix(material.name) if material else "M_Default"
    try:
        return unreal_materials.instance_path(name)
    except ValueError:
        return unreal_materials.instance_path("M_Default")


# --------------------------------------------------------------------------
# Skeletal calibration rig
# --------------------------------------------------------------------------


def build_rig(name: str, bones: tuple, out_dir: Path) -> ExportResult:
    """Build and export a skinned armature: one 10 cm box per bone, rigid weights.

    `bones` is a tuple of (name, parent, head, tail) in Blender metres.
    """
    scene = _export_scene()
    arm_data = bpy.data.armatures.new(f"{name}_Data")
    # The Unreal importer drops a root node named "Armature", so the first
    # bone of the skeleton is the rig's own `Root`.
    arm_obj = bpy.data.objects.new("Armature", arm_data)
    scene.objects.link(arm_obj)
    bpy.context.view_layer.update()
    bpy.context.view_layer.objects.active = arm_obj
    with bpy.context.temp_override(active_object=arm_obj, object=arm_obj):
        bpy.ops.object.mode_set(mode="EDIT")
        edit = arm_data.edit_bones
        for bone_name, parent, head, tail in bones:
            bone = edit.new(bone_name)
            bone.head = head
            bone.tail = tail
            bone.roll = 0.0
            bone.use_deform = True
            if parent:
                bone.parent = edit[parent]
        bpy.ops.object.mode_set(mode="OBJECT")

    bm = bmesh.new()
    groups: list[tuple[str, list[int]]] = []
    for bone_name, _parent, head, tail in bones:
        centre = (Vector(head) + Vector(tail)) * 0.5
        start = len(bm.verts)
        geom = bmesh.ops.create_cube(bm, size=0.1)
        bmesh.ops.translate(bm, verts=geom["verts"], vec=centre)
        groups.append((bone_name, list(range(start, start + len(geom["verts"])))))
    mesh = bpy.data.meshes.new(f"SK_{name[3:]}" if name.startswith("SK_") else name)
    bm.to_mesh(mesh)
    bm.free()
    box_project_uv(mesh)
    mesh.materials.append(bpy.data.materials.get("M_Calib") or bpy.data.materials.new("M_Calib"))
    body = bpy.data.objects.new(name, mesh)
    scene.objects.link(body)
    body.parent = arm_obj
    for bone_name, indices in groups:
        group = body.vertex_groups.new(name=bone_name)
        group.add(indices, 1.0, "REPLACE")
    modifier = body.modifiers.new("Armature", "ARMATURE")
    modifier.object = arm_obj
    path = out_dir / f"{name}.fbx"
    box = bounds_cm(mesh)  # metres -> cm before the export scales the copies
    digest = _write_fbx(scene, [arm_obj, body], path)
    return ExportResult(
        name=name,
        file=path,
        sha256=digest,
        triangles=triangle_count(mesh),
        vertices=len(mesh.vertices),
        bounds_cm=box,
        uv_sets=len(mesh.uv_layers),
        material_slots=[],
        collision_primitives=0,
        bones=[b[0] for b in bones],
    )


def write_result(path: Path, results: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"settings_id": SETTINGS_ID, "assets": results}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
