"""Is the space view there? A check of the `Verse.Visual.Decks` backdrop shots (WP12.9).

Pure Python (numpy, Pillow). `Verse.Visual.Decks` renders the space view on its own
(`space_earth.png`, `space_stars.png` in `Saved/Harness/proof/WP12/visual/`). This script
fails when the Earth frame is black (less than `MIN_EARTH_SHARE` of its pixels above the
art-pipeline 8.3 value floor of 0.08), when the star frame shows fewer than `MIN_STARS`
bright pixels, or when either frame has a banned pixel (art-pipeline 8.3).

    python art/verse/kit/space_check.py [--dir DIR] [--json OUT]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[3]
SHOTS = REPO_ROOT / "unreal" / "Verse" / "Saved" / "Harness" / "proof" / "WP12" / "visual"
MIN_EARTH_SHARE = 0.25
MIN_STARS = 150
VALUE_FLOOR = 0.08


def hsv(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mx = rgb.max(axis=-1)
    mn = rgb.min(axis=-1)
    delta = mx - mn
    sat = np.where(mx > 0, delta / np.maximum(mx, 1e-9), 0.0)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    safe = np.maximum(delta, 1e-9)
    hue = np.where(
        mx == r, ((g - b) / safe) % 6, np.where(mx == g, (b - r) / safe + 2, (r - g) / safe + 4)
    )
    return np.where(delta > 0, hue * 60.0, 0.0), sat, mx


def banned(rgb: np.ndarray) -> int:
    hue, sat, value = hsv(rgb)
    return int(((hue >= 160) & (hue <= 330) & (sat > 0.25) & (value > VALUE_FLOOR)).sum())


def measure(folder: Path) -> dict:
    out: dict = {"ok": True, "problems": []}
    for name in ("space_earth", "space_stars"):
        path = folder / f"{name}.png"
        if not path.is_file():
            out["ok"] = False
            out["problems"].append(f"{path.name} missing")
            continue
        rgb = np.asarray(Image.open(path).convert("RGB"), dtype=np.float64) / 255.0
        value = rgb.max(axis=-1)
        entry = {
            "lit_share": round(float((value > VALUE_FLOOR).mean()), 4),
            "bright_pixels": int((value > 0.5).sum()),
            "banned_pixels": banned(rgb),
        }
        out[name] = entry
        if entry["banned_pixels"]:
            out["problems"].append(f"{name}: {entry['banned_pixels']} banned pixels")
        if name == "space_earth" and entry["lit_share"] < MIN_EARTH_SHARE:
            out["problems"].append(f"{name}: black ({entry['lit_share']:.1%} lit)")
        if name == "space_stars" and entry["bright_pixels"] < MIN_STARS:
            out["problems"].append(f"{name}: {entry['bright_pixels']} stars")
    out["ok"] = not out["problems"]
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dir", type=Path, default=SHOTS)
    parser.add_argument("--json", type=Path)
    options = parser.parse_args(argv)
    report = measure(options.dir)
    text = json.dumps(report, indent=1)
    if options.json:
        options.json.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
