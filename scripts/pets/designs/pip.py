"""Pip: the penguin chick (a design module for ``scripts/pets/build_pets.py``).

A round little emperor chick in fluffy grey down: a dark cap with a fluffy
cowlick, a white face mask, big round black eyes with glints, a tiny orange
beak, short flippers and orange feet. Pip is curious and a bit clumsy: it
stands tall with its flippers out to listen, taps its beak while it thinks,
hops with its flippers up when something works, shivers with its down all
ruffled when something fails, pecks at a laptop while it works, peers through
a magnifier while it searches and naps sitting down with its beak tucked into
its fluff. Its idle acts are little scenes: a belly slide, a snowball that
lands on its own head, a fish snack, a flight attempt, a tumble and a preen.

``design(bp)`` gets the builder module as ``bp`` and every helper comes from
there; the module keeps a reference in ``bp`` for the drawing functions.
"""

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

#: The builder module (``scripts/pets/build_pets.py``), set by ``design``.
bp: Any = None

Px = tuple[int, int]
Pt = tuple[float, float]
RGBA = tuple[int, int, int, int]
Mask = set[Px]


def _hex(value: str) -> RGBA:
    value = value.lstrip("#")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), 255)


# -- Palette ------------------------------------------------------------------

DOWN = _hex("#9aa4b3")
DOWN_LIGHT = _hex("#c4ccd8")
DOWN_DARK = _hex("#6c7686")
#: The little V-shaped down marks on the body.
DOWN_TICK = _hex("#838d9d")
BELLY = _hex("#d2d8e2")
BELLY_DARK = _hex("#b2bbc8")
CAP = _hex("#3e4555")
CAP_LIGHT = _hex("#5f687b")
CAP_DARK = _hex("#2b303c")
MASK = _hex("#f7f8fb")
MASK_SHADE = _hex("#d5dbe6")
EYE = _hex("#17131d")
BEAK = _hex("#ffa63d")
BEAK_LIGHT = _hex("#ffd48a")
BEAK_DARK = _hex("#d9692b")
FOOT = _hex("#ff9b3d")
FOOT_LIGHT = _hex("#ffc27a")
FOOT_DARK = _hex("#cc6127")
BLUSH = _hex("#ffb0bf")
FLIP = _hex("#7f8999")
FLIP_LIGHT = _hex("#a8b2c0")
FLIP_DARK = _hex("#5c6576")
SNOW = _hex("#f4f8ff")
SNOW_SHADE = _hex("#c3d4ec")
ICE = _hex("#8fd0ff")
ICE_CORE = _hex("#e3f4ff")
FISH = _hex("#5aa6e6")
FISH_LIGHT = _hex("#a8dcff")
FISH_FIN = _hex("#2f6eb0")
HEART = _hex("#ff6f91")
HEART_SHINE = _hex("#ffd3de")
BUBBLE = _hex("#bfe3ff")

# -- Geometry -----------------------------------------------------------------

CX = 24
HEAD = (24.0, 18.5, 12.0, 10.0)
BODY = (24.0, 33.5, 13.0, 10.5)
#: The sitting body (sleeping, working and the tumble's plop): lower and wider.
SIT_BODY = (24.0, 36.0, 13.5, 9.0)
#: Top-left of each 5 x 6 eye box.
EYE_AT: tuple[Px, Px] = ((16, 16), (27, 16))
BEAK_AT: Px = (22, 23)
#: The left flipper's shoulder; the right one is mirrored.
SHOULDER: Pt = (14.5, 27.5)
#: Left flipper tips per name (the right flipper uses the mirrored tip).
FLIPPER_TIPS: dict[str, Pt] = {
    "rest": (10.5, 37.5),
    "half": (7.5, 33.5),
    "out": (4.5, 29.5),
    "up": (6.5, 18.5),
    "flap_up": (3.5, 21.5),
    "flap_down": (4.5, 37.5),
    "hug": (18.5, 34.5),
    "hug2": (18.5, 33.5),
    "front": (19.5, 36.5),
    "tap": (21.5, 25.5),
    "tap2": (21.5, 26.5),
    "preen": (9.5, 25.5),
    "key": (18.5, 37.5),
    "key2": (19.5, 36.5),
}
#: Where each eye style moves the whole eye.
LOOKS: dict[str, Px] = {
    "open": (0, 0),
    "wide": (0, 0),
    "look_left": (-1, 0),
    "look_right": (1, 0),
    "up_left": (-1, -1),
    "up_right": (1, -1),
    "up": (0, -1),
    "down": (0, 1),
}
#: Closed-eye shapes on the 5 x 6 eye box (the right eye is mirrored).
LIDS: dict[str, tuple[str, ...]] = {
    "closed": (".....", ".....", ".....", "#...#", ".###.", "....."),
    "sleep": (".....", ".....", ".....", "#...#", ".###.", "....."),
    "happy": (".....", ".###.", "#...#", ".....", ".....", "....."),
    "squint": (".....", "##...", "..##.", "....#", "..##.", "##..."),
    "x": (".....", "#...#", ".#.#.", "..#..", ".#.#.", "#...#"),
    "dizzy": (".###.", "#...#", "#.#.#", "#.##.", "#....", ".####"),
}
#: The fluffy cowlick on top of the head.
TUFT = ("...#.#", "..#.#.", "..##..")


# -- One frame's drawing ------------------------------------------------------


