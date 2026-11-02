"""The styled screen mirror of one watched pane (contract 5.1, architecture 5.3).

``dodaios.agentic_ide.screen.ScreenBuffer`` replays a PTY stream for reading
and drops colours. The Verse desk monitors need what the IDE shows, so this
is a second, attribute-keeping grid created only for the panes Verse
watches. It keeps per cell ``(char, fg, bg, attrs)`` in the ``cells.bin/1``
encodings (:mod:`.cells_codec`) and records which rows changed since the
last frame, so the screens relay sends dirty rows only.

Supported beyond the base buffer: SGR (bold, dim, italic, underline, blink,
inverse, invisible, strikethrough, 16/256 palette colours, 24-bit RGB, their
resets), wide glyphs (two columns), the alternate screen (1049/1047/47),
save and restore cursor (DECSC/DECRC, CSI s/u). The base buffer stays
untouched and dependency-free.
"""

from __future__ import annotations

import re
import unicodedata

from .cells_codec import (
    ATTR_BITS,
    DEFAULT_COLOUR,
    MAX_COLS,
    MAX_ROWS,
    WIDE,
    Cell,
    is_wide,
    palette,
    rgb,
    row_runs,
)

_SGR_SET = {
    1: ATTR_BITS["bold"],
    2: ATTR_BITS["dim"],
    3: ATTR_BITS["italic"],
    4: ATTR_BITS["underline"],
    5: ATTR_BITS["blink"],
    6: ATTR_BITS["blink"],
    7: ATTR_BITS["inverse"],
    8: ATTR_BITS["invisible"],
    9: ATTR_BITS["strikethrough"],
}
_SGR_CLEAR = {
    21: ATTR_BITS["bold"],
    22: ATTR_BITS["bold"] | ATTR_BITS["dim"],
    23: ATTR_BITS["italic"],
    24: ATTR_BITS["underline"],
    25: ATTR_BITS["blink"],
    27: ATTR_BITS["inverse"],
    28: ATTR_BITS["invisible"],
    29: ATTR_BITS["strikethrough"],
}


_ASCII_RUN = re.compile(r"[ -~]+")


def _clamp(value: int, low: int, high: int) -> int:
    return low if value < low else high if value > high else value


