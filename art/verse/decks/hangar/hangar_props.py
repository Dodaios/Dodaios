"""Hangar dressing: shuttle, cargo, gantry, fuel lines, ground equipment, desks, racks.

Each element uses the shared kit piece when it is registered (props-industrial,
props-command) and falls back to a bespoke stand-in built here, so the deck
always cooks. Placement is purposeful: cargo stands in its painted slots, hoses
run from the hydrants to the shuttle, vehicles park where their tracks end.
"""

from __future__ import annotations

import importlib
import math

import bpy
import hangar_layout as L
from hangar_arch import PANEL, PANEL_MID, RECESS, RUBBER, STEEL, TRIM, box, ucx
from hangar_paint import cargo_row_centres, cargo_slots
from lib import kit, materials, naming, scene
from mathutils import Vector

B = L.B
CRATE = "M_Crate_Paint"
GLASS = "M_Glass_Viewport"

# Kit packages that register the pieces used here (imported when present).
KIT_MODULES = ("kit.props.industrial", "kit.props.command")


@materials.material("M_Hangar_ArmourWhite", viewport=(0.8, 0.8, 0.78))
def _armour_white(g) -> None:
    """Moulded white armour plastic: glossy, slightly scuffed."""
    co = g.coord()
    scuff = materials._scratches(g, co, contrast=(0.55, 0.85))
    cav = g.cavity(0.05)
    base = g.mix_color(g.mul(cav, 0.6), (0.72, 0.72, 0.7), (0.3, 0.3, 0.29))
    bsdf = g.principled(
        Base_Color=base,
        Roughness=g.add(0.22, g.mul(scuff, 0.2)),
        Coat_Weight=0.6,
        Coat_Roughness=0.08,
    )
    g.output(bsdf.outputs[0])


@materials.material("M_Hangar_SignBacklit", viewport=(1.0, 1.0, 1.0))
def _sign_backlit(g) -> None:
    """Backlit sign lettering, cool white."""
    materials._emitter(g, 4.0, kelvin=6500.0, falloff=0.02, sampling="NONE")


def load_kit() -> dict:
    for module in KIT_MODULES:
        try:
            importlib.import_module(module)
        except Exception as error:  # noqa: BLE001 - optional packages: report and go on
            print(f"[hangar] kit package {module} unavailable: {error}", flush=True)
    return kit.registry()


def _props():
    return kit.into(scene.collection("Props"))


def _build(mb, name, bevel=0.008, nav=None, **props):
    with _props():
        obj = mb.build(name, bevel_width=bevel, **props)
    if obj is not None and nav is not None:
        kit.tag(obj, nav=nav)
    return obj


def _place(name: str, x: float, z: float, h: float = 0.0, yaw: float = 0.0, **kw):
    """Place kit piece ``name`` at plan (x, z); yaw 0 = the piece's -Y faces the camera."""
    with _props():
        return kit.place(name, B(x, z, h), yaw, **kw)


def _adopt_socket(place_id: str, kind: str, local_id: str, new_id: str, **props) -> Vector:
    """Rename a piece-emitted socket to the deck's contract name; return its location."""
    old = bpy.data.objects.get(naming.socket_name(kind, f"{place_id}__{local_id}"))
    if old is None:
        raise RuntimeError(f"piece {place_id} emitted no {kind} socket {local_id!r}")
    old.name = naming.socket_name(kind, new_id)
    for key, value in props.items():
        old[key] = value
    return old.matrix_world.translation.copy()


# --------------------------------------------------------------------------
# Shuttle
# --------------------------------------------------------------------------


def shuttle(pieces: dict) -> Vector | None:
    """The arrival shuttle on pad 4; returns the ramp foot (Blender) if known."""
    cx, cz = L.SHUTTLE_C
    if "SM_Hangar_Shuttle" in pieces:
        if USE_LANDING_PAD and "SM_Hangar_LandingPad" in pieces:
            _place("SM_Hangar_LandingPad", cx, cz, id="Pad4", room="flight_deck")
        _place("SM_Hangar_Shuttle", cx, cz, id="Shuttle", room="flight_deck")
        _exhaust_grates(cx, cz)
        foot = _adopt_socket("Shuttle", "spawn", "arrival", "arrival", room="flight_deck")
        _adopt_socket("Shuttle", "waypoint", "ramp_top", "ramp_top", room="flight_deck")
        _adopt_socket("Shuttle", "light", "cabin", "shuttle_cabin", room="flight_deck")
        return foot
    _shuttle_placeholder(cx, cz)
    return None