@dataclass(frozen=True)
class Cell:
    """One frame: the pose fields plus the parts only Pip moves."""

    dx: int = 0
    dy: int = 0
    eyes: str = "open"
    beak: str = "rest"
    stretch: int = 0
    #: Left and right flipper: a tip name, or a tip point in left-flipper
    #: coordinates (the right flipper mirrors it).
    flips: tuple[str | Pt, str | Pt] = ("rest", "rest")
    #: The head's offset from the body.
    head: Px = (0, 0)
    #: How far each foot is lifted.
    feet: Px = (0, 0)
    #: 0 smooth down, 1 ruffled (spiky tufts), 2 puffed up round.
    fluff: int = 0
    #: "stand", "sit", "plop" (sitting, feet out front), "dangle" or "prone".
    view: str = "stand"
    #: The body's centre x while lying on the belly (``view == "prone"``).
    slide: int = 24
    snow: bool = False
    #: The beak tucked into the fluff (asleep).
    tuck: bool = False


_C = Cell
_UP = ("up", "up")
_OUT = ("out", "out")
_HALF = ("half", "half")


def _in_cell(mask: Iterable[Px], margin: int = 1) -> Mask:
    """``mask`` clipped so that it and its outline stay inside the cell."""
    hi = bp.CELL - 1 - margin
    return {(x, y) for x, y in mask if margin <= x <= hi and margin <= y <= hi}


def _down(f: Any, mask: Mask, depth: int = 2) -> None:
    f.part(mask, bp.shade(mask, DOWN, light=DOWN_LIGHT, dark=DOWN_DARK, dark_depth=depth))


def _tufts(cx: float, cy: float, rx: float, ry: float, angles: Iterable[int], size: float) -> Mask:
    """Little spiky tufts of down poking out of an ellipse at ``angles`` (degrees)."""
    out: Mask = set()
    for deg in angles:
        a = math.radians(deg)
        b1, b2 = math.radians(deg - 9), math.radians(deg + 9)
        tip = (cx + math.cos(a) * (rx + size), cy + math.sin(a) * (ry + size))
        out |= bp.polygon(
            [
                (cx + math.cos(b1) * (rx - 1), cy + math.sin(b1) * (ry - 1)),
                tip,
                (cx + math.cos(b2) * (rx - 1), cy + math.sin(b2) * (ry - 1)),
            ]
        )
    return out


def _body_mask(cx: float, cy: float, rx: float, ry: float, fluff: int) -> Mask:
    """The round body with a scalloped, fluffy rim along its sides and bottom."""
    if fluff == 2:
        rx, ry = rx + 1.0, ry + 0.5
    body = bp.ellipse(cx, cy, rx, ry)
    for deg in range(-10, 191, 25):
        a = math.radians(deg)
        body |= bp.ellipse(cx + math.cos(a) * rx * 0.97, cy + math.sin(a) * ry * 0.95, 1.7, 1.5)
    if fluff == 1:
        body |= _tufts(cx, cy, rx, ry, (-150, -125, -55, -30, 10, 60, 120, 170), 2.4)
    return body


def _down_ticks(f: Any, body: Mask, cx: float, cy: float) -> None:
    """A few soft V-marks of down on the body."""
    marks: Mask = set()
    for mx, my in ((-8, -2), (7, -3), (-6, 5), (9, 4), (-10, 3)):
        x, y = int(cx) + mx, int(cy) + my
        marks |= {(x - 1, y), (x, y + 1), (x + 1, y)}
    f.paint(marks & bp.eroded(body, 2), DOWN_TICK)


def _belly(f: Any, cx: float, cy: float, rx: float, ry: float, body: Mask) -> None:
    belly = bp.ellipse(cx, cy, rx, ry) & bp.eroded(body, 1)
    f.paint_map(bp.shade(belly, BELLY, dark=BELLY_DARK, dark_depth=1))


def _flipper(f: Any, tip: str | Pt, *, right: bool, root: Pt = SHOULDER) -> None:
    """A short tapered flipper from ``root`` to ``tip``, outlined everywhere but
    where it grows out of the body."""
    tx, ty = FLIPPER_TIPS[tip] if isinstance(tip, str) else tip
    rx, ry = root
    ex, ey = tx - rx, ty - ry
    length = math.hypot(ex, ey) or 1.0
    nx, ny = -ey / length, ex / length
    mask = bp.polygon(
        [
            (rx + nx * 2.4, ry + ny * 2.4),
            (tx + nx * 1.3, ty + ny * 1.3),
            (tx - nx * 1.3, ty - ny * 1.3),
            (rx - nx * 2.4, ry - ny * 2.4),
        ]
    ) | bp.ellipse(tx, ty, 1.5, 1.5)
    joint = bp.ellipse(rx, ry, 2.6, 2.6)
    if right:
        mask, joint = bp.mirrored(mask), bp.mirrored(joint)
    f.paint(bp.outer_ring(mask) - joint, bp.OUTLINE)
    f.paint_map(bp.shade(mask, FLIP, light=FLIP_LIGHT, dark=FLIP_DARK, dark_depth=1))


def _flippers(f: Any, c: Cell, root: Pt = SHOULDER) -> None:
    _flipper(f, c.flips[0], right=False, root=root)
    _flipper(f, c.flips[1], right=True, root=root)


