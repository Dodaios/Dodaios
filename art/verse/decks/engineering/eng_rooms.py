"""Rooms of the engineering deck: control room, far wall, lobby, bay, gallery.

Terminals and the master console are deck-side stand-ins until the
props-command pieces land; their sockets come from ``eng_sockets`` so the
runtime contract does not change when the geometry is swapped.
"""

from __future__ import annotations

import math

import bpy
import eng_common as c
from eng_common import Geo, b, build_into
from lib import kit, scene
from mathutils import Matrix, Vector

GUNMETAL = "M_Struct_Gunmetal"
HULL = "M_Hull_Structure"
WALL_LIGHT = "M_Wall_PaintedLight"
WALL_MID = "M_Wall_PaintedMid"
WALL_DARK = "M_Wall_PaintedDark"
CONSOLE = "M_Console_Body"
DECK = "M_Console_Deck"
KEYS = "M_Console_Keys"
SCREEN = "M_Screen"
SEAT = "M_Seat_Upholstery"
RECESS = "M_Recess_Dark"
PIPE = "M_Hull_Pipe"
LAGGED = "M_Hull_PipeInsulated"
HAZARD = "M_Deck_Hazard"
STRIP = "M_Light_WallStrip"

TERMINAL_TILT = 32.0
TERMINAL_SCREEN = (1.3, 0.62)  # live pane size, metres
TERMINAL_SCREEN_Y = 1.13  # centre height of the screen
TERMINAL_SCREEN_BACK = 0.18  # screen centre sits this far behind the screen line
SEAT_OFFSET = 0.85  # seat point in front of the screen line (three +z)
SEAT_HEIGHT = 0.48


def screen_frame(centre: Vector, tilt_deg: float) -> Matrix:
    """Local frame of a tilted screen: x across, y into the screen, z up the screen."""
    t = math.radians(tilt_deg)
    x = Vector((1.0, 0.0, 0.0))
    y = Vector((0.0, math.cos(t), -math.sin(t)))
    z = Vector((0.0, math.sin(t), math.cos(t)))
    m = Matrix((x, y, z)).transposed().to_4x4()
    m.translation = centre
    return m


def terminal_screen_centre(x: float, z_line: float) -> Vector:
    return Vector(b(x, z_line - TERMINAL_SCREEN_BACK, TERMINAL_SCREEN_Y))


# ---------------------------------------------------------------- terminals


BANK_HALF = 5.4  # half length of a two-station console bank
BANK_STATIONS = (-2.4, 2.4)  # live terminals along the bank (local x)


def _hood_profile() -> list[tuple[float, float]]:
    """Rear instrument hood (local y, z), its sloped face in the screens' plane."""
    t = math.radians(TERMINAL_TILT)
    up = (math.sin(t), math.cos(t))
    y_c, z_c = TERMINAL_SCREEN_BACK + 0.012, TERMINAL_SCREEN_Y
    k0 = (0.79 - z_c) / up[1]
    k1 = (1.5 - z_c) / up[1]
    return [
        (y_c + up[0] * k0, 0.79),
        (0.62, 0.79),
        (0.62, 1.5),
        (y_c + up[0] * k1, 1.5),
    ]


