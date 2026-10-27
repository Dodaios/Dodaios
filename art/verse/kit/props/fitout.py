"""Working-deck fit-out props for the Verse kit, deck-agnostic.

The furniture a busy ship's deck collects along its walls and under its
ceiling: equipment racks with status lights, low service cabinets, wall-side
workstations with screens and a crew stool, stacked cargo cases, a small holo
plinth, flush floor grilles and hatches, and the overhead services (pipe
runs, ducts, cable ladders on hangers).

Every builder adds boxes and tubes to a ``kit.architecture.cladding.Builders``
in its current frame ``(u, v, h)``: ``u`` along, ``v`` out of the wall toward
the prop's front, ``h`` up (``cladding.run_matrix`` for a wall run,
``cladding.place_matrix`` for a freestanding piece). Lamps and screens go to
``B.lamps`` (nav ``none``, no shadow); the deck decides what is a ghost and
what stands on the plate. Only existing library materials are used.
"""

from __future__ import annotations

import math

from kit.architecture.cladding import (
    BODY,
    DARK,
    GUNMETAL,
    KEYS,
    MID,
    PIPE,
    PIPE_INS,
    RECESS,
    RUBBER,
    SCREEN,
    STEEL,
    WHITE_PAINT,
    Builders,
    box,
    louvre,
    seed01,
)

CRATE = "M_Crate_Paint"
GRATING = "M_Floor_Grating"
SEAT = "M_Seat_Upholstery"
DECK = "M_Console_Deck"
GLASS = "M_Glass_Clear"
STATUS = ("M_Indicator_Green", "M_Indicator_White", "M_Indicator_Green", "M_Indicator_Amber")


def _pip_mat(seed, *parts) -> str:
    r = seed01(seed, *parts)
    if r < 0.05:
        return "M_Indicator_Red"
    return STATUS[int(r * 4) % 4]


# ---------------------------------------------------------------- racks


def equipment_rack(B: Builders, u0: float, u1: float, *, h: float = 2.1, depth: float = 0.62,
                   seed=0) -> None:  # fmt: skip
    """Equipment rack against a wall: gunmetal frame, one door per 0.6 m
    module (vent grille, a column of status pips, a handle), a plinth and a
    cable bundle leaving the top toward the wall."""
    v0, v1 = 0.04, 0.04 + depth
    box(B.struct, u0, u1, v0, v1, 0.0, 0.08, RUBBER)
    box(B.struct, u0, u1, v0, v1 - 0.03, 0.08, h, BODY)
    box(B.struct, u0 - 0.01, u1 + 0.01, v0, v1, h, h + 0.04, GUNMETAL)
    n = max(1, round((u1 - u0) / 0.6))
    step = (u1 - u0) / n
    for i in range(n):
        a, b = u0 + i * step + 0.02, u0 + (i + 1) * step - 0.02
        kind = seed01(seed, "door", i)
        box(B.panels, a, b, v1 - 0.03, v1, 0.12, h - 0.04, DARK if kind < 0.6 else MID)
        if kind < 0.35:  # vented door
            for k in range(10):
                z = 0.3 + k * 0.08
                box(B.flat, a + 0.06, b - 0.06, v1, v1 + 0.004, z, z + 0.03, RECESS)
        elif kind < 0.7:  # instrument window with blades
            box(B.flat, a + 0.05, b - 0.05, v1, v1 + 0.003, 0.8, h - 0.3, RECESS)
            for k in range(int((h - 1.1) / 0.09)):
                z = 0.84 + k * 0.09
                box(B.struct, a + 0.07, b - 0.07, v1 - 0.02, v1 + 0.002, z, z + 0.045, GUNMETAL)
        else:  # plain door with a label strip
            box(B.flat, a + 0.08, a + 0.3, v1, v1 + 0.003, h - 0.42, h - 0.36, WHITE_PAINT)
        # Status column on the hinge side, sparse.
        z, k = 1.0, 0
        while z < h - 0.3:
            if seed01(seed, "led", i, k) < 0.55:
                box(B.lamps, a + 0.03, a + 0.055, v1, v1 + 0.006, z, z + 0.02, _pip_mat(seed, i, k))
            z += 0.07
            k += 1
        box(B.struct, b - 0.06, b - 0.04, v1, v1 + 0.03, 0.9, 1.25, STEEL)
    # Cable bundle from the top into the wall.
    for k in range(3):
        cu = u0 + 0.2 + k * 0.1
        B.pipes.tube((cu, v0 + 0.25, h + 0.04), (cu, v0 + 0.25, h + 0.25), 0.02, RUBBER, 6)
        B.pipes.tube((cu, v0 + 0.25, h + 0.25), (cu, 0.01, h + 0.25), 0.02, RUBBER, 6)


