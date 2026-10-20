"""Consoles: crew-pit stations, standing and wall terminals, the commander's
station, the master systems console, engineering and instructor terminals.

Every console faces the camera: its screens look toward -Y (and up), the
operator stands or sits on the -Y side and faces +Y. Builders work with the
desk front edge at local Y = 0 and finish with ``anchor()``.
"""

from __future__ import annotations

import math
import random

from lib import kit

from ._base import (
    ACCENT_RED,
    BACKLIT,
    BODY,
    BODY_LIGHT,
    CHROME,
    LAMP_AMBER,
    LAMP_GREEN,
    LAMP_PALETTE_BRIDGE,
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
    edge_strip,
    fasteners,
    finish_all,
    frame_on_slope,
    keyboard,
    oriented_box_occluder,
    pname,
    screen,
    slat_stack,
    stand_socket,
    tr,
    xform,
)
from .seating import office_chair, stool

# --------------------------------------------------------------------------
# Seated crew console (crew pits, instructor)
# --------------------------------------------------------------------------

# Side profiles (y, z). The seated console is stepped: low key wings either
# side of a raised screen turret, the silhouette of the classic crew-pit desk.
_SEATED_WING = (
    (0.30, 0.08),
    (0.34, 0.08),
    (0.34, 0.0),
    (0.84, 0.0),
    (0.84, 0.93),
    (0.79, 0.985),
    (0.56, 0.985),
    (0.38, 0.81),
    (0.36, 0.81),
    (0.36, 0.715),
    (0.30, 0.715),
)
_SEATED_CHEEK = (
    (-0.03, 0.0),
    (0.84, 0.0),
    (0.84, 0.94),
    (0.795, 0.995),
    (0.565, 0.995),
    (0.385, 0.815),
    (0.37, 0.815),
    (-0.03, 0.75),
)
_SEATED_TURRET = (
    (0.40, 0.75),
    (0.84, 0.75),
    (0.84, 1.14),
    (0.79, 1.20),
    (0.62, 1.20),
    (0.44, 0.888),
    (0.40, 0.86),
)
_TURRET_CHEEK = (
    (0.395, 0.75),
    (0.845, 0.75),
    (0.845, 1.145),
    (0.793, 1.208),
    (0.617, 1.208),
    (0.435, 0.892),
    (0.395, 0.866),
)
_SCREEN_TILT = 30.0  # turret screen face, degrees back from vertical
_WING_TILT = 45.8  # key wing slope
_DESK_TILT = 10.0  # key shelf rises 10 degrees toward the screens


