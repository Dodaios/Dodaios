"""Hangar control booth console (``decks/hangar/hangar_props.py`` contract).

The hangar deck places ``SM_Console_BoothRear`` at the booth console centre
with yaw 180 and builds the operators' chairs itself on the camera side. The
piece is therefore modelled turned by 180 degrees: placed at yaw 180 its
screens face the camera and its operator edge is on the camera side, the
standard arrangement (BRIEF section 5). Low hood (1.30 m) so the operators
see over it through the booth window.
"""

from __future__ import annotations

from lib import kit

from ._base import (
    ACCENT_RED,
    BODY,
    BODY_LIGHT,
    CHROME,
    DARK_PANEL,
    LAMP_GREEN,
    LAMP_PALETTE_COOL,
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
    oriented_box_occluder,
    pname,
    screen,
    slat_stack,
    stand_socket,
    tr,
    xform,
)


@kit.piece("SM_Console_BoothRear", dims=(3.78, 1.09, 1.31))
def booth_console() -> None:
    """3.6 m booth desk with a low three-screen hood; place at yaw 180
    (modelled turned). No chairs. SOCKET_screen '1'-'3'."""
    mbs = builders()
    body, trim, detail, lamps = mbs["body"], mbs["trim"], mbs["detail"], mbs["lamps"]
    w = 3.6
    body.box((-w / 2, -0.45, 0.08), (w / 2, 0.45, 0.80), BODY)
    trim.box((-w / 2 + 0.05, -0.40, 0.0), (w / 2 - 0.05, 0.45, 0.08), SATIN)
    trim.box((-w / 2 - 0.05, -0.50, 0.80), (w / 2 + 0.05, 0.55, 0.86), BODY_LIGHT)
    detail.box((-w / 2 - 0.05, -0.515, 0.79), (w / 2 + 0.05, -0.50, 0.865), SATIN)
    for side in (-1, 1):
        x0 = side * (w / 2 + 0.05)
        trim.box(
            (min(x0, x0 + side * 0.04), -0.52, 0.0), (max(x0, x0 + side * 0.04), 0.57, 1.31), STEEL
        )
    body.prism_x(
        ((0.10, 0.86), (0.45, 0.86), (0.45, 1.28), (0.40, 1.30), (0.30, 1.30)), -w / 2, w / 2, BODY
    )
    for i in range(6):
        px = -w / 2 + 0.3 + i * 0.6
        detail.box((px - 0.27, -0.456, 0.14), (px + 0.27, -0.45, 0.74), BODY_LIGHT)
    for i, sx in enumerate((-1.2, 0.0, 1.2)):
        face = frame_on_slope((sx, 0.20, 1.08), 27.0)
        screen(
            f"{pname()}_screen{i + 1}",
            face,
            0.56,
            0.30,
            detail,
            local_id=str(i + 1),
            border=0.025,
            depth=0.02,
        )
        keyboard(detail, frame_on_slope((sx, -0.20, 0.86), 90.0), w=0.46, d=0.15)
    for sx in (-0.6, 0.6):
        face = frame_on_slope((sx, 0.20, 1.08), 27.0)
        button_bank(
            lamps,
            detail,
            face @ tr(0.0, 0.04),
            5,
            4,
            (0.034, 0.04),
            (0.024, 0.026),
            int(700 + sx * 10),
            lit=0.45,
            palette=LAMP_PALETTE_COOL,
        )
        slat_stack(lamps, detail, face @ tr(0.0, -0.10), 2, 0.3, 0.012, 0.02, seed=int(710 + sx))
    top = frame_on_slope((0.0, 0.375, 1.30), 90.0)
    with xform(detail, top):
        detail.box((-w / 2 + 0.02, -0.075, 0.0), (w / 2 - 0.02, -0.063, 0.003), ACCENT_RED)
    with xform(lamps, top):
        for i in range(9):
            lx = -1.6 + i * 0.4
            mat = LAMP_GREEN if i % 3 == 1 else LAMP_WHITE
            lamps.box((lx - 0.01, 0.0, 0.0), (lx + 0.01, 0.02, 0.008), mat)
    finish_all(mbs)
    box_occluder((-w / 2 - 0.09, -0.52, 0.0), (w / 2 + 0.09, 0.57, 0.86))
    box_occluder((-w / 2, 0.10, 0.86), (w / 2, 0.45, 1.31))
    anchor("centre", spin_deg=180.0)


