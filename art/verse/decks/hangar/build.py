"""Deck 4 `hangar`: the Main Hangar, where new agents arrive by shuttle.

A 100 x 62 m flight deck seen from the gallery: the hero wall with the closed
blast doors at the top of the plate, the shuttle on its pad on the centre axis
with the ramp down toward the camera, the launch well under its blue field on
the left, ordered cargo under a portal gantry on the right; along the front
the raised control booth, the ground-crew bay, the arrivals desk, the lift
lobby and the armoury.

Layout: hangar_layout.py. Floor paint and grime: hangar_paint.py.
Architecture: hangar_arch.py. Dressing: hangar_props.py. Light: hangar_light.py.

Run: python scripts/verse/cook.py deck hangar --quality preview
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import bpy  # noqa: E402
import hangar_arch as arch  # noqa: E402
import hangar_layout as L  # noqa: E402
import hangar_light as light  # noqa: E402
import hangar_props as props  # noqa: E402
from lib import kit, scene  # noqa: E402

B = L.B
EXPOSURE = -0.5


def _rooms() -> None:
    # Probe points sit on open floor at eye height (the centroids can fall in
    # the shuttle or a rack).
    def probe(x, z, floor=0.0):
        return B(x, z, floor + 1.4)

    kit.room(
        "flight_deck",
        "Flight Deck",
        L.rect_xy(2.5, 97.5, 1.5, 46.0),
        main=True,
        probe_at=probe(33.0, 24.5),
    )
    bx0, bx1, bz0, bz1 = L.BOOTH
    kit.room(
        "booth",
        "Control Booth",
        L.rect_xy(bx0, bx1, bz0, bz1),
        z=L.BOOTH_FLOOR,
        probe_at=probe(14.0, 51.6, L.BOOTH_FLOOR),
    )
    kit.room(
        "crew_bay",
        "Ground Crew Bay",
        L.rect_xy(L.CREW_BAY[0], L.CREW_BAY[1], 46.0, 61.6),
        probe_at=probe(36.0, 51.0),
    )
    kit.room(
        "arrivals",
        "Arrivals",
        L.rect_xy(L.ARRIVALS[0], L.ARRIVALS[1], 46.0, 61.6),
        probe_at=probe(50.0, 55.5),
    )
    kit.room(
        "lift_lobby",
        "Lift Lobby",
        L.rect_xy(L.LOBBY[0], L.LOBBY[1], 46.0, 61.6),
        probe_at=probe(70.0, 56.5),
    )
    ax0, ax1, az0, az1 = L.ARMOURY
    kit.room("armoury", "Armoury", L.rect_xy(ax0, ax1, az0 + 0.3, az1), probe_at=probe(89.0, 52.4))


def _yaw_toward(a, b) -> float:
    """Socket yaw (0 = facing the camera, three +Z) looking from plan a to plan b."""
    dx, dz = b[0] - a[0], b[1] - a[1]
    return round(math.degrees(math.atan2(dx, dz)), 2)


def _sockets() -> None:
    add = scene.add_socket
    # New agents step off the shuttle ramp; the commander arrives by lift.
    add("spawn", "commander", B(70.0, 54.2), 0.0, room="lift_lobby")
    # Lift: doors face the camera; the commander stands in front to call it.
    add("lift", "main", B(68.0, 51.0), 0.0, decks="all", room="lift_lobby")
    add("station", "lift", B(68.0, 52.4), 180.0, station_kind="lift", room="lift_lobby")
    add("door", "lift_a", B(68.0, 50.72), 0.0, width=2.0, station="lift")
    add("door", "lift_b", B(72.0, 50.72), 0.0, width=2.0, station="lift")
    # Arrivals desk: the commander works the terminal from the camera side,
    # the arriving agent reports on the far side, facing the commander.
    dx, dz = L.DESK_C
    if bpy.data.objects.get("SOCKET_station_arrivals") is None:  # bespoke counter
        add(
            "station",
            "arrivals",
            B(dx, dz + 1.45),
            180.0,
            station_kind="create_agent",
            room="arrivals",
        )
        add("stand", "arrivals_report", B(dx, dz - 1.15), 0.0, station="arrivals", room="arrivals")
    for k, x in enumerate((dx - 0.9, dx + 0.9), start=1):
        add("stand", f"arrivals_queue_{k}", B(x, L.WALKWAY_Z[1] - 1.6), 0.0, room="flight_deck")
    # Ceremonial welcome: two files flanking the walkway at the ramp foot.
    n = 0
    for side in (-1, 1):
        for row in range(4):
            n += 1
            x = 50.0 + side * 3.0
            z = L.RAMP_FOOT[1] + 0.6 + row * 1.8
            add("stand", f"welcome_{n:02d}", B(x, z), -90.0 * side, room="flight_deck")
    # Patrol loops for the ship's company.
    for loop, points in L.PATROLS.items():
        for i, p in enumerate(points):
            q = points[(i + 1) % len(points)]
            add("waypoint", f"{loop}_{i + 1:02d}", B(*p), _yaw_toward(p, q), loop=loop, order=i + 1)
    # Beacons the runtime animates.
    add(
        "light",
        "lift_beacon",
        B(70.0, 49.0, L.LIFT_HOUSING_H + 0.65),
        0.0,
        colour="#ff4a1a",
        blink_hz=0.5,
    )
    x0, x1, z0, z1 = L.WELL
    for k, (x, z) in enumerate(
        ((x0 - 0.6, z0 - 0.6), (x1 + 0.6, z0 - 0.6), (x0 - 0.6, z1 + 0.6), (x1 + 0.6, z1 + 0.6)),
        start=1,
    ):
        add("light", f"well_beacon_{k}", B(x, z, 0.3), 0.0, colour="#ffae2a", blink_hz=1.0)
    add(
        "light",
        "door_warning",
        B(50.0, L.PIER_FRONT_Z, L.DOOR_H + 3.6),
        0.0,
        colour="#ff2a1a",
        blink_hz=0.0,
    )


def build() -> None:
    bounds = scene.Bounds(
        x_min=0.0, y_min=-L.DEPTH, x_max=L.WIDTH, y_max=0.0, z_min=0.0, z_max=L.VIEW_TOP
    )
    scene.new_deck(L.DECK_ID, bounds, name=L.NAME, floor=L.FLOOR_INDEX, exposure=EXPOSURE)
    pieces = props.load_kit()
    well_piece = False  # bespoke dark shaft (art direction), not the kit well
    arch.floors(well_piece=well_piece)
    mounts = arch.hero_wall(door_piece="SM_Hangar_BlastDoor" in pieces)
    arch.side_walls()
    arch.launch_well(well_piece=well_piece)
    arch.front_band()
    arch.ceiling()
    arch.occluders(well_piece=well_piece)
    props.build_all()
    light.build(mounts)
    _rooms()
    _sockets()


if __name__ == "__main__":
    build()
