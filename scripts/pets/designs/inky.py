"""Inky: the living inkwell.

A squat glass ink bottle with a cork-coloured rim, a brass neck ring and deep
blue ink sloshing behind its face. A cream quill feather sticks out of the
neck and does the talking with its body: it perks up to listen, taps while
thinking, waves on success, droops on an error and flops over the face to
sleep. When there is writing to do the quill hops out and scribbles on a
sheet of paper beside the bottle. Literary, neat and a little dramatic.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence

#: The builder module (``scripts/pets/build_pets.py``), set by ``design``.
B = None


def _hex(value: str) -> tuple[int, int, int, int]:
    value = value.lstrip("#")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), 255)


# -- Palette -------------------------------------------------------------------

GLASS = _hex("#c6e2ec")
GLASS_LIGHT = _hex("#eef9fc")
GLASS_DARK = _hex("#8fb8c8")
#: Asleep the glass dims a little, like a room with the lamp turned down.
GLASS_COOL = (_hex("#a9c8d6"), _hex("#d3e8f0"), _hex("#7699ab"))
GLASS_SHINE = _hex("#ffffff")
INK = _hex("#2c3fa0")
INK_DEEP = _hex("#1b276b")
INK_TOP = _hex("#5d7ff0")
INK_SHINE = _hex("#93a9f6")
#: A 1 px ink stroke in the air: a mid blue that holds on dark AND light.
INK_STROKE = _hex("#4a6ff0")
INK_STROKE_FADE = _hex("#8ea4f0")
CORK = _hex("#b98552")
CORK_LIGHT = _hex("#deaa76")
CORK_DARK = _hex("#86562f")
GOLD = _hex("#ffcf45")
GOLD_LIGHT = _hex("#fff1a8")
GOLD_DARK = _hex("#c9952a")
QUILL = _hex("#f7eedb")
QUILL_LIGHT = _hex("#fffaf0")
QUILL_SHADE = _hex("#e2cfa6")
QUILL_SHAFT = _hex("#c4a26a")
#: The bare quill below the vane: translucent, almost white.
QUILL_BARREL = _hex("#fdf8ec")
NIB = _hex("#3a3f52")
NIB_LIGHT = _hex("#8d95a6")
FACE = _hex("#1b1f3a")
PAPER = _hex("#fbf6e9")
PAPER_DARK = _hex("#d8cdb4")
PAPER_RULE = _hex("#c9d6ee")

# -- Geometry (cell coordinates, before the pose offset) -----------------------

#: Where the quill leaves the bottle's mouth.
QUILL_BASE = (24, 15)
#: The resting ink level (its surface row).
INK_LEVEL = 35
EYE_L = (17, 26)
EYE_R = (28, 26)
MOUTH = (22, 31)
#: The sheet of paper Inky writes on while working (top-left).
PAPER_AT = (34, 30)


def _body() -> set:
    """The glass bottle: rounded shoulders, a flatter bottom."""
    top = B.rounded_rect(11, 23, 36, 34, 5)
    bottom = B.rounded_rect(11, 28, 36, 41, 2)
    return top | bottom


# -- Quill ---------------------------------------------------------------------


def _quill_path(bx: float, by: float, angle: float, curl: float, length: float) -> list:
    """Centre line of the quill as (x, y, angle_radians, t) samples, base first.

    ``angle`` is degrees clockwise from straight up; ``curl`` is how many
    more degrees the tip bends.
    """
    steps = max(2, int(length * 2))
    x, y = bx + 0.5, by + 0.5
    out = []
    for k in range(steps + 1):
        t = k / steps
        a = math.radians(angle + curl * t)
        out.append((x, y, a, t))
        x += math.sin(a) * 0.5
        y -= math.cos(a) * 0.5
    return out


def _vane_width(t: float, side: float, ruffle: bool, k: int) -> float:
    if t < 0.2:
        return 0.0
    u = min(1.0, (t - 0.2) / 0.84)
    w = side * math.sin(math.pi * u) ** 0.6
    if ruffle and k % 3 == 0:
        w += 1.2
    return w


def quill_tip(bx: float, by: float, angle: float, curl: float, length: float) -> tuple:
    x, y, _a, _t = _quill_path(bx, by, angle, curl, length)[-1]
    return math.floor(x), math.floor(y)


def quill_length(angle: float, curl: float, lift: int) -> int:
    """13 px, or shorter where standing tall would take the tip out of the cell."""
    bx, by = QUILL_BASE
    length = 15
    while quill_tip(bx, by, angle, curl, length)[1] + lift < 3:
        length -= 1
    return length


def draw_quill(
    f,
    bx: int,
    by: int,
    angle: float,
    curl: float,
    length: float = 14,
    *,
    nib: bool = False,
    ruffle: bool = False,
    shine: bool = False,
) -> None:
    """The cream quill feather from its base ``(bx, by)``.

    The left vane is lit, the right one shaded, a tan shaft runs down the
    middle; with ``nib`` the steel writing nib shows below the base.
    """
    path = _quill_path(bx, by, angle, curl, length)
    right_edge, left_edge, spine = [], [], []
    for k, (x, y, a, t) in enumerate(path):
        nx, ny = math.cos(a), math.sin(a)
        wr = _vane_width(t, 3.3, ruffle, k)
        wl = _vane_width(t, 2.5, ruffle, k + 1)
        if t >= 0.18:
            spine.append((x, y))
            right_edge.append((x + nx * wr, y + ny * wr))
            left_edge.append((x - nx * wl, y - ny * wl))
    right = B.polygon(spine + right_edge[::-1])
    left = B.polygon(spine + left_edge[::-1])
    shaft = B.polyline([(math.floor(x), math.floor(y)) for x, y, _a, t in path if t <= 0.9])
    mask = right | left | shaft
    nib_px: set = set()
    if nib:
        a = path[0][2]
        nib_px = B.line(
            bx, by, round(bx - math.sin(a) * 3), round(by + math.cos(a) * 3)
        ) - shaft
        mask |= nib_px
    fill = {}
    for p in mask:
        fill[p] = QUILL_SHADE if p in right and p not in left else QUILL
    for p in left - right:
        fill[p] = QUILL_LIGHT if shine else QUILL
    barrel = {(math.floor(x), math.floor(y)) for x, y, _a, t in path if t < 0.2}
    for p in shaft:
        fill[p] = QUILL_BARREL if p in barrel else QUILL_SHAFT
    for p in nib_px:
        fill[p] = NIB
    f.part(mask, fill)
    if nib_px:
        tip = max(nib_px, key=lambda p: p[1])
        f.paint({tip}, INK_TOP)


# -- Per-pose tables ---------------------------------------------------------------

#: (angle, curl) of the quill per state frame; length stays 14.
_QUILL: dict[str, tuple[tuple[float, float], ...]] = {
    "idle": ((20, 22), (20, 22), (18, 22), (15, 22), (15, 22), (18, 22), (20, 22), (20, 22)),
    "listening": ((0, 4), (-3, 6), (0, 4), (3, 4), (0, 4), (-2, 6)),
    "thinking": ((20, 22), (45, 30), (75, 40), (45, 30), (20, 22), (45, 30), (75, 40), (45, 30)),
    "talking": ((22, 24), (16, 20), (10, 16), (4, 12)),
    "success": ((20, 22), (30, 28), (38, 32), (30, 28), (20, 22), (12, 16), (20, 22), (20, 22)),
    "error": ((40, 30), (70, 45), (95, 50), (110, 50), (115, 50), (115, 50)),
    "sleeping": ((-118, -45), (-118, -45), (-122, -45), (-122, -45), (-118, -45), (-118, -45)),
    "searching": (
        (-12, -10), (-8, -8), (0, 6), (10, 12), (16, 16), (10, 12), (0, 6), (-8, -8),
    ),
    "held": ((35, 30), (20, 22), (5, 10), (20, 22), (35, 30), (20, 22)),
}

#: Held: the ink surface's tilt per frame (rows of drop per column), lagging the swing.
_HELD_TILT = (0.25, 0.0, -0.25, 0.0, 0.25, 0.0)
_WORK_DX = -4


def inky_pose(state: str, i: int):
    if state == "working":
        return B.Pose(state, i, dx=_WORK_DX, dy=B.WORK_BOB[i], eyes="look_right", mouth="closed")
    if state == "held":
        mouth = ("half", "open")[i % 2]
        return B.Pose(
            state, i, dx=B.HELD_SWAY[i], dy=-2, eyes="wide", mouth=mouth, stretch=1
        )
    return B.base_pose(state, i)


def _quill_for(pose) -> tuple[float, float] | None:
    """The quill's (angle, curl) in this pose, or None when it is out writing."""
    if pose.act:
        return _ACT_QUILL[pose.act][pose.i]
    if pose.state == "working":
        return None
    return _QUILL[pose.state][pose.i]


