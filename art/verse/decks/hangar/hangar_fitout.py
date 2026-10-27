"""Fit-out of the Main Hangar: the working clutter of a military flight deck.

On top of the shuttle, cargo rows, stores and ground vehicles
(hangar_props.py) the deck gets what a flight deck works with:

* parts racks (kit storage racks) and tool racks along the side walls, a
  fuel manifold (kit valve cluster) with a pump skid in the far corners;
* a refuelling rig beside the pad's starboard hydrant, with its boom, hose
  reel and a hose to the deck, and a grated fuel trench from the hydrant;
* ordnance carts with racked munitions canisters, a cargo cart, a mobile
  lifting rig with an engine module on its hoist;
* deck-crew stations (console podiums with beacons) facing the blast doors
  and the pad, case stacks between the hero wall's piers;
* flush drain grilles and hatches, guide lights to the pad and along the
  cargo aisles, hazard paint on the launch well's kerb, and a reporting point
  with bollards in front of the arrivals desk.

Floor props stand on the plate (``Props``, nav ``block``) only where the
patrol loops, the walkway, the formation fields, sockets and stations leave
the floor free; lanes stay at least a body width wide (checked against the
nav grid after the cook). Grilles, hatches, lights and paint are flush
inlays (nav ``none``).
"""

from __future__ import annotations

import hangar_arch as A
import hangar_layout as L
from hangar_cladding import HAZARD
from kit.architecture import cladding as C
from kit.props import fitout as F
from lib import kit, scene

PALETTE_CAN = ("M_Crate_Paint", "M_Wall_PaintedDark")

# Kit pieces: (piece, plan x, plan z, yaw). Yaw 90 faces +x (west wall),
# -90 faces -x (east wall); the racks' backs sit on the wall plane.
KIT = (
    ("SM_Hangar_StorageRack", L.SIDE_T, 13.15, 90.0),
    ("SM_Hangar_StorageRack", L.SIDE_T, 18.85, 90.0),
    ("SM_Hangar_StorageRack", L.WIDTH - L.SIDE_T, 10.8, -90.0),
    ("SM_Hangar_StorageRack", L.WIDTH - L.SIDE_T, 16.4, -90.0),
    ("SM_Eng_ToolRack", L.SIDE_T, 31.0, 90.0),
    ("SM_Eng_ToolRack", L.SIDE_T, 37.0, 90.0),
    ("SM_Eng_ToolRack", L.WIDTH - L.SIDE_T, 38.6, -90.0),
    ("SM_Eng_ToolRack", L.WIDTH - L.SIDE_T, 41.3, -90.0),
    ("SM_Eng_ValveCluster", L.SIDE_T + 0.45, 4.4, 90.0),
    ("SM_Eng_ValveCluster", L.WIDTH - L.SIDE_T - 0.45, 4.4, -90.0),
)

# Freestanding props: (kind, plan x, plan z, yaw, room).
PROPS = (
    # The column between the pad and the cargo rows keeps the cargo patrol's
    # lane at plan x 66 clear (everything ends by x 65.6).
    ("refuel", 64.2, 29.0, 0.0, "flight_deck"),
    ("ordnance", 64.0, 13.0, 180.0, "flight_deck"),
    ("ordnance", 64.0, 16.4, 180.0, "flight_deck"),
    ("cargo", 64.0, 20.4, 90.0, "flight_deck"),
    ("ordnance", 35.6, 48.6, 0.0, "crew_bay"),
    ("lift", 63.8, 39.6, 0.0, "flight_deck"),
    ("station", 42.0, 8.2, 0.0, "flight_deck"),
    ("station", 58.0, 8.2, 0.0, "flight_deck"),
    ("station", 64.9, 8.8, 90.0, "flight_deck"),
    ("skid", 3.5, 7.4, 90.0, "flight_deck"),
    ("skid", 96.5, 7.4, -90.0, "flight_deck"),
)

# Wall runs on the near hull wall: room -> [(kind, x0, x1)].
BAND_RUNS = {
    "arrivals": [
        ("rack", 41.4, 44.4),
        ("cabinet", 44.8, 47.2),
        ("rack", 55.0, 58.0),
        ("cabinet", 58.4, 60.6),
    ],  # fmt: skip
    "lift_lobby": [("rack", 62.6, 65.0), ("cabinet", 74.4, 76.6)],
}

