"""The upper parts of the bridge's cut-away walls (BRIEF section 5).

The plate camera sees the aft bulkhead and the aft hull wall cut at 1.1 m.
Above the cut they still exist as ceiling ghosts: invisible to the plate
camera and to shadow rays, they close the rooms for floor reflections, the
environment map, the probes and the realtime (eye-level) export, which turns
them into normal walls (docs/verse/realtime.md).

Bulkhead: a solid wall from the cut up to the aft rooms' ceiling with door
heads over the three passages and the lift shafts closed up to the same
height; above the rooms the hall-side skin runs on up to the hall ceiling.
Aft wall: closed up to the rooms' ceiling. Faces get the same light-grey
panelling as the walls below the cut.
"""

from __future__ import annotations

from lib import kit, scene

from . import layout as L

DOOR_H = 2.7  # passage and lift door head
SKIN = 0.3  # hall-side skin of the double bulkhead
PANEL = "M_Wall_PaintedLight"
BODY = "M_Wall_PaintedMid"
BAND = "M_Struct_Gunmetal"
BAND_Z = (3.0, 3.18)  # gunmetal band where the room ceilings meet the hall skin


def _panels(
    mb: kit.MeshBuilder, x0: float, x1: float, y_face: float, z0: float, z1: float, sign: int
) -> None:
    """Inset light-grey panels on the 1.2 m module standing proud of a face.

    ``sign`` is the face's outward direction along Blender Y (+1 toward
    Blender +Y, i.e. three -z).
    """
    n = max(1, round((x1 - x0) / L.M))
    step = (x1 - x0) / n
    y_a, y_b = sorted((y_face, y_face + sign * 0.02))
    for i in range(n):
        a, b = x0 + i * step, x0 + (i + 1) * step
        mb.box((a + 0.006, y_a, z0 + 0.02), (b - 0.006, y_b, z1 - 0.02), PANEL)


def _openings() -> list[tuple[float, float, str]]:
    return [
        (*L.BRIEF_DOOR_X, "door"),
        (*L.LIFT_P_X, "lift"),
        (*L.MAIN_DOOR_X, "door"),
        (*L.LIFT_S_X, "lift"),
        (*L.READY_DOOR_X, "door"),
    ]


def _solid_spans(x_lo: float, x_hi: float) -> list[tuple[float, float]]:
    spans, x = [], x_lo
    for a, b, _ in _openings():
        spans.append((x, a))
        x = b
    spans.append((x, x_hi))
    return spans


def _bulkhead() -> None:
    zf, zn = L.BULKHEAD_Z
    y_hall, y_room = -zf, -zn  # Blender Y of the hall face and the room face
    x_lo, x_hi = L.SIDE_WALL_X[0] - L.SIDE_WALL_T, L.SIDE_WALL_X[1] + L.SIDE_WALL_T
    body = kit.MeshBuilder()
    faces = kit.MeshBuilder()
    for a, b in _solid_spans(x_lo, x_hi):
        body.box((a, y_room, L.CUT_H), (b, y_hall, L.ROOM_CEILING), BODY)
        _panels(faces, a, b, y_room, L.CUT_H, L.ROOM_CEILING, -1)
        _panels(faces, a, b, y_hall, L.CUT_H, BAND_Z[0], 1)
    for a, b, kind in _openings():
        # Door head across the whole thickness, with a gunmetal soffit.
        body.box((a, y_room, DOOR_H), (b, y_hall, L.ROOM_CEILING), BODY)
        faces.box((a, y_room - 0.01, DOOR_H - 0.03), (b, y_hall + 0.01, DOOR_H), BAND)
        _panels(faces, a, b, y_room, DOOR_H, L.ROOM_CEILING, -1)
        _panels(faces, a, b, y_hall, DOOR_H, BAND_Z[0], 1)
        if kind == "door":
            # Jambs carry on up to the door head.
            for x, side in ((a, 1), (b, -1)):
                j0, j1 = sorted((x, x + side * 0.22))
                faces.box((j0, y_room + 0.05, L.CUT_H), (j1, y_hall - 0.05, DOOR_H), BAND)
        else:
            # Lift shaft walls up to the car ceiling, a lit car ceiling below the head.
            t = 0.18
            faces.box((a, y_room, L.CUT_H), (a + t, y_hall, DOOR_H), BODY)
            faces.box((b - t, y_room, L.CUT_H), (b, y_hall, DOOR_H), BODY)
            faces.box((a, y_hall - t, L.CUT_H), (b, y_hall, DOOR_H), BODY)
            for x, side in ((a, 1), (b, -1)):
                f0, f1 = sorted((x - side * 0.06, x + side * 0.32))
                faces.box((f0, y_room - 0.08, L.CUT_H), (f1, y_room + 0.12, DOOR_H + 0.02), BAND)
    # Above the rooms the hall-side skin runs on to the hall ceiling.
    body.box((x_lo, y_hall - SKIN, L.ROOM_CEILING), (x_hi, y_hall, L.HALL_CEILING), BODY)
    faces.box((x_lo, y_hall, BAND_Z[0]), (x_hi, y_hall + 0.04, BAND_Z[1]), BAND)
    _panels(faces, x_lo, x_hi, y_hall, BAND_Z[1], L.HALL_CEILING - 0.3, 1)
    faces.box(
        (x_lo, y_hall, L.HALL_CEILING - 0.3), (x_hi, y_hall + 0.03, L.HALL_CEILING), "M_Recess_Dark"
    )
    body.build("SM_bulkhead_upper", bevel_width=0.004)
    faces.build("SM_bulkhead_upper_faces", bevel_width=0.003)


def _aft_wall() -> None:
    zf, zn = L.AFT_WALL_Z
    x_lo, x_hi = L.SIDE_WALL_X[0] - L.SIDE_WALL_T, L.SIDE_WALL_X[1] + L.SIDE_WALL_T
    body = kit.MeshBuilder()
    body.box((x_lo, -zn, L.CUT_H), (x_hi, -zf, L.ROOM_CEILING), BODY)
    body.build("SM_aftwall_upper", bevel_width=0.004)
    faces = kit.MeshBuilder()
    for x0, x1 in (L.BRIEFING_X, L.LOBBY_X, L.READY_X):
        _panels(faces, x0, x1, -zf, L.CUT_H, L.ROOM_CEILING - 0.1, 1)
    faces.build("SM_aftwall_upper_faces", bevel_width=0.003)


def build() -> None:
    with kit.into(scene.collection("Ceiling")), kit.ghost(L.CUT_H):
        _bulkhead()
        _aft_wall()
