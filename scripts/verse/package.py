"""Deck cook, package side (outside Blender): raw cook output -> runtime content.

Encodes the plate into AVIF tiles (L0, full density, 2048 px tiles) plus one
quarter-resolution overview (L1), the nav grid into an 8-bit PNG, copies the
occluder GLB and the environment map, and writes `manifest.json`
(schema `verse.deck/1`). The output directory is replaced atomically.
"""

from __future__ import annotations

import json
import math
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

SCHEMA = "verse.deck/1"
TILE_PX = 2048
L1_DIVISOR = 4


@dataclass(frozen=True)
class AvifSettings:
    """Chosen by scripts/verse/avif_test.py on the testbed plate (see pipeline.md)."""

    quality: int = 72
    speed: int = 4
    subsampling: str = "4:4:4"


AVIF = AvifSettings()
L1_AVIF = AvifSettings(quality=70)


def _save_avif(image: Image.Image, path: Path, settings: AvifSettings) -> None:
    image.save(
        path,
        format="AVIF",
        quality=settings.quality,
        speed=settings.speed,
        subsampling=settings.subsampling,
    )


def assemble_plate(raw_dir: Path, cook: dict) -> Image.Image:
    """Stitch the cook's plate regions into one RGB image (also kept as raw plate.png)."""
    camera = cook["camera"]
    plate = Image.new("RGB", (camera["plate_w_px"], camera["plate_h_px"]))
    covered = 0
    for part in cook["plate_parts"]:
        region = np.load(raw_dir / part["file"])
        size = (part["row1"] - part["row0"], part["col1"] - part["col0"], 3)
        if region.shape != size:
            raise ValueError(f"{part['file']} is {region.shape}, expected {size}")
        plate.paste(Image.fromarray(region, mode="RGB"), (part["col0"], part["row0"]))
        covered += size[0] * size[1]
    if covered != plate.width * plate.height:
        raise ValueError("plate regions do not cover the plate exactly once")
    plate.save(raw_dir / "plate.png", compress_level=1)
    return plate


def _encode_plate(plate: Image.Image, out_dir: Path) -> dict:
    width, height = plate.size
    cols, rows = math.ceil(width / TILE_PX), math.ceil(height / TILE_PX)
    tile_dir = out_dir / "plate"
    tile_dir.mkdir(parents=True, exist_ok=True)
    for row in range(rows):
        for col in range(cols):
            box = (
                col * TILE_PX,
                row * TILE_PX,
                min(width, (col + 1) * TILE_PX),
                min(height, (row + 1) * TILE_PX),
            )
            _save_avif(plate.crop(box), tile_dir / f"L0_{col}_{row}.avif", AVIF)
    l1_size = (round(width / L1_DIVISOR), round(height / L1_DIVISOR))
    overview = plate.resize(l1_size, Image.Resampling.LANCZOS)
    _save_avif(overview, tile_dir / "L1.avif", L1_AVIF)
    return {
        "format": "avif",
        "tile_px": TILE_PX,
        "cols": cols,
        "rows": rows,
        "tile_url": "plate/L0_{col}_{row}.avif",
        "l1_url": "plate/L1.avif",
        "l1_w_px": l1_size[0],
        "l1_h_px": l1_size[1],
    }


def _encode_nav(nav_npy: Path, out_dir: Path, nav: dict) -> dict:
    grid = np.load(nav_npy)
    if grid.shape != (nav["h"], nav["w"]):
        raise ValueError(f"nav grid shape {grid.shape} does not match {nav['h']}x{nav['w']}")
    Image.fromarray(grid.astype(np.uint8), mode="L").save(out_dir / "nav.png", optimize=True)
    return {"url": "nav.png", **nav}


def _bytes(out_dir: Path) -> int:
    return sum(path.stat().st_size for path in out_dir.rglob("*") if path.is_file())


def build_manifest(cook: dict, plate: dict, nav: dict) -> dict:
    return {
        "schema": SCHEMA,
        "id": cook["id"],
        "name": cook["name"],
        "floor": cook["floor"],
        "quality": cook["quality"],
        "camera": cook["camera"],
        "plate": plate,
        "occluders": {"url": "occluders.glb", **cook["occluders"]},
        "nav": nav,
        "env": {"url": "env.hdr", **cook["env"]},
        "probes": cook["probes"],
        "rooms": cook["rooms"],
        "sockets": cook["sockets"],
        "stations": cook["stations"],
        "stats": dict(cook["stats"]),
    }


def package_deck(raw_dir: Path, out_dir: Path, extra_stats: dict | None = None) -> dict:
    """Turn the raw Blender output in `raw_dir` into the runtime deck at `out_dir`.

    Everything is written to `<out_dir>.staging` first and swapped in at the
    end; a failure removes the staging directory and leaves `out_dir` as it was.
    """
    started = time.monotonic()
    cook = json.loads((raw_dir / "cook.json").read_text(encoding="utf-8"))
    staging = out_dir.with_name(out_dir.name + ".staging")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    try:
        manifest = _write_deck(raw_dir, staging, cook, extra_stats or {}, started)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    if out_dir.exists():
        shutil.rmtree(out_dir)
    staging.rename(out_dir)
    return manifest


def _write_deck(
    raw_dir: Path, staging: Path, cook: dict, extra_stats: dict, started: float
) -> dict:
    plate = _encode_plate(assemble_plate(raw_dir, cook), staging)
    nav = _encode_nav(raw_dir / "nav.npy", staging, cook["nav"])
    shutil.copyfile(raw_dir / "occluders.glb", staging / "occluders.glb")
    shutil.copyfile(raw_dir / "env.hdr", staging / "env.hdr")
    manifest = build_manifest(cook, plate, nav)
    stats = manifest["stats"]
    stats.update(extra_stats)
    stats["package_s"] = round(time.monotonic() - started, 2)
    stats["plate_bytes"] = sum(p.stat().st_size for p in (staging / "plate").iterdir())
    stats["bytes"] = 0
    manifest_path = staging / "manifest.json"
    for _ in range(3):  # the byte count includes the manifest that states it
        manifest_path.write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
        stats["bytes"] = _bytes(staging)
    manifest_path.write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    return manifest
