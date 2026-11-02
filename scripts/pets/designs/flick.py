"""Flick: a little house elf helper.

A slim caramel-skinned elf in a cream shirt and a patched dark-teal work
apron, a wrench poking out of its pocket and a knitted mustard cap tipped
over one ear. Its huge pointed ears carry the mood: they shoot up and fan out
to listen, twitch while it thinks, flap on a happy jump, droop flat when
something goes wrong and fold down over it like a blanket while it sleeps.
Eager and tidy, it scrubs the floor while it works and dusts, polishes and
bows while nothing happens.

Built by ``scripts/pets/build_pets.py``: ``design(bp)`` gets that module as
``bp`` and uses its shapes, shading, poses and shared effects.
"""

import math
from dataclasses import dataclass, replace

#: The builder module, set by ``design``.
bp = None


def _hex(value: str) -> tuple[int, int, int, int]:
    value = value.lstrip("#")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16), 255)


SKIN = _hex("#d99a5b")
SKIN_LIGHT = _hex("#f2c48c")
SKIN_DARK = _hex("#a96a37")
SKIN_DEEP = _hex("#7c4824")
EAR_INNER = _hex("#e98d72")
EAR_INNER_DARK = _hex("#c06650")
NOSE = _hex("#b8723e")
NOSE_SHINE = _hex("#f7d2a2")
BLUSH = _hex("#f08a7e")
IRIS = _hex("#f0a531")
IRIS_LIGHT = _hex("#ffd877")
IRIS_DARK = _hex("#b8691c")
PUPIL = _hex("#2b1608")
SHIRT = _hex("#ecdcb8")
SHIRT_LIGHT = _hex("#f8eed6")
SHIRT_DARK = _hex("#c4ab80")
APRON = _hex("#21716b")
APRON_LIGHT = _hex("#36978e")
APRON_DARK = _hex("#14504c")
PATCH = _hex("#c8653a")
PATCH_LIGHT = _hex("#ea9363")
STITCH = _hex("#f4e8cc")
CAP = _hex("#e6b42e")
CAP_LIGHT = _hex("#f8d873")
CAP_DARK = _hex("#b07f14")
POMPOM = _hex("#fbf1d6")
BOOT = _hex("#6a4330")
BOOT_LIGHT = _hex("#93644a")
BOOT_DARK = _hex("#45291c")
STEEL = _hex("#a9b1c2")
STEEL_LIGHT = _hex("#e1e6ef")
WOOD = _hex("#9a6238")
WOOD_LIGHT = _hex("#c88b55")
FEATHER = _hex("#d0738f")
FEATHER_LIGHT = _hex("#f4a9c0")
FEATHER_DARK = _hex("#9c4766")
BRISTLE = _hex("#f1d58c")
SUDS = _hex("#e9f4ff")
SUDS_SHADE = _hex("#a9cdee")
WATER = _hex("#7ec4f0")
BUCKET = _hex("#7f8aa0")
BUCKET_LIGHT = _hex("#b7c0d2")
BUCKET_DARK = _hex("#545d72")
GOLD = _hex("#ffcf45")
GOLD_LIGHT = _hex("#fff1b0")
GOLD_DARK = _hex("#c9952a")
DUST = _hex("#c9bfb3")

# ---------------------------------------------------------------------------
# Geometry (cell coordinates of the standing elf, before any offset).
# ---------------------------------------------------------------------------

#: The ear's root on the left side of the head (top and bottom corner); the
#: right ear is the mirror image.
_EAR_ROOT = ((18.0, 13.0), (18.0, 21.5))
#: Left-ear shapes: (tip, bulge). The bulge pushes the upper edge out, so a
#: bigger one is a fanned-out ear.
_EARS: dict[str, tuple[tuple[float, float], float]] = {
    "rest": ((2.5, 10.5), 2.0),
    "lift": ((3.0, 6.0), 2.2),
    "twitch": ((2.0, 8.0), 2.0),
    "perk": ((6.5, 1.5), 3.6),
    "fan": ((5.0, 2.5), 4.2),
    "low": ((3.0, 16.5), 1.8),
    "droop": ((4.0, 27.0), 1.6),
    "flap_up": ((3.5, 5.5), 2.4),
    "flap_down": ((3.5, 21.0), 2.0),
    "forward": ((10.0, 24.0), 1.6),
}
_EYE_AT = ((17, 16), (26, 16))
#: Where the 3 x 4 pupil sits in the 5 x 6 eye box per look.
_PUPIL = {
    "open": (1, 1),
    "wide": (1, 2),
    "look_left": (0, 1),
    "look_right": (2, 1),
    "up_left": (0, 0),
    "up_right": (2, 0),
    "down": (1, 2),
}
#: Closed-eye shapes on the 5 x 6 box (the right eye is mirrored).
_LIDS = {
    "closed": (".....", ".....", ".....", "#...#", ".###.", "....."),
    "sleep": (".....", ".....", ".....", "#...#", ".###.", "....."),
    "happy": (".....", ".###.", "#...#", ".....", ".....", "....."),
}
_SHOULDERS = ((18.5, 29.0), (29.5, 29.0))
_REST_HANDS = ((15.5, 37.0), (32.5, 37.0))
_GROUND = 45