# Case stacks between the hero wall's piers (clear of the wall patrol at z 5.4).
STACKS = (8.2, 11.0, 15.6, 18.4, 81.8, 84.6, 89.0, 91.8)
STACK_Z = 4.0

# Flush floor inlays: (kind, x0, x1, z0, z1).
FLOOR = (
    *(("grille", x - 0.6, x + 0.6, 22.7, 23.3) for x in (12.0, 19.2, 26.4, 33.6)),
    *(("grille", x - 0.6, x + 0.6, 44.0, 44.6) for x in (10.0, 20.0, 30.0, 44.0, 56.0, 88.0)),
    ("grille", 41.4, 42.6, 18.7, 19.3),
    ("grille", 57.4, 58.6, 18.7, 19.3),
    ("grille", 41.4, 42.6, 28.2, 28.8),
    ("hatch", 44.4, 45.6, 3.7, 4.9),
    ("hatch", 54.4, 55.6, 3.7, 4.9),
    ("hatch", 22.4, 23.6, 44.0, 45.2),
    ("hatch", 72.4, 73.6, 44.4, 45.6),
    ("trench", 60.3, 63.0, 27.35, 27.85),  # fuel trench, starboard hydrant to the rig
    ("trench", 34.4, 39.8, 27.35, 27.85),  # fuel trench, port hydrant
)
GUIDE_LIGHTS = (
    *((x, z) for x in (46.0, 54.0) for z in (7.4, 9.2, 11.0, 12.8, 14.6)),
    *((x, 8.0 + 4.8 * k) for x in (76.2, 84.7) for k in range(8)),
)


# ---------------------------------------------------------------- props


def ordnance_cart(B: C.Builders, seed) -> None:
    """Low munitions trolley: chassis on four wheels, three cradles holding
    two or three long canisters with coloured bands, a tow bar, hazard
    bumpers. Long axis along u, 2.5 x 1.26 m."""
    C.box(B.struct, -1.2, 1.2, -0.5, 0.5, 0.32, 0.42, C.GUNMETAL)
    for s in (-1, 1):
        C.box(B.struct, -1.2, 1.2, s * 0.5 - 0.04, s * 0.5 + 0.04, 0.26, 0.46, C.STEEL)
        C.box(B.flat, s * 1.2 - 0.05, s * 1.2 + 0.05, -0.5, 0.5, 0.28, 0.46, HAZARD)
    for wu in (-0.85, 0.85):
        for s in (-1, 1):
            B.pipes.tube((wu, s * 0.5, 0.2), (wu, s * 0.63, 0.2), 0.2, C.RUBBER, 16)
            B.pipes.tube((wu, s * 0.62, 0.2), (wu, s * 0.64, 0.2), 0.1, C.STEEL, 12)
    C.box(B.struct, 1.25, 1.9, -0.04, 0.04, 0.3, 0.36, C.STEEL)
    B.pipes.tube((1.95, 0.0, 0.25), (1.95, 0.0, 0.4), 0.08, C.STEEL, 12)
    for cu in (-0.8, 0.0, 0.8):
        C.box(B.struct, cu - 0.08, cu + 0.08, -0.46, 0.46, 0.42, 0.62, C.GUNMETAL)
    cans = [(-0.22, 0.75), (0.22, 0.75)]
    if C.seed01(seed, "top") < 0.6:
        cans.append((0.0, 1.07))
    for i, (cv, ch) in enumerate(cans):
        body = PALETTE_CAN[int(C.seed01(seed, "c", i) * 2)]
        B.pipes.tube((-1.05, cv, ch), (0.9, cv, ch), 0.17, body, 16)
        B.pipes.tube((0.9, cv, ch), (1.12, cv, ch), 0.12, body, 14)
        B.pipes.tube((1.12, cv, ch), (1.2, cv, ch), 0.06, C.STEEL, 10)
        B.pipes.tube((-0.62, cv, ch), (-0.54, cv, ch), 0.176, "M_Paint_TrimRed", 16)
        B.pipes.tube((0.52, cv, ch), (0.6, cv, ch), 0.176, HAZARD, 16)
        for fu in (-1.05, -0.95):  # tail fins
            C.box(B.flat, fu, fu + 0.04, cv - 0.24, cv + 0.24, ch - 0.01, ch + 0.01, C.GUNMETAL)