def seated_unit(
    mbs,
    x: float,
    width: float,
    seed: int,
    local_id: str,
    *,
    palette=LAMP_PALETTE_BRIDGE,
    chair: str = "crew",
    mirror: bool = False,
    screen_w: float = 0.38,
) -> None:
    """One seated console module centred at ``x`` with its chair and sockets."""
    rng = random.Random(seed)  # noqa: S311 - deterministic set dressing
    half = width / 2
    tw = screen_w + 0.10
    body, trim, detail, lamps = mbs["body"], mbs["trim"], mbs["detail"], mbs["lamps"]
    body.prism_x(_SEATED_WING, x - half + 0.03, x + half - 0.03, BODY)
    for side in (-1, 1):
        x0 = x + side * (half - 0.03)
        c0, c1 = sorted((x0, x0 + side * 0.03))
        trim.prism_x(_SEATED_CHEEK, c0, c1, STEEL)
        edge_strip(detail, _SEATED_CHEEK[2:], c0, c1)
        x1 = x + side * tw / 2
        t0, t1 = sorted((x1, x1 + side * 0.016))
        trim.prism_x(_TURRET_CHEEK, t0, t1, STEEL)
        edge_strip(detail, _TURRET_CHEEK[2:6], t0, t1)
    body.prism_x(_SEATED_TURRET, x - tw / 2, x + tw / 2, BODY)
    # Key shelf sloping up 10 degrees toward the screens, brushed-steel lip.
    rise = 0.39 * math.tan(math.radians(_DESK_TILT))
    shelf = ((-0.02, 0.705), (0.37, 0.705), (0.37, 0.735 + rise), (-0.02, 0.735))
    trim.prism_x(shelf, x - half + 0.03, x + half - 0.03, BODY_LIGHT)
    detail.box((x - half + 0.03, -0.034, 0.70), (x + half - 0.03, -0.018, 0.74), CHROME)
    for k in (-1, 1):  # panel seams across the shelf
        sxk = x + k * (half - 0.03) / 3
        with xform(detail, frame_on_slope((sxk, 0.175, 0.735 + rise / 2), 90.0 - _DESK_TILT)):
            detail.box((-0.0015, -0.19, 0.0), (0.0015, 0.19, 0.0012), SATIN)
    # Kick plate and a ventilation grille under the desk.
    trim.box((x - half + 0.03, 0.30, 0.0), (x + half - 0.03, 0.35, 0.08), SATIN)
    for i in range(7):
        z = 0.22 + i * 0.045
        detail.box((x - half + 0.12, 0.295, z), (x + half - 0.12, 0.305, z + 0.018), SATIN)

    # Turret: tilted screen and a short read-out on its top.
    face = frame_on_slope((x, 0.53, 1.044), _SCREEN_TILT)
    screen(f"{pname()}_screen{local_id}", face, screen_w, 0.25, detail, local_id=local_id)
    top = frame_on_slope((x, 0.705, 1.20), 90.0)
    fasteners(detail, top, tw, 0.17)
    with xform(detail, top):  # thin red trim along the turret's front edge
        detail.box((-tw / 2 + 0.01, -0.083, 0.0), (tw / 2 - 0.01, -0.071, 0.003), ACCENT_RED)
    slat_stack(lamps, detail, top @ tr(-0.06, 0.0), 3, 0.12, 0.011, 0.013, seed=seed + 2, lit=0.67)
    with xform(lamps, top):
        for i in range(3):
            lx = 0.07 + i * 0.045
            mat = LAMP_RED if rng.random() < 0.35 else LAMP_WHITE
            lamps.box((lx - 0.01, -0.01, 0.0), (lx + 0.01, 0.008, 0.008), mat)

    # Key wings either side of the turret.
    side_w = (width - 0.06 - tw - 0.032) / 2
    sx = tw / 2 + 0.016 + side_w / 2
    left, right = (-sx, sx) if not mirror else (sx, -sx)
    wing_l = frame_on_slope((x + left, 0.47, 0.8975), _WING_TILT)
    wing_r = frame_on_slope((x + right, 0.47, 0.8975), _WING_TILT)
    for wing_top_x in (left, right):
        fasteners(detail, frame_on_slope((x + wing_top_x, 0.675, 0.985), 90.0), side_w, 0.23)
    cols = max(2, int((side_w - 0.03) / 0.026))
    button_bank(
        lamps,
        detail,
        wing_l,
        cols,
        6,
        (0.026, 0.032),
        (0.018, 0.020),
        seed,
        lit=0.45,
        palette=palette,
    )
    slat_stack(
        lamps,
        detail,
        wing_r @ tr(0.0, 0.035),
        4,
        side_w - 0.05,
        0.012,
        0.016,
        seed=seed + 1,
        lit=0.75,
    )
    with xform(lamps, wing_r):
        for i in range(3):
            lx = -0.04 + i * 0.04
            lamps.box(
                (lx - 0.008, -0.085, 0.003),
                (lx + 0.008, -0.073, 0.010),
                (LAMP_RED, LAMP_GREEN, LAMP_WHITE)[(i + seed) % 3],
            )
    # Wing tops: a vent grille on one, a card slot and a lamp on the other.
    with xform(detail, frame_on_slope((x + left, 0.675, 0.985), 90.0)):
        for i in range(5):
            gy = -0.07 + i * 0.035
            detail.box((-side_w / 2 + 0.03, gy, 0.0), (side_w / 2 - 0.03, gy + 0.016, 0.004), SATIN)
    with xform(detail, frame_on_slope((x + right, 0.675, 0.985), 90.0)):
        detail.box((-0.07, -0.02, 0.0), (0.07, 0.02, 0.006), SATIN)
    with xform(lamps, frame_on_slope((x + right, 0.675, 0.985), 90.0)):
        lamps.box((0.09, -0.01, 0.0), (0.11, 0.01, 0.008), LAMP_GREEN)

    # Desk: keyboard, a backlit key pad and a small lamp pad.
    desk = frame_on_slope(
        (x, 0.17, 0.735 + 0.19 * math.tan(math.radians(_DESK_TILT))), 90.0 - _DESK_TILT
    )
    kw = min(0.42, width * 0.46)
    keyboard(detail, desk @ tr(0.0, -0.01), w=kw, d=0.14)
    pad_x = kw / 2 + 0.09
    button_bank(
        lamps,
        detail,
        desk @ tr(-pad_x if not mirror else pad_x, 0.02),
        3,
        3,
        (0.03, 0.03),
        (0.022, 0.022),
        seed + 3,
        lit=0.35,
        palette=palette,
    )
    with xform(detail, desk):
        px = pad_x if not mirror else -pad_x
        detail.box((px - 0.05, -0.04, 0.0), (px + 0.05, 0.06, 0.012), SATIN)

    office_chair(f"{pname()}_chair{local_id}", x, -0.36, 0.0, chair, seat_id=local_id)
    stand_socket(local_id, x, -1.0, 180.0)
    box_occluder((x - half, -0.04, 0.0), (x + half, 0.84, 0.995))
    box_occluder((x - tw / 2 - 0.016, 0.40, 0.995), (x + tw / 2 + 0.016, 0.845, 1.208))


