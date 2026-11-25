"""How the installer looks in a terminal: one design for both stages.

The shell bootstrap (``install/install.sh``, ``install/install.ps1``) draws the
hero and phases 1-3 before Python exists; ``install/installer.py`` draws phases
4-6 and the finale with this module. The three surfaces share one look: gold
phase pills, a check per finished step with its time on the right, a red rail
under a failed step, and a framed card at the end.

All three decide what the terminal can show by the same rules, in this order:

* **Colour** is off with ``NO_COLOR``, with ``TERM=dumb``, and when the output
  is not a terminal (a pipe, a file, CI); ``FORCE_COLOR`` turns it back on for
  logs that render colour. The tier is truecolor with ``COLORTERM=truecolor``
  or ``24bit``, in Windows Terminal, in a known modern terminal program and in
  a Windows 10+ console; 256 colours when ``TERM`` says so; 16 otherwise.
* **Glyphs** are plain ASCII with ``JARVIS_INSTALL_ASCII``, on ``TERM=linux``,
  ``dumb`` or a ``vt*`` terminal, and with a locale that is not UTF-8. A
  classic Windows console gets the set its default font draws (Consolas has
  no check mark and no Braille); everything else gets the full set.
* **Motion** (spinners) needs a terminal and never runs in CI.
* **Width** comes from ``COLUMNS``, else the terminal, else 80 columns.

Nothing here waits for effect: a spinner redraws while a real command runs
and stops the moment it ends.
"""

from __future__ import annotations

import os
import shutil
import sys
import threading
import time
import unicodedata
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TextIO

RGB = tuple[int, int, int]

# Brand palette (docs/BRAND.md): the wordmark's signal gold, a deep gold for
# frames, and the status colours. Plain text keeps the terminal's own
# foreground, so a light theme reads it as well as a dark one.
GOLD: RGB = (255, 214, 10)
GOLD_DEEP: RGB = (184, 134, 11)
INK: RGB = (10, 10, 10)
OK: RGB = (34, 195, 94)
WARN: RGB = (245, 158, 11)
BAD: RGB = (223, 58, 58)
MUTED: RGB = (138, 138, 138)

# The nearest colours where only 256 or 16 exist.
_XTERM_256: dict[RGB, int] = {
    GOLD: 220, GOLD_DEEP: 136, INK: 232, OK: 35, WARN: 214, BAD: 167, MUTED: 245,
}
_ANSI_16: dict[RGB, int] = {GOLD: 3, GOLD_DEEP: 3, INK: 0, OK: 2, WARN: 3, BAD: 1, MUTED: 8}

#: The line a launch always leaves behind: a spawned app can fail to surface.
RELAUNCH_LABEL = "If it doesn't open, run:"

#: Widest layout: on a wide terminal the right-hand times stay near the text.
MAX_LAYOUT = 88
STEP_INDENT = 5
TEXT_INDENT = 8
PHASES = 6


@dataclass(frozen=True)
class Glyphs:
    ok: str
    fail: str
    skip: str
    warn: str
    rail: str
    point: str
    spin: str
    h: str
    v: str
    corners: tuple[str, str, str, str]  # top-left, top-right, bottom-left, bottom-right
    ellipsis: str


FULL = Glyphs("✓", "×", "·", "!", "┃", "▸", "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏", "─", "│", ("┌", "┐", "└", "┘"), "…")
#: What a classic Windows console's default font (Consolas) can draw.
BASIC = Glyphs("√", "×", "·", "!", "┃", "▸", "|/-\\", "─", "│", ("┌", "┐", "└", "┘"), "…")
ASCII = Glyphs("+", "x", "-", "!", "|", ">", "|/-\\", "-", "|", ("+", "+", "+", "+"), "...")

# Typography the messages use, spelled out for an ASCII-only terminal.
_ASCII_TEXT = str.maketrans({
    "—": "-", "–": "-", "…": "...", "→": "->", "←": "<-", "›": ">", "·": "-",
    "‘": "'", "’": "'", "“": '"', "”": '"', "✓": "+", "✗": "x", "×": "x",
    "•": "*", "▸": ">", "━": "-", "─": "-", "│": "|", "┃": "|",
})

