"""Engineering props (deck 3): power conduits, junction boxes, cable trays,
coolant pipes, warning panels, tool racks, the drone dock and the heavy wall
machinery of the engineering hull wall.

Piece-local frame: centred on X, deck at Z = 0, -Y toward the camera.
Wall-mounted pieces stand with their back against the wall plane at Y = 0 and
protrude toward -Y (into the room); place them on a wall's room face.
"""

from __future__ import annotations

import math

from lib import kit as K

from . import _geo as G
from ._mats import m

DECK_HEIGHT = 6.0  # default floor-to-ceiling for floor-to-ceiling pieces


# --------------------------------------------------------------------------
# Power conduits
# --------------------------------------------------------------------------


def _conduit_tube(mb, decals, x, y, r, height, rnd, slot=True):
    """One segmented conduit tube with collars, fins and an inspection slot."""
    metal, steel = m("gunmetal"), m("dark_steel")
    G.tube_z(mb, r, 0.35, height, m("panel_dark"), 32, x=x, y=y)
    with G.xf(decals, G.T(x, y, 0.0)):  # cut at the (hidden) ceiling: section cap
        G.annulus(decals, 0.0, r + 0.001, height + 0.002, m("section_cap"), 32)
    seg = 1.2
    n = int((height - 0.6) / seg)
    for k in range(n + 1):
        z = 0.4 + k * seg
        with G.xf(mb, G.T(x, y, 0.0)):
            G.ring(mb, r - 0.02, r + 0.07, z, z + 0.12, metal, 32)
            for i in range(8):
                with G.xf(mb, G.Rz(45.0 * i + 22.5)):
                    mb.box((r + 0.04, -0.025, z + 0.12), (r + 0.075, 0.025, z + 0.2), steel)
    with G.xf(mb, G.T(x, y, 0.0)):
        for i in range(12):  # cooling fins on the lowest segment
            with G.xf(mb, G.Rz(30.0 * i)):
                mb.box((r, -0.015, 0.55), (r + 0.16, 0.015, 1.5), metal)
    if slot:
        slot_mat = m("core_hot")
        for k in (2, 3):
            z0 = 0.4 + k * seg + 0.25
            mb.box((x - 0.04, y - r - 0.012, z0), (x + 0.04, y - r + 0.03, z0 + 0.7), steel)
            decals.box(
                (x - 0.022, y - r - 0.016, z0 + 0.04),
                (x + 0.022, y - r - 0.012, z0 + 0.66),
                slot_mat,
            )
    G.text(
        decals,
        f"PC-{rnd.randrange(10, 99)}",
        0.12,
        m("stencil_white"),
        G.on_face((x, y - r - 0.075, 1.75), "-Y"),
    )


def build_power_conduit(height=DECK_HEIGHT, tubes=1):
    """Floor-to-ceiling power conduit (single or triple) on a plinth."""
    rnd = G.rng("conduit", height, tubes)
    mb, decals = K.MeshBuilder(), K.MeshBuilder()
    metal, steel = m("gunmetal"), m("dark_steel")
    if tubes == 1:
        w, d = 1.2, 1.2
        spots = [(0.0, 0.0, 0.42)]
    else:
        w, d = 2.4, 1.2
        spots = [(-0.6, 0.15, 0.3), (0.6, 0.15, 0.3), (0.0, -0.25, 0.3)]
    G.chamfer_box(mb, (-w / 2, -d / 2, 0.0), (w / 2, d / 2, 0.35), 0.12, steel)
    G.chamfer_box(
        mb, (-w / 2 + 0.06, -d / 2 + 0.06, 0.35), (w / 2 - 0.06, d / 2 - 0.06, 0.42), 0.1, metal
    )
    G.chamfer_box(
        mb,
        (-w / 2 + 0.1, -d / 2 + 0.1, height - 0.6),
        (w / 2 - 0.1, d / 2 - 0.1, height - 0.45),
        0.1,
        steel,
    )
    for x, y, r in spots:
        _conduit_tube(mb, decals, x, y, r, height, rnd, slot=(y <= 0.0))
    for sx in (-1, 1):  # anchor bolts
        for sy in (-1, 1):
            G.tube_z(mb, 0.035, 0.35, 0.4, metal, 8, x=sx * (w / 2 - 0.15), y=sy * (d / 2 - 0.15))
    mb.build("SM_conduit_body", bevel_width=0.008)
    lamps = K.MeshBuilder()
    lamps.box((w / 2 - 0.3, -d / 2 - 0.005, 0.2), (w / 2 - 0.2, -d / 2, 0.26), m("lamp_green"))
    lamps.build("SM_conduit_lamps", bevel_width=0.0, nav="none")
    decals.build("SM_conduit_decals", bevel_width=0.0, nav="none")
    K.occluder(((-w / 2, -d / 2, 0.0), (w / 2, d / 2, height)), nav="block")