@kit.piece("SM_Console_CrewPit", dims=(0.92, 1.62, 1.21), seed=11, mirror=False)
@kit.piece("SM_Console_CrewPitB", dims=(0.92, 1.62, 1.21), seed=23, mirror=True)
def crew_pit_console(seed: int, mirror: bool) -> None:
    """Seated crew-pit console with chair; SOCKET_seat/screen/stand ''."""
    mbs = builders()
    seated_unit(mbs, 0.0, 0.92, seed, "", mirror=mirror)
    finish_all(mbs)
    anchor("centre")


@kit.piece("SM_Console_CrewPitDouble", dims=(1.84, 1.62, 1.21))
def crew_pit_console_double() -> None:
    """Two seated stations on one body; sockets '1' (left) and '2' (right)."""
    mbs = builders()
    seated_unit(mbs, -0.46, 0.92, 31, "1")
    seated_unit(mbs, 0.46, 0.92, 37, "2", mirror=True)
    finish_all(mbs)
    anchor("centre")


# --------------------------------------------------------------------------
# Standing console (also the module of the command station)
# --------------------------------------------------------------------------

_STAND_BODY = (
    (0.04, 0.0),
    (0.62, 0.0),
    (0.62, 1.32),
    (0.56, 1.38),
    (0.42, 1.38),
    (0.26, 1.04),
    (0.0, 0.96),
    (0.0, 0.10),
    (0.04, 0.10),
)
_STAND_CHEEK = (
    (-0.01, 0.0),
    (0.62, 0.0),
    (0.62, 1.33),
    (0.565, 1.392),
    (0.425, 1.392),
    (0.265, 1.052),
    (-0.01, 0.972),
)