@kit.piece("SM_EngBlk_ConsoleBank", dims=(10.8, 1.6, 1.5))
def _console_bank_piece() -> None:
    """Engineering console bank stand-in: two live terminals in a continuous
    desk with a sloped instrument hood, static panels between, two chairs."""
    hb = BANK_HALF
    body = Geo()
    body.box((-hb, -0.3, 0.08), (hb, 0.6, 0.74), CONSOLE)
    body.box((-hb + 0.06, -0.22, 0.0), (hb - 0.06, 0.55, 0.08), RECESS)  # toe recess
    body.box((-hb - 0.04, -0.44, 0.74), (hb + 0.04, 0.64, 0.79), DECK)
    body.prism_x(_hood_profile(), -hb, hb, CONSOLE)
    for x in (-hb, hb):
        body.box((x - 0.06, -0.46, 0.0), (x + 0.06, 0.66, 1.56), GUNMETAL)  # end frames
    body.build("SM_EngBlk_BankBody", bevel_width=0.008)

    w, h = TERMINAL_SCREEN
    centre = Vector((0.0, TERMINAL_SCREEN_BACK, TERMINAL_SCREEN_Y))
    keys = Geo()
    for sx in BANK_STATIONS:
        frame = Matrix.Translation((sx, 0.0, 0.0)) @ screen_frame(centre, TERMINAL_TILT)
        bezel = Geo(frame)
        bezel.box((-w / 2 - 0.05, -0.01, -h / 2 - 0.05), (w / 2 + 0.05, 0.01, h / 2 + 0.05),
                  GUNMETAL)  # fmt: skip
        bezel.build(f"SM_EngBlk_BankBezel_{int(sx * 10)}", bevel_width=0.004)
        g = Geo(frame)
        g.quad([(-w / 2, -0.012, -h / 2), (w / 2, -0.012, -h / 2), (w / 2, -0.012, h / 2),
                (-w / 2, -0.012, h / 2)], SCREEN)  # fmt: skip
        g.build(f"SM_EngBlk_BankScreen_{int(sx * 10)}", bevel_width=0.0)
        keys.box((sx - 0.55, -0.38, 0.79), (sx + 0.55, -0.1, 0.805), KEYS)
    # Static instrument panels on the hood between and beside the terminals.
    for px, pw in ((0.0, 2.2), (-hb + 0.95, 1.5), (hb - 0.95, 1.5)):
        frame = Matrix.Translation((px, 0.0, 0.0)) @ screen_frame(centre, TERMINAL_TILT)
        g = Geo(frame)
        g.box((-pw / 2, -0.014, -0.28), (pw / 2, -0.004, 0.0), KEYS)
        g.box((-pw / 2, -0.014, 0.06), (pw / 2, -0.004, 0.3), "M_Screen")
        g.build(f"SM_EngBlk_BankPanel_{int(px * 10)}", bevel_width=0.0)
        keys.box((px - pw / 2, -0.38, 0.79), (px + pw / 2, -0.12, 0.805), KEYS)
    keys.build("SM_EngBlk_BankKeys", bevel_width=0.002)

    chairs = Geo()
    cy = -SEAT_OFFSET
    for sx in BANK_STATIONS:
        chairs.box((sx - 0.27, cy - 0.25, 0.4), (sx + 0.27, cy + 0.25, SEAT_HEIGHT), SEAT)
        chairs.box((sx - 0.25, cy - 0.34, 0.5), (sx + 0.25, cy - 0.26, 1.06), SEAT)
        chairs.tube((sx, cy, 0.05), (sx, cy, 0.4), 0.045, GUNMETAL, 12)
        chairs.box((sx - 0.3, cy - 0.03, 0.0), (sx + 0.3, cy + 0.03, 0.05), GUNMETAL)
        chairs.box((sx - 0.03, cy - 0.3, 0.0), (sx + 0.03, cy + 0.3, 0.05), GUNMETAL)
    chairs.build("SM_EngBlk_BankChairs", bevel_width=0.012)


# Bank composition of the props-command modules (local x, piece, socket-bearing).
BANK_LAYOUT = (
    (-5.46, "SM_Terminal_EngineeringEnd", False),
    (-4.5, "SM_Terminal_EngineeringFillShort", False),
    (-2.4, "SM_Terminal_Engineering", True),
    (0.0, "SM_Terminal_EngineeringFill", False),
    (2.4, "SM_Terminal_Engineering", True),
    (4.5, "SM_Terminal_EngineeringFillShort", False),
    (5.46, "SM_Terminal_EngineeringEnd", False),
)