def _feet(f: Any, lift: Px = (0, 0), spread: int = 0) -> None:
    """Two orange feet in front of the fluff, toes split by darker lines."""
    for side, up in enumerate(lift):
        foot = bp.ellipse(18.5 - spread, 44.5 - up, 3.8, 2.1)
        y = 45 - up
        toes = {(17 - spread, y), (19 - spread, y), (16 - spread, y + 1), (20 - spread, y + 1)}
        light = {(16 - spread, 43 - up), (17 - spread, 43 - up), (18 - spread, 43 - up)}
        if side:
            foot, toes, light = bp.mirrored(foot), bp.mirrored(toes), bp.mirrored(light)
        f.part(foot, FOOT)
        f.paint(light & foot, FOOT_LIGHT)
        f.paint((toes & foot) - light, FOOT_DARK)


def _soles(f: Any) -> None:
    """Both feet stuck out in front, soles to the viewer (sitting with a plop)."""
    for side in (0, 1):
        sole = bp.ellipse(17.5, 42.5, 2.6, 3.2)
        toes = {(16, 40), (18, 40)}
        if side:
            sole, toes = bp.mirrored(sole), bp.mirrored(toes)
        f.part(sole, bp.shade(sole, FOOT, light=FOOT_LIGHT, dark=FOOT_DARK, dark_depth=1))
        f.paint(toes, FOOT_DARK)


def _eyes(f: Any, style: str) -> None:
    for side, (x, y) in enumerate(EYE_AT):
        if style in LIDS:
            rows = LIDS[style]
            if side:
                rows = tuple(r[::-1] for r in rows)
            f.paint(bp.from_rows(x, y, rows), bp.OUTLINE)
            continue
        lx, ly = LOOKS[style]
        x, y = x + lx, y + ly
        top, h = (y - 1, 7) if style == "wide" else (y, 6)
        oval = bp.rect(x, top, x + 4, top + h - 1)
        oval -= {(x, top), (x + 4, top), (x, top + h - 1), (x + 4, top + h - 1)}
        f.paint(oval, EYE)
        f.paint(bp.rect(x + 2, top + 1, x + 3, top + 2), bp.FX_WHITE)
        f.paint({(x + 1, top + h - 2)}, bp.FX_WHITE)


def _beak(f: Any, style: str) -> None:
    """The tiny beak; talking opens it from closed to widest."""
    x, y = BEAK_AT
    dark = bp.MOUTH_DARK
    if style == "tuck":
        f.paint(bp.rect(x + 1, y, x + 2, y), BEAK)
        f.paint({(x + 1, y)}, BEAK_LIGHT)
        return
    if style in ("rest", "closed", "smile", "fish"):
        f.paint(bp.rect(x, y, x + 3, y), BEAK)
        f.paint({(x, y)}, BEAK_LIGHT)
        f.paint({(x + 1, y + 1)}, BEAK)
        f.paint({(x + 2, y + 1)}, BEAK_DARK)
        return
    if style == "half":
        f.paint(bp.rect(x, y, x + 3, y), BEAK)
        f.paint({(x, y)}, BEAK_LIGHT)
        f.paint(bp.rect(x, y + 1, x + 3, y + 1), dark)
        f.paint(bp.rect(x + 1, y + 2, x + 2, y + 2), BEAK_DARK)
        return
    if style == "open":
        f.paint(bp.rect(x - 1, y, x + 4, y), BEAK)
        f.paint({(x - 1, y)}, BEAK_LIGHT)
        f.paint(bp.rect(x, y + 1, x + 3, y + 2), dark)
        f.paint(bp.rect(x + 1, y + 2, x + 2, y + 2), bp.TONGUE)
        f.paint(bp.rect(x, y + 3, x + 3, y + 3), BEAK)
        f.paint({(x + 3, y + 3)}, BEAK_DARK)
        return
    if style == "wide":
        f.paint(bp.rect(x - 1, y, x + 4, y), BEAK)
        f.paint({(x - 1, y)}, BEAK_LIGHT)
        f.paint(bp.rect(x - 1, y + 1, x + 4, y + 3) - {(x - 1, y + 3), (x + 4, y + 3)}, dark)
        f.paint(bp.rect(x, y + 3, x + 3, y + 3), bp.TONGUE)
        f.paint(bp.rect(x, y + 4, x + 3, y + 4), BEAK)
        f.paint({(x + 3, y + 4)}, BEAK_DARK)
        return
    raise KeyError(style)


def _head_mask(fluff: int) -> Mask:
    head = bp.ellipse(*HEAD) | bp.from_rows(19, 6, TUFT)
    if fluff == 1:
        head |= _tufts(HEAD[0], HEAD[1], HEAD[2], HEAD[3], (-160, -125, -55, -20, 160, 20), 2.2)
    return head


def _face_mask(head: Mask) -> Mask:
    eye = bp.ellipse(18.5, 19.0, 5.2, 5.0)
    face = eye | bp.mirrored(eye) | bp.ellipse(CX, 23.5, 9.0, 5.0)
    return face & bp.eroded(head, 1) | (face & head & bp.rect(0, 25, 47, 47))


def _head(f: Any, c: Cell, eyes: str, beak: str) -> None:
    """The dark cap with its cowlick, the white face mask and the face."""
    head = _head_mask(c.fluff)
    f.part(head, bp.shade(head, CAP, light=CAP_LIGHT, dark=CAP_DARK, dark_depth=1))
    face = _face_mask(bp.ellipse(*HEAD))
    f.paint_map(bp.shade(face, MASK, dark=MASK_SHADE, dark_depth=1))
    cheek = bp.rect(15, 23, 17, 23)
    f.paint(cheek | bp.mirrored(cheek), BLUSH)
    _eyes(f, eyes)
    _beak(f, "tuck" if c.tuck else beak)
    if c.snow:
        _snow_cap(f)


