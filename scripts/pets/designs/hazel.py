"""Hazel: the red squirrel.

A russet squirrel that sits upright with a cream belly and muzzle, tufted
pointy ears and a huge bushy tail that rises behind her back and curls out at
the top. She is busy, quick and a hoarder, and her tail does most of the
talking: it sways while she idles, stands straight up while she listens,
flicks while she ponders an acorn held to her chin and bottle-brushes out when
something goes wrong. She types next to her stash of acorns, sniffs along
behind the magnifier, tosses an acorn and catches it on a happy hop, sleeps
curled inside her own tail and dangles with the tail swinging when picked up.

Built by ``scripts/pets/build_pets.py``, which passes itself in as ``bp``.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from types import ModuleType
from typing import Any

#: The builder module, set by ``design()`` before anything is drawn.
bp: Any = None

Px = tuple[int, int]
RGBA = tuple[int, int, int, int]
Mask = set[Px]
Frame = Any
Pose = Any


def _hex(value: str) -> RGBA:
    value = value.lstrip("#")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), 255)


# -- Palette ------------------------------------------------------------------

FUR = _hex("#c9572a")
FUR_LIGHT = _hex("#ec8a4c")
FUR_DARK = _hex("#93371a")
TAIL = _hex("#d4652f")
TAIL_LIGHT = _hex("#f6a463")
TAIL_DARK = _hex("#9c3d1b")
#: The darker streak down the middle of the tail: it gives the brush volume.
TAIL_SPINE = _hex("#b24a22")
TUFT = _hex("#6e2812")
TUFT_LIGHT = _hex("#a2441e")
CREAM = _hex("#fbe8cb")
CREAM_DARK = _hex("#e9c79c")
EAR_INNER = _hex("#f0a37e")
NOSE = _hex("#4a2420")
BLUSH = _hex("#ef7f73")
IRIS = _hex("#24161a")
#: A second, dimmer glint low in each eye.
IRIS_GLINT = _hex("#6b5a66")
TOOTH = _hex("#ffffff")
ACORN_CAP = _hex("#7f4f2a")
ACORN_CAP_LIGHT = _hex("#b07a46")
ACORN_NUT = _hex("#d7963f")
ACORN_NUT_LIGHT = _hex("#f6c879")
ACORN_STEM = _hex("#4f2c16")
DIRT = _hex("#9a7452")
DIRT_LIGHT = _hex("#c49c74")
DIRT_DARK = _hex("#6a4c34")
CRUMB = _hex("#e3b06a")

#: Hazel sits a little left of the cell's centre to leave room for the tail;
#: everything symmetric mirrors across the line between columns 21 and 22.
AXIS = 22

#: Eye boxes (top-left) of the left and right eye.
EYE_L: Px = (15, 18)
EYE_R: Px = (26, 18)

_ACORN = ("..s..", ".cCc.", "ccccc", ".lnn.", ".lnn.", "..n..")
_ACORN_S = (".s.", "cCc", "lnn", ".n.")
_ACORN_PALETTE = {
    "s": ACORN_STEM,
    "c": ACORN_CAP,
    "C": ACORN_CAP_LIGHT,
    "n": ACORN_NUT,
    "l": ACORN_NUT_LIGHT,
}
_HEART = ("#.#", "###", ".#.")


# -- Shapes -------------------------------------------------------------------


def _mirror(mask: Mask) -> Mask:
    return bp.mirrored(mask, AXIS)


def _fur(f: Frame, mask: Mask, depth: int = 2) -> None:
    f.part(mask, bp.shade(mask, FUR, light=FUR_LIGHT, dark=FUR_DARK, dark_depth=depth))


def _paw(f: Frame, cx: float, cy: float, rx: float = 1.8, ry: float = 1.6) -> None:
    """A small front paw, a shade lighter than the fur."""
    paw = bp.ellipse(cx, cy, rx, ry)
    f.part(paw, bp.shade(paw, FUR_LIGHT, dark=FUR, dark_depth=1))


def _arm(f: Frame, start: Px, paw: tuple[float, float]) -> None:
    """A thin front leg from the shoulder ``start`` to a paw centred on ``paw``."""
    _fur(f, bp.thick(bp.line(*start, math.floor(paw[0]), math.floor(paw[1]))), 1)
    _paw(f, *paw)


def _acorn(f: Frame, x: int, y: int, *, small: bool = False) -> None:
    """An acorn glyph with its top-left at ``(x, y)``."""
    f.glyph(x, y, _ACORN_S if small else _ACORN, _ACORN_PALETTE)


def _clip(f: Frame) -> None:
    """Drop whatever a prop painted outside the cell."""
    for p in [p for p in f.px if not (0 <= p[0] < bp.CELL and 0 <= p[1] < bp.CELL)]:
        del f.px[p]


# -- The tail -----------------------------------------------------------------

Spine = Sequence[tuple[float, float, float]]


def _brush(spine: Spine) -> tuple[Mask, list[tuple[float, float]]]:
    """A bushy tail: round puffs along ``spine`` (x, y, radius) sampled a
    pixel apart, with locks of fur bulging out of alternate sides every few
    pixels. Also returns the centre line the dark streak follows."""
    mask: Mask = set()
    centre: list[tuple[float, float]] = []
    for (x0, y0, r0), (x1, y1, r1) in zip(spine, spine[1:], strict=False):
        length = math.hypot(x1 - x0, y1 - y0)
        steps = max(1, math.ceil(length))
        nx, ny = (y0 - y1) / (length or 1), (x1 - x0) / (length or 1)
        for k in range(steps + 1):
            t = k / steps
            x, y, r = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, r0 + (r1 - r0) * t
            mask |= bp.ellipse(x, y, r, r)
            centre.append((x, y))
            if len(centre) % 4 == 2 and r >= 3:
                # Round locks of fur bulge out of the edge, alternating sides,
                # so the outline billows like a cloud.
                side = 1 if len(centre) % 8 == 2 else -1
                lx, ly = x + side * nx * (r - 0.2), y + side * ny * (r - 0.2)
                mask |= bp.ellipse(lx, ly, 2.0, 2.0)
    return mask, centre


def _tail(f: Frame, spine: Spine, *, puff: float = 0.0) -> Mask:
    """Paint a tail along ``spine``; ``puff`` widens every puff (a bottle-brush)."""
    if puff:
        spine = [(x, y, r + puff) for x, y, r in spine]
    mask, centre = _brush(spine)
    colors = bp.shade(mask, TAIL, light=TAIL_LIGHT, dark=TAIL_DARK, dark_depth=1)
    # A second light row along the top-left edge: soft, fluffy fur.
    for x, y in bp.eroded(mask):
        if (x - 1, y - 1) not in mask or (x, y - 2) not in mask:
            colors[(x, y)] = TAIL_LIGHT
    # The darker streak down the middle.
    inner = bp.eroded(mask, 2)
    streak = {(math.floor(x + 0.5), math.floor(y)) for x, y in centre[2:-3]}
    for p in streak & inner:
        colors[p] = TAIL_SPINE
    f.part(mask, colors)
    return mask


#: Tail spines, base first. The base tucks in behind the right hip.
_TAIL_REST: Spine = (
    (29, 41, 2.6),
    (35, 39.5, 4.0),
    (38.5, 33, 5.4),
    (39, 25, 5.8),
    (37.5, 17, 5.4),
    (34.5, 11.5, 4.4),
    (30.5, 9.5, 3.0),
)
#: Straight up: alert.
_TAIL_UP: Spine = (
    (30, 41, 3.0),
    (35, 38, 4.0),
    (37, 31, 4.4),
    (37, 23, 4.8),
    (37, 15, 4.6),
    (37.5, 10, 3.8),
    (38, 7, 2.6),
)


def _tail_swayed(sway: float, curl: float = 0.0) -> Spine:
    """The resting tail with its upper half swayed ``sway`` px sideways and the
    tip curled ``curl`` px further down."""
    out = []
    for k, (x, y, r) in enumerate(_TAIL_REST):
        weight = max(0.0, (k - 2) / 4)
        tip = curl if k == len(_TAIL_REST) - 1 else curl / 2 if k == len(_TAIL_REST) - 2 else 0
        out.append((x + sway * weight, y + tip, r))
    return out


def _bristle(f: Frame, i: int, x_min: int) -> None:
    """Puffed-up fur: tufts poke out of the outline right of ``x_min`` and
    tremble from frame to frame."""
    filled = dict(f.px)
    for (x, y), color in filled.items():
        if color != bp.OUTLINE or x < x_min or (2 * x + 3 * y + i) % 5 != 0:
            continue
        for dx, dy in ((1, 0), (0, -1), (-1, 0), (0, 1)):
            tip = (x + dx, y + dy)
            far = (x + 2 * dx, y + 2 * dy)
            if tip in filled or not (0 <= far[0] < bp.CELL and 0 <= far[1] < bp.CELL):
                continue
            if far in filled or filled.get((x - dx, y - dy)) in (None, bp.OUTLINE):
                continue
            fur = TAIL_LIGHT if dy < 0 or dx < 0 else TAIL
            f.px[(x, y)] = fur
            f.px[tip] = fur
            f.px[far] = bp.OUTLINE
            for side in ((dy, dx), (-dy, -dx)):
                beside = (tip[0] + side[0], tip[1] + side[1])
                if beside not in filled:
                    f.px[beside] = bp.OUTLINE
            break


# -- The head -----------------------------------------------------------------

#: Left ear tip per look; the right ear uses the same table, mirrored.
_EAR_TIPS: dict[str, tuple[float, float]] = {
    "rest": (13.0, 6.0),
    "perk": (14.0, 5.0),
    "flick": (10.5, 6.5),
    "back": (9.5, 9.5),
    "flat": (7.5, 13.5),
}


def _ear(f: Frame, look: str, *, tuft: int = 3) -> Mask:
    """One left ear: a pointed triangle with a dark tuft growing off its tip."""
    tx, ty = _EAR_TIPS[look]
    ear = bp.polygon([(11.5, 16.5), (tx, ty), (19.5, 12.0)])
    _fur(f, ear, 1)
    f.paint(bp.eroded(ear, 2), EAR_INNER)
    # The tuft: a little flame of dark fur that leans away from the head.
    x, y = math.floor(tx), math.floor(ty)
    lean = -1 if tx < 12 else 0
    tuft_mask = bp.line(x, y + 1, x + lean, y - tuft + 1) | {(x - 1 + lean, y - tuft + 2)}
    if tuft >= 3:
        tuft_mask |= {(x + 1, y), (x - 1, y - 1)}
    f.part(tuft_mask, {p: TUFT_LIGHT if p[1] == y + 1 else TUFT for p in tuft_mask})
    return ear


def _head(
    f: Frame,
    pose: Pose,
    *,
    cheeks: float = 0.0,
    nose_dy: int = 0,
) -> None:
    """Head and face of the sitting squirrel; ``cheeks`` puffs them out and
    ``nose_dy`` twitches the nose."""
    head = bp.ellipse(AXIS, 20.5, 10.5, 8.5) | bp.ellipse(AXIS, 24, 11 + cheeks, 5 + cheeks / 2)
    _fur(f, head)
    # Cream cheeks and muzzle.
    cheek = bp.ellipse(18.0 - cheeks / 2, 26, 4.2 + cheeks, 3.2 + cheeks / 2)
    muzzle = cheek | _mirror(cheek)
    muzzle = {p for p in muzzle if p in bp.eroded(head)}
    f.paint(muzzle, CREAM)
    f.paint({p for p in muzzle if p[1] >= 29 and (p[0], p[1] + 1) not in muzzle}, CREAM_DARK)
    # A pale rim on the outer side of each eye.
    ring = {(14, 19), (14, 20), (14, 21)}
    f.paint(ring | _mirror(ring), FUR_LIGHT)
    f.paint({(13, 24), (14, 24), (29, 24), (30, 24)}, BLUSH)
    _eyes(f, pose.eyes)
    f.paint(bp.rect(21, 24 + nose_dy, 22, 24 + nose_dy) | {(21, 23 + nose_dy)}, NOSE)
    _mouth(f, pose.mouth)


def _ears(f: Frame, ears: tuple[str, str], tuft: int = 3) -> None:
    """Both ears: the left one as drawn, the right one mirrored from its own look."""
    for side, look in enumerate(ears):
        if side == 0:
            _ear(f, look, tuft=tuft)
        else:
            sub = bp.Frame()
            _ear(sub, look, tuft=tuft)
            f.paint_map({(2 * AXIS - 1 - x, y): c for (x, y), c in sub.px.items()})


#: Big, dark, glossy eyes (an ``EyeStyle``, built in ``design()``).
_EYES: Any = None


def _eyes(f: Frame, style: str) -> None:
    bp.draw_eyes(f, style, EYE_L, EYE_R, _EYES)
    if style in ("open", "wide"):
        # The second glint: bright, wet eyes.
        f.paint({(15, 21), (26, 21)}, IRIS_GLINT)


def _mouth(f: Frame, style: str) -> None:
    """The squirrel mouth: a small split lip under the nose, with buck teeth
    showing whenever it opens."""
    x, y = 20, 26
    if style == "rest":
        f.paint({(20, 26), (21, 25), (22, 25), (23, 26)}, bp.OUTLINE)
        f.paint({(21, 26), (22, 26)}, TOOTH)
    elif style in ("half", "open", "wide"):
        bp.draw_mouth(f, style, x, y, 4)
        f.paint({(21, y + 1), (22, y + 1)}, TOOTH)
    elif style == "nibble":
        f.paint(bp.rect(20, 26, 23, 27), bp.MOUTH_DARK)
        f.paint(bp.rect(20, 26, 23, 26), bp.OUTLINE)
        f.paint({(21, 27), (22, 27)}, TOOTH)
    elif style == "lick":
        bp.draw_mouth(f, "smile", x, y, 4)
        f.paint({(21, 28), (22, 28), (22, 29)}, bp.TONGUE)
    elif style == "puff":
        f.paint(bp.rect(21, 27, 22, 27), bp.OUTLINE)
    else:
        bp.draw_mouth(f, style, x, y, 4)


# -- Poses --------------------------------------------------------------------

#: Idle: the tail's slow sway over the seven breathing cells.
_IDLE_SWAY = (0, 0, 1, 2, 2, 1, 0)
#: Listening: the ears take turns twitching forward.
_LISTEN_EARS = (
    ("perk", "perk"),
    ("perk", "rest"),
    ("perk", "perk"),
    ("rest", "perk"),
    ("perk", "perk"),
    ("perk", "perk"),
)
#: Thinking: the tail tip flicks (sway, curl) while she ponders.
_THINK_FLICK = ((0, 0), (2, -1), (0, 0), (-1, 1), (0, 0), (2, -1), (0, 0), (-1, 1))
#: Success: where the tossed acorn's top-left is per frame (None while in the paws).
_TOSS = (None, (7, 17), (4, 6), (5, 2), (8, 9), None, None, None)
#: Working: which paw presses a key (left, right), then a pause.
_TYPE = (
    (True, False),
    (False, True),
    (True, False),
    (False, False),
    (False, True),
    (True, False),
    (False, True),
    (False, False),
)
#: Held: the swing from the cursor.
_SWAY = (-1, 0, 1, 1, 0, -1)
_SHAKE = (-2, 2, -2, 2, -1, 0)


def hazel_pose(state: str, i: int) -> Pose:
    pose = bp.base_pose(state, i)
    if state == "idle" and i == 5:
        return bp.replace(pose, mouth="rest")
    if state == "thinking":
        return bp.replace(pose, mouth="closed")
    if state == "error":
        return bp.Pose(state, i, dx=_SHAKE[i], eyes="wide", mouth="half")
    if state == "held":
        return bp.Pose(state, i, dx=_SWAY[i % len(_SWAY)], eyes="wide", mouth="half")
    return pose


# -- The sitting squirrel -----------------------------------------------------

#: The shoulders front legs grow from (left, right).
_SHOULDERS: tuple[Px, Px] = ((17, 33), (26, 33))


def _sit(
    f: Frame,
    pose: Pose,
    *,
    ears: tuple[str, str] = ("rest", "rest"),
    tail: Spine | None = None,
    puff: float = 0.0,
    paws: str = "chest",
    tuft: int = 3,
    cheeks: float = 0.0,
    head_dx: int = 0,
    nose_dy: int = 0,
) -> None:
    """The sitting squirrel every upright state draws: tail, body, hind feet,
    the head and the front paws (``"chest"`` held together under the chin,
    ``"none"`` when the caller draws them)."""
    _tail(f, _TAIL_REST if tail is None else tail, puff=puff)
    body = bp.ellipse(AXIS, 37, 8.5, 7)
    _fur(f, body)
    f.paint(bp.ellipse(AXIS, 38.5, 4.8, 4.6), CREAM)
    for cx in (15.5, 28.5):
        foot = bp.ellipse(cx, 43.2, 3.4, 1.8)
        f.part(foot, bp.shade(foot, FUR, light=FUR_LIGHT, dark=FUR_DARK, dark_depth=1))
    with f.offset(head_dx, 0):
        _ears(f, ears, tuft)
        _head(f, pose, cheeks=cheeks, nose_dy=nose_dy)
    if paws == "chest":
        _paw(f, 19.5, 32.5)
        _paw(f, 24.5, 32.5)


def draw_hazel(f: Frame, pose: Pose) -> None:
    """The pet's ``draw``: the body for the pose, kept inside the cell."""
    _draw_body(f, pose)
    _seal(f)


