"""Otto: the sea otter.

A round little sea otter sitting upright: warm brown fur, a pale cream face
with whiskers and a dark button nose, small round ears, short arms with
webbed paws held together on the chest, big webbed hind feet and a thick
flat tail. Relaxed and playful. It cracks a clam on its belly with a pebble
while it thinks, does a backflip with a shell when something works, drops
the shell in fright on an error, and naps floating on its back with its
paws over its eyes. The idle acts are otter habits: cracking a clam,
rolling over, juggling a pebble, washing its whiskers, floating on its back
and slapping the water with its tail.

Built by ``scripts/pets/build_pets.py``: ``design(bp)`` gets that module and
everything here draws with its helpers, so Otto shares the outline, the
shading pass and the effect conventions of the other pets.
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Any, NamedTuple

#: The builder module (``scripts/pets/build_pets.py``), set by ``design``.
bp: Any = None

Px = tuple[int, int]
RGBA = tuple[int, int, int, int]
FPx = tuple[float, float]


def _rgb(value: str) -> RGBA:
    value = value.lstrip("#")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), 255)


CX = 24

OTTO_FUR = _rgb("#9a6440")
OTTO_LIGHT = _rgb("#c08455")
OTTO_SHINE = _rgb("#d49a68")
OTTO_DARK = _rgb("#6b4029")
OTTO_DEEP = _rgb("#4a2a1a")
OTTO_BELLY = _rgb("#b98457")
OTTO_CREAM = _rgb("#f3e3c6")
OTTO_CREAM_DARK = _rgb("#dcc29c")
OTTO_PAD = _rgb("#fbf2e2")
OTTO_EAR_IN = _rgb("#5a3220")
OTTO_NOSE = _rgb("#2a1a16")
OTTO_NOSE_SHINE = _rgb("#8f7a74")
OTTO_EYE = _rgb("#21161a")
OTTO_BLUSH = _rgb("#ec9a94")
OTTO_WHISKER = _rgb("#8a6a52")
OTTO_WHISKER_TIP = _rgb("#c9b8a2")
#: A clam: a cool lavender-blue that holds on dark AND light desktops.
OTTO_CLAM = _rgb("#9fb0dc")
OTTO_CLAM_LIGHT = _rgb("#dbe3f7")
OTTO_CLAM_DARK = _rgb("#6a78b0")
OTTO_CLAM_MEAT = _rgb("#ffb7a1")
OTTO_PEBBLE = _rgb("#8e8b98")
OTTO_PEBBLE_LIGHT = _rgb("#c4c1cc")
OTTO_WATER = _rgb("#3f9ad8")
OTTO_WATER_LIGHT = _rgb("#8fd0f4")
OTTO_WATER_DARK = _rgb("#2a6aa8")

_CLAM = (
    "..lll..",
    ".l#l#l.",
    "l#d#d#l",
    "#d#d#d#",
    ".##d##.",
    "..ddd..",
)
_CLAM_OPEN = (
    "..lll..",
    ".l#l#l.",
    "#d#d#d#",
    ".mmmmm.",
    "#d#d#d#",
    ".##d##.",
)
_PEBBLE = (".l#.", "l###", ".##.")
_BUBBLE = (".#.", "#o#", ".#.")
_DRIP = (".#", "##")


def _clam_palette() -> dict[str, RGBA]:
    return {
        "#": OTTO_CLAM,
        "l": OTTO_CLAM_LIGHT,
        "d": OTTO_CLAM_DARK,
        "m": OTTO_CLAM_MEAT,
    }


def _pebble_palette() -> dict[str, RGBA]:
    return {"#": OTTO_PEBBLE, "l": OTTO_PEBBLE_LIGHT}


def _water_palette() -> dict[str, RGBA]:
    return {"#": OTTO_WATER_LIGHT, "o": bp.FX_WHITE}


# ---------------------------------------------------------------------------
# Small helpers.
# ---------------------------------------------------------------------------


def _in_cell(mask: set[Px], margin: int = 1) -> set[Px]:
    """``mask`` clipped so that it AND its outline stay inside the cell."""
    hi = bp.CELL - margin
    return {(x, y) for x, y in mask if margin <= x < hi and margin <= y < hi}


def _fur(f: Any, mask: set[Px], depth: int = 2) -> None:
    f.part(mask, bp.shade(mask, OTTO_FUR, light=OTTO_LIGHT, dark=OTTO_DARK, dark_depth=depth))


def _limb(start: Px, end: Px) -> set[Px]:
    """A short otter arm or leg, three pixels wide."""
    return bp.thick(bp.thick(bp.line(*start, *end)))


def _paw(
    f: Any, cx: float, cy: float, rx: float = 2.4, ry: float = 2.0, *, toes_down: bool = False
) -> None:
    """A small webbed front paw with two toe creases, along its top edge (a
    raised paw) or its bottom edge (a paw resting on the belly)."""
    paw = bp.ellipse(cx, cy, rx, ry)
    _fur(f, paw, 1)
    edge = max(y for _x, y in paw) if toes_down else min(y for _x, y in paw) + 1
    x = math.floor(cx)
    f.paint({(x - 1, edge), (x + 1, edge)} & paw, OTTO_DARK)


def _clam(f: Any, x: int, y: int, *, open_: bool = False) -> None:
    f.glyph(x, y, _CLAM_OPEN if open_ else _CLAM, _clam_palette())


def _pebble(f: Any, x: int, y: int) -> None:
    f.glyph(x, y, _PEBBLE, _pebble_palette())


def _tail_mask(root: FPx, ctrl: FPx, tip: FPx, r0: float = 3.0, r1: float = 1.6) -> set[Px]:
    """The thick flat otter tail: round blobs along a curve, tapering to the tip."""
    mask: set[Px] = set()
    steps = 8
    for k in range(steps + 1):
        t = k / steps
        x = (1 - t) ** 2 * root[0] + 2 * (1 - t) * t * ctrl[0] + t * t * tip[0]
        y = (1 - t) ** 2 * root[1] + 2 * (1 - t) * t * ctrl[1] + t * t * tip[1]
        r = r0 + (r1 - r0) * t
        mask |= bp.ellipse(x, y, r, r * 0.85)
    return _in_cell(mask)


def _tail(f: Any, root: FPx, ctrl: FPx, tip: FPx, r0: float = 3.0) -> None:
    tail = _tail_mask(root, ctrl, tip, r0)
    _fur(f, tail, 1)
    # A darker stripe along the middle: the tail is flat and thick.
    mid = {
        (
            math.floor(root[0] + (tip[0] - root[0]) * t),
            math.floor(ctrl[1] - 1 + (tip[1] - ctrl[1]) * t),
        )
        for t in (0.55, 0.7)
    }
    f.paint(mid & tail, OTTO_DARK)


def _water(f: Any, mask: set[Px]) -> None:
    """Water with a lit surface row and a darker bottom edge."""
    mask = _in_cell(mask)
    f.part(mask, bp.shade(mask, OTTO_WATER, light=OTTO_WATER_LIGHT, dark=OTTO_WATER_DARK))


def _transform(f: Any, sub: Any, fn: Any, offset: Px = (0, 0)) -> None:
    """Lay ``sub`` onto ``f`` with every pixel moved by ``fn`` and ``offset``,
    clipped to the cell."""
    out: dict[Px, RGBA] = {}
    for (x, y), color in sub.px.items():
        nx, ny = fn(x, y)
        nx, ny = nx + offset[0], ny + offset[1]
        if 0 <= nx < bp.CELL and 0 <= ny < bp.CELL:
            out[(nx, ny)] = color
    f.paint_map(out)


def _rot90(k: int, ox: int, oy: int) -> Any:
    """Turn a pixel ``k`` quarter turns clockwise about the corner point ``(ox, oy)``."""

    def fn(x: int, y: int) -> Px:
        for _ in range(k % 4):
            x, y = ox + oy - y - 1, oy - ox + x
        return x, y

    return fn


def _squash(k: float, oy: int) -> Any:
    """Squash rows towards the line ``oy`` by ``k``."""

    def fn(x: int, y: int) -> Px:
        return x, oy + math.floor((y + 0.5 - oy) * k)

    return fn


# ---------------------------------------------------------------------------
# The face.
# ---------------------------------------------------------------------------

#: The top-left of each 4 x 5 eye box.
_EYE_AT: tuple[Px, Px] = ((16, 14), (28, 14))
_LOOK: dict[str, Px] = {
    "open": (0, 0),
    "wide": (0, 0),
    "look_left": (-1, 0),
    "look_right": (1, 0),
    "up_left": (-1, -1),
    "up_right": (1, -1),
    "down": (0, 1),
}
#: Closed-eye shapes on the 4 x 5 eye box (the right eye is mirrored).
_LIDS: dict[str, tuple[str, ...]] = {
    "closed": ("....", "....", "#..#", ".##.", "...."),
    "sleep": ("....", "....", "#..#", ".##.", "...."),
    "happy": ("....", ".##.", "#..#", "....", "...."),
    "squint": ("#...", ".##.", "...#", ".##.", "#..."),
    "x": ("#..#", ".##.", ".##.", "#..#", "...."),
    "dizzy": (".##.", "#..#", "#.##", "#...", ".###"),
}
_W = {(20, 22), (21, 23), (22, 23), (23, 22), (24, 22), (25, 23), (26, 23), (27, 22)}


def _eyes(f: Any, style: str) -> None:
    for side, (x, y) in enumerate(_EYE_AT):
        if style in _LIDS:
            rows = _LIDS[style]
            if side:
                rows = tuple(r[::-1] for r in rows)
            f.paint(bp.from_rows(x, y, rows), bp.OUTLINE)
            continue
        lx, ly = _LOOK[style]
        x, y = x + lx, y + ly
        top, h = (y - 1, 6) if style == "wide" else (y, 5)
        f.paint(bp._oval(x, top, 4, h), OTTO_EYE)
        f.paint({(x + 2, top + 1), (x + 2, top + 2)}, bp.FX_WHITE)
        f.paint({(x + 1, top + h - 2)}, OTTO_NOSE_SHINE)
        if style == "down":
            f.paint(bp.rect(x, top, x + 3, top), bp.OUTLINE)


def _mouth(f: Any, mouth: str) -> None:
    if mouth in ("rest", "closed"):
        f.paint(_W, bp.OUTLINE)
    elif mouth == "smile":
        f.paint(_W | {(19, 21), (28, 21)}, bp.OUTLINE)
    elif mouth == "frown":
        f.paint(
            {(23, 22), (24, 22), (21, 24), (22, 23), (25, 23), (26, 24)},
            bp.OUTLINE,
        )
    elif mouth == "o":
        f.paint({(23, 22), (24, 22)}, bp.OUTLINE)
        f.part(bp.rect(23, 24, 24, 25), bp.MOUTH_DARK)
    elif mouth == "munch":
        f.paint(_W, bp.OUTLINE)
        f.paint({(23, 23), (24, 23)}, bp.MOUTH_DARK)
    elif mouth in ("half", "open", "wide"):
        depth = {"half": 1, "open": 2, "wide": 3}[mouth]
        inside = bp.rect(21, 23, 26, 23 + depth) - {(21, 23 + depth), (26, 23 + depth)}
        f.paint(inside, bp.MOUTH_DARK)
        f.paint(bp.rect(20, 22, 27, 22) | {(19, 21), (28, 21)}, bp.OUTLINE)
        if depth >= 2:
            f.paint(bp.rect(22, 22 + depth, 25, 23 + depth) & inside, bp.TONGUE)
        f.paint({(22, 23), (25, 23)}, bp.FX_WHITE)  # two little teeth
    else:
        raise KeyError(mouth)


#: Ear centres (left ear; the right one is mirrored) and radii per mood.
_EARS: dict[str, tuple[float, float, float, float]] = {
    "rest": (13.0, 12.0, 2.4, 2.4),
    "up": (13.5, 10.5, 2.4, 2.6),
    "flat": (11.5, 14.5, 2.8, 1.8),
    "flick": (12.5, 11.0, 2.2, 2.2),
}


def _ears(f: Any, ears: tuple[str, str]) -> None:
    for side, name in enumerate(ears):
        x, y, rx, ry = _EARS[name]
        ear = bp.ellipse(x, y, rx, ry)
        inner = {(math.floor(x), math.floor(y)), (math.floor(x), math.floor(y) + 1)}
        if side:
            ear, inner = bp.mirrored(ear), bp.mirrored(inner)
        _fur(f, ear, 1)
        f.paint(inner & ear, OTTO_EAR_IN)


def _head(f: Any, pose: Any, look: _Look) -> None:
    """Ears, the round head, the cream face, whiskers and the features
    (head centred on (CX, 18))."""
    with f.offset(*look.head):
        _ears(f, look.ears)
        head = bp.ellipse(CX, 18.5, 12.5, 9.0)
        _fur(f, head)
        f.paint({(19, 10), (20, 10), (21, 10), (22, 10), (17, 11)} & head, OTTO_SHINE)
        # A sea otter's pale face reaches up over the brow; the brown stays a cap.
        brow = bp.ellipse(18.0, 16.5, 4.5, 4.5)
        face = bp.ellipse(CX, 21.0, 10.0, 6.5) | brow | bp.mirrored(brow)
        face |= bp.ellipse(CX, 15.5, 5.0, 3.5)
        face &= bp.eroded(head, 1) | {p for p in head if p[1] >= 24}
        f.paint_map(bp.shade(face, OTTO_CREAM, dark=OTTO_CREAM_DARK, dark_depth=1))
        # Puffy whisker pads either side of the nose, freckled with whisker roots.
        pad = bp.ellipse(21.0, 21.0, 3.4, 2.6)
        f.paint(pad | bp.mirrored(pad), OTTO_PAD)
        f.paint({(19, 20), (20, 21), (18, 21), (28, 20), (27, 21), (29, 21)}, OTTO_WHISKER)
        if look.blush:
            f.paint(bp.rect(14, 22, 16, 22) | bp.rect(31, 22, 33, 22), OTTO_BLUSH)
        _eyes(f, pose.eyes)
        lift = -1 if look.sniff else 0
        nose = bp.rect(21, 17 + lift, 26, 18 + lift) - {(21, 18 + lift), (26, 18 + lift)}
        nose |= {(23, 19 + lift), (24, 19 + lift)}
        f.paint(nose, OTTO_NOSE)
        f.paint({(22, 17 + lift), (23, 17 + lift)}, OTTO_NOSE_SHINE)
        _mouth(f, pose.mouth)
        _whiskers(f, look.whiskers)


def _whiskers(f: Any, spread: int) -> None:
    """Two whiskers each side, rooted on the cheek; ``spread`` fans them out."""
    left: dict[Px, RGBA] = {}
    for y0, y1 in ((20, 19 - spread), (22, 22 + spread)):
        for x, y in bp.line(16, y0, 8, y1):
            left[(x, y)] = OTTO_WHISKER if x >= 12 else OTTO_WHISKER_TIP
    right = {(2 * CX - 1 - x, y): c for (x, y), c in left.items()}
    f.paint_map(left | right)


# ---------------------------------------------------------------------------
# The sitting otter: one ``_Look`` per frame says how it holds itself.
# ---------------------------------------------------------------------------

_SHOULDERS: tuple[Px, Px] = ((16, 29), (31, 29))
#: Both paws resting together on the round belly.
_REST_PAWS: tuple[FPx, FPx] = ((21.0, 36.5), (27.0, 36.5))
#: Paws at or below this row lie tucked on the belly, without a visible arm.
_TUCKED = 34.0
_CHIN_PAWS: tuple[FPx, FPx] = ((21.5, 27.5), (26.5, 27.5))


class _Look(NamedTuple):
    """How the sitting otter holds itself, beyond the pose's eyes and mouth."""

    ears: tuple[str, str] = ("rest", "rest")
    #: The tail's tip: (sway right, lift up) in pixels.
    tail: Px = (0, 0)
    #: Paw centres (left, right); ``None`` hides that arm (drawn elsewhere).
    paws: tuple[FPx | None, FPx | None] = _REST_PAWS
    head: Px = (0, 0)
    whiskers: int = 0
    blush: bool = True
    sniff: bool = False
    #: Hind feet lifted off the floor (left, right).
    feet: Px = (0, 0)
    #: Items in the paws: (kind, x, y) top-left; kinds "clam", "clam_open", "pebble".
    items: tuple[tuple[str, int, int], ...] = ()
    #: Items drawn in front of the paws.
    front: tuple[tuple[str, int, int], ...] = ()