def low_cabinet(B: Builders, u0: float, u1: float, *, h: float = 0.95, depth: float = 0.6,
                seed=0, clutter: bool = True) -> None:  # fmt: skip
    """Service cabinet run: plinth, doors per 0.6 m, a brushed top with a
    few cases and a small readout on it."""
    v0, v1 = 0.04, 0.04 + depth
    box(B.struct, u0, u1, v0 + 0.06, v1 - 0.06, 0.0, 0.1, RUBBER)
    box(B.struct, u0, u1, v0, v1 - 0.02, 0.1, h - 0.03, BODY)
    box(B.struct, u0 - 0.02, u1 + 0.02, v0, v1 + 0.02, h - 0.03, h, STEEL)
    n = max(1, round((u1 - u0) / 0.6))
    step = (u1 - u0) / n
    for i in range(n):
        a, b = u0 + i * step + 0.015, u0 + (i + 1) * step - 0.015
        box(B.panels, a, b, v1 - 0.02, v1, 0.14, h - 0.07, DARK if i % 3 else MID)
        box(B.struct, (a + b) / 2 - 0.08, (a + b) / 2 + 0.08, v1, v1 + 0.025, h - 0.18, h - 0.15,
            STEEL)  # fmt: skip
        if seed01(seed, "lv", i) < 0.3:
            louvre(B, (a + b) / 2, 0.22, w=min(0.45, b - a - 0.1), h=0.22)
    if not clutter:
        return
    u = u0 + 0.15
    k = 0
    while u < u1 - 0.5:
        r = seed01(seed, "cl", k)
        if r < 0.35:
            w = 0.3 + 0.2 * seed01(seed, "w", k)
            box(B.struct, u, u + w, v0 + 0.1, v0 + 0.42, h, h + 0.16 + 0.1 * r, CRATE)
            u += w + 0.15
        elif r < 0.5:
            box(B.struct, u, u + 0.34, v0 + 0.08, v0 + 0.3, h, h + 0.03, BODY)
            B.struct.prism_x([(v0 + 0.1, h + 0.03), (v0 + 0.16, h + 0.03), (v0 + 0.16, h + 0.26),
                              (v0 + 0.13, h + 0.26)], u + 0.04, u + 0.3, BODY)  # fmt: skip
            box(B.lamps, u + 0.06, u + 0.28, v0 + 0.161, v0 + 0.163, h + 0.07, h + 0.24, SCREEN)
            u += 0.5
        else:
            u += 0.45
        k += 1


# ---------------------------------------------------------------- workstations


def stool(B: Builders, cu: float, cv: float, *, back: bool = True, yaw_deg: float = 0.0) -> None:
    """Crew stool: weighted base, column, cushion, optional low back (toward +v)."""
    B.struct.tube((cu, cv, 0.0), (cu, cv, 0.04), 0.24, GUNMETAL, 16)
    B.struct.tube((cu, cv, 0.04), (cu, cv, 0.42), 0.035, STEEL, 10)
    B.struct.tube((cu, cv, 0.42), (cu, cv, 0.47), 0.22, BODY, 18)
    B.panels.tube((cu, cv, 0.47), (cu, cv, 0.52), 0.21, SEAT, 18)
    if back:
        s, c = math.sin(math.radians(yaw_deg)), math.cos(math.radians(yaw_deg))
        bu, bv = cu + 0.2 * s, cv + 0.2 * c
        B.struct.tube((bu, bv, 0.47), (bu, bv, 0.62), 0.02, STEEL, 8)
        box(B.panels, bu - 0.18, bu + 0.18, bv - 0.03, bv + 0.03, 0.62, 0.86, SEAT)