def terminals() -> None:
    """Three rows of two banks; bank centres sit between their two terminals.

    With the props-command kit, each bank is composed from its modules and
    the live terminal modules are placed as ``term_<n>`` so their sockets come
    out as ``SOCKET_seat_term_<n>`` / ``SOCKET_screen_term_<n>``.
    """
    if c.KIT_COMMAND:
        n = 0
        with kit.into(scene.collection("Props")):
            for z_line in c.TERM_ROWS_Z:
                for xs in (c.TERM_COLS_X[:2], c.TERM_COLS_X[2:]):
                    xc = sum(xs) / 2
                    # Individual stations: each live module between two end
                    # frames, so every technician's seat reads on its own.
                    for dx in (-2.4, 2.4):
                        n += 1
                        sid = f"term_{n}"
                        x = xc + dx
                        kit.place("SM_Terminal_Engineering", b(x, z_line), 0.0, id=sid,
                                  room="control", group="terminal", link=sid, order=n)  # fmt: skip
                        for k, ex in enumerate((-1.26, 1.26)):
                            kit.place("SM_Terminal_EngineeringEnd", b(x + ex, z_line), 0.0,
                                      room="control", id=f"EngTermEnd_{n:02d}_{k}")  # fmt: skip
        return
    with kit.into(scene.collection("Props")):
        for r, z_line in enumerate(c.TERM_ROWS_Z):
            for side, xs in enumerate((c.TERM_COLS_X[:2], c.TERM_COLS_X[2:])):
                xc = sum(xs) / 2
                obj = kit.place("SM_EngBlk_ConsoleBank", b(xc, z_line), 0.0,
                                id=f"EngBank_{r + 1}{'WE'[side]}")  # fmt: skip
                kit.tag(obj, nav="block")


def plot_table() -> None:
    """Systems plot table in the aisle between the master console and the banks."""
    x, z = c.MASTER_X, 9.6
    geo = Geo()
    geo.box3(x - 2.3, x + 2.3, z - 1.1, z + 1.1, 0.12, 0.86, CONSOLE)
    geo.box3(x - 2.1, x + 2.1, z - 0.9, z + 0.9, 0.0, 0.12, RECESS)
    geo.box3(x - 2.45, x + 2.45, z - 1.25, z + 1.25, 0.86, 0.94, GUNMETAL)
    obj = build_into("Props", geo, "SM_Eng_PlotTable", bevel_width=0.01)
    kit.tag(obj, nav="block")
    top = Geo()
    top.quad([b(x - 2.25, z + 1.05, 0.945), b(x + 2.25, z + 1.05, 0.945),
              b(x + 2.25, z - 1.05, 0.945), b(x - 2.25, z - 1.05, 0.945)], SCREEN)  # fmt: skip
    build_into("Props", top, "SM_Eng_PlotTableTop", bevel_width=0.0)


def standing_consoles() -> None:
    """Diagnostics line in the south of the control room: standing consoles
    aligned with the terminal columns, where off-duty technicians idle."""
    if not c.KIT_COMMAND:
        return
    with kit.into(scene.collection("Props")):
        for i, x in enumerate(c.TERM_COLS_X):
            kit.place("SM_Console_Standing", b(x, 36.6), 0.0, id=f"workshop_{11 + i}",
                      room="control")  # fmt: skip


def master_console() -> None:
    """Master systems console against the far wall, with the wall display."""
    if c.KIT_COMMAND:
        with kit.into(scene.collection("Props")):
            kit.place("SM_Console_MasterDesk", b(c.MASTER_X, c.MASTER_Z), 0.0, id="master",
                      room="control", station="master", station_kind="coding_launcher")  # fmt: skip
        return
    geo = Geo()
    x0, x1 = c.MASTER_X - 4.8, c.MASTER_X + 4.8
    zf = c.MASTER_Z
    geo.box3(x0, x1, zf - 1.4, zf, 0.0, 0.74, CONSOLE)
    geo.box3(x0 - 0.05, x1 + 0.05, zf - 1.45, zf + 0.06, 0.74, 0.8, DECK)
    geo.box3(x0, x1, c.FAR_WALL_Z, zf - 1.4, 0.0, 1.9, CONSOLE)  # back cabinet
    geo.box3(x0 + 0.1, x1 - 0.1, zf - 0.02, zf + 0.04, 0.0, 0.1, RECESS)
    obj = build_into("Props", geo, "SM_Eng_MasterConsole", bevel_width=0.01)
    kit.tag(obj, nav="block")

    for i in range(5):
        sx = c.MASTER_X + (i - 2) * 1.9
        frame = screen_frame(Vector(b(sx, zf - 1.05, 1.18)), 30.0)
        g = Geo(frame)
        g.box((-0.82, 0.004, -0.34), (0.82, 0.08, 0.34), CONSOLE)
        build_into("Props", g, f"SM_Eng_MasterHousing_{i}", bevel_width=0.005)
        q = Geo(frame)
        q.quad([(-0.78, 0, -0.3), (0.78, 0, -0.3), (0.78, 0, 0.3), (-0.78, 0, 0.3)], SCREEN)
        build_into("Props", q, f"SM_Eng_MasterScreen_{i}", bevel_width=0.0)
    keys = Geo()
    keys.box3(x0 + 0.3, x1 - 0.3, zf - 0.45, zf - 0.1, 0.8, 0.82, KEYS)
    build_into("Props", keys, "SM_Eng_MasterKeys", bevel_width=0.002)


