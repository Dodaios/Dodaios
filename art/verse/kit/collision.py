"""Authored simple collision for kit pieces whose bounding box is the wrong shape (WP12.2, WP12.3).

Pure Python, no bpy. A kit piece exports with an auto box (its bounds) unless it is
listed here (contracts/art-pipeline.md 5). This module lists the pieces where that box
would be wrong for a walking pawn:

* stairs (`SM_Stairs_<w>_H<rise>`): a solid block would fill the flight, so each gets
  one box per tread plus a ramp under the noses (art-pipeline 5: "a ramp box plus step
  boxes"); the flight descends toward +X from the top edge at X = 0, Z = 0
  (`kit/architecture/structure.py`);
* open blast doors: two jamb boxes and, when the frame is taller than the opening,
  a lintel box, so the doorway stays open;
* hollow or see-through reactor pieces (shaft, collar, control ring, catwalks, haze):
  no collision of their own. Their walkable tops and rails come from the deck bounds
  (`kit/deck_bounds.py`), which follow today's nav grid exactly.

Primitives are in piece space, Blender metres: `("box", lo, hi)` for an axis-aligned
box, `("obox", points)` for the eight corners of an oriented box.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence

#: Tread depth and riser height of the kit stairs (`kit/architecture/structure.py`).
TREAD_M = 0.3
RISER_M = 0.2
#: Thickness of the ramp under the stair noses.
RAMP_THICKNESS_M = 0.3
#: Blast door opening (`kit/architecture/doors.py`).
DOOR_OPENING_W = 2.4
DOOR_OPENING_H = 3.0

#: Pieces with no collision of their own; the deck bounds carry their floors and rails.
NO_COLLISION = frozenset(
    {
        "SM_Reactor_Shaft",
        "SM_Reactor_Collar",
        "SM_Reactor_ControlRing",
        "SM_Reactor_Catwalk",
        "SM_Reactor_Haze",
        "SM_Space_Earth",
        "SM_Space_StarDome",
    }
)

_STAIRS = re.compile(r"^SM_Stairs_(?P<w>\d+)_H(?P<rise>\d+)$")
_OPEN_DOOR = re.compile(r"^SM_BlastDoor_240(?:_Cut)?$")

Primitive = tuple


def stairs(width_m: float, rise_m: float) -> list[Primitive]:
    """Step boxes (one per tread, from the bottom floor up to the tread) and a ramp."""
    steps = round(rise_m / RISER_M)
    hw = width_m / 2.0
    out: list[Primitive] = []
    for i in range(steps - 1):
        top = -(i + 1) * RISER_M
        out.append(("box", (i * TREAD_M, -hw, -rise_m), ((i + 1) * TREAD_M, hw, top)))
    # The ramp's top runs through the front edge of every tread, from the walkway edge
    # (0, 0) down to the bottom floor at x = rise * tread / riser: one box turned about Y
    # (Interchange keeps the rotation of UBX_ boxes and drops UCX_ hulls).
    end = rise_m * TREAD_M / RISER_M
    length = math.hypot(end, rise_m)
    nx, nz = rise_m / length, end / length  # up, out of the slope
    drop = RAMP_THICKNESS_M
    top = [(0.0, 0.0), (end, -rise_m)]
    profile = top + [(x - nx * drop, z - nz * drop) for x, z in top]
    points = [(x, y, z) for x, z in profile for y in (-hw, hw)]
    out.append(("obox", points))
    return out


def open_door(bounds_min: Sequence[float], bounds_max: Sequence[float]) -> list[Primitive]:
    """Jambs either side of the opening and a lintel above it (when the frame is that tall)."""
    hw = DOOR_OPENING_W / 2.0
    x0, y0, z0 = bounds_min
    x1, y1, z1 = bounds_max
    out: list[Primitive] = [
        ("box", (x0, y0, z0), (-hw, y1, z1)),
        ("box", (hw, y0, z0), (x1, y1, z1)),
    ]
    if z1 > DOOR_OPENING_H + 0.05:
        out.append(("box", (-hw, y0, DOOR_OPENING_H), (hw, y1, z1)))
    return out


def recipe(name: str, bounds_min: Sequence[float], bounds_max: Sequence[float]):
    """Primitives for `name`; [] for no collision; None to keep the auto box."""
    if name in NO_COLLISION:
        return []
    match = _STAIRS.match(name)
    if match:
        return stairs(int(match["w"]) / 100.0, int(match["rise"]) / 100.0)
    if _OPEN_DOOR.match(name):
        return open_door(bounds_min, bounds_max)
    return None


def record_collision(name: str, profile: str, primitives: int) -> dict | None:
    """The import record `collision` block for a piece listed here; None for the rest."""
    if name in NO_COLLISION:
        return {"profile": "Verse_NoCollision", "source": "none", "primitives": 0}
    if _STAIRS.match(name) or _OPEN_DOOR.match(name):
        return {"profile": profile, "source": "authored", "primitives": primitives}
    return None


def walked_on_its_own(name: str) -> bool:
    """True for pieces whose own collision carries the commander (the stairs)."""
    return bool(_STAIRS.match(name))
