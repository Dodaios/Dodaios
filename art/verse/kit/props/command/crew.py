"""Crew living props: mess table with benches, double bunk with lockers,
simulator pod, medical bed."""

from __future__ import annotations

from lib import kit

from ._base import (
    BLANKET,
    BODY,
    BODY_LIGHT,
    CHROME,
    DARK_PANEL,
    FABRIC,
    LAMP_GREEN,
    LAMP_PALETTE_COOL,
    LAMP_RED,
    LAMP_WHITE,
    LINEN,
    MED_WHITE,
    SATIN,
    SEAT_H,
    STEEL,
    VINYL,
    anchor,
    box_occluder,
    builders,
    bunk_socket,
    button_bank,
    cushion,
    finish_all,
    frame_on_slope,
    oriented_box_occluder,
    pname,
    rounded_rect,
    screen,
    seat_socket,
    slab,
    slat_stack,
    stand_socket,
    tr,
    xform,
)

# --------------------------------------------------------------------------
# Mess table
# --------------------------------------------------------------------------


@kit.piece("SM_Table_Mess", dims=(2.10, 1.56, 0.83))
def mess_table() -> None:
    """Steel mess table with two fixed benches, six places.
    SOCKET_seat '01'-'03' (camera side, left to right), '04'-'06' (far side,
    right to left)."""
    mbs = builders()
    body, trim, detail, soft = mbs["body"], mbs["trim"], mbs["detail"], mbs["soft"]
    slab(body, rounded_rect(2.10, 0.80, 0.03), 0.715, 0.75, BODY_LIGHT, chamfer=0.006)
    trim.box((-1.05, -0.405, 0.722), (1.05, -0.395, 0.745), CHROME)
    trim.box((-1.05, 0.395, 0.722), (1.05, 0.405, 0.745), CHROME)
    trim.box((-0.98, -0.30, 0.66), (0.98, 0.30, 0.715), STEEL)
    for x in (-0.80, 0.80):
        trim.box((x - 0.04, -0.04, 0.05), (x + 0.04, 0.04, 0.66), STEEL)
        trim.box((x - 0.05, -0.78, 0.0), (x + 0.05, 0.78, 0.05), STEEL)
        for sy in (-1, 1):
            trim.box((x - 0.03, sy * 0.62 - 0.03, 0.05), (x + 0.03, sy * 0.62 + 0.03, 0.40), STEEL)
    for sy in (-1, 1):
        y = sy * 0.62
        trim.box((-1.0, y - 0.16, 0.40), (1.0, y + 0.16, 0.425), STEEL)
        cushion(soft, 1.98, 0.30, 0.425, SEAT_H - 0.425, VINYL, corner=0.03, edge=0.012, cy=y)
    # Condiment caddy in the middle of the table.
    detail.box((-0.09, -0.05, 0.75), (0.09, 0.05, 0.77), SATIN)
    for i in range(3):
        detail.tube((-0.05 + i * 0.05, 0.0, 0.77), (-0.05 + i * 0.05, 0.0, 0.83), 0.016, CHROME, 12)
    finish_all(mbs)
    for k, x in enumerate((-0.68, 0.0, 0.68), start=1):
        seat_socket(f"{k:02d}", x, -0.62, 0.0)
    for k, x in enumerate((0.68, 0.0, -0.68), start=4):
        seat_socket(f"{k:02d}", x, 0.62, 180.0)
    box_occluder((-1.05, -0.40, 0.66), (1.05, 0.40, 0.75))
    for sy in (-1, 1):
        box_occluder((-1.0, sy * 0.62 - 0.16, 0.0), (1.0, sy * 0.62 + 0.16, SEAT_H))
    anchor("centre")


# --------------------------------------------------------------------------
# Double bunk
# --------------------------------------------------------------------------


