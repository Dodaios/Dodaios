"""Tables: strategy holo-table, briefing table, team round table, commander's desk.

Seats around a table are numbered clockwise as seen on the plate, starting
with the left-most seat on the camera side: ``SOCKET_seat_<id>__01`` ...
"""

from __future__ import annotations

import math

from lib import kit

from ._base import (
    BODY,
    BODY_LIGHT,
    CHROME,
    GLOSS,
    HOLO_LENS,
    LAMP_BLUE,
    LAMP_GREEN,
    LAMP_PALETTE_COOL,
    LAMP_RED,
    LAMP_WHITE,
    SATIN,
    STEEL,
    anchor,
    builders,
    button_bank,
    circle,
    finish_all,
    frame_on_slope,
    holo_socket,
    lathe,
    loft,
    pname,
    prism_occluder,
    rounded_rect,
    screen,
    slab,
    stand_socket,
    superellipse,
    tr,
    xform,
)
from .seating import office_chair


def _facing_centre(phi_deg: float) -> float:
    """Seat/stand facing angle for a spot at polar angle ``phi`` looking inward."""
    return phi_deg + 90.0


def _projector(mbs, z: float, r: float = 0.30) -> None:
    """Low holo emitter: steel collar, black cap, glowing lens."""
    trim, detail, lamps = mbs["trim"], mbs["detail"], mbs["lamps"]
    lathe(
        trim,
        ((0.0, z), (r, z), (r, z + 0.03), (r - 0.02, z + 0.045), (0.0, z + 0.045)),
        STEEL,
        48,
    )
    lathe(
        detail,
        ((0.0, z + 0.045), (r - 0.05, z + 0.045), (r - 0.07, z + 0.062), (0.0, z + 0.062)),
        GLOSS,
        48,
    )
    lathe(
        lamps,
        ((0.0, z + 0.062), (r * 0.32, z + 0.062), (r * 0.26, z + 0.078), (0.0, z + 0.082)),
        HOLO_LENS,
        32,
    )
    for i in range(8):
        a = math.radians(22.5 + 45 * i)
        cx, cy = math.cos(a) * (r - 0.12), math.sin(a) * (r - 0.12)
        lamps.box_c((cx, cy, z + 0.064), (0.012, 0.012, 0.006), LAMP_BLUE)


# --------------------------------------------------------------------------
# Strategy holo-table
# --------------------------------------------------------------------------


@kit.piece("SM_Table_HoloStrategy", dims=(3.60, 3.60, 0.97))
def holo_strategy_table() -> None:
    """Round 3.6 m strategy table: pedestal, sloped control ring, sunken
    glass well and a central emitter. SOCKET_holo '', SOCKET_station '',
    SOCKET_stand 's1'-'s8' around the rim."""
    mbs = builders()
    body, trim, detail, lamps = mbs["body"], mbs["trim"], mbs["detail"], mbs["lamps"]
    lathe(trim, ((0.0, 0.0), (1.16, 0.0), (1.16, 0.08), (0.0, 0.08)), SATIN, 64)
    lathe(body, ((0.0, 0.08), (1.22, 0.08), (1.22, 0.80), (0.0, 0.80)), BODY, 64)
    # Vertical service panels on the pedestal.
    for i in range(16):
        a = math.radians(11.25 + 22.5 * i)
        with xform(detail, tr(math.cos(a) * 1.22, math.sin(a) * 1.22, 0.0, math.degrees(a) - 90)):
            detail.box((-0.012, -0.004, 0.14), (0.012, 0.004, 0.74), SATIN)
    lathe(trim, ((1.15, 0.78), (1.56, 0.78), (1.56, 0.82), (1.15, 0.82)), SATIN, 64, closed=True)
    lathe(
        trim,
        ((1.55, 0.80), (1.80, 0.80), (1.80, 0.885), (1.785, 0.90), (1.55, 0.90)),
        STEEL,
        96,
        closed=True,
    )
    lathe(body, ((1.30, 0.80), (1.56, 0.80), (1.56, 0.90), (1.30, 0.97)), BODY, 96, closed=True)
    lathe(
        trim,
        ((1.22, 0.80), (1.31, 0.80), (1.31, 0.975), (1.27, 0.975), (1.25, 0.86)),
        STEEL,
        96,
        closed=True,
    )
    lathe(detail, ((0.0, 0.83), (1.26, 0.83), (1.26, 0.85), (0.0, 0.85)), GLOSS, 96)
    # Concentric emitter rings etched into the well glass.
    for r in (0.55, 0.85, 1.10):
        lathe(
            detail,
            ((r - 0.006, 0.849), (r + 0.006, 0.849), (r + 0.006, 0.853), (r - 0.006, 0.853)),
            STEEL,
            96,
            closed=True,
        )
    _projector(mbs, 0.85, 0.26)

    # Control panels on the sloped ring, one per operator place.
    for k in range(8):
        phi = 22.5 + 45.0 * k
        a = math.radians(phi)
        panel = frame_on_slope(
            (math.cos(a) * 1.43, math.sin(a) * 1.43, 0.935), 75.0, rz_deg=phi + 90.0
        )
        screen(
            f"{pname()}_panel{k + 1}",
            panel @ tr(-0.12, 0.0),
            0.20,
            0.11,
            detail,
            socket_on=False,
            border=0.015,
            depth=0.01,
        )
        button_bank(
            lamps,
            detail,
            panel @ tr(0.12, 0.0),
            5,
            3,
            (0.028, 0.03),
            (0.018, 0.02),
            300 + k,
            lit=0.45,
            palette=LAMP_PALETTE_COOL,
        )
        with xform(lamps, panel):
            lamps.box((0.27, -0.01, 0.0), (0.29, 0.01, 0.007), (LAMP_RED, LAMP_GREEN)[k % 2])
    finish_all(mbs)

    holo_socket("", 0.0, 0.0, 0.94, radius=1.2, height=1.6)
    for k in range(8):
        phi = 22.5 + 45.0 * k
        a = math.radians(phi)
        stand_socket(f"s{k + 1}", math.cos(a) * 2.15, math.sin(a) * 2.15, _facing_centre(phi))
    stand_socket("", 0.0, -2.15, 0.0, kind="station")
    pts = [(p.x, p.y) for p, _ in circle(1.82, 16)]
    prism_occluder(pts, 0.0, 0.98)
    anchor("centre")


