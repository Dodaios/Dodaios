"""Bespoke furniture of the Operations deck, built straight into deck meshes.

These stand in for the shared prop kit until props-command / props-industrial
pieces exist (``dressing.py`` swaps a piece in when ``kit.registry()`` has
it). They follow the same bar: bevelled, real sizes, fixed to the deck, made
of the shared materials. Every function adds geometry to the ``Mesh`` it is
given (one mesh per room keeps the object count low) and returns the socket
positions it implies, in deck coordinates (x, z, h).
"""

from __future__ import annotations

import math

from decks.ops.geo import Mesh

STEEL = "M_Struct_Gunmetal"
BRUSHED = "M_Trim_BrushedSteel"
DARK = "M_Wall_PaintedDark"
LIGHT = "M_Wall_PaintedLight"
MID = "M_Wall_PaintedMid"
RECESS = "M_Recess_Dark"
SEAT = "M_Seat_Upholstery"
BODY = "M_Console_Body"
DECK = "M_Console_Deck"
SCREEN = "M_Screen"


# ---------------------------------------------------------------- mess


def mess_table(
    m: Mesh,
    soft: Mesh,
    cx: float,
    cz: float,
    seats_per_side: int = 3,
    pitch: float = 1.2,
    top: str = "M_Ops_Table_Top",
) -> list[tuple[float, float, float]]:
    """Refectory table fixed to the deck with a bench on each side.
    Returns seat sockets (x, z, yaw): north bench faces the camera."""
    length = seats_per_side * pitch
    a, b = cx - length / 2, cx + length / 2
    # Top: black lacquer slab on a steel apron.
    m.box(a, b, cz - 0.45, cz + 0.45, 0.70, 0.74, top)
    m.box(a + 0.05, b - 0.05, cz - 0.4, cz + 0.4, 0.66, 0.70, STEEL)
    # Two T-pedestals and a floor rail.
    for x in (a + 0.5, b - 0.5):
        m.box(x - 0.06, x + 0.06, cz - 0.06, cz + 0.06, 0.0, 0.66, STEEL)
        m.box(x - 0.05, x + 0.05, cz - 0.38, cz + 0.38, 0.0, 0.05, STEEL)
    m.box(a + 0.5, b - 0.5, cz - 0.04, cz + 0.04, 0.12, 0.18, STEEL)
    seats = []
    for side in (-1, 1):
        bz = cz + side * 0.82
        soft.box(a + 0.08, b - 0.08, bz - 0.18, bz + 0.18, 0.40, 0.46, SEAT)
        m.box(a + 0.1, b - 0.1, bz - 0.15, bz + 0.15, 0.36, 0.40, STEEL)
        for x in (a + 0.5, b - 0.5):
            m.box(x - 0.04, x + 0.04, bz - 0.04, bz + 0.04, 0.0, 0.36, STEEL)
            m.box(x - 0.04, x + 0.04, min(bz, cz), max(bz, cz), 0.1, 0.16, STEEL)
        for i in range(seats_per_side):
            x = a + pitch * (i + 0.5)
            seats.append((x, bz, 0.0 if side < 0 else 180.0))
    return seats


def table_clutter(m: Mesh, cx: float, cz: float, seed: int, length: float = 3.6) -> None:
    """A few trays and cups left on a table (deterministic)."""
    rnd = _rng(seed)
    for i in range(int(length / 1.2)):
        x = cx - length / 2 + 0.6 + i * 1.2
        if rnd() < 0.55:
            side = -1 if rnd() < 0.5 else 1
            tz = cz + side * 0.2
            m.box(x - 0.22, x + 0.22, tz - 0.15, tz + 0.15, 0.74, 0.755, BRUSHED)
            m.box(x - 0.16, x - 0.02, tz - 0.09, tz + 0.05, 0.755, 0.765, MID)
        if rnd() < 0.5:
            m.cyl(
                x + 0.3 * (rnd() - 0.5), cz + 0.25 * (rnd() - 0.5), 0.035, 0.74, 0.84, BRUSHED, 12
            )


def mess_place_settings(m: Mesh, cx: float, cz: float, seed: int, top: float = 0.75) -> None:
    """Trays, plates and cups left at some places of a kit mess table (six
    places at x -0.68 / 0 / 0.68 on both long sides; the caddy sits in the
    middle). Deterministic per table."""
    rnd = _rng(seed)
    for side in (-1, 1):
        for dx in (-0.68, 0.0, 0.68):
            r = rnd()
            if r > 0.45:
                continue
            x, z = cx + dx + 0.05 * (rnd() - 0.5), cz + side * 0.2
            m.box(x - 0.2, x + 0.2, z - 0.14, z + 0.14, top, top + 0.012, BRUSHED)
            m.box(x - 0.19, x + 0.19, z - 0.13, z + 0.13, top + 0.012, top + 0.016, MID)
            m.cyl(x - 0.06, z, 0.095, top + 0.016, top + 0.03, LIGHT, 20)
            if r < 0.3:
                m.cyl(x + 0.12, z - side * 0.06, 0.034, top + 0.016, top + 0.11, BRUSHED, 12)
            if r < 0.12:
                za, zb = sorted((z + side * 0.02, z + side * 0.09))
                m.box(x + 0.07, x + 0.17, za, zb, top + 0.016, top + 0.05, DARK)


def serving_counter(m: Mesh, lights: Mesh, x0: float, x1: float, z0: float) -> None:
    """Serving line along the far wall: steel counter, heated wells under a
    sneeze guard, tray slide on the room side."""
    z1 = z0 + 0.95
    m.box(x0, x1, z0, z1 - 0.05, 0.0, 0.9, BRUSHED)
    m.box(x0 - 0.02, x1 + 0.02, z1 - 0.06, z1, 0.08, 0.9, DARK)  # front skin
    m.box(x0, x1, z1 - 0.06, z1 + 0.01, 0.0, 0.08, "M_Rubber_Black")
    m.box(x0 - 0.03, x1 + 0.03, z0 - 0.02, z1 + 0.02, 0.9, 0.94, BRUSHED)
    n = int((x1 - x0) / 0.62)
    for i in range(n):
        x = x0 + 0.3 + i * (x1 - x0 - 0.6) / max(n - 1, 1)
        m.box(x - 0.27, x + 0.27, z0 + 0.12, z0 + 0.6, 0.915, 0.94, RECESS)
        m.box(x - 0.24, x + 0.24, z0 + 0.15, z0 + 0.57, 0.92, 0.93, "M_Trim_Chrome")
    # Sneeze guard posts and glass.
    for i in range(int((x1 - x0) / 1.2) + 1):
        x = x0 + 0.1 + i * (x1 - x0 - 0.2) / max(int((x1 - x0) / 1.2), 1)
        m.box(x - 0.02, x + 0.02, z0 + 0.66, z0 + 0.7, 0.94, 1.38, BRUSHED)
    m.box(x0 + 0.05, x1 - 0.05, z0 + 0.6, z0 + 0.72, 1.36, 1.38, "M_Ops_Glass_Case")
    lights.box(x0 + 0.1, x1 - 0.1, z0 + 0.62, z0 + 0.7, 1.345, 1.355, "M_Ops_Light_Hatch")
    # Tray slide.
    for k in range(3):
        m.box(x0, x1, z1 + 0.05 + k * 0.1, z1 + 0.07 + k * 0.1, 0.86, 0.88, BRUSHED)
    for x in (x0 + 0.3, x1 - 0.3, (x0 + x1) / 2):
        m.box(x - 0.02, x + 0.02, z1, z1 + 0.28, 0.7, 0.86, BRUSHED)


