"""The rows a pane has scrolled past, kept so a viewer can be handed them again.

## Why this exists

A pane's viewer is xterm in the app, and its scrollback lives in that xterm
instance. The instance does not live long: switching between Chat and Grid,
switching workspace, reloading the window or restarting the app all build a new
one, and it starts empty. What it is rebuilt from is the pane's
:class:`~dodaios.agentic_ide.transcript.ReplayBuffer` — the last 128 KB of raw
output. For a coding agent that is very little: one short exchange in Claude
Code measured about 5.5 KB of drawing commands for ten rows of text (2.1.322,
2026-11-12), and a spinner alone writes several KB a second. And a resize
emptied the buffer altogether, because cursor moves made for one grid cannot be
replayed into another. So a re-joined pane held the last few screens at best,
and the start of the conversation was out of reach: "I could scroll a little,
but not all the way to the top" (maintainer report, 2026-11-12).

Keeping more raw bytes does not fix it. They are mostly repaints of the same
few rows, they cannot survive a resize, and megabytes of them would have to be
parsed again on every re-join.

So the pane's output is replayed onto a grid HERE, the way a terminal does it,
and every row that scrolls off the top is kept as one short string of text and
colour. That is what tmux does for the same reason. Ten thousand rows of
history cost about as much memory as a few seconds of raw output, are valid at
any width, and are written back in one pass.

## What it mirrors

xterm.js, because the goal is a re-joined viewer that holds what a viewer which
never left would hold. Where terminals differ, xterm's choice is the one
implemented:

* a row enters the history only when a line feed, a wrapping line or a resize
  pushes it off the top of the PRIMARY screen; ``CSI S`` discards rows, and so
  does everything on the alternate screen,
* ``ED 2`` erases in place (no scroll), ``ED 3`` empties the history,
* a resize drops rows below the cursor before it scrolls rows off the top.

The agreement is tested, not assumed: ``tests/fakes/terminal_scrollback_cases.json``
holds output streams with the replay this module makes of each, and the
frontend test ``terminalScrollbackReplay.test.ts`` plays every case through the
real xterm twice — as a pane that stayed, and as a pane rebuilt from that
replay — and compares the rows. A recorded Claude Code 2.1.322 session compared
the same way, at nineteen points including a resize, matched row for row.

Scope: the sequences a line-mode CLI or an inline TUI lays its output out with —
text with wrapping and wide glyphs, the C0 controls, cursor moves, erase, insert
and delete, scroll regions, SGR colours, the alternate screen. Hyperlinks
(OSC 8), character sets and protected areas are parsed and dropped.

Honest limits: glyph widths come from Python's Unicode tables, which can differ
from xterm's for a few emoji. Kept rows are text, not cells, so two things xterm
does on a resize are not repeated here: pulling rows back out of the scrollback
when a pane grows with the cursor on its last row, and joining wrapped rows
again when a pane widens. Either leaves a few rows near the seam doubled or in
another place than a viewer that stayed would have them; none is lost. And the
grid is a mirror, not the viewer's own buffer, so the visible screen it hands
back is followed by a repaint request wherever the agent can answer one (see
``SessionRegistry._attach_locked``). The history above the screen does not
depend on that.
"""

from __future__ import annotations

import re
import unicodedata
from collections import deque
from itertools import islice

from .screen import MAX_COLS, MAX_ROWS

#: How many scrolled-off rows a pane keeps. The same number as the viewer's own
#: scrollback (``scrollback`` in frontend/AgenticTerminal.tsx): rows past it
#: could be sent and would be dropped on arrival.
HISTORY_LIMIT_ROWS = 10_000

#: Upper bound on the characters those rows may hold, colour codes included.
#: Rows are usually well under 100 characters, so the row limit is the one that
#: is normally reached; this one bounds a pane that prints very long or densely
#: coloured rows. It also bounds the single write a re-joining viewer parses.
HISTORY_LIMIT_CHARS = 1024 * 1024

#: Smallest grid mirrored. A repaint nudge shrinks a pane to two rows at most.
_MIN_COLS, _MIN_ROWS = 2, 2

#: An unfinished escape sequence longer than this is not waited for; its
#: payload (an inline image, a clipboard write) is skipped up to its end mark.
_PENDING_MAX = 4096

#: Longest parameter string of a CSI sequence that is acted on. A colour change
#: naming every attribute stays far below it; past it the numbers are noise,
#: and Python refuses to convert a number of several thousand digits at all.
_PARAMS_MAX = 256