def standing_unit(
    mbs,
    matrix,
    width: float,
    seed: int,
    local_id: str,
    *,
    palette=LAMP_PALETTE_BRIDGE,
    screen_w: float = 0.40,
    screen_socket: bool = True,
) -> None:
    """Standing console module in ``matrix`` space (front edge on local Y = 0)."""
    half = width / 2
    body, trim, detail, lamps = mbs["body"], mbs["trim"], mbs["detail"], mbs["lamps"]
    with xform(body, matrix), xform(trim, matrix), xform(detail, matrix):
        body.prism_x(_STAND_BODY, -half + 0.025, half - 0.025, BODY)
        trim.prism_x(_STAND_CHEEK, -half, -half + 0.025, STEEL)
        trim.prism_x(_STAND_CHEEK, half - 0.025, half, STEEL)
        trim.box((-half + 0.025, 0.0, 0.0), (half - 0.025, 0.06, 0.10), SATIN)
        detail.box((-half + 0.025, -0.012, 0.93), (half - 0.025, 0.004, 0.975), SATIN)
        for i in range(5):
            z = 0.30 + i * 0.09
            detail.box((-half + 0.10, -0.006, z), (half - 0.10, 0.002, z + 0.05), BODY_LIGHT)
    work = matrix @ frame_on_slope((0.0, 0.13, 1.0), 73.0)
    keyboard(detail, work @ tr(0.0, -0.005), w=min(0.40, width * 0.45), d=0.13)
    pad = min(0.40, width * 0.45) / 2 + 0.07
    if width > 0.75:
        button_bank(
            lamps,
            detail,
            work @ tr(-pad - 0.01, 0.0),
            3,
            3,
            (0.028, 0.028),
            (0.02, 0.02),
            seed,
            lit=0.4,
            palette=palette,
        )
        button_bank(
            lamps,
            detail,
            work @ tr(pad + 0.01, 0.0),
            3,
            3,
            (0.028, 0.028),
            (0.02, 0.02),
            seed + 1,
            lit=0.4,
            palette=palette,
        )
    slope = matrix @ frame_on_slope((0.0, 0.34, 1.21), 25.0)
    screen(
        f"{pname()}_screen{local_id}",
        slope,
        screen_w,
        0.25,
        detail,
        local_id=local_id,
        socket_on=screen_socket,
    )
    side_w = (width - 0.05 - screen_w - 0.06) / 2
    if side_w > 0.06:
        sx = screen_w / 2 + 0.03 + side_w / 2
        cols = max(2, int((side_w - 0.02) / 0.026))
        button_bank(
            lamps,
            detail,
            slope @ tr(-sx, 0.0),
            cols,
            6,
            (0.026, 0.032),
            (0.018, 0.02),
            seed + 2,
            lit=0.5,
            palette=palette,
        )
        slat_stack(
            lamps,
            detail,
            slope @ tr(sx, 0.03),
            4,
            side_w - 0.04,
            0.012,
            0.016,
            seed=seed + 3,
            lit=0.75,
        )
    top = matrix @ frame_on_slope((0.0, 0.49, 1.38), 90.0)
    with xform(detail, top):  # thin red trim along the hood's front edge
        detail.box((-half + 0.04, -0.068, 0.0), (half - 0.04, -0.056, 0.003), ACCENT_RED)
    with xform(lamps, top):
        for i in range(3):
            lx = -0.08 + i * 0.08
            lamps.box(
                (lx - 0.012, -0.02, 0.0),
                (lx + 0.012, 0.0, 0.007),
                (LAMP_WHITE, LAMP_RED, LAMP_WHITE)[i],
            )
    m = matrix
    oriented_box_occluder(m, (-half, 0.0, 0.0), (half, 0.62, 1.04))
    oriented_box_occluder(m, (-half, 0.26, 1.04), (half, 0.62, 1.39))


@kit.piece("SM_Console_Standing", dims=(1.00, 0.63, 1.39))
def standing_console() -> None:
    """Standing operator console; SOCKET_screen/stand ''."""
    mbs = builders()
    standing_unit(mbs, tr(), 1.0, 41, "")
    finish_all(mbs)
    stand_socket("", 0.0, -0.32, 0.0)
    anchor("centre")


# --------------------------------------------------------------------------
# Wall terminal
# --------------------------------------------------------------------------


@kit.piece("SM_Terminal_Wall", dims=(0.84, 0.30, 1.32))
def wall_terminal() -> None:
    """Wall-mounted terminal (anchor: back on the wall face, local Y = 0)."""
    mbs = builders()
    body, trim, detail, lamps = mbs["body"], mbs["trim"], mbs["detail"], mbs["lamps"]
    # Built with the wall at Y = 0 and the terminal toward -Y.
    trim.box((-0.42, -0.04, 0.80), (0.42, 0.0, 2.12), STEEL)
    body.prism_x(
        ((-0.04, 0.86), (-0.30, 1.02), (-0.30, 1.07), (-0.16, 1.16), (-0.04, 1.16)),
        -0.38,
        0.38,
        BODY,
    )
    body.prism_x(((-0.04, 1.20), (-0.15, 1.24), (-0.07, 1.92), (-0.04, 1.96)), -0.38, 0.38, BODY)
    work = frame_on_slope((0.0, -0.19, 1.06), 70.0)
    keyboard(detail, work @ tr(-0.05, 0.0), w=0.38, d=0.12)
    button_bank(
        lamps, detail, work @ tr(0.25, 0.0), 2, 3, (0.028, 0.028), (0.02, 0.02), 51, lit=0.5
    )
    slope = frame_on_slope((0.0, -0.11, 1.58), 7.0)
    screen(f"{pname()}_screen", slope, 0.50, 0.34, detail)
    slat_stack(
        lamps, detail, frame_on_slope((0.0, -0.075, 1.85), 7.0), 2, 0.5, 0.012, 0.016, seed=52
    )
    with xform(lamps, frame_on_slope((0.0, -0.045, 2.04), 0.0)):
        for i, mat in enumerate((LAMP_RED, LAMP_WHITE, LAMP_WHITE, LAMP_GREEN)):
            lamps.box((-0.3 + i * 0.03, -0.008, 0.0), (-0.282 + i * 0.03, 0.008, 0.006), mat)
    finish_all(mbs)
    stand_socket("", 0.0, -0.65, 0.0)
    box_occluder((-0.42, -0.30, 0.80), (0.42, 0.0, 2.12))
    anchor("wall")