def cargo_cart(B: C.Builders, seed) -> None:
    """Flatbed cart with two hard cases strapped down."""
    C.box(B.struct, -1.2, 1.2, -0.55, 0.55, 0.36, 0.46, C.GUNMETAL)
    C.box(B.flat, -1.2, 1.2, -0.555, 0.555, 0.38, 0.44, HAZARD)
    for wu in (-0.85, 0.85):
        for s in (-1, 1):
            B.pipes.tube((wu, s * 0.48, 0.2), (wu, s * 0.6, 0.2), 0.2, C.RUBBER, 16)
    C.box(B.struct, 1.25, 1.9, -0.04, 0.04, 0.3, 0.36, C.STEEL)
    F.case(B, -0.55, 0.0, 0.46, 1.0, 0.9, 0.6, (seed, 0))
    F.case(B, 0.6, 0.0, 0.46, 0.9, 0.8, 0.45, (seed, 1), mat=C.DARK)
    for su in (-0.55, 0.6):
        C.box(B.flat, su - 0.03, su + 0.03, -0.47, 0.47, 0.46, 1.08 if su < 0 else 0.93, C.RUBBER)


def refuel_rig(B: C.Builders, seed) -> None:
    """Refuelling rig on a skid: two fuel tanks, a pump housing with a
    control panel, a hose reel, a mast with a boom reaching toward the pad
    (-u) and a hose dropping from it to the deck. 2.4 x 1.8 m footprint."""
    C.box(B.struct, -1.2, 1.2, -0.9, 0.9, 0.0, 0.15, C.GUNMETAL)
    for a, b, c, d in ((-1.2, 1.2, -0.9, -0.82), (-1.2, 1.2, 0.82, 0.9), (-1.2, -1.12, -0.9, 0.9),
                       (1.12, 1.2, -0.9, 0.9)):  # fmt: skip
        C.box(B.flat, a, b, c, d, 0.15, 0.17, HAZARD)
    for tv in (-0.42, 0.42):
        B.pipes.tube((-0.6, tv, 0.15), (-0.6, tv, 2.25), 0.38, "M_Crate_Paint", 24)
        B.pipes.tube((-0.6, tv, 2.25), (-0.6, tv, 2.38), 0.3, C.STEEL, 20)
        for hb in (0.6, 1.7):
            B.pipes.tube((-0.6, tv, hb), (-0.6, tv, hb + 0.06), 0.39, C.GUNMETAL, 24)
        B.pipes.tube((-0.6, tv, 1.15), (-0.6, tv, 1.3), 0.385, HAZARD, 24)
    C.box(B.panels, 0.1, 1.1, -0.7, 0.7, 0.15, 1.5, C.MID)
    C.box(B.struct, 0.08, 1.12, -0.72, 0.72, 1.5, 1.56, C.STEEL)
    for k in range(6):  # louvres on the pump's front
        hz = 0.35 + k * 0.12
        C.box(B.flat, 0.2, 1.0, 0.7, 0.73, hz, hz + 0.05, C.GUNMETAL)
    C.box(B.struct, 0.25, 0.95, 0.7, 0.76, 1.05, 1.42, C.BODY)
    C.box(B.lamps, 0.3, 0.7, 0.76, 0.764, 1.12, 1.36, C.SCREEN)
    for i, mat in enumerate(("M_Indicator_Green", "M_Indicator_Amber")):
        C.box(B.lamps, 0.78 + i * 0.07, 0.83 + i * 0.07, 0.76, 0.766, 1.3, 1.35, mat)
    B.pipes.tube((0.6, -0.72, 1.95), (0.6, 0.72, 1.95), 0.36, C.RUBBER, 24)  # hose reel
    for rv in (-0.74, 0.74):
        B.pipes.tube((0.6, rv - 0.02, 1.95), (0.6, rv + 0.02, 1.95), 0.44, C.STEEL, 24)
    C.box(B.struct, 0.5, 0.7, -0.78, -0.72, 1.56, 2.0, C.GUNMETAL)
    C.box(B.struct, 0.5, 0.7, 0.72, 0.78, 1.56, 2.0, C.GUNMETAL)
    C.box(B.struct, 0.95, 1.15, -0.12, 0.12, 0.15, 4.6, C.GUNMETAL)  # mast
    C.box(B.struct, -1.8, 1.15, -0.09, 0.09, 4.42, 4.6, C.STEEL)  # boom
    B.struct.prism_x([(-0.06, 4.42), (0.06, 4.42), (0.06, 3.7), (-0.06, 3.7)], 0.85, 0.95,
                     C.GUNMETAL)  # fmt: skip
    C.box(B.flat, -1.8, 0.9, -0.095, -0.09, 4.45, 4.57, HAZARD)
    B.pipes.tube((1.05, 0.0, 4.6), (1.05, 0.0, 4.78), 0.08, C.STEEL, 12)
    B.lamps.tube((1.05, 0.0, 4.78), (1.05, 0.0, 4.9), 0.07, "M_Indicator_Amber", 12)
    hose = [(-1.75, 0.0, 4.4), (-1.85, 0.05, 3.2), (-1.95, 0.1, 1.6), (-2.1, 0.2, 0.4),
            (-2.4, 0.35, 0.07), (-2.7, 0.55, 0.07)]  # fmt: skip
    B.pipes.polyline_tube(hose, 0.06, C.RUBBER, 10)
    B.pipes.tube((-2.7, 0.5, 0.07), (-2.7, 0.75, 0.07), 0.08, C.STEEL, 12)
    # Coupling to the fuel trench and a feed into the tanks.
    C.box(B.struct, -1.45, -1.2, -0.75, -0.45, 0.0, 0.25, C.GUNMETAL)
    B.pipes.tube((-1.32, -0.6, 0.25), (-1.32, -0.6, 0.9), 0.07, C.PIPE, 12)
    B.pipes.tube((-1.32, -0.6, 0.9), (-0.95, -0.5, 0.9), 0.07, C.PIPE, 12)
    B.pipes.tube((-1.32, -0.6, 0.55), (-1.32, -0.6, 0.62), 0.11, "M_Paint_TrimRed", 12)