def _bunk_bed(mbs, z_pan: float) -> None:
    """Mattress, blanket and pillow on a steel pan (head at -X)."""
    trim, soft = mbs["trim"], mbs["soft"]
    trim.box((-1.0, -0.45, z_pan), (1.0, 0.45, z_pan + 0.06), STEEL)
    trim.box((-1.0, -0.47, z_pan - 0.02), (1.0, -0.43, z_pan + 0.12), STEEL)
    cushion(soft, 1.94, 0.84, z_pan + 0.06, 0.14, FABRIC, corner=0.04, edge=0.03)
    cushion(soft, 1.30, 0.88, z_pan + 0.19, 0.03, BLANKET, corner=0.03, edge=0.012, cx=0.30)
    cushion(soft, 0.36, 0.56, z_pan + 0.20, 0.07, LINEN, corner=0.06, edge=0.03, cx=-0.72)


@kit.piece("SM_Bunk_Double", dims=(2.73, 1.00, 2.04))
def bunk_double() -> None:
    """Double bunk open to the camera, with a two-door locker at the foot end.
    SOCKET_bunk '1' (lower) and '2' (upper), head toward -X; SOCKET_stand ''."""
    mbs = builders()
    body, trim, detail, lamps = mbs["body"], mbs["trim"], mbs["detail"], mbs["lamps"]
    body.box((-1.07, 0.45, 0.0), (1.02, 0.49, 2.0), DARK_PANEL)
    body.box((-1.09, -0.47, 0.0), (-1.03, 0.49, 2.0), DARK_PANEL)
    for x in (-1.03, 0.98):
        for y in (-0.47, 0.43):
            trim.box((x, y, 0.0), (x + 0.05, y + 0.04, 2.02), STEEL)
    # Open top: only a slim head rail on the back panel, so the upper bunk shows.
    trim.box((-1.09, 0.43, 1.98), (1.04, 0.49, 2.04), DARK_PANEL)
    # Drawers under the lower bunk.
    body.box((-1.0, -0.43, 0.04), (1.0, 0.43, 0.30), BODY)
    with xform(detail, frame_on_slope((0.0, -0.43, 0.0), 0.0)):
        for sx in (-1, 1):
            detail.box((sx * 0.01, 0.06, 0.0), (sx * 0.97, 0.28, 0.006), BODY_LIGHT)
            detail.box((sx * 0.42, 0.20, 0.006), (sx * 0.56, 0.22, 0.02), CHROME)
    _bunk_bed(mbs, 0.32)
    _bunk_bed(mbs, 1.30)
    # Upper bunk guard rail and ladder at the foot end.
    detail.polyline_tube(
        ((-0.95, -0.45, 1.36), (-0.95, -0.45, 1.68), (0.35, -0.45, 1.68), (0.35, -0.45, 1.36)),
        0.014,
        CHROME,
        12,
    )
    for x in (0.70, 0.94):
        detail.tube((x, -0.50, 0.0), (x, -0.50, 1.80), 0.014, CHROME, 12)
    for z in (0.62, 0.92, 1.22, 1.52):
        detail.tube((0.70, -0.50, z), (0.94, -0.50, z), 0.012, CHROME, 12)
    # Reading lamps on the back panel.
    for z in (0.78, 1.76):
        detail.box((-0.90, 0.43, z), (-0.70, 0.45, z + 0.06), SATIN)
        lamps.box((-0.88, 0.428, z + 0.01), (-0.72, 0.432, z + 0.025), LAMP_WHITE)
    # Locker at the foot end, two doors facing the camera.
    body.box((1.07, -0.47, 0.08), (1.63, 0.49, 2.0), BODY)
    trim.box((1.08, -0.43, 0.0), (1.62, 0.47, 0.08), SATIN)
    trim.box((1.06, -0.49, 2.0), (1.64, 0.49, 2.04), DARK_PANEL)
    with xform(detail, frame_on_slope((1.35, -0.47, 0.0), 0.0)):
        for z0, z1 in ((0.12, 1.02), (1.06, 1.96)):
            detail.box((-0.26, z0, 0.0), (0.26, z1, 0.008), DARK_PANEL)
            for k in range(4):
                vy = z1 - 0.14 + k * 0.03
                detail.box((-0.14, vy, 0.008), (0.14, vy + 0.014, 0.011), SATIN)
            detail.box((0.18, z0 + 0.35, 0.008), (0.20, z0 + 0.52, 0.035), CHROME)
    with xform(lamps, frame_on_slope((1.35, -0.47, 0.0), 0.0)):
        lamps.box((-0.20, 1.80, 0.008), (-0.185, 1.815, 0.014), LAMP_GREEN)
        lamps.box((-0.20, 0.86, 0.008), (-0.185, 0.875, 0.014), LAMP_GREEN)
    finish_all(mbs)
    bunk_socket("1", 0.0, 0.0, 0.53, 90.0)
    bunk_socket("2", 0.0, 0.0, 1.51, 90.0)
    stand_socket("", 0.0, -0.95, 0.0)
    box_occluder((-1.0, -0.47, 1.28), (1.0, 0.45, 1.56))
    box_occluder((-1.0, -0.47, 0.0), (1.0, 0.45, 0.52))
    box_occluder((-1.09, 0.43, 0.0), (1.04, 0.49, 2.04))
    box_occluder((-1.09, -0.49, 0.0), (-1.03, 0.49, 2.04))
    box_occluder((1.06, -0.49, 0.0), (1.64, 0.49, 2.04))
    anchor("centre")