@dataclass(frozen=True)
class _Look:
    """How the elf holds itself beyond the pose's eyes and mouth."""

    ears: tuple[str, str] = ("rest", "rest")
    #: The head's offset from the body.
    head: tuple[int, int] = (0, 0)
    #: Each hand's centre and an optional elbow; None hangs it at the side.
    hands: tuple[tuple | None, tuple | None] = (None, None)
    elbows: tuple[tuple | None, tuple | None] = (None, None)
    #: The cap's offset from the head and its extra tilt (radians).
    cap: tuple[int, int] = (0, 0)
    cap_tilt: float = 0.0
    brows: str = "rest"
    blush: bool = True
    #: The wrench stays in the apron pocket.
    wrench: bool = True
    #: How far the boots hang below the ground (held) and spread apart.
    feet_drop: int = 0
    feet_spread: int = 0
    #: Torso and head pushed down (a crouch).
    crouch: int = 0
    #: Which hands are pressed over the eyes as open palms: (left, right).
    cover: tuple[bool, bool] = (False, False)
    #: A prop in the right hand: "", "duster", "rag", "cup".
    prop: str = ""
    prop_at: tuple[float, float] = (0.0, 0.0)
    prop_angle: float = 0.0


# ---------------------------------------------------------------------------
# Parts.
# ---------------------------------------------------------------------------


def _fill(f, mask, base, light, dark, depth=1):
    f.part(mask, bp._shade(mask, base, light, dark, depth))


def _edge_point(x, y, ex, ey, nx, ny, bulge, t):
    """A point ``t`` of the way along an edge, pushed ``bulge`` px along its normal."""
    lift = bulge * math.sin(math.pi * t)
    return (x + ex * t + nx * lift, y + ey * t + ny * lift)


def _ear_mask(name, *, right=False):
    """A big bat-like ear: a long point with a fanned upper edge and a
    slightly hollow lower edge."""
    (tx, ty), bulge = _EARS[name]
    (r0x, r0y), (r1x, r1y) = _EAR_ROOT
    # Outward normal of the upper edge (away from the lower root corner).
    ex, ey = tx - r0x, ty - r0y
    length = math.hypot(ex, ey) or 1.0
    nx, ny = -ey / length, ex / length
    if nx * (r1x - r0x) + ny * (r1y - r0y) > 0:
        nx, ny = -nx, -ny
    top = [_edge_point(r0x, r0y, ex, ey, nx, ny, bulge, t) for t in (0.0, 0.25, 0.5, 0.75)]
    bx, by = tx - r1x, ty - r1y
    blen = math.hypot(bx, by) or 1.0
    mx, my = -by / blen, bx / blen
    if mx * (r0x - r1x) + my * (r0y - r1y) < 0:
        mx, my = -mx, -my
    bottom = [_edge_point(r1x, r1y, bx, by, mx, my, 0.9, t) for t in (0.7, 0.4, 0.0)]
    mask = bp.polygon([*top, (tx, ty), *bottom])
    return bp.mirrored(mask) if right else mask


def _draw_ear(f, name, *, right=False):
    ear = _ear_mask(name, right=right)
    _fill(f, ear, SKIN, SKIN_LIGHT, SKIN_DARK, 1)
    inner = bp.eroded(ear, 2)
    # Keep the inner ear away from the root, where the head covers it.
    inner = {(x, y) for x, y in inner if (x >= 30 if right else x <= 17)}
    if inner:
        f.paint_map(bp._shade(inner, EAR_INNER, EAR_INNER, EAR_INNER_DARK, 1))


def _head_mask():
    return bp.ellipse(24, 18.8, 9.6, 7.8) | bp.ellipse(24, 22.3, 7.4, 5.4)


def _eyes(f, style):
    for side, (x, y) in enumerate(_EYE_AT):
        if style == "hidden":
            continue
        if style == "wink" and side == 1:
            rows = tuple(r[::-1] for r in _LIDS["happy"])
            f.paint(bp.from_rows(x, y, rows), bp.OUTLINE)
            continue
        if style in _LIDS:
            rows = _LIDS[style]
            if side:
                rows = tuple(r[::-1] for r in rows)
            f.paint(bp.from_rows(x, y, rows), bp.OUTLINE)
            continue
        look = "open" if style == "wink" else style
        top, h = (y - 1, 7) if look == "wide" else (y, 6)
        eye = bp._oval(x, top, 5, h)
        # A lash line over the top lifts the amber off the caramel skin.
        f.paint({p for p in bp.outer_ring(eye) if p[1] < top + 2}, bp.OUTLINE)
        f.paint(eye, IRIS)
        f.paint({p for p in eye if p[1] >= top + h - 2}, IRIS_LIGHT)
        f.paint({p for p in eye if p[1] == top}, IRIS_DARK)
        px, py = _PUPIL[look]
        px, py = x + px, top + py + (1 if look == "wide" else 0)
        f.paint(bp.rect(px, py, px + 2, py + 3), PUPIL)
        f.paint(bp.rect(px + 1, py, px + 2, py + 1), bp.FX_WHITE)
        f.paint({(px, py + 3)}, IRIS_LIGHT)


#: Left brow pixels per mood (the right one is mirrored).
_BROWS = {
    "up": ((18, 13), (19, 12), (20, 12)),
    "worried": ((19, 14), (20, 13), (21, 13)),
    "focus": ((18, 13), (19, 14), (20, 14)),
}


