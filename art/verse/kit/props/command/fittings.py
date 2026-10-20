"""Room fittings: display case, lectern, rank board, drink dispenser, serving
and quartermaster counters, uniform lockers, fitting platform.

Wall pieces (rank board, dispenser, lockers) use the ``wall`` anchor: their
back sits on local Y = 0, the room face of a wall piece, and they extend
toward -Y. They are built that way directly.
"""

from __future__ import annotations

import math

from lib import kit

from ._base import (
    BACKLIT,
    BODY,
    BODY_LIGHT,
    CHROME,
    DARK_PANEL,
    FABRIC,
    GLASS,
    GLOSS,
    LAMP_GREEN,
    LAMP_PALETTE_COOL,
    LAMP_RED,
    LAMP_WHITE,
    RANK_BLUE,
    RANK_GOLD,
    RANK_RED,
    RUBBER,
    SATIN,
    STEEL,
    UNIFORM_CLOTH,
    anchor,
    box_occluder,
    builders,
    button_bank,
    cushion,
    finish_all,
    frame_on_slope,
    keyboard,
    lathe,
    oriented_box_occluder,
    pname,
    prism_occluder,
    screen,
    slat_stack,
    stand_socket,
    tr,
    xform,
)

# --------------------------------------------------------------------------
# Display case
# --------------------------------------------------------------------------


@kit.piece("SM_Case_Display", dims=(1.22, 0.58, 1.40))
def display_case() -> None:
    """Glass-topped commendation case on a steel plinth, lit from inside."""
    mbs = builders()
    body, trim, detail, lamps = mbs["body"], mbs["trim"], mbs["detail"], mbs["lamps"]
    w, d = 0.60, 0.28
    trim.box((-w + 0.03, -d + 0.03, 0.0), (w - 0.03, d - 0.03, 0.06), SATIN)
    body.box((-w, -d, 0.06), (w, d, 0.86), STEEL)
    trim.box((-w - 0.005, -d - 0.005, 0.86), (w + 0.005, d + 0.005, 0.885), BODY_LIGHT)
    detail.box((-w + 0.05, -d - 0.004, 0.16), (w - 0.05, -d, 0.76), BODY)
    # Glass hood with a steel frame.
    g = 0.006
    z0, z1 = 0.885, 1.36
    for sy in (-1, 1):
        detail.box((-w + 0.02, sy * (d - 0.02) - g, z0), (w - 0.02, sy * (d - 0.02) + g, z1), GLASS)
    for sx in (-1, 1):
        detail.box((sx * (w - 0.02) - g, -d + 0.02, z0), (sx * (w - 0.02) + g, d - 0.02, z1), GLASS)
    detail.box((-w + 0.02, -d + 0.02, z1 - g), (w - 0.02, d - 0.02, z1 + g), GLASS)
    for sx in (-1, 1):
        for sy in (-1, 1):
            trim.box(
                (sx * (w - 0.005) - 0.016, sy * (d - 0.005) - 0.016, z0),
                (sx * (w - 0.005) + 0.016, sy * (d - 0.005) + 0.016, z1 + 0.03),
                STEEL,
            )
    trim.box((-w, -d, z1 + 0.006), (w, d, z1 + 0.04), STEEL)
    lamps.box((-w + 0.06, -0.02, z1 - 0.002), (w - 0.06, 0.02, z1 + 0.004), LAMP_WHITE)
    # Contents: a dark velvet bed, a plaque, a medal, a baton.
    detail.box((-w + 0.03, -d + 0.03, z0), (w - 0.03, d - 0.03, z0 + 0.015), SATIN)
    with xform(detail, tr(-0.30, 0.02, z0 + 0.015, rx_deg=-18.0)):
        detail.box((-0.14, -0.005, 0.0), (0.14, 0.012, 0.20), GLOSS)
        detail.box((-0.12, -0.009, 0.03), (0.12, -0.004, 0.17), RANK_GOLD)
    with xform(detail, tr(0.08, -0.04, z0 + 0.015)):
        lathe(detail, ((0.0, 0.0), (0.07, 0.0), (0.07, 0.012), (0.0, 0.012)), BODY, 32)
        lathe(detail, ((0.0, 0.012), (0.05, 0.012), (0.048, 0.02), (0.0, 0.022)), RANK_GOLD, 32)
    detail.tube((0.26, -0.10, z0 + 0.03), (0.50, 0.08, z0 + 0.03), 0.018, CHROME, 16)
    finish_all(mbs)
    stand_socket("", 0.0, -0.70, 0.0)
    box_occluder((-w, -d, 0.0), (w, d, z1 + 0.04))
    anchor("centre")