# A cell nothing was written to. Kept apart from a space the program printed,
# as xterm keeps them apart: only written cells count towards a row's length.
_BLANK = "\x00"
_RESET = "\x1b[0m"

# Characters that are certain to fill exactly one cell: ASCII, Latin, general
# punctuation, arrows, mathematical operators, box drawing, block elements,
# most geometric shapes, braille (spinners). A run of them is laid out in one
# step; every other character is looked up on its own (see ``_width``).
_NARROW = (
    r"\x20-\x7e\xa0-\u02ff\u2010-\u2027\u2030-\u205e"
    r"\u2190-\u22ff\u2500-\u25fc\u2800-\u28ff"
)

# One token of a terminal stream, most common first. The group NUMBERS are
# what ``feed`` dispatches on. The last branch excludes the bytes that open a
# longer sequence, so a CSI cut off by a PTY read is never mistaken for a
# two-byte escape.
_TOKEN_RE = re.compile(
    rf"([{_NARROW}]+)"  # 1: a run of one-cell characters
    r"|(\x1b\[([<-?]*)([0-9;:]*)([ -/]*)([@-~]))"  # 2: CSI — 3..6 its parts
    r"|([\x00-\x1a\x1c-\x1f\x7f])"  # 7: a C0 control
    r"|([^\x00-\x1f\x7f])"  # 8: any other character
    r"|(\x1b\][^\x07\x1b]*(?:\x07|\x1b\\))"  # 9: OSC
    r"|(\x1b[PX^_][^\x1b]*\x1b\\)"  # 10: DCS, SOS, PM, APC
    r"|(\x1b([ -/]*)([0-OQ-WYZ\\`-~]))"  # 11: other escapes — 12, 13 its parts
)
_NARROW_RE = re.compile(rf"[{_NARROW}]+")
# A sequence the read ended inside of: the rest is at the front of the next one.
_INCOMPLETE_RE = re.compile(
    r"\x1b(?:\[[<-?]*[0-9;:]*[ -/]*|\][^\x07\x1b]*\x1b?|[PX^_][^\x1b]*\x1b?|[ -/]*)\Z"
)
_STRING_OPENERS = ("\x1b]", "\x1bP", "\x1bX", "\x1b^", "\x1b_")
_STRING_END_RE = re.compile(r"\x07|\x1b\\")

_WIDTHS: dict[str, int] = {}


def _width(ch: str) -> int:
    """Cells a non-ASCII character occupies: 0, 1 or 2."""
    cached = _WIDTHS.get(ch)
    if cached is not None:
        return cached
    code = ord(ch)
    if code < 0xA0:
        width = 0  # C1 controls: nothing to draw
    elif code < 0x300:
        width = 1
    elif unicodedata.combining(ch) or unicodedata.category(ch) in ("Mn", "Me", "Cf"):
        width = 0
    elif unicodedata.east_asian_width(ch) in ("W", "F"):
        width = 2
    else:
        width = 1
    if len(_WIDTHS) < 8192:
        _WIDTHS[ch] = width
    return width


class _Row:
    """One row of cells. A wide glyph is followed by an empty-string cell."""

    __slots__ = ("chars", "styles", "continued")

    def __init__(self, cols: int, style: str = "") -> None:
        self.chars: list[str] = [_BLANK] * cols
        self.styles: list[str] = [style] * cols
        #: This row carries on the text of the row above: it was reached by
        #: wrapping, not by a line break (xterm's ``isWrapped``).
        self.continued = False

    def content_end(self) -> int:
        """Index past the last cell that shows anything."""
        chars, styles = self.chars, self.styles
        end = len(chars)
        while end and chars[end - 1] == _BLANK and not styles[end - 1]:
            end -= 1
        return end

    def fit(self, cols: int) -> None:
        current = len(self.chars)
        if current < cols:
            self.chars.extend([_BLANK] * (cols - current))
            self.styles.extend([""] * (cols - current))
        elif current > cols:
            del self.chars[cols:]
            del self.styles[cols:]

    def text(self, *, full: bool = False) -> str:
        """The row as a terminal would be sent it: text plus colour changes.

        ``full`` keeps the blank cells at its end, for a row whose text runs on
        into the next one: the next row has to start in the first column.
        """
        end = len(self.chars) if full else self.content_end()
        if not end:
            return ""
        return self._text(end).replace(_BLANK, " ")

    def _text(self, end: int) -> str:
        chars, styles = self.chars, self.styles
        if not any(styles[:end]):
            return "".join(chars[:end])
        out: list[str] = []
        current = ""
        start = 0
        for index in range(end):
            style = styles[index]
            if style != current:
                if index > start:
                    out.append("".join(chars[start:index]))
                # Absolute, so a row never depends on the one before it.
                out.append(f"\x1b[0;{style}m" if style else _RESET)
                current = style
                start = index
        out.append("".join(chars[start:end]))
        if current:
            out.append(_RESET)
        return "".join(out)