def _ink_shape(pose) -> tuple[int, float, int]:
    """(level, tilt, wave phase) of the ink surface; phase -1 = calm."""
    if pose.act:
        level, tilt = _ACT_INK.get(pose.act, ((INK_LEVEL, 0.0),) * 8)[pose.i]
        return level, tilt, -1
    if pose.state == "held":
        return INK_LEVEL, _HELD_TILT[pose.i], -1
    if pose.state == "error":
        return INK_LEVEL + (1 if pose.i >= 2 else 0), 0.0, pose.i if pose.i < 3 else -1
    if pose.state == "talking":
        return INK_LEVEL, 0.0, pose.i if pose.i == 3 else -1
    if pose.state == "success":
        return INK_LEVEL, 0.0, pose.i if 2 <= pose.i <= 5 else -1
    return INK_LEVEL, 0.0, -1


# -- The body ---------------------------------------------------------------------


def _paint_ink(f, body: set, pose) -> set:
    level, tilt, phase = _ink_shape(pose)
    inner = B.eroded(body, 1)
    ink: dict = {}
    for x, y in inner:
        surface = level + math.floor(round((x - 23.5) * tilt + 0.5, 6))
        if phase >= 0:
            surface += math.floor(math.sin((x + 2 * phase) * math.pi / 4) + 0.5)
        if y < surface:
            continue
        if y == surface:
            ink[(x, y)] = INK_TOP
        elif (x + 1, y) not in inner or (x, y + 1) not in inner:
            ink[(x, y)] = INK_DEEP
        else:
            ink[(x, y)] = INK
    f.paint_map(ink)
    return set(ink)