# --------------------------------------------------------------------------
# Lectern
# --------------------------------------------------------------------------


@kit.piece("SM_Lectern", dims=(0.66, 0.50, 1.13))
def lectern() -> None:
    """Speaker's lectern with a sloped reading desk facing its user (-Y side)."""
    mbs = builders()
    body, trim, detail, lamps = mbs["body"], mbs["trim"], mbs["detail"], mbs["lamps"]
    trim.box((-0.30, -0.24, 0.0), (0.30, 0.26, 0.03), SATIN)
    body.prism_x(((-0.15, 0.03), (0.17, 0.03), (0.13, 1.0), (-0.11, 1.0)), -0.22, 0.22, BODY)
    trim.prism_x(((-0.155, 0.03), (0.175, 0.03), (0.135, 1.0), (-0.115, 1.0)), -0.235, -0.22, STEEL)
    trim.prism_x(((-0.155, 0.03), (0.175, 0.03), (0.135, 1.0), (-0.115, 1.0)), 0.22, 0.235, STEEL)
    desk = frame_on_slope((0.0, 0.02, 1.08), 76.0)
    with xform(trim, desk):
        trim.box((-0.33, -0.22, -0.05), (0.33, 0.22, 0.0), BODY_LIGHT)
        trim.box((-0.33, -0.235, -0.05), (0.33, -0.22, 0.02), SATIN)
    screen(f"{pname()}_screen", desk @ tr(0.06, 0.04), 0.30, 0.18, detail)
    button_bank(lamps, detail, desk @ tr(-0.22, 0.04), 2, 4, (0.03, 0.03), (0.02, 0.02), 501)
    finish_all(mbs)
    stand_socket("", 0.0, -0.48, 0.0)
    box_occluder((-0.33, -0.25, 0.0), (0.33, 0.26, 1.15))
    anchor("centre")


# --------------------------------------------------------------------------
# Rank board
# --------------------------------------------------------------------------

# (tile material, tile count) per rank plate, ladder order (BRIEF section 8).
_RANK_PLATES = (
    [(CHROME, n) for n in (1, 2, 3, 4)]
    + [(RANK_BLUE, n) for n in (1, 2, 3, 4, 5)]
    + [(RANK_RED, n) for n in (3, 4)]
    + [(RANK_GOLD, n) for n in (3, 4, 5, 6)]
)


def _rank_plate(detail: kit.MeshBuilder, frame, x: float, y: float, mat: str, n: int) -> None:
    with xform(detail, frame @ tr(x, y)):
        detail.box((-0.17, -0.045, 0.0), (0.17, 0.045, 0.012), CHROME)
        detail.box((-0.16, -0.036, 0.012), (0.16, 0.036, 0.015), SATIN)
        for row in range(2):
            for col in range(3):
                i = row * 3 + col
                if i >= n:
                    continue
                tx = -0.055 + col * 0.055
                ty = 0.017 - row * 0.034
                detail.box((tx - 0.022, ty - 0.012, 0.015), (tx + 0.022, ty + 0.012, 0.021), mat)


