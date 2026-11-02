"""Sprout: a little forest plant spirit.

A plump, leaf-green seedling bulb with a lighter belly, two bright leaves on
a short stem on top of its head, stubby root feet and tiny leaf arms. The head
leaves carry its mood: they perk up and open to listen, wilt and drop a leaf
when something goes wrong and fold down over its face to sleep. While it
thinks a new little leaf unfurls on the stem, and on success a flower blooms.

Built by ``scripts/pets/build_pets.py`` (``design(bp)`` gets that module).
"""

import math
from collections.abc import Callable
from dataclasses import dataclass, replace
from types import ModuleType
from typing import Any

#: The builder module, set by ``design``; every helper reaches it through here.
bp: Any = None

Px = tuple[int, int]
Mask = set[Px]


def _c(value: str) -> tuple[int, int, int, int]:
    value = value.lstrip("#")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), 255)


BODY = _c("#9bd46f")
BODY_LIGHT = _c("#c8f09a")
BODY_DARK = _c("#67a64e")
BELLY = _c("#e6f7c6")
BELLY_DARK = _c("#cbe9a4")
LEAF = _c("#3cbf5c")
LEAF_LIGHT = _c("#8ef08c")
LEAF_DARK = _c("#22883f")
STEM = _c("#4fa94a")
SHOOT = _c("#b4ec6a")
SHOOT_LIGHT = _c("#e4ffb0")
INK = _c("#2a2433")
ROOT = _c("#c99a63")
ROOT_LIGHT = _c("#ecc590")
ROOT_DARK = _c("#94643a")
PETAL = _c("#ff8fbf")
PETAL_LIGHT = _c("#ffd2e6")
PETAL_DARK = _c("#e0609a")
POLLEN = _c("#ffd23f")
POLLEN_DARK = _c("#e0a020")
WATER = _c("#7cc8ff")
WATER_LIGHT = _c("#e3f4ff")
WING = _c("#b48cff")
WING_LIGHT = _c("#e2d2ff")
SUN = _c("#ffd23f")
SUN_CORE = _c("#fff3b0")
SUN_RAY = _c("#ffb53f")
HEART = _c("#ff6f91")
HEART_LIGHT = _c("#ffd3de")
FLUFF = _c("#f7f7fb")
FLUFF_DIM = _c("#c9cfdb")

#: The top-left of each 3 x 4 eye box, and the mouth's left end and top row.
EYE_L: Px = (18, 28)
EYE_R: Px = (27, 28)
MOUTH: Px = (22, 33)
#: Where the head leaves join the stem (left, right) and the stem's top.
LEAF_ROOT_L = (23.0, 18.0)
LEAF_ROOT_R = (25.0, 18.0)
STEM_TOP = 16
#: Where the leaf arms leave the body.
ARM_ROOT_L = (14.5, 33.0)
ARM_ROOT_R = (33.5, 33.0)
ARM_LEN = 7.5


@dataclass(frozen=True)
class Look:
    """How Sprout holds itself, beyond the pose's eyes and mouth."""

    #: Head leaves: elevation in degrees above the horizontal, pointing out.
    leaves: tuple[float, float] = (35.0, 35.0)
    leaf_len: float = 11.5
    #: How far each leaf tip sags under its own weight (pixels, down).
    sag: tuple[float, float] = (0.0, 0.0)
    #: Leaves folded down in front of the face (asleep).
    front: bool = False
    #: Leaf arms: elevation in degrees, pointing out (negative hangs down).
    arms: tuple[float, float] = (-45.0, -45.0)
    #: 0 none, 1 bud, 2 opening, 3 full bloom.
    flower: int = 0
    #: 0 none .. 4 an open new leaf on the stem (thinking).
    sprout: int = 0
    #: Each root foot's drop (dangling) and how far apart they kick.
    feet: tuple[int, int] = (0, 0)
    spread: int = 0
    #: Little root tendrils under the feet (only with room below).
    roots: bool = False
    blush: bool = True


# ---------------------------------------------------------------------------
# Shapes.
# ---------------------------------------------------------------------------