def dispenser(m: Mesh, lights: Mesh, cx: float, z0: float) -> None:
    """Drink dispenser cabinet against the wall: lit panel, two taps."""
    w = 1.0
    a, b = cx - w / 2, cx + w / 2
    m.box(a, b, z0, z0 + 0.62, 0.0, 1.85, BODY)
    m.box(a + 0.04, b - 0.04, z0 + 0.62, z0 + 0.64, 0.95, 1.75, DECK)
    lights.box(a + 0.12, b - 0.12, z0 + 0.64, z0 + 0.65, 1.42, 1.7, "M_Screen")
    m.box(a + 0.08, b - 0.08, z0 + 0.3, z0 + 0.64, 0.92, 0.95, BRUSHED)
    m.box(a + 0.1, b - 0.1, z0 + 0.35, z0 + 0.6, 0.6, 0.62, "M_Floor_Grating")
    for x in (cx - 0.2, cx + 0.2):
        m.box(x - 0.04, x + 0.04, z0 + 0.5, z0 + 0.62, 0.86, 0.94, "M_Trim_Chrome")
    lights.box(a + 0.1, a + 0.15, z0 + 0.64, z0 + 0.65, 1.0, 1.04, "M_Indicator_Green")
    m.box(a, b, z0 - 0.02, z0 + 0.66, 1.85, 1.9, STEEL)


def tray_stand(m: Mesh, x0: float, x1: float, z0: float) -> None:
    m.box(x0, x1, z0, z0 + 0.6, 0.0, 0.85, BRUSHED)
    for k in range(12):
        m.box(
            x0 + 0.05,
            x1 - 0.05,
            z0 + 0.05,
            z0 + 0.55,
            0.85 + k * 0.012,
            0.86 + k * 0.012,
            MID if k % 2 else BRUSHED,
        )


def lean_rail(m: Mesh, x0: float, x1: float, z: float) -> None:
    """Standing ledge under the viewport."""
    m.box(x0, x1, z - 0.16, z + 0.16, 1.02, 1.06, "M_Ops_Table_Top")
    m.box(x0, x1, z - 0.15, z + 0.15, 0.98, 1.02, STEEL)
    n = int((x1 - x0) / 2.4) + 1
    for i in range(n):
        x = x0 + 0.15 + i * (x1 - x0 - 0.3) / max(n - 1, 1)
        m.box(x - 0.04, x + 0.04, z - 0.04, z + 0.04, 0.0, 0.98, STEEL)
    m.box(x0, x1, z + 0.08, z + 0.12, 0.18, 0.22, BRUSHED)  # foot rail


# ---------------------------------------------------------------- records


TIERS = (
    ("M_Ops_Enamel_Steel", (1, 3, 5, 8)),
    ("M_Ops_Enamel_Blue", (11, 14, 17, 21, 25)),
    ("M_Ops_Enamel_Red", (29, 33)),
    ("M_Ops_Enamel_Gold", (37, 41, 45, 50)),
)


def rank_board(m: Mesh, lights: Mesh, x0: float, x1: float, z: float, h0: float, h1: float) -> None:
    """The fleet's rank ladder: one row per tier, a steel rank plate per rank
    with up to six inset tiles (the plate pattern of the uniforms)."""
    m.box(x0 - 0.1, x1 + 0.1, z - 0.05, z + 0.05, h0 - 0.1, h1 + 0.1, STEEL)
    m.box(x0, x1, z + 0.05, z + 0.08, h0, h1, "M_Ops_Table_Top")
    rows = len(TIERS)
    row_h = (h1 - h0 - 0.35) / rows
    m.box(x0, x1, z + 0.08, z + 0.1, h1 - 0.3, h1 - 0.05, DARK)
    lights.box(x0 + 0.2, x1 - 0.2, z + 0.1, z + 0.105, h1 - 0.2, h1 - 0.17, "M_Light_WallStrip")
    for r, (mat, ranks) in enumerate(TIERS):
        hc = h1 - 0.35 - row_h * (r + 0.5)
        m.box(
            x0 + 0.1, x1 - 0.1, z + 0.08, z + 0.095, hc - row_h * 0.46, hc - row_h * 0.43, BRUSHED
        )
        n = len(ranks)
        pw = 0.62
        gap = (x1 - x0 - n * pw) / (n + 1)
        for i in range(n):
            px = x0 + gap + i * (pw + gap)
            m.box(px, px + pw, z + 0.08, z + 0.11, hc - 0.16, hc + 0.16, "M_Ops_Enamel_Steel")
            tiles = min(6, 1 + i + (2 if r >= 2 else 0) + (1 if r == 3 else 0))
            for t in range(6):
                tx = px + 0.08 + (t % 3) * 0.17
                th = hc + (0.04 if t < 3 else -0.1)
                on = t < tiles
                m.box(
                    tx,
                    tx + 0.12,
                    z + 0.11,
                    z + (0.125 if on else 0.112),
                    th,
                    th + 0.07,
                    mat if on else RECESS,
                )


def display_case(m: Mesh, glass: Mesh, lights: Mesh, cx: float, cz: float, seed: int) -> None:
    """Commendation case: steel plinth, glass hood, medals on a dark bed."""
    a, b, c, d = cx - 0.9, cx + 0.9, cz - 0.35, cz + 0.35
    m.box(a, b, c, d, 0.0, 0.08, "M_Rubber_Black")
    m.box(a + 0.02, b - 0.02, c + 0.02, d - 0.02, 0.08, 0.86, STEEL)
    m.box(a, b, c, d, 0.86, 0.9, BRUSHED)
    m.box(a + 0.06, b - 0.06, c + 0.06, d - 0.06, 0.9, 0.92, "M_Seat_Upholstery")
    glass.box(a + 0.03, b - 0.03, c + 0.03, d - 0.03, 0.9, 1.12, "M_Ops_Glass_Case")
    m.box(a, b, c, d, 1.12, 1.14, BRUSHED)
    rnd = _rng(seed)
    for i in range(5):
        x = a + 0.3 + i * 0.3
        mat = ("M_Ops_Enamel_Gold", "M_Ops_Enamel_Steel", "M_Ops_Enamel_Red", "M_Ops_Enamel_Blue")[
            int(rnd() * 4)
        ]
        m.cyl(x, cz + 0.05 * (rnd() - 0.5), 0.055, 0.92, 0.935, mat, 16)
        m.box(x - 0.015, x + 0.015, cz - 0.2, cz - 0.07, 0.92, 0.926, "M_Ops_Enamel_Red")
    lights.box(a + 0.1, b - 0.1, c + 0.05, c + 0.07, 1.1, 1.11, "M_Light_FloorInlay")