# ---------------------------------------------------------------- far wall


DISPLAY_X = (11.6, 22.4)  # wall stretch behind the master desk carrying the display


def far_wall_control() -> None:
    """Control-room stretch of the hull wall: panelling, display, plenum above."""
    z = c.FAR_WALL_Z
    if c.KIT_ARCH:
        _display(z)
        return
    wall = Geo()
    # Panels on the 1.2 m grid, proud of the hull by 4 cm, reveals between.
    x = c.WEST_HULL_X[1]
    while x < c.PARTITION_X[0] - 0.01:
        wall.box3(x + 0.02, x + c.MODULE - 0.02, z, z + 0.05, 0.25, c.CONTROL_H - 0.3, WALL_LIGHT)
        x += c.MODULE
    wall.box3(c.WEST_HULL_X[1], c.PARTITION_X[0], z, z + 0.08, 0.0, 0.25, WALL_DARK)  # kick
    wall.box3(c.WEST_HULL_X[1], c.PARTITION_X[0], z, z + 0.7, c.CONTROL_H - 0.3, c.CONTROL_H + 0.5,
              GUNMETAL)  # fmt: skip
    obj = build_into("Architecture", wall, "SM_Eng_CtrlWallPanels", bevel_width=0.005)
    kit.tag(obj, nav="block")

    _plenum(z)


def _display(z: float) -> None:
    """Master wall display, framed and mounted proud of the hero wall."""
    display = Geo()
    dx0, dx1 = c.MASTER_X - 4.8, c.MASTER_X + 4.8
    display.box3(dx0 - 0.15, dx1 + 0.15, z, z + 0.16, 2.2, 4.3, GUNMETAL)
    obj = build_into("Architecture", display, "SM_Eng_WallDisplayFrame", bevel_width=0.008)
    kit.tag(obj, nav="block")
    face = Geo()
    face.quad([b(dx0, z + 0.17, 2.3), b(dx1, z + 0.17, 2.3), b(dx1, z + 0.17, 4.2),
               b(dx0, z + 0.17, 4.2)], SCREEN)  # fmt: skip
    build_into("Architecture", face, "SM_Eng_WallDisplay", bevel_width=0.0)


def _display_wall(z: float) -> None:
    """Dark panelled stretch with the master wall display above the desk."""
    x0, x1 = DISPLAY_X
    wall = Geo()
    wall.slab3(x0, x1, z - 0.3, z, 0.0, c.CONTROL_H, WALL_DARK, "M_Section_Cap")
    x = x0
    while x < x1 - 0.01:
        wall.box3(x + 0.015, x + c.MODULE - 0.015, z, z + 0.03, 0.2, 1.95, "M_Wall_Charcoal")
        x += c.MODULE
    wall.box3(x0, x1, z, z + 0.06, 4.3, 4.36, "M_Trim_BrushedSteel")
    obj = build_into("Architecture", wall, "SM_Eng_DisplayWall", bevel_width=0.004)
    kit.tag(obj, nav="block")
    display = Geo()
    dx0, dx1 = c.MASTER_X - 4.8, c.MASTER_X + 4.8
    display.box3(dx0 - 0.15, dx1 + 0.15, z, z + 0.14, 2.0, 4.2, GUNMETAL)
    obj = build_into("Architecture", display, "SM_Eng_WallDisplayFrame", bevel_width=0.008)
    kit.tag(obj, nav="block")
    face = Geo()
    face.quad([b(dx0, z + 0.15, 2.1), b(dx1, z + 0.15, 2.1), b(dx1, z + 0.15, 4.1),
               b(dx0, z + 0.15, 4.1)], SCREEN)  # fmt: skip
    build_into("Architecture", face, "SM_Eng_WallDisplay", bevel_width=0.0)