def _face(f, eyes, mouth, brows="rest", blush=True):
    if blush:
        f.paint({(15, 23), (16, 23), (31, 23), (32, 23)}, BLUSH)
    _eyes(f, eyes)
    if brows in _BROWS:
        left = set(_BROWS[brows])
        f.paint(left | bp.mirrored(left), SKIN_DEEP)
    # A small round nose with a shine.
    f.paint({(23, 21), (24, 21), (22, 22), (23, 22), (24, 22), (25, 22)}, NOSE)
    f.paint({(23, 21)}, NOSE_SHINE)
    _mouth(f, mouth)


def _mouth(f, style):
    x, y = 22, 24
    if style == "hidden":
        return
    if style == "rest":
        f.paint({(x + 1, y + 1), (x + 2, y + 1), (x, y), (x + 3, y)}, SKIN_DEEP)
    elif style == "grin":
        f.paint(bp.rect(x - 1, y, x + 4, y + 1) - {(x - 1, y + 1), (x + 4, y + 1)}, bp.MOUTH_DARK)
        f.paint(bp.rect(x, y, x + 3, y), bp.FX_WHITE)
        f.paint({(x + 1, y + 2), (x + 2, y + 2)}, bp.MOUTH_DARK)
        f.paint({(x + 1, y + 1), (x + 2, y + 1)}, bp.TONGUE)
    elif style == "wobble":
        f.paint({(x, y + 1), (x + 1, y), (x + 2, y + 1), (x + 3, y)}, SKIN_DEEP)
    elif style == "tongue":
        f.paint({(x, y), (x + 1, y + 1), (x + 2, y + 1), (x + 3, y)}, SKIN_DEEP)
        f.paint({(x + 3, y + 1), (x + 3, y + 2)}, bp.TONGUE)
    elif style == "o":
        f.paint(bp.rect(x + 1, y, x + 2, y + 1), bp.MOUTH_DARK)
    else:
        bp.draw_mouth(f, style, x, y, 4, SKIN_DEEP)


def _cap_parts(dx, dy, tilt):
    """The knitted cap tipped over the right ear: (cap, band, pompom, frame).

    Its brim runs down across the crown to the right ear; below the brim it
    hugs the skull, above it a low dome rises. ``frame`` is (cx, cy, d) for
    the ribbing along the brim."""
    theta = 0.36 + tilt
    cx, cy = 27.6 + dx, 12.6 + dy
    d = (math.cos(theta), math.sin(theta))
    n = (math.sin(theta), -math.cos(theta))
    a, b = 7.4, 6.0
    pts = []
    for k in range(13):
        t = math.pi * k / 12
        u, v = a * math.cos(t), b * math.sin(t)
        pts.append((cx + u * d[0] + v * n[0], cy + u * d[1] + v * n[1]))
    dome = bp.polygon(pts)
    band = set()
    for x in range(math.floor(cx - a - 2), math.ceil(cx + a + 2)):
        for y in range(math.floor(cy - a), math.ceil(cy + a)):
            u = (x + 0.5 - cx) * d[0] + (y + 0.5 - cy) * d[1]
            v = (x + 0.5 - cx) * n[0] + (y + 0.5 - cy) * n[1]
            if abs(u) <= a + 0.3 and -1.7 <= v <= 1.0:
                band.add((x, y))
    cap = dome | band
    apex = (cx + (b + 0.6) * n[0] + 1.6 * d[0], cy + (b + 0.6) * n[1] + 1.6 * d[1])
    pompom = bp.ellipse(apex[0], apex[1], 2.1, 2.1)
    return cap, band, pompom, (cx, cy, d)


def _draw_cap(f, dx, dy, tilt):
    cap, band, pompom, (cx, cy, d) = _cap_parts(dx, dy, tilt)
    colors = bp._shade(cap, CAP, CAP_LIGHT, CAP_DARK, 1)
    for x, y in cap:
        u = (x + 0.5 - cx) * d[0] + (y + 0.5 - cy) * d[1]
        v = (x + 0.5 - cx) * d[1] - (y + 0.5 - cy) * d[0]
        if (x, y) in band:
            colors[(x, y)] = CAP_DARK if math.floor(u) % 2 == 0 else CAP
        elif colors[(x, y)] == CAP and 3.0 <= v < 4.0 and math.floor(u) % 2 == 0:
            colors[(x, y)] = CAP_DARK
    f.part(cap, colors)
    _fill(f, pompom, POMPOM, bp.FX_WHITE, SHIRT_DARK, 1)


def _draw_head(f, pose, look):
    with f.offset(*look.head):
        left, right = look.ears
        _draw_ear(f, left)
        _draw_ear(f, right, right=True)
        head = _head_mask()
        _fill(f, head, SKIN, SKIN_LIGHT, SKIN_DARK, 2)
        _face(f, pose.eyes, pose.mouth, look.brows, look.blush)
        _draw_cap(f, *look.cap, look.cap_tilt)


def _limb(a, b):
    ax, ay, bx, by = (math.floor(v) for v in (*a, *b))
    return bp.thick(bp.line(ax, ay, bx, by))


