"""Runtime contract of the engineering deck: sockets, stations, rooms, occluders.

Socket props read by the engine: ``group`` (what a seat/stand is for, or the
waypoint route), ``link`` (a seat's screen and back), ``order`` (route order).
"""

from __future__ import annotations

import math

import bpy
import eng_arch
import eng_common as c
import eng_dressing
import eng_reactor
import eng_rooms
from eng_common import b, ucx3, ucx_cylinder
from lib import scene
from mathutils import Vector


def _rect(x0: float, x1: float, z0: float, z1: float) -> list[tuple[float, float]]:
    """three.js rectangle -> counter-clockwise Blender XY polygon."""
    return [(x0, -z1), (x1, -z1), (x1, -z0), (x0, -z0)]


def terminals() -> None:
    if c.KIT_COMMAND:
        return  # the terminal modules carry their own seat/screen/stand sockets
    n = 0
    t = math.radians(eng_rooms.TERMINAL_TILT)
    normal = Vector((0.0, -math.cos(t), math.sin(t)))
    for z_line in c.TERM_ROWS_Z:
        for x in c.TERM_COLS_X:
            n += 1
            sid = f"term_{n}"
            scene.add_socket(
                "seat", sid, b(x, z_line + eng_rooms.SEAT_OFFSET), 180.0,
                group="terminal", link=sid, order=n, seat_height=eng_rooms.SEAT_HEIGHT,
            )  # fmt: skip
            centre = eng_rooms.terminal_screen_centre(x, z_line) + normal * 0.012
            w, h = eng_rooms.TERMINAL_SCREEN
            scene.add_screen(
                sid, centre, w - 0.04, h - 0.04, yaw_deg=0.0, tilt_deg=eng_rooms.TERMINAL_TILT,
                group="terminal", link=sid, order=n,
            )  # fmt: skip


def stations() -> None:
    # Master systems console: the commander stands at its front edge.
    if not c.KIT_COMMAND:
        scene.add_socket(
            "station", "master", b(c.MASTER_X, c.MASTER_Z + 0.75), 180.0,
            station_kind="coding_launcher",
        )  # fmt: skip
        t = math.radians(30.0)
        normal = Vector((0.0, -math.cos(t), math.sin(t)))
        centre = Vector(b(c.MASTER_X, c.MASTER_Z - 1.05, 1.18)) + normal * 0.012
        scene.add_screen("master_desk", centre, 1.52, 0.56, tilt_deg=30.0, station="master")
    scene.add_screen(
        "master_wall", b(c.MASTER_X, c.FAR_WALL_Z + 0.165, 3.4), 9.4, 2.4,
        station="master", group="wall",
    )  # fmt: skip
    # Turbolift: the kit door carries SOCKET_lift_main and a spawn point in
    # front of it, which becomes the commander's spawn.
    z1 = c.CONTROL_SOUTH_Z[1]
    if c.KIT_ARCH:
        lift = bpy.data.objects["SOCKET_lift_main"]
        lift["station"] = "lift"
        lift["decks"] = "all"
        spawn = bpy.data.objects["SOCKET_spawn_main"]
        spawn.name = "SOCKET_spawn_commander"
    else:
        scene.add_socket("lift", "main", b(c.LIFT_X, z1 + 0.8), 0.0, decks="all", station="lift")
        scene.add_socket("spawn", "commander", b(c.LIFT_X, 47.6), 0.0)
    scene.add_socket("station", "lift", b(c.LIFT_X, z1 + 1.9), 180.0, station_kind="lift")
    if not c.KIT_REACTOR:
        scene.add_socket("spawn", "drone", b(26.4, 48.6, 0.08), 0.0)


