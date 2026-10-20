"""Shared constants and small helpers for the character builders.

Blender axes throughout (X = character's left, -Y = forward, Z = up). The glTF
exporter's +Y-up conversion turns -Y into three.js +Z, so every character faces
+Z in the runtime.
"""

from __future__ import annotations

import math
import os
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Vector

HERE = Path(__file__).resolve().parent
ART_ROOT = HERE.parent
REPO_ROOT = ART_ROOT.parent.parent
CACHE = ART_ROOT / ".cache" / "characters"
OUT_DIR = REPO_ROOT / "dodaios" / "ui" / "web" / "frontend" / "public" / "verse" / "characters"

BUNDLE_URL = (
    "https://download.blender.org/demo/asset-bundles/human-base-meshes/"
    "human-base-meshes-bundle-v1.4.1.zip"
)
BUNDLE_SHA256 = "811f43accbb31a88266d932f8f5563b2d13586fca0ba2693aad1f5fe582b3515"
BUNDLE_BLEND = (
    CACHE / "download" / "human-base-meshes-bundle-v1.4.1" / "human_base_meshes_bundle.blend"
)

FPS = 30

# Body variants: same bone names and hierarchy, own rest pose (proportions).
VARIANTS = {
    "M": {"source": "GEO-body_male_realistic", "height": 1.78},
    "F": {"source": "GEO-body_female_realistic", "height": 1.68},
}

SEAT_HEIGHT = 0.46  # seat surface above the floor, metres
DESK_HEIGHT = 0.74  # typing surface for seated consoles
STAND_DESK_HEIGHT = 1.02  # typing surface for standing consoles
WALK_SPEED = 1.40  # m/s at which A_Walk does not slide (male skeleton)

# Bone names are fixed: three.js strips "." from node names, so sides use "_L"/"_R".
SPINE = ["Hips", "Spine", "Chest", "Neck", "Head"]
SIDE_BONES = [
    "Shoulder",
    "UpperArm",
    "ForeArm",
    "Hand",
    "Fingers",
    "Thumb",
    "UpperLeg",
    "LowerLeg",
    "Foot",
    "Toe",
]
BONES = SPINE + [f"{b}_{s}" for s in ("L", "R") for b in SIDE_BONES]
PARENTS = {
    "Hips": None,
    "Spine": "Hips",
    "Chest": "Spine",
    "Neck": "Chest",
    "Head": "Neck",
}
for _s in ("L", "R"):
    PARENTS.update(
        {
            f"Shoulder_{_s}": "Chest",
            f"UpperArm_{_s}": f"Shoulder_{_s}",
            f"ForeArm_{_s}": f"UpperArm_{_s}",
            f"Hand_{_s}": f"ForeArm_{_s}",
            f"Fingers_{_s}": f"Hand_{_s}",
            f"Thumb_{_s}": f"Hand_{_s}",
            f"UpperLeg_{_s}": "Hips",
            f"LowerLeg_{_s}": f"UpperLeg_{_s}",
            f"Foot_{_s}": f"LowerLeg_{_s}",
            f"Toe_{_s}": f"Foot_{_s}",
        }
    )


def v3(x, y, z) -> Vector:
    return Vector((x, y, z))


def mirror(v: Vector) -> Vector:
    return Vector((-v.x, v.y, v.z))


def reset_scene() -> None:
    """Empty the current file deterministically (factory startup is assumed)."""
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    for coll in (
        bpy.data.meshes,
        bpy.data.armatures,
        bpy.data.materials,
        bpy.data.actions,
        bpy.data.cameras,
        bpy.data.lights,
        bpy.data.images,
        bpy.data.curves,
    ):
        for item in list(coll):
            coll.remove(item)
    for c in list(bpy.data.collections):
        bpy.data.collections.remove(c)
    scene = bpy.context.scene
    scene.render.fps = FPS
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0


def link(ob, collection=None):
    (collection or bpy.context.scene.collection).objects.link(ob)
    return ob


def mesh_object(name: str, bm: bmesh.types.BMesh, collection=None):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    return link(ob, collection)


def tri_count(ob) -> int:
    return sum(len(p.vertices) - 2 for p in ob.data.polygons)


def set_active(ob):
    for o in bpy.context.scene.objects:
        o.select_set(False)
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob


def apply_modifiers(ob):
    """Apply every modifier of a mesh object (evaluated copy -> data)."""
    dg = bpy.context.evaluated_depsgraph_get()
    ev = ob.evaluated_get(dg)
    me = bpy.data.meshes.new_from_object(ev, preserve_all_data_layers=True, depsgraph=dg)
    old = ob.data
    ob.modifiers.clear()
    ob.data = me
    me.name = old.name
    bpy.data.meshes.remove(old)


def material_index(ob, name: str) -> int:
    """Index of material `name` in the object's slots (appended if missing)."""
    mats = ob.data.materials
    for i, m in enumerate(mats):
        if m and m.name == name:
            return i
    mats.append(bpy.data.materials[name])
    return len(mats) - 1


def smoothstep(e0: float, e1: float, x: float) -> float:
    if e0 == e1:
        return 0.0 if x < e0 else 1.0
    t = max(0.0, min(1.0, (x - e0) / (e1 - e0)))
    return t * t * (3.0 - 2.0 * t)


def lerp(a, b, t):
    return a + (b - a) * t


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def deg(x: float) -> float:
    return math.radians(x)


def rot_axis(axis: Vector, angle: float) -> Matrix:
    return Matrix.Rotation(angle, 4, axis.normalized())


def frame_matrix(head: Vector, y_dir: Vector, z_hint: Vector) -> Matrix:
    """Bone matrix with Y along y_dir and Z as close to z_hint as possible."""
    y = y_dir.normalized()
    x = y.cross(z_hint)
    if x.length < 1e-6:
        x = y.cross(Vector((0, 0, 1)) if abs(y.z) < 0.9 else Vector((0, -1, 0)))
    x.normalize()
    z = x.cross(y).normalized()
    m = Matrix.Identity(4)
    m.col[0][:3] = x
    m.col[1][:3] = y
    m.col[2][:3] = z
    m.col[3][:3] = head
    return m


def ensure_dir(p: Path) -> Path:
    os.makedirs(p, exist_ok=True)
    return p