def _items(f: Any, items: tuple[tuple[str, int, int], ...]) -> None:
    for kind, x, y in items:
        if kind == "pebble":
            _pebble(f, x, y)
        else:
            _clam(f, x, y, open_=kind == "clam_open")


def _feet(f: Any, lift: Px = (0, 0)) -> None:
    """Big webbed hind feet, toes pointing out, three toe creases each."""
    for side, up in enumerate(lift):
        foot = bp.ellipse(16.0, 45.0 - up, 4.4, 2.0)
        toes = {(13, 46 - up), (15, 46 - up), (17, 46 - up)}
        if side:
            foot, toes = bp.mirrored(foot), bp.mirrored(toes)
        _fur(f, foot, 1)
        f.paint(toes & foot, OTTO_DEEP)


def _sit_body() -> set[Px]:
    return bp.ellipse(CX, 35.5, 10.5, 9.5) | bp.ellipse(CX, 41.0, 12.0, 5.0)


def _arm(f: Any, shoulder: Px, end: Px, body: set[Px]) -> None:
    """An arm from ``shoulder`` to ``end``: outlined where it stands free,
    only a soft fur crease where it lies against the body."""
    arm = _limb(shoulder, end)
    ring = bp.outer_ring(arm)
    f.paint(ring - body, bp.OUTLINE)
    f.paint(ring & body, OTTO_DARK)
    f.paint_map(bp.shade(arm, OTTO_FUR, light=OTTO_LIGHT, dark=OTTO_DARK, dark_depth=1))