def _exhaust_grates(cx: float, cz: float) -> None:
    """Flush blast grates behind the engine nacelles, either side of the ramp."""
    grate = kit.MeshBuilder()
    frame = kit.MeshBuilder()
    z0, z1 = cz + 10.0, cz + 13.6
    for gx0, gx1 in ((cx - 5.6, cx - 2.2), (cx + 2.2, cx + 5.6)):
        box(grate, gx0, gx1, z0, z1, -0.02, 0.004, "M_Floor_Grating")
        box(frame, gx0 - 0.08, gx1 + 0.08, z0 - 0.08, z0, -0.02, 0.008, STEEL)
        box(frame, gx0 - 0.08, gx1 + 0.08, z1, z1 + 0.08, -0.02, 0.008, STEEL)
        box(frame, gx0 - 0.08, gx0, z0, z1, -0.02, 0.008, STEEL)
        box(frame, gx1, gx1 + 0.08, z0, z1, -0.02, 0.008, STEEL)
    _build(grate, "SM_Hangar_BlastGrates", bevel=0.0, nav="none")
    _build(frame, "SM_Hangar_BlastGrateFrames", bevel=0.003, nav="none")


def _shuttle_placeholder(cx: float, cz: float) -> None:
    hull = kit.MeshBuilder()
    trim = kit.MeshBuilder()

    def plan_poly(points):
        return [(x, -z) for x, z in points]

    lower = [
        (cx - 2.6, cz - 10.3),
        (cx + 2.6, cz - 10.3),
        (cx + 2.6, cz + 7.2),
        (cx + 2.25, cz + 9.6),
        (cx - 2.25, cz + 9.6),
        (cx - 2.6, cz + 7.2),
    ]
    hull.prism_z(plan_poly(lower), 1.4, 5.0, PANEL)
    for sx in (-1, 1):
        hull.prism_x(
            [(-(cz - 5.0), 5.0), (-(cz + 6.0), 5.0), (-(cz + 4.0), 9.0), (-(cz - 1.0), 9.0)],
            cx + sx * 1.0 - 0.2,
            cx + sx * 1.0 + 0.2,
            PANEL,
        )
    for gx, gz in ((cx - 2.0, cz + 5.0), (cx + 2.0, cz + 5.0), (cx, cz - 6.0)):
        trim.tube(B(gx, gz, 0.0), B(gx, gz, 1.4), 0.16, TRIM, 12)
    _build(hull, "SM_HangarPH_ShuttleHull", bevel=0.03, room="flight_deck")
    _build(trim, "SM_HangarPH_ShuttleTrim", bevel=0.0)
    ramp = kit.MeshBuilder()
    rz0, rz1 = cz + 9.6, L.RAMP_FOOT[1] - 0.8
    ramp.prism_x(
        [(-rz0, 1.5), (-rz0, 1.35), (-rz1, -0.02), (-rz1 - 0.01, 0.02)], cx - 0.9, cx + 0.9, STEEL
    )
    _build(ramp, "SM_HangarPH_ShuttleRamp", bevel=0.01, nav="walk", room="flight_deck")
    ucx("shuttle_body", cx - 2.6, cx + 2.6, cz - 10.3, cz + 9.6, 1.4, 9.0)
    scene.add_socket("spawn", "arrival", B(*L.RAMP_FOOT), 0.0, room="flight_deck")


# --------------------------------------------------------------------------
# Cargo: containers in painted slots, portal gantry over them
# --------------------------------------------------------------------------

CONTAINER_L = (
    "SM_Hangar_Container_L_Charcoal",
    "SM_Hangar_Container_L_Grey",
    "SM_Hangar_Container_L_Olive",
)


def _stack_plan() -> list[tuple[int, int, int]]:
    """(row, slot, height) of every container stack: ordered, mostly full, some gaps."""
    bits = kit.seed_for("hangar-cargo")
    plan = []
    for row in range(len(cargo_row_centres())):
        for slot in range(len(cargo_slots())):
            b = (bits >> ((row * 5 + slot) % 31)) & 3
            if b == 0 and (row + slot) % 3 == 1:
                height = 0
            elif b == 3 or (row in (1, 4) and slot in (0, 1)):
                height = 2
            else:
                height = 1
            plan.append((row, slot, height))
    return plan


