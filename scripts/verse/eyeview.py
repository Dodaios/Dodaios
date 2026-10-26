"""Render eye-level Cycles views of a deck as the realtime export sees it.

    python scripts/verse/eyeview.py <deck_id> <out_dir> [--rooms] [--only ROOM]
        [--rig X,Z,YAW[,FLOOR]] [--eye X,Y,Z,YAW,PITCH] [--size 960x522]
        [--samples 64] [--device auto|optix|cuda|cpu]

Builds the deck in headless Blender (GPU lock) with every ceiling and
ceiling ghost visible (ghosts cast shadows, as in the realtime export) and
renders perspective views at the realtime view's 72 deg field of view:

- `--rooms` (the default without other views): in every room (`--only`
  narrows it) four headings from the inside centre at 1.9 m, plus more
  points along long rooms. Use it to find black voids above cut walls,
  missing ceilings and hull gaps before a realtime export
  (docs/verse/realtime.md, "Exporting another deck").
- `--rig x,z,yaw[,floor]`: the shoulder rig's camera behind a commander at
  three.js (x, floor, z) facing `yaw` degrees (0 = +Z, 90 = +X); the truth
  render to compare the browser against.
- `--eye x,y,z,yaw,pitch`: a free camera in three.js metres (pitch down).

Writes `<out_dir>/<name>.png` per view and `<out_dir>/sheet.png`, a labelled
contact sheet of all of them.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))

import blender  # noqa: E402

ENTRY = Path(__file__).resolve().with_name("_eyeview_entry.py")
SHEET_TILE = (480, 261)
SHEET_COLUMNS = 4


def _floats(text: str) -> list[float]:
    return [float(part) for part in text.split(",")]


def render_views(
    deck_id: str,
    out_dir: Path,
    views: list[dict],
    *,
    samples: int = 64,
    size: str = "960x522",
    device: str = "auto",
) -> list[Path]:
    """Render `views` of deck `deck_id`; return the PNG paths (sheet last)."""
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    spec = out_dir / "views_in.json"
    spec.write_text(json.dumps(views), encoding="utf-8")
    args = [deck_id, str(out_dir), str(spec), "--samples", str(samples), "--size", size]
    result = blender.run(ENTRY, args, device=device, timeout=3 * 3600)
    done = json.loads((out_dir / "views.json").read_text(encoding="utf-8"))
    paths = [out_dir / f"{view['name']}.png" for view in done]
    sheet = out_dir / "sheet.png"
    contact_sheet(paths, sheet)
    print(f"[verse] {len(paths)} eye views in {result.seconds:.0f} s; sheet {sheet}")
    return [*paths, sheet]


def contact_sheet(paths: list[Path], target: Path) -> None:
    """Tile the views into one labelled image."""
    tw, th = SHEET_TILE
    rows = max(1, -(-len(paths) // SHEET_COLUMNS))
    sheet = Image.new("RGB", (tw * SHEET_COLUMNS, (th + 18) * rows), (12, 12, 14))
    draw = ImageDraw.Draw(sheet)
    for index, path in enumerate(paths):
        x, y = (index % SHEET_COLUMNS) * tw, (index // SHEET_COLUMNS) * (th + 18)
        with Image.open(path) as image:
            sheet.paste(image.convert("RGB").resize((tw, th)), (x, y + 18))
        draw.text((x + 4, y + 3), path.stem, fill=(220, 220, 220))
    sheet.save(target)


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("deck_id")
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("--rooms", action="store_true")
    parser.add_argument("--only", action="append", default=[], help="room id (repeatable)")
    parser.add_argument("--rig", action="append", default=[])
    parser.add_argument("--eye", action="append", default=[])
    parser.add_argument("--size", default="960x522")
    parser.add_argument("--samples", type=int, default=64)
    parser.add_argument("--device", choices=blender.DEVICES, default="auto")
    options = parser.parse_args(argv)
    views: list[dict] = []
    if options.rooms or options.only or not (options.rig or options.eye):
        views.append({"name": "rooms", "rooms": True, "only": options.only})
    for index, text in enumerate(options.rig):
        views.append({"name": f"rig_{index}", "rig": _floats(text)})
    for index, text in enumerate(options.eye):
        views.append({"name": f"eye_{index}", "eye": _floats(text)})
    try:
        render_views(
            options.deck_id,
            options.out_dir,
            views,
            samples=options.samples,
            size=options.size,
            device=options.device,
        )
    except blender.BlenderError as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(_main())