def _snow_cap(f: Any) -> None:
    """A dollop of snow sitting on the head after the snowball came down."""
    pile = bp.ellipse(CX, 9.5, 7.5, 3.2) | bp.ellipse(18.5, 11.5, 2.2, 1.6)
    pile |= bp.ellipse(30.0, 12.0, 1.6, 1.8)
    f.part(pile, bp.shade(pile, SNOW, dark=SNOW_SHADE, dark_depth=1))


def _collar(f: Any, dy: int) -> None:
    """Puffs of chest fluff pulled up over the chin: the beak tucked in."""
    collar: Mask = set()
    for x in (17.0, 20.5, 24.0, 27.5, 31.0):
        collar |= bp.ellipse(x, 26.5 + dy + (0.5 if x in (17.0, 31.0) else 0.0), 2.6, 2.0)
    f.part(collar, bp.shade(collar, DOWN_LIGHT, dark=DOWN, dark_depth=1))


# -- Views --------------------------------------------------------------------


def _draw_stand(f: Any, pose: Any, c: Cell) -> None:
    with f.offset(pose.dx, pose.dy):
        body = _body_mask(*BODY, c.fluff)
        _down(f, body)
        _belly(f, CX, 36.5, 8.0, 6.5, body)
        _down_ticks(f, body, BODY[0], BODY[1])
        with f.offset(*c.head):
            _head(f, c, pose.eyes, pose.mouth)
        _flippers(f, c)
        if c.view == "dangle":
            _dangling_feet(f, pose.i)
    if c.view != "dangle":
        with f.offset(pose.dx, min(pose.dy, 0)):
            _feet(f, c.feet)


def _dangling_feet(f: Any, i: int) -> None:
    """Held: the feet hang down and kick in turn."""
    for side in (0, 1):
        kick = (i + side) % 2
        foot = bp.ellipse(19.0 - kick, 44.5 - kick, 2.8, 2.4)
        if side:
            foot = bp.mirrored(foot)
        f.part(foot, bp.shade(foot, FOOT, light=FOOT_LIGHT, dark=FOOT_DARK, dark_depth=1))


def _draw_sit(f: Any, pose: Any, c: Cell) -> None:
    """Sitting down: a round ball of fluff, the head sunk a little lower."""
    with f.offset(pose.dx, pose.dy):
        if c.view == "plop":
            _soles(f)
        body = _body_mask(*SIT_BODY, c.fluff)
        _down(f, body)
        _belly(f, CX, 38.5, 8.5, 5.5, body)
        _down_ticks(f, body, SIT_BODY[0], SIT_BODY[1])
        if c.view == "plop":
            _soles(f)
        with f.offset(c.head[0], c.head[1]):
            _head(f, c, pose.eyes, pose.mouth)
        if c.tuck:
            _collar(f, c.head[1])
        _flippers(f, c, root=(14.0, 32.5))


def _draw_prone(f: Any, pose: Any, c: Cell) -> None:
    """Lying on the belly and sliding along, facing right."""
    s = c.slide
    for fx, fy in ((s - 13.0, 40.5), (s - 12.0, 43.0)):
        foot = bp.ellipse(fx, fy, 2.6, 1.3)
        f.part(foot, bp.shade(foot, FOOT, light=FOOT_LIGHT, dark=FOOT_DARK, dark_depth=1))
    body = bp.ellipse(s, 38.0, 12.5, 7.0)
    for k in range(5):
        body |= bp.ellipse(s - 9.0 + 4.5 * k, 31.8 + (0.6 if k % 2 else 0.0), 1.8, 1.5)
    _down(f, body)
    under = {(x, y) for x, y in bp.eroded(body, 1) if y >= 41}
    f.paint(under, BELLY)
    head = bp.ellipse(s + 10.0, 33.5, 8.0, 7.5) | bp.from_rows(s + 7, 24, ("#.#", ".##"))
    f.part(head, bp.shade(head, CAP, light=CAP_LIGHT, dark=CAP_DARK, dark_depth=1))
    face = bp.ellipse(s + 12.5, 35.0, 5.5, 4.5) & bp.eroded(head, 1)
    f.paint_map(bp.shade(face, MASK, dark=MASK_SHADE, dark_depth=1))
    f.paint({(s + 10, 37), (s + 11, 37)}, BLUSH)
    ex, ey = s + 12, 31
    if pose.eyes == "happy":
        f.paint({(ex, ey + 2), (ex + 1, ey + 1), (ex + 2, ey + 1), (ex + 3, ey + 2)}, bp.OUTLINE)
    else:
        f.paint(bp.rect(ex, ey, ex + 2, ey + 3) - {(ex, ey), (ex, ey + 3)}, EYE)
        f.paint({(ex + 1, ey + 1)}, bp.FX_WHITE)
    bx, by = s + 18, 35
    if pose.mouth in ("open", "wide"):
        f.paint(bp.rect(bx, by - 1, bx + 2, by - 1), BEAK)
        f.paint(bp.rect(bx, by, bx + 1, by), bp.MOUTH_DARK)
        f.paint(bp.rect(bx, by + 1, bx + 1, by + 1), BEAK_DARK)
    else:
        f.paint(bp.rect(bx, by, bx + 2, by) | {(bx, by + 1), (bx + 1, by + 1)}, BEAK)
        f.paint({(bx + 1, by + 1)}, BEAK_DARK)
    flip = bp.polygon([(s + 3.5, 33.5), (s - 9.5, 31.5), (s - 9.0, 33.5), (s + 3.5, 36.5)])
    f.paint(bp.outer_ring(flip) - bp.ellipse(s + 3.5, 35.5, 2.0, 2.0), bp.OUTLINE)
    f.paint_map(bp.shade(flip, FLIP, light=FLIP_LIGHT, dark=FLIP_DARK, dark_depth=1))