def cargo(pieces: dict) -> None:
    rows = cargo_row_centres()
    slots = cargo_slots()
    use_kit = all(name in pieces for name in CONTAINER_L)
    shell = kit.MeshBuilder()
    for row, slot, height in _stack_plan():
        cx = rows[row]
        z0, z1 = slots[slot]
        cz = (z0 + z1) / 2
        for level in range(height):
            h0 = level * 2.6
            if use_kit:
                # Long axis along the deck, door end toward the camera.
                name = CONTAINER_L[(row * 3 + slot * 2 + level) % 3 if (row + slot) % 4 else 0]
                _place(name, cx, cz, h0, -90.0, room="flight_deck")
                continue
            box(shell, cx - 1.2, cx + 1.2, cz - 3.0, cz + 3.0, h0, h0 + 2.6, CRATE)
        if height and not use_kit:
            ucx(f"cargo_{row}_{slot}", cx - 1.2, cx + 1.2, cz - 3.0, cz + 3.0, 0.0, height * 2.6)
    if not use_kit:
        _build(shell, "SM_HangarPH_Containers", bevel=0.02, room="flight_deck")
    # Smaller cases and crate stacks at the aisle heads, ready to move.
    if "SM_Hangar_Container_M_Gunmetal" in pieces:
        for x, z, name, yaw in (
            (76.0, 41.6, "SM_Hangar_Container_M_Gunmetal", 0.0),
            (84.4, 8.6, "SM_Hangar_Container_M_Charcoal", -90.0),
            (94.8, 30.0, "SM_Hangar_Container_S_Grey", -90.0),
            (94.8, 33.0, "SM_Hangar_Container_S_Charcoal", -90.0),
            (94.8, 26.4, "SM_Hangar_CrateStack", -90.0),
        ):
            if name in pieces:
                _place(name, x, z, 0.0, yaw, room="flight_deck")
    gantry(pieces)


def gantry(pieces: dict) -> None:
    xw, xe = L.GANTRY_RAILS_X
    zc = L.GANTRY_Z
    rails = kit.MeshBuilder()
    for x in (xw, xe):
        box(rails, x - 0.25, x + 0.25, 4.2, 44.4, 0.0, 0.04, STEEL)
        box(rails, x - 0.05, x + 0.05, 4.2, 44.4, 0.04, 0.1, TRIM)
        for z in (4.4, 44.2):
            box(rails, x - 0.3, x + 0.3, z - 0.2, z + 0.2, 0.0, 0.35, "M_Deck_Hazard")
    _build(rails, "SM_Hangar_GantryFloorRails", bevel=0.004, nav="none")
    if "SM_Hangar_GantryColumn" in pieces and "SM_Hangar_GantryBridge" in pieces:
        for x in (xw, xe):
            _place("SM_Hangar_GantryColumn", x, zc, room="flight_deck")
        _place("SM_Hangar_GantryBridge", (xw + xe) / 2, zc, room="flight_deck")
        return
    mb = kit.MeshBuilder()
    top = 12.0
    for x in (xw, xe):
        box(mb, x - 0.6, x + 0.6, zc - 0.6, zc + 0.6, 0.0, top, PANEL_MID)
    box(mb, xw - 0.5, xe + 0.5, zc - 0.5, zc + 0.5, top, top + 1.4, PANEL)
    _build(mb, "SM_HangarPH_Gantry", bevel=0.02, room="flight_deck")
    for x in (xw, xe):
        ucx(f"gantry_leg_{int(x)}", x - 0.6, x + 0.6, zc - 0.6, zc + 0.6, 0.0, top)


# --------------------------------------------------------------------------
# Fuel lines, ground equipment, stores
# --------------------------------------------------------------------------


# The kit landing pad (plated disc with its own edge lights); when off, the
# painted ring and a ring of deck lamps mark the pad instead.
USE_LANDING_PAD = True

# Starboard fuel intake of the shuttle piece (piece-local, coupling toward +X).
SHUTTLE_INTAKE = (3.28, -5.5, 1.8)