def _seal(f: Frame) -> None:
    """Keep a hop or a puffed tail inside the cell: drop whatever pokes out and
    close the silhouette with the outline along the cell's edge."""
    last = bp.CELL - 1
    for p in [p for p in f.px if not (0 <= p[0] <= last and 0 <= p[1] <= last)]:
        del f.px[p]
    for (x, y), color in list(f.px.items()):
        if color != bp.OUTLINE and (x in (0, last) or y in (0, last)):
            f.px[(x, y)] = bp.OUTLINE


def _draw_body(f: Frame, pose: Pose) -> None:
    if pose.act:
        _ACT_BODIES[pose.act](f, pose)
    elif pose.state == "sleeping":
        _draw_curled(f, pose)
    elif pose.state == "held":
        _draw_dangling(f, pose)
    else:
        with f.offset(pose.dx, pose.dy):
            _draw_sitting(f, pose)
        if pose.state == "error":
            _bristle(f, pose.i, 30 + pose.dx)


def _draw_sitting(f: Frame, pose: Pose) -> None:
    state, i = pose.state, pose.i
    if state == "idle":
        if i >= len(_IDLE_SWAY):
            _sit(f, pose, ears=("flick", "rest"), tail=_tail_swayed(-1, 1))
        else:
            _sit(f, pose, tail=_tail_swayed(_IDLE_SWAY[i]), nose_dy=-1 if i == 5 else 0)
    elif state == "listening":
        lift = (0, 1, 1, 0, 1, 0)[i % 6]
        tail = [(x, y - (lift if k > 2 else 0), r) for k, (x, y, r) in enumerate(_TAIL_UP)]
        _sit(f, pose, ears=_LISTEN_EARS[i % 6], tail=tail, tuft=4)
    elif state == "thinking":
        sway, curl = _THINK_FLICK[i % 8]
        _sit(f, pose, tail=_tail_swayed(sway, curl), paws="none")
        # Both paws hold an acorn to the chin; it taps on every other beat.
        tap = 1 if i % 4 in (1, 2) else 0
        _paw(f, 17.5, 31.5 + tap)
        _paw(f, 26.5, 31.5 + tap)
        _acorn(f, 20, 28 + tap)
    elif state == "talking":
        ears = ("rest", "rest") if i < 3 else ("perk", "perk")
        _sit(f, pose, ears=ears, tail=_tail_swayed((0, 1, 1, 2)[i % 4]))
    elif state == "success":
        up = _TOSS[i] is not None
        ears = ("perk", "perk") if pose.dy >= -1 else ("back", "back")
        _sit(
            f,
            pose,
            ears=ears,
            tail=_tail_swayed(-1 if up else 1, -1),
            paws="none" if up else "chest",
        )
        if up:
            # Hooray: both paws up after the acorn.
            _arm(f, _SHOULDERS[0], (11.5, 27))
            _arm(f, _SHOULDERS[1], (32.5, 27))
        else:
            # Caught: back in both paws.
            _paw(f, 17.5, 31.5)
            _paw(f, 26.5, 31.5)
            _acorn(f, 20, 28)
    elif state == "error":
        _sit(f, pose, ears=("flat", "flat"), tail=_tail_swayed(-3, -1), puff=1.0)
    elif state == "working":
        sway = (0, 1, 1, 0, -1, -1, 0, 0)[i % 8]
        glow = any(_TYPE[i % 8])
        _sit(
            f,
            pose,
            tail=_tail_swayed(sway),
            paws="none",
            ears=("rest", "flick") if i in (3, 4) else ("rest", "rest"),
        )
        if glow:
            f.paint({(19, 29), (20, 29), (21, 29), (22, 29), (23, 29), (24, 29)}, bp.SCREEN_GLOW)
    elif state == "searching":
        look = bp.SEARCH_SWEEP[i % 8]
        lean = (look > 2) - (look < -2)
        _sit(
            f, pose, ears=("perk", "perk"), tail=_tail_swayed(-lean), head_dx=lean, nose_dy=-(i % 2)
        )
    else:
        _sit(f, pose)