K.register_variant("SM_Eng_PowerConduit", build_power_conduit, dims=(1.2, 1.2, DECK_HEIGHT))
K.register_variant(
    "SM_Eng_PowerConduit_Triple", build_power_conduit, dims=(2.4, 1.2, DECK_HEIGHT), tubes=3
)


# --------------------------------------------------------------------------
# Junction boxes and cabinets (wall-mounted: back at Y = 0, toward -Y)
# --------------------------------------------------------------------------


def _door_panel(mb, x0, x1, z0, z1, y, rnd):
    """Hinged steel door with latches and a small window of indicators."""
    metal, steel = m("gunmetal"), m("dark_steel")
    mb.box((x0, y - 0.03, z0), (x1, y, z1), m("panel_light"))
    mb.box((x0 + 0.06, y - 0.045, z0 + 0.06), (x1 - 0.06, y - 0.03, z1 - 0.06), m("panel_light"))
    for zz in (z0 + 0.15, z1 - 0.25):
        mb.box((x0 - 0.02, y - 0.05, zz), (x0 + 0.03, y, zz + 0.1), steel)
    mb.box(
        (x1 - 0.12, y - 0.07, (z0 + z1) / 2 - 0.08),
        (x1 - 0.08, y - 0.03, (z0 + z1) / 2 + 0.08),
        metal,
    )


def build_junction_box(w=1.2, h=1.5, d=0.35, z0=0.6, floor=False):
    """Electrical junction box/cabinet with door, indicators, conduits, label."""
    rnd = G.rng("jbox", w, h, d, floor)
    mb, decals, lamps = K.MeshBuilder(), K.MeshBuilder(), K.MeshBuilder()
    body, steel, metal = m("panel_dark"), m("dark_steel"), m("gunmetal")
    if floor:
        z0 = 0.0
        G.chamfer_box(mb, (-w / 2, -d, 0.0), (w / 2, 0.0, 0.12), 0.03, steel)
        z0 = 0.12
    mb.box((-w / 2, -d, z0), (w / 2, 0.0, z0 + h), body)
    mb.box((-w / 2 - 0.02, -d - 0.02, z0 + h - 0.06), (w / 2 + 0.02, 0.0, z0 + h), steel)
    leaves = 2 if w > 0.9 else 1
    for i in range(leaves):
        x0 = -w / 2 + 0.05 + i * (w - 0.1) / leaves
        x1 = x0 + (w - 0.1) / leaves - 0.02
        _door_panel(mb, x0, x1, z0 + 0.06, z0 + h - 0.1, -d, rnd)
    for i in range(4):  # indicator row
        x = -w / 2 + 0.2 + i * 0.12
        lamps.box(
            (x - 0.025, -d - 0.05, z0 + h - 0.28),
            (x + 0.025, -d - 0.045, z0 + h - 0.23),
            m(("lamp_green", "lamp_green", "lamp_amber", "lamp_red")[i]),
        )
    for x in (-w / 4, w / 4):  # conduits up the wall
        mb.tube((x, -0.12, z0 + h), (x, -0.12, z0 + h + 1.6), 0.05, metal, 10)
        mb.box((x - 0.08, -0.2, z0 + h + 0.8), (x + 0.08, 0.0, z0 + h + 0.86), steel)
    with G.xf(decals, G.on_face((w / 4 - 0.02, -d - 0.046, z0 + h * 0.62), "-Y")):
        decals.quad(
            [(-0.14, -0.1, 0), (0.14, -0.1, 0), (0.14, 0.1, 0), (-0.14, 0.1, 0)], m("hazard")
        )
    G.text(
        decals,
        f"JB-{rnd.randrange(100, 999)}  11 KV",
        0.06,
        m("stencil_dark"),
        G.on_face((-w / 4, -d - 0.046, z0 + h * 0.62), "-Y"),
    )
    mb.build("SM_jbox_body", bevel_width=0.006)
    lamps.build("SM_jbox_lamps", bevel_width=0.0, nav="none")
    decals.build("SM_jbox_decals", bevel_width=0.0, nav="none")
    K.occluder(((-w / 2, -d, 0.0 if floor else z0), (w / 2, 0.0, z0 + h)), nav="block")


K.register_variant("SM_Eng_JunctionBox", build_junction_box, dims=(1.2, 0.35, 2.1))
K.register_variant(
    "SM_Eng_JunctionCabinet",
    build_junction_box,
    dims=(1.2, 0.6, 2.12),
    w=1.2,
    h=2.0,
    d=0.6,
    floor=True,
)


# --------------------------------------------------------------------------
# Cable trays
# --------------------------------------------------------------------------