def _swirl(i: int) -> set:
    """Thinking: three dashes circling inside the ink."""
    out = set()
    for k in range(3):
        a = 2 * math.pi * (i / 8 + k / 3)
        x = math.floor(23.5 + math.cos(a) * 6)
        y = math.floor(38.5 + math.sin(a) * 1.6)
        out |= {(x, y), (x + (1 if math.sin(a) > 0 else -1), y)}
    return out


def draw_inky(f, pose) -> None:
    sleeping = pose.state == "sleeping"
    base, light, dark = GLASS_COOL if sleeping else (GLASS, GLASS_LIGHT, GLASS_DARK)
    with f.offset(pose.dx, pose.dy):
        # Two tiny cork feet peeking out under the bottle.
        for x0 in (14, 28):
            foot = B.rounded_rect(x0, 41, x0 + 5, 44, 1)
            f.part(foot, B.shade(foot, CORK, light=CORK_LIGHT, dark=CORK_DARK, dark_depth=1))
        # The neck, the brass ring and the cork-coloured lip.
        neck = B.rect(19, 16, 28, 23)
        f.part(neck, B.shade(neck, base, light=light, dark=dark, dark_depth=1))
        body = _body()
        f.part(body, B.shade(body, base, light=light, dark=dark, dark_depth=2))
        ink = _paint_ink(f, body, pose)
        if pose.state == "thinking":
            f.paint(_swirl(pose.i) & ink, INK_SHINE)
        _bubbles(f, pose, ink)
        # The glass shine: a tall streak on the left and a dot on the right.
        streak = B.rect(14, 26, 14, 38) | B.rect(15, 25, 15, 26)
        f.paint(streak - ink, GLASS_SHINE)
        f.paint(streak & ink, INK_SHINE)
        f.paint({(33, 27), (33, 28)}, light)
        ring = B.rect(18, 20, 29, 21)
        f.part(ring, {p: GOLD_LIGHT if p[1] == 20 else GOLD_DARK for p in ring})
        f.paint({(19, 20), (20, 20)}, GLASS_SHINE)
        lip = B.rounded_rect(18, 14, 29, 16, 1)
        f.part(lip, {p: CORK_LIGHT if p[1] == 14 else CORK_DARK if p[1] == 16 else CORK
                     for p in lip})
        quill = _quill_for(pose)
        if quill is None:
            f.paint(B.rect(21, 14, 26, 14), INK_DEEP)  # the empty mouth of the bottle
        f.paint({(20, 17), (20, 18)}, GLASS_SHINE)
        # The face on the glass.
        eyes = pose.eyes
        B.draw_eyes(f, eyes, EYE_L, EYE_R, INKY_EYES)
        blush = B.rect(14, 31, 15, 31) | B.rect(32, 31, 33, 31)
        if pose.state in ("success", "held") or pose.i in _ACT_BLUSH.get(pose.act, ()):
            blush |= {(13, 31), (34, 31)}
        f.paint(blush, B.BLUSH)
        mx, my = MOUTH
        if pose.mouth == "o":
            f.paint({(mx + 1, my + 1), (mx + 2, my + 1)}, B.MOUTH_DARK)
            f.paint({(mx + 1, my), (mx + 2, my), (mx, my + 1), (mx + 3, my + 1),
                     (mx + 1, my + 2), (mx + 2, my + 2)}, FACE)
        else:
            B.draw_mouth(f, pose.mouth, mx, my, 4, color=FACE)
        if quill is not None:
            angle, curl = quill
            if sleeping:
                angle += (0, 0, -3, -3, 0, 0)[pose.i]
            bx, by = QUILL_BASE
            length = quill_length(angle, curl, pose.dy - max(0, pose.stretch))
            draw_quill(
                f, bx, by, angle, curl, length,
                ruffle=pose.act == "feather_preen" and 2 <= pose.i <= 4,
                shine=pose.act == "feather_preen" and pose.i == 6,
            )