def workstation(B: Builders, cu: float, *, width: float = 1.6, depth: float = 0.8, seed=0,
                chair: bool = True) -> None:  # fmt: skip
    """Wall-side workstation: pedestal desk, a sloped key deck, two or three
    screens on a riser at the back, a document tray and a crew stool."""
    a, b = cu - width / 2, cu + width / 2
    v0, v1 = 0.04, 0.04 + depth
    top = 0.76
    box(B.struct, a, a + 0.42, v0, v1 - 0.05, 0.0, top - 0.03, BODY)  # drawer pedestal
    for k in range(3):
        z = 0.06 + k * 0.22
        box(B.panels, a + 0.02, a + 0.4, v1 - 0.05, v1 - 0.035, z, z + 0.2, DARK)
    box(B.struct, b - 0.08, b - 0.03, v0 + 0.05, v1 - 0.1, 0.0, top - 0.03, GUNMETAL)  # leg
    box(B.struct, a, b, v0, v1, top - 0.03, top, DECK)
    box(B.struct, a, b, v1 - 0.01, v1 + 0.01, top - 0.05, top + 0.002, STEEL)
    # Riser with screens.
    box(B.struct, a + 0.05, b - 0.05, v0, v0 + 0.16, top, top + 0.12, BODY)
    n = 3 if seed01(seed, "n") < 0.4 and width >= 1.5 else 2
    sw = (width - 0.2) / n
    for i in range(n):
        su = a + 0.1 + (i + 0.5) * sw
        tilt = 0.06 if n == 2 else (0.1 if i != 1 else 0.0)
        box(B.struct, su - 0.04, su + 0.04, v0 + 0.05, v0 + 0.1, top + 0.12, top + 0.32, GUNMETAL)
        lo, hi = top + 0.3, top + 0.3 + sw * 0.62
        f_lo, f_hi = v0 + 0.12 + tilt, v0 + 0.1  # front face leans back to the top
        B.struct.prism_x([(f_lo - 0.04, lo), (f_lo, lo), (f_hi, hi), (f_hi - 0.04, hi)],
                         su - sw / 2 + 0.03, su + sw / 2 - 0.03, BODY)  # fmt: skip

        def front(hh: float, out: float, f_lo=f_lo, f_hi=f_hi, lo=lo, hi=hi):
            return f_lo + (f_hi - f_lo) * (hh - lo) / (hi - lo) + out

        a0, a1 = lo + 0.03, hi - 0.03
        B.lamps.prism_x([(front(a0, 0.001), a0), (front(a0, 0.004), a0),
                         (front(a1, 0.004), a1), (front(a1, 0.001), a1)],
                        su - sw / 2 + 0.06, su + sw / 2 - 0.06, SCREEN)  # fmt: skip
    # Sloped key deck and a tray.
    B.struct.prism_x([(v0 + 0.3, top), (v0 + 0.62, top), (v0 + 0.62, top + 0.03),
                      (v0 + 0.3, top + 0.08)], cu - 0.35, cu + 0.25, BODY)  # fmt: skip
    for k in range(8):
        ku = cu - 0.31 + k * 0.065
        box(B.flat, ku, ku + 0.05, v0 + 0.38, v0 + 0.56, top + 0.035, top + 0.06, KEYS)
    box(B.struct, b - 0.42, b - 0.12, v0 + 0.3, v0 + 0.62, top, top + 0.025, GUNMETAL)
    box(B.struct, b - 0.4, b - 0.14, v0 + 0.32, v0 + 0.6, top + 0.025, top + 0.06, CRATE)
    box(B.lamps, a + 0.12, a + 0.15, v1 + 0.01, v1 + 0.013, top - 0.02, top - 0.005,
        _pip_mat(seed, "desk"))  # fmt: skip
    if chair:
        stool(B, cu - 0.05, v1 + 0.42, yaw_deg=0.0)


# ---------------------------------------------------------------- cargo


def case(B: Builders, cu: float, cv: float, h0: float, w: float, d: float, h: float, seed,
         mat: str = CRATE) -> None:  # fmt: skip
    """A hard cargo case: body, two reinforcing bands, corner caps, latches
    and a white stencil bar on its front (+v)."""
    box(B.struct, cu - w / 2, cu + w / 2, cv - d / 2, cv + d / 2, h0, h0 + h - 0.01, mat)
    for f in (0.22, 0.78):
        u = cu - w / 2 + f * w
        box(B.struct, u - 0.03, u + 0.03, cv - d / 2 - 0.008, cv + d / 2 + 0.008, h0, h0 + h,
            GUNMETAL)  # fmt: skip
    box(B.struct, cu - w / 2 - 0.006, cu + w / 2 + 0.006, cv - d / 2 - 0.006, cv + d / 2 + 0.006,
        h0 + h * 0.62, h0 + h * 0.66, GUNMETAL)  # fmt: skip
    for su in (-1, 1):
        box(B.flat, cu + su * w * 0.12 - 0.03, cu + su * w * 0.12 + 0.03, cv + d / 2,
            cv + d / 2 + 0.018, h0 + h * 0.58, h0 + h * 0.7, STEEL)  # fmt: skip
    if seed01(seed, "st") < 0.7:
        sw = w * (0.2 + 0.25 * seed01(seed, "sw"))
        box(B.flat, cu - w * 0.38, cu - w * 0.38 + sw, cv + d / 2, cv + d / 2 + 0.003,
            h0 + h * 0.3, h0 + h * 0.4, WHITE_PAINT)  # fmt: skip


def case_stack(B: Builders, cu: float, cv: float, seed, *, levels: int | None = None) -> float:
    """1-3 cases stacked with a little offset, on a steel skid. Returns the
    stack height."""
    if levels is None:
        levels = 1 + int(seed01(seed, "lv") * 3)
    box(B.struct, cu - 0.62, cu + 0.62, cv - 0.42, cv + 0.42, 0.0, 0.1, GUNMETAL)
    for k in (-0.4, 0.0, 0.4):
        box(B.struct, cu + k - 0.05, cu + k + 0.05, cv - 0.44, cv + 0.44, 0.0, 0.11, STEEL)
    h = 0.11
    for i in range(levels):
        w = 1.2 if i == 0 else 0.8 + 0.3 * seed01(seed, "w", i)
        d = 0.8 if i == 0 else 0.6
        ch = 0.55 if i == 0 else 0.35 + 0.15 * seed01(seed, "h", i)
        du = (seed01(seed, "du", i) - 0.5) * (1.2 - w)
        mat = CRATE if seed01(seed, "m", i) < 0.75 else DARK
        case(B, cu + du, cv, h, w, d, ch, (seed, i), mat)
        h += ch
    return h


