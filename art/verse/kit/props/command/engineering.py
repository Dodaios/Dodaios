"""Engineering control room: technician terminal banks and the master desk.

These pieces match the engineering deck's layout contract
(``decks/engineering/eng_rooms.py``) so they replace its stand-ins without
moving a socket:

* Terminal modules: origin on the **screen line** (``TERM_ROWS_Z``), the live
  screen 1.30 x 0.62 m tilted 32 degrees back, its centre 0.18 m behind the
  line at 1.13 m; the seat 0.85 m in front of the line. Modules are 2.4 m
  (station, fill) or 1.8 m (short fill) wide and butt together into banks;
  ``SM_Terminal_EngineeringEnd`` caps a bank.
* ``SM_Console_MasterDesk``: origin on the desk's front edge (``MASTER_Z``),
  9.6 m wide, five 1.56 x 0.60 screens at 1.9 m pitch tilted 30 degrees, the
  back cabinet reaching 2.6 m to the far wall.

All use the ``design`` anchor (their origin is the contract line).
"""

from __future__ import annotations

import math

from lib import kit

from ._base import (
    ACCENT_RED,
    BODY,
    BODY_LIGHT,
    DARK_PANEL,
    LAMP_GREEN,
    LAMP_PALETTE_COOL,
    LAMP_PALETTE_ENGINE,
    LAMP_RED,
    LAMP_WHITE,
    SATIN,
    STEEL,
    anchor,
    box_occluder,
    builders,
    button_bank,
    finish_all,
    frame_on_slope,
    keyboard,
    pname,
    screen,
    slat_stack,
    stand_socket,
    tr,
    xform,
)
from .seating import office_chair

TILT = 32.0
SCREEN = (1.30, 0.62)
SCREEN_BACK = 0.18
SCREEN_Z = 1.13
SEAT_OFFSET = 0.85
HOOD_TOP = 1.50
HOOD_BACK = 0.62
STATION_W = 2.4
SHORT_W = 1.8


def _hood_profile() -> tuple[tuple[float, float], ...]:
    """Hood side profile (y, z) whose sloped face is the screen plane."""
    t = math.tan(math.radians(TILT))

    def y_at(z: float) -> float:
        return SCREEN_BACK + 0.012 + (z - SCREEN_Z) * t

    return (
        (y_at(0.79), 0.79),
        (HOOD_BACK, 0.79),
        (HOOD_BACK, HOOD_TOP - 0.05),
        (HOOD_BACK - 0.05, HOOD_TOP),
        (y_at(HOOD_TOP), HOOD_TOP),
    )


def _module_body(mbs, x: float, w: float) -> None:
    """Desk carcass, work deck and sloped hood of one bank module."""
    body, trim, detail = mbs["body"], mbs["trim"], mbs["detail"]
    x0, x1 = x - w / 2, x + w / 2
    body.box((x0, -0.30, 0.08), (x1, 0.60, 0.74), BODY)
    trim.box((x0 + 0.04, -0.22, 0.0), (x1 - 0.04, 0.55, 0.08), SATIN)
    trim.box((x0, -0.44, 0.74), (x1, 0.64, 0.79), BODY_LIGHT)
    detail.box((x0, -0.46, 0.73), (x1, -0.44, 0.795), SATIN)
    body.prism_x(_hood_profile(), x0, x1, BODY)
    # Front panel seams under the deck lip, one per 0.6 m.
    n = max(1, round(w / 0.6))
    for i in range(n):
        px = x0 + (i + 0.5) * w / n
        detail.box(
            (px - w / n / 2 + 0.02, -0.306, 0.14), (px + w / n / 2 - 0.02, -0.30, 0.68), BODY_LIGHT
        )
    top = frame_on_slope((x, (HOOD_BACK + _hood_profile()[-1][0]) / 2, HOOD_TOP), 90.0)
    depth = HOOD_BACK - _hood_profile()[-1][0]
    with xform(detail, top):
        detail.box(
            (-w / 2 + 0.02, -depth / 2 + 0.004, 0.0),
            (w / 2 - 0.02, -depth / 2 + 0.016, 0.003),
            ACCENT_RED,
        )