_MODERN_PROGRAMS = (
    "iterm.app", "wezterm", "vscode", "ghostty", "hyper", "tabby", "warpterminal",
)
_ASCII_TERMS = ("linux", "dumb", "ansi", "cons25")


def _truthy(value: str | None) -> bool:
    return bool(value) and str(value).strip().lower() not in {"0", "false", "no", "off"}


@dataclass(frozen=True)
class Caps:
    """What the terminal in front of the installer can show."""

    color: str  # "none" | "16" | "256" | "truecolor"
    glyphs: str  # "ascii" | "basic" | "full"
    motion: bool
    width: int


def _is_tty(stream: TextIO) -> bool:
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError, OSError):
        # A closed or replaced stream (pytest's capture) is not a terminal.
        return False


def _windows_vt(stream: TextIO) -> bool:
    """Turn on escape-sequence output in a Windows console; False if it cannot be."""
    try:
        import ctypes  # noqa: PLC0415 - Windows only
        import msvcrt  # noqa: PLC0415 - Windows only

        kernel32 = ctypes.windll.kernel32
        handle = msvcrt.get_osfhandle(stream.fileno())
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        enable_vt = 0x0004
        if mode.value & enable_vt:
            return True
        return bool(kernel32.SetConsoleMode(handle, mode.value | enable_vt))
    except (AttributeError, ImportError, OSError, ValueError):
        # No console behind the stream, or not Windows: no escape sequences.
        return False


def _color_tier(env: Mapping[str, str], platform: str) -> str:
    colorterm = env.get("COLORTERM", "").lower()
    term = env.get("TERM", "").lower()
    program = env.get("TERM_PROGRAM", "").lower()
    if colorterm in {"truecolor", "24bit"} or "direct" in term:
        return "truecolor"
    if env.get("WT_SESSION") or env.get("WSL_DISTRO_NAME") or program in _MODERN_PROGRAMS:
        # Windows Terminal forwards WT_SESSION into WSL, and every Windows
        # console behind WSL draws 24-bit colour without saying so in COLORTERM.
        return "truecolor"
    if platform == "win32" and not term:
        # The Windows 10+ console renders 24-bit colour once VT output is on.
        return "truecolor"
    if "256" in term:
        return "256"
    return "16" if term else "256"


def _glyph_level(env: Mapping[str, str], platform: str) -> str:
    if _truthy(env.get("JARVIS_INSTALL_ASCII")):
        return "ascii"
    term = env.get("TERM", "").lower()
    if term in _ASCII_TERMS or term.startswith("vt"):
        return "ascii"
    if platform == "win32":
        modern = (
            env.get("WT_SESSION")
            or env.get("TERM_PROGRAM", "").lower() in _MODERN_PROGRAMS
            or env.get("ConEmuANSI", "").upper() == "ON"
        )
        return "full" if modern else "basic"
    locale = env.get("LC_ALL") or env.get("LC_CTYPE") or env.get("LANG") or ""
    if not locale:
        # No locale at all (a bare container): trust a terminal that names itself.
        return "full" if env.get("TERM_PROGRAM") or env.get("COLORTERM") else "ascii"
    lowered = locale.lower()
    return "full" if "utf-8" in lowered or "utf8" in lowered else "ascii"


def _width(env: Mapping[str, str], stream: TextIO) -> int:
    columns = env.get("COLUMNS", "").strip()
    if columns.isdigit() and int(columns) > 0:
        return max(20, min(int(columns), 500))
    try:
        cols = os.get_terminal_size(stream.fileno()).columns
    except (AttributeError, ValueError, OSError):
        # Not a terminal behind the stream: the process's own size, or 80.
        cols = shutil.get_terminal_size((80, 24)).columns
    return max(20, min(cols or 80, 500))