def _sit(f: Any, pose: Any, look: _Look) -> None:
    """The otter sitting upright, facing out."""
    with f.offset(pose.dx, min(pose.dy, 0)):
        _feet(f, look.feet)
    with f.offset(pose.dx, pose.dy):
        sway, lift = look.tail
        _tail(f, (32.0, 42.5), (41.0, 45.0), (43.0 + sway, 39.0 - lift))
        body = _sit_body()
        _fur(f, body)
        belly = bp.ellipse(CX, 37.5, 6.5, 6.5)
        f.paint(belly, OTTO_BELLY)
        f.paint({(22, 32), (23, 32), (21, 33)}, OTTO_SHINE)
        f.paint(bp.line(15, 41, 17, 44) | bp.line(32, 41, 30, 44), OTTO_DARK)
        for shoulder, paw in zip(_SHOULDERS, look.paws, strict=True):
            # A paw low on the belly needs no arm: it is tucked against the body.
            if paw is not None and paw[1] < _TUCKED:
                _arm(f, shoulder, (math.floor(paw[0]) - 1, math.floor(paw[1]) - 1), body)
        _items(f, look.items)
        _head(f, pose, look)
        for paw in look.paws:
            if paw is not None:
                if paw[1] >= _TUCKED:
                    _paw(f, *paw, 3.0, 2.1, toes_down=True)
                else:
                    _paw(f, *paw)
        _items(f, look.front)


