"""Terminal screen cells: ``cells.bin/1`` and ``cells.json/1`` (contract 5.4).

The backend codec. It produces byte for byte what the golden vectors in
``tests/unit/verse_host/fixtures/bridge/cells/vectors.json`` hold, and the
Unreal decoder (``VerseBridge``) reads the same bytes.

A row is sent as runs of cells sharing ``fg``, ``bg`` and ``attrs``. Colour
u32: high byte mode (0 default, 1 palette, 2 RGB). Attribute bits: bold, dim,
italic, underline, inverse, strikethrough, invisible, blink, wide.
"""

from __future__ import annotations

import re
import struct
import unicodedata
from collections.abc import Iterable, Sequence
from typing import Any

MAGIC = b"VC"
VERSION = 1
KIND_SNAPSHOT = 1
KIND_DELTA = 2
KINDS = {"snapshot": KIND_SNAPSHOT, "delta": KIND_DELTA}
KIND_NAMES = {v: k for k, v in KINDS.items()}

ATTRS = (
    "bold",
    "dim",
    "italic",
    "underline",
    "inverse",
    "strikethrough",
    "invisible",
    "blink",
    "wide",
)
ATTR_BITS = {name: 1 << i for i, name in enumerate(ATTRS)}
WIDE = ATTR_BITS["wide"]
#: Attributes that paint a blank cell, so a trailing blank carrying one is kept.
_VISIBLE_ON_BLANK = ATTR_BITS["inverse"] | ATTR_BITS["underline"] | ATTR_BITS["strikethrough"]

MODE_DEFAULT = 0
MODE_PALETTE = 1
MODE_RGB = 2
DEFAULT_COLOUR = 0

MAX_COLS = 240
MAX_ROWS = 60

_HEADER = struct.Struct("<2sBBHIIHHhhH")
_ROW = struct.Struct("<HH")
_RUN = struct.Struct("<HHIIHH")
_HEX = re.compile(r"^#[0-9a-f]{6}$")
HEADER_SIZE = _HEADER.size


class CellsError(ValueError):
    """A frame that is not valid ``cells.bin/1`` or ``cells.json/1``."""


# ------------------------------------------------------------------ colours, attrs


def palette(index: int) -> int:
    return (MODE_PALETTE << 24) | (index & 0xFF)


def rgb(r: int, g: int, b: int) -> int:
    return (MODE_RGB << 24) | ((r & 0xFF) << 16) | ((g & 0xFF) << 8) | (b & 0xFF)


def colour_to_u32(colour: Any) -> int:
    if colour is None:
        return DEFAULT_COLOUR
    if isinstance(colour, dict):
        index = colour.get("i")
        if (
            set(colour) != {"i"}
            or not isinstance(index, int)
            or isinstance(index, bool)
            or not 0 <= index <= 255
        ):
            raise CellsError(f"bad palette colour {colour!r}")
        return palette(index)
    if isinstance(colour, str) and _HEX.match(colour):
        return (MODE_RGB << 24) | int(colour[1:], 16)
    raise CellsError(f"bad colour {colour!r}")


def colour_from_u32(value: int) -> Any:
    mode, low = value >> 24, value & 0xFFFFFF
    if mode == MODE_DEFAULT:
        if low:
            raise CellsError(f"default colour with payload {value:#010x}")
        return None
    if mode == MODE_PALETTE:
        if low > 0xFF:
            raise CellsError(f"palette colour out of range {value:#010x}")
        return {"i": low}
    if mode == MODE_RGB:
        return f"#{low:06x}"
    raise CellsError(f"unknown colour mode {mode}")


def attrs_to_u16(names: Iterable[str]) -> int:
    bits = 0
    for name in names:
        if name not in ATTR_BITS:
            raise CellsError(f"unknown attribute {name!r}")
        bits |= ATTR_BITS[name]
    return bits


def attrs_from_u16(bits: int) -> list[str]:
    if bits >> len(ATTRS):
        raise CellsError(f"unknown attribute bits {bits:#06x}")
    return [name for name in ATTRS if bits & ATTR_BITS[name]]


# ------------------------------------------------------------------ graphemes