#: Bubbles rising through the ink: per act/state, (x, y) per frame or None.
_IDLE_BUBBLE = (None, (30, 40), (30, 39), (29, 38), (30, 37), None, None, None)
_POP_BUBBLE = ((25, 40), (24, 38), (25, 36), None, None, None, None, None)


def _bubbles(f, pose, ink: set) -> None:
    spot = None
    if pose.act == "bubble_pop":
        spot = _POP_BUBBLE[pose.i]
    elif pose.state == "idle" and not pose.act:
        spot = _IDLE_BUBBLE[pose.i]
    if spot is None:
        return
    x, y = spot
    big = pose.act == "bubble_pop"
    bubble = B.rect(x, y, x + 1, y + 1) if big else {(x, y)}
    f.paint(bubble & ink, INK_SHINE)
    f.paint({(x, y)} & ink, GLASS_SHINE)


# -- Effects -------------------------------------------------------------------------

_QUOTE = ("##.##", "##.##", ".#..#")


def inky_talking(f, pose) -> None:
    """Quotation marks pop up beside the quill as the voice gets louder."""
    with f.offset(pose.dx, pose.dy):
        if pose.i >= 2:
            f.glyph(8, 15 - (pose.i - 2), _QUOTE, {"#": INK_STROKE})
        if pose.i == 3:
            f.glyph(35, 12, _QUOTE, {"#": INK_STROKE})


_INK_SPARK = {"#": INK_STROKE, "o": INK_SHINE}


def _ribbon(f, path: Sequence, shown: int, fade: int) -> None:
    """The first ``shown`` points of a flourish as a 1 px ink ribbon; its
    first ``fade`` segments already drying (lighter)."""
    pts = path[:shown]
    if len(pts) < 2:
        return
    old = B.polyline(pts[: fade + 1]) if fade else set()
    f.paint(B.polyline(pts) - old, INK_STROKE)
    f.paint(old, INK_STROKE_FADE)