# ---------------------------------------------------------------------------
# Floating on its back (sleeping, the belly float).
# ---------------------------------------------------------------------------


#: Where the sitting head goes when the otter lies afloat (its face to the
#: viewer, chin just above the water).
_FLOAT_HEAD: Px = (-9, 11)


def _waves(f: Any, phase: int, top: int = 42) -> None:
    """A band of water across the bottom of the cell with a rolling crest."""
    water: set[Px] = set()
    crest: set[Px] = set()
    for x in range(2, 46):
        y0 = top + round(1.2 * math.sin((x + phase) * 0.7))
        # Rounded ends, so the band reads as a patch of sea, not a slab.
        y0 = max(y0, top + {2: 4, 3: 2, 4: 1, 43: 1, 44: 2, 45: 4}.get(x, -9))
        water |= {(x, y) for y in range(y0, 47)}
        if math.sin((x + phase) * 0.7) < -0.5:
            crest.add((x, y0))
    _water(f, water)
    f.paint(crest & water, bp.FX_WHITE)
    f.paint({(x, 44) for x in range(6 + phase % 4, 42, 7)} & water, OTTO_WATER_LIGHT)


def _float(f: Any, pose: Any, *, mode: str, rise: int = 0, bob: int = 0) -> None:
    """Afloat on its back: the head to the left with its face to the viewer,
    the belly up, the webbed feet poking out of the water on the right.
    ``mode`` is "sleep" (paws over the eyes) or "clam" (a clam on the belly)."""
    hx, hy = _FLOAT_HEAD
    with f.offset(0, bob):
        _tail(f, (40.0, 39.0), (44.0, 40.0), (45.5, 36.5), 2.4)
        for cx, cy in ((37.5, 29.5), (42.5, 30.5)):
            _fur(f, _limb((math.floor(cx) - 2, 35), (math.floor(cx) - 1, math.floor(cy) + 1)), 1)
            foot = bp.ellipse(cx, cy, 2.2, 3.0)
            _fur(f, foot, 1)
            top = min(y for _x, y in foot)
            f.paint({(math.floor(cx) - 1, top), (math.floor(cx) + 1, top)} & foot, OTTO_DEEP)
        body = bp.ellipse(31.0, 37.0 - rise * 0.5, 12.0, 5.5 + rise * 0.5)
        _fur(f, body)
        f.paint(bp.ellipse(32.0, 34.0 - rise, 8.0, 2.0) & body, OTTO_BELLY)
        f.paint({(29, 33 - rise), (30, 33 - rise)}, OTTO_SHINE)
        # Drawn alone and clipped: the far whisker tips leave the cell.
        sub = bp.Frame()
        _head(sub, pose, _Look(paws=(None, None), head=(hx, hy)))
        _transform(f, sub, lambda x, y: (x, y))
        if mode == "sleep":
            # Both paws over the eyes, the slim arms rising from the water.
            for px, shoulder in ((8.5, (10, 40)), (20.5, (18, 40))):
                _fur(f, bp.thick(bp.line(*shoulder, math.floor(px) - 1, 29)), 1)
                _paw(f, px, 27.5, 2.8, 2.3)
        else:
            _clam(f, 29, 28 - rise)
            for px in (27.5, 37.5):
                _fur(f, _limb((math.floor(px) - 1, 35), (math.floor(px) - 1, 31)), 1)
                _paw(f, px, 31.0 - rise, 2.3, 2.0)
    _waves(f, pose.i + bob)


# ---------------------------------------------------------------------------
# Held, the backflip and the roll.
# ---------------------------------------------------------------------------


def _dangle(f: Any, pose: Any) -> None:
    """Held: scooped up, body hanging long, paws paddling at the air and the
    hind feet kicking as if swimming."""
    i = pose.i
    lag = -pose.dx
    paddle = i % 2
    with f.offset(pose.dx, 0):
        sway = (-2, 0, 2, 2, 0, -2)[i % 6]
        _tail(f, (27.0, 39.0), (31.0, 44.0), (33.0 + sway, 44.5), 2.6)
        for side, (hip, out) in enumerate((((19, 38), -1), ((28, 38), 1))):
            up = (paddle + side) % 2
            foot_at = (hip[0] + out * 2 + lag, 43 - up)
            _fur(f, _limb(hip, foot_at), 1)
            foot = bp.ellipse(foot_at[0] + 0.5 + out, foot_at[1] + 1.5, 3.4, 1.8)
            _fur(f, foot, 1)
            f.paint(
                {(foot_at[0] - 1 + out, foot_at[1] + 2), (foot_at[0] + 1 + out, foot_at[1] + 2)}
                & foot,
                OTTO_DEEP,
            )
        body = bp.ellipse(CX, 32.0, 9.5, 9.0)
        _fur(f, body)
        f.paint(bp.ellipse(CX, 33.5, 5.5, 5.5), OTTO_BELLY)
        look = _Look(ears=("up", "up"), head=(0, -4), paws=(None, None), whiskers=1)
        _head(f, pose, look)
        # A doggy paddle: one paw reaches up and forward while the other pulls
        # down and back, then they swap.
        for side in (0, 1):
            up = (paddle + side) % 2
            x = 18.5 if up else 15.0
            paw = (x, 28.5 if up else 35.0)
            if side:
                paw = (2 * CX - paw[0], paw[1])
            shoulder = _SHOULDERS[side][0], 27
            _arm(f, shoulder, (math.floor(paw[0]) - 1, math.floor(paw[1]) - 1), body)
            _paw(f, paw[0] + 0.5 * lag, paw[1], 2.6, 2.1)


