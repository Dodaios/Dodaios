#!/usr/bin/env python3
"""Render the HUD item icons of the Unreal Verse from the weapon meshes.

    python scripts/verse/hud_icons.py [--raw DIR] [--skip-render]

1. Blender (`art/verse/weapons/_icons_entry.py`) builds every weapon and
   gadget and renders a flat mask and a shaded pass of its readable side.
2. This script closes hairline gaps between parts, keeps the panel lines as
   a faint shade inside the white silhouette, trims the margin and writes
   `unreal/Verse/Data/ui/icons/<item>_<height>.png` at a few heights. The
   HUD picks the smallest one at least as tall as the drawn icon and tints
   it, so the pixels are white with the shade in RGB and the shape in alpha.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "unreal" / "Verse" / "Data" / "ui" / "icons"
ENTRY = REPO_ROOT / "art" / "verse" / "weapons" / "_icons_entry.py"
#: Items rendered from their meshes.
RENDERED = ("graveline", "tallow", "hookbill", "skitter", "longsight")
#: Gadgets read badly from any side of their mesh: drawn as pictograms.
DRAWN = ("bulwark", "breach_charge")
ITEMS = RENDERED + DRAWN
HEIGHTS = (32, 64, 128)
#: Darkest shade inside the silhouette (1 = flat white).
SHADE_FLOOR = 0.62
#: Gap closing radius as a share of the image width.
CLOSE_SHARE = 0.004
#: Items whose parts sit further apart (the pistol grip under its frame).
CLOSE_SHARE_BY_ITEM = {"tallow": 0.02}
#: Pictogram canvas (supersampled, then scaled down).
PICTO = 1024


def _render(raw: Path) -> None:
    sys.path.insert(0, str(REPO_ROOT))
    from scripts.verse import blender

    blender.main(["run", "--no-lock", str(ENTRY), "--out", str(raw)])


def _close(mask: Image.Image, radius: int) -> Image.Image:
    size = radius * 2 + 1
    return mask.filter(ImageFilter.MaxFilter(size)).filter(ImageFilter.MinFilter(size))


def compose(raw: Path, item: str) -> Image.Image:
    mask = Image.open(raw / f"{item}_mask.png").convert("RGBA").getchannel("A")
    shade = Image.open(raw / f"{item}_shade.png").convert("RGBA")
    # Fill hairline gaps between parts so the silhouette reads as one object.
    radius = max(1, round(mask.width * CLOSE_SHARE_BY_ITEM.get(item, CLOSE_SHARE)))
    alpha = _close(mask, radius)
    # Panel detail: the studio luminance, lifted towards white, only where the
    # model itself is (closed gaps stay plain white).
    lum = shade.convert("L")
    lift = lum.point(lambda v: int(255 * (SHADE_FLOOR + (1 - SHADE_FLOOR) * min(1.0, v / 235))))
    plain = Image.new("L", mask.size, 255)
    detail = Image.composite(lift, plain, mask.point(lambda v: 255 if v > 128 else 0))
    out = Image.merge("RGBA", (detail, detail, detail, alpha))
    box = ImageChops.difference(alpha, Image.new("L", alpha.size, 0)).getbbox()
    return out.crop(box) if box else out


def _picto(draw_fn) -> Image.Image:
    alpha = Image.new("L", (PICTO, PICTO), 0)
    shade = Image.new("L", (PICTO, PICTO), 255)
    draw_fn(ImageDraw.Draw(alpha), ImageDraw.Draw(shade))
    out = Image.merge("RGBA", (shade, shade, shade, alpha))
    box = alpha.getbbox()
    return out.crop(box) if box else out


def _shield(a: ImageDraw.ImageDraw, s: ImageDraw.ImageDraw) -> None:
    """Bulwark: a heater shield with a raised rim and a centre ridge."""
    outline = [(112, 96), (512, 32), (912, 96), (912, 520), (512, 992), (112, 520)]
    a.polygon(outline, fill=255)
    inner = [(212, 172), (512, 124), (812, 172), (812, 500), (512, 852), (212, 500)]
    s.polygon(inner, fill=226)
    s.polygon([(492, 128), (532, 128), (532, 846), (492, 846)], fill=255)


def _charge(a: ImageDraw.ImageDraw, s: ImageDraw.ImageDraw) -> None:
    """Breach charge: a slab with a detonator and its wire."""
    a.rounded_rectangle((64, 330, 960, 900), radius=48, fill=255)
    a.rectangle((400, 190, 624, 330), fill=255)
    a.rectangle((470, 110, 554, 190), fill=255)
    s.rounded_rectangle((136, 400, 888, 830), radius=24, fill=228)
    for x in (230, 400, 570, 740):
        s.rectangle((x, 440, x + 54, 790), fill=255)


PICTOGRAMS = {"bulwark": _shield, "breach_charge": _charge}


def write(icon: Image.Image, item: str, out_dir: Path) -> list[Path]:
    paths = []
    for height in HEIGHTS:
        width = max(1, round(icon.width * height / icon.height))
        # Premultiply before scaling so edges do not pick up dark fringes.
        small = icon.convert("RGBa").resize((width, height), Image.LANCZOS).convert("RGBA")
        path = out_dir / f"{item}_{height}.png"
        small.save(path, optimize=True)
        paths.append(path)
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw", type=Path, help="keep the Blender passes here")
    parser.add_argument("--skip-render", action="store_true", help="reuse the passes in --raw")
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    options = parser.parse_args(argv)
    with tempfile.TemporaryDirectory() as tmp:
        raw = options.raw or Path(tmp)
        if not options.skip_render:
            _render(raw)
        options.out.mkdir(parents=True, exist_ok=True)
        for item in ITEMS:
            icon = _picto(PICTOGRAMS[item]) if item in DRAWN else compose(raw, item)
            for path in write(icon, item, options.out):
                print(f"[hud-icons] {path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
