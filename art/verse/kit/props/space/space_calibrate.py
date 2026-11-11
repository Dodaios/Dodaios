"""Measure the game's tonemapper for the space view and write its inverse.

`Verse.Visual.SpaceView` first shoots `ue_calib.png`: the dome draws scene values from 2^-12
(left edge) to 2^6 (right edge), already divided by the exposure, through the game's post
(`M_Verse_Space` `Calibrate`). For every displayed sRGB level (i / 32)^2 and each channel,
this finds the log2 scene value that shows it and writes `tonemap_inverse.json`, which
`weapons/editor/masters.py` bakes into `M_Verse_Space`: the shader takes what three.js shows
(AgX) and asks the game for exactly that.

    python art/verse/kit/props/space/space_calibrate.py <ue_calib.png>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
OUT = HERE / "tonemap_inverse.json"
LOG2_MIN, LOG2_MAX = -12.0, 6.0
LEVELS = 33


def inverse(shot: Path) -> dict:
    image = np.asarray(Image.open(shot).convert("RGB")).astype(np.float64) / 255.0
    height, width, _ = image.shape
    # The middle band of rows: the ramp is the same down a column; skip the vignetted edges.
    row = image[height // 3 : 2 * height // 3].mean(axis=0)
    log2v = LOG2_MIN + (np.arange(width) + 0.5) / width * (LOG2_MAX - LOG2_MIN)
    tables = {}
    for c, name in enumerate("rgb"):
        shown = np.maximum.accumulate(row[:, c])  # monotonic despite noise
        out = []
        # Square-root spacing: fine steps in the dark, where the sky and the night side are.
        for level in np.linspace(0.0, 1.0, LEVELS) ** 2:
            if level <= shown[0]:
                out.append(LOG2_MIN)
            elif level >= shown[-1]:
                out.append(LOG2_MAX)
            else:
                i = int(np.searchsorted(shown, level))
                a, b = shown[i - 1], shown[i]
                t = 0.0 if b <= a else (level - a) / (b - a)
                out.append(float(log2v[i - 1] + t * (log2v[i] - log2v[i - 1])))
        tables[name] = [round(float(v), 5) for v in np.maximum.accumulate(out)]
    return tables


def main(argv: list[str]) -> int:
    tables = inverse(Path(argv[0]))
    doc = {
        "source": "Verse.Visual.SpaceView ue_calib.png (the game's post, hangar world)",
        "levels": "displayed sRGB (i / 32)^2, i = 0..32",
        "log2_scene": tables,
    }
    OUT.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    print(f"[verse] wrote {OUT.name}: mid grey r/g/b {[tables[c][16] for c in 'rgb']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