def lectern(m: Mesh, lights: Mesh, cx: float, cz: float) -> None:
    """Speaker's lectern; the speaker stands north of it, facing the hall."""
    m.box(cx - 0.35, cx + 0.35, cz - 0.25, cz + 0.25, 0.0, 0.06, STEEL)
    m.box(cx - 0.12, cx + 0.12, cz - 0.1, cz + 0.1, 0.06, 1.0, BODY)
    m.quad(
        [
            (cx - 0.36, cz - 0.3, 1.18),
            (cx + 0.36, cz - 0.3, 1.18),
            (cx + 0.36, cz + 0.12, 1.0),
            (cx - 0.36, cz + 0.12, 1.0),
        ],
        DECK,
    )
    m.box(cx - 0.36, cx + 0.36, cz - 0.3, cz + 0.12, 0.96, 1.0, BODY)
    lights.box(cx - 0.3, cx + 0.3, cz + 0.12, cz + 0.13, 0.9, 0.93, "M_Indicator_Blue")


# ---------------------------------------------------------------- simulator


def wall_seg(m: Mesh, p0, p1, t: float, h0: float, h1: float, mat: str, cap: str | None = None):
    """A straight wall slab between plan points p0 -> p1 (x, z), thickness t to
    the left of the direction of travel, from h0 to h1; ``cap`` paints its top."""
    (x0, z0), (x1, z1) = p0, p1
    dx, dz = x1 - x0, z1 - z0
    n = math.hypot(dx, dz)
    ox, oz = -dz / n * t, dx / n * t
    a, b, c, d = (x0, z0), (x1, z1), (x1 + ox, z1 + oz), (x0 + ox, z0 + oz)
    ring = [a, b, c, d]
    for i in range(4):
        (ax, az), (bx, bz) = ring[i], ring[(i + 1) % 4]
        m.quad([(ax, az, h0), (bx, bz, h0), (bx, bz, h1), (ax, az, h1)], mat)
    m.poly([(x, z, h1) for x, z in ring], cap or mat)
    m.poly([(x, z, h0) for x, z in ring[::-1]], mat)


def octagon(cx: float, cz: float, w: float, d: float, ch: float):
    """Plan octagon (counter-clockwise from the south-west corner) with 45° chamfers."""
    x0, x1, z0, z1 = cx - w / 2, cx + w / 2, cz - d / 2, cz + d / 2
    return [
        (x0 + ch, z1),
        (x1 - ch, z1),
        (x1, z1 - ch),
        (x1, z0 + ch),
        (x1 - ch, z0),
        (x0 + ch, z0),
        (x0, z0 + ch),
        (x0, z1 - ch),
    ]


def sim_pod(
    m: Mesh,
    soft: Mesh,
    scr: Mesh,
    cx: float,
    cz: float,
    lights: Mesh | None = None,
    walk: Mesh | None = None,
):
    """Simulator pod: an octagonal tub open to the section with a luminous rim
    cap, a wrap-around screen facing the seat (and the camera), the seat on
    the near side and the entry gap at the south."""
    oct_pts = octagon(cx, cz, 2.0, 2.6, 0.5)
    base = walk if walk is not None else m
    # Octagonal plinth: the pod floor people step onto (0.16 m).
    base.poly([(x, z, 0.16) for x, z in oct_pts], DECK)
    base.poly([(x, z, 0.0) for x, z in oct_pts[::-1]], STEEL)
    for i in range(len(oct_pts)):
        (ax, az), (bx, bz) = oct_pts[i], oct_pts[(i + 1) % len(oct_pts)]
        base.quad([(ax, az, 0.0), (bx, bz, 0.0), (bx, bz, 0.16), (ax, az, 0.16)], STEEL)
    n = len(oct_pts)
    for i in range(n):
        if i == 0:
            continue  # the entry: south edge open
        p0, p1 = oct_pts[i], oct_pts[(i + 1) % n]
        wall_seg(m, p1, p0, 0.1, 0.16, 1.05, BODY, cap=STEEL)
        if lights is not None:
            # Rim cap: a thin lit line along the top of the tub wall.
            (x0, z0), (x1, z1) = p0, p1
            k = 0.06 / math.hypot(x1 - x0, z1 - z0)
            ex, ez = (x1 - x0) * k, (z1 - z0) * k
            wall_seg(
                lights,
                (x1 - ex, z1 - ez),
                (x0 + ex, z0 + ez),
                0.03,
                1.05,
                1.058,
                "M_Ops_Light_SimBar",
            )
    # Screen: three panels in an arc, facing +z.
    for ang in (-35.0, 0.0, 35.0):
        r = math.radians(ang)
        px, pz = cx + math.sin(r) * 0.62, cz - 0.95 + (1 - math.cos(r)) * 0.55
        w = 0.62
        dx, dz = math.cos(r) * w / 2, math.sin(r) * w / 2
        scr.quad(
            [
                (px - dx, pz + dz + 0.02, 0.62),
                (px + dx, pz - dz + 0.02, 0.62),
                (px + dx, pz - dz - 0.06, 1.2),
                (px - dx, pz + dz - 0.06, 1.2),
            ],
            SCREEN,
        )
        m.quad(
            [
                (px - dx, pz + dz - 0.01, 0.58),
                (px + dx, pz - dz - 0.01, 0.58),
                (px + dx, pz - dz - 0.1, 1.24),
                (px - dx, pz + dz - 0.1, 1.24),
            ],
            BODY,
        )
    # Control deck, yokes and the seat.
    m.box(cx - 0.4, cx + 0.4, cz - 0.55, cz - 0.25, 0.16, 0.7, BODY)
    m.box(cx - 0.42, cx + 0.42, cz - 0.6, cz - 0.3, 0.7, 0.74, DECK)
    for s in (-1, 1):
        m.cyl(cx + s * 0.22, cz - 0.42, 0.025, 0.74, 0.86, BRUSHED, 8)
    soft.box(cx - 0.28, cx + 0.28, cz + 0.05, cz + 0.55, 0.42, 0.52, SEAT)
    soft.box(cx - 0.28, cx + 0.28, cz + 0.55, cz + 0.68, 0.52, 1.0, SEAT)
    m.box(cx - 0.08, cx + 0.08, cz + 0.2, cz + 0.4, 0.16, 0.42, STEEL)
    seat = (cx, cz + 0.3, 180.0)
    screen = (cx, cz - 0.93, 0.91, 1.7, 0.56)
    return seat, screen