# -- Sleeping and held --------------------------------------------------------


def _draw_curled(f: Frame, pose: Pose) -> None:
    """Asleep: curled in a ball with the head on the paws, the big tail wrapped
    up over the back like a blanket, its tip twitching in a dream."""
    i = pose.i
    with f.offset(pose.dx, pose.dy):
        body = bp.ellipse(26, 38.5, 11, 6)
        _fur(f, body)
        twitch = (0, 0, 1, 1, 0, 0)[i % 6]
        _tail(
            f,
            (
                (35, 42.5, 3.0),
                (39.5, 37, 4.4),
                (38, 30.5, 5.2),
                (31, 27, 5.2),
                (24, 27.5, 4.4),
                (20.5 - twitch, 30.5, 3.0),
            ),
        )
        for ear in (
            bp.polygon([(9.5, 34.5), (10.5, 27.5), (15.5, 31.5)]),
            bp.polygon([(17.5, 31.5), (21.5, 27.5), (22.0, 34.0)]),
        ):
            _fur(f, ear, 1)
            f.paint(bp.eroded(ear, 2), EAR_INNER)
        head = bp.ellipse(16, 38, 8, 6) | bp.ellipse(16, 40.5, 8.5, 3.5)
        _fur(f, head)
        cheek = bp.ellipse(12.5, 41.5, 3, 2) | bp.ellipse(19.5, 41.5, 3, 2)
        f.paint(cheek & bp.eroded(head), CREAM)
        bp.draw_eye(f, "sleep", 10, 37, _EYES, right=False)
        bp.draw_eye(f, "sleep", 19, 37, _EYES, right=True)
        f.paint({(15, 40), (16, 40), (15, 39)}, NOSE)
        f.paint({(8, 40), (23, 40)}, BLUSH)
        _paw(f, 12.0, 44.5, 2.0, 1.2)
        _paw(f, 19.0, 44.5, 2.0, 1.2)