@kit.piece("SM_Bunk_Single", dims=(1.29, 2.57, 1.60))
def bunk_single() -> None:
    """Single-level berth running away from the camera (head at +Y), so the
    sleeper is fully visible; head unit with a shelf niche and a reading lamp,
    low side partitions. SOCKET_bunk '' (local -Y toward the feet),
    SOCKET_stand '' at the foot."""
    mbs = builders()
    body, trim, detail, lamps, soft = (
        mbs["body"],
        mbs["trim"],
        mbs["detail"],
        mbs["lamps"],
        mbs["soft"],
    )
    trim.box((-0.47, -1.10, 0.0), (0.47, 1.10, 0.08), SATIN)
    body.box((-0.46, -1.08, 0.08), (0.46, 1.08, 0.38), BODY)
    trim.box((-0.48, -1.10, 0.38), (0.48, 1.10, 0.42), STEEL)
    with xform(detail, frame_on_slope((0.0, -1.08, 0.0), 0.0)):
        detail.box((-0.42, 0.14, 0.0), (0.42, 0.32, 0.006), DARK_PANEL)
        detail.box((-0.08, 0.22, 0.006), (0.08, 0.24, 0.02), CHROME)
    cushion(soft, 0.88, 2.14, 0.42, 0.13, FABRIC, corner=0.04, edge=0.03)
    cushion(soft, 0.92, 1.30, 0.545, 0.03, BLANKET, corner=0.03, edge=0.012, cy=-0.38)
    cushion(soft, 0.92, 0.20, 0.57, 0.035, LINEN, corner=0.02, edge=0.012, cy=0.36)
    cushion(soft, 0.58, 0.34, 0.55, 0.08, LINEN, corner=0.07, edge=0.03, cy=0.82)
    # Head unit at +Y: a locker column with a shelf niche and the lamp.
    body.box((-0.60, 1.10, 0.0), (0.60, 1.46, 1.55), DARK_PANEL)
    trim.box((-0.61, 1.09, 1.55), (0.61, 1.47, 1.60), DARK_PANEL)
    detail.box((-0.42, 1.098, 0.72), (0.42, 1.30, 1.08), SATIN)
    detail.box((0.10, 1.12, 0.72), (0.28, 1.28, 0.88), STEEL)
    lamps.box((-0.20, 1.095, 1.05), (0.20, 1.10, 1.07), LAMP_WHITE)
    for sx in (-1, 1):
        x = sx * 0.62
        trim.box((x - 0.02, -0.90, 0.0), (x + 0.02, 1.46, 1.20), DARK_PANEL)
        trim.box((x - 0.025, -0.91, 1.20), (x + 0.025, 1.47, 1.23), STEEL)
    finish_all(mbs)
    bunk_socket("", 0.0, 0.15, 0.55, 0.0)
    stand_socket("", 0.0, -1.45, 0.0)
    box_occluder((-0.48, -1.10, 0.0), (0.48, 1.10, 0.55))
    box_occluder((-0.60, 1.09, 0.0), (0.60, 1.47, 1.60))
    for sx in (-1, 1):
        box_occluder((sx * 0.62 - 0.025, -0.91, 0.0), (sx * 0.62 + 0.025, 1.47, 1.23))
    anchor("centre")