def console(m: Mesh, scr: Mesh, lights: Mesh, x0: float, x1: float, cz: float, tilt: float = 35.0):
    """Desk console facing +z (operator on the +z side, seen over the shoulder).
    Returns the screen socket spec (cx, cz, ch, w, h, tilt)."""
    m.box(x0, x1, cz - 0.4, cz + 0.2, 0.0, 0.08, "M_Rubber_Black")
    m.box(x0 + 0.02, x1 - 0.02, cz - 0.38, cz + 0.18, 0.08, 0.78, BODY)
    m.box(x0, x1, cz - 0.4, cz + 0.4, 0.78, 0.82, DECK)
    m.box(x0 + 0.1, x1 - 0.1, cz + 0.05, cz + 0.32, 0.82, 0.84, "M_Console_Keys")
    t = math.radians(tilt)
    h0, h1 = 0.84, 0.84 + 0.42 * math.cos(t)
    za, zb = cz + 0.0, cz - 0.42 * math.sin(t)
    m.quad(
        [
            (x0 + 0.05, za + 0.01, h0),
            (x1 - 0.05, za + 0.01, h0),
            (x1 - 0.05, zb + 0.01, h1),
            (x0 + 0.05, zb + 0.01, h1),
        ],
        BODY,
    )
    m.box(x0 + 0.05, x1 - 0.05, zb - 0.12, za - 0.02, h0, h1, BODY)
    scr.quad(
        [
            (x0 + 0.1, za + 0.02, h0 + 0.04),
            (x1 - 0.1, za + 0.02, h0 + 0.04),
            (x1 - 0.1, zb + 0.06, h1 - 0.02),
            (x0 + 0.1, zb + 0.06, h1 - 0.02),
        ],
        SCREEN,
    )
    lights.box(x0 + 0.06, x0 + 0.1, cz + 0.4, cz + 0.41, 0.6, 0.64, "M_Indicator_Green")
    lights.box(x0 + 0.13, x0 + 0.17, cz + 0.4, cz + 0.41, 0.6, 0.64, "M_Indicator_Red")
    return ((x0 + x1) / 2, (za + zb) / 2 + 0.05, (h0 + h1) / 2 + 0.01, x1 - x0 - 0.22, 0.4, tilt)


def wall_display(m: Mesh, scr: Mesh, x0: float, x1: float, z: float, h0: float, h1: float) -> None:
    m.box(x0 - 0.12, x1 + 0.12, z - 0.02, z + 0.1, h0 - 0.12, h1 + 0.12, STEEL)
    m.box(x0, x1, z + 0.1, z + 0.11, h0, h1, RECESS)
    scr.box(x0 + 0.02, x1 - 0.02, z + 0.11, z + 0.115, h0 + 0.02, h1 - 0.02, SCREEN)


# ---------------------------------------------------------------- quartermaster


UNIFORMS = (
    "M_Ops_Uniform_Charcoal",
    "M_Ops_Uniform_Olive",
    "M_Ops_Uniform_Black",
    "M_Ops_Uniform_White",
)


def wardrobe(
    m: Mesh, glass: Mesh, x0: float, x1: float, z0: float, tier: int, lights: Mesh
) -> None:
    """Glass-fronted uniform cabinet: tunics on a rail, boots below."""
    z1 = z0 + 0.62
    m.box(x0, x1, z0, z1, 0.0, 0.12, "M_Rubber_Black")
    m.box(x0, x0 + 0.04, z0, z1, 0.12, 2.5, STEEL)
    m.box(x1 - 0.04, x1, z0, z1, 0.12, 2.5, STEEL)
    m.box(x0, x1, z0, z1, 2.46, 2.56, STEEL)
    m.box(x0 + 0.04, x1 - 0.04, z0, z0 + 0.04, 0.12, 2.46, RECESS)
    m.box(x0 + 0.04, x1 - 0.04, z0, z1 - 0.04, 0.12, 0.3, DARK)
    m.box(x0 + 0.04, x1 - 0.04, z0 + 0.28, z0 + 0.3, 2.2, 2.22, BRUSHED)
    n = max(2, int((x1 - x0) / 0.16))
    mat = UNIFORMS[tier]
    for i in range(n):
        x = x0 + 0.1 + i * (x1 - x0 - 0.2) / (n - 1)
        m.box(x - 0.055, x + 0.055, z0 + 0.12, z0 + 0.46, 1.25, 2.12, mat)
        m.box(x - 0.045, x + 0.045, z0 + 0.14, z0 + 0.44, 0.95, 1.25, mat)
    for i in range(int((x1 - x0) / 0.25)):
        x = x0 + 0.15 + i * 0.25
        m.box(x - 0.05, x + 0.05, z0 + 0.15, z0 + 0.4, 0.3, 0.52, "M_Rubber_Black")
    glass.box(x0 + 0.04, x1 - 0.04, z1 - 0.03, z1 - 0.02, 0.32, 2.44, "M_Ops_Glass_Case")
    lights.box(x0 + 0.06, x1 - 0.06, z0 + 0.06, z0 + 0.1, 2.4, 2.42, "M_Light_WallStrip")
    m.box((x0 + x1) / 2 - 0.01, (x0 + x1) / 2 + 0.01, z1 - 0.04, z1, 0.32, 2.44, STEEL)
    # Tier marker tile on the cornice.
    tile = ("M_Ops_Enamel_Steel", "M_Ops_Enamel_Blue", "M_Ops_Enamel_Red", "M_Ops_Enamel_Gold")[
        tier
    ]
    xc = (x0 + x1) / 2
    m.box(xc - 0.08, xc + 0.08, z1, z1 + 0.012, 2.47, 2.55, tile)


def dais(walk: Mesh, m: Mesh, lights: Mesh, cx: float, cz: float, r: float = 1.25) -> None:
    """Fitting platform: a low round dais in a ring of scanner posts."""
    walk.cyl(cx, cz, r, 0.0, 0.14, STEEL, 48)
    walk.cyl(cx, cz, r - 0.08, 0.14, 0.16, "M_Ops_Table_Top", 48)
    lights.cyl(cx, cz, r + 0.02, 0.05, 0.08, "M_Light_FloorInlay", 48)
    for i in range(5):
        t = math.radians(-90 + 180 * i / 4 + 180)
        px, pz = cx + (r + 0.35) * math.cos(t), cz + (r + 0.35) * math.sin(t)
        m.box(px - 0.06, px + 0.06, pz - 0.06, pz + 0.06, 0.0, 2.1, STEEL)
        lights.box(px - 0.02, px + 0.02, pz + 0.06, pz + 0.07, 0.3, 1.95, "M_Light_FloorInlay")


