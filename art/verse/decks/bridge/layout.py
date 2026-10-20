"""Command Bridge layout: every measurement of the deck in one place.

Plan coordinates are three.js metres as in LEVELS.md: ``x`` grows to screen
right, ``z`` grows toward the camera (screen bottom), ``z = 0`` is the far
edge of the plate. Builders convert to Blender axes with :func:`P`
(Blender X = x, Blender Y = -z, Blender Z = up). Edges sit on the 1.2 m
module, mirrored about the walkway axis ``x = 36``.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

M = 1.2  # module
AXIS_X = 36.0
WIDTH = 72.0
DEPTH = 44.0

# Heights (Blender Z).
PIT_Z = -1.4  # sunken crew pits
HALL_CEILING = 7.2  # bridge hall ceiling (camera-invisible)
ROOM_CEILING = 3.6  # aft rooms
CUT_H = 1.1  # cut-away walls (BRIEF section 5)

# Viewport wall: room face of the sill at z = 3.6; centre run and chamfers.
VP_FACE_Z = 3.6
VP_CENTRE_X = (8.4, 63.6)  # includes a 1.2 m corner pier at each end
VP_BAY = 4.8
VP_BAYS = 11
SIDE_WALL_X = (3.6, 68.4)  # inner faces of the side hull walls
SIDE_WALL_T = 1.2
CHAMFER = 4.8  # legs of the 45 degree corner chamfers

# Upper deck (y = 0) and the two pits.
FORWARD_EDGE_Z = 7.2  # pits start here (forward gallery z 3.6 .. 7.2)
AFT_EDGE_Z = 28.8  # pits end here (aft gallery z 28.8 .. 31.2)
PIT_CHAMFER = ((9.6, 7.2), (3.6, 13.2))  # port pit's forward-outer corner
WALKWAY_X = (32.4, 39.6)  # black walkway between the edge inlays
RIM_X = (31.8, 40.2)  # pit edges on the walkway side

# Aft bulkhead (cut at 1.1 m) and the rooms behind it.
BULKHEAD_Z = (31.2, 33.6)
ROOMS_Z = (33.6, 43.2)
AFT_WALL_Z = (43.2, 44.0)
BRIEFING_X = (3.6, 28.2)
LOBBY_X = (30.6, 41.4)
READY_X = (43.8, 68.4)
MAIN_DOOR_X = (34.2, 37.8)
LIFT_P_X = (31.2, 33.6)
LIFT_S_X = (38.4, 40.8)
BRIEF_DOOR_X = (25.2, 27.6)
READY_DOOR_X = (44.4, 46.8)


def P(x: float, z: float, h: float = 0.0) -> tuple[float, float, float]:  # noqa: N802
    """Plan point (x, z) at height h -> Blender (X, Y, Z)."""
    return (x, -z, h)


def XY(x: float, z: float) -> tuple[float, float]:  # noqa: N802
    return (x, -z)


def mirror_x(x: float) -> float:
    """Starboard counterpart of a port x coordinate."""
    return 2 * AXIS_X - x


def poly(points: Iterable[Sequence[float]]) -> list[tuple[float, float]]:
    """Plan polygon -> Blender XY polygon, counter-clockwise seen from above."""
    pts = [XY(p[0], p[1]) for p in points]
    area = 0.5 * sum(
        x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1], strict=True)
    )
    return pts if area > 0 else list(reversed(pts))


def rect(x0: float, z0: float, x1: float, z1: float) -> list[tuple[float, float]]:
    return poly([(x0, z0), (x1, z0), (x1, z1), (x0, z1)])


def pit_outline(side: int) -> list[tuple[float, float]]:
    """Plan outline of a pit floor; side -1 = port, +1 = starboard."""
    (cx0, cz0), (cx1, cz1) = PIT_CHAMFER
    port = [
        (cx1, cz1),
        (cx0, cz0),
        (RIM_X[0], FORWARD_EDGE_Z),
        (RIM_X[0], AFT_EDGE_Z),
        (SIDE_WALL_X[0], AFT_EDGE_Z),
    ]
    if side < 0:
        return port
    return [(mirror_x(x), z) for x, z in reversed(port)]


def hall_outline() -> list[tuple[float, float]]:
    """Plan outline of the whole bridge hall at deck level (incl. the pits)."""
    x0, x1 = SIDE_WALL_X
    c0, c1 = VP_CENTRE_X
    return [
        (x0, VP_FACE_Z + CHAMFER),
        (c0, VP_FACE_Z),
        (c1, VP_FACE_Z),
        (x1, VP_FACE_Z + CHAMFER),
        (x1, BULKHEAD_Z[0]),
        (x0, BULKHEAD_Z[0]),
    ]


def upper_deck_outline() -> list[tuple[float, float]]:
    """The I-shaped deck around the pits: forward gallery, walkway, aft gallery."""
    x0, x1 = SIDE_WALL_X
    c0, c1 = VP_CENTRE_X
    (pc0x, pc0z), (pc1x, pc1z) = PIT_CHAMFER
    r0, r1 = RIM_X
    return [
        (x0, VP_FACE_Z + CHAMFER),
        (c0, VP_FACE_Z),
        (c1, VP_FACE_Z),
        (x1, VP_FACE_Z + CHAMFER),
        (x1, pc1z),
        (mirror_x(pc0x), pc0z),
        (r1, FORWARD_EDGE_Z),
        (r1, AFT_EDGE_Z),
        (x1, AFT_EDGE_Z),
        (x1, BULKHEAD_Z[0]),
        (x0, BULKHEAD_Z[0]),
        (x0, AFT_EDGE_Z),
        (r0, AFT_EDGE_Z),
        (r0, FORWARD_EDGE_Z),
        (pc0x, pc0z),
        (x0, pc1z),
    ]