def _ball(f: Any, pose: Any) -> None:
    """Curled up into a ball: the head tucked over the belly, feet and tail
    wrapped round the front. Turned about its centre for the roll."""
    look = _Look(paws=(None, None), head=(0, 3), ears=("flat", "flat"), blush=True)
    body = bp.ellipse(CX, 34.0, 11.0, 10.0)
    _fur(f, body)
    _tail(f, (33.0, 39.0), (30.0, 46.0), (17.0, 43.5), 2.6)
    _head(f, pose, look)
    for x in (18.5, 29.5):
        _paw(f, x, 33.0, 2.6, 2.2)


def _crouch(f: Any, pose: Any, look: _Look) -> None:
    """The sitting otter squashed down onto its feet: winding up for a jump,
    or the landing."""
    sub = bp.Frame()
    _sit(sub, replace(pose, dx=0, dy=0), look)
    _transform(f, sub, _squash(0.9, 47), (pose.dx, 0))


def _rolled(f: Any, pose: Any, turns: int) -> None:
    """The ball turned ``turns`` quarter turns clockwise (3 = one back)."""
    sub = bp.Frame()
    _ball(sub, replace(pose, dx=0, dy=0))
    _transform(f, sub, _rot90(turns, CX, 30), (pose.dx, pose.dy))


# ---------------------------------------------------------------------------
# Poses.
# ---------------------------------------------------------------------------

_IDLE_EYES = ("open", "open", "open", "look_left", "look_left", "open", "open")
_IDLE_TAIL = ((0, 0), (0, 0), (1, 1), (2, 2), (2, 2), (1, 1), (0, 0))
#: Thinking: the pebble paw per frame: raised, striking the clam, or mid-way.
_THINK_PAW = ("up", "hit", "mid", "up", "up", "hit", "mid", "up")
#: Success: the backflip. Vertical squash and flip per frame, then the shell
#: is held up in triumph.
_FLIP_DY = (0, -4, -8, -9, -7, -2, 0, 0)
#: The tucked ball's quarter turns while airborne (None: drawn sitting).
_FLIP_TURNS: tuple[int | None, ...] = (None, None, 3, 2, 1, None, None, None)
_ERROR_EYES = ("wide", "wide", "wide", "x", "x", "squint")
_ERROR_MOUTH = ("o", "o", "o", "frown", "frown", "frown")
_ERROR_DY = (-2, -1, 0, 0, 0, 0)
_ERROR_SHAKE = (0, 0, 0, -1, 1, 0)
_SWAY = (-1, 0, 1, 1, 0, -1)


def otto_pose(state: str, i: int) -> Any:
    pose = bp.base_pose(state, i)
    if state == "idle":
        if i < len(_IDLE_EYES):
            return replace(pose, eyes=_IDLE_EYES[i], mouth="rest")
        return replace(pose, mouth="rest")
    if state == "listening":
        return replace(pose, mouth="closed")
    if state == "thinking":
        return replace(pose, eyes="down" if _THINK_PAW[i] == "hit" else "up_right", mouth="closed")
    if state == "talking":
        return pose
    if state == "success":
        eyes = "happy"
        mouth = "smile" if i < 6 else "open"
        return bp.Pose(state, i, dy=_FLIP_DY[i], eyes=eyes, mouth=mouth)
    if state == "error":
        return bp.Pose(
            state,
            i,
            dx=_ERROR_SHAKE[i],
            dy=_ERROR_DY[i],
            eyes=_ERROR_EYES[i],
            mouth=_ERROR_MOUTH[i],
        )
    if state == "sleeping":
        return bp.Pose(state, i, eyes="sleep", mouth="closed")
    if state == "working":
        return replace(pose, mouth="closed")
    if state == "searching":
        return pose
    if state == "held":
        return bp.Pose(state, i, dx=_SWAY[i % len(_SWAY)], eyes="wide", mouth="o")
    return pose


def _look(pose: Any) -> _Look:
    """The sitting otter's body language per state."""
    state, i = pose.state, pose.i
    if state == "idle":
        if i >= len(_IDLE_TAIL):
            return _Look(ears=("flick", "rest"))  # the accent: a blink and an ear flick
        return _Look(tail=_IDLE_TAIL[i], whiskers=1 if i == 5 else 0, sniff=i == 5)
    if state == "listening":
        return _Look(ears=("up", "up"), paws=_CHIN_PAWS, tail=(1, 2))
    if state == "thinking":
        phase = _THINK_PAW[i]
        paw = {"up": (31.5, 25.5), "mid": (29.5, 28.0), "hit": (27.0, 32.5)}[phase]
        return _Look(
            paws=((18.5, 37.5), paw),
            items=(("clam", 20, 33),),
            front=(("pebble", math.floor(paw[0]) - 2, math.floor(paw[1]) - 3),),
            tail=(0, i % 2),
        )
    if state == "talking":
        lift = (0, 1, 2, 4)[i]
        paws = ((21.0 - lift, 31.5 - lift / 2), (27.0 + lift, 31.5 - lift / 2))
        return _Look(paws=paws, ears=("flick", "flick") if i == 3 else ("rest", "rest"))
    if state == "error":
        if i < 1:
            return _Look(ears=("up", "up"), items=(("clam", 21, 30),), whiskers=1)
        flung = ((14.5, 25.0), (33.5, 25.0)) if i < 3 else ((19.5, 33.0), (28.5, 33.0))
        return _Look(ears=("flat", "flat"), paws=flung, tail=(-1, -2), whiskers=1 if i < 3 else -1)
    if state == "working":
        return _Look(paws=(None, None))
    if state == "searching":
        return _Look(paws=(_REST_PAWS[0], None))
    return _Look()


# ---------------------------------------------------------------------------
# Drawing.
# ---------------------------------------------------------------------------


def draw_otto(f: Any, pose: Any) -> None:
    state, i = pose.state, pose.i
    if pose.act:
        _draw_act(f, pose)
    elif state == "sleeping":
        _float(f, pose, mode="sleep", rise=bp.SLEEP_BREATH[i % 6], bob=0)
    elif state == "held":
        _dangle(f, pose)
    elif state == "success":
        _draw_success(f, pose)
    elif state == "working":
        _draw_working(f, pose)
    elif state == "searching":
        _draw_searching(f, pose)
    else:
        _sit(f, pose, _look(pose))