def service_counter(m: Mesh, scr: Mesh, lights: Mesh, x0: float, x1: float, cz: float) -> None:
    m.box(x0, x1, cz - 0.4, cz + 0.4, 0.0, 0.1, "M_Rubber_Black")
    m.box(x0 + 0.02, x1 - 0.02, cz - 0.38, cz + 0.38, 0.1, 1.0, LIGHT)
    m.box(x0 - 0.04, x1 + 0.04, cz - 0.45, cz + 0.45, 1.0, 1.05, "M_Ops_Table_Top")
    for k in range(int((x1 - x0) / 1.2)):
        x = x0 + 0.6 + k * 1.2
        m.box(x - 0.003, x + 0.003, cz + 0.38, cz + 0.39, 0.12, 0.98, RECESS)
    xc = (x0 + x1) / 2
    m.box(xc - 0.3, xc + 0.3, cz - 0.3, cz - 0.1, 1.05, 1.4, BODY)
    scr.quad(
        [
            (xc - 0.26, cz - 0.09, 1.08),
            (xc + 0.26, cz - 0.09, 1.08),
            (xc + 0.26, cz - 0.16, 1.38),
            (xc - 0.26, cz - 0.16, 1.38),
        ],
        SCREEN,
    )
    lights.box(x0 + 0.1, x1 - 0.1, cz + 0.4, cz + 0.41, 0.12, 0.15, "M_Light_FloorInlay")


# ---------------------------------------------------------------- quarters


def berth(
    m: Mesh,
    soft: Mesh,
    lights: Mesh,
    cx: float,
    cz: float,
    heads_north: bool,
    seed: int,
    made: bool = True,
):
    """Single-level bunk berth (no upper berth: the camera must see the
    sleeper). Head unit with a shelf and a warm reading lamp. Returns the bunk
    socket (x, z, h, yaw) and the lamp position."""
    s = -1 if heads_north else 1  # direction from foot to head along z
    head = cz + s * 1.1
    foot = cz - s * 1.1
    za, zb = sorted((head, foot))
    # Frame and drawers.
    m.box(cx - 0.47, cx + 0.47, za, zb, 0.0, 0.08, "M_Rubber_Black")
    m.box(cx - 0.46, cx + 0.46, za + 0.02, zb - 0.02, 0.08, 0.38, BODY)
    m.box(cx - 0.48, cx + 0.48, za, zb, 0.38, 0.42, STEEL)
    fz = zb - 0.03 if not heads_north else za + 0.01
    m.box(cx - 0.44, cx - 0.04, fz, fz + 0.02, 0.14, 0.32, DECK)
    # Mattress, sheet, pillow, blanket (folded at the foot or spread).
    soft.box(cx - 0.43, cx + 0.43, za + 0.03, zb - 0.03, 0.42, 0.55, "M_Ops_Fabric_Sheet")
    pz = head - s * 0.25
    soft.box(cx - 0.3, cx + 0.3, pz - 0.17, pz + 0.17, 0.55, 0.64, "M_Ops_Fabric_Sheet")
    rnd = _rng(seed)
    if made:
        bz0, bz1 = sorted((head - s * 0.5, foot + s * 0.04))
        soft.box(cx - 0.45, cx + 0.45, bz0, bz1, 0.55, 0.585, "M_Ops_Fabric_Blanket")
        fz0, fz1 = sorted((head - s * 0.5, head - s * 0.72))
        soft.box(cx - 0.45, cx + 0.45, fz0, fz1, 0.585, 0.6, "M_Ops_Fabric_Sheet")
    else:
        fz = foot + s * 0.35
        soft.box(cx - 0.42, cx + 0.42, fz - 0.18, fz + 0.18, 0.55, 0.66, "M_Ops_Fabric_Blanket")
    # Head unit: locker column with a shelf niche and the lamp.
    hz0, hz1 = sorted((head, head + s * 0.36))
    m.box(cx - 0.6, cx + 0.6, hz0, hz1, 0.0, 1.55, LIGHT)
    face = head
    nz0, nz1 = sorted((face, face + s * 0.22))
    m.box(cx - 0.42, cx + 0.42, nz0, nz1, 0.72, 1.08, RECESS)
    m.box(cx - 0.6, cx + 0.6, hz0 - 0.01, hz1 + 0.01, 1.55, 1.6, STEEL)
    lz = face + s * 0.04
    lights.box(
        cx - 0.2,
        cx + 0.2,
        min(lz, lz + s * 0.03),
        max(lz, lz + s * 0.03),
        1.05,
        1.07,
        "M_Ops_Light_Reading",
    )
    if rnd() < 0.6:
        m.box(cx + 0.1, cx + 0.3, nz0 + 0.03, nz1 - 0.03, 0.72, 0.9, "M_Ops_Enamel_Steel")
    # Side partitions (edge-on to the camera).
    for x in (cx - 0.62, cx + 0.62):
        m.box(
            x - 0.02,
            x + 0.02,
            za - (0.36 if s < 0 else 0),
            zb + (0.36 if s > 0 else 0),
            0.0,
            1.4,
            MID,
        )
    bunk = (cx, cz + s * 0.15, 0.55, 0.0 if heads_north else 180.0)
    lamp = (cx, face - s * 0.15, 1.0)
    return bunk, lamp


def locker_row(m: Mesh, lights: Mesh, x0: float, x1: float, z0: float, h: float = 2.0) -> None:
    """Tall personal lockers, fronts to the camera, vents and number plates."""
    n = int((x1 - x0) / 0.6)
    w = (x1 - x0) / n
    m.box(x0, x1, z0, z0 + 0.55, 0.0, 0.1, "M_Rubber_Black")
    m.box(x0, x1, z0, z0 + 0.55, h, h + 0.05, STEEL)
    for i in range(n):
        a, b = x0 + i * w + 0.006, x0 + (i + 1) * w - 0.006
        m.box(a, b, z0, z0 + 0.55, 0.1, h, LIGHT)
        for k in range(4):
            hh = h - 0.25 - k * 0.04
            m.box(a + 0.15, b - 0.15, z0 + 0.55, z0 + 0.556, hh, hh + 0.015, RECESS)
        m.box(b - 0.08, b - 0.05, z0 + 0.55, z0 + 0.57, 0.95, 1.15, BRUSHED)
        m.box(a + 0.2, b - 0.2, z0 + 0.55, z0 + 0.553, h - 0.48, h - 0.42, DARK)


def bench(m: Mesh, soft: Mesh, x0: float, x1: float, cz: float) -> None:
    m.box(x0, x1, cz - 0.2, cz + 0.2, 0.38, 0.42, STEEL)
    soft.box(x0 + 0.02, x1 - 0.02, cz - 0.19, cz + 0.19, 0.42, 0.47, SEAT)
    for x in (x0 + 0.15, x1 - 0.15):
        m.box(x - 0.04, x + 0.04, cz - 0.15, cz + 0.15, 0.0, 0.38, STEEL)


