"""Blender side of `scripts/verse/export_unreal.py weapons` (WP14; run by scripts/verse/blender.py).

argv: --out DIR --result FILE [--only ASSET ...]

Builds the weapons, gadgets and weapon VFX meshes of `weapons.specs`,
writes their FBX files into DIR and a JSON summary into FILE that the host
turns into import records. Exceptions propagate, so Blender exits with 1.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import bpy
from lib import unreal_export


def _reset() -> None:
    """Empty the factory scene (Blender runs with --factory-startup)."""
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.context.scene.unit_settings.system = "METRIC"
    bpy.context.scene.unit_settings.scale_length = 1.0


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="weapons._export_entry")
    parser.add_argument("--only", action="append", default=[])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    options = parser.parse_args(argv)

    from weapons import export as weapon_export

    _reset()
    results = list(weapon_export.export_all(options.out, options.only))
    unreal_export.write_result(options.result, results)
    for result in results:
        print(f"[verse] exported {result['name']}: {result['triangles']} tris")


main(sys.argv[1:])