def holo_plinth(B: Builders, cu: float, cv: float, *, r: float = 0.6, seed=0) -> None:
    """Compact holo plinth: stepped round base, a dark glass top with a blue
    emitter ring and a few pips round the rim."""
    B.struct.tube((cu, cv, 0.0), (cu, cv, 0.08), r + 0.08, RUBBER, 32)
    B.struct.tube((cu, cv, 0.08), (cu, cv, 0.78), r * 0.55, BODY, 28)
    B.struct.tube((cu, cv, 0.78), (cu, cv, 0.9), r, GUNMETAL, 40)
    B.panels.tube((cu, cv, 0.9), (cu, cv, 0.93), r - 0.05, "M_Lacquer_BlackGloss", 40)
    ring = 40
    for i in range(ring):
        a0, a1 = 2 * math.pi * i / ring, 2 * math.pi * (i + 1) / ring
        ri, ro = r * 0.35, r * 0.42
        B.lamps.quad(
            [
                (cu + ro * math.cos(a0), cv + ro * math.sin(a0), 0.932),
                (cu + ro * math.cos(a1), cv + ro * math.sin(a1), 0.932),
                (cu + ri * math.cos(a1), cv + ri * math.sin(a1), 0.932),
                (cu + ri * math.cos(a0), cv + ri * math.sin(a0), 0.932),
            ],
            "M_Indicator_Blue",
        )
    for i in range(6):
        a = 2 * math.pi * (i + 0.5) / 6
        pu, pv = cu + (r - 0.025) * math.cos(a), cv + (r - 0.025) * math.sin(a)
        box(B.lamps, pu - 0.015, pu + 0.015, pv - 0.015, pv + 0.015, 0.9, 0.905,
            _pip_mat(seed, "holo", i))  # fmt: skip


# ---------------------------------------------------------------- floor


def floor_grille(B: Builders, u0: float, u1: float, v0: float, v1: float) -> None:
    """Flush floor grille: brushed frame and grating over a dark well."""
    t = 0.05
    box(B.flat, u0, u1, v0, v1, 0.0004, 0.002, RECESS)
    box(B.flat, u0 + t, u1 - t, v0 + t, v1 - t, 0.002, 0.0045, GRATING)
    for a, b, c, d in ((u0, u1, v0, v0 + t), (u0, u1, v1 - t, v1), (u0, u0 + t, v0, v1),
                       (u1 - t, u1, v0, v1)):  # fmt: skip
        box(B.flat, a, b, c, d, 0.0005, 0.005, STEEL)


def floor_hatch(B: Builders, u0: float, u1: float, v0: float, v1: float) -> None:
    """Flush access hatch: steel frame, a dark plate with two recessed
    handle slots and a seam down the middle."""
    t = 0.06
    box(B.flat, u0, u1, v0, v1, 0.0004, 0.004, STEEL)
    box(B.flat, u0 + t, u1 - t, v0 + t, v1 - t, 0.0004, 0.0048, DARK)
    um = (u0 + u1) / 2
    box(B.flat, um - 0.006, um + 0.006, v0 + t, v1 - t, 0.0004, 0.005, RECESS)
    for uc in ((u0 + um) / 2, (um + u1) / 2):
        box(B.flat, uc - 0.08, uc + 0.08, (v0 + v1) / 2 - 0.025, (v0 + v1) / 2 + 0.025, 0.0004,
            0.0052, RECESS)  # fmt: skip


# ---------------------------------------------------------------- overhead


def _hanger(B: Builders, u: float, v0: float, v1: float, h: float, top: float) -> None:
    box(B.struct, u - 0.02, u + 0.02, v0, v1, h - 0.04, h, GUNMETAL)
    for v in (v0 + 0.02, v1 - 0.02):
        box(B.struct, u - 0.012, u + 0.012, v - 0.012, v + 0.012, h, top, STEEL)


