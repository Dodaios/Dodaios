"""Room dressing, lighting, sockets, stations and room polygons of the
Operations deck. One function per room; LEVELS.md deck 2 is the contract.

Furniture comes from the shared command-prop kit (``kit.props.command``)
where a piece exists; ``props.py`` builds the rest. Kit sockets are renamed to
the engine's grouping (the id minus its trailing number is the group):
``seat_mess_<n>``, ``bunk_<n>``, ``seat_sim_<n>``, ``seat_team_a_<n>``,
``stand_viewport_<n>``, ``waypoint_corridor_<n>``, ``waypoint_patrol_a_<n>``.
"""

from __future__ import annotations

from collections.abc import Callable

import bpy
import kit.props.command  # noqa: F401 - registers the command props
import kit.props.industrial  # noqa: F401 - registers the industrial props
from decks.ops import arch, props
from decks.ops import layout as L
from decks.ops.geo import (
    Mesh,
    P,
    point_light,
    room,
    screen,
    sock,
    spot_light,
    tag,
    ucx,
)
from lib import kit, naming, scene

Rename = Callable[[str, str], "str | None"]


class RoomMeshes:
    """The handful of merged meshes one room's bespoke furniture goes into."""

    def __init__(self, rid: str) -> None:
        self.rid = rid
        self.hard, self.soft, self.lights, self.scr, self.glass = (Mesh() for _ in range(5))
        self.flat = Mesh()  # flush floor inlays: never nav obstacles
        self.walk = Mesh()  # raised floors people step onto

    def build(self) -> None:
        r = self.rid
        tag(self.hard.build(f"SM_Ops_Props_{r}", "Props", bevel=0.006), nav="block", room=r)
        soft = self.soft.build(f"SM_Ops_Soft_{r}", "Props", bevel=0.02, segments=3)
        tag(soft, nav="block", room=r)
        lamps = self.lights.build(f"SM_Ops_Lamps_{r}", "Props", bevel=0.0, keep_normals=True)
        tag(lamps, nav="none", room=r)
        tag(self.scr.build(f"SM_Ops_Screens_{r}", "Props", bevel=0.0), nav="none", room=r)
        tag(self.flat.build(f"SM_Ops_Inlays_{r}", "Props", bevel=0.002), nav="none", room=r)
        tag(self.walk.build(f"SM_Ops_Dais_{r}", "Props", bevel=0.008), nav="walk", room=r)
        g = self.glass.build(f"SM_Ops_Glass_{r}", "Props", bevel=0.0)
        if g is not None:
            g.visible_shadow = False
            tag(g, nav="none", room=r)


def place(
    piece: str,
    x: float,
    z: float,
    rot: float,
    pid: str,
    room_id: str,
    rename: Rename | None = None,
    **props,
) -> bpy.types.Object:
    """Place a kit piece at deck coordinates and rename the sockets it emits:
    ``rename(kind, local_id)`` returns the new socket id, or None to drop it."""
    with kit.into(scene.collection("Props")):
        root = kit.place(piece, P(x, z, 0.0), rot, room_id, id=pid, **props)
    if rename is None:
        return root
    for obj in list(scene.collection("Sockets").objects):
        if obj.get("owner") != pid:
            continue
        parsed = naming.parse_socket(obj.name)
        local = parsed.id[len(pid) + 2 :] if parsed.id != pid else ""
        new = rename(parsed.kind, local)
        if new is None:
            bpy.data.objects.remove(obj, do_unlink=True)
        elif new != parsed.id:
            obj.name = naming.socket_name(parsed.kind, new)
    return root


def pool(
    name: str, x: float, z: float, watts: float, cone: float = 60.0, kelvin: float = 5600.0
) -> None:
    """A downlight pool from a (camera-invisible) ceiling fixture."""
    spot_light(
        f"LT_Pool_{name}",
        x,
        z,
        L.ROOM_H - 0.1,
        watts,
        kelvin=kelvin,
        angle_deg=cone,
        blend=0.85,
        radius=0.35,
    )