def fuel_lines(pieces: dict) -> None:
    if "SM_Hangar_FuelHydrant" in pieces:
        _fuel_service(pieces)
        return
    cx, cz = L.PAD_C
    mb = kit.MeshBuilder()
    hose = kit.MeshBuilder()
    for sx in (-1, 1):
        hx, hz = cx + sx * 9.6, 27.6
        if "SM_Hangar_FuelPort" in pieces:
            _place("SM_Hangar_FuelPort", hx, hz, room="flight_deck")
        else:
            box(mb, hx - 0.45, hx + 0.45, hz - 0.35, hz + 0.35, 0.0, 0.55, STEEL)
        # Hose: across the deck in a lazy curve, then up to the intake on the hull.
        ix = cx + sx * 2.7
        iz = cz + 1.2
        pts = [
            B(hx + 0.15, hz - 0.1, 0.35),
            B(hx - sx * 0.9, hz + 0.5, 0.09),
            B(hx - sx * 3.2, hz + 0.9, 0.09),
            B(hx - sx * 5.2, hz - 0.6, 0.09),
            B(ix + sx * 0.9, iz + 0.6, 0.09),
            B(ix + sx * 0.25, iz + 0.2, 0.8),
            B(ix + sx * 0.05, iz, 1.7),
        ]
        hose.polyline_tube(_smooth(pts, 6), 0.085, RUBBER, 10)
        for t in (0.3, 0.62):
            p = _lerp_path(pts, t)
            hose.tube((p[0], p[1] - 0.12, 0.09), (p[0], p[1] + 0.12, 0.09), 0.11, TRIM, 12)
    if not mb.is_empty():
        _build(mb, "SM_Hangar_FuelHydrants", bevel=0.006, room="flight_deck")
    else:
        mb.bm.free()
    _build(hose, "SM_Hangar_FuelHoses", bevel=0.0, nav="none")


def _fuel_service(pieces: dict) -> None:
    """Starboard hydrant fuelling the shuttle; the port hydrant has a cart standing by."""
    from kit.props.industrial.hangar_service import build_hose

    cx, cz = L.SHUTTLE_C
    hz = 27.6
    for sx in (-1, 1):
        _place("SM_Hangar_FuelHydrant", cx + sx * 9.6, hz, room="flight_deck")
    ix, iy, ih = SHUTTLE_INTAKE
    intake = (cx + ix, -(cz - iy))  # Blender XY of the intake
    hx = cx + 9.6
    points = [
        (hx - 0.55, -hz, 0.45),
        (hx - 1.6, -(hz + 0.5)),
        (hx - 3.4, -(hz + 0.3)),
        (intake[0] + 1.6, intake[1] - 0.4),
        (intake[0] + 0.5, intake[1], 0.7),
        (intake[0] + 0.15, intake[1], ih),
    ]
    with _props():
        build_hose("SM_Hangar_FuelHose_Stbd", points, radius=0.075, room="flight_deck")
    if "SM_Hangar_FuelCart" in pieces:
        _place("SM_Hangar_FuelCart", cx - 9.6, hz + 2.4, 0.0, 0.0, room="flight_deck")
    if "SM_Hangar_ToolCart" in pieces:
        _place("SM_Hangar_ToolCart", cx + 6.4, cz + 9.0, 0.0, 20.0, room="flight_deck")


def _lerp_path(points, t):
    i = min(int(t * (len(points) - 1)), len(points) - 2)
    f = t * (len(points) - 1) - i
    a, b = Vector(points[i]), Vector(points[i + 1])
    return tuple(a.lerp(b, f))


def _smooth(points, samples):
    """Catmull-Rom through Blender-space points."""
    pts = [Vector(p) for p in points]
    out = []
    for i in range(len(pts) - 1):
        p0 = pts[max(i - 1, 0)]
        p1, p2 = pts[i], pts[i + 1]
        p3 = pts[min(i + 2, len(pts) - 1)]
        for s in range(samples):
            t = s / samples
            t2, t3 = t * t, t * t * t
            out.append(
                0.5
                * (
                    (2 * p1)
                    + (-p0 + p2) * t
                    + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2
                    + (-p0 + 3 * p1 - 3 * p2 + p3) * t3
                )
            )
    out.append(pts[-1])
    return [tuple(p) for p in out]