def _plenum(z: float) -> None:
    """Structure above the control-room ceiling line, up to the hull wall top."""
    plenum = Geo()
    x = c.WEST_HULL_X[1]
    while x <= c.PARTITION_X[1] + 0.01:
        plenum.box3(x - 0.18, x + 0.18, z, z + 0.45, c.CONTROL_H + 0.5, c.HALL_H, GUNMETAL)
        x += 2.4
    plenum.box3(c.WEST_HULL_X[1], c.PARTITION_X[1], z, z + 0.9, 7.2, 8.0, HULL)  # duct
    plenum.box3(c.WEST_HULL_X[1], c.PARTITION_X[1], z, z + 0.6, 10.2, 10.7, HULL)
    obj = build_into("Architecture", plenum, "SM_Eng_CtrlPlenum", bevel_width=0.01)
    kit.tag(obj, nav="block")
    pipes = Geo()
    for y, r in ((8.6, 0.22), (9.2, 0.16), (9.65, 0.16)):
        pipes.tube(b(c.WEST_HULL_X[1], z + 0.5, y), b(c.PARTITION_X[1], z + 0.5, y), r, PIPE, 16)
    build_into("Architecture", pipes, "SM_Eng_CtrlPlenumPipes", bevel_width=0.0)
    # Dim service lamps keep the plenum from reading as void: a housing on a
    # rib, its lens, and the light it casts.
    lamps = Geo()
    lenses = Geo()
    for i, x in enumerate((6.8, 14.0, 21.2, 28.4)):
        lamps.box3(x - 0.16, x + 0.16, z + 0.45, z + 0.62, 6.2, 6.42, GUNMETAL)
        mat = "M_Light_Maint_Amber" if i % 2 == 0 else "M_Light_Maint_Red"
        lenses.box3(x - 0.1, x + 0.1, z + 0.62, z + 0.64, 6.24, 6.38, mat)
        light = bpy.data.lights.new(f"LT_CtrlPlenum_{i}", "POINT")
        light.energy = 40.0
        light.color = (1.0, 0.45, 0.12) if i % 2 == 0 else (1.0, 0.1, 0.05)
        light.shadow_soft_size = 0.08
        obj = bpy.data.objects.new(f"LT_CtrlPlenum_{i}", light)
        obj.location = b(x, z + 0.8, 6.3)
        scene.collection("Lights").objects.link(obj)
    build_into("Architecture", lamps, "SM_Eng_CtrlPlenumLamps", bevel_width=0.004)
    build_into("Architecture", lenses, "SM_Eng_CtrlPlenumLenses", bevel_width=0.0)


