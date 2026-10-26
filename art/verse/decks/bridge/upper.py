"""The upper parts of the bridge's cut-away walls (BRIEF section 5).

The plate camera sees the aft bulkhead and the aft hull wall cut at 1.1 m.
Above the cut they still exist as ceiling ghosts: invisible to the plate
camera and to shadow rays, they close the rooms for floor reflections, the
environment map, the probes and the realtime (eye-level) export, which turns
them into normal walls (docs/verse/realtime.md).

Bulkhead: a solid wall from the cut up to the aft rooms' ceiling with door
heads over the three passages and the lift shafts closed up to the same
height; above the rooms the hall-side skin runs on up to the hall ceiling.
Aft wall: closed up to the rooms' ceiling. The faces of both walls are
dressed by ``cladding.py`` (hall face: ribs, panels, conduits and light
columns; room faces: the light-grey room panelling).
"""

from __future__ import annotations

from lib import kit, scene

from . import layout as L

DOOR_H = 2.7  # passage and lift door head
SKIN = 0.3  # hall-side skin of the double bulkhead
BODY = "M_Wall_PaintedMid"
BAND = "M_Struct_Gunmetal"


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
    for a, b, kind in _openings():
        # Door head across the whole thickness, with a gunmetal soffit.
        body.box((a, y_room, DOOR_H), (b, y_hall, L.ROOM_CEILING), BODY)
        faces.box((a, y_room - 0.01, DOOR_H - 0.03), (b, y_hall + 0.01, DOOR_H), BAND)
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
    body.build("SM_bulkhead_upper", bevel_width=0.004)
    faces.build("SM_bulkhead_upper_faces", bevel_width=0.003)


def _aft_wall() -> None:
    zf, zn = L.AFT_WALL_Z
    x_lo, x_hi = L.SIDE_WALL_X[0] - L.SIDE_WALL_T, L.SIDE_WALL_X[1] + L.SIDE_WALL_T
    body = kit.MeshBuilder()
    body.box((x_lo, -zn, L.CUT_H), (x_hi, -zf, L.ROOM_CEILING), BODY)
    body.build("SM_aftwall_upper", bevel_width=0.004)


def build() -> None:
    with kit.into(scene.collection("Ceiling")), kit.ghost(L.CUT_H):
        _bulkhead()
        _aft_wall()