def ground_equipment(pieces: dict) -> None:
    mb = kit.MeshBuilder()
    det = kit.MeshBuilder()
    # Tow tug parked at the end of its tracks beside the pad, nose to the shuttle.
    if "SM_Hangar_TowTug" in pieces:
        _place("SM_Hangar_TowTug", 37.4, 31.2, 0.0, 60.0, room="flight_deck")
        _place("SM_Hangar_TowTug", 38.0, 54.0, 0.0, 90.0, room="crew_bay")
    # Fuel bowser parked in the crew bay.
    bx, bz = 31.4, 53.6
    box(mb, bx - 1.25, bx + 1.25, bz - 3.6, bz + 3.6, 0.35, 1.0, STEEL)
    box(mb, bx - 1.2, bx + 1.2, bz + 1.6, bz + 3.5, 1.0, 2.6, PANEL)
    box(det, bx - 1.15, bx + 1.15, bz + 3.5, bz + 3.52, 1.8, 2.3, GLASS)
    det.tube(B(bx, bz - 3.2, 1.9), B(bx, bz + 1.4, 1.9), 1.1, PANEL_MID, 24)
    for wz in (bz - 2.6, bz + 2.4):
        for wx in (bx - 1.3, bx + 1.16):
            det.tube(B(wx, wz, 0.4), B(wx + 0.14, wz, 0.4), 0.4, RUBBER, 16)
    for k in range(5):
        hz = bz - 2.6 + k * 0.9
        box(det, bx - 1.12, bx + 1.12, hz - 0.03, hz + 0.03, 1.9, 3.02, STEEL)
    box(det, bx - 0.9, bx + 0.9, bz + 3.52, bz + 3.54, 0.5, 0.8, "M_Deck_Hazard")
    ucx("bowser", bx - 1.3, bx + 1.3, bz - 3.7, bz + 3.7, 0.0, 3.0)
    # Tool chests and a work bench along the crew bay's near wall.
    for i, x in enumerate((26.6, 28.0, 36.4, 37.8)):
        box(mb, x - 0.6, x + 0.6, 59.8, 60.6, 0.0, 1.05 + 0.1 * (i % 2), PANEL_MID)
        for d in range(4):
            box(det, x - 0.55, x + 0.55, 59.74, 59.8, 0.15 + d * 0.24, 0.33 + d * 0.24, STEEL)
    box(mb, 34.6, 39.0, 57.6, 58.4, 0.9, 0.98, STEEL)
    for x in (34.8, 38.8):
        box(mb, x - 0.05, x + 0.05, 57.7, 58.3, 0.0, 0.9, STEEL)
    ucx("crew_chests", 26.0, 38.4, 59.8, 60.6, 0.0, 1.15)
    _build(mb, "SM_Hangar_GroundEquipment", bevel=0.012)
    _build(det, "SM_Hangar_GroundEquipmentDetail", bevel=0.004)


def stores(pieces: dict) -> None:
    x0, _, z0, _ = L.STORES
    loaded = "SM_Hangar_Pallet_Loaded" in pieces
    mb = kit.MeshBuilder()
    bits = kit.seed_for("hangar-stores")
    for i in range(6):
        bx = x0 + 1.2 + i * 4.6
        for j, bz in enumerate((z0 + 5.4, z0 + 10.8)):
            style = (bits >> (i * 2 + j)) & 3
            if (i, j) in ((2, 0), (5, 1)):
                # Drawn down: one pallet left in a nearly empty bay.
                if loaded:
                    _place("SM_Hangar_Pallet_Loaded", bx + 0.6, bz + 2.9, room="flight_deck")
            elif (i, j) in ((1, 1), (4, 0)) and "SM_Hangar_Container_M_Gunmetal" in pieces:
                # A medium case waiting for the tug, two pallets beside it.
                _place(
                    "SM_Hangar_Container_M_Gunmetal",
                    bx + 1.8,
                    bz + 1.2,
                    0.0,
                    0.0,
                    room="flight_deck",
                )
                if loaded:
                    for a in range(2):
                        _place(
                            "SM_Hangar_Pallet_Loaded",
                            bx + 0.6 + a * 2.4,
                            bz + 3.0,
                            room="flight_deck",
                        )
            elif loaded and style != 3:
                # A 3 x 3 block of loaded pallets, a couple already gone.
                for a in range(3):
                    for b in range(3):
                        if (a * 3 + b + style) % 7 == 0:
                            continue
                        _place(
                            "SM_Hangar_Pallet_Loaded",
                            bx + 0.6 + a * 1.2,
                            bz + 0.6 + b * 1.2,
                            room="flight_deck",
                        )
            elif "SM_Hangar_CrateStack" in pieces:
                for b in range(3):
                    _place("SM_Hangar_CrateStack", bx + 1.8, bz + 0.6 + b * 1.2, room="flight_deck")
            else:
                box(mb, bx + 0.05, bx + 3.55, bz + 0.05, bz + 3.55, 0.0, 1.0, CRATE)
                ucx(f"stores_{i}_{j}", bx, bx + 3.6, bz, bz + 3.6, 0.0, 1.0)
    if not mb.is_empty():
        _build(mb, "SM_HangarPH_Stores", bevel=0.012, room="flight_deck")
    else:
        mb.bm.free()


