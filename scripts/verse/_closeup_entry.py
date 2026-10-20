"""Blender-side close-up job: build a deck and render windows of its plate.

Run by scripts/verse/closeup.py through scripts/verse/blender.py:
    _closeup_entry.py <deck_id> <out_dir> <quality> <windows.json>
                      [--samples N] [--threshold T]

Each window is rendered exactly like the cook renders a plate region (same
camera, density, Cycles settings, denoiser, view transform and dither), with
the glow computed from the window plus its padding. Output per window:
`<name>.npy` (uint8 RGB, row 0 at the top) and `windows.json` with the plate
rectangle each one covers.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from pathlib import Path

import bpy
import numpy as np
from lib import cook, plate_post, scene
from mathutils import Vector

ART_ROOT = Path(__file__).resolve().parents[2] / "art" / "verse"
PAD_PX = 64  # denoiser and glow context around each window, cropped away
ALIGN_PX = plate_post.REGION_ALIGN_PX


def _plate_px(frame: scene.Frame, point: Vector) -> tuple[float, float]:
    """L0 pixel of a Blender-space point (same maths as worldToPlatePx)."""
    right, up, _ = scene.camera_basis()
    offset = point - Vector(frame.centre)
    u, v = offset.dot(right), offset.dot(up)
    return frame.width_px / 2 + u * frame.px_per_m, frame.height_px / 2 - v * frame.px_per_m


def _anchor(frame: scene.Frame, window: dict) -> tuple[float, float]:
    if "px" in window:  # L0 pixel at this quality's density
        return float(window["px"][0]), float(window["px"][1])
    if "socket" in window:
        obj = bpy.data.objects.get(f"SOCKET_{window['socket']}")
        if obj is None:
            raise KeyError(f"no socket SOCKET_{window['socket']}")
        return _plate_px(frame, obj.matrix_world.translation)
    x, y, z = window["three"]  # three.js world point
    return _plate_px(frame, Vector((x, -z, y)))


def _align_down(value: float) -> int:
    return int(value // ALIGN_PX * ALIGN_PX)


def _region(frame: scene.Frame, window: dict) -> plate_post.Region:
    cx, cy = _anchor(frame, window)
    width, height = int(window.get("w", 1600)), int(window.get("h", 900))
    col0 = min(max(0, _align_down(cx - width / 2)), max(0, frame.width_px - width))
    row0 = min(max(0, _align_down(cy - height / 2)), max(0, frame.height_px - height))
    col1, row1 = min(frame.width_px, col0 + width), min(frame.height_px, row0 + height)
    return plate_post.Region(
        row0=max(0, row0 - PAD_PX),
        row1=min(frame.height_px, row1 + PAD_PX),
        col0=max(0, col0 - PAD_PX),
        col1=min(frame.width_px, col1 + PAD_PX),
        inner_row0=row0,
        inner_row1=row1,
        inner_col0=col0,
        inner_col1=col1,
    )


def _load_builder(deck_id: str):
    path = ART_ROOT / "decks" / deck_id / "build.py"
    spec = importlib.util.spec_from_file_location(f"verse_deck_{deck_id}", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("deck_id")
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("quality")
    parser.add_argument("windows", type=Path)
    parser.add_argument("--samples", type=int)
    parser.add_argument("--threshold", type=float)
    options = parser.parse_args(sys.argv[1:])
    windows = json.loads(options.windows.read_text(encoding="utf-8"))
    out_dir = options.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    _load_builder(options.deck_id).build()
    bpy.context.view_layer.update()
    preset = scene.QUALITY[options.quality]
    info = scene.deck_info()
    frame = scene.frame_for(info["bounds"], preset.px_per_m)
    bpy_scene = bpy.context.scene
    cook._prepare_visibility()
    scene.apply_frame(bpy_scene, bpy_scene.camera, frame)
    bpy_scene.cycles.samples = options.samples or preset.samples
    bpy_scene.cycles.adaptive_threshold = options.threshold or preset.adaptive_threshold
    bpy_scene.render.use_compositing = False
    bpy_scene.render.use_persistent_data = True

    done = []
    for index, window in enumerate(windows):
        region = _region(frame, window)
        path = out_dir / f"_linear_{index}.exr"
        started = time.monotonic()
        cook._render_region(bpy_scene, frame, region, path, use_border=True)
        seconds = time.monotonic() - started
        linear = cook._load_linear_rgb(path)
        path.unlink()
        # Glow from the padded window (sides cut to the glow factor).
        factor = plate_post.GLOW_FACTOR
        height = linear.shape[0] // factor * factor
        width = linear.shape[1] // factor * factor
        glowing = plate_post.bloom(linear[:height, :width].copy(), frame.px_per_m)
        rows, cols = region.inner_slice()
        inner = glowing[rows, cols].copy()
        pixels = cook._to_display_8bit(bpy_scene, inner, out_dir / "_display.png", seed=index)
        name = window.get("name", f"window_{index}")
        np.save(out_dir / f"{name}.npy", pixels)
        done.append(
            {
                "name": name,
                "plate_rect": [
                    region.inner_col0,
                    region.inner_row0,
                    region.inner_col1,
                    region.inner_row1,
                ],
                "render_s": round(seconds, 1),
                "samples": bpy_scene.cycles.samples,
                "threshold": bpy_scene.cycles.adaptive_threshold,
            }
        )
        print(
            f"[verse] close-up {name}: {region.inner_col1 - region.inner_col0}x"
            f"{region.inner_row1 - region.inner_row0} px in {seconds:.1f} s",
            flush=True,
        )
    meta = {
        "deck": options.deck_id,
        "quality": options.quality,
        "px_per_m": frame.px_per_m,
        "plate_px": [frame.width_px, frame.height_px],
        "windows": done,
    }
    (out_dir / "windows.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