def draw_pip(f: Any, pose: Any) -> None:
    c = _cell(pose)
    if c.view == "prone":
        _draw_prone(f, pose, c)
    elif c.view in ("sit", "plop"):
        _draw_sit(f, pose, c)
    else:
        _draw_stand(f, pose, c)


# -- States -------------------------------------------------------------------

_IDLE_EYES = ("open", "open", "open", "look_left", "look_left", "open", "look_right")
_IDLE_FLIPS: tuple[tuple[str, str], ...] = (
    ("rest", "rest"),
    ("rest", "rest"),
    ("rest", "rest"),
    ("rest", "half"),
    ("rest", "rest"),
    ("rest", "rest"),
    ("rest", "rest"),
)
#: A tiny waddle: the weight shifts from foot to foot.
_IDLE_FEET: tuple[Px, ...] = ((0, 0), (0, 0), (1, 0), (0, 0), (0, 0), (0, 1), (0, 0))
_LISTEN_TILT = (0, 1, 1, 1, 1, 0)
_HOP = (0, -1, -3, -4, -3, -1, 0, 0)
_HOP_STRETCH = (-1, 1, 1, 0, 0, 1, -1, 0)
_SHIVER = (-1, 1, -1, 1, -1, 1)
_ERROR_EYES = ("wide", "squint", "squint", "x", "x", "squint")
_ERROR_BEAK = ("half", "closed", "half", "closed", "half", "closed")
_PECK = (0, 1, 2, 0, 0, 1, 2, 0)
_HELD_FLAP = (("flap_up", "flap_down"), ("flap_down", "flap_up")) * 3


def _search_tip(sweep: int) -> Pt:
    """Left-flipper coordinates of the right flipper holding the magnifier."""
    hx = CX + sweep + 6
    return (2 * CX - 1 - hx + 0.5, 27.5)


def _state_cell(state: str, i: int) -> Cell:
    if state == "idle":
        if i >= len(_IDLE_EYES):
            return _C(eyes="closed")  # the blink (the accent cell)
        return _C(
            eyes=_IDLE_EYES[i],
            stretch=bp.IDLE_BREATH[i],
            flips=_IDLE_FLIPS[i],
            feet=_IDLE_FEET[i],
        )
    if state == "listening":
        return _C(dy=-1, eyes="wide", stretch=1, flips=_OUT, head=(_LISTEN_TILT[i], 0))
    if state == "thinking":
        tap = "tap2" if i % 4 in (1, 2) else "tap"
        return _C(eyes="up_left" if i < 4 else "up_right", beak="closed", flips=("rest", tap))
    if state == "talking":
        flips = (("rest", "rest"), ("rest", "rest"), ("half", "rest"), _HALF)[i]
        return _C(dy=0 if i < 2 else -1, beak=bp.TALK_MOUTHS[i], flips=flips)
    if state == "success":
        air = _HOP[i] <= -1
        return _C(
            dy=_HOP[i],
            eyes="happy",
            beak="open" if 1 <= i <= 5 else "smile",
            stretch=_HOP_STRETCH[i],
            flips=_UP if air else _HALF,
            feet=(1, 1) if _HOP[i] <= -3 else (0, 0),
        )
    if state == "error":
        return _C(
            dx=_SHIVER[i],
            eyes=_ERROR_EYES[i],
            beak=_ERROR_BEAK[i],
            flips=("hug", "hug2") if i % 2 else ("hug2", "hug"),
            fluff=1,
        )
    if state == "sleeping":
        return _C(
            dy=1,
            eyes="sleep",
            beak="closed",
            stretch=bp.SLEEP_BREATH[i],
            flips=("front", "front"),
            head=(0, 4),
            view="sit",
            tuck=True,
        )
    if state == "working":
        key = ("key", "key2") if i % 2 else ("key2", "key")
        return _C(eyes="down", beak="closed", flips=key, head=(0, 3 + _PECK[i]), view="sit")
    if state == "searching":
        sweep = bp.SEARCH_SWEEP[i]
        lean = (sweep > 2) - (sweep < -2)
        flips = ("rest", _search_tip(sweep))
        return _C(dx=lean, eyes=bp.SEARCH_EYES[i], beak="closed", flips=flips)
    if state == "held":
        return _C(
            dx=bp.HELD_SWAY[i],
            dy=-2,
            eyes="wide",
            beak="half",
            stretch=1,
            flips=_HELD_FLAP[i],
            view="dangle",
        )
    raise KeyError(state)


# -- Idle acts ----------------------------------------------------------------

