"""Lookdev renders of the industrial props through the fixed plate camera.

Run (one Cycles job at a time; the wrapper holds the GPU lock):

    python scripts/verse/blender.py run art/verse/kit/props/industrial/lookdev.py \
        [--pieces SM_A,SM_B] [--density 96] [--crop 3] [--samples 64] \
        [--vignette reactor|hangar] [--vignette-density 48] [--list]

Each piece is placed alone on a polished deck floor under overhead panels and
rendered with the game camera (orthographic, 60 degrees below the horizon) at
``--density`` px/m, plus a crop at ``--crop`` times that density around its
detail point. Output: art/verse/.cache/lookdev/props-industrial/.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path

import bpy
from mathutils import Vector

ART = Path(__file__).resolve().parents[3]
if str(ART) not in sys.path:
    sys.path.insert(0, str(ART))

from lib import kit as K  # noqa: E402

import kit.props.industrial as IND  # noqa: E402

OUT = ART / ".cache" / "lookdev" / "props-industrial"
PITCH = math.radians(60.0)
R_VEC = Vector((1.0, 0.0, 0.0))
U_VEC = Vector((0.0, math.sin(PITCH), math.cos(PITCH)))  # screen up, Blender axes
D_VEC = Vector((0.0, math.cos(PITCH), -math.sin(PITCH)))  # view direction


# --------------------------------------------------------------------------
# Scene
# --------------------------------------------------------------------------


def reset_scene(samples: int) -> bpy.types.Scene:
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    backend = os.environ.get("VERSE_CYCLES_BACKEND", "CPU")
    sc.cycles.device = "GPU" if backend in ("OPTIX", "CUDA") else "CPU"
    sc.cycles.samples = samples
    sc.cycles.use_adaptive_sampling = True
    sc.cycles.adaptive_threshold = 0.015
    sc.cycles.use_denoising = True
    sc.cycles.denoiser = "OPENIMAGEDENOISE"
    sc.cycles.max_bounces = 8
    sc.cycles.diffuse_bounces = 3
    sc.cycles.glossy_bounces = 4
    sc.cycles.transparent_max_bounces = 16
    sc.cycles.volume_bounces = 1
    sc.cycles.sample_clamp_indirect = 6.0
    sc.cycles.blur_glossy = 0.8
    sc.cycles.caustics_reflective = False
    sc.cycles.caustics_refractive = False
    sc.render.film_transparent = False
    sc.view_settings.view_transform = "AgX"
    try:
        sc.view_settings.look = "None"
    except TypeError:
        pass
    sc.view_settings.exposure = 0.0
    world = bpy.data.worlds.get("LookdevWorld") or bpy.data.worlds.new("LookdevWorld")
    try:
        world.use_nodes = True
    except AttributeError:
        pass
    nt = world.node_tree
    bg = nt.nodes.get("Background")
    if bg is None:
        nt.nodes.clear()
        bg = nt.nodes.new("ShaderNodeBackground")
        out = nt.nodes.new("ShaderNodeOutputWorld")
        nt.links.new(bg.outputs[0], out.inputs["Surface"])
    bg.inputs["Color"].default_value = (0.0, 0.0, 0.0, 1.0)
    bg.inputs["Strength"].default_value = 1.0
    sc.world = world
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_depth = "8"
    return sc


def camera(sc) -> bpy.types.Object:
    cam = bpy.data.objects.get("PlateCam")
    if cam is None:
        data = bpy.data.cameras.new("PlateCam")
        data.type = "ORTHO"
        data.clip_start = 0.1
        data.clip_end = 2000.0
        cam = bpy.data.objects.new("PlateCam", data)
        sc.collection.objects.link(cam)
    cam.rotation_euler = (math.radians(30.0), 0.0, 0.0)
    sc.camera = cam
    return cam


def frame(sc, cam, u0, u1, v0, v1, density, max_px=4096):
    w, h = u1 - u0, v1 - v0
    scale = min(1.0, max_px / max(w * density, h * density))
    sc.render.resolution_x = max(16, round(w * density * scale))
    sc.render.resolution_y = max(16, round(h * density * scale))
    sc.render.resolution_percentage = 100
    cam.data.ortho_scale = max(w, h)
    uc, vc = (u0 + u1) / 2, (v0 + v1) / 2
    cam.location = R_VEC * uc + U_VEC * vc - D_VEC * 400.0
    return density * scale


def uv(p) -> tuple[float, float]:
    p = Vector(p)
    return p.dot(R_VEC), p.dot(U_VEC)


class _track:
    """Collect the objects created inside the ``with`` block."""

    def __enter__(self):
        self.before = set(bpy.data.objects)
        self.made: list = []
        return self.made

    def __exit__(self, *exc):
        self.made.extend(o for o in bpy.data.objects if o not in self.before)
        return False


def floor(sc, half=40.0, hole=None):
    """Production deck floor (kit floors); ``hole`` = half-size of a centred
    square opening. Returns the objects created."""
    from kit.architecture import floors

    rects = [(-half, -half, half, half)]
    if hole is not None:
        rects = [
            (-half, -half, -hole, half),
            (hole, -half, half, half),
            (-hole, -half, hole, -hole),
            (-hole, hole, hole, half),
        ]
    with _track() as made, K.into(sc.collection):
        for i, (x0, y0, x1, y1) in enumerate(rects):
            floors.fill_rect(f"LD_floor_{i}", x0, y0, x1, y1)
    return made


def ceiling_lights(sc, x0, x1, y0, y1, height=5.2, pitch=2.4, power=None):
    """Production ceiling (camera-invisible slab + diffuser panel grid), the
    same rig the kit sheet uses. Returns the objects created."""
    from kit.architecture import ceiling

    del power  # the kit panels carry their own calibrated emission
    with _track() as made, K.into(sc.collection):
        ceiling.fill_ceiling(
            "lookdev", (x0, x1), (y0, y1), z=height, pitch=(pitch, pitch), size=(1.2, 0.6)
        )
    return made


def master_bounds(name: str, skip_none_nav: bool = True):
    master = K.build_master(name)
    lo = Vector((1e9, 1e9, 1e9))
    hi = -lo
    for ob in master.all_objects:
        if ob.type != "MESH" or ob.name.startswith("UCX_"):
            continue
        if skip_none_nav and ob.get("nav") == "none" and len(master.all_objects) > 1:
            continue
        for c in ob.bound_box:
            w = ob.matrix_world @ Vector(c)
            lo = Vector(map(min, lo, w))
            hi = Vector(map(max, hi, w))
    if lo.x > hi.x and skip_none_nav:  # every mesh is nav "none" (decals, panels)
        return master_bounds(name, skip_none_nav=False)
    return lo, hi


def bounds_uv(lo, hi):
    us, vs = [], []
    for x in (lo.x, hi.x):
        for y in (lo.y, hi.y):
            for z in (lo.z, hi.z):
                u, v = uv((x, y, z))
                us.append(u)
                vs.append(v)
    return min(us), max(us), min(vs), max(vs)


def render(sc, path: Path) -> float:
    path.parent.mkdir(parents=True, exist_ok=True)
    sc.render.filepath = str(path)
    t = time.time()
    bpy.ops.render.render(write_still=True)
    return time.time() - t


# --------------------------------------------------------------------------
# Piece sheet
# --------------------------------------------------------------------------


def industrial_pieces() -> list[str]:
    return sorted(
        name
        for name, pdef in K.registry().items()
        if pdef.builder.__module__.startswith("kit.props.industrial")
    )


def hints(name: str) -> dict:
    for mod in (IND.reactor, IND.engineering, IND.hangar, IND.hangar_service, IND.shuttle):
        table = getattr(mod, "LOOKDEV", {})
        if name in table:
            return table[name]
    return {}


def render_piece(sc, cam, name, density, crop, margin=0.8):
    h = hints(name)
    if h.get("skip"):
        return None
    root = K.place(name, (0, 0, 0), 0.0, collection=sc.collection, id=f"LD_{name[3:]}")
    lo, hi = master_bounds(name)
    u0, u1, v0, v1 = h.get("frame") or bounds_uv(lo, hi)
    fl = floor(sc, half=max(hi.x - lo.x, hi.y - lo.y) / 2 + 12) if h.get("floor", True) else None
    lights = ceiling_lights(sc, lo.x - 4, hi.x + 4, lo.y - 4, hi.y + 4, height=max(5.2, hi.z + 1.5))
    stats = {"piece": name, "dims": [round(hi[i] - lo[i], 2) for i in range(3)]}
    used = frame(
        sc, cam, u0 - margin, u1 + margin, v0 - margin, v1 + margin, density, h.get("max_px", 2400)
    )
    stats["px_per_m"] = round(used, 1)
    stats["full_s"] = round(render(sc, OUT / f"{name}.png"), 1)
    stats["full_px"] = [sc.render.resolution_x, sc.render.resolution_y]
    if crop:
        focus = Vector(h.get("focus") or ((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, hi.z * 0.8))
        fu, fv = uv(focus)
        cw, ch = h.get("crop_size", (2.6, 1.6))
        frame(sc, cam, fu - cw / 2, fu + cw / 2, fv - ch / 2, fv + ch / 2, density * crop)
        stats["crop_s"] = round(render(sc, OUT / f"{name}__crop{crop}x.png"), 1)
    for ob in [root, *lights, *(fl or [])]:
        if ob is not None:
            bpy.data.objects.remove(ob, do_unlink=True)
    for ob in list(bpy.data.objects):  # sockets and occluders emitted by place()
        if ob.name.startswith(("SOCKET_", "UCX_")):
            bpy.data.objects.remove(ob, do_unlink=True)
    print(f"[props-industrial] {json.dumps(stats)}", flush=True)
    return stats


# --------------------------------------------------------------------------
# Vignettes
# --------------------------------------------------------------------------


def vignette_reactor(sc, cam, density, crop):
    parts = IND.reactor.place_reactor((0, 0, 0), room="reactor", prefix="LD_reactor")
    if os.environ.get("VERSE_PI_NO_HAZE") == "1":
        for ob in parts:
            if "haze" in ob.name:
                ob.hide_render = True
    half = IND.reactor.COLLAR_SIZE / 2
    floor(sc, half=half + 14, hole=half)
    ceiling_lights(sc, -half - 10, half + 10, -half - 10, half + 10, height=7.0, pitch=2.4)
    extra = getattr(IND.engineering, "dress_reactor_vignette", None)
    if extra:
        extra(sc.collection, half)
    r = IND.reactor.SHAFT_RADIUS
    u0, u1 = -r - 4.0, r + 4.0
    v0, v1 = uv((0, -r - 3.0, 0))[1], uv((0, r + 3.0, 6.0))[1]
    frame(sc, cam, u0, u1, v0, v1, density, 4096)
    t = render(sc, OUT / f"VIGNETTE_reactor_{int(density)}ppm.png")
    print(
        f"[props-industrial] vignette reactor {sc.render.resolution_x}x"
        f"{sc.render.resolution_y} in {t:.1f}s",
        flush=True,
    )
    if crop:
        for tag, focus, size in (
            ("farwall", (0.0, 13.0, -9.0), (12.0, 7.2)),
            ("core", (0.0, 0.0, 1.0), (12.0, 7.2)),
            ("catwalk", (-3.0, -9.5, 0.0), (6.0, 3.6)),
        ):
            fu, fv = uv(focus)
            w, h = size
            frame(sc, cam, fu - w / 2, fu + w / 2, fv - h / 2, fv + h / 2, 96.0 * crop / 3)
            render(sc, OUT / f"VIGNETTE_reactor__{tag}_{int(96 * crop / 3)}ppm.png")


def vignette_hangar(sc, cam, density, crop):
    fn = getattr(IND.hangar, "place_hangar_vignette", None)
    if fn is None:
        raise SystemExit("hangar vignette not available yet")
    u0, u1, v0, v1 = fn(sc.collection)
    # deck floor with the launch well's opening cut out (rects + chamfer corners)
    from kit.props.industrial import _mats

    wx, wy = 0.0, 27.0
    hl, hw = 30.0 / 2 + 1.2, 12.0 / 2 + 1.2
    c = 2.4 + 1.2 * 0.414
    half = 60.0
    mb = K.MeshBuilder()
    mat = _mats.m("floor")
    for x0, y0, x1, y1 in (
        (-half, -half, half, wy - hw),
        (-half, wy + hw, half, half),
        (-half, wy - hw, wx - hl, wy + hw),
        (wx + hl, wy - hw, half, wy + hw),
    ):
        mb.box((x0, y0, -0.2), (x1, y1, 0.0), mat)
    for sx in (-1, 1):
        for sy in (-1, 1):
            corner = (wx + sx * hl, wy + sy * hw, 0.0)
            a = (wx + sx * (hl - c), wy + sy * hw, 0.0)
            b = (wx + sx * hl, wy + sy * (hw - c), 0.0)
            tri = [corner, a, b] if sx * sy > 0 else [corner, b, a]
            mb._add([Vector(p) for p in tri], [(0, 1, 2)], mat)
    with K.into(sc.collection):
        mb.build("LD_hangar_floor", bevel_width=0.0, nav="walk")
    ceiling_lights(sc, -36, 36, -20, 42, height=12.0, pitch=3.6)
    frame(sc, cam, u0, u1, v0, v1, density, 4096)
    t = render(sc, OUT / f"VIGNETTE_hangar_{int(density)}ppm.png")
    print(f"[props-industrial] vignette hangar in {t:.1f}s", flush=True)
    if crop:
        for tag, focus, size in (
            ("shuttle_ramp", (0.0, -5.5, 2.0), (12.0, 7.2)),
            ("well", (-10.0, 21.0, -0.5), (12.0, 7.2)),
            ("cargo", (-17.0, 7.0, 1.3), (12.0, 7.2)),
        ):
            fu, fv = uv(focus)
            w, h = size
            frame(sc, cam, fu - w / 2, fu + w / 2, fv - h / 2, fv + h / 2, 96.0 * crop / 3)
            render(sc, OUT / f"VIGNETTE_hangar__{tag}_{int(96 * crop / 3)}ppm.png")


# --------------------------------------------------------------------------


def clear_stage(sc, cam) -> None:
    """Remove everything placed on the stage (masters and camera stay)."""
    for ob in list(sc.collection.objects):
        if ob != cam:
            bpy.data.objects.remove(ob, do_unlink=True)
    for ob in list(bpy.data.objects):
        if ob.name.startswith(("SOCKET_", "UCX_")):
            bpy.data.objects.remove(ob, do_unlink=True)


def main(argv):
    p = argparse.ArgumentParser()
    p.add_argument("--pieces", default="", help="comma list, 'all', or empty with --vignette")
    p.add_argument("--density", type=float, default=96.0)
    p.add_argument("--crop", type=int, default=3)
    p.add_argument("--samples", type=int, default=64)
    p.add_argument("--vignette", default="", help="comma list of reactor, hangar")
    p.add_argument("--vignette-density", type=float, default=32.0)
    p.add_argument("--list", action="store_true")
    a = p.parse_args(argv)
    names = industrial_pieces()
    if a.list:
        for n in names:
            pdef = K.registry()[n]
            K.build_master(n)
            print(
                f"[props-industrial] {n} dims={pdef.dims} nav={pdef.nav} "
                f"sockets={[f'{s.kind}:{s.local_id}' for s in pdef.sockets]} "
                f"occluders={len(pdef.occluders)}",
                flush=True,
            )
        return
    sc = reset_scene(a.samples)
    cam = camera(sc)
    if a.pieces or not a.vignette:
        wanted = set(a.pieces.split(",")) if a.pieces not in ("", "all") else None
        chosen = [n for n in names if wanted is None or n in wanted]
        path = OUT / "stats.json"
        merged = {s["piece"]: s for s in json.loads(path.read_text())} if path.exists() else {}
        for n in chosen:
            stat = render_piece(sc, cam, n, a.density, a.crop)
            if stat:
                merged[n] = stat
                path.write_text(
                    json.dumps(sorted(merged.values(), key=lambda s: s["piece"]), indent=1)
                )
    for v in filter(None, a.vignette.split(",")):
        clear_stage(sc, cam)
        {"reactor": vignette_reactor, "hangar": vignette_hangar}[v](
            sc, cam, a.vignette_density, a.crop
        )


if __name__ == "__main__":
    main(sys.argv[1:])
