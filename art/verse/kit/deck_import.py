"""Deck manifests (`verse.deck/1`) to zone placement JSON (`verse.placement/1`).

Pure Python, no bpy and no unreal (WP12.1, contracts/art-pipeline.md 4).
Today's cooked manifests (`dodaios/ui/web/frontend/public/verse/decks/<deck>/
manifest.json`) hold the rooms, sockets and stations every deck is built
around. This module carries them, converted once into Unreal space
(contracts/coordinates.md 2), into the `rooms[]` and `sockets[]` of one
placement file per zone, `unreal/Verse/Art/Placements/<deck>/<zone>.placement.json`.
`VerseDecks` reads those files at runtime (`FVerseDeckManifest`), so the
Unreal Verse keeps every room, socket and station id of today (A12.1).

Each deck's zones are listed by a builder file next to its deck builder:

* `art/verse/decks/<deck>/zones.py` (bridge, ops, engineering), a `ZONES`
  tuple of `Zone`;
* `art/verse/decks/hangar/zones/<zone>.py` (`lift_lobby`, `day_stations`),
  one `ZONE` each; the other hangar zones belong to WP11.

A zone claims rooms. A socket belongs to the zone of its room; a socket
without a room goes to the zone whose rooms are nearest on the plan. A zone
listed with `rest=True` takes every room no other zone of the deck claims.

Socket ids are `<kind>-<manifest id>`: manifest ids are unique per kind only
(`main` is both a lift and a waypoint on the bridge), and the placement id
must be unique per zone. `socket_key` reverses it.

    python art/verse/kit/deck_import.py            # write every zone file
    python art/verse/kit/deck_import.py --check    # exit 1 when a file is stale
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ART_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ART_ROOT.parents[1]
if str(ART_ROOT) not in sys.path:
    sys.path.insert(0, str(ART_ROOT))

from lib import placement, ue_space  # noqa: E402

MANIFEST_ROOT = REPO_ROOT / "dodaios" / "ui" / "web" / "frontend" / "public" / "verse" / "decks"
PLACEMENTS_ROOT = REPO_ROOT / "unreal" / "Verse" / "Art" / "Placements"
DECKS_ROOT = ART_ROOT / "decks"

OWNER = "WP12"
GENERATOR = {"script": "deck_import.py", "version": "1", "blender": "5.0.1"}

#: The decks of the ship, top to bottom (`decks.ts:7`, `progression/rules.py` VERSE_DECKS).
DECK_IDS = ("bridge", "ops", "engineering", "hangar")
#: Decks whose zones all belong to WP12; on the hangar only `HANGAR_ZONES` do.
AGENT_DECKS = ("bridge", "ops", "engineering")
HANGAR_ZONES = ("lift_lobby", "day_stations")

SOCKET_SEP = "-"
#: Horizontal margin around a zone's rooms and sockets, cm.
ZONE_MARGIN_CM = 60.0
#: Vertical extent of a zone around its floor, cm (below for pits and wells, above for ceilings).
ZONE_BELOW_CM = 300.0
ZONE_ABOVE_CM = 900.0

#: Light sockets: manifest `light_kind` -> placement light type.
LIGHT_TYPES = {"ceiling_grid": "rect", "ceiling_fixtures": "rect"}
#: Work-light defaults (art-pipeline 8.2: 4300-6500 K, shadows on).
WORK_LIGHT_KELVIN = 5600.0
LAMP_LUMEN = 400.0
FIXTURE_LUMEN = 3000.0
DEFAULT_ATTENUATION_M = 12.0


@dataclass(frozen=True)
class Zone:
    """One deck zone: its id and the manifest rooms it claims."""

    id: str
    rooms: tuple[str, ...] = ()
    rest: bool = False
    builder: str = ""


@dataclass
class _ZoneDoc:
    zone: Zone
    rooms: list[dict] = field(default_factory=list)
    sockets: list[dict] = field(default_factory=list)
    points: list[list[float]] = field(default_factory=list)


# --------------------------------------------------------------------------
# Conversions (contracts/coordinates.md 2.1, 2.2)
# --------------------------------------------------------------------------


def heading_deg(three_yaw_deg: float) -> float:
    """Manifest `yaw_deg` -> Unreal heading in (-180, 180] (coordinates 2.2)."""
    value = math.fmod(90.0 - float(three_yaw_deg), 360.0)
    if value <= -180.0:
        value += 360.0
    elif value > 180.0:
        value -= 360.0
    return 0.0 if value == 0 else value


def three_yaw_deg(heading: float) -> float:
    """Inverse of `heading_deg`, in (-180, 180]: 90 - (90 - a) == a."""
    return heading_deg(heading)


def yaw_quat_xyzw(yaw_deg: float) -> list[float]:
    """Unit quaternion [x, y, z, w] of a rotation about +Z (Unreal yaw), w >= 0."""
    half = math.radians(float(yaw_deg)) / 2.0
    quat = [0.0, 0.0, math.sin(half), math.cos(half)]
    if quat[3] < 0:
        quat = [-v for v in quat]
    return [0.0 if abs(v) < 1e-12 else v for v in quat]


def quat_yaw_deg(quat_xyzw: Sequence[float]) -> float:
    """Unreal yaw of a yaw-only [x, y, z, w] quaternion, in (-180, 180]."""
    return _norm(placement.yaw_from_quat_xyzw(quat_xyzw))


def _norm(deg: float) -> float:
    value = math.fmod(float(deg), 360.0)
    if value <= -180.0:
        value += 360.0
    elif value > 180.0:
        value -= 360.0
    return value


def to_cm(value_m: float) -> float:
    return float(value_m) * ue_space.CM_PER_M


def socket_id(kind: str, manifest_id: str) -> str:
    return f"{kind}{SOCKET_SEP}{manifest_id}"


def socket_key(placement_socket_id: str) -> tuple[str, str]:
    """`door-brief` -> ("door", "brief")."""
    kind, _, rest = placement_socket_id.partition(SOCKET_SEP)
    if not rest:
        raise ValueError(f"{placement_socket_id!r} is not a <kind>-<id> socket id")
    return kind, rest


def _prop(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


# --------------------------------------------------------------------------
# Geometry helpers on the plan (Unreal cm, X/Y)
# --------------------------------------------------------------------------


def _segment_distance(p: Sequence[float], a: Sequence[float], b: Sequence[float]) -> float:
    ax, ay = a
    bx, by = b
    px, py = p
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def inside_polygon(point: Sequence[float], polygon: Sequence[Sequence[float]]) -> bool:
    """Even-odd rule, the same as the three.js `insidePolygon` and `FVerseDeckRoom::Contains`."""
    x, y = point[0], point[1]
    inside = False
    j = len(polygon) - 1
    for i in range(len(polygon)):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def polygon_distance(point: Sequence[float], polygon: Sequence[Sequence[float]]) -> float:
    if inside_polygon(point, polygon):
        return 0.0
    return min(
        _segment_distance(point, polygon[i], polygon[(i + 1) % len(polygon)])
        for i in range(len(polygon))
    )


# --------------------------------------------------------------------------
# Manifest -> rooms and sockets
# --------------------------------------------------------------------------


def convert_room(room: Mapping[str, Any]) -> dict:
    return {
        "id": room["id"],
        "name": room["name"],
        "polygon_cm": [[to_cm(x), to_cm(z)] for x, z in room["polygon"]],
        "z_cm": to_cm(room.get("floor_y", 0.0)),
        "main": bool(room.get("main", False)),
    }


def _light_block(raw: Mapping[str, Any]) -> dict:
    props = raw.get("props", {})
    light_kind = props.get("light_kind")
    kind = LIGHT_TYPES.get(light_kind, "point")
    count = int(props.get("count", 1) or 1)
    lumen = FIXTURE_LUMEN * count if light_kind else LAMP_LUMEN
    radius_m = float(props.get("radius", DEFAULT_ATTENUATION_M))
    block = {
        "type": kind,
        "kelvin": float(props.get("kelvin", WORK_LIGHT_KELVIN)),
        "intensity_lm": lumen,
        "attenuation_cm": to_cm(radius_m),
        "shadows": True,
    }
    if kind == "rect":
        block["source_size_cm"] = to_cm(1.2)
    return block


def convert_socket(raw: Mapping[str, Any], stations: Mapping[str, Mapping[str, Any]]) -> dict:
    kind = raw["kind"]
    yaw = float(raw.get("yaw_deg", 0.0))
    out: dict[str, Any] = {
        "id": socket_id(kind, raw["id"]),
        "kind": kind,
        "location": ue_space.three_to_ue(raw["position"]),
        "rotation": yaw_quat_xyzw(heading_deg(yaw)),
        "room": raw.get("room"),
        "station": None,
    }
    station_id = raw.get("station")
    if kind == "station" and raw["id"] in stations:
        station_id = raw["id"]
    if station_id is not None:
        station = stations.get(station_id)
        out["station"] = {"id": station_id, "kind": station["kind"] if station else "unknown"}
    props = {key: _prop(value) for key, value in sorted(raw.get("props", {}).items())}
    props["manifest_id"] = raw["id"]
    props["yaw_deg"] = _prop(yaw)
    if kind == "screen" and raw.get("size"):
        out["size_cm"] = [to_cm(v) for v in raw["size"]]
    if raw.get("normal") is not None:
        nx, ny, nz = (float(v) for v in raw["normal"])
        props["normal"] = _prop([round(v, 6) for v in (nx, nz, ny)])
    if raw.get("corners"):
        props["corners_cm"] = _prop(
            [[round(v, 3) for v in ue_space.three_to_ue(c)] for c in raw["corners"]]
        )
    if kind == "light":
        out["light"] = _light_block(raw)
    if kind == "spawn":
        out["spawn"] = {"team": "any", "duel": False}
    if kind == "station" and raw["id"] in stations:
        station = stations[raw["id"]]
        for group, ids in sorted(station.get("sockets", {}).items()):
            props[f"sockets.{group}"] = ",".join(ids)
        props["station_yaw_deg"] = _prop(float(station.get("yaw_deg", 0.0)))
    out["props"] = props
    return out


def _load_zone_module(path: Path):
    name = f"verse_zones_{path.parent.name}_{path.stem}"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def zone_builders(deck: str) -> list[Path]:
    if deck == "hangar":
        folder = DECKS_ROOT / "hangar" / "zones"
        return [folder / f"{zone}.py" for zone in HANGAR_ZONES]
    return [DECKS_ROOT / deck / "zones.py"]


def zones_of(deck: str) -> list[Zone]:
    out: list[Zone] = []
    for path in zone_builders(deck):
        module = _load_zone_module(path)
        builder = path.relative_to(REPO_ROOT).as_posix()
        found = list(getattr(module, "ZONES", ())) or [module.ZONE]
        for zone in found:
            out.append(Zone(zone.id, tuple(zone.rooms), zone.rest, builder))
    return out


def load_manifest(deck: str, root: Path = MANIFEST_ROOT) -> dict:
    return json.loads((root / deck / "manifest.json").read_text(encoding="utf-8"))


def _sha256(paths: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()


def assign_zones(manifest: Mapping[str, Any], zones: Sequence[Zone]) -> dict[str, str]:
    """Room id -> zone id. Rooms no zone claims go to the `rest` zone (if any)."""
    owner: dict[str, str] = {}
    for zone in zones:
        for room in zone.rooms:
            if room in owner:
                raise ValueError(f"room {room!r} is claimed by {owner[room]} and {zone.id}")
            owner[room] = zone.id
    rest = [z for z in zones if z.rest]
    for room in manifest["rooms"]:
        if room["id"] not in owner and rest:
            owner[room["id"]] = rest[0].id
    return owner


def build_zone_docs(deck: str, manifest: Mapping[str, Any] | None = None) -> list[dict]:
    """Every WP12 zone document of `deck`, canonical and validated."""
    manifest = manifest if manifest is not None else load_manifest(deck)
    zones = zones_of(deck)
    room_zone = assign_zones(manifest, zones)
    docs = {zone.id: _ZoneDoc(zone) for zone in zones}
    rooms = {room["id"]: convert_room(room) for room in manifest["rooms"]}
    for room_id, zone_id in room_zone.items():
        docs[zone_id].rooms.append(rooms[room_id])
    stations = {station["id"]: station for station in manifest.get("stations", [])}

    for raw in manifest["sockets"]:
        converted = convert_socket(raw, stations)
        zone_id = room_zone.get(raw.get("room")) if raw.get("room") else None
        if zone_id is None and raw.get("room") is None:
            plan = converted["location"][:2]
            best = None
            for zid, doc in docs.items():
                if not doc.rooms:
                    continue
                distance = min(polygon_distance(plan, r["polygon_cm"]) for r in doc.rooms)
                if best is None or distance < best[0]:
                    best = (distance, zid)
            zone_id = best[1] if best else None
        if zone_id is None:
            continue  # a room another package owns (hangar arena zones)
        if converted["room"] is not None and converted["room"] not in room_zone:
            converted["room"] = None
        docs[zone_id].sockets.append(converted)

    manifest_path = MANIFEST_ROOT / deck / "manifest.json"
    shared = [Path(__file__), ART_ROOT / "lib" / "ue_space.py", ART_ROOT / "lib" / "placement.py"]
    out = []
    for doc in docs.values():
        out.append(_finish(deck, doc, shared, manifest_path))
    return out


def _finish(deck: str, doc: _ZoneDoc, shared: list[Path], manifest_path: Path) -> dict:
    xs: list[float] = []
    ys: list[float] = []
    zs: list[float] = []
    for room in doc.rooms:
        for x, y in room["polygon_cm"]:
            xs.append(x)
            ys.append(y)
        zs.append(room["z_cm"])
    for socket in doc.sockets:
        x, y, z = socket["location"]
        xs.append(x)
        ys.append(y)
        zs.append(z)
    if not xs:
        raise ValueError(f"{deck}/{doc.zone.id}: zone has no rooms and no sockets")
    floor = min(zs)
    bounds = {
        "min": [min(xs) - ZONE_MARGIN_CM, min(ys) - ZONE_MARGIN_CM, floor - ZONE_BELOW_CM],
        "max": [max(xs) + ZONE_MARGIN_CM, max(ys) + ZONE_MARGIN_CM, max(zs) + ZONE_ABOVE_CM],
    }
    builder = REPO_ROOT / doc.zone.builder
    result = {
        "schema": placement.SCHEMA_ID,
        "deck": deck,
        "zone": doc.zone.id,
        "bounds_cm": bounds,
        "level": placement.level_path(deck),
        "source": {
            "builder": doc.zone.builder,
            "sha256": _sha256([builder, *shared, manifest_path]),
        },
        "generator": dict(GENERATOR),
        "placements": [],
        "sockets": doc.sockets,
        "rooms": doc.rooms,
    }
    return placement.canonical(result)


def zone_path(deck: str, zone: str) -> Path:
    return PLACEMENTS_ROOT / deck / f"{zone}.placement.json"


def write_all(
    decks: Sequence[str] = (*AGENT_DECKS, "hangar"), *, check: bool = False
) -> list[str]:
    """Write (or, with `check`, compare) every WP12 zone file; return the stale ones."""
    stale = []
    for deck in decks:
        for doc in build_zone_docs(deck):
            path = zone_path(deck, doc["zone"])
            text = placement.dumps(doc)
            current = path.read_text(encoding="utf-8") if path.is_file() else None
            if current == text:
                continue
            stale.append(path.relative_to(REPO_ROOT).as_posix())
            if not check:
                placement.write(path, doc)
    return stale


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--check", action="store_true", help="fail when a zone file is stale")
    options = parser.parse_args(argv)
    stale = write_all(check=options.check)
    for path in stale:
        print(f"[verse] {'stale' if options.check else 'wrote'} {path}")
    if options.check and stale:
        print("[verse] run python art/verse/kit/deck_import.py", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
