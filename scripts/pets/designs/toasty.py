"""Toasty: a retro two-slot toaster.

A rounded mint-enamel toaster with a chrome band, a coral lever on its right
side, a little chrome dial on its left and two slices of golden toast peeking
out of its slots. Toasty's moods live in its toast (it rises to listen, pops
sky-high on a success, burns on an error and sinks out of sight asleep), its
slots (they glow orange while it thinks and works) and its lever, which perks
up, bounces and clicks down with the toast.
"""

from __future__ import annotations


def design(bp):  # noqa: C901, PLR0915 - one closure per drawing helper
    hexc = bp.hexc
    Pose = bp.Pose
    rect = bp.rect
    line = bp.line
    ellipse = bp.ellipse
    rounded_rect = bp.rounded_rect
    shade = bp.shade
    mirrored = bp.mirrored
    shifted = bp.shifted
    OUTLINE = bp.OUTLINE
    FX_WHITE = bp.FX_WHITE

    # -- Palette ----------------------------------------------------------------
    enamel = (hexc("#9fdec4"), hexc("#d3f4e5"), hexc("#5fae95"))
    #: Asleep the enamel cools down: the same toaster, dimmed.
    enamel_cool = (hexc("#7fb9a6"), hexc("#a9d6c6"), hexc("#4a8a77"))
    chrome = hexc("#d9dee7")
    chrome_light = hexc("#ffffff")
    chrome_dark = hexc("#8d95a6")
    lever = hexc("#f07a5a")
    lever_light = hexc("#ffb59c")
    lever_dark = hexc("#b9503b")
    foot = hexc("#a9b0bf")
    foot_light = hexc("#e3e7ef")
    ink = hexc("#2a2430")
    blush = hexc("#ff8fa3")
    eyes_style = bp.EyeStyle(w=3, h=4, iris=ink, glint=FX_WHITE, lid=ink)
    #: Toast: (crust, crumb, highlight) per doneness.
    toast_golden = (hexc("#a65d24"), hexc("#f3c46e"), hexc("#ffe6ae"))
    toast_burnt = (hexc("#2e211b"), hexc("#5a3e2e"), hexc("#7a5844"))
    toast_hot = (hexc("#a65d24"), hexc("#f6a54c"), hexc("#ffd28f"))
    glow = hexc("#ff8a2a")
    glow_light = hexc("#ffc06a")
    #: Heat shimmer: a mid orange that holds on dark AND light desktops.
    heat = hexc("#ff9a3c")
    heat_fade = hexc("#f7c27e")
    smoke = hexc("#6e6872")
    smoke_light = hexc("#9b95a2")
    #: Flying crumbs: a mid tone that holds on dark AND light desktops.
    crumb = hexc("#d98a3a")
    butter = hexc("#fff0a0")
    butter_dark = hexc("#e8c95a")

    # -- Geometry ---------------------------------------------------------------
    #: The slots' left columns; each slice is 9 px wide.
    slots = (14, 25)
    #: The deck: the body's top row, where the slots open.
    deck = 20
    #: A slice's top row at rest (six rows peek out of the slot).
    rest = 15
    #: A slice's top row when it has sunk out of sight.
    sunk = 22
    #: The lever knob's top row at rest.
    lever_rest = 28
    dial_c = (8, 32)

    # -- Per-state tables -------------------------------------------------------
    #: (left, right) toast top per frame.
    tops: dict[str, tuple[tuple[int, int], ...]] = {
        "listening": ((14, 14), (13, 13), (12, 12), (12, 12), (13, 13), (14, 14)),
        "talking": ((rest, rest), (rest, rest), (14, 14), (13, 13)),
        "success": (
            (rest, rest),
            (12, 14),
            (7, 10),
            (6, 6),
            (8, 5),
            (12, 9),
            (rest, 14),
            (rest, rest),
        ),
        "error": ((rest, rest), (13, 14), (rest, rest), (14, 13), (rest, rest), (rest, rest)),
        "sleeping": ((sunk, sunk),) * 6,
        "working": (
            (16, 16),
            (17, 16),
            (16, 16),
            (16, 17),
            (16, 16),
            (17, 16),
            (16, 16),
            (16, 16),
        ),
        "searching": ((16, 16),) * 8,
        "held": ((13, 16), (14, 15), (16, 13), (15, 14), (13, 16), (14, 15)),
    }
    levers: dict[str, tuple[int, ...]] = {
        "listening": (26, 25, 24, 24, 25, 26),
        "talking": (28, 28, 27, 26),
        "success": (28, 27, 24, 24, 25, 27, 28, 28),
        "error": (28, 26, 30, 26, 30, 28),
        "sleeping": (34,) * 6,
        "working": (31, 30, 31, 31, 30, 31, 30, 31),
        "held": (27, 29, 27, 29, 27, 29),
    }
    #: Slot glow per frame: 0 off, 1 warm, 2 bright.
    glows: dict[str, tuple[int, ...]] = {
        "thinking": (1, 1, 2, 2, 2, 2, 1, 1),
        "working": (1, 1, 1, 1, 1, 1, 1, 1),
        "error": (2, 2, 1, 1, 0, 0),
    }
    #: The dial pointer's direction per frame, as a (dx, dy) step from its hub.
    dial_dirs = ((0, -1), (1, -1), (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1))
    #: Idle: the chrome band's glint sliding across (None = no glint).
    band_glint = (None, None, 13, 18, 23, 28, None, None)

    # -- Idle acts' tables ------------------------------------------------------
    act_tops: dict[str, tuple[tuple[int, int], ...]] = {
        "toast_pop": (
            (rest, rest),
            (17, 17),
            (6, 7),
            (1, 2),
            (2, 1),
            (8, 7),
            (14, 14),
            (rest, rest),
        ),
        "toast_juggle": (
            (rest, rest),
            (7, 17),
            (3, 15),
            (9, 8),
            (15, 3),
            (17, 7),
            (14, 14),
            (rest, rest),
        ),
        "crumb_shake": ((rest, rest), (14, 16), (16, 14), (14, 16), (16, 14), (rest, rest)) + (
            (rest, rest),
            (rest, rest),
        ),
        "lever_bounce": (
            (rest, rest),
            (18, 18),
            (sunk, sunk),
            (sunk, sunk),
            (7, 7),
            (11, 11),
            (14, 14),
            (rest, rest),
        ),
        "butter_shine": ((rest, rest),) * 8,
        "heat_shimmer": (
            (rest, rest),
            (16, 16),
            (17, 17),
            (17, 17),
            (17, 17),
            (17, 17),
            (12, 12),
            (rest, rest),
        ),
    }
    #: Juggle: the slices drift towards the middle at the top of their arc.
    act_toast_dx: dict[str, tuple[tuple[int, int], ...]] = {
        "toast_juggle": ((0, 0), (1, 0), (3, 0), (1, -1), (0, -3), (0, -1), (0, 0), (0, 0)),
    }
    act_levers: dict[str, tuple[int, ...]] = {
        "toast_pop": (28, 31, 24, 24, 24, 26, 28, 28),
        "toast_juggle": (28, 25, 28, 25, 28, 25, 28, 28),
        "crumb_shake": (28, 27, 29, 27, 29, 28, 28, 28),
        "lever_bounce": (28, 31, 34, 34, 22, 25, 27, 28),
        "butter_shine": (28,) * 8,
        "heat_shimmer": (28, 30, 32, 32, 32, 32, 25, 28),
    }
    act_glows: dict[str, tuple[int, ...]] = {
        "lever_bounce": (0, 0, 1, 2, 0, 0, 0, 0),
        "heat_shimmer": (0, 1, 1, 2, 2, 2, 1, 0),
    }
    act_blush: dict[str, tuple[int, ...]] = {
        "toast_pop": (7,),
        "butter_shine": (5, 6),
        "heat_shimmer": (3, 4, 5),
    }

    # -- Pose -------------------------------------------------------------------
    def toasty_pose(state: str, i: int) -> Pose:
        if state == "held":
            mouth = ("half", "open")[i % 2]
            return Pose(state, i, dx=bp.HELD_SWAY[i], dy=-2, eyes="wide", mouth=mouth, stretch=1)
        if state == "thinking":
            eyes = "up_left" if i < 4 else "up_right"
            return Pose(state, i, eyes=eyes, mouth="closed", stretch=(0, 0, 0, 1, 1, 0, 0, 0)[i])
        if state == "error":
            mouth = ("frown", "half", "frown", "half", "frown", "frown")[i]
            return Pose(state, i, dx=bp.SHAKE[i], eyes="x", mouth=mouth)
        return bp.base_pose(state, i)

    def act_pose(name: str, **columns):
        def pose(i: int) -> Pose:
            fields = {key: values[i] for key, values in columns.items()}
            return Pose("idle", i, act=name, **fields)

        return pose

    # -- Lookups ----------------------------------------------------------------
    def _tops(pose: Pose) -> tuple[int, int]:
        table = act_tops.get(pose.act) if pose.act else tops.get(pose.state)
        return table[pose.i] if table is not None else (rest, rest)

    def _toast_dx(pose: Pose) -> tuple[int, int]:
        table = act_toast_dx.get(pose.act) if pose.act else None
        return table[pose.i] if table is not None else (0, 0)

    def _lever(pose: Pose) -> int:
        table = act_levers.get(pose.act) if pose.act else levers.get(pose.state)
        return table[pose.i] if table is not None else lever_rest

    def _glow(pose: Pose) -> int:
        table = act_glows.get(pose.act) if pose.act else glows.get(pose.state)
        return table[pose.i] if table is not None else 0

    def _dial_dir(pose: Pose) -> tuple[int, int]:
        if pose.act == "heat_shimmer" or pose.state in ("thinking", "working"):
            return dial_dirs[(pose.i + 1) % 8]
        if pose.state == "error":
            return dial_dirs[(3 * pose.i) % 8]
        if pose.state == "sleeping":
            return dial_dirs[6]
        return dial_dirs[1]

    # -- Parts ------------------------------------------------------------------
    def _slice(x0: int, top: int) -> set:
        """A bread slice: a rounded crown with shoulders over a narrower body."""
        crown = rounded_rect(x0, top, x0 + 8, top + 3, 2)
        return crown | rect(x0 + 1, top + 2, x0 + 7, top + 16)

    def _draw_toast(f, x0: int, top: int, kind: tuple, glowing: int, edge: bool = False) -> None:
        if top >= sunk:
            return
        crust, crumb_c, high = kind
        if edge:
            # Flipping in the air, seen edge-on: a thin slab of crust.
            slab = rect(x0, top + 4, x0 + 8, top + 5)
            f.part(slab, {p: crumb_c if p[1] == top + 4 else crust for p in slab})
            f.paint({(x0 + 1, top + 4), (x0 + 2, top + 4)}, high)
            return
        full = _slice(x0, top)
        colors = shade(full, crumb_c, rim=crust)
        if glowing >= 2 and kind is not toast_burnt:
            for p in list(colors):
                if p[1] >= deck - 3 and colors[p] == crumb_c:
                    colors[p] = toast_hot[1]
        colors[(x0 + 2, top + 1)] = high
        colors[(x0 + 3, top + 1)] = high
        colors[(x0 + 1, top + 2)] = high
        if kind is toast_burnt:
            # Charred: a few black specks on the crumb.
            for p in ((x0 + 5, top + 2), (x0 + 3, top + 4), (x0 + 6, top + 4)):
                colors[p] = crust
        else:
            # A darker toasted patch in the middle of the slice.
            for p in ((x0 + 4, top + 3), (x0 + 5, top + 3), (x0 + 5, top + 4)):
                colors[p] = toast_hot[1] if kind is toast_golden else crumb_c
        shown = {p for p in full if p[1] <= deck}
        f.part(shown, {p: colors[p] for p in shown})

    def _draw_slots(f, glowing: int) -> None:
        for x0 in slots:
            f.paint(rect(x0 - 1, deck, x0 + 9, deck), OUTLINE)

    def _glow_slots(f, glowing: int) -> None:
        if not glowing:
            return
        for x0 in slots:
            edge = {(x0 - 1, deck), (x0, deck), (x0 + 8, deck), (x0 + 9, deck)}
            f.paint(edge, glow if glowing >= 2 else glow_light)
            if glowing >= 2:
                f.paint({(x0 - 1, deck + 1), (x0 + 9, deck + 1)}, glow_light)

    def _draw_lever(f, top: int) -> None:
        stem = rect(36, top + 1, 37, top + 1)
        f.paint(stem, chrome_dark)
        knob = rounded_rect(38, top, 42, top + 2, 1)
        f.part(knob, shade(knob, lever, light=lever_light, dark=lever_dark, dark_depth=1))

    def _draw_dial(f, direction: tuple[int, int]) -> None:
        cx, cy = dial_c
        disc = ellipse(cx + 0.5, cy + 0.5, 2.6, 2.6)
        f.part(disc, shade(disc, chrome, light=chrome_light, dark=chrome_dark, dark_depth=1))
        dx, dy = direction
        f.paint({(cx, cy), (cx + dx, cy + dy)}, ink)

    def _feet(pose: Pose) -> set:
        left = rounded_rect(13, 41, 17, 42, 1)
        if pose.state == "held":
            kick = 1 if pose.i % 2 == 0 else 0
            return shifted(left, 0, kick) | shifted(mirrored(left), 0, 1 - kick)
        return left | mirrored(left)

    def draw_toasty(f, pose: Pose) -> None:
        base, light, dark = enamel_cool if pose.state == "sleeping" else enamel
        kind = toast_golden
        if pose.state == "error":
            kind = toast_burnt
        glowing = _glow(pose)
        left_top, right_top = _tops(pose)
        ldx, rdx = _toast_dx(pose)
        with f.offset(pose.dx, pose.dy):
            feet = _feet(pose)
            f.part(feet, shade(feet, foot, light=foot_light, dark=chrome_dark, dark_depth=1))
            body = rounded_rect(10, deck, 37, 40, 3)
            f.part(body, shade(body, base, light=light, dark=dark, dark_depth=2))
            # The enamel's shine: a soft highlight in the upper left corner.
            f.paint({(12, 24), (12, 25), (13, 23), (14, 23)}, FX_WHITE)
            # The chrome band, with its own glint.
            band = rect(11, 35, 36, 37)
            band_colors = {
                p: chrome_light if p[1] == 35 else chrome if p[1] == 36 else chrome_dark
                for p in band
            }
            f.paint_map(band_colors)
            f.paint({(10, 35), (10, 36), (10, 37), (37, 35), (37, 36), (37, 37)}, chrome_dark)
            glint_x = band_glint[pose.i] if pose.state == "idle" and not pose.act else None
            if glint_x is not None:
                f.paint({(glint_x, 36), (glint_x + 1, 36), (glint_x + 2, 36)}, chrome_light)
            else:
                f.paint({(14, 36), (15, 36)}, chrome_light)
            _draw_slots(f, glowing)
            edge = pose.act == "toast_pop" and pose.i == 3
            _draw_toast(f, slots[0] + ldx, left_top, kind, glowing, edge)
            _draw_toast(f, slots[1] + rdx, right_top, kind, glowing, edge)
            _glow_slots(f, glowing)
            _draw_lever(f, _lever(pose))
            _draw_dial(f, _dial_dir(pose))
            # The face.
            bp.draw_eyes(f, pose.eyes, (15, 26), (30, 26), eyes_style)
            cheeks = rect(12, 31, 13, 31) | rect(34, 31, 35, 31)
            wide = pose.state in ("success", "held") or pose.i in act_blush.get(pose.act, ())
            if wide:
                cheeks |= {(12, 30), (35, 30)}
            f.paint(cheeks, blush)
            bp.draw_mouth(f, pose.mouth, 22, 30, 4, color=ink)

    # -- Effects ----------------------------------------------------------------
    def _puff(f, x: int, y: int, r: float) -> None:
        mask = ellipse(x + 0.5, y + 0.5, r, r)
        f.part(mask, shade(mask, smoke, light=smoke_light, dark=smoke, dark_depth=1))

    def _shimmer(f, x: int, y: int, length: int, phase: int, color) -> None:
        """A thin wavy thread of hot air rising from ``(x, y)``."""
        wave = (0, 1, 1, 0, -1, -1)
        f.paint({(x + wave[(k + phase) % 6], y - k) for k in range(length)}, color)

    def _juggle_fx(f, pose: Pose) -> None:
        """Whoosh ticks under each slice as it is tossed up."""
        if pose.i in (1, 2):
            f.paint(line(16, 21, 16, 19) | line(20, 21, 20, 19), bp.ARC_FADE)
        if pose.i in (4, 5):
            f.paint(line(27, 21, 27, 19) | line(31, 21, 31, 19), bp.ARC_FADE)
        if pose.i == 3:
            bp.fx_sparkles(f, 0, ((23, 7, 0),))

    def _crumbs(f, pixels) -> None:
        f.paint({(x, y) for x, y in pixels} | {(x + 1, y) for x, y in pixels}, crumb)

    def toasty_thinking(f, pose: Pose) -> None:
        """Thinking dots, and heat shimmering up off the glowing slices."""
        with f.offset(pose.dx, pose.dy):
            bp.fx_dots(f, pose.i, 19, 4)
            for k, x0 in enumerate(slots):
                x = x0 + 4
                y = rest - 3 - (pose.i % 2)
                color = heat if (pose.i + k) % 2 == 0 else heat_fade
                _shimmer(f, x, y, 4, pose.i + 3 * k, color)

    def toasty_talking(f, pose: Pose) -> None:
        """At the loudest, a crumb or two jumps out of the slots."""
        with f.offset(pose.dx, pose.dy):
            if pose.i == 3:
                _crumbs(f, ((18, 11), (29, 10)))
            elif pose.i == 2:
                _crumbs(f, ((19, 13),))

    def toasty_success(f, pose: Pose) -> None:
        bp.fx_sparkles(f, pose.i, anchors.sparkles)
        if 2 <= pose.i <= 4:
            # Pop! Ticks beside the slices at the top of their flight.
            with f.offset(pose.dx, pose.dy):
                f.paint(line(10, 14, 8, 12) | line(37, 14, 39, 12), bp.ARC)

    #: Error: dark smoke puffs from the slots, (dx, dy, radius) per frame.
    smoke_puffs = (
        ((4, -4, 1.6),),
        ((3, -6, 2.2), (5, -3, 1.4)),
        ((2, -9, 2.6), (5, -5, 2.0)),
        ((1, -12, 2.6), (4, -8, 2.4)),
        ((0, -14, 2.0), (3, -11, 2.4)),
        ((2, -13, 1.6),),
    )

    def toasty_error(f, pose: Pose) -> None:
        """Burnt! Dark smoke billows from the slots and the "!" pops up."""
        bp.fx_bang(f, *anchors.bang)
        with f.offset(pose.dx, pose.dy):
            for k, x0 in enumerate(slots):
                for dx, dy, r in smoke_puffs[pose.i]:
                    x = x0 + dx + (2 * k)
                    _puff(f, x, deck - 3 + dy, r)
        with f.offset(pose.dx, 0):
            bp.fx_sweat(f, pose.i, *anchors.sweat)

    def toasty_sleeping(f, pose: Pose) -> None:
        bp.fx_zzz(f, pose.i, *anchors.zzz)

    #: Working: keystroke ticks above the lid per frame, (dx, dy) from its top-left.
    key_ticks = (((3, -2),), ((9, -2),), ((5, -2), (11, -3)), (), ((7, -2),), ((2, -3),), (), ())
    code_glyphs = (("#.#", "#.#", ".#."), ("##.", ".##", "##."), (".#.", "##.", ".#."))

    def toasty_working(f, pose: Pose) -> None:
        """Typing on a laptop while the slots glow softly; instead of toast,
        little code chips pop out of the slots."""
        x, y = anchors.laptop
        lid = rounded_rect(x, y, x + 13, y + 7, 1)
        f.part(lid, shade(lid, bp.LAPTOP_LID, light=bp.LAPTOP_LID_LIGHT, dark=bp.LAPTOP_LID))
        logo = bp.LAPTOP_LOGO if pose.i % 4 != 3 else bp.LAPTOP_LID_LIGHT
        f.paint(rect(x + 6, y + 3, x + 7, y + 4), logo)
        base = rect(x - 2, y + 8, x + 15, y + 9)
        f.part(base, {p: bp.LAPTOP_BASE if p[1] == y + 8 else bp.LAPTOP_BASE_DARK for p in base})
        ticks = key_ticks[pose.i]
        if ticks:
            f.paint(rect(x + 2, y - 1, x + 11, y - 1), bp.SCREEN_GLOW)
        for dx, dy in ticks:
            f.paint({(x + dx, y + dy - 1), (x + dx, y + dy - 2)}, FX_WHITE)
        with f.offset(pose.dx, pose.dy):
            # One chip pops out of a slot every four frames, alternating slots.
            age = pose.i % 4
            k = (pose.i // 4) % 2
            glyph = code_glyphs[(pose.i // 4 + 1) % len(code_glyphs)]
            gx = slots[k] + 3 + (k * 2 - 1) * (age // 2)
            f.glyph(gx, rest - 5 - 2 * age, glyph, {"#": bp.CODE_CHIP})
            if age in (1, 3):
                _shimmer(f, slots[1 - k] + 4, rest - 2, 2, pose.i, heat_fade)

    # -- Idle acts' effects -----------------------------------------------------
    def _pop_fx(f, pose: Pose) -> None:
        """Both slices spring out, flip at the top and land back with a ding."""
        i = pose.i
        if i == 2:
            f.paint(line(11, 18, 9, 16) | line(36, 18, 38, 16), bp.ARC)
        if i in (3, 4):
            f.paint(line(12, 5, 10, 5) | line(35, 5, 37, 5), bp.ARC_FADE)
        if i == 7:
            f.paint(line(11, 15, 9, 13) | line(36, 15, 38, 13), bp.ARC)
            bp.fx_sparkles(f, 0, ((40, 12, 0),))

    #: Crumb shake: crumbs per frame, flying out of the slots and settling.
    shake_crumbs = (
        (),
        ((16, 14), (30, 15)),
        ((13, 12), (33, 11), (22, 13)),
        ((11, 15), (36, 14), (21, 9), (26, 12)),
        ((9, 21), (38, 20), (20, 14), (27, 17)),
        ((8, 30), (39, 30), (19, 20), (28, 22)),
        ((7, 42), (40, 42), (5, 43), (42, 43)),
        (),
    )

    def _crumb_fx(f, pose: Pose) -> None:
        _crumbs(f, shake_crumbs[pose.i])
        if pose.i in (1, 2, 3, 4):
            side = -1 if pose.dx > 0 else 1
            x = 8 if side < 0 else 39
            f.paint(line(x, 26, x, 30), bp.ARC_FADE)

    def _lever_fx(f, pose: Pose) -> None:
        """Click down, a beat of toasting, then BOING: everything springs up."""
        i = pose.i
        if i == 1:
            f.paint(line(44, 30, 45, 32), bp.ARC)
        if i in (2, 3):
            # The slots heat up: a shimmer each.
            for k, x0 in enumerate(slots):
                _shimmer(f, x0 + 4, deck - 2, 3 + i - 2, i + 2 * k, heat)
        if i == 4:
            f.paint(line(44, 20, 46, 18) | line(44, 24, 46, 24), bp.ARC)
            f.paint(line(11, 9, 9, 7) | line(36, 9, 38, 7), bp.ARC)
        if i == 5:
            f.paint(line(44, 23, 46, 22), bp.ARC_FADE)

    #: Butter: the pat's (x, y) top-left per frame (None = not there yet).
    butter_fall = (None, (27, 1), (27, 6), (27, 11), None, None, None, None)

    def _butter_fx(f, pose: Pose) -> None:
        """A pat of butter drops onto the right slice and melts in; it shines."""
        i = pose.i
        at = butter_fall[i]
        if at is not None:
            pat = rect(at[0], at[1], at[0] + 4, at[1] + 2)
            f.part(pat, {p: butter if p[1] == at[1] or p[0] == at[0] else butter_dark for p in pat})
            f.paint({(at[0] + 1, at[1])}, FX_WHITE)
        x0, top = slots[1], rest + (1 if pose.stretch < 0 else 0)
        if i == 4:
            pat = rect(x0 + 1, top - 1, x0 + 7, top)
            f.part(pat, {p: butter if p[1] == top - 1 else butter_dark for p in pat})
            ticks = line(x0 - 1, top - 3, x0 - 2, top - 4) | line(x0 + 9, top - 3, x0 + 10, top - 4)
            f.paint(ticks, bp.ARC)
        elif i in (5, 6):
            # Melted: a glossy pool on the crumb with a drip down the side.
            f.paint(rect(x0 + 2, top + 1, x0 + 6, top + 1), butter)
            drip = 1 + min(i - 5, 2)
            f.paint(rect(x0 + 6, top + 2, x0 + 6, top + 1 + drip), butter_dark)
            f.paint({(x0 + 3, top + 1)}, FX_WHITE)
            if i in (5, 6):
                bp.fx_sparkles(f, i - 4, ((x0 + 11, top - 3, 0),))

    def _heat_fx(f, pose: Pose) -> None:
        """Toasty basks: the slots glow, heat shimmers up and the dial turns;
        then the toast pops with a ding."""
        i = pose.i
        if 2 <= i <= 5:
            for k, x0 in enumerate(slots):
                color = heat if (i + k) % 2 == 0 else heat_fade
                top = _tops(pose)[k] - pose.stretch
                _shimmer(f, x0 + 4, top - 2 - (i % 2), 3 + min(i - 2, 2), i + 3 * k, color)
        if i == 6:
            f.paint(line(11, 13, 9, 11) | line(36, 13, 38, 11), bp.ARC)
            bp.fx_sparkles(f, 1, ((41, 9, 0),))
        if i == 7:
            bp.fx_sparkles(f, 3, ((41, 9, 0),))

    acts = (
        bp.IdleAct(
            "toast_pop",
            8,
            10,
            act_pose(
                "toast_pop",
                eyes=("open", "closed", "wide", "up_left", "up_right", "wide", "open", "happy"),
                mouth=("rest", "closed", "open", "open", "wide", "half", "rest", "smile"),
                stretch=(0, -1, 1, 0, 0, 0, -1, 0),
            ),
            _pop_fx,
        ),
        bp.IdleAct(
            "toast_juggle",
            8,
            8,
            act_pose(
                "toast_juggle",
                dx=(0, -1, -1, 0, 1, 1, 0, 0),
                eyes=(
                    "open",
                    "up_left",
                    "up_left",
                    "up_right",
                    "up_right",
                    "up_right",
                    "open",
                    "happy",
                ),
                mouth=("rest", "half", "open", "rest", "open", "half", "rest", "smile"),
            ),
            _juggle_fx,
        ),
        bp.IdleAct(
            "crumb_shake",
            8,
            10,
            act_pose(
                "crumb_shake",
                dx=(0, -2, 2, -2, 2, -1, 0, 0),
                eyes=("open", "closed", "closed", "closed", "closed", "open", "happy", "open"),
                mouth=("rest", "wide", "open", "wide", "open", "closed", "smile", "rest"),
            ),
            _crumb_fx,
        ),
        bp.IdleAct(
            "lever_bounce",
            8,
            8,
            act_pose(
                "lever_bounce",
                dy=(0, 0, 0, 0, -2, -1, 0, 0),
                stretch=(0, -1, -1, 0, 1, 0, 0, 0),
                eyes=("open", "closed", "down", "down", "wide", "happy", "happy", "open"),
                mouth=("rest", "closed", "closed", "closed", "open", "smile", "smile", "rest"),
            ),
            _lever_fx,
        ),
        bp.IdleAct(
            "butter_shine",
            8,
            8,
            act_pose(
                "butter_shine",
                stretch=(0, 0, 0, 0, -1, 0, 0, 0),
                eyes=("open", "up_right", "up_right", "up_right", "wide", "happy", "happy", "open"),
                mouth=("rest", "half", "half", "open", "wide", "smile", "smile", "rest"),
            ),
            _butter_fx,
        ),
        bp.IdleAct(
            "heat_shimmer",
            8,
            8,
            act_pose(
                "heat_shimmer",
                eyes=("open", "down", "happy", "happy", "happy", "happy", "wide", "open"),
                mouth=("rest", "closed", "smile", "smile", "smile", "smile", "open", "rest"),
                stretch=(0, 0, 0, 1, 1, 0, 1, 0),
            ),
            _heat_fx,
        ),
    )

    anchors = bp.Anchors(
        arcs_left=(11, 14),
        arcs_right=(36, 14),
        dots=(19, 4),
        zzz=(30, 15),
        bang=(41, 3),
        sweat=(39, 13),
        sparkles=((6, 12, 1), (38, 4, 2), (4, 38, 3), (43, 30, 3)),
        laptop=(17, 34),
        magnifier=(bp.CX, 11),
    )

    return bp.PetDesign(
        id="toasty",
        name="Toasty",
        description="A cheerful toaster that glows while it thinks and pops up when it's done.",
        draw=draw_toasty,
        pose=toasty_pose,
        anchors=anchors,
        fx={
            "thinking": toasty_thinking,
            "talking": toasty_talking,
            "success": toasty_success,
            "error": toasty_error,
            "sleeping": toasty_sleeping,
            "working": toasty_working,
        },
        acts=acts,
        waist=40,
    )