def lift_rig(B: C.Builders, seed) -> None:
    """Mobile gantry hoist: two A-frame legs on castors, a hazard-striped
    I-beam, a chain hoist holding an engine module at work height."""
    for lu in (-1.5, 1.5):
        C.box(B.struct, lu - 0.1, lu + 0.1, -0.8, 0.8, 0.12, 0.24, C.GUNMETAL)
        for s in (-1, 1):
            B.pipes.tube((lu, s * 0.72, 0.24), (lu, 0.0, 3.7), 0.07, C.GUNMETAL, 12)
            B.pipes.tube((lu, s * 0.72, 0.0), (lu, s * 0.72, 0.12), 0.07, C.RUBBER, 12)
        B.pipes.tube((lu, -0.45, 1.2), (lu, 0.45, 1.2), 0.04, C.STEEL, 8)
    C.box(B.struct, -1.75, 1.75, -0.13, 0.13, 3.7, 3.76, C.STEEL)
    C.box(B.struct, -1.75, 1.75, -0.03, 0.03, 3.76, 4.0, HAZARD)
    C.box(B.struct, -1.75, 1.75, -0.13, 0.13, 4.0, 4.06, C.STEEL)
    C.box(B.struct, -0.25, 0.25, -0.16, 0.16, 3.25, 3.7, C.MID)
    B.pipes.tube((0.0, 0.0, 3.25), (0.0, 0.0, 2.05), 0.018, C.STEEL, 6)
    B.pipes.tube((0.08, 0.0, 3.25), (0.08, 0.0, 2.6), 0.012, C.STEEL, 6)  # control pendant
    C.box(B.struct, 0.04, 0.12, -0.04, 0.04, 2.45, 2.6, HAZARD)
    C.box(B.struct, -0.12, 0.12, -0.08, 0.08, 1.9, 2.05, C.GUNMETAL)
    for s in (-1, 1):  # slings to the module
        B.pipes.tube((0.0, 0.0, 1.9), (s * 0.6, 0.0, 1.62), 0.012, C.STEEL, 6)
    C.box(B.panels, -0.8, 0.8, -0.5, 0.5, 0.95, 1.6, C.DARK)
    B.pipes.tube((-0.8, 0.0, 1.27), (-1.05, 0.0, 1.27), 0.26, C.GUNMETAL, 20)
    B.pipes.tube((-1.05, 0.0, 1.27), (-1.12, 0.0, 1.27), 0.2, C.RECESS, 20)
    for k in range(4):
        u = -0.6 + k * 0.4
        B.pipes.tube((u, 0.5, 1.45), (u, 0.62, 1.45), 0.05, C.PIPE, 10)
    C.box(B.flat, -0.4, 0.2, 0.5, 0.503, 1.1, 1.2, C.WHITE_PAINT)