class _Screen:
    """A grid with its own cursor and scroll region (primary or alternate)."""

    __slots__ = ("grid", "cx", "cy", "pending", "top", "bottom", "saved")

    def __init__(self, cols: int, rows: int) -> None:
        self.grid: list[_Row] = [_Row(cols) for _ in range(rows)]
        self.cx = 0
        self.cy = 0
        #: A glyph sits in the last column and the next one starts a new row.
        self.pending = False
        self.top = 0
        self.bottom = rows - 1
        self.saved: tuple[int, int, str] = (0, 0, "")


# SGR attributes that are simple switches: the code that sets each one, and
# the slot it occupies. Bold and dim share a reset (22), as terminals have it.
_SGR_ON = {1: 0, 2: 1, 3: 2, 5: 4, 6: 4, 7: 5, 8: 6, 9: 7, 53: 8}
_SGR_OFF = {22: (0, 1), 23: (2,), 24: (3,), 25: (4,), 27: (5,), 28: (6,), 29: (7,), 55: (8,)}
_SLOT_FG, _SLOT_BG, _SLOT_UNDERLINE_COLOUR = 9, 10, 11
_SLOT_COUNT = 12
_SLOT_UNDERLINE = 3


def _apply_sgr(slots: list[str], params: str) -> None:
    """Fold one ``CSI ... m`` into the attribute slots."""
    parts = params.split(";") if params else ["0"]
    index = 0
    count = len(parts)
    while index < count:
        part = parts[index]
        index += 1
        head, _, sub = part.partition(":")
        if head and not (head.isascii() and head.isdigit()):
            continue  # not a number: skipped, as a terminal skips it
        code = int(head) if head else 0
        if code == 0:
            slots[:] = [""] * _SLOT_COUNT
        elif code in _SGR_ON:
            slots[_SGR_ON[code]] = str(code)
        elif code in _SGR_OFF:
            for slot in _SGR_OFF[code]:
                slots[slot] = ""
        elif code == 4:
            # ``4:0`` is "no underline"; ``4:3`` a curly one.
            slots[_SLOT_UNDERLINE] = "" if sub == "0" else part
        elif code == 21:
            slots[_SLOT_UNDERLINE] = "21"
        elif 30 <= code <= 37 or 90 <= code <= 97:
            slots[_SLOT_FG] = str(code)
        elif 40 <= code <= 47 or 100 <= code <= 107:
            slots[_SLOT_BG] = str(code)
        elif code == 39:
            slots[_SLOT_FG] = ""
        elif code == 49:
            slots[_SLOT_BG] = ""
        elif code == 59:
            slots[_SLOT_UNDERLINE_COLOUR] = ""
        elif code in (38, 48, 58):
            slot = {38: _SLOT_FG, 48: _SLOT_BG, 58: _SLOT_UNDERLINE_COLOUR}[code]
            if sub:
                slots[slot] = part  # the colon form carries its own arguments
                continue
            mode = parts[index] if index < count else ""
            take = 2 if mode == "5" else 4 if mode == "2" else 0
            if not take or index + take > count:
                break  # malformed: nothing after it can be trusted
            slots[slot] = ";".join([str(code), *parts[index : index + take]])
            index += take