def _draw_arm(f, side, hand, elbow, cover=False):
    """A thin arm: a cream sleeve to the elbow, then the bare forearm."""
    shoulder = _SHOULDERS[side]
    hand = hand or _REST_HANDS[side]
    if elbow is None:
        elbow = (
            shoulder[0] + (hand[0] - shoulder[0]) * 0.5,
            shoulder[1] + (hand[1] - shoulder[1]) * 0.5,
        )
    forearm = _limb(elbow, hand)
    _fill(f, forearm, SKIN, SKIN_LIGHT, SKIN_DARK, 1)
    sleeve = _limb(shoulder, elbow) | bp.ellipse(shoulder[0], shoulder[1] + 0.5, 1.8, 1.6)
    sleeve |= bp.ellipse(elbow[0] + 0.5, elbow[1] + 0.5, 1.5, 1.5)
    _fill(f, sleeve, SHIRT, SHIRT_LIGHT, SHIRT_DARK, 1)
    if cover:
        # A palm over the eye, fingers up.
        hx, hy = math.floor(hand[0]), math.floor(hand[1])
        palm = bp.rounded_rect(hx - 2, hy - 1, hx + 2, hy + 2, 1)
        palm |= {(hx - 2, hy - 2), (hx, hy - 2), (hx + 2, hy - 2)}
        _fill(f, palm, SKIN_LIGHT, SKIN_LIGHT, SKIN, 1)
        f.paint({(hx - 1, hy - 1), (hx + 1, hy - 1)}, SKIN_DARK)
    else:
        _fill(f, bp.ellipse(hand[0], hand[1], 1.8, 1.7), SKIN, SKIN_LIGHT, SKIN_DARK, 1)


_WRENCH = ("#.#", "###", ".#.", ".#.")


def _draw_wrench(f, x, y):
    """A tiny wrench standing in the pocket: an open jaw on a short handle."""
    f.glyph(x, y, _WRENCH, {"#": STEEL_LIGHT})
    f.paint({(x + 1, y + 2), (x + 1, y + 3)}, STEEL)