def sink_island(m: Mesh, x0: float, x1: float, cz: float) -> None:
    m.box(x0, x1, cz - 0.55, cz + 0.55, 0.0, 0.85, LIGHT)
    m.box(x0 - 0.03, x1 + 0.03, cz - 0.58, cz + 0.58, 0.85, 0.89, BRUSHED)
    n = int((x1 - x0) / 0.8)
    for side in (-1, 1):
        for i in range(n):
            x = x0 + 0.4 + i * (x1 - x0 - 0.8) / max(n - 1, 1)
            m.box(
                x - 0.2,
                x + 0.2,
                cz + side * 0.42 - 0.14,
                cz + side * 0.42 + 0.14,
                0.86,
                0.895,
                "M_Trim_Chrome",
            )
            m.cyl(x, cz + side * 0.2, 0.02, 0.89, 1.1, "M_Trim_Chrome", 8)
    m.box(x0 + 0.1, x1 - 0.1, cz - 0.05, cz + 0.05, 0.89, 1.6, STEEL)
    m.box(x0 + 0.05, x1 - 0.05, cz - 0.08, cz + 0.08, 1.6, 1.65, BRUSHED)


def shower_stalls(m: Mesh, x0: float, x1: float, z0: float, n: int, depth: float = 1.4) -> None:
    """Stalls along a wall at x0 (opening toward +x)."""
    pitch = 1.2
    for i in range(n + 1):
        z = z0 + i * pitch
        m.box(
            x0, x0 + depth, z - 0.03, z + 0.03, 0.0, 2.0, "M_Ops_Glass_Case" if 0 < i < n else LIGHT
        )
        m.box(x0, x0 + depth, z - 0.04, z + 0.04, 2.0, 2.04, BRUSHED)
    for i in range(n):
        zc = z0 + (i + 0.5) * pitch
        m.box(x0 + 0.02, x0 + depth, zc - 0.57, zc + 0.57, 0.0, 0.02, "M_Floor_Grating")
        m.cyl(x0 + 0.12, zc, 0.02, 0.0, 2.1, "M_Trim_Chrome", 8)
        m.cyl(x0 + 0.25, zc, 0.09, 2.05, 2.08, "M_Trim_Chrome", 16)


# ---------------------------------------------------------------- ready rooms


def round_table(
    m: Mesh,
    soft: Mesh,
    lights: Mesh,
    cx: float,
    cz: float,
    r: float = 1.5,
    chairs: int = 8,
    gap_south: bool = True,
):
    """Team table: a black gloss disc with a brushed rim (it reads as a lit ring
    from above), a small projector lens in the centre, eight grey shell chairs.
    Returns seats [(x, z, yaw)] and the holo socket (x, z, h, radius)."""
    m.cyl(cx, cz, 0.5, 0.0, 0.06, "M_Rubber_Black", 48)
    m.cyl(cx, cz, 0.3, 0.06, 0.68, BODY, 32)
    m.cyl(cx, cz, r, 0.7, 0.76, "M_Ops_Table_Top", 96)
    m.cyl(cx, cz, r + 0.04, 0.66, 0.745, BRUSHED, 96)
    m.cyl(cx, cz, 0.3, 0.76, 0.775, STEEL, 32)
    lights.cyl(cx, cz, 0.18, 0.775, 0.782, "M_Indicator_Blue", 32)
    seats = []
    for i in range(chairs):
        ang = 2 * math.pi * (i + 0.5) / chairs + math.pi / 2  # gap at the south (+z)
        if not gap_south:
            ang -= math.pi / chairs
        sx, sz = cx + (r + 0.5) * math.cos(ang), cz + (r + 0.5) * math.sin(ang)
        _chair(m, soft, sx, sz, ang)
        yaw = math.degrees(math.atan2(cx - sx, cz - sz))
        seats.append((sx, sz, yaw))
    return seats, (cx, cz, 0.8, 0.4)


def _chair(m: Mesh, soft: Mesh, x: float, z: float, ang: float) -> None:
    """Swivel shell chair turned to the table; the back sits on the far side."""
    m.cyl(x, z, 0.27, 0.0, 0.025, STEEL, 24)
    m.cyl(x, z, 0.035, 0.025, 0.4, BRUSHED, 10)
    soft.cyl(x, z, 0.25, 0.4, 0.48, MID, 24)
    soft.cyl(x, z, 0.21, 0.48, 0.5, SEAT, 24)
    ux, uz = math.cos(ang), math.sin(ang)  # radial, away from the table
    tx, tz = -uz, ux
    bx, bz = x + ux * 0.24, z + uz * 0.24
    p0 = (bx - tx * 0.23, bz - tz * 0.23)
    p1 = (bx + tx * 0.23, bz + tz * 0.23)
    wall_seg(soft, p0, p1, 0.06, 0.48, 0.98, MID, cap=STEEL)


def display_pylon(
    m: Mesh, scr: Mesh, x0: float, x1: float, z: float, h0: float = 1.0, h1: float = 2.7
) -> None:
    """Freestanding display wall facing the camera (the room's far wall is cut
    at 1.1 m, so wall screens stand on their own plinth)."""
    m.box(x0 - 0.1, x1 + 0.1, z - 0.3, z + 0.1, 0.0, 0.9, BODY)
    m.box(x0 - 0.12, x1 + 0.12, z - 0.32, z + 0.12, 0.9, 0.95, DECK)
    m.box(x0 - 0.08, x1 + 0.08, z - 0.12, z - 0.02, h0 - 0.08, h1 + 0.08, STEEL)
    for x in (x0 + 0.3, x1 - 0.3):
        m.box(x - 0.06, x + 0.06, z - 0.2, z - 0.1, 0.95, h0, STEEL)
    scr.box(x0, x1, z - 0.02, z - 0.012, h0, h1, SCREEN)


def gear_rack(m: Mesh, x0: float, x1: float, z0: float) -> None:
    """Field-kit rack against a side wall: helmets, packs."""
    m.box(x0, x1, z0, z0 + 0.5, 0.0, 0.1, "M_Rubber_Black")
    m.box(x0, x1, z0, z0 + 0.05, 0.1, 1.9, STEEL)
    for h in (0.5, 1.3):
        m.box(x0, x1, z0, z0 + 0.48, h, h + 0.03, "M_Floor_Grating")
    n = int((x1 - x0) / 0.5)
    for i in range(n):
        x = x0 + 0.25 + i * 0.5
        m.box(x - 0.17, x + 0.17, z0 + 0.06, z0 + 0.4, 0.53, 0.98, "M_Crate_Paint")
        m.cyl(x, z0 + 0.25, 0.14, 1.33, 1.55, DARK, 16)


# ---------------------------------------------------------------- stores, med