def _leaf(
    root: tuple[float, float],
    elev: float,
    length: float,
    width: float,
    *,
    left: bool,
    sag: float = 0.0,
) -> tuple[Mask, Mask]:
    """A pointed leaf from ``root``: its mask and the pixels of its midrib."""
    a = math.radians(elev)
    ux = -math.cos(a) if left else math.cos(a)
    uy = -math.sin(a)
    out: Mask = set()
    rib: Mask = set()
    steps = max(6, int(length * 2))
    for k in range(steps + 1):
        t = k / steps
        x = root[0] + ux * length * t
        y = root[1] + uy * length * t + sag * t * t
        r = width * math.sin(math.pi * (0.18 + 0.82 * t) ** 1.1)
        if r < 0.7:
            out.add((math.floor(x), math.floor(y)))
        else:
            out |= bp.ellipse(x, y, r, r * 0.9)
        if 0.2 <= t <= 0.7:
            rib.add((math.floor(x), math.floor(y)))
    return out, rib


def _body() -> Mask:
    """The plump bulb: round below, a little narrower towards the stem."""
    return bp.ellipse(24, 32, 12, 9.5) | bp.ellipse(24, 27.5, 8.5, 7)


def _paint_leaves(f: Any, leaves: list[tuple[Mask, Mask]], extra: Mask = frozenset()) -> None:
    """Outline the leaves (and ``extra``, e.g. the stem) as one shape, then fill."""
    whole: Mask = set(extra)
    for mask, _rib in leaves:
        whole |= mask
    f.paint(bp.outer_ring(whole), bp.OUTLINE)
    for mask, rib in leaves:
        f.paint_map(bp.shade(mask, LEAF, light=LEAF_LIGHT, dark=LEAF_DARK, dark_depth=1))
        f.paint(rib & bp.eroded(mask, 1), LEAF_DARK)


def _head_leaves(look: Look) -> list[tuple[Mask, Mask]]:
    return [
        _leaf(LEAF_ROOT_L, look.leaves[0], look.leaf_len, 3.4, left=True, sag=look.sag[0]),
        _leaf(LEAF_ROOT_R, look.leaves[1], look.leaf_len, 3.4, left=False, sag=look.sag[1]),
    ]


def _stem() -> Mask:
    return bp.rect(23, STEM_TOP, 24, 21)


def _draw_sprout(f: Any, stage: int) -> None:
    """Thinking: a new leaf curls up from the top of the stem and unfurls."""
    if stage <= 0:
        return
    stalk = bp.rect(23, STEM_TOP - 1 - min(stage, 3), 24, STEM_TOP)
    if stage == 1:
        f.part(stalk, SHOOT)
        f.paint({(23, STEM_TOP - 2)}, SHOOT_LIGHT)
        return
    top = STEM_TOP - 1 - min(stage, 3)
    if stage == 2:
        curl = bp.from_rows(23, top - 4, (".##.", "#..#", "#.##", ".#.."))
        f.part(stalk | curl, SHOOT)
        f.paint({(24, top - 4)}, SHOOT_LIGHT)
        return
    length, width = (5.5, 2.0) if stage == 3 else (7.0, 2.5)
    elev = 70.0 if stage == 3 else 55.0
    leaf, rib = _leaf((24.5, top + 0.5), elev, length, width, left=False)
    f.part(stalk | leaf, SHOOT)
    f.paint_map(bp.shade(leaf, SHOOT, light=SHOOT_LIGHT, dark=LEAF, dark_depth=1))
    f.paint(rib & bp.eroded(leaf, 1), LEAF)


#: Petal centres around the flower's heart, as (dx, dy).
_PETALS = tuple(
    (2.6 * math.cos(math.radians(90 + 72 * k)), -2.6 * math.sin(math.radians(90 + 72 * k)))
    for k in range(5)
)