@kit.piece("SM_Board_Rank", dims=(3.60, 0.52, 2.50))
def rank_board() -> None:
    """Wall-mounted rank board: the ladder's 15 rank plates either side of a
    live screen. Anchor: wall. SOCKET_screen/station/stand ''."""
    mbs = builders()
    body, trim, detail, lamps = mbs["body"], mbs["trim"], mbs["detail"], mbs["lamps"]
    trim.box((-1.80, -0.06, 0.70), (1.80, 0.0, 3.20), STEEL)
    face = frame_on_slope((0.0, -0.26, 1.95), 10.0)
    with xform(body, face):
        body.box((-1.72, -1.15, -0.10), (1.72, 1.15, 0.0), BODY)
    with xform(trim, face):
        trim.box((-1.74, 1.02, 0.0), (1.74, 1.15, 0.02), STEEL)
        trim.box((-1.74, -1.15, 0.0), (1.74, -1.06, 0.02), STEEL)
        trim.box((-0.92, -1.06, 0.0), (-0.88, 1.02, 0.015), STEEL)
        trim.box((0.88, -1.06, 0.0), (0.92, 1.02, 0.015), STEEL)
    slat_stack(lamps, detail, face @ tr(0.0, 1.085), 1, 3.2, 0.03, 0.0, frame_mat=SATIN)
    screen(f"{pname()}_screen", face @ tr(0.0, 0.22), 1.62, 0.92, detail, border=0.03)
    for i in range(5):
        x = -0.72 + i * 0.36
        with xform(detail, face @ tr(x, -0.58)):
            detail.box((-0.15, -0.10, 0.0), (0.15, 0.10, 0.01), SATIN)
        slat_stack(lamps, detail, face @ tr(x, -0.58), 2, 0.22, 0.012, 0.03, seed=520 + i)
    left, right = _RANK_PLATES[:8], _RANK_PLATES[8:]
    for col, plates in ((-1.31, left), (1.31, right)):
        for row, (mat, n) in enumerate(plates):
            _rank_plate(detail, face, col, 0.86 - row * 0.235, mat, n)
    with xform(lamps, face):
        for x in (-1.31, 1.31):
            lamps.box((x - 0.20, 0.97, 0.0), (x + 0.20, 0.985, 0.006), LAMP_WHITE)
    finish_all(mbs)
    stand_socket("", 0.0, -1.30, 0.0, kind="station")
    stand_socket("", 0.0, -1.30, 0.0)
    oriented_box_occluder(face, (-1.74, -1.15, -0.10), (1.74, 1.15, 0.03))
    anchor("wall")


# --------------------------------------------------------------------------
# Drink dispenser
# --------------------------------------------------------------------------


@kit.piece("SM_Dispenser", dims=(0.92, 0.52, 2.02))
def dispenser() -> None:
    """Wall drink dispenser with a lit bay, three nozzles and a drip grille.
    Anchor: wall. SOCKET_screen/stand ''."""
    mbs = builders()
    body, trim, detail, lamps = mbs["body"], mbs["trim"], mbs["detail"], mbs["lamps"]
    w, d = 0.45, 0.48
    trim.box((-w + 0.02, -d + 0.04, 0.0), (w - 0.02, 0.0, 0.08), SATIN)
    body.box((-w, -d, 0.08), (w, 0.0, 0.95), BODY_LIGHT)
    body.box((-w, -d, 1.38), (w, 0.0, 2.0), BODY_LIGHT)
    for sx in (-1, 1):
        body.box((sx * w - 0.06 * sx, -d, 0.95), (sx * w, 0.0, 1.38), BODY_LIGHT)
    trim.box((-w + 0.06, -0.16, 0.95), (w - 0.06, 0.0, 1.38), STEEL)
    trim.box((-w - 0.01, -d - 0.01, 1.98), (w + 0.01, 0.01, 2.02), DARK_PANEL)
    # Bay: light in its ceiling, nozzles, drip grille.
    lamps.box((-w + 0.10, -d + 0.08, 1.372), (w - 0.10, -0.20, 1.378), BACKLIT)
    for i in range(3):
        x = -0.18 + i * 0.18
        detail.tube((x, -0.30, 1.38), (x, -0.30, 1.30), 0.016, CHROME, 12)
        detail.tube((x, -0.30, 1.30), (x, -0.30, 1.27), 0.009, CHROME, 12)
    trim.box((-w + 0.07, -d - 0.03, 0.95), (w - 0.07, -0.16, 0.975), CHROME)
    for i in range(12):
        x = -0.34 + i * 0.062
        detail.box((x - 0.012, -d - 0.025, 0.975), (x + 0.012, -0.17, 0.979), SATIN)
    # Upper cabinet: menu screen and selector keys; lower: two doors.
    front = frame_on_slope((0.0, -d, 1.70), 0.0)
    screen(f"{pname()}_screen", front @ tr(-0.07, 0.04), 0.48, 0.28, detail, border=0.02)
    button_bank(
        lamps,
        detail,
        front @ tr(0.31, 0.04),
        1,
        5,
        (0.03, 0.045),
        (0.035, 0.03),
        531,
        lit=0.6,
        palette=((LAMP_WHITE, 0.7), (LAMP_GREEN, 0.3)),
    )
    with xform(detail, frame_on_slope((0.0, -d, 0.0), 0.0)):
        for sx in (-1, 1):
            detail.box((sx * 0.005, 0.14, 0.0), (sx * (w - 0.02), 0.90, 0.006), BODY)
            detail.box((sx * 0.03, 0.75, 0.006), (sx * 0.05, 0.85, 0.02), CHROME)
    finish_all(mbs)
    stand_socket("", 0.0, -0.95, 0.0)
    box_occluder((-w, -d - 0.03, 0.0), (w, 0.0, 2.02))
    anchor("wall")


