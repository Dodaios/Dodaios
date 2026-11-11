"""The hangar flight deck's waypoint routes for the Unreal placements, from the three.js deck.

The three.js hangar (`dodaios/ui/web/frontend/public/verse/decks/hangar/manifest.json`, built by
`decks/hangar/build.py`) puts its routes on the flight deck: the cargo and pad rounds the
utility drones drive (`life/cast.ts`), and the front, wall and well loops. The Unreal hangar
placements had none, so no utility drone drove there. This writes them, and nothing else, as
`unreal/Verse/Art/Placements/hangar/flight_deck_routes.placement.json`: one `waypoint` socket per
point, at the converted position (three.js metres (x, y, z) -> Unreal centimetres (x, z, y),
coordinates.md section 1), with the route (`loop`) and its `order`.

    python art/verse/decks/hangar/flight_deck_routes.py [--check]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
REPO = HERE.parents[4]
MANIFEST = REPO / "dodaios/ui/web/frontend/public/verse/decks/hangar/manifest.json"
OUT = REPO / "unreal/Verse/Art/Placements/hangar/flight_deck_routes.placement.json"
ZONE = "flight_deck_routes"


def _quat_z(yaw_deg: float) -> list[float]:
    """Unreal rotation of a socket facing the three.js yaw (0 faces +Z -> Unreal yaw 90)."""
    unreal_yaw = math.radians(90.0 - yaw_deg)
    return [0.0, 0.0, round(math.sin(unreal_yaw / 2), 7), round(math.cos(unreal_yaw / 2), 7)]


def sockets(manifest: dict) -> list[dict]:
    out = []
    for s in manifest["sockets"]:
        props = s.get("props") or {}
        if s.get("kind") != "waypoint" or "loop" not in props:
            continue
        x, y, z = s["position"]
        yaw = float(s.get("yaw_deg", 0.0))
        out.append(
            {
                "id": f"waypoint-{s['id']}",
                "kind": "waypoint",
                "location": [round(x * 100.0, 3), round(z * 100.0, 3), round(y * 100.0, 3)],
                "props": {
                    "manifest_id": s["id"],
                    "yaw_deg": str(yaw),
                    "loop": str(props["loop"]),
                    "order": str(props["order"]),
                },
                "room": s.get("room"),
                "rotation": _quat_z(yaw),
                "station": None,
            }
        )
    return sorted(out, key=lambda d: d["id"])


def document() -> dict:
    raw = MANIFEST.read_bytes()
    manifest = json.loads(raw)
    return {
        "schema": "verse.placement/1",
        "deck": "hangar",
        "zone": ZONE,
        "level": "/Game/Verse/Decks/Hangar/LV_Hangar",
        "bounds_cm": {"min": [0.0, 0.0, 0.0], "max": [10000.0, 5500.0, 0.0]},
        "source": {
            "builder": HERE.relative_to(REPO).as_posix(),
            "sha256": hashlib.sha256(raw).hexdigest(),
        },
        "generator": {"blender": "0.0.0", "script": HERE.name, "version": "1"},
        "placements": [],
        "rooms": [],
        "sockets": sockets(manifest),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="fail when the file is stale")
    options = parser.parse_args(argv)
    text = json.dumps(document(), indent=1, sort_keys=True) + "\n"
    if OUT.is_file() and OUT.read_text(encoding="utf-8") == text:
        return 0
    if options.check:
        print(f"[verse] stale {OUT.relative_to(REPO).as_posix()}")
        return 1
    OUT.write_text(text, encoding="utf-8")
    print(f"[verse] wrote {OUT.relative_to(REPO).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
