"""Deck-agnostic wall cladding for the eye-level (realtime) view.

The bridge's ``decks/bridge/cladding.py`` (PR #910) set the wall-detail level
the eye-level view needs: panel seams, ribs with dash lamps, light columns,
louvre vents, conduit runs on a rail, a recessed cornice. That module is tied
to the bridge's layout; this one carries the same language with every height
a parameter, so any deck can dress its walls with it, plus the wall-mounted
fittings a working deck shows (terminals, sign plates, junction boxes,
vertical conduit drops).

Frame: every builder works in a wall's local frame ``(u, v, h)``: ``u`` runs
along the wall in plan metres, ``v`` from the wall face into the room, ``h`` is
the height above the deck. ``run_matrix`` makes that frame for a wall face
(Blender axes, plan ``z`` = Blender ``-y``); ``place_matrix`` makes it for a
freestanding prop (``v`` toward the prop's front).

Builds go through ``kit.MeshBuilder``; call them inside ``kit.ghost(...)`` to
make them ceiling ghosts (invisible to the plate camera, nav ``none``), which
is how the walls are dressed without touching the plate, the nav grid or the
occluders (docs/verse/realtime.md).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from lib import kit
from mathutils import Matrix

CHARCOAL = "M_Wall_Charcoal"
DARK = "M_Wall_PaintedDark"
MID = "M_Wall_PaintedMid"
LIGHT = "M_Wall_PaintedLight"
GUNMETAL = "M_Struct_Gunmetal"
STEEL = "M_Trim_BrushedSteel"
RECESS = "M_Recess_Dark"
RUBBER = "M_Rubber_Black"
PIPE = "M_Hull_Pipe"
PIPE_INS = "M_Hull_PipeInsulated"
BACKLIT = "M_Light_Backlit"
STRIP = "M_Light_WallStrip"
RED = "M_Light_RedTrim"
BODY = "M_Console_Body"
KEYS = "M_Console_Keys"
SCREEN = "M_Screen"
WHITE_PAINT = "M_Deck_Marking_White"

SEAM = 0.008  # reveal between panels
BACK = 0.012  # dark backing plate: what the seams show
PANEL_V = 0.045  # panel face, metres proud of the wall
RIB_W = 0.6
RIB_V = 0.15  # rib depth (inside the nav grid's 0.25 m body clearance)
DASH = (0.1, 0.3, 0.15)  # dash lamp width, height, gap
LIGHT_W, LIGHT_H, LIGHT_GAP = 0.26, 0.15, 0.05  # backlit rectangles


@dataclass(frozen=True)
class Bands:
    """Heights of a hall wall's bands (above deck level)."""

    plinth_top: float = 0.3
    lower: tuple[float, float] = (0.33, 2.73)
    rail: tuple[float, float] = (2.73, 2.88)
    conduit: tuple[float, float] = (2.88, 3.36)
    cornice: float = 0.6  # recessed band under the ceiling


@dataclass(frozen=True)
class RoomBands:
    """Heights of the light-grey room panelling."""

    base: float = 0.6
    channel: tuple[float, float] = (2.78, 3.02)


DEFAULT_BANDS = Bands()
DEFAULT_ROOM_BANDS = RoomBands()


@dataclass
class Opening:
    u0: float
    u1: float
    head: float  # top of the opening


def run_matrix(axis: str, fixed: float, room_sign: int) -> Matrix:
    """Local (u, v, h) -> Blender for a wall face.

    The face lies at plan ``x = fixed`` (axis "z", ``u`` = plan z) or plan
    ``z = fixed`` (axis "x", ``u`` = plan x); ``room_sign`` is the room's side
    along the other plan axis.
    """
    if axis == "z":
        return Matrix(((0, room_sign, 0, fixed), (-1, 0, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1)))
    return Matrix(((1, 0, 0, 0), (0, -room_sign, 0, -fixed), (0, 0, 1, 0), (0, 0, 0, 1)))


def place_matrix(x: float, z: float, yaw_deg: float = 0.0) -> Matrix:
    """Local (u, v, h) -> Blender for a freestanding prop at plan (x, z).

    ``v`` points to the prop's front: yaw 0 faces plan +z (the plate camera),
    180 faces -z, 90 faces +x (same convention as ``kit.place``)."""
    flip = Matrix(((1, 0, 0, 0), (0, -1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1)))
    return Matrix.Translation((x, -z, 0.0)) @ Matrix.Rotation(math.radians(yaw_deg), 4, "Z") @ flip


