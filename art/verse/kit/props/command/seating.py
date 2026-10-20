"""Seats: bridge crew seat, conference chair, commander's chair, stool.

The chair geometry functions are reused by consoles and tables, which bake
their seats into the same piece. Chair-local space: the sitter faces +Y, the
seat centre is at the origin, the cushion top is at SEAT_H (0.46 m).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from lib import kit

from ._base import (
    CHROME,
    RUBBER,
    SATIN,
    SEAT_H,
    STEEL,
    VINYL,
    anchor,
    cushion,
    finish,
    lathe,
    oriented_box_occluder,
    pname,
    seat_socket,
    tr,
    xform,
)


@dataclass(frozen=True)
class ChairStyle:
    width: float
    depth: float
    back_top: float  # height of the backrest's top edge
    back_w: float
    recline_deg: float
    base_r: float
    base_mat: str
    arms: bool
    casters: bool = True
    wings: bool = False
    pedestal: bool = False  # fixed floor pedestal instead of a five-star base


CHAIR_STYLES = {
    # Mid-back so the seated crew's shoulders and head stay visible from above.
    "bridge": ChairStyle(0.50, 0.47, 0.98, 0.44, 9.0, 0.30, STEEL, True),
    "conference": ChairStyle(0.52, 0.48, 1.06, 0.46, 11.0, 0.31, CHROME, True, casters=False),
    "commander": ChairStyle(0.58, 0.52, 1.16, 0.52, 12.0, 0.33, CHROME, True, wings=True),
    "operator": ChairStyle(0.48, 0.45, 0.92, 0.42, 7.0, 0.29, STEEL, False),
    # Fixed crew seat of the bridge pits: bolted pedestal, high back, bolsters.
    "crew": ChairStyle(0.50, 0.47, 1.08, 0.46, 8.0, 0.19, STEEL, True, wings=True, pedestal=True),
}


def office_chair(
    prefix: str,
    x: float,
    y: float,
    facing_deg: float = 0.0,
    style: str = "bridge",
    *,
    seat_id: str | None = None,
    occlude: bool = True,
) -> None:
    """Swivel chair on a five-star base at (x, y); sitter faces ``facing_deg``.

    ``facing_deg`` 0 = the sitter faces +Y (away from the camera), 180 = faces
    the camera. Emits SOCKET_seat ``seat_id`` when given, and a UCX for the
    backrest so a seated character is hidden behind it correctly.
    """
    st = CHAIR_STYLES[style]
    place = tr(x, y, 0.0, facing_deg)
    frame = kit.MeshBuilder(place)
    pads = kit.MeshBuilder(place)
    small = kit.MeshBuilder(place)

    if st.pedestal:
        _pedestal(frame, small, st)
    else:
        _star_base(frame, small, st)
        frame.tube((0, 0, 0.10), (0, 0, 0.30), 0.032, SATIN, 16)
        frame.tube((0, 0, 0.30), (0, 0, 0.37), 0.021, CHROME, 16)
    frame.box((-0.13, -0.13, 0.355), (0.13, 0.12, 0.395), STEEL)

    cushion(pads, st.width, st.depth, 0.385, SEAT_H - 0.385, VINYL, corner=0.07, edge=0.03)
    by = -st.depth / 2 + 0.01
    frame.box((-0.035, by - 0.06, 0.36), (0.035, by - 0.01, 0.56), STEEL)
    frame.box((-0.035, -0.10, 0.355), (0.035, by - 0.01, 0.39), STEEL)
    _backrest(pads, frame, st, by - 0.03)
    if st.arms:
        for side in (-1, 1):
            ax = side * (st.width / 2 + 0.025)
            frame.box((ax - 0.015, -0.06, 0.37), (ax + 0.015, 0.0, 0.62), STEEL)
            frame.box((ax - 0.015, -0.06, 0.37), (side * 0.12, 0.0, 0.39), STEEL)
            cushion(
                pads, 0.065, 0.27, 0.615, 0.035, SATIN, corner=0.025, edge=0.012, cx=ax, cy=-0.04
            )

    finish(frame, f"{prefix}_frame", bevel_width=0.004)
    finish(pads, f"{prefix}_pads", bevel_width=0.0)
    finish(small, f"{prefix}_small", bevel_width=0.0015, segments=1)

    if seat_id is not None:
        local = tr(x, y, 0.0, facing_deg)
        p = local @ tr(0.0, 0.02, 0.0).to_translation()
        seat_socket(seat_id, p.x, p.y, facing_deg)
    if occlude:
        back = tr(x, y, 0.0, facing_deg)
        oriented_box_occluder(
            back, (-st.back_w / 2, by - 0.13, 0.50), (st.back_w / 2, by - 0.02, st.back_top)
        )


def _pedestal(frame: kit.MeshBuilder, small: kit.MeshBuilder, st: ChairStyle) -> None:
    """Floor plate bolted to the deck, a fixed column and a swivel collar."""
    lathe(
        frame,
        ((0.0, 0.0), (st.base_r, 0.0), (st.base_r, 0.012), (st.base_r - 0.02, 0.025), (0.0, 0.025)),
        SATIN,  # dark plate: a steel disc reads as a bright ring at game scale
        40,
    )
    lathe(
        frame,
        (
            (0.0, 0.025),
            (0.075, 0.025),
            (0.06, 0.06),
            (0.05, 0.30),
            (0.065, 0.32),
            (0.065, 0.36),
            (0.0, 0.36),
        ),
        STEEL,
        32,
    )
    for i in range(6):
        a = math.radians(30 + 60 * i)
        r = st.base_r - 0.045
        small.tube(
            (math.cos(a) * r, math.sin(a) * r, 0.022),
            (math.cos(a) * r, math.sin(a) * r, 0.03),
            0.009,
            CHROME,
            8,
        )


def _star_base(frame: kit.MeshBuilder, small: kit.MeshBuilder, st: ChairStyle) -> None:
    lathe(
        frame,
        ((0.0, 0.05), (0.055, 0.05), (0.06, 0.09), (0.04, 0.115), (0.0, 0.115)),
        st.base_mat,
        24,
    )
    for i in range(5):
        with xform(frame, tr(rz_deg=36 + 72 * i)), xform(small, tr(rz_deg=36 + 72 * i)):
            frame.prism_x(
                ((0.03, 0.06), (st.base_r, 0.065), (st.base_r, 0.085), (0.03, 0.105)),
                -0.022,
                0.022,
                st.base_mat,
            )
            if st.casters:
                small.tube(
                    (-0.02, st.base_r - 0.02, 0.027),
                    (0.02, st.base_r - 0.02, 0.027),
                    0.027,
                    RUBBER,
                    12,
                )
                small.box(
                    (-0.012, st.base_r - 0.035, 0.03), (0.012, st.base_r - 0.005, 0.066), SATIN
                )
            else:
                small.box((-0.02, st.base_r - 0.04, 0.0), (0.02, st.base_r - 0.005, 0.062), RUBBER)


def _backrest(pads: kit.MeshBuilder, frame: kit.MeshBuilder, st: ChairStyle, y: float) -> None:
    z0 = 0.52
    h = st.back_top - z0
    tilt = tr(0.0, y, z0, rx_deg=90 + st.recline_deg)
    with xform(pads, tilt):
        # Front cushion (thickness runs backward along local +Z).
        cushion(pads, st.back_w, h, 0.0, 0.055, VINYL, corner=0.08, edge=0.022, cy=h / 2)
        # Rear shell, the face the camera sees over a sitter's shoulder.
        cushion(
            pads, st.back_w + 0.02, h + 0.02, 0.05, 0.03, SATIN, corner=0.085, edge=0.012, cy=h / 2
        )
        if st.wings:
            for side in (-1, 1):
                cushion(
                    pads,
                    0.07,
                    h * 0.75,
                    -0.04,
                    0.09,
                    VINYL,
                    corner=0.03,
                    edge=0.02,
                    cx=side * (st.back_w / 2 - 0.02),
                    cy=h * 0.45,
                )


def stool(
    prefix: str, x: float, y: float, *, seat_id: str | None = None, facing_deg: float = 0.0
) -> None:
    """Round stool on a weighted disc base with a foot ring."""
    frame = kit.MeshBuilder(tr(x, y))
    pads = kit.MeshBuilder(tr(x, y))
    lathe(
        frame,
        ((0.0, 0.0), (0.23, 0.0), (0.235, 0.012), (0.20, 0.032), (0.05, 0.04), (0.0, 0.04)),
        STEEL,
        40,
    )
    frame.tube((0, 0, 0.03), (0, 0, 0.36), 0.026, CHROME, 16)
    lathe(
        frame,
        ((0.17, 0.215), (0.185, 0.225), (0.17, 0.235), (0.155, 0.225)),
        CHROME,
        40,
        closed=True,
    )
    for i in range(3):
        with xform(frame, tr(rz_deg=90 + 120 * i)):
            frame.box((-0.008, 0.02, 0.218), (0.008, 0.162, 0.232), CHROME)
    lathe(frame, ((0.0, 0.355), (0.17, 0.355), (0.17, 0.395), (0.0, 0.395)), SATIN, 40)
    lathe(
        pads,
        ((0.0, 0.392), (0.175, 0.392), (0.19, 0.405), (0.192, 0.44), (0.18, SEAT_H), (0.0, SEAT_H)),
        VINYL,
        40,
    )
    finish(frame, f"{prefix}_frame", bevel_width=0.003)
    finish(pads, f"{prefix}_pad", bevel_width=0.0)
    if seat_id is not None:
        seat_socket(seat_id, x, y, facing_deg)


# --------------------------------------------------------------------------
# Pieces
# --------------------------------------------------------------------------


@kit.piece("SM_Chair_Crew", dims=(0.61, 0.65, 1.08), style="crew")
@kit.piece("SM_Chair_Bridge", dims=(0.61, 0.67, 0.97), style="bridge")
@kit.piece("SM_Chair_Conference", dims=(0.64, 0.70, 1.05), style="conference")
@kit.piece("SM_Chair_Commander", dims=(0.69, 0.78, 1.14), style="commander")
def chair_piece(style: str) -> None:
    """Free-standing swivel chair; SOCKET_seat '' (sitter faces local +Y)."""
    office_chair(pname(), 0.0, 0.0, 0.0, style, seat_id="")
    anchor("centre")


@kit.piece("SM_Stool", dims=(0.47, 0.47, 0.46))
def stool_piece() -> None:
    """Round swivel stool; SOCKET_seat ''."""
    stool(pname(), 0.0, 0.0, seat_id="")
    anchor("centre")