def wall_wash(name: str, x: float, width: float, watts: float) -> None:
    """Wall-washer for a hero far wall: a long area light near the ceiling,
    tilted toward the wall (lights the panelling, the props and the floor in
    front of them)."""
    scene.add_area_light(
        f"LT_Wash_{name}",
        P(x, L.HERO_Z + 1.8, L.ROOM_H - 0.2),
        (width, 0.3),
        watts,
        5600.0,
        rotation_deg=(38.0, 0.0, 0.0),
        spread_deg=120.0,
    ).visible_glossy = False


def build(bays: dict) -> None:
    mess(bays["mess"])
    records()
    simulator()
    quartermaster()
    quarters()
    team_room("team_a", 46.0)
    team_room("team_b", 62.0)
    lobby()
    storage()
    medbay()
    corridor()
    rooms()
    occluders()


# ---------------------------------------------------------------- mess

MESS_RUNS = (4.6, 18.9)  # west edge of each run of five tables
MESS_ROWS = (8.4, 12.6, 16.8, 21.0)


def mess(bay_spans) -> None:
    x0, x1, z0, z1 = L.ROOMS["mess"].rect
    rm = RoomMeshes("mess")
    hatch = [(a, b) for a, b, k in bay_spans if k == "hatch"]
    slit = [(a, b) for a, b, k in bay_spans if k == "slit"]
    hc = (hatch[0][0] + hatch[-1][1]) / 2
    # Serving line: two counters in front of the galley hatch.
    for i, dx in enumerate((-2.43, 2.43)):
        place(
            "SM_Counter_Serving",
            hc + dx,
            L.HERO_Z + 1.93,
            0.0,
            f"mess_counter_{i + 1}",
            "mess",
            lambda k, loc, i=i: None if k == "station" else f"mess_server_{i + 1}",
        )
    sock(
        "station",
        "mess_call",
        hc,
        L.HERO_Z + 3.0,
        0.0,
        180.0,
        station_kind="mess_call",
        room="mess",
    )
    for i, x in enumerate((hc - 3.6, hc - 1.2, hc + 1.2, hc + 3.6)):
        sock("stand", f"mess_{i + 1}", x, L.HERO_Z + 3.2, 0.0, 180.0, room="mess")
    props.tray_stand(rm.hard, hatch[0][0] - 0.9, hatch[0][0] - 0.1, L.HERO_Z + 0.5)
    for i, x in enumerate((3.68, 4.72)):
        place(
            "SM_Dispenser",
            x,
            L.HERO_Z,
            0.0,
            f"mess_dispenser_{i + 1}",
            "mess",
            lambda k, loc, i=i: f"dispenser_{i + 1}",
        )
    # Viewport ledge: idle crew stand here looking out.
    sx0, sx1 = slit[0][0] + 0.2, slit[-1][1] - 0.2
    props.lean_rail(rm.hard, sx0, sx1, L.HERO_Z + 0.75)
    for i in range(4):
        x = sx0 + (sx1 - sx0) * (i + 0.5) / 4
        sock("stand", f"viewport_{i + 1}", x, L.HERO_Z + 1.25, 0.0, 180.0, room="mess")
    # Refectory rows: four rows, each two runs of five tables end to end
    # (240 places), a 3.8 m centre aisle and a long warm light over each run.
    n = [0]

    def seat_name(kind: str, loc: str) -> str | None:
        if kind != "seat":
            return None
        n[0] += 1
        return f"mess_{n[0]}"

    strips = []
    for r, cz in enumerate(MESS_ROWS):
        for side, run_x0 in enumerate(MESS_RUNS):
            for k in range(5):
                tx = run_x0 + 1.05 + 2.1 * k
                place("SM_Table_Mess", tx, cz, 0.0, f"mess_table_{r}{side}{k}", "mess", seat_name)
                props.mess_place_settings(rm.hard, tx, cz, seed=101 + r * 17 + side * 7 + k * 3)
            # A ceiling panel over every table: the rows mirror in the black
            # deck as dashes down each aisle.
            for k in range(5):
                tx = run_x0 + 1.05 + 2.1 * k
                strips.append((tx - 0.45, tx + 0.45, cz - 0.15, cz + 0.15))
                if r == 0:
                    strips.append((tx - 0.45, tx + 0.45, 4.85, 5.15))
            # Two downlight pools per run: the tables glow, the aisles fall off.
            for k in (1, 3):
                pool(f"mess_run_{r}{side}{k}", run_x0 + 1.05 + 2.1 * k, cz, 200.0, 60.0, 6200.0)
    props.floor_code(rm.flat, "2-01", 17.0, 24.8)
    # Duty terminal in the far wall's last panel bay (sockets dropped).
    place("SM_Terminal_Wall", 29.84, L.HERO_Z + 0.02, 0.0, "mess_terminal", "mess", _drop)
    rm.build()
    arch.linear_lights("mess_tables", strips, mat="M_Ops_Light_MessCool")
    # The one warm note: a 3 200 K pool over the serving line.
    pool("mess_galley", hc, L.HERO_Z + 2.3, 280.0, 72.0, kelvin=3200.0)
    pool("mess_aisle_n", 17.0, 6.0, 160.0, 60.0)
    wall_wash("mess_counter", hc, 9.6, 520.0)
    wall_wash("mess_slit", (sx0 + sx1) / 2, sx1 - sx0, 200.0)


