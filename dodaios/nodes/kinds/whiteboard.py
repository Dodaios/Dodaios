"""The ``whiteboard`` node: a board of notes, shapes and connections.

A person asks for "a board with our launch ideas" or "the signup flow as a
diagram". The model writes WHAT is on the board (notes, shapes, which group a
note belongs to, what points at what); it does not write where things sit.

Why the layout is computed HERE and not by the model: a model that emits
coordinates produces boards that overlap, drift off a grid and have to be
rewritten in full whenever one note is added. So the default layout is
``"auto"``: notes that share a ``group`` are gathered into one titled frame
and flow in a grid, linked shapes outside a group are layered left to right
along their links, and the frames are packed into rows. The result depends on
the spec alone, so the same spec always gives the same board, and an edit
re-flows it. Coordinates are honoured when the model sends them (the person
asked for a specific arrangement); they are never written back into the spec.

The page is one self-contained document: an infinite canvas that pans and
zooms (pointer, touch, wheel, keys, four small buttons), with every item as a
list entry in reading order so a screen reader reads the board as a list. All
text reaches the page through :mod:`dodaios.nodes.shell`; every number in a
``style`` or an SVG path is formatted here from a float, never copied from
the spec.
"""

from __future__ import annotations

import base64
import binascii
import json
import math
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Final

from dodaios.nodes import shell
from dodaios.nodes.types import NodeError

# --- the grammar -----------------------------------------------------------------

MAX_ITEMS: Final[int] = 300
MAX_LINKS: Final[int] = 300
MAX_TEXT_CHARS: Final[int] = 400
MAX_TITLE_CHARS: Final[int] = 80
MAX_GROUP_CHARS: Final[int] = 60
MAX_LABEL_CHARS: Final[int] = 60
MAX_ID_CHARS: Final[int] = 40
PREVIEW_NOTES: Final[int] = 4
PREVIEW_CHARS: Final[int] = 40

ITEM_TYPES: Final[tuple[str, ...]] = ("note", "text", "shape", "frame", "image")
COLORS: Final[tuple[str, ...]] = ("yellow", "pink", "blue", "green", "violet", "orange", "gray")
SHAPES: Final[tuple[str, ...]] = ("rect", "ellipse", "diamond", "pill")
LINK_STYLES: Final[tuple[str, ...]] = ("arrow", "line", "dashed")
LAYOUTS: Final[tuple[str, ...]] = ("auto", "free")

_COLOR_ALIASES: Final[dict[str, str]] = {
    "amber": "yellow",
    "purple": "violet",
    "grey": "gray",
    "red": "pink",
}
_SHAPE_ALIASES: Final[dict[str, str]] = {
    "rectangle": "rect",
    "box": "rect",
    "circle": "ellipse",
    "oval": "ellipse",
    "rhombus": "diamond",
    "decision": "diamond",
    "capsule": "pill",
    "rounded": "pill",
}
_DEFAULT_COLOR: Final[dict[str, str]] = {
    "note": "yellow",
    "text": "gray",
    "shape": "blue",
    "frame": "gray",
    "image": "gray",
}

# Board units are CSS pixels at 100 % zoom.
_COORD_LIMIT: Final[float] = 20_000.0
_SIZE_MIN: Final[float] = 24.0
_SIZE_MAX: Final[float] = 2_400.0

_NEED_ITEMS: Final[str] = (
    'A whiteboard needs "items": a list of 1 to 300 objects such as '
    '{"id": "a", "text": "One idea", "group": "Ideas"}, plus optional "links" '
    '([{"from": "a", "to": "b"}]).'
)

EXAMPLE: Final[dict[str, Any]] = {
    "layout": "auto",
    "items": [
        {"id": "a", "text": "Interview five customers", "group": "Now"},
        {"id": "b", "text": "Draft the pricing page", "group": "Now", "color": "blue"},
        {"id": "c", "text": "Open the beta", "group": "Next", "color": "green"},
    ],
    "links": [{"from": "b", "to": "c", "label": "unblocks"}],
}

GUIDE: Final[str] = (
    "Whiteboard spec: a board of notes, shapes and connections.\n"
    '{"items": [item, ...], "links": [link, ...], "layout": "auto" | "free"}\n'
    'item: {"id", "type": "note" (default) | "text" | "shape" | "frame" | "image", '
    '"text" (<= 400 chars; **bold**, *italic*, `code`, [label](https://...)), '
    '"title" (frames), "color": yellow | pink | blue | green | violet | orange | gray, '
    '"shape": rect | ellipse | diamond | pill (type shape), '
    '"image": a data:image/...;base64 URI (type image; "text" is its caption), '
    '"group", "x", "y", "w", "h"}\n'
    'link: {"from": id, "to": id, "label" (optional), '
    '"style": "arrow" (default) | "line" | "dashed"}\n'
    "Rules:\n"
    '- 1 to 300 items, at most 300 links. Give every item you link a short unique "id"; '
    "a link to an unknown id is dropped.\n"
    '- Prefer "layout": "auto" and send NO coordinates: the board is laid out for you, '
    'and it re-flows when you add or remove an item. Items that share a "group" are '
    "gathered into one titled frame per group (the group name is the title), in the "
    "order the groups first appear, and flow in a tidy grid inside it.\n"
    "- Ungrouped items joined by links are laid out as a flow from left to right "
    "along the arrows, so link them in reading direction (a process, a small map).\n"
    '- An ungrouped "text" item at the very start is the heading of the board.\n'
    '- A "frame" item is needed only to give a group\'s frame a color or a longer '
    'title: set "group" on its members to the frame\'s "id".\n'
    '- Give "x", "y" (and "w", "h"; board units are px at 100 % zoom) only when the '
    'person asks for a specific arrangement. An item with "x" and "y" sits exactly '
    "there; sizes are ignored for items without coordinates.\n"
    "- One thought per note, a few words each. Notes for ideas and tasks, shapes for "
    "the steps of a process (diamond = decision, pill = start or end), text for "
    "labels. A color means one thing across the board (a kind, an owner, a state); "
    "do not use it to decorate.\n"
    "Example:\n" + json.dumps(EXAMPLE, ensure_ascii=False, separators=(", ", ": "))
)


# --- normalize -------------------------------------------------------------------


def _scalar(value: Any) -> str:
    """A string or a number from a spec as text; nothing for any other value."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return ""
    return str(value)


def _line(value: Any, limit: int) -> str:
    """One clipped line with no space left at the cut, so a second pass changes nothing."""
    return shell.clean(_scalar(value), limit).strip()


def _id_text(value: Any) -> str:
    """An id from a spec: a short string or a number, else nothing."""
    return _line(value, MAX_ID_CHARS)


def _tidy(value: float) -> int | float:
    """A coordinate as the spec keeps it: two decimals, an int when it is whole."""
    rounded = round(value, 2)
    return int(rounded) if rounded == int(rounded) else rounded


def _named(value: Any, allowed: tuple[str, ...], aliases: dict[str, str]) -> str:
    name = _scalar(value).strip().lower()
    name = aliases.get(name, name)
    return name if name in allowed else ""


def _item(raw: Any) -> dict[str, Any] | None:
    """One item without its id (ids are settled across the whole list)."""
    if isinstance(raw, str):
        raw = {"text": raw}
    if not isinstance(raw, dict):
        return None
    shape = _named(raw.get("shape"), SHAPES, _SHAPE_ALIASES)
    image = shell.safe_image(_scalar(raw.get("image")))
    kind = _named(raw.get("type"), ITEM_TYPES, {})
    if not kind:
        kind = "shape" if shape else "image" if image else "note"
    item: dict[str, Any] = {"type": kind}
    text = shell.clean_block(_scalar(raw.get("text")), MAX_TEXT_CHARS).strip()
    title = _line(raw.get("title"), MAX_TITLE_CHARS)
    if kind == "frame":
        title = title or _line(text, MAX_TITLE_CHARS)
        if title:
            item["title"] = title
    else:
        text = text or title
        if text:
            item["text"] = text
    color = _named(raw.get("color"), COLORS, _COLOR_ALIASES)
    if color:
        item["color"] = color
    if kind == "shape" and shape:
        item["shape"] = shape
    if kind == "image" and image:
        item["image"] = image
    group = _line(raw.get("group"), MAX_GROUP_CHARS)
    if kind != "frame" and group:
        item["group"] = group
    x, y = shell.number(raw.get("x")), shell.number(raw.get("y"))
    if x is not None and y is not None:
        item["x"] = _tidy(max(-_COORD_LIMIT, min(_COORD_LIMIT, x)))
        item["y"] = _tidy(max(-_COORD_LIMIT, min(_COORD_LIMIT, y)))
    for key in ("w", "h"):
        size = shell.number(raw.get(key))
        if size is not None:
            item[key] = _tidy(max(_SIZE_MIN, min(_SIZE_MAX, size)))
    return item


def _assign_ids(raws: list[Any], items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Give every item a unique id; the first holder of an id keeps it.

    A missing id becomes ``i1``, ``i2``, …; a repeated one gets ``-2``, ``-3``, …
    appended. Ids the spec states are reserved before any is generated, so a
    generated id never takes one that an item further down carries.
    """
    wanted = [_id_text(raw.get("id")) if isinstance(raw, dict) else "" for raw in raws]
    taken: set[str] = set()
    final: list[str] = [""] * len(items)
    for index, name in enumerate(wanted):
        if name and name not in taken:
            taken.add(name)
            final[index] = name
    counter = 0
    for index, name in enumerate(wanted):
        if final[index]:
            continue
        if name:
            stem, suffix = name[: MAX_ID_CHARS - 4].strip(), 2
            while f"{stem}-{suffix}" in taken:
                suffix += 1
            fresh = f"{stem}-{suffix}"
        else:
            counter += 1
            while f"i{counter}" in taken:
                counter += 1
            fresh = f"i{counter}"
        taken.add(fresh)
        final[index] = fresh
    return [{"id": final[index], **item} for index, item in enumerate(items)]