ACTS: dict[str, tuple[Cell, ...]] = {
    #: A run-up, a hop, a belly flop and a slide across the floor: wheee.
    "belly_slide": (
        _C(eyes="look_right"),
        _C(dy=1, eyes="look_right", stretch=-1, flips=_HALF, feet=(0, 0)),
        _C(dx=1, dy=-2, eyes="happy", beak="open", stretch=1, flips=_UP, feet=(1, 1)),
        _C(eyes="happy", beak="open", view="prone", slide=17),
        _C(eyes="happy", beak="wide", view="prone", slide=20),
        _C(eyes="happy", beak="open", view="prone", slide=23),
        _C(eyes="open", beak="closed", view="prone", slide=25),
        _C(dx=1, eyes="happy", beak="smile", flips=_HALF),
    ),
    #: A snowball tossed up high that comes straight back down on the head.
    "snowball": (
        _C(eyes="down"),
        _C(eyes="down", beak="closed", flips=("front", "front")),
        _C(dy=-1, eyes="up", beak="closed", stretch=1, flips=_UP),
        _C(eyes="up", beak="half", flips=_HALF),
        _C(eyes="wide", beak="open", flips=_HALF),
        _C(dy=1, eyes="squint", beak="closed", stretch=-1, flips=_OUT, snow=True),
        _C(dx=-1, eyes="closed", beak="half", flips=_HALF, snow=True, fluff=2),
        _C(dx=1, eyes="happy", beak="smile"),
    ),
    #: A fish comes flying in, Pip catches it and gulps it down.
    "fish_snack": (
        _C(eyes="look_left"),
        _C(eyes="up_left", beak="closed", flips=("half", "rest")),
        _C(eyes="up_left", beak="open", stretch=1, flips=_HALF),
        _C(dy=-1, eyes="up", beak="wide", stretch=1, flips=_OUT),
        _C(eyes="happy", beak="fish", flips=_HALF),
        _C(eyes="happy", beak="closed", stretch=1, fluff=2),
        _C(dy=-2, eyes="happy", beak="open", flips=_UP, feet=(1, 1)),
        _C(eyes="happy", beak="smile"),
    ),
    #: Flap, flap, flap: an attempt at flying that ends in a bump.
    "flipper_flap": (
        _C(eyes="up"),
        _C(eyes="wide", beak="closed", flips=_UP),
        _C(dy=-1, eyes="wide", beak="closed", stretch=1, flips=("flap_down", "flap_down")),
        _C(dy=-3, eyes="happy", beak="open", flips=("flap_up", "flap_up"), feet=(1, 1)),
        _C(dy=-4, eyes="happy", beak="open", flips=("flap_down", "flap_down"), feet=(2, 2)),
        _C(dy=-2, eyes="wide", beak="half", flips=_UP, feet=(1, 1)),
        _C(dy=1, eyes="squint", beak="closed", stretch=-1, flips=_OUT),
        _C(eyes="look_right", beak="closed", flips=_HALF),
    ),
    #: A clumsy waddle, a trip and a plop onto its bottom, a little dizzy.
    "tumble": (
        _C(),
        _C(dx=-1, flips=("half", "rest"), head=(-1, 0), feet=(0, 1)),
        _C(dx=1, flips=("rest", "half"), head=(1, 0), feet=(1, 0)),
        _C(dx=2, eyes="wide", beak="half", flips=("up", "out"), head=(2, 0), feet=(0, 2)),
        _C(dy=1, eyes="squint", beak="half", stretch=-1, flips=_OUT, head=(0, 3), view="plop"),
        _C(dy=1, eyes="dizzy", beak="closed", flips=_HALF, head=(0, 3), view="plop"),
        _C(dy=1, eyes="look_left", beak="closed", flips=_HALF, head=(0, 3), view="plop"),
        _C(eyes="happy", beak="smile", flips=_HALF),
    ),
    #: A careful preen of the shoulder fluff, then a big fluffy shake.
    "preen": (
        _C(eyes="look_left"),
        _C(eyes="look_left", beak="closed", flips=("half", "rest"), head=(-1, 1)),
        _C(eyes="closed", beak="closed", flips=("preen", "rest"), head=(-3, 2)),
        _C(eyes="closed", beak="half", flips=("preen", "rest"), head=(-3, 3)),
        _C(eyes="closed", beak="closed", flips=("preen", "rest"), head=(-3, 2)),
        _C(dx=-1, eyes="closed", beak="closed", flips=_HALF, fluff=2),
        _C(dx=1, eyes="happy", beak="smile", flips=_HALF, fluff=2),
        _C(eyes="happy", beak="smile"),
    ),
}


def _cell(pose: Any) -> Cell:
    if pose.act:
        return ACTS[pose.act][pose.i]
    return _state_cell(pose.state, pose.i)


def _pose_of(state: str, i: int, c: Cell, act: str = "") -> Any:
    return bp.Pose(
        state, i, dx=c.dx, dy=c.dy, eyes=c.eyes, mouth=c.beak, stretch=c.stretch, act=act
    )


def pip_pose(state: str, i: int) -> Any:
    return _pose_of(state, i, _state_cell(state, i))


# -- Effects ------------------------------------------------------------------

_SNOWFLAKE = ("#.#", ".o.", "#.#")
_SNOWFLAKE_PALETTE = {"#": ICE, "o": ICE_CORE}
_HEART = ("#.#", "###", ".#.")
_HEART_L = ("##.##", "#o###", "#####", ".###.", "..#..")
_HEART_PALETTE = {"#": HEART, "o": HEART_SHINE}
_FISH = ("#..###.", "##.##e#", ".######", "##.###.", "#..##..")
_FISH_PALETTE = {"#": FISH, "e": EYE}
_STAR = (".#.", "#o#", ".#.")


def _flake(f: Any, x: int, y: int) -> None:
    f.glyph(x - 1, y - 1, _SNOWFLAKE, _SNOWFLAKE_PALETTE)