@kit.piece("SM_Counter_Arrivals", dims=(5.46, 1.02, 1.29))
def arrivals_counter() -> None:
    """Arrivals desk (station kind create_agent): 5.4 m counter facing the
    camera, the commander's terminal on the -Y side, a raised transaction
    ledge toward +Y where arriving agents walk up from the shuttle.
    SOCKET_screen/station '' (commander side), SOCKET_stand 'arrival' (+Y)."""
    mbs = builders()
    body, trim, detail, lamps = mbs["body"], mbs["trim"], mbs["detail"], mbs["lamps"]
    w = 5.4
    trim.box((-w / 2 + 0.05, -0.40, 0.0), (w / 2 - 0.05, 0.42, 0.08), SATIN)
    body.box((-w / 2, -0.45, 0.08), (w / 2, 0.45, 0.90), BODY)
    trim.box((-w / 2 - 0.03, -0.52, 0.90), (w / 2 + 0.03, 0.47, 0.94), BODY_LIGHT)
    detail.box((-w / 2 - 0.03, -0.535, 0.89), (w / 2 + 0.03, -0.52, 0.945), CHROME)
    for i in range(9):
        px = -w / 2 + 0.3 + i * 0.6
        detail.box((px - 0.27, -0.458, 0.14), (px + 0.27, -0.45, 0.84), BODY_LIGHT)
    # Raised transaction ledge on the arrivals side.
    body.box((-w / 2, 0.30, 0.94), (w / 2, 0.47, 1.12), BODY)
    trim.box((-w / 2 - 0.02, 0.28, 1.12), (w / 2 + 0.02, 0.49, 1.15), DARK_PANEL)
    detail.box((-w / 2 - 0.02, 0.275, 1.11), (w / 2 + 0.02, 0.285, 1.155), CHROME)
    # Commander's terminal at the centre, facing the camera.
    term = frame_on_slope((0.0, 0.08, 1.10), 28.0)
    with xform(trim, term):
        trim.box((-0.40, -0.22, -0.10), (0.40, 0.22, -0.01), BODY)
    trim.box((-0.15, -0.02, 0.94), (0.15, 0.22, 0.98), STEEL)
    screen(f"{pname()}_screen", term, 0.70, 0.38, detail, border=0.025)
    keyboard(detail, frame_on_slope((0.0, -0.30, 0.94), 90.0), w=0.46, d=0.15)
    for sx in (-1.6, 1.6):
        with xform(detail, frame_on_slope((sx, -0.10, 0.94), 90.0)):
            detail.box((-0.30, -0.18, 0.0), (0.30, 0.18, 0.012), SATIN)
        button_bank(
            lamps,
            detail,
            frame_on_slope((sx + 0.42, -0.25, 0.94), 90.0),
            3,
            2,
            (0.03, 0.03),
            (0.02, 0.02),
            int(760 + sx * 10),
            lit=0.3,
            palette=LAMP_PALETTE_COOL,
        )
    # Identity scanner pad for the new arrivals, on the ledge.
    detail.box((0.80, 0.31, 1.15), (1.10, 0.46, 1.17), SATIN)
    lamps.box((0.84, 0.34, 1.17), (1.06, 0.43, 1.174), LAMP_GREEN)
    with xform(detail, frame_on_slope((0.0, 0.375, 1.15), 90.0)):
        detail.box((-w / 2 + 0.05, -0.012, 0.0), (w / 2 - 0.05, 0.0, 0.003), ACCENT_RED)
    finish_all(mbs)
    stand_socket("", 0.0, -0.95, 0.0, kind="station")
    stand_socket("arrival", 0.0, 0.95, 180.0)
    box_occluder((-w / 2 - 0.03, -0.54, 0.0), (w / 2 + 0.03, 0.49, 1.155))
    oriented_box_occluder(term, (-0.40, -0.22, -0.10), (0.40, 0.22, 0.01))
    anchor("centre")