# --------------------------------------------------------------------------
# Front band: arrivals desk, booth consoles, armoury racks, signs
# --------------------------------------------------------------------------


def arrivals_desk(pieces: dict) -> None:
    dx, dz = L.DESK_C
    if "SM_Counter_Arrivals" in pieces:
        # Placement id "arrivals": the piece's station and screen sockets come out
        # as SOCKET_station_arrivals / SOCKET_screen_arrivals (the deck contract).
        _place(
            "SM_Counter_Arrivals",
            dx,
            dz,
            id="arrivals",
            room="arrivals",
            station="arrivals",
            station_kind="create_agent",
        )
    else:
        mb = kit.MeshBuilder()
        det = kit.MeshBuilder()
        # Counter: light front fascia toward the arrivals side (+z far side), a dark
        # work top, and a backlit status band on the camera side.
        box(mb, dx - 3.0, dx + 3.0, dz - 0.5, dz + 0.5, 0.0, 1.0, PANEL)
        box(mb, dx - 3.1, dx + 3.1, dz - 0.62, dz + 0.58, 1.0, 1.06, "M_Console_Body")
        box(mb, dx - 3.06, dx + 3.06, dz - 0.56, dz + 0.54, 0.0, 0.12, STEEL)
        box(det, dx - 2.8, dx + 2.8, dz + 0.5, dz + 0.52, 0.72, 0.8, "M_Hangar_SignBacklit")
        for k in range(5):
            x = dx - 2.4 + k * 1.2
            box(det, x - 0.02, x + 0.02, dz + 0.5, dz + 0.53, 0.14, 0.7, RECESS)
        box(det, dx - 1.0, dx + 1.0, dz - 0.3, dz + 0.1, 1.06, 1.09, "M_Console_Keys")
        box(det, dx - 0.06, dx + 0.06, dz - 0.15, dz - 0.05, 1.06, 1.32, STEEL)
        obj = _build(mb, "SM_Hangar_ArrivalsCounter", bevel=0.01, room="arrivals")
        kit.tag(obj, station="arrivals", station_kind="create_agent")
        _build(det, "SM_Hangar_ArrivalsCounterDetail", bevel=0.0)
        # Terminal: a monitor leaning back 12 degrees, screen toward the camera.
        tilt = math.radians(12.0)
        centre = Vector(B(dx, dz - 0.1, 1.55))
        mon = kit.MeshBuilder()
        mon.box((-0.46, -0.02, -0.28), (0.46, 0.05, 0.28), "M_Console_Body")
        mon_obj = _build(mon, "SM_Hangar_ArrivalsMonitor", bevel=0.006)
        mon_obj.location = centre
        mon_obj.rotation_euler = (-tilt, 0.0, 0.0)
        scr = kit.MeshBuilder()
        scr.quad(
            [
                (-0.42, -0.021, -0.24),
                (0.42, -0.021, -0.24),
                (0.42, -0.021, 0.24),
                (-0.42, -0.021, 0.24),
            ],
            "M_Screen",
        )
        scr_obj = _build(scr, "SM_Hangar_ArrivalsScreen", bevel=0.0)
        scr_obj.location = centre
        scr_obj.rotation_euler = (-tilt, 0.0, 0.0)
        normal = Vector((0.0, -math.cos(tilt), math.sin(tilt)))
        scene.add_screen(
            "arrivals",
            centre + normal * 0.03,
            0.84,
            0.48,
            yaw_deg=0.0,
            tilt_deg=12.0,
            station="arrivals",
        )
        ucx("arrivals_desk", dx - 3.1, dx + 3.1, dz - 0.62, dz + 0.58, 0.0, 1.85)
    # Queue posts with belts from the walkway to the counter.
    posts = kit.MeshBuilder()
    for x in (dx - 1.6, dx + 1.6):
        zs = [L.WALKWAY_Z[1] - 0.6 + 0.7 * k for k in range(3)]
        for z in zs:
            posts.tube(B(x, z, 0.0), B(x, z, 0.95), 0.03, TRIM, 10)
            posts.tube(B(x, z, 0.0), B(x, z, 0.03), 0.17, STEEL, 16)
        posts.box(B(x - 0.015, zs[-1], 0.82), B(x + 0.015, zs[0], 0.88), RUBBER)
    _build(posts, "SM_Hangar_QueuePosts", bevel=0.0, room="arrivals")
    for sx in (-1, 1):
        sign_pylon(
            f"SM_Hangar_SignArrivals_{'W' if sx < 0 else 'E'}", dx + sx * 6.6, 48.0, "ARRIVALS"
        )


