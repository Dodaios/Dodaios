"""The Dodaios Bar's look: a small black pill with white marks.

This module owns everything the bar draws and where its controls are. It is
pure (Pillow only, no toolkit) so the Tk surface (Windows/Linux), the Qt
surface (macOS) and the tests all use the same layout and the same pixels.

The bar has four shapes, chosen by :func:`layout`:

- ``rest``   -- idle and nothing to say: a slim pill that stays out of the way.
- ``status`` -- idle, but a state is switched on that the user must be able to
  see without hovering (microphone muted, voice muted, Prompt Mode): the pill
  grows just enough to show those marks.
- ``live``   -- a voice conversation or a dictation runs: level bars move with
  whoever is speaking, the user into the microphone or Dodaios out of the
  speakers. Thinking and connecting have their own quiet dot animations.
- ``open``   -- the pointer is on the bar: the controls slide out around the
  centre (microphone, centre, speaker, and hang up / new chat).

Sizes are design points at ``scale == 1``; the surfaces pass their effective
scale (monitor calibration times the user's "Bar size").
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from PIL import Image, ImageDraw

from dodaios.ui.dodaiosbar.modes import (
    ACTIVE_VOICE_MODES,
    CONNECT_MODES,
    DICTATION_MODES,
    NOTICE_MODES,
)

# --------------------------------------------------------------------------- #
# Geometry (design points at scale 1)                                         #
# --------------------------------------------------------------------------- #
WINDOW_W = 236.0
WINDOW_H = 50.0
BOTTOM_PAD = 5.0

REST_W, REST_H = 42.0, 9.0
STATUS_H = 22.0
LIVE_W, LIVE_H = 86.0, 26.0
OPEN_H = 34.0
EDGE_PAD = 6.0
MARK_W = 18.0
SLOT_W = 30.0
CENTER_W = 66.0
HOVER_KEEP_PAD = 5.0

BAR_COUNT = 11
BAR_WIDTH = 2.4
BAR_GAP = 3.1

# --------------------------------------------------------------------------- #
# Colours: black and white only, opaque and pre-blended                       #
# --------------------------------------------------------------------------- #
FILL = (12, 12, 12)
RIM = (66, 66, 66)
RIM_ACTIVE = (235, 235, 235)
WHITE = (244, 244, 244)
GREY = (150, 150, 150)
DIM = (92, 92, 92)
HOVER_BG = (46, 46, 46)
ON_BG = (30, 30, 30)

#: Shape names, for the surfaces and tests.
SHAPES = ("rest", "status", "live", "open")

#: Control names a hit test can return.
CONTROLS = ("prompt", "mic", "center", "speaker", "close", "compose")


@dataclass(frozen=True)
class BarState:
    """Everything that decides the bar's shape and what it shows."""

    mode: str = "idle"
    hovered: bool = False
    muted: bool = False
    speaker_muted: bool = False
    prompt_mode: bool = False
    prompt_mode_paused: bool = False
    drop_state: str = "none"
    #: The control under the pointer (drawn highlighted; no effect on layout).
    hover_control: str | None = None


@dataclass(frozen=True)
class Layout:
    shape: str
    width: float
    height: float
    #: ``(name, x0, x1)`` in pill-local design points, left to right.
    slots: tuple[tuple[str, float, float], ...] = field(default_factory=tuple)
    #: Status marks drawn in ``status`` and ``live`` (never clickable).
    marks: tuple[str, ...] = field(default_factory=tuple)


def is_live(mode: str) -> bool:
    return mode in ACTIVE_VOICE_MODES or mode in DICTATION_MODES or mode in NOTICE_MODES


def _status_marks(state: BarState) -> tuple[str, ...]:
    marks: list[str] = []
    if state.muted:
        marks.append("mic_off")
    if state.speaker_muted:
        marks.append("speaker_off")
    if state.prompt_mode and state.mode == "idle":
        marks.append("prompt_paused" if state.prompt_mode_paused else "prompt")
    return tuple(marks)