def _fluff_bit(f: Any, x: int, y: int) -> None:
    if 1 <= x < bp.CELL - 2 and 1 <= y < bp.CELL - 1:
        f.part({(x, y), (x + 1, y)}, DOWN_LIGHT)


def _snow_puff(f: Any, x: float, y: float, r: float) -> None:
    puff = _in_cell(bp.ellipse(x, y, r, r * 0.8))
    if puff:
        f.part(puff, bp.shade(puff, SNOW, dark=SNOW_SHADE, dark_depth=1))


def _talking_fx(f: Any, pose: Any) -> None:
    """Loud cheeps: little lines spring from the beak."""
    if pose.i < 2:
        return
    with f.offset(pose.dx, pose.dy):
        near = {(10, 22), (9, 23), (10, 25), (9, 25)}
        f.paint(near | bp.mirrored(near), bp.ARC)
        if pose.i == 3:
            far = {(7, 20), (6, 21), (7, 26), (6, 27)}
            f.paint(far | bp.mirrored(far), bp.ARC_FADE)


def _success_fx(f: Any, pose: Any) -> None:
    """Sparkles and a flurry of snowflakes around the happy hop."""
    bp.fx_sparkles(f, pose.i, ((6, 12, 1), (41, 7, 3), (5, 27, 4)))
    for x, y, start in ((40, 24, 0), (9, 5, 2), (42, 32, 4)):
        age = pose.i - start
        if 0 <= age <= 3:
            _flake(f, x, y + age)


def _error_fx(f: Any, pose: Any) -> None:
    """A red "!", shiver lines on both sides and a cold little breath cloud."""
    i = pose.i
    bp.fx_bang(f, 41, 3)
    side = (6, 32) if i % 2 else (4, 30)
    lines = bp.line(side[0], side[1], side[0], side[1] + 4)
    lines |= bp.line(side[0] - 2, side[1] + 1, side[0] - 2, side[1] + 3)
    f.paint(lines | bp.mirrored(lines), bp.ARC_FADE)
    if i in (1, 3, 5):
        _snow_puff(f, 38.0 + pose.dx, 25.0, 1.3)
    elif i in (2, 4):
        _snow_puff(f, 40.0 + pose.dx, 23.0, 1.9)
    if i >= 2:
        _flake(f, 7, 12 + i)


def _sleeping_fx(f: Any, pose: Any) -> None:
    """Rising z marks and a sleepy bubble that swells and pops."""
    bp.fx_zzz(f, pose.i, 34, 15)
    i = pose.i
    size = (1.0, 1.6, 2.2, 2.8, 0.0, 0.0)[i]
    if size:
        ring = bp.ellipse(29.5, 28.0, size, size)
        f.paint(ring - bp.eroded(ring), BUBBLE)
        f.paint({(29, 27)} if size > 1.5 else set(), bp.FX_WHITE)
    elif i == 4:
        f.paint({(27, 25), (32, 25), (29, 23), (31, 30)}, BUBBLE)


def _working_fx(f: Any, pose: Any) -> None:
    bp.fx_laptop(f, pose.i, 17, 35)


def _searching_fx(f: Any, pose: Any) -> None:
    """The magnifier held up in front of the eyes, sweeping left and right."""
    with f.offset(pose.dx, 0):
        bp.fx_magnifier(f, pose.i, CX, 19)


def _held_fx(f: Any, pose: Any) -> None:
    with f.offset(pose.dx, pose.dy):
        bp.fx_held(f, pose.i, (8, 21), (39, 21))
        if pose.i % 2 == 0:
            _fluff_bit(f, 3, 30)
            _fluff_bit(f, 43, 27)


def _belly_slide_fx(f: Any, pose: Any) -> None:
    """Speed lines behind the slide and a spray of snow at the front."""
    i = pose.i
    if i == 2:
        f.paint(bp.line(4, 30, 8, 30) | bp.line(5, 33, 8, 33), bp.ARC_FADE)
    if 3 <= i <= 5:
        s = (17, 20, 23)[i - 3]
        tail = s - 16
        for y, n in ((34, 4), (37, 6), (40, 4)):
            if tail - n >= 1:
                f.paint(bp.line(tail - n, y, tail - 1, y), bp.ARC_FADE)
            else:
                f.paint(bp.line(1, y, max(1, tail - 1), y), bp.ARC_FADE)
        f.paint(bp.line(s - 12, 45, s + 16, 45), SNOW_SHADE)
    if i in (5, 6):
        x = 44 if i == 5 else 43
        _snow_puff(f, x, 42.0, 1.8 if i == 5 else 2.4)
        _snow_puff(f, x - 2, 38.0 + (i - 5), 1.2)
        _flake(f, 42, 31 - (i - 5) * 2)
    if i == 7:
        bp.fx_sparkles(f, 1, ((40, 12, 0),))


def _snowball_fx(f: Any, pose: Any) -> None:
    """The snowball: held, tossed up, falling and bursting on the head."""
    i = pose.i
    ball = {1: (24.0, 37.0, 3.2), 2: (24.0, 6.0, 3.0), 3: (24.0, 3.5, 2.4), 4: (24.0, 6.5, 3.0)}
    if i in ball:
        x, y, r = ball[i]
        mask = _in_cell(bp.ellipse(x, y + (pose.dy if i == 1 else 0), r, r))
        f.part(mask, bp.shade(mask, SNOW, dark=SNOW_SHADE, dark_depth=1))
        if i == 3:
            f.paint(bp.line(22, 8, 22, 10) | bp.line(26, 8, 26, 10), bp.ARC_FADE)
    if i == 5:
        for x, y in ((13, 6), (35, 5), (10, 12), (38, 11)):
            _snow_puff(f, x, y, 1.3)
        bp.fx_sparkles(f, 0, ((40, 3, 0),), _SNOWFLAKE_PALETTE)
    if i == 6:
        for x, y in ((8, 10), (40, 9), (6, 18), (42, 17)):
            _snow_puff(f, x, y, 1.0)
        f.paint(bp.line(5, 24, 5, 28) | bp.line(42, 24, 42, 28), bp.ARC_FADE)
    if i == 7:
        _flake(f, 9, 20)
        _flake(f, 39, 16)