def _draw_flower(f: Any, stage: int, cx: float = 24.0, cy: float = 13.0) -> None:
    """A pink blossom on top of the stem: a bud, opening, in full bloom."""
    if stage <= 0:
        return
    if stage == 1:
        bud = bp.ellipse(cx, cy + 1.5, 1.6, 2.2)
        f.part(bud, bp.shade(bud, PETAL, light=PETAL_LIGHT, dark=PETAL_DARK, dark_depth=1))
        f.paint({(23, int(cy) + 3), (24, int(cy) + 3)}, LEAF)
        return
    r = 1.4 if stage == 2 else 1.9
    dist = 0.75 if stage == 2 else 1.0
    petals: Mask = set()
    for dx, dy in _PETALS:
        petals |= bp.ellipse(cx + dx * dist, cy + dy * dist, r, r)
    f.part(petals, bp.shade(petals, PETAL, light=PETAL_LIGHT, dark=PETAL_DARK, dark_depth=1))
    heart = bp.rect(23, int(cy) - 1, 24, int(cy))
    f.paint(heart, POLLEN)
    f.paint({(24, int(cy))}, POLLEN_DARK)


def _feet(look: Look) -> Mask:
    out: Mask = set()
    for side, cx in ((0, 19.0 - look.spread), (1, 29.0 + look.spread)):
        dy = look.feet[side]
        foot = bp.ellipse(cx, 42.0 + dy, 3.3, 2.2)
        toe = (math.floor(cx) - 3, 43 + dy) if side == 0 else (math.floor(cx) + 3, 43 + dy)
        out |= foot | {toe}
    return out


def _draw_feet(f: Any, look: Look) -> None:
    feet = _feet(look)
    if look.roots:
        for side, cx in ((0, 19 - look.spread), (1, 29 + look.spread)):
            dy = look.feet[side]
            wiggle = 1 if (dy + side) % 2 else -1
            feet |= {(cx - 1, 45 + dy), (cx - 1 + wiggle, 46 + dy)}
    f.part(feet, bp.shade(feet, ROOT, light=ROOT_LIGHT, dark=ROOT_DARK, dark_depth=1))


#: Arms raised above this elevation are drawn in front of the body.
ARM_FRONT = 10.0


def _draw_arms(f: Any, look: Look, *, front: bool) -> None:
    arms = []
    for root, elev, left in ((ARM_ROOT_L, look.arms[0], True), (ARM_ROOT_R, look.arms[1], False)):
        if (elev > ARM_FRONT) == front:
            mask, _rib = _leaf(root, elev, ARM_LEN, 2.3, left=left)
            arms.append((mask, set()))
    if arms:
        _paint_leaves(f, arms)


def _mouth(f: Any, style: str) -> None:
    x, y = MOUTH
    if style == "o":
        f.paint(bp.rect(23, y, 24, y + 1), bp.MOUTH_DARK)
        f.paint(bp.outer_ring(bp.rect(23, y, 24, y + 1)), INK)
    elif style == "puff":
        f.paint({(23, y + 1), (24, y + 1)}, INK)
    else:
        bp.draw_mouth(f, style, x, y, 4, INK)


def _draw_face(f: Any, pose: Any, look: Look) -> None:
    eyes = bp.EyeStyle(w=3, h=4, iris=INK, glint=bp.FX_WHITE, lid=INK)
    bp.draw_eyes(f, pose.eyes, EYE_L, EYE_R, eyes)
    if look.blush:
        cheek = bp.BLUSH if pose.mouth != "puff" else PETAL
        f.paint(bp.rect(14, 33, 16, 33) | bp.rect(31, 33, 33, 33), cheek)
        if pose.mouth == "puff":
            f.paint(bp.rect(15, 32, 16, 34) | bp.rect(31, 32, 32, 34), cheek)
    _mouth(f, pose.mouth)


