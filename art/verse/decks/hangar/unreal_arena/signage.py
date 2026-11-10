"""Stencil masks for the hangar arena's signage decals (WP11, arena.md 9.2).

Own work: each mask is text or a symbol drawn with the repo's licensed stencil
font (JetBrains Mono Bold, `unreal/Verse/Art/Fonts`, OFL, ledger "Fonts"),
roughened along the edges like sprayed paint. White is paint (R), black is
bare. Writes `art/verse/.cache/unreal/textures/arena/T_Arena_Sign_<Name>_M.png`
and one `verse.import/1` texture record per mask.

    python art/verse/decks/hangar/unreal_arena/signage.py
"""

from __future__ import annotations

import hashlib
import json
import random
import sys
from pathlib import Path

VERSE = Path(__file__).resolve().parents[3]
REPO = VERSE.parents[1]
FONT = REPO / "unreal" / "Verse" / "Art" / "Fonts" / "JetBrainsMono" / "JetBrainsMono-Bold.ttf"
OUT = VERSE / ".cache" / "unreal" / "textures" / "arena"
RECORDS = REPO / "unreal" / "Verse" / "Art" / "Import" / "Textures" / "Arena"

#: Mask name -> (text, width, height). Fictional hall markings only.
SIGNS: dict[str, tuple[str, int, int]] = {
    "Bay": ("BAY 04", 1024, 256),
    "KeepClear": ("KEEP CLEAR", 1024, 256),
    "NoStep": ("NO STEP", 1024, 256),
    "Lift": ("LIFT ZONE", 1024, 256),
    "Deck": ("D4", 512, 512),
    "Arrow": (">>>", 1024, 256),
    "Row1": ("R1", 512, 512),
    "Row2": ("R2", 512, 512),
    "Row3": ("R3", 512, 512),
}


def draw(text: str, width: int, height: int, seed: int):
    from PIL import Image, ImageDraw, ImageFilter, ImageFont

    image = Image.new("L", (width, height), 0)
    pen = ImageDraw.Draw(image)
    size = int(height * 0.78)
    font = ImageFont.truetype(str(FONT), size)
    while pen.textlength(text, font=font) > width * 0.9 and size > 8:
        size -= 4
        font = ImageFont.truetype(str(FONT), size)
    box = pen.textbbox((0, 0), text, font=font)
    x = (width - (box[2] - box[0])) / 2 - box[0]
    y = (height - (box[3] - box[1])) / 2 - box[1]
    pen.text((x, y), text, fill=255, font=font)
    # Stencil bridges: thin horizontal gaps through every glyph, as cut stencils have.
    for gap in (0.47, 0.53):
        pen.rectangle((0, int(height * gap) - 2, width, int(height * gap) + 2), fill=0)
    # Sprayed, worn paint: soft edge, then speckled loss.
    image = image.filter(ImageFilter.GaussianBlur(1.6))
    rng = random.Random(seed)  # noqa: S311 - seeded wear pattern, not security
    px = image.load()
    for _ in range(width * height // 18):
        u, v = rng.randrange(width), rng.randrange(height)
        px[u, v] = int(px[u, v] * rng.uniform(0.15, 0.8))
    return image.filter(ImageFilter.GaussianBlur(0.6))


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    RECORDS.mkdir(parents=True, exist_ok=True)
    for index, (name, (text, width, height)) in enumerate(sorted(SIGNS.items())):
        asset = f"T_Arena_Sign_{name}_M"
        png = OUT / f"{asset}.png"
        draw(text, width, height, seed=4242 + index).save(png, optimize=True)
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
                "args": {"text": text},
                "builder": "art/verse/decks/hangar/unreal_arena/signage.py",
                "function": "main",
            },
            "texture": {
                "channels": {"r": "paint coverage"},
                "compression": "Grayscale",
                "flip_green": False,
                "group": "World",
                "max_size": 1024,
                "srgb": False,
            },
        }
        text_json = json.dumps(doc, indent=2, sort_keys=True) + "\n"
        (RECORDS / f"{asset}.import.json").write_bytes(text_json.encode("utf-8"))
        print(f"[verse] {asset}: {text}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
