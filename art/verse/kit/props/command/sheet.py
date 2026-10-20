"""Lookdev sheet for the command props (run inside Blender).

    python scripts/verse/blender.py run art/verse/kit/props/command/sheet.py -- \
        [--pieces SM_A,SM_B] [--ppm 96] [--crop 3] [--samples 64] [--no-crop]

Renders every piece alone through the fixed plate camera (orthographic,
60 degrees below the horizon, yaw 0) on a black glossy deck under a grid of
ceiling light panels: one image at game density (``--ppm``) and one at
``--crop`` times that density. Writes PNGs and ``pieces.json`` (measured
dims, sockets, occluder counts) to ``art/verse/.cache/lookdev/props-command``.
Compose the contact sheet afterwards with ``compose_sheet.py``.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path

import bpy
from mathutils import Vector

ART_ROOT = Path(__file__).resolve().parents[3]
if str(ART_ROOT) not in sys.path:
    sys.path.insert(0, str(ART_ROOT))

from lib import kit  # noqa: E402

import kit.props.command as command  # noqa: E402
from kit.architecture.ceiling import fill_ceiling  # noqa: E402

OUT = ART_ROOT / ".cache" / "lookdev" / "props-command"
PITCH = math.radians(60.0)
# Blender axes: camera looks along +Y and down; plate up vector U.
VIEW = Vector((0.0, math.cos(PITCH), -math.sin(PITCH)))
RIGHT = Vector((1.0, 0.0, 0.0))
UP = RIGHT.cross(VIEW).normalized()


def parse_args() -> argparse.Namespace:
    argv = sys.argv[1:]
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    p = argparse.ArgumentParser()
    p.add_argument("--pieces", default="")
    p.add_argument("--ppm", type=float, default=96.0)
    p.add_argument("--crop", type=float, default=3.0)
    p.add_argument("--samples", type=int, default=64)
    p.add_argument("--no-crop", action="store_true")
    p.add_argument("--crop-only", action="store_true")
    p.add_argument("--margin", type=float, default=0.35)
    p.add_argument("--exposure", type=float, default=0.0)
    p.add_argument("--vignette", action="store_true", help="render the arrangement only")
    return p.parse_args(argv)


def _clear_file() -> None:
    for block in (
        bpy.data.objects,
        bpy.data.meshes,
        bpy.data.lights,
        bpy.data.cameras,
        bpy.data.collections,
        bpy.data.materials,
        bpy.data.node_groups,
        bpy.data.worlds,
    ):
        for item in list(block):
            block.remove(item)


def reset_scene(exposure: float) -> bpy.types.Scene:
    """Empty file with the deck render settings of ``lib.scene`` (AgX, black world)."""
    # Never read_factory_settings(): it resets the Cycles device the bootstrap
    # chose (OptiX) and the render silently falls back to the CPU.
    _clear_file()
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    backend = os.environ.get("VERSE_CYCLES_BACKEND", "CPU")
    scene.cycles.device = "CPU" if backend == "CPU" else "GPU"
    scene.cycles.use_adaptive_sampling = True
    scene.cycles.adaptive_threshold = 0.02
    scene.cycles.use_denoising = True
    # OIDN (GPU-accelerated): the OptiX denoiser smears the floor reflections at
    # lookdev sample counts.
    scene.cycles.denoiser = "OPENIMAGEDENOISE"
    scene.cycles.denoising_input_passes = "RGB_ALBEDO_NORMAL"
    scene.cycles.max_bounces = 12
    scene.cycles.diffuse_bounces = 4
    scene.cycles.glossy_bounces = 6
    scene.cycles.transmission_bounces = 8
    scene.cycles.caustics_reflective = False
    scene.cycles.caustics_refractive = False
    scene.cycles.blur_glossy = 1.0
    scene.cycles.sample_clamp_indirect = 8.0
    scene.render.film_transparent = False
    scene.render.dither_intensity = 1.0
    scene.render.image_settings.file_format = "PNG"
    scene.render.resolution_percentage = 100
    scene.view_settings.view_transform = "AgX"
    scene.view_settings.look = "None"
    scene.view_settings.exposure = exposure
    world = bpy.data.worlds.new("WO_props_lookdev")
    if getattr(world, "node_tree", None) is None:
        world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg is not None:
        bg.inputs["Color"].default_value = (0.0, 0.0, 0.0, 1.0)
        bg.inputs["Strength"].default_value = 0.0
    scene.world = world
    return scene


def build_stage(half: float = 8.4, ceiling_z: float = 4.5) -> None:
    """Black glossy deck under the kit's ceiling light grid (camera-invisible)."""
    stage = kit.ensure_collection("Stage")
    with kit.into(stage):
        mb = kit.MeshBuilder()
        mb.box((-half, -half, -0.05), (half, half, 0.0), "M_Floor_GlossBlack")
        mb.build("LD_floor", bevel_width=0.0, nav="walk")
        fill_ceiling("lookdev", (-half, half), (-half, half), z=ceiling_z)


def piece_bounds(name: str) -> tuple[Vector, Vector]:
    master = kit.build_master(name)
    lo = Vector((1e9, 1e9, 1e9))
    hi = Vector((-1e9, -1e9, -1e9))
    for obj in master.all_objects:
        if obj.type != "MESH":
            continue
        for v in obj.data.vertices:
            w = obj.matrix_world @ v.co
            lo = Vector(map(min, lo, w))
            hi = Vector(map(max, hi, w))
    return lo, hi


