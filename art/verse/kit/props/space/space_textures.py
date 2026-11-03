"""Own-work textures of the space view (WP12.9): a Noir Earth and a star field.

Pure Python (numpy, Pillow), no bpy, deterministic. Writes two equirectangular PNGs
(longitude -180 deg at the left edge, north at the top) into the export cache and their
`verse.import/1` texture records:

* ``T_Space_Earth_E`` (2048 x 1024, sRGB): continents, ice and clouds from 3D value
  noise on the sphere (no seam at the date line), in the near-grey tones of
  Military-Industrial Noir: art-pipeline 8.3 bans blue and cyan pixels in a rendered
  view, so the oceans are slate, not blue;
* ``T_Space_Stars_E`` (2048 x 1024, sRGB): a black sky with white and warm stars and a
  faint band.

Today's three.js Earth uses NASA imagery, which is public domain but not CC0; the ledger
(`art/verse/LICENSES.md`, art-pipeline 11) takes CC0 only, so the Unreal view uses these.

The texture import (`verse_pipeline.import_textures`) lands with WP14, and the art text
gate fails a record whose asset is not imported, so the records are written only with
`--records`, in the PR that imports them:

    python art/verse/kit/props/space/space_textures.py             # write the PNGs
    python art/verse/kit/props/space/space_textures.py --records   # and their import records
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve()
REPO_ROOT = HERE.parents[5]
CACHE = REPO_ROOT / "art" / "verse" / ".cache" / "unreal" / "kit" / "space"
RECORDS = REPO_ROOT / "unreal" / "Verse" / "Art" / "Import" / "Kit" / "Space"
FOLDER = "/Game/Verse/Kit/Space"
WIDTH, HEIGHT = 2048, 1024
SEED = 1207
#: Share of the sphere that is land, and where the ice caps start (|latitude|, degrees).
LAND_SHARE = 0.31
ICE_LAT_DEG = 66.0

#: Noir Earth colours, sRGB 0-255 (saturation below 0.25 or hues outside the banned band).
OCEAN_DEEP = (19, 21, 23)
OCEAN_SHELF = (34, 37, 39)
LAND_LOW = (58, 55, 48)
LAND_HIGH = (96, 90, 80)
ICE = (198, 199, 198)
CLOUD = (214, 214, 212)


def _lattice(seed: int, size: int = 256) -> np.ndarray:
    return np.random.default_rng(seed).random((size, size, size), dtype=np.float32)


def value_noise(points: np.ndarray, frequency: float, lattice: np.ndarray) -> np.ndarray:
    """Trilinear value noise at 3D points (N, 3) in [-1, 1], smoothstep weights."""
    size = lattice.shape[0]
    p = (points + 1.0) * 0.5 * frequency
    i0 = np.floor(p).astype(np.int64)
    f = p - i0
    w = f * f * (3.0 - 2.0 * f)
    out = np.zeros(points.shape[0], dtype=np.float32)
    for dx in (0, 1):
        for dy in (0, 1):
            for dz in (0, 1):
                ix = (i0[:, 0] + dx) % size
                iy = (i0[:, 1] + dy) % size
                iz = (i0[:, 2] + dz) % size
                weight = (
                    (w[:, 0] if dx else 1 - w[:, 0])
                    * (w[:, 1] if dy else 1 - w[:, 1])
                    * (w[:, 2] if dz else 1 - w[:, 2])
                )
                out += weight * lattice[ix, iy, iz]
    return out


def fbm(points: np.ndarray, base: float, octaves: int, seed: int) -> np.ndarray:
    total = np.zeros(points.shape[0], dtype=np.float32)
    amplitude, norm = 1.0, 0.0
    for octave in range(octaves):
        lattice = _lattice(seed + octave)
        total += amplitude * value_noise(points, base * 2.0**octave, lattice)
        norm += amplitude
        amplitude *= 0.5
    return total / norm


def sphere_points(width: int, height: int) -> tuple[np.ndarray, np.ndarray]:
    """Unit vectors of every pixel centre and the latitude (radians) per pixel."""
    lon = (np.arange(width) + 0.5) / width * 2.0 * np.pi - np.pi
    lat = np.pi / 2.0 - (np.arange(height) + 0.5) / height * np.pi
    lon, lat = np.meshgrid(lon, lat)
    xyz = np.stack(
        [np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)], axis=-1
    ).reshape(-1, 3)
    return xyz.astype(np.float32), lat


def _mix(a, b, t):
    t = np.clip(t, 0.0, 1.0)[..., None]
    return np.asarray(a, np.float32) * (1.0 - t) + np.asarray(b, np.float32) * t


def earth(width: int = WIDTH, height: int = HEIGHT) -> Image.Image:
    xyz, lat = sphere_points(width, height)
    shape = (height, width)
    warp = fbm(xyz * 1.0, 3.0, 3, SEED + 50).reshape(-1, 1) - 0.5
    land_noise = fbm(xyz + warp * 0.6, 2.2, 6, SEED).reshape(shape)
    level = np.quantile(land_noise, 1.0 - LAND_SHARE)
    height_above = (land_noise - level) / max(1e-6, float(land_noise.max() - level))
    detail = fbm(xyz, 24.0, 3, SEED + 20).reshape(shape)
    ocean = _mix(OCEAN_DEEP, OCEAN_SHELF, (land_noise - (level - 0.06)) / 0.06)
    land = _mix(LAND_LOW, LAND_HIGH, height_above * 1.4 + (detail - 0.5) * 0.5)
    image = np.where((land_noise > level)[..., None], land, ocean)
    abs_lat = np.degrees(np.abs(lat))
    ice = np.clip((abs_lat - ICE_LAT_DEG + (detail - 0.5) * 8.0) / 4.0, 0.0, 1.0)
    image = _mix(image, ICE, ice)
    clouds = fbm(xyz * 1.0 + warp, 5.0, 6, SEED + 90).reshape(shape)
    cover = np.clip((clouds - 0.52) / 0.18, 0.0, 1.0) ** 1.4
    image = _mix(image, CLOUD, cover * 0.85)
    return Image.fromarray(np.clip(np.round(image), 0, 255).astype(np.uint8), "RGB")


def stars(width: int = WIDTH, height: int = HEIGHT) -> Image.Image:
    rng = np.random.default_rng(SEED + 7)
    sky = np.zeros((height, width, 3), dtype=np.float32)
    xyz, lat = sphere_points(width, height)
    band = np.exp(-((xyz[:, 2] * 0.9 + xyz[:, 0] * 0.44) ** 2) / 0.02).reshape(height, width)
    haze = fbm(xyz, 6.0, 4, SEED + 30).reshape(height, width)
    sky += (band * haze * 18.0)[..., None]
    count = 9000
    # Uniform on the sphere: latitude from arcsin of a uniform z.
    rows = ((np.pi / 2 - np.arcsin(rng.uniform(-1, 1, count))) / np.pi * height).astype(int)
    cols = rng.integers(0, width, count)
    rows = np.clip(rows, 0, height - 1)
    brightness = 255.0 * rng.power(0.12, count) ** 2.2 + 30.0
    warm = rng.random(count) < 0.35
    colour = np.where(warm[:, None], [[1.0, 0.92, 0.8]], [[1.0, 1.0, 0.98]])
    sky[rows, cols] = np.maximum(sky[rows, cols], colour * brightness[:, None])
    return Image.fromarray(np.clip(np.round(sky), 0, 255).astype(np.uint8), "RGB")


TEXTURES = {"T_Space_Earth_E": ("earth", earth), "T_Space_Stars_E": ("stars", stars)}


def record(name: str, function: str, png: Path) -> dict:
    digest = hashlib.sha256(png.read_bytes()).hexdigest()
    return {
        "schema": "verse.import/1",
        "name": name,
        "asset_path": f"{FOLDER}/{name}.{name}",
        "kind": "texture",
        "source": {
            "builder": HERE.relative_to(REPO_ROOT).as_posix(),
            "function": function,
            "args": {"width": WIDTH, "height": HEIGHT, "seed": SEED},
        },
        "export": {
            "format": "png",
            "settings_id": "png-ue/1",
            "file": png.relative_to(REPO_ROOT).as_posix(),
            "sha256": digest,
            "blender": "5.0.1",
        },
        "texture": {
            "group": "World",
            "max_size": 2048,
            "srgb": True,
            "compression": "Default",
            "flip_green": False,
        },
        "lightmap": "none",
        "license": {"kind": "own"},
        "owner": "WP12",
    }


def dumps(doc: dict) -> str:
    return json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def write_all(*, check: bool = False, records: bool = False) -> list[str]:
    stale = []
    CACHE.mkdir(parents=True, exist_ok=True)
    for name, (function, make) in TEXTURES.items():
        png = CACHE / f"{name}.png"
        make().save(png, optimize=False, compress_level=6)
        print(f"[verse] wrote {png.relative_to(REPO_ROOT).as_posix()}")
        if not records:
            continue
        path = RECORDS / f"{name}.import.json"
        text = dumps(record(name, function, png))
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
    options = parser.parse_args(argv)
    stale = write_all(check=options.check, records=options.records or options.check)
    for path in stale:
        print(f"[verse] {'stale' if options.check else 'wrote'} {path}")
    return 1 if options.check and stale else 0


if __name__ == "__main__":
    sys.exit(main())