# --------------------------------------------------------------------------
# Commander's command station
# --------------------------------------------------------------------------


@kit.piece("SM_Console_Command", dims=(3.28, 1.18, 1.39))
def command_station() -> None:
    """Commander's standing station: three faceted modules around the
    commander's spot. SOCKET_station/stand '', SOCKET_screen 'c','l','r'."""
    mbs = builders()
    r = 0.55
    standing_unit(mbs, tr(0.0, r), 1.1, 61, "c", screen_w=0.52)
    for side, sid in ((-1, "l"), (1, "r")):
        # Side module hinged at the centre module's front corner.
        hinge = tr(side * 0.55, r, 0.0, side * -38.0)
        standing_unit(mbs, hinge @ tr(side * 0.45), 0.9, 67 + side, sid, screen_w=0.40)
        _command_pillar(mbs, side, r)
    finish_all(mbs)
    stand_socket("", 0.0, 0.0, 0.0, kind="station")
    stand_socket("", 0.0, 0.0, 0.0)
    anchor("centre")


def _command_pillar(mbs, side: int, r: float) -> None:
    """Instrument pillar filling the wedge between the centre and a wing."""
    a = math.radians(side * -38.0)
    inner_back = (side * 0.55 + -math.sin(a) * 0.62, r + math.cos(a) * 0.62)
    pts = [(side * 0.55, r + 0.62), (side * 0.55, r + 0.02), inner_back]
    if side < 0:
        pts = list(reversed(pts))
    mbs["trim"].prism_z(pts, 0.0, 1.30, BODY)
    cx = sum(p[0] for p in pts) / 3
    cy = sum(p[1] for p in pts) / 3
    with xform(mbs["lamps"], tr(cx, cy, 1.30)):
        mbs["lamps"].box((-0.015, -0.05, 0.0), (0.015, 0.05, 0.006), BACKLIT)


# --------------------------------------------------------------------------
# Master systems console
# --------------------------------------------------------------------------