def sign_pylon(name: str, x: float, z: float, body: str) -> None:
    mb = kit.MeshBuilder()
    box(mb, x - 1.2, x + 1.2, z - 0.15, z + 0.15, 0.0, 2.9, PANEL_MID)
    box(mb, x - 1.25, x + 1.25, z - 0.2, z + 0.2, 0.0, 0.18, STEEL)
    box(mb, x - 1.1, x + 1.1, z + 0.15, z + 0.17, 2.05, 2.75, RECESS)
    _build(mb, name, bevel=0.01, room="arrivals")
    text = _text_object(f"{name}_Text", body, 0.42, "M_Hangar_SignBacklit")
    text.location = B(x, z + 0.18, 2.42)
    text.rotation_euler = (math.radians(90.0), 0.0, 0.0)
    bar = kit.MeshBuilder()
    bar.quad(
        [
            B(x - 0.95, z + 0.18, 2.14),
            B(x + 0.95, z + 0.18, 2.14),
            B(x + 0.95, z + 0.18, 2.17),
            B(x - 0.95, z + 0.18, 2.17),
        ],
        "M_Hangar_SignBacklit",
    )
    _build(bar, f"{name}_Bar", bevel=0.0)
    ucx(name.removeprefix("SM_Hangar_").lower(), x - 1.25, x + 1.25, z - 0.2, z + 0.2, 0.0, 2.9)


def _text_object(name: str, body: str, size: float, material: str) -> bpy.types.Object:
    """Font text converted to a mesh object (centred), in the Props collection."""
    curve = bpy.data.curves.new(f"{name}_curve", "FONT")
    curve.body = body
    curve.size = size
    curve.align_x = "CENTER"
    curve.align_y = "CENTER"
    try:
        curve.font = bpy.data.fonts.load("C:/Windows/Fonts/ARIALNB.TTF", check_existing=True)
    except RuntimeError:
        pass
    tmp = bpy.data.objects.new(f"{name}_tmp", curve)
    bpy.context.scene.collection.objects.link(tmp)
    depsgraph = bpy.context.evaluated_depsgraph_get()
    mesh = bpy.data.meshes.new_from_object(tmp.evaluated_get(depsgraph))
    bpy.data.objects.remove(tmp)
    bpy.data.curves.remove(curve)
    mesh.materials.clear()
    mesh.materials.append(materials.get(material))
    obj = bpy.data.objects.new(name, mesh)
    scene.collection("Props").objects.link(obj)
    kit.tag(obj, nav="none")
    return obj