def _links(raw: Any, known: set[str]) -> list[dict[str, Any]]:
    links: list[dict[str, Any]] = []
    for entry in shell.as_list(raw, MAX_LINKS * 8):
        if not isinstance(entry, dict):
            continue
        start, end = _id_text(entry.get("from")), _id_text(entry.get("to"))
        if start not in known or end not in known or start == end:
            continue
        link: dict[str, Any] = {"from": start, "to": end}
        label = _line(entry.get("label"), MAX_LABEL_CHARS)
        if label:
            link["label"] = label
        style = _named(entry.get("style"), LINK_STYLES, {})
        if style:
            link["style"] = style
        links.append(link)
        if len(links) == MAX_LINKS:
            break
    return links


def normalize(spec: Any) -> dict[str, Any]:
    """The spec, validated and bounded; raises ``NodeError`` when it holds no item."""
    if not isinstance(spec, dict) or not isinstance(spec.get("items"), (list, tuple)):
        raise NodeError(_NEED_ITEMS)
    raws: list[Any] = []
    items: list[dict[str, Any]] = []
    for raw in spec["items"]:
        item = _item(raw)
        if item is None:
            continue
        raws.append(raw)
        items.append(item)
        if len(items) == MAX_ITEMS:
            break
    if not items:
        raise NodeError(_NEED_ITEMS)
    items = _assign_ids(raws, items)
    return {
        "items": items,
        "links": _links(spec.get("links"), {item["id"] for item in items}),
        "layout": shell.pick(_scalar(spec.get("layout")), LAYOUTS, "auto"),
    }


def _usable(spec: Any) -> dict[str, Any]:
    """The normalized spec, or an empty board for a spec that cannot be one."""
    try:
        return normalize(spec)
    except NodeError:  # a stored node must still open: an empty board, not a crash
        return {"items": [], "links": [], "layout": "auto"}


# --- text measures ---------------------------------------------------------------

_MARK_LINK_RE: Final = re.compile(r"\[([^\]\n]+)\]\(([^)\s]+)\)")


def _plain(value: Any) -> str:
    """Text without its inline marks, as a reader sees it."""
    text = _MARK_LINK_RE.sub(r"\1", str(value or ""))
    return text.replace("**", "").replace("`", "").replace("*", "")


def _units(text: str) -> int:
    """The width of ``text`` in Latin characters (a wide CJK glyph counts two)."""
    return sum(2 if unicodedata.east_asian_width(char) in "WF" else 1 for char in text)


def _line_count(text: str, per_line: float) -> int:
    """How many lines ``text`` takes when a line holds ``per_line`` characters."""
    room = max(4, int(per_line))
    return sum(max(1, math.ceil(_units(part) / room)) for part in text.split("\n"))