# --------------------------------------------------------------------------
# Simulator pod
# --------------------------------------------------------------------------


@kit.piece("SM_Pod_Simulator", dims=(1.36, 2.02, 1.59))
def simulator_pod() -> None:
    """Open-backed simulator cockpit on a motion plinth: bucket seat, side
    sticks, a three-facet wrap screen. SOCKET_seat/screen/stand ''."""
    mbs = builders()
    body, trim, detail, lamps, soft = (
        mbs["body"],
        mbs["trim"],
        mbs["detail"],
        mbs["lamps"],
        mbs["soft"],
    )
    slab(trim, rounded_rect(1.36, 2.02, 0.16), 0.0, 0.06, STEEL, chamfer=0.01)
    slab(trim, rounded_rect(1.10, 1.70, 0.12), 0.06, 0.14, SATIN)
    slab(body, rounded_rect(1.30, 1.94, 0.14), 0.14, 0.20, BODY_LIGHT, chamfer=0.008)
    # Side walls of the tub, low at the back, rising toward the cowl.
    for sx in (-1, 1):
        x0, x1 = sorted((sx * 0.56, sx * 0.64))
        body.prism_x(
            ((-0.85, 0.20), (0.95, 0.20), (0.95, 1.20), (0.55, 1.20), (-0.35, 0.92), (-0.85, 0.80)),
            x0,
            x1,
            BODY,
        )
        top = frame_on_slope((sx * 0.60, -0.10, 0.866), 72.7)
        button_bank(
            lamps,
            detail,
            top,
            2,
            5,
            (0.03, 0.04),
            (0.02, 0.026),
            600 + sx,
            lit=0.45,
            palette=LAMP_PALETTE_COOL,
            plate=None,
        )
    # Front cowl with three screen facets.
    body.prism_x(
        ((0.55, 0.20), (0.97, 0.20), (0.97, 1.50), (0.82, 1.58), (0.62, 1.40)), -0.56, 0.56, BODY
    )
    trim.prism_x(
        ((0.54, 0.20), (0.98, 0.20), (0.98, 1.51), (0.82, 1.595), (0.61, 1.41)), -0.64, -0.56, STEEL
    )
    trim.prism_x(
        ((0.54, 0.20), (0.98, 0.20), (0.98, 1.51), (0.82, 1.595), (0.61, 1.41)), 0.56, 0.64, STEEL
    )
    centre = frame_on_slope((0.0, 0.57, 1.10), 14.0)
    screen(f"{pname()}_screen", centre, 0.44, 0.30, detail, border=0.02)
    for sx in (-1, 1):
        wing = frame_on_slope((sx * 0.37, 0.50, 1.10), 14.0, rz_deg=sx * -32.0)
        with xform(body, wing):
            body.box((-0.16, -0.18, -0.06), (0.16, 0.18, -0.01), BODY)
        screen(
            f"{pname()}_screen_{'r' if sx > 0 else 'l'}",
            wing,
            0.28,
            0.30,
            detail,
            socket_on=False,
            border=0.02,
        )
    slat_stack(
        lamps, detail, frame_on_slope((0.0, 0.72, 1.49), 62.0), 3, 0.5, 0.012, 0.016, seed=611
    )
    # Bucket seat on its pedestal, side sticks.
    trim.box((-0.10, -0.32, 0.20), (0.10, -0.12, 0.385), STEEL)
    cushion(soft, 0.50, 0.48, 0.385, SEAT_H - 0.385, VINYL, corner=0.08, edge=0.03, cy=-0.20)
    back = tr(0.0, -0.45, 0.48, rx_deg=90 + 14.0)
    with xform(soft, back):
        cushion(soft, 0.50, 0.66, 0.0, 0.07, VINYL, corner=0.10, edge=0.03, cy=0.33)
        cushion(soft, 0.54, 0.70, 0.06, 0.04, SATIN, corner=0.11, edge=0.015, cy=0.35)
    for sx in (-1, 1):
        detail.tube((sx * 0.36, 0.05, 0.40), (sx * 0.36, 0.05, 0.66), 0.018, SATIN, 12)
        detail.tube((sx * 0.36, 0.05, 0.66), (sx * 0.36, 0.08, 0.74), 0.026, SATIN, 12)
        lamps.box((sx * 0.36 - 0.008, 0.07, 0.75), (sx * 0.36 + 0.008, 0.09, 0.762), LAMP_RED)
    finish_all(mbs)
    seat_socket("", 0.0, -0.20, 0.0)
    stand_socket("", 0.0, -1.35, 180.0)
    for sx in (-1, 1):
        box_occluder(
            (min(sx * 0.56, sx * 0.64), -0.85, 0.0), (max(sx * 0.56, sx * 0.64), 0.97, 1.20)
        )
    box_occluder((-0.64, 0.55, 0.0), (0.64, 0.98, 1.595))
    oriented_box_occluder(back, (-0.27, 0.0, -0.01), (0.27, 0.72, 0.11))
    anchor("centre")