#: Success: a cursive swash with a loop, written in the air left of the head.
_SWASH = (
    (19, 11), (17, 7), (14, 4), (10, 3), (7, 5), (7, 8), (10, 9), (12, 7), (11, 4),
    (8, 2), (5, 2), (3, 4),
)
#: How many swash points show per success frame, and how many have dried.
_SWASH_SHOWN = (0, 3, 6, 9, 12, 12, 12, 0)
_SWASH_FADE = (0, 0, 0, 0, 0, 5, 9, 0)


def inky_success(f, pose) -> None:
    """A happy hop while a swash of ink writes itself in the air, loop and
    all; gold and ink sparkles go off around it."""
    _ribbon(f, _SWASH, _SWASH_SHOWN[pose.i], _SWASH_FADE[pose.i])
    B.fx_sparkles(f, pose.i, ((41, 22, 2), (5, 36, 3), (40, 40, 4)))
    B.fx_sparkles(f, pose.i, ((38, 10, 1), (4, 14, 5)), _INK_SPARK)


_BLOT = (".##.", "####", "####", ".##.")
_DROP = (".#.", "###", "###")
#: Error: ink drops thrown out of the mouth, (x, y) per frame, mirrored.
_SPLASH = (
    ((21, 9),),
    ((18, 6), (22, 3)),
    ((14, 6), (21, 1)),
    ((11, 10),),
    ((9, 16),),
    (),
)


def inky_error(f, pose) -> None:
    """An ink blot bursts out of the bottle: drops fly up and out and land
    as blots on the floor; the red "!" overhead."""
    B.fx_bang(f, 41, 3)
    pal = {"#": INK_STROKE, "o": INK_SHINE}
    with f.offset(pose.dx, 0):
        for x, y in _SPLASH[pose.i]:
            f.glyph(x, y, _DROP, pal)
            f.glyph(47 - x - 3, y + 1, _DROP, pal)
        if pose.i == 0:
            f.paint(B.rect(22, 11, 25, 12), INK_STROKE)
    if pose.i >= 4:
        f.glyph(4, 42, _BLOT, pal)
        f.glyph(40, 43, ("###", ".#."), pal)
    if pose.i >= 5:
        f.glyph(39, 42, _BLOT, pal)


def inky_sleeping(f, pose) -> None:
    B.fx_zzz(f, pose.i, 33, 15)


def _paper(f, lines: int, partial: int) -> None:
    """The sheet of paper with ``lines`` full ink lines and one ``partial`` px long."""
    x, y = PAPER_AT
    sheet = B.rect(x, y, x + 11, y + 13) - {(x + 11, y), (x + 10, y), (x + 11, y + 1)}
    fill = {p: PAPER for p in sheet}
    for p in sheet:
        if p[0] == x + 11 or p[1] == y + 13:
            fill[p] = PAPER_DARK
    fill[(x + 10, y + 1)] = PAPER_DARK
    for r in range(4):
        for cx in range(x + 2, x + 10):
            fill[(cx, y + 3 + 3 * r)] = PAPER_RULE
    f.part(sheet, fill)
    scribble = (0, 1, 0, 0, 1, 1, 0, 1)
    for r in range(4):
        n = 7 if r < lines else partial if r == lines else 0
        for k in range(n):
            f.paint({(x + 2 + k, y + 2 + 3 * r + scribble[(k + r) % 8])}, INK_DEEP)


#: Working: (lines done, partial length) per frame: one line takes four frames.
_WRITE = ((0, 1), (0, 3), (0, 5), (0, 7), (1, 1), (1, 3), (1, 5), (1, 7))


def _writing_quill(f, lines: int, partial: int, i: int) -> None:
    x, y = PAPER_AT
    nx = x + 2 + max(0, partial - 1)
    ny = y + 2 + 3 * min(lines, 3) + (i % 2)
    draw_quill(f, nx, ny - 1, -12 + 6 * (i % 2), 8, 13, nib=True)