def _extends(ch: str) -> bool:
    cp = ord(ch)
    return (
        unicodedata.category(ch) in {"Mn", "Me", "Mc"}
        or cp == 0x200D
        or 0xFE00 <= cp <= 0xFE0F
        or 0x1F3FB <= cp <= 0x1F3FF
        or 0xE0020 <= cp <= 0xE007F
    )


def graphemes(text: str) -> list[str]:
    """Grapheme clusters: combining marks, ZWJ sequences, variation selectors,
    skin-tone modifiers and tag characters extend the previous cluster."""
    clusters: list[str] = []
    join_next = False
    for ch in text:
        if clusters and (join_next or _extends(ch)):
            clusters[-1] += ch
        else:
            clusters.append(ch)
        join_next = ord(ch) == 0x200D
    return clusters


def is_wide(cluster: str) -> bool:
    """East Asian wide or fullwidth glyphs and emoji presentation take two columns."""
    if not cluster:
        return False
    first = cluster[0]
    if unicodedata.east_asian_width(first) in ("W", "F"):
        return True
    return "️" in cluster and ord(first) > 0x2000


def run_span(run: dict) -> int:
    width = 2 if "wide" in run.get("attrs", []) else 1
    return len(graphemes(run["text"])) * width


def check_rows(cols: int, rows: int, rows_changed: Sequence[dict]) -> None:
    """Rows inside the grid, each row once, runs sorted, inside the row, not overlapping."""
    if not 1 <= cols <= MAX_COLS or not 1 <= rows <= MAX_ROWS:
        raise CellsError(f"grid {cols}x{rows} outside 1..{MAX_COLS} x 1..{MAX_ROWS}")
    seen: set[int] = set()
    for record in rows_changed:
        row = record["row"]
        if not 0 <= row < rows:
            raise CellsError(f"row {row} outside 0..{rows - 1}")
        if row in seen:
            raise CellsError(f"row {row} sent twice")
        seen.add(row)
        end = 0
        for run in record["runs"]:
            if not run["text"]:
                raise CellsError(f"row {row}: empty run at col {run['col']}")
            if run["col"] < end:
                raise CellsError(f"row {row}: run at col {run['col']} overlaps or is out of order")
            end = run["col"] + run_span(run)
            if end > cols:
                raise CellsError(
                    f"row {row}: run at col {run['col']} ends at {end}, past {cols} cols"
                )


# ------------------------------------------------------------------ cells -> runs

#: One cell of a styled grid: ``(char, fg, bg, attrs)`` with u32 colours and
#: u16 attrs. The second column of a wide glyph holds ``""``.
Cell = tuple[str, int, int, int]


def row_runs(cells: Sequence[Cell], cols: int | None = None) -> list[dict]:
    """One row of cells as JSON runs: equal style merged, trailing blanks dropped.

    A trailing blank (a space on the default background with no attribute
    that paints a blank) is not sent; Verse clears to the default background.
    A wide glyph covers two columns and its second column is skipped.
    """
    limit = len(cells) if cols is None else min(cols, len(cells))
    end = limit
    while end > 0:
        ch, _fg, bg, attrs = cells[end - 1]
        if ch in (" ", "") and bg == DEFAULT_COLOUR and not attrs & _VISIBLE_ON_BLANK:
            end -= 1
            continue
        break
    runs: list[dict] = []
    cur: dict | None = None
    cur_key: tuple[int, int, int] | None = None
    cur_end = -1
    col = 0
    while col < end:
        ch, fg, bg, attrs = cells[col]
        if ch == "":
            col += 1
            continue
        width = 2 if attrs & WIDE else 1
        if col + width > limit:
            # A wide glyph cut by the right edge becomes a blank.
            ch, attrs, width = " ", attrs & ~WIDE, 1
        key = (fg, bg, attrs)
        if cur is not None and key == cur_key and cur_end == col:
            cur["text"] += ch
        else:
            cur = {
                "col": col,
                "text": ch,
                "fg": colour_from_u32(fg),
                "bg": colour_from_u32(bg),
                "attrs": attrs_from_u16(attrs),
            }
            cur_key = key
            runs.append(cur)
        cur_end = col + width
        col += width
    return runs