# --------------------------------------------------------------------------
# Counters
# --------------------------------------------------------------------------


def _counter_carcass(mbs, w: float, top_mat: str) -> None:
    """Counter body 0.9 m deep with a fluted front facing the camera."""
    body, trim, detail = mbs["body"], mbs["trim"], mbs["detail"]
    trim.box((-w / 2 + 0.04, -0.41, 0.0), (w / 2 - 0.04, 0.45, 0.08), SATIN)
    body.box((-w / 2, -0.45, 0.08), (w / 2, 0.45, 0.90), BODY)
    n = int(w / 0.3)
    for i in range(n):
        x = -w / 2 + (i + 0.5) * w / n
        detail.box((x - 0.11, -0.458, 0.14), (x + 0.11, -0.45, 0.84), BODY_LIGHT)
    slab_lo, slab_hi = (-w / 2 - 0.02, -0.52, 0.90), (w / 2 + 0.02, 0.47, 0.94)
    trim.box(slab_lo, slab_hi, top_mat)


@kit.piece("SM_Counter_Serving", dims=(4.84, 1.15, 1.27))
def serving_counter() -> None:
    """Mess serving counter: steam-table wells, a pass shelf with lamps on the
    galley side, tray rail on the crew side. SOCKET_station '' (crew side),
    SOCKET_stand 'server' (galley side)."""
    mbs = builders()
    trim, detail, lamps = mbs["trim"], mbs["detail"], mbs["lamps"]
    w = 4.8
    _counter_carcass(mbs, w, BODY)
    for i in range(5):
        x = -1.84 + i * 0.92
        detail.box((x - 0.36, -0.20, 0.925), (x + 0.36, 0.22, 0.942), CHROME)
        detail.box((x - 0.33, -0.17, 0.928), (x + 0.33, 0.19, 0.944), GLOSS)
    # Pass shelf on posts behind the wells (galley side), lamps under it.
    for x in (-2.3, -0.92, 0.92, 2.3):
        detail.tube((x, 0.33, 0.94), (x, 0.33, 1.24), 0.014, CHROME, 12)
    trim.box((-2.36, 0.24, 1.24), (2.36, 0.44, 1.27), DARK_PANEL)
    trim.box((-2.36, 0.235, 1.235), (2.36, 0.245, 1.275), CHROME)
    for i in range(5):
        x = -1.84 + i * 0.92
        lamps.box((x - 0.28, 0.27, 1.234), (x + 0.28, 0.33, 1.24), BACKLIT)
    for z in (0.78, 0.84):
        detail.tube((-2.35, -0.66, z), (2.35, -0.66, z), 0.016, CHROME, 12)
    for x in (-2.2, -0.73, 0.73, 2.2):
        detail.box((x - 0.012, -0.66, 0.77), (x + 0.012, -0.45, 0.85), CHROME)
    finish_all(mbs)
    stand_socket("", 0.0, -1.0, 0.0, kind="station")
    stand_socket("server", 0.0, 0.85, 180.0)
    box_occluder((-2.42, -0.68, 0.0), (2.42, 0.47, 0.94))
    box_occluder((-2.36, 0.24, 0.94), (2.36, 0.44, 1.275), nav="none")
    anchor("centre")