def detect(
    env: Mapping[str, str] | None = None,
    stream: TextIO | None = None,
    platform: str | None = None,
) -> Caps:
    """Decide colour, glyphs, motion and width by the rules in the module doc."""
    env = os.environ if env is None else env
    stream = sys.stdout if stream is None else stream
    platform = sys.platform if platform is None else platform
    tty = _is_tty(stream)
    term = env.get("TERM", "").lower()
    vt = tty and (platform != "win32" or _windows_vt(stream))
    if env.get("NO_COLOR") or term == "dumb":
        color = "none"
    elif vt or (not tty and _truthy(env.get("FORCE_COLOR"))):
        color = _color_tier(env, platform)
    else:
        color = "none"
    motion = vt and term != "dumb" and not _truthy(env.get("CI"))
    return Caps(color, _glyph_level(env, platform), motion, _width(env, stream))


def cell_width(text: str) -> int:
    """Terminal columns ``text`` takes (wide East Asian characters count twice)."""
    width = 0
    for char in text:
        if unicodedata.combining(char):
            continue
        width += 2 if unicodedata.east_asian_width(char) in {"W", "F"} else 1
    return width


def strip_ansi(value: str) -> str:
    """``value`` without escape sequences, for width arithmetic and tests."""
    out: list[str] = []
    i = 0
    while i < len(value):
        if value[i] == "\x1b" and value[i + 1 : i + 2] == "[":
            end = i + 2
            while end < len(value) and not ("@" <= value[end] <= "~"):
                end += 1
            i = end + 1
            continue
        out.append(value[i])
        i += 1
    return "".join(out)