def _cables(mb, x0, x1, y0, y1, z, rnd, n=7):
    for i in range(n):
        y = y0 + (i + 0.5) * (y1 - y0) / n
        r = rnd.choice((0.025, 0.03, 0.04))
        sag = rnd.uniform(-0.01, 0.01)
        mb.tube(
            (x0, y + sag, z + r),
            (x1, y - sag, z + r),
            r,
            m("rubber") if i % 3 else m("dark_steel"),
            8,
        )


def build_cable_tray(length=2.4, wall=False, height=2.6):
    """Ladder cable tray along X with cable bundle; floor or wall bracketed."""
    rnd = G.rng("tray", length, wall)
    mb = K.MeshBuilder()
    metal, steel = m("gunmetal"), m("dark_steel")
    hl = length / 2
    w = 0.6
    if wall:
        y0, y1, z = -w - 0.1, -0.1, height
        for x in (-hl + 0.3, hl - 0.3):
            mb.box((x - 0.04, -w - 0.12, z - 0.06), (x + 0.04, 0.0, z), steel)
            G.beam(mb, (x, -0.02, z - 0.5), (x, -w * 0.8, z - 0.06), 0.06, 0.06, steel)
            mb.box((x - 0.08, -0.03, z - 0.6), (x + 0.08, 0.0, z + 0.05), steel)
    else:
        y0, y1, z = -w / 2, w / 2, 0.12
        for x in (-hl + 0.2, hl - 0.2):
            for y in (y0, y1):
                mb.box((x - 0.04, y - 0.04, 0.0), (x + 0.04, y + 0.04, z), steel)
    for y in (y0, y1):  # side rails
        mb.box((-hl, y - 0.015, z), (hl, y + 0.015, z + 0.12), metal)
    for i in range(int(length / 0.3) + 1):  # rungs
        x = -hl + 0.05 + i * (length - 0.1) / int(length / 0.3)
        mb.box((x - 0.015, y0, z), (x + 0.015, y1, z + 0.025), metal)
    _cables(mb, -hl, hl, y0 + 0.05, y1 - 0.05, z + 0.025, rnd)
    mb.build("SM_tray_body", bevel_width=0.004, nav="none" if wall else "block")
    if not wall:
        K.occluder(((-hl, y0, 0.0), (hl, y1, z + 0.14)), nav="block")


K.register_variant("SM_Eng_CableTray_Floor", build_cable_tray, dims=(2.4, 0.64, 0.26))
K.register_variant(
    "SM_Eng_CableTray_Wall", build_cable_tray, dims=(2.4, 0.72, 2.75), nav="none", wall=True
)


# --------------------------------------------------------------------------
# Coolant pipes
# --------------------------------------------------------------------------


def build_coolant_pipes(length=4.8):
    """Three coolant pipes on floor stands with flanges, valve and insulation."""
    mb, decals = K.MeshBuilder(), K.MeshBuilder()
    metal, steel = m("gunmetal"), m("dark_steel")
    hl = length / 2
    pipes = ((-0.35, 0.55, 0.13), (0.0, 0.55, 0.13), (0.4, 0.75, 0.22))
    for y, z, r in pipes:
        mb.tube((-hl, y, z), (hl, y, z), r, metal if r < 0.2 else m("insulation"), 20, caps=False)
        for x in (-hl + 0.05, 0.0, hl - 0.05):
            mb.tube((x - 0.05, y, z), (x + 0.05, y, z), r + 0.05, steel, 20)
    for x in (-hl + 0.6, hl - 0.6):  # stands
        mb.box((x - 0.06, -0.6, 0.0), (x + 0.06, 0.7, 0.08), steel)
        for y, z, r in pipes:
            mb.box((x - 0.04, y - 0.04, 0.08), (x + 0.04, y + 0.04, z - r), steel)
            mb.box((x - 0.05, y - r - 0.02, z - 0.02), (x + 0.05, y + r + 0.02, z + 0.02), metal)
    for i in range(int(length / 0.8)):  # insulation jacket bands on the big pipe
        x = -hl + 0.4 + i * 0.8
        mb.tube((x - 0.02, 0.4, 0.75), (x + 0.02, 0.4, 0.75), 0.235, metal, 20)
    vx = hl * 0.35  # valve on the middle pipe
    mb.tube((vx, 0.0, 0.55), (vx, 0.0, 0.95), 0.05, steel, 10)
    with G.xf(mb, G.T(vx, 0.0, 0.97)):
        G.ring(mb, 0.16, 0.2, -0.02, 0.02, m("stencil_red"), 24)
        for i in range(4):
            with G.xf(mb, G.Rz(45.0 * i)):
                mb.box((-0.17, -0.012, -0.012), (0.17, 0.012, 0.012), metal)
    for x in (-hl * 0.6, hl * 0.6):  # flow bands and arrows (painted)
        for y, z, r in pipes[:2]:
            mb.tube((x - 0.08, y, z), (x + 0.08, y, z), r + 0.004, m("stencil_amber"), 20)
    G.text(
        decals,
        "COOLANT RETURN  >>",
        0.09,
        m("stencil_dark"),
        G.T(-hl * 0.6 + 0.4, 0.4, 0.75 + 0.236),
    )
    mb.build("SM_coolant_body", bevel_width=0.005)
    decals.build("SM_coolant_decals", bevel_width=0.0, nav="none")
    K.occluder(((-hl, -0.6, 0.0), (hl, 0.7, 1.0)), nav="block")