def _drop(kind: str, loc: str) -> None:
    """Socket rename that drops every socket of a dressing-only kit piece."""
    return None


# ---------------------------------------------------------------- records


def records() -> None:
    x0, x1, z0, z1 = L.ROOMS["records"].rect
    rm = RoomMeshes("records")
    cx = (x0 + x1) / 2
    place(
        "SM_Board_Rank",
        cx,
        L.HERO_Z,
        0.0,
        "service_record",
        "records",
        lambda k, loc: "service_record",
        station="service_record",
        station_kind="service_record",
    )
    place(
        "SM_Lectern", cx, 7.6, 180.0, "records_lectern", "records", lambda k, loc: "records_lectern"
    )
    # Archive stacks along both side walls: dark cabinets, pip-lit ends.
    for xa in (x0 + 0.4, x1 - 1.3):
        z = 6.0
        while z + 2.4 <= z1 - 0.8:
            props.archive_rack(rm.hard, rm.lights, xa, xa + 0.9, z, z + 2.4)
            z += 3.0
    cases = ((38.1, 11.4), (45.9, 11.4), (38.1, 16.2), (45.9, 16.2), (38.1, 21.0), (45.9, 21.0))
    for i, (x, z) in enumerate(cases):
        place(
            "SM_Case_Display",
            x,
            z,
            0.0,
            f"records_case_{i + 1}",
            "records",
            lambda k, loc, i=i: f"records_{i + 1}",
        )
    # Ceremonial runner: steel inlays with a line of white pips to the board.
    for x in (cx - 1.8, cx + 1.8):
        rm.flat.box(x - 0.06, x + 0.06, 8.6, z1 - 0.6, 0.0005, 0.003, "M_Trim_BrushedSteel")
        z = 9.0
        while z < z1 - 0.8:
            rm.lights.box(x - 0.02, x + 0.02, z - 0.04, z + 0.04, 0.001, 0.0045, "M_Ops_Light_Pip")
            z += 0.6
    rm.build()
    arch.linear_lights(
        "records",
        [(x0 + 2.8, x0 + 3.0, z0 + 3.0, z1 - 1.0), (x1 - 3.0, x1 - 2.8, z0 + 3.0, z1 - 1.0)],
    )
    wall_wash("records_board", cx, 9.0, 520.0)
    for i, z in enumerate((11.0, 17.0, 23.0)):
        pool(f"records_{i}", cx, z, 420.0, 55.0)


# ---------------------------------------------------------------- simulator


