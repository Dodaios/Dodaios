"""Wear masks for the hangar's grime decals (WP11, arena.md 9.3).

Own work: seeded noise drawn with Pillow. White is coverage (R), black is
bare. Each mask feeds one `M_Verse_Decal` instance:

- Puddle: standing water with ragged shores (low roughness: reflects the lights).
- Leak: rust and oil streaks running down a wall from a seam.
- Grime: blotchy dirt build-up at the foot of walls and around equipment.
- Tyre: the double track of a tow tug's wheels, worn into the deck.

Writes `art/verse/.cache/unreal/textures/arena/T_Arena_Wear_<Name>_M.png` and one
`verse.import/1` texture record per mask.

    python art/verse/decks/hangar/unreal_arena/grime.py
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import sys
from pathlib import Path

VERSE = Path(__file__).resolve().parents[3]
REPO = VERSE.parents[1]
OUT = VERSE / ".cache" / "unreal" / "textures" / "arena"
RECORDS = REPO / "unreal" / "Verse" / "Art" / "Import" / "Textures" / "Arena"
SIZE = 1024


def _noise(rng: random.Random, size: int, octaves: tuple[int, ...]):
    """Value noise in 0..255 as an 'L' image: sum of upscaled random grids."""
    from PIL import Image, ImageChops

    out = Image.new("L", (size, size), 0)
    weight = 1.0
    total = 0.0
    layers = []
    for cells in octaves:
        grid = Image.new("L", (cells, cells))
        grid.putdata([rng.randrange(256) for _ in range(cells * cells)])
        layers.append((grid.resize((size, size), Image.Resampling.BICUBIC), weight))
        total += weight
        weight *= 0.5
    for layer, w in layers:
        out = ImageChops.add(out, layer.point(lambda v, w=w: int(v * w / total)))
    return out


def _radial(size: int, power: float = 1.6):
    from PIL import Image

    image = Image.new("L", (size, size))
    c = (size - 1) / 2
    image.putdata(
        [
            int(255 * max(0.0, 1.0 - (math.hypot(x - c, y - c) / c) ** power))
            for y in range(size)
            for x in range(size)
        ]
    )
    return image


def puddle(rng: random.Random):
    from PIL import ImageChops, ImageFilter

    n = _noise(rng, SIZE, (4, 9, 21, 48))
    shaped = ImageChops.multiply(n, _radial(SIZE, 1.3)).point(lambda v: 255 if v > 70 else 0)
    return shaped.filter(ImageFilter.GaussianBlur(5))


def leak(rng: random.Random):
    from PIL import Image, ImageDraw, ImageFilter

    image = Image.new("L", (SIZE, SIZE), 0)
    pen = ImageDraw.Draw(image)
    for _ in range(38):
        x = rng.gauss(SIZE / 2, SIZE / 7)
        length = rng.uniform(0.25, 0.95) * SIZE
        width = rng.uniform(3, 18)
        strength = rng.uniform(0.35, 1.0)
        steps = 40
        for i in range(steps):
            t = i / steps
            y0, y1 = t * length, (t + 1 / steps) * length
            fade = int(255 * strength * (1.0 - t) ** 1.4)
            wobble = rng.uniform(-1.5, 1.5)
            pen.rectangle((x + wobble - width / 2, y0, x + wobble + width / 2, y1), fill=fade)
        width *= 0.9
    # A soaked band along the seam the streaks start from.
    pen.rectangle((0, 0, SIZE, 12), fill=90)
    return image.filter(ImageFilter.GaussianBlur(3))


def grime(rng: random.Random):
    from PIL import ImageChops, ImageFilter

    n = _noise(rng, SIZE, (3, 7, 17, 41, 97))
    return ImageChops.multiply(
        n.point(lambda v: max(0, min(255, (v - 60) * 2))), _radial(SIZE, 2.2)
    ).filter(ImageFilter.GaussianBlur(2))


def tyre(rng: random.Random):
    from PIL import Image, ImageChops, ImageDraw, ImageFilter

    image = Image.new("L", (SIZE, SIZE), 0)
    pen = ImageDraw.Draw(image)
    bend = rng.uniform(-0.25, 0.25)
    for lane in (0.36, 0.64):
        for i in range(SIZE):
            y = i
            x = SIZE * lane + bend * SIZE * (i / SIZE - 0.5) ** 2 * 2
            pen.rectangle((x - 34, y, x + 34, y + 1), fill=150 + int(rng.uniform(-40, 40)))
    n = _noise(rng, SIZE, (8, 23, 61))
    image = ImageChops.multiply(image, n.point(lambda v: min(255, v + 90)))
    ends = Image.new("L", (SIZE, SIZE))
    ends.putdata(
        [int(255 * math.sin(math.pi * y / SIZE) ** 0.7) for y in range(SIZE) for _ in range(SIZE)]
    )
    return ImageChops.multiply(image, ends).filter(ImageFilter.GaussianBlur(2.5))


MASKS = {"Puddle": puddle, "Leak": leak, "Grime": grime, "Tyre": tyre}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    RECORDS.mkdir(parents=True, exist_ok=True)
    for index, (name, draw) in enumerate(sorted(MASKS.items())):
        asset = f"T_Arena_Wear_{name}_M"
        png = OUT / f"{asset}.png"
        draw(random.Random(7700 + index)).save(png, optimize=True)  # noqa: S311 - seeded art
        doc = {
            "asset_path": f"/Game/Verse/Textures/Arena/{asset}.{asset}",
            "export": {
                "blender": "0.0.0",
                "file": png.relative_to(REPO).as_posix(),
                "format": "png",
                "settings_id": "png-ue/1",
                "sha256": hashlib.sha256(png.read_bytes()).hexdigest(),
            },
            "kind": "texture",
            "license": {"kind": "own"},
            "lightmap": "none",
            "name": asset,
            "owner": "WP11",
            "schema": "verse.import/1",
            "source": {
                "args": {"mask": name},
                "builder": "art/verse/decks/hangar/unreal_arena/grime.py",
                "function": "main",
            },
            "texture": {
                "channels": {"r": "coverage"},
                "compression": "Grayscale",
                "flip_green": False,
                "group": "World",
                "max_size": SIZE,
                "srgb": False,
            },
        }
        text = json.dumps(doc, indent=2, sort_keys=True) + "\n"
        (RECORDS / f"{asset}.import.json").write_bytes(text.encode("utf-8"))
        print(f"[verse] {asset}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