def _open_slots(state: BarState) -> list[tuple[str, float]]:
    """The controls of the open bar, left to right, with their widths."""
    if state.mode in DICTATION_MODES:
        # A dictation is not a conversation: the only control is "stop".
        return [("center", CENTER_W), ("close", SLOT_W)]
    if state.mode in ACTIVE_VOICE_MODES:
        return [("mic", SLOT_W), ("center", CENTER_W), ("speaker", SLOT_W), ("close", SLOT_W)]
    slots: list[tuple[str, float]] = []
    if state.prompt_mode:
        slots.append(("prompt", SLOT_W))
    slots += [("mic", SLOT_W), ("center", CENTER_W), ("speaker", SLOT_W), ("compose", SLOT_W)]
    return slots


def layout(state: BarState) -> Layout:
    """The bar's target shape for ``state`` (design points, unscaled)."""
    opens = state.hovered and state.mode not in NOTICE_MODES
    if opens:
        widths = _open_slots(state)
        total = EDGE_PAD * 2 + sum(w for _, w in widths)
        x = EDGE_PAD
        slots = []
        for name, w in widths:
            slots.append((name, x, x + w))
            x += w
        return Layout("open", total, OPEN_H, tuple(slots))
    marks = _status_marks(state)
    if is_live(state.mode) or state.drop_state != "none":
        width = LIVE_W + MARK_W * len(marks)
        return Layout("live", width, LIVE_H, (("center", EDGE_PAD, width - EDGE_PAD),), marks)
    if marks:
        width = EDGE_PAD * 2 + MARK_W * len(marks) + 4.0
        return Layout("status", width, STATUS_H, (("center", 0.0, width),), marks)
    return Layout("rest", REST_W, REST_H, (("center", 0.0, REST_W),))


def pill_rect(lay: Layout, scale: float) -> tuple[float, float, float, float]:
    """The pill's rectangle in window pixels: bottom-centred in the window."""
    win_w, win_h = window_size(scale)
    w, h = lay.width * scale, lay.height * scale
    x0 = (win_w - w) / 2.0
    y1 = win_h - BOTTOM_PAD * scale
    return (x0, y1 - h, x0 + w, y1)


def window_size(scale: float) -> tuple[int, int]:
    return (max(1, round(WINDOW_W * scale)), max(1, round(WINDOW_H * scale)))


def hit_test(x: float, y: float, state: BarState, scale: float) -> str | None:
    """The control under window point ``(x, y)``, or ``None``.

    Uses the target layout (not the eased frame), so a click resolves against
    the controls the user is aiming at even while the pill is still growing.
    """
    lay = layout(state)
    x0, y0, x1, y1 = pill_rect(lay, scale)
    if not (x0 <= x <= x1 and y0 <= y <= y1):
        return None
    local = (x - x0) / scale
    for name, sx0, sx1 in lay.slots:
        if sx0 <= local <= sx1:
            return name
    # The rounded ends of the open pill belong to the nearest control.
    if lay.slots:
        return lay.slots[0][0] if local < lay.slots[0][1] else lay.slots[-1][0]
    return None


def control_center(name: str, state: BarState, scale: float) -> tuple[float, float] | None:
    """Window point at the middle of control ``name`` in ``state``'s layout."""
    lay = layout(state)
    x0, y0, _x1, y1 = pill_rect(lay, scale)
    for slot, sx0, sx1 in lay.slots:
        if slot == name:
            return (x0 + (sx0 + sx1) / 2.0 * scale, (y0 + y1) / 2.0)
    return None


def in_hover_footprint(x: float, y: float, state: BarState, scale: float) -> bool:
    """True while the pointer is on the (open) pill or just around its edge."""
    x0, y0, x1, y1 = pill_rect(layout(state), scale)
    pad = HOVER_KEEP_PAD * scale
    return x0 - pad <= x <= x1 + pad and y0 - pad <= y <= y1 + pad


# --------------------------------------------------------------------------- #
# Motion helpers (pure)                                                       #
# --------------------------------------------------------------------------- #
def bar_heights(level: float, t: float, *, count: int = BAR_COUNT) -> list[float]:
    """Relative bar heights in ``[0, 1]`` for a level in ``[0, 1]``.

    A level of zero gives all zeros: when nobody speaks, the bars rest as dots
    and do not move. Louder speech raises the middle bars most, and each bar
    sways on its own slow rhythm so the row reads as a voice, not a meter.
    """
    lv = max(0.0, min(1.0, float(level)))
    if lv <= 0.0:
        return [0.0] * count
    centre = (count - 1) / 2.0
    out = []
    for i in range(count):
        envelope = 0.32 + 0.68 * math.exp(-(((i - centre) / (count * 0.30)) ** 2))
        sway = 0.62 + 0.38 * math.sin(t * (6.1 + 0.9 * (i % 3)) + i * 0.85)
        out.append(max(0.0, min(1.0, lv * envelope * sway * 1.35)))
    return out