def crew_station(B: C.Builders, seed) -> None:
    """Deck-crew station: hazard-painted plinth, a console pedestal with a
    sloped key deck facing +v, a screen hood at the back and a beacon mast."""
    C.box(B.struct, -0.75, 0.75, -0.45, 0.45, 0.0, 0.1, HAZARD)
    C.box(B.panels, -0.6, 0.6, -0.35, 0.3, 0.1, 0.95, C.BODY)
    B.struct.prism_x([(-0.38, 0.95), (0.4, 0.95), (0.4, 1.0), (-0.38, 1.18)], -0.64, 0.64,
                     C.BODY)  # fmt: skip
    for i in range(8):
        k = -0.5 + i * 0.13
        C.box(B.flat, k, k + 0.09, 0.05, 0.25, 1.05, 1.08, C.KEYS)
    C.box(B.struct, -0.6, 0.6, -0.42, -0.3, 1.0, 1.6, C.BODY)
    C.box(B.lamps, -0.52, 0.52, -0.3, -0.296, 1.08, 1.52, C.SCREEN)
    B.pipes.tube((0.66, -0.36, 0.1), (0.66, -0.36, 2.1), 0.025, C.STEEL, 8)
    B.lamps.tube((0.66, -0.36, 2.1), (0.66, -0.36, 2.2), 0.05, "M_Indicator_Amber", 10)
    pip = "M_Indicator_Green" if C.seed01(seed, "p") < 0.6 else "M_Indicator_Amber"
    C.box(B.lamps, 0.45, 0.52, 0.3, 0.304, 0.8, 0.86, pip)


def pump_skid(B: C.Builders, seed) -> None:
    """Fuel pump skid by the manifold: base, two pump bodies with motors,
    piping to the wall and a riser to the fuel main overhead."""
    C.box(B.struct, -1.2, 1.2, -0.7, 0.7, 0.0, 0.15, C.GUNMETAL)
    C.box(B.flat, -1.2, 1.2, 0.7, 0.705, 0.02, 0.13, HAZARD)
    for pu in (-0.6, 0.6):
        B.pipes.tube((pu - 0.35, 0.0, 0.5), (pu + 0.35, 0.0, 0.5), 0.3, "M_Crate_Paint", 20)
        B.pipes.tube((pu + 0.35, 0.0, 0.5), (pu + 0.5, 0.0, 0.5), 0.2, C.GUNMETAL, 16)
        C.box(B.struct, pu - 0.3, pu + 0.3, -0.25, 0.25, 0.15, 0.3, C.GUNMETAL)
        B.pipes.tube((pu, 0.0, 0.8), (pu, 0.0, 1.3), 0.08, C.PIPE, 12)
        B.pipes.tube((pu, 0.0, 1.3), (pu, -0.7, 1.3), 0.08, C.PIPE, 12)
        B.pipes.tube((pu - 0.04, 0.0, 1.0), (pu + 0.04, 0.0, 1.0), 0.14, "M_Paint_TrimRed", 16)
    B.pipes.tube((-0.6, -0.7, 1.3), (0.6, -0.7, 1.3), 0.1, C.PIPE, 12)
    B.pipes.tube((0.0, -0.7, 1.3), (0.0, -0.7, 4.7), 0.1, C.PIPE_INS, 12)
    C.box(B.lamps, -1.0, -0.94, 0.7, 0.704, 0.08, 0.11, "M_Indicator_Green")


BUILDERS = {
    "refuel": refuel_rig,
    "ordnance": ordnance_cart,
    "cargo": cargo_cart,
    "lift": lift_rig,
    "station": crew_station,
    "skid": pump_skid,
}


# ---------------------------------------------------------------- placement


def _kit(pieces: dict) -> None:
    for i, (piece, x, z, yaw) in enumerate(KIT):
        if piece in pieces:
            kit.place(piece, L.B(x, z, 0.0), yaw, id=f"HangarFit_{i:02d}", room="flight_deck")


def _props() -> None:
    by_room: dict[str, C.Builders] = {}
    for i, (kind, x, z, yaw, room) in enumerate(PROPS):
        B = by_room.setdefault(room, C.Builders()).at(C.place_matrix(x, z, yaw))
        BUILDERS[kind](B, ("hangar-fit", i))
    for i, x in enumerate(STACKS):
        B = by_room.setdefault("flight_deck", C.Builders()).at(C.place_matrix(x, STACK_Z, 0.0))
        F.case_stack(B, 0.0, 0.0, ("hangar-stack", i))
    for room, B in by_room.items():
        B.finish(f"SM_Hangar_Fit_{room}", room=room, nav="block")
    # The tall rigs hide a character standing behind them.
    A.ucx("refuel_rig", 63.2, 65.4, 28.2, 29.8, 0.0, 2.4)