def _draw_success(f: Any, pose: Any) -> None:
    """A backflip: crouch, leap, tuck into a ball that turns over backwards,
    land, and hold the shell up high."""
    i = pose.i
    turns = _FLIP_TURNS[i]
    if turns is not None:
        _rolled(f, pose, turns)
        return
    if i < 7:
        look = _Look(
            ears=("up", "up"),
            items=(("clam", 21, 32),),
            paws=((20.0, 35.0), (28.0, 35.0)),
            tail=(1, 3) if 0 < i < 6 else (0, 0),
            feet=(1, 1) if 1 <= i <= 5 else (0, 0),
        )
        if i in (0, 6):
            _crouch(f, pose, look)
        else:
            _sit(f, pose, look)
        return
    # Landed: the shell goes up in one paw, the other on the belly.
    look = _Look(
        ears=("up", "up"),
        paws=((20.5, 33.0), (36.5, 13.5 + (i - 6))),
        front=(("clam", 34, 5 + (i - 6)),),
        tail=(2, 4 - i % 2 * 2),
    )
    _sit(f, pose, look)


def _draw_working(f: Any, pose: Any) -> None:
    """Typing on the laptop: the arms reach down behind the lid; the paws
    that tap the keys are drawn with the effect, in front."""
    _sit(f, pose, _Look(paws=(None, None)))
    with f.offset(pose.dx, pose.dy):
        for shoulder, end in ((_SHOULDERS[0], (16, 38)), (_SHOULDERS[1], (31, 38))):
            _arm(f, shoulder, end, _sit_body())


def _draw_searching(f: Any, pose: Any) -> None:
    """One paw holds the magnifier's handle and sweeps it along: the left
    paw while it is on the left, the right one after; the other paw rests."""
    sweep = bp.SEARCH_SWEEP[pose.i % len(bp.SEARCH_SWEEP)]
    side = 0 if sweep < 0 else 1
    paws = (None, _REST_PAWS[1]) if side == 0 else (_REST_PAWS[0], None)
    _sit(f, pose, _Look(paws=paws, whiskers=1))
    hx, hy = _MAG[0] + sweep + 6, _MAG[1] + 7
    with f.offset(pose.dx, pose.dy):
        _arm(f, _SHOULDERS[side], (hx - 1, hy - 1), _sit_body())


# ---------------------------------------------------------------------------
# Effects.
# ---------------------------------------------------------------------------

_MAG: Px = (CX, 32)


def _listening_fx(f: Any, pose: Any) -> None:
    with f.offset(pose.dx, pose.dy):
        bp.fx_arcs(f, pose.i, (8, 11), (39, 11))


def _tink(f: Any, x: int, y: int) -> None:
    """The click of pebble on shell: a little white burst."""
    f.paint({(x - 3, y - 1), (x - 4, y - 2), (x + 3, y - 1), (x + 4, y - 2)}, bp.FX_WHITE)
    f.paint({(x, y - 4), (x, y - 5), (x - 2, y - 3), (x + 2, y - 3)}, bp.SPARK)


def _thinking_fx(f: Any, pose: Any) -> None:
    """Thought dots orbit overhead; each strike of the pebble goes *tink*."""
    i = pose.i
    with f.offset(pose.dx, pose.dy):
        bp.fx_dots(f, i, 19, 3)
        if _THINK_PAW[i] == "hit":
            _tink(f, 23, 33)


def _talking_fx(f: Any, pose: Any) -> None:
    """Little bubbles pop up beside the head, more the louder it talks."""
    i = pose.i
    spots = ((10, 24), (37, 24), (8, 17), (39, 17), (11, 10), (36, 10))
    with f.offset(pose.dx, pose.dy):
        for x, y in spots[: 2 * i]:
            f.glyph(x - 1, y - 1, _BUBBLE, _water_palette())


#: Success: speed lines on the way up and down, then sparkles round the shell.
def _success_fx(f: Any, pose: Any) -> None:
    i = pose.i
    if 1 <= i <= 4:
        for x in (8, 39):
            y0 = 22 + pose.dy
            f.paint(bp.line(x, y0 + 4, x, y0 + 10) & bp.rect(0, 0, 47, 47), bp.ARC_FADE)
    if i in (0, 6):
        for x in (6, 9, 38, 41):
            f.paint({(x, 46), (x + 1, 45)}, bp.ARC_FADE)
    bp.fx_sparkles(f, i, ((31, 4, 5), (44, 9, 6), (6, 16, 6), (42, 22, 7)))


#: Error: where the dropped clam is per frame (glyph top-left), and whether
#: it lies upside down.
_DROP_PATH: tuple[tuple[int, int, bool] | None, ...] = (
    None,
    (22, 35, False),
    (25, 41, True),
    (30, 37, True),
    (34, 41, False),
    (35, 41, False),
)


def _error_fx(f: Any, pose: Any) -> None:
    """The clam slips from the paws, bounces off the floor and rolls away; a
    red "!" and a sweat drop."""
    i = pose.i
    spot = _DROP_PATH[i]
    if spot is not None:
        x, y, upside = spot
        rows = tuple(reversed(_CLAM)) if upside else _CLAM
        f.glyph(x, y, rows, _clam_palette())
        if i == 2:
            f.paint({(23, 46), (22, 45), (33, 46), (34, 45)}, bp.ARC_FADE)
    bp.fx_bang(f, 40, 3)
    if i >= 1:
        with f.offset(pose.dx, 0):
            bp.fx_sweat(f, i - 1, 34, 9)


def _sleeping_fx(f: Any, pose: Any) -> None:
    bp.fx_zzz(f, pose.i, 27, 21)


#: Working: which paw is down on a key per frame (0 left, 1 right, None both up).
_TYPE = (0, 1, 0, None, 1, 0, 1, None)


def _working_fx(f: Any, pose: Any) -> None:
    i = pose.i
    with f.offset(0, pose.dy):
        bp.fx_laptop(f, i, 17, 34)
        down = _TYPE[i]
        for side, x in enumerate((16.0, 32.0)):
            up = 0 if down == side else 1
            _paw(f, x, 40.5 - up, 2.4, 1.9)