def pipe_run(B: Builders, u0: float, u1: float, v: float, h: float, top: float, *,
             pipes=((0.0, 0.07, PIPE_INS), (0.2, 0.045, PIPE), (0.36, 0.035, PIPE)),
             hanger_every: float = 2.4) -> None:  # fmt: skip
    """Overhead pipe run along u: pipes side by side (offset in v), on
    trapeze hangers from the ceiling."""
    vmax = max(dv + r for dv, r, _ in pipes)
    vmin = min(dv - r for dv, r, _ in pipes)
    for dv, r, mat in pipes:
        hh = h + r
        B.pipes.tube((u0, v + dv, hh), (u1, v + dv, hh), r, mat, 12)
    u = u0 + 0.3
    while u < u1 - 0.1:
        _hanger(B, u, v + vmin - 0.05, v + vmax + 0.05, h, top)
        for dv, r, _ in pipes:  # clamp bands
            p0, p1 = (u + 0.05, v + dv, h + r), (u + 0.09, v + dv, h + r)
            B.struct.tube(p0, p1, r + 0.008, GUNMETAL, 12)
        u += hanger_every


def duct_run(B: Builders, u0: float, u1: float, v0: float, v1: float, h0: float, h1: float,
             top: float) -> None:  # fmt: skip
    """Rectangular ventilation duct along u: flanged sections every 1.2 m,
    a louvred outlet every third section, hangers to the ceiling."""
    box(B.panels, u0, u1, v0, v1, h0, h1, MID)
    u, k = u0 + 1.2, 0
    while u < u1 - 0.05:
        box(B.struct, u - 0.025, u + 0.025, v0 - 0.02, v1 + 0.02, h0 - 0.02, h1 + 0.02, GUNMETAL)
        if k % 3 == 1:
            # Outlet grille on the duct's underside.
            box(B.flat, u - 0.85, u - 0.35, v0 + 0.06, v1 - 0.06, h0 - 0.012, h0, RECESS)
            for j in range(6):
                vv = v0 + 0.08 + j * (v1 - v0 - 0.16) / 6
                box(B.flat, u - 0.84, u - 0.36, vv, vv + 0.02, h0 - 0.02, h0 - 0.012, GUNMETAL)
        if k % 2 == 0:
            _hanger(B, u + 0.3, v0 - 0.04, v1 + 0.04, h0 - 0.02, top)
            box(B.struct, u + 0.28, u + 0.32, v0 - 0.04, v0 - 0.02, h0 - 0.02, h1 + 0.02, GUNMETAL)
            box(B.struct, u + 0.28, u + 0.32, v1 + 0.02, v1 + 0.04, h0 - 0.02, h1 + 0.02, GUNMETAL)
        u += 1.2
        k += 1


def cable_ladder(B: Builders, u0: float, u1: float, v0: float, v1: float, h: float,
                 top: float, *, cables: int = 4) -> None:  # fmt: skip
    """Overhead cable ladder: two side rails, rungs every 0.3 m, a bundle of
    cables laid in it, hangers every 2.4 m."""
    for v in (v0, v1 - 0.03):
        box(B.struct, u0, u1, v, v + 0.03, h, h + 0.08, GUNMETAL)
    u = u0 + 0.15
    while u < u1:
        box(B.struct, u - 0.012, u + 0.012, v0, v1, h, h + 0.02, GUNMETAL)
        u += 0.3
    for i in range(cables):
        v = v0 + 0.06 + i * (v1 - v0 - 0.12) / max(1, cables - 1)
        B.pipes.tube((u0, v, h + 0.04), (u1, v, h + 0.04), 0.018 + 0.006 * (i % 2), RUBBER, 6)
    u = u0 + 0.4
    while u < u1 - 0.1:
        for v in (v0 + 0.015, v1 - 0.015):
            box(B.struct, u - 0.01, u + 0.01, v - 0.01, v + 0.01, h + 0.08, top, STEEL)
        u += 2.4


# ---------------------------------------------------------------- engine room
# Heavy industrial pieces for engine-room decks (engineering): coolant tanks,
# wall pipe manifolds with valves, static heat vents, hazard bands, guard
# rails, a wall-mounted maintenance gantry and an overhead gantry crane.

HAZARD = "M_Paint_Hazard"
GLOW = "M_Light_Maint_Amber"


def valve_wheel(B: Builders, cu: float, v: float, h: float, *, r: float = 0.11,
                red: bool = False) -> None:  # fmt: skip
    """Hand wheel facing +v: a rim of short tube segments, a hub and three
    spokes (red or dark paint)."""
    mat = "M_Paint_TrimRed" if red else GUNMETAL
    n = 10
    for i in range(n):
        a0, a1 = 2 * math.pi * i / n, 2 * math.pi * (i + 1) / n
        B.struct.tube((cu + r * math.cos(a0), v, h + r * math.sin(a0)),
                      (cu + r * math.cos(a1), v, h + r * math.sin(a1)), 0.012, mat, 6,
                      caps=False)  # fmt: skip
    B.struct.tube((cu, v - 0.06, h), (cu, v + 0.012, h), 0.022, STEEL, 8)
    for i in range(3):
        a = 2 * math.pi * i / 3 + 0.4
        B.struct.tube((cu, v, h), (cu + r * math.cos(a), v, h + r * math.sin(a)), 0.008, mat, 4,
                      caps=False)  # fmt: skip


