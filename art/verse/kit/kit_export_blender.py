"""Blender side of `art/verse/kit/kit_export.py`: export many kit pieces in one Blender run.

    argv: --names NAMES.json --out DIR --result FILE

Same `fbx-ue/1` export as `scripts/verse/_export_unreal_entry.py piece` (it calls
the same `lib.unreal_export.export_static_mesh`), with one extra step the kit
needs for Unreal: before a piece exports, the modifiers of every mesh in its
master (and in the masters it instances) are applied and faces whose area is
zero after the bevels are removed, so the zero-area check of the exporter
passes on hard-surface pieces (art-pipeline 6.1 "Mesh hygiene").
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

from kit import cap_fit

MODULES = ("kit.architecture", "kit.props.command", "kit.props.industrial")
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
            results.append(entry)
            print(f"[verse] exported {name}: {entry['triangles']} tris", flush=True)
        except Exception as error:  # noqa: BLE001 - report every piece, fail none silently
            failed.append({"name": name, "error": repr(error)[:400]})
            print(f"[verse] FAILED {name}: {error!r}", flush=True)
    unreal_export.write_result(options.result, results)
    options.result.with_suffix(".failed.json").write_text(json.dumps(failed, indent=1))


main(sys.argv[1:])