K.register_variant("SM_Eng_CoolantPipes", build_coolant_pipes, dims=(4.8, 1.3, 1.0))


# --------------------------------------------------------------------------
# Warning panel, tool rack, drone dock
# --------------------------------------------------------------------------


def build_warning_panel():
    """Wall warning panel: hazard border, generic warning text, red beacon."""
    mb, decals, lamps = K.MeshBuilder(), K.MeshBuilder(), K.MeshBuilder()
    steel = m("dark_steel")
    mb.box((-0.6, -0.05, 0.4), (0.6, 0.0, 2.8), m("panel_light"))
    for x0, x1, z0, z1 in (
        (-0.6, 0.6, 0.4, 0.55),
        (-0.6, 0.6, 2.65, 2.8),
        (-0.6, -0.45, 0.4, 2.8),
        (0.45, 0.6, 0.4, 2.8),
    ):
        mb.box((x0, -0.065, z0), (x1, -0.05, z1), m("hazard"))
    G.tube_z(mb, 0.1, 2.8, 2.9, steel, 16, y=-0.12)
    G.tube_z(lamps, 0.08, 2.9, 3.05, m("lamp_red"), 16, y=-0.12)
    for i, line in enumerate(
        ("DANGER", "REACTOR ACCESS", "AUTHORISED CREW ONLY", "RADIATION SHIELD 4")
    ):
        size = 0.2 if i == 0 else 0.075
        G.text(
            decals,
            line,
            size,
            m("stencil_dark"),
            G.on_face((0.0, -0.051, 2.25 - i * 0.28 - (0.1 if i else 0.0)), "-Y"),
        )
    mb.build("SM_warnpanel_body", bevel_width=0.004, nav="none")
    lamps.build("SM_warnpanel_lamps", bevel_width=0.0, nav="none")
    decals.build("SM_warnpanel_decals", bevel_width=0.0, nav="none")


def build_tool_rack():
    """Wall tool rack: pegboard, hanging tools, shelf cases, gas cylinders."""
    rnd = G.rng("toolrack")
    mb = K.MeshBuilder()
    metal, steel, dark = m("gunmetal"), m("dark_steel"), m("panel_dark")
    mb.box((-1.2, -0.03, 0.6), (1.2, 0.0, 2.2), dark)
    for x in (-1.2, 1.2):
        mb.box((x - 0.04, -0.45, 0.0), (x + 0.04, 0.0, 2.3), steel)
    mb.box((-1.2, -0.45, 0.55), (1.2, 0.0, 0.6), steel)
    mb.box((-1.2, -0.45, 0.0), (1.2, 0.0, 0.08), steel)
    for i in range(14):  # hanging tools
        x = -1.05 + i * 0.16
        kind = rnd.randrange(3)
        if kind == 0:
            mb.box((x - 0.02, -0.06, 1.3), (x + 0.02, -0.04, 1.95), metal)
            mb.box((x - 0.05, -0.065, 1.85), (x + 0.05, -0.04, 1.97), metal)
        elif kind == 1:
            mb.box((x - 0.035, -0.08, 1.45), (x + 0.035, -0.04, 1.9), m("stencil_red"))
            mb.box((x - 0.012, -0.07, 1.25), (x + 0.012, -0.05, 1.45), metal)
        else:
            mb.tube((x, -0.06, 1.5), (x, -0.06, 1.95), 0.018, steel, 8)
    with G.xf(mb, G.T(0.8, -0.12, 1.35) @ G.Rx(90.0)):  # cable coil
        G.lathe(
            mb,
            [
                (0.18 + 0.04 * math.cos(t), 0.04 * math.sin(t))
                for t in (2 * math.pi * i / 6 for i in range(6))
            ],
            m("rubber"),
            24,
            closed=True,
        )
    for x, w in ((-0.9, 0.5), (-0.3, 0.45), (0.3, 0.6)):  # cases on the shelf
        G.chamfer_box(
            mb,
            (x - w / 2, -0.4, 0.6),
            (x + w / 2, -0.08, 0.6 + 0.25),
            0.03,
            m(rnd.choice(("container_charcoal", "container_olive", "stencil_red"))),
        )
    for x in (0.85, 1.05):  # gas cylinders
        G.tube_z(mb, 0.11, 0.08, 1.4, m("container_grey"), 20, x=x, y=-0.25)
        with G.xf(mb, G.T(x, -0.25, 0.0)):
            G.lathe(
                mb, [(0.11, 1.4), (0.07, 1.48), (0.03, 1.52), (0.0, 1.52)], m("container_grey"), 20
            )
        G.tube_z(mb, 0.035, 1.4, 1.56, metal, 10, x=x, y=-0.25)
    mb.box((0.7, -0.4, 0.95), (1.2, -0.37, 1.0), steel)  # cylinder chain bar
    mb.build("SM_toolrack_body", bevel_width=0.004)
    K.occluder(((-1.24, -0.45, 0.0), (1.24, 0.0, 2.3)), nav="block")