def _searching_fx(f: Any, pose: Any) -> None:
    i = pose.i
    sweep = bp.SEARCH_SWEEP[i % len(bp.SEARCH_SWEEP)]
    with f.offset(pose.dx, pose.dy):
        bp.fx_magnifier(f, i, *_MAG)
        _paw(f, _MAG[0] + sweep + 6.5, _MAG[1] + 6.5, 2.4, 2.1)


def _held_fx(f: Any, pose: Any) -> None:
    """Swing streaks and water dripping off the kicking feet."""
    i = pose.i
    with f.offset(pose.dx, 0):
        bp.fx_held(f, i, (9, 22), (38, 22))
    for x, start in ((15, 0), (33, 3)):
        age = (i - start) % 6
        if age < 3:
            f.glyph(x, 41 + 2 * age, _DRIP, {"#": OTTO_WATER_LIGHT})


# ---------------------------------------------------------------------------
# Idle acts.
# ---------------------------------------------------------------------------


def _act_pose(name: str, i: int) -> Any:
    eyes, mouth, dx, dy = "open", "rest", 0, 0
    if name == "clam_crack":
        eyes = ("down", "up_right", "down", "up_right", "down", "wide", "happy", "happy")[i]
        mouth = ("rest", "rest", "closed", "rest", "closed", "o", "munch", "smile")[i]
    elif name == "roll_over":
        eyes = ("open", "closed", "happy", "happy", "happy", "closed", "dizzy", "open")[i]
        mouth = ("rest", "closed", "smile", "smile", "smile", "closed", "smile", "rest")[i]
        dy = (0, 1, 0, 0, 0, 1, 0, 0)[i]
    elif name == "juggle_pebble":
        eyes = ("down", "up_left", "up_left", "up_right", "down", "up_right", "up_left", "open")[i]
        mouth = ("rest", "rest", "o", "rest", "smile", "rest", "o", "smile")[i]
    elif name == "whisker_wash":
        eyes = ("open", "closed", "closed", "closed", "closed", "closed", "happy", "open")[i]
        mouth = ("rest", "closed", "closed", "closed", "closed", "smile", "smile", "rest")[i]
    elif name == "belly_float":
        eyes = ("open", "squint", "happy", "open", "open", "happy", "squint", "open")[i]
        mouth = ("rest", "closed", "smile", "rest", "munch", "smile", "closed", "smile")[i]
    elif name == "splash":
        eyes = ("open", "open", "squint", "happy", "closed", "closed", "happy", "open")[i]
        mouth = ("rest", "smile", "open", "smile", "closed", "closed", "smile", "rest")[i]
        dx = (0, 0, 0, 0, -1, 1, 0, 0)[i]
    return bp.Pose("idle", i, dx=dx, dy=dy, eyes=eyes, mouth=mouth, act=name)


#: Juggling: the pebble's top-left per frame and which paw is up.
_JUGGLE_PEBBLE: tuple[Px, ...] = (
    (18, 29),
    (17, 19),
    (22, 3),
    (28, 15),
    (27, 29),
    (28, 18),
    (23, 4),
    (18, 29),
)
_JUGGLE_PAWS: tuple[tuple[FPx, FPx], ...] = (
    ((19.5, 31.5), (27.0, 31.5)),
    ((18.0, 26.0), (27.0, 31.5)),
    ((19.5, 31.5), (27.0, 31.5)),
    ((19.5, 31.5), (29.0, 30.5)),
    ((19.5, 31.5), (28.5, 31.5)),
    ((19.5, 31.5), (30.0, 26.0)),
    ((19.5, 31.5), (27.0, 31.5)),
    ((19.5, 31.5), (27.0, 31.5)),
)
#: Whisker wash: both paws rub round the cheeks.
_WASH_PAWS: tuple[tuple[FPx, FPx], ...] = (
    _REST_PAWS,
    ((16.5, 24.5), (31.5, 24.5)),
    ((15.5, 21.5), (32.5, 23.5)),
    ((16.5, 19.5), (31.5, 21.5)),
    ((15.5, 22.5), (32.5, 19.5)),
    ((16.5, 24.5), (31.5, 22.5)),
    _CHIN_PAWS,
    _REST_PAWS,
)
_CRACK_PAW: tuple[FPx, ...] = (
    (28.0, 31.0),
    (31.5, 25.5),
    (27.0, 32.5),
    (31.5, 25.5),
    (27.0, 32.5),
    (29.0, 33.0),
    (27.5, 26.0),
    (27.0, 31.5),
)


def _act_look(pose: Any) -> _Look | None:
    """The sitting look of an act frame, or None when the act draws it otherwise."""
    name, i = pose.act, pose.i
    if name == "clam_crack":
        if i < 5:
            paw = _CRACK_PAW[i]
            return _Look(
                paws=((18.5, 37.5), paw),
                items=(("clam", 20, 33),),
                front=(("pebble", math.floor(paw[0]) - 2, math.floor(paw[1]) - 3),),
            )
        if i < 7:
            return _Look(
                paws=((18.5, 37.5), _CRACK_PAW[i]),
                items=(("clam_open", 20, 32),),
                whiskers=1 if i == 6 else 0,
            )
        return _Look(whiskers=1)
    if name == "juggle_pebble":
        x, y = _JUGGLE_PEBBLE[i]
        return _Look(paws=_JUGGLE_PAWS[i], front=(("pebble", x, y),), tail=(i % 3 - 1, 1))
    if name == "whisker_wash":
        return _Look(paws=_WASH_PAWS[i], whiskers=(0, -1, 1, -1, 1, -1, 1, 0)[i])
    if name == "splash":
        tail = ((0, 0), (1, 7), (3, -2), (2, 0), (1, 1), (1, 1), (0, 1), (0, 0))[i]
        ears = ("flat", "flat") if i in (4, 5) else ("rest", "rest")
        paws = _CHIN_PAWS if i in (2, 3) else _REST_PAWS
        return _Look(tail=tail, ears=ears, paws=paws, whiskers=(0, 0, 1, 1, -1, 1, 0, 0)[i])
    if name == "roll_over":
        if i in (0, 7):
            return _Look()
        if i == 6:
            return _Look(ears=("flick", "rest"), whiskers=1)
        return None
    if name == "belly_float" and i in (0, 7):
        return _Look(feet=(0, 0), whiskers=1 if i == 7 else 0)
    return None


