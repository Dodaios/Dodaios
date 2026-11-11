"""Desk and floor clutter for the Unreal decks (WP12, decks look pass).

Small props the deck look scatters at runtime (`VerseDeckLife.cpp`): tablets,
mugs, data pads, a headset and a toolkit on the consoles, cable coils on the
floor, a wireframe holo globe over each holo table and the gold floor guide
strip. They carry no sockets and no occluders; collision is off in the deck
look, so they never change the deck's nav or the coordinates contract.
"""

from __future__ import annotations

import math

from lib import kit

from ._base import (
    BODY,
    CHROME,
    GLOSS,
    MED_WHITE,
    RANK_GOLD,
    RUBBER,
    SATIN,
    anchor,
    builders,
    finish_all,
    lathe,
    screen,
    tr,
    xform,
)

HOLO = "M_Emit_HoloAmber"  # thin amber light lines of the holo globe
GUIDE = "M_Light_GuideGold"  # gold floor guide light


def _torus(mb: kit.MeshBuilder, radius: float, tube: float, mat: str, z: float = 0.0) -> None:
    profile = [
        (radius + tube * math.cos(a), z + tube * math.sin(a))
        for a in (2 * math.pi * i / 6 for i in range(6))
    ]
    lathe(mb, profile, mat, 64, closed=True)


@kit.piece("SM_Clutter_Tablet", dims=(0.26, 0.18, 0.02), nav="none")
def tablet() -> None:
    """Crew tablet lying on a desk, its screen lit (the slot takes a deck read-out)."""
    mbs = builders()
    body = mbs["body"]
    body.box((-0.13, -0.09, 0.0), (0.13, 0.09, 0.011), SATIN)
    body.box((-0.128, -0.088, 0.011), (0.128, 0.088, 0.013), GLOSS)
    screen("SM_Clutter_Tablet_glass", tr(0.0, 0.0, 0.012), 0.236, 0.158, socket_on=False)
    finish_all(mbs)
    anchor("centre")


@kit.piece("SM_Clutter_Mug", dims=(0.11, 0.08, 0.10), nav="none")
def mug() -> None:
    """Crew mug with a gold band and a dark brew in it."""
    mbs = builders()
    body, trim, detail = mbs["body"], mbs["trim"], mbs["detail"]
    lathe(
        body,
        (
            (0.0, 0.0),
            (0.038, 0.0),
            (0.040, 0.004),
            (0.041, 0.095),
            (0.036, 0.095),
            (0.035, 0.012),
            (0.0, 0.012),
        ),
        MED_WHITE,
        32,
    )
    lathe(trim, ((0.0412, 0.070), (0.0418, 0.070), (0.0418, 0.080), (0.0412, 0.080)), RANK_GOLD, 32)
    lathe(detail, ((0.0, 0.075), (0.0355, 0.075), (0.0355, 0.077), (0.0, 0.077)), GLOSS, 32)
    with xform(body, tr(0.050, 0.0, 0.050, rx_deg=90.0)):
        _torus(body, 0.022, 0.0055, MED_WHITE)
    finish_all(mbs)
    anchor("centre")


@kit.piece("SM_Clutter_DataPads", dims=(0.30, 0.24, 0.04), nav="none")
def data_pads() -> None:
    """A loose stack of three data pads, the top one lit."""
    mbs = builders()
    body = mbs["body"]
    for i, (dx, dy, rz) in enumerate(((0.0, 0.0, 0.0), (0.02, 0.015, 9.0), (-0.015, 0.01, -14.0))):
        with xform(body, tr(dx, dy, i * 0.009, rz_deg=rz)):
            body.box((-0.10, -0.07, 0.0), (0.10, 0.07, 0.008), SATIN if i != 1 else BODY)
    screen(
        "SM_Clutter_DataPads_glass",
        tr(-0.015, 0.01, 0.027, rz_deg=-14.0),
        0.18,
        0.12,
        socket_on=False,
    )
    finish_all(mbs)
    anchor("centre")


@kit.piece("SM_Clutter_Headset", dims=(0.20, 0.10, 0.20), nav="none")
def headset() -> None:
    """Comms headset left on a console: band, two cups, a mic boom."""
    mbs = builders()
    body, trim, detail = mbs["body"], mbs["trim"], mbs["detail"]
    for sx in (-1, 1):
        with xform(body, tr(sx * 0.08, 0.0, 0.035, rx_deg=0.0)):
            body.tube((0.0, 0.0, -0.035), (0.0, 0.0, 0.0), 0.035, SATIN, 24)
            detail.tube((0.0, 0.0, 0.0), (0.0, 0.0, 0.006), 0.03, RUBBER, 24)
    with xform(trim, tr(0.0, 0.0, 0.035, rx_deg=90.0)):
        lathe(
            trim,
            [
                (0.08 + 0.006 * math.cos(a), 0.006 * math.sin(a))
                for a in (i * math.pi / 3 for i in range(6))
            ],
            CHROME,
            48,
            closed=True,
        )
    detail.polyline_tube(
        ((0.08, -0.03, 0.02), (0.05, -0.08, 0.02), (0.0, -0.10, 0.02)), 0.004, RUBBER
    )
    finish_all(mbs)
    anchor("centre")