def _image_ratio(src: str) -> float:
    """Width over height of an embedded picture; 4:3 when it cannot be read.

    Read from the file header, so a picture gets a box of its own proportions
    instead of being letterboxed into a fixed one.
    """
    fallback = 4 / 3
    payload = "".join(src.partition(",")[2].split())[:87_384]
    try:
        data = base64.b64decode(payload[: len(payload) // 4 * 4])
    except (binascii.Error, ValueError):  # not a readable picture: keep the default box
        return fallback
    width = height = 0
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        width, height = int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    elif data[:6] in (b"GIF87a", b"GIF89a") and len(data) >= 10:
        width = int.from_bytes(data[6:8], "little")
        height = int.from_bytes(data[8:10], "little")
    elif data[:2] == b"\xff\xd8":
        at = 2
        while at + 9 <= len(data) and data[at] == 0xFF:
            marker = data[at + 1]
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                height = int.from_bytes(data[at + 5 : at + 7], "big")
                width = int.from_bytes(data[at + 7 : at + 9], "big")
                break
            at += 2 + int.from_bytes(data[at + 2 : at + 4], "big")
    elif data[:4] == b"RIFF" and data[8:12] == b"WEBP" and len(data) >= 30:
        chunk = data[12:16]
        if chunk == b"VP8X":
            width = 1 + int.from_bytes(data[24:27], "little")
            height = 1 + int.from_bytes(data[27:30], "little")
        elif chunk == b"VP8 ":
            width = int.from_bytes(data[26:28], "little") & 0x3FFF
            height = int.from_bytes(data[28:30], "little") & 0x3FFF
        elif chunk == b"VP8L":
            bits = int.from_bytes(data[21:25], "little")
            width, height = (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    if width <= 0 or height <= 0:
        return fallback
    return max(0.4, min(3.0, width / height))


# --- sizes -----------------------------------------------------------------------

_NOTE_W: Final[float] = 200.0
_NOTE_H: Final[float] = 160.0  # a note that carries its own coordinates
_NOTE_H_AUTO: Final[float] = 120.0  # a note in a grid: lower, so a column stays compact
_NOTE_PAD: Final[float] = 14.0
_LINE: Final[float] = 20.0  # line height of 14 px text
_CHAR: Final[float] = 8.2  # px one character takes at 14 px, wrapping losses included
_SHAPE_SIZE: Final[tuple[float, float]] = (180.0, 96.0)
_DIAMOND_SIZE: Final[tuple[float, float]] = (200.0, 124.0)
# The share of a shape's box its text can use, per form.
_SHAPE_ROOM: Final[dict[str, float]] = {"rect": 1.0, "pill": 0.88, "ellipse": 0.74, "diamond": 0.54}
_FRAME_SIZE: Final[tuple[float, float]] = (480.0, 320.0)
_EMPTY_FRAME_SIZE: Final[tuple[float, float]] = (320.0, 200.0)
_IMAGE_W: Final[float] = 240.0
_BIG_TEXT_UNITS: Final[int] = 36
_BIG_CHAR: Final[float] = 12.6
_TEXT_MAX_W: Final[float] = 360.0


def _is_big(text: str) -> bool:
    """A short one-line label is set larger: it is a heading on the board."""
    return "\n" not in text and 0 < _units(text) <= _BIG_TEXT_UNITS


def _size(item: dict[str, Any], *, placed: bool) -> tuple[float, float]:
    """Width and height of ``item``; its own ``w``/``h`` count only when it is placed."""
    given_w = float(item["w"]) if placed and "w" in item else None
    given_h = float(item["h"]) if placed and "h" in item else None
    kind = item["type"]
    text = _plain(item.get("text", ""))
    if kind == "frame":
        return given_w or _FRAME_SIZE[0], given_h or _FRAME_SIZE[1]
    if kind == "note":
        width = given_w or _NOTE_W
        lines = _line_count(text, (width - 2 * _NOTE_PAD - 2) / _CHAR)
        need = 2 * _NOTE_PAD + 2 + lines * _LINE
        return width, given_h or max(_NOTE_H if placed else _NOTE_H_AUTO, need)
    if kind == "shape":
        form = item.get("shape", "rect")
        room = _SHAPE_ROOM[form]
        base_w, base_h = _DIAMOND_SIZE if form == "diamond" else _SHAPE_SIZE
        widths = (given_w,) if given_w else (base_w, 240.0, 300.0)
        width, lines = base_w, 1
        for width in widths:
            lines = _line_count(text, (width - 32) * room / _CHAR)
            if lines <= 3:
                break
        need = (lines * _LINE + 24) / room
        return width, given_h or max(base_h, math.ceil(need / 4) * 4)
    if kind == "image":
        width = given_w or _IMAGE_W
        caption = 8 + _line_count(text, width / 7.0) * 16 if text else 0
        if given_h:
            return width, given_h
        return width, round(width / _image_ratio(item.get("image", ""))) + caption
    # text
    if _is_big(text):
        natural = _units(text) * _BIG_CHAR + 8
        width = given_w or max(40.0, min(560.0, natural))
        return width, given_h or _line_count(text, width / _BIG_CHAR) * 28.0
    longest = max((_units(part) for part in text.split("\n")), default=0)
    width = given_w or max(40.0, min(_TEXT_MAX_W, longest * _CHAR + 4))
    return width, given_h or _line_count(text, width / _CHAR) * 22.0


# --- layout ----------------------------------------------------------------------

_GAP: Final[float] = 16.0  # between notes in a grid
_FRAME_PAD: Final[float] = 20.0
_TITLE_ROOM: Final[float] = 30.0  # a frame's title sits above its top-left edge
_BLOCK_GAP: Final[float] = 48.0
_ROW_GAP: Final[float] = 56.0
_LAYER_GAP: Final[float] = 88.0
_LAYER_GAP_LABELED: Final[float] = 128.0
_FLOW_GAP: Final[float] = 32.0
_HEADING_GAP: Final[float] = 40.0
_SHEET: Final[tuple[float, float]] = (1440.0, 860.0)  # the window a board is packed for
#: A board that fits the window at this zoom is readable; a wider wrap is not worth more rows.
_READABLE_ZOOM: Final[float] = 0.66


@dataclass
class _Placed:
    """One thing on the board with its rectangle, in board units."""

    key: str
    item: dict[str, Any]
    x: float
    y: float
    w: float
    h: float

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2


@dataclass
class _Block:
    """Items that are laid out together and then moved as one."""

    order: int
    w: float
    h: float
    parts: list[_Placed] = field(default_factory=list)
    frame: _Placed | None = None
    top: float = 0.0
    x: float = 0.0
    y: float = 0.0

    def move(self, dx: float, dy: float) -> None:
        for part in self.parts:
            part.x += dx
            part.y += dy


def _has_place(item: dict[str, Any]) -> bool:
    return "x" in item and "y" in item


def _frame_columns(most: int) -> int:
    """How many notes sit side by side in the frames of a board, by its fullest frame.

    One number for the whole board, so its frames are equally wide and read
    as columns. Zero when no frame holds more than three: each is one row.
    """
    if most <= 3:
        return 0
    return 2 if most <= 8 else 3


def _loose_columns(count: int) -> int:
    if count <= 3:
        return max(1, count)
    return min(6, math.ceil(math.sqrt(count)))


def _grid(members: list[dict[str, Any]], columns: int) -> tuple[list[_Placed], float, float]:
    """``members`` in a grid from (0, 0): even gaps, notes of one row equally tall."""
    sizes = [_size(item, placed=False) for item in members]
    rows = [
        list(range(start, min(start + columns, len(members))))
        for start in range(0, len(members), columns)
    ]
    col_w = [
        max((sizes[row[col]][0] for row in rows if col < len(row)), default=0.0)
        for col in range(columns)
    ]
    placed: list[_Placed] = []
    top = 0.0
    for row in rows:
        row_h = max(sizes[index][1] for index in row)
        left = 0.0
        for col, index in enumerate(row):
            item = members[index]
            width, height = sizes[index]
            if item["type"] == "note":
                placed.append(_Placed(item["id"], item, left, top, width, row_h))
            elif item["type"] == "text":
                placed.append(_Placed(item["id"], item, left, top, width, height))
            else:
                dx, dy = (col_w[col] - width) / 2, (row_h - height) / 2
                placed.append(_Placed(item["id"], item, left + dx, top + dy, width, height))
            left += col_w[col] + _GAP
        top += row_h + _GAP
    used = [width for width in col_w if width]
    return placed, sum(used) + _GAP * max(0, len(used) - 1), max(0.0, top - _GAP)


def _frame_block(
    order: int,
    key: str,
    frame: dict[str, Any],
    members: list[dict[str, Any]],
    *,
    columns: int,
    pinned: bool,
) -> _Block:
    """A frame around its members' grid; a pinned frame keeps its own position."""
    inner, inner_w, inner_h = _grid(members, columns or max(1, len(members)))
    if members:
        width, height = inner_w + 2 * _FRAME_PAD, inner_h + 2 * _FRAME_PAD
    else:
        width, height = _EMPTY_FRAME_SIZE
    if pinned:
        own_w, own_h = _size(frame, placed=True)
        width = max(width, own_w) if "w" in frame else width
        height = max(height, own_h) if "h" in frame else height
    box = _Placed(key, frame, 0.0, 0.0, width, height)
    for part in inner:
        part.x += _FRAME_PAD
        part.y += _FRAME_PAD
    top = _TITLE_ROOM if frame.get("title") else 0.0
    block = _Block(order=order, w=width, h=height, parts=[box, *inner], frame=box, top=top)
    if pinned:
        block.move(float(frame["x"]), float(frame["y"]))
    return block


def _layers(ids: list[str], edges: list[tuple[str, str]]) -> dict[str, int]:
    """Longest-path layering: every link points to a later layer where it can.

    The links are taken in the order the spec states them, and one that would
    close a cycle with the links before it is left out of the layering (it is
    still drawn). So a flow reads in the direction it was written, and the
    loop back to an earlier step does not turn it around.
    """
    after: dict[str, list[str]] = {name: [] for name in ids}
    forward: list[tuple[str, str]] = []
    for start, end in edges:
        seen = {end}
        trail = [end]
        while trail and start not in seen:
            for target in after[trail.pop()]:
                if target not in seen:
                    seen.add(target)
                    trail.append(target)
        if start in seen:
            continue  # closes a cycle
        after[start].append(end)
        forward.append((start, end))
    before: dict[str, list[str]] = {name: [] for name in ids}
    ahead: dict[str, list[str]] = {name: [] for name in ids}
    for start, end in forward:
        before[end].append(start)
        ahead[start].append(end)
    waiting = {name: len(before[name]) for name in ids}
    ready = [name for name in ids if not waiting[name]]
    layer: dict[str, int] = {name: 0 for name in ids}
    while ready:
        name = ready.pop(0)
        for target in ahead[name]:
            layer[target] = max(layer[target], layer[name] + 1)
            waiting[target] -= 1
            if not waiting[target]:
                ready.append(target)
    # A source that only feeds a late step sits right before that step.
    for name in ids:
        if not before[name] and ahead[name]:
            layer[name] = min(layer[target] for target in ahead[name]) - 1
    return layer


def _flow_block(
    order: int, members: list[dict[str, Any]], edges: list[tuple[str, str]], *, labeled: bool
) -> _Block:
    """Linked items in layers from left to right, each centred on what feeds it."""
    ids = [item["id"] for item in members]
    layer = _layers(ids, edges)
    sizes = {item["id"]: _size(item, placed=False) for item in members}
    feeds: dict[str, list[str]] = {name: [] for name in ids}
    for start, end in edges:
        if layer[start] < layer[end]:
            feeds[end].append(start)
    columns: dict[int, list[dict[str, Any]]] = {}
    for item in members:
        columns.setdefault(layer[item["id"]], []).append(item)
    gap = _LAYER_GAP_LABELED if labeled else _LAYER_GAP
    placed: dict[str, _Placed] = {}
    left = 0.0
    for number in sorted(columns):
        column = columns[number]
        col_w = max(sizes[item["id"]][0] for item in column)
        wish: dict[str, float | None] = {}
        for item in column:
            sources = [placed[name].cy for name in feeds[item["id"]] if name in placed]
            wish[item["id"]] = sum(sources) / len(sources) if sources else None
        ranked = sorted(
            enumerate(column),
            key=lambda pair: (
                wish[pair[1]["id"]] is None,
                wish[pair[1]["id"]] or 0.0,
                pair[0],
            ),
        )
        bottom: float | None = None
        drift: list[float] = []
        column_parts: list[_Placed] = []
        for _, item in ranked:
            width, height = sizes[item["id"]]
            centre = wish[item["id"]]
            top = (
                centre - height / 2
                if centre is not None
                else (bottom or 0.0) + (_FLOW_GAP if bottom is not None else 0.0)
            )
            if bottom is not None:
                top = max(top, bottom + _FLOW_GAP)
            if centre is not None:
                drift.append(centre - (top + height / 2))
            part = _Placed(item["id"], item, left + (col_w - width) / 2, top, width, height)
            column_parts.append(part)
            bottom = top + height
        if number == min(columns) and column_parts:
            # The first layer has nothing to follow: centre it on zero.
            span = column_parts[-1].y + column_parts[-1].h - column_parts[0].y
            shift = -span / 2 - column_parts[0].y
        else:
            shift = sum(drift) / len(drift) if drift else 0.0
        for part in column_parts:
            part.y += shift
            placed[part.key] = part
        left += col_w + gap
    parts = [placed[name] for name in ids]
    min_x = min(part.x for part in parts)
    min_y = min(part.y for part in parts)
    for part in parts:
        part.x -= min_x
        part.y -= min_y
    width = max(part.x + part.w for part in parts)
    height = max(part.y + part.h for part in parts)
    return _Block(order=order, w=width, h=height, parts=parts)


def _components(ids: list[str], edges: list[tuple[str, str]]) -> list[list[str]]:
    """The linked clusters among ``ids``, each in spec order, by first member."""
    root: dict[str, str] = {name: name for name in ids}

    def find(name: str) -> str:
        while root[name] != name:
            root[name] = root[root[name]]
            name = root[name]
        return name

    position = {name: index for index, name in enumerate(ids)}
    for start, end in edges:
        a, b = find(start), find(end)
        if a != b:
            first, second = (a, b) if position[a] < position[b] else (b, a)
            root[second] = first
    groups: dict[str, list[str]] = {}
    for name in ids:
        groups.setdefault(find(name), []).append(name)
    return list(groups.values())


def _rows(blocks: list[_Block], limit: float) -> list[list[_Block]]:
    rows: list[list[_Block]] = [[]]
    width = 0.0
    for block in blocks:
        need = block.w if not rows[-1] else width + _BLOCK_GAP + block.w
        if rows[-1] and need > limit + 0.5:
            rows.append([block])
            width = block.w
        else:
            rows[-1].append(block)
            width = need
    return rows


def _row_size(row: list[_Block]) -> tuple[float, float]:
    width = sum(block.w for block in row) + _BLOCK_GAP * (len(row) - 1)
    return width, max(block.top for block in row) + max(block.h for block in row)


def _pack(blocks: list[_Block]) -> None:
    """Place the blocks left to right, wrapped into rows of a sheet-like shape.

    Every row width that some run of neighbouring blocks would need is tried;
    the one whose board is largest when fitted into a landscape window wins,
    and every board that is readable there counts the same, with the fewer
    rows winning a tie. So a board stays one row for as long as its notes can
    be read, and a wider one wraps where that keeps them largest.
    """
    if not blocks:
        return
    widths = [block.w for block in blocks]
    limits: list[float] = []
    for run in range(1, len(blocks) + 1):
        window = sum(widths[:run]) + _BLOCK_GAP * (run - 1)
        widest = window
        for end in range(run, len(blocks)):
            window += widths[end] - widths[end - run]
            widest = max(widest, window)
        limits.append(widest)
    best: list[list[_Block]] = []
    best_zoom = -1.0
    for limit in sorted(set(limits), reverse=True):
        rows = _rows(blocks, limit)
        sizes = [_row_size(row) for row in rows]
        board_w = max(size[0] for size in sizes)
        board_h = sum(size[1] for size in sizes) + _ROW_GAP * (len(rows) - 1)
        zoom = min(_SHEET[0] / max(board_w, 1.0), _SHEET[1] / max(board_h, 1.0), _READABLE_ZOOM)
        if zoom > best_zoom + 1e-9:
            best, best_zoom = rows, zoom
    top = 0.0
    for row in best:
        title_room = max(block.top for block in row)
        frames = [block for block in row if block.frame is not None]
        frame_h = max((block.h for block in frames), default=0.0)
        left = 0.0
        for block in row:
            if block.frame is not None:
                # Frames of one row end on one line, like the columns of a board.
                block.frame.h = frame_h
                block.h = frame_h
            block.move(left, top + title_room)
            left += block.w + _BLOCK_GAP
        top += title_room + max(block.h for block in row) + _ROW_GAP


def _arrange(spec: dict[str, Any]) -> list[_Placed]:
    """Every item with its rectangle, in the order a reader takes the board in."""
    items: list[dict[str, Any]] = spec["items"]
    links: list[dict[str, Any]] = spec["links"]
    frame_by_id = {item["id"]: item for item in items if item["type"] == "frame"}
    frame_by_title: dict[str, dict[str, Any]] = {}
    for item in items:
        if item["type"] == "frame" and item.get("title"):
            frame_by_title.setdefault(item["title"], item)

    # Which frame each unplaced item belongs to; a group without a frame item
    # gets a frame of its own, titled with the group's name.
    frames: dict[str, tuple[int, dict[str, Any]]] = {}
    members: dict[str, list[dict[str, Any]]] = {}
    ungrouped: list[tuple[int, dict[str, Any]]] = []
    for index, item in enumerate(items):
        if item["type"] == "frame":
            if not _has_place(item):
                frames.setdefault(f"id:{item['id']}", (index, item))
            continue
        if _has_place(item):
            continue
        group = item.get("group", "")
        if not group:
            ungrouped.append((index, item))
            continue
        frame = frame_by_id.get(group) or frame_by_title.get(group)
        key = f"id:{frame['id']}" if frame else f"group:{group}"
        frames.setdefault(key, (index, frame or {"id": "", "type": "frame", "title": group}))
        members.setdefault(key, []).append(item)

    linked = {link["from"] for link in links} | {link["to"] for link in links}
    heading: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        is_heading = (
            item["type"] == "text"
            and not _has_place(item)
            and not item.get("group")
            and item["id"] not in linked
        )
        if not is_heading or index != len(heading):
            break
        heading.append(item)
    if len(heading) == len(items):
        heading = []
    heading_ids = {item["id"] for item in heading}
    ungrouped = [pair for pair in ungrouped if pair[1]["id"] not in heading_ids]

    # Ungrouped items that are linked to one another form flows; the rest is a
    # loose cluster.
    free_ids = [item["id"] for _, item in ungrouped]
    free_set = set(free_ids)
    edges: list[tuple[str, str]] = []
    labeled: set[str] = set()
    for link in links:
        pair = (link["from"], link["to"])
        if pair[0] in free_set and pair[1] in free_set and pair not in edges:
            edges.append(pair)
            if link.get("label"):
                labeled.update(pair)
    in_flow = {name for pair in edges for name in pair}
    index_of = {item["id"]: index for index, item in ungrouped}
    item_of = {item["id"]: item for _, item in ungrouped}

    blocks: list[_Block] = []
    pinned: dict[str, _Block] = {}
    columns = _frame_columns(max((len(group) for group in members.values()), default=0))
    for key, (index, frame) in frames.items():
        is_pinned = _has_place(frame)
        placed_key = frame["id"] or f"frame:{frame.get('title', '')}"
        block = _frame_block(
            index, placed_key, frame, members.get(key, []), columns=columns, pinned=is_pinned
        )
        if is_pinned:
            pinned[frame["id"]] = block
        else:
            blocks.append(block)
    if columns and blocks:
        widest = max(block.w for block in blocks)
        for block in blocks:
            if block.frame is not None:
                block.frame.w = block.w = widest
    for cluster in _components([name for name in free_ids if name in in_flow], edges):
        inside = set(cluster)
        blocks.append(
            _flow_block(
                index_of[cluster[0]],
                [item_of[name] for name in cluster],
                [pair for pair in edges if pair[0] in inside],
                labeled=bool(inside & labeled),
            )
        )
    loose = [item for _, item in ungrouped if item["id"] not in in_flow]
    if loose:
        parts, width, height = _grid(loose, _loose_columns(len(loose)))
        blocks.append(_Block(order=index_of[loose[0]["id"]], w=width, h=height, parts=parts))
    blocks.sort(key=lambda block: block.order)
    _pack(blocks)

    flowing: list[_Placed] = []
    top = 0.0
    for item in heading:
        width, height = _size(item, placed=False)
        flowing.append(_Placed(item["id"], item, 0.0, top, width, height))
        top += height + 8
    if heading:
        for block in blocks:
            block.move(0.0, top - 8 + _HEADING_GAP)
    for block in blocks:
        flowing.extend(block.parts)

    # Items that carry their own place sit exactly there; whatever was laid
    # out by this module goes below them, so the two never collide.
    fixed: list[_Placed] = []
    for item in items:
        if not _has_place(item):
            continue
        if item["id"] in pinned:
            fixed.extend(pinned[item["id"]].parts)
            continue
        width, height = _size(item, placed=True)
        fixed.append(_Placed(item["id"], item, float(item["x"]), float(item["y"]), width, height))
    if fixed and flowing:
        dx = min(part.x for part in fixed)
        dy = max(part.y + part.h for part in fixed) + _ROW_GAP + _TITLE_ROOM
        for part in flowing:
            part.x += dx
            part.y += dy
    return [*flowing, *fixed]


def layout(spec: Any) -> list[dict[str, Any]]:
    """Where every item sits: ``[{"id", "type", "x", "y", "w", "h"}, …]``.

    The id of a frame made for a group is ``frame:<group>``. Computed from the
    spec alone; nothing here is stored.
    """
    return [
        {
            "id": part.key,
            "type": part.item["type"],
            "x": round(part.x, 2),
            "y": round(part.y, 2),
            "w": round(part.w, 2),
            "h": round(part.h, 2),
        }
        for part in _arrange(_usable(spec))
    ]


# --- connectors ------------------------------------------------------------------

_NORMAL: Final[dict[str, tuple[float, float]]] = {
    "left": (-1.0, 0.0),
    "right": (1.0, 0.0),
    "top": (0.0, -1.0),
    "bottom": (0.0, 1.0),
}
_START_GAP: Final[float] = 3.0
_END_GAP: Final[float] = 5.0
_HEAD_LENGTH: Final[float] = 7.0
_HEAD_HALF: Final[float] = 4.0


def _n(value: float) -> str:
    """A number for a style or a path: one decimal at most, never ``-0``."""
    text = f"{value:.1f}"
    if text.endswith(".0"):
        text = text[:-2]
    return "0" if text == "-0" else text


def _sides(a: _Placed, b: _Placed) -> tuple[str, str]:
    """The sides of ``a`` and ``b`` that face each other across the wider gap."""
    gap_x = max(b.x - (a.x + a.w), a.x - (b.x + b.w))
    gap_y = max(b.y - (a.y + a.h), a.y - (b.y + b.h))
    if gap_x >= gap_y:
        return ("right", "left") if b.cx >= a.cx else ("left", "right")
    return ("bottom", "top") if b.cy >= a.cy else ("top", "bottom")


def _spreads(part: _Placed) -> bool:
    """Whether several connectors may share a side at different points."""
    if part.item["type"] == "shape":
        return part.item.get("shape", "rect") == "rect"
    return part.item["type"] in ("note", "frame", "image")


def _anchor(part: _Placed, side: str, share: float) -> tuple[float, float]:
    if side in ("left", "right"):
        return (part.x if side == "left" else part.x + part.w, part.y + part.h * share)
    return (part.x + part.w * share, part.y if side == "top" else part.y + part.h)


_Curve = tuple[float, float, float, float, float, float, float, float]


def _curve(
    a: _Placed, side_a: str, share_a: float, b: _Placed, side_b: str, share_b: float, end_gap: float
) -> _Curve:
    """A cubic curve that leaves ``a`` and reaches ``b`` square to their sides."""
    na, nb = _NORMAL[side_a], _NORMAL[side_b]
    ax, ay = _anchor(a, side_a, share_a)
    bx, by = _anchor(b, side_b, share_b)
    x1, y1 = ax + na[0] * _START_GAP, ay + na[1] * _START_GAP
    x2, y2 = bx + nb[0] * end_gap, by + nb[1] * end_gap
    reach = max(1.0, min(120.0, math.hypot(x2 - x1, y2 - y1) * 0.45))
    if na[0] == -nb[0] and na[1] == -nb[1]:
        # Facing sides: half the gap between them gives an even S, however close they are.
        gap = (x2 - x1) * na[0] + (y2 - y1) * na[1]
        reach = max(6.0, min(reach, gap / 2))
    return (
        x1,
        y1,
        x1 + na[0] * reach,
        y1 + na[1] * reach,
        x2 + nb[0] * reach,
        y2 + nb[1] * reach,
        x2,
        y2,
    )


def _on_curve(curve: _Curve, t: float) -> tuple[float, float]:
    u = 1.0 - t
    k0, k1, k2, k3 = u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t
    return (
        k0 * curve[0] + k1 * curve[2] + k2 * curve[4] + k3 * curve[6],
        k0 * curve[1] + k1 * curve[3] + k2 * curve[5] + k3 * curve[7],
    )


def _aligned(a: _Placed, side_a: str, b: _Placed, side_b: str) -> tuple[float, float]:
    """Where a lone connector meets its two sides so that it runs straight.

    Two sides on one axis that overlap are joined at one height (or one
    column), which makes the connector a straight line; sides that do not
    overlap are joined at their nearest points. A diamond, an ellipse and a
    pill are met at the middle of a side, where their outline is.
    """
    upright = side_a in ("left", "right")
    if side_a == side_b or upright != (side_b in ("left", "right")):
        return 0.5, 0.5

    def span(part: _Placed) -> tuple[float, float, float, float]:
        start, size = (part.y, part.h) if upright else (part.x, part.w)
        inset = min(16.0, size / 4) if _spreads(part) else size / 2
        return start, size, start + inset, start + size - inset

    start_a, size_a, low_a, high_a = span(a)
    start_b, size_b, low_b, high_b = span(b)
    middle = (max(low_a, low_b) + min(high_a, high_b)) / 2
    at_a = max(low_a, min(high_a, middle))
    at_b = max(low_b, min(high_b, middle))
    return (at_a - start_a) / size_a, (at_b - start_b) / size_b


_Rect = tuple[float, float, float, float]
_SAMPLES: Final[tuple[float, ...]] = tuple(step / 14 for step in range(1, 14))
#: Above this many link-by-item checks a board is routed by the facing sides
#: alone, so a very large board still renders at once.
_ROUTING_BUDGET: Final[int] = 12_000


def _clear_sides(
    a: _Placed, b: _Placed, others: list[_Rect], taken: set[tuple[str, str]]
) -> tuple[str, str]:
    """The pair of sides whose curve crosses the fewest other items.

    The facing sides win unless another pair passes fewer items; among
    equals the shorter curve wins. ``taken`` holds the pairs earlier links
    between the same two items already use, so a link back takes another way
    instead of lying on top of the first.
    """
    facing = _sides(a, b)
    reach = (
        min(a.x, b.x) - 24,
        min(a.y, b.y) - 24,
        max(a.x + a.w, b.x + b.w) + 24,
        max(a.y + a.h, b.y + b.h) + 24,
    )
    near = [
        rect
        for rect in others
        if rect[0] < reach[2] and rect[2] > reach[0] and rect[1] < reach[3] and rect[3] > reach[1]
    ]
    if not near and not taken:
        return facing
    dx, dy = b.cx - a.cx, b.cy - a.cy
    from_a = [side for side, n in _NORMAL.items() if n[0] * dx + n[1] * dy > 0]
    from_b = [side for side, n in _NORMAL.items() if n[0] * dx + n[1] * dy < 0]
    pairs = [facing, *((p, q) for p in from_a for q in from_b if (p, q) != facing)]
    # Last resort: an arc that leaves and arrives on the same side, around
    # whatever stands between the two.
    pairs += [(side, side) for side in _NORMAL]
    pairs = [pair for pair in pairs if pair not in taken] or [facing]
    best, best_cost = pairs[0], math.inf
    for pair in pairs:
        curve = _curve(a, pair[0], 0.5, b, pair[1], 0.5, _END_GAP)
        points = [_on_curve(curve, t) for t in _SAMPLES]
        crossed = sum(
            1
            for x, y in points
            if any(rect[0] < x < rect[2] and rect[1] < y < rect[3] for rect in near)
        )
        length = sum(
            math.hypot(q[0] - p[0], q[1] - p[1]) for p, q in zip(points, points[1:], strict=False)
        )
        detour = 0 if pair == facing else 160 if pair[0] == pair[1] else 48
        cost = crossed * 400 + length + detour
        if cost < best_cost - 1e-9:
            best, best_cost = pair, cost
    return best


@dataclass(frozen=True)
class _Wire:
    path: str
    head: str
    dashed: bool
    mid: tuple[float, float]
    label: str
    start: _Placed
    end: _Placed
    directed: bool
    box: _Rect
    """What the curve and its label cover (left, top, right, bottom)."""


def _route(links: list[dict[str, Any]], parts: dict[str, _Placed]) -> list[_Wire]:
    """Every link as a curve between two sides of its items, clear of the others."""
    careful = len(links) * len(parts) <= _ROUTING_BUDGET
    solid = [part for part in parts.values() if part.item["type"] != "frame"]
    chosen: dict[int, tuple[_Placed, _Placed, str, str]] = {}
    between: dict[tuple[str, str], set[tuple[str, str]]] = {}
    docks: dict[tuple[str, str], list[tuple[float, int, int]]] = {}
    for index, link in enumerate(links):
        a, b = parts.get(link["from"]), parts.get(link["to"])
        if a is None or b is None:
            continue
        if careful:
            others = [
                (part.x + 1, part.y + 1, part.x + part.w - 1, part.y + part.h - 1)
                for part in solid
                if part is not a and part is not b
            ]
            side_a, side_b = _clear_sides(a, b, others, between.get((a.key, b.key), set()))
            between.setdefault((a.key, b.key), set()).add((side_a, side_b))
            between.setdefault((b.key, a.key), set()).add((side_b, side_a))
        else:
            side_a, side_b = _sides(a, b)
        chosen[index] = (a, b, side_a, side_b)
        along_a = b.cy if side_a in ("left", "right") else b.cx
        along_b = a.cy if side_b in ("left", "right") else a.cx
        docks.setdefault((a.key, side_a), []).append((along_a, index, 0))
        docks.setdefault((b.key, side_b), []).append((along_b, index, 1))
    share: dict[tuple[int, int], float] = {}
    for dock in docks.values():
        dock.sort()
        for place, (_, index, end) in enumerate(dock):
            share[(index, end)] = 0.2 + 0.6 * (place + 0.5) / len(dock)
    wires: list[_Wire] = []
    for index, (a, b, side_a, side_b) in chosen.items():
        link = links[index]
        style = link.get("style", "arrow")
        directed = style != "line"
        if len(docks[(a.key, side_a)]) == 1 and len(docks[(b.key, side_b)]) == 1:
            share_a, share_b = _aligned(a, side_a, b, side_b)
        else:
            share_a = share[(index, 0)] if _spreads(a) else 0.5
            share_b = share[(index, 1)] if _spreads(b) else 0.5
        end_gap = _END_GAP if directed else _START_GAP
        curve = _curve(a, side_a, share_a, b, side_b, share_b, end_gap)
        x1, y1, c1x, c1y, c2x, c2y, x2, y2 = curve
        path = f"M{_n(x1)} {_n(y1)}C{_n(c1x)} {_n(c1y)} {_n(c2x)} {_n(c2y)} {_n(x2)} {_n(y2)}"
        head = ""
        if directed:
            nb = _NORMAL[side_b]
            bx0, by0 = x2 + nb[0] * _HEAD_LENGTH, y2 + nb[1] * _HEAD_LENGTH
            px, py = -nb[1] * _HEAD_HALF, nb[0] * _HEAD_HALF
            head = f"M{_n(bx0 + px)} {_n(by0 + py)}L{_n(x2)} {_n(y2)}L{_n(bx0 - px)} {_n(by0 - py)}"
        label = link.get("label", "")
        mid = _on_curve(curve, 0.5)
        points = [_on_curve(curve, step / 16) for step in range(17)]
        half = (min(220.0, _units(label) * 6.6 + 18) / 2) if label else 0.0
        wires.append(
            _Wire(
                path=path,
                head=head,
                dashed=style == "dashed",
                mid=mid,
                label=label,
                start=a,
                end=b,
                directed=directed,
                box=(
                    min(mid[0] - half, *(point[0] for point in points)),
                    min(mid[1] - 10, *(point[1] for point in points)),
                    max(mid[0] + half, *(point[0] for point in points)),
                    max(mid[1] + 10, *(point[1] for point in points)),
                ),
            )
        )
    return wires


# --- the page --------------------------------------------------------------------

# Paper tints come from the series tokens, so a note keeps its hue in both
# themes; the share of the hue is higher on the dark ground, where a light
# tint would read as grey. Defined in all three theme scopes, like the tokens.
_CSS: Final[str] = """
:root{--wb-tint:15%;--wb-edge:30%;--wb-fill:7%}
@media screen and (prefers-color-scheme:dark){
:root:not([data-theme="light"]){--wb-tint:20%;--wb-edge:34%;--wb-fill:10%}}
@media screen{:root[data-theme="dark"]{--wb-tint:20%;--wb-edge:34%;--wb-fill:10%}}
.c-yellow{--c:var(--s4)}.c-pink{--c:var(--s6)}.c-blue{--c:var(--s1)}.c-green{--c:var(--s3)}
.c-violet{--c:var(--s5)}.c-orange{--c:var(--s2)}.c-gray{--c:var(--ink-3)}
.wb{position:fixed;inset:0;overflow:hidden;background:var(--bg);touch-action:none;cursor:grab;
  -webkit-user-select:none;user-select:none}
.wb:focus-visible{outline-offset:-2px}
.wb.is-panning{cursor:grabbing}
.wb-grid{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}
.wb-grid circle{fill:var(--line-2)}
.wb-board{position:absolute;left:0;top:0;width:0;height:0;transform-origin:0 0}
.wb-board ul{margin:0;padding:0;list-style:none}
.wb-wires{position:absolute;left:0;top:0;width:1px;height:1px;overflow:visible;z-index:1;
  pointer-events:none}
.wb-wires path{fill:none;stroke:var(--ink-3);stroke-width:1.5;stroke-linecap:round;
  stroke-linejoin:round}
.wb-wires .is-dashed{stroke-dasharray:5 6}
.wb-frame{position:absolute;z-index:0;border-radius:16px;
  border:1px solid color-mix(in srgb,var(--c) 26%,var(--line-2));
  background:color-mix(in srgb,var(--c) 4%,var(--bg));pointer-events:none}
.wb-frame h2{position:absolute;left:2px;bottom:calc(100% + 8px);max-width:100%;font-size:14px;
  line-height:20px;font-weight:600;letter-spacing:0;color:var(--ink-2);white-space:nowrap;
  overflow:hidden;text-overflow:ellipsis;pointer-events:auto;cursor:auto;
  -webkit-user-select:text;user-select:text}
.wb-item{position:absolute;z-index:2;cursor:auto;-webkit-user-select:text;user-select:text}
.wb-item a{color:inherit}
.wb-item code{background:color-mix(in srgb,var(--ink) 8%,transparent)}
.wb-note{padding:14px;border:1px solid color-mix(in srgb,var(--c) var(--wb-edge),var(--bg));
  border-radius:8px;background:color-mix(in srgb,var(--c) var(--wb-tint),var(--bg));
  box-shadow:0 1px 2px color-mix(in srgb,var(--ink) 7%,transparent);font-size:14px;
  line-height:20px}
.wb-shape{display:flex;align-items:center;justify-content:center;padding:10px 16px;
  border:1.5px solid color-mix(in srgb,var(--c) 62%,var(--bg));border-radius:10px;
  background:color-mix(in srgb,var(--c) var(--wb-fill),var(--bg));font-size:14px;line-height:20px;
  font-weight:500;text-align:center}
.wb-shape.is-pill{border-radius:999px}
.wb-shape.is-ellipse{border-radius:50%;padding:10px 13%}
.wb-shape.is-diamond{border:0;background:none;padding:10px 23%}
.wb-shape p{position:relative;min-width:0}
.wb-diamond{position:absolute;inset:0;width:100%;height:100%;overflow:visible}
.wb-diamond polygon{fill:color-mix(in srgb,var(--c) var(--wb-fill),var(--bg));
  stroke:color-mix(in srgb,var(--c) 62%,var(--bg));stroke-width:1.5;stroke-linejoin:round}
.wb-text{font-size:14px;line-height:22px}
.wb-text.is-big{font-size:22px;line-height:28px;font-weight:600;letter-spacing:-.01em}
.wb-text.is-tinted{color:color-mix(in srgb,var(--c) 62%,var(--ink))}
.wb-image figure{display:flex;flex-direction:column;gap:8px;height:100%}
.wb-image img,.wb-blank{display:block;flex:1 1 auto;width:100%;min-height:0;border-radius:10px;
  background:var(--bg-2);object-fit:contain}
.wb-blank{border:1px solid var(--line)}
.wb-image figcaption{font-size:12px;line-height:16px;color:var(--ink-2)}
.wb-label{position:absolute;z-index:3;max-width:220px;padding:1px 8px;
  border:1px solid var(--line-2);border-radius:999px;background:var(--bg);color:var(--ink-2);
  font-size:12px;line-height:18px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
  transform:translate(-50%,-50%);cursor:auto;-webkit-user-select:text;user-select:text}
.wb-tools{position:absolute;right:16px;bottom:16px;z-index:5;display:flex;align-items:center;
  gap:2px;padding:4px;border:1px solid var(--line-2);border-radius:12px;background:var(--bg);
  cursor:auto}
.wb-tools button{appearance:none;display:inline-flex;align-items:center;justify-content:center;
  min-width:32px;height:32px;padding:0 6px;border:0;border-radius:8px;background:transparent;
  color:var(--ink-2);font:500 12px/16px var(--font);font-variant-numeric:tabular-nums;
  cursor:pointer}
.wb-tools button:hover{background:var(--bg-2);color:var(--ink)}
.wb-tools .wb-zoom{min-width:52px}
.wb-tools svg{width:16px;height:16px;fill:none;stroke:currentColor;stroke-width:1.6;
  stroke-linecap:round;stroke-linejoin:round}
.wb-tools i{width:1px;height:16px;margin:0 4px;background:var(--line-2)}
.wb-meta{position:absolute;left:16px;top:12px;z-index:5;padding:4px 10px;
  border:1px solid var(--line-2);border-radius:10px;background:var(--bg);cursor:auto}
.wb-meta .node-meta,.wb-meta .node-note{margin-top:0}
@media (pointer:coarse){.wb-tools button{min-width:40px;height:40px}}
@media print{@page{size:landscape;margin:12mm}
html,body{height:auto}body.fill{overflow:visible}
.wb{position:relative;inset:auto;width:var(--wb-pw);height:var(--wb-ph);margin:0 auto}
.wb-grid,.wb-tools,.wb-meta{display:none}
.wb-board{transform:var(--wb-pt)!important}}
"""

# In print the board keeps its clip on purpose: the page is the scaled board's
# size, and without the clip a browser measures the unscaled board as overflow
# and shrinks the whole sheet.
#
# Pan, zoom and fit. The script reads the board's bounding box (numbers this
# module wrote) and nothing from the spec. No network, no storage.
_JS: Final[str] = """
(function(){
var d=document,view=d.getElementById("wb"),board=d.getElementById("wb-board");
if(!view||!board)return;
var pat=d.getElementById("wb-dots"),zoomLabel=d.getElementById("wb-zoom");
var box=(view.getAttribute("data-box")||"").split(" ").map(Number);
if(box.length!==4||box.some(isNaN))box=[0,0,1,1];
var s=1,tx=0,ty=0,moved=false,MIN=.05,MAX=4;
function draw(){
  board.style.transform="translate("+Math.round(tx)+"px,"+Math.round(ty)+"px) scale("+s+")";
  if(pat){var g=24*s;while(g<16)g*=2;
    pat.setAttribute("width",g);pat.setAttribute("height",g);
    pat.setAttribute("x",Math.round(tx)-1);pat.setAttribute("y",Math.round(ty)-1);}
  if(zoomLabel)zoomLabel.textContent=Math.round(s*100)+"%";
}
function fit(){
  var w=view.clientWidth,h=view.clientHeight;if(!w||!h)return;
  var pad=Math.max(16,Math.min(64,Math.min(w,h)*.08));
  var k=Math.min((w-2*pad)/box[2],(h-2*pad-40)/box[3],1);
  s=Math.max(MIN,k);
  tx=(w-box[2]*s)/2-box[0]*s;ty=(h-box[3]*s)/2-box[1]*s;moved=false;draw();
}
function zoomAt(k,cx,cy){
  var n=Math.max(MIN,Math.min(MAX,s*k));if(n===s)return;
  tx=cx-(cx-tx)*n/s;ty=cy-(cy-ty)*n/s;s=n;moved=true;draw();
}
function centre(k){zoomAt(k,view.clientWidth/2,view.clientHeight/2);}
function pan(dx,dy){tx+=dx;ty+=dy;moved=true;draw();}
var ptrs={},dragging=false,travelled=0,swallow=false;
function list(){return Object.keys(ptrs).map(function(k){return ptrs[k];});}
view.addEventListener("pointerdown",function(e){
  var t=e.target;if(!t.closest||t.closest(".wb-tools,.wb-meta"))return;
  if(e.pointerType==="mouse"){
    if(e.button!==0&&e.button!==1)return;
    if(e.button===0&&t.closest(".wb-item,.wb-label,.wb-frame h2"))return;
    if(e.button===1)e.preventDefault();
  }
  ptrs[e.pointerId]={x:e.clientX,y:e.clientY};
  if(list().length===1){travelled=0;dragging=false;swallow=false;}
});
view.addEventListener("pointermove",function(e){
  var p=ptrs[e.pointerId];if(!p)return;
  var all=list();
  if(all.length===1){
    var dx=e.clientX-p.x,dy=e.clientY-p.y;travelled+=Math.abs(dx)+Math.abs(dy);
    p.x=e.clientX;p.y=e.clientY;
    if(!dragging){if(travelled<4)return;dragging=true;swallow=true;
      view.classList.add("is-panning");
      try{view.setPointerCapture(e.pointerId);}catch(err){}}
    pan(dx,dy);
  }else if(all.length===2){
    var o=all[0]===p?all[1]:all[0];
    var d0=Math.hypot(p.x-o.x,p.y-o.y),mx0=(p.x+o.x)/2,my0=(p.y+o.y)/2;
    p.x=e.clientX;p.y=e.clientY;
    var d1=Math.hypot(p.x-o.x,p.y-o.y),mx1=(p.x+o.x)/2,my1=(p.y+o.y)/2;
    swallow=true;
    if(d0>0&&d1>0)zoomAt(d1/d0,mx1,my1);
    pan(mx1-mx0,my1-my0);
  }
});
function release(e){
  if(!ptrs[e.pointerId])return;delete ptrs[e.pointerId];
  if(!list().length){dragging=false;view.classList.remove("is-panning");
    setTimeout(function(){swallow=false;},0);}
}
view.addEventListener("pointerup",release);
view.addEventListener("pointercancel",release);
view.addEventListener("wheel",function(e){
  e.preventDefault();
  var u=e.deltaMode===1?16:e.deltaMode===2?view.clientHeight:1,dx=e.deltaX*u,dy=e.deltaY*u;
  if(e.ctrlKey||e.metaKey){
    zoomAt(Math.exp(-Math.max(-60,Math.min(60,dy))*.01),e.clientX,e.clientY);
  }else if(e.shiftKey&&!dx){pan(-dy,0);}
  else{pan(-dx,-dy);}
},{passive:false});
var pinch=1;
view.addEventListener("gesturestart",function(e){e.preventDefault();pinch=s;});
view.addEventListener("gesturechange",function(e){e.preventDefault();
  if(!list().length&&e.scale>0)zoomAt(pinch*e.scale/s,e.clientX,e.clientY);});
view.addEventListener("gestureend",function(e){e.preventDefault();});
d.addEventListener("keydown",function(e){
  if(e.ctrlKey||e.metaKey||e.altKey)return;
  var k=e.key,step=e.shiftKey?240:60;
  if(k==="ArrowLeft")pan(step,0);else if(k==="ArrowRight")pan(-step,0);
  else if(k==="ArrowUp")pan(0,step);else if(k==="ArrowDown")pan(0,-step);
  else if(k==="+"||k==="=")centre(1.25);else if(k==="-"||k==="_")centre(.8);
  else if(k==="0")centre(1/s);else if(k==="1")fit();
  else return;
  e.preventDefault();
});
d.addEventListener("click",function(e){
  if(swallow){swallow=false;
    if(!e.target.closest||!e.target.closest(".wb-tools")){
      e.preventDefault();e.stopPropagation();return;}}
  var b=e.target.closest?e.target.closest(".wb-tools button"):null;
  if(b){var act=b.getAttribute("data-act");
    if(act==="in")centre(1.25);else if(act==="out")centre(.8);
    else if(act==="reset")centre(1/s);else if(act==="fit")fit();
    return;}
  var a=e.target.closest?e.target.closest("a[href]"):null;
  var h=a?(a.getAttribute("href")||"").trim():"";
  if(h.indexOf("http://")===0||h.indexOf("https://")===0){
    e.preventDefault();
    if(window.parent!==window){window.parent.postMessage({type:"dodaios-open-link",href:h},"*");}
    else{location.href=h;}
  }
},true);
addEventListener("resize",function(){if(!moved)fit();});
addEventListener("load",function(){if(!moved)fit();});
fit();
})();
"""

_ICONS: Final[dict[str, str]] = {
    "out": '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3.5 8h9"/></svg>',
    "in": '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3.5 8h9M8 3.5v9"/></svg>',
    "fit": (
        '<svg viewBox="0 0 16 16" aria-hidden="true">'
        '<path d="M2.5 6V3.5a1 1 0 0 1 1-1H6M10 2.5h2.5a1 1 0 0 1 1 1V6'
        'M13.5 10v2.5a1 1 0 0 1-1 1H10M6 13.5H3.5a1 1 0 0 1-1-1V10"/></svg>'
    ),
}

_TOOLS: Final[str] = (
    '<div class="wb-tools" role="group" aria-label="Zoom">'
    f'<button type="button" data-act="out" aria-label="Zoom out" title="Zoom out">'
    f"{_ICONS['out']}</button>"
    '<button type="button" class="wb-zoom" id="wb-zoom" data-act="reset" '
    'aria-label="Reset zoom to 100%" title="Reset zoom to 100%">100%</button>'
    f'<button type="button" data-act="in" aria-label="Zoom in" title="Zoom in">'
    f"{_ICONS['in']}</button>"
    '<i aria-hidden="true"></i>'
    f'<button type="button" data-act="fit" aria-label="Fit all" title="Fit all">'
    f"{_ICONS['fit']}</button>"
    "</div>"
)

_GRID: Final[str] = (
    '<svg class="wb-grid" aria-hidden="true" focusable="false"><defs>'
    '<pattern id="wb-dots" width="24" height="24" patternUnits="userSpaceOnUse">'
    '<circle cx="1" cy="1" r="1"/></pattern></defs>'
    '<rect width="100%" height="100%" fill="url(#wb-dots)"/></svg>'
)

# The printable area of a landscape sheet inside the page margins, in CSS px:
# the smaller of A4 and Letter in each direction, so the board fits both.
_PRINT_W: Final[float] = 960.0
_PRINT_H: Final[float] = 690.0
_EDGE: Final[float] = 4.0


def _box_style(part: _Placed, *, grow: bool = False) -> str:
    height = "min-height" if grow else "height"
    return f"left:{_n(part.x)}px;top:{_n(part.y)}px;width:{_n(part.w)}px;{height}:{_n(part.h)}px"


#: The colors groups take in turn when the board itself names none.
_GROUP_COLORS: Final[tuple[str, ...]] = ("yellow", "blue", "green", "pink", "violet", "orange")


def _group_tinted(spec: dict[str, Any]) -> dict[str, Any]:
    """The spec with one note color per group, when the board chose no colors.

    A board whose grouped notes carry no color at all would be one wall of
    yellow; giving each group its own paper makes the groups readable at a
    glance. As soon as one grouped note names a color the board is left
    alone: there a color means something, and a guessed one would lie.
    Not written back into the spec.
    """
    items = spec["items"]
    grouped = [item for item in items if item["type"] == "note" and item.get("group")]
    if not grouped or any(item.get("color") for item in grouped):
        return spec
    order: dict[str, str] = {}
    for item in grouped:
        order.setdefault(item["group"], _GROUP_COLORS[len(order) % len(_GROUP_COLORS)])
    tinted = [
        {**item, "color": order[item["group"]]}
        if item["type"] == "note" and item.get("group")
        else item
        for item in items
    ]
    return {**spec, "items": tinted}


def _color_class(item: dict[str, Any]) -> str:
    name = shell.pick(item.get("color"), COLORS, _DEFAULT_COLOR[item["type"]])
    return f"c-{name}"


def _item_html(part: _Placed) -> str:
    item = part.item
    kind = item["type"]
    ident = f' data-id="{shell.attr(item["id"])}"' if item.get("id") else ""
    color = _color_class(item)
    text = shell.lines(item.get("text", ""), MAX_TEXT_CHARS)
    if kind == "frame":
        title = item.get("title", "")
        head = f"<h2>{shell.esc(title)}</h2>" if title else ""
        return f'<li class="wb-frame {color}"{ident} style="{_box_style(part)}">{head}</li>'
    if kind == "note":
        return (
            f'<li class="wb-item wb-note {color}"{ident} style="{_box_style(part, grow=True)}">'
            f"<p>{text}</p></li>"
        )
    if kind == "shape":
        form = shell.pick(item.get("shape"), SHAPES, "rect")
        outline = ""
        if form == "diamond":
            w, h = part.w, part.h
            points = f"{_n(w / 2)},1 {_n(w - 1)},{_n(h / 2)} {_n(w / 2)},{_n(h - 1)} 1,{_n(h / 2)}"
            outline = (
                f'<svg class="wb-diamond" viewBox="0 0 {_n(w)} {_n(h)}" aria-hidden="true">'
                f'<polygon points="{points}"/></svg>'
            )
        return (
            f'<li class="wb-item wb-shape is-{form} {color}"{ident} style="{_box_style(part)}">'
            f"{outline}<p>{text}</p></li>"
        )
    if kind == "image":
        src = shell.safe_image(item.get("image"))
        alt = shell.attr(shell.clean(_plain(item.get("text", "")), 120))
        picture = (
            f'<img src="{shell.attr(src)}" alt="{alt}">' if src else '<div class="wb-blank"></div>'
        )
        caption = f"<figcaption>{text}</figcaption>" if item.get("text") else ""
        return (
            f'<li class="wb-item wb-image"{ident} style="{_box_style(part)}">'
            f"<figure>{picture}{caption}</figure></li>"
        )
    plain = _plain(item.get("text", ""))
    classes = "wb-item wb-text" + (" is-big" if _is_big(plain) else "")
    if item.get("color") and item["color"] != "gray":
        classes += f" is-tinted {color}"
    return f'<li class="{classes}"{ident} style="{_box_style(part, grow=True)}"><p>{text}</p></li>'


def _name(part: _Placed) -> str:
    """What a connector's end is called when the board is read aloud."""
    item = part.item
    text = shell.clean(_plain(item.get("title") or item.get("text") or ""), PREVIEW_CHARS)
    return text or item["type"]


def _wires_html(wires: list[_Wire]) -> tuple[str, str]:
    """The connectors as one SVG, and their labels as a list beside it."""
    paths: list[str] = []
    labels: list[str] = []
    for wire in wires:
        dashed = ' class="is-dashed"' if wire.dashed else ""
        paths.append(f'<path{dashed} d="{wire.path}"/>')
        if wire.head:
            paths.append(f'<path d="{wire.head}"/>')
        joint = "→" if wire.directed else "–"
        spoken = f"{shell.esc(_name(wire.start))} {joint} {shell.esc(_name(wire.end))}"
        if wire.label:
            labels.append(
                f'<li class="wb-label" style="left:{_n(wire.mid[0])}px;top:{_n(wire.mid[1])}px">'
                f'<span class="visually-hidden">{spoken}: </span>{shell.esc(wire.label)}</li>'
            )
        else:
            labels.append(f'<li class="visually-hidden">{spoken}</li>')
    svg = (
        f'<svg class="wb-wires" aria-hidden="true" focusable="false">{"".join(paths)}</svg>'
        if paths
        else ""
    )
    listing = (
        f'<ul class="wb-links" aria-label="Connections">{"".join(labels)}</ul>' if labels else ""
    )
    return svg, listing


def _bounds(parts: list[_Placed], wires: list[_Wire]) -> tuple[float, float, float, float]:
    """The board's bounding box (x, y, width, height): items, frame titles, connectors."""
    if not parts:
        return 0.0, 0.0, 1.0, 1.0
    boxes: list[_Rect] = [wire.box for wire in wires]
    for part in parts:
        titled = part.item["type"] == "frame" and part.item.get("title")
        top = part.y - (_TITLE_ROOM if titled else 0.0)
        boxes.append((part.x, top, part.x + part.w, part.y + part.h))
    # A few units of air, so a border or a note's shadow is not cut at the edge.
    left = min(box[0] for box in boxes) - _EDGE
    top = min(box[1] for box in boxes) - _EDGE
    right = max(box[2] for box in boxes) + _EDGE
    bottom = max(box[3] for box in boxes) + _EDGE
    return left, top, right - left, bottom - top


def render(node: Any) -> str:
    """The board as one self-contained page; the same node gives the same page."""
    spec = _group_tinted(_usable(getattr(node, "spec", None)))
    parts = _arrange(spec)
    by_key = {part.key: part for part in parts if part.item.get("id")}
    wires = _route(spec["links"], by_key)
    svg, listing = _wires_html(wires)
    left, top, width, height = _bounds(parts, wires)
    scale = min(_PRINT_W / width, _PRINT_H / height, 1.0)
    print_vars = (
        f"--wb-pw:{_n(width * scale)}px;--wb-ph:{_n(height * scale)}px;"
        f"--wb-pt:scale({scale:.4f}) translate({_n(-left)}px,{_n(-top)}px)"
    )
    title = getattr(node, "title", "") or ""
    meta = shell.upkeep_meta(node)
    body = (
        f'<main class="wb" id="wb" tabindex="0" aria-label="{shell.attr(title)}" '
        f'data-box="{_n(left)} {_n(top)} {_n(width)} {_n(height)}" style="{print_vars}">'
        f"{_GRID}"
        f'<h1 class="visually-hidden">{shell.esc(title)}</h1>'
        + (f'<div class="wb-meta">{meta}</div>' if meta else "")
        + '<div class="wb-board" id="wb-board">'
        f"{svg}"
        f'<ul class="wb-items">{"".join(_item_html(part) for part in parts)}</ul>'
        f"{listing}"
        "</div>"
        f"{_TOOLS}"
        "</main>"
    )
    return shell.document(node, body=body, css=_CSS, js=_JS, body_class="fill", kit_js=False)


# --- the library card, and a fresh board -----------------------------------------


def preview(spec: dict[str, Any]) -> dict[str, Any]:
    """What the library draws on the card: the first few notes and the item count."""
    items = _group_tinted(_usable(spec))["items"]
    notes: list[dict[str, str]] = []
    for item in items:
        text = shell.clean(_plain(item.get("text", "")), PREVIEW_CHARS).strip()
        if not text:
            continue
        color = shell.pick(item.get("color"), COLORS, _DEFAULT_COLOR[item["type"]])
        notes.append({"text": text, "color": color})
        if len(notes) == PREVIEW_NOTES:
            break
    return {"notes": notes, "count": len(items)}


def starter(title: str, language: str) -> dict[str, Any]:
    """A small board to start from: one frame of three notes, a fourth beside it."""
    return normalize(
        {
            "layout": "auto",
            "items": [
                {"id": "n1", "text": "First idea", "group": "Ideas"},
                {"id": "n2", "text": "Second idea", "group": "Ideas", "color": "blue"},
                {"id": "n3", "text": "Third idea", "group": "Ideas", "color": "green"},
                {"id": "n4", "text": "Next step", "color": "pink"},
            ],
            "links": [{"from": "n3", "to": "n4"}],
        }
    )


__all__ = [
    "COLORS",
    "EXAMPLE",
    "GUIDE",
    "ITEM_TYPES",
    "LINK_STYLES",
    "MAX_ITEMS",
    "MAX_LINKS",
    "SHAPES",
    "layout",
    "normalize",
    "preview",
    "render",
    "starter",
]