def build_drone_dock():
    """Utility drone charging dock: floor pad, mast with arm, status panel."""
    mb, lamps = K.MeshBuilder(), K.MeshBuilder()
    metal, steel = m("gunmetal"), m("dark_steel")
    G.lathe(mb, [(0.0, 0.0), (0.75, 0.0), (0.75, 0.04), (0.7, 0.06), (0.0, 0.06)], steel, 48)
    G.annulus(lamps, 0.6, 0.64, 0.061, m("lamp_green"), 48)
    G.chamfer_box(mb, (-0.35, 0.55, 0.0), (0.35, 0.95, 1.6), 0.08, m("panel_dark"))
    mb.box((-0.25, 0.53, 1.0), (0.25, 0.55, 1.35), m("screen_dim"))
    G.beam(mb, (0.0, 0.6, 1.3), (0.0, 0.1, 0.9), 0.1, 0.1, metal)
    mb.tube((0.0, 0.1, 0.9), (0.0, 0.1, 0.7), 0.05, metal, 10)
    G.sweep(
        mb,
        G.catmull_rom(
            [(0.2, 0.6, 0.3), (0.35, 0.3, 0.05), (0.2, -0.2, 0.04), (0.0, -0.4, 0.04)], 6
        ),
        0.025,
        m("rubber"),
        8,
    )
    lamps.box((-0.2, 0.545, 1.45), (-0.1, 0.55, 1.5), m("lamp_amber"))
    mb.build("SM_dronedock_body", bevel_width=0.005)
    lamps.build("SM_dronedock_lamps", bevel_width=0.0, nav="none")
    K.socket("spawn", "drone", K.socket_matrix((0.0, 0.0, 0.06), (0, 0, 1), up=(0, 1, 0)))
    K.occluder(((-0.35, 0.55, 0.0), (0.35, 0.95, 1.6)), nav="block")


K.register_variant("SM_Eng_WarningPanel", build_warning_panel, dims=(1.2, 0.12, 3.05), nav="none")
K.register_variant("SM_Eng_ToolRack", build_tool_rack, dims=(2.48, 0.45, 2.3))
K.register_variant("SM_Eng_DroneDock", build_drone_dock, dims=(1.5, 1.7, 1.6))


# --------------------------------------------------------------------------
# Wall machinery (engineering hull wall, back at Y = 0)
# --------------------------------------------------------------------------


def _transformer(mb, lamps, decals, x, rnd):
    """Finned transformer housing with bushings on top and feeder conduits."""
    metal, steel = m("gunmetal"), m("dark_steel")
    G.chamfer_box(mb, (x - 1.5, -1.25, 0.0), (x + 1.5, -0.05, 0.25), 0.06, steel)
    mb.box((x - 1.4, -1.15, 0.25), (x + 1.4, -0.1, 3.4), m("panel_light"))
    for i in range(17):  # cooling fins on the front
        xx = x - 1.28 + i * 0.16
        mb.box((xx - 0.025, -1.42, 0.5), (xx + 0.025, -1.15, 3.0), metal)
    for i in range(3):  # bushings
        bx = x - 0.8 + i * 0.8
        with G.xf(mb, G.T(bx, -0.6, 3.4)):
            G.lathe(
                mb,
                [(0.16, 0.0)]
                + [(0.16 if k % 2 else 0.11, 0.08 * (k + 1)) for k in range(9)]
                + [(0.05, 0.8), (0.0, 0.8)],
                m("panel_light"),
                16,
            )
        mb.tube((bx, -0.6, 4.2), (bx, -0.2, 5.5), 0.05, metal, 10)
        mb.tube((bx, -0.2, 5.5), (bx, -0.2, 7.2), 0.05, metal, 10)
    lamps.box((x - 1.3, -1.43, 3.1), (x - 1.15, -1.42, 3.25), m("lamp_red"))
    lamps.box((x - 1.1, -1.43, 3.1), (x - 0.95, -1.42, 3.25), m("lamp_green"))
    G.text(
        decals,
        f"XFMR {rnd.randrange(1, 9)}  -  480 V / 11 KV",
        0.11,
        m("stencil_white"),
        G.on_face((x + 0.2, -1.425, 3.2), "-Y"),
    )


