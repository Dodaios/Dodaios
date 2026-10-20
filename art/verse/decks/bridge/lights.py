"""Ceilings and their light fixtures (camera-invisible; they light the deck
and mirror in the black floor).

Bridge hall, ceiling at 7.2 m: two continuous lines of long diffusers along
the walkway (their reflections run up the walkway like rails of light),
cross rows over the pits on a 3.6 m rhythm, a row along the viewport wall
that washes the sill and the frames, and one along the aft gallery. The
aft rooms get the kit's regular 2.4 m panel grid at 3.6 m.
"""

from __future__ import annotations

from lib import kit, scene
from mathutils import Matrix

from . import layout as L

# Over the aisle just north of each rack wall: their mirror images in the
# satin pit floor land behind the next rack wall, out of the camera's view.
PIT_ROWS_Z = (9.95, 14.75, 19.55, 23.85)  # last row clear of the aft coping's mirror line


def _panel(prefix, x, z, size, height):
    from kit.architecture import ceiling

    ceiling.light_panel(prefix, (x, -z, height), size)


def build_hall() -> None:
    from kit.architecture import ceiling

    h = L.HALL_CEILING
    ceiling.ceiling_slab("CEIL_bridge", L.poly(L.hall_outline()), h, thickness=0.12)
    count = 0
    # Walkway rails of light.
    for x in (L.AXIS_X - 2.4, L.AXIS_X + 2.4):
        z = L.FORWARD_EDGE_Z + 2.4
        while z <= L.BULKHEAD_Z[0] - 1.0:
            _panel(f"LGT_walk_{x:.0f}_{z:.0f}", x, z, (0.12, 1.2), h)
            count += 1
            z += 4.8
    # Over both pits: long diffusers above each desk row and the front aisle.
    for side in (-1, 1):
        for j, z in enumerate(PIT_ROWS_Z):
            x = 7.2
            while x <= 26.4:  # stay over the rack walls (they hide the mirror images)
                if x + z > 16.0:
                    px = x if side < 0 else L.mirror_x(x)
                    tag = "p" if side < 0 else "s"
                    _panel(f"LGT_pit_{tag}_{j}_{x:.0f}", px, z, (2.4, 0.3), h)
                    count += 1
                x += 4.8
    # Along the viewport wall (washes the sill), skipping the walkway head.
    x = L.VP_CENTRE_X[0] + 1.2
    while x <= L.VP_CENTRE_X[1] - 1.2:
        # Only over the pits' rack walls: their mirror images land behind row 1.
        if x <= 26.4 + 1e-6 or x >= L.mirror_x(26.4) - 1e-6:
            _panel(f"LGT_fwd_{x:.0f}", x, L.VP_FACE_Z + 2.0, (1.2, 0.3), h)
            count += 1
        x += 2.4
    x = L.SIDE_WALL_X[0] + 1.2
    while x <= L.SIDE_WALL_X[1] - 1.2:
        _panel(f"LGT_aft_{x:.0f}", x, L.AFT_EDGE_Z + 1.2, (1.2, 0.3), h)
        count += 1
        x += 2.4
    kit.socket(
        "light",
        "bridge_ceiling",
        Matrix.Translation(L.P(L.AXIS_X, 18.0, h - 0.06)) @ Matrix.Rotation(3.14159265, 4, "X"),
        room="bridge",
        light_kind="ceiling_grid",
        count=count,
        kelvin=6200.0,
    )


ROOM_FIXTURES = {
    # room: [(x, z, (size_x, size_z)), ...] - pools of light, not a grid.
    # Placed so their mirror images miss the lacquered table and desk tops.
    "briefing": [
        *[(x, 38.6, (1.8, 0.4)) for x in (13.0, 15.9, 18.8)],
        *[(x, 35.0, (1.2, 0.3)) for x in (10.8, 15.9, 21.0)],
    ],
    "lobby": [
        (33.6, 37.8, (1.2, 0.4)),
        (38.4, 37.8, (1.2, 0.4)),
        (32.4, 34.8, (1.2, 0.3)),
        (39.6, 34.8, (1.2, 0.3)),
    ],
    "ready": [
        (56.4, 36.8, (2.4, 0.4)),
        (63.0, 39.4, (1.2, 0.4)),
        (53.4, 34.6, (1.2, 0.3)),
        (59.4, 34.6, (1.2, 0.3)),
        (48.6, 39.0, (1.2, 0.4)),
    ],
}


def build_rooms() -> None:
    from kit.architecture import ceiling

    for room, (x0, x1) in (
        ("briefing", L.BRIEFING_X),
        ("lobby", L.LOBBY_X),
        ("ready", L.READY_X),
    ):
        ceiling.ceiling_slab(
            f"CEIL_{room}", L.rect(x0, L.ROOMS_Z[0], x1, L.ROOMS_Z[1]), L.ROOM_CEILING
        )
        for i, (x, z, size) in enumerate(ROOM_FIXTURES[room]):
            _panel(f"LGT_{room}_{i:02d}", x, z, size, L.ROOM_CEILING)
        kit.socket(
            "light",
            f"{room}_ceiling",
            Matrix.Translation(L.P((x0 + x1) / 2, sum(L.ROOMS_Z) / 2, L.ROOM_CEILING - 0.06))
            @ Matrix.Rotation(3.14159265, 4, "X"),
            room=room,
            light_kind="ceiling_fixtures",
            count=len(ROOM_FIXTURES[room]),
            kelvin=6200.0,
        )


def build() -> None:
    with kit.into(scene.collection("Ceiling")):
        build_hall()
        build_rooms()