def frame_camera(scene, cam, lo: Vector, hi: Vector, ppm: float, margin: float) -> None:
    us, vs = [], []
    for x in (lo.x, hi.x):
        for y in (lo.y, hi.y):
            for z in (lo.z, hi.z):
                p = Vector((x, y, z))
                us.append(p.dot(RIGHT))
                vs.append(p.dot(UP))
    u0, u1 = min(us) - margin, max(us) + margin
    v0, v1 = min(vs) - margin, max(vs) + margin
    width, height = u1 - u0, v1 - v0
    scene.render.resolution_x = max(64, round(width * ppm))
    scene.render.resolution_y = max(64, round(height * ppm))
    cam.data.ortho_scale = scene.render.resolution_x / ppm
    centre = RIGHT * (u0 + u1) / 2 + UP * (v0 + v1) / 2
    cam.location = centre - VIEW * 30.0


def make_camera(scene) -> bpy.types.Object:
    data = bpy.data.cameras.new("LD_camera")
    data.type = "ORTHO"
    data.sensor_fit = "HORIZONTAL"
    data.clip_start = 0.1
    data.clip_end = 100.0
    cam = bpy.data.objects.new("LD_camera", data)
    cam.rotation_euler = (math.radians(90.0) - PITCH, 0.0, 0.0)
    scene.collection.objects.link(cam)
    scene.camera = cam
    return cam


# Pieces a deck places at a fixed yaw are previewed that way.
PREVIEW_YAW = {"SM_Console_BoothRear": 180.0}

# A small bridge-like arrangement to judge rhythm and contrast in context.
VIGNETTE = (
    *[
        ("SM_Console_CrewPit" if k % 2 == 0 else "SM_Console_CrewPitB", -5.52 + k * 0.92, 3.2, 0.0)
        for k in range(4)
    ],
    *[
        ("SM_Console_CrewPitB" if k % 2 == 0 else "SM_Console_CrewPit", -5.52 + k * 0.92, 0.6, 0.0)
        for k in range(4)
    ],
    ("SM_Console_Command", 1.6, 3.6, 0.0),
    ("SM_Table_HoloStrategy", 1.6, -0.4, 0.0),
    ("SM_Terminal_Engineering", -5.6, -3.4, 0.0),
    ("SM_Terminal_EngineeringFill", -3.2, -3.4, 0.0),
    ("SM_Terminal_Engineering", -0.8, -3.4, 0.0),
    ("SM_Table_Mess", 3.2, -4.6, 0.0),
    ("SM_Chair_Commander", 5.6, 1.2, 200.0),
)


def render_vignette(scene, cam, args) -> None:
    col = kit.ensure_collection("Vignette")
    with kit.into(col):
        for k, (name, x, y, rot) in enumerate(VIGNETTE):
            kit.place(name, (x, y, 0.0), rot, id=f"v{k:02d}")
    lo = Vector((-7.2, -6.0, 0.0))
    hi = Vector((6.4, 4.6, 1.5))
    for tag, ppm, samples in (("game", args.ppm, args.samples * 2),):
        scene.cycles.samples = samples
        frame_camera(scene, cam, lo, hi, ppm, 0.0)
        path = OUT / f"vignette_{tag}.png"
        scene.render.filepath = str(path)
        bpy.ops.render.render(write_still=True)
        print(f"[props-command] rendered {path.name}", flush=True)


def main() -> None:
    args = parse_args()
    scene = reset_scene(args.exposure)
    build_stage()
    cam = make_camera(scene)
    OUT.mkdir(parents=True, exist_ok=True)
    if args.vignette:
        render_vignette(scene, cam, args)
        return
    names = [n for n in args.pieces.split(",") if n] or list(command.PIECES)
    OUT.mkdir(parents=True, exist_ok=True)
    props = kit.ensure_collection("Props")
    roots = {}
    with kit.into(props):
        for name in names:
            yaw = PREVIEW_YAW.get(name, 0.0)
            roots[name] = kit.place(name, (0.0, 0.0, 0.0), yaw, id=name[3:].lower())
    report = {}
    for name in names:
        for other, root in roots.items():
            root.hide_render = other != name
        lo, hi = piece_bounds(name)
        pdef = kit.registry()[name]
        report[name] = {
            "dims_measured": [round(hi[i] - lo[i], 3) for i in range(3)],
            "dims_registered": list(pdef.dims) if pdef.dims else None,
            "bbox_min": [round(c, 3) for c in lo],
            "bbox_max": [round(c, 3) for c in hi],
            "sockets": [
                f"SOCKET_{s.kind}_<id>" + (f"__{s.local_id}" if s.local_id else "")
                for s in pdef.sockets
            ],
            "occluders": len(pdef.occluders),
            "anchor": pdef.master.get("anchor") if pdef.master else None,
            "doc": pdef.doc,
        }
        passes = [] if args.crop_only else [(args.ppm, "game", args.samples)]
        if not args.no_crop:
            passes.append((args.ppm * args.crop, "crop", args.samples * 2))
        for ppm, tag, samples in passes:
            scene.cycles.samples = samples
            frame_camera(scene, cam, lo, hi, ppm, args.margin)
            path = OUT / f"{name}_{tag}.png"
            scene.render.filepath = str(path)
            bpy.ops.render.render(write_still=True)
            print(
                f"[props-command] rendered {path.name} "
                f"{scene.render.resolution_x}x{scene.render.resolution_y}",
                flush=True,
            )
    report_path = OUT / "pieces.json"
    merged = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
    merged.update(report)
    ordered = {n: merged[n] for n in command.PIECES if n in merged}
    report_path.write_text(json.dumps(ordered, indent=2), encoding="utf-8")
    print(f"[props-command] wrote {len(report)} pieces to {OUT}", flush=True)


main()
