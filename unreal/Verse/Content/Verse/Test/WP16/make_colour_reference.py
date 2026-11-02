#!/usr/bin/env python3
"""Write colour_reference.json: the drawn colours of the WP16 colour test screen (A16.3).

The reference is what the IDE's web painter draws for each cell, computed with the
rules of frontend components/society/verse/effects/terminalCanvas.ts (paletteFor,
lineRuns: bold brightens palette 0-7, inverse swaps with the ground, dim mixes 45 %
toward the background) over the DARK_TERMINAL_THEME of
components/agentic/terminalThemes.ts. Verse.Screens.Colour.ReferenceScreen draws the
same screen through the Unreal palette and compares with CIEDE2000.

    python unreal/Verse/Content/Verse/Test/WP16/make_colour_reference.py
"""

from __future__ import annotations

import json
from pathlib import Path

ANSI = [
    "#2b2b2b", "#fc6b83", "#3fa266", "#d2943e", "#81a1c1", "#b48ead", "#88c0d0", "#dcdcdc",
    "#8a8a8a", "#ff8fa3", "#70b489", "#f1b467", "#a5bdd6", "#d4b3cc", "#a8d6e1", "#ffffff",
]
INK = "#f4f4f6"
GROUND = "#12141a"  # rgba(18, 20, 26, 0) with the alpha dropped (terminalCanvas.ts opaque)


def hex2(n: int) -> str:
    return f"{n:02x}"


def palette() -> list[str]:
    out = list(ANSI)
    steps = [0, 95, 135, 175, 215, 255]
    for r in steps:
        for g in steps:
            for b in steps:
                out.append(f"#{hex2(r)}{hex2(g)}{hex2(b)}")
    for i in range(24):
        v = 8 + i * 10
        out.append(f"#{hex2(v)}{hex2(v)}{hex2(v)}")
    return out


def mix(a: str, b: str, t: float) -> str:
    pa, pb = int(a[1:7], 16), int(b[1:7], 16)

    def ch(s: int) -> int:
        # Math.round in JS rounds .5 up; values here are never negative.
        return int(((pa >> s) & 255) * (1 - t) + ((pb >> s) & 255) * t + 0.5)

    return f"#{hex2(ch(16))}{hex2(ch(8))}{hex2(ch(0))}"


def resolve(fg, bg, attrs: list[str], pal: list[str]) -> tuple[str, str]:
    bold = "bold" in attrs
    if isinstance(fg, str):
        f = fg
    elif isinstance(fg, dict):
        idx = fg["i"]
        if bold and idx < 8:
            idx += 8
        f = pal[idx]
    else:
        f = INK
    b = bg if isinstance(bg, str) else pal[bg["i"]] if isinstance(bg, dict) else None
    if "inverse" in attrs:
        f, b = (b or GROUND), f
    if "dim" in attrs:
        f = mix(f, b or GROUND, 0.45)
    return f, (b or GROUND)


def cells() -> list[dict]:
    out = []
    for i in range(256):
        out.append({"fg": {"i": i}, "bg": None, "attrs": []})
        out.append({"fg": None, "bg": {"i": i}, "attrs": []})
    for i in range(8):
        out.append({"fg": {"i": i}, "bg": None, "attrs": ["bold"]})
    rgb = ["#000000", "#ffffff", "#e3242b", "#4fb86a", "#1f6feb", "#7f7f7f", "#ffb000", "#102030"]
    for c in rgb:
        out.append({"fg": c, "bg": None, "attrs": []})
        out.append({"fg": None, "bg": c, "attrs": []})
        out.append({"fg": c, "bg": "#202020", "attrs": ["inverse"]})
        out.append({"fg": c, "bg": None, "attrs": ["dim"]})
    out.append({"fg": {"i": 2}, "bg": {"i": 236}, "attrs": ["dim", "inverse"]})
    out.append({"fg": None, "bg": None, "attrs": ["inverse"]})
    return out


def main() -> None:
    pal = palette()
    rows = []
    for c in cells():
        fg, bg = resolve(c["fg"], c["bg"], c["attrs"], pal)
        rows.append({**c, "drawn_fg": fg, "drawn_bg": bg})
    doc = {
        "format": "wp16-colour-reference/1",
        "theme": "DARK_TERMINAL_THEME",
        "ground": GROUND,
        "ink": INK,
        "cells": rows,
    }
    path = Path(__file__).with_name("colour_reference.json")
    path.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {len(rows)} cells to {path.name}")


if __name__ == "__main__":
    main()