def gauge(B: Builders, cu: float, v: float, h: float, *, r: float = 0.06) -> None:
    """Round pressure gauge facing +v: steel bezel, white dial, dark needle."""
    B.struct.tube((cu, v, h), (cu, v + 0.03, h), r + 0.012, STEEL, 14)
    B.lamps.tube((cu, v + 0.03, h), (cu, v + 0.033, h), r, "M_Indicator_White", 14)
    box(B.flat, cu - 0.004, cu + 0.004, v + 0.033, v + 0.036, h, h + r * 0.8, RECESS)


def hazard_band(B: Builders, u0: float, u1: float, v0: float, v1: float, h0: float = 0.0,
                h1: float = 0.004) -> None:  # fmt: skip
    """Opaque worn amber/black hazard paint: a flush floor band at a
    threshold, or a band on a kick plate or plinth when ``h1`` is higher."""
    box(B.flat, u0, u1, v0, v1, h0, h1, HAZARD)


def coolant_tank(B: Builders, cu: float, cv: float, *, r: float = 0.55, h: float = 2.7,
                 seed=0) -> None:  # fmt: skip
    """Upright coolant tank on a hazard-banded plinth: insulated body with
    steel bands and a stepped crown, a lit level sight-glass on its front
    (+v), a gauge, an outlet with a hand wheel and feed pipes into the wall
    behind it (v = 0)."""
    p = r + 0.12
    box(B.struct, cu - p, cu + p, cv - p, cv + p, 0.0, 0.16, GUNMETAL)
    hazard_band(B, cu - p, cu + p, cv + p, cv + p + 0.005, 0.02, 0.14)
    for s in (-1, 1):
        a, b = sorted((cu + s * p, cu + s * (p + 0.005)))
        hazard_band(B, a, b, cv - p, cv + p, 0.02, 0.14)
    B.struct.tube((cu, cv, 0.16), (cu, cv, 0.36), r + 0.04, GUNMETAL, 28)
    B.panels.tube((cu, cv, 0.36), (cu, cv, h - 0.25), r, PIPE_INS, 28)
    B.struct.tube((cu, cv, h - 0.25), (cu, cv, h - 0.12), r - 0.06, GUNMETAL, 28)
    B.struct.tube((cu, cv, h - 0.12), (cu, cv, h), r * 0.55, GUNMETAL, 20)
    z = 0.75
    while z < h - 0.4:
        B.struct.tube((cu, cv, z), (cu, cv, z + 0.06), r + 0.02, GUNMETAL, 28)
        z += 0.62
    # Level sight-glass: a lit column in a steel frame on the front.
    fv = cv + r
    box(B.struct, cu - 0.07, cu + 0.07, fv - 0.04, fv + 0.03, 0.55, h - 0.5, GUNMETAL)
    level = 0.35 + 0.5 * seed01(seed, "lvl")
    top = 0.6 + (h - 1.15) * level
    box(B.lamps, cu - 0.03, cu + 0.03, fv + 0.03, fv + 0.034, 0.6, top, "M_Indicator_Blue")
    box(B.flat, cu - 0.03, cu + 0.03, fv + 0.03, fv + 0.034, top, h - 0.55, RECESS)
    gauge(B, cu + 0.3, fv - 0.08, 1.45)
    # Outlet low on one side with a hand wheel, then into the wall.
    side = 1 if seed01(seed, "side") < 0.5 else -1
    ou = cu + side * (r + 0.02)
    ue = ou + side * 0.25
    B.pipes.tube((ou, cv, 0.55), (ue, cv, 0.55), 0.06, PIPE, 12)
    B.pipes.tube((ue, cv, 0.55), (ue, 0.0, 0.55), 0.06, PIPE, 12)
    valve_wheel(B, ue, cv + 0.12, 0.55, red=seed01(seed, "red") < 0.4)
    B.pipes.tube((cu, cv, h - 0.06), (cu, cv, h + 0.25), 0.07, PIPE, 12)
    B.pipes.tube((cu, cv, h + 0.25), (cu, 0.0, h + 0.25), 0.07, PIPE, 12)
    box(B.struct, cu - 0.12, cu + 0.12, 0.0, 0.04, h + 0.13, h + 0.37, GUNMETAL)