def draw_sprout(f: Any, pose: Any) -> None:
    look = _look(pose)
    with f.offset(pose.dx, pose.dy):
        leaves = _head_leaves(look)
        if not look.front:
            _paint_leaves(f, leaves, _stem())
            f.paint(_stem(), STEM)
            f.paint({(23, STEM_TOP)}, LEAF_LIGHT)
        _draw_sprout(f, look.sprout)
        _draw_flower(f, look.flower)
        _draw_feet(f, look)
        _draw_arms(f, look, front=False)
        body = _body()
        f.part(body, bp.shade(body, BODY, light=BODY_LIGHT, dark=BODY_DARK, dark_depth=2))
        inner = bp.eroded(body, 2)
        belly = bp.ellipse(24, 38.5, 6.5, 3.6) & inner
        f.paint_map(bp.shade(belly, BELLY, dark=BELLY_DARK, dark_depth=1))
        # A dewy shine on the bulb's shoulder.
        f.paint({(16, 25), (17, 24), (18, 24), (15, 26)} & bp.eroded(body, 1), bp.FX_WHITE)
        _draw_face(f, pose, look)
        _draw_arms(f, look, front=True)
        if look.front:
            _paint_leaves(f, leaves, _stem())
            f.paint(_stem() - set().union(*(m for m, _r in leaves)), STEM)


# ---------------------------------------------------------------------------
# Poses and looks per state.
# ---------------------------------------------------------------------------

#: Idle: a gentle sway of the head leaves over the seven breathing cells.
_IDLE_SWAY = (0, 1, 2, 2, 1, 0, -1)
#: Listening: the leaves perk up and open towards the sound.
_LISTEN_LEAVES = (50.0, 60.0, 66.0, 68.0, 66.0, 62.0)
#: Thinking: the new leaf's growth stage per frame.
_THINK_SPROUT = (1, 1, 2, 2, 3, 3, 4, 4)
#: Talking: the leaves bounce higher the louder it speaks.
_TALK_LEAVES = (35.0, 39.0, 44.0, 50.0)
#: Success: the flower opens on the way up and stays in bloom.
_HOP_FLOWER = (1, 2, 3, 3, 3, 3, 3, 3)
#: Error: the leaves wilt a little more every frame.
_WILT = ((30.0, 1.0), (18.0, 3.0), (8.0, 5.0), (0.0, 8.0), (-4.0, 10.0), (-4.0, 10.0))
#: Held: the roots kick in turn.
_HELD_FEET = ((1, 2), (2, 1), (1, 2), (2, 1), (1, 2), (2, 1))


def sprout_pose(state: str, i: int) -> Any:
    pose = bp.base_pose(state, i)
    if state == "success" and 2 <= i <= 4:
        return replace(pose, mouth="open")
    if state == "error":
        return replace(pose, dy=1)
    if state == "thinking":
        return replace(pose, mouth="rest" if i >= 6 else "closed")
    return pose


def _look(pose: Any) -> Look:
    if pose.act:
        return _ACT_LOOKS[pose.act](pose.i)
    state, i = pose.state, pose.i
    if state == "idle":
        sway = _IDLE_SWAY[i] if i < len(_IDLE_SWAY) else 0
        return Look(leaves=(35.0 + 4 * sway, 35.0 - 4 * sway))
    if state == "listening":
        e = _LISTEN_LEAVES[i]
        return Look(leaves=(e, e - 2), leaf_len=11.0, arms=(-20.0, -20.0))
    if state == "thinking":
        tilt = 3.0 if i % 4 < 2 else -3.0
        return Look(leaves=(38.0 + tilt, 38.0 - tilt), sprout=_THINK_SPROUT[i])
    if state == "talking":
        e = _TALK_LEAVES[i]
        return Look(leaves=(e, e))
    if state == "success":
        air = 1 <= i <= 5
        e = 58.0 if air else 30.0
        arms = (40.0, 40.0) if air else (-25.0, -25.0)
        return Look(leaves=(e, e), flower=_HOP_FLOWER[i], arms=arms)
    if state == "error":
        e, sag = _WILT[i]
        # Limp leaves flop down over the sides of the head like sad ears; the
        # right one holds on a little longer than the left.
        return Look(
            leaves=(e, e + 6),
            sag=(sag, sag - 2),
            leaf_len=12.0,
            front=i >= 2,
            arms=(-75.0, -75.0),
            blush=False,
        )
    if state == "sleeping":
        return Look(leaves=(-62.0, -62.0), leaf_len=12.5, front=True, arms=(-60.0, -60.0))
    if state == "working":
        bob = 3.0 if i % 2 else 0.0
        return Look(leaves=(35.0 + bob, 35.0 + bob), arms=(-70.0, -70.0))
    if state == "searching":
        lean = bp.SEARCH_SWEEP[i] * 1.6
        return Look(leaves=(38.0 + lean, 38.0 - lean), arms=(-40.0, -40.0))
    if state == "held":
        return Look(
            leaves=(72.0, 72.0),
            leaf_len=11.0,
            arms=(45.0, 45.0),
            feet=_HELD_FEET[i],
            spread=i % 2,
            roots=True,
        )
    return Look()