def simulator() -> None:
    """Training room: dark satin deck, mirrored ceiling bars, four pods and a raised platform."""
    x0, x1, z0, z1 = L.ROOMS["simulator"].rect
    rm = RoomMeshes("simulator")
    cx = (x0 + x1) / 2
    props.wall_display(rm.hard, rm.scr, cx - 4.4, cx + 4.4, L.HERO_Z, 1.45, 3.65)
    screen("sim_main", cx, L.HERO_Z + 0.13, 2.55, 8.7, 2.1, room="simulator", station="games")
    for i, px in enumerate((cx - 6.0, cx - 2.0, cx + 2.0, cx + 6.0)):
        place("SM_Pod_Simulator", px, 10.2, 0.0, f"sim_{i + 1}", "simulator", station="games")
        point_light(f"LT_SimPod_{i}", px, 10.2, 1.4, 6.0, kelvin=8000.0, radius=0.2)
    place("SM_Console_Instructor", cx, 14.2, 0.0, "sim_instructor", "simulator", station="games")
    sock("station", "games", cx + 1.6, 15.4, 0.0, 180.0, station_kind="games", room="simulator")
    props.arena(rm.walk, rm.hard, rm.lights, cx, 21.0, 12.0, 6.0)
    rm.build()
    bars = []
    for k in range(5):
        x = x0 + 2.0 + k * (x1 - x0 - 4.0) / 4
        for z in (5.4, 12.6, 19.8):
            bars.append((x - 0.6, x + 0.6, z - 0.075, z + 0.075))
    arch.linear_lights("simulator", bars, mat="M_Ops_Light_Corridor")
    pool("sim_pods", cx, 10.2, 320.0, 70.0, kelvin=6500.0)
    pool("sim_instructor", cx, 14.6, 120.0, 50.0)
    pool("sim_arena", cx, 21.0, 300.0, 65.0, kelvin=6500.0)
    wall_wash("sim_display", cx, 9.4, 260.0)


# ---------------------------------------------------------------- quartermaster


def quartermaster() -> None:
    x0, x1, z0, z1 = L.ROOMS["quartermaster"].rect
    rm = RoomMeshes("quartermaster")
    cx = (x0 + x1) / 2
    for i in range(5):
        place(
            "SM_Lockers_Uniform",
            cx + (i - 2) * 2.44,
            L.HERO_Z,
            0.0,
            f"qm_lockers_{i + 1}",
            "quartermaster",
            lambda k, loc: None,
        )
    place(
        "SM_Platform_Fitting",
        cx,
        11.4,
        0.0,
        "fitting",
        "quartermaster",
        lambda k, loc: "fitting",
        station="quartermaster",
    )
    place(
        "SM_Counter_Quartermaster",
        cx,
        18.0,
        0.0,
        "quartermaster",
        "quartermaster",
        lambda k, loc: "quartermaster_clerk" if loc == "clerk" else "quartermaster",
        station="quartermaster",
        station_kind="quartermaster",
    )
    for x in (cx - 3.0, cx + 3.0):
        props.service_counter(rm.hard, rm.scr, rm.lights, x - 1.3, x + 1.3, 18.0)
    # Issue stores behind the counter: rack rows running away from the camera.
    for k, rx in enumerate((76.0, 78.4, 88.6, 91.0)):
        props.shelf_rack(rm.hard, rx, rx + 1.0, 5.0, 14.6, seed=60 + k, levels=5)
    for i, x in enumerate((x0 + 1.0, x0 + 2.4, x1 - 2.4, x1 - 1.0)):
        props.crate_stack(rm.hard, x, 23.6, seed=5 + i * 4)
    rm.build()
    strips = [(cx - 6.0, cx + 6.0, L.HERO_Z + 1.5, L.HERO_Z + 1.65)]
    strips += [(cx - 4.0, cx + 4.0, 18.6, 18.75)]
    strips += [(x, x + 0.15, 5.4, 14.2) for x in (77.6, 90.2)]
    arch.linear_lights("quartermaster", strips)
    spot_light(
        "LT_QM_Dais", cx, 11.4, 4.4, 90.0, kelvin=6000.0, angle_deg=40.0, blend=0.5, radius=0.3
    )
    wall_wash("qm_lockers", cx, 12.4, 600.0)
    pool("qm_counter", cx, 19.2, 280.0, 60.0)