def seed01(*parts) -> float:
    return (kit.seed_for("clad", *parts) % 10000) / 10000.0


@dataclass
class Builders:
    """One builder per finish, shared by every wall (or prop) of a group."""

    panels: kit.MeshBuilder = field(default_factory=kit.MeshBuilder)
    struct: kit.MeshBuilder = field(default_factory=kit.MeshBuilder)
    flat: kit.MeshBuilder = field(default_factory=kit.MeshBuilder)
    pipes: kit.MeshBuilder = field(default_factory=kit.MeshBuilder)
    lamps: kit.MeshBuilder = field(default_factory=kit.MeshBuilder)

    def at(self, matrix: Matrix) -> Builders:
        for mb in self._all():
            mb.matrix = matrix
        return self

    def _all(self):
        return (self.panels, self.struct, self.flat, self.pipes, self.lamps)

    def finish(self, prefix: str, **props) -> list:
        """Build the meshes; ``props`` are cook properties for the solid parts
        (lamps are always nav ``none`` and cast no shadow)."""
        out = [
            self.panels.build(f"{prefix}_panels", bevel_width=0.003, segments=1, **props),
            self.struct.build(f"{prefix}_struct", bevel_width=0.006, segments=1, **props),
            self.flat.build(f"{prefix}_flat", bevel_width=0.0, **props),
            self.pipes.build(f"{prefix}_conduits", bevel_width=0.0, **props),
        ]
        lamp_props = {**props, "nav": "none"}
        lamps = self.lamps.build(f"{prefix}_lamps", bevel_width=0.0, **lamp_props)
        if lamps is not None:
            lamps.visible_shadow = False
        out.append(lamps)
        return [o for o in out if o is not None]


def box(mb: kit.MeshBuilder, u0, u1, v0, v1, h0, h1, material: str) -> None:
    if u1 - u0 > 1e-4 and h1 - h0 > 1e-4 and v1 - v0 > 1e-5:
        mb.box((u0, v0, h0), (u1, v1, h1), material)


def modules(a: float, b: float, module: float) -> list[tuple[float, float]]:
    n = max(1, round((b - a) / module))
    step = (b - a) / n
    return [(a + i * step, a + (i + 1) * step) for i in range(n)]


def subtract(a: float, b: float, holes) -> list[tuple[float, float]]:
    """Parts of [a, b] outside the given (u0, u1) holes."""
    spans = [(a, b)]
    for h0, h1 in sorted(holes):
        out = []
        for s0, s1 in spans:
            if h1 <= s0 or h0 >= s1:
                out.append((s0, s1))
                continue
            if h0 > s0:
                out.append((s0, h0))
            if h1 < s1:
                out.append((h1, s1))
        spans = out
    return [(s0, s1) for s0, s1 in spans if s1 - s0 > 0.05]


# ---------------------------------------------------------------- elements


def louvre(B: Builders, cu: float, h0: float, w: float = 0.6, h: float = 0.3) -> None:
    """Louvre vent: gunmetal frame, 8 dark slats."""
    box(B.struct, cu - w / 2, cu + w / 2, BACK, PANEL_V + 0.012, h0, h0 + h, GUNMETAL)
    box(B.flat, cu - w / 2 + 0.04, cu + w / 2 - 0.04, PANEL_V + 0.012, PANEL_V + 0.014,
        h0 + 0.03, h0 + h - 0.03, RECESS)  # fmt: skip
    pitch = (h - 0.06) / 8
    for k in range(8):
        z = h0 + 0.03 + k * pitch + pitch * 0.3
        box(B.flat, cu - w / 2 + 0.05, cu + w / 2 - 0.05, PANEL_V + 0.014, PANEL_V + 0.03,
            z, z + pitch * 0.45, GUNMETAL)  # fmt: skip


def panel(B: Builders, u0, u1, h0, h1, material: str, *, inset: bool, v: float = PANEL_V):
    """A panel proud of the backing; ``inset`` adds a recessed field with a
    50 mm border."""
    a, b = u0 + SEAM / 2, u1 - SEAM / 2
    z0, z1 = h0 + SEAM / 2, h1 - SEAM / 2
    if not inset or b - a < 0.25 or z1 - z0 < 0.25:
        box(B.panels, a, b, BACK, v, z0, z1, material)
        return
    bd = 0.05
    box(B.panels, a, b, BACK, v, z0, z0 + bd, material)
    box(B.panels, a, b, BACK, v, z1 - bd, z1, material)
    box(B.panels, a, a + bd, BACK, v, z0 + bd, z1 - bd, material)
    box(B.panels, b - bd, b, BACK, v, z0 + bd, z1 - bd, material)
    box(B.panels, a + bd, b - bd, BACK, v - 0.02, z0 + bd, z1 - bd, material)


