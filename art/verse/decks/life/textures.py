"""Material texture sets of the deck look pass (WP12): seats, fabric, rubber, brushed metal.

Two sets are CC0 scans from Poly Haven, fetched through `lib.textures.ensure`
(MD5 check, one append-only row per file in `art/verse/LICENSES.md`):

- Leather: `brown_leather`, stored as luminance so the MI tint picks the hide colour.
- Fabric: `denim_fabric_04`, a woven grain, stored as luminance as well.

Two are own work, drawn with Pillow, because no CC0 scan fits:

- Brushed: fine anisotropic streaks of brushed steel (console trim, rails, fittings).
- Rubber: matte micro grain with a few scuffs (mats, grips, cable jackets).

Writes PNGs to `art/verse/.cache/unreal/textures/decklife/` and one `verse.import/1`
record per map under `unreal/Verse/Art/Import/Textures/DeckLife/`
(`/Game/Verse/Textures/DeckLife/T_Deck_<Set>_<BC|N|ORM>`).

    python art/verse/decks/life/textures.py
"""

from __future__ import annotations

import hashlib
import json
import random
import sys
from pathlib import Path

VERSE = Path(__file__).resolve().parents[2]
REPO = VERSE.parents[1]
if str(VERSE) not in sys.path:
    sys.path.insert(0, str(VERSE))

OUT = VERSE / ".cache" / "unreal" / "textures" / "decklife"
RECORDS = REPO / "unreal" / "Verse" / "Art" / "Import" / "Textures" / "DeckLife"
SIZE = 1024

#: Set name -> Poly Haven asset (CC0); the colour map is stored as luminance.
SCANNED = {"Leather": "brown_leather", "Fabric": "denim_fabric_04"}
#: Poly Haven map key -> (suffix, sRGB, compression, flip green).
MAPS: dict[str, tuple[str, bool, str, bool]] = {
    "Diffuse": ("BC", True, "Default", False),
    "arm": ("ORM", False, "Masks", False),
    "nor_gl": ("N", False, "Normalmap", True),
}
SUFFIX = {suffix: (srgb, compression) for suffix, srgb, compression, _flip in MAPS.values()}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _record(name: str, set_name: str, suffix: str, png: Path, source: dict, license_: dict) -> dict:
    srgb, compression = SUFFIX[suffix]
    return {
        "asset_path": f"/Game/Verse/Textures/DeckLife/{name}.{name}",
        "export": {
            "blender": "0.0.0",
            "file": png.relative_to(REPO).as_posix(),
            "format": "png",
            "settings_id": "png-ue/1",
            "sha256": _sha256(png),
        },
        "kind": "texture",
        "license": license_,
        "lightmap": "none",
        "name": name,
        "owner": "WP12",
        "schema": "verse.import/1",
        "source": {
            "args": {"set": set_name, **source},
            "builder": "art/verse/decks/life/textures.py",
            "function": "main",
        },
        "texture": {
            "compression": compression,
            "flip_green": suffix == "N",
            "group": "WorldNormalMap" if suffix == "N" else "World",
            "max_size": SIZE,
            "srgb": srgb,
        },
    }


def _write(name: str, doc: dict) -> None:
    text = json.dumps(doc, indent=2, sort_keys=True) + "\n"
    (RECORDS / f"{name}.import.json").write_bytes(text.encode("utf-8"))
    print(f"[verse] {name}")


def _noise(rng: random.Random, w: int, h: int, cells_x: int, cells_y: int):
    """Upscaled random grid as an 'L' image."""
    from PIL import Image

    grid = Image.new("L", (cells_x, cells_y))
    grid.putdata([rng.randrange(256) for _ in range(cells_x * cells_y)])
    return grid.resize((w, h), Image.Resampling.BICUBIC)