# ---------------------------------------------------------------- quarters

BERTH_GROUPS = (13.8, 25.6)
BERTH_PAIRS = (40.2, 48.6)


def quarters() -> None:
    x0, x1, z0, z1 = L.ROOMS["quarters"].rect
    rm = RoomMeshes("quarters")
    # Washroom block behind a low partition at x = 11.
    arch.ns_wall("Washroom", 11.0, 11.3, z0, 48.0)
    props.shower_stalls(rm.hard, x0, x0 + 1.4, z0 + 1.2, 6)
    props.sink_island(rm.hard, 6.6, 9.8, 44.4)
    props.bench(rm.hard, rm.soft, 6.0, 10.2, 50.4)
    # Personal lockers along the far wall, fronts to the camera.
    for i in range(10):
        place(
            "SM_Lockers_Uniform",
            12.2 + 1.21 + i * 2.44,
            z0,
            0.0,
            f"q_lockers_{i + 1}",
            "quarters",
            lambda k, loc: None,
        )
    # Berths: two back-to-back double rows in two groups (48 single berths).
    n = 0
    for gx0 in BERTH_GROUPS:
        for pair_z in BERTH_PAIRS:
            for heads_north, cz in ((False, pair_z - 1.32), (True, pair_z + 1.32)):
                for i in range(6):
                    bx = gx0 + 1.4 * (i + 0.5)
                    n += 1
                    place(
                        "SM_Bunk_Single",
                        bx,
                        cz,
                        0.0 if heads_north else 180.0,
                        f"berth_{n:02d}",
                        "quarters",
                        lambda k, loc, n=n: str(n) if k == "bunk" else None,
                        approach=[bx, cz + (1.5 if heads_north else -1.5)],
                    )
                    # Reading lamp in front of the head unit, over the pillow.
                    head = cz - 0.75 if heads_north else cz + 0.75
                    point_light(f"LT_Bunk_{n:02d}", bx, head, 1.35, 5.0, kelvin=5200.0, radius=0.1)
    # Locker banks closing the gap between the two berth groups at the aisle
    # end of each double row, doors to the aisle (sockets dropped).
    for pair_z in BERTH_PAIRS:
        pid = f"q_gap_{pair_z:.0f}"
        place("SM_Lockers_Uniform", 23.9, pair_z + 2.02, 0.0, pid, "quarters", _drop)
    # Off-duty corner: two tables by the near wall.
    for i, x in enumerate((20.0, 30.0)):
        place(
            "SM_Table_Mess",
            x,
            55.0,
            0.0,
            f"quarters_table_{i + 1}",
            "quarters",
            lambda k, loc, i=i: f"quarters_{i * 6 + int(loc)}" if k == "seat" else None,
        )
        props.mess_place_settings(rm.hard, x, 55.0, seed=71 + i * 13)
    props.floor_code(rm.flat, "2-11", 15.6, 35.9)
    # Washroom: grey satin tile laid flush over the deck plate.
    rm.flat.box(x0, 11.0, z0, 48.0, 0.0005, 0.003, "M_Ops_Floor_WashTile")
    rm.build()
    # Night strips over the berth rows, placed so each mirrors into the aisle
    # in front of it; a pool per aisle and group; a clinical pool in the washroom.
    rows = (33.95, 41.7, 51.9)
    strips = [
        (gx + 1.4 * (i + 0.5) - 0.4, gx + 1.4 * (i + 0.5) + 0.4, z, z + 0.15)
        for z in rows
        for gx in BERTH_GROUPS
        for i in range(6)
    ]
    strips += [(4.0, 10.4, 39.0, 39.15), (4.0, 10.4, 47.0, 47.15)]
    arch.linear_lights("quarters", strips, mat="M_Ops_Light_Night")
    for i, z in enumerate((35.9, 44.4, 54.2)):
        for j, x in enumerate((18.0, 29.8)):
            pool(f"quarters_{i}{j}", x, z, 240.0, 64.0, kelvin=5600.0)
    pool("quarters_wash", 7.2, 42.0, 110.0, 64.0, kelvin=6500.0)