def light_column(B: Builders, cu: float, h0: float, h1: float, seed) -> None:
    """The hero wall's light column in one 0.6 m module: charcoal cheeks,
    gunmetal ribs and a recessed bay of stacked backlit rectangles, every
    fifth slot a dark plate."""
    bay = 0.36
    for s in (-1, 1):
        cheek0, cheek1 = sorted((cu + s * (bay / 2 + 0.06), cu + s * (0.3 - SEAM / 2)))
        box(B.panels, cheek0, cheek1, BACK, PANEL_V, h0 + SEAM / 2, h1 - SEAM / 2, CHARCOAL)
        r0, r1 = sorted((cu + s * bay / 2, cu + s * (bay / 2 + 0.06)))
        box(B.struct, r0, r1, BACK, PANEL_V + 0.02, h0, h1, GUNMETAL)
    box(B.flat, cu - bay / 2, cu + bay / 2, BACK, BACK + 0.004, h0, h1, RECESS)
    z = h0 + 0.1
    slot = kit.seed_for(seed) % 5
    while z + LIGHT_H < h1 - 0.06:
        if slot % 5 != 4:
            box(B.lamps, cu - LIGHT_W / 2, cu + LIGHT_W / 2, BACK + 0.012, BACK + 0.016,
                z, z + LIGHT_H, BACKLIT)  # fmt: skip
        else:
            box(B.struct, cu - LIGHT_W / 2, cu + LIGHT_W / 2, BACK + 0.004, BACK + 0.03,
                z, z + LIGHT_H, GUNMETAL)  # fmt: skip
        z += LIGHT_H + LIGHT_GAP
        slot += 1


def rib(B: Builders, r: float, bottom: float, top: float, *, foot: bool, red: bool, dashes) -> None:
    """Gunmetal rib: stepped core and front plates around a lamp slot, a
    splayed foot and a chamfered capital."""
    w = RIB_W / 2
    box(B.struct, r - w, r + w, BACK, 0.11, bottom, top, GUNMETAL)
    for s in (-1, 1):
        a, b = sorted((r + s * 0.06, r + s * 0.19))
        box(B.struct, a, b, 0.11, RIB_V, bottom + (0.4 if foot else 0.0), top - 0.5, GUNMETAL)
    box(B.flat, r - 0.06, r + 0.06, 0.11, 0.128, bottom, top - 0.5, RECESS)
    if foot:
        B.struct.prism_x(
            [(BACK, bottom), (0.2, bottom), (0.2, bottom + 0.22), (0.11, bottom + 0.4),
             (BACK, bottom + 0.4)],
            r - w - 0.06,
            r + w + 0.06,
            GUNMETAL,
        )  # fmt: skip
    B.struct.prism_x(
        [(BACK, top - 0.5), (0.11, top - 0.5), (0.2, top - 0.36), (0.2, top), (BACK, top)],
        r - w - 0.04,
        r + w + 0.04,
        GUNMETAL,
    )
    dw, dh, _ = DASH
    for z in dashes:
        box(B.lamps, r - dw / 2, r + dw / 2, 0.128, 0.132, z, z + dh, BACKLIT)
    if red:
        box(B.lamps, r - 0.025, r + 0.025, 0.128, 0.132, max(bottom + 2.0, top - 2.6), top - 0.6,
            RED)  # fmt: skip


