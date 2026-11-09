#!/usr/bin/env python3
"""Write the WP15 crew fixture decks from today's web deck manifests.

Until WP12 ships the real deck placement files, crew life needs the sockets
of each deck (seats, screens, stands, bunks, waypoints, spawns, the lift).
This converts the sockets, stations and rooms of
``dodaios/ui/web/frontend/public/verse/decks/<deck>/manifest.json`` into
``verse.placement/1`` files (contracts/art-pipeline.md 4) through the
coordinate contract (contracts/coordinates.md 2): metres to centimetres,
three.js (x, y, z) to Unreal (x, z, y), heading ``90 - yaw_deg``.

    python unreal/Verse/Content/Verse/Test/WP15/Tools/make_crew_fixture_decks.py

Output: ``unreal/Verse/Content/Verse/Test/WP15/Decks/<deck>.placement.json``.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
REPO = HERE.parents[7]
MANIFESTS = REPO / "dodaios" / "ui" / "web" / "frontend" / "public" / "verse" / "decks"
OUT = HERE.parents[1] / "Decks"
DECKS = ("bridge", "ops", "engineering", "hangar")
LEVELS = {"bridge": "Bridge", "ops": "Ops", "engineering": "Engineering", "hangar": "Hangar"}
#: Socket kinds crew life reads; doors, lights and holos stay with WP12.
CREW_KINDS = {"seat", "screen", "stand", "bunk", "waypoint", "spawn", "lift", "station"}


def to_unreal(position: list[float]) -> list[float]:
    x, y, z = position
    return [round(100.0 * x, 3), round(100.0 * z, 3), round(100.0 * y, 3)]


def heading_deg(yaw_deg: float) -> float:
    value = math.fmod(90.0 - yaw_deg, 360.0)
    if value <= -180.0:
        value += 360.0
    if value > 180.0:
        value -= 360.0
    return value


def yaw_quat(heading: float) -> list[float]:
    half = math.radians(heading) / 2.0
    return [0.0, 0.0, round(math.sin(half), 6), round(math.cos(half), 6)]


def convert(deck: str) -> dict:
    path = MANIFESTS / deck / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    station_kind = {s["id"]: s["kind"] for s in manifest.get("stations", [])}
    # A team table's member seats name their station only in the station list.
    seat_station: dict[str, str] = {}
    for station in manifest.get("stations", []):
        if station["kind"] == "team":
            for seat in station.get("sockets", {}).get("seat", []):
                seat_station.setdefault(seat, station["id"])
    sockets = []
    for raw in manifest["sockets"]:
        kind = raw["kind"]
        if kind not in CREW_KINDS:
            continue
        station = raw.get("station") or (seat_station.get(raw["id"]) if kind == "seat" else None)
        entry = {
            "id": raw["id"],
            "kind": kind,
            "location": to_unreal(raw["position"]),
            "rotation": yaw_quat(heading_deg(float(raw.get("yaw_deg", 0.0)))),
            "room": raw.get("room"),
            "station": {"id": station, "kind": station_kind.get(station, "")} if station else None,
        }
        if kind == "screen":
            size = raw.get("size") or (raw.get("props") or {}).get("size") or [1.0, 0.6]
            entry["size_cm"] = [round(100.0 * size[0], 1), round(100.0 * size[1], 1)]
        if kind == "spawn":
            entry["spawn"] = {"team": "any", "duel": False}
        sockets.append(entry)
    rooms = [
        {
            "id": room["id"],
            "name": room.get("name", room["id"]),
            "polygon_cm": [[round(100.0 * x, 2), round(100.0 * z, 2)] for x, z in room["polygon"]],
            "z_cm": round(100.0 * float(room.get("floor_y", 0.0)), 2),
            "main": bool(room.get("main", False)),
        }
        for room in manifest.get("rooms", [])
    ]
    xs = [s["location"][0] for s in sockets] or [0.0]
    ys = [s["location"][1] for s in sockets] or [0.0]
    zs = [s["location"][2] for s in sockets] or [0.0]
    builder = HERE.relative_to(REPO).as_posix()
    digest = hashlib.sha256(HERE.read_bytes() + path.read_bytes()).hexdigest()
    return {
        "schema": "verse.placement/1",
        "deck": deck,
        "zone": "crew_fixture",
        "bounds_cm": {
            "min": [min(xs), min(ys), min(zs) - 10.0],
            "max": [max(xs), max(ys), max(zs) + 300.0],
        },
        "level": f"/Game/Verse/Decks/{LEVELS[deck]}/LV_{LEVELS[deck]}",
        "source": {"builder": builder, "sha256": digest},
        "generator": {"script": HERE.name, "version": "1", "blender": "none"},
        "placements": [],
        "sockets": sockets,
        "rooms": rooms,
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for deck in DECKS:
        data = convert(deck)
        target = OUT / f"{deck}.placement.json"
        target.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
        name = target.relative_to(REPO).as_posix()
        print(f"{name}: {len(data['sockets'])} sockets, {len(data['rooms'])} rooms")
    return 0


if __name__ == "__main__":
    sys.exit(main())