def _draw_dangling(f: Frame, pose: Pose) -> None:
    """Held: hanging by the scruff, legs dangling and the tail swinging behind."""
    lag = -pose.dx
    with f.offset(pose.dx, 0):
        _tail(
            f,
            (
                (26, 38, 2.8),
                (30 + lag, 41.5, 3.6),
                (35 + 2 * lag, 40, 4.0),
                (37 + 3 * lag, 34, 4.0),
                (36 + 3 * lag, 28, 3.4),
                (34 + 3 * lag, 24, 2.6),
            ),
        )
        for x in (18, 25):
            _fur(f, bp.thick(bp.line(x, 38, x + lag, 42)), 1)
            foot = bp.ellipse(x + 1 + lag, 44, 2.2, 1.6)
            f.part(foot, bp.shade(foot, FUR, light=FUR_LIGHT, dark=FUR_DARK, dark_depth=1))
        body = bp.ellipse(AXIS, 32, 6.5, 8)
        _fur(f, body)
        f.paint(bp.ellipse(AXIS, 33.5, 3.6, 5), CREAM)
        for x, end in ((17, 14), (26, 29)):
            _fur(f, bp.thick(bp.line(x, 28, end + lag, 33)), 1)
            _paw(f, end + 1 + lag, 34.5)
        with f.offset(0, -3):
            tuft = bp.polygon([(19.5, 13.5), (22.0, 8.5), (24.5, 13.5)])
            _fur(f, tuft, 1)
            _ears(f, ("back", "back"), 2)
            _head(f, pose)


