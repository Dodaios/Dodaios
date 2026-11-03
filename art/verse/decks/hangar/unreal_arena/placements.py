"""`verse.placement/1` documents for the WP11 hangar zones (art-pipeline 4).

Graybox stage: every box of `layout` becomes one placement of its family's
graybox mesh, `SM_<Family>` (a 1 m cube, pivot at the bottom centre) scaled
to the box, or `GC_<Family>` with its proxies for the destructibles. The art
pass swaps the meshes behind the same ids, so actor files keep their names.
Spawns and lights are sockets; stations are placements with a `station`.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path

from . import layout as L

PACKAGE = Path(__file__).resolve().parent
REPO = PACKAGE.parents[4]
BUILDER = "art/verse/decks/hangar/unreal_arena/layout.py"
GENERATOR = {"script": "unreal_arena_build.py", "version": "1", "blender": "0.0.0"}
DESTRUCTIBLE_CLASS = "/Script/VerseDestruction.VerseDestructible"
STATES = ["Intact", "Damaged", "Holed", "Breached", "Destroyed", "Repairing"]
PROXY_STATES = ["Intact", "Holed", "Breached", "Destroyed"]
LAYERS = {"base": "DL_Hangar_Base", "day": "DL_Hangar_Day", "arena": "DL_Hangar_Arena"}
FOLDERS = {
    "shell": "Shell",
    "arena_canyon": "ArenaCanyon",
    "arena_shuttle": "ArenaShuttle",
    "arena_booth": "ArenaBooth",
    "arena_catwalks": "ArenaCatwalks",
    "armoury": "Armoury",
}


def cm(v: float) -> float:
    return round(v * 100.0, 3)


def yaw_quat(heading_deg: float, pitch_deg: float = 0.0) -> list[float]:
    """Unreal [x, y, z, w] of FRotator(pitch, yaw, 0) (the engine's own formula)."""
    sp, cp = math.sin(math.radians(pitch_deg) / 2), math.cos(math.radians(pitch_deg) / 2)
    sy, cy = math.sin(math.radians(heading_deg) / 2), math.cos(math.radians(heading_deg) / 2)
    return [round(v, 7) + 0.0 for v in (sp * sy, -sp * cy, cp * sy, cp * cy)]


def asset(zone: str, name: str) -> str:
    return f"/Game/Verse/Decks/Hangar/{FOLDERS[zone]}/{name}.{name}"


def source_hash() -> str:
    h = hashlib.sha256()
    for name in sorted(p.name for p in PACKAGE.glob("*.py")):
        h.update(name.encode())
        h.update((PACKAGE / name).read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()


def _box_placement(box: L.Box) -> dict:
    sx, sz, sh = box.size
    destructible = None
    collision = "Verse_Architecture"
    if box.piece_class is not None:
        piece = f"GC_{box.family}"
        material, health, repair = L.PIECE_CLASSES[box.piece_class]
        destructible = {
            "actor_class": DESTRUCTIBLE_CLASS,
            "penetration_material": material,
            "health": health,
            "states": STATES,
            "proxies": {s: asset(box.zone, f"SM_{box.family}_Proxy_{s}") for s in PROXY_STATES},
            "repair_s": repair,
        }
        collision = "Verse_Destructible"
    else:
        piece = f"SM_{box.family}"
        if not box.solid:
            collision = "Verse_NoCollision"
        elif not box.sight:
            collision = "Verse_Prop"
    nav = "walk" if box.walk else ("block" if box.solid else "none")
    return {
        "id": box.id,
        "piece": piece,
        "asset": asset(box.zone, piece),
        "location": [cm((box.x0 + box.x1) / 2), cm((box.z0 + box.z1) / 2), cm(box.h0)],
        "rotation": [0.0, 0.0, 0.0, 1.0],
        "scale": [round(sx, 6), round(sz, 6), round(sh, 6)],
        "room": None,
        "nav": nav,
        "mobility": "movable" if destructible else "static",
        "data_layer": LAYERS[box.layer],
        "collision": collision,
        "destructible": destructible,
        "station": None,
        "owner": L.OWNER,
        "tags": [f"Verse.Material.{box.material}"],
    }


def _ramp_placement(ramp: L.Ramp) -> dict:
    sx, sz = ramp.x1 - ramp.x0, ramp.z1 - ramp.z0
    rise = abs(ramp.h_end - ramp.h_start)
    # The stair mesh rises along its local +X; turn it so it climbs the way the ramp does.
    if ramp.axis == "x":
        heading = 0.0 if ramp.h_end > ramp.h_start else 180.0
        length, width = sx, sz
    else:
        heading = 90.0 if ramp.h_end > ramp.h_start else 270.0
        length, width = sz, sx
    return {
        "id": ramp.id,
        "piece": f"SM_{ramp.family}",
        "asset": asset(ramp.zone, f"SM_{ramp.family}"),
        "location": [
            cm((ramp.x0 + ramp.x1) / 2),
            cm((ramp.z0 + ramp.z1) / 2),
            cm(min(ramp.h_start, ramp.h_end)),
        ],
        "rotation": yaw_quat(heading),
        "scale": [round(length, 6), round(width, 6), round(rise, 6)],
        "room": None,
        "nav": "walk",
        "mobility": "static",
        "data_layer": LAYERS[ramp.layer],
        "collision": "Verse_Architecture",
        "destructible": None,
        "station": None,
        "owner": L.OWNER,
    }


def _station_placement(st: L.Station) -> dict:
    sx, sz, sh = st.size
    return {
        "id": st.id,
        "piece": f"SM_{st.family}",
        "asset": asset(st.zone, f"SM_{st.family}"),
        "location": [cm(st.x), cm(st.z), cm(st.h)],
        "rotation": yaw_quat(st.heading_deg),
        "scale": [sx, sz, sh],
        "room": "armoury" if st.zone == "armoury" else None,
        "nav": "block",
        "mobility": "static",
        "data_layer": "DL_Hangar_Base",
        "collision": "Verse_Prop",
        "destructible": None,
        "station": {"id": st.id, "kind": st.kind},
        "owner": L.OWNER,
    }


def _light_socket(light: L.Light) -> dict:
    data = {
        "type": light.type,
        "kelvin": light.kelvin,
        "intensity_lm": light.intensity_lm,
        "attenuation_cm": cm(light.attenuation_m),
        "shadows": True,
    }
    if light.cone_deg is not None:
        data["cone_deg"] = light.cone_deg
    if light.source_size_m is not None:
        data["source_size_cm"] = cm(light.source_size_m)
    return {
        "id": f"light__{light.id}",
        "kind": "light",
        "location": [cm(light.x), cm(light.z), cm(light.h)],
        "rotation": yaw_quat(0.0, light.pitch_deg),
        "room": None,
        "station": None,
        "light": data,
    }


def _spawn_socket(spawn: L.Spawn) -> dict:
    return {
        "id": f"spawn__{spawn.id}",
        "kind": "spawn",
        "location": [cm(spawn.x), cm(spawn.z), cm(spawn.h)],
        "rotation": yaw_quat(spawn.heading_deg),
        "room": None,
        "station": None,
        "spawn": {"team": "any", "duel": True},
        "props": {"probe_heights_m": "0.3,1.0,1.65", "spawn_id": spawn.id},
    }


def _bounds(points: list[list[float]]) -> dict:
    lo = [min(p[i] for p in points) - 1.0 for i in range(3)]
    hi = [max(p[i] for p in points) + 1.0 for i in range(3)]
    return {"min": [round(v, 3) for v in lo], "max": [round(v, 3) for v in hi]}


def documents(layout: L.Layout) -> dict[str, dict]:
    """zone -> verse.placement/1 document."""
    digest = source_hash()
    out = {}
    for zone in L.ZONES:
        placements = [_box_placement(b) for b in layout.zone_boxes(zone)]
        placements += [_ramp_placement(r) for r in layout.zone_ramps(zone)]
        placements += [_station_placement(s) for s in layout.stations if s.zone == zone]
        sockets = [_light_socket(li) for li in layout.lights if li.zone == zone]
        sockets += [_spawn_socket(s) for s in layout.spawns if s.zone == zone]
        rooms = []
        if zone == "armoury":
            x0, x1, z0, z1 = L.ARMOURY
            rooms.append(
                {
                    "id": "armoury",
                    "name": "Armoury",
                    "polygon_cm": [
                        [cm(x0), cm(z0)],
                        [cm(x1), cm(z0)],
                        [cm(x1), cm(z1)],
                        [cm(x0), cm(z1)],
                    ],
                    "z_cm": 0.0,
                    "main": False,
                }
            )
        points = [p["location"] for p in placements] + [s["location"] for s in sockets]
        out[zone] = {
            "schema": "verse.placement/1",
            "deck": L.DECK,
            "zone": zone,
            "bounds_cm": _bounds(points),
            "level": "/Game/Verse/Decks/Hangar/LV_Hangar",
            "source": {"builder": BUILDER, "sha256": digest},
            "generator": dict(GENERATOR),
            "placements": placements,
            "sockets": sockets,
            "rooms": rooms,
        }
    return out