def _hood_frame(x: float, up: float) -> object:
    """Frame on the hood face, ``up`` metres up the slope from the screen centre."""
    t = math.radians(TILT)
    return frame_on_slope(
        (x, SCREEN_BACK + 0.012 + up * math.sin(t), SCREEN_Z + up * math.cos(t)), TILT
    )


def station_module(mbs, x: float, seed: int, local_id: str, *, chair: bool = True) -> None:
    """Live terminal: the big tilted screen, keys, chair, sockets."""
    lamps, detail = mbs["lamps"], mbs["detail"]
    w = STATION_W
    _module_body(mbs, x, w)
    sw, sh = SCREEN
    screen(
        f"{pname()}_screen{local_id}",
        _hood_frame(x, 0.0) @ tr(0.0, 0.0, 0.02),  # glass where the deck's socket is
        sw,
        sh,
        detail,
        local_id=local_id,
        border=0.04,
        depth=0.03,
    )
    side = (w - sw - 0.08) / 2
    sx = sw / 2 + 0.04 + side / 2
    button_bank(
        lamps,
        detail,
        _hood_frame(x - sx, 0.05),
        4,
        9,
        (0.034, 0.05),
        (0.024, 0.032),
        seed,
        lit=0.45,
        palette=LAMP_PALETTE_ENGINE,
    )
    slat_stack(
        lamps,
        detail,
        _hood_frame(x + sx, 0.10),
        6,
        side - 0.12,
        0.014,
        0.03,
        seed=seed + 1,
        lit=0.7,
    )
    with xform(lamps, _hood_frame(x + sx, -0.22)):
        for i, mat in enumerate((LAMP_GREEN, LAMP_WHITE, LAMP_RED)):
            lamps.box((-0.06 + i * 0.05, -0.008, 0.003), (-0.04 + i * 0.05, 0.008, 0.01), mat)
    desk = frame_on_slope((x, -0.20, 0.79), 90.0)
    keyboard(detail, desk, w=0.52, d=0.16, cols=18)
    with xform(detail, desk):
        detail.box((0.34, -0.06, 0.0), (0.46, 0.06, 0.008), SATIN)
    button_bank(
        lamps,
        detail,
        desk @ tr(-0.46, 0.0),
        3,
        4,
        (0.03, 0.03),
        (0.022, 0.022),
        seed + 2,
        lit=0.35,
        palette=LAMP_PALETTE_ENGINE,
    )
    if chair:
        office_chair(
            f"{pname()}_chair{local_id}",
            x,
            -SEAT_OFFSET - 0.02,  # the seat socket sits 2 cm ahead of the chair centre
            0.0,
            "operator",
            seat_id=local_id,
        )
        stand_socket(local_id, x, -1.55, 180.0)
    box_occluder((x - w / 2, -0.46, 0.0), (x + w / 2, 0.64, 0.79))
    box_occluder((x - w / 2, -0.04, 0.79), (x + w / 2, HOOD_BACK, HOOD_TOP))


def fill_module(mbs, x: float, w: float, seed: int) -> None:
    """Static instrument module between live terminals."""
    lamps, detail = mbs["lamps"], mbs["detail"]
    _module_body(mbs, x, w)
    n = 2 if w > 2.0 else 1
    for i in range(n):
        px = x + (i - (n - 1) / 2) * (w / n)
        cell = w / n
        screen(
            f"{pname()}_panel{seed}_{i}",
            _hood_frame(px - cell * 0.18, 0.12),
            cell * 0.42,
            0.26,
            detail,
            socket_on=False,
            border=0.025,
            depth=0.015,
        )
        button_bank(
            lamps,
            detail,
            _hood_frame(px + cell * 0.26, 0.12),
            3,
            5,
            (0.034, 0.045),
            (0.024, 0.03),
            seed + 10 * i,
            lit=0.45,
            palette=LAMP_PALETTE_COOL,
        )
        slat_stack(
            lamps,
            detail,
            _hood_frame(px, -0.20),
            3,
            cell * 0.7,
            0.012,
            0.022,
            seed=seed + 10 * i + 1,
            lit=0.67,
        )
        with xform(detail, frame_on_slope((px, -0.20, 0.79), 90.0)):
            detail.box((-cell * 0.35, -0.08, 0.0), (cell * 0.35, 0.08, 0.012), SATIN)
    box_occluder((x - w / 2, -0.46, 0.0), (x + w / 2, 0.64, 0.79))
    box_occluder((x - w / 2, -0.04, 0.79), (x + w / 2, HOOD_BACK, HOOD_TOP))


