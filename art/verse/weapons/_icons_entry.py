"""Blender side of `scripts/verse/hud_icons.py` (run by scripts/verse/blender.py).

argv: --out DIR

Builds every weapon of `weapons.build.BUILDERS` and renders a side
view of each (orthographic, from -Y, muzzle to +X, Z up) in Workbench, two
passes per item on a transparent film:

- `<item>_mask.png`: flat white, the antialiased silhouette;
- `<item>_shade.png`: studio light with cavity, the panel detail.

The host script turns both into the HUD icons.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import bpy
from mathutils import Vector

#: HUD item id -> builder asset.
ITEMS = {
    "graveline": "SK_Weapon_Graveline",
    "tallow": "SK_Weapon_Tallow",
    "hookbill": "SK_Weapon_Hookbill",
    "skitter": "SK_Weapon_Skitter",
    "longsight": "SK_Weapon_Longsight",
}

WIDTH = 2048


def _reset() -> None:
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)


def _scene() -> bpy.types.Scene:
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.film_transparent = True
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.display.render_aa = "32"
    scene.view_settings.view_transform = "Standard"
    shading = scene.display.shading
    shading.color_type = "SINGLE"
    shading.single_color = (1.0, 1.0, 1.0)
    shading.show_object_outline = False
    shading.show_specular_highlight = False
    return scene


def _render(scene, path: Path, studio: bool) -> None:
    shading = scene.display.shading
    shading.light = "STUDIO" if studio else "FLAT"
    shading.show_cavity = studio
    if studio:
        shading.cavity_type = "BOTH"
        shading.cavity_ridge_factor = 1.0
        shading.cavity_valley_factor = 2.0
        shading.curvature_ridge_factor = 1.0
        shading.curvature_valley_factor = 1.5
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="weapons._icons_entry")
    parser.add_argument("--out", type=Path, required=True)
    options = parser.parse_args(argv)
    options.out.mkdir(parents=True, exist_ok=True)

    from weapons import build

    scene = _scene()
    for item, asset in ITEMS.items():
        _reset()
        builder = build.Builder(asset)
        build.BUILDERS[asset](builder)
        mesh, _groups = builder.mesh()
        obj = bpy.data.objects.new(asset, mesh)
        scene.collection.objects.link(obj)
        bpy.context.view_layer.update()

        corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
        lo = Vector(tuple(min(c[i] for c in corners) for i in range(3)))
        hi = Vector(tuple(max(c[i] for c in corners) for i in range(3)))
        size_x = hi.x - lo.x
        size_z = hi.z - lo.z
        margin = 1.04
        scene.render.resolution_x = WIDTH
        scene.render.resolution_y = max(16, int(WIDTH * size_z / size_x))
        cam_data = bpy.data.cameras.new(f"{item}_cam")
        cam_data.type = "ORTHO"
        cam_data.ortho_scale = max(size_x, size_z) * margin
        cam = bpy.data.objects.new(f"{item}_cam", cam_data)
        cam.location = ((lo.x + hi.x) / 2, lo.y - 2.0, (lo.z + hi.z) / 2)
        cam.rotation_euler = (1.5708, 0.0, 0.0)
        scene.collection.objects.link(cam)
        scene.camera = cam

        _render(scene, options.out / f"{item}_mask.png", studio=False)
        _render(scene, options.out / f"{item}_shade.png", studio=True)
        print(f"[icons] {item}: {size_x:.3f} x {size_z:.3f} m")


main(sys.argv[1:])