# ---------------------------------------------------------------- ready rooms


def team_room(rid: str, cx: float) -> None:
    x0, x1, z0, z1 = L.ROOMS[rid].rect
    rm = RoomMeshes(rid)
    letter = rid[-1]
    tz = 42.0
    seats, holo = props.round_table(rm.hard, rm.soft, rm.lights, cx, tz)
    for i, (sx, sz, yaw) in enumerate(seats):
        sock(
            "seat",
            f"team_{letter}_{i + 1}",
            sx,
            sz,
            0.0,
            yaw,
            room=rid,
            station=rid,
            seat_height=0.5,
        )
    hx, hz, hh, hr = holo
    sock("holo", f"team_{letter}", hx, hz, hh, 0.0, room=rid, station=rid, radius=hr)
    sock("station", rid, cx, tz + 2.75, 0.0, 180.0, station_kind="team", room=rid)
    point_light(f"LT_{rid}_Projector", cx, tz, 0.95, 1.5, color=(0.25, 0.5, 1.0), radius=0.1)
    props.display_pylon(rm.hard, rm.scr, cx - 2.4, cx + 2.4, z0 + 1.0)
    screen(f"team_{letter}_wall", cx, z0 + 0.97, 1.85, 4.8, 1.7, room=rid, station=rid)
    for gz in (48.6, 52.2):
        props.gear_rack(rm.hard, x0 + 0.6, x0 + 3.6, gz)
        props.gear_rack(rm.hard, x1 - 3.6, x1 - 0.6, gz)
    spec = props.console(rm.hard, rm.scr, rm.lights, cx - 1.8, cx + 1.8, 53.4, tilt=55.0)
    sx, sz, sh, w, h, tilt = spec
    screen(f"team_{letter}_plan", sx, sz, sh, w, h, tilt_deg=tilt, room=rid)
    # Standing status consoles flanking the display wall (sockets dropped).
    for i, dx in enumerate((-4.4, 4.4)):
        place("SM_Console_Standing", cx + dx, z0 + 1.6, 0.0, f"{rid}_status_{i + 1}", rid, _drop)
    # The room's code stencilled by the door.
    props.floor_code(rm.flat, "2-1" + ("2" if letter == "a" else "3"), cx - 3.0, 35.5)
    rm.build()
    arch.ring_luminaire(rid, cx, tz, r=2.0, mat="M_Ops_Light_Ring", fins=False)
    # A light pool over the table, one at the display wall, one at the planning
    # desk, one over each kit rack.
    pool(f"{rid}_table", cx, tz, 380.0, 60.0)
    pool(f"{rid}_wall", cx, z0 + 2.4, 260.0, 65.0)
    pool(f"{rid}_plan", cx, 52.4, 240.0, 65.0)
    for side, x in (("w", x0 + 2.1), ("e", x1 - 2.1)):
        pool(f"{rid}_gear_{side}", x, 50.6, 170.0, 62.0)


# ---------------------------------------------------------------- lobby


def lobby() -> None:
    x0, x1, z0, z1 = L.ROOMS["lobby"].rect
    rm = RoomMeshes("lobby")
    cx = (L.LIFT_DOORS[0] + L.LIFT_DOORS[1]) / 2
    lz = L.LIFT_CORE[3]
    sock("lift", "main", cx, lz + 0.45, 0.0, 0.0, room="lobby", decks="all")
    sock("station", "lift", cx, lz + 0.7, 0.0, 180.0, station_kind="lift", room="lobby")
    sock("spawn", "commander", cx, lz + 2.2, 0.0, 0.0, room="lobby")
    for i, dx in enumerate(L.LIFT_DOORS):
        sock("door", f"lift_{i + 1}", dx, lz, 0.0, 0.0, room="lobby", width=L.LIFT_DOOR_W)
    props.deck_mark(rm.flat, cx, 42.0)
    z = lz + 0.6
    while z < 39.8:
        rm.lights.box(cx - 0.02, cx + 0.02, z - 0.04, z + 0.04, 0.001, 0.0045, "M_Ops_Light_Pip")
        z += 0.3
    for bz in (40.8, 43.2):
        for a, b in ((x0 + 0.1, x0 + 0.6), (x1 - 0.6, x1 - 0.1)):
            rm.hard.box(a, b, bz - 0.9, bz + 0.9, 0.0, 0.45, "M_Struct_Gunmetal")
            rm.soft.box(a + 0.02, b - 0.02, bz - 0.88, bz + 0.88, 0.45, 0.5, "M_Seat_Upholstery")
    rm.build()
    arch.linear_lights("lobby", [(x0 + 1.2, x1 - 1.2, z, z + 0.15) for z in (41.4, 43.6)])


