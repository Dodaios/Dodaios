"""Evaluate the `Verse.Visual.Characters` shots (WP13 evidence; Pillow + numpy).

    python art/verse/characters/fps/visual_report.py [--dir <shots folder>]

* A13.5: the body mask is where `fp_wall_off` differs from `fp_wall_nobody`;
  a body pixel counts as hidden by the wall when `fp_wall_on` differs from
  `fp_wall_off` there by more than the threshold. Pass: 0 hidden pixels.
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
#: Per-channel difference (0..255) that counts as a changed pixel.
THRESHOLD = 40


def load(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGB"), dtype=np.int16)


def clipping(folder: Path) -> dict:
    off, on, nobody = (load(folder / f"fp_wall_{n}.png") for n in ("off", "on", "nobody"))
    body = np.abs(off - nobody).max(axis=2) > THRESHOLD
    hidden = body & (np.abs(on - off).max(axis=2) > THRESHOLD)
    return {
        "body_pixels": int(body.sum()),
        "hidden_body_pixels": int(hidden.sum()),
        "threshold": THRESHOLD,
        "pass": bool(body.sum() > 0 and hidden.sum() == 0),
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