class StyledScreen:
    """A styled cell grid with a cursor and dirty-row tracking."""

    def __init__(self, cols: int = 100, rows: int = 30) -> None:
        self.cols = _clamp(cols, 1, 500)
        self.rows = _clamp(rows, 1, 200)
        self._fg = DEFAULT_COLOUR
        self._bg = DEFAULT_COLOUR
        self._attrs = 0
        self._grid = [self._blank_row() for _ in range(self.rows)]
        self._alt: list[list[Cell]] | None = None
        self._main_saved: list[list[Cell]] | None = None
        self.cursor_row = 0
        self.cursor_col = 0
        self.cursor_visible = True
        self._saved_cursor = (0, 0, DEFAULT_COLOUR, DEFAULT_COLOUR, 0)
        self._scroll_top = 0
        self._scroll_bottom = self.rows - 1
        self._wrap_pending = False
        self._pending = ""
        self.dirty: set[int] = set(range(self.rows))
        self.resized = False
        self.errors = 0

    # ------------------------------------------------------------------ grid
    def _blank(self) -> Cell:
        # Erase fills with the current background (VT "bce" behaviour).
        return (" ", DEFAULT_COLOUR, self._bg, 0)

    def _blank_row(self) -> list[Cell]:
        blank = self._blank()
        return [blank] * self.cols

    def _touch(self, row: int) -> None:
        self.dirty.add(row)

    def _touch_range(self, top: int, bottom: int) -> None:
        self.dirty.update(range(top, bottom + 1))

    def resize(self, cols: int, rows: int) -> None:
        cols, rows = _clamp(cols, 1, 500), _clamp(rows, 1, 200)
        if (cols, rows) == (self.cols, self.rows):
            return
        old = self._grid
        self.cols, self.rows = cols, rows
        self._grid = [self._blank_row() for _ in range(rows)]
        for r in range(min(rows, len(old))):
            for c in range(min(cols, len(old[r]))):
                self._grid[r][c] = old[r][c]
        self.cursor_row = min(self.cursor_row, rows - 1)
        self.cursor_col = min(self.cursor_col, cols - 1)
        self._scroll_top, self._scroll_bottom = 0, rows - 1
        self.dirty = set(range(rows))
        self.resized = True

    def _scroll_up(self, count: int = 1) -> None:
        for _ in range(max(1, count)):
            self._grid.pop(self._scroll_top)
            self._grid.insert(self._scroll_bottom, self._blank_row())
        self._touch_range(self._scroll_top, self._scroll_bottom)

    def _scroll_down(self, count: int = 1) -> None:
        for _ in range(max(1, count)):
            self._grid.pop(self._scroll_bottom)
            self._grid.insert(self._scroll_top, self._blank_row())
        self._touch_range(self._scroll_top, self._scroll_bottom)

    def _newline(self) -> None:
        if self.cursor_row == self._scroll_bottom:
            self._scroll_up()
        elif self.cursor_row < self.rows - 1:
            self.cursor_row += 1

    def _put(self, ch: str) -> None:
        width = 2 if is_wide(ch) else 1
        if self._wrap_pending or self.cursor_col + width > self.cols:
            if self._wrap_pending or self.cursor_col > 0:
                self.cursor_col = 0
                self._newline()
            self._wrap_pending = False
        row = self._grid[self.cursor_row]
        col = self.cursor_col
        # Writing over half of a wide glyph blanks its other half.
        if row[col][0] == "" and col > 0:
            row[col - 1] = self._blank()
        attrs = self._attrs | (WIDE if width == 2 else 0)
        row[col] = (ch, self._fg, self._bg, attrs)
        if width == 2 and col + 1 < self.cols:
            row[col + 1] = ("", self._fg, self._bg, 0)
        elif col + 1 < self.cols and row[col + 1][0] == "" and width == 1:
            row[col + 1] = self._blank()
        self._touch(self.cursor_row)
        if col + width >= self.cols:
            self._wrap_pending = True
            self.cursor_col = self.cols - 1
        else:
            self.cursor_col = col + width

    def _append_combining(self, ch: str) -> None:
        col = self.cursor_col - 1 if not self._wrap_pending else self.cursor_col
        row = self._grid[self.cursor_row]
        while col > 0 and row[col][0] == "":
            col -= 1
        if 0 <= col < self.cols and row[col][0] not in ("", " "):
            c, fg, bg, attrs = row[col]
            row[col] = (c + ch, fg, bg, attrs)
            self._touch(self.cursor_row)

    # ------------------------------------------------------------------ feed
    def feed(self, chunk: str) -> None:
        """Replay a raw PTY chunk; a parser error marks the mirror unreliable."""
        if not chunk:
            return
        try:
            self._feed(chunk)
        except Exception:  # noqa: BLE001 — a hostile stream must not take the relay down
            self.errors += 1
            self._pending = ""

    def _put_ascii(self, text: str) -> None:
        """Fast path for a run of printable ASCII (one column per char, no clusters)."""
        fg, bg, attrs = self._fg, self._bg, self._attrs
        cols = self.cols
        pos = 0
        n = len(text)
        while pos < n:
            if self._wrap_pending:
                self.cursor_col = 0
                self._newline()
                self._wrap_pending = False
            row = self._grid[self.cursor_row]
            col = self.cursor_col
            if col > 0 and row[col][0] == "":
                row[col - 1] = self._blank()
            take = min(n - pos, cols - col)
            for k in range(take):
                row[col + k] = (text[pos + k], fg, bg, attrs)
            end = col + take
            if end < cols and row[end][0] == "":
                row[end] = self._blank()
            self.dirty.add(self.cursor_row)
            pos += take
            if end >= cols:
                self._wrap_pending = True
                self.cursor_col = cols - 1
            else:
                self.cursor_col = end

    def _feed(self, chunk: str) -> None:
        data = self._pending + chunk
        self._pending = ""
        i, n = 0, len(data)
        while i < n:
            ch = data[i]
            if " " <= ch <= "~":
                m = _ASCII_RUN.match(data, i)
                assert m is not None
                self._put_ascii(m.group())
                i = m.end()
                continue
            if ch == "\x1b":
                consumed = self._escape(data, i)
                if consumed == 0:
                    self._pending = data[i:][:256]
                    return
                i += consumed
                continue
            i += 1
            if ch == "\n" or ch == "\x0b" or ch == "\x0c":
                self._wrap_pending = False
                self._newline()
            elif ch == "\r":
                self._wrap_pending = False
                self.cursor_col = 0
            elif ch == "\b":
                self._wrap_pending = False
                self.cursor_col = max(0, self.cursor_col - 1)
            elif ch == "\t":
                self._wrap_pending = False
                self.cursor_col = min(self.cols - 1, (self.cursor_col // 8 + 1) * 8)
            elif ch < " " or ch == "\x7f":
                continue
            elif (
                unicodedata.category(ch) in ("Mn", "Me", "Mc")
                or ch == "‍"
                or "︀" <= ch <= "️"
                or 0x1F3FB <= ord(ch) <= 0x1F3FF
            ):
                self._append_combining(ch)
            else:
                self._put(ch)

    def _escape(self, data: str, start: int) -> int:
        n = len(data)
        if start + 1 >= n:
            return 0
        kind = data[start + 1]
        if kind == "[":
            return self._csi(data, start)
        if kind in "]PX^_":
            # OSC / DCS / SOS / PM / APC: string ends at BEL or ST.
            j = start + 2
            while j < n:
                if data[j] == "\x07":
                    return j - start + 1
                if data[j] == "\x1b":
                    if j + 1 >= n:
                        return 0
                    return j - start + (2 if data[j + 1] == "\\" else 1)
                j += 1
            return 0
        if kind in "()#%*+":
            return 3 if start + 2 < n else 0
        if kind == "D":
            self._newline()
        elif kind == "M":
            if self.cursor_row == self._scroll_top:
                self._scroll_down()
            else:
                self.cursor_row = max(0, self.cursor_row - 1)
        elif kind == "E":
            self.cursor_col = 0
            self._newline()
        elif kind == "7":
            self._save_cursor()
        elif kind == "8":
            self._restore_cursor()
        elif kind == "c":
            self.reset()
        return 2

    def _save_cursor(self) -> None:
        self._saved_cursor = (self.cursor_row, self.cursor_col, self._fg, self._bg, self._attrs)

    def _restore_cursor(self) -> None:
        r, c, self._fg, self._bg, self._attrs = self._saved_cursor
        self.cursor_row = min(r, self.rows - 1)
        self.cursor_col = min(c, self.cols - 1)
        self._wrap_pending = False

    def _set_alt(self, on: bool) -> None:
        if on and self._main_saved is None:
            self._main_saved = self._grid
            self._grid = [self._blank_row() for _ in range(self.rows)]
        elif not on and self._main_saved is not None:
            saved = self._main_saved
            self._main_saved = None
            self._grid = [
                (row + [self._blank()] * self.cols)[: self.cols] for row in saved[: self.rows]
            ]
            while len(self._grid) < self.rows:
                self._grid.append(self._blank_row())
        self.dirty = set(range(self.rows))

    def _csi(self, data: str, start: int) -> int:
        n = len(data)
        j = start + 2
        params_start = j
        while j < n and "\x30" <= data[j] <= "\x3f":
            j += 1
        while j < n and "\x20" <= data[j] <= "\x2f":
            j += 1
        if j >= n:
            return 0 if n - start < 256 else n - start
        final = data[j]
        raw = data[params_start:j]
        length = j - start + 1
        if raw.startswith("?"):
            modes = raw[1:].split(";")
            if final in "hl":
                on = final == "h"
                if "25" in modes:
                    self.cursor_visible = on
                if any(m in ("1049", "1047", "47") for m in modes):
                    if on and "1049" in modes:
                        self._save_cursor()
                    self._set_alt(on)
                    if not on and "1049" in modes:
                        self._restore_cursor()
            return length
        if raw[:1] in (">", "=", "<"):
            return length
        if final == "m":
            self._sgr(raw)
            return length
        params = (
            [int(p) if p.isdigit() else 0 for p in raw.replace(":", ";").split(";")] if raw else []
        )

        def p(index: int, default: int = 1) -> int:
            if index < len(params) and params[index] > 0:
                return params[index]
            return default

        self._wrap_pending = False
        row_i = self.cursor_row
        if final in "Hf":
            self.cursor_row = _clamp(p(0) - 1, 0, self.rows - 1)
            self.cursor_col = _clamp(p(1) - 1, 0, self.cols - 1)
        elif final == "A":
            self.cursor_row = max(0, self.cursor_row - p(0))
        elif final in "Be":
            self.cursor_row = min(self.rows - 1, self.cursor_row + p(0))
        elif final in "Ca":
            self.cursor_col = min(self.cols - 1, self.cursor_col + p(0))
        elif final == "D":
            self.cursor_col = max(0, self.cursor_col - p(0))
        elif final in "G`":
            self.cursor_col = _clamp(p(0) - 1, 0, self.cols - 1)
        elif final == "d":
            self.cursor_row = _clamp(p(0) - 1, 0, self.rows - 1)
        elif final == "E":
            self.cursor_col = 0
            self.cursor_row = min(self.rows - 1, self.cursor_row + p(0))
        elif final == "F":
            self.cursor_col = 0
            self.cursor_row = max(0, self.cursor_row - p(0))
        elif final == "K":
            mode = params[0] if params else 0
            row = self._grid[row_i]
            lo, hi = (
                (self.cursor_col, self.cols)
                if mode == 0
                else (0, min(self.cursor_col + 1, self.cols))
                if mode == 1
                else (0, self.cols)
            )
            blank = self._blank()
            for c in range(lo, hi):
                row[c] = blank
            self._touch(row_i)
        elif final == "J":
            mode = params[0] if params else 0
            blank = self._blank()
            if mode == 0:
                for c in range(self.cursor_col, self.cols):
                    self._grid[row_i][c] = blank
                for r in range(row_i + 1, self.rows):
                    self._grid[r] = self._blank_row()
                self._touch_range(row_i, self.rows - 1)
            elif mode == 1:
                for c in range(0, min(self.cursor_col + 1, self.cols)):
                    self._grid[row_i][c] = blank
                for r in range(0, row_i):
                    self._grid[r] = self._blank_row()
                self._touch_range(0, row_i)
            else:
                self._grid = [self._blank_row() for _ in range(self.rows)]
                self.dirty = set(range(self.rows))
        elif final == "L":
            if self._scroll_top <= row_i <= self._scroll_bottom:
                for _ in range(p(0)):
                    self._grid.pop(self._scroll_bottom)
                    self._grid.insert(row_i, self._blank_row())
                self._touch_range(row_i, self._scroll_bottom)
        elif final == "M":
            if self._scroll_top <= row_i <= self._scroll_bottom:
                for _ in range(p(0)):
                    self._grid.pop(row_i)
                    self._grid.insert(self._scroll_bottom, self._blank_row())
                self._touch_range(row_i, self._scroll_bottom)
        elif final == "P":
            row = self._grid[row_i]
            for _ in range(min(p(0), self.cols - self.cursor_col)):
                del row[self.cursor_col]
                row.append(self._blank())
            self._touch(row_i)
        elif final == "@":
            row = self._grid[row_i]
            for _ in range(min(p(0), self.cols - self.cursor_col)):
                row.insert(self.cursor_col, self._blank())
                row.pop()
            self._touch(row_i)
        elif final == "X":
            row = self._grid[row_i]
            blank = self._blank()
            for c in range(self.cursor_col, min(self.cursor_col + p(0), self.cols)):
                row[c] = blank
            self._touch(row_i)
        elif final == "S":
            self._scroll_up(p(0))
        elif final == "T":
            self._scroll_down(p(0))
        elif final == "r":
            top = _clamp(p(0) - 1, 0, self.rows - 1)
            bottom = _clamp(p(1, self.rows) - 1, 0, self.rows - 1)
            if top < bottom:
                self._scroll_top, self._scroll_bottom = top, bottom
            else:
                self._scroll_top, self._scroll_bottom = 0, self.rows - 1
            self.cursor_row, self.cursor_col = 0, 0
        elif final == "s":
            self._save_cursor()
        elif final == "u":
            self._restore_cursor()
        return length

    def _sgr(self, raw: str) -> None:
        parts = raw.replace(":", ";").split(";") if raw else ["0"]
        values = [int(v) if v.isdigit() else 0 for v in parts]
        i = 0
        while i < len(values):
            v = values[i]
            i += 1
            if v == 0:
                self._fg, self._bg, self._attrs = DEFAULT_COLOUR, DEFAULT_COLOUR, 0
            elif v in _SGR_SET:
                self._attrs |= _SGR_SET[v]
            elif v in _SGR_CLEAR:
                self._attrs &= ~_SGR_CLEAR[v]
            elif 30 <= v <= 37:
                self._fg = palette(v - 30)
            elif 90 <= v <= 97:
                self._fg = palette(v - 90 + 8)
            elif v == 39:
                self._fg = DEFAULT_COLOUR
            elif 40 <= v <= 47:
                self._bg = palette(v - 40)
            elif 100 <= v <= 107:
                self._bg = palette(v - 100 + 8)
            elif v == 49:
                self._bg = DEFAULT_COLOUR
            elif v in (38, 48, 58):
                colour = None
                if i < len(values) and values[i] == 5 and i + 1 < len(values):
                    colour = palette(values[i + 1])
                    i += 2
                elif i < len(values) and values[i] == 2 and i + 3 < len(values):
                    colour = rgb(values[i + 1], values[i + 2], values[i + 3])
                    i += 4
                else:
                    break
                if v == 38:
                    self._fg = colour
                elif v == 48:
                    self._bg = colour

    def reset(self) -> None:
        self._fg = self._bg = DEFAULT_COLOUR
        self._attrs = 0
        self._grid = [self._blank_row() for _ in range(self.rows)]
        self._main_saved = None
        self.cursor_row = self.cursor_col = 0
        self.cursor_visible = True
        self._scroll_top, self._scroll_bottom = 0, self.rows - 1
        self._wrap_pending = False
        self._pending = ""
        self.dirty = set(range(self.rows))

    # ---------------------------------------------------------------- output
    @property
    def cut(self) -> bool:
        return self.cols > MAX_COLS or self.rows > MAX_ROWS

    @property
    def sent_cols(self) -> int:
        return min(self.cols, MAX_COLS)

    @property
    def sent_rows(self) -> int:
        return min(self.rows, MAX_ROWS)

    def cursor(self) -> list[int]:
        """``[row, col]`` inside the sent grid, or ``[-1, -1]`` when hidden or cut away."""
        if not self.cursor_visible:
            return [-1, -1]
        if self.cursor_row >= self.sent_rows or self.cursor_col >= self.sent_cols:
            return [-1, -1]
        return [self.cursor_row, self.cursor_col]

    def row_record(self, row: int) -> dict:
        return {"row": row, "runs": row_runs(self._grid[row], self.sent_cols)}

    def snapshot_rows(self) -> list[dict]:
        """Every non-empty row of the sent grid (snapshot rule of 5.4)."""
        out = []
        for r in range(self.sent_rows):
            record = self.row_record(r)
            if record["runs"]:
                out.append(record)
        return out

    def take_dirty(self) -> list[dict]:
        """Row records of the rows changed since the last call, then clear the set."""
        rows = sorted(r for r in self.dirty if r < self.sent_rows)
        self.dirty = set()
        return [self.row_record(r) for r in rows]

    def text_rows(self) -> list[str]:
        return ["".join(c[0] for c in row).rstrip() for row in self._grid]


def plain_cells(lines: list[str], cols: int) -> list[list[Cell]]:
    """Plain ``ScreenBuffer`` rows as default-coloured cells (the ``style: plain`` fallback)."""
    grid: list[list[Cell]] = []
    for line in lines:
        row: list[Cell] = []
        for ch in line[:cols]:
            row.append((ch, DEFAULT_COLOUR, DEFAULT_COLOUR, 0))
        grid.append(row)
    return grid
