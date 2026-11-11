"""Textures of the space view outside the windows, the same images today's three.js view uses.

Pure Python (numpy, Pillow), no bpy, deterministic. Writes equirectangular images (longitude
-180 deg at the left edge, north at the top) into the export cache and, with ``--records``,
their `verse.import/1` texture records:

* ``T_Space_EarthDay_BC`` (8192 x 4096, sRGB): `earth_day.webp`, NASA Blue Marble;
* ``T_Space_EarthNight_E`` (4096 x 2048, sRGB): `earth_night.webp`, NASA Black Marble;
* ``T_Space_EarthClouds_M`` (8192 x 4096, linear R): `earth_clouds.webp`;
* ``T_Space_EarthRelief_M`` (4096 x 2048, linear): `earth_relief.webp`, R,G terrain slope,
  B open water;
* ``T_Space_Stars_E`` (8192 x 4096, sRGB): the 9000 stars of `starField` in
  `engine/realtime/spaceView.ts` (same generator, same seed), drawn into the sky at
  ``STAR_SCALE`` below their brightness (the material scales them back).

The four Earth images come from `scripts/verse/earth.py` (NASA Visible Earth, public domain;
`art/verse/LICENSES.md`). `M_Verse_Space` (`weapons/editor/masters.py`) draws them the way
`engine/realtime/spaceShader.ts` does.

    python art/verse/kit/props/space/space_textures.py             # write the images
    python art/verse/kit/props/space/space_textures.py --records   # and their import records
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None

HERE = Path(__file__).resolve()
REPO_ROOT = HERE.parents[5]
CACHE = REPO_ROOT / "art" / "verse" / ".cache" / "unreal" / "kit" / "space"
RECORDS = REPO_ROOT / "unreal" / "Verse" / "Art" / "Import" / "Kit" / "Space"
WEB = REPO_ROOT / "dodaios" / "ui" / "web" / "frontend" / "public" / "verse" / "space"
FOLDER = "/Game/Verse/Kit/Space"

#: `starField` in spaceView.ts.
STAR_COUNT = 9000
STAR_SEED = 7
STAR_WIDTH, STAR_HEIGHT = 8192, 4096
#: Stars are stored at brightness / STAR_SCALE (the brightest is about 3.6).
STAR_SCALE = 4.0
#: Screen pixels per texel of the star sky, for the point sizes of the three.js points.
STAR_PX_PER_TEXEL = 1.0

APPROVAL = "integration"


def _u32(x: int) -> int:
    return x & 0xFFFFFFFF


def _imul(a: int, b: int) -> int:
    return _u32(_u32(a) * _u32(b))


def random(seed: int):
    """`random` of spaceView.ts (mulberry32), bit for bit."""
    state = [_u32(seed)]

    def next_value() -> float:
        state[0] = _u32(state[0] + 0x6D2B79F5)
        t = state[0]
        t = _imul(t ^ (t >> 15), t | 1)
        t = _u32(t ^ _u32(t + _imul(t ^ (t >> 7), t | 61)))
        return _u32(t ^ (t >> 14)) / 4294967296

    return next_value


def star_field(count: int = STAR_COUNT, seed: int = STAR_SEED):
    """`starField` of spaceView.ts: directions (three.js axes), colours, point sizes."""
    rand = random(seed)
    pole = np.array([0.35, 0.82, -0.45])
    pole /= np.linalg.norm(pole)
    temps = [
        (0.62, 0.72, 1.0),
        (0.8, 0.86, 1.0),
        (1.0, 1.0, 1.0),
        (1.0, 0.95, 0.82),
        (1.0, 0.82, 0.6),
        (1.0, 0.7, 0.5),
    ]
    dirs = np.zeros((count, 3))
    colours = np.zeros((count, 3))
    sizes = np.zeros(count)
    for i in range(count):
        while True:
            z = rand() * 2 - 1
            a = rand() * math.pi * 2
            r = math.sqrt(1 - z * z)
            v = (r * math.cos(a), z, r * math.sin(a))
            band = abs(v[0] * pole[0] + v[1] * pole[1] + v[2] * pole[2])
            if i % 2 == 0 or rand() > band * 1.6:
                break
        dirs[i] = v
        m = rand() ** 5.5
        brightness = 0.06 + m * 3.5
        t = temps[min(len(temps) - 1, math.floor(rand() ** 0.8 * len(temps)))]
        colours[i] = [c * brightness for c in t]
        sizes[i] = 1.0 + m * 2.2
    return dirs, colours, sizes


def stars(width: int = STAR_WIDTH, height: int = STAR_HEIGHT) -> Image.Image:
    """The star sky, equirectangular in three.js axes (+Y up; longitude atan2(-z, x), as the
    Earth's maps), each star drawn as its point sprite: (1 - r^2)^2 over its size."""
    sky = np.zeros((height, width, 3), dtype=np.float64)
    dirs, colours, sizes = star_field()
    for d, colour, size in zip(dirs, colours, sizes, strict=True):
        lon = math.atan2(-d[2], d[0])
        lat = math.asin(max(-1.0, min(1.0, d[1])))
        x = (lon / (2.0 * math.pi) + 0.5) * width - 0.5
        y = (0.5 - lat / math.pi) * height - 0.5
        radius = max(0.5, 0.5 * size / STAR_PX_PER_TEXEL)
        stretch = 1.0 / max(math.cos(lat), 0.05)
        rx, ry = radius * stretch, radius
        cx, cy = round(x), round(y)
        for py in range(cy - math.ceil(ry), cy + math.ceil(ry) + 1):
            if not 0 <= py < height:
                continue
            for px in range(cx - math.ceil(rx), cx + math.ceil(rx) + 1):
                u = (px - x) / rx
                w = (py - y) / ry
                f = max(1.0 - (u * u + w * w), 0.0)
                if px == cx and py == cy:
                    f = max(f, 1.0)
                if f > 0.0:
                    sky[py, px % width] += colour * f * f
    linear = np.clip(sky / STAR_SCALE, 0.0, 1.0)
    srgb = np.where(linear <= 0.0031308, linear * 12.92, 1.055 * linear ** (1 / 2.4) - 0.055)
    return Image.fromarray(np.round(srgb * 255).astype(np.uint8), "RGB")


def _web(name: str, mode: str):
    def make() -> Image.Image:
        return Image.open(WEB / name).convert(mode)

    return make


#: name -> (builder function, maker, record texture block, web source or None)
TEXTURES = {
    "T_Space_EarthDay_BC": (
        "earth_day",
        _web("earth_day.webp", "RGB"),
        {"max_size": 8192, "srgb": True, "compression": "Default"},
        "earth_day.webp",
    ),
    "T_Space_EarthNight_E": (
        "earth_night",
        _web("earth_night.webp", "RGB"),
        {"max_size": 4096, "srgb": True, "compression": "Default"},
        "earth_night.webp",
    ),
    "T_Space_EarthClouds_M": (
        "earth_clouds",
        _web("earth_clouds.webp", "L"),
        {"max_size": 8192, "srgb": False, "compression": "Grayscale"},
        "earth_clouds.webp",
    ),
    "T_Space_EarthRelief_M": (
        "earth_relief",
        _web("earth_relief.webp", "RGB"),
        {"max_size": 4096, "srgb": False, "compression": "BC7"},
        "earth_relief.webp",
    ),
    "T_Space_Stars_E": (
        "stars",
        stars,
        {"max_size": 8192, "srgb": True, "compression": "BC7"},
        None,
    ),
}


def record(name: str, function: str, png: Path, spec: dict, web: str | None) -> dict:
    digest = hashlib.sha256(png.read_bytes()).hexdigest()
    doc = {
        "schema": "verse.import/1",
        "name": name,
        "asset_path": f"{FOLDER}/{name}.{name}",
        "kind": "texture",
        "source": {
            "builder": HERE.relative_to(REPO_ROOT).as_posix(),
            "function": function,
            "args": {"count": STAR_COUNT, "seed": STAR_SEED} if web is None else {"file": web},
        },
        "export": {
            "format": "png",
            "settings_id": "png-ue/1",
            "file": png.relative_to(REPO_ROOT).as_posix(),
            "sha256": digest,
            "blender": "0.0.0",
        },
        "texture": {
            "group": "World",
            "max_size": spec["max_size"],
            "srgb": spec["srgb"],
            "compression": spec["compression"],
            "flip_green": False,
            "never_stream": True,
        },
        "lightmap": "none",
        "license": {"kind": "own"},
        "owner": "WP12",
    }
    if web is not None:
        source = hashlib.sha256((WEB / web).read_bytes()).hexdigest()
        doc["license"] = {"kind": "ledger", "ledger_sha256": [source]}
    if spec["max_size"] > 2048:
        doc["budget_override"] = {
            "field": "max_size",
            "value": spec["max_size"],
            "reason": "the sky behind every window: the same resolution as the three.js view",
            "approved_by": APPROVAL,
        }
    return doc


def dumps(doc: dict) -> str:
    return json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def write_all(
    *, check: bool = False, records: bool = False, only: set[str] | None = None
) -> list[str]:
    stale = []
    CACHE.mkdir(parents=True, exist_ok=True)
    for name, (function, make, spec, web) in TEXTURES.items():
        if only and name not in only:
            continue
        png = CACHE / f"{name}.png"
        if not (check and png.is_file()):
            make().save(png, optimize=False, compress_level=6)
            print(f"[verse] wrote {png.relative_to(REPO_ROOT).as_posix()}", flush=True)
        if not records:
            continue
        path = RECORDS / f"{name}.import.json"
        text = dumps(record(name, function, png, spec, web))
        if path.is_file() and path.read_text(encoding="utf-8") == text:
            continue
        stale.append(path.relative_to(REPO_ROOT).as_posix())
        if not check:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode("utf-8"))
    return stale


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--records", action="store_true", help="also write the import records")
    parser.add_argument("--only", action="append", help="one texture name (repeatable)")
    options = parser.parse_args(argv)
    stale = write_all(
        check=options.check,
        records=options.records or options.check,
        only=set(options.only or ()),
    )
    for path in stale:
        print(f"[verse] {'stale' if options.check else 'wrote'} {path}")
    return 1 if options.check and stale else 0


if __name__ == "__main__":
    sys.exit(main())