def _pump(mb, x, rnd):
    """Horizontal motor + pump on a skid with flanged pipework into the wall."""
    metal, steel = m("gunmetal"), m("dark_steel")
    G.chamfer_box(mb, (x - 1.1, -1.4, 0.0), (x + 1.1, -0.2, 0.2), 0.05, steel)
    mb.tube((x - 0.9, -0.8, 0.7), (x + 0.1, -0.8, 0.7), 0.42, m("panel_light"), 24)
    for i in range(10):
        xx = x - 0.85 + i * 0.1
        mb.tube((xx, -0.8, 0.7), (xx + 0.03, -0.8, 0.7), 0.46, metal, 24)
    with G.xf(mb, G.T(x + 0.55, -0.8, 0.7)):
        G.lathe(
            mb,
            [(0.0, -0.35), (0.4, -0.35), (0.45, -0.2), (0.45, 0.2), (0.4, 0.35), (0.0, 0.35)],
            metal,
            24,
        )
    G.sweep(
        mb,
        [
            (x + 0.55, -0.8, 1.1),
            (x + 0.55, -0.8, 1.6),
            (x + 0.55, -0.5, 2.0),
            (x + 0.55, -0.25, 2.0),
        ],
        0.15,
        metal,
        16,
    )
    mb.tube((x + 0.55, -0.25, 2.0), (x + 0.55, 0.0, 2.0), 0.22, steel, 16)
    mb.tube((x + 0.95, -0.8, 0.7), (x + 1.2, -0.8, 0.7), 0.15, metal, 16)
    G.sweep(
        mb,
        [
            (x + 1.2, -0.8, 0.7),
            (x + 1.5, -0.8, 0.7),
            (x + 1.6, -0.6, 1.2),
            (x + 1.6, -0.3, 4.0),
            (x + 1.6, -0.3, 7.2),
        ],
        0.14,
        metal,
        16,
    )


def _tanks(mb, lamps, decals, x, rnd):
    """Pair of vertical tanks with bands, manifold, valves and a ladder."""
    metal, steel = m("gunmetal"), m("dark_steel")
    for k, tx in enumerate((x - 0.85, x + 0.85)):
        G.tube_z(mb, 0.72, 0.3, 5.0, m("container_grey"), 32, x=tx, y=-0.85)
        with G.xf(mb, G.T(tx, -0.85, 5.0)):
            G.lathe(
                mb,
                [(0.72, 0.0), (0.65, 0.25), (0.45, 0.42), (0.15, 0.5), (0.0, 0.5)],
                m("container_grey"),
                32,
            )
        for z in (0.9, 2.4, 3.9):
            with G.xf(mb, G.T(tx, -0.85, 0.0)):
                G.ring(mb, 0.71, 0.76, z, z + 0.1, metal, 32)
        G.tube_z(mb, 0.78, 0.0, 0.3, steel, 32, x=tx, y=-0.85)
        G.text(decals, f"T-{k + 1}", 0.3, m("stencil_dark"), G.on_face((tx, -1.575, 3.2), "-Y"))
    mb.tube((x - 0.85, -0.85, 5.5), (x + 0.85, -0.85, 5.5), 0.1, metal, 12)
    mb.tube((x, -0.85, 5.5), (x, -0.85, 7.2), 0.12, metal, 12)
    for z in (1.6, 4.4):
        mb.tube((x - 0.15, -1.2, z), (x + 0.15, -1.2, z), 0.09, metal, 12)
        with G.xf(mb, G.T(x, -1.32, z) @ G.Rx(90.0)):
            G.ring(mb, 0.12, 0.15, -0.015, 0.015, m("stencil_red"), 20)
    for sx in (-0.2, 0.2):  # ladder between the tanks
        mb.box((x + sx - 0.025, -0.35, 0.0), (x + sx + 0.025, -0.3, 6.0), steel)
    for i in range(20):
        z = 0.3 + i * 0.28
        mb.tube((x - 0.2, -0.33, z), (x + 0.2, -0.33, z), 0.015, metal, 6)
    lamps.box((x - 0.06, -1.65, 2.5), (x + 0.06, -1.64, 2.62), m("lamp_amber"))


