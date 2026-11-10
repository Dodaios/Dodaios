#!/usr/bin/env python3
"""Write the hangar arena graybox the Verse builds at runtime.

WP11's arena (``art/verse/decks/hangar/unreal_arena/layout.py``) is a set of
boxes, ramps, spawns and lights in plan metres. Until its placement files and
graybox meshes are imported into ``LV_Hangar`` (arena.md 10), the primary
module spawns the same arena from this JSON when the hangar switches to the
arena (``UVerseArenaGraybox``), so the duel is playable now.

    python scripts/unreal/arena_graybox.py           # writes the JSON
    python scripts/unreal/arena_graybox.py --check   # exit 1 when it is stale

Unreal space is (100 x, 100 z, 100 h) cm (coordinates 2.1). Pure Python.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LAYOUT_DIR = REPO / "art" / "verse" / "decks" / "hangar"
OUT = REPO / "unreal" / "Verse" / "Data" / "arena" / "hangar_graybox.json"
SCHEMA = "verse.arena_graybox/1"
#: Ramp slab thickness, m.
RAMP_T = 0.2


def _layout():
    sys.path.insert(0, str(LAYOUT_DIR))
    sys.path.insert(0, str(REPO / "art" / "verse"))
    from unreal_arena import layout  # noqa: PLC0415 - the art tree is not a package

    return layout


def cm(value: float) -> float:
    return round(value * 100.0, 1)


def box_entry(box) -> dict:
    cx, cz, ch = box.centre
    sx, sz, sh = box.size
    entry = {
        "id": box.id,
        "zone": box.zone,
        "layer": box.layer,
        "center": [cm(cx), cm(cz), cm(ch)],
        "size": [cm(sx), cm(sz), cm(sh)],
        "material": box.material,
        "solid": box.solid,
        "sight": box.sight,
    }
    if box.piece_class:
        entry["piece"] = box.piece_class
    return entry


def ramp_entry(ramp) -> dict:
    """A ramp as a slab from its low edge to its high edge (top-surface centre line)."""
    if ramp.axis == "x":
        mid = (ramp.z0 + ramp.z1) / 2
        start = (ramp.x0, mid, ramp.h_start)
        end = (ramp.x1, mid, ramp.h_end)
        width = ramp.z1 - ramp.z0
    else:
        mid = (ramp.x0 + ramp.x1) / 2
        start = (mid, ramp.z0, ramp.h_start)
        end = (mid, ramp.z1, ramp.h_end)
        width = ramp.x1 - ramp.x0
    return {
        "id": ramp.id,
        "zone": ramp.zone,
        "layer": ramp.layer,
        "start": [cm(v) for v in start],
        "end": [cm(v) for v in end],
        "widthCm": cm(width),
        "thicknessCm": cm(RAMP_T),
    }


def build() -> dict:
    layout = _layout()
    out = layout.build()
    x0, x1, z0, z1 = layout.ARENA
    return {
        "schema": SCHEMA,
        "source": "art/verse/decks/hangar/unreal_arena/layout.py",
        "arenaBoundsCm": [cm(x0), cm(z0), cm(x1), cm(z1)],
        "boxes": [box_entry(b) for b in out.boxes if b.layer in ("base", "arena")],
        "ramps": [ramp_entry(r) for r in out.ramps if r.layer in ("base", "arena")],
        "spawns": [
            {"id": s.id, "location": [cm(s.x), cm(s.z), cm(s.h)], "yaw": s.heading_deg}
            for s in out.spawns
        ],
        "lights": [
            {
                "id": light.id,
                "zone": light.zone,
                # The arena's practicals (catwalks, booth, cabin, canyon aisles) come and go with
                # the arena; the truss work lights and the armoury light the hall on every visit.
                "layer": "arena" if light.zone.startswith("arena") else "base",
                "type": light.type,
                "location": [cm(light.x), cm(light.z), cm(light.h)],
                "pitch": light.pitch_deg,
                "kelvin": light.kelvin,
                "lumens": light.intensity_lm,
                "attenuationCm": cm(light.attenuation_m),
                "coneDeg": light.cone_deg or 0.0,
            }
            for light in out.lights
        ],
    }


def render(data: dict) -> str:
    return json.dumps(data, indent=1) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="Fail when the JSON is stale.")
    args = parser.parse_args(argv)
    text = render(build())
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.is_file() else ""
        if current != text:
            print(f"{OUT.relative_to(REPO)} is stale: run scripts/unreal/arena_graybox.py")
            return 1
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8", newline="\n")
    data = json.loads(text)
    print(
        f"wrote {OUT.relative_to(REPO)}: {len(data['boxes'])} boxes, {len(data['ramps'])} ramps, "
        f"{len(data['spawns'])} spawns, {len(data['lights'])} lights"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