def _fish_snack_fx(f: Any, pose: Any) -> None:
    """The fish arcs in from the left; its tail wiggles out of the beak; a heart."""
    i = pose.i
    path = {1: (2, 12), 2: (9, 4), 3: (20, 1)}
    if i in path:
        x, y = path[i]
        f.glyph(x, y, _FISH, _FISH_PALETTE)
        if i == 1:
            f.paint(bp.line(2, 19, 4, 18), bp.ARC_FADE)
    if i == 4:
        f.glyph(26, 23, (".#", "#.", ".#"), {"#": FISH})
    if i == 5:
        f.paint({(17, 27), (31, 27)}, bp.ARC_FADE)
    if i == 6:
        f.glyph(36, 4, _HEART_L, _HEART_PALETTE)
        f.glyph(8, 9, _HEART, _HEART_PALETTE)
    if i == 7:
        f.glyph(38, 2, _HEART, _HEART_PALETTE)


def _flipper_flap_fx(f: Any, pose: Any) -> None:
    """Whoosh lines under the flapping flippers, loose down, a bump on landing."""
    i = pose.i
    if i in (2, 3, 4, 5):
        with f.offset(0, pose.dy):
            f.paint(bp.line(1, 40, 4, 40) | bp.line(2, 42, 4, 42), bp.ARC_FADE)
            f.paint(bp.line(43, 40, 46, 40) | bp.line(43, 42, 45, 42), bp.ARC_FADE)
    if i in (3, 5):
        _fluff_bit(f, 4, 14 + i)
    if i == 4:
        _fluff_bit(f, 41, 15)
    if i == 6:
        for x in (9, 38):
            _snow_puff(f, x, 44.5, 1.6)
        f.paint({(6, 40), (41, 40)}, bp.ARC)
    if i == 7:
        _fluff_bit(f, 6, 30)


def _tumble_fx(f: Any, pose: Any) -> None:
    """A wobble mark, a puff of snow on the plop and stars round the head."""
    i = pose.i
    if i == 3:
        f.paint(bp.line(43, 22, 43, 26) | bp.line(45, 23, 45, 25), bp.ARC)
    if i == 4:
        for x in (7, 40):
            _snow_puff(f, x, 44.0, 2.0)
    if i in (4, 5, 6):
        spots = (((9, 9), (38, 6)), ((14, 5), (34, 9)), ((8, 12), (40, 10)))[i - 4]
        for x, y in spots:
            f.glyph(x - 1, y - 1, _STAR, {"#": bp.SPARK, "o": bp.SPARK_CORE})


def _preen_fx(f: Any, pose: Any) -> None:
    """Loose bits of down float off the shoulder and drift away."""
    i = pose.i
    bits = {
        3: ((10, 22),),
        4: ((8, 19), (12, 24)),
        5: ((6, 15), (11, 21), (38, 22)),
        6: ((5, 12), (40, 18), (9, 27)),
        7: ((4, 10),),
    }
    for x, y in bits.get(i, ()):
        _fluff_bit(f, x, y)
    if i in (5, 6):
        f.paint(bp.line(4, 30, 4, 35) | bp.line(43, 30, 43, 35), bp.ARC_FADE)


ACT_FX: dict[str, tuple[int, Callable[[Any, Any], None]]] = {
    "belly_slide": (9, _belly_slide_fx),
    "snowball": (7, _snowball_fx),
    "fish_snack": (8, _fish_snack_fx),
    "flipper_flap": (10, _flipper_flap_fx),
    "tumble": (8, _tumble_fx),
    "preen": (6, _preen_fx),
}


def _act(name: str) -> Any:
    fps, fx = ACT_FX[name]
    cells = ACTS[name]
    return bp.IdleAct(name, len(cells), fps, lambda i: _pose_of("idle", i, cells[i], name), fx)


# -- The pet ------------------------------------------------------------------


def design(builder: Any) -> Any:
    global bp
    bp = builder
    return bp.PetDesign(
        id="pip",
        name="Pip",
        description=(
            "A penguin chick in grey fluff who waddles to listen and belly-slides "
            "when something goes right."
        ),
        draw=draw_pip,
        pose=pip_pose,
        waist=40,
        anchors=bp.Anchors(
            arcs_left=(8, 19),
            arcs_right=(39, 19),
            dots=(19, 3),
            zzz=(34, 15),
            bang=(41, 3),
            sparkles=((6, 12, 1), (41, 7, 3), (5, 27, 4)),
            laptop=(17, 35),
            magnifier=(CX, 19),
        ),
        fx={
            "talking": _talking_fx,
            "success": _success_fx,
            "error": _error_fx,
            "sleeping": _sleeping_fx,
            "working": _working_fx,
            "searching": _searching_fx,
            "held": _held_fx,
        },
        acts=tuple(_act(name) for name in ACTS),
    )