def pipe_manifold(B: Builders, u0: float, u1: float, *, h: float = 2.05, drops: int = 4,
                  seed=0) -> None:  # fmt: skip
    """Wall pipe manifold: a header across the span on brackets, ``drops``
    branches down to a floor header, each with a flanged valve, a hand wheel
    and (on most) a gauge; a lit status tag on the header."""
    v = 0.16
    for hh, rr, mat in ((h, 0.075, PIPE_INS), (0.32, 0.065, PIPE)):
        B.pipes.tube((u0, v, hh), (u1, v, hh), rr, mat, 14)
        for uu in (u0 + 0.12, u1 - 0.12):
            box(B.struct, uu - 0.04, uu + 0.04, 0.0, v + 0.09, hh - 0.11, hh - 0.07, GUNMETAL)
        for uu in (u0, u1):
            B.struct.tube((uu - 0.02, v, hh), (uu + 0.02, v, hh), rr + 0.025, GUNMETAL, 14)
    step = (u1 - u0) / (drops + 1)
    for i in range(drops):
        du = u0 + step * (i + 1)
        B.pipes.tube((du, v, 0.32), (du, v, h), 0.045, PIPE, 10)
        hv = 0.95 + 0.25 * seed01(seed, "vh", i)
        B.struct.tube((du, v, hv - 0.09), (du, v, hv + 0.09), 0.075, GUNMETAL, 12)  # valve body
        for f in (hv - 0.11, hv + 0.09):
            B.struct.tube((du, v, f), (du, v, f + 0.02), 0.09, STEEL, 12)
        B.struct.tube((du, v, hv), (du, v + 0.16, hv), 0.02, STEEL, 6)
        valve_wheel(B, du, v + 0.17, hv, red=seed01(seed, "wr", i) < 0.25)
        if seed01(seed, "g", i) < 0.6:
            gauge(B, du + 0.13, v + 0.02, h - 0.3)
            B.pipes.tube((du, v, h - 0.3), (du + 0.13, v, h - 0.3), 0.012, STEEL, 6)
    box(B.struct, u0 + 0.3, u0 + 0.7, v + 0.07, v + 0.1, h + 0.1, h + 0.24, DARK)
    box(B.lamps, u0 + 0.33, u0 + 0.45, v + 0.1, v + 0.103, h + 0.15, h + 0.19,
        _pip_mat(seed, "tag"))  # fmt: skip


def heat_vent(B: Builders, cu: float, h0: float, *, w: float = 0.9, h: float = 0.5,
              glow: bool = True) -> None:  # fmt: skip
    """Static heat vent on a wall: heavy frame, slanted slats and a dim amber
    glow behind them (exhaust from the machinery behind the wall)."""
    box(B.struct, cu - w / 2 - 0.06, cu + w / 2 + 0.06, 0.0, 0.09, h0 - 0.06, h0 + h + 0.06,
        GUNMETAL)  # fmt: skip
    box(B.lamps if glow else B.flat, cu - w / 2, cu + w / 2, 0.09, 0.092, h0, h0 + h,
        GLOW if glow else RECESS)  # fmt: skip
    n = max(4, int(h / 0.07))
    pitch = h / n
    for k in range(n):
        z = h0 + k * pitch + pitch * 0.15
        B.struct.prism_x([(0.092, z), (0.13, z + pitch * 0.25), (0.13, z + pitch * 0.7),
                          (0.092, z + pitch * 0.45)], cu - w / 2, cu + w / 2,
                         GUNMETAL)  # fmt: skip
    for su in (-1, 1):
        for sh in (0, 1):
            uc, hc = cu + su * (w / 2 + 0.03), h0 - 0.03 + sh * (h + 0.06)
            box(B.flat, uc - 0.012, uc + 0.012, 0.09, 0.096, hc - 0.012, hc + 0.012, STEEL)


def guard_rail(B: Builders, u0: float, u1: float, v: float, h0: float, *, height: float = 1.05,
               kick: bool = True) -> None:  # fmt: skip
    """Guard rail along u at ``v``: posts every 1.2 m, a top and a knee rail,
    a hazard-painted kick plate."""
    u = u0
    while u <= u1 + 1e-6:
        box(B.struct, u - 0.025, u + 0.025, v - 0.025, v + 0.025, h0, h0 + height, GUNMETAL)
        u += 1.2
    B.struct.tube((u0, v, h0 + height), (u1, v, h0 + height), 0.024, STEEL, 8)
    B.struct.tube((u0, v, h0 + height * 0.5), (u1, v, h0 + height * 0.5), 0.016, GUNMETAL, 8)
    if kick:
        box(B.flat, u0, u1, v - 0.006, v + 0.006, h0, h0 + 0.12, HAZARD)


