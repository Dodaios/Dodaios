"""Nox: the little owl.

A round, plump owl in soft brown-grey: one egg-shaped body with the head
on top, small ear tufts, a pale heart-shaped facial disc with two BIG amber
eyes, a tiny hooked beak, a speckled chest, folded wings and small talons.
Wise, calm and a bookworm: it turns and tilts its head to listen, puts a wing
to its chin while it thinks, puts on round reading glasses to work, sweeps a
magnifier while it searches and sinks into its feathers to sleep.

The head (disc, eyes, beak, tufts) is painted into its own frame and laid
over the body, sheared column by column for a tilt and moved for a sink, so
the face stays crisp. A head turn slides the face inside the head's round,
which also gives the famous owl head spin.
"""

import math
from dataclasses import dataclass, replace


def design(bp):  # noqa: C901, PLR0915 - one closure per pet keeps the module self-contained
    hexc = bp.hexc
    ellipse, rect, line, polygon = bp.ellipse, bp.rect, bp.line, bp.polygon
    mirrored, shifted, from_rows = bp.mirrored, bp.shifted, bp.from_rows
    outer_ring, eroded, shade = bp.outer_ring, bp.eroded, bp.shade
    Frame, Pose, base_pose = bp.Frame, bp.Pose, bp.base_pose
    OUTLINE, FX_WHITE, FX_DIM, CX, CELL = bp.OUTLINE, bp.FX_WHITE, bp.FX_DIM, bp.CX, bp.CELL

    # -- Palette ---------------------------------------------------------------

    base = hexc("#8c7d70")
    light = hexc("#b3a597")
    shine = hexc("#cfc3b6")
    dark = hexc("#66584c")
    wing = hexc("#796a5d")
    wing_light = hexc("#a39282")
    wing_dark = hexc("#54483d")
    wing_bar = hexc("#c9b9a6")
    disc = hexc("#f1e7d7")
    disc_rim = hexc("#c8b399")
    lid = hexc("#d9c9b1")
    chest = hexc("#e3d7c4")
    chest_shade = hexc("#cdbfa9")
    speck = hexc("#7d6a59")
    amber = hexc("#f7a928")
    amber_light = hexc("#ffd66e")
    amber_dark = hexc("#cf7019")
    pupil = hexc("#1a1216")
    beak = hexc("#e9b54f")
    beak_light = hexc("#ffe39a")
    beak_dark = hexc("#a8742e")
    talon = hexc("#e2a84a")
    talon_dark = hexc("#9a6a2a")
    blush = hexc("#f2a0a8")
    glasses = hexc("#3a3146")
    glasses_shine = hexc("#cfe6ff")
    book = hexc("#4f7fd1")
    book_light = hexc("#7fa6ea")
    book_dark = hexc("#33589e")
    page = hexc("#f7f1e3")
    page_line = hexc("#b9ae9b")
    ribbon = hexc("#e5383b")
    note = bp.ARC
    note_fade = bp.ARC_FADE

    # -- Small helpers ---------------------------------------------------------

    def inside(mask, margin=1):
        """``mask`` clipped so it AND its outline stay in the cell."""
        return {
            (x, y) for x, y in mask if margin <= x < CELL - margin and margin <= y < CELL - margin
        }

    def feathers(f, mask, depth=2):
        f.part(mask, shade(mask, base, light=light, dark=dark, dark_depth=depth))

    def wing_fill(mask):
        colors = shade(mask, wing, light=wing_light, dark=wing_dark, dark_depth=1)
        return colors

    # -- Geometry --------------------------------------------------------------

    head_c = (CX, 17.5)
    head_r = (12.5, 10.0)
    body_mask = ellipse(CX, 33.5, 12.5, 11.0)

    #: Ear tufts (left; the right one is mirrored): rest, perked, flattened.
    tufts = {
        "rest": [(12.0, 13.5), (12.0, 4.5), (14.5, 6.5), (19.0, 9.5)],
        "perk": [(12.0, 13.5), (11.5, 3.0), (14.5, 5.5), (19.0, 9.5)],
        "flat": [(12.0, 14.0), (7.5, 9.5), (11.0, 9.0), (18.0, 10.0)],
        "droop": [(12.5, 13.5), (10.5, 7.5), (14.0, 8.0), (18.5, 10.0)],
        "flick": [(12.0, 13.5), (9.5, 4.0), (13.0, 6.0), (19.0, 9.5)],
    }

    #: Top-left of each eye box at the neutral face.
    eye_at = ((16, 13), (25, 13))

    @dataclass(frozen=True)
    class Look:
        """How Nox holds itself beyond the pose's eyes and mouth."""

        #: The face slides this far sideways inside the head (a head turn).
        turn: int = 0
        #: The head seen from behind (mid head spin).
        back: bool = False
        #: Column shear of the head (positive drops the right side).
        tilt: float = 0.0
        #: Head offset from the body (a sink, a lift).
        head: tuple[int, int] = (0, 0)
        tufts: tuple[str, str] = ("rest", "rest")
        #: Wing styles, left and right (the right one is mirrored).
        wings: tuple[str, str] = ("fold", "fold")
        #: Round reading glasses on the beak.
        glasses: bool = False
        #: How ruffled the feathers are (0 = smooth).
        ruffle: int = 0
        #: How puffed up the whole body is (0 = normal).
        puff: float = 0.0
        blush: bool = True
        #: Dangling talons (held up by the mouse).
        dangle: bool = False

    # -- Eyes ------------------------------------------------------------------

    eye_disc = ellipse(3.5, 3.5, 3.6, 3.6)

    spiral = ("#####", "....#", "###.#", "#...#", "#####")

    def spin_rows(k):
        rows = [list(r) for r in spiral]
        for _ in range(k % 4):
            rows = [list(r) for r in zip(*rows[::-1], strict=True)]
        return tuple("".join(r) for r in rows)

    #: Closed-eye strokes on the 7 x 7 box (left eye; the right is mirrored).
    eye_lines = {
        "closed": (".......", ".......", ".......", "#.....#", ".#...#.", "..###..", "......."),
        "sleep": (".......", ".......", ".......", "#.....#", ".##.##.", "..###..", "......."),
        "happy": (".......", "..###..", ".#...#.", "#.....#", ".......", ".......", "......."),
        "x": (".......", ".#...#.", "..#.#..", "...#...", "..#.#..", ".#...#.", "......."),
    }

    def draw_eye(f, style, x, y, right, frame_i=0):
        mask = shifted(eye_disc, x, y)
        if style in eye_lines:
            rows = eye_lines[style]
            if right:
                rows = tuple(r[::-1] for r in rows)
            if style == "x":
                f.paint(mask, lid)
            f.paint(from_rows(x, y, rows), OUTLINE)
            return
        f.paint(outer_ring(mask), OUTLINE)
        rim = mask - eroded(mask)
        colors = {p: amber for p in mask}
        for p in rim:
            if p[1] >= y + 4 or (p[0] >= x + 5 and p[1] >= y + 2):
                colors[p] = amber_dark
        for p in mask:
            if p not in rim and p[1] == y + 1 and p[0] <= x + 4:
                colors[p] = amber_light
        f.paint_map(colors)
        if style == "spin":
            f.paint(from_rows(x + 1, y + 1, spin_rows(frame_i)), pupil)
            return
        big = style in ("wide", "heavy_wide")
        offs = {
            "open": (0, 0),
            "wide": (0, 0),
            "look_left": (-1, 0),
            "look_right": (1, 0),
            "up_left": (-1, -1),
            "up_right": (1, -1),
            "down": (0, 1),
            "read": (0, 1),
            "half": (0, 1),
            "heavy": (0, 1),
            "squint": (0, 1),
        }
        ox, oy = offs.get(style, (0, 0))
        if big:
            pup = rect(x + 1, y + 1, x + 5, y + 5) - {
                (x + 1, y + 1), (x + 5, y + 1), (x + 1, y + 5), (x + 5, y + 5)
            }
        else:
            pup = rect(x + 2, y + 2, x + 4, y + 4)
        pup = shifted(pup, ox, oy)
        f.paint(pup & mask, pupil)
        gx, gy = (x + 4 + ox, y + 2 + oy)
        f.paint({(gx, gy)} & mask, FX_WHITE)
        if big:
            f.paint({(gx, gy - 1), (gx - 1, gy - 1), (x + 2, y + 4)} & mask, FX_WHITE)
        # Lids: a feathered lid comes down over the top of the eye.
        if style == "squint":
            # Squeezed nearly shut: a feathered lid with a thin amber slit.
            f.paint(mask, lid)
            f.paint(line(x, y + 3, x + 6, y + 3), OUTLINE)
            f.paint(line(x + 2, y + 4, x + 4, y + 4), amber)
            f.paint({(x + 1, y + 2), (x + 5, y + 2)} if not right else {(x + 5, y + 2)}, OUTLINE)
            return
        cover = {"down": 1, "heavy": 2, "half": 3}.get(style, 0)
        if cover:
            lid_px = {p for p in mask if p[1] < y + cover}
            f.paint(lid_px, lid)
            edge = {(px, py) for px, py in mask if py == y + cover} | {
                (px, py) for px, py in outer_ring(mask) if py == y + cover
            }
            f.paint(edge, OUTLINE)

    def draw_eyes(f, style, turn, frame_i=0):
        left, _, right = style.partition("/")
        right = right or left
        for side, (x, y) in enumerate(eye_at):
            name = right if side else left
            if name == "spin" and side:
                draw_eye(f, name, x + turn, y, True, frame_i + 2)
            else:
                draw_eye(f, name, x + turn, y, bool(side), frame_i)

    # -- Beak ------------------------------------------------------------------

    def draw_beak(f, mouth, tx):
        """The hooked beak; talking drops the lower half below it."""
        x = 22 + tx
        upper = from_rows(x, 19, (".##.", "####", ".##."))
        gap = {"half": 1, "open": 2, "wide": 3, "smile": 1, "hoot": 2}.get(mouth, 0)
        if gap == 0:
            tip = {(x + 1, 22), (x + 2, 22)}
            f.part(upper | tip, beak)
            f.paint({(x + 1, 19)}, beak_light)
            f.paint({(x, 20)}, beak_light)
            f.paint({(x + 2, 22), (x + 3, 20)}, beak_dark)
            return
        inner = rect(x + 1, 22, x + 2, 21 + gap)
        lower = {(x + 1, 22 + gap), (x + 2, 22 + gap)}
        if mouth == "wide":
            inner |= {(x, 23), (x + 3, 23)}
        f.part(upper | inner | lower, beak)
        f.paint({(x + 1, 19), (x, 20)}, beak_light)
        f.paint({(x + 3, 20)}, beak_dark)
        f.paint(inner, bp.MOUTH_DARK)
        if gap >= 3:
            f.paint({(x + 1, 21 + gap), (x + 2, 21 + gap)}, bp.TONGUE)
        f.paint(lower, beak_dark)

    # -- Head ------------------------------------------------------------------

    def head_mask(look):
        head = ellipse(*head_c, *head_r)
        left = polygon(tufts[look.tufts[0]])
        right = mirrored(polygon(tufts[look.tufts[1]]))
        return head, left, right

    def disc_mask(tx):
        lobe = ellipse(19.5 + tx, 17.5, 6.4, 6.6)
        lobe_r = ellipse(28.5 + tx, 17.5, 6.4, 6.6)
        chin = polygon([(16.0 + tx, 20.0), (32.0 + tx, 20.0), (CX + tx, 27.5)])
        return lobe | lobe_r | chin

    def draw_head(f, pose, look):
        """The head at the neutral spot, onto ``f`` (a sub-frame)."""
        head, tuft_l, tuft_r = head_mask(look)
        whole = head | tuft_l | tuft_r
        colors = shade(whole, base, light=light, dark=dark, dark_depth=1)
        for p in tuft_l | tuft_r:
            if p not in head:
                colors[p] = dark if colors[p] == base else colors[p]
        # The tuft tips catch the light.
        for tuft in (tuft_l, tuft_r):
            top = min(y for _x, y in tuft)
            for p in tuft:
                if p[1] <= top + 1 and p not in head:
                    colors[p] = light
        f.paint(outer_ring(whole), OUTLINE)
        f.paint_map(colors)
        f.paint({(20, 8), (21, 8), (22, 8), (19, 9), (26, 8), (27, 8)} & head, shine)
        face = eroded(head)
        if look.back:
            # The back of the head: speckled feathers and a darker nape.
            for k, (x, y) in enumerate(((16, 12), (22, 11), (28, 12), (19, 15), (25, 15),
                                        (31, 16), (16, 19), (22, 19), (28, 19), (19, 23),
                                        (25, 23))):
                f.paint({(x, y), (x + 1, y + 1), (x + 2, y)} & face, light if k % 2 else dark)
            f.paint({(x, y) for x, y in face if y >= 26}, dark)
            return
        tx = look.turn
        dm = disc_mask(tx) & face
        dcol = {p: disc for p in dm}
        for p in dm - eroded(dm):
            dcol[p] = disc_rim
        f.paint_map(dcol)
        if look.blush and abs(tx) <= 2:
            f.paint({(15 + tx, 22), (16 + tx, 22), (31 + tx, 22), (32 + tx, 22)} & dm, blush)
        sub = Frame()
        draw_eyes(sub, pose.eyes, tx, pose.i)
        if look.glasses:
            draw_glasses(sub, tx)
        draw_beak(sub, pose.mouth, tx)
        f.paint_map({p: c for p, c in sub.px.items() if p in head})

    def draw_glasses(f, tx):
        """Small round reading glasses perched on the beak."""
        for x, y in eye_at:
            x += tx
            lens = ellipse(x + 3.5, y + 3.5, 4.4, 4.4)
            rim = {(px, py) for px, py in outer_ring(lens) if py >= y + 4}
            f.paint(rim | line(x - 1, y + 4, x + 7, y + 4), glasses)
            # The lens: the lower half of the eye a shade paler, with a glint.
            f.paint({(x + 1, y + 6), (x + 2, y + 6)}, glasses_shine)

    def lay(f, sub, k, offset=(0, 0)):
        """Lay ``sub`` onto ``f`` sheared by ``k`` around the centre."""
        ox, oy = offset
        out = {}
        for (x, y), color in sub.px.items():
            ny = y + oy + math.floor((x + 0.5 - CX) * k + 0.5)
            out[(x + ox, ny)] = color
        f.paint_map(out)

    # -- Wings -----------------------------------------------------------------

    def bezier(root, ctrl, tip, r0, r1, steps=8):
        mask = set()
        for k in range(steps + 1):
            t = k / steps
            x = (1 - t) ** 2 * root[0] + 2 * (1 - t) * t * ctrl[0] + t * t * tip[0]
            y = (1 - t) ** 2 * root[1] + 2 * (1 - t) * t * ctrl[1] + t * t * tip[1]
            r = r0 + (r1 - r0) * t
            mask |= ellipse(x, y, r, r)
        return mask

    #: Wing shapes for the LEFT wing: (root, ctrl, tip, root radius, tip radius),
    #: and whether it sits behind the body.
    wing_shapes = {
        "fold": (((14.0, 27.5), (11.0, 33.0), (15.0, 41.5), 4.0, 1.6), False),
        "half": (((15.0, 28.0), (9.0, 27.0), (5.0, 33.0), 3.8, 1.6), True),
        "spread": (((15.0, 28.0), (8.0, 22.0), (3.5, 18.5), 3.8, 1.8), True),
        "up": (((15.0, 27.0), (10.0, 18.0), (7.0, 10.5), 3.8, 1.8), True),
        "down": (((15.0, 28.5), (10.0, 33.0), (7.5, 40.0), 3.8, 1.6), True),
        "chin": (((14.0, 29.0), (16.0, 33.5), (21.5, 26.0), 3.6, 2.2), False),
        "type_up": (((14.0, 28.0), (12.5, 35.0), (18.0, 38.5), 3.8, 2.0), False),
        "type_down": (((14.0, 28.0), (12.5, 36.0), (18.0, 40.5), 3.8, 2.0), False),
        "hold": (((14.0, 28.0), (12.0, 35.0), (17.0, 37.5), 3.8, 2.2), False),
        "stretch": (((15.0, 28.0), (7.0, 26.0), (2.5, 29.5), 3.8, 1.6), True),
    }

    def wing_mask(style):
        (root, ctrl, tip, r0, r1), _behind = wing_shapes[style]
        mask = bezier(root, ctrl, tip, r0, r1)
        if style in ("spread", "up", "half", "stretch", "down"):
            # Fingered primaries at the open wing's end.
            tx, ty = tip
            ang = math.atan2(ty - ctrl[1], tx - ctrl[0])
            for k, da in enumerate((-0.7, -0.15, 0.4)):
                a = ang + da + math.pi / 2 * 0.5
                ex = tx + math.cos(a) * (2.5 + k % 2)
                ey = ty + math.sin(a) * (2.5 + k % 2)
                mask |= line(math.floor(tx), math.floor(ty), math.floor(ex), math.floor(ey))
        return inside(mask)

    def draw_wing(f, style, right):
        mask = wing_mask(style)
        if right:
            mask = mirrored(mask)
        colors = wing_fill(mask)
        (root, ctrl, tip, _r0, _r1), _ = wing_shapes[style]
        # Pale feather bars across the wing, towards its end.
        for t in (0.55, 0.75):
            x = (1 - t) ** 2 * root[0] + 2 * (1 - t) * t * ctrl[0] + t * t * tip[0]
            y = (1 - t) ** 2 * root[1] + 2 * (1 - t) * t * ctrl[1] + t * t * tip[1]
            bx, by = math.floor(x), math.floor(y)
            if right:
                bx = 2 * CX - 1 - bx
            for p in ((bx - 1, by), (bx, by), (bx + 1, by)):
                if p in mask and colors.get(p) == wing:
                    colors[p] = wing_bar
        f.part(mask, colors)

    # -- Body ------------------------------------------------------------------

    def ruffled(mask, amount, phase):
        """Spiky tufts sticking out of the outline: ruffled feathers."""
        if amount <= 0:
            return mask
        out = set(mask)
        cx, cy = 24.0, 31.0
        for k in range(14):
            a = 2 * math.pi * (k / 14 + phase * 0.03)
            for r in range(10, 22):
                x = math.floor(cx + math.cos(a) * r)
                y = math.floor(cy + math.sin(a) * r * 0.95)
                if (x, y) not in mask:
                    for s in range(amount):
                        out.add((math.floor(cx + math.cos(a) * (r + s)),
                                 math.floor(cy + math.sin(a) * (r + s) * 0.95)))
                    break
        return inside(out)

    specks = ((20, 30), (26, 30), (17, 34), (23, 33), (29, 34), (20, 37), (26, 37), (23, 40))

    def draw_body(f, look, i):
        body = body_mask
        if look.puff:
            body = ellipse(CX, 33.5 - look.puff / 2, 12.5 + look.puff, 11.0 + look.puff / 2)
        body = ruffled(body, look.ruffle, i)
        feathers(f, inside(body))
        belly = ellipse(CX, 35.0, 8.0, 7.5) & eroded(body)
        f.paint_map({p: chest_shade if p[1] >= 41 else chest for p in belly})
        for x, y in specks:
            v = {(x, y), (x + 1, y + 1), (x + 2, y)} & belly
            f.paint(v, speck)

    def draw_feet(f, look):
        if look.dangle:
            for x in (19, 26):
                leg = rect(x, 43, x + 2, 44)
                toes = {(x - 1, 45), (x + 1, 46), (x + 3, 45)}
                f.part(leg | toes, talon)
                f.paint({(x - 1, 45), (x + 1, 46), (x + 3, 45)}, talon_dark)
            return
        for x in (18, 26):
            foot = rect(x, 44, x + 3, 44) | {(x, 45), (x + 1, 45), (x + 3, 45)}
            f.part(foot, talon)
            f.paint({(x, 45), (x + 3, 45)}, talon_dark)

    # -- Looks per state ---------------------------------------------------------

    listen_tilt = (0.0, 0.1, 0.17, 0.17, 0.1, 0.0)
    listen_turn = (0, 1, 1, 1, 1, 0)
    idle_turn = (0, 0, 0, 1, 1, 0, 0)
    flap = ("up", "half", "down", "half", "up", "half")
    hop_wings = ("half", "spread", "up", "up", "up", "spread", "half", "fold")

    def look_for(pose):
        state, i = pose.state, pose.i
        if state == "idle":
            turn = idle_turn[i] if i < len(idle_turn) else 0
            return Look(turn=turn)
        if state == "listening":
            return Look(turn=listen_turn[i], tilt=listen_tilt[i], tufts=("perk", "perk"))
        if state == "thinking":
            tap = i % 4 == 2
            return Look(tilt=-0.06, wings=("fold", "chin"), head=(0, 1 if tap else 0))
        if state == "talking":
            # The tufts lift from the first frame, so talking never reads as idle.
            t = ("flick", "flick", "perk", "perk")[i]
            return Look(tufts=(t, t))
        if state == "success":
            return Look(wings=(hop_wings[i], hop_wings[i]), tufts=("perk", "perk"))
        if state == "error":
            return Look(ruffle=(1, 2, 2, 2, 1, 1)[i], tufts=("flick", "flat"), blush=False)
        if state == "sleeping":
            return Look(head=(0, 3), tufts=("droop", "droop"), blush=False)
        if state == "working":
            up = i % 2 == 0
            return Look(
                glasses=True,
                wings=("type_up" if up else "type_down", "type_down" if up else "type_up"),
            )
        if state == "searching":
            sweep = bp.SEARCH_SWEEP[i % 8]
            turn = (sweep > 2) - (sweep < -2)
            return Look(turn=2 * turn, wings=("fold", "fold"))
        if state == "held":
            w = flap[i % len(flap)]
            return Look(wings=(w, w), dangle=True, tufts=("perk", "perk"))
        return Look()

    # -- Poses -----------------------------------------------------------------

    idle_eyes = ("open", "open", "open", "look_right", "look_right", "open", "open")
    error_eyes = ("x", "x", "spin", "spin", "spin", "spin")
    #: A lower hop than the shared one: the ear tufts must stay in the cell.
    hop = (0, -1, -2, -3, -3, -2, 0, 0)

    def nox_pose(state, i):
        pose = base_pose(state, i)
        if state == "idle" and i < len(idle_eyes):
            return replace(pose, eyes=idle_eyes[i])
        if state == "thinking":
            return replace(pose, eyes=("up_left" if i < 4 else "up_right") + "/squint")
        if state == "success":
            return replace(pose, dy=hop[i], mouth="smile")
        if state == "error":
            return replace(pose, eyes=error_eyes[i], mouth="rest")
        if state == "sleeping":
            return replace(pose, eyes="sleep", mouth="rest")
        if state == "working":
            return replace(pose, eyes="read", mouth="rest")
        if state == "searching":
            return replace(pose, mouth="rest")
        if state == "held":
            return replace(pose, mouth="half")
        if state == "listening":
            return replace(pose, mouth="rest")
        return pose

    # -- Drawing ---------------------------------------------------------------

    def draw_owl(f, pose, look):
        planted = (pose.dx, min(pose.dy, 0))
        with f.offset(pose.dx, pose.dy):
            for side, style in enumerate(look.wings):
                if wing_shapes[style][1]:
                    draw_wing(f, style, bool(side))
            draw_body(f, look, pose.i)
        with f.offset(*planted):
            draw_feet(f, look)
        with f.offset(pose.dx, pose.dy):
            sub = Frame()
            draw_head(sub, pose, look)
            lay(f, sub, look.tilt, look.head)
            for side, style in enumerate(look.wings):
                if not wing_shapes[style][1]:
                    draw_wing(f, style, bool(side))

    def draw(f, pose):
        if pose.act:
            look, extra = act_look(pose)
            draw_owl(f, pose, look)
            if extra is not None:
                extra(f, pose)
            return
        draw_owl(f, pose, look_for(pose))

    # -- Effects ---------------------------------------------------------------

    feather_rows = ("..##", ".##.", "##..", "#...")

    def loose_feather(f, x, y, flip=False):
        rows = feather_rows if not flip else tuple(r[::-1] for r in feather_rows)
        cells = from_rows(x, y, rows)
        cells = inside(cells)
        f.part(cells, wing_light)
        f.paint({(x, y + 3) if not flip else (x + 3, y + 3)} & cells, wing_dark)

    def error_fx(f, pose):
        i = pose.i
        bp.fx_bang(f, 42, 4)
        with f.offset(pose.dx, 0):
            bp.fx_sweat(f, i, 36, 11)
        if i >= 1:
            loose_feather(f, 6, 26 + 2 * i, flip=i % 2 == 0)
            loose_feather(f, 39, 30 + i, flip=i % 2 == 1)

    question = ("##.", "..#", ".#.", "...", ".#.")
    bulb = (".#.", "#o#", "#o#", ".#.", ".b.")

    def thinking_fx(f, pose):
        """A thought bubble puffs up beside the tufts: a question, then an idea."""
        i = pose.i
        with f.offset(pose.dx, pose.dy):
            f.part({(36, 13)}, FX_WHITE)
            if i >= 1:
                f.part(rect(38, 10, 39, 11), FX_WHITE)
            if i < 2:
                return
            cloud = inside(
                ellipse(42.0, 5.5, 4.6, 3.6) | ellipse(39.5, 7.0, 2.4, 2.2)
                | ellipse(44.5, 7.0, 2.4, 2.2)
            )
            f.part(cloud, {p: FX_WHITE if p[1] < 8 else FX_DIM for p in cloud})
            if i < 6:
                f.paint(from_rows(41, 3 + (i % 2), question), note)
            else:
                f.glyph(41, 3, bulb, {"#": bp.SPARK, "o": bp.SPARK_CORE, "b": FX_DIM})
                if i == 7:
                    bp.fx_sparkles(f, 1, ((37, 3, 0),))

    def working_fx(f, pose):
        bp.fx_laptop(f, pose.i, 17, 34)

    def searching_fx(f, pose):
        i = pose.i
        with f.offset(pose.dx, pose.dy):
            bp.fx_magnifier(f, i, CX, 32)

    # -- Idle acts ---------------------------------------------------------------

    spin_turn = (0, 2, 4, 9, 9, -4, -2, 0)
    stretch_wings = (
        ("fold", "fold"),
        ("half", "fold"),
        ("stretch", "fold"),
        ("stretch", "fold"),
        ("fold", "half"),
        ("fold", "stretch"),
        ("fold", "stretch"),
        ("fold", "fold"),
    )
    blink_eyes = ("open", "heavy", "half", "closed", "closed", "half", "heavy", "open")
    ruffle_amount = (0, 1, 2, 3, 3, 2, 1, 0)
    ruffle_puff = (0.0, 0.5, 1.0, 1.5, 1.5, 1.0, 0.5, 0.0)
    hoot_mouth = ("rest", "half", "hoot", "hoot", "rest", "half", "hoot", "rest")
    hoot_dy = (0, -1, -2, -2, 0, -1, -2, 0)

    def act_pose(name, i):
        if name == "head_spin":
            eyes = "open" if abs(spin_turn[i]) < 4 else "look_left"
            return Pose("idle", i, eyes=eyes if spin_turn[i] >= 0 else "look_right")
        if name == "wing_stretch":
            eyes = "happy" if 2 <= i <= 6 else "open"
            return Pose("idle", i, eyes=eyes, stretch=1 if 2 <= i <= 5 else 0)
        if name == "slow_blink":
            return Pose("idle", i, eyes=blink_eyes[i], stretch=1 if i in (3, 4) else 0)
        if name == "read_book":
            eyes = "look_left/look_left" if i < 3 else "look_right/look_right"
            if i == 7:
                eyes = "happy"
            return Pose("idle", i, eyes=eyes, mouth="rest")
        if name == "feather_ruffle":
            eyes = "closed" if 2 <= i <= 5 else "open"
            return Pose("idle", i, eyes=eyes, dx=(0, 0, -1, 1, -1, 1, 0, 0)[i])
        if name == "hoot":
            eyes = "closed" if hoot_mouth[i] == "hoot" else "open"
            return Pose("idle", i, eyes=eyes, mouth=hoot_mouth[i], stretch=-hoot_dy[i] // 2)
        raise KeyError(name)

    def act_look(pose):
        name, i = pose.act, pose.i
        if name == "head_spin":
            t = spin_turn[i]
            return Look(turn=t, back=abs(t) >= 9, blush=abs(t) < 2), None
        if name == "wing_stretch":
            return Look(wings=stretch_wings[i], tufts=("perk", "perk") if 2 <= i <= 6
                        else ("rest", "rest")), None
        if name == "slow_blink":
            return Look(tilt=(0, 0, 0.04, 0.06, 0.06, 0.04, 0, 0)[i]), None
        if name == "read_book":
            return Look(glasses=i < 7, wings=("hold", "hold"), head=(0, 1)), draw_book
        if name == "feather_ruffle":
            return Look(ruffle=ruffle_amount[i], puff=ruffle_puff[i],
                        tufts=("flick", "flick") if 2 <= i <= 5 else ("rest", "rest")), None
        if name == "hoot":
            return Look(head=(0, hoot_dy[i]), tufts=("perk", "perk")
                        if hoot_mouth[i] == "hoot" else ("rest", "rest")), None
        raise KeyError(name)

    def draw_book(f, pose):
        """An open book held up in front of the chest; a page turns at frame 4-5."""
        i = pose.i
        with f.offset(pose.dx, pose.dy):
            cover = rect(13, 33, 34, 42)
            f.part(cover, shade(cover, book, light=book_light, dark=book_dark, dark_depth=1))
            left = rect(14, 33, 23, 40)
            right = rect(24, 33, 33, 40)
            f.paint(left | right, page)
            f.paint(line(CX - 1, 33, CX - 1, 41) | line(CX, 33, CX, 41), page_line)
            for y in (35, 37, 39):
                f.paint(line(15, y, 21, y) | line(26, y, 32, y), page_line)
            if i in (4, 5):
                # The page lifting over the spine.
                flip = rect(18, 31, 23, 38) if i == 4 else rect(24, 31, 28, 38)
                f.part(flip, page)
                f.paint(line(min(x for x, _ in flip) + 1, 33, max(x for x, _ in flip) - 1, 33),
                        page_line)
            f.paint({(30, 41), (30, 42), (30, 43), (31, 43)}, ribbon)
            # The wing tips holding it at the sides.
            for x in (13, 34):
                tip = ellipse(x + 0.5, 37.5, 2.0, 2.5)
                f.part(tip, wing_fill(tip))

    def wing_stretch_fx(f, pose):
        if pose.i in (3, 6):
            x = 4 if pose.i == 3 else 43
            bp.fx_sparkles(f, 1, ((x, 22, 0),))

    def ruffle_fx(f, pose):
        i = pose.i
        if 3 <= i <= 6:
            age = i - 3
            loose_feather(f, 6 - age, 18 + 3 * age)
            loose_feather(f, 39 + age, 16 + 3 * age, flip=True)
            f.paint({(10, 12 + age), (37, 11 + age)}, FX_DIM)

    def hoot_fx(f, pose):
        i = pose.i
        for start in (2, 6):
            age = i - start
            if 0 <= age <= 1:
                f.paint({(37 + age, 14 - age), (38 + age, 13 - age), (39 + age, 14 - age)},
                        note if age == 0 else note_fade)
                bp.fx_arcs(f, 2 + age * 2, (11, 18), (36, 18))

    def slow_blink_fx(f, pose):
        if pose.i in (3, 4):
            f.paint({(38, 12), (39, 11), (40, 12)}, FX_DIM)

    def act(name, fps, fx=None):
        return bp.IdleAct(name, 8, fps, lambda i: act_pose(name, i), fx)

    acts = (
        act("head_spin", 8),
        act("wing_stretch", 7, wing_stretch_fx),
        act("slow_blink", 5, slow_blink_fx),
        act("read_book", 5),
        act("feather_ruffle", 9, ruffle_fx),
        act("hoot", 6, hoot_fx),
    )

    return bp.PetDesign(
        id="nox",
        name="Nox",
        description=(
            "A little owl who turns its head to listen, puts on reading glasses to work"
            " and spreads its wings when something goes right."
        ),
        draw=draw,
        pose=nox_pose,
        waist=40,
        anchors=bp.Anchors(
            arcs_left=(9, 16),
            arcs_right=(38, 16),
            dots=(31, 3),
            zzz=(35, 15),
            bang=(42, 4),
            sparkles=((6, 8, 1), (41, 6, 2), (10, 4, 4), (38, 3, 5)),
            laptop=(17, 34),
            magnifier=(CX, 34),
        ),
        fx={
            "thinking": thinking_fx,
            "error": error_fx,
            "working": working_fx,
            "searching": searching_fx,
        },
        acts=acts,
    )
