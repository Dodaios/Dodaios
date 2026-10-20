"""Kit sheet: every architecture piece in a labelled lineup, lit and seen
through the fixed plate camera.

    python scripts/verse/blender.py run art/verse/lookdev/kit_sheet.py \
        --out art/verse/.cache/lookdev/kit_sheet.png --ppm 32 --samples 96

Pieces are packed left to right in rows (grouped by module), each with its
name painted on the deck in front of it. A camera-invisible ceiling with a
light grid lights the whole sheet; the deck is the production black floor.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import bpy
from kit.architecture import (  # noqa: F401 - registers the pieces
    ceiling,
    corridor,
    doors,
    floors,
    hull,
    pit,
    structure,
    walls,
    windows,
)
from lib import kit
from lib import scene as deck

ROW_WIDTH = 44.0
GAP = 1.6
SKIP = {"SM_CeilingLight_Grid_480"}  # camera-invisible by design
BELOW_DECK = ("SM_Hull", "SM_CrewPit", "SM_PitWall", "SM_Stairs", "SM_Grating", "SM_Catwalk")
GROUPS = (
    "SM_Wall_",
    "SM_WallLight_",
    "SM_Corridor",
    "SM_Bulkhead",
    "SM_BlastDoor",
    "SM_Turbolift",
    "SM_Viewport",
    "SM_PitWall",
    "SM_Console",
    "SM_Seat",
    "SM_CrewPit",
    "SM_CommandWalkway",
    "SM_Stairs",
    "SM_Railing",
    "SM_Catwalk",
    "SM_Pillar",
    "SM_Grating",
    "SM_Hull",
)


def _group_index(name: str) -> int:
    for i, prefix in enumerate(GROUPS):
        if name.startswith(prefix):
            return i
    return len(GROUPS)


def label_material() -> bpy.types.Material:
    mat = bpy.data.materials.get("LOOKDEV_Label") or bpy.data.materials.new("LOOKDEV_Label")
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (0.6, 0.6, 0.58, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.6
    return mat


def label(text: str, x: float, y: float) -> None:
    curve = bpy.data.curves.new(f"LBL_{text}", "FONT")
    curve.body = text.removeprefix("SM_")
    curve.size = 0.28
    curve.align_x = "CENTER"
    obj = bpy.data.objects.new(f"LBL_{text}", curve)
    obj.location = (x, y, 0.002)
    obj.data.materials.append(label_material())
    kit.link(obj)


def layout() -> tuple[float, float, float, float]:
    names = sorted((n for n in kit.registry() if n not in SKIP), key=lambda n: (_group_index(n), n))
    x, y = 0.0, 0.0
    row_depth = 0.0
    last_group = None
    xs, ys = [0.0], [0.0]
    with kit.into(deck.collection("Architecture")):
        for name in names:
            dims = kit.registry()[name].dims or (2.4, 2.4, 2.4)
            w, d, h = dims[0], max(dims[1], 1.2), dims[2]
            group = _group_index(name)
            if x > 0 and (x + w > ROW_WIDTH or (group != last_group and x > ROW_WIDTH * 0.6)):
                x = 0.0
                y -= row_depth + 2.2
                row_depth = 0.0
            last_group = group
            kit.place(name, (x + w / 2, y, 0.0), 0.0, id=f"sheet_{name[3:]}")
            tile_z = -2.5 if name.startswith(BELOW_DECK) else -0.002
            floors.fill_rect(
                f"FLR_{name}",
                x - GAP / 2,
                y - d / 2 - 1.5,
                x + w + GAP / 2,
                y + d / 2 + 0.6,
                tile_z,
            )
            label(name, x + w / 2, y - d / 2 - 0.9)
            x += w + GAP
            row_depth = max(row_depth, d + 1.2 + 0.6 * h)
            xs.append(x)
            ys.append(y - row_depth)
    return min(xs) - 1.5, min(ys) - 1.5, max(xs) + 1.0, max(ys) + 3.5


def build() -> tuple[bpy.types.Scene, deck.Bounds]:
    provisional = deck.Bounds(0.0, -40.0, ROW_WIDTH, 4.0, 0.0, 4.5)
    scene = deck.new_deck("lookdev_kit", provisional, name="Lookdev kit sheet")
    x0, y0, x1, y1 = layout()
    with kit.into(deck.collection("Ceiling")):
        ceiling.fill_ceiling("sheet", (x0, x1), (y0, y1), z=5.2, pitch=(2.4, 2.4), size=(1.2, 0.6))
    return scene, deck.Bounds(x0, y0, x1, y1, -1.0, 4.5)


def report() -> None:
    """Print each piece with its nominal size, sockets and occluders."""
    for name, pdef in sorted(kit.registry().items()):
        kinds = sorted({s.kind for s in pdef.sockets})
        dims = "x".join(f"{d:.2f}" for d in pdef.dims) if pdef.dims else "?"
        sockets = ",".join(kinds) or "-"
        print(f"[kit] {name:34s} {dims:16s} sockets={sockets} ucx={len(pdef.occluders)}")


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--ppm", type=int, default=32)
    parser.add_argument("--samples", type=int, default=96)
    parser.add_argument("--build-only", action="store_true", help="build and validate, no render")
    args = parser.parse_args(argv)
    scene, bounds = build()
    report()
    if args.build_only:
        bpy.ops.wm.save_as_mainfile(filepath=str(args.out.with_suffix(".blend").resolve()))
        return
    deck.apply_frame(scene, scene.camera, deck.frame_for(bounds, args.ppm, margin=0.0))
    scene.cycles.samples = args.samples
    scene.cycles.adaptive_threshold = 0.03
    args.out.parent.mkdir(parents=True, exist_ok=True)
    scene.render.filepath = str(args.out.resolve())
    bpy.ops.render.render(write_still=True)
    print(f"[lookdev] wrote {args.out} {scene.render.resolution_x}x{scene.render.resolution_y}")


if __name__ == "__main__":
    main(sys.argv[1:])