def far_wall_reactor() -> None:
    """Reactor stretch of the hull wall: heat-exchanger stacks, coolant lines,
    a service gantry and slot lights, all at full height."""
    z = c.FAR_WALL_Z
    stacks = Geo()
    stack_x = (37.8, 45.0, 63.0, 70.2, 77.4)
    for x in stack_x:
        stacks.cylinder(x, z + 1.35, 1.25, 0.0, c.HALL_H - 0.4, LAGGED, 48)
        for y in (0.6, 3.6, 6.6, 9.6):
            stacks.cylinder(x, z + 1.35, 1.35, y, y + 0.3, GUNMETAL, 48)
        stacks.box3(x - 1.5, x + 1.5, z, z + 2.8, 0.0, 0.5, GUNMETAL)  # plinth
    obj = build_into("Props", stacks, "SM_Eng_HeatStacks", bevel_width=0.01)
    kit.tag(obj, nav="block")

    lines = Geo()
    x0, x1 = c.PARTITION_X[1], c.EAST_HULL_X[0]
    for y, r, dz in ((1.5, 0.32, 0.45), (2.3, 0.26, 0.4), (4.5, 0.4, 0.55)):
        lines.tube(b(x0, z + dz, y), b(x1, z + dz, y), r, PIPE, 20)
    obj = build_into("Props", lines, "SM_Eng_CoolantLines", bevel_width=0.0)
    kit.tag(obj, nav="block")

    gantry = Geo()
    gantry.box3(x0, x1, z, z + 1.4, 6.0, 6.15, "M_Floor_Grating")
    x = x0
    while x <= x1:
        gantry.box3(x - 0.04, x + 0.04, z + 1.3, z + 1.38, 6.15, 7.2, GUNMETAL)
        x += 1.2
    gantry.box3(x0, x1, z + 1.3, z + 1.38, 7.12, 7.2, GUNMETAL)
    gantry.box3(x0, x1, z + 1.3, z + 1.38, 6.62, 6.68, GUNMETAL)
    obj = build_into("Props", gantry, "SM_Eng_WallGantry", bevel_width=0.004)
    kit.tag(obj, nav="none")

    lights = Geo()
    slot_x = (41.4, 48.6, 51.6, 56.4, 59.4, 66.6, 73.8)
    for x in slot_x:
        for i, y0 in enumerate((1.0, 3.4, 8.0)):
            h = 1.8 if i < 2 else 2.6
            lights.box3(x - 0.09, x + 0.09, z, z + 0.04, y0, y0 + h, STRIP)
            lights.box3(x + 0.31, x + 0.49, z, z + 0.04, y0 + 0.6, y0 + h - 0.3, STRIP)
    obj = build_into("Props", lights, "SM_Eng_WallSlotLights", bevel_width=0.0)
    kit.tag(obj, nav="none")

    lamps = Geo()
    for x in (34.2, 40.2, 46.8, 52.8, 55.2, 61.2, 67.8, 74.4, 80.4):
        lamps.box3(x - 0.08, x + 0.08, z + 1.4, z + 1.5, 7.3, 7.42, "M_Light_Maint_Red")
    build_into("Props", lamps, "SM_Eng_WallMaintLamps", bevel_width=0.0)

    hazard = Geo()
    hazard.box3(x0, x1, z, z + 0.03, 0.0, 0.4, HAZARD)
    build_into("Props", hazard, "SM_Eng_WallHazardBase", bevel_width=0.0)


# ---------------------------------------------------------------- lobby, bay, gallery


def lift_lobby() -> None:
    if c.KIT_ARCH:
        z1 = c.CONTROL_SOUTH_Z[1]
        with kit.into(scene.collection("Props")):
            # Deck directory beside the lift and crew lockers along the wall.
            kit.place("SM_Terminal_Wall", b(c.LIFT_CORE_X[1] - 0.6, z1), 0.0, room="lobby",
                      id="EngLobbyDirectory")  # fmt: skip
            if c.KIT_COMMAND:
                kit.place("SM_Lockers_Uniform", b(8.6, z1), 0.0, room="lobby",
                          id="EngLobbyLockers")  # fmt: skip
        return
    core = Geo()
    lx = c.LIFT_X
    z0, z1 = c.LIFT_CORE_Z
    core.slab3(lx - 3.0, lx + 3.0, c.CONTROL_SOUTH_Z[0], z1, 0.0, c.CONTROL_H, WALL_DARK,
               "M_Section_Cap")  # fmt: skip
    obj = build_into("Architecture", core, "SM_Eng_LiftCore", bevel_width=0.008)
    kit.tag(obj, nav="block")
    doors = Geo()
    doors.box3(lx - 1.55, lx + 1.55, z1, z1 + 0.18, 0.0, 3.25, GUNMETAL)  # frame
    doors.box3(lx - 1.2, lx - 0.01, z1 + 0.18, z1 + 0.24, 0.02, 2.95, WALL_MID)
    doors.box3(lx + 0.01, lx + 1.2, z1 + 0.18, z1 + 0.24, 0.02, 2.95, WALL_MID)
    obj = build_into("Architecture", doors, "SM_Eng_LiftDoors", bevel_width=0.006)
    kit.tag(obj, nav="block")
    glow = Geo()
    glow.box3(lx - 1.2, lx + 1.2, z1 + 0.18, z1 + 0.2, 3.05, 3.15, STRIP)
    glow.box3(lx + 1.75, lx + 1.95, z1, z1 + 0.06, 1.2, 1.5, "M_Indicator_Amber")
    build_into("Architecture", glow, "SM_Eng_LiftLights", bevel_width=0.0)
    mark = Geo()
    mark.box3(lx - 1.6, lx + 1.6, z1 + 0.25, z1 + 1.45, 0.0, 0.004, HAZARD)
    obj = build_into("Props", mark, "SM_Eng_LiftHazard", bevel_width=0.0)
    kit.tag(obj, nav="none")