def shelf_rack(
    m: Mesh, x0: float, x1: float, z0: float, z1: float, seed: int, levels: int = 4, h: float = 2.4
) -> None:
    """Pallet shelving with crates and drums (placeholder for the prop kit)."""
    rnd = _rng(seed)
    for x in (x0, x1 - 0.08):
        for z in (z0, z1 - 0.08):
            m.box(x, x + 0.08, z, z + 0.08, 0.0, h, STEEL)
    for k in range(levels):
        hh = 0.12 + k * (h - 0.2) / levels
        m.box(x0, x1, z0, z1, hh, hh + 0.05, "M_Floor_Grating")
        m.box(x0, x0 + 0.08, z0, z1, hh + 0.05, hh + 0.12, STEEL)
        z = z0 + 0.1
        while z < z1 - 0.5:
            w = 0.5 + 0.6 * rnd()
            if z + w > z1 - 0.1:
                break
            ch = min(0.2 + 0.3 * rnd(), (h - 0.2) / levels - 0.12)
            if rnd() < 0.8:
                m.box(x0 + 0.08, x1 - 0.08, z, z + w, hh + 0.05, hh + 0.05 + ch, "M_Crate_Paint")
            z += w + 0.08


def crate_stack(m: Mesh, cx: float, cz: float, seed: int) -> None:
    rnd = _rng(seed)
    h = 0.0
    for _ in range(1 + int(rnd() * 3)):
        w, d, ch = 1.2, 0.8, 0.6
        m.box(cx - w / 2, cx + w / 2, cz - d / 2, cz + d / 2, h, h + ch - 0.01, "M_Crate_Paint")
        m.box(
            cx - w / 2 - 0.01,
            cx + w / 2 + 0.01,
            cz - d / 2 - 0.01,
            cz + d / 2 + 0.01,
            h + ch * 0.45,
            h + ch * 0.55,
            STEEL,
        )
        h += ch


def med_bed(m: Mesh, soft: Mesh, scr: Mesh, lights: Mesh, cx: float, z_head: float) -> None:
    """Recovery bed, head to the north, a diagnostic screen at its head."""
    za, zb = z_head + 0.3, z_head + 2.4
    m.box(cx - 0.45, cx + 0.45, za + 0.2, zb - 0.2, 0.0, 0.08, "M_Rubber_Black")
    m.box(cx - 0.12, cx + 0.12, za + 0.6, zb - 0.6, 0.08, 0.55, STEEL)
    m.box(cx - 0.48, cx + 0.48, za, zb, 0.55, 0.62, LIGHT)
    soft.box(cx - 0.44, cx + 0.44, za + 0.03, zb - 0.03, 0.62, 0.72, "M_Ops_Fabric_Sheet")
    soft.box(cx - 0.3, cx + 0.3, za + 0.08, za + 0.42, 0.72, 0.8, "M_Ops_Fabric_Sheet")
    # Head column with a screen facing the camera, and an overhead lamp arm.
    m.box(cx - 0.5, cx + 0.5, z_head, z_head + 0.3, 0.0, 1.9, LIGHT)
    m.box(cx - 0.42, cx + 0.42, z_head + 0.3, z_head + 0.33, 1.05, 1.65, STEEL)
    scr.box(cx - 0.38, cx + 0.38, z_head + 0.33, z_head + 0.335, 1.09, 1.61, SCREEN)
    m.box(cx - 0.05, cx + 0.05, z_head + 0.05, z_head + 1.6, 1.9, 1.98, STEEL)
    m.box(cx - 0.3, cx + 0.3, z_head + 1.2, z_head + 1.7, 1.86, 1.9, STEEL)
    lights.box(cx - 0.26, cx + 0.26, z_head + 1.24, z_head + 1.66, 1.855, 1.86, "M_Ops_Light_Med")
    lights.box(cx + 0.3, cx + 0.36, z_head + 0.3, z_head + 0.31, 1.75, 1.8, "M_Indicator_Green")


def med_cabinet(m: Mesh, lights: Mesh, x0: float, x1: float, z0: float) -> None:
    m.box(x0, x1, z0, z0 + 0.5, 0.0, 1.9, LIGHT)
    n = int((x1 - x0) / 0.6)
    for i in range(n):
        a = x0 + i * (x1 - x0) / n
        b = a + (x1 - x0) / n
        m.box(a + 0.01, b - 0.01, z0 + 0.5, z0 + 0.52, 0.1, 0.9, MID)
        m.box(a + 0.01, b - 0.01, z0 + 0.5, z0 + 0.51, 0.95, 1.8, "M_Ops_Glass_Case")
    m.box(x0, x1, z0, z0 + 0.55, 0.88, 0.92, BRUSHED)
    lights.box(x0 + 0.05, x0 + 0.12, z0 + 0.52, z0 + 0.53, 1.82, 1.86, "M_Indicator_White")


# ---------------------------------------------------------------- misc


def _rng(seed: int):
    """Tiny deterministic LCG (no global random state)."""
    state = [seed & 0x7FFFFFFF or 1]

    def nxt() -> float:
        state[0] = (1103515245 * state[0] + 12345) & 0x7FFFFFFF
        return state[0] / 0x7FFFFFFF

    return nxt


def archive_rack(
    m: Mesh, lights: Mesh, x0: float, x1: float, z0: float, z1: float, h: float = 2.2
) -> None:
    """Records archive stack running away from the camera: dark cabinet, a
    column of white pips on its camera-facing end (the hall's receding lines)."""
    m.box(x0, x1, z0, z1, 0.0, 0.08, "M_Rubber_Black")
    m.box(x0 + 0.02, x1 - 0.02, z0 + 0.02, z1 - 0.02, 0.08, h, "M_Console_Body")
    m.box(x0, x1, z0, z1, h, h + 0.04, STEEL)
    m.box(x0 + 0.1, x1 - 0.1, z1 - 0.02, z1, 0.25, h - 0.15, RECESS)
    xc = (x0 + x1) / 2
    for col, dx in enumerate((-0.18, 0.0, 0.18)):
        hh = 0.4 + 0.06 * col
        while hh < h - 0.3:
            lights.box(
                xc + dx - 0.025, xc + dx + 0.025, z1, z1 + 0.008, hh, hh + 0.03, "M_Ops_Light_Pip"
            )
            hh += 0.12 + 0.06 * ((col + int(hh * 10)) % 3)
    # Top: drawer fronts read as a fine grid from above.
    k = 0.3
    zz = z0 + k
    while zz < z1 - 0.1:
        m.box(x0 + 0.05, x1 - 0.05, zz - 0.006, zz + 0.006, h + 0.04, h + 0.046, RECESS)
        zz += k