class ScrollbackMirror:
    """A terminal screen replayed from a PTY stream, with its scrolled-off rows."""

    __slots__ = (
        "cols",
        "rows",
        "limit_rows",
        "limit_chars",
        "scrolled",
        "_primary",
        "_alt",
        "_screen",
        "_history",
        "_history_chars",
        "_dropped",
        "_pending",
        "_skipping",
        "_slots",
        "_style",
        "_erase",
        "_styles",
        "_autowrap",
        "_last",
    )

    def __init__(
        self,
        cols: int = 100,
        rows: int = 30,
        *,
        limit_rows: int = HISTORY_LIMIT_ROWS,
        limit_chars: int = HISTORY_LIMIT_CHARS,
    ) -> None:
        self.cols = min(max(cols, _MIN_COLS), MAX_COLS)
        self.rows = min(max(rows, _MIN_ROWS), MAX_ROWS)
        self.limit_rows = limit_rows
        self.limit_chars = limit_chars
        #: Rows that have entered the history since the last :meth:`clear` — a
        #: counter that only grows, so a caller can remember "up to here".
        self.scrolled = 0
        self._history: deque[str] = deque()
        self._styles: dict[tuple[str, str], tuple[str, list[str]]] = {}
        self._start()

    def _start(self) -> None:
        self._primary = _Screen(self.cols, self.rows)
        self._alt: _Screen | None = None
        self._screen = self._primary
        self._history.clear()
        self._history_chars = 0
        self._dropped = self.scrolled
        self._pending = ""
        self._skipping = False
        self._slots = [""] * _SLOT_COUNT
        self._style = ""
        self._erase = ""
        self._autowrap = True
        self._last = ""

    # ------------------------------------------------------------- lifecycle
    def clear(self) -> None:
        """Forget everything: the pane is being handed to a new process."""
        self.scrolled = 0
        self._start()

    @property
    def history_rows(self) -> int:
        return len(self._history)

    @property
    def on_alternate_screen(self) -> bool:
        return self._screen is not self._primary

    def resize(self, cols: int, rows: int) -> None:
        """Follow the pane to a new size, the way the viewer's terminal does.

        In xterm's order, because the agent repaints for the terminal xterm
        leaves behind. First the height: growing adds blank rows at the bottom;
        shrinking drops the rows below the cursor and only then scrolls rows
        off the top (into the history, on the primary screen). Then the width:
        a row too long for it is broken into several rather than cut, so its
        text is still there when it later scrolls off, and the rows that adds
        push the top of the screen into the history. Widening only pads.
        """
        cols = min(max(cols, _MIN_COLS), MAX_COLS)
        rows = min(max(rows, _MIN_ROWS), MAX_ROWS)
        if cols == self.cols and rows == self.rows:
            return
        old_cols = self.cols
        self.cols, self.rows = cols, rows
        for screen in (self._primary, self._alt):
            if screen is None:
                continue
            primary = screen is self._primary
            grid = screen.grid
            if cols > old_cols:
                for row in grid:
                    row.fit(cols)
            while len(grid) < rows:
                grid.append(_Row(max(cols, old_cols)))
            while len(grid) > rows:
                if len(grid) - 1 > screen.cy:
                    grid.pop()
                else:
                    row = grid.pop(0)
                    if primary:
                        self._keep(row, full=grid[0].continued)
                    screen.cy -= 1
            if cols < old_cols:
                if primary:
                    self._rewrap(screen, cols)
                    grid = screen.grid
                    while len(grid) > rows:
                        if not self._history and len(grid) - 1 > screen.cy:
                            grid.pop()
                        else:
                            row = grid.pop(0)
                            self._keep(row, full=grid[0].continued)
                            screen.cy -= 1
                for row in grid:
                    row.fit(cols)
            screen.cy = min(max(screen.cy, 0), rows - 1)
            screen.cx = min(screen.cx, cols - 1)
            screen.pending = False
            screen.top, screen.bottom = 0, rows - 1
            saved_x, saved_y, saved_style = screen.saved
            screen.saved = (min(saved_x, cols - 1), min(saved_y, rows - 1), saved_style)

    def _rewrap(self, screen: _Screen, cols: int) -> None:
        """Lay rows wider than ``cols`` out again, keeping their text.

        A row and the rows that continue it are one line of text and are
        broken as one, so a line that already wrapped does not gain a short
        row in its middle.
        """
        old = screen.grid
        grid: list[_Row] = []
        cursor_row = screen.cy
        cursor_col = screen.cx
        index = 0
        while index < len(old):
            last = index
            while last + 1 < len(old) and old[last + 1].continued:
                last += 1
            group = old[index : last + 1]
            ends = [len(row.chars) for row in group[:-1]] + [group[-1].content_end()]
            if last == index and ends[0] <= cols:
                if index == screen.cy:
                    cursor_row = len(grid)
                grid.append(group[0])
                index = last + 1
                continue
            chars: list[str] = []
            styles: list[str] = []
            cursor_at = -1
            for offset, (row, end) in enumerate(zip(group, ends, strict=True)):
                if index + offset == screen.cy:
                    cursor_at = len(chars) + screen.cx
                chars.extend(row.chars[:end])
                styles.extend(row.styles[:end])
            start = 0
            first = True
            while True:
                stop = min(start + cols, len(chars))
                # Never between the two halves of a wide glyph.
                if stop < len(chars) and chars[stop] == "" and stop - start > 1:
                    stop -= 1
                piece = _Row(cols)
                piece.chars[: stop - start] = chars[start:stop]
                piece.styles[: stop - start] = styles[start:stop]
                piece.continued = group[0].continued if first else True
                if cursor_at >= start:
                    cursor_row = len(grid)
                    cursor_col = min(cursor_at - start, cols - 1)
                grid.append(piece)
                first = False
                start = stop
                if start >= len(chars):
                    break
            index = last + 1
        screen.grid = grid
        screen.cy = cursor_row
        screen.cx = cursor_col

    # ---------------------------------------------------------------- output
    def history_text(self, upto: int | None = None) -> str:
        """The scrolled-off rows, oldest first, ready to be written to a terminal.

        ``upto`` limits them to the rows that had scrolled off when
        :attr:`scrolled` held that value. Rows are separated by line breaks,
        except where one carries on the text of the row before it; there is no
        line break after the last one.
        """
        if upto is None:
            text = "".join(self._history)
        else:
            keep = upto - self._dropped
            if keep <= 0:
                return ""
            text = "".join(islice(self._history, keep))
        return text[2:] if text.startswith("\r\n") else text

    def rows_text(self) -> str:
        """The history and then the primary screen's rows, as one piece of text.

        Written into a terminal of this size, the screen's rows land in the
        viewport and the history above it — every row of the screen is written,
        the empty ones too, which is what pushes the history out of view.
        """
        parts: list[str] = list(self._history)
        grid = self._primary.grid
        last = len(grid) - 1
        for index, row in enumerate(grid):
            if not row.continued:
                parts.append("\r\n")
            parts.append(row.text(full=index < last and grid[index + 1].continued))
        text = "".join(parts)
        return text[2:] if text.startswith("\r\n") else text

    def cursor_text(self) -> str:
        """Scroll region, cursor position and colour — written after the modes."""
        screen = self._primary
        out: list[str] = []
        if screen.top != 0 or screen.bottom != self.rows - 1:
            out.append(f"\x1b[{screen.top + 1};{screen.bottom + 1}r")
        out.append(f"\x1b[{screen.cy + 1};{screen.cx + 1}H")
        style = self._style
        out.append(f"\x1b[0;{style}m" if style else _RESET)
        return "".join(out)

    def display(self) -> list[str]:
        """Plain text of the active screen's rows (for tests and diagnostics)."""
        return ["".join(row.chars).replace(_BLANK, " ").rstrip() for row in self._screen.grid]

    # ------------------------------------------------------------------ feed
    def feed(self, chunk: str) -> None:
        """Replay a raw PTY chunk onto the grid."""
        if not chunk:
            return
        data = self._pending + chunk if self._pending else chunk
        self._pending = ""
        pos = 0
        end = len(data)
        if self._skipping:
            found = _STRING_END_RE.search(data)
            if found is None:
                # The end mark may itself be split: keep a lone trailing ESC.
                self._pending = "\x1b" if data.endswith("\x1b") else ""
                return
            self._skipping = False
            pos = found.end()
        match = _TOKEN_RE.match
        while pos < end:
            token = match(data, pos)
            if token is None:
                if _INCOMPLETE_RE.match(data, pos) is not None:
                    if end - pos <= _PENDING_MAX:
                        self._pending = data[pos:]
                        return
                    if data.startswith(_STRING_OPENERS, pos):
                        self._skipping = True
                        self._pending = "\x1b" if data.endswith("\x1b") else ""
                        return
                pos += 1  # a malformed sequence: drop its ESC and go on
                continue
            pos = token.end()
            kind = token.lastindex
            if kind == 1:
                self._print(token.group())
            elif kind == 2:
                private, params, intermediates, final = token.group(3, 4, 5, 6)
                if final == "m" and not private and not intermediates:
                    if len(params) <= _PARAMS_MAX:
                        self._sgr(params)
                else:
                    self._csi(private, params, intermediates, final)
            elif kind == 7:
                self._control(token.group())
            elif kind == 8:
                self._print_glyph(token.group())
            elif kind == 11 and not token.group(12):
                self._escape(token.group(13))
            # OSC and the other string sequences draw nothing.

    def _print(self, run: str) -> None:
        """Lay out a run of characters that each fill one cell."""
        screen = self._screen
        cols = self.cols
        style = self._style
        index = 0
        count = len(run)
        while index < count:
            if screen.pending:
                self._wrap(screen)
            row = screen.grid[screen.cy]
            cx = screen.cx
            take = min(cols - cx, count - index)
            row.chars[cx : cx + take] = run[index : index + take]
            row.styles[cx : cx + take] = [style] * take
            index += take
            cx += take
            if cx >= cols:
                screen.cx = cols - 1
                if self._autowrap:
                    screen.pending = True
                else:
                    # Without wraparound the rest piles up in the last cell.
                    row.chars[cols - 1] = run[-1]
                    break
            else:
                screen.cx = cx
        self._last = run[-1]

    def _print_glyph(self, ch: str) -> None:
        """Lay out one character of unknown width: wide, combining, or neither."""
        screen = self._screen
        cols = self.cols
        width = _width(ch)
        if width == 0:
            # A combining mark or joiner belongs to the glyph before it.
            target = screen.cx if screen.pending else screen.cx - 1
            if target >= 0:
                row = screen.grid[screen.cy]
                if row.chars[target] == "" and target > 0:
                    target -= 1
                row.chars[target] += ch
            return
        if screen.pending:
            self._wrap(screen)
        if width == 2 and screen.cx + 2 > cols:
            if not self._autowrap:
                return
            self._wrap(screen)
        row = screen.grid[screen.cy]
        cx = screen.cx
        row.chars[cx] = ch
        row.styles[cx] = self._style
        if width == 2 and cx + 1 < cols:
            row.chars[cx + 1] = ""
            row.styles[cx + 1] = self._style
        cx += width
        if cx >= cols:
            screen.cx = cols - 1
            screen.pending = self._autowrap
        else:
            screen.cx = cx
        self._last = ch

    def _wrap(self, screen: _Screen) -> None:
        screen.pending = False
        screen.cx = 0
        self._index(screen)
        screen.grid[screen.cy].continued = True

    def _index(self, screen: _Screen) -> None:
        """Move down one row, scrolling the region when at its bottom."""
        if screen.cy == screen.bottom:
            self._scroll_up(screen, 1, keep=True)
        elif screen.cy < self.rows - 1:
            screen.cy += 1
            # An explicit move onto a row ends whatever wrapped onto it before.
            screen.grid[screen.cy].continued = False

    def _reverse_index(self, screen: _Screen) -> None:
        if screen.cy == screen.top:
            self._scroll_down(screen, 1)
        elif screen.cy > 0:
            screen.cy -= 1

    def _scroll_up(self, screen: _Screen, count: int, *, keep: bool) -> None:
        grid = screen.grid
        top, bottom = screen.top, screen.bottom
        # Only a row leaving the very top of the primary screen is history.
        keep = keep and top == 0 and screen is self._primary
        for _ in range(min(count, bottom - top + 1)):
            row = grid.pop(top)
            if keep:
                self._keep(row, full=bool(grid) and grid[0].continued)
            grid.insert(bottom, _Row(self.cols, self._erase))

    def _scroll_down(self, screen: _Screen, count: int) -> None:
        grid = screen.grid
        top, bottom = screen.top, screen.bottom
        for _ in range(min(count, bottom - top + 1)):
            grid.pop(bottom)
            grid.insert(top, _Row(self.cols, self._erase))

    def _keep(self, row: _Row, *, full: bool = False) -> None:
        """Move ``row`` into the history. ``full``: the next row continues it."""
        text = row.text(full=full) if row.continued else "\r\n" + row.text(full=full)
        history = self._history
        history.append(text)
        self._history_chars += len(text)
        self.scrolled += 1
        while history and (
            len(history) > self.limit_rows or self._history_chars > self.limit_chars
        ):
            self._history_chars -= len(history.popleft())
            self._dropped += 1

    def _control(self, ch: str) -> None:
        screen = self._screen
        if ch == "\n" or ch == "\x0b" or ch == "\x0c":
            screen.pending = False
            self._index(screen)
        elif ch == "\r":
            screen.pending = False
            screen.cx = 0
        elif ch == "\x08":
            screen.pending = False
            if screen.cx > 0:
                screen.cx -= 1
        elif ch == "\t" and not screen.pending:
            screen.cx = min(self.cols - 1, (screen.cx // 8 + 1) * 8)

    def _escape(self, final: str) -> None:
        screen = self._screen
        if final == "7":
            screen.saved = (screen.cx, screen.cy, self._style)
        elif final == "8":
            self._restore_cursor(screen)
        elif final == "D":
            screen.pending = False
            self._index(screen)
        elif final == "E":
            screen.pending = False
            screen.cx = 0
            self._index(screen)
        elif final == "M":
            screen.pending = False
            self._reverse_index(screen)
        elif final == "c":
            # A full reset empties the terminal, history included.
            self._start()

    def _restore_cursor(self, screen: _Screen) -> None:
        cx, cy, style = screen.saved
        screen.cx = min(cx, self.cols - 1)
        screen.cy = min(cy, self.rows - 1)
        screen.pending = False
        self._set_style(style)

    def _set_style(self, style: str) -> None:
        slots = [""] * _SLOT_COUNT
        if style:
            _apply_sgr(slots, style)
        self._slots = slots
        self._style = style
        self._erase = slots[_SLOT_BG]

    def _sgr(self, params: str) -> None:
        # An agent repeats a handful of colour changes thousands of times, so
        # what each one turns the current style into is remembered.
        key = (self._style, params)
        known = self._styles.get(key)
        if known is None:
            slots = list(self._slots)
            _apply_sgr(slots, params)
            known = (";".join(slot for slot in slots if slot), slots)
            if len(self._styles) >= 4096:
                self._styles.clear()
            self._styles[key] = known
        self._style, self._slots = known
        self._erase = self._slots[_SLOT_BG]

    def _csi(self, private: str, params: str, intermediates: str, final: str) -> None:
        if len(params) > _PARAMS_MAX:
            return  # not a sequence any program lays text out with
        if intermediates:
            if intermediates == "!" and final == "p" and not private:
                self._soft_reset()
            return
        if private:
            if private != "?":
                return  # ``CSI > ... m`` and friends configure keys, not cells
            if final == "h" or final == "l":
                for part in params.split(";"):
                    if part.isdigit():
                        self._private_mode(int(part), final == "h")
                return
            if final != "J" and final != "K":
                return
        if final == "m":
            self._sgr(params)
            return
        screen = self._screen
        cols, rows = self.cols, self.rows
        numbers = _numbers(params)
        first = numbers[0] if numbers else 0
        count = first or 1
        if final == "H" or final == "f":
            second = numbers[1] if len(numbers) > 1 else 0
            screen.cy = min(max(first, 1), rows) - 1
            screen.cx = min(max(second, 1), cols) - 1
            screen.pending = False
        elif final == "A":
            floor = screen.top if screen.cy >= screen.top else 0
            screen.cy = max(floor, screen.cy - count)
            screen.pending = False
        elif final == "B" or final == "e":
            ceiling = screen.bottom if screen.cy <= screen.bottom else rows - 1
            screen.cy = min(ceiling, screen.cy + count)
            screen.pending = False
        elif final == "C" or final == "a":
            screen.cx = min(cols - 1, screen.cx + count)
            screen.pending = False
        elif final == "D":
            screen.cx = max(0, screen.cx - count)
            screen.pending = False
        elif final == "E":
            ceiling = screen.bottom if screen.cy <= screen.bottom else rows - 1
            screen.cy = min(ceiling, screen.cy + count)
            screen.cx = 0
            screen.pending = False
        elif final == "F":
            floor = screen.top if screen.cy >= screen.top else 0
            screen.cy = max(floor, screen.cy - count)
            screen.cx = 0
            screen.pending = False
        elif final == "G" or final == "`":
            screen.cx = min(count, cols) - 1
            screen.pending = False
        elif final == "d":
            screen.cy = min(count, rows) - 1
            screen.pending = False
        elif final == "K":
            self._erase_in_line(screen, first)
        elif final == "J":
            self._erase_in_display(screen, first)
        elif final == "L":
            self._insert_lines(screen, count)
        elif final == "M":
            self._delete_lines(screen, count)
        elif final == "P":
            self._delete_chars(screen, count)
        elif final == "@":
            self._insert_chars(screen, count)
        elif final == "X":
            cx = screen.cx
            stop = min(cols, cx + count)
            row = screen.grid[screen.cy]
            row.chars[cx:stop] = [_BLANK] * (stop - cx)
            row.styles[cx:stop] = [self._erase] * (stop - cx)
            screen.pending = False
        elif final == "S":
            self._scroll_up(screen, count, keep=False)
        elif final == "T":
            self._scroll_down(screen, count)
        elif final == "r":
            second = numbers[1] if len(numbers) > 1 else 0
            top = max(first, 1)
            bottom = second if 0 < second <= rows else rows
            if bottom > top:
                screen.top, screen.bottom = top - 1, bottom - 1
                screen.cx = screen.cy = 0
                screen.pending = False
        elif final == "s":
            if not params:
                screen.saved = (screen.cx, screen.cy, self._style)
        elif final == "u":
            if not params:
                self._restore_cursor(screen)
        elif final == "b":
            # Repeat the last character. Bounded by the screen: more than that
            # could only scroll, and a stream must not be able to ask for work
            # without end.
            if self._last and _NARROW_RE.fullmatch(self._last):
                self._print(self._last * min(count, cols * rows))
            elif self._last:
                for _ in range(min(count, cols)):
                    self._print_glyph(self._last)

    def _private_mode(self, mode: int, on: bool) -> None:
        if mode == 7:
            self._autowrap = on
        elif mode == 1048:
            if on:
                self._screen.saved = (self._screen.cx, self._screen.cy, self._style)
            else:
                self._restore_cursor(self._screen)
        elif mode in (47, 1047, 1049):
            primary = self._primary
            if on:
                if mode == 1049:
                    primary.saved = (primary.cx, primary.cy, self._style)
                if self._screen is primary:
                    # The alternate screen always starts empty, cursor in place.
                    alt = _Screen(self.cols, self.rows)
                    alt.cx, alt.cy = primary.cx, primary.cy
                    primary.pending = False
                    self._alt = alt
                    self._screen = alt
            else:
                if self._screen is not primary:
                    alt = self._screen
                    primary.cx, primary.cy = alt.cx, alt.cy
                    self._alt = None
                    self._screen = primary
                if mode == 1049:
                    self._restore_cursor(primary)

    def _soft_reset(self) -> None:
        screen = self._screen
        screen.top, screen.bottom = 0, self.rows - 1
        screen.saved = (0, 0, "")
        self._autowrap = True
        self._set_style("")

    def _erase_in_line(self, screen: _Screen, mode: int) -> None:
        row = screen.grid[screen.cy]
        cols = self.cols
        cx = screen.cx
        if mode == 0:
            start, stop = cx, cols
            if cx == 0:
                row.continued = False
        elif mode == 1:
            start, stop = 0, cx + 1
        elif mode == 2:
            start, stop = 0, cols
            row.continued = False
        else:
            return
        row.chars[start:stop] = [_BLANK] * (stop - start)
        row.styles[start:stop] = [self._erase] * (stop - start)
        screen.pending = False

    def _erase_in_display(self, screen: _Screen, mode: int) -> None:
        grid = screen.grid
        if mode == 0:
            self._erase_in_line(screen, 0)
            first, last = screen.cy + 1, self.rows
        elif mode == 1:
            self._erase_in_line(screen, 1)
            first, last = 0, screen.cy
        elif mode == 2:
            first, last = 0, self.rows
            screen.pending = False
        elif mode == 3:
            # The terminal's own "forget the scrollback".
            self._history.clear()
            self._history_chars = 0
            self._dropped = self.scrolled
            return
        else:
            return
        for index in range(first, last):
            grid[index] = _Row(self.cols, self._erase)

    def _insert_lines(self, screen: _Screen, count: int) -> None:
        if not screen.top <= screen.cy <= screen.bottom:
            return
        grid = screen.grid
        for _ in range(min(count, screen.bottom - screen.cy + 1)):
            grid.pop(screen.bottom)
            grid.insert(screen.cy, _Row(self.cols, self._erase))
        screen.cx = 0
        screen.pending = False

    def _delete_lines(self, screen: _Screen, count: int) -> None:
        if not screen.top <= screen.cy <= screen.bottom:
            return
        grid = screen.grid
        for _ in range(min(count, screen.bottom - screen.cy + 1)):
            grid.pop(screen.cy)
            grid.insert(screen.bottom, _Row(self.cols, self._erase))
        screen.cx = 0
        screen.pending = False

    def _insert_chars(self, screen: _Screen, count: int) -> None:
        row = screen.grid[screen.cy]
        cx = screen.cx
        count = min(count, self.cols - cx)
        row.chars[cx:cx] = [_BLANK] * count
        row.styles[cx:cx] = [self._erase] * count
        row.fit(self.cols)
        screen.pending = False

    def _delete_chars(self, screen: _Screen, count: int) -> None:
        row = screen.grid[screen.cy]
        cx = screen.cx
        count = min(count, self.cols - cx)
        del row.chars[cx : cx + count]
        del row.styles[cx : cx + count]
        row.chars.extend([_BLANK] * count)
        row.styles.extend([self._erase] * count)
        screen.pending = False


def _numbers(params: str) -> list[int]:
    """The numeric parameters of a CSI sequence; a missing one reads as 0."""
    if not params:
        return []
    if params.isdigit():
        return [int(params)]
    numbers: list[int] = []
    for part in params.split(";"):
        head = part.partition(":")[0]
        numbers.append(int(head) if head.isdigit() else 0)
    return numbers


__all__ = ["HISTORY_LIMIT_CHARS", "HISTORY_LIMIT_ROWS", "ScrollbackMirror"]