def conduits(B: Builders, u0: float, u1: float, h0: float, h1: float, ribs, seed) -> None:
    """Conduit bundle on the rail: three pipes with clamps every 1.2 m and a
    junction box every other bay."""
    box(B.panels, u0, u1, BACK, BACK + 0.008, h0, h1, DARK)
    span = h1 - h0
    for f, r, mat in ((0.2, 0.045, PIPE_INS), (0.46, 0.03, PIPE), (0.7, 0.04, PIPE)):
        v = BACK + r + 0.035
        B.pipes.tube((u0 + 0.02, v, h0 + f * span), (u1 - 0.02, v, h0 + f * span), r, mat,
                     segments=10)  # fmt: skip
    u = u0 + 0.6
    k = 0
    while u < u1 - 0.3:
        if all(abs(u - rr) > RIB_W / 2 + 0.1 for rr in ribs):
            box(B.struct, u - 0.03, u + 0.03, BACK, 0.135, h0 + 0.03, h1 - 0.05, GUNMETAL)
            if k % 4 == 2 and seed01(seed, "jbox", k) < 0.6:
                box(B.panels, u + 0.15, u + 0.45, BACK, 0.16, h0 + 0.05, h1 - 0.1, MID)
                lamp = "M_Indicator_Green" if seed01(seed, "jl", k) < 0.5 else "M_Indicator_White"
                box(B.lamps, u + 0.38, u + 0.42, 0.16, 0.164, h1 - 0.18, h1 - 0.14, lamp)
        u += 1.2
        k += 1


# ---------------------------------------------------------------- fittings


def wall_terminal(B: Builders, cu: float, h0: float = 1.05, *, seed=0) -> None:
    """Wall-mounted duty terminal: gunmetal housing, a recessed dark-blue
    screen with thin readouts, a key strip and two status pips."""
    w, h = 0.62, 0.86
    box(B.struct, cu - w / 2, cu + w / 2, BACK, 0.11, h0, h0 + h, GUNMETAL)
    box(B.panels, cu - w / 2 + 0.03, cu + w / 2 - 0.03, 0.11, 0.13, h0 + 0.02, h0 + h - 0.02, BODY)
    box(B.flat, cu - 0.24, cu + 0.24, 0.13, 0.132, h0 + 0.33, h0 + 0.74, RECESS)
    box(B.lamps, cu - 0.22, cu + 0.22, 0.132, 0.134, h0 + 0.35, h0 + 0.72, SCREEN)
    # Sloped key shelf.
    B.struct.prism_x(
        [(0.13, h0 + 0.1), (0.24, h0 + 0.16), (0.24, h0 + 0.2), (0.13, h0 + 0.3)],
        cu - 0.26,
        cu + 0.26,
        BODY,
    )
    for i in range(6):
        k = cu - 0.2 + i * 0.08
        box(B.flat, k - 0.025, k + 0.025, 0.2, 0.245, h0 + 0.2, h0 + 0.215, KEYS)
    pips = ("M_Indicator_Green", "M_Indicator_White", "M_Indicator_Amber", "M_Indicator_Red")
    first = pips[int(seed01(seed, "pip") * 2)]
    second = pips[1 + int(seed01(seed, "pip2") * 3)]
    for du, mat in ((-0.26, first), (-0.2, second)):
        box(B.lamps, cu + du, cu + du + 0.035, 0.13, 0.136, h0 + 0.77, h0 + 0.8, mat)


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


def _segments(text: str, ch: float):
    """Stencil segments of digit codes as (u0, u1, d0, d1); d down from the top."""
    w, t, gap = ch * 0.5, ch * 0.13, ch * 0.06
    out, u = [], 0.0
    for c in text:
        if c == " ":
            u += w * 0.8
            continue
        hv = ch / 2
        segs = {
            "a": (u + gap, u + w - gap, 0.0, t),
            "b": (u + w - t, u + w, gap, hv - gap / 2),
            "c": (u + w - t, u + w, hv + gap / 2, ch - gap),
            "d": (u + gap, u + w - gap, ch - t, ch),
            "e": (u, u + t, hv + gap / 2, ch - gap),
            "f": (u, u + t, gap, hv - gap / 2),
            "g": (u + gap, u + w - gap, hv - t / 2, hv + t / 2),
        }
        out += [segs[s] for s in DIGITS[c]]
        u += w + ch * 0.28
    return out, u - ch * 0.28


def sign_plate(B: Builders, cu: float, h_top: float, code: str, *, ch: float = 0.12,
               stripe: str | None = "M_Paint_TrimRed") -> None:  # fmt: skip
    """Section sign: a dark plate with a brushed top edge, a white stencil
    code (digits and dashes only, no words) and an optional colour stripe."""
    segs, width = _segments(code, ch)
    pad = ch * 0.5
    w = width + 2 * pad + (0.1 if stripe else 0.0)
    u0 = cu - w / 2
    h0 = h_top - ch - 2 * pad
    box(B.panels, u0, u0 + w, BACK, 0.03, h0, h_top, DARK)
    box(B.struct, u0 - 0.01, u0 + w + 0.01, BACK, 0.036, h_top, h_top + 0.014, STEEL)
    x = u0 + pad
    if stripe:
        box(B.panels, u0 + 0.03, u0 + 0.07, 0.03, 0.033, h0 + 0.03, h_top - 0.03, stripe)
        x += 0.1
    for a, b, d0, d1 in segs:
        box(B.flat, x + a, x + b, 0.03, 0.034, h_top - pad - d1, h_top - pad - d0, WHITE_PAINT)