def arena(walk: Mesh, m: Mesh, lights: Mesh, cx: float, cz: float, w: float, d: float) -> None:
    """Simulator training platform: a raised octagonal deck (0.22 m) with a
    steel edge, a recessed toe light that washes the floor around it, and small
    red target markers along its far edge."""
    top = 0.22
    pts = octagon(cx, cz, w, d, 1.2)
    walk.poly([(x, z, top) for x, z in pts], "M_Floor_Grating")
    walk.poly([(x, z, 0.0) for x, z in pts[::-1]], STEEL)
    n = len(pts)
    for i in range(n):
        (ax, az), (bx, bz) = pts[i], pts[(i + 1) % n]
        walk.quad([(ax, az, 0.0), (bx, bz, 0.0), (bx, bz, top), (ax, az, top)], STEEL)
    # Physical edge: a brushed nosing round the top, inset from the outline.
    inner = octagon(cx, cz, w - 0.3, d - 0.3, 1.14)
    for i in range(n):
        (ax, az), (bx, bz) = pts[i], pts[(i + 1) % n]
        (cx0, cz0), (cx1, cz1) = inner[i], inner[(i + 1) % n]
        m.quad(
            [
                (ax, az, top + 0.012),
                (bx, bz, top + 0.012),
                (cx1, cz1, top + 0.012),
                (cx0, cz0, top + 0.012),
            ],
            BRUSHED,
        )
    # Toe light: a thin band low on every face, outside the outline.
    outer = octagon(cx, cz, w + 0.03, d + 0.03, 1.21)
    for i in range(n):
        (ax, az), (bx, bz) = outer[i], outer[(i + 1) % n]
        lights.quad(
            [(ax, az, 0.03), (bx, bz, 0.03), (bx, bz, 0.05), (ax, az, 0.05)], "M_Ops_Light_Dim"
        )
    for k in range(5):
        x = cx - w / 2 + 1.4 + k * (w - 2.8) / 4
        lights.box(
            x - 0.06,
            x + 0.06,
            cz - d / 2 + 0.3,
            cz - d / 2 + 0.36,
            top,
            top + 0.008,
            "M_Indicator_Red",
        )


SEGMENTS = {"0": "abcdef", "2": "abged"}
DIGITS = {
    "0": "abcdef",
    "1": "bc",
    "2": "abged",
    "3": "abgcd",
    "4": "fgbc",
    "5": "afgcd",
    "6": "afgedc",
    "7": "abc",
    "8": "abcdefg",
    "9": "abfgcd",
    "-": "g",
}


def _seg_boxes(text: str, char_h: float):
    """Stencil segments of ``text`` as (u0, u1, v0, v1) in a box whose origin
    is the top-left corner; u to the right, v down. Stencil gaps break every
    segment at its ends, as on a painted stencil."""
    w, t, gap = char_h * 0.5, char_h * 0.13, char_h * 0.06
    out, u = [], 0.0
    for ch in text:
        if ch == " ":
            u += w * 0.8
            continue
        hv = char_h / 2
        segs = {
            "a": (u + gap, u + w - gap, 0.0, t),
            "b": (u + w - t, u + w, gap, hv - gap / 2),
            "c": (u + w - t, u + w, hv + gap / 2, char_h - gap),
            "d": (u + gap, u + w - gap, char_h - t, char_h),
            "e": (u, u + t, hv + gap / 2, char_h - gap),
            "f": (u, u + t, gap, hv - gap / 2),
            "g": (u + gap, u + w - gap, hv - t / 2, hv + t / 2),
        }
        for s in DIGITS[ch]:
            out.append(segs[s])
        u += w + char_h * 0.28
    return out, u - char_h * 0.28


def floor_code(m: Mesh, text: str, cx: float, cz: float, char_h: float = 0.36) -> None:
    """A worn room code stencilled flush on the deck, reading from the camera."""
    boxes, width = _seg_boxes(text, char_h)
    x0, z0 = cx - width / 2, cz - char_h / 2
    for u0, u1, v0, v1 in boxes:
        m.box(x0 + u0, x0 + u1, z0 + v0, z0 + v1, 0.0005, 0.0025, "M_Deck_Marking_White")


def wall_plate(m: Mesh, text: str, x0: float, z: float, h_top: float, char_h: float = 0.09):
    """Small dark ident plate on a camera-facing wall with white stencil digits."""
    boxes, width = _seg_boxes(text, char_h)
    pad = char_h * 0.45
    x1 = x0 + width + 2 * pad
    m.box(x0, x1, z, z + 0.012, h_top - char_h - 2 * pad, h_top, DARK)
    m.box(x0 - 0.01, x1 + 0.01, z - 0.002, z + 0.008, h_top, h_top + 0.012, BRUSHED)
    for u0, u1, v0, v1 in boxes:
        m.box(
            x0 + pad + u0,
            x0 + pad + u1,
            z + 0.012,
            z + 0.015,
            h_top - pad - v1,
            h_top - pad - v0,
            "M_Deck_Marking_White",
        )


def deck_mark(m: Mesh, cx: float, cz: float) -> None:
    """The ship's own mark set into the lobby deck: a plain chamfered frame, a
    wedge pointing to the lifts and the deck number in segment strips."""
    t, h = 0.06, 0.003
    w, d, ch = 4.8, 2.4, 0.3
    pts = octagon(cx, cz, w, d, ch)
    for i in range(len(pts)):
        (ax, az), (bx, bz) = pts[i], pts[(i + 1) % len(pts)]
        wall_seg(m, (ax, az), (bx, bz), t, 0.0005, h, BRUSHED)
    # Wedge (the hull's plan shape), apex to the north.
    wx, wz = cx - 1.0, cz
    apex, left, right = (wx, wz - 0.85), (wx - 0.55, wz + 0.75), (wx + 0.55, wz + 0.75)
    for p0, p1 in ((apex, right), (right, left), (left, apex)):
        wall_seg(m, p0, p1, t, 0.0005, h, BRUSHED)
    wall_seg(m, (wx, wz - 0.35), (wx, wz + 0.6), 0.04, 0.0005, h, BRUSHED)
    # Deck number "02".
    for k, ch_ in enumerate("02"):
        x0, z0 = cx + 0.35 + k * 0.8, cz - 0.5
        sw, sh = 0.5, 1.0
        segs = {
            "a": ((x0, z0), (x0 + sw, z0)),
            "b": ((x0 + sw, z0), (x0 + sw, z0 + sh / 2)),
            "c": ((x0 + sw, z0 + sh / 2), (x0 + sw, z0 + sh)),
            "d": ((x0 + sw, z0 + sh), (x0, z0 + sh)),
            "e": ((x0, z0 + sh), (x0, z0 + sh / 2)),
            "f": ((x0, z0 + sh / 2), (x0, z0)),
            "g": ((x0, z0 + sh / 2), (x0 + sw, z0 + sh / 2)),
        }
        for s in SEGMENTS[ch_]:
            p0, p1 = segs[s]
            m.box(
                min(p0[0], p1[0]) - 0.035,
                max(p0[0], p1[0]) + 0.035,
                min(p0[1], p1[1]) - 0.035,
                max(p0[1], p1[1]) + 0.035,
                0.0005,
                h,
                "M_Deck_Marking_White",
            )