def _band_runs() -> None:
    """Equipment racks and service cabinets on the near hull wall of the
    arrivals hall and the lift lobby (clear of the wall terminals)."""
    for room, runs in BAND_RUNS.items():
        B = C.Builders().at(C.run_matrix("x", L.NEAR_WALL_Z[0], -1))
        for i, (kind, a, b) in enumerate(runs):
            seed = ("hangar-band", room, i)
            if kind == "rack":
                F.equipment_rack(B, a, b, seed=seed)
            else:
                F.low_cabinet(B, a, b, seed=seed)
        B.finish(f"SM_Hangar_FitBand_{room}", room=room, nav="block")


def _floor() -> None:
    B = C.Builders().at(C.place_matrix(0.0, 0.0, 0.0))  # u = plan x, v = plan z
    for kind, x0, x1, z0, z1 in FLOOR:
        if kind == "hatch":
            F.floor_hatch(B, x0, x1, z0, z1)
        else:
            F.floor_grille(B, x0, x1, z0, z1)
            if kind == "trench":  # the fuel main under the grating
                zc = (z0 + z1) / 2
                B.pipes.tube((x0 + 0.05, zc, -0.08), (x1 - 0.05, zc, -0.08), 0.07, C.PIPE, 10)
                C.box(B.flat, x0, x1, z0 - 0.06, z0, 0.0004, 0.005, HAZARD)
                C.box(B.flat, x0, x1, z1, z1 + 0.06, 0.0004, 0.005, HAZARD)
    # Hazard paint on the launch well's kerb.
    x0, x1, z0, z1 = L.WELL
    k, kh = 0.45, 0.22
    for a, b, c, d in ((x0 - k, x1 + k, z0 - k, z0), (x0 - k, x1 + k, z1, z1 + k),
                       (x0 - k, x0, z0, z1), (x1, x1 + k, z0, z1)):  # fmt: skip
        C.box(B.flat, a, b, c, d, kh, kh + 0.004, HAZARD)
    # Reporting point in front of the arrivals desk: a painted box round
    # the two report stands, steel bollards with amber caps either side.
    dx = L.DESK_C[0]
    zr = L.WALKWAY_Z[1] - 1.6
    rx0, rx1, rz0, rz1 = dx - 1.6, dx + 1.6, zr - 0.7, zr + 0.7
    for a, b, c, d in ((rx0, rx1, rz0, rz0 + 0.1), (rx0, rx1, rz1 - 0.1, rz1),
                       (rx0, rx0 + 0.1, rz0, rz1), (rx1 - 0.1, rx1, rz0, rz1)):  # fmt: skip
        C.box(B.flat, a, b, c, d, 0.0004, 0.004, HAZARD)
    B.finish("SM_Hangar_FitFloor", room="flight_deck", nav="none")
    posts = C.Builders().at(C.place_matrix(0.0, 0.0, 0.0))
    for x in (dx - 1.95, dx + 1.95):
        posts.struct.tube((x, zr, 0.0), (x, zr, 0.9), 0.12, HAZARD, 16)
        posts.struct.tube((x, zr, 0.0), (x, zr, 0.06), 0.16, C.STEEL, 16)
        posts.struct.tube((x, zr, 0.9), (x, zr, 0.95), 0.13, C.STEEL, 16)
        posts.lamps.tube((x, zr, 0.95), (x, zr, 1.02), 0.08, "M_Indicator_Amber", 12)
    posts.finish("SM_Hangar_ReportPosts", room="arrivals", nav="block")


def _guide_lights(pieces: dict) -> None:
    if "SM_Hangar_FloorLight" not in pieces:
        return
    for i, (x, z) in enumerate(GUIDE_LIGHTS):
        kit.place("SM_Hangar_FloorLight", L.B(x, z, 0.0), 0.0, id=f"GuideLight_{i:02d}",
                  room="flight_deck")  # fmt: skip


def build(pieces: dict) -> None:
    with kit.into(scene.collection("Props")):
        _kit(pieces)
        _props()
        _band_runs()
        _floor()
        _guide_lights(pieces)