def sweep_glow(t: float, *, count: int = BAR_COUNT, period: float = 1.5) -> list[float]:
    """Brightness ``[0, 1]`` per dot for thinking: a soft light that walks
    left and right across the row."""
    phase = (t % period) / period
    pos = (1.0 - abs(1.0 - 2.0 * phase)) * (count - 1)
    return [math.exp(-(((i - pos) / 1.5) ** 2)) for i in range(count)]


def connect_bumps(t: float, *, count: int = BAR_COUNT, period: float = 1.1) -> list[float]:
    """Relative heights ``[0, 1]`` for connecting: a small wave runs left to
    right while the voice connection is being set up."""
    pos = ((t % period) / period) * (count + 3) - 1.5
    return [0.55 * math.exp(-(((i - pos) / 1.1) ** 2)) for i in range(count)]


def connected_swell(progress: float, *, count: int = BAR_COUNT) -> list[float]:
    """Relative heights ``[0, 1]`` for the moment a call connects: one swell
    runs from the middle out to both ends and fades (``progress`` 0 to 1)."""
    p = max(0.0, min(1.0, float(progress)))
    centre = (count - 1) / 2.0
    front = p * (centre + 1.0)
    return [
        0.6 * (1.0 - 0.6 * p) * math.exp(-(((abs(i - centre) - front) / 1.2) ** 2))
        for i in range(count)
    ]


def blink(t: float) -> float:
    return 0.55 + 0.45 * (0.5 + 0.5 * math.sin(t * 3.4))


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], f: float) -> tuple[int, int, int]:
    f = max(0.0, min(1.0, f))
    return tuple(round(a[i] + (b[i] - a[i]) * f) for i in range(3))  # type: ignore[return-value]


