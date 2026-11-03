"""Aurelia: a kind, poised princess in an emerald-and-ivory ball gown.

A chibi figure that uses the full cell height: a big head with long, softly
waving chestnut-to-copper hair, a delicate gold tiara with a small sapphire,
big blue-violet eyes, and a bell skirt with gold trim that sways and flares.
The face, the hair and the gown are drawn as left halves mirrored across the
cell's centre line, so she stays perfectly symmetric; each frame's ``_Look``
moves the arms, tilts the head and swings the hair and the hem.
"""

import math
from dataclasses import dataclass, replace

Px = tuple[int, int]


@dataclass(frozen=True)
class _Look:
    """How one frame poses the figure beyond the shared ``Pose``."""

    #: Head offset from the body (a tilt or a bow).
    head: Px = (0, 0)
    #: Arm paths from each shoulder: an optional elbow, then the hand.
    left: tuple[Px, ...] = ((16, 35),)
    right: tuple[Px, ...] = ((31, 35),)
    #: Which arm is drawn in front of the head and hair (left, right).
    front: tuple[bool, bool] = (False, False)
    #: Hair swing (+ = the tips swing right).
    sway: int = 0
    #: Skirt hem swing (+ = right) and flare (+ = wider and lifted).
    hem: int = 0
    flare: int = 0
    brows: str = ""
    view: str = "front"
    sit: bool = False
    feet: bool = False
    prop: str = ""
    prop_i: int = 0
    #: Narrowing of the whole figure for a twirl: 1.0 = none.
    squash: float = 1.0
    #: Where the gleam runs along the tiara (-1 = none).
    shine: int = -1