# ---------------------------------------------------------------- stores, med


def storage() -> None:
    x0, x1, z0, z1 = L.ROOMS["storage"].rect
    rm = RoomMeshes("storage")
    for i, rx in enumerate((84.0, 87.2, 90.4)):
        props.shelf_rack(rm.hard, rx, rx + 1.0, z0 + 2.0, z1 - 1.6, seed=31 + i)
    for i, (piece, x, z) in enumerate(
        (
            ("SM_Hangar_CrateStack", 91.6, z0 + 1.0),
            ("SM_Hangar_Pallet_Loaded", 84.6, z1 - 0.8),
            ("SM_Hangar_Crate_A", 86.0, z1 - 0.6),
            ("SM_Hangar_Crate_B", 91.9, z1 - 0.5),
        )
    ):
        place(piece, x, z, 0.0, f"store_{i + 1}", "storage", lambda k, loc: None)
    rm.build()
    arch.linear_lights(
        "storage",
        [(x, x + 0.12, z0 + 1.6, z1 - 1.2) for x in (85.8, 89.0, 92.2)],
        mat="M_Ops_Light_Dim",
    )


def medbay() -> None:
    """Light-grey variant, but shaded: pools under the bed lamps, cabinets and
    wall terminals along the far wall, the room falls off toward the corners."""
    x0, x1, z0, z1 = L.ROOMS["medbay"].rect
    rm = RoomMeshes("medbay")
    k = 0

    def med_name(kind: str, loc: str, k: int) -> str | None:
        if kind == "bunk":
            return None  # bunk sockets are for paused crew in the quarters only
        return f"medbay_{k}" if kind == "stand" else f"med_{k}"

    beds_x = (75.2, 79.8, 84.4, 89.0)
    for bz in (50.2, 55.0):
        for bx in beds_x:
            k += 1
            place(
                "SM_Bed_Medical",
                bx,
                bz,
                0.0,
                f"med_bed_{k}",
                "medbay",
                lambda kind, loc, k=k: med_name(kind, loc, k),
            )
            spot_light(
                f"LT_Med_Bed_{k}",
                bx,
                bz,
                4.3,
                70.0,
                kelvin=6500.0,
                angle_deg=45.0,
                blend=0.7,
                radius=0.25,
            )
    # Cabinets on the far (med) wall between the doors.
    for a, b in ((71.3, 74.6), (77.4, 86.9), (89.6, 92.7)):
        props.med_cabinet(rm.hard, rm.lights, a, b, z0 + 0.05)
    rm.build()
    arch.linear_lights("medbay", [(x0 + 1.0, x1 - 1.0, 52.55, 52.65)], mat="M_Ops_Light_Dim")


# ---------------------------------------------------------------- corridor