# ---------------------------------------------------------------------------
# State effects.
# ---------------------------------------------------------------------------

_ARC_S = ((0, -2), (1, -1), (1, 0), (0, 1))
_ARC_M = ((0, -3), (1, -2), (2, -1), (2, 0), (1, 1), (0, 2))


def _arc(f: Any, x: int, y: int, arc: tuple[Px, ...], color: Any, *, left: bool) -> None:
    f.paint({(x - ax if left else x + ax, y + ay) for ax, ay in arc}, color)


def _talking_fx(f: Any, pose: Any) -> None:
    """Little ripples beside the cheeks on the louder frames."""
    i = pose.i
    with f.offset(pose.dx, pose.dy):
        if i >= 2:
            _arc(f, 9, 32, _ARC_S, bp.ARC_FADE if i == 2 else bp.ARC, left=True)
            _arc(f, 38, 32, _ARC_S, bp.ARC_FADE if i == 2 else bp.ARC, left=False)
        if i == 3:
            _arc(f, 6, 32, _ARC_M, bp.ARC_FADE, left=True)
            _arc(f, 41, 32, _ARC_M, bp.ARC_FADE, left=False)


_PETAL_FALL = ((8, 0, 1), (39, 0, 2), (12, 0, 3), (36, 0, 4))
_PETAL_GLYPHS = (("##",), ("#", "#"))


def _success_fx(f: Any, pose: Any) -> None:
    """Sparkles and pink petals fluttering down around the hop."""
    bp.fx_sparkles(f, pose.i, ((10, 12, 2), (38, 8, 3), (42, 22, 4)))
    for x, _dy, start in _PETAL_FALL:
        age = pose.i - start
        if age < 0:
            continue
        y = 18 + 4 * age
        if y > 42:
            continue
        rows = _PETAL_GLYPHS[age % 2]
        f.glyph(x + (age % 2), y, rows, {"#": PETAL})


#: A wilted leaf drifting to the ground, swaying as it falls.
_FALL = ((11, 14), (7, 19), (9, 24), (5, 29), (8, 34), (5, 40))
_FALLEN = (("..#", ".##", "##."), ("#..", "##.", ".##"))


def _error_fx(f: Any, pose: Any) -> None:
    i = pose.i
    x, y = _FALL[i]
    f.glyph(x, y, _FALLEN[i % 2], {"#": LEAF})
    with f.offset(pose.dx, pose.dy):
        bp.fx_sweat(f, i, 37, 22)


#: A vine curling up beside Sprout as it works: its path, one step per pixel.
_VINE = (
    (41, 45), (41, 44), (41, 43), (42, 42), (42, 41), (42, 40), (41, 39), (41, 38),
    (41, 37), (42, 36), (43, 35), (43, 34), (42, 33), (41, 33), (40, 34), (40, 35), (41, 35),
)
#: Little leaves along the vine: (index on the path, x offset side).
_VINE_LEAVES = ((4, 1), (9, -1))


def _working_fx(f: Any, pose: Any) -> None:
    i = pose.i
    bp.fx_laptop(f, i, 17, 34)
    # Two leaf hands tapping the keys in turn.
    for side, x in ((0, 18), (1, 28)):
        up = (i + side) % 2
        hand = bp.rect(x, 40 - up, x + 1, 41 - up)
        f.part(hand, LEAF)
        f.paint({(x, 40 - up)}, LEAF_LIGHT)
    shown = _VINE[: min(len(_VINE), 4 + 2 * i)]
    f.part(set(shown), STEM)
    for index, side in _VINE_LEAVES:
        if index < len(shown):
            vx, vy = _VINE[index]
            leaf = {(vx + side, vy), (vx + 2 * side, vy - 1), (vx + side, vy - 1)}
            f.part(leaf, LEAF)