def _upper_section(mb, lamps, decals, height, rnd):
    """Upper hull-wall bay (7.2 m to ``height``): service gantry at 7.4 m,
    finned heat-exchanger stack, risers and dim red maintenance lights."""
    metal, steel = m("gunmetal"), m("dark_steel")
    mb.box((-2.4, -1.0, 7.3), (2.4, -0.1, 7.4), m("grating"))  # gantry deck
    mb.box((-2.4, -1.02, 7.4), (2.4, -0.98, 7.55), steel)  # toe board
    for x in (-1.8, 0.0, 1.8):
        G.beam(mb, (x, -0.1, 6.6), (x, -0.95, 7.3), 0.08, 0.08, steel)
    top = height - 1.2
    for k, x in enumerate((-1.3, 0.1, 1.5)):  # heat-exchanger columns
        G.chamfer_box(mb, (x - 0.5, -0.9, 7.6), (x + 0.5, -0.15, top), 0.08, m("panel_dark"))
        for i in range(int((top - 8.0) / 0.3)):
            z = 7.9 + i * 0.3
            mb.box((x - 0.46, -0.96, z), (x + 0.46, -0.9, z + 0.06), metal)
        G.text(
            decals, f"HX-{k + 1}", 0.16, m("stencil_white"), G.on_face((x, -0.97, top - 0.4), "-Y")
        )
    for x in (-2.0, 2.05):  # risers to the deckhead
        mb.tube((x, -0.3, 7.4), (x, -0.3, height), 0.12, metal, 14)
    mb.box((-2.4, -0.3, height - 0.25), (2.4, 0.0, height), steel)
    for x in (-1.8, 1.8):
        lamps.box((x - 0.1, -0.31, top + 0.4), (x + 0.1, -0.3, top + 0.5), m("lamp_maint_red"))


def build_wall_machinery(variant="A", height=7.2):
    """4.8 m bay of heavy hull-wall machinery (variant A: transformer+pump,
    B: tank pair), back plate at Y = 0. ``height`` > 7.2 adds an upper
    section (service gantry, heat exchangers, risers) up to the deckhead."""
    rnd = G.rng("wallmach", variant)
    mb, lamps, decals = K.MeshBuilder(), K.MeshBuilder(), K.MeshBuilder()
    dark, steel = m("panel_dark"), m("dark_steel")
    mb.box((-2.4, -0.1, 0.0), (2.4, 0.0, height), dark)
    for x in (-2.4, 2.4):
        mb.box((x - 0.2, -0.35, 0.0), (x + 0.2, 0.0, height), steel)
    for z in (3.6, 7.0):
        mb.box((-2.4, -0.3, z - 0.2), (2.4, 0.0, z), steel)
    if variant == "A":
        _transformer(mb, lamps, decals, -0.75, rnd)
        _pump(mb, 1.0, rnd)
    else:
        _tanks(mb, lamps, decals, 0.0, rnd)
    for i in range(int(4.8 / 0.6)):  # cable tray across the top
        x = -2.4 + 0.3 + i * 0.6
        mb.box((x - 0.02, -0.75, 6.2), (x + 0.02, -0.1, 6.25), steel)
    for i in range(5):
        mb.tube((-2.4, -0.2 - i * 0.11, 6.3), (2.4, -0.2 - i * 0.11, 6.3), 0.04, m("rubber"), 8)
    lamps.box((-2.1, -0.36, 6.8), (2.1, -0.35, 6.86), m("lamp_dim"))
    if height > 8.0:
        _upper_section(mb, lamps, decals, height, rnd)
    mb.build("SM_wallmach_body", bevel_width=0.008)
    lamps.build("SM_wallmach_lamps", bevel_width=0.0, nav="none")
    decals.build("SM_wallmach_decals", bevel_width=0.0, nav="none")
    K.occluder(((-2.6, -1.6, 0.0), (2.6, 0.0, height)), nav="block")


K.register_variant(
    "SM_Eng_WallMachinery_A_12", build_wall_machinery, dims=(5.2, 1.6, 12.0), height=12.0
)
K.register_variant(
    "SM_Eng_WallMachinery_B_12",
    build_wall_machinery,
    dims=(5.2, 1.6, 12.0),
    variant="B",
    height=12.0,
)
K.register_variant("SM_Eng_PowerConduit_480", build_power_conduit, dims=(1.2, 1.2, 4.8), height=4.8)


def build_valve_cluster():
    """Valve cluster on a plinth: three risers, a header, valve wheels, gauges."""
    mb, lamps = K.MeshBuilder(), K.MeshBuilder()
    metal, steel = m("gunmetal"), m("dark_steel")
    G.chamfer_box(mb, (-0.6, -0.4, 0.0), (0.6, 0.4, 0.15), 0.05, steel)
    for i, x in enumerate((-0.35, 0.0, 0.35)):
        mb.tube((x, 0.05, 0.15), (x, 0.05, 1.45), 0.07, metal, 14)
        mb.tube((x, 0.05, 0.7), (x, 0.05, 0.82), 0.1, steel, 14)
        mb.tube((x, 0.05, 0.76), (x, -0.2, 0.76), 0.025, metal, 8)
        with G.xf(mb, G.T(x, -0.22, 0.76) @ G.Rx(90.0)):
            G.ring(
                mb, 0.09, 0.115, -0.015, 0.015, m("stencil_red" if i == 1 else "stencil_amber"), 20
            )
    mb.tube((-0.55, 0.05, 1.45), (0.55, 0.05, 1.45), 0.1, metal, 16)
    mb.tube((0.55, 0.05, 1.45), (0.55, 0.4, 1.45), 0.1, metal, 16)
    for x in (-0.18, 0.18):  # gauges
        with G.xf(mb, G.T(x, -0.02, 1.15) @ G.Rx(90.0)):
            G.lathe(
                mb, [(0.0, 0.0), (0.07, 0.0), (0.07, 0.04), (0.0, 0.04)], steel, 16, closed=True
            )
    mb.build("SM_valvecluster_body", bevel_width=0.004)
    lamps.box((0.45, -0.41, 0.08), (0.53, -0.4, 0.12), m("lamp_green"))
    lamps.build("SM_valvecluster_lamps", bevel_width=0.0, nav="none")
    K.occluder(((-0.6, -0.4, 0.0), (0.66, 0.5, 1.56)), nav="block")


