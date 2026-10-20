"""Assemble the industrial props lookdev renders into one contact sheet.

Runs outside Blender (venv Python with Pillow):

    python art/verse/kit/props/industrial/contact_sheet.py

Reads art/verse/.cache/lookdev/props-industrial/*.png (written by lookdev.py)
and writes SHEET_props-industrial.png next to them: every piece's full render
beside its crop, labelled with the piece name and pixel density.
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parents[3] / ".cache" / "lookdev" / "props-industrial"
CELL_W, CELL_H = 760, 430
LABEL_H = 28
COLS = 3
BG = (16, 17, 19)
FG = (210, 212, 215)


def _fit(img: Image.Image, w: int, h: int) -> Image.Image:
    img = img.copy()
    img.thumbnail((w, h), Image.LANCZOS)
    return img


def _font(size: int):
    for name in ("bahnschrift.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def main() -> None:
    stats = {}
    stats_path = OUT / "stats.json"
    if stats_path.exists():
        stats = {s["piece"]: s for s in json.loads(stats_path.read_text())}
    pieces = sorted(p.stem for p in OUT.glob("SM_*.png") if "__crop" not in p.stem)
    rows = (len(pieces) + COLS - 1) // COLS
    sheet = Image.new("RGB", (COLS * CELL_W, rows * (CELL_H + LABEL_H)), BG)
    draw = ImageDraw.Draw(sheet)
    font = _font(17)
    for i, name in enumerate(pieces):
        x0 = (i % COLS) * CELL_W
        y0 = (i // COLS) * (CELL_H + LABEL_H)
        full = Image.open(OUT / f"{name}.png").convert("RGB")
        crops = sorted(OUT.glob(f"{name}__crop*.png"))
        if crops:
            left = _fit(full, CELL_W * 3 // 5 - 6, CELL_H - 6)
            right = _fit(Image.open(crops[0]).convert("RGB"), CELL_W * 2 // 5 - 6, CELL_H - 6)
            sheet.paste(left, (x0 + 3, y0 + LABEL_H + 3))
            sheet.paste(right, (x0 + CELL_W * 3 // 5 + 3, y0 + LABEL_H + 3))
        else:
            sheet.paste(_fit(full, CELL_W - 6, CELL_H - 6), (x0 + 3, y0 + LABEL_H + 3))
        s = stats.get(name, {})
        dims = " x ".join(f"{d:g}" for d in s.get("dims", []))
        label = f"{name}   {dims} m   {s.get('px_per_m', '?')} px/m"
        draw.text((x0 + 8, y0 + 5), label, fill=FG, font=font)
    target = OUT / "SHEET_props-industrial.png"
    sheet.save(target)
    print(f"wrote {target} ({sheet.width}x{sheet.height}, {len(pieces)} pieces)")


if __name__ == "__main__":
    main()