def inky_working(f, pose) -> None:
    """The quill hops out of the bottle and scribbles line after line on a
    sheet of paper; little ticks fly off the nib."""
    lines, partial = _WRITE[pose.i]
    _paper(f, lines, partial)
    _writing_quill(f, lines, partial, pose.i)
    if pose.i % 2 == 0:
        x, y = PAPER_AT
        tx = x + 2 + partial
        f.paint({(tx + 1, y + 1 + 3 * lines)}, INK_STROKE)


def inky_held(f, pose) -> None:
    """Dangling: ink drops fling out of the mouth as it swings."""
    B.fx_held(f, pose.i, (9, 25), (38, 25))
    with f.offset(pose.dx, pose.dy):
        drops = ((15, 10), (), (32, 9), (34, 5), (), (13, 6))[pose.i]
        if drops:
            f.glyph(drops[0], drops[1], ("##", "#o"), {"#": INK_STROKE, "o": INK_SHINE})


# -- Idle acts -------------------------------------------------------------------

_ACT_QUILL: dict[str, tuple[tuple[float, float] | None, ...]] = {
    "quill_flourish": (
        (20, 22), (32, 26), (42, 30), (50, 34), (55, 36), (45, 30), (30, 26), (20, 22),
    ),
    "ink_slosh": (
        (20, 22), (35, 25), (20, 22), (5, 15), (20, 22), (30, 25), (20, 22), (20, 22),
    ),
    "blot_oops": (
        (20, 22), (5, 10), (45, 35), (30, 25), (25, 25), (70, 70), (75, 75), (20, 22),
    ),
    "signature": ((20, 22), None, None, None, None, None, None, (20, 22)),
    "feather_preen": (
        (20, 22), (-40, -40), (-70, -60), (-55, -50), (-70, -60), (-20, -10), (15, 18), (20, 22),
    ),
    "bubble_pop": (
        (20, 22), (20, 22), (30, 28), (40, 32), (45, 34), (45, 34), (30, 26), (20, 22),
    ),
}
_ACT_INK: dict[str, tuple[tuple[int, float], ...]] = {
    "ink_slosh": (
        (35, 0.0), (35, 0.3), (35, 0.0), (35, -0.3), (35, 0.0), (35, 0.2), (35, -0.1), (35, 0.0),
    ),
}
_ACT_BLUSH: dict[str, tuple[int, ...]] = {
    "blot_oops": (5, 6),
    "signature": (7,),
    "feather_preen": (6, 7),
    "bubble_pop": (7,),
}


def _act_pose(name: str, **columns: Sequence) -> Callable:
    def pose(i: int):
        fields = {key: values[i] for key, values in columns.items()}
        return B.Pose("idle", i, act=name, **fields)

    return pose


#: Quill flourish: the loop the quill's tip writes to the right of the head.
_LOOP = (
    (33, 6), (36, 3), (40, 2), (43, 4), (43, 7), (40, 9), (37, 8), (37, 5), (40, 3),
    (44, 2), (46, 4),
)
_LOOP_SHOWN = (0, 2, 4, 6, 8, 11, 11, 0)
_LOOP_FADE = (0, 0, 0, 0, 0, 3, 7, 0)


def _flourish_fx(f, pose) -> None:
    """The quill leans out and writes a loop in the air, a ribbon of ink
    that dries from its tail; a sparkle crowns the finish."""
    _ribbon(f, _LOOP, _LOOP_SHOWN[pose.i], _LOOP_FADE[pose.i])
    if pose.i >= 5:
        B.fx_sparkles(f, pose.i - 5, ((42, 12, 0),))


def _slosh_fx(f, pose) -> None:
    """Ticks on the side the ink sloshes against."""
    tilt = _ACT_INK["ink_slosh"][pose.i][1]
    with f.offset(pose.dx, 0):
        if tilt > 0.2:
            f.paint(B.line(39, 33, 41, 31) | B.line(39, 36, 42, 36), B.ARC)
        elif tilt < -0.2:
            f.paint(B.line(8, 33, 6, 31) | B.line(8, 36, 5, 36), B.ARC)