def _draw_body(f, look):
    c = look.crouch
    # Legs and boots stay planted unless dangling.
    for side in (0, 1):
        lx = 20 if side == 0 else 27
        spread = -look.feet_spread if side == 0 else look.feet_spread
        foot_y = _GROUND - 1.5 + look.feet_drop
        leg = bp.rect(lx + spread // 2, 38 + c, lx + 1 + spread // 2, math.floor(foot_y))
        _fill(f, leg, SKIN, SKIN_LIGHT, SKIN_DARK, 1)
        bx = lx + 0.5 + spread + (-1.0 if side == 0 else 1.0)
        boot = bp.ellipse(bx, foot_y + 0.3, 3.2, 2.1)
        boot |= bp.rect(lx + spread, math.floor(foot_y) - 2, lx + 1 + spread, math.floor(foot_y))
        _fill(f, boot, BOOT, BOOT_LIGHT, BOOT_DARK, 1)
    with f.offset(0, c):
        torso = {p for p in bp.ellipse(24, 33.6, 7.0, 7.0) if p[1] <= 39}
        _fill(f, torso, SHIRT, SHIRT_LIGHT, SHIRT_DARK, 1)
        skirt = bp.polygon([(19.5, 31), (28.5, 31), (30.6, 41), (17.4, 41)])
        apron = skirt | bp.rect(21, 28, 26, 31)
        colors = bp._shade(apron, APRON, APRON_LIGHT, APRON_DARK, 1)
        f.part(apron, colors)
        # Straps up over the shoulders.
        f.paint({(20, 27), (19, 26), (27, 27), (28, 26)}, APRON_DARK)
        # A patch with cross stitches, low on the left.
        patch = bp.rect(19, 36, 21, 38)
        f.part(patch, PATCH)
        f.paint({(19, 36), (21, 38)}, PATCH_LIGHT)
        f.paint({(20, 37)}, STITCH)
        # The tool pocket on the right with its stitched rim.
        if look.wrench:
            _draw_wrench(f, 24, 30)
        brush = bp.rect(27, 31, 28, 33)
        f.part(brush, {p: (BRISTLE if p[1] == 31 else WOOD) for p in brush})
        pocket = bp.rect(23, 34, 28, 37)
        f.part(pocket, bp._shade(pocket, APRON_LIGHT, APRON_LIGHT, APRON, 1))
        f.paint(bp.rect(23, 34, 28, 34), APRON_DARK)
        f.paint({(24, 36), (26, 36)}, APRON)


_GOBLET = ("#####", "#o###", ".###.", "..#..", ".###.")


def _draw_prop(f, look):
    x, y = look.prop_at
    if look.prop == "duster":
        a = look.prop_angle
        tip = (x + 6 * math.cos(a), y + 6 * math.sin(a))
        f.part(_limb((x, y), tip), WOOD)
        cx, cy = tip[0] + 2.5 * math.cos(a), tip[1] + 2.5 * math.sin(a)
        tuft = bp.ellipse(cx, cy, 3.6, 3.6)
        colors = bp._shade(tuft, FEATHER, FEATHER_LIGHT, FEATHER_DARK, 1)
        # Feather quills fanning out from the handle.
        for k in (-1, 0, 1):
            ang = a + 0.6 * k
            for r in (1.0, 2.0, 3.0):
                q = (
                    math.floor(tip[0] + (r + 0.5) * math.cos(ang)),
                    math.floor(tip[1] + (r + 0.5) * math.sin(ang)),
                )
                if q in colors:
                    colors[q] = FEATHER_DARK
        f.part(tuft, colors)
    elif look.prop == "cup":
        f.glyph(math.floor(x) - 2, math.floor(y) - 4, _GOBLET, {"#": GOLD, "o": GOLD_LIGHT})
        f.paint(
            {(math.floor(x) + 2, math.floor(y) - 3), (math.floor(x) + 1, math.floor(y) - 2)},
            GOLD_DARK,
        )
    elif look.prop == "rag":
        rag = bp.polygon([(x - 3, y - 1), (x + 2, y - 2.5), (x + 3, y + 1), (x - 1.5, y + 2)])
        f.part(rag, bp._shade(rag, SHIRT, SHIRT_LIGHT, SHIRT_DARK, 1))


def _draw_standing(f, pose, look):
    with f.offset(pose.dx, pose.dy):
        _draw_body(f, look)
        c = look.crouch
        head_look = replace(look, head=(look.head[0], look.head[1] + c))
        _draw_head(f, pose, head_look)
        for side in (0, 1):
            hand = look.hands[side]
            elbow = look.elbows[side]
            if hand is None and c:
                hand = (_REST_HANDS[side][0], _REST_HANDS[side][1] + c)
            with f.offset(0, c):
                _draw_arm(
                    f,
                    side,
                    None if hand is None else (hand[0], hand[1] - c),
                    None if elbow is None else (elbow[0], elbow[1] - c),
                    look.cover[side],
                )
        if look.prop:
            _draw_prop(f, look)


# ---------------------------------------------------------------------------
# Poses.
# ---------------------------------------------------------------------------

_IDLE_EARS = (
    ("rest", "rest"),
    ("rest", "rest"),
    ("rest", "rest"),
    ("rest", "twitch"),
    ("rest", "rest"),
    ("rest", "rest"),
    ("rest", "rest"),
)
_LISTEN_EARS = ("lift", "perk", "fan", "perk", "fan", "perk")
_THINK_EAR = ("rest", "twitch", "rest", "rest", "rest", "twitch", "rest", "twitch")
_TALK_EARS = ("rest", "rest", "lift", "lift")
_HOP = (1, -1, -3, -4, -3, -1, 1, 0)
_HOP_STRETCH = (-1, 1, 1, 0, 0, 1, -1, 0)
_HOP_EARS = ("low", "flap_down", "flap_up", "flap_down", "flap_up", "flap_down", "low", "rest")
_SCRUB = (-4, -2, 1, 4, 4, 2, -1, -4)
#: Searching: the ear on the side Flick peers towards lifts, the other sinks.
_SEARCH_EARS = {
    "look_left": ("lift", "low"),
    "look_right": ("low", "lift"),
    "open": ("rest", "rest"),
}
_HELD_EARS = ("flap_up", "flap_down", "flap_up", "flap_down", "flap_up", "flap_down")
_HELD_SWAY = (-1, 0, 1, 1, 0, -1)


def flick_pose(state, i):
    pose = bp.base_pose(state, i)
    if state == "idle":
        return replace(pose, mouth="rest")
    if state == "listening":
        return replace(pose, mouth="o" if i in (2, 3) else "closed")
    if state == "thinking":
        return replace(pose, mouth="tongue" if 2 <= i <= 5 else "closed")
    if state == "success":
        return bp.Pose(state, i, dy=_HOP[i], eyes="happy", mouth="grin", stretch=_HOP_STRETCH[i])
    if state == "error":
        return bp.Pose(state, i, dx=(-1, 1, -1, 1, 0, 0)[i], eyes="hidden", mouth="wobble")
    if state == "sleeping":
        return bp.Pose(state, i, eyes="sleep", mouth="o", stretch=bp.SLEEP_BREATH[i])
    if state == "working":
        return bp.Pose(state, i, eyes="down", mouth="tongue")
    if state == "searching":
        return replace(pose, mouth="closed")
    if state == "held":
        return bp.Pose(state, i, dx=_HELD_SWAY[i], dy=-2, eyes="wide", mouth="o")
    return pose


def _look(pose):
    s, i = pose.state, pose.i
    if s == "idle":
        ears = _IDLE_EARS[i] if i < len(_IDLE_EARS) else ("rest", "rest")
        return _Look(ears=ears)
    if s == "listening":
        e = _LISTEN_EARS[i]
        return _Look(ears=(e, e), brows="up", cap=(0, -1) if e != "lift" else (0, 0))
    if s == "thinking":
        return _Look(
            ears=("rest", _THINK_EAR[i]),
            hands=((30.5, 35.0), (25.5, 27.5)),
            elbows=((20.0, 36.0), (30.5, 34.0)),
            brows="focus",
        )
    if s == "talking":
        e = _TALK_EARS[i]
        return _Look(ears=(e, e))
    if s == "success":
        e = _HOP_EARS[i]
        up = 1 <= i <= 5
        hands = ((12.5, 22.0), (35.5, 22.0)) if up else (None, None)
        return _Look(ears=(e, e), hands=hands)
    if s == "error":
        peek = i in (3, 4)
        left = (19.5, 20.0) if not peek else (17.5, 27.0)
        return _Look(
            ears=("droop", "droop"),
            hands=(left, (28.5, 20.0)),
            elbows=((15.0, 31.0), (33.0, 31.0)),
            cover=(not peek, True),
            blush=False,
        )
    if s == "working":
        x = 24 + _SCRUB[i]
        e = "low" if i % 2 else "rest"
        return _Look(
            ears=(e, e),
            crouch=3,
            hands=((x - 2.5, 41.0), (x + 2.5, 41.0)),
            feet_spread=2,
            brows="focus",
        )
    if s == "searching":
        gx = 24 + bp.SEARCH_SWEEP[i]
        return _Look(
            ears=_SEARCH_EARS[pose.eyes],
            hands=(None, (gx + 7.5, 37.5)),
            elbows=(None, (33.0, 36.0) if gx > 22 else None),
        )
    if s == "held":
        e = _HELD_EARS[i]
        flail = i % 2 == 0
        return _Look(
            ears=(e, e),
            hands=((12.5, 29.0 if flail else 33.0), (35.5, 33.0 if flail else 29.0)),
            feet_drop=3,
            brows="up",
        )
    return _Look()


def draw_flick(f, pose):
    if pose.act:
        _ACT_DRAW[pose.act](f, pose)
    elif pose.state == "sleeping":
        _draw_sleeping(f, pose)
    else:
        _draw_standing(f, pose, _look(pose))


# ---------------------------------------------------------------------------
# Sleeping: curled up, the big ears folded down over it like a blanket.
# ---------------------------------------------------------------------------


def _blanket_ear(right=False):
    pts = [
        (18.0, 23.0),
        (11.0, 26.0),
        (7.5, 32.0),
        (8.5, 38.5),
        (14.0, 43.0),
        (21.0, 45.0),
        (29.5, 45.5),
        (22.0, 42.0),
        (18.5, 37.0),
        (18.0, 31.0),
    ]
    mask = bp.polygon(pts)
    return bp.mirrored(mask) if right else mask


def _draw_sleeping(f, pose):
    with f.offset(0, pose.dy):
        # Boots poke out at the bottom, toes up.
        for bx in (16.5, 31.5):
            boot = bp.ellipse(bx, 44.0, 3.0, 2.0)
            _fill(f, boot, BOOT, BOOT_LIGHT, BOOT_DARK, 1)
        body = bp.ellipse(24, 39.0, 9.0, 5.5)
        _fill(f, body, APRON, APRON_LIGHT, APRON_DARK, 1)
        for right in (False, True):
            ear = _blanket_ear(right)
            _fill(f, ear, SKIN, SKIN_LIGHT, SKIN_DARK, 1)
            inner = {(x, y) for x, y in bp.eroded(ear, 2) if y < 42}
            inner = bp.eroded(inner, 1) if right else inner
            f.paint_map(bp._shade(inner, EAR_INNER, EAR_INNER, EAR_INNER_DARK, 1))
        with f.offset(0, 9):
            head = _head_mask()
            _fill(f, head, SKIN, SKIN_LIGHT, SKIN_DARK, 2)
            _face(f, "sleep", "o" if pose.i in (2, 3) else "rest")
            _draw_cap(f, 1, 1, 0.25)


# ---------------------------------------------------------------------------
# Effects.
# ---------------------------------------------------------------------------


def _suds(f, x, y, r):
    bubble = bp.ellipse(x, y, r, r)
    f.part(bubble, bp._shade(bubble, SUDS, bp.FX_WHITE, SUDS_SHADE, 1))


_BUBBLES = ((0, -1, 1.2), (3, -3, 1.0), (-3, -2, 0.9))


def _working_fx(f, pose):
    """A bucket of suds beside the elf and bubbles rising off the brush."""
    i = pose.i
    x = 24 + _SCRUB[i]
    # The scrub brush under both hands.
    brush = bp.rect(x - 4, 42, x + 4, 43)
    f.part(brush, {p: (WOOD_LIGHT if p[1] == 42 else WOOD) for p in brush})
    f.paint(bp.rect(x - 4, 44, x + 4, 44) - {(x - 3 + 2 * k, 44) for k in range(4)}, BRISTLE)
    # Suds on the floor behind the brush.
    trail = -1 if _SCRUB[i] > _SCRUB[i - 1] else 1
    _suds(f, x + 6 * trail, 44.0, 1.6)
    _suds(f, x + 9 * trail, 44.5, 1.0)
    # The bucket on the left.
    bucket = bp.polygon([(2.5, 36), (11.5, 36), (10.5, 45.5), (3.5, 45.5)])
    f.part(bucket, bp._shade(bucket, BUCKET, BUCKET_LIGHT, BUCKET_DARK, 1))
    f.paint(bp.rect(3, 38, 10, 38), BUCKET_DARK)
    f.paint(bp.rect(3, 36, 10, 36), WATER)
    for k, (dx, dy, r) in enumerate(_BUBBLES):
        age = (i + 3 * k) % 8
        if age < 6:
            _suds(f, 7 + dx, 34 + dy - age, r)


def _search_fx(f, pose):
    i = pose.i
    bp.fx_magnifier(f, i, 24, 30)


def _success_fx(f, pose):
    bp.fx_sparkles(f, pose.i, FLICK_SPARKLES)


def _held_fx(f, pose):
    moving = _HELD_SWAY[pose.i] - _HELD_SWAY[pose.i - 1]
    if not moving:
        return
    x, step = (5, -2) if moving > 0 else (42, 2)
    f.paint(bp.line(x, 30, x, 35) | bp.line(x + step, 31, x + step, 34), bp.ARC_FADE)


FLICK_SPARKLES = ((6, 9, 1), (42, 8, 2), (5, 30, 3), (42, 30, 3))


# ---------------------------------------------------------------------------
# Idle acts.
# ---------------------------------------------------------------------------

_BOW_HEAD = (0, 1, 3, 5, 5, 4, 1, 0)
_BOW_CROUCH = (0, 0, 1, 2, 2, 1, 0, 0)
_BOW_EYES = ("open", "happy", "closed", "hidden", "hidden", "closed", "happy", "open")


def _bow_pose(i):
    return bp.Pose("idle", i, eyes=_BOW_EYES[i], mouth="smile" if i in (1, 6) else "rest")


def _draw_bow(f, pose):
    """A deep, polite bow: a hand on the heart, the other swept out, the
    head dipped so far the cap points at you and the ears fall forward."""
    i = pose.i
    down = _BOW_HEAD[i]
    ears = "forward" if down >= 5 else "low" if down >= 3 else "rest"
    sweep = 1 <= i <= 6
    look = _Look(
        ears=(ears, ears),
        head=(0, down - _BOW_CROUCH[i]),
        crouch=_BOW_CROUCH[i],
        hands=((10.5, 35.0) if sweep else None, (23.5, 31.5) if sweep else None),
        elbows=((14.0, 32.0) if sweep else None, (29.0, 34.0) if sweep else None),
        cap=(0, 1 if down >= 5 else 0),
        cap_tilt=0.1 if down >= 5 else 0.0,
    )
    if down >= 5:
        pose = replace(pose, mouth="hidden")
    _draw_standing(f, pose, look)


_DUST_ANGLES = (-1.3, -1.3, -1.6, -1.1, -0.8, -1.3, -1.6, -1.4)
_DUST_HAND = ((34, 31), (36, 24), (36, 22), (38, 23), (38, 25), (37, 23), (36, 22), (35, 30))
_DUST_EYES = ("open", "up_right", "up_right", "up_right", "up_right", "up_right", "up_left", "open")


def _duster_pose(i):
    return bp.Pose("idle", i, eyes=_DUST_EYES[i], mouth="smile" if 2 <= i <= 5 else "rest")


def _draw_duster(f, pose):
    i = pose.i
    hand = _DUST_HAND[i]
    look = _Look(
        hands=(None, (hand[0] + 0.5, hand[1] + 0.5)),
        elbows=(None, (33.0, 30.0) if hand[1] < 28 else None),
        prop="duster",
        prop_at=(hand[0], hand[1]),
        prop_angle=_DUST_ANGLES[i],
        ears=("rest", "low" if i in (2, 3, 6) else "rest"),
    )
    _draw_standing(f, pose, look)


#: Dust motes shaken off the duster: (x, y, first frame).
_MOTES = ((40, 9, 2), (44, 13, 3), (37, 5, 3), (42, 6, 5), (45, 10, 6), (39, 3, 6))


def _duster_fx(f, pose):
    for x, y, start in _MOTES:
        age = pose.i - start
        if 0 <= age <= 1:
            f.part({(x, y + age)}, DUST)


_WIGGLE = (
    ("lift", "low"),
    ("low", "lift"),
    ("lift", "low"),
    ("low", "lift"),
    ("flap_up", "flap_up"),
    ("fan", "fan"),
    ("lift", "lift"),
    ("rest", "rest"),
)


def _wiggle_pose(i):
    mouth = "grin" if i in (4, 5) else "smile" if 1 <= i <= 6 else "rest"
    return bp.Pose(
        "idle",
        i,
        eyes="happy" if 1 <= i <= 6 else "open",
        mouth=mouth,
        stretch=1 if i in (4, 5) else 0,
    )


def _draw_wiggle(f, pose):
    _draw_standing(f, pose, _Look(ears=_WIGGLE[pose.i]))


#: The rag circles over the goblet, then the goblet goes up to shine.
_POLISH_RAG = ((26, 30), (23, 29), (25, 28), (27, 30), (24, 31), (23, 29))


def _polish_pose(i):
    eyes = ("open", "down", "down", "down", "down", "down", "happy", "open")[i]
    mouth = "tongue" if 1 <= i <= 5 else "grin" if i == 6 else "smile"
    return bp.Pose("idle", i, eyes=eyes, mouth=mouth, stretch=1 if i == 6 else 0)


def _draw_polish(f, pose):
    i = pose.i
    if i >= 6:
        hand = (34.5, 22.0) if i == 6 else (33.5, 30.0)
        look = _Look(
            hands=(None, hand),
            elbows=(None, (33.0, 29.0) if i == 6 else None),
            prop="cup",
            prop_at=(hand[0], hand[1] - 1.5),
            ears=("lift", "lift") if i == 6 else ("rest", "rest"),
        )
        _draw_standing(f, pose, look)
        return
    rag = _POLISH_RAG[i]
    look = _Look(
        hands=((20.5, 34.0), (rag[0] + 0.5, rag[1] + 0.5)),
        elbows=(None, (31.0, 34.0)),
        prop="cup",
        prop_at=(22.5, 33.0),
    )
    _draw_standing(f, pose, look)
    with f.offset(pose.dx, pose.dy):
        _draw_prop(f, replace(look, prop="rag", prop_at=(rag[0], rag[1])))


def _polish_fx(f, pose):
    if pose.i == 6:
        bp.fx_sparkles(f, 1, ((39, 15, 0), (30, 13, 1)))
    elif pose.i == 7:
        bp.fx_sparkles(f, 3, ((38, 24, 0),))
    elif pose.i in (2, 4):
        bp.fx_sparkles(f, 0, ((19, 28, 0),))


#: The juggled tools loop in front of the apron, hand to hand under the chin.
_JUGGLE_PATH = tuple(
    (24 + 9.5 * math.cos(math.pi * (1 + k / 8)), 35 + 8.5 * math.sin(math.pi * (1 + k / 8)))
    for k in range(9)
)
_JUGGLE_HANDS = (
    ((15.5, 36.0), (32.5, 36.0)),
    ((15.5, 34.0), (32.5, 36.0)),
    ((15.5, 36.0), (32.5, 34.0)),
    ((15.5, 34.0), (32.5, 36.0)),
    ((15.5, 36.0), (32.5, 34.0)),
    ((15.5, 34.0), (32.5, 36.0)),
    ((15.5, 36.0), (32.5, 34.0)),
    (None, None),
)


def _juggle_pose(i):
    eyes = ("open", "down", "look_left", "down", "look_right", "down", "happy", "open")[i]
    return bp.Pose("idle", i, eyes=eyes, mouth="grin" if i == 6 else "o" if i in (3, 4) else "rest")


def _draw_juggle(f, pose):
    i = pose.i
    look = _Look(
        hands=_JUGGLE_HANDS[i],
        wrench=i == 7,
        ears=("lift", "lift") if i == 6 else ("rest", "rest"),
    )
    _draw_standing(f, pose, look)


_TOOLS = (
    (("#.#", "###", ".#.", ".#.", ".#."), {"#": STEEL_LIGHT}),
    (("ooo", "ooo", "###", ".#.", ".#."), {"#": WOOD_LIGHT, "o": BRISTLE}),
    ((".##.", "#oo#", "#oo#", ".##."), {"#": GOLD, "o": GOLD_LIGHT}),
)


def _juggle_fx(f, pose):
    i = pose.i
    if i == 7:
        return
    for k, (rows, palette) in enumerate(_TOOLS):
        step = (i * 2 + k * 3) % 9
        if i == 6 and step not in (0, 8):
            # Caught: everything lands back in the hands.
            step = 0 if k == 0 else 8
        x, y = _JUGGLE_PATH[step]
        f.glyph(math.floor(x) - 1, math.floor(y) - 3, rows, palette)


_TIP_HAND = (
    None,
    (32.5, 16.0),
    (32.5, 12.0),
    (32.5, 9.0),
    (32.5, 9.0),
    (32.5, 12.0),
    (33.5, 22.0),
    None,
)
_TIP_CAP = ((0, 0), (0, 0), (0, -2), (0, -4), (0, -4), (0, -1), (0, 0), (0, 0))
_TIP_TILT = (0.0, 0.0, 0.1, 0.25, 0.25, 0.05, 0.0, 0.0)


def _tip_pose(i):
    eyes = ("open", "open", "happy", "wink", "wink", "happy", "open", "open")[i]
    return bp.Pose("idle", i, eyes=eyes, mouth="smile" if 2 <= i <= 5 else "rest")


def _draw_tip(f, pose):
    i = pose.i
    hand = _TIP_HAND[i]
    look = _Look(
        hands=(None, hand),
        elbows=(None, (36.0, 24.0) if hand else None),
        cap=_TIP_CAP[i],
        cap_tilt=_TIP_TILT[i],
        ears=("rest", "low" if 1 <= i <= 6 else "rest"),
    )
    _draw_standing(f, pose, look)


_ACT_DRAW = {
    "bow": _draw_bow,
    "feather_duster": _draw_duster,
    "ear_wiggle": _draw_wiggle,
    "polish_shine": _draw_polish,
    "tool_juggle": _draw_juggle,
    "cap_tip": _draw_tip,
}


def design(module):
    global bp
    bp = module
    acts = (
        bp.IdleAct("bow", 8, 6, _bow_pose),
        bp.IdleAct("feather_duster", 8, 8, _duster_pose, _duster_fx),
        bp.IdleAct("ear_wiggle", 8, 8, _wiggle_pose),
        bp.IdleAct("polish_shine", 8, 7, _polish_pose, _polish_fx),
        bp.IdleAct("tool_juggle", 8, 8, _juggle_pose, _juggle_fx),
        bp.IdleAct("cap_tip", 8, 6, _tip_pose),
    )
    anchors = bp.Anchors(
        arcs_left=(8, 18),
        arcs_right=(39, 18),
        dots=(8, 3),
        zzz=(37, 16),
        bang=(41, 3),
        sweat=(6, 12),
        sparkles=FLICK_SPARKLES,
    )
    return bp.PetDesign(
        id="flick",
        name="Flick",
        description=(
            "A tidy house elf: its huge ears shoot up to listen and droop when things go wrong."
        ),
        draw=draw_flick,
        anchors=anchors,
        pose=flick_pose,
        fx={
            "success": _success_fx,
            "working": _working_fx,
            "searching": _search_fx,
            "held": _held_fx,
        },
        acts=acts,
        waist=38,
    )
