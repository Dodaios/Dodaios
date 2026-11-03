"""Blender side of `art/verse/kit/kit_export.py`: export many kit pieces in one Blender run.

    argv: --names NAMES.json --out DIR --result FILE

Same `fbx-ue/1` export as `scripts/verse/_export_unreal_entry.py piece` (it calls
the same `lib.unreal_export.export_static_mesh`), with one extra step the kit
needs for Unreal: before a piece exports, the modifiers of every mesh in its
master (and in the masters it instances) are applied and faces whose area is
zero after the bevels are removed, so the zero-area check of the exporter
passes on hard-surface pieces (art-pipeline 6.1 "Mesh hygiene").

Two more WP12 steps run per piece: the authored collision of `kit/collision.py`
becomes `UECOL_` objects in the master (stairs, open doors), and the builders'
stand-in materials get their Unreal names (`kit/export_materials.py`); each result
also carries the tint of every material slot for `kit/mi_recipes.py`.
"""

from __future__ import annotations

import argparse
import importlib
import inspect
import json
import sys
from pathlib import Path

import bmesh
import bpy
from lib import kit, unreal_export
from mathutils import Matrix, Vector

from kit import cap_fit, collision, export_materials

MODULES = ("kit.architecture", "kit.props.command", "kit.props.industrial", "kit.props.space")
MIN_FACE_AREA = 1e-7  # m2; well below any visible face, above the exporter check after scaling


def _clean_collection(collection, done: set[str]) -> None:
    if collection.name in done:
        return
    done.add(collection.name)
    scene_root = bpy.context.scene.collection
    linked = collection.name not in scene_root.children
    if linked:
        scene_root.children.link(collection)
    try:
        bpy.context.view_layer.update()
        depsgraph = bpy.context.evaluated_depsgraph_get()
        nested = []
        for obj in list(collection.all_objects):
            if obj.instance_type == "COLLECTION" and obj.instance_collection is not None:
                nested.append(obj.instance_collection)
            if obj.type != "MESH":
                continue
            mesh = bpy.data.meshes.new_from_object(
                obj.evaluated_get(depsgraph), preserve_all_data_layers=True, depsgraph=depsgraph
            )
            bm = bmesh.new()
            bm.from_mesh(mesh)
            bad = [f for f in bm.faces if f.calc_area() < MIN_FACE_AREA]
            if bad:
                bmesh.ops.delete(bm, geom=bad, context="FACES")
            bm.to_mesh(mesh)
            bm.free()
            materials = [slot.material for slot in obj.material_slots]
            obj.modifiers.clear()
            obj.data = mesh
            for index, material in enumerate(materials):
                if index < len(obj.material_slots):
                    obj.material_slots[index].material = material
    finally:
        if linked:
            scene_root.children.unlink(collection)
    for child in nested:
        _clean_collection(child, done)


def _bounds(collection) -> tuple[list[float], list[float]]:
    """Piece-space box of the render meshes of a (cleaned) master, Blender metres."""
    lo = [float("inf")] * 3
    hi = [float("-inf")] * 3
    for obj, matrix in unreal_export._walk(collection, Matrix.Identity(4)):  # noqa: SLF001
        name = unreal_export.strip_suffix(obj.name)
        if obj.type != "MESH" or name.startswith(("UECOL_", "UCX_")):
            continue
        if unreal_export._is_ghost(obj):  # noqa: SLF001
            continue
        for vertex in obj.data.vertices:
            point = matrix @ vertex.co
            for axis in range(3):
                lo[axis] = min(lo[axis], point[axis])
                hi[axis] = max(hi[axis], point[axis])
    return lo, hi


def _collision_mesh(name: str, points) -> bpy.types.Mesh:
    bm = bmesh.new()
    for point in points:
        bm.verts.new(Vector(point))
    bmesh.ops.convex_hull(bm, input=list(bm.verts))
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    return mesh


def _add_collision(name: str, master) -> int:
    """Link the authored primitives of `kit/collision.py` into the master; returns their count."""
    for obj in list(master.objects):
        if obj.name.startswith("UECOL_"):
            bpy.data.objects.remove(obj)
    lo, hi = _bounds(master)
    prims = collision.recipe(name, lo, hi)
    if not prims:
        return 0
    for nn, prim in enumerate(prims):
        if prim[0] == "box":
            (x0, y0, z0), (x1, y1, z1) = prim[1], prim[2]
            points = [(x, y, z) for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)]
            kind = "Box"
        else:  # "obox": the eight corners of an oriented box, imported as UBX_
            points = prim[1]
            kind = "Box"
        obj_name = f"UECOL_{kind}_{nn:02d}"
        master.objects.link(bpy.data.objects.new(obj_name, _collision_mesh(obj_name, points)))
    return len(prims)


def _source_of(fn, args: dict) -> dict:
    path = Path(inspect.getsourcefile(fn)).resolve()
    return {
        "builder": path.relative_to(unreal_export.REPO_ROOT).as_posix(),
        "function": fn.__name__,
        "module": fn.__module__,
        "args": {k: v for k, v in args.items() if isinstance(v, (int, float, str, bool))},
    }


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="kit_export_blender")
    parser.add_argument("--names", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--deck", help="build this deck first (it registers its own variants)")
    options = parser.parse_args(argv)
    names = json.loads(options.names.read_text(encoding="utf-8"))
    for module_name in MODULES:
        module = importlib.import_module(module_name)
        if callable(getattr(module, "load_all", None)):
            module.load_all()
    if options.deck:
        importlib.import_module(f"decks.{options.deck}.build").build()
    registry = kit.registry()
    done: set[str] = set()
    results, failed = [], []
    for name in names:
        try:
            pdef = registry[name]
            master = kit.build_master(name)
            _clean_collection(master, done)
            export_materials.rename_stand_ins()
            authored = _add_collision(name, master)
            source = _source_of(pdef.builder, pdef.params)
            result = cap_fit.export(
                name,
                master,
                options.out,
                cap=cap_fit.cap_for(source["builder"]),
                root_name=kit.MASTER_ROOT,
            )
            entry = result.as_dict()
            entry["source"] = source
            entry["nav"] = pdef.nav
            entry["authored_collision"] = authored
            for obj in [o for o in master.objects if o.name.startswith("UECOL_")]:
                bpy.data.objects.remove(obj)  # a piece that instances this master keeps its own
            entry["material_tints"] = export_materials.tints(
                bpy.data.materials.get(slot["slot"]) for slot in entry["material_slots"]
            )
            results.append(entry)
            print(f"[verse] exported {name}: {entry['triangles']} tris", flush=True)
        except Exception as error:  # noqa: BLE001 - report every piece, fail none silently
            failed.append({"name": name, "error": repr(error)[:400]})
            print(f"[verse] FAILED {name}: {error!r}", flush=True)
    unreal_export.write_result(options.result, results)
    options.result.with_suffix(".failed.json").write_text(json.dumps(failed, indent=1))


main(sys.argv[1:])