#: Blot oops: the flying drop (x, y) per frame, then the blot on the floor.
_OOPS_DROP = (None, None, (36, 3), (40, 6), (42, 14), None, None, None)


def _oops_fx(f, pose) -> None:
    """A flick of the quill sends a drop flying; it lands as a blot on the
    floor. Oops. A sheepish blush."""
    pal = {"#": INK_STROKE, "o": INK_SHINE}
    spot = _OOPS_DROP[pose.i]
    if spot is not None:
        f.glyph(spot[0], spot[1], (".#.", "###", "#o#", ".#."), pal)
    if pose.i == 4:
        f.paint(B.line(43, 20, 43, 30), INK_STROKE_FADE)
    if pose.i == 5:
        f.glyph(37, 41, ("#..#..#", ".#####.", "###o###", ".#.#.#."), pal)
    if pose.i >= 6:
        f.glyph(37, 43, (".####..", "###o###", ".#####."), pal)
    if pose.i in (5, 6):
        B.fx_sweat(f, 0, 35, 16)


#: Signature: how many points of the name show per frame (None = no paper).
_SIGN_SHOWN = (None, 1, 4, 7, 10, 10, 10, None)


def _signature_fx(f, pose) -> None:
    """Inky pulls the quill out and signs its name on a sheet with a loop,
    a dot and a proud underline."""
    i = pose.i
    shown = _SIGN_SHOWN[i]
    if shown is None:
        if i == 7:
            B.fx_sparkles(f, 1, ((41, 34, 0),))
        return
    x, y = PAPER_AT
    _paper(f, 0, 0)
    name = [(x + 1, y + 9), (x + 2, y + 6), (x + 3, y + 5), (x + 3, y + 8), (x + 4, y + 9),
            (x + 5, y + 7), (x + 6, y + 9), (x + 7, y + 7), (x + 8, y + 9), (x + 9, y + 6),
            (x + 10, y + 8)]
    pts = name[:shown]
    f.paint(B.polyline(pts) if len(pts) > 1 else set(pts), INK_DEEP)
    nx, ny = pts[-1]
    if i >= 5:
        f.paint({(x + 5, y + 4)}, INK_DEEP)  # the dot
        f.paint(B.line(x + 1, y + 11, x + 3 + 2 * (i - 4), y + 11), INK_STROKE)
        nx, ny = (x + 5, y + 4) if i == 5 else (x + 3 + 2 * (i - 4), y + 11)
    draw_quill(f, nx, ny - 1, -12 + 6 * (i % 2), 8, 13, nib=True)


def _preen_fx(f, pose) -> None:
    """The quill bends down and ruffles; a shake sends fluff flying, then it
    lies smooth and gleams."""
    if pose.i in (3, 4, 5):
        k = pose.i - 3
        for x, y in ((7 - k, 19 + 2 * k), (10 - k, 12 - 2 * k), (4 - k, 14 - k)):
            f.glyph(x, y, ("##",), {"#": QUILL})
    if pose.i == 6:
        bx, by = QUILL_BASE
        tx, ty = quill_tip(bx, by, 15, 18, 14)
        B.fx_sparkles(f, 1, ((tx + 3, ty + 2, 0),))


#: Bubble pop: the bubble above the bottle, (x, y, size) per frame.
_POP_AIR = (None, None, None, (20, 10, 1), (17, 6, 2), (14, 2, 3), None, None)


def _bubble_fx(f, pose) -> None:
    """An ink bubble rises through the ink, squeezes out of the mouth, floats
    up and pops."""
    spot = _POP_AIR[pose.i]
    pal = {"#": INK_TOP, "o": INK_SHINE, "w": GLASS_SHINE}
    if spot is not None:
        x, y, size = spot
        rows = {
            1: ("##", "##"),
            2: (".##.", "#wo#", "#oo#", ".##."),
            3: (".###.", "#woo#", "#ooo#", "#ooo#", ".###."),
        }[size]
        f.glyph(x, y, rows, pal)
    if pose.i == 6:
        x, y = 14, 2
        f.paint({(x, y), (x + 4, y), (x, y + 4), (x + 4, y + 4)}, INK_STROKE)
        f.paint({(x + 2, y - 1), (x - 1, y + 2), (x + 5, y + 2), (x + 2, y + 5)}, INK_STROKE_FADE)
        B.fx_sparkles(f, 0, ((x + 7, y + 3, 0),), _INK_SPARK)