def maintenance_bay() -> None:
    racks = Geo()
    for zr in (43.2, 45.6, 48.0, 50.4):
        x0 = c.LOBBY_BAY_X[1]
        if abs(zr - c.DOOR_LOBBY_BAY) > 2.0:
            racks.box3(x0, x0 + 0.7, zr - 1.1, zr + 1.1, 0.0, 2.2, GUNMETAL)
        x0 = c.BAY_GALLERY_X[0] - 0.7
        if abs(zr - c.DOOR_BAY_GALLERY) > 2.0:
            racks.box3(x0, x0 + 0.7, zr - 1.1, zr + 1.1, 0.0, 2.2, GUNMETAL)
    bench_z = c.CONTROL_SOUTH_Z[1]
    racks.box3(18.0, 22.8, bench_z + 0.1, bench_z + 0.9, 0.0, 0.9, CONSOLE)
    obj = build_into("Props", racks, "SM_Eng_BayRacks", bevel_width=0.008)
    kit.tag(obj, nav="block")
    dock = Geo()
    dock.sector(0.0, 0.9, 0.0, 0.08, GUNMETAL, segments=48, centre=(26.4, -48.6))
    dock.box3(26.2, 26.6, 49.5, 49.9, 0.0, 1.3, GUNMETAL)
    obj = build_into("Props", dock, "SM_Eng_DroneDock", bevel_width=0.006)
    kit.tag(obj, nav="none")


def conduit_gallery() -> None:
    pipes = Geo()
    x0, x1 = c.GALLERY[0] + 0.2, c.EAST_HULL_X[0]
    # North bank: broken at each opening from the hall, where the lines dive
    # under the deck plates.
    cuts = [x0]
    for xo in c.GALLERY_OPENINGS:
        cuts += [xo - c.DOOR_W / 2 - 0.2, xo + c.DOOR_W / 2 + 0.2]
    cuts.append(x1)
    for zz, y, r, mat in ((39.1, 0.45, 0.3, LAGGED), (39.8, 0.4, 0.25, PIPE),
                          (40.4, 0.35, 0.2, PIPE)):  # fmt: skip
        for a, bb in zip(cuts[0::2], cuts[1::2], strict=True):
            pipes.tube(b(a, zz, y), b(bb, zz, y), r, mat, 20)
            for xe in (a, bb):
                if x0 < xe < x1:
                    pipes.tube(b(xe, zz, y), b(xe, zz, -0.4), r, mat, 20)
    for zz, y, r, mat in ((51.4, 0.5, 0.42, LAGGED), (50.5, 0.38, 0.26, PIPE)):
        pipes.tube(b(x0, zz, y), b(x1, zz, y), r, mat, 20)
    x = 36.0
    while x < x1:
        for zs in (39.8, 51.0):
            if zs > 45 or all(abs(x - xo) > c.DOOR_W / 2 + 0.3 for xo in c.GALLERY_OPENINGS):
                pipes.box3(x - 0.12, x + 0.12, zs - 1.0, zs + 1.0, 0.0, 0.3, GUNMETAL)
        x += 2.4
    obj = build_into("Props", pipes, "SM_Eng_GalleryConduits", bevel_width=0.0)
    kit.tag(obj, nav="block")
    risers = Geo()
    for x in (44.4, 63.6, 79.2):
        risers.cylinder(x, 39.2, 0.32, 0.0, 3.0, LAGGED, 24)
        risers.box3(x - 0.5, x + 0.5, 39.6, 40.0, 1.0, 2.0, CONSOLE)
    obj = build_into("Props", risers, "SM_Eng_GalleryRisers", bevel_width=0.006)
    kit.tag(obj, nav="block")


def build() -> None:
    terminals()
    standing_consoles()
    plot_table()
    master_console()
    far_wall_control()
    lift_lobby()
    if c.KIT_REACTOR:
        import eng_dressing

        eng_dressing.build()
    else:
        far_wall_reactor()
        maintenance_bay()
        conduit_gallery()