@kit.piece("SM_Clutter_Toolkit", dims=(0.46, 0.22, 0.20), nav="none")
def toolkit() -> None:
    """Engineer's tool case: charcoal shell, gold latches, a handle."""
    mbs = builders()
    body, trim, detail = mbs["body"], mbs["trim"], mbs["detail"]
    body.box((-0.23, -0.11, 0.0), (0.23, 0.11, 0.16), BODY)
    trim.box((-0.232, -0.112, 0.075), (0.232, 0.112, 0.085), RUBBER)
    for sx in (-1, 1):
        detail.box((sx * 0.15 - 0.02, -0.114, 0.10), (sx * 0.15 + 0.02, -0.11, 0.14), RANK_GOLD)
    detail.tube((-0.09, 0.0, 0.16), (-0.09, 0.0, 0.20), 0.008, CHROME)
    detail.tube((0.09, 0.0, 0.16), (0.09, 0.0, 0.20), 0.008, CHROME)
    detail.tube((-0.09, 0.0, 0.20), (0.09, 0.0, 0.20), 0.012, RUBBER)
    finish_all(mbs)
    anchor("centre")


@kit.piece("SM_Clutter_CableCoil", dims=(0.60, 0.60, 0.06), nav="none")
def cable_coil() -> None:
    """Loose coil of heavy power cable on the floor, a tail running off."""
    mbs = builders()
    soft = mbs["soft"]
    for i, r in enumerate((0.22, 0.25, 0.28)):
        with xform(soft, tr(0.01 * i, -0.008 * i, 0.016 + 0.012 * (i % 2))):
            _torus(soft, r, 0.016, RUBBER)
    soft.polyline_tube(
        ((0.28, 0.0, 0.016), (0.40, 0.06, 0.016), (0.55, 0.02, 0.016), (0.70, 0.10, 0.016)),
        0.016,
        RUBBER,
    )
    finish_all(mbs)
    anchor("centre")


@kit.piece("SM_Clutter_HoloGlobe", dims=(1.0, 1.0, 1.0), nav="none")
def holo_globe() -> None:
    """Wireframe planet hologram: latitude and meridian rings of thin amber light, 1 m across."""
    mbs = builders()
    lamps = mbs["lamps"]
    r, line = 0.5, 0.009
    for lat in (-60, -30, 0, 30, 60):
        a = math.radians(lat)
        _torus(lamps, r * math.cos(a), line, HOLO, z=r + r * math.sin(a))
    for k in range(6):
        with xform(lamps, tr(0.0, 0.0, r, rz_deg=30.0 * k, rx_deg=90.0)):
            _torus(lamps, r, line, HOLO)
    _torus(lamps, r * 1.25, line * 2, HOLO, z=r)
    finish_all(mbs)
    anchor("design")


@kit.piece("SM_Clutter_GuideStrip", dims=(1.0, 0.04, 0.01), nav="none")
def guide_strip() -> None:
    """One metre of gold floor guide light in a steel channel (the deck look scales it)."""
    mbs = builders()
    trim, lamps = mbs["trim"], mbs["lamps"]
    trim.box((-0.5, -0.02, 0.0), (0.5, 0.02, 0.006), CHROME)
    lamps.box((-0.49, -0.008, 0.006), (0.49, 0.008, 0.009), GUIDE)
    finish_all(mbs)
    anchor("centre")


@kit.piece("SM_Clutter_WallDisplay", dims=(1.68, 0.08, 0.98), nav="none")
def wall_display() -> None:
    """Wall-mounted 1.6 x 0.9 m display in a charcoal bezel with a gold lower lip; the glass
    takes a deck read-out. Back on local Y = 0, facing -Y, centred on the glass."""
    mbs = builders()
    body, trim = mbs["body"], mbs["trim"]
    w, h, d = 0.84, 0.49, 0.06
    body.box((-w, -d, -h), (w, 0.0, h), SATIN)
    trim.box((-w, -d - 0.004, -h - 0.02), (w, 0.0, -h), RANK_GOLD)
    screen(
        "SM_Clutter_WallDisplay_glass",
        tr(0.0, -d - 0.002, 0.0, rx_deg=90.0),
        1.6,
        0.9,
        socket_on=False,
    )
    finish_all(mbs)
    anchor("design")


PIECES = (
    "SM_Clutter_Tablet",
    "SM_Clutter_Mug",
    "SM_Clutter_DataPads",
    "SM_Clutter_Headset",
    "SM_Clutter_Toolkit",
    "SM_Clutter_CableCoil",
    "SM_Clutter_HoloGlobe",
    "SM_Clutter_GuideStrip",
    "SM_Clutter_WallDisplay",
)