def _sleeping_fx(f: Any, pose: Any) -> None:
    bp.fx_zzz(f, pose.i, 34, 18)


# ---------------------------------------------------------------------------
# Idle acts.
# ---------------------------------------------------------------------------


def _pose(i: int, eyes: str = "open", mouth: str = "rest", dy: int = 0, stretch: int = 0) -> Any:
    return bp.Pose("idle", i, dy=dy, eyes=eyes, mouth=mouth, stretch=stretch)


# -- bloom: a flower slowly opens on its head, then closes again.
_BLOOM = (0, 1, 2, 3, 3, 3, 2, 1)
_BLOOM_EYES = ("open", "up_left", "up_left", "happy", "happy", "happy", "open", "open")


def _bloom_pose(i: int) -> Any:
    return _pose(i, _BLOOM_EYES[i], "smile" if 3 <= i <= 5 else "rest", stretch=1 if i == 4 else 0)


def _bloom_look(i: int) -> Look:
    e = 35.0 + 6 * min(_BLOOM[i], 2)
    return Look(leaves=(e, e), flower=_BLOOM[i])


def _bloom_fx(f: Any, pose: Any) -> None:
    bp.fx_sparkles(f, pose.i, ((14, 8, 2), (34, 7, 3), (37, 17, 4)))


# -- leaf_wave: a friendly wave with the right leaf arm.
_WAVE_ARM = (-45.0, 15.0, 60.0, 30.0, 60.0, 30.0, 60.0, -20.0)


def _wave_pose(i: int) -> Any:
    eyes = "happy" if 2 <= i <= 6 else "open"
    return _pose(i, eyes, "open" if i in (2, 4) else "smile" if 1 <= i <= 6 else "rest")


def _wave_look(i: int) -> Look:
    tilt = 4.0 if 2 <= i <= 6 else 0.0
    return Look(leaves=(35.0 - tilt, 35.0 + tilt), arms=(-45.0, _WAVE_ARM[i]))


def _wave_fx(f: Any, pose: Any) -> None:
    i = pose.i
    if 2 <= i <= 6:
        color = bp.ARC if i % 2 == 0 else bp.ARC_FADE
        f.paint(bp.line(43, 23, 44, 26) | bp.line(41, 20, 43, 19), color)


# -- water_drop: a raindrop lands on its head, it drinks it up happily.
_DROP_Y = (1, 5, 9, None, None, None, None, None)
_DROP_EYES = ("up_left", "up_left", "up_left", "closed", "happy", "happy", "happy", "open")
_DROP_LEAVES = (35.0, 35.0, 35.0, 25.0, 50.0, 58.0, 52.0, 38.0)


def _drop_pose(i: int) -> Any:
    mouth = "o" if i in (1, 2) else "smile" if 4 <= i <= 6 else "rest"
    return _pose(i, _DROP_EYES[i], mouth, stretch=1 if i in (4, 5) else -1 if i == 3 else 0)


def _drop_look(i: int) -> Look:
    e = _DROP_LEAVES[i]
    return Look(leaves=(e, e), arms=(-45.0, -45.0) if i < 4 else (10.0, 10.0))


_DROP_GLYPH = (".#.", "###", "#o#", ".#.")


def _drop_fx(f: Any, pose: Any) -> None:
    i = pose.i
    palette = {"#": WATER, "o": WATER_LIGHT}
    y = _DROP_Y[i]
    if y is not None:
        f.glyph(23, y, _DROP_GLYPH, palette)
    if i == 3:
        # The splash on the stem's top.
        f.paint({(20, 13), (21, 12), (27, 13), (26, 12), (22, 11), (25, 11)}, WATER)
    if i == 4:
        f.paint({(18, 12), (19, 11), (29, 12), (28, 11)}, WATER_LIGHT)
    if 4 <= i <= 6:
        heart = ("#.#", "###", ".#.")
        f.glyph(36, 14 - (i - 4) * 2, heart, {"#": HEART})
    if i == 5:
        bp.fx_sparkles(f, 1, ((11, 20, 0),))