# --------------------------------------------------------------------------- #
# Painter                                                                     #
# --------------------------------------------------------------------------- #
class BarPainter:
    """Draws frames. Keeps a little state for smooth motion between frames:
    the pill's eased size and the smoothed audio level."""

    EASE_TAU_S = 0.075
    LEVEL_ATTACK_S = 0.035
    LEVEL_RELEASE_S = 0.14

    def __init__(self) -> None:
        self._cur: tuple[float, float] | None = None
        self._target: tuple[float, float] | None = None
        self._last_t: float | None = None
        self._level = 0.0

    def reset(self) -> None:
        self._cur = None
        self._last_t = None
        self._level = 0.0

    # -- state easing -------------------------------------------------------
    def _advance(self, t: float, target: tuple[float, float], level: float) -> float:
        """Ease the pill size and the level towards their targets; return the
        smoothed level. The first frame jumps straight to the target."""
        if self._cur is None or self._last_t is None:
            self._cur, self._level, self._last_t = target, level, t
            return level
        dt = max(0.0, min(0.25, t - self._last_t))
        self._last_t = t
        if dt > 0.0:
            k = 1.0 - math.exp(-dt / self.EASE_TAU_S)
            w = self._cur[0] + (target[0] - self._cur[0]) * k
            h = self._cur[1] + (target[1] - self._cur[1]) * k
            if abs(w - target[0]) < 0.25 and abs(h - target[1]) < 0.25:
                w, h = target
            self._cur = (w, h)
            tau = self.LEVEL_ATTACK_S if level > self._level else self.LEVEL_RELEASE_S
            self._level += (level - self._level) * (1.0 - math.exp(-dt / tau))
        return self._level

    @property
    def easing(self) -> bool:
        """True while the pill is still growing or shrinking."""
        return self._cur is not None and self._cur != self._target

    # -- frame --------------------------------------------------------------
    def paint(
        self,
        state: BarState,
        t: float,
        level: float,
        *,
        look: str,
        scale: float,
        pixel_ratio: float = 1.0,
        flourish: float | None = None,
    ) -> Image.Image:
        """One RGBA frame of the whole window (transparent outside the pill).

        ``look`` is the rendered look the surface derived from the mode and the
        live audio (``idle`` / ``speak`` / ``think`` / ``connect`` / ``notice``).
        ``flourish`` (0 to 1) plays the "connected" swell instead of resting dots.
        """
        self._flourish = flourish
        target = layout(state)
        self._target = (target.width, target.height)
        smooth = self._advance(t, (target.width, target.height), level)
        cur_w, cur_h = self._cur or (target.width, target.height)

        px = scale * pixel_ratio
        ss = 4 if px < 1.5 else 3 if px < 2.5 else 2
        u = px * ss  # supersampled pixels per design point
        win_w, win_h = window_size(scale)
        out_w, out_h = max(1, round(win_w * pixel_ratio)), max(1, round(win_h * pixel_ratio))
        big = Image.new("RGBA", (out_w * ss, out_h * ss), (0, 0, 0, 0))
        draw = ImageDraw.Draw(big)

        cx = out_w * ss / 2.0
        bottom = out_h * ss - BOTTOM_PAD * u
        pw, ph = cur_w * u, cur_h * u
        x0, y0, x1, y1 = cx - pw / 2.0, bottom - ph, cx + pw / 2.0, bottom
        cy = (y0 + y1) / 2.0

        armed = state.drop_state == "armed"
        rim = RIM_ACTIVE if armed else RIM
        rim_w = max(1.0, (1.5 if armed else 1.0) * u)
        draw.rounded_rectangle((x0, y0, x1, y1), radius=ph / 2.0, fill=rim + (255,))
        draw.rounded_rectangle(
            (x0 + rim_w, y0 + rim_w, x1 - rim_w, y1 - rim_w),
            radius=max(0.0, ph / 2.0 - rim_w),
            fill=FILL + (255,),
        )

        # The target layout tells what to show; the eased pill tells how much
        # of it is revealed yet. Content is laid out around the window centre
        # so it stays put while the pill grows or shrinks.
        tx0 = cx - target.width * u / 2.0
        reveal = 1.0 - min(1.0, abs(target.width - cur_w) / 40.0)
        hovered_control = state.hover_control

        if target.shape == "rest":
            return self._finish(big, out_w, out_h)

        if target.shape in ("status", "live"):
            mx = tx0 + EDGE_PAD * u + 2.0 * u
            for mark in target.marks:
                self._mark(draw, mark, mx + MARK_W * u / 2.0, cy, u, reveal, t)
                mx += MARK_W * u
            if target.shape == "live":
                left = tx0 + (EDGE_PAD + MARK_W * len(target.marks)) * u
                right = tx0 + (target.width - EDGE_PAD) * u
                self._center(draw, state, look, left, right, cy, u, smooth, t, reveal=1.0)
            return self._finish(big, out_w, out_h)

        # open
        for name, sx0, sx1 in target.slots:
            a, b = tx0 + sx0 * u, tx0 + sx1 * u
            if a < x0 + rim_w - 0.5 * u or b > x1 - rim_w + 0.5 * u:
                continue  # not revealed yet
            hot = hovered_control == name
            if name == "center":
                if hot and not is_live(state.mode):
                    pad = 3.0 * u
                    draw.rounded_rectangle(
                        (a + pad, cy - (OPEN_H / 2 - 5) * u, b - pad, cy + (OPEN_H / 2 - 5) * u),
                        radius=(OPEN_H / 2 - 5) * u,
                        fill=HOVER_BG + (255,),
                    )
                self._center(
                    draw, state, look, a + 6 * u, b - 6 * u, cy, u, smooth, t,
                    reveal=reveal, hot=hot,
                )
                continue
            mid = (a + b) / 2.0
            on = (name == "mic" and state.muted) or (name == "speaker" and state.speaker_muted)
            r = 12.0 * u
            if hot or on:
                draw.ellipse(
                    (mid - r, cy - r, mid + r, cy + r),
                    fill=(HOVER_BG if hot else ON_BG) + (255,),
                )
            colour = _mix(FILL, WHITE if hot else (215, 215, 215), reveal)
            self._icon(draw, name, mid, cy, u, colour, state)
        return self._finish(big, out_w, out_h)

    @staticmethod
    def _finish(big: Image.Image, out_w: int, out_h: int) -> Image.Image:
        return big.resize((out_w, out_h), Image.Resampling.LANCZOS)

    # -- centre: bars, sweep, loading, notice, drop marks ----------------------
    def _center(
        self,
        draw: ImageDraw.ImageDraw,
        state: BarState,
        look: str,
        left: float,
        right: float,
        cy: float,
        u: float,
        level: float,
        t: float,
        *,
        reveal: float,
        hot: bool = False,
    ) -> None:
        cx = (left + right) / 2.0
        if state.drop_state in ("ok", "rejected") or look in NOTICE_MODES:
            r = 4.5 * u
            if state.drop_state == "ok":
                draw.line(
                    [(cx - r, cy), (cx - r * 0.25, cy + r * 0.7), (cx + r, cy - r * 0.7)],
                    fill=WHITE, width=round(1.8 * u), joint="curve",
                )
            else:
                c = _mix(FILL, WHITE, blink(t) if look in NOTICE_MODES else 1.0)
                w = round(1.8 * u)
                draw.line((cx - r, cy - r, cx + r, cy + r), fill=c, width=w)
                draw.line((cx - r, cy + r, cx + r, cy - r), fill=c, width=w)
            return
        if state.drop_state == "armed":
            r = 5.0 * u
            w = round(1.8 * u)
            draw.line((cx - r, cy, cx + r, cy), fill=WHITE, width=w)
            draw.line((cx, cy - r, cx, cy + r), fill=WHITE, width=w)
            return

        n = BAR_COUNT
        bw, gap = BAR_WIDTH * u, BAR_GAP * u
        row = n * bw + (n - 1) * gap
        room = right - left
        if row > room > 0:
            shrink = room / row
            bw, gap, row = bw * shrink, gap * shrink, room
        start = cx - row / 2.0
        max_h = (min(LIVE_H, OPEN_H) - 10.0) * u
        if look == "speak":
            heights = bar_heights(level, t, count=n)
            colours = [WHITE] * n
        elif look == "think":
            heights = [0.0] * n
            colours = [_mix(DIM, WHITE, g) for g in sweep_glow(t, count=n)]
        elif look == "connect":
            heights = connect_bumps(t, count=n)
            colours = [_mix(GREY, WHITE, h / 0.55) for h in heights]
        elif look == "connected":
            heights = connected_swell(getattr(self, "_flourish", None) or 0.0, count=n)
            colours = [WHITE] * n
        else:  # idle: the quiet row of dots, brighter under the pointer
            heights = [0.0] * n
            colours = [WHITE if hot else GREY] * n
        for i in range(n):
            h = bw + (max_h - bw) * heights[i]
            bx = start + i * (bw + gap)
            colour = _mix(FILL, colours[i], reveal)
            draw.rounded_rectangle(
                (bx, cy - h / 2.0, bx + bw, cy + h / 2.0), radius=bw / 2.0, fill=colour + (255,)
            )

    # -- status marks ----------------------------------------------------------
    def _mark(self, draw, mark: str, cx: float, cy: float, u: float, reveal: float, t: float):
        colour = _mix(FILL, (225, 225, 225), reveal)
        k = 0.82
        if mark == "mic_off":
            _mic(draw, cx, cy, u * k, colour, slashed=True)
        elif mark == "speaker_off":
            _speaker(draw, cx, cy, u * k, colour, slashed=True)
        elif mark in ("prompt", "prompt_paused"):
            _sparkle(draw, cx, cy, u * k, colour, slashed=mark == "prompt_paused")

    # -- control icons ---------------------------------------------------------
    @staticmethod
    def _icon(draw, name: str, cx: float, cy: float, u: float, colour, state: BarState) -> None:
        if name == "mic":
            _mic(draw, cx, cy, u, colour, slashed=state.muted)
        elif name == "speaker":
            _speaker(draw, cx, cy, u, colour, slashed=state.speaker_muted)
        elif name == "close":
            r = 4.2 * u
            w = max(1, round(1.6 * u))
            draw.line((cx - r, cy - r, cx + r, cy + r), fill=colour, width=w)
            draw.line((cx - r, cy + r, cx + r, cy - r), fill=colour, width=w)
        elif name == "compose":
            _pencil(draw, cx, cy, u, colour)
        elif name == "prompt":
            _sparkle(draw, cx, cy, u, colour, slashed=state.prompt_mode_paused)


