"""Kiko: the axolotl.

A soft pink axolotl seen from the front: a wide flat head with a gentle,
ever-present smile, small dark eyes set far apart, three feathery gill fronds
on each side in a deeper magenta, stubby four-fingered limbs and a finned tail
curling out to the right. The fronds carry most of the acting: they fan out
to listen, a light pulse runs along them while Kiko thinks, they flare on a
happy hop and droop when something goes wrong.
"""

import math
from dataclasses import dataclass, replace
from typing import Any

#: The build_pets module, handed in by ``design``.
bp: Any = None


def _hex(value: str) -> tuple[int, int, int, int]:
    value = value.lstrip("#")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), 255)


SKIN = _hex("#ffb3cf")
SKIN_LIGHT = _hex("#ffdbe9")
SKIN_DARK = _hex("#e384aa")
BELLY = _hex("#ffe6f0")
GILL = _hex("#e0508f")
GILL_LIGHT = _hex("#ff8cc0")
GILL_DARK = _hex("#a83270")
#: The light pulse running along the fronds while Kiko thinks.
GILL_GLOW = _hex("#ffe3f2")
FIN = _hex("#ffd0e2")
INK = _hex("#2e1a2a")
CHEEK = _hex("#ff6f9f")
#: Pale cheeks: the blush drains when something goes wrong.
CHEEK_PALE = _hex("#f4e6ec")
BUBBLE = _hex("#9fd8ff")
BUBBLE_SHINE = _hex("#f2fbff")
HEART = _hex("#ff5c8a")

CX = 24
#: Left fronds' roots on the head (upper, middle, lower) and their resting
#: directions in degrees (screen coordinates, 180 = straight left).
_ROOTS = ((13, 19), (11, 23), (12, 28))
_ANGLES = (218.0, 186.0, 156.0)
_FROND_LEN = 7


@dataclass(frozen=True)
class Look:
    """Everything a frame can change on Kiko besides the pose."""

    #: Fronds fan out (+1) or fold in (-1).
    spread: float = 0.0
    #: Fronds rotate towards the ground (1 = a full droop).
    droop: float = 0.0
    #: Per-frond extra angle in degrees (upper, middle, lower), each side;
    #: the right side's angles are mirrored, so +1 lifts a frond on both sides.
    wave_l: tuple[float, float, float] = (0.0, 0.0, 0.0)
    wave_r: tuple[float, float, float] = (0.0, 0.0, 0.0)
    #: Frond lengths, each side.
    len_l: tuple[int, int, int] = (_FROND_LEN,) * 3
    len_r: tuple[int, int, int] = (_FROND_LEN,) * 3
    #: Where the light pulse sits along the fronds (None = no glow).
    glow: int | None = None
    cheek: str = "pink"
    #: Tail tip lift in pixels (+ up).
    tail: int = 0
    #: Arm pose of each side: rest, up, type_up, type_down, dangle, hug.
    arm_l: str = "rest"
    arm_r: str = "rest"
    #: Head offset against the body (a tilt-like wiggle).
    head_dx: int = 0
    #: Turned away (the back of the head, no face).
    back: bool = False
    held: bool = False


# ---------------------------------------------------------------------------
# Shapes.
# ---------------------------------------------------------------------------


def _frond(root: tuple[int, int], angle: float, length: int) -> tuple[set, set, list]:
    """One feathery frond for the left side: (stalk, fringe, centre line).

    A plump stalk that tapers and curls up a little towards its tip, with
    short barbs on both sides slanting towards the tip, like a feather.
    """
    stalk: set = set()
    fringe: set = set()
    centre: list = []
    x, y = root[0] + 0.5, root[1] + 0.5
    a = math.radians(angle)
    curl = math.radians(2.5)
    for t in range(length + 1):
        c, s = round(math.cos(a), 6), round(math.sin(a), 6)
        p = (math.floor(x), math.floor(y))
        centre.append(p)
        r = 1.0 if t < length else 0.6
        stalk |= bp.ellipse(x, y, r, r)
        if t % 2 == 1:
            # A pair of barbs slanting towards the tip: a feathery plume.
            px, py = -s, c
            fringe.add((math.floor(x + px * 1.5 + c * 0.5), math.floor(y + py * 1.5 + s * 0.5)))
            fringe.add((math.floor(x - px * 1.5 + c * 0.5), math.floor(y - py * 1.5 + s * 0.5)))
        x, y = x + c, y + s
        # Curl the tip upwards: the left fronds turn clockwise, towards the sky.
        a += curl if math.sin(a) <= 0.3 else -curl
    return stalk, fringe - stalk, centre