def status_panel(B: Builders, cu: float, h0: float, *, seed=0) -> None:
    """Backlit status board: a gunmetal frame around a column of white bars
    with one coloured pip (amber or red only on some)."""
    w, h = 0.36, 0.7
    box(B.struct, cu - w / 2, cu + w / 2, BACK, 0.07, h0, h0 + h, GUNMETAL)
    box(B.flat, cu - w / 2 + 0.04, cu + w / 2 - 0.04, 0.07, 0.072, h0 + 0.04, h0 + h - 0.04, RECESS)
    for i in range(5):
        z = h0 + 0.1 + i * 0.11
        ln = 0.12 + 0.12 * seed01(seed, "bar", i)
        box(B.lamps, cu - 0.12, cu - 0.12 + ln, 0.072, 0.075, z, z + 0.04, BACKLIT)
    r = seed01(seed, "pip")
    mat = "M_Indicator_Red" if r < 0.2 else "M_Indicator_Amber" if r < 0.45 else "M_Indicator_Green"
    box(B.lamps, cu + 0.08, cu + 0.12, 0.072, 0.078, h0 + h - 0.12, h0 + h - 0.08, mat)


def junction_box(B: Builders, cu: float, h0: float, w: float = 0.42, h: float = 0.5, *,
                 seed=0) -> None:  # fmt: skip
    """Electrical junction box with a hinged lid, bolts and a cable gland
    feeding a conduit up to the rail."""
    box(B.struct, cu - w / 2, cu + w / 2, BACK, 0.17, h0, h0 + h, MID)
    box(B.panels, cu - w / 2 + 0.025, cu + w / 2 - 0.025, 0.17, 0.18, h0 + 0.025, h0 + h - 0.025,
        DARK)  # fmt: skip
    for su in (-1, 1):
        for sh in (0, 1):
            box(B.flat, cu + su * (w / 2 - 0.045) - 0.012, cu + su * (w / 2 - 0.045) + 0.012,
                0.18, 0.186, h0 + 0.04 + sh * (h - 0.08) - 0.012,
                h0 + 0.04 + sh * (h - 0.08) + 0.012, STEEL)  # fmt: skip
    mat = "M_Indicator_Green" if seed01(seed, "jb") < 0.7 else "M_Indicator_Amber"
    box(B.lamps, cu - 0.02, cu + 0.02, 0.18, 0.186, h0 + h - 0.08, h0 + h - 0.05, mat)


def conduit_drop(B: Builders, cu: float, h0: float, h1: float, n: int = 2) -> None:
    """Vertical conduit pipes on stand-off clamps (a feed from the rail down
    to a fitting)."""
    for i in range(n):
        u = cu + (i - (n - 1) / 2) * 0.09
        B.pipes.tube((u, 0.06, h0), (u, 0.06, h1), 0.025, PIPE, segments=8)
    z = h0 + 0.3
    while z < h1 - 0.1:
        box(B.struct, cu - 0.05 * n - 0.02, cu + 0.05 * n + 0.02, BACK, 0.1, z, z + 0.04, GUNMETAL)
        z += 0.6


# ---------------------------------------------------------------- walls