# --------------------------------------------------------------------------- #
# Glyphs (drawn from lines, own shapes)                                       #
# --------------------------------------------------------------------------- #
def _slash(draw, cx: float, cy: float, r: float, colour, w: int) -> None:
    # A dark cut first so the slash reads on top of the glyph.
    draw.line((cx - r, cy - r, cx + r, cy + r), fill=FILL, width=w * 3)
    draw.line((cx - r, cy - r, cx + r, cy + r), fill=colour, width=w)


def _mic(draw, cx: float, cy: float, u: float, colour, *, slashed: bool) -> None:
    w = max(1, round(1.5 * u))
    cap_w, cap_h = 2.6 * u, 4.6 * u
    top = cy - 6.2 * u
    draw.rounded_rectangle(
        (cx - cap_w, top, cx + cap_w, top + 2 * cap_h), radius=cap_w, outline=colour, width=w
    )
    arc_r = 5.0 * u
    arc_cy = top + 2 * cap_h - 3.6 * u
    draw.arc(
        (cx - arc_r, arc_cy - arc_r, cx + arc_r, arc_cy + arc_r), 15, 165, fill=colour, width=w
    )
    draw.line((cx, arc_cy + arc_r, cx, cy + 6.4 * u), fill=colour, width=w)
    if slashed:
        _slash(draw, cx, cy, 6.6 * u, colour, w)