def _frond_angles(look: Look, wave: tuple[float, float, float]) -> list[float]:
    out = []
    for k, base in enumerate(_ANGLES):
        fan = (20.0, 0.0, -20.0)[k] * look.spread
        out.append(base + fan - 30.0 * look.droop + wave[k])
    return out


def _draw_fronds(f, look: Look, hx: int) -> None:
    """Six fronds behind the head; the right side mirrors the left."""
    for side in (0, 1):
        wave = look.wave_l if side == 0 else look.wave_r
        lengths = look.len_l if side == 0 else look.len_r
        for k, angle in enumerate(_frond_angles(look, wave)):
            if lengths[k] <= 0:
                continue
            stalk, fringe, centre = _frond(_ROOTS[k], angle, lengths[k])
            # The pulse runs down the fronds one after the other.
            glow = None if look.glow is None else look.glow - 2 * k
            colors = {p: GILL for p in stalk}
            for t, p in enumerate(centre):
                if t <= 1:
                    colors[p] = GILL_DARK
            for p in fringe:
                colors[p] = GILL_LIGHT
            if glow is not None:
                # A light pulse travelling from the root to the tip.
                for t, p in enumerate(centre):
                    d = glow - t
                    if 0 <= d <= 2:
                        # A bright head with a fading trail behind it.
                        tone = (GILL_GLOW, GILL_GLOW, GILL_LIGHT)[d]
                        for q in bp.rect(p[0] - 1, p[1] - 1, p[0] + 1, p[1] + 1) & stalk:
                            colors[q] = tone
                for p in fringe:
                    if _near(p, centre, glow):
                        colors[p] = GILL_GLOW
            if side == 1:
                colors = {(2 * CX - 1 - x, y): c for (x, y), c in colors.items()}
            colors = {(x + hx, y): c for (x, y), c in colors.items()}
            f.part(set(colors), colors)


def _near(p, centre, glow: int) -> bool:
    if glow < 0 or glow >= len(centre):
        return False
    cx, cy = centre[glow]
    return abs(p[0] - cx) <= 1 and abs(p[1] - cy) <= 2 or abs(p[0] - cx) <= 2 and p[1] == cy


def _head() -> set:
    """Wide and flat: a broad oval with a flattened crown."""
    return bp.ellipse(CX, 24.5, 13.5, 9.0) | bp.ellipse(CX, 22.5, 11.5, 7.5)


def _body() -> set:
    return bp.ellipse(CX, 38.5, 9.0, 6.5)


def _tail(lift: float) -> tuple[set, set]:
    """The tail curling out to the right, tip ``lift`` px up: (tail, fin) masks."""
    p0, p1, p2 = (29.0, 41.0), (38.0, 44.5), (43.0, 38.5 - lift)
    tail: set = set()
    fin: set = set()
    for n in range(25):
        t = n / 24
        x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0]
        y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1]
        r = 2.4 * (1 - t) + 0.7
        tail |= bp.ellipse(x, y, r, r)
        if 0.25 < t < 0.97:
            # A soft fin along the top of the tail, tallest in the middle.
            h = 1.0 + 1.2 * math.sin(math.pi * (t - 0.25) / 0.72)
            top = math.floor(y - r - h + 0.5)
            fin |= {(math.floor(x), yy) for yy in range(top, math.floor(y) + 1)}
    return tail, fin - tail


_ARM_TIPS = {
    "rest": ((16, 37), (13, 41)),
    "up": ((16, 36), (11, 31)),
    "type_up": ((15, 37), (14, 40)),
    "type_down": ((15, 37), (16, 43)),
    "dangle": ((16, 37), (15, 43)),
    "hug": ((16, 37), (19, 40)),
}