def hall_wall(
    B: Builders,
    seed,
    t0: float,
    t1: float,
    *,
    top: float,
    ribs: list[float],
    floor: float = 0.0,
    bands: Bands = DEFAULT_BANDS,
    lit_bays: set[int] | None = None,
    lit_upper: set[int] | None = None,
    red_ribs: set[int] | None = None,
    lower_material: str = CHARCOAL,
    openings: list[Opening] = (),
) -> list[tuple[float, float]]:
    """Dress a hall wall face between ``t0`` and ``t1`` (plan metres along it)
    in the hero language: plinth with louvres, a lower field of 0.6 m charcoal
    panels with light columns in ``lit_bays``, a rail with a conduit bundle, an
    upper field, a recessed cornice and gunmetal ribs at ``ribs``. Returns the
    bays (u spans between ribs) for further fittings."""
    lit_bays, lit_upper, red_ribs = lit_bays or set(), lit_upper or set(), red_ribs or set()
    holes = [(o.u0, o.u1) for o in openings]
    lower = (floor + bands.lower[0], floor + bands.lower[1])
    rail = (floor + bands.rail[0], floor + bands.rail[1])
    cond = (floor + bands.conduit[0], floor + bands.conduit[1])
    plinth_top = floor + bands.plinth_top
    for a, b in subtract(t0, t1, holes):
        box(B.flat, a, b, 0.0, BACK, floor, top, RECESS)
    for o in openings:
        box(B.flat, o.u0, o.u1, 0.0, BACK, o.head, top, RECESS)
    for a, b in subtract(t0, t1, holes):
        for i, (m0, m1) in enumerate(modules(a, b, 1.2)):
            box(B.panels, m0 + SEAM / 2, m1 - SEAM / 2, BACK, BACK + 0.022, floor, plinth_top, DARK)
            if i % 2 == 1 and m1 - m0 > 0.8:
                louvre(B, (m0 + m1) / 2, floor + 0.02, w=0.6, h=0.24)
        box(B.struct, a, b, BACK, 0.05, plinth_top, lower[0], STEEL)
    edges = [t0, *[r for r in ribs if t0 < r < t1], t1]
    bays = []
    for a, b in zip(edges[:-1], edges[1:], strict=True):
        bays.append((a + (RIB_W / 2 if a in ribs else 0.0), b - (RIB_W / 2 if b in ribs else 0.0)))
    upper = (cond[1], top - bands.cornice)
    for bi, (a, b) in enumerate(bays):
        cu = round(((a + b) / 2) / 0.3) * 0.3
        lit_low = bi in lit_bays and b - a > 1.8 and not any(
            o.u0 - 0.4 < cu < o.u1 + 0.4 for o in openings
        )
        lit_up = bi in lit_upper and b - a > 1.8 and upper[1] - upper[0] > 0.8
        low_holes = holes + ([(cu - 0.3, cu + 0.3)] if lit_low else [])
        for sa, sb in subtract(a, b, low_holes):
            for i, (m0, m1) in enumerate(modules(sa, sb, 0.6)):
                inset = seed01(seed, bi, sa, i) < 0.25
                mat = DARK if seed01(seed, "m", bi, sa, i) < 0.12 else lower_material
                panel(B, m0, m1, lower[0], lower[1], mat, inset=inset)
        for o in openings:
            for sa, sb in subtract(max(a, o.u0), min(b, o.u1), []):
                if o.head < lower[1] - 0.1:
                    panel(B, sa, sb, o.head + 0.03, lower[1], lower_material, inset=False)
        if lit_low:
            light_column(B, cu, lower[0], lower[1], (seed, "low", bi))
        if upper[1] - upper[0] < 0.1:
            continue
        up_holes = [(cu - 0.3, cu + 0.3)] if lit_up else []
        rows = max(1, round((upper[1] - upper[0]) / 1.1))
        rh = (upper[1] - upper[0]) / rows
        for sa, sb in subtract(a, b, up_holes):
            for i, (m0, m1) in enumerate(modules(sa, sb, 1.2)):
                for j in range(rows):
                    h0, h1 = upper[0] + j * rh, upper[0] + (j + 1) * rh
                    r = seed01(seed, "u", bi, sa, i, j)
                    panel(B, m0, m1, h0, h1, MID if r < 0.16 else DARK, inset=0.16 <= r < 0.4)
                    if j == 0 and r > 0.88 and m1 - m0 > 0.9 and h1 - h0 > 0.5:
                        louvre(B, (m0 + m1) / 2, h0 + 0.12)
        if lit_up:
            light_column(B, cu, upper[0] + 0.08, upper[1] - 0.08, (seed, "up", bi))
    box(B.struct, t0, t1, BACK, 0.09, rail[0], rail[1] - 0.015, GUNMETAL)
    box(B.struct, t0, t1, BACK, 0.095, rail[1] - 0.015, rail[1], STEEL)
    conduits(B, t0, t1, cond[0], cond[1], ribs, seed)
    c0 = top - bands.cornice
    box(B.struct, t0, t1, BACK, 0.07, c0, c0 + 0.06, GUNMETAL)
    for m0, m1 in modules(t0, t1, 2.4):
        box(B.panels, m0 + SEAM / 2, m1 - SEAM / 2, BACK, BACK + 0.01, c0 + 0.06, top - 0.06, DARK)
    box(B.struct, t0, t1, BACK, 0.05, top - 0.06, top, GUNMETAL)
    dw, dh, gap = DASH
    for ri, r in enumerate(ribs):
        if not t0 < r < t1:
            continue
        blocked = any(o.u0 - RIB_W < r < o.u1 + RIB_W for o in openings)
        bottom = cond[0] if blocked else floor
        dashes = [] if blocked else [floor + 0.6 + k * (dh + gap) for k in range(7)]
        rib(B, r, bottom, top, foot=not blocked, red=ri in red_ribs, dashes=dashes)
    return bays


