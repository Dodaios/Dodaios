"""Bake `T_Verse_Grade_LUT_M` and the AgX chart reference with Blender itself (bpy).

    python scripts/verse/blender.py run --no-lock art/verse/weapons/look/_blender_lut.py \
        --out art/verse/.cache/unreal/look

Both images are float images in scene-linear Rec.709 that Blender saves
through the scene's colour management (view transform AgX, look None,
display sRGB, exposure 0, gamma 1), so their 8-bit pixels are exactly what a
Blender render of the same scene-linear values shows.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy

from weapons.look import agx


def _scene():
    scene = bpy.context.scene
    vs = scene.view_settings
    vs.view_transform = "AgX"
    vs.look = "None"
    vs.exposure = 0.0
    vs.gamma = 1.0
    scene.display_settings.display_device = "sRGB"
    settings = scene.render.image_settings
    settings.file_format = "PNG"
    settings.color_mode = "RGB"
    settings.color_depth = "8"
    return scene


def _save(name: str, width: int, height: int, values: list[tuple], path: Path) -> None:
    """`values` row-major from the top row; Blender images store rows bottom-up."""
    image = bpy.data.images.new(name, width, height, alpha=False, float_buffer=True)
    image.colorspace_settings.name = "Linear Rec.709"
    pixels = [0.0] * (width * height * 4)
    for row in range(height):
        for col in range(width):
            r, g, b = values[row * width + col]
            i = ((height - 1 - row) * width + col) * 4
            pixels[i : i + 4] = (r, g, b, 1.0)
    image.pixels.foreach_set(pixels)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save_render(str(path), scene=bpy.context.scene)


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="_blender_lut")
    parser.add_argument("--out", type=Path, required=True)
    options = parser.parse_args(argv)
    _scene()
    lut = []
    for y in range(agx.STRIP_HEIGHT):
        for x in range(agx.STRIP_WIDTH):
            r, g, b = agx.strip_texel(x, y)
            lut.append((agx.lattice_value(r), agx.lattice_value(g), agx.lattice_value(b)))
    lut_path = options.out / "T_Verse_Grade_LUT_M.png"
    _save("T_Verse_Grade_LUT_M", agx.STRIP_WIDTH, agx.STRIP_HEIGHT, lut, lut_path)
    chart = agx.chart_linear()
    chart_path = options.out / "chart_agx_reference.png"
    _save("ChartReference", len(chart), 1, chart, chart_path)
    meta = {
        "blender": bpy.app.version_string,
        "view_transform": "AgX",
        "look": "None",
        "lut": lut_path.name,
        "chart": chart_path.name,
        "chart_linear": chart,
        "size": agx.SIZE,
        "ev_min": agx.EV_MIN,
        "ev_max": agx.EV_MAX,
    }
    (options.out / "look_bake.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    print(f"[verse] baked {lut_path} and {chart_path}")


main(sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:])
