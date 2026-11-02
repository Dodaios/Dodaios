"""Side-by-side sheet for WP12: today's view and the Unreal view of the same spot.

    python art/verse/kit/reference_sheet.py            # render today's frames, build the sheet
    python art/verse/kit/reference_sheet.py --sheet    # only rebuild the sheet

Reads `Verse.Visual.Decks` output (`views.json` and one PNG per shot) from the
proof folder, renders today's look of each deck from the same cameras in
headless Blender (`reference_render_blender.py`, one run per deck, no GPU
lock: CPU Cycles), and writes `sheet_<deck>.png` with today on the left and
Unreal on the right. Everything lands in the ignored proof folder.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
PROOF = REPO_ROOT / "unreal" / "Verse" / "Saved" / "Harness" / "proof" / "WP12"
VISUAL = PROOF / "visual"
TODAY = PROOF / "today"
ENTRY = HERE / "reference_render_blender.py"
DECKS = ("bridge", "ops", "engineering", "hangar")
TILE = (640, 360)


def render_today(views: Path) -> None:
    sys.path.insert(0, str(REPO_ROOT / "scripts" / "verse"))
    import blender  # noqa: PLC0415 - scripts/verse is not a package

    for deck in DECKS:
        args = [deck, "--views", str(views), "--out", str(TODAY)]
        blender.run(ENTRY, args, lock=False, device="cpu", timeout=3600)


def build_sheets(views: Path) -> list[Path]:
    from PIL import Image, ImageDraw  # noqa: PLC0415 - only the sheet needs Pillow

    shots = json.loads(views.read_text(encoding="utf-8"))
    written = []
    for deck in DECKS:
        rows = [s for s in shots if s["deck"] == deck]
        if not rows:
            continue
        sheet = Image.new("RGB", (TILE[0] * 2, (TILE[1] + 24) * len(rows)), (12, 12, 14))
        draw = ImageDraw.Draw(sheet)
        for index, shot in enumerate(rows):
            top = index * (TILE[1] + 24)
            draw.text((8, top + 6), f"{shot['name']}   today | unreal", fill=(220, 220, 220))
            for column, folder in enumerate((TODAY, VISUAL)):
                path = folder / f"{shot['name']}.png"
                if path.is_file():
                    tile = Image.open(path).convert("RGB").resize(TILE)
                    sheet.paste(tile, (column * TILE[0], top + 24))
        out = PROOF / f"sheet_{deck}.png"
        sheet.save(out)
        written.append(out)
        print(f"[verse] {out.relative_to(REPO_ROOT).as_posix()}: {len(rows)} shots")
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sheet", action="store_true", help="only rebuild the sheet")
    options = parser.parse_args(argv)
    views = VISUAL / "views.json"
    if not views.is_file():
        suite = "scripts/unreal/screenshot.py --suite Verse.Visual.Decks"
        print(f"[verse] {views} is missing: run {suite}")
        return 1
    if not options.sheet:
        render_today(views)
    build_sheets(views)
    return 0


if __name__ == "__main__":
    sys.exit(main())
