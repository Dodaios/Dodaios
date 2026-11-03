"""WP12: deck bounds, the pawn collision of the deck shells, follow today's nav (art-pipeline 5)."""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "art" / "verse"))

from kit import deck_bounds, deck_import  # noqa: E402


def nav_from(rows: list[str], heights: dict[str, float] | None = None) -> deck_bounds.Nav:
    """A nav grid from text: `.` blocked, any other letter walkable at `heights[letter]` (0 m)."""
    heights = heights or {}
    walk = np.array([[ch != "." for ch in row] for row in rows])
    height = np.array([[heights.get(ch, 0.0) for ch in row] for row in rows], dtype=float)
    return deck_bounds.Nav(
        walk=walk,
        height=np.where(walk, height, np.nan),
        cell=1.0,
        origin_x=0.0,
        origin_z=0.0,
        max_step=0.3,
    )


def rect(x0, z0, x1, z1):
    return [[x0, z0], [x1, z0], [x1, z1], [x0, z1]]


TWO_ROOMS = [
    "..........",
    ".aaaa.bbb.",
    ".aaaa.bbb.",
    ".aaaaabbb.",  # the doorway: row 3, column 5
    ".aaaa.bbb.",
    "..........",
]


def covered(boxes, x: float, z: float, kind: str) -> bool:
    for box in boxes:
        if box.kind != kind:
            continue
        cx, _cy, cz = box.centre
        length, _h, width = box.size
        dx, dz = x - cx, z - cz
        along = dx * math.cos(box.yaw) + dz * math.sin(box.yaw)
        across = -dx * math.sin(box.yaw) + dz * math.cos(box.yaw)
        if abs(along) <= length / 2 + 1e-9 and abs(across) <= width / 2 + 1e-9:
            return True
    return False


def test_floors_cover_every_walkable_cell_of_a_zone():
    nav = nav_from(TWO_ROOMS)
    zones = {"west": [rect(1, 1, 5, 5)], "east": [rect(5, 1, 9, 5)]}
    boxes = deck_bounds.deck_boxes(nav, zones, [], [])
    everything = boxes["west"] + boxes["east"]
    for r, c in zip(*np.nonzero(nav.walk), strict=True):
        x, z = nav.centre(r, c)
        assert covered(everything, x, z, "floor"), (r, c)
    for box in everything:
        if box.kind == "floor":
            assert box.centre[1] + box.size[1] / 2 == pytest.approx(0.0)


def test_walls_close_the_rooms_and_leave_the_doorway_open():
    nav = nav_from(TWO_ROOMS)
    zones = {"west": [rect(1, 1, 5, 5)], "east": [rect(5, 1, 9, 5)]}
    boxes = deck_bounds.deck_boxes(nav, zones, [], [])
    walls = boxes["west"] + boxes["east"]
    # Just outside the north wall of the west room, and outside the east room's far side.
    assert covered(walls, 2.5, 0.9, "wall")
    assert covered(walls, 9.1, 2.5, "wall")
    # The wall between the rooms is there above and below the doorway, not in it.
    assert covered(walls, 5.15, 1.5, "wall") and covered(walls, 5.85, 1.5, "wall")
    assert not covered(walls, 5.15, 3.5, "wall") and not covered(walls, 5.85, 3.5, "wall")
    for box in walls:
        if box.kind == "wall":
            assert box.size[2] >= 0.2  # art-pipeline 5: at least 20 cm thick
            assert box.centre[1] - box.size[1] / 2 < 0.0 < box.centre[1] + box.size[1] / 2


def test_a_drop_deeper_than_a_step_is_walled_and_a_gentle_slope_is_not():
    rows = [
        "........",
        ".aaabbb.",
        ".aaaccc.",
        "........",
    ]
    nav = nav_from(rows, {"a": 0.0, "b": -1.4, "c": -0.2})
    boxes = deck_bounds.deck_boxes(nav, {"deck": [rect(1, 1, 7, 3)]}, [], [])["deck"]
    assert covered(boxes, 3.85, 1.5, "wall")  # a -> b drops 1.4 m: walled on the high side
    assert not covered(boxes, 3.85, 2.5, "wall")  # a -> c is a 0.2 m step
    floors = [b for b in boxes if b.kind == "floor"]
    tops = sorted({round(b.centre[1] + b.size[1] / 2, 2) for b in floors})
    assert tops == [-1.4, -0.2, 0.0]


def test_props_and_own_walk_pieces_take_their_own_cells():
    nav = nav_from(["......", ".aaaa.", ".aaaa.", "......"])
    prop = [[2.0, 1.0], [3.0, 1.0], [3.0, 3.0], [2.0, 3.0]]
    with_prop = deck_bounds.deck_boxes(nav, {"z": [rect(1, 1, 5, 3)]}, [prop], [])["z"]
    plain = deck_bounds.deck_boxes(nav, {"z": [rect(1, 1, 5, 3)]}, [], [])["z"]
    assert sum(b.kind == "wall" for b in with_prop) < sum(b.kind == "wall" for b in plain)
    own = deck_bounds.deck_boxes(nav, {"z": [rect(1, 1, 5, 3)]}, [], [prop])["z"]
    assert not covered([b for b in own if b.kind == "floor"], 2.5, 1.5, "floor")


def test_blender_boxes_mirror_three_z():
    box = deck_bounds.Box("wall", (2.0, 1.0, 3.0), (4.0, 2.0, 0.3), math.radians(30.0))
    out = deck_bounds.to_blender(box)
    assert out["centre"] == [2.0, -3.0, 1.0]
    assert out["size"] == [4.0, 0.3, 2.0]
    assert out["yaw_deg"] == pytest.approx(-30.0)


@pytest.mark.parametrize("deck", ["bridge", "ops", "engineering", "hangar"])
def test_every_wp12_zone_of_the_real_decks_gets_floors_and_walls(deck):
    boxes = deck_import.bounds_boxes(deck)
    assert set(boxes) == {zone.id for zone in deck_import.zones_of(deck)}
    for zone, items in boxes.items():
        assert any(b.kind == "floor" for b in items), zone
        assert any(b.kind == "wall" for b in items), zone


def test_the_reactor_ring_and_catwalks_get_floors_and_rails():
    boxes = deck_import.bounds_boxes("engineering")["reactor"]
    walls = sum(b.kind == "wall" for b in boxes)
    assert walls > 100  # the shaft rim, both ring edges and both sides of four catwalks