_ROLL_TURNS = (0, 0, 1, 2, 3, 0, 0, 0)


def _draw_act(f: Any, pose: Any) -> None:
    look = _act_look(pose)
    if look is not None:
        _sit(f, pose, look)
        return
    if pose.act == "roll_over":
        _rolled(f, pose, _ROLL_TURNS[pose.i])
    elif pose.act == "belly_float":
        i = pose.i
        rise = (0, 0, 1, 1, 0, 0, 0, 0)[i]
        _float(f, pose, mode="clam", rise=rise, bob=(1, 0, 0, 1, 1, 0, 1, 1)[i])


def _clam_crack_fx(f: Any, pose: Any) -> None:
    i = pose.i
    if i in (2, 4):
        _tink(f, 23, 33)
    if i == 4:
        f.paint({(22, 35), (23, 36), (24, 35)}, bp.OUTLINE)
    if i == 5:
        bp.fx_sparkles(f, 1, ((14, 26, 0),))
    if i == 7:
        # The empty halves dropped beside it.
        f.glyph(36, 41, ("lll", "#d#"), _clam_palette())
        f.glyph(5, 42, ("#d#", "lll"), _clam_palette())
        bp.fx_sparkles(f, 0, ((13, 26, 0),))


def _roll_over_fx(f: Any, pose: Any) -> None:
    i = pose.i
    if 2 <= i <= 4:
        # Motion arcs round the rolling ball.
        f.paint({(6, 26 + i), (7, 24 + i), (40, 38 - i), (41, 36 - i)}, bp.ARC_FADE)
        f.paint({(10, 46), (11, 46), (36, 46), (37, 46)}, bp.ARC_FADE)
    if i == 6:
        bp.fx_dots(f, 2, 19, 4)


def _juggle_fx(f: Any, pose: Any) -> None:
    i = pose.i
    if i in (2, 6):
        x, y = _JUGGLE_PEBBLE[i]
        f.paint({(x - 2, y + 1), (x + 5, y + 1)}, bp.ARC_FADE)
    if i == 7:
        bp.fx_sparkles(f, 1, ((36, 20, 0),))


def _wash_fx(f: Any, pose: Any) -> None:
    i = pose.i
    for x, y, start in ((9, 15, 1), (38, 13, 2), (11, 7, 3), (37, 6, 4)):
        age = i - start
        if 0 <= age <= 2:
            f.glyph(x - 1, y - 1 - 2 * age, _BUBBLE, _water_palette())
    if i == 6:
        bp.fx_sparkles(f, 1, ((10, 18, 0), (38, 17, 0)))


def _float_fx(f: Any, pose: Any) -> None:
    i = pose.i
    if i in (1, 6):
        _splash(f, CX, 44, big=True)
    if 2 <= i <= 5:
        bp.fx_sparkles(f, i, ((32, 20, 4),))
    if i == 7:
        for x, y in ((14, 9), (33, 9)):
            f.glyph(x, y, _DRIP, {"#": OTTO_WATER_LIGHT})


def _splash(f: Any, x: int, y: int, *, big: bool) -> None:
    """A crown of water drops thrown up from ``(x, y)``."""
    spread = ((-10, -6), (-6, -11), (0, -14), (6, -11), (10, -6))
    if not big:
        spread = ((-4, -4), (0, -7), (4, -4))
    for dx, dy in spread:
        f.glyph(x + dx - 1, y + dy - 1, _DRIP, {"#": OTTO_WATER_LIGHT})


def _splash_fx(f: Any, pose: Any) -> None:
    """Tail slap: a puddle behind it, a crown of drops where the tail lands,
    then a shake that throws the drops off the fur."""
    i = pose.i
    if 1 <= i <= 6:
        _water(f, bp.ellipse(40.0, 45.5, 6.5, 1.8))
    if i == 2:
        _splash(f, 41, 44, big=False)
        f.paint({(34, 43), (47 - 1, 43)}, bp.FX_WHITE)
    if i == 3:
        for x, y in ((35, 30), (40, 27), (45, 32), (31, 26)):
            f.glyph(x, y, _DRIP, {"#": OTTO_WATER_LIGHT})
    if i in (4, 5):
        side = -1 if i == 4 else 1
        for x, y in ((8, 22), (6, 32), (39, 20), (41, 30)):
            f.glyph(x + side, y + (i - 4) * 2, _DRIP, {"#": OTTO_WATER_LIGHT})
        f.paint({(11, 18), (10, 19), (36, 18), (37, 19)}, bp.ARC_FADE)
    if i == 6:
        bp.fx_sparkles(f, 1, ((40, 36, 0),))


# ---------------------------------------------------------------------------
# The design.
# ---------------------------------------------------------------------------


def design(module: Any) -> Any:
    global bp
    bp = module
    acts = (
        ("clam_crack", 7, _clam_crack_fx),
        ("roll_over", 8, _roll_over_fx),
        ("juggle_pebble", 8, _juggle_fx),
        ("whisker_wash", 7, _wash_fx),
        ("belly_float", 6, _float_fx),
        ("splash", 8, _splash_fx),
    )
    return bp.PetDesign(
        id="otto",
        name="Otto",
        description=(
            "A sea otter who cracks clams on its belly while it thinks"
            " and naps floating on its back."
        ),
        draw=draw_otto,
        pose=otto_pose,
        waist=41,
        anchors=bp.Anchors(
            arcs_left=(8, 11),
            arcs_right=(39, 11),
            dots=(19, 3),
            zzz=(27, 21),
            bang=(40, 3),
            sparkles=((31, 4, 5), (44, 9, 6), (6, 16, 6), (42, 22, 7)),
            laptop=(17, 34),
            magnifier=_MAG,
        ),
        fx={
            "listening": _listening_fx,
            "thinking": _thinking_fx,
            "talking": _talking_fx,
            "success": _success_fx,
            "error": _error_fx,
            "sleeping": _sleeping_fx,
            "working": _working_fx,
            "searching": _searching_fx,
            "held": _held_fx,
        },
        acts=tuple(
            bp.IdleAct(name, 8, fps, (lambda n: lambda i: _act_pose(n, i))(name), fx)
            for name, fps, fx in acts
        ),
    )