@kit.piece("SM_Counter_Quartermaster", dims=(3.04, 0.99, 1.25))
def quartermaster_counter() -> None:
    """Issue counter: terminal, folded tunics, a scanner pad.
    SOCKET_screen/station '' (crew side), SOCKET_stand 'clerk'."""
    mbs = builders()
    trim, detail, lamps, soft = mbs["trim"], mbs["detail"], mbs["lamps"], mbs["soft"]
    w = 3.0
    _counter_carcass(mbs, w, BODY_LIGHT)
    term = frame_on_slope((0.75, 0.10, 1.10), 28.0)
    with xform(trim, term):
        trim.box((-0.26, -0.17, -0.10), (0.26, 0.17, -0.01), BODY)
    trim.box((0.60, 0.05, 0.94), (0.90, 0.25, 0.98), STEEL)
    screen(f"{pname()}_screen", term, 0.44, 0.27, detail, border=0.02)
    keyboard(detail, frame_on_slope((0.70, -0.24, 0.94), 90.0), w=0.40, d=0.14)
    # Folded tunics, two stacks.
    for sx, n in ((-0.95, 4), (-0.45, 3)):
        for k in range(n):
            z = 0.94 + k * 0.045
            mat = UNIFORM_CLOTH if k % 2 == 0 else FABRIC
            cushion(
                soft,
                0.36,
                0.30,
                z,
                0.042,
                mat,
                corner=0.03,
                edge=0.015,
                cx=sx + 0.004 * k,
                cy=-0.02,
            )
    detail.box((-0.10, -0.30, 0.94), (0.14, -0.10, 0.96), SATIN)
    lamps.box((-0.06, -0.26, 0.96), (0.10, -0.14, 0.964), LAMP_GREEN)
    button_bank(
        lamps,
        detail,
        frame_on_slope((1.25, -0.25, 0.94), 90.0),
        3,
        2,
        (0.03, 0.03),
        (0.02, 0.02),
        541,
        lit=0.5,
        palette=LAMP_PALETTE_COOL,
    )
    finish_all(mbs)
    stand_socket("", 0.0, -0.95, 0.0, kind="station")
    stand_socket("clerk", 0.0, 0.85, 180.0)
    box_occluder((-1.52, -0.52, 0.0), (1.52, 0.47, 0.98))
    anchor("centre")


# --------------------------------------------------------------------------
# Uniform lockers
# --------------------------------------------------------------------------


