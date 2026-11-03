"""Evaluate the `Verse.Visual.Characters` shots (WP13 evidence; Pillow + numpy).

    python art/verse/characters/fps/visual_report.py [--dir <shots folder>]

* A13.5: the stand-in weapon is saturated red, so its pixels are found by
  colour in `fp_wall_off` (no wall) and `fp_wall_on` (wall 20 cm past the
  support hand); a weapon pixel is hidden when it is no longer red with the
  wall up. Grey against grey (body, floor, wall) cannot tell occlusion from
  the light the wall bounces onto the arms. Pass: weapon in view and 0 hidden
  weapon pixels; the anti-aliased silhouette (2 px) is reported on its own.
* Contact sheets: turnarounds, first-person views and the finisher phases,
  written next to the shots (`sheet_*.png`), plus `fp_clipping.json`.

Exit 1 when A13.5 fails or a shot is missing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[4]
DEFAULT = REPO / "unreal/Verse/Saved/Harness/proof/WP13/visual"


def load(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB"), dtype=np.int16)


#: Red minus the larger of green and blue. The weapon measures about 120 in the
#: open and about 30 with the wall's bounced light on it; the grey scene stays
#: at or below 20 (99.9 %), and an occluded weapon pixel shows bare wall (~0).
CHROMA = 24
#: Width of the anti-aliased silhouette, in pixels.
EDGE = 2


def red(img: np.ndarray) -> np.ndarray:
    """Pixels of the saturated red stand-in weapon, under any of the scene's light."""
    r = img[..., 0]
    return (r > 50) & (r - np.maximum(img[..., 1], img[..., 2]) > CHROMA)


def clipping(folder: Path) -> dict:
    """A13.5: weapon pixels in the owner's view without the wall that the wall hides."""
    off, on = (load(folder / f"fp_wall_{n}.png") for n in ("off", "on"))
    weapon = red(off)
    hidden = weapon & ~red(on)
    # Silhouette pixels (within EDGE px of the outline) are anti-aliased against
    # whatever lies behind, so their colour changes with the backdrop alone.
    pad = np.pad(weapon, EDGE)
    interior = np.ones_like(weapon)
    for dy in range(2 * EDGE + 1):
        for dx in range(2 * EDGE + 1):
            interior &= pad[dy : dy + weapon.shape[0], dx : dx + weapon.shape[1]]
    return {
        "weapon_pixels": int(weapon.sum()),
        "hidden_weapon_pixels": int((hidden & interior).sum()),
        "hidden_silhouette_pixels": int((hidden & ~interior).sum()),
        "silhouette_px": EDGE,
        "pass": bool(weapon.sum() > 0 and (hidden & interior).sum() == 0),
    }


def sheet(paths: list[Path], out: Path, cols: int = 6, size=(480, 270)) -> None:
    if not paths:
        return
    rows = (len(paths) + cols - 1) // cols
    canvas = Image.new("RGB", (cols * size[0], rows * size[1]), (20, 20, 20))
    for i, path in enumerate(paths):
        canvas.paste(
            Image.open(path).convert("RGB").resize(size),
            ((i % cols) * size[0], (i // cols) * size[1]),
        )
    canvas.save(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", type=Path, default=DEFAULT)
    folder = ap.parse_args(argv).dir
    shots = sorted(folder.glob("*.png"))
    shots = [p for p in shots if not p.name.startswith("sheet_")]
    if not shots:
        print(f"[verse] no shots in {folder}", file=sys.stderr)
        return 1
    sheet(
        [p for p in shots if p.name.startswith("turn_")], folder / "sheet_turnarounds.png", cols=8
    )
    sheet([p for p in shots if p.name.startswith("fp_")], folder / "sheet_first_person.png", cols=4)
    sheet(
        [p for p in shots if p.name.startswith("finisher_")], folder / "sheet_finisher.png", cols=5
    )
    result = clipping(folder)
    (folder / "fp_clipping.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"[verse] A13.5: {result}")
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
