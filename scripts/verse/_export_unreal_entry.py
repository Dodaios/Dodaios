"""Blender side of scripts/verse/export_unreal.py (run by scripts/verse/blender.py).

argv: <mode> [options]; modes:
    piece <SM_Name> --out DIR --result FILE [--module M ...]
    calib --out DIR --result FILE

Writes FBX files into DIR and a JSON summary into FILE that the host turns
into import records. Exceptions propagate, so Blender exits with 1.
"""

from __future__ import annotations

import argparse
import importlib
import inspect
import sys
from pathlib import Path

import bpy
from lib import kit, unreal_export

#: Kit modules that register pieces when imported (kit/README.md).
DEFAULT_MODULES = (
    "kit.architecture",
    "kit.props.command",
    "kit.props.industrial",
    "kit.calib",
)


def _load(modules: list[str]) -> None:
    for name in modules:
        module = importlib.import_module(name)
        loader = getattr(module, "load_all", None)
        if callable(loader):
            loader()


def _reset() -> None:
    """Empty the factory scene (Blender runs with --factory-startup)."""
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.context.scene.unit_settings.system = "METRIC"
    bpy.context.scene.unit_settings.scale_length = 1.0


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="_export_unreal_entry")
    sub = parser.add_subparsers(dest="mode", required=True)
    piece = sub.add_parser("piece")
    piece.add_argument("name")
    piece.add_argument("--module", action="append", default=[])
    calib = sub.add_parser("calib")
    for p in (piece, calib):
        p.add_argument("--out", type=Path, required=True)
        p.add_argument("--result", type=Path, required=True)
    options = parser.parse_args(argv)

    _reset()
    results = []
    if options.mode == "piece":
        _load(options.module or list(DEFAULT_MODULES))
        results.append(_export_piece(options.name, options.out))
    else:
        from kit import calib as calib_kit

        _load(["kit.calib"])
        results.append(_export_piece("SM_Calib_Axes", options.out))
        rig = unreal_export.build_rig("SK_Calib_Rig", calib_kit.RIG_BONES, options.out)
        entry = rig.as_dict()
        entry["source"] = _source_of(calib_kit.build_rig_marker, {})
        results.append(entry)
    unreal_export.write_result(options.result, results)
    for result in results:
        print(f"[verse] exported {result['name']}: {result['triangles']} tris")


def _source_of(fn, args: dict) -> dict:
    path = Path(inspect.getsourcefile(fn)).resolve()
    return {
        "builder": path.relative_to(unreal_export.REPO_ROOT).as_posix(),
        "function": fn.__name__,
        "module": fn.__module__,
        "args": {k: v for k, v in args.items() if isinstance(v, (int, float, str, bool))},
    }


def _export_piece(name: str, out: Path) -> dict:
    pdef = kit.registry().get(name)
    if pdef is None:
        raise KeyError(f"unknown kit piece {name!r}")
    master = kit.build_master(name)
    result = unreal_export.export_static_mesh(name, master, out, root_name=kit.MASTER_ROOT)
    entry = result.as_dict()
    entry["source"] = _source_of(pdef.builder, pdef.params)
    entry["nav"] = pdef.nav
    return entry


main(sys.argv[1:])