# -- Idle acts: bodies --------------------------------------------------------


def _draw_toss(f: Frame, pose: Pose) -> None:
    """Acorn toss: flicked up past the left ear, eyes on it, caught again."""
    i = pose.i
    with f.offset(pose.dx, pose.dy):
        _sit(
            f,
            pose,
            tail=_tail_swayed((0, 0, -1, -1, 0, 1, 1, 0)[i]),
            paws="none",
            ears=("perk", "perk") if 1 <= i <= 5 else ("rest", "rest"),
        )
        if 2 <= i <= 4:
            # The left paw follows the acorn up; the right stays at the chest.
            _arm(f, _SHOULDERS[0], (11.5, (27, 25, 28)[i - 2]))
            _paw(f, 24.5, 32.5)
        else:
            lift = 2 if i == 1 else 0
            _paw(f, 17.5, 31.5 - lift)
            _paw(f, 26.5, 31.5 - lift)
            if i != 1:
                _acorn(f, 20, 28)
            else:
                _acorn(f, 18, 25)


#: Tail grooming: how far round the front the tail has come (0 behind, 1 halfway, 2 in front).
_GROOM = (0, 1, 2, 2, 2, 2, 1, 0)


def _draw_groom(f: Frame, pose: Pose) -> None:
    """Tail grooming: the tail hugged round the front and combed with both paws."""
    i = pose.i
    reach = _GROOM[i]
    with f.offset(pose.dx, pose.dy):
        if reach == 0:
            _sit(f, pose)
            return
        if reach == 1:
            _sit(f, pose, tail=_tail_swayed(-4, 2))
            return
        _sit(f, pose, tail=((30, 41, 3.0), (34, 40, 3.4)), paws="none", head_dx=-1)
        comb = (0, 0, 0, 1, 0, 1, 0, 0)[i]
        _tail(
            f,
            (
                (31, 42, 2.8),
                (25, 43, 3.4),
                (18, 41.5, 3.8),
                (13.5, 37.5, 3.8),
                (12, 33 + comb, 3.2),
                (13.5, 29.5 + comb, 2.4),
            ),
        )
        _paw(f, 16.5, 34.5 + comb)
        _paw(f, 20.5, 38.0 - comb)