def waypoints() -> None:
    """Routes (the engine groups waypoints by id prefix: `patrol_*` routes get a
    trooper, others a utility drone) and idle stands for off-duty technicians
    (`workshop_<n>`)."""
    routes = {
        "patrol_hall": [
            (37.2, 7.2), (54.0, 5.4), (70.8, 7.2), (76.8, 22.0),
            (70.8, 35.4), (54.0, 36.8), (37.8, 35.4), (36.0, 22.0),
        ],
        "patrol_gallery": [(36.6, 45.2), (48.0, 45.2), (60.0, 45.2), (72.0, 45.2),
                           (80.4, 45.2)],
        "service": [(26.4, 47.0), (33.0, 46.4), (44.4, 45.6), (58.8, 45.6), (44.4, 45.6),
                    (33.0, 46.4)],
    }  # fmt: skip
    for route, points in routes.items():
        for i, (x, z) in enumerate(points):
            nxt = points[(i + 1) % len(points)]
            yaw = math.degrees(math.atan2(nxt[0] - x, nxt[1] - z))
            scene.add_socket("waypoint", f"{route}_{i + 1}", b(x, z), yaw)
    ring_r = sum(c.RING_R) / 2
    for i, a in enumerate((45.0, 135.0, 225.0, 315.0) if not c.KIT_REACTOR else ()):
        rad = math.radians(a)
        x = c.SHAFT_C[0] + ring_r * math.cos(rad)
        z = c.SHAFT_C[1] - ring_r * math.sin(rad)
        yaw = math.degrees(math.atan2(c.SHAFT_C[0] - x, c.SHAFT_C[1] - z))
        scene.add_socket("stand", f"ring_{i + 1}", b(x, z), yaw)
    stands = [
        (31.2, 9.6, 90.0), (31.2, 26.4, 90.0), (31.2, 36.0, 90.0),  # at the glass
        (15.8, 11.4, 180.0), (18.2, 11.4, 180.0),  # plot table
        (20.4, 42.9, 180.0),  # bay bench
        (75.2, 17.0, 90.0), (75.2, 27.0, 90.0),  # power units
        (36.4, 14.0, 90.0), (36.4, 30.0, 90.0),  # hall, looking at the core
    ]  # fmt: skip
    for i, (x, z, yaw) in enumerate(stands):
        scene.add_socket("stand", f"workshop_{i + 1}", b(x, z), yaw)
    if c.KIT_REACTOR:
        # The kit's catwalk start/end points become one trooper patrol over the
        # shaft: N catwalk in, round the ring, E out, S in, W out.
        order = [(1, "start"), (1, "end"), (2, "end"), (2, "start"),
                 (3, "start"), (3, "end"), (4, "end"), (4, "start")]  # fmt: skip
        for i, (n, end) in enumerate(order):
            obj = bpy.data.objects.get(f"SOCKET_waypoint_reactor_catwalk_{n}__{end}")
            if obj is not None:
                obj.name = f"SOCKET_waypoint_patrol_core_{i + 1}"


def lights_and_doors() -> None:
    cx, cz = c.SHAFT_C
    scene.add_socket(
        "light", "core", b(cx, cz, 2.0), 0.0, colour="#ffb47a", intensity=1.0, radius=16.0,
        pulse_hz=0.12,
    )  # fmt: skip
    scene.add_socket(
        "light", "lift_call", b(c.LIFT_X + 1.0, c.CONTROL_SOUTH_Z[1] + 0.1, 1.35), 0.0,
        colour="#ff9a2a", blink_hz=0.5,
    )  # fmt: skip
    doors = {
        "control_lobby": (c.DOOR_CONTROL_LOBBY, sum(c.CONTROL_SOUTH_Z) / 2, 0.0),
        "control_bay": (c.DOOR_CONTROL_BAY, sum(c.CONTROL_SOUTH_Z) / 2, 0.0),
        "partition": (sum(c.PARTITION_X) / 2, c.DOOR_PARTITION, 90.0),
        "lobby_bay": (sum(c.LOBBY_BAY_X) / 2, c.DOOR_LOBBY_BAY, 90.0),
        "bay_gallery": (sum(c.BAY_GALLERY_X) / 2, c.DOOR_BAY_GALLERY, 90.0),
    }
    for i, x in enumerate(c.GALLERY_OPENINGS):
        doors[f"gallery_{i + 1}"] = (x, sum(c.GALLERY_NORTH_Z) / 2, 0.0)
    if c.KIT_ARCH:  # the blast doors carry their own door sockets
        for name in ("control_lobby", "control_bay", "gallery_1", "gallery_2", "gallery_3"):
            doors.pop(name)
    for name, (x, z, yaw) in doors.items():
        scene.add_socket("door", name, b(x, z), yaw, width=c.DOOR_W)