def end_frame(mbs, x: float) -> None:
    mbs["trim"].box((x - 0.06, -0.46, 0.0), (x + 0.06, 0.66, 1.56), STEEL)
    box_occluder((x - 0.06, -0.46, 0.0), (x + 0.06, 0.66, 1.56))


@kit.piece("SM_Terminal_Engineering", dims=(2.40, 1.88, 1.50))
def engineering_station() -> None:
    """Technician's live terminal module (2.4 m): 1.30 x 0.62 m screen, keys,
    operator chair. Origin on the screen line. SOCKET_seat/screen/stand ''."""
    mbs = builders()
    station_module(mbs, 0.0, 401, "")
    finish_all(mbs)
    anchor("design")


@kit.piece("SM_Terminal_EngineeringFill", dims=(2.40, 1.10, 1.50), width=STATION_W, seed=411)
@kit.piece("SM_Terminal_EngineeringFillShort", dims=(1.80, 1.10, 1.50), width=SHORT_W, seed=421)
def engineering_fill(width: float, seed: int) -> None:
    """Static instrument module of a terminal bank (no sockets)."""
    mbs = builders()
    fill_module(mbs, 0.0, width, seed)
    finish_all(mbs)
    anchor("design")


@kit.piece("SM_Terminal_EngineeringEnd", dims=(0.12, 1.12, 1.56))
def engineering_end() -> None:
    """Gunmetal end frame capping a terminal bank."""
    mbs = builders()
    end_frame(mbs, 0.0)
    finish_all(mbs)
    anchor("design")


@kit.piece("SM_Terminal_EngineeringBank", dims=(11.04, 1.90, 1.56))
def engineering_bank() -> None:
    """Two-station bank (10.8 m + end frames), stations at x = -2.4 and +2.4
    as in the engineering deck. SOCKET_seat/screen/stand '1' and '2'."""
    mbs = builders()
    end_frame(mbs, -5.46)
    fill_module(mbs, -4.5, SHORT_W, 431)
    station_module(mbs, -2.4, 433, "1")
    fill_module(mbs, 0.0, STATION_W, 435)
    station_module(mbs, 2.4, 437, "2")
    fill_module(mbs, 4.5, SHORT_W, 439)
    end_frame(mbs, 5.46)
    finish_all(mbs)
    anchor("design")


# --------------------------------------------------------------------------
# Master systems desk
# --------------------------------------------------------------------------

MASTER_W = 9.6
MASTER_DEPTH = 1.4
MASTER_CABINET = 2.6  # front edge to the far wall's room face
MASTER_SCREEN = (1.56, 0.60)
MASTER_PITCH = 1.9


def _cabinet_top(mbs, x0: float, x1: float) -> None:
    """Equipment on the back cabinet's top: housings with vent grilles and a
    status lamp, two conduits along the wall. Keeps the large top from
    reading as a void."""
    body, trim, detail, lamps = mbs["body"], mbs["trim"], mbs["detail"], mbs["lamps"]
    z = 1.9
    for k in range(6):
        cx = x0 + 0.8 + k * (x1 - x0 - 1.6) / 5
        h = 0.12 + 0.06 * (k % 3)
        body.box((cx - 0.55, MASTER_DEPTH + 0.12, z), (cx + 0.55, MASTER_DEPTH + 0.72, z + h), BODY)
        for i in range(6):
            gy = MASTER_DEPTH + 0.22 + i * 0.07
            detail.box((cx - 0.40, gy, z + h), (cx + 0.40, gy + 0.03, z + h + 0.004), SATIN)
        lamps.box(
            (cx + 0.44, MASTER_DEPTH + 0.16, z + h),
            (cx + 0.47, MASTER_DEPTH + 0.19, z + h + 0.006),
            LAMP_GREEN if k % 2 else LAMP_WHITE,
        )
    for y in (MASTER_CABINET - 0.30, MASTER_CABINET - 0.16):
        trim.tube((x0 + 0.1, y, z + 0.06), (x1 - 0.1, y, z + 0.06), 0.05, STEEL, 12)