def corridor() -> None:
    zc = L.CORR_Z_MID
    xs = [x for x in (7.2 + 4.8 * k for k in range(18)) if x < 90.0]
    for i, x in enumerate(xs):
        if any(abs(x - fx) < 1.0 for fx in L.BLAST_FRAMES):
            x += 1.2
        sock("waypoint", f"corridor_{i + 1}", x, zc, 0.0, 90.0, room="corridor")
    route = [(8.4, 29.2), (88.8, 29.2), (88.8, 30.8), (8.4, 30.8)]
    for i, (x, z) in enumerate(route):
        sock(
            "waypoint",
            f"patrol_a_{i + 1}",
            x,
            z,
            0.0,
            90.0 if i in (0, 3) else -90.0,
            room="corridor",
        )
    for name, (x, w) in L.DOORS_NORTH.items():
        sock("door", name, x, L.CORR_N + 0.6, 0.0, 0.0, room="corridor", width=w)
    for name, (x, w) in L.DOORS_SOUTH.items():
        sock("door", name, x, L.CORR_S - 0.6, 0.0, 0.0, room="corridor", width=w)
    for x in L.BLAST_FRAMES:
        for dx in (-0.42, 0.42):
            sock(
                "light",
                f"blast_{int(x)}_{'w' if dx < 0 else 'e'}",
                x + dx,
                27.5,
                2.1,
                0.0,
                room="corridor",
                colour="#f4f7ff",
                blink_hz=0.0,
            )


# ---------------------------------------------------------------- rooms


def rooms() -> None:
    for rid, r in L.ROOMS.items():
        room(rid, r.name, r.rect)
    room("corridor", "Main Corridor", (L.CORR_X[0], L.CORR_X[1], *L.CORR_FLOOR), main=True)


def occluders() -> None:
    """Depth-only proxies of the architecture and bespoke furniture that stand
    in front of walkable floor (kit pieces bring their own)."""
    hz = L.HERO_Z
    ucx("corridor_n", 3.0, 93.0, L.CORR_N, L.CORR_FLOOR[0], 0.0, 1.1)
    ucx("corridor_s", 3.0, 93.0, L.CORR_FLOOR[1], L.CORR_S, 0.0, 1.1)
    ucx("near", 2.4, 93.6, L.NEAR_Z, L.NEAR_Z + 2.0, 0.0, 1.1)
    ucx("med", 71.0, 93.0, L.MED_WALL[0], L.MED_WALL[1], 0.0, 1.1)
    for i, (a, b) in enumerate(L.CHASES_NORTH):
        ucx(f"chase_n{i}", a, b, hz, L.CORR_N, 0.0, 1.1)
    for i, (a, b) in enumerate(L.CHASES_SOUTH):
        ucx(f"chase_s{i}", a, b, L.CORR_S, L.NEAR_Z, 0.0, 1.1)
    ucx("chase_ls", *L.LOBBY_STORE_CHASE, L.CORR_S, L.MED_WALL[0], 0.0, 1.1)
    ucx("washroom", 11.0, 11.3, L.CORR_S, 48.0, 0.0, 1.1)
    ucx("hull_far", 0.0, 96.0, -2.0, hz + 0.3, 0.0, L.HULL_H)
    for x in (*L.BLAST_FRAMES, *L.END_PORTALS):
        ucx(f"frame_n_{int(x)}", x - 0.6, x + 0.6, L.CORR_N, 28.05, 0.0, 3.0)
        ucx(f"frame_s_{int(x)}", x - 0.6, x + 0.6, 31.95, L.CORR_S, 0.0, 1.1)
    for x in L.END_PORTALS:
        ucx(f"portal_leaf_{int(x)}", x - 0.08, x + 0.08, L.CORR_N, L.CORR_S, 0.0, 3.0)
    x0, x1, _, z1 = L.LIFT_CORE
    ucx("lift_core", x0, x1, z1 - 0.3, z1 + 0.06, 0.0, 3.4)
    ucx("quarters_lockers", 12.0, 36.6, L.CORR_S + 0.05, L.CORR_S + 0.6, 0.0, 2.05)
    for name, cx in (("team_a", 46.0), ("team_b", 62.0)):
        ucx(f"{name}_pylon", cx - 2.5, cx + 2.5, L.CORR_S + 0.68, L.CORR_S + 1.12, 0.0, 2.78)
    for i, rx in enumerate((84.0, 87.2, 90.4)):
        ucx(f"store_rack_{i}", rx, rx + 1.0, L.CORR_S + 2.0, 46.0 - 1.6, 0.0, 2.4)
