"""Cassie: a living 1980s audio cassette.

A chunky coral cassette standing on two little feet. A cream label with neon
stripes carries the face: the two reels in the dark tape window are Cassie's
eyes (their hubs are the pupils and turn while the tape plays), the mouth sits
on the label below them and the trapezoid tape guide with its screw closes the
shell at the bottom. Cassie's moods live in the reels: they turn slowly to
listen, whirr while thinking and working, run backwards to rewind, stop dead
asleep, and when something goes wrong the tape spills out as brown spaghetti.
"""

from __future__ import annotations

import math


def design(bp):  # noqa: C901, PLR0915 - one closure per pet keeps the module self-contained
    hexc = bp.hexc
    rect = bp.rect
    line = bp.line
    ellipse = bp.ellipse
    polygon = bp.polygon
    polyline = bp.polyline
    rounded_rect = bp.rounded_rect
    shade = bp.shade
    Pose = bp.Pose

    # -- Palette ---------------------------------------------------------------

    shell_day = (hexc("#f07a6a"), hexc("#ffb09f"), hexc("#c4524f"))
    #: Asleep the shell cools down: the same cassette, dimmed.
    shell_night = (hexc("#c4645e"), hexc("#dc8a80"), hexc("#984646"))
    guide_color = hexc("#d9665c")
    label_color = hexc("#fbefd2")
    label_dark = hexc("#e6d2a6")
    neon_pink = hexc("#ff3fa4")
    neon_cyan = hexc("#22d8d0")
    neon_yellow = hexc("#ffd23f")
    window_color = hexc("#2b2236")
    window_shine = hexc("#4a3d5c")
    reel_color = hexc("#f6f3ec")
    reel_shadow = hexc("#c9c2b6")
    tape = hexc("#7a4a2e")
    tape_light = hexc("#b0703f")
    metal = hexc("#d7dbe4")
    metal_dark = hexc("#8d95a6")
    foot_color = hexc("#463a52")
    blush_color = hexc("#ff8fa3")
    pencil = hexc("#ffc93c")
    pencil_dark = hexc("#d79a1c")
    pencil_wood = hexc("#f2d2a0")
    eraser = hexc("#ff8fb0")
    ink = bp.OUTLINE
    flat_eyes = bp.EyeStyle(w=6, h=5, iris=reel_color, glint=None, lid=reel_color)

    note_palettes = (
        {"#": neon_pink},
        {"#": neon_cyan},
        {"#": neon_yellow},
    )
    note_single = ("..##", "..#.", "..#.", "###.", "##..")
    note_double = (".####", ".#..#", ".#..#", "##.##", "##.##")

    # -- Geometry (cell coordinates, before the pose offset) ------------------

    #: The reel centres: the eyes.
    reel_left = (17.0, 21.0)
    reel_right = (31.0, 21.0)
    shell = rounded_rect(5, 9, 42, 40, 3)
    label = rounded_rect(8, 12, 39, 33, 2)
    window = rounded_rect(11, 16, 36, 25, 2)
    guide = polygon([(12.5, 41.0), (16.5, 35.0), (31.5, 35.0), (35.5, 41.0)]) & rect(0, 0, 47, 40)
    screws = ((7, 11), (40, 11), (7, 38), (40, 38))

    # -- Poses -----------------------------------------------------------------

    #: Degrees the reels turn per frame in each state (0: they stand still).
    spin_step = {
        "idle": 17,
        "listening": 20,
        "thinking": 50,
        "talking": 30,
        "success": 30,
        "working": 40,
        "held": 0,
    }
    #: Searching: rewinding left, fast-forwarding right (sign of the sweep).
    sweep_dir = tuple((x > 2) - (x < -2) for x in bp.SEARCH_SWEEP)
    #: Error: the reels jam and twitch.
    jam = (0, 25, -10, 30, 0, 15)

    def pose(state: str, i: int) -> Pose:
        if state == "working":
            return Pose(state, i, dy=bp.WORK_BOB[i], eyes="down", mouth="closed")
        if state == "held":
            mouth = ("half", "open")[i % 2]
            return Pose(state, i, dx=bp.HELD_SWAY[i], dy=-2, eyes="wide", mouth=mouth, stretch=1)
        return bp.base_pose(state, i)

    def reel_angle(p: Pose) -> float:
        if p.act:
            return act_spin[p.act][p.i]
        if p.state == "error":
            return jam[p.i]
        if p.state == "searching":
            total = 0
            for k in range(p.i + 1):
                total += sweep_dir[k] * 35
            return total
        return spin_step.get(p.state, 0) * p.i

    # -- Drawing ---------------------------------------------------------------

    def hub_offset(style: str) -> tuple[int, int]:
        return {
            "look_left": (-1, 0),
            "look_right": (1, 0),
            "up_left": (-1, -1),
            "up_right": (1, -1),
            "down": (0, 1),
        }.get(style, (0, 0))

    def draw_reel(f, cx: float, cy: float, style: str, angle: float) -> None:
        """One reel eye: a white hub disc whose dark centre and three teeth
        turn by ``angle`` and shift towards where Cassie looks."""
        radius = 4.1 if style == "wide" else 3.6
        disc = ellipse(cx, cy, radius, radius)
        f.paint_map(shade(disc, reel_color, dark=reel_shadow, dark_depth=1))
        ox, oy = hub_offset(style)
        hx, hy = cx + ox, cy + oy
        f.paint(rect(int(hx) - 1, int(hy) - 1, int(hx), int(hy)), ink)
        for k in range(3):
            a = math.radians(angle + 120 * k - 90)
            tx = math.floor(round(hx + 2.3 * math.cos(a), 6))
            ty = math.floor(round(hy + 2.3 * math.sin(a), 6))
            f.paint({(tx, ty)}, ink)
        if style == "down":
            # A lowered lid: eyes on the keys.
            f.paint({p for p in disc if p[1] <= int(cy - radius) + 1}, window_color)

    def draw_eyes(f, p: Pose) -> None:
        style = p.eyes
        if style in ("open", "wide", "look_left", "look_right", "up_left", "up_right", "down"):
            angle = reel_angle(p)
            draw_reel(f, *reel_left, style, angle)
            draw_reel(f, *reel_right, style, angle)
            return
        for (cx, cy), right in ((reel_left, False), (reel_right, True)):
            bp.draw_eye(f, style, int(cx) - 3, int(cy) - 2, flat_eyes, right=right)

    def draw_feet(f, p: Pose) -> None:
        foot = rounded_rect(11, 40, 16, 43, 1)
        if p.state == "held":
            kick = 2 if p.i % 2 == 0 else 0
            feet = bp.shifted(foot, -1, kick) | bp.shifted(bp.mirrored(foot), 1, 2 - kick)
        elif p.act == "dance_bop":
            lift = act_feet[p.i]
            feet = bp.shifted(foot, 0, -max(0, -lift)) | bp.shifted(
                bp.mirrored(foot), 0, -max(0, lift)
            )
        else:
            feet = foot | bp.mirrored(foot)
        f.part(feet, {q: foot_color for q in feet})

    def side_b(p: Pose) -> bool:
        return p.act == "flip_side" and 3 <= p.i <= 4

    def draw(f, p: Pose) -> None:
        base, light, dark = shell_night if p.state == "sleeping" else shell_day
        with f.offset(p.dx, p.dy):
            draw_feet(f, p)
            f.part(shell, shade(shell, base, light=light, dark=dark, dark_depth=2))
            # The tape guide: a raised trapezoid with two capstan holes and the
            # tape running along its bottom edge.
            f.part(guide, shade(guide, guide_color, light=light, dark=dark, dark_depth=1))
            f.paint(rect(17, 37, 18, 38) | rect(29, 37, 30, 38), window_color)
            f.paint(rect(15, 40, 32, 40), tape)
            f.paint({(23, 37), (24, 37)}, metal_dark)
            f.paint({(23, 36), (24, 36)}, metal)
            for x, y in screws:
                f.paint({(x, y)}, metal)
                f.paint({(x + 1, y)}, metal_dark)
            # The label with its neon stripes (swapped on side B).
            top, bottom = (neon_cyan, neon_pink) if side_b(p) else (neon_pink, neon_cyan)
            f.part(label, shade(label, label_color, dark=label_dark, dark_depth=1))
            f.paint(rect(9, 13, 38, 13), top)
            f.paint(rect(9, 14, 38, 14), neon_yellow)
            f.paint(rect(10, 31, 37, 31), bottom)
            # The tape window: tape packed between the reels, a shine top left.
            f.part(window, window_color)
            f.paint({(12, 17), (13, 17), (12, 18)}, window_shine)
            draw_eyes(f, p)
            blush = rect(9, 27, 10, 27) | rect(37, 27, 38, 27)
            if p.state in ("success", "held") or p.i in act_blush.get(p.act, ()):
                blush |= {(11, 27), (36, 27)}
            if p.state != "sleeping":
                f.paint(blush, blush_color)
            if p.mouth == "o":
                f.paint({(23, 28), (24, 28)}, bp.MOUTH_DARK)
                f.paint({(23, 27), (24, 27), (22, 28), (25, 28), (23, 29), (24, 29)}, ink)
            else:
                bp.draw_mouth(f, p.mouth, 22, 27, 4)

    # -- Shared effect bits ------------------------------------------------------

    def note(f, x: int, y: int, k: int) -> None:
        glyph = note_double if k % 2 else note_single
        f.glyph(x, y, glyph, note_palettes[k % len(note_palettes)])

    def spaghetti(f, length: int, sway: int = 0) -> None:
        """Brown tape spilling out of the capstan holes in loose loops;
        ``length`` 0-6 is how much has come out."""
        loops = (
            [(18, 38), (16, 42), (19, 45), (22, 43)],
            [(29, 38), (31, 42), (28, 45), (25, 43)],
            [(22, 43), (21, 40), (24, 39), (25, 43)],
            [(19, 45), (13, 44), (9, 41), (5, 43), (7, 46)],
            [(28, 45), (34, 44), (38, 41), (42, 43), (40, 46)],
            [(5, 43), (2, 38), (4, 34)],
        )
        pts: set = set()
        for k in range(min(length, len(loops))):
            bent = [(x + sway * (y - 38) // 6, y) for x, y in loops[k]]
            pts |= polyline(bent)
        pts = {q for q in pts if 1 <= q[0] < 47 and 1 <= q[1] < 47}
        # A thin 1 px ribbon: tan with darker twists, readable on dark and light.
        f.paint(pts, tape_light)
        f.paint({q for q in pts if (q[0] + 2 * q[1]) % 5 == 0}, tape)

    def arrows(f, x: int, y: int, direction: int, color) -> None:
        """Two little triangles: fast-forward (1) or rewind (-1)."""
        tri = ("#..", "##.", "###", "##.", "#..")
        if direction < 0:
            tri = tuple(row[::-1] for row in tri)
        f.glyph(x, y, tri, {"#": color})
        f.glyph(x + 3, y, tri, {"#": color})

    z_small = ("####", "..#.", ".#..", "####")
    z_big = ("#####", "...#.", "..#..", ".#...", "#####")
    #: (x, y, glyph) of each z, lowest first; which show per sleeping frame.
    z_marks = ((36, 4, z_small), (41, 1, z_big), (30, 1, z_small))
    z_phases = ((0,), (0,), (0, 1), (0, 1), (1, 2), (2,))
    z_drift = (1, 0, 1, 0, 0, 0)

    # -- State effects -------------------------------------------------------------

    def fx_listening(f, p: Pose) -> None:
        with f.offset(p.dx, p.dy):
            bp.fx_arcs(f, p.i, anchors.arcs_left, anchors.arcs_right)
            if p.i >= 1:
                age = p.i - 1
                note(f, 37 + (0, 1, 0, -1, 0)[age], 6 - age, 0)

    def fx_thinking(f, p: Pose) -> None:
        with f.offset(p.dx, p.dy):
            bp.fx_dots(f, p.i, 19, 4)
            # Whirr ticks beside the window while the reels race.
            if p.i % 2 == 0:
                f.paint({(9, 19), (9, 22), (38, 19), (38, 22)}, bp.ARC)

    def fx_talking(f, p: Pose) -> None:
        with f.offset(p.dx, p.dy):
            if p.i >= 2:
                note(f, 39, 3, 0)
            if p.i == 3:
                note(f, 3, 2, 1)

    def fx_success(f, p: Pose) -> None:
        bp.fx_sparkles(f, p.i, anchors.sparkles)
        for start, x, k in ((1, 2, 0), (3, 39, 1), (5, 8, 2)):
            age = p.i - start
            if 0 <= age <= 3:
                note(f, x + (0, 1, 0, -1)[age], 8 - 2 * age, k)

    def fx_error(f, p: Pose) -> None:
        bp.fx_bang(f, *anchors.bang)
        with f.offset(p.dx, p.dy):
            spaghetti(f, 1 + p.i, sway=(p.i % 2) * 2 - 1)

    def fx_sleeping(f, p: Pose) -> None:
        """Z marks drifting up off the right corner, in the strip above the shell."""
        for k in z_phases[p.i]:
            x, y, rows = z_marks[k]
            f.glyph(x, y + (z_drift[p.i] if k == 0 else 0), rows, {"#": bp.Z_BLUE})

    def fx_working(f, p: Pose) -> None:
        bp.fx_laptop(f, p.i, *anchors.laptop)
        with f.offset(p.dx, p.dy):
            if p.i % 2 == 0:
                f.paint({(9, 19), (9, 22), (38, 19), (38, 22)}, bp.ARC)

    def fx_searching(f, p: Pose) -> None:
        bp.fx_magnifier(f, p.i, *anchors.magnifier)
        direction = sweep_dir[p.i]
        if direction:
            arrows(f, 21, 2, direction, bp.ARC if p.i % 2 else neon_cyan)

    def fx_held(f, p: Pose) -> None:
        with f.offset(p.dx, p.dy):
            bp.fx_held(f, p.i, (3, 16), (44, 16))
            sway = (-1, 0, 1, 1, 0, -1)[p.i]
            loop = polyline([(22, 41), (21 + sway, 44), (23 + 2 * sway, 46), (26 + sway, 44)])
            f.part(loop, {q: tape_light if q[1] == 44 else tape for q in loop})

    # -- Idle acts ---------------------------------------------------------------------

    #: Reel angle per act frame.
    act_spin = {
        "rewind": (0, -30, -70, -120, -170, -220, -250, -260),
        "pencil_wind": (0, -40, -80, -120, -160, -200, -240, -240),
        "music_notes": (0, 20, 40, 60, 80, 100, 120, 120),
        "tape_tangle": (0, 0, 0, 0, -50, -100, -150, -150),
        "flip_side": (0,) * 8,
        "dance_bop": (0, 30, 60, 90, 120, 150, 180, 180),
    }
    act_blush = {"music_notes": (3, 4, 5), "tape_tangle": (7,), "dance_bop": (2, 3, 4, 5, 6)}
    #: Dance: which foot lifts per frame (-1 left, 1 right).
    act_feet = (0, -2, 0, 2, 0, -2, 0, 2)
    flip_widths = (1.0, 0.6, 0.2, 0.6, 1.0, 0.6, 0.2, 1.0)

    def act_pose(name: str, **columns):
        def make(i: int) -> Pose:
            return Pose("idle", i, act=name, **{k: v[i] for k, v in columns.items()})

        return make

    def fx_rewind(f, p: Pose) -> None:
        i = p.i
        if 1 <= i <= 6:
            arrows(f, 19, 2, -1, neon_cyan if i % 2 else bp.ARC)
            # Speed lines streaming off to the right.
            for y, length in ((15, 3), (21, 4), (27, 3)):
                x = 43 - (i % 2)
                f.paint(line(x, y, min(47, x + length - 1), y), bp.ARC_FADE)
        if i == 7:
            bp.fx_sparkles(f, 0, ((40, 8, 0),))

    #: Pencil wind: the pencil's angle per frame (degrees, 0 = east; None = gone).
    pencil_angles = (None, -95, -125, -155, -125, -95, -125, None)

    def fx_pencil(f, p: Pose) -> None:
        """A pencil pokes into the left reel and cranks the tape back by hand."""
        a = pencil_angles[p.i]
        if a is None:
            return
        cx, cy = reel_left
        ca, sa = math.cos(math.radians(a)), math.sin(math.radians(a))

        def at(r: float) -> tuple[int, int]:
            return round(cx - 0.5 + r * ca), round(cy - 0.5 + r * sa)

        stroke = polyline([at(4), at(16)])
        shade_side = bp.shifted(stroke, 1, 0) - stroke
        body = stroke | shade_side
        colors = {q: pencil for q in stroke} | {q: pencil_dark for q in shade_side}
        f.part(body, colors)
        f.paint(polyline([at(1), at(3)]), pencil_wood)
        f.paint({at(1)}, ink)
        end = at(17)
        cap = rect(end[0], end[1], end[0] + 1, end[1] + 1)
        f.part(cap, eraser)
        if p.i in (3, 5):
            f.paint(line(4, 12, 2, 10) | line(4, 30, 2, 32), bp.ARC)

    def fx_music(f, p: Pose) -> None:
        for start, x, k in ((1, 8, 0), (2, 33, 1), (4, 19, 2), (5, 37, 0)):
            age = p.i - start
            if 0 <= age <= 3:
                note(f, x + (0, 1, 0, -1)[age], 7 - 2 * age, k)

    def fx_tangle(f, p: Pose) -> None:
        length = (0, 1, 2, 4, 3, 2, 1, 0)[p.i]
        with f.offset(p.dx, p.dy):
            spaghetti(f, length, sway=(0, 0, 1, -1, 1, 0, 0, 0)[p.i])
        if p.i == 3:
            bp.fx_bang(f, 41, 1)
        if p.i == 7:
            bp.fx_sparkles(f, 0, ((41, 8, 0),))

    def fx_flip(f, p: Pose) -> None:
        if p.i in (2, 6):
            f.paint(line(4, 22, 1, 22) | line(43, 22, 46, 22), bp.ARC_FADE)
        if p.i == 4:
            bp.fx_sparkles(f, 0, ((42, 8, 0),))

    def fx_dance(f, p: Pose) -> None:
        for start, x, k in ((1, 3, 1), (3, 38, 0), (5, 6, 2)):
            age = p.i - start
            if 0 <= age <= 2:
                note(f, x, 6 - 2 * age, k)
        if p.i in (2, 6):
            f.paint(line(2, 30, 2, 33) | line(45, 30, 45, 33), bp.ARC_FADE)

    acts = (
        bp.IdleAct(
            "rewind",
            8,
            10,
            act_pose(
                "rewind",
                dx=(0, -1, -1, -1, -1, -1, -1, 0),
                eyes=(
                    "open",
                    "look_left",
                    "look_left",
                    "look_left",
                    "look_left",
                    "look_left",
                    "look_left",
                    "happy",
                ),
                mouth=("rest", "o", "o", "o", "o", "o", "closed", "smile"),
            ),
            fx_rewind,
        ),
        bp.IdleAct(
            "pencil_wind",
            8,
            8,
            act_pose(
                "pencil_wind",
                eyes=(
                    "open",
                    "look_left",
                    "look_left",
                    "look_left",
                    "look_left",
                    "look_left",
                    "happy",
                    "open",
                ),
                mouth=("rest", "half", "closed", "closed", "closed", "closed", "smile", "rest"),
            ),
            fx_pencil,
        ),
        bp.IdleAct(
            "music_notes",
            8,
            8,
            act_pose(
                "music_notes",
                dx=(0, -1, 0, 1, 0, -1, 0, 0),
                stretch=(0, 1, 0, 1, 0, 1, 0, 0),
                eyes=("open", "happy", "happy", "happy", "happy", "happy", "happy", "open"),
                mouth=("rest", "o", "smile", "o", "smile", "o", "smile", "rest"),
            ),
            fx_music,
        ),
        bp.IdleAct(
            "tape_tangle",
            8,
            8,
            act_pose(
                "tape_tangle",
                dy=(0, 0, 0, -2, 0, 0, 0, 0),
                eyes=("open", "down", "down", "wide", "look_left", "look_right", "down", "happy"),
                mouth=("rest", "closed", "half", "wide", "closed", "closed", "closed", "smile"),
            ),
            fx_tangle,
        ),
        bp.IdleAct(
            "flip_side",
            8,
            10,
            act_pose(
                "flip_side",
                dy=(0, -2, -4, -5, -4, -2, 0, 0),
                eyes=("open", "wide", "closed", "happy", "happy", "closed", "wide", "open"),
                mouth=("rest", "half", "closed", "smile", "smile", "closed", "half", "rest"),
            ),
            fx_flip,
        ),
        bp.IdleAct(
            "dance_bop",
            8,
            8,
            act_pose(
                "dance_bop",
                dx=(0, -2, 0, 2, 0, -2, 0, 0),
                dy=(0, -1, 0, -1, 0, -1, 0, 0),
                stretch=(0, 0, -1, 0, -1, 0, -1, 0),
                eyes=("open", "happy", "happy", "happy", "happy", "happy", "happy", "open"),
                mouth=("rest", "smile", "open", "smile", "open", "smile", "smile", "rest"),
            ),
            fx_dance,
        ),
    )

    def post(img, p: Pose):
        if p.act == "flip_side":
            return bp.squash_x(img, flip_widths[p.i])
        return img

    anchors = bp.Anchors(
        arcs_left=(9, 5),
        arcs_right=(38, 5),
        dots=(19, 4),
        zzz=(38, 6),
        bang=(43, 1),
        sweat=(36, 6),
        sparkles=((4, 8, 1), (43, 14, 2), (3, 34, 3), (44, 32, 3)),
        laptop=(17, 35),
        magnifier=(bp.CX, 21),
    )

    return bp.PetDesign(
        id="cassie",
        name="Cassie",
        description=(
            "A groovy 80s cassette whose reels spin while it thinks and hum along to music."
        ),
        draw=draw,
        pose=pose,
        anchors=anchors,
        fx={
            "listening": fx_listening,
            "thinking": fx_thinking,
            "talking": fx_talking,
            "success": fx_success,
            "error": fx_error,
            "sleeping": fx_sleeping,
            "working": fx_working,
            "searching": fx_searching,
            "held": fx_held,
        },
        acts=acts,
        post=post,
        waist=39,
    )