# -- sun_stretch: a sun peeks out, Sprout stretches up towards it.
_SUN_STRETCH = (0, 1, 1, 1, 1, 1, 0, 0)
_SUN_ARMS = (-45.0, 5.0, 35.0, 45.0, 45.0, 35.0, 5.0, -45.0)
_SUN_EYES = ("open", "up_right", "happy", "happy", "happy", "happy", "open", "open")


def _sun_pose(i: int) -> Any:
    mouth = "o" if i in (2, 3) else "smile" if i in (4, 5) else "rest"
    return _pose(i, _SUN_EYES[i], mouth, dy=-1 if 2 <= i <= 5 else 0, stretch=_SUN_STRETCH[i])


def _sun_look(i: int) -> Look:
    a = _SUN_ARMS[i]
    e = 35.0 + max(0.0, a) * 0.6
    return Look(leaves=(e, e), leaf_len=12.5 if a > 30 else 11.5, arms=(a, a))


def _sun_fx(f: Any, pose: Any) -> None:
    i = pose.i
    if i == 0 or i == 7:
        return
    cx, cy = 41.0, 6.0
    sun = bp.ellipse(cx, cy, 3.2, 3.2)
    f.part(sun, bp.shade(sun, SUN, light=SUN_CORE, dark=POLLEN_DARK, dark_depth=1))
    long = i % 2 == 0
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, 1), (1, -1), (-1, -1)):
        diag = dx != 0 and dy != 0
        r0 = 4.5 if not diag else 3.6
        r1 = r0 + (2.0 if long else 1.0)
        a = (math.floor(cx + dx * r0), math.floor(cy + dy * r0))
        b = (math.floor(cx + dx * r1), math.floor(cy + dy * r1))
        ray = {(x, y) for x, y in bp.line(*a, *b) if 0 <= x < 48 and 0 <= y < 48}
        f.paint(ray, SUN_RAY)


# -- butterfly_visit: a butterfly lands on its left leaf, then flies off.
_FLY = ((1, 24), (4, 17), (7, 11), (9, 6), (9, 6), (9, 6), (20, 2), (34, 5))
_FLY_EYES = ("look_left", "look_left", "up_left", "up_left", "up_left", "up_left", "up_right",
             "look_right")
_WINGS_OPEN = ("ww...ww", "wowbwow", "wwwbwww", ".wwbww.", "..w.w..")
_WINGS_SHUT = ("..w.w..", ".wwbww.", "..owo..", "...b...", ".......")


def _fly_pose(i: int) -> Any:
    mouth = "o" if i == 3 else "smile" if 4 <= i <= 6 else "rest"
    return _pose(i, _FLY_EYES[i], mouth)


def _fly_look(i: int) -> Look:
    # The left leaf dips a little under the butterfly's weight.
    left = 28.0 if 3 <= i <= 5 else 35.0
    return Look(leaves=(left, 35.0))


def _fly_fx(f: Any, pose: Any) -> None:
    i = pose.i
    x, y = _FLY[i]
    landed = 3 <= i <= 5
    rows = _WINGS_SHUT if (i % 2 == 1 if not landed else i != 4) else _WINGS_OPEN
    f.glyph(x, y + (1 if landed else 0), rows, {"w": WING, "o": WING_LIGHT, "b": bp.OUTLINE})
    if i == 4:
        f.paint({(7, 4), (17, 4), (7, 7), (17, 7)}, bp.ARC_FADE)


# -- seed_puff: it lifts a dandelion clock and blows the seeds away.
_PUFF_ARM = (-20.0, 40.0, 50.0, 50.0, 50.0, 50.0, 30.0, -45.0)
_PUFF_FACE = (
    ("open", "rest"),
    ("up_right", "smile"),
    ("closed", "puff"),
    ("closed", "o"),
    ("closed", "o"),
    ("happy", "smile"),
    ("happy", "smile"),
    ("open", "rest"),
)
#: Seeds by (start frame, dx, dy per frame), flying off to the upper right.
_SEEDS = ((3, 3, -2), (3, 2, -1), (4, 3, -1), (4, 2, -3), (5, 4, -2))