# --------------------------------------------------------------------------
# Medical bed
# --------------------------------------------------------------------------


@kit.piece("SM_Bed_Medical", dims=(2.21, 0.87, 1.52))
def medical_bed() -> None:
    """Treatment bed on a column with a vitals monitor on an arm.
    SOCKET_bunk '' (lying, head toward -X), SOCKET_screen '', SOCKET_stand 'medic'."""
    mbs = builders()
    body, trim, detail, lamps, soft = (
        mbs["body"],
        mbs["trim"],
        mbs["detail"],
        mbs["lamps"],
        mbs["soft"],
    )
    slab(trim, rounded_rect(1.40, 0.62, 0.08), 0.0, 0.06, STEEL, chamfer=0.008)
    slab(body, rounded_rect(0.44, 0.40, 0.06), 0.06, 0.60, MED_WHITE)
    slab(body, rounded_rect(2.02, 0.84, 0.08), 0.60, 0.70, MED_WHITE, chamfer=0.012)
    cushion(soft, 1.94, 0.76, 0.70, 0.09, LINEN, corner=0.06, edge=0.03)
    cushion(soft, 0.34, 0.52, 0.79, 0.06, LINEN, corner=0.06, edge=0.025, cx=-0.76)
    # Side rail on the far side.
    detail.polyline_tube(
        ((-0.55, 0.44, 0.70), (-0.55, 0.44, 0.94), (0.55, 0.44, 0.94), (0.55, 0.44, 0.70)),
        0.013,
        CHROME,
        12,
    )
    # Monitor post and arm at the head end.
    trim.box((-1.20, 0.20, 0.0), (-1.08, 0.40, 0.04), SATIN)
    detail.tube((-1.14, 0.30, 0.04), (-1.14, 0.30, 1.50), 0.025, CHROME, 16)
    detail.tube((-1.14, 0.30, 1.50), (-0.96, 0.20, 1.50), 0.018, CHROME, 12)
    mon = frame_on_slope((-0.86, 0.14, 1.36), 22.0, rz_deg=-15.0)
    with xform(body, mon):
        body.box((-0.24, -0.17, -0.07), (0.24, 0.17, -0.01), MED_WHITE)
    screen(f"{pname()}_screen", mon, 0.40, 0.26, detail, border=0.02)
    with xform(lamps, mon):
        lamps.box((0.19, -0.155, 0.0), (0.21, -0.14, 0.006), LAMP_GREEN)
    finish_all(mbs)
    bunk_socket("", 0.0, 0.0, 0.79, 90.0)
    stand_socket("medic", 0.0, -0.85, 0.0)
    box_occluder((-1.01, -0.42, 0.0), (1.01, 0.42, 0.79))
    oriented_box_occluder(mon, (-0.24, -0.17, -0.07), (0.24, 0.17, 0.01))
    anchor("centre")
