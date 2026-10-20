"""Deck 4 `hangar` layout: every rectangle and anchor the builder uses.

Plan coordinates are LEVELS.md coordinates: x grows to screen right, z grows
toward the camera (screen bottom), z = 0 is the far hull wall. Blender axes
are (x, -z, height); use :func:`B` to convert.

Composition (top of the screen first):

* hero wall (z 0..3): closed blast doors centred on x = 50, angled piers with
  light strips either side, a gantry rail and flood lights above.
* flight deck (z 3..46): the shuttle on its pad on the centre axis, ramp down
  toward the camera; the launch well on the left; ordered cargo rows under a
  portal gantry on the right; stores and ground equipment on the lower left;
  two formation fields flank the arrivals walkway.
* front band (z 46..62): control booth (raised), ground-crew bay, arrivals
  desk on the centre axis, turbolift lobby, armoury.
"""

from __future__ import annotations

from dataclasses import dataclass

DECK_ID = "hangar"
NAME = "Main Hangar"
FLOOR_INDEX = 4

WIDTH = 100.0
DEPTH = 62.0

# Hero wall
WALL_TOP = 22.0  # built height; the frame shows ~21 m of it
VIEW_TOP = 18.0  # Bounds.z_max: the height of the hero wall the plate frames
WALL_FACE_Z = 1.5  # plan z of the panelled wall face (Blender y = -1.5)
PIER_FRONT_Z = 3.0  # angled piers reach this far into the hall
DOOR_X = (32.0, 68.0)  # clear opening of the blast door piece
DOOR_H = 16.0
FRAME_W = 2.4  # pressure frame width around the opening
RAIL_Z = 15.6  # gantry rail height on the hero wall

# Side hull walls (full height over the flight deck, cut in the front band)
SIDE_T = 2.5  # x 0..2.5 and 97.5..100

# Flight deck
DECK_Z = (WALL_FACE_Z, 46.0)
WELL = (8.0, 38.0, 8.0, 20.0)  # x0, x1, z0, z1 of the launch well opening
WELL_DEPTH = 26.0
PAD_C = (50.0, 23.6)
PAD_R = 8.4
SHUTTLE_C = (50.0, 23.6)  # piece origin of the shuttle (nose toward the doors)
SHUTTLE_L = 20.0
RAMP_FOOT = (50.0, 38.14)  # SOCKET_spawn_arrival (the shuttle piece's ramp foot)
WALKWAY_X = (48.6, 51.4)
WALKWAY_Z = (39.0, 48.6)
FORMATION_L = (36.6, 46.2, 35.4, 42.6)
FORMATION_R = (53.8, 63.4, 35.4, 42.6)
CARGO = (69.2, 91.6, 5.4, 43.2)
GANTRY_RAILS_X = (68.4, 92.4)
GANTRY_Z = 31.2  # between the high-bay rows, so no fitting sits right over the trolley
STORES = (4.0, 34.0, 25.0, 43.0)

# Front band
FRONT_Z = 46.0
NEAR_WALL_Z = (61.6, 62.6)
CUT_H = 1.1
BOOTH = (3.0, 25.0, 47.2, 61.6)
BOOTH_FLOOR = 1.2
CREW_BAY = (25.0, 40.0)
ARRIVALS = (40.0, 62.0)
DESK_C = (50.0, 50.9)
LOBBY = (62.0, 77.0)
LIFT_HOUSING = (65.0, 75.0, 47.4, 50.6)
LIFT_HOUSING_H = 3.9
ARMOURY = (77.0, 97.5, 47.2, 61.6)


def B(x: float, z: float, h: float = 0.0) -> tuple[float, float, float]:
    """Plan (x, z) plus height -> Blender (x, y, z)."""
    return (x, -z, h)


def rect_xy(x0: float, x1: float, z0: float, z1: float) -> list[tuple[float, float]]:
    """Counter-clockwise Blender XY polygon of a plan rectangle."""
    return [(x0, -z1), (x1, -z1), (x1, -z0), (x0, -z0)]


@dataclass(frozen=True)
class Waypoint:
    loop: str
    order: int
    x: float
    z: float


# Patrol loops for the ship's company (ambient troopers and drones).
PATROLS: dict[str, list[tuple[float, float]]] = {
    "pad": [(40.2, 11.0), (60.0, 11.0), (62.4, 23.0), (60.0, 34.2), (40.2, 34.2), (39.8, 23.0)],
    "wall": [(6.0, 5.4), (28.0, 5.4), (72.0, 5.4), (94.0, 5.4)],
    "cargo": [
        (66.0, 5.4),
        (76.2, 5.4),
        (76.2, 44.0),
        (84.7, 44.0),
        (84.7, 5.4),
        (94.6, 5.4),
        (94.6, 44.0),
        (66.0, 44.0),
    ],
    "front": [(27.0, 45.0), (47.0, 45.0), (64.0, 45.0)],
    "well": [(6.0, 23.4), (36.0, 23.4), (39.6, 14.0), (36.0, 6.0), (6.0, 6.0)],
}
