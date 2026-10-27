"""Bake the textures of the Earth seen through the Verse's viewports.

Sources are NASA imagery in the public domain (NASA Visible Earth):

* day:    Blue Marble Next Generation, topography + bathymetry, July 2004
* night:  Black Marble 2016 (city lights)
* clouds: Blue Marble cloud composite
* relief: GEBCO 08 elevation (land) and bathymetry (water mask)

Usage::

    python scripts/verse/earth.py --src <dir with the downloads> [--size 8192]

``--fetch`` downloads the sources into ``--src`` first. Writes WebP files to
dodaios/ui/web/frontend/public/verse/space/ (equirectangular, longitude -180
at the left edge, north at the top):

* earth_day.webp     RGB colour (sRGB)
* earth_night.webp   RGB city lights (sRGB), half size
* earth_clouds.webp  cloud cover in R (linear), full size
* earth_relief.webp  R,G = tangent-space slope of the terrain (0.5 = flat),
                     B = water (255 = open water), half size
"""

from __future__ import annotations

import argparse
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "dodaios/ui/web/frontend/public/verse/space"

SOURCES = {
    "day.jpg": "https://eoimages.gsfc.nasa.gov/images/imagerecords/73000/73751/world.topo.bathy.200407.3x21600x10800.jpg",
    "night.jpg": "https://eoimages.gsfc.nasa.gov/images/imagerecords/144000/144898/BlackMarble_2016_3km.jpg",
    "clouds.tif": "https://eoimages.gsfc.nasa.gov/images/imagerecords/57000/57747/cloud_combined_8192.tif",
    "topo.png": "https://eoimages.gsfc.nasa.gov/images/imagerecords/73000/73934/gebco_08_rev_elev_21600x10800.png",
    "water.png": "https://eoimages.gsfc.nasa.gov/images/imagerecords/73000/73963/gebco_08_rev_bath_21600x10800.png",
}


def fetch(src: Path) -> None:
    src.mkdir(parents=True, exist_ok=True)
    for name, url in SOURCES.items():
        target = src / name
        if not target.exists():
            print(f"[earth] fetch {name}", flush=True)
            urllib.request.urlretrieve(url, target)  # noqa: S310 (fixed https URLs)


def resized(path: Path, size: int, mode: str) -> Image.Image:
    image = Image.open(path).convert(mode)
    return image.resize((size, size // 2), Image.Resampling.LANCZOS)


def save(image: Image.Image, name: str, quality: int) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / name
    image.save(target, "WEBP", quality=quality, method=6)
    mb = target.stat().st_size / 1e6
    print(f"[earth] {name} {image.size[0]}x{image.size[1]} {mb:.2f} MB", flush=True)


def relief(src: Path, size: int) -> Image.Image:
    """Terrain slope from the elevation (R, G) and the water mask (B)."""
    height = np.asarray(resized(src / "topo.png", size, "L"), dtype=np.float32) / 255.0
    # The source spans 0-6400 m in 255 steps; this is about how steep the
    # mountains read under a low sun, not a physical scale.
    strength = 6.0 * size / 4096
    dx = (np.roll(height, -1, axis=1) - np.roll(height, 1, axis=1)) * strength
    dy = (np.roll(height, -1, axis=0) - np.roll(height, 1, axis=0)) * strength
    dy[0, :] = 0
    dy[-1, :] = 0
    # Longitude shrinks towards the poles: the same step east is shorter there.
    lat = (0.5 - (np.arange(height.shape[0]) + 0.5) / height.shape[0]) * np.pi
    dx /= np.maximum(np.cos(lat), 0.05)[:, None]
    red = np.clip(0.5 - dx * 0.5, 0, 1)
    green = np.clip(0.5 + dy * 0.5, 0, 1)
    bath = np.asarray(resized(src / "water.png", size, "L"), dtype=np.float32) / 255.0
    # The bathymetry is white over land and darker with depth over water.
    water = np.clip((0.995 - bath) * 60.0, 0, 1)
    rgb = np.stack([red, green, water], axis=-1)
    return Image.fromarray((rgb * 255 + 0.5).astype(np.uint8), "RGB")


def city_lights(src: Path, size: int) -> Image.Image:
    """Only the lights of Black Marble: its moonlit blue land and sea drop out."""
    night = np.asarray(resized(src / "night.jpg", size, "RGB"), dtype=np.float32) / 255.0
    # The moonlit ground is blue (blue above red); lights are warm and bright.
    light = np.clip((night[..., 0] - 0.85 * night[..., 2] + 0.02) * 2.2, 0, 1) ** 1.3
    tint = np.array([1.0, 0.78, 0.5], dtype=np.float32)
    rgb = light[..., None] * tint
    return Image.fromarray((rgb * 255 + 0.5).astype(np.uint8), "RGB")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--src", type=Path, required=True)
    parser.add_argument("--size", type=int, default=8192)
    parser.add_argument("--fetch", action="store_true")
    args = parser.parse_args()
    if args.fetch:
        fetch(args.src)
    size = args.size
    save(resized(args.src / "day.jpg", size, "RGB"), "earth_day.webp", 88)
    save(city_lights(args.src, size // 2), "earth_night.webp", 85)
    save(resized(args.src / "clouds.tif", size, "L").convert("RGB"), "earth_clouds.webp", 72)
    save(relief(args.src, size // 2), "earth_relief.webp", 90)


if __name__ == "__main__":
    main()