@kit.piece("SM_Console_MasterDesk", dims=(9.70, 2.67, 2.15))
def master_desk() -> None:
    """Master systems console of the engineering control room: long desk,
    five tilted screens, back cabinet to the wall. Origin on the front edge.
    SOCKET_station '' (the commander's spot), SOCKET_screen '1'-'5'
    (3 = the centre "master_desk" screen)."""
    mbs = builders()
    body, trim, detail, lamps = mbs["body"], mbs["trim"], mbs["detail"], mbs["lamps"]
    x0, x1 = -MASTER_W / 2, MASTER_W / 2
    body.box((x0, 0.0, 0.08), (x1, MASTER_DEPTH, 0.74), BODY)
    trim.box((x0 + 0.1, 0.04, 0.0), (x1 - 0.1, MASTER_DEPTH, 0.08), SATIN)
    trim.box((x0 - 0.05, -0.05, 0.74), (x1 + 0.05, MASTER_DEPTH + 0.06, 0.80), BODY_LIGHT)
    detail.box((x0 - 0.05, -0.065, 0.73), (x1 + 0.05, -0.05, 0.805), SATIN)
    body.box((x0, MASTER_DEPTH, 0.0), (x1, MASTER_CABINET, 1.9), BODY)
    trim.box((x0 - 0.04, MASTER_DEPTH - 0.02, 1.86), (x1 + 0.04, MASTER_CABINET, 1.9), DARK_PANEL)
    trim.box((x0 - 0.04, MASTER_DEPTH - 0.03, 1.84), (x1 + 0.04, MASTER_DEPTH - 0.01, 1.905), STEEL)
    _cabinet_top(mbs, x0, x1)
    for k in range(9):
        px = x0 + 0.53 + k * 1.07
        detail.box((px - 0.02, MASTER_DEPTH - 0.006, 0.86), (px + 0.02, MASTER_DEPTH, 1.84), STEEL)
    for i in range(16):
        px = x0 + 0.3 + i * 0.6
        detail.box((px - 0.27, -0.006, 0.14), (px + 0.27, 0.0, 0.68), BODY_LIGHT)
    sw, sh = MASTER_SCREEN
    for i in range(5):
        sx = (i - 2) * MASTER_PITCH
        f = frame_on_slope((sx, 1.05, 1.18), 30.0)
        with xform(body, f):
            body.box((-0.82, -0.34, -0.08), (0.82, 0.34, -0.004), BODY)
        screen(
            f"{pname()}_screen{i + 1}",
            f,
            sw,
            sh,
            detail,
            local_id=str(i + 1),
            border=0.03,
            depth=0.02,
        )
        with xform(detail, f):
            detail.box((-0.06, -0.36, -0.30), (0.06, -0.30, -0.004), STEEL)
    for i in range(4):
        sx = (i - 1.5) * MASTER_PITCH
        f = frame_on_slope((sx, 1.05, 1.18), 30.0)
        slat_stack(lamps, detail, f @ tr(0.0, 0.12), 4, 0.18, 0.012, 0.02, seed=450 + i)
        button_bank(
            lamps,
            detail,
            f @ tr(0.0, -0.16),
            4,
            3,
            (0.032, 0.04),
            (0.022, 0.026),
            460 + i,
            lit=0.45,
            palette=LAMP_PALETTE_COOL,
        )
    deck = frame_on_slope((0.0, 0.28, 0.80), 90.0)
    for i in range(5):
        keyboard(detail, deck @ tr((i - 2) * MASTER_PITCH, 0.0), w=0.56, d=0.17, cols=19)
        button_bank(
            lamps,
            detail,
            deck @ tr((i - 2) * MASTER_PITCH + 0.48, 0.0),
            3,
            4,
            (0.03, 0.03),
            (0.022, 0.022),
            470 + i,
            lit=0.35,
        )
    finish_all(mbs)
    stand_socket("", 0.0, -0.75, 0.0, kind="station")
    box_occluder((x0 - 0.05, -0.07, 0.0), (x1 + 0.05, MASTER_CABINET, 0.80))
    box_occluder((x0, 0.70, 0.80), (x1, MASTER_CABINET, 1.9))
    anchor("design")