def _puff_pose(i: int) -> Any:
    eyes, mouth = _PUFF_FACE[i]
    return _pose(i, eyes, mouth, stretch=1 if i == 2 else 0)


def _puff_look(i: int) -> Look:
    return Look(arms=(-45.0, _PUFF_ARM[i]))


def _puff_hand(i: int) -> tuple[int, int]:
    a = math.radians(_PUFF_ARM[i])
    x = ARM_ROOT_R[0] + (ARM_LEN - 1) * math.cos(a)
    y = ARM_ROOT_R[1] - (ARM_LEN - 1) * math.sin(a)
    return (math.floor(x), math.floor(y))


def _puff_fx(f: Any, pose: Any) -> None:
    i = pose.i
    if i == 7:
        return
    hx, hy = _puff_hand(i)
    top = (hx, hy - 6)
    f.part(bp.line(hx, hy - 1, *top), LEAF_DARK)
    if i <= 2:
        puff = bp.ellipse(top[0] + 0.5, top[1] - 1.5, 3.0, 3.0)
        f.part(puff, FLUFF)
        f.paint({(top[0] - 1, top[1] - 2), (top[0] + 1, top[1] - 3), (top[0], top[1])}, FLUFF_DIM)
    else:
        # What is left once the seeds have flown: a bare seed head.
        f.part({(top[0], top[1] - 1), (top[0] + 1, top[1] - 1)}, POLLEN_DARK)
    for start, sx, sy in _SEEDS:
        age = i - start
        if age < 0:
            continue
        x = top[0] + 2 + sx * (age + 1)
        y = top[1] - 2 + sy * (age + 1) + (age % 2)
        if 0 <= x < 47 and 0 <= y < 47:
            # A white tuft over its little brown seed.
            f.paint({(x, y), (x + 1, y)}, FLUFF)
            f.paint({(x, y + 1)}, ROOT_DARK)


_ACT_LOOKS: dict[str, Callable[[int], Look]] = {
    "bloom": _bloom_look,
    "leaf_wave": _wave_look,
    "water_drop": _drop_look,
    "sun_stretch": _sun_look,
    "butterfly_visit": _fly_look,
    "seed_puff": _puff_look,
}


def design(module: ModuleType) -> Any:
    global bp  # noqa: PLW0603 - the builder hands itself in at load time
    bp = module
    acts = (
        bp.IdleAct("bloom", 8, 6, _bloom_pose, _bloom_fx),
        bp.IdleAct("leaf_wave", 8, 8, _wave_pose, _wave_fx),
        bp.IdleAct("water_drop", 8, 7, _drop_pose, _drop_fx),
        bp.IdleAct("sun_stretch", 8, 6, _sun_pose, _sun_fx),
        bp.IdleAct("butterfly_visit", 8, 6, _fly_pose, _fly_fx),
        bp.IdleAct("seed_puff", 8, 7, _puff_pose, _puff_fx),
    )
    return bp.PetDesign(
        id="sprout",
        name="Sprout",
        description=(
            "A little forest plant spirit whose leaves perk up to listen and who"
            " bursts into bloom when something goes right."
        ),
        draw=draw_sprout,
        pose=sprout_pose,
        waist=40,
        anchors=bp.Anchors(
            arcs_left=(9, 28),
            arcs_right=(38, 28),
            dots=(19, 3),
            zzz=(34, 18),
            bang=(42, 6),
            sparkles=((10, 12, 2), (38, 8, 3), (42, 22, 4)),
            sweat=(37, 22),
            laptop=(17, 34),
            magnifier=(24, 30),
        ),
        fx={
            "talking": _talking_fx,
            "success": _success_fx,
            "error": _error_fx,
            "working": _working_fx,
            "sleeping": _sleeping_fx,
        },
        acts=acts,
    )