def booth_consoles(pieces: dict) -> None:
    bx0, _, bz0, _ = L.BOOTH
    bf = L.BOOTH_FLOOR
    xs = (6.6, 11.4, 16.2, 21.0)
    use_kit = "SM_Console_BoothRear" in pieces
    mb = kit.MeshBuilder()
    det = kit.MeshBuilder()
    cz = bz0 + 1.15
    for n, x in enumerate(xs, start=1):
        if use_kit:
            _place("SM_Console_BoothRear", x, cz, bf, 180.0, id=f"booth_{n}", room="booth")
        else:
            box(mb, x - 1.8, x + 1.8, cz - 0.45, cz + 0.45, bf, bf + 0.8, "M_Console_Body")
            box(mb, x - 1.6, x + 1.6, cz - 0.42, cz - 0.3, bf + 0.86, bf + 1.3, "M_Console_Body")
            ucx(f"booth_console_{n}", x - 1.85, x + 1.85, cz - 0.5, cz + 0.55, 0.0, bf + 1.3)
        # Operator chairs on the camera side; the crew look over the hood to the deck.
        for dxs in (-0.9, 0.9):
            sx, sz = x + dxs, cz + 1.25
            box(
                mb,
                sx - 0.28,
                sx + 0.28,
                sz - 0.28,
                sz + 0.28,
                bf + 0.42,
                bf + 0.52,
                "M_Seat_Upholstery",
            )
            box(
                mb,
                sx - 0.28,
                sx + 0.28,
                sz + 0.22,
                sz + 0.32,
                bf + 0.52,
                bf + 1.12,
                "M_Seat_Upholstery",
            )
            mb.tube(B(sx, sz, bf), B(sx, sz, bf + 0.42), 0.04, TRIM, 10)
            mb.tube(B(sx, sz, bf), B(sx, sz, bf + 0.03), 0.26, STEEL, 16)
            side = "a" if dxs < 0 else "b"
            scene.add_socket(
                "seat", f"booth_{n}{side}", B(sx, sz, bf), 180.0, seat_height=0.5, room="booth"
            )
    # Supervisor stand at the back of the booth.
    box(mb, 12.0, 15.6, 56.2, 56.9, bf, bf + 1.05, "M_Console_Body")
    box(det, 12.2, 15.4, 56.9, 56.92, bf + 0.8, bf + 1.0, "M_Screen")
    scene.add_socket("stand", "booth_supervisor", B(13.8, 57.8, bf), 180.0, room="booth")
    ucx("booth_supervisor", 12.0, 15.6, 56.2, 56.9, 0.0, bf + 1.05)
    # Equipment cabinets along the west wall.
    for z in (50.0, 52.4, 54.8, 57.2):
        box(mb, bx0 + 0.3, bx0 + 1.0, z - 1.0, z + 1.0, bf, bf + 2.0, PANEL_MID)
        box(det, bx0 + 1.0, bx0 + 1.02, z - 0.1, z + 0.1, bf + 1.6, bf + 1.7, "M_Indicator_Green")
    ucx("booth_cabinets", bx0 + 0.3, bx0 + 1.0, 49.0, 58.2, 0.0, bf + 2.0)
    _build(mb, "SM_Hangar_BoothFittings", bevel=0.008, room="booth")
    _build(det, "SM_Hangar_BoothDetail", bevel=0.0)


def armoury(pieces: dict) -> None:
    ax0, ax1, _, _ = L.ARMOURY
    rack = kit.MeshBuilder()
    use_kit = "SM_Hangar_ArmourRack" in pieces
    for r, z in enumerate((50.6, 54.2, 57.8)):
        x0, x1 = 82.2, ax1 - 1.0
        if use_kit:
            for k in range(5):
                _place("SM_Hangar_ArmourRack", x0 + 1.3 + k * 2.65, z, 0.0, 0.0, room="armoury")
        else:
            box(rack, x0, x1, z - 0.7, z, 0.0, 2.3, PANEL_MID)
            ucx(f"armoury_rack_{r}", x0, x1, z - 0.7, z, 0.0, 2.3)
    # Weapon lockers along the west wall and crates by the door.
    for z in (49.6, 51.8, 54.0, 56.2, 58.4):
        box(rack, ax0 + 0.3, ax0 + 1.1, z - 1.0, z + 1.0, 0.0, 2.1, CRATE)
        box(rack, ax0 + 1.1, ax0 + 1.12, z - 0.05, z + 0.05, 1.2, 1.4, TRIM)
    ucx("armoury_lockers", ax0 + 0.3, ax0 + 1.1, 48.6, 59.4, 0.0, 2.1)
    if "SM_Hangar_Crate_A" in pieces:
        for x, z, h in ((84.0, 60.4, 0.0), (85.4, 60.4, 0.0), (84.7, 60.4, 0.8)):
            _place("SM_Hangar_Crate_A", x, z, h, 0.0, room="armoury")
    _build(rack, "SM_Hangar_ArmouryLockers", bevel=0.008, room="armoury")


def build_all() -> Vector | None:
    pieces = load_kit()
    foot = shuttle(pieces)
    cargo(pieces)
    fuel_lines(pieces)
    ground_equipment(pieces)
    stores(pieces)
    arrivals_desk(pieces)
    booth_consoles(pieces)
    armoury(pieces)
    return foot