# --------------------------------------------------------------------------
# Briefing table
# --------------------------------------------------------------------------


def _seat_pad(mbs, x: float, y: float, facing_deg: float, k: int) -> None:
    """Inset data pad on the table top in front of a seat (no socket)."""
    pad = frame_on_slope((x, y, 0.761), 90.0, rz_deg=facing_deg)
    screen(
        f"{pname()}_pad{k:02d}",
        pad,
        0.24,
        0.14,
        mbs["detail"],
        socket_on=False,
        border=0.012,
        depth=0.006,
    )
    with xform(mbs["lamps"], pad):
        for i, mat in enumerate((LAMP_WHITE, LAMP_RED, LAMP_WHITE)):
            mbs["lamps"].box((0.15, -0.05 + i * 0.03, 0.0), (0.165, -0.04 + i * 0.03, 0.006), mat)


@kit.piece("SM_Table_Briefing", dims=(7.24, 4.04, 1.05))
def briefing_table() -> None:
    """Black glossy oval conference table for 12 with a central projector.
    SOCKET_seat '01'-'12', SOCKET_holo '', SOCKET_station ''."""
    mbs = builders()
    body, trim = mbs["body"], mbs["trim"]
    a, b = 2.70, 1.15
    top = superellipse(a, b, 3.0, 128)
    loft(
        body,
        top,
        ((-0.035, 0.70), (-0.004, 0.712), (0.0, 0.72), (0.0, 0.752), (-0.006, 0.76)),
        GLOSS,
    )
    skirt = superellipse(a - 0.40, b - 0.38, 3.0, 96)
    slab(trim, skirt, 0.56, 0.70, SATIN)
    for x in (-1.45, 1.45):
        slab(trim, rounded_rect(0.95, 0.66, 0.12, 6, x, 0.0), 0.04, 0.56, STEEL, chamfer=0.01)
        slab(trim, rounded_rect(1.10, 0.80, 0.14, 6, x, 0.0), 0.0, 0.04, SATIN, chamfer=0.008)
    _projector(mbs, 0.76, 0.32)

    seats: list[tuple[float, float, float]] = []
    for x in (-1.8, -0.9, 0.0, 0.9, 1.8):
        seats.append((x, -1.58, 0.0))
    seats.append((3.18, 0.0, 90.0))
    for x in (1.8, 0.9, 0.0, -0.9, -1.8):
        seats.append((x, 1.58, 180.0))
    seats.append((-3.18, 0.0, 270.0))
    for k, (x, y, facing) in enumerate(seats, start=1):
        office_chair(f"{pname()}_chair{k:02d}", x, y, facing, "conference", seat_id=f"{k:02d}")
        f = math.radians(facing)
        dx, dy = -math.sin(f), math.cos(f)
        _seat_pad(mbs, x + dx * 0.62, y + dy * 0.62, facing, k)
    finish_all(mbs)

    holo_socket("", 0.0, 0.0, 0.85, radius=1.0, height=1.2)
    stand_socket("", 0.0, -2.35, 0.0, kind="station")
    pts = [(p.x, p.y) for p, _ in superellipse(a, b, 3.0, 20)]
    prism_occluder(pts, 0.0, 0.76)
    anchor("centre")


