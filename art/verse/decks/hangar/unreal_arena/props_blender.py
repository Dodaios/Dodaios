"""Blender side of `props.py`: glTF in, one `fbx-ue/1` FBX per mesh out.

    argv: --jobs JOBS.json --out DIR --result FILE

Per job: import the glTF into an empty scene, drop degenerate faces (scans
carry a few), rename each material to `M_<Mesh>_<n>` and note the image files
it samples (`*_diff_*`, `*_arm_*`, `*_nor_gl_*`), then export the whole file
(or each listed piece) with `lib.unreal_export.export_static_mesh`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bmesh
import bpy
from lib import unreal_export
from mathutils import Vector

MIN_FACE_AREA = 1e-9


def _args() -> argparse.Namespace:
    argv = sys.argv[1:]
    parser = argparse.ArgumentParser()
    parser.add_argument("--jobs", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--result", required=True)
    return parser.parse_args(argv)


def _clear() -> None:
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for block in (bpy.data.meshes, bpy.data.materials, bpy.data.images, bpy.data.collections):
        for item in list(block):
            if block is bpy.data.collections and item.name == unreal_export.EXPORT_COLLECTION:
                continue
            block.remove(item)


def _clean(obj: bpy.types.Object) -> None:
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.dissolve_degenerate(bm, dist=1e-6, edges=bm.edges[:])
    bad = [f for f in bm.faces if f.calc_area() < MIN_FACE_AREA]
    if bad:
        bmesh.ops.delete(bm, geom=bad, context="FACES")
    bm.to_mesh(obj.data)
    bm.free()


def _maps(material: bpy.types.Material) -> dict[str, str]:
    found: dict[str, str] = {}
    if not material or not material.use_nodes:
        return found
    for node in material.node_tree.nodes:
        if node.type != "TEX_IMAGE" or not node.image:
            continue
        path = bpy.path.abspath(node.image.filepath)
        stem = Path(path).stem.lower()
        for kind in ("nor_gl", "arm", "diff"):
            if f"_{kind}_" in stem or stem.endswith(f"_{kind}"):
                found.setdefault(kind, path)
    return found


def _bounds(objects: list[bpy.types.Object]) -> tuple[Vector, Vector]:
    lo = Vector((1e9, 1e9, 1e9))
    hi = Vector((-1e9, -1e9, -1e9))
    for obj in objects:
        for corner in obj.bound_box:
            p = obj.matrix_world @ Vector(corner)
            lo = Vector(map(min, lo, p))
            hi = Vector(map(max, hi, p))
    return lo, hi


def export_job(job: dict, out: Path) -> dict:
    _clear()
    bpy.ops.import_scene.gltf(filepath=job["gltf"])
    bpy.context.view_layer.update()
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    name = job["name"]
    materials: list[dict] = []
    fallbacks: dict[str, str] = {}
    renamed: dict[str, str] = {}
    for obj in meshes:
        _clean(obj)
        for slot in obj.material_slots:
            mat = slot.material
            if mat is None or mat.name in renamed.values():
                continue
            if mat.name not in renamed:
                new = f"M_{name[3:]}_{len(renamed) + 1}"
                maps = _maps(mat)
                renamed[mat.name] = new
                original = mat.name
                mat.name = new
                if {"diff", "arm", "nor_gl"} <= set(maps):
                    materials.append({"slot": new, "maps": maps})
                else:
                    fallbacks[new] = original
                    print(f"[verse] {name}: material {new} ({original}) has no texture set")
    pieces = job.get("pieces") or {"": []}
    scale = float(job.get("scale", 1.0))
    results = []
    for suffix, object_names in pieces.items():
        picked = [o for o in meshes if not object_names or strip(o.name) in object_names]
        if not picked:
            raise RuntimeError(f"{name}: no objects named {object_names}")
        col = bpy.data.collections.new(f"PIECE_{name}{suffix}")
        for obj in picked:
            col.objects.link(obj)
        # Origin at the bottom centre: the piece is instanced with its foot point as offset.
        lo, hi = _bounds(picked)
        col.instance_offset = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))
        outer = bpy.data.collections.new(f"OUTER_{name}{suffix}")
        holder = bpy.data.objects.new(f"HOLD_{name}{suffix}", None)
        holder.instance_type = "COLLECTION"
        holder.instance_collection = col
        holder.scale = (scale, scale, scale)
        outer.objects.link(holder)
        bpy.context.scene.collection.children.link(outer)
        bpy.context.view_layer.update()
        mesh_name = f"{name}_{suffix}" if suffix else name
        result = unreal_export.export_static_mesh(mesh_name, outer, out)
        bpy.context.scene.collection.children.unlink(outer)
        results.append(result.as_dict())
        print(f"[verse] exported {mesh_name}: {result.triangles} tris")
    return {
        "asset": job["asset"],
        "materials": materials,
        "fallbacks": fallbacks,
        "meshes": results,
    }


def strip(name: str) -> str:
    return unreal_export.strip_suffix(name)


def main() -> None:
    args = _args()
    jobs = json.loads(Path(args.jobs).read_text(encoding="utf-8"))
    out = Path(args.out)
    done = [export_job(job, out) for job in jobs]
    Path(args.result).write_text(json.dumps(done, indent=1), encoding="utf-8")


main()