def format_duration(seconds: float | None) -> str:
    """``12s`` / ``1m 31s`` / ``1h 02m``; nothing under a second."""
    if seconds is None or seconds < 1:
        return ""
    total = int(seconds)
    if total < 60:
        return f"{total}s"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m {secs:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


@dataclass
class _Live:
    """The spinner line redrawn while a command runs."""

    label: str
    started: float = field(default_factory=time.monotonic)
    frame: int = 0


class InstallUI:
    """Draws the installer's phases, steps, failures and finale."""

    def __init__(self, caps: Caps | None = None, out: TextIO | None = None) -> None:
        self.caps = caps if caps is not None else detect(stream=out)
        self._out = out
        self.g = {"full": FULL, "basic": BASIC}.get(self.caps.glyphs, ASCII)
        self._lock = threading.RLock()
        self._live: _Live | None = None

    # ------------------------------------------------------------ output
    @property
    def out(self) -> TextIO:
        # Resolved at write time, so a replaced sys.stdout (pytest) is honoured.
        return self._out if self._out is not None else sys.stdout

    @property
    def layout(self) -> int:
        return min(self.caps.width, MAX_LAYOUT)

    def text(self, value: str) -> str:
        """Message text as this terminal can show it."""
        return value.translate(_ASCII_TEXT) if self.caps.glyphs == "ascii" else value

    def paint(
        self, value: str, rgb: RGB | None = None, *, bold: bool = False, bg: RGB | None = None
    ) -> str:
        """``value`` in a colour (and weight) this terminal supports."""
        if not value or self.caps.color == "none" or (rgb is None and bg is None and not bold):
            return value
        codes: list[str] = ["1"] if bold else []
        for colour, base in ((rgb, 30), (bg, 40)):
            if colour is None:
                continue
            if self.caps.color == "truecolor":
                codes.append(f"{base + 8};2;{colour[0]};{colour[1]};{colour[2]}")
            elif self.caps.color == "256":
                codes.append(f"{base + 8};5;{_XTERM_256.get(colour, 7)}")
            else:
                index = _ANSI_16.get(colour, 7)
                codes.append(str(base + index if index < 8 else base + 60 + index - 8))
        return f"\x1b[{';'.join(codes)}m{value}\x1b[0m"

    def emit(self, line: str = "") -> None:
        """Write one line, keeping a running spinner below it."""
        with self._lock:
            live = self._live is not None
            if live:
                self.out.write("\r\x1b[K")
            self.out.write(line + "\n")
            if live:
                self._draw_live()
            self.out.flush()

    def _right(self, left: str, right: str) -> str:
        """``left`` with ``right`` on the layout's right edge, when it fits."""
        if not right:
            return left
        gap = self.layout - 2 - cell_width(strip_ansi(left)) - cell_width(strip_ansi(right))
        return f"{left}{' ' * max(gap, 2)}{right}"

    # ------------------------------------------------------------ pieces
    def context(self, text: str) -> None:
        """A quiet line under the hero or a phase: where and what."""
        self.emit(f"  {self.paint(self.text(text), MUTED)}")

    def phase(self, num: int, title: str, total: int = PHASES) -> None:
        """A phase heading: a gold pill with the step number, then the title."""
        tag = f"{num}/{total}"
        title = self.text(title)
        self.emit()
        if self.caps.color == "none":
            self.emit(f"  [{tag}] {title}")
            return
        pill = self.paint(f" {tag} ", INK, bold=True, bg=GOLD)
        self.emit(f"  {pill}  {self.paint(title, bold=True)}")

    def ok(self, text: str, seconds: float | None = None, detail: str = "") -> None:
        """A finished step, with its time on the right.

        ``detail`` (a path, a reason) follows the text in a quiet colour when
        the line has room for it, and goes on its own quiet line when not.
        """
        mark = self.paint(self.g.ok, OK)
        body = self.text(text)
        detail = self.text(detail)
        took = format_duration(seconds)
        room = self.layout - 2 - TEXT_INDENT - (len(took) + 2 if took else 0)
        own_line = bool(detail) and cell_width(body) + 2 + cell_width(detail) > room
        if detail and not own_line:
            body += "  " + self.paint(detail, MUTED)
        left = f"{' ' * STEP_INDENT}{mark}  {body}"
        self.emit(self._right(left, self.paint(took, MUTED)))
        if own_line:
            self.note(detail)

    def skip(self, text: str) -> None:
        """Something optional that is not there; the install goes on."""
        self.emit(f"{' ' * STEP_INDENT}{self.paint(self.g.skip + '  ' + self.text(text), MUTED)}")

    def warn(self, text: str) -> None:
        mark = self.paint(self.g.warn, WARN, bold=True)
        self.emit(f"{' ' * STEP_INDENT}{mark}  {self.text(text)}")

    def note(self, text: str) -> None:
        """A quiet line under the step above it."""
        self.emit(f"{' ' * TEXT_INDENT}{self.paint(self.text(text), MUTED)}")

    def fail(
        self,
        title: str,
        lines: Sequence[str] = (),
        hints: Sequence[str] = (),
        help_url: str = "",
    ) -> None:
        """A failed step: what failed, the evidence, then what to try."""
        mark = self.paint(self.g.fail, BAD, bold=True)
        rail = self.paint(self.g.rail, BAD)
        pad = " " * STEP_INDENT
        self.emit(f"{pad}{mark}  {self.paint(self.text(title), bold=True)}")
        for line in lines:
            self.emit(f"{pad}{rail}  {self.paint(line, MUTED)}")
        if lines and (hints or help_url):
            self.emit(f"{pad}{rail}")
        self.hints(hints, help_url)

    def hints(self, hints: Sequence[str], help_url: str = "") -> None:
        """The "What to try" part of a failure, on the same red rail."""
        if not (hints or help_url):
            return
        rail = self.paint(self.g.rail, BAD)
        pad = " " * STEP_INDENT
        self.emit(f"{pad}{rail}  {self.paint('What to try', bold=True)}")
        for index, hint in enumerate(hints, 1):
            self.emit(f"{pad}{rail}  {self.paint(str(index), GOLD)}  {self.text(hint)}")
        if help_url:
            self.emit(f"{pad}{rail}  {self.paint('Help', MUTED)}  {help_url}")

    def stopped(self, text: str) -> None:
        """The closing line of a run that stopped."""
        self.emit()
        if self.caps.color == "none":
            self.emit(f"  [STOPPED] {self.text(text)}")
            return
        pill = self.paint(" STOPPED ", INK, bold=True, bg=BAD)
        self.emit(f"  {pill}  {self.text(text)}")

    def card(self, title: str, rows: Sequence[tuple[str, str]], took: str = "") -> None:
        """The finale: a framed card with the result and what to do next."""
        key_w = max((cell_width(key) for key, _ in rows), default=0) + 3
        body = [f"{self.paint(key.ljust(key_w), MUTED)}{self.text(value)}" for key, value in rows]
        badge = f" {self.g.ok} READY " if self.caps.glyphs != "ascii" else " READY "
        if self.caps.color == "none":
            head = f"[{badge.strip()}]  {self.text(title)}"
        else:
            head = f"{self.paint(badge, INK, bold=True, bg=OK)}  {self.paint(title, bold=True)}"
        took = self.paint(self.text(took), MUTED)
        widths = [cell_width(strip_ansi(line)) for line in body]
        need = max([*widths, cell_width(strip_ansi(head)) + cell_width(strip_ansi(took)) + 4])
        inner = max(need + 4, 60)
        if inner > self.layout - 4:
            inner = self.layout - 4
        if need + 4 > inner:
            # Too narrow for a frame: the same rows, unframed.
            self.emit()
            self.emit(f"  {head}" + (f"  {took}" if took else ""))
            for line in body:
                self.emit(f"  {line}")
            return
        top_l, top_r, bot_l, bot_r = self.g.corners
        edge = self.paint(self.g.v, GOLD_DEEP)

        def framed(content: str = "") -> str:
            fill = inner - 2 - cell_width(strip_ansi(content))
            return f"  {edge}  {content}{' ' * max(fill, 0)}{edge}"

        gap = inner - 4 - cell_width(strip_ansi(head)) - cell_width(strip_ansi(took))
        self.emit()
        self.emit(f"  {self.paint(top_l + self.g.h * inner + top_r, GOLD_DEEP)}")
        self.emit(framed())
        self.emit(framed(f"{head}{' ' * max(gap, 2)}{took}"))
        self.emit(framed())
        for line in body:
            self.emit(framed(line))
        self.emit(framed())
        self.emit(f"  {self.paint(bot_l + self.g.h * inner + bot_r, GOLD_DEEP)}")

    def launch(self, what: str, command: str) -> None:
        """The last lines: the app is starting, and the command if it does not."""
        point = self.paint(self.g.point, GOLD)
        title = self.paint(self.text(f"Launching {what}"), bold=True)
        self.emit()
        self.emit(f"  {point} {title} {self.paint(self.text('— it takes over from here.'), MUTED)}")
        self.emit(f"    {self.paint(RELAUNCH_LABEL, MUTED)} {command}")

    # ------------------------------------------------------------ live steps
    @contextmanager
    def spinner(self, label: str) -> Iterator[None]:
        """A live line with a spinner and the elapsed time while a command runs.

        Without motion (a pipe, CI) it writes the label once, so a log shows
        what the wait is for.
        """
        if not self.caps.motion:
            self.emit(f"{' ' * STEP_INDENT}{self.paint(self.g.skip, MUTED)}  "
                      f"{self.paint(self.text(label) + self.g.ellipsis, MUTED)}")
            yield
            return
        stop = threading.Event()
        with self._lock:
            self._live = _Live(self.text(label))
            self.out.write("\x1b[?25l")
            self._draw_live()
        thread = threading.Thread(target=self._spin, args=(stop,), daemon=True)
        thread.start()
        try:
            yield
        finally:
            stop.set()
            thread.join(timeout=1.0)
            with self._lock:
                self._live = None
                self.out.write("\r\x1b[K\x1b[?25h")
                self.out.flush()

    def _spin(self, stop: threading.Event) -> None:
        while not stop.wait(0.1):
            with self._lock:
                if self._live is None:
                    return
                self._live.frame += 1
                self._draw_live()

    def _draw_live(self) -> None:
        live = self._live
        if live is None:
            return
        frames = self.g.spin
        frame = self.paint(frames[live.frame % len(frames)], GOLD)
        elapsed = format_duration(time.monotonic() - live.started) or "0s"
        left = f"{' ' * STEP_INDENT}{frame}  {live.label}"
        line = self._right(left, self.paint(elapsed, MUTED))
        if cell_width(strip_ansi(line)) >= self.caps.width:
            # Never wrap the live line: a wrapped line cannot be redrawn in place.
            line = f"{' ' * STEP_INDENT}{frame}  {self.paint(elapsed, MUTED)}"
        self.out.write(f"\r\x1b[K{line}")
        self.out.flush()


__all__ = [
    "ASCII",
    "BASIC",
    "FULL",
    "Caps",
    "InstallUI",
    "cell_width",
    "detect",
    "format_duration",
    "strip_ansi",
]