@kit.piece("SM_Lockers_Uniform", dims=(2.42, 0.58, 2.14), count=4)
def uniform_lockers(count: int) -> None:
    """Bank of tall uniform lockers (0.6 m doors). Anchor: wall.
    SOCKET_stand '1'..'n' in front of each door."""
    mbs = builders()
    body, trim, detail, lamps = mbs["body"], mbs["trim"], mbs["detail"], mbs["lamps"]
    w = 0.6 * count
    d = 0.54
    trim.box((-w / 2 + 0.02, -d + 0.04, 0.0), (w / 2 - 0.02, 0.0, 0.10), SATIN)
    body.box((-w / 2, -d, 0.10), (w / 2, 0.0, 2.10), BODY)
    trim.box((-w / 2 - 0.01, -d - 0.02, 2.10), (w / 2 + 0.01, 0.0, 2.14), DARK_PANEL)
    for i in range(count):
        x = -w / 2 + 0.3 + i * 0.6
        with xform(detail, frame_on_slope((x, -d, 0.0), 0.0)):
            detail.box((-0.285, 0.13, 0.0), (0.285, 2.07, 0.008), DARK_PANEL)
            for k in range(6):
                vy = 1.80 + k * 0.035
                detail.box((-0.18, vy, 0.008), (0.18, vy + 0.016, 0.011), SATIN)
                detail.box(
                    (-0.18, 0.30 + k * 0.035, 0.008), (0.18, 0.316 + k * 0.035, 0.011), SATIN
                )
            detail.box((0.20, 1.02, 0.008), (0.225, 1.22, 0.04), CHROME)
            detail.box((-0.12, 1.55, 0.008), (0.12, 1.62, 0.012), SATIN)
        with xform(lamps, frame_on_slope((x, -d, 0.0), 0.0)):
            mat = LAMP_GREEN if i % 3 else LAMP_RED
            lamps.box((0.15, 1.575, 0.012), (0.165, 1.595, 0.018), mat)
    finish_all(mbs)
    for i in range(count):
        stand_socket(str(i + 1), -w / 2 + 0.3 + i * 0.6, -1.05, 0.0)
    box_occluder((-w / 2 - 0.01, -d - 0.02, 0.0), (w / 2 + 0.01, 0.0, 2.14))
    anchor("wall")


# --------------------------------------------------------------------------
# Fitting platform
# --------------------------------------------------------------------------


@kit.piece("SM_Platform_Fitting", dims=(2.30, 1.82, 2.10))
def fitting_platform() -> None:
    """Round fitting dais between two scanner pylons, a screen behind.
    SOCKET_stand '' on the dais (facing the camera), SOCKET_screen ''."""
    mbs = builders()
    body, trim, detail, lamps = mbs["body"], mbs["trim"], mbs["detail"], mbs["lamps"]
    lathe(
        trim,
        ((0.0, 0.0), (0.82, 0.0), (0.85, 0.03), (0.85, 0.10), (0.83, 0.12), (0.0, 0.12)),
        STEEL,
        96,
    )
    lathe(detail, ((0.0, 0.12), (0.72, 0.12), (0.72, 0.125), (0.0, 0.125)), RUBBER, 96)
    lathe(
        lamps,
        ((0.851, 0.035), (0.856, 0.035), (0.856, 0.05), (0.851, 0.05)),
        LAMP_WHITE,
        96,
        closed=True,
    )
    for sx in (-1, 1):
        x = sx * 1.05
        body.box((x - 0.09, 0.05, 0.0), (x + 0.09, 0.30, 2.10), BODY)
        trim.box((x - 0.10, 0.04, 2.04), (x + 0.10, 0.31, 2.10), STEEL)
        lamps.box((x - 0.015, 0.044, 0.25), (x + 0.015, 0.05, 1.95), BACKLIT)
    back = frame_on_slope((0.0, 0.80, 1.45), 8.0)
    with xform(body, back):
        body.box((-0.82, -0.58, -0.08), (0.82, 0.58, 0.0), BODY)
    trim.box((-0.20, 0.82, 0.0), (0.20, 0.96, 0.90), STEEL)
    screen(f"{pname()}_screen", back, 1.30, 0.80, detail, border=0.03)
    finish_all(mbs)
    stand_socket("", 0.0, 0.0, 180.0, z=0.12)
    pts = [
        (math.cos(math.radians(a)) * 0.85, math.sin(math.radians(a)) * 0.85)
        for a in range(0, 360, 30)
    ]
    prism_occluder(pts, 0.0, 0.12, nav="walk")
    oriented_box_occluder(back, (-0.82, -0.58, -0.08), (0.82, 0.58, 0.03))
    for sx in (-1, 1):
        box_occluder((sx * 1.05 - 0.10, 0.04, 0.0), (sx * 1.05 + 0.10, 0.31, 2.10))
    anchor("centre")
