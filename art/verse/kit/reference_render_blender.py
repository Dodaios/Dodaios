"""Render today's look of a deck from the Unreal reference cameras (WP12 evidence), in Blender.

    blender -b --python reference_render_blender.py -- <deck> --views views.json --out DIR

Builds the deck the way the three.js cook does, then renders every shot of
`views.json` (written by `Verse.Visual.Decks`) whose `deck` matches, from the
same spot: the Unreal location and forward vector are mapped back to Blender
space (`lib.ue_space`, art-pipeline 4.1). Eye-level shots show the ceilings,
as today's first-person view does; overview shots keep today's plate cutaway.
Cycles on the CPU, low samples: these are reference frames, not plates.
"""

from __future__ import annotations

import argparse
import importlib
import json
import math
import sys
from pathlib import Path

import bpy
from lib import ue_space
from mathutils import Vector

KIT_MODULES = ("kit.architecture", "kit.props.command", "kit.props.industrial")
WIDTH, HEIGHT = 960, 540
SAMPLES = 24


def _show_ceilings(show: bool, hidden: list[bpy.types.Object]) -> None:
    for obj in hidden:
        obj.visible_camera = show


def _camera(hfov_deg: float) -> bpy.types.Object:
    data = bpy.data.cameras.new("WP12_RefCam")
    data.sensor_fit = "HORIZONTAL"
    data.angle = math.radians(hfov_deg)
    data.clip_start = 0.05
    data.clip_end = 2000.0
    cam = bpy.data.objects.new("WP12_RefCam", data)
    bpy.context.scene.collection.objects.link(cam)
    bpy.context.scene.camera = cam
    return cam


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="reference_render_blender")
    parser.add_argument("deck")
    parser.add_argument("--views", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    options = parser.parse_args(argv)
    views = json.loads(options.views.read_text(encoding="utf-8"))
    shots = [v for v in views if v["deck"] == options.deck]
    if not shots:
        print(f"[verse] {options.deck}: no reference shots in {options.views}")
        return
    for name in KIT_MODULES:
        module = importlib.import_module(name)
        if callable(getattr(module, "load_all", None)):
            module.load_all()
    importlib.import_module(f"decks.{options.deck}.build").build()

    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.samples = SAMPLES
    scene.cycles.use_denoising = True
    scene.render.resolution_x = WIDTH
    scene.render.resolution_y = HEIGHT
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    # Ceilings and fixtures are hidden from today's plate camera, not from an eye in the room.
    hidden = [
        o for o in scene.objects
        if o.type == "MESH" and not o.visible_camera and not o.hide_render and not o.get("ucx")
    ]
    options.out.mkdir(parents=True, exist_ok=True)
    for shot in shots:
        cam = _camera(float(shot.get("hfov_deg", 85.0)))
        cam.location = Vector(ue_space.location_from_ue(shot["location_cm"]))
        fx, fy, fz = shot["forward"]
        forward = Vector((fx, -fy, fz)).normalized()
        cam.rotation_euler = forward.to_track_quat("-Z", "Y").to_euler()
        _show_ceilings(not shot["name"].endswith("_overview"), hidden)
        scene.render.filepath = str(options.out / f"{shot['name']}.png")
        bpy.ops.render.render(write_still=True)
        print(f"[verse] rendered {shot['name']}", flush=True)
        bpy.data.objects.remove(cam, do_unlink=True)
    _show_ceilings(False, hidden)


main(sys.argv[1:])