# ------------------------------------------------------------------ encode / decode


def encode(data: dict, *, ref: int, seq: int, base: int | None) -> bytes:
    """Encode the ``data`` of a ``screens.frame`` (``cells.json/1``) as ``cells.bin/1``."""
    kind = KINDS.get(data["kind"])
    if kind is None:
        raise CellsError(f"bad kind {data['kind']!r}")
    if kind == KIND_SNAPSHOT:
        base = 0
    elif base is None:
        raise CellsError("a delta needs a base seq")
    cols, rows = data["cols"], data["rows"]
    check_rows(cols, rows, data["rows_changed"])
    cur_row, cur_col = data["cursor"]
    parts = [
        _HEADER.pack(
            MAGIC,
            VERSION,
            kind,
            ref,
            seq,
            base,
            cols,
            rows,
            cur_row,
            cur_col,
            len(data["rows_changed"]),
        )
    ]
    for record in data["rows_changed"]:
        parts.append(_ROW.pack(record["row"], len(record["runs"])))
        for run in record["runs"]:
            text = run["text"].encode("utf-8")
            parts.append(
                _RUN.pack(
                    run["col"],
                    len(graphemes(run["text"])),
                    colour_to_u32(run.get("fg")),
                    colour_to_u32(run.get("bg")),
                    attrs_to_u16(run.get("attrs", [])),
                    len(text),
                )
            )
            parts.append(text)
    return b"".join(parts)


def decode(blob: bytes) -> dict:
    """Decode a ``cells.bin/1`` frame; :class:`CellsError` on anything malformed."""
    if len(blob) < HEADER_SIZE:
        raise CellsError(
            f"frame of {len(blob)} bytes is shorter than the {HEADER_SIZE}-byte header"
        )
    magic, version, kind, ref, seq, base, cols, rows, cur_row, cur_col, count = _HEADER.unpack_from(
        blob, 0
    )
    if magic != MAGIC:
        raise CellsError(f"bad magic {magic!r}")
    if version != VERSION:
        raise CellsError(f"unsupported version {version}")
    if kind not in KIND_NAMES:
        raise CellsError(f"bad kind {kind}")
    if kind == KIND_SNAPSHOT and base != 0:
        raise CellsError("a snapshot carries base 0")
    if (cur_row, cur_col) != (-1, -1) and not (0 <= cur_row < rows and 0 <= cur_col < cols):
        raise CellsError(f"cursor {cur_row},{cur_col} outside the grid")
    offset = HEADER_SIZE
    records: list[dict] = []
    for _ in range(count):
        if offset + _ROW.size > len(blob):
            raise CellsError("truncated row record")
        row, run_count = _ROW.unpack_from(blob, offset)
        offset += _ROW.size
        runs: list[dict] = []
        for _ in range(run_count):
            if offset + _RUN.size > len(blob):
                raise CellsError("truncated run")
            col, cells, fg, bg, attrs, text_bytes = _RUN.unpack_from(blob, offset)
            offset += _RUN.size
            if offset + text_bytes > len(blob):
                raise CellsError("run text runs past the end of the frame")
            try:
                text = blob[offset : offset + text_bytes].decode("utf-8")
            except UnicodeDecodeError as exc:
                raise CellsError(f"run text is not UTF-8: {exc}") from exc
            offset += text_bytes
            held = len(graphemes(text))
            if held != cells:
                raise CellsError(f"run at row {row} col {col} says {cells} cells but holds {held}")
            runs.append(
                {
                    "col": col,
                    "text": text,
                    "fg": colour_from_u32(fg),
                    "bg": colour_from_u32(bg),
                    "attrs": attrs_from_u16(attrs),
                }
            )
        records.append({"row": row, "runs": runs})
    if offset != len(blob):
        raise CellsError(f"{len(blob) - offset} trailing bytes")
    check_rows(cols, rows, records)
    return {
        "kind": KIND_NAMES[kind],
        "ref": ref,
        "seq": seq,
        "base": base if kind == KIND_DELTA else None,
        "cols": cols,
        "rows": rows,
        "cursor": [cur_row, cur_col],
        "rows_changed": records,
    }