def _acts():
    return (
        B.IdleAct(
            "quill_flourish", 8, 9,
            _act_pose(
                "quill_flourish",
                eyes=("open", "up_right", "up_right", "up_right", "up_right", "happy", "happy",
                      "open"),
                mouth=("rest", "rest", "half", "open", "open", "smile", "smile", "rest"),
                stretch=(0, 1, 1, 1, 0, 0, 0, 0),
            ),
            _flourish_fx,
        ),
        B.IdleAct(
            "ink_slosh", 8, 8,
            _act_pose(
                "ink_slosh",
                dx=(0, -1, 0, 1, 0, -1, 0, 0),
                eyes=("open", "look_right", "open", "look_left", "open", "look_right", "happy",
                      "open"),
                mouth=("rest", "half", "closed", "half", "closed", "half", "smile", "rest"),
            ),
            _slosh_fx,
        ),
        B.IdleAct(
            "blot_oops", 8, 8,
            _act_pose(
                "blot_oops",
                dy=(0, 0, -1, 0, 0, 0, 0, 0),
                eyes=("open", "up_right", "wide", "look_right", "look_right", "wide", "happy",
                      "open"),
                mouth=("rest", "closed", "half", "o", "o", "frown", "closed", "rest"),
            ),
            _oops_fx,
        ),
        B.IdleAct(
            "signature", 8, 7,
            _act_pose(
                "signature",
                dx=(0, -2, -4, -4, -4, -4, -2, 0),
                eyes=("open", "look_right", "down", "down", "down", "look_right", "happy",
                      "happy"),
                mouth=("rest", "rest", "closed", "closed", "closed", "smile", "smile", "smile"),
                stretch=(0, 0, 0, 0, 0, 1, 1, 0),
            ),
            _signature_fx,
        ),
        B.IdleAct(
            "feather_preen", 8, 8,
            _act_pose(
                "feather_preen",
                dx=(0, 0, 0, -1, 1, 0, 0, 0),
                eyes=("open", "look_left", "closed", "closed", "closed", "open", "happy",
                      "open"),
                mouth=("rest", "closed", "smile", "closed", "closed", "rest", "smile", "rest"),
            ),
            _preen_fx,
        ),
        B.IdleAct(
            "bubble_pop", 8, 8,
            _act_pose(
                "bubble_pop",
                eyes=("down", "down", "open", "up_left", "up_left", "up_left", "wide", "happy"),
                mouth=("rest", "closed", "closed", "o", "o", "o", "open", "smile"),
                dy=(0, 0, 0, 0, 0, 0, -1, 0),
            ),
            _bubble_fx,
        ),
    )


INKY_EYES = None


def design(bp):
    global B, INKY_EYES
    B = bp
    INKY_EYES = bp.EyeStyle(w=3, h=4, iris=FACE, glint=bp.FX_WHITE, lid=FACE)
    return bp.PetDesign(
        id="inky",
        name="Inky",
        description="A little inkwell with a quill for a tuft that writes down every idea.",
        draw=draw_inky,
        pose=inky_pose,
        anchors=bp.Anchors(
            arcs_left=(9, 25),
            arcs_right=(38, 25),
            dots=(4, 8),
            zzz=(33, 15),
            bang=(41, 3),
            sweat=(35, 16),
            sparkles=((6, 14, 1), (41, 22, 2), (5, 36, 3)),
            laptop=(17, 34),
            magnifier=(24, 28),
        ),
        fx={
            "talking": inky_talking,
            "success": inky_success,
            "error": inky_error,
            "sleeping": inky_sleeping,
            "working": inky_working,
            "held": inky_held,
        },
        acts=_acts(),
        waist=38,
    )