def _arm(mode: str) -> tuple[set, set]:
    """A left front limb: (arm, fingers). Four tiny fingers splay from the hand."""
    (sx, sy), (hx, hy) = _ARM_TIPS[mode]
    arm: set = set()
    for x, y in bp.line(sx, sy, hx, hy):
        arm |= bp.ellipse(x + 0.5, y + 0.5, 1.3, 1.3)
    hand = bp.ellipse(hx + 0.5, hy + 0.5, 1.6, 1.6)
    dx, dy = hx - sx, hy - sy
    norm = math.hypot(dx, dy) or 1.0
    ux, uy = dx / norm, dy / norm
    fingers: set = set()
    for spread in (-0.9, -0.3, 0.3, 0.9):
        ang = math.atan2(uy, ux) + spread
        fingers.add(
            (math.floor(hx + 0.5 + math.cos(ang) * 2.0), math.floor(hy + 0.5 + math.sin(ang) * 2.0))
        )
    return arm | hand, fingers - arm - hand


def _leg() -> tuple[set, set]:
    """A left hind leg, a stub with its toes on the ground."""
    leg = bp.ellipse(17.0, 43.5, 2.2, 1.8)
    toes = {(15, 45), (16, 46)}
    return leg, toes - leg


def _paint_limb(f, mask: set, fingers: set, mirror: bool, dx: int = 0) -> None:
    if mirror:
        mask, fingers = bp.mirrored(mask), bp.mirrored(fingers)
    mask, fingers = bp.shifted(mask, dx, 0), bp.shifted(fingers, dx, 0)
    whole = mask | fingers
    colors = bp.shade(mask, SKIN, light=SKIN_LIGHT, dark=SKIN_DARK, dark_depth=1)
    colors.update({p: SKIN_DARK for p in fingers})
    f.part(whole, colors)


# ---------------------------------------------------------------------------
# Drawing.
# ---------------------------------------------------------------------------


def _paint_kiko(f, pose, look: Look) -> None:
    hx = look.head_dx
    # Back to front: the fronds, the tail and hind legs, the body, the head.
    _draw_fronds(f, look, hx)
    tail, fin = _tail(look.tail)
    colors = bp.shade(tail, SKIN, light=SKIN_LIGHT, dark=SKIN_DARK, dark_depth=1)
    colors.update({p: FIN for p in fin})
    f.part(tail | fin, colors)
    if not look.held:
        for mirror in (False, True):
            leg, toes = _leg()
            _paint_limb(f, leg, toes, mirror)
    else:
        # Dangling: the hind feet hang down, toes pointing at the floor.
        for mirror in (False, True):
            leg = bp.ellipse(18.5, 45.5, 1.7, 2.4)
            _paint_limb(f, leg, {(17, 48), (19, 48)} - leg, mirror)
    body = _body()
    colors = bp.shade(body, SKIN, light=SKIN_LIGHT, dark=SKIN_DARK, dark_depth=2)
    belly = bp.ellipse(CX, 40.0, 5.0, 3.6) & bp.eroded(body, 1)
    colors.update({p: BELLY for p in belly})
    f.part(body, colors)
    head = bp.shifted(_head(), hx, 0)
    colors = bp.shade(head, SKIN, light=SKIN_LIGHT, dark=SKIN_DARK, dark_depth=2)
    f.part(head, colors)
    inner = bp.eroded(head, 1)
    shine = {(15 + hx, 18), (16 + hx, 17), (17 + hx, 17), (18 + hx, 17)}
    f.paint(shine & inner, bp.FX_WHITE)
    if look.back:
        # The back of the head: a darker crown stripe instead of a face.
        f.paint(bp.rect(19 + hx, 18, 28 + hx, 18) & inner, SKIN_DARK)
    else:
        _face(f, pose, look, hx)
    # Front limbs over the body (at work they reach round the laptop instead).
    if pose.state != "working":
        _paint_limb(f, *_arm(look.arm_l), False)
        _paint_limb(f, *_arm(look.arm_r), True)


EYES = None  # set in design (needs bp.EyeStyle)


