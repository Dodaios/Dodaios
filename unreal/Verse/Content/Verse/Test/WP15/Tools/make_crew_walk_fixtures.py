#!/usr/bin/env python3
"""Write the WP15 walk fixtures: the walkable floor of each deck as boxes.

Crew life walks over Recast (work-packages.md 15.3, parity C-18). Until the
deck levels carry their floors and WP12's placements land, the automation tests
build a navmesh over these boxes. They come from the walkability grid of
today's web decks (``dodaios/ui/web/frontend/public/verse/decks/<deck>/nav.png``,
grey 0 = blocked, else floor height ``(code - height_zero) * height_step`` m,
as ``content/loadDeck.ts`` navFromCodes reads it), merged into rectangles of
one height, converted through the coordinate contract (contracts/coordinates.md
2): metres to centimetres, three.js (x, z) to Unreal (x, y), height to z.

The cook erodes that grid by the body clearance (``art/verse/lib/navgrid.py``,
0.25 m), so its cells are where a body's centre may stand, not the floor.
Recast erodes the floor by its own agent radius, so the grid is first grown
back by ``DILATE_CELLS`` (each new cell takes the height of its nearest
walkable neighbour) to stand in for the floor itself.

    python unreal/Verse/Content/Verse/Test/WP15/Tools/make_crew_walk_fixtures.py

Output: ``unreal/Verse/Content/Verse/Test/WP15/Decks/<deck>.walk.json``
(``verse.crew.walk/1``): ``boxes`` as ``[x0, y0, x1, y1, top_z]`` in deck cm.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve()
REPO = HERE.parents[7]
DECKS_DIR = REPO / "dodaios" / "ui" / "web" / "frontend" / "public" / "verse" / "decks"
OUT = HERE.parents[1] / "Decks"
DECKS = ("bridge", "ops", "engineering", "hangar")
#: Grows the eroded grid back toward the floor: 2 cells of 0.2 m cover the 0.25 m clearance.
DILATE_CELLS = 2


def dilate(codes: list[list[int]], cells: int) -> list[list[int]]:
    """Grow the walkable cells by a disk of ``cells``; a new cell copies its nearest neighbour."""
    rows = len(codes)
    cols = len(codes[0]) if rows else 0
    offsets = sorted(
        ((dc, dr) for dr in range(-cells, cells + 1) for dc in range(-cells, cells + 1)
         if 0 < dc * dc + dr * dr <= cells * cells),
        key=lambda o: o[0] * o[0] + o[1] * o[1],
    )
    out = [row[:] for row in codes]
    for r in range(rows):
        for c in range(cols):
            if codes[r][c]:
                continue
            for dc, dr in offsets:
                rr, cc = r + dr, c + dc
                if 0 <= rr < rows and 0 <= cc < cols and codes[rr][cc]:
                    out[r][c] = codes[rr][cc]
                    break
    return out


def merge_boxes(codes: list[list[int]]) -> list[tuple[int, int, int, int, int]]:
    """Greedy rectangles of equal non-zero code: (col0, row0, col1, row1, code), ends exclusive."""
    rows = len(codes)
    cols = len(codes[0]) if rows else 0
    used = [[False] * cols for _ in range(rows)]
    boxes = []
    for r in range(rows):
        for c in range(cols):
            code = codes[r][c]
            if code == 0 or used[r][c]:
                continue
            c1 = c
            while c1 < cols and codes[r][c1] == code and not used[r][c1]:
                c1 += 1
            r1 = r + 1
            while r1 < rows and all(codes[r1][k] == code and not used[r1][k] for k in range(c, c1)):
                r1 += 1
            for rr in range(r, r1):
                for k in range(c, c1):
                    used[rr][k] = True
            boxes.append((c, r, c1, r1, code))
    return boxes


def convert(deck: str) -> dict:
    manifest_path = DECKS_DIR / deck / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    nav = manifest["nav"]
    png = DECKS_DIR / deck / nav["url"]
    image = Image.open(png).convert("L")
    if image.size != (nav["w"], nav["h"]):
        raise SystemExit(f"{png}: grid is {image.size}, the manifest says {(nav['w'], nav['h'])}")
    pixels = image.load()
    grid = [[pixels[c, r] for c in range(nav["w"])] for r in range(nav["h"])]
    codes = dilate(grid, DILATE_CELLS)
    cell = float(nav["cell"])
    x0 = float(nav["origin_x"])
    z0 = float(nav["origin_z"])
    boxes = []
    for c0, r0, c1, r1, code in merge_boxes(codes):
        top_m = (code - nav["height_zero"]) * nav["height_step"]
        boxes.append([
            round(100.0 * (x0 + c0 * cell), 2),
            round(100.0 * (z0 + r0 * cell), 2),
            round(100.0 * (x0 + c1 * cell), 2),
            round(100.0 * (z0 + r1 * cell), 2),
            round(100.0 * top_m, 2),
        ])
    walkable = sum(1 for row in grid for code in row if code)
    return {
        "schema": "verse.crew.walk/1",
        "deck": deck,
        "note": (
            "Walkable floor of the web deck's nav grid as boxes (deck cm: x0, y0, x1, y1,"
            " top z). Test fixture for the crew navmesh only."
        ),
        "source": {
            "nav": f"dodaios/ui/web/frontend/public/verse/decks/{deck}/{nav['url']}",
            "sha256": hashlib.sha256(png.read_bytes()).hexdigest(),
            "builder": "unreal/Verse/Content/Verse/Test/WP15/Tools/make_crew_walk_fixtures.py",
        },
        "cell_cm": round(100.0 * cell, 2),
        "dilate_cells": DILATE_CELLS,
        "walkable_cells": walkable,
        "boxes": boxes,
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for deck in DECKS:
        doc = convert(deck)
        path = OUT / f"{deck}.walk.json"
        text = json.dumps(doc, separators=(",", ":")) + "\n"
        path.write_text(text, encoding="utf-8", newline="\n")
        boxes = len(doc["boxes"])
        print(f"{deck}: {boxes} boxes over {doc['walkable_cells']} cells -> {path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