def design(bp):
    hexc = bp.hexc
    ellipse, rect, line, polygon = bp.ellipse, bp.rect, bp.line, bp.polygon
    mirrored, thick, outer_ring = bp.mirrored, bp.thick, bp.outer_ring
    Pose = bp.Pose
    cx = bp.CX

    # -- Palette -------------------------------------------------------------
    skin = hexc("#ffe2d0")
    skin_light = hexc("#fff2e8")
    skin_shade = hexc("#f2bea6")
    skin_deep = hexc("#dd9c88")
    blush = hexc("#ff9cb0")
    blush_soft = hexc("#ffc6cf")
    lip = hexc("#e0607c")
    lip_dark = hexc("#a83450")

    hair_deep = hexc("#4a1c16")
    hair_dark = hexc("#73301f")
    hair = hexc("#9c4428")
    hair_mid = hexc("#bc5d34")
    hair_light = hexc("#da8148")
    hair_shine = hexc("#f6bb84")

    iris_dark = hexc("#33238a")
    iris = hexc("#4a3bb2")
    iris_light = hexc("#7f76e6")
    iris_glow = hexc("#b9b6ff")
    pupil = hexc("#150c30")
    glint = hexc("#ffffff")
    lash = hexc("#2a1420")

    emerald_deep = hexc("#0b3b2d")
    emerald_dark = hexc("#125e48")
    emerald = hexc("#1b8761")
    emerald_light = hexc("#35ab7b")
    emerald_shine = hexc("#7ad8a7")

    ivory = hexc("#fcf5e2")
    ivory_shade = hexc("#e7d7b2")

    gold = hexc("#f1c04b")
    gold_light = hexc("#fff1a8")
    gold_dark = hexc("#b4812a")
    sapphire = hexc("#3263e3")
    sapphire_light = hexc("#b2cdff")
    sapphire_dark = hexc("#1b3592")

    ink = hexc("#2b2440")
    paper = hexc("#fdf8ec")
    paper_shade = hexc("#e6d8bb")
    seal = hexc("#d2384e")
    feather = hexc("#f8f6ff")
    feather_shade = hexc("#c6c0e2")
    heart = hexc("#ff7aa0")
    heart_light = hexc("#ffd0dd")

    def sym(mask):
        """A left-half mask completed by its mirror image."""
        return set(mask) | mirrored(mask)

    def ramp(mask, light, base, dark, deep=None):
        """Light on the top/left inner edge, dark on the bottom/right band, a deep base rim."""
        out = {}
        for x, y in mask:
            color = base
            if deep is not None and (x, y + 1) not in mask:
                color = deep
            elif (x, y - 1) not in mask or (x - 1, y) not in mask:
                color = light
            elif (x, y + 2) not in mask or (x + 1, y) not in mask:
                color = dark
            out[(x, y)] = color
        return out

    # -- Hair ----------------------------------------------------------------

    #: Strand clumps: dark valley, base, mid, a lit ridge, mid.
    clump = (hair_dark, hair, hair_mid, hair_light, hair_light, hair_mid, hair)

    def crown_tone(mask, origin):
        """Hair radiating from the parting at ``origin``: clumps, a halo, a dark rim."""
        ox, oy = origin
        out = {}
        for x, y in mask:
            dx, dy = x + 0.5 - ox, y + 0.5 - oy
            r = math.hypot(dx, dy)
            # Mirror the angle so both sides of the parting match.
            theta = math.atan2(abs(dx), dy)
            k = theta * 2.6 + 0.1
            color = clump[int((k - math.floor(k)) * len(clump))]
            if 5.5 <= r <= 7.2 and color in (hair_mid, hair_light):
                color = hair_shine
            elif 5.0 <= r <= 7.8 and color == hair:
                color = hair_light
            if (x, y + 1) not in mask:
                color = hair_deep if color in (hair_dark, hair) else hair_dark
            out[(x, y)] = color
        return out

    def flow_tone(mask, phase=0.0):
        """Long hair falling in soft waves: vertical clumps that ripple with depth."""
        out = {}
        for x, y in mask:
            wave = 1.3 * math.sin((y + phase) / 2.7)
            rel = abs(x + 0.5 - cx)
            k = (rel + wave) / 3.4
            color = clump[int((k - math.floor(k)) * len(clump))]
            if (x, y + 1) not in mask:
                color = hair_deep
            elif (x, y + 2) not in mask and color != hair_light:
                color = hair_dark
            out[(x, y)] = color
        return out

    face = frozenset(sym(ellipse(cx, 17.8, 7.6, 7.2) | ellipse(cx, 20.6, 6.0, 5.4)))
    dome = frozenset(sym(ellipse(cx, 14.6, 10.4, 10.2)))

    #: The lower edge of the curtain bangs by distance from the parting.
    #: Uneven by a pixel here and there, so the bangs end in pointed strands.
    bangs_edge = (9.8, 10.8, 12.4, 11.6, 12.6, 13.8, 13.0, 16.4)

    def bangs_mask():
        out = set()
        for x, y in dome:
            d = int(abs(x + 0.5 - cx))
            if y < bangs_edge[min(d, len(bangs_edge) - 1)]:
                out.add((x, y))
        return out

    bangs = frozenset(bangs_mask())

    def side_lock(sway):
        """The lock falling in front of the shoulder (left side), curling at its tip."""
        s = sway * 0.5
        return polygon(
            [
                (13.4, 12),
                (17.0, 14.0),
                (16.8, 18),
                (15.6, 22),
                (16.4 + s * 0.4, 26),
                (16.2 + s * 0.8, 29.6),
                (14.6 + s, 31.8),
                (13.0 + s, 31.0),
                (14.2 + s * 0.8, 29.4),
                (13.4 + s * 0.5, 26),
                (12.4 + s * 0.2, 22),
                (12.4, 17),
            ]
        )

    def back_hair(sway, full=False):
        """The long hair behind the body, waving down past the shoulders.

        ``full`` is the hair seen from behind: one wavy curtain down the back.
        """
        left = [
            (cx, 5.0),
            (16.0, 6.6),
            (12.0, 10.5),
            (10.6, 15),
            (11.0, 19),
            (10.0, 23),
            (10.6, 27),
            (9.4, 31),
            (9.8, 34.6),
            (8.6, 37.4),
            (10.6, 38.6),
            (12.2, 37.0),
            (13.6, 38.4),
            (15.4, 36.4),
            (cx, 34.0),
        ]
        if full:
            left[-2:] = [(16.0, 37.0), (18.6, 39.0), (21.4, 37.4), (cx, 39.0)]
        right = [(2 * cx - x, y) for x, y in reversed(left[1:-1])]

        def swing(p):
            x, y = p
            return (x + sway * max(0.0, y - 18) / 14.0, y)

        return polygon([swing(p) for p in [*left, *right]])

    def draw_tiara(f, shine):
        rows_l = (
            "...g.",
            ".g.gG",
            "gGgGs",
            "dGGGs",
            ".dddd",
        )
        palette = {"g": gold_light, "G": gold, "d": gold_dark, "s": sapphire}
        x0, y0 = cx - 5, 3
        cells = {}
        for r, text in enumerate(rows_l):
            for c, mark in enumerate(text):
                if mark in palette:
                    for px in ((x0 + c, y0 + r), (2 * cx - 1 - (x0 + c), y0 + r)):
                        cells[px] = palette[mark]
        f.paint(outer_ring(set(cells)), bp.OUTLINE)
        f.paint_map(cells)
        # The sapphire: a lit facet top left, a deep one bottom right.
        f.paint({(cx - 1, y0 + 2)}, sapphire_light)
        f.paint({(cx, y0 + 3)}, sapphire_dark)
        if shine >= 0:
            gx = x0 + shine
            f.paint({(gx, y0 + 3), (gx + 1, y0 + 2)}, glint)

    # -- Face ------------------------------------------------------------------

    #: Left eyes, five columns from x=17; the right eye is the mirror image.
    eye_rows = {
        "open": (
            "LLLLL",
            "DWWDD",
            "DWWPD",
            "DIPPD",
            "DlliD",
            ".DDD.",
        ),
        "wide": (
            "LLLLL",
            "DWWDD",
            "DWWPD",
            "DIPPD",
            "DIPPD",
            "DlliD",
            ".DDD.",
        ),
        "up": (
            "LLLLL",
            "DWPPD",
            "DWPPD",
            "DIIID",
            "DlliD",
            ".DDD.",
        ),
        "down": (
            ".....",
            ".....",
            "LLLLL",
            "DIPPD",
            "DlPPD",
            ".DDD.",
        ),
        "closed": (
            ".....",
            ".....",
            ".....",
            "LLLLL",
            ".L..L",
            ".....",
        ),
        "sleep": (
            ".....",
            ".....",
            ".....",
            "L....",
            ".LLLL",
            ".....",
        ),
        "happy": (
            ".....",
            ".....",
            "..LL.",
            ".L..L",
            "L....",
            ".....",
        ),
        "worry": (
            ".....",
            "LLLL.",
            "DWWDL",
            "DWWPD",
            "DlliD",
            ".DDD.",
        ),
    }
    eye_palette = {
        "L": lash,
        "W": glint,
        "w": iris_glow,
        "I": iris,
        "D": iris_dark,
        "P": pupil,
        "l": iris_light,
        "i": iris_glow,
    }
    eye_names = {
        "open": "open",
        "wide": "wide",
        "up_left": "up",
        "up_right": "up",
        "look_left": "open",
        "look_right": "open",
        "down": "down",
        "closed": "closed",
        "sleep": "sleep",
        "happy": "happy",
        "x": "worry",
        "worry": "worry",
    }

    def draw_eyes(f, style):
        name = eye_names.get(style, "open")
        look = 0
        if style in ("up_left", "look_left"):
            look = -1
        elif style in ("up_right", "look_right"):
            look = 1
        x, y = 17, 14
        for r, text in enumerate(eye_rows[name]):
            for c, mark in enumerate(text):
                if mark not in eye_palette:
                    continue
                shift = look if mark in "PW" else 0
                lx = x + c + shift
                rx = 2 * cx - 1 - (x + c) + shift
                f.paint({(lx, y + r), (rx, y + r)}, eye_palette[mark])

    def draw_mouth(f, style):
        y = 22
        a, b = cx - 1, cx
        if style in ("rest", "closed"):
            f.paint({(a, y), (b, y)}, lip)
        elif style == "smile":
            f.paint({(a - 1, y - 1), (b + 1, y - 1)}, lip)
            f.paint({(a, y), (b, y)}, lip_dark)
        elif style == "frown":
            f.paint({(a - 1, y + 1), (b + 1, y + 1)}, lip)
            f.paint({(a, y), (b, y)}, lip_dark)
        elif style == "half":
            f.paint({(a, y), (b, y)}, lip_dark)
            f.paint({(a, y + 1), (b, y + 1)}, lip)
        elif style == "open":
            f.paint({(a - 1, y), (b + 1, y)}, lip)
            f.paint({(a, y), (b, y)}, bp.MOUTH_DARK)
            f.paint({(a, y + 1), (b, y + 1)}, bp.TONGUE)
        elif style == "wide":
            f.paint({(a - 1, y), (b + 1, y), (a - 1, y + 1), (b + 1, y + 1)}, lip)
            f.paint({(a, y), (b, y), (a, y + 1), (b, y + 1)}, bp.MOUTH_DARK)
            f.paint({(a, y + 2), (b, y + 2)}, bp.TONGUE)
        elif style == "o":
            f.paint({(a, y), (b, y), (a, y + 1), (b, y + 1)}, bp.MOUTH_DARK)

    def draw_face(f):
        colors = {}
        for x, y in face:
            color = skin
            if (x, y + 1) not in face or ((x + 1, y) not in face and x > cx):
                color = skin_shade
            elif (x - 1, y) not in face and x < cx:
                color = skin_light
            colors[(x, y)] = color
        f.part(set(face), colors)
        f.paint(sym({(16, 21), (18, 21)}), blush_soft)
        f.paint(sym({(17, 21)}), blush)
        f.paint({(cx - 1, 25), (cx, 25)}, skin_deep)

    def draw_features(f, pose, look):
        draw_eyes(f, pose.eyes)
        if look.brows == "worry":
            f.paint({(18, 12), (19, 11), (28, 11), (29, 12)}, hair_dark)
        draw_mouth(f, pose.mouth)

    def draw_head(f, pose, look):
        if look.view == "back":
            head = set(dome) | sym(side_lock(0))
            f.part(head, crown_tone(head, (cx, 1)))
            draw_tiara(f, look.shine)
            return
        draw_face(f)
        top = set(bangs)
        f.part(top, crown_tone(top, (cx, 3)))
        # Where the bangs meet the forehead: a soft shadow, not an ink line.
        f.paint(outer_ring(top) & face, skin_shade)
        draw_features(f, pose, look)
        lock_l = side_lock(look.sway)
        lock_r = mirrored(side_lock(-look.sway))
        for lock in (lock_l, lock_r):
            f.part(lock, flow_tone(lock, 1.0))
        draw_tiara(f, look.shine)

    # -- Body ------------------------------------------------------------------

    bodice = frozenset(sym(polygon([(19.4, 25.6), (cx, 25.6), (cx, 33.0), (20.6, 33.0)])))
    sleeve = frozenset(sym(ellipse(19.0, 28.0, 3.0, 2.6)))

    def skirt_mask(hem, flare, sit):
        if sit:
            return sym(ellipse(cx, 41.6, 16.0, 5.4)) | sym(
                polygon([(20.4, 32.0), (cx, 32.0), (cx, 40.0), (14.0, 40.0)])
            )
        g = flare
        left = [
            (20.4, 32.4),
            (17.0 - g * 0.3, 35.5),
            (13.2 - g * 0.8, 39.6 - g * 0.2),
            (9.4 - g * 1.4, 44.0 - g * 0.6),
            (8.8 - g * 1.5, 45.9 - g * 0.6),
        ]
        right = [(2 * cx - x, y) for x, y in reversed(left)]
        out = polygon([*left, *right])
        if hem:
            out = {(x + round(hem * max(0, y - 35) / 10.0), y) for x, y in out}
        return out

    def draw_skirt(f, look):
        mask = skirt_mask(look.hem, look.flare, look.sit)
        colors = ramp(mask, emerald_light, emerald, emerald_dark, emerald_deep)
        bottom = max(y for _, y in mask)
        top = min(y for _, y in mask)
        for x, y in mask:
            lean = look.hem * max(0, y - 35) / 10.0
            rel = x + 0.5 - cx - lean
            spread = 1.0 + (y - top) * 0.17
            band = abs(rel) / spread
            # Folds fanning out from the waist: a lit ridge, a shadowed valley.
            if colors[(x, y)] == emerald:
                if abs(band - 4.0) < 0.5:
                    colors[(x, y)] = emerald_light
                elif abs(band - 4.0) < 0.9 and y > top + 5:
                    colors[(x, y)] = emerald_shine if rel < 0 else emerald_light
                elif abs(band - 6.3) < 0.5:
                    colors[(x, y)] = emerald_dark
            # The ivory front panel with gold edges.
            half = 0.5 + (y - top) * 0.3
            if y >= top + 2 and abs(rel) < half and not look.sit and look.view != "back":
                if abs(rel) >= half - 1:
                    colors[(x, y)] = gold
                elif rel > half - 2.2:
                    colors[(x, y)] = ivory_shade
                else:
                    colors[(x, y)] = ivory
        for x, y in mask:
            if y == bottom - 1 and colors[(x, y)] not in (ivory, ivory_shade, gold):
                colors[(x, y)] = gold
            if y == bottom:
                colors[(x, y)] = gold_dark
        f.part(mask, colors)
        if look.sit:
            return
        # An ivory ruffle peeking under the hem.
        xs = sorted(x for x, y in mask if y == bottom)
        ruffle = {(x, bottom + 1) for x in xs[1:-1] if (x - look.hem) % 3 != 1}
        f.part(ruffle, {p: ivory_shade if p[0] % 3 else ivory for p in ruffle})
        if look.feet:
            # Dangling: ivory stockings and emerald slippers below the ruffle.
            for sx in (cx - 4, cx + 2):
                lx = sx + 1 - look.hem // 2
                leg = rect(lx, bottom + 1, lx, bottom + 2)
                shoe = rect(sx - look.hem, bottom + 3, sx + 1 - look.hem, bottom + 3)
                foot = leg | shoe
                f.part(foot, {p: emerald_dark if p in shoe else ivory_shade for p in foot})

    def draw_bodice(f):
        mask = set(bodice)
        colors = ramp(mask, emerald_light, emerald, emerald_dark, emerald_deep)
        for x, y in mask:
            if x in (cx - 1, cx) and y >= 27:
                colors[(x, y)] = ivory if y % 2 else ivory_shade
            if y == 26:
                colors[(x, y)] = gold if x not in (cx - 1, cx) else gold_light
        f.part(mask, colors)
        sash = {(x, 33) for x in range(20, 2 * cx - 20)}
        f.part(sash, {p: (gold_light if p[0] in (cx - 1, cx) else gold) for p in sash})
        f.paint({(cx - 2, 24), (cx - 1, 24), (cx, 24), (cx + 1, 24)}, skin_shade)
        f.paint({(cx - 1, 25), (cx, 25)}, skin_shade)

    def draw_sleeves(f):
        mask = set(sleeve)
        f.part(mask, ramp(mask, emerald_shine, emerald_light, emerald, emerald_dark))
        f.paint({(x, y) for x, y in mask if (x, y + 1) not in mask}, gold)

    def draw_arm(f, start, path):
        pts = [start, *path]
        stroke = set()
        for a, b in zip(pts, pts[1:], strict=False):
            stroke |= thick(line(*a, *b))
        hx, hy = path[-1]
        glove = rect(hx - 1, hy - 1, hx + 1, hy + 1) - {(hx + 1, hy + 1)}
        mask = stroke | glove
        colors = {}
        for p in mask:
            near = abs(p[0] - hx) <= 2 and abs(p[1] - hy) <= 2
            colors[p] = ivory_shade if near else skin
        for p in glove:
            colors[p] = ivory_shade if p[1] == hy + 1 or p[0] == hx + 1 else ivory
        f.part(mask, colors)

    def draw_letter(f, i):
        sheet = rect(16, 34, 31, 41)
        f.part(sheet, {p: (paper_shade if p[1] == 41 or p[0] == 31 else paper) for p in sheet})
        for row in range(min(i, 7)):
            y = 35 + (row // 2) * 2
            x0 = 18 if row % 2 == 0 else 24
            if y <= 39:
                f.paint({(x, y) for x in range(x0, x0 + 5)}, ink)
        f.paint({(29, 39), (30, 39), (29, 40), (30, 40)}, seal)

    def draw_quill(f, hand, k):
        """A white feather quill held in the right glove, its tip on the letter."""
        hx, hy = hand
        vane = polygon(
            [(hx + 1, hy - 2), (hx + 4, hy - 8 - k), (hx + 8, hy - 11 - k), (hx + 6, hy - 5 - k)]
        )
        f.part(vane, {p: (feather if p[0] + p[1] < hx + hy - 6 else feather_shade) for p in vane})
        f.paint(line(hx + 1, hy - 1, hx + 6, hy - 9 - k), feather_shade)
        f.paint({(hx - 1, hy + 1), (hx - 2, hy + 2)}, ink)

    def draw_fan(f, i):
        """A folding fan open above the right glove: ivory pleats, a gold rim."""
        tilt = (0.0, 0.25, 0.0, -0.2)[i % 4]
        px, py = 34, 27
        lo, hi = -math.pi * 0.92 + tilt, -math.pi * 0.30 + tilt
        fan = {}
        for y in range(py - 9, py + 1):
            for x in range(px - 9, px + 9):
                dx, dy = x + 0.5 - px, y + 0.5 - py
                r = math.hypot(dx, dy)
                a = math.atan2(dy, dx)
                if 2.0 <= r <= 8.2 and lo <= a <= hi:
                    pleat = int((a - lo) / (hi - lo) * 7) % 2
                    color = ivory if pleat else ivory_shade
                    if r > 7.0:
                        color = gold if pleat else gold_dark
                    fan[(x, y)] = color
        f.part(set(fan), fan)
        f.paint({(px - 1, py - 1), (px, py - 1)}, gold_dark)

    def draw_figure(f, pose, look):
        lift = 4 if look.sit else 0
        with f.offset(look.head[0], look.head[1] + lift):
            mane = back_hair(look.sway)
            f.part(mane, flow_tone(mane))
        draw_skirt(f, look)
        with f.offset(0, lift):
            draw_bodice(f)
            draw_sleeves(f)
            if not look.front[0]:
                draw_arm(f, (18, 29), look.left)
            if not look.front[1]:
                draw_arm(f, (29, 29), look.right)
            if look.view == "back":
                # Seen from behind, the long hair falls over the back of the gown.
                with f.offset(*look.head):
                    curtain = back_hair(look.sway, full=True)
                    f.part(curtain, flow_tone(curtain))
            if look.prop == "letter":
                draw_letter(f, look.prop_i)
            with f.offset(*look.head):
                draw_head(f, pose, look)
            if look.prop == "fan":
                draw_fan(f, look.prop_i)
            if look.front[0]:
                draw_arm(f, (18, 29), look.left)
            if look.front[1]:
                draw_arm(f, (29, 29), look.right)
            if look.prop == "letter":
                draw_quill(f, look.right[-1], look.prop_i % 2)

    # -- Frame tables ----------------------------------------------------------

    Look = _Look
    rest = Look()
    looks = {}

    looks["idle"] = tuple(
        Look(sway=s, hem=h)
        for s, h in zip((0, 0, 1, 1, 1, 0, 0, 0), (0, 0, 0, 1, 0, 0, 0, 0), strict=True)
    )

    ear = ((33, 26), (33, 18))
    looks["listening"] = tuple(
        Look(head=(1, 0), right=ear, front=(False, True), sway=s) for s in (1, 2, 2, 1, 0, 1)
    )

    chin = ((31, 31), (26, 25))
    looks["thinking"] = tuple(Look(right=chin, front=(False, True)) for _ in range(8))

    looks["talking"] = (
        rest,
        rest,
        Look(right=((32, 32), (34, 29))),
        Look(right=((32, 31), (35, 27)), sway=1),
    )

    spin = (1.0, 0.7, 0.45, 0.7, 1.0, 0.7, 0.45, 1.0)
    views = ("front", "front", "back", "back", "back", "back", "front", "front")
    looks["success"] = tuple(
        Look(
            view=views[i],
            squash=spin[i],
            flare=(1, 2, 3, 3, 3, 3, 2, 1)[i],
            sway=(0, -1, -2, -2, -1, 1, 2, 1)[i],
            left=((13, 31),) if 1 <= i <= 6 else ((14, 33),),
            right=((34, 31),) if 1 <= i <= 6 else ((33, 33),),
        )
        for i in range(8)
    )

    forehead = ((12, 23), (17, 14))
    looks["error"] = tuple(
        Look(left=forehead, front=(True, False), brows="worry") for _ in range(6)
    )

    looks["sleeping"] = tuple(
        Look(
            head=(2, 2),
            sit=True,
            left=((22, 33), (28, 28)),
            right=((34, 32), (31, 28)),
            front=(True, True),
            sway=(1, 1, 2, 2, 1, 1)[i],
        )
        for i in range(6)
    )

    pen = ((27, 36), (24, 37), (28, 37), (25, 36), (29, 37), (26, 37), (22, 36), (27, 37))
    looks["working"] = tuple(
        Look(
            left=((15, 37),),
            right=((32, 33), pen[i]),
            front=(False, True),
            prop="letter",
            prop_i=i + 1,
        )
        for i in range(8)
    )

    looks["searching"] = tuple(Look() for _ in range(8))

    looks["held"] = tuple(
        Look(
            left=((14, 34), (12, 37)),
            right=((33, 34), (35, 37)),
            sway=-s,
            hem=-s,
            flare=1 + (i % 2),
            feet=True,
        )
        for i, s in enumerate(bp.HELD_SWAY)
    )

    # -- Idle acts -------------------------------------------------------------

    curtsy_dip = (0, 1, 2, 3, 3, 2, 1, 0)
    flip_hand = (
        rest.right,
        ((33, 27), (33, 23)),
        ((34, 25), (36, 20)),
        ((35, 24), (38, 19)),
        ((34, 25), (36, 21)),
        ((33, 28), (33, 25)),
        rest.right,
        rest.right,
    )
    act_looks = {
        "curtsy": tuple(
            Look(
                head=(0, (0, 0, 1, 1, 1, 1, 0, 0)[i]),
                left=((12, 38),) if 1 <= i <= 6 else rest.left,
                right=((35, 38),) if 1 <= i <= 6 else rest.right,
                flare=(0, 1, 2, 3, 3, 2, 1, 0)[i],
            )
            for i in range(8)
        ),
        "twirl": tuple(
            Look(
                view=views[i],
                squash=spin[i],
                flare=(0, 2, 3, 3, 3, 3, 2, 0)[i],
                sway=(0, -1, -2, -2, -1, 1, 2, 0)[i],
                left=((13, 31),) if 1 <= i <= 6 else rest.left,
                right=((34, 31),) if 1 <= i <= 6 else rest.right,
            )
            for i in range(8)
        ),
        "hair_flip": tuple(
            Look(
                right=flip_hand[i],
                front=(False, 1 <= i <= 5),
                sway=(0, 1, 3, 4, 3, 1, -1, 0)[i],
            )
            for i in range(8)
        ),
        "fan_flutter": tuple(
            Look(
                right=((33, 31), (34, 28)) if 1 <= i <= 6 else rest.right,
                front=(False, 1 <= i <= 6),
                prop="fan" if 1 <= i <= 6 else "",
                prop_i=i,
                sway=(0, 0, 1, 1, 0, 0, 1, 0)[i],
            )
            for i in range(8)
        ),
        "tiara_shine": tuple(
            Look(
                head=(0, -1) if 2 <= i <= 5 else (0, 0),
                left=((22, 31),) if 1 <= i <= 6 else rest.left,
                right=((25, 31),) if 1 <= i <= 6 else rest.right,
                shine=(-1, -1, 0, 2, 4, 6, 8, -1)[i],
            )
            for i in range(8)
        ),
        "wave": tuple(
            Look(
                right=rest.right if i in (0, 7) else ((34, 26), ((36, 20), (38, 19))[i % 2]),
                front=(False, i not in (0, 7)),
            )
            for i in range(8)
        ),
    }
    act_eyes = {
        "curtsy": ("open", "open", "closed", "closed", "closed", "closed", "happy", "open"),
        "twirl": ("open", "happy", "happy", "happy", "happy", "happy", "happy", "open"),
        "hair_flip": ("open", "open", "closed", "closed", "happy", "happy", "open", "open"),
        "fan_flutter": ("open", "happy", "happy", "open", "happy", "happy", "open", "open"),
        "tiara_shine": (
            "open",
            "up_right",
            "up_right",
            "up_right",
            "happy",
            "happy",
            "open",
            "open",
        ),
        "wave": ("open", "happy", "happy", "open", "open", "happy", "happy", "open"),
    }
    act_mouth = {
        "curtsy": "smile",
        "twirl": "smile",
        "hair_flip": "smile",
        "fan_flutter": "rest",
        "tiara_shine": "smile",
        "wave": "smile",
    }

    def look_for(pose):
        rows = act_looks[pose.act] if pose.act else looks[pose.state]
        return rows[pose.i % len(rows)]

    # -- Poses -----------------------------------------------------------------

    def pose_for(state, i):
        p = bp.base_pose(state, i)
        if state == "idle":
            return replace(p, mouth="rest")
        if state == "listening":
            return replace(p, dy=0, stretch=(0, 1, 1, 1, 0, 0)[i], eyes="open", mouth="rest")
        if state == "thinking":
            return replace(p, eyes="up_right", mouth="rest")
        if state == "talking":
            # She lifts a pixel while she speaks, so talking never reads as idle.
            return replace(p, dy=-1)
        if state == "success":
            dy = (0, -1, -2, -2, -2, -2, -1, 0)[i]
            return Pose(state, i, dy=dy, eyes="happy", mouth="smile")
        if state == "error":
            return Pose(state, i, dx=(-1, 1, -1, 1, 0, 0)[i], eyes="worry", mouth="frown")
        if state == "sleeping":
            return replace(p, dy=0, mouth="rest")
        if state == "working":
            return replace(p, dy=0, mouth="rest")
        if state == "searching":
            x = bp.SEARCH_SWEEP[i]
            return replace(p, eyes="look_left" if x < -2 else "look_right" if x > 2 else "down")
        if state == "held":
            return replace(p, mouth="o", stretch=0)
        return p

    def draw(f, pose):
        with f.offset(pose.dx, pose.dy):
            draw_figure(f, pose, look_for(pose))

    def post(img, pose):
        look = look_for(pose)
        if look.squash < 1.0:
            return bp.squash_x(img, look.squash)
        return img

    # -- Effects ---------------------------------------------------------------

    sparkles = ((7, 14, 1), (41, 10, 2), (5, 34, 3), (42, 33, 4), (12, 3, 5))
    heart_rows = ("#.#", "#o#", ".#.")
    heart_palette = {"#": heart, "o": heart_light}

    def fx_thinking(f, pose):
        bp.fx_dots(f, pose.i, 31, 3)
        if pose.i in (2, 3, 4):
            bp.fx_sparkles(f, pose.i - 2, ((38, 13, 0),))

    def fx_success(f, pose):
        bp.fx_sparkles(f, pose.i, sparkles)

    def fx_working(f, pose):
        if pose.i % 4 == 2:
            bp.fx_sparkles(f, 0, ((38, 24, 0),))

    def fx_searching(f, pose):
        """The magnifier sweeps across the skirt, a gloved hand on its handle."""
        i = pose.i
        gx = cx + bp.SEARCH_SWEEP[i]
        bp.fx_magnifier(f, i, cx, 30)
        hand = rect(gx + 5, 35, gx + 7, 37)
        f.part(hand, {p: ivory_shade if p[1] == 37 else ivory for p in hand})

    def fx_held(f, pose):
        moving = bp.HELD_SWAY[pose.i] - bp.HELD_SWAY[pose.i - 1]
        if moving:
            x, step = (5, -2) if moving > 0 else (42, 2)
            f.paint(line(x, 30, x, 36) | line(x + step, 31, x + step, 35), bp.ARC_FADE)

    def fx_tiara(f, pose):
        if pose.i in (3, 4, 5):
            bp.fx_sparkles(f, pose.i - 3, ((35, 4, 0),))

    def fx_twirl(f, pose):
        bp.fx_sparkles(f, pose.i, ((6, 30, 2), (41, 28, 3), (9, 12, 4)))

    def fx_curtsy(f, pose):
        if pose.i in (3, 4, 5):
            for x, y in ((6, 20), (39, 20)):
                f.glyph(x, y - (pose.i - 3), heart_rows, heart_palette)

    def fx_wave(f, pose):
        if 1 <= pose.i <= 6:
            hx = 40 if pose.i % 2 else 42
            f.paint(line(hx, 16, hx + 2, 14) | line(hx + 1, 19, hx + 3, 19), bp.ARC)

    def act_pose(name):
        eyes, mouth = act_eyes[name], act_mouth[name]

        def make(i):
            dip = curtsy_dip[i] if name == "curtsy" else 0
            return Pose("idle", i, eyes=eyes[i], mouth=mouth, stretch=-1 if dip >= 2 else 0)

        return make

    acts = (
        bp.IdleAct("curtsy", 8, 6, act_pose("curtsy"), fx_curtsy),
        bp.IdleAct("twirl", 8, 9, act_pose("twirl"), fx_twirl),
        bp.IdleAct("hair_flip", 8, 8, act_pose("hair_flip")),
        bp.IdleAct("fan_flutter", 8, 8, act_pose("fan_flutter")),
        bp.IdleAct("tiara_shine", 8, 7, act_pose("tiara_shine"), fx_tiara),
        bp.IdleAct("wave", 8, 7, act_pose("wave"), fx_wave),
    )

    anchors = bp.Anchors(
        arcs_left=(8, 17),
        arcs_right=(39, 17),
        dots=(31, 3),
        zzz=(36, 15),
        bang=(40, 3),
        sweat=(34, 9),
        sparkles=sparkles,
        magnifier=(cx, 30),
    )

    return bp.PetDesign(
        id="aurelia",
        name="Aurelia",
        description=(
            "A gentle princess in an emerald gown who tilts her head to listen, writes letters"
            " with a quill and twirls when something goes right."
        ),
        draw=draw,
        pose=pose_for,
        anchors=anchors,
        waist=33,
        post=post,
        fx={
            "thinking": fx_thinking,
            "success": fx_success,
            "working": fx_working,
            "searching": fx_searching,
            "held": fx_held,
        },
        acts=acts,
    )