@kit.piece("SM_Console_MasterSystems", dims=(6.20, 0.95, 2.62))
def master_systems_console() -> None:
    """Long standing desk under a three-screen display gantry flanked by
    instrument towers. SOCKET_screen '1'-'3' (gantry) and 'd1'-'d4' (desk),
    SOCKET_station ''."""
    mbs = builders()
    body, trim, detail, lamps = mbs["body"], mbs["trim"], mbs["detail"], mbs["lamps"]
    for i in range(4):
        x = -1.8 + i * 1.2
        standing_unit(
            mbs, tr(x, 0.0), 1.2, 71 + i, f"d{i + 1}", screen_w=0.42, palette=LAMP_PALETTE_COOL
        )
    # Gantry frame behind the desk.
    trim.box((-2.45, 0.66, 0.0), (2.45, 0.92, 0.10), SATIN)
    for x in (-2.42, -0.64, 0.64, 2.42):
        trim.box((x - 0.05, 0.70, 0.0), (x + 0.05, 0.90, 2.60), STEEL)
    trim.box((-2.47, 0.70, 2.48), (2.47, 0.90, 2.62), STEEL)
    body.box((-2.37, 0.80, 1.40), (2.37, 0.92, 2.48), BODY)
    for i, x in enumerate((-1.27, 0.0, 1.27)):
        f = frame_on_slope((x, 0.76, 1.95), 12.0)
        screen(
            f"{pname()}_gantry{i + 1}",
            f,
            1.12,
            0.64,
            detail,
            local_id=str(i + 1),
            border=0.03,
            depth=0.06,
        )
    slat_stack(lamps, detail, frame_on_slope((0.0, 0.795, 1.52), 0.0), 2, 3.6, 0.014, 0.02, seed=77)
    # Instrument towers.
    for side in (-1, 1):
        cx = side * 2.78
        body.box((cx - 0.30, 0.20, 0.0), (cx + 0.30, 0.92, 2.30), BODY)
        trim.box((cx - 0.32, 0.18, 2.24), (cx + 0.32, 0.94, 2.34), BODY)
        trim.box((cx - 0.32, 0.18, 0.0), (cx + 0.32, 0.94, 0.08), SATIN)
        face = frame_on_slope((cx, 0.20, 1.55), 0.0)
        slat_stack(lamps, detail, face @ tr(0.0, 0.28), 6, 0.40, 0.016, 0.022, seed=80 + side)
        button_bank(
            lamps,
            detail,
            face @ tr(0.0, -0.22),
            8,
            7,
            (0.05, 0.05),
            (0.032, 0.032),
            90 + side,
            lit=0.45,
            palette=LAMP_PALETTE_COOL,
        )
        button_bank(
            lamps,
            detail,
            face @ tr(0.0, -0.75),
            4,
            3,
            (0.08, 0.07),
            (0.05, 0.045),
            95 + side,
            lit=0.3,
            palette=LAMP_PALETTE_BRIDGE,
        )
        top = frame_on_slope((cx, 0.56, 2.34), 90.0)
        button_bank(lamps, detail, top, 5, 6, (0.07, 0.07), (0.045, 0.045), 99 + side, lit=0.35)
    finish_all(mbs)
    stand_socket("", 0.0, -0.55, 0.0, kind="station")
    for i in range(4):
        stand_socket(f"d{i + 1}", -1.8 + i * 1.2, -0.35, 0.0)
    box_occluder((-2.47, 0.66, 0.0), (2.47, 0.94, 2.62))
    for side in (-1, 1):
        box_occluder((side * 2.78 - 0.32, 0.18, 0.0), (side * 2.78 + 0.32, 0.94, 2.34))
    anchor("centre")


# --------------------------------------------------------------------------
# Engineering terminal
# --------------------------------------------------------------------------