#: Burying a nut: how far the whole squirrel leans to the left per frame.
_BURY_LEAN = (0, -1, -3, -3, -3, -3, -1, 0)
#: The digging paws' heights per frame (None: paws at the chest).
_BURY_DIG: tuple[tuple[float, float] | None, ...] = (
    None,
    None,
    (42.5, 40.5),
    (40.5, 42.5),
    (42.5, 42.5),
    (41.5, 43.0),
    (43.0, 41.5),
    None,
)


def _draw_bury(f: Frame, pose: Pose) -> None:
    """Burying a nut: lean over, dig, drop the acorn in, pat the earth down."""
    i = pose.i
    dig = _BURY_DIG[i]
    with f.offset(pose.dx + _BURY_LEAN[i], pose.dy):
        _sit(
            f,
            pose,
            tail=_tail_swayed((0, 1, 2, 2, 1, 2, 1, 0)[i]),
            paws="none",
            nose_dy=-1 if i == 1 else 0,
        )
        if dig is None:
            _paw(f, 17.5, 31.5)
            _paw(f, 26.5, 31.5)
            if i in (0, 1):
                _acorn(f, 20, 28)
        else:
            _paw(f, 16.5, dig[0], 2.2, 1.5)
            _paw(f, 21.5, dig[1], 2.2, 1.5)


#: Cheek stuffing: how far the cheeks are puffed out per frame.
_CHEEKS = (0.0, 0.0, 0.0, 0.8, 1.4, 1.8, 1.8, 1.0)
_CHEEK_PAWS = (31.5, 30.0, 28.5, 31.0, 31.5, 31.5, 31.5, 31.5)


def _draw_cheek_stuff(f: Frame, pose: Pose) -> None:
    """Cheek stuffing: one more acorn in, and the cheeks balloon out."""
    i = pose.i
    with f.offset(pose.dx, pose.dy):
        _sit(
            f,
            pose,
            cheeks=_CHEEKS[i],
            paws="none",
            ears=("perk", "perk") if i >= 5 else ("rest", "rest"),
        )
        _paw(f, 17.5, _CHEEK_PAWS[i])
        _paw(f, 26.5, _CHEEK_PAWS[i])
        if i <= 2:
            _acorn(f, 20, (28, 26, 25)[i])


#: Nibbling: the pixels bitten out of the acorn per frame.
_BITES: tuple[frozenset[Px], ...] = (
    frozenset(),
    frozenset(),
    frozenset({(23, 31)}),
    frozenset({(23, 31)}),
    frozenset({(23, 31), (23, 30)}),
    frozenset({(23, 31), (23, 30), (21, 31)}),
)