def _normal_from_height(height, strength: float):
    """Tangent-space normal map (OpenGL green, flipped on import) from an 'L' height image."""
    from PIL import Image, ImageChops

    shifted_x = ImageChops.offset(height, 1, 0)
    shifted_y = ImageChops.offset(height, 0, 1)
    hx, hy, sx, sy = (list(i.tobytes()) for i in (height, height, shifted_x, shifted_y))
    pixels = []
    for a, b, c, d in zip(hx, sx, hy, sy, strict=True):
        dx = (a - b) / 255.0 * strength
        dy = (c - d) / 255.0 * strength
        length = (dx * dx + dy * dy + 1.0) ** 0.5
        pixels.append(
            (
                int(128 + 127 * dx / length),
                int(128 + 127 * dy / length),
                int(128 + 127 * 1.0 / length),
            )
        )
    image = Image.new("RGB", height.size)
    image.putdata(pixels)
    return image


def _orm(ao, roughness, metallic: int):
    from PIL import Image

    return Image.merge("RGB", (ao, roughness, Image.new("L", ao.size, metallic)))


def brushed(rng: random.Random):
    """Brushed steel: long horizontal streaks over a faint mottling."""
    from PIL import Image, ImageChops

    streaks = _noise(rng, SIZE, SIZE, 6, 700)
    fine = _noise(rng, SIZE, SIZE, 3, 1024)
    height = ImageChops.blend(streaks, fine, 0.5)
    mottle = _noise(rng, SIZE, SIZE, 8, 8)
    colour = ImageChops.blend(height, mottle, 0.3).point(lambda v: 150 + (v - 128) // 4)
    roughness = ImageChops.blend(height, mottle, 0.5).point(lambda v: 80 + (v - 128) // 3)
    ao = Image.new("L", (SIZE, SIZE), 255)
    return colour.convert("RGB"), _normal_from_height(height, 1.2), _orm(ao, roughness, 255)


def rubber(rng: random.Random):
    """Matte rubber: dense micro grain, a few lighter scuffs."""
    from PIL import Image, ImageChops, ImageDraw

    grain = _noise(rng, SIZE, SIZE, 400, 400)
    soft = _noise(rng, SIZE, SIZE, 12, 12)
    height = ImageChops.blend(grain, soft, 0.3)
    scuffs = Image.new("L", (SIZE, SIZE), 0)
    draw = ImageDraw.Draw(scuffs)
    for _ in range(40):
        x, y = rng.uniform(0, SIZE), rng.uniform(0, SIZE)
        length, width = rng.uniform(20, 120), rng.randint(1, 3)
        draw.line((x, y, x + length, y + rng.uniform(-8, 8)), fill=rng.randint(40, 90), width=width)
    colour = ImageChops.add(grain.point(lambda v: 110 + (v - 128) // 8), scuffs)
    roughness = ImageChops.subtract(grain.point(lambda v: 225 + (v - 128) // 10), scuffs)
    ao = soft.point(lambda v: 225 + (v - 128) // 6)
    return colour.convert("RGB"), _normal_from_height(height, 0.8), _orm(ao, roughness, 0)


PROCEDURAL = {"Brushed": brushed, "Rubber": rubber}


def main() -> int:
    from lib import textures
    from PIL import Image

    OUT.mkdir(parents=True, exist_ok=True)
    RECORDS.mkdir(parents=True, exist_ok=True)
    for set_name, asset in SCANNED.items():
        paths = textures.ensure(asset, list(MAPS), res="1k")
        for key, source in paths.items():
            suffix = MAPS[key][0]
            name = f"T_Deck_{set_name}_{suffix}"
            png = OUT / f"{name}.png"
            with Image.open(source) as image:
                image = (
                    image.convert("L").convert("RGB") if suffix == "BC" else image.convert("RGB")
                )
                if max(image.size) > SIZE:
                    image = image.resize((SIZE, SIZE), Image.Resampling.LANCZOS)
                image.save(png, optimize=True)
            license_ = {"kind": "ledger", "ledger_sha256": [_sha256(source)]}
            _write(
                name, _record(name, set_name, suffix, png, {"asset": asset, "map": key}, license_)
            )
    for set_name, build in PROCEDURAL.items():
        rng = random.Random(f"verse-deck-{set_name}")  # noqa: S311 - seeded art, not crypto
        for suffix, image in zip(("BC", "N", "ORM"), build(rng), strict=True):
            name = f"T_Deck_{set_name}_{suffix}"
            png = OUT / f"{name}.png"
            image.save(png, optimize=True)
            _write(name, _record(name, set_name, suffix, png, {}, {"kind": "own"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