def _speaker(draw, cx: float, cy: float, u: float, colour, *, slashed: bool) -> None:
    w = max(1, round(1.5 * u))
    left = cx - 6.0 * u
    body = [
        (left, cy - 2.4 * u),
        (left + 3.2 * u, cy - 2.4 * u),
        (left + 7.0 * u, cy - 5.6 * u),
        (left + 7.0 * u, cy + 5.6 * u),
        (left + 3.2 * u, cy + 2.4 * u),
        (left, cy + 2.4 * u),
    ]
    draw.polygon(body, fill=colour)
    if slashed:
        _slash(draw, cx, cy, 6.6 * u, colour, w)
        return
    for r in (3.2, 6.0):
        rr = r * u
        ox = left + 7.6 * u
        draw.arc((ox - rr, cy - rr, ox + rr, cy + rr), -50, 50, fill=colour, width=w)


def _pencil(draw, cx: float, cy: float, u: float, colour) -> None:
    w = max(1, round(1.6 * u))
    r = 5.2 * u
    draw.line((cx - r, cy + r, cx + r * 0.75, cy - r * 0.75), fill=colour, width=w * 2)
    draw.polygon(
        [(cx - r - 0.6 * u, cy + r + 0.6 * u), (cx - r + 2.6 * u, cy + r), (cx - r, cy + r - 2.6 * u)],
        fill=colour,
    )
    draw.line((cx - 1.0 * u, cy + r + 0.4 * u, cx + r, cy + r + 0.4 * u), fill=colour, width=w)


def _sparkle(draw, cx: float, cy: float, u: float, colour, *, slashed: bool) -> None:
    r, q = 6.0 * u, 1.5 * u
    draw.polygon(
        [
            (cx, cy - r), (cx + q, cy - q), (cx + r, cy), (cx + q, cy + q),
            (cx, cy + r), (cx - q, cy + q), (cx - r, cy), (cx - q, cy - q),
        ],
        fill=colour,
    )
    if slashed:
        _slash(draw, cx, cy, 6.6 * u, colour, max(1, round(1.5 * u)))


def to_keyed_rgb(frame: Image.Image, key: tuple[int, int, int]) -> Image.Image:
    """RGBA → RGB on a colour key, for surfaces with binary transparency.

    Pixels at least half covered keep their colour (the pill is dark, so its
    soft edge stays dark); the rest become the key colour, which the window
    system cuts out. No key-coloured fringe can appear around the pill.
    """
    rgba = frame.convert("RGBA")
    alpha = rgba.getchannel("A").point(lambda a: 255 if a >= 128 else 0)
    base = Image.new("RGB", rgba.size, key)
    base.paste(rgba.convert("RGB"), mask=alpha)
    return base
