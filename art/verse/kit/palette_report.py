"""Palette report for the WP12 reference views (A12.3, art-pipeline 8.1 and 8.3).

    python art/verse/kit/palette_report.py

For every `Verse.Visual.Decks` shot in the proof folder it counts banned pixels
with the rendered-pixel rule of art-pipeline 8.3 (HSV hue 160-330 degrees,
saturation above 0.25, value above 0.08; passes at 0) and the share of each 8.1
palette role (nearest role colour, `other` beyond a distance of 40 in sRGB),
per shot and per deck, against the 8.1 share bands. Writes `palette.json`
next to the shots.
"""

from __future__ import annotations

import colorsys
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
VISUAL = REPO_ROOT / "unreal" / "Verse" / "Saved" / "Harness" / "proof" / "WP12" / "visual"
SAMPLE = (480, 270)
OTHER_DISTANCE = 40.0

#: Role -> (sRGB colours, min share, max share) of art-pipeline 8.1.
ROLES: dict[str, tuple[tuple[str, ...], float, float]] = {
    "void_black": (("#0B0C0E",), 0.25, 0.45),
    "blackened_steel": (("#16171A",), 0.15, 0.30),
    "graphite": (("#2A2D31",), 0.10, 0.25),
    "gunmetal": (("#3B3F47",), 0.05, 0.15),
    "concrete": (("#5E6368", "#6A6C6B"), 0.05, 0.20),
    "oil_grime": (("#121212",), 0.0, 1.0),
    "worn_steel": (("#A9ADB2",), 0.0, 0.03),
    "work_light": (("#F2F4F5", "#D9DDE0"), 0.03, 0.08),
    "signal_red": (("#E3242B",), 0.0, 0.015),
    "amber": (("#F2A33A",), 0.0, 0.008),
    "hazard_yellow": (("#D9B23A",), 0.0, 0.01),
    "brand_gold": (("#C8A24A",), 0.0, 0.005),
}


def _rgb(hex_colour: str) -> tuple[int, int, int]:
    h = hex_colour.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


PALETTE = [(role, _rgb(c)) for role, (colours, _, _) in ROLES.items() for c in colours]


def banned(rgb: tuple[int, int, int]) -> bool:
    h, s, v = colorsys.rgb_to_hsv(*(c / 255.0 for c in rgb))
    hue = h * 360.0
    return 160.0 <= hue <= 330.0 and s > 0.25 and v > 0.08


def classify(rgb: tuple[int, int, int]) -> str:
    best, role = None, "other"
    for name, (r, g, b) in PALETTE:
        d = ((rgb[0] - r) ** 2 + (rgb[1] - g) ** 2 + (rgb[2] - b) ** 2) ** 0.5
        if best is None or d < best:
            best, role = d, name
    return role if best is not None and best <= OTHER_DISTANCE else "other"


def _pixels(image) -> list[tuple[int, int, int]]:
    data = image.tobytes()
    return [(data[i], data[i + 1], data[i + 2]) for i in range(0, len(data), 3)]


def measure(path: Path) -> dict:
    from PIL import Image  # noqa: PLC0415 - only the report needs Pillow

    image = Image.open(path).convert("RGB")
    full = _pixels(image)
    bad = sum(1 for p in full if banned(p))
    counts: dict[str, int] = {}
    small = _pixels(image.resize(SAMPLE))
    for pixel in small:
        role = classify(pixel)
        counts[role] = counts.get(role, 0) + 1
    shares = {k: round(v / len(small), 4) for k, v in sorted(counts.items())}
    return {"banned_pixels": bad, "pixels": len(full), "shares": shares}


def bands(shares: dict[str, float]) -> list[str]:
    out = []
    for role, (_, low, high) in ROLES.items():
        share = shares.get(role, 0.0)
        if share < low or share > high:
            out.append(f"{role} {share:.1%} outside {low:.1%}-{high:.1%}")
    return out


def main() -> int:
    shots = sorted(VISUAL.glob("*.png"))
    if not shots:
        print(f"[verse] no shots in {VISUAL}")
        return 1
    rule = "art-pipeline 8.1 shares, 8.3 rendered-pixel ban"
    report: dict = {"rule": rule, "shots": {}, "decks": {}}
    for path in shots:
        report["shots"][path.stem] = measure(path)
    for deck in sorted({name.split("_")[0] for name in report["shots"]}):
        rows = [v for k, v in report["shots"].items() if k.split("_")[0] == deck]
        shares: dict[str, float] = {}
        for row in rows:
            for role, share in row["shares"].items():
                shares[role] = shares.get(role, 0.0) + share / len(rows)
        report["decks"][deck] = {
            "shots": len(rows),
            "banned_pixels": sum(r["banned_pixels"] for r in rows),
            "shares": {k: round(v, 4) for k, v in sorted(shares.items())},
            "outside_bands": bands(shares),
        }
        d = report["decks"][deck]
        print(f"[verse] {deck}: {d['shots']} shots, {d['banned_pixels']} banned pixels, "
              f"{len(d['outside_bands'])} roles outside their band")
    out = VISUAL / "palette.json"
    out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"[verse] {out.relative_to(REPO_ROOT).as_posix()}")
    return 0 if all(d["banned_pixels"] == 0 for d in report["decks"].values()) else 1


if __name__ == "__main__":
    sys.exit(main())