def rooms() -> None:
    scene.add_room("control", "Engineering Control", _rect(*c.CONTROL), main=True, kind="control")
    scene.add_room("reactor", "Reactor Shaft", _rect(*c.HALL), kind="reactor")
    scene.add_room("gallery", "Power Conduit Gallery", _rect(*c.GALLERY), kind="gallery")
    scene.add_room("lobby", "Turbolift Lobby", _rect(*c.LOBBY), kind="lobby")
    scene.add_room("bay", "Maintenance Bay", _rect(*c.BAY), kind="bay")


def occluders() -> None:
    for name, box in eng_arch.OCCLUDER_BOXES:
        ucx3(name, *box)
    n = 0
    for z_line in c.TERM_ROWS_Z if not c.KIT_COMMAND else ():
        for x in c.TERM_COLS_X:
            n += 1
            ucx3(f"term_{n}_desk", x - 1.0, x + 1.0, z_line - 0.42, z_line + 0.42, 0.0, 0.78)
            ucx3(f"term_{n}_screen", x - 0.72, x + 0.72, z_line - 0.5, z_line + 0.02, 0.78, 1.45)
            zs = z_line + eng_rooms.SEAT_OFFSET
            ucx3(f"term_{n}_chair", x - 0.24, x + 0.24, zs + 0.25, zs + 0.33, 0.5, 1.02)
    if not c.KIT_COMMAND:
        ucx3("master", c.MASTER_X - 4.85, c.MASTER_X + 4.85, c.FAR_WALL_Z, c.MASTER_Z + 0.06,
             0.0, 1.9)  # fmt: skip
    if not c.KIT_ARCH:
        lx0, lx1 = c.LIFT_CORE_X
        ucx3("lift_core", lx0, lx1, c.LIFT_CORE_Z[0], c.CONTROL_SOUTH_Z[1], 0.0, c.CONTROL_H)
    cx, cz = c.SHAFT_C
    if not c.KIT_REACTOR:
        ucx_cylinder("core_cap", cx, cz, c.CORE_R + 0.6, -0.8, 2.5)
    stacks = eng_dressing.STACK_X if c.KIT_REACTOR else (37.8, 45.0, 63.0, 70.2, 77.4)
    for i, x in enumerate(stacks):
        ucx_cylinder(f"stack_{i}", x, c.FAR_WALL_Z + 1.35, 1.36, 0.0, c.HALL_H - 0.4)
    if c.KIT_REACTOR:
        return  # gallery and bay props carry their own occluders
    for i, (x, z) in enumerate(eng_reactor.POWER_UNITS if not c.KIT_REACTOR else ()):
        ucx_cylinder(f"power_unit_{i}", x, z, 1.55, 0.0, 3.15, sides=8)
    for i, x in enumerate((44.4, 63.6, 79.2)):
        ucx_cylinder(f"riser_{i}", x, 39.2, 0.32, 0.0, 3.0, sides=10)
    for i, x0 in enumerate((c.LOBBY_BAY_X[1], c.BAY_GALLERY_X[0] - 0.7)):
        ucx3(f"bay_racks_{i}", x0, x0 + 0.7, 42.1, 51.5, 0.0, 2.2)


def build() -> None:
    terminals()
    stations()
    waypoints()
    lights_and_doors()
    rooms()
    occluders()