def build_chase_pipes(length=2.4):
    """Service-chase pipe run along X for 2 m chases seen from above: five
    pipes on low frames (top 1.05 m) plus a cable tray, all below the 1.1 m cut."""
    rnd = G.rng("chase", length)
    mb = K.MeshBuilder()
    metal, steel = m("gunmetal"), m("dark_steel")
    hl = length / 2
    pipes = (
        (-0.65, 0.35, 0.09),
        (-0.35, 0.35, 0.09),
        (0.0, 0.55, 0.16),
        (0.4, 0.3, 0.07),
        (0.62, 0.85, 0.11),
    )
    for y, z, r in pipes:
        mat = m("insulation") if r > 0.15 else metal
        mb.tube((-hl, y, z), (hl, y, z), r, mat, 16, caps=False)
        mb.tube((-0.05, y, z), (0.05, y, z), r + 0.03, steel, 16)
    for x in (-hl + 0.3, hl - 0.3):
        mb.box((x - 0.04, -0.85, 0.0), (x + 0.04, 0.85, 0.05), steel)
        for y in (-0.85, 0.85):
            mb.box((x - 0.04, y - 0.04, 0.05), (x + 0.04, y + 0.04, 0.95), steel)
        mb.box((x - 0.04, -0.85, 0.95), (x + 0.04, 0.85, 0.99), steel)
    for i in range(int(length / 0.3)):  # cable tray on top of the frames
        x = -hl + 0.15 + i * 0.3
        mb.box((x - 0.012, -0.8, 0.99), (x + 0.012, -0.2, 1.01), metal)
    for i in range(4):
        mb.tube(
            (-hl, -0.72 + i * 0.13, 1.03),
            (hl, -0.72 + i * 0.13 + rnd.uniform(-0.01, 0.01), 1.03),
            0.025,
            m("rubber"),
            8,
        )
    mb.build("SM_chasepipes_body", bevel_width=0.004)
    K.occluder(((-hl, -0.9, 0.0), (hl, 0.9, 1.06)), nav="block")


K.register_variant("SM_Eng_ValveCluster", build_valve_cluster, dims=(1.2, 0.9, 1.56))
K.register_variant("SM_Eng_ChasePipes", build_chase_pipes, dims=(2.4, 1.8, 1.06))


K.register_variant("SM_Eng_WallMachinery_A", build_wall_machinery, dims=(5.2, 1.6, 7.2))
K.register_variant(
    "SM_Eng_WallMachinery_B", build_wall_machinery, dims=(5.2, 1.6, 7.2), variant="B"
)


# --------------------------------------------------------------------------
# Lookdev
# --------------------------------------------------------------------------

LOOKDEV = {
    "SM_Eng_WallMachinery_A": {"focus": (-0.75, -1.3, 3.0), "crop_size": (3.0, 1.9)},
    "SM_Eng_WallMachinery_B": {"focus": (0.0, -1.5, 3.0), "crop_size": (3.0, 1.9)},
    "SM_Eng_PowerConduit": {"focus": (0.0, -0.5, 3.4), "crop_size": (2.2, 1.4)},
}


def dress_reactor_vignette(collection, half):
    """A few engineering props around the shaft collar for context."""
    with K.into(collection):
        for i, x in enumerate((-half - 1.2, half + 1.2)):
            for j, y in enumerate((-6.0, 0.0, 6.0)):
                name = "SM_Eng_PowerConduit_Triple" if j == 1 else "SM_Eng_PowerConduit"
                K.place(name, (x, y, 0.0), 90.0, room="reactor", id=f"LD_cond_{i}_{j}")
        K.place("SM_Eng_CoolantPipes", (-6.0, -half - 1.6, 0.0), room="reactor", id="LD_cool_a")
        K.place("SM_Eng_CoolantPipes", (6.0, -half - 1.6, 0.0), room="reactor", id="LD_cool_b")