# --------------------------------------------------------------------------
# Team round table
# --------------------------------------------------------------------------


@kit.piece("SM_Table_TeamRound", dims=(3.96, 3.96, 1.05))
def team_round_table() -> None:
    """Round table for 8 with a holo emitter. SOCKET_seat '01'-'08',
    SOCKET_holo '', SOCKET_station ''."""
    mbs = builders()
    body, trim = mbs["body"], mbs["trim"]
    r = 1.25
    loft(
        body,
        circle(r, 96),
        ((-0.03, 0.70), (-0.004, 0.712), (0.0, 0.72), (0.0, 0.752), (-0.006, 0.76)),
        GLOSS,
    )
    lathe(trim, ((0.0, 0.60), (0.80, 0.60), (0.80, 0.70), (0.0, 0.70)), SATIN, 64)
    lathe(
        trim,
        ((0.0, 0.0), (0.62, 0.0), (0.62, 0.03), (0.42, 0.06), (0.34, 0.60), (0.0, 0.60)),
        STEEL,
        64,
    )
    _projector(mbs, 0.76, 0.26)
    for k in range(8):
        phi = -112.5 - 45.0 * k  # clockwise from the camera-side left seat
        a = math.radians(phi)
        x, y = math.cos(a) * 1.62, math.sin(a) * 1.62
        facing = _facing_centre(phi)
        office_chair(
            f"{pname()}_chair{k + 1:02d}", x, y, facing, "conference", seat_id=f"{k + 1:02d}"
        )
        _seat_pad(mbs, math.cos(a) * 0.98, math.sin(a) * 0.98, facing, k + 1)
    finish_all(mbs)
    holo_socket("", 0.0, 0.0, 0.84, radius=0.9, height=1.2)
    stand_socket("", 0.0, -2.30, 0.0, kind="station")
    prism_occluder([(p.x, p.y) for p, _ in circle(r + 0.02, 16)], 0.0, 0.76)
    anchor("centre")


# --------------------------------------------------------------------------
# Commander's desk
# --------------------------------------------------------------------------


@kit.piece("SM_Desk_Commander", dims=(2.20, 1.77, 1.14))
def commander_desk() -> None:
    """Black glossy desk on steel pedestals, the commander's chair behind it
    facing the camera. SOCKET_seat/screen/station ''."""
    mbs = builders()
    body, trim, detail, lamps = mbs["body"], mbs["trim"], mbs["detail"], mbs["lamps"]
    slab(body, rounded_rect(2.2, 0.95, 0.05), 0.72, 0.77, GLOSS, chamfer=0.01)
    for x in (-0.80, 0.80):
        trim.box((x - 0.27, -0.42, 0.04), (x + 0.27, 0.42, 0.72), STEEL)
        trim.box((x - 0.25, -0.40, 0.0), (x + 0.25, 0.40, 0.04), SATIN)
        for z in (0.24, 0.46):
            detail.box((x - 0.24, 0.42, z), (x + 0.24, 0.425, z + 0.012), SATIN)
    # Modesty panel facing the camera, with vertical fluting.
    trim.box((-0.53, -0.40, 0.16), (0.53, -0.36, 0.72), BODY)
    for i in range(9):
        fx = -0.48 + i * 0.12
        detail.box((fx - 0.012, -0.408, 0.20), (fx + 0.012, -0.398, 0.68), BODY_LIGHT)
    # Inset screen, tilted toward the sitter on the +Y side.
    face = frame_on_slope((0.0, 0.16, 0.775), 80.0, rz_deg=180.0)
    screen(f"{pname()}_screen", face, 0.50, 0.28, detail, border=0.02, depth=0.03)
    with xform(detail, frame_on_slope((0.62, 0.10, 0.77), 90.0)):
        detail.box((-0.16, -0.10, 0.0), (0.16, 0.10, 0.012), SATIN)
        for i in range(4):
            detail.tube(
                (-0.09 + i * 0.06, -0.06, 0.03), (-0.09 + i * 0.06, 0.06, 0.03), 0.014, CHROME, 12
            )
    button_bank(
        lamps,
        detail,
        frame_on_slope((-0.62, 0.12, 0.77), 90.0, rz_deg=180.0),
        4,
        3,
        (0.03, 0.03),
        (0.02, 0.02),
        411,
        lit=0.4,
    )
    finish_all(mbs)
    office_chair(f"{pname()}_chair", 0.0, 0.80, 180.0, "commander", seat_id="")
    stand_socket("", 0.0, 0.80, 180.0, kind="station")
    prism_occluder([(-1.1, -0.48), (1.1, -0.48), (1.1, 0.48), (-1.1, 0.48)], 0.0, 0.77)
    anchor("centre")
