"""Blender-side eye-level view job: build a deck and render perspective views
with every ceiling and ceiling ghost visible, as the realtime export sees it.

Run by scripts/verse/eyeview.py through scripts/verse/blender.py:
    _eyeview_entry.py <deck_id> <out_dir> <views.json> [--samples N] [--size WxH]

views.json: a list of views. Each view is either
    {"name", "rooms": true}                  every room: 4 headings per point
    {"name", "rig": [x, z, yaw_deg, floor]}  the shoulder rig's camera behind a
                                             commander at three.js (x, floor, z)
                                             facing yaw (0 = +Z, 90 = +X)
    {"name", "eye": [x, y, z, yaw_deg, pitch_deg]}  a free camera (three.js)
Output: `<name>.png` per view and `views.json` with what each one shows.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import bpy
from _cook_entry import load_builder
from lib import cook, realtime, scene
from mathutils import Euler, Vector

HFOV_DEG = 72.0
# The realtime view's shoulder rig (SHOULDER in engine/realtime/shoulderRig.ts).
RIG_DISTANCE = 2.4
RIG_SIDE = -0.47
RIG_PIVOT = 1.74
RIG_PITCH_DEG = 7.0
ROOM_EYE_M = 1.9  # camera height above the floor for the room views
ROOM_STEP_M = 22.0  # long rooms get a point every this many metres
HEADINGS = (("n", 180.0), ("e", 90.0), ("s", 0.0), ("w", 270.0))


def _realtime_visibility() -> None:
    """Show what the realtime export shows: ceilings, ghosts and fixtures as
    normal geometry (ghosts cast shadows), mirror-only emitters lit; helper
    collections stay hidden."""
    for name in ("Occluders", "Sockets", "NavOnly"):
        scene.collection(name).hide_render = True
    for obj in cook._camera_hidden_objects():
        obj.visible_camera = True
        if obj.get("ceiling_ghost"):
            obj.visible_shadow = True
            obj.visible_diffuse = True
            obj.visible_glossy = True
    for obj in scene.objects_in("Lights"):
        if obj.type == "MESH":
            obj.visible_camera = True
    realtime.light_glossy_emitters(bpy.data.materials)


def _camera(bpy_scene) -> bpy.types.Object:
    data = bpy.data.cameras.new("CAM_eye")
    data.lens_unit = "FOV"
    data.sensor_fit = "HORIZONTAL"
    data.angle = math.radians(HFOV_DEG)
    data.clip_start = 0.05
    data.clip_end = 400.0
    camera = bpy.data.objects.new("CAM_eye", data)
    bpy_scene.collection.objects.link(camera)
    bpy_scene.camera = camera
    return camera


def _aim(camera: bpy.types.Object, position: Vector, yaw_deg: float, pitch_deg: float) -> None:
    """Blender camera at `position` looking along three.js heading `yaw_deg`
    (0 = +Z, 90 = +X), `pitch_deg` down."""
    camera.location = position
    camera.rotation_euler = Euler(
        (math.radians(90.0 - pitch_deg), 0.0, math.radians(yaw_deg) - math.pi)
    )


def _rig_position(x: float, z: float, yaw_deg: float, floor: float) -> Vector:
    yaw, pitch = math.radians(yaw_deg), math.radians(RIG_PITCH_DEG)
    fx, fz = math.sin(yaw), math.cos(yaw)
    rx, rz = -math.cos(yaw), math.sin(yaw)
    px, py, pz = x + rx * RIG_SIDE, floor + RIG_PIVOT, z + rz * RIG_SIDE
    dx, dy, dz = fx * math.cos(pitch), -math.sin(pitch), fz * math.cos(pitch)
    cx, cy, cz = px - dx * RIG_DISTANCE, py - dy * RIG_DISTANCE, pz - dz * RIG_DISTANCE
    return Vector((cx, -cz, cy))


def _room_points(room: cook.Room) -> list[tuple[float, float]]:
    """The room's inside centre, plus points along its long axis for long rooms."""
    xs = [p[0] for p in room.polygon]
    ys = [p[1] for p in room.polygon]
    points = [room.centre]
    span_x, span_y = max(xs) - min(xs), max(ys) - min(ys)
    steps = int(max(span_x, span_y) // ROOM_STEP_M)
    for k in range(steps):
        t = (k + 1) / (steps + 1)
        if span_x >= span_y:
            p = (min(xs) + span_x * t, room.centre[1])
        else:
            p = (room.centre[0], min(ys) + span_y * t)
        if cook._point_in_polygon(p[0], p[1], room.polygon) and all(
            (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 > 36.0 for q in points
        ):
            points.append(p)
    return points


def _expand(views: list[dict]) -> list[dict]:
    """Turn {"rooms": true} into explicit eye views per room point and heading."""
    out = []
    for view in views:
        if not view.get("rooms"):
            out.append(view)
            continue
        only = set(view.get("only", []))
        for room in cook._rooms():
            if only and room.id not in only:
                continue
            for index, (bx, by) in enumerate(_room_points(room)):
                for tag, yaw in HEADINGS:
                    out.append(
                        {
                            "name": f"{room.id}_{index}{tag}",
                            "eye": [bx, room.z + ROOM_EYE_M, -by, yaw, 7.0],
                            "room": room.id,
                        }
                    )
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("deck_id")
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("views", type=Path)
    parser.add_argument("--samples", type=int, default=64)
    parser.add_argument("--size", default="960x522")
    options = parser.parse_args(sys.argv[1:])
    started = time.monotonic()
    load_builder(options.deck_id).build()
    print(f"[verse] stage build: {time.monotonic() - started:.1f} s", flush=True)
    bpy.context.view_layer.update()
    bpy_scene = bpy.context.scene
    _realtime_visibility()
    width, height = (int(v) for v in options.size.lower().split("x"))
    render = bpy_scene.render
    render.resolution_x, render.resolution_y = width, height
    render.resolution_percentage = 100
    render.use_compositing = False
    bpy_scene.cycles.samples = options.samples
    bpy_scene.cycles.adaptive_threshold = 0.03
    bpy_scene.cycles.adaptive_min_samples = 16
    settings = render.image_settings
    settings.file_format = "PNG"
    settings.color_mode = "RGB"
    settings.color_depth = "8"
    camera = _camera(bpy_scene)
    views = _expand(json.loads(options.views.read_text(encoding="utf-8")))
    options.out_dir.mkdir(parents=True, exist_ok=True)
    done = []
    for view in views:
        if "rig" in view:
            x, z, yaw, floor = (list(view["rig"]) + [0.0])[:4]
            _aim(camera, _rig_position(x, z, yaw, floor), yaw, RIG_PITCH_DEG)
        else:
            x, y, z, yaw, pitch = view["eye"]
            _aim(camera, Vector((x, -z, y)), yaw, pitch)
        render.filepath = str(options.out_dir / f"{view['name']}.png")
        t0 = time.monotonic()
        bpy.ops.render.render(write_still=True)
        view["render_s"] = round(time.monotonic() - t0, 1)
        done.append(view)
        print(f"[verse] eye view {view['name']}: {view['render_s']} s", flush=True)
    (options.out_dir / "views.json").write_text(json.dumps(done, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
