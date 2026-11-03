#!/usr/bin/env python3
"""Reference codec for terminal screen cells of ``verse.bridge/1``.

Implements ``cells.bin/1`` and ``cells.json/1`` exactly as
``docs/verse/unreal/contracts/bridge-protocol.md`` section 5.4 freezes them.
It is the codec the golden vectors in ``unreal/Verse/Tests/Data/bridge/cells/``
were written with and the one ``scripts/unreal/fake_bridge.py`` sends binary
frames with. The backend codec (WP17, ``dodaios/verse_host/cells_codec.py``)
and the Unreal decoder (WP16) must reproduce the same bytes; this file is not
imported by the app.

Binary layout (little endian)::

    0  u8[2]  magic "VC"            14 u16 cols
    2  u8     version 1             16 u16 rows
    3  u8     kind 1 snap / 2 delta 18 i16 cursor row, i16 cursor col
    4  u16    ref                   22 u16 row record count
    6  u32    seq                   24 row records
    10 u32    base (0 on snapshot)

    row record: u16 row, u16 run_count, runs
    run:        u16 col, u16 cells, u32 fg, u32 bg, u16 attrs, u16 text_bytes, UTF-8 text
"""

from __future__ import annotations

import re
import struct
import unicodedata
from typing import Any

MAGIC = b"VC"
VERSION = 1
KIND_SNAPSHOT = 1
KIND_DELTA = 2
KINDS = {"snapshot": KIND_SNAPSHOT, "delta": KIND_DELTA}
KIND_NAMES = {v: k for k, v in KINDS.items()}

#: Attribute bit order of section 5.4.
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

MODE_DEFAULT = 0
MODE_PALETTE = 1
MODE_RGB = 2

MAX_COLS = 240
MAX_ROWS = 60

_HEADER = struct.Struct("<2sBBHIIHHhhH")
_ROW = struct.Struct("<HH")
_RUN = struct.Struct("<HHIIHH")
_HEX = re.compile(r"^#[0-9a-f]{6}$")

HEADER_SIZE = _HEADER.size  # 24


class CellsError(ValueError):
    """A frame that is not valid ``cells.bin/1`` or ``cells.json/1``."""


# ------------------------------------------------------------------ colours, attrs


def colour_to_u32(colour: Any) -> int:
    """JSON colour (``null``, ``{"i": n}``, ``"#rrggbb"``) to its u32 form."""
    if colour is None:
        return MODE_DEFAULT << 24
    if isinstance(colour, dict):
        index = colour.get("i")
        if (
            set(colour) != {"i"}
            or not isinstance(index, int)
            or isinstance(index, bool)
            or not 0 <= index <= 255
        ):
            raise CellsError(f"bad palette colour {colour!r}")
        return (MODE_PALETTE << 24) | index
    if isinstance(colour, str) and _HEX.match(colour):
        return (MODE_RGB << 24) | int(colour[1:], 16)
    raise CellsError(f"bad colour {colour!r}")


def colour_from_u32(value: int) -> Any:
    mode = value >> 24
    low = value & 0xFFFFFF
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


def attrs_to_u16(names: list[str]) -> int:
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
    """Split ``text`` into grapheme clusters.

    A simplified rule set (combining marks, zero-width joiner sequences,
    variation selectors, skin-tone modifiers and tag characters extend the
    previous cluster). It covers every string in the golden vectors; a
    terminal cell never holds more.
    """
    clusters: list[str] = []
    join_next = False
    for ch in text:
        if clusters and (join_next or _extends(ch)):
            clusters[-1] += ch
        else:
            clusters.append(ch)
        join_next = ord(ch) == 0x200D
    return clusters


def run_span(run: dict) -> int:
    """Columns a JSON run covers (wide glyphs cover two)."""
    width = 2 if "wide" in run.get("attrs", []) else 1
    return len(graphemes(run["text"])) * width


# ------------------------------------------------------------------ structure checks


def check_rows(cols: int, rows: int, rows_changed: list[dict]) -> None:
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
    """Decode a ``cells.bin/1`` frame.

    Returns ``{"kind", "ref", "seq", "base", "cols", "rows", "cursor",
    "rows_changed"}`` with runs in the JSON form (``col``, ``text``, ``fg``,
    ``bg``, ``attrs``). Raises :class:`CellsError` on anything malformed.
    """
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


def normalise_runs(rows_changed: list[dict]) -> list[dict]:
    """JSON rows with every optional run field spelled out, for comparisons."""
    return [
        {
            "row": r["row"],
            "runs": [
                {
                    "col": u["col"],
                    "text": u["text"],
                    "fg": u.get("fg"),
                    "bg": u.get("bg"),
                    "attrs": list(u.get("attrs", [])),
                }
                for u in r["runs"]
            ],
        }
        for r in rows_changed
    ]