def maintenance_gantry(B: Builders, u0: float, u1: float, *, h: float = 2.75,
                       depth: float = 0.95) -> None:  # fmt: skip
    """Wall-mounted maintenance gantry: a grated walkway at ``h`` on
    triangular wall brackets, a guard rail on its open side and work lamps
    under it (the access ladder is ``gantry_ladder``)."""
    box(B.struct, u0, u1, 0.0, depth, h - 0.08, h - 0.04, GUNMETAL)
    box(B.flat, u0 + 0.03, u1 - 0.03, 0.03, depth - 0.03, h - 0.04, h, GRATING)
    for vv in (0.0, depth - 0.06):
        box(B.struct, u0, u1, vv, vv + 0.06, h - 0.2, h, GUNMETAL)
    u = u0 + 0.3
    while u < u1:
        B.struct.prism_x([(0.0, h - 0.2), (depth - 0.06, h - 0.2), (0.0, h - 0.95)],
                         u - 0.03, u + 0.03, GUNMETAL)  # fmt: skip
        if u + 0.6 < u1:
            box(B.lamps, u + 0.4, u + 0.6, 0.3, 0.5, h - 0.215, h - 0.205, "M_Light_WallStrip")
        u += 1.8
    guard_rail(B, u0, u1, depth - 0.03, h)
    for uu in (u0, u1):
        box(B.struct, uu - 0.025, uu + 0.025, 0.0, depth, h + 1.03, h + 1.07, GUNMETAL)


def gantry_ladder(B: Builders, cu: float, *, h: float = 2.75, w: float = 0.5) -> None:
    """Vertical access ladder against a wall up to a gantry at ``h``, with a
    hazard band on the floor at its foot."""
    for s in (-1, 1):
        box(B.struct, cu + s * w / 2 - 0.025, cu + s * w / 2 + 0.025, 0.12, 0.18, 0.0, h + 1.0,
            GUNMETAL)  # fmt: skip
    z = 0.3
    while z < h:
        B.struct.tube((cu - w / 2, 0.15, z), (cu + w / 2, 0.15, z), 0.014, STEEL, 6)
        z += 0.3
    for z in (0.6, h - 0.4):
        box(B.struct, cu - 0.02, cu + 0.02, 0.0, 0.15, z, z + 0.05, GUNMETAL)
    hazard_band(B, cu - w / 2 - 0.04, cu + w / 2 + 0.04, 0.0, 0.5)


def gantry_crane(B: Builders, u0: float, u1: float, v0: float, v1: float, h: float, top: float,
                 *, at: float = 0.5, hook: float = 2.4) -> None:  # fmt: skip
    """Overhead gantry crane: two runway beams along u at ``v0`` / ``v1``
    hung from the ceiling, a bridge girder across them at ``at`` (0..1) with
    a thin hazard band on its flanks, end trucks, a hoist trolley and a hook block on
    its cables down to ``hook`` metres."""
    for v in (v0, v1):
        box(B.struct, u0, u1, v - 0.1, v + 0.1, h, h + 0.04, GUNMETAL)
        box(B.struct, u0, u1, v - 0.025, v + 0.025, h + 0.04, h + 0.32, GUNMETAL)
        box(B.struct, u0, u1, v - 0.1, v + 0.1, h + 0.32, h + 0.36, GUNMETAL)
        u = u0 + 0.4
        while u < u1:
            box(B.struct, u - 0.015, u + 0.015, v - 0.015, v + 0.015, h + 0.36, top, STEEL)
            u += 2.4
    bu = u0 + (u1 - u0) * at
    gb, gt = h - 0.5, h - 0.02
    box(B.struct, bu - 0.2, bu + 0.2, v0 - 0.15, v1 + 0.15, gb, gt, GUNMETAL)
    for s in (-1, 1):  # a thin worn band along the girder's lower edge
        a, b = sorted((bu + s * 0.2, bu + s * 0.206))
        box(B.flat, a, b, v0 - 0.15, v1 + 0.15, gb + 0.03, gb + 0.1, HAZARD)
    for v in (v0, v1):  # end trucks riding the runways
        box(B.struct, bu - 0.45, bu + 0.45, v - 0.16, v + 0.16, h - 0.18, h, BODY)
        box(B.lamps, bu + 0.3, bu + 0.36, v - 0.165, v - 0.16, h - 0.12, h - 0.06,
            "M_Indicator_Amber")  # fmt: skip
    tv = v0 + (v1 - v0) * 0.42
    box(B.struct, bu - 0.32, bu + 0.32, tv - 0.35, tv + 0.35, gb - 0.42, gb, BODY)
    box(B.struct, bu - 0.34, bu + 0.34, tv - 0.12, tv + 0.12, gb - 0.5, gb - 0.42, GUNMETAL)
    for du in (-0.08, 0.08):
        B.pipes.tube((bu + du, tv, gb - 0.5), (bu + du, tv, hook + 0.35), 0.008, STEEL, 4)
    box(B.struct, bu - 0.14, bu + 0.14, tv - 0.09, tv + 0.09, hook + 0.1, hook + 0.36, HAZARD)
    B.struct.tube((bu, tv, hook + 0.1), (bu, tv, hook - 0.05), 0.025, STEEL, 8)
    B.struct.tube((bu, tv - 0.04, hook - 0.08), (bu, tv + 0.04, hook - 0.08), 0.06, STEEL, 10)