def _draw_nibble(f: Frame, pose: Pose) -> None:
    """Nibbling: the acorn turned in both paws at the mouth, bitten smaller."""
    i = pose.i
    with f.offset(pose.dx, pose.dy):
        _sit(f, pose, paws="none")
        if i <= 5:
            jig = (0, 0, 1, 0, 1, 0)[i]
            _paw(f, 17.5, 31.0 + jig)
            _paw(f, 26.5, 31.0 + jig)
            _acorn(f, 20, 27 + jig)
            # Bites out of the nut: it gets smaller as she nibbles.
            f.paint({(x, y + jig) for x, y in _BITES[i]}, bp.OUTLINE)
        else:
            _paw(f, 19.5, 32.5)
            _paw(f, 24.5, 32.5)


#: Ear scratch: the paw's height at the ear per frame (None: paws at the chest).
_SCRATCH = (None, 21.0, 15.0, 13.0, 15.0, 13.0, 21.0, None)


def _draw_ear_scratch(f: Frame, pose: Pose) -> None:
    """A quick scratch behind the left ear, the arm reaching round the cheek."""
    i = pose.i
    height = _SCRATCH[i]
    ears = ("flick", "rest") if i in (3, 5) else ("rest", "rest")
    with f.offset(pose.dx, pose.dy):
        _sit(
            f,
            pose,
            ears=ears,
            paws="none" if height else "chest",
            tail=_tail_swayed((0, 1, 2, 1, 2, 1, 1, 0)[i]),
            head_dx=1 if height and height < 20 else 0,
        )
        if height:
            arm = bp.thick(bp.polyline([(15, 33), (10, 27), (10, math.floor(height) + 2)]))
            _fur(f, arm, 1)
            _paw(f, 11.5, height)
            _paw(f, 24.5, 32.5)


# -- Effects ------------------------------------------------------------------


def _success_fx(f: Frame, pose: Pose) -> None:
    """The acorn flies up off the paws, spins at the top and is caught again,
    sparkles pop around the catch."""
    spot = _TOSS[pose.i]
    if spot is not None:
        x, y = spot
        if pose.i in (2, 3):
            # Spinning at the top: the acorn upside down.
            f.glyph(x, y, tuple(reversed(_ACORN)), _ACORN_PALETTE)
        else:
            _acorn(f, x, y)
    bp.fx_sparkles(f, pose.i, ((41, 5, 4), (5, 27, 5), (8, 9, 6), (42, 24, 6)))


def _working_fx(f: Frame, pose: Pose) -> None:
    """A laptop beside her stash of acorns; paws hammer the keys."""
    i = pose.i
    x, y = 15, 34
    bp.fx_laptop(f, i, x, y)
    pressed = _TYPE[i % 8]
    for down, cx, side in ((pressed[0], 13.0, -1), (pressed[1], 30.0, 1)):
        if down:
            _paw(f, cx, 41.0, 2.4, 1.3)
            tx = math.floor(cx) + side * 3
            f.paint({(tx, 38), (tx + side, 37)}, bp.ARC)
        else:
            _paw(f, cx, 37.5 + pose.dy)
    # The stash: a little pile of acorns on the left, the top one wobbling.
    _acorn(f, 1, 40, small=True)
    _acorn(f, 5, 41, small=True)
    _acorn(f, 3 + (1 if i % 4 == 2 else 0), 37, small=True)


def _searching_fx(f: Frame, pose: Pose) -> None:
    """The magnifier sweeps across, and sniff puffs come off the nose."""
    bp.fx_magnifier(f, pose.i, *ANCHORS.magnifier)
    if pose.i % 2:
        f.paint({(17, 24), (16, 23), (27, 24), (28, 23)}, bp.ARC_FADE)


def _toss_fx(f: Frame, pose: Pose) -> None:
    """The acorn's flight past the left ear, flipping over at the top."""
    spot = (None, None, (7, 15), (5, 3), (8, 13), None, None, None)[pose.i]
    if spot is not None:
        f.glyph(*spot, _ACORN if pose.i != 3 else tuple(reversed(_ACORN)), _ACORN_PALETTE)
    if pose.i == 5:
        bp.fx_sparkles(f, 1, ((33, 24, 0),))


def _groom_fx(f: Frame, pose: Pose) -> None:
    """Sparkles off the freshly combed tail tip."""
    if pose.i in (3, 5):
        bp.fx_sparkles(f, 0, ((8, 24, 0),))
    elif pose.i == 4:
        bp.fx_sparkles(f, 1, ((7, 22, 0),))


#: The dirt mound per frame (0 none, 1 a little, 2 a pile) and flying dirt.
_MOUND = (0, 0, 1, 2, 2, 2, 1, 1)


def _bury_fx(f: Frame, pose: Pose) -> None:
    """The dirt mound, flying earth, the acorn going in and a pleased heart."""
    i = pose.i
    size = _MOUND[i]
    if size:
        mound = bp.ellipse(7, 45.5, 3 + 1.2 * size, 1.0 + 1.2 * size)
        mound = {p for p in mound if p[1] <= 45}
        f.part(mound, bp.shade(mound, DIRT, light=DIRT_LIGHT, dark=DIRT_DARK, dark_depth=1))
    if i in (2, 3):
        # Dirt flies up behind the digging paw.
        for p in (((4, 38), (2, 35), (7, 36)), ((3, 34), (6, 32), (1, 38)))[i - 2]:
            f.part({p}, DIRT)
    if i == 4:
        _acorn(f, 6, 36, small=True)  # into the hole it goes
    if i == 7:
        f.glyph(4, 37, _HEART, {"#": BLUSH})
    _clip(f)