def _face(f, pose, look: Look, hx: int) -> None:
    bp.draw_eyes(f, pose.eyes, (15 + hx, 21), (30 + hx, 21), EYES)
    cheek = {
        "pink": CHEEK,
        "pale": CHEEK_PALE,
    }[look.cheek]
    cheeks = bp.rect(12 + hx, 26, 14 + hx, 26) | bp.rect(33 + hx, 26, 35 + hx, 26)
    f.paint(cheeks, cheek)
    _mouth(f, pose.mouth, hx)


#: The wide axolotl grin, 10 px across, centred under the eyes.
_SMILE = ("#........#", ".##....##.", "...####...")
_SMILE_BIG = ("#........#", "#........#", ".##....##.", "...####...")


def _mouth(f, style: str, hx: int) -> None:
    x = 19 + hx
    if style == "rest":
        f.paint(bp.from_rows(x, 26, _SMILE), INK)
    elif style == "smile":
        f.paint(bp.from_rows(x, 26, _SMILE), INK)
        f.paint(bp.rect(x + 3, 27, x + 6, 27), bp.TONGUE)
    elif style == "pucker":
        f.paint(bp.from_rows(x + 3, 26, (".##.", "#..#", ".##.")), INK)
    elif style == "closed":
        f.paint(bp.from_rows(x, 27, ("#........#", ".########.")), INK)
    elif style == "frown":
        f.paint(bp.from_rows(x + 2, 27, ("..##..", ".#..#.", "#....#")), INK)
    else:
        bp.draw_mouth(f, style, x + 2, 27, 6, color=INK)
        f.paint({(x, 26), (x + 9, 26), (x + 1, 27), (x + 8, 27)}, INK)


def draw_kiko(f, pose) -> None:
    look = _look(pose)
    with f.offset(pose.dx, pose.dy):
        _paint_kiko(f, pose, look)
        if pose.state == "working":
            _laptop(f, pose)


# ---------------------------------------------------------------------------
# Per-state looks and poses.
# ---------------------------------------------------------------------------

#: Idle: a slow ripple through the fronds and a lazy tail.
_IDLE_WAVE = (0, 3, 6, 6, 3, 0, -3)
_IDLE_TAIL = (0, 0, 1, 1, 1, 0, 0)
#: Working: which hand is down on the keys per frame.
_TAPS = "LRL.RLR."
_SLEEP_FLOAT = (0, 0, -1, -1, 0, 0)
#: Held: the tail wiggles up and down while Kiko dangles.
_HELD_TAIL = (5, 1, -2, 1, 5, 2)


def kiko_pose(state: str, i: int):
    pose = bp.base_pose(state, i)
    if state == "idle" and pose.eyes != "closed":
        return replace(pose, mouth="rest")
    if state == "thinking":
        return replace(pose, mouth="rest")
    if state == "success":
        return replace(pose, mouth="smile" if i not in (2, 3, 4) else "open")
    if state == "sleeping":
        return replace(pose, dy=_SLEEP_FLOAT[i], mouth="rest")
    if state == "searching":
        return replace(pose, mouth="rest")
    if state == "held":
        return replace(pose, dy=-3, mouth="pucker" if i % 3 == 2 else "half")
    if state == "working":
        # No nod: the feet and the laptop stay on the ground.
        return replace(pose, dy=0, mouth="rest")
    return pose