def room_wall(
    B: Builders,
    seed,
    t0: float,
    t1: float,
    *,
    top: float,
    bands: RoomBands = DEFAULT_ROOM_BANDS,
    pilasters: list[float] = (),
    openings: list[Opening] = (),
    base_from: float = 0.0,
) -> None:
    """Light-grey secondary panelling: base band with vents, panels with
    hatches, a light channel with its fixture hidden under the lip, upper
    panels, gunmetal pilasters."""
    base = bands.base
    c0, c1 = bands.channel
    holes = [(o.u0, o.u1) for o in openings]
    for a, b in subtract(t0, t1, holes):
        box(B.flat, a, b, 0.0, BACK, base_from, top, RECESS)
        for i, (m0, m1) in enumerate(modules(a, b, 1.2)):
            box(B.panels, m0 + SEAM / 2, m1 - SEAM / 2, BACK, BACK + 0.022,
                base_from, base - 0.025, DARK)  # fmt: skip
            if i % 2 == 1 and m1 - m0 > 0.8:
                louvre(B, (m0 + m1) / 2, 0.14, w=0.6, h=0.3)
            hatch = i % 4 == 2 and seed01(seed, "hatch", a, i) < 0.7
            panel(B, m0, m1, base, c0, LIGHT, inset=hatch)
            if hatch:
                cu = (m0 + m1) / 2
                box(B.struct, cu - 0.09, cu + 0.09, PANEL_V, PANEL_V + 0.01, 2.1, 2.15, STEEL)
            panel(B, m0, m1, c1, top - 0.04, MID, inset=False)
        box(B.struct, a, b, BACK, 0.05, base - 0.025, base, STEEL)
    for o in openings:
        if o.head < c0:
            for m0, m1 in modules(o.u0, o.u1, 1.2):
                panel(B, m0, m1, o.head + 0.03, c0, LIGHT, inset=False)
            box(B.flat, o.u0, o.u1, 0.0, BACK, o.head, top, RECESS)
            for m0, m1 in modules(o.u0, o.u1, 1.2):
                panel(B, m0, m1, c1, top - 0.04, MID, inset=False)
    box(B.struct, t0, t1, BACK, 0.065, c0, c0 + 0.05, STEEL)
    box(B.panels, t0, t1, BACK, 0.1, c1 - 0.07, c1, MID)
    box(B.flat, t0, t1, BACK, BACK + 0.006, c0 + 0.05, c1 - 0.07, LIGHT)
    for a, b in modules(t0, t1, 2.4):
        cu, half = (a + b) / 2, (b - a) / 4
        box(B.lamps, cu - half, cu + half, 0.03, 0.09, c1 - 0.074, c1 - 0.07, STRIP)
    box(B.struct, t0, t1, BACK, 0.04, top - 0.04, top, GUNMETAL)
    for p in pilasters:
        if t0 < p < t1:
            box(B.struct, p - 0.15, p + 0.15, BACK, 0.1, base_from, top, GUNMETAL)
            box(B.struct, p - 0.08, p + 0.08, 0.1, 0.12, base_from + 0.3, top - 0.3, GUNMETAL)
            box(B.flat, p - 0.02, p + 0.02, 0.12, 0.122, 0.9, c0 - 0.2, RECESS)


def rib_stations(t0: float, t1: float, step: float = 4.8, origin: float = 0.0) -> list[float]:
    """Rib positions on a ``step`` grid from ``origin``, clear of the ends."""
    out = []
    k = math.ceil((t0 - origin) / step)
    while origin + k * step < t1:
        r = origin + k * step
        if t0 + 0.5 < r < t1 - 0.5:
            out.append(round(r, 3))
        k += 1
    return out
