"""Hull structure around the engineering deck's rooms (the plate's border).

Every part of the plate outside the rooms is ship (ART_DIRECTION: no voids):
open hull bays from the kit (frames, stringers, pipe runs, cable trays, dim
service lamps) below deck level along the west, east and near sides, and a
row of bays along the top of the far hull wall behind the hero wall. The
room-side walls are thin (0.3 m), so the bays read right up to the rooms.
"""

from __future__ import annotations

import eng_common as c
from lib import kit, scene

BAY = 2.4
VARIANTS = ("A", "B", "C", "D")
WALL_H1200 = "_H1200"  # far hull wall height variant of the kit hero wall


def register_variants() -> None:
    """12 m hero wall modules (the kit's light columns scale with height)."""
    from kit.architecture import walls

    for w in (1.2, 2.4, 4.8):
        name = f"SM_Wall_{round(w * 100)}{WALL_H1200}"
        if name not in kit.registry():
            kit.register_variant(
                name, walls.build_wall, dims=(w, walls.THICKNESS, c.HALL_H), width=w,
                height=c.HALL_H,
            )  # fmt: skip


def _bay_piece(i: int, j: int, salt: str) -> str:
    """Stable mix of bay variants with a sparse rhythm of service lamps."""
    h = kit.seed_for(salt, i, j)
    if (i + 2 * j) % 3 == 0:  # a lamp every third bay: the structure stays readable
        return "SM_Hull_Bay_LampRed" if h % 4 == 0 else "SM_Hull_Bay_LampWhite"
    return f"SM_Hull_Bay_{VARIANTS[(h >> 4) % len(VARIANTS)]}"


def _band(prefix: str, xs: list[float], zs: list[float], height: float = 0.0) -> None:
    with kit.into(scene.collection("Architecture")):
        for i, x in enumerate(xs):
            for j, z in enumerate(zs):
                kit.place(_bay_piece(i, j, prefix), c.b(x, z, height), 0.0,
                          id=f"{prefix}_{i:02d}_{j:02d}", nav="none")  # fmt: skip


def _steps(start: float, end: float) -> list[float]:
    """Bay centres from `start` (first bay's near edge) while the bay starts before `end`."""
    out, edge = [], start
    while edge < end - 1e-6:
        out.append(edge + BAY / 2)
        edge += BAY
    return out


def build() -> None:
    wall_in = c.WEST_HULL_X[1] - 0.3  # outer face of the thin west room wall
    east_out = c.EAST_HULL_X[0] + 0.3
    south_out = c.SOUTH_HULL_Z[0] + 0.3
    # West and east bands run the full depth; the near band spans the width.
    zs = _steps(c.FAR_WALL_Z - 0.3, south_out)
    _band("EngHullW", [wall_in - BAY / 2, wall_in - 1.5 * BAY], zs)
    _band("EngHullE", [east_out + BAY / 2, east_out + 1.5 * BAY], zs)
    xs = _steps(wall_in - 2 * BAY, east_out + 2 * BAY)
    _band("EngHullS", xs, [south_out + BAY / 2, south_out + 1.5 * BAY])
    # Behind the hero wall: one row of bays on top of the far hull backing.
    _band("EngHullN", xs, [c.FAR_WALL_Z - 0.3 - BAY / 2], height=c.HALL_H)