def _look(pose) -> Look:
    if pose.act:
        return _ACT_LOOKS[pose.act](pose.i)
    s, i = pose.state, pose.i
    if s == "idle":
        if i >= len(_IDLE_WAVE):
            return Look()
        w = _IDLE_WAVE[i]
        return Look(wave_l=(w, w * 0.6, w * 0.3), wave_r=(w, w * 0.6, w * 0.3), tail=_IDLE_TAIL[i])
    if s == "listening":
        fan = (0.6, 1.0, 1.3, 1.3, 1.0, 0.8)[i % 6]
        return Look(spread=fan, wave_l=(4, 0, 0), wave_r=(4, 0, 0), tail=1)
    if s == "thinking":
        return Look(glow=i + 1, spread=0.2, tail=i % 4 // 2)
    if s == "talking":
        return Look(spread=(0.0, 0.3, 0.6, 1.0)[i], tail=i // 2)
    if s == "success":
        up = i in (1, 2, 3, 4, 5)
        return Look(
            spread=1.6 if up else 0.8,
            wave_l=(8, 6, 4) if up else (0, 0, 0),
            wave_r=(8, 6, 4) if up else (0, 0, 0),
            arm_l="up" if up else "rest",
            arm_r="up" if up else "rest",
            tail=3 if up else 1,
        )
    if s == "error":
        return Look(droop=(0.7, 0.9, 1.0, 1.0, 1.1, 1.1)[i], spread=-0.5, cheek="pale", tail=-2)
    if s == "sleeping":
        return Look(droop=0.5, spread=-0.3, tail=-1, wave_l=(0, 0, _SLEEP_FLOAT[i] * 4))
    if s == "working":
        tap = _TAPS[i % len(_TAPS)]
        return Look(
            arm_l="type_down" if tap == "L" else "type_up",
            arm_r="type_down" if tap == "R" else "type_up",
            tail=i % 2,
        )
    if s == "searching":
        return Look(spread=0.5, arm_r="hug")
    if s == "held":
        return Look(
            held=True,
            droop=-0.4,
            spread=1.0,
            arm_l="dangle",
            arm_r="dangle",
            wave_l=(bp.HELD_SWAY[i] * 6,) * 3,
            wave_r=(-bp.HELD_SWAY[i] * 6,) * 3,
            tail=_HELD_TAIL[i % len(_HELD_TAIL)],
        )
    return Look()


def _laptop(f, pose) -> None:
    """A laptop in front: the lid hides the belly, the little hands reach round
    its sides and tap the keyboard, one key lighting up under each tap."""
    bp.fx_laptop(f, pose.i, 17, 36)
    tap = _TAPS[pose.i % len(_TAPS)]
    for side, mirror in (("L", False), ("R", True)):
        down = tap == side
        arm, fingers = _arm("type_down" if down else "type_up")
        _paint_limb(f, arm, fingers, mirror)
        if down:
            f.paint({(19, 44) if side == "L" else (28, 44)}, bp.FX_WHITE)


# ---------------------------------------------------------------------------
# Effects.
# ---------------------------------------------------------------------------


def _bubble(f, cx: int, cy: int, size: int) -> None:
    """A see-through bubble: a dot, a pair, or a ring with a shine."""
    if size <= 0:
        f.part({(cx, cy)}, BUBBLE)
        return
    if size == 1:
        dot = bp.rect(cx, cy, cx + 1, cy + 1)
        f.part(dot, BUBBLE)
        f.paint({(cx, cy)}, BUBBLE_SHINE)
        return
    disc = bp.ellipse(cx + 0.5, cy + 0.5, size, size)
    ring = disc - bp.eroded(disc, 1)
    f.paint(bp.outer_ring(disc), bp.OUTLINE)
    f.paint(ring, BUBBLE)
    top = min(y for _, y in ring)
    f.paint({p for p in ring if p[1] <= top + 1 and p[0] < cx}, BUBBLE_SHINE)


def kiko_success(f, pose) -> None:
    """Bubbles stream up from both sides of the hop, sparkles at the top."""
    i = pose.i
    for x, start, size in ((6, 0, 2), (40, 1, 1), (9, 3, 1), (38, 4, 2)):
        age = i - start
        if 0 <= age <= 4:
            _bubble(f, x + (age % 2), 40 - 6 * age, size if age else 0)
    bp.fx_sparkles(f, i, ((CX, 5, 2), (5, 20, 3), (42, 18, 4)))


def kiko_sleeping(f, pose) -> None:
    """Slow bubbles rising from the smile, one at a time, and a sleepy z."""
    i, dy = pose.i, pose.dy
    for start in (0, 3):
        age = (i - start) % 6
        if age <= 4:
            _bubble(f, 31 + (age % 2), 24 + dy - 4 * age, min(2, age))
    bp.fx_zzz(f, i, 36, 15)


def kiko_working(f, pose) -> None:
    """The laptop is part of the body drawing (the hands sit on its keys)."""


def kiko_held(f, pose) -> None:
    """Swing streaks on the trailing side and two startled marks."""
    sway = bp.HELD_SWAY[pose.i % len(bp.HELD_SWAY)]
    x = pose.dx
    if sway < 0:
        f.paint(bp.line(41 + x, 34, 41 + x, 39) | bp.line(43 + x, 35, 43 + x, 38), bp.ARC_FADE)
    elif sway > 0:
        f.paint(bp.line(6 + x, 34, 6 + x, 39) | bp.line(4 + x, 35, 4 + x, 38), bp.ARC_FADE)
    if pose.i % 3 != 2:
        f.paint(bp.line(17 + x, 10, 15 + x, 8) | bp.line(30 + x, 10, 32 + x, 8), bp.ARC)


# ---------------------------------------------------------------------------
# Idle acts.
# ---------------------------------------------------------------------------


def _act_pose(name: str, rows):
    """An act's pose function from (dx, dy, eyes, mouth) rows."""

    def pose(i: int):
        dx, dy, eyes, mouth = rows[i]
        return bp.Pose("idle", i, dx=dx, dy=dy, eyes=eyes, mouth=mouth, act=name)

    return pose


# bubble_blow: a breath, a pucker, a bubble swells in front of Kiko's chest,
# floats up over the head and pops; Kiko watches it all the way.
_BLOW = (
    (0, 0, "open", "rest"),
    (0, 0, "closed", "closed"),
    (0, 0, "down", "pucker"),
    (0, 0, "down", "pucker"),
    (0, 0, "down", "pucker"),
    (0, 0, "up_right", "rest"),
    (0, 0, "wide", "open"),
    (0, 0, "happy", "smile"),
)
#: The bubble per frame: (centre x, centre y, radius); radius 0 = no bubble.
_BLOW_BUBBLE = (
    (0.0, 0.0, 0.0),
    (0.0, 0.0, 0.0),
    (24.0, 31.5, 1.5),
    (24.0, 33.0, 2.6),
    (24.0, 34.0, 3.6),
    (26.0, 9.0, 3.6),
    (0.0, 0.0, 0.0),
    (0.0, 0.0, 0.0),
)
_POP = (26.0, 8.0)


def _blow_look(i: int) -> Look:
    return Look(spread=0.8 if i == 6 else 0.0, wave_l=(4, 2, 0) if i == 7 else (0, 0, 0))


def act_bubble_blow(f, pose) -> None:
    i = pose.i
    cx, cy, r = _BLOW_BUBBLE[i]
    if r:
        disc = bp.ellipse(cx, cy, r, r)
        ring = disc - bp.eroded(disc, 1)
        f.paint(bp.outer_ring(disc), bp.OUTLINE)
        f.paint(ring, BUBBLE)
        top = min(y for _, y in ring)
        f.paint({p for p in ring if p[1] <= top + 1 and p[0] < cx - 1}, BUBBLE_SHINE)
        return
    if i == 6:
        px, py = _POP
        for k in range(8):
            ang = 2.0 * math.pi * k / 8
            c, s = round(math.cos(ang), 6), round(math.sin(ang), 6)
            a = (math.floor(px + c * 3.5), math.floor(py + s * 3.5))
            b = (math.floor(px + c * 5.5), math.floor(py + s * 5.5))
            f.paint(bp.line(*a, *b), bp.ARC if k % 2 else bp.ARC_FADE)
    if i == 7:
        for x, y, size in ((31, 6, 1), (19, 4, 0), (36, 10, 0)):
            _bubble(f, x, y, size)


# frond_wave: a ripple runs down the left fronds, then the right ones.
_Z3 = (0, 0, 0)
_WAVE_L = (_Z3, (20, 6, 0), (10, 20, 6), (0, 10, 20), (0, 0, 10), _Z3, _Z3, _Z3)
_WAVE_R = (_Z3, _Z3, _Z3, _Z3, (20, 6, 0), (10, 20, 6), (0, 10, 20), _Z3)
_WAVE_FACE = (
    (0, 0, "open", "rest"),
    (0, 0, "look_left", "rest"),
    (0, 0, "look_left", "smile"),
    (0, 0, "look_left", "smile"),
    (0, 0, "look_right", "smile"),
    (0, 0, "look_right", "smile"),
    (0, 0, "look_right", "rest"),
    (0, 0, "happy", "smile"),
)


def _wave_look(i: int) -> Look:
    return Look(wave_l=_WAVE_L[i], wave_r=_WAVE_R[i])


def act_frond_wave(f, pose) -> None:
    i = pose.i
    if i in (2, 3):
        f.paint({(2, 14 + i), (3, 13 + i)}, bp.ARC_FADE)
    if i in (5, 6):
        f.paint({(45, 14 + i - 3), (44, 13 + i - 3)}, bp.ARC_FADE)
    if i == 7:
        bp.fx_sparkles(f, 1, ((CX, 8, 0),))


# tail_swish: the tail flicks up and down; little water swirls follow it.
_SWISH_TAIL = (0, 4, 8, 3, -3, 6, 2, 0)
_SWISH_FACE = (
    (0, 0, "open", "rest"),
    (0, 0, "look_right", "rest"),
    (0, 0, "look_right", "smile"),
    (0, 0, "look_right", "smile"),
    (0, 0, "happy", "smile"),
    (0, 0, "look_right", "smile"),
    (0, 0, "happy", "smile"),
    (0, 0, "open", "rest"),
)


def _swish_look(i: int) -> Look:
    return Look(tail=_SWISH_TAIL[i], wave_r=(0, 2 * (i % 2), 4 * (i % 2)))


def act_tail_swish(f, pose) -> None:
    i = pose.i
    tip_y = 38 - _SWISH_TAIL[i]
    prev = _SWISH_TAIL[i - 1] if i else 0
    if _SWISH_TAIL[i] != prev:
        direction = 1 if _SWISH_TAIL[i] < prev else -1
        f.paint(bp.line(45, tip_y - 2 * direction, 45, tip_y - 4 * direction), bp.ARC_FADE)
    if i in (3, 4, 5):
        _bubble(f, 44, 30 - 3 * (i - 3), 0 if i == 3 else 1)


# smile_wiggle: the head bobs side to side with a widening grin, hearts float up.
_WIGGLE_DX = (0, -1, 0, 1, 0, -1, 1, 0)
_WIGGLE_FACE = (
    (0, 0, "open", "rest"),
    (0, 0, "happy", "smile"),
    (0, -1, "happy", "smile"),
    (0, 0, "happy", "smile"),
    (0, -1, "happy", "smile"),
    (0, 0, "happy", "smile"),
    (0, -1, "happy", "smile"),
    (0, 0, "open", "smile"),
)


def _wiggle_look(i: int) -> Look:
    d = _WIGGLE_DX[i]
    return Look(
        head_dx=d, wave_l=(-4 * d, -3 * d, -2 * d), wave_r=(4 * d, 3 * d, 2 * d), tail=i % 2
    )


_HEART = ("#.#", "###", ".#.")


def act_smile_wiggle(f, pose) -> None:
    hearts = {2: ((40, 14),), 3: ((41, 10), (5, 16)), 4: ((42, 6), (4, 12)), 5: ((3, 8),)}
    for x, y in hearts.get(pose.i, ()):
        f.glyph(x, y, _HEART, {"#": HEART})


# regenerate_sparkle: a short frond sparkles and grows back to full length.
_REGEN_LEN = (3, 3, 4, 5, 6, 7, 7, 7)
_REGEN_FACE = (
    (0, 0, "up_left", "rest"),
    (0, 0, "up_left", "closed"),
    (0, 0, "closed", "closed"),
    (0, 0, "closed", "closed"),
    (0, 0, "up_left", "rest"),
    (0, 0, "wide", "open"),
    (0, 0, "happy", "smile"),
    (0, 0, "open", "rest"),
)


def _regen_look(i: int) -> Look:
    n = _REGEN_LEN[i]
    return Look(len_l=(n, _FROND_LEN, _FROND_LEN), wave_l=(6, 0, 0) if i in (5, 6) else (0, 0, 0))


def act_regenerate_sparkle(f, pose) -> None:
    i = pose.i
    a = math.radians(_ANGLES[0])
    n = _REGEN_LEN[i]
    tip = (
        math.floor(_ROOTS[0][0] + 0.5 + math.cos(a) * (n + 2)),
        math.floor(_ROOTS[0][1] + 0.5 + math.sin(a) * (n + 2)),
    )
    if 1 <= i <= 5:
        bp.fx_sparkles(f, (i - 1) % 3 + 1, ((tip[0], tip[1], 0),))
    if i == 6:
        bp.fx_sparkles(f, 1, ((6, 26, 0), (CX, 6, 0)))
    if i == 7:
        bp.fx_sparkles(f, 3, ((6, 26, 0), (CX, 6, 0)))


# float_spin: Kiko floats up, turns a full circle and drifts back down.
_SPIN = (1.0, 1.0, 0.6, 0.2, 0.6, 1.0, 1.0, 1.0)
_SPIN_FACE = (
    (0, 0, "open", "rest"),
    (0, -2, "happy", "smile"),
    (0, -4, "happy", "smile"),
    (0, -5, "happy", "smile"),
    (0, -5, "happy", "smile"),
    (0, -4, "happy", "smile"),
    (0, -2, "open", "smile"),
    (0, 0, "happy", "rest"),
)


def _spin_look(i: int) -> Look:
    return Look(back=i == 4, spread=0.6 if 1 <= i <= 6 else 0.0, tail=2 if 1 <= i <= 6 else 0)


def act_float_spin(f, pose) -> None:
    i = pose.i
    if 2 <= i <= 4:
        f.paint(bp.line(8, 30, 12, 30) | bp.line(35, 30, 39, 30), bp.ARC_FADE)
    for x, start in ((10, 1), (36, 2), (22, 4)):
        age = i - start
        if 0 <= age <= 3:
            _bubble(f, x, 44 - 5 * age, min(2, age))


def kiko_post(img, pose):
    if pose.act == "float_spin":
        return bp.squash_x(img, _SPIN[pose.i])
    return img


_ACT_LOOKS = {
    "bubble_blow": _blow_look,
    "frond_wave": _wave_look,
    "tail_swish": _swish_look,
    "smile_wiggle": _wiggle_look,
    "regenerate_sparkle": _regen_look,
    "float_spin": _spin_look,
}


def design(bp_module):
    global bp, EYES
    bp = bp_module
    EYES = bp.EyeStyle(w=3, h=4, iris=INK, glint=bp.FX_WHITE, lid=INK)
    acts = (
        bp.IdleAct("bubble_blow", 8, 8, _act_pose("bubble_blow", _BLOW), act_bubble_blow),
        bp.IdleAct("frond_wave", 8, 8, _act_pose("frond_wave", _WAVE_FACE), act_frond_wave),
        bp.IdleAct("tail_swish", 8, 9, _act_pose("tail_swish", _SWISH_FACE), act_tail_swish),
        bp.IdleAct("smile_wiggle", 8, 8, _act_pose("smile_wiggle", _WIGGLE_FACE), act_smile_wiggle),
        bp.IdleAct(
            "regenerate_sparkle",
            8,
            7,
            _act_pose("regenerate_sparkle", _REGEN_FACE),
            act_regenerate_sparkle,
        ),
        bp.IdleAct("float_spin", 8, 9, _act_pose("float_spin", _SPIN_FACE), act_float_spin),
    )
    return bp.PetDesign(
        id="kiko",
        name="Kiko",
        description=(
            "A dreamy pink axolotl whose gill fronds fan out to listen and glow as it thinks."
        ),
        draw=draw_kiko,
        anchors=bp.Anchors(
            arcs_left=(8, 11),
            arcs_right=(39, 11),
            dots=(19, 6),
            zzz=(36, 15),
            bang=(40, 3),
            sweat=(36, 13),
            sparkles=((CX, 5, 2), (5, 20, 3), (42, 18, 4)),
            laptop=(17, 36),
            magnifier=(CX, 38),
        ),
        pose=kiko_pose,
        waist=44,
        post=kiko_post,
        fx={
            "success": kiko_success,
            "sleeping": kiko_sleeping,
            "working": kiko_working,
            "held": kiko_held,
        },
        acts=acts,
    )
