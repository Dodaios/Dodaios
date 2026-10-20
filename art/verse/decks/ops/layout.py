"""Operations deck layout (pure Python, no bpy): the numbers every module shares.

Units are metres in three.js axes, as in LEVELS.md: x to screen right, z toward
the camera, z = 0 at the far hull. Rects are (x0, x1, z0, z1) of the walkable
floor inside the walls.
"""

from __future__ import annotations

from dataclasses import dataclass

W, D = 96.0, 60.0
MODULE = 1.2

# Heights.
HULL_H = 5.4  # visible top of the far (hero) hull wall
ROOM_H = 4.6  # room ceilings (camera-invisible)
CORR_H = 4.2  # corridor ceiling

# Far hull wall: room face at z = 2.
HERO_Z = 2.0

# Main corridor: outer wall lines and floor.
CORR_N = 26.4  # room-side face of the north corridor wall
CORR_S = 33.6  # room-side face of the south corridor wall
CORR_FLOOR = (27.6, 32.4)  # floor edges (feet of the sloped lower walls)
CORR_X = (4.2, 91.8)  # floor between the closed end portals
CORR_Z_MID = 30.0
SLOPE_RUN = 0.6  # lower wall leans back 0.6 m over 1.2 m
SLOPE_TOP = 1.2
CHAMFER_LOW = 3.3
BLAST_FRAMES = (16.0, 38.0, 60.0, 82.0)  # frame centres (x)
END_PORTALS = (3.6, 92.4)
FRAME_DEPTH = 1.2

# Near hull wall (cut at 1.1 m): room face at z = 58.
NEAR_Z = 58.0

# Rooms north of the corridor (z 2 .. 26.4) and south (z 33.6 .. 58).
NORTH = (HERO_Z, CORR_N)
SOUTH = (CORR_S, NEAR_Z)

WALL_T = 0.3  # interior wall skin


@dataclass(frozen=True)
class RoomDef:
    id: str
    name: str
    rect: tuple[float, float, float, float]  # x0, x1, z0, z1 (inside faces)


ROOMS = {
    "mess": RoomDef("mess", "Mess Hall", (3.0, 31.0, *NORTH)),
    "records": RoomDef("records", "Records Hall", (33.0, 51.0, *NORTH)),
    "simulator": RoomDef("simulator", "Simulator Room", (53.0, 73.0, *NORTH)),
    "quartermaster": RoomDef("quartermaster", "Quartermaster", (75.0, 93.0, *NORTH)),
    "quarters": RoomDef("quarters", "Crew Quarters", (3.0, 37.0, *SOUTH)),
    "team_a": RoomDef("team_a", "Ready Room A", (39.0, 53.0, *SOUTH)),
    "team_b": RoomDef("team_b", "Ready Room B", (55.0, 69.0, *SOUTH)),
    "lobby": RoomDef("lobby", "Turbolift Lobby", (71.0, 81.0, CORR_S, 46.0)),
    "storage": RoomDef("storage", "Stores", (83.0, 93.0, CORR_S, 46.0)),
    "medbay": RoomDef("medbay", "Medical Bay", (71.0, 93.0, 47.0, NEAR_Z)),
}

# Service chases between rooms (x0, x1), north and south of the corridor.
CHASES_NORTH = ((31.0, 33.0), (51.0, 53.0), (73.0, 75.0))
CHASES_SOUTH = ((37.0, 39.0), (53.0, 55.0), (69.0, 71.0))
LOBBY_STORE_CHASE = (81.0, 83.0)  # z CORR_S .. 46
MED_WALL = (46.0, 47.0)  # E-W wall between the lobby/stores and the med bay

# Doors: (x centre, width). North doors pierce the north corridor wall, south
# doors the south corridor wall.
DOORS_NORTH = {
    "mess_w": (8.4, 2.4),
    "mess_e": (25.8, 2.4),
    "records": (42.0, 3.6),
    "simulator": (66.0, 2.4),
    "quartermaster": (87.0, 2.4),
}
DOORS_SOUTH = {
    "quarters_w": (10.8, 2.4),
    "quarters_e": (30.0, 2.4),
    "team_a": (46.0, 2.4),
    "team_b": (64.2, 2.4),
    "lobby_w": (72.2, 2.4),
    "lobby_e": (79.8, 2.4),
    "storage": (88.2, 2.4),
}
# Doors in the med wall (z 46..47): from the lobby and from the stores.
DOORS_MED = {"medbay": (76.0, 2.4), "medbay_stores": (88.2, 1.8)}

# Turbolift core in the lobby (x0, x1, z0, z1), doors on its +z face.
LIFT_CORE = (73.4, 78.6, CORR_S, 37.2)
LIFT_DOORS = (74.8, 77.2)  # door centres
LIFT_DOOR_W = 1.6


def door_spans(doors: dict[str, tuple[float, float]]) -> list[tuple[float, float]]:
    return sorted((x - w / 2, x + w / 2) for x, w in doors.values())


def solid_spans(x0: float, x1: float, holes: list[tuple[float, float]]):
    """Split x0..x1 around the hole spans."""
    out, cur = [], x0
    for a, b in sorted(holes):
        if b <= x0 or a >= x1:
            continue
        if a > cur:
            out.append((cur, a))
        cur = max(cur, b)
    if cur < x1:
        out.append((cur, x1))
    return out