def _cheek_fx(f: Frame, pose: Pose) -> None:
    """A heart floats up from the full cheeks."""
    if pose.i == 6:
        f.glyph(33, 14, _HEART, {"#": BLUSH})
    elif pose.i == 7:
        f.glyph(34, 11, _HEART, {"#": BLUSH})


def _nibble_fx(f: Frame, pose: Pose) -> None:
    """Crumbs and bits of shell fall from the busy teeth."""
    i = pose.i
    if 1 <= i <= 6:
        falls = (
            ((18, 33),),
            ((25, 34), (17, 36)),
            ((19, 35), (26, 38)),
            ((16, 37), (24, 36)),
            ((27, 40), (18, 39)),
            ((16, 42),),
        )[i - 1]
        f.part(set(falls), CRUMB)
    if i == 7:
        f.paint({(25, 44), (17, 45), (27, 45)}, CRUMB)


def _scratch_fx(f: Frame, pose: Pose) -> None:
    """Scratch marks twitching beside the ear."""
    if pose.i in (2, 3, 4, 5):
        f.paint({(8, 9 + pose.i % 2), (7, 12 + pose.i % 2)}, bp.ARC_FADE)


#: Effect anchors (an ``Anchors``, built in ``design()``).
ANCHORS: Any = None


def _act(
    name: str, eyes: Sequence[str], mouth: Sequence[str], fx: Callable | None, fps: int = 8
) -> Any:
    """An eight-frame idle act; its body is drawn by ``_ACT_BODIES[name]``."""
    return bp.IdleAct(
        name,
        8,
        fps,
        lambda i: bp.Pose("idle", i, eyes=eyes[i], mouth=mouth[i]),
        fx,
    )


_ACT_BODIES: dict[str, Callable[[Frame, Pose], None]] = {
    "acorn_toss": _draw_toss,
    "tail_groom": _draw_groom,
    "bury_nut": _draw_bury,
    "cheek_stuff": _draw_cheek_stuff,
    "nibble": _draw_nibble,
    "ear_scratch": _draw_ear_scratch,
}


def design(module: ModuleType) -> Any:
    """Build Hazel with the builder's helpers (``module`` is ``build_pets``)."""
    global bp, _EYES, ANCHORS
    bp = module
    _EYES = bp.EyeStyle(w=3, h=5, iris=IRIS, glint=bp.FX_WHITE, lid=bp.OUTLINE)
    ANCHORS = bp.Anchors(
        arcs_left=(9, 14),
        arcs_right=(34, 14),
        dots=(16, 3),
        zzz=(36, 18),
        bang=(4, 2),
        sweat=(7, 15),
        sparkles=((5, 12, 1), (40, 6, 2), (5, 32, 3), (42, 30, 3)),
        laptop=(15, 34),
        magnifier=(22, 27),
    )
    acts = (
        _act(
            "acorn_toss",
            ("open", "up_left", "up_left", "up_left", "up_left", "open", "happy", "open"),
            ("rest", "rest", "half", "open", "half", "rest", "smile", "rest"),
            _toss_fx,
        ),
        _act(
            "tail_groom",
            ("open", "look_left", "down", "closed", "closed", "closed", "happy", "open"),
            ("rest", "rest", "closed", "lick", "closed", "lick", "smile", "rest"),
            _groom_fx,
        ),
        _act(
            "bury_nut",
            ("open", "look_left", "down", "down", "down", "down", "happy", "happy"),
            ("rest", "rest", "closed", "closed", "half", "closed", "smile", "smile"),
            _bury_fx,
        ),
        _act(
            "cheek_stuff",
            ("open", "open", "happy", "happy", "wide", "happy", "happy", "open"),
            ("rest", "half", "nibble", "puff", "puff", "puff", "puff", "rest"),
            _cheek_fx,
        ),
        _act(
            "nibble",
            ("open", "down", "down", "down", "down", "down", "happy", "open"),
            ("rest", "nibble", "closed", "nibble", "closed", "nibble", "smile", "rest"),
            _nibble_fx,
            fps=10,
        ),
        _act(
            "ear_scratch",
            ("open", "closed", "happy", "happy", "happy", "happy", "closed", "open"),
            ("rest", "rest", "smile", "smile", "smile", "smile", "rest", "rest"),
            _scratch_fx,
        ),
    )
    return bp.PetDesign(
        id="hazel",
        name="Hazel",
        description="A red squirrel who perks her tufted ears to listen and naps inside her tail.",
        draw=draw_hazel,
        pose=hazel_pose,
        anchors=ANCHORS,
        waist=36,
        fx={
            "success": _success_fx,
            "working": _working_fx,
            "searching": _searching_fx,
        },
        acts=acts,
    )