@kit.piece("SM_Terminal_Desk", dims=(1.35, 1.54, 1.29))
def engineering_terminal() -> None:
    """Seated desk workstation: steel desk, tilted monitor, equipment tower,
    operator chair (offices, quartermaster, med bay). SOCKET_seat/screen/stand ''."""
    mbs = builders()
    body, trim, detail, lamps = mbs["body"], mbs["trim"], mbs["detail"], mbs["lamps"]
    # Desk frame: the front edge at Y = 0, depth 0.78.
    for x in (-0.60, 0.33):
        trim.box((x - 0.03, 0.03, 0.0), (x + 0.03, 0.74, 0.72), STEEL)
        trim.box((x - 0.035, 0.0, 0.0), (x + 0.035, 0.78, 0.05), SATIN)
    trim.box((-0.63, 0.66, 0.30), (0.36, 0.72, 0.72), STEEL)
    trim.box((-0.66, -0.01, 0.72), (0.40, 0.78, 0.755), BODY_LIGHT)
    detail.box((-0.66, -0.022, 0.712), (0.40, -0.006, 0.762), SATIN)
    # Equipment tower at the right.
    body.box((0.40, 0.08, 0.0), (0.68, 0.78, 1.24), BODY)
    trim.box((0.39, 0.07, 1.20), (0.69, 0.79, 1.26), BODY)
    face = frame_on_slope((0.54, 0.08, 0.0), 0.0)
    slat_stack(lamps, detail, face @ tr(0.0, 1.06), 3, 0.18, 0.012, 0.016, seed=121)
    button_bank(
        lamps,
        detail,
        face @ tr(0.0, 0.86),
        4,
        4,
        (0.04, 0.035),
        (0.026, 0.022),
        122,
        lit=0.5,
        palette=LAMP_PALETTE_ENGINE,
    )
    with xform(detail, face):
        for i in range(3):
            z = 0.18 + i * 0.16
            detail.box((-0.11, z, 0.0), (0.11, z + 0.12, 0.006), STEEL)
            detail.box((-0.08, z + 0.05, 0.006), (0.08, z + 0.065, 0.01), SATIN)
    top = frame_on_slope((0.54, 0.43, 1.26), 90.0)
    button_bank(
        lamps,
        detail,
        top,
        3,
        6,
        (0.06, 0.07),
        (0.04, 0.045),
        123,
        lit=0.4,
        palette=LAMP_PALETTE_ENGINE,
    )
    # Monitor on a stand.
    detail.box((-0.20, 0.46, 0.755), (0.08, 0.62, 0.77), SATIN)
    trim.box((-0.09, 0.52, 0.76), (-0.03, 0.58, 0.92), STEEL)
    mon = frame_on_slope((-0.06, 0.52, 1.10), 20.0)
    with xform(body, mon):
        body.box((-0.34, -0.21, -0.07), (0.34, 0.21, -0.02), SATIN)
    screen(f"{pname()}_screen", mon, 0.62, 0.36, detail, border=0.02)
    desk = frame_on_slope((-0.10, 0.20, 0.755), 90.0)
    keyboard(detail, desk, w=0.44, d=0.15)
    button_bank(
        lamps,
        detail,
        desk @ tr(-0.38, 0.0),
        2,
        4,
        (0.03, 0.03),
        (0.022, 0.022),
        124,
        lit=0.4,
        palette=LAMP_PALETTE_ENGINE,
    )
    detail.box((0.18, 0.12, 0.755), (0.30, 0.26, 0.765), SATIN)
    with xform(lamps, tr(0.36, 0.0, 0.70)):
        lamps.box((0.0, -0.004, 0.0), (0.03, 0.0, 0.01), LAMP_AMBER)
    finish_all(mbs)
    office_chair(f"{pname()}_chair", -0.10, -0.38, 0.0, "operator", seat_id="")
    stand_socket("", -0.10, -1.0, 180.0)
    box_occluder((-0.66, -0.03, 0.0), (0.69, 0.79, 0.77))
    box_occluder((0.39, 0.07, 0.77), (0.69, 0.79, 1.26))
    oriented_box_occluder(mon, (-0.34, -0.21, -0.07), (0.34, 0.21, 0.01))
    anchor("centre")


# --------------------------------------------------------------------------
# Instructor console
# --------------------------------------------------------------------------


@kit.piece("SM_Console_Instructor", dims=(2.10, 1.62, 1.21))
def instructor_console() -> None:
    """Seated instructor console with an angled side wing. SOCKET_seat,
    screen and stand '', wing screen 'aux'."""
    mbs = builders()
    seated_unit(mbs, 0.0, 1.10, 131, "", palette=LAMP_PALETTE_COOL, screen_w=0.50)
    wing = tr(0.55, 0.0, 0.0, -30.0)
    body, trim, detail, lamps = mbs["body"], mbs["trim"], mbs["detail"], mbs["lamps"]
    profile = ((0.0, 0.0), (0.62, 0.0), (0.62, 0.90), (0.45, 0.94), (0.0, 0.80))
    with xform(body, wing), xform(trim, wing):
        body.prism_x(profile, 0.02, 0.76, BODY)
        trim.prism_x(
            ((-0.01, 0.0), (0.63, 0.0), (0.63, 0.91), (0.455, 0.952), (-0.01, 0.812)),
            0.76,
            0.79,
            STEEL,
        )
    panel = wing @ frame_on_slope((0.39, 0.22, 0.87), 76.0)
    screen(f"{pname()}_screen_aux", panel @ tr(-0.06, 0.0), 0.36, 0.22, detail, local_id="aux")
    button_bank(
        lamps,
        detail,
        panel @ tr(0.24, 0.0),
        2,
        5,
        (0.03, 0.03),
        (0.02, 0.02),
        133,
        lit=0.5,
        palette=LAMP_PALETTE_COOL,
    )
    oriented_box_occluder(wing, (0.0, 0.0, 0.0), (0.79, 0.63, 0.95))
    finish_all(mbs)
    anchor("centre")


# Kept for deck builders that want a bare technician stool at a terminal bank.
__all__ = ["seated_unit", "standing_unit", "stool"]
