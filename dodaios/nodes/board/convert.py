"""Diagrams and the old whiteboard grammar, turned into scene elements.

Two things become elements here:

* A DIAGRAM: nodes, edges, groups and a direction (what the ``diagram``
  action takes, and what a Mermaid flowchart is read into). It is laid out by
  :mod:`dodaios.nodes.board.layout` and drawn with the board's own elements:
  each node a shape with a bound label, each edge an arrow bound to the two
  shapes, each group a frame around its members.
* The OLD GRAMMAR of whiteboard nodes (``items``/``links``/``layout``),
  which older nodes store and a model may still send: ``legacy_to_scene``
  turns it into a scene laid out the same way, notes as yellow sticky boxes,
  groups as frames, links as bound arrows.

Why a diagram looks the same every time: the nodes of one kind get one size
(the largest label decides, within a cap, longer labels wrap), positions sit
on the editor's 20 px grid, gaps are fixed, and a shape's colour follows its
kind unless the model names one (boxes blue, decisions yellow, start and end
green, notes yellow), each a stroke in the palette's strong shade over a fill
in its light one. So a board made of several diagrams still reads as one.

The shared builders (:func:`build_node`, :func:`arrow_between`,
:func:`route`, :func:`parse_style`) are what the scene actions use for single
things too.
"""

from __future__ import annotations

import base64
import binascii
import math
import re
from collections.abc import Callable
from typing import Any, Final

from dodaios.nodes import shell
from dodaios.nodes.board import elements as el
from dodaios.nodes.board import layout as lay
from dodaios.nodes.types import NodeError

# --- kinds and styles -----------------------------------------------------------------

#: What a model may call a thing, and the kind this module builds.
KIND_ALIASES: Final[dict[str, str]] = {
    "box": "box",
    "rectangle": "box",
    "rect": "rect",
    "square": "rect",
    "process": "box",
    "step": "box",
    "card": "box",
    "rounded": "rounded",
    "round": "rounded",
    "pill": "rounded",
    "stadium": "rounded",
    "capsule": "rounded",
    "ellipse": "ellipse",
    "oval": "ellipse",
    "circle": "circle",
    "diamond": "diamond",
    "decision": "diamond",
    "rhombus": "diamond",
    "note": "note",
    "sticky": "note",
    "sticky note": "note",
    "sticky-note": "note",
    "stickynote": "note",
    "postit": "note",
    "post-it": "note",
    "text": "text",
    "label": "text",
    "heading": "text",
    "title": "text",
    "frame": "frame",
    "group": "frame",
    "section": "frame",
    "arrow": "arrow",
    "connector": "arrow",
    "line": "line",
    "image": "image",
    "picture": "image",
    "photo": "image",
    "freedraw": "freedraw",
    "draw": "freedraw",
    "drawing": "freedraw",
    "pen": "freedraw",
    "sketch": "freedraw",
}
NODE_KINDS: Final[tuple[str, ...]] = (
    "box",
    "rect",
    "rounded",
    "ellipse",
    "circle",
    "diamond",
    "note",
    "text",
    "image",
)
#: The colour a kind takes when the model names none.
KIND_COLOR: Final[dict[str, str]] = {
    "box": "blue",
    "rect": "blue",
    "rounded": "blue",
    "ellipse": "green",
    "circle": "green",
    "diamond": "yellow",
}
#: The editor shape each kind is drawn as.
KIND_SHAPE: Final[dict[str, str]] = {
    "box": "rectangle",
    "rect": "rectangle",
    "rounded": "rectangle",
    "note": "rectangle",
    "ellipse": "ellipse",
    "circle": "ellipse",
    "diamond": "diamond",
}
#: Smallest size per kind, and how wide its label may run before it wraps.
MIN_SIZE: Final[dict[str, tuple[float, float]]] = {
    "box": (160.0, 80.0),
    "rect": (160.0, 80.0),
    "rounded": (160.0, 80.0),
    "ellipse": (160.0, 80.0),
    "circle": (120.0, 120.0),
    "diamond": (180.0, 120.0),
    "note": (200.0, 140.0),
    "image": (240.0, 180.0),
}
MAX_TEXT_WIDTH: Final[dict[str, float]] = {
    "box": 240.0,
    "rect": 240.0,
    "rounded": 240.0,
    "ellipse": 200.0,
    "circle": 160.0,
    "diamond": 160.0,
    "note": 168.0,
    "text": 520.0,
}
NOTE_WIDTH: Final[float] = 200.0
LABEL_SIZE: Final[float] = 20.0
EDGE_LABEL_SIZE: Final[float] = 16.0
ARROW_GAP: Final[float] = 8.0
FRAME_PAD: Final[float] = 40.0
FRAME_NAME_ROOM: Final[float] = 32.0

MAX_LABEL_CHARS: Final[int] = 1_000
MAX_DIAGRAM_NODES: Final[int] = 300
MAX_DIAGRAM_EDGES: Final[int] = 600
MAX_DIAGRAM_GROUPS: Final[int] = 60

_STYLE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "color",
        "fill",
        "stroke",
        "fill_style",
        "stroke_width",
        "stroke_style",
        "roughness",
        "sloppiness",
        "opacity",
        "font",
        "size",
        "align",
        "text_color",
        "rounded",
    }
)


def kind_of(value: Any, default: str = "box") -> str:
    """The kind a model means by ``value``; raises ``ValueError`` with the choices."""
    if value is None or value == "":
        return default
    name = str(value).strip().lower().replace("_", " ")
    kind = KIND_ALIASES.get(name) or KIND_ALIASES.get(name.replace(" ", "-"))
    if kind is None:
        raise ValueError(
            f"unknown type {value!r}; use box, rect, rounded, ellipse, circle, diamond, note, "
            "text, frame, arrow, line, image or freedraw"
        )
    return kind


def parse_style(raw: dict[str, Any]) -> dict[str, Any]:
    """The style words of an action or a node, checked; only the keys given.

    Keys: ``color`` (one palette name for stroke and fill), ``fill``,
    ``stroke``, ``fill_style``, ``stroke_width``, ``stroke_style``,
    ``roughness``/``sloppiness``, ``opacity`` (0-100), ``font``, ``size``,
    ``align``, ``text_color``, ``rounded``. Raises ``ValueError``.
    """
    style: dict[str, Any] = {}
    if raw.get("color") not in (None, ""):
        el.resolve_color(raw["color"], "stroke")  # checked now, applied per kind
        style["color"] = str(raw["color"])
    if raw.get("fill") not in (None, ""):
        style["fill"] = el.resolve_color(raw["fill"], "fill")
    if raw.get("stroke") not in (None, ""):
        style["stroke"] = el.resolve_color(raw["stroke"], "stroke")
    if raw.get("text_color") not in (None, ""):
        style["text_color"] = el.resolve_color(raw["text_color"], "stroke")
    if raw.get("fill_style") not in (None, ""):
        style["fill_style"] = el.Palette.choice(
            raw["fill_style"], el.Palette.FILL_STYLES, "fill_style"
        )
    if raw.get("stroke_width") not in (None, ""):
        style["stroke_width"] = el.Palette.stroke_width(raw["stroke_width"])
    if raw.get("stroke_style") not in (None, ""):
        style["stroke_style"] = el.Palette.choice(
            raw["stroke_style"], el.Palette.STROKE_STYLES, "stroke_style"
        )
    rough = raw.get("roughness", raw.get("sloppiness"))
    if rough not in (None, ""):
        style["roughness"] = el.Palette.roughness(rough)
    if raw.get("opacity") not in (None, ""):
        style["opacity"] = int(max(0, min(100, el.number_of(raw["opacity"], "opacity"))))
    if raw.get("font") not in (None, ""):
        style["font"] = el.Palette.font(raw["font"])
    if raw.get("size") not in (None, ""):
        style["size"] = el.Palette.font_size(raw["size"])
    if raw.get("align") not in (None, ""):
        style["align"] = el.Palette.choice(raw["align"], ("left", "center", "right"), "align")
    if raw.get("rounded") is not None:
        style["rounded"] = bool(raw["rounded"])
    return style


def colors_for(kind: str, style: dict[str, Any]) -> tuple[str, str]:
    """Stroke and fill of a ``kind`` under ``style``."""
    if kind == "note":
        stroke, fill = el.NOTE_STROKE, el.NOTE_FILL
        if style.get("color"):
            stroke = el.resolve_color(style["color"], "stroke")
            fill = el.resolve_color(style["color"], "fill")
    elif kind in KIND_COLOR or style.get("color"):
        name = style.get("color") or KIND_COLOR[kind]
        stroke = el.resolve_color(name, "stroke")
        fill = el.resolve_color(f"light {name}", "fill") if _is_palette(name) else el.TRANSPARENT
    else:
        stroke, fill = el.BLACK, el.TRANSPARENT
    return style.get("stroke", stroke), style.get("fill", fill)


def _is_palette(name: str) -> bool:
    value = str(name).strip().lower()
    return value in el.PALETTE or value in (
        "grey",
        "purple",
        "magenta",
        "amber",
        "gold",
        "brown",
        "navy",
        "turquoise",
        "mint",
    )


def label_font(style: dict[str, Any], default_size: float = LABEL_SIZE) -> tuple[float, int]:
    return float(style.get("size", default_size)), int(style.get("font", el.FONT_HAND))


def node_size(kind: str, label: str, style: dict[str, Any]) -> tuple[float, float]:
    """The size a node of ``kind`` needs for ``label``, on the grid."""
    size, family = label_font(style)
    if kind == "text":
        wrapped = el.wrap_text(label, MAX_TEXT_WIDTH["text"], size, family)
        return el.estimate_text(wrapped, size, family)
    if kind == "image":
        return MIN_SIZE["image"]
    if kind == "note":
        _, height = el.fit_container(
            "rectangle",
            label or " ",
            font_size=size,
            font_family=family,
            min_size=MIN_SIZE["note"],
            max_text_width=MAX_TEXT_WIDTH["note"],
        )
        return NOTE_WIDTH, height
    width, height = el.fit_container(
        KIND_SHAPE[kind],
        label or " ",
        font_size=size,
        font_family=family,
        min_size=MIN_SIZE[kind],
        max_text_width=MAX_TEXT_WIDTH[kind],
    )
    if kind == "circle":
        width = height = max(width, height)
    return width, height


def build_node(
    kind: str,
    label: str,
    *,
    x: float,
    y: float,
    w: float,
    h: float,
    style: dict[str, Any],
    now_ms: int,
    element_id: str | None = None,
    label_id: str | None = None,
    file_id: str | None = None,
) -> list[dict[str, Any]]:
    """The elements of one node: a shape and its label, a text, or an image."""
    size, family = label_font(style)
    common = {
        "stroke_width": style.get("stroke_width", 1 if kind == "note" else el.DEFAULT_STROKE_WIDTH),
        "stroke_style": style.get("stroke_style", "solid"),
        "roughness": style.get("roughness", el.DEFAULT_ROUGHNESS),
        "opacity": style.get("opacity", 100),
    }
    if kind == "text":
        color = (
            style.get("text_color")
            or style.get("stroke")
            or (el.resolve_color(style["color"], "stroke") if style.get("color") else el.BLACK)
        )
        wrapped = el.wrap_text(label, max(w, size), size, family) if w else label
        item = el.text(
            wrapped,
            x=x,
            y=y,
            now_ms=now_ms,
            font_size=size,
            font_family=family,
            align=style.get("align", "left"),
            color=color,
            element_id=element_id,
            original=wrapped,
            opacity=common["opacity"],
        )
        return [item]
    if kind == "image":
        if not file_id:
            raise ValueError("an image needs 'file': the id of a picture already on the board")
        return [
            el.image(
                file_id,
                x=x,
                y=y,
                width=w,
                height=h,
                now_ms=now_ms,
                element_id=element_id,
                opacity=common["opacity"],
            )
        ]
    stroke, fill = colors_for(kind, style)
    roundness: dict[str, int] | None
    if kind == "rect" or style.get("rounded") is False:
        roundness = None
    elif KIND_SHAPE[kind] == "rectangle":
        roundness = el.ROUND_ADAPTIVE
    elif KIND_SHAPE[kind] == "diamond":
        roundness = el.ROUND_PROPORTIONAL
    else:
        roundness = None
    box = el.shape(
        KIND_SHAPE[kind],
        x=x,
        y=y,
        width=w,
        height=h,
        now_ms=now_ms,
        element_id=element_id,
        stroke=stroke,
        fill=fill,
        fill_style=style.get("fill_style", "solid"),
        roundness=roundness,
        **common,
    )
    out = [box]
    if label:
        out.append(
            el.label_for(
                box,
                label,
                now_ms=now_ms,
                font_size=size,
                font_family=family,
                color=style.get("text_color", el.BLACK),
                align=style.get("align", "center"),
                element_id=label_id,
            )
        )
    return out


# --- arrows -------------------------------------------------------------------------------

_BLOCKING: Final[frozenset[str]] = frozenset({"rectangle", "ellipse", "diamond", "image", "text"})


def _segment_hits(p: tuple[float, float], q: tuple[float, float], rect: lay.Rect) -> bool:
    """Whether the segment ``p``–``q`` crosses ``rect`` (Liang-Barsky clipping)."""
    x0, y0, x1, y1 = rect
    dx, dy = q[0] - p[0], q[1] - p[1]
    t0, t1 = 0.0, 1.0
    for edge_p, edge_q in ((-dx, p[0] - x0), (dx, x1 - p[0]), (-dy, p[1] - y0), (dy, y1 - p[1])):
        if abs(edge_p) < 1e-12:
            if edge_q < 0:
                return False
            continue
        t = edge_q / edge_p
        if edge_p < 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
        if t0 > t1:
            return False
    return True


def obstacle_rects(elements: list[dict[str, Any]], skip: set[str]) -> list[lay.Rect]:
    """Boxes an arrow should not cross: live shapes, pictures and free texts."""
    rects: list[lay.Rect] = []
    for item in elements:
        if item.get("isDeleted") or item.get("id") in skip or item.get("type") not in _BLOCKING:
            continue
        if item.get("type") == "text" and item.get("containerId"):
            continue
        x0, y0, x1, y1 = el.box_of(item)
        rects.append((x0 - 6, y0 - 6, x1 + 6, y1 + 6))
    return rects


def route(
    start: dict[str, Any],
    end: dict[str, Any],
    obstacles: list[lay.Rect],
    *,
    bend: float = 0.0,
) -> list[tuple[float, float]]:
    """Points of an arrow from ``start`` to ``end``: straight when that is clear,
    else bent around what is in the way (the editor draws three points as a curve)."""
    sx, sy, ex, ey = (
        float(start["x"]) + float(start["width"]) / 2,
        float(start["y"]) + float(start["height"]) / 2,
        float(end["x"]) + float(end["width"]) / 2,
        float(end["y"]) + float(end["height"]) / 2,
    )
    length = math.hypot(ex - sx, ey - sy) or 1.0
    px, py = -(ey - sy) / length, (ex - sx) / length

    def path(offset: float) -> list[tuple[float, float]]:
        if abs(offset) < 1e-6:
            a = el.outline_point(start, (ex, ey), ARROW_GAP)
            b = el.outline_point(end, (sx, sy), ARROW_GAP)
            return [a, b]
        mid = ((sx + ex) / 2 + px * offset, (sy + ey) / 2 + py * offset)
        a = el.outline_point(start, mid, ARROW_GAP)
        b = el.outline_point(end, mid, ARROW_GAP)
        return [a, mid, b]

    def clear(points: list[tuple[float, float]]) -> bool:
        return not any(
            _segment_hits(points[i], points[i + 1], rect)
            for i in range(len(points) - 1)
            for rect in obstacles
        )

    preferred = path(bend)
    if clear(preferred):
        return preferred
    for share in (0.2, -0.2, 0.35, -0.35, 0.5, -0.5, 0.8, -0.8):
        offset = bend + share * max(120.0, length)
        candidate = path(offset)
        if clear(candidate):
            return candidate
    return preferred


def arrow_between(
    start: dict[str, Any],
    end: dict[str, Any],
    *,
    now_ms: int,
    obstacles: list[lay.Rect],
    label: str = "",
    style: dict[str, Any] | None = None,
    start_head: str | None = None,
    end_head: str | None = "arrow",
    kind: str = "arrow",
    element_id: str | None = None,
    bend: float = 0.0,
) -> list[dict[str, Any]]:
    """An arrow (or line) bound to ``start`` and ``end``, plus its label.

    Both shapes record the arrow in their ``boundElements``.
    """
    style = style or {}
    points = route(start, end, obstacles, bend=bend)
    stroke = style.get("stroke") or (
        el.resolve_color(style["color"], "stroke") if style.get("color") else el.BLACK
    )
    arrow = el.linear(
        kind,
        points,
        now_ms=now_ms,
        element_id=element_id,
        stroke=stroke,
        stroke_width=style.get("stroke_width", el.DEFAULT_STROKE_WIDTH),
        stroke_style=style.get("stroke_style", "solid"),
        roughness=style.get("roughness", el.DEFAULT_ROUGHNESS),
        opacity=style.get("opacity", 100),
        start_head=start_head,
        end_head=end_head,
        curved=len(points) > 2,
    )
    arrow["startBinding"] = el.binding(start["id"], ARROW_GAP)
    arrow["endBinding"] = el.binding(end["id"], ARROW_GAP)
    el.add_bound(start, arrow["id"], "arrow")
    el.add_bound(end, arrow["id"], "arrow")
    out = [arrow]
    if label:
        size, family = label_font(style, EDGE_LABEL_SIZE)
        out.append(
            el.label_for(
                arrow,
                label,
                now_ms=now_ms,
                font_size=size,
                font_family=family,
                color=style.get("text_color", el.BLACK),
            )
        )
    return out


def edge_heads(arrow: Any, start: Any = None, end: Any = None) -> tuple[str | None, str | None]:
    """Arrowheads from ``arrow`` (end, start, both, none) and explicit heads."""
    name = str(arrow or "end").strip().lower()
    if name not in ("end", "start", "both", "none", "forward", "back", "backward", "two-way"):
        raise ValueError("arrow must be end, start, both or none")
    head_start = "arrow" if name in ("start", "both", "back", "backward", "two-way") else None
    head_end = "arrow" if name in ("end", "both", "forward", "two-way") else None
    if start is not None:
        head_start = el.Palette.arrowhead(start)
    if end is not None:
        head_end = el.Palette.arrowhead(end)
    return head_start, head_end


def edge_style(raw: dict[str, Any]) -> dict[str, Any]:
    """An edge's style: ``style`` (solid, dashed, dotted, bold) plus the common keys."""
    style = parse_style({k: v for k, v in raw.items() if k in _STYLE_KEYS})
    line = str(raw.get("style") or "").strip().lower()
    if line in ("dashed", "dotted", "solid"):
        style.setdefault("stroke_style", line)
    elif line in ("bold", "thick", "strong"):
        style.setdefault("stroke_width", 4.0)
    elif line:
        raise ValueError("an edge's style must be solid, dashed, dotted or bold")
    return style


# --- diagrams -----------------------------------------------------------------------------


def _text(value: Any, limit: int = MAX_LABEL_CHARS) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return ""
    return shell.clean_block(str(value), limit)


def _ident(value: Any, where: str) -> str:
    try:
        return el.check_model_id(value)
    except ValueError as exc:
        raise ValueError(f"{where}: {exc}") from None


def normalize_diagram(raw: Any) -> dict[str, Any]:
    """A diagram checked and completed; raises ``ValueError`` naming the place to fix.

    ``{"nodes": [{"id", "label", "type", "color", ...} | "label"], "edges":
    [{"from", "to", "label", "style", "arrow"}], "groups": [{"id", "label",
    "nodes": [ids]}], "direction": LR|RL|TB|BT, "layout": flow|tree|mindmap|grid,
    "root", "title"}``. A node may also name its ``group``.
    """
    if not isinstance(raw, dict):
        raise ValueError("a diagram is an object with 'nodes' (and 'edges', 'groups')")
    nodes_raw = raw.get("nodes")
    if not isinstance(nodes_raw, list) or not nodes_raw:
        raise ValueError(
            '\'nodes\' must be a list of 1 to 300 nodes, e.g. [{"id": "a", "label": "Start"}]'
        )
    if len(nodes_raw) > MAX_DIAGRAM_NODES:
        raise ValueError(f"a diagram holds at most {MAX_DIAGRAM_NODES} nodes; split it")
    nodes: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(nodes_raw):
        where = f"nodes[{index}]"
        if isinstance(item, (str, int, float)) and not isinstance(item, bool):
            item = {"label": str(item)}
        if not isinstance(item, dict):
            raise ValueError(f"{where} must be an object or a label")
        node_id = _ident(item["id"], where) if item.get("id") not in (None, "") else f"n{index + 1}"
        if node_id in seen:
            raise ValueError(f"{where}: the id {node_id!r} is used twice")
        seen.add(node_id)
        try:
            kind = kind_of(item.get("type") or item.get("shape") or item.get("kind"))
            style = parse_style(item)
        except ValueError as exc:
            raise ValueError(f"{where}: {exc}") from None
        if kind not in NODE_KINDS:
            raise ValueError(f"{where}: a diagram node is one of {', '.join(NODE_KINDS)}")
        label = _text(item.get("label", item.get("text", "")))
        node: dict[str, Any] = {"id": node_id, "kind": kind, "label": label, "style": style}
        if kind == "image":
            node["file"] = str(item.get("file") or "")
        for key in ("w", "h", "x", "y"):
            alias = {"w": "width", "h": "height"}.get(key, key)
            value = item.get(key, item.get(alias))
            if value not in (None, ""):
                try:
                    number = el.number_of(value, key)
                except ValueError as exc:
                    raise ValueError(f"{where}: {exc}") from None
                node[key] = max(20.0, min(4000.0, number)) if key in ("w", "h") else number
        if item.get("group") not in (None, ""):
            node["group"] = str(item["group"])
        if item.get("link"):
            node["link"] = shell.safe_link(item["link"]) or None
        nodes.append(node)
    groups: list[dict[str, Any]] = []
    group_ids: set[str] = set()
    groups_raw = raw.get("groups") or []
    if not isinstance(groups_raw, list):
        raise ValueError("'groups' must be a list of {id, label, nodes}")
    if len(groups_raw) > MAX_DIAGRAM_GROUPS:
        raise ValueError(f"a diagram holds at most {MAX_DIAGRAM_GROUPS} groups")
    member_of: dict[str, str] = {}
    for index, item in enumerate(groups_raw):
        where = f"groups[{index}]"
        if not isinstance(item, dict):
            raise ValueError(f"{where} must be an object {{id, label, nodes}}")
        label = _text(item.get("label", item.get("name", item.get("title", ""))), 120)
        group_id = (
            _ident(item["id"], where)
            if item.get("id") not in (None, "")
            else re.sub(r"[^A-Za-z0-9_]+", "_", label).strip("_")[:40] or f"g{index + 1}"
        )
        if group_id in seen or group_id in group_ids:
            raise ValueError(f"{where}: the id {group_id!r} is already used")
        group_ids.add(group_id)
        members = item.get("nodes") or []
        if not isinstance(members, list):
            raise ValueError(f"{where}: 'nodes' must be a list of node ids")
        for member in members:
            name = str(member)
            if name not in seen:
                raise ValueError(f"{where}: no node with the id {name!r}")
            if name in member_of and member_of[name] != group_id:
                raise ValueError(f"{where}: node {name!r} is already in group {member_of[name]!r}")
            member_of[name] = group_id
        group: dict[str, Any] = {"id": group_id, "label": label}
        for key in ("x", "y", "w", "h"):
            if item.get(key) not in (None, ""):
                try:
                    group[key] = el.number_of(item[key], key)
                except ValueError as exc:
                    raise ValueError(f"{where}: {exc}") from None
        groups.append(group)
    by_label = {g["label"]: g["id"] for g in groups if g["label"]}
    for node in nodes:
        name = node.pop("group", None)
        if name is None:
            continue
        target = name if name in group_ids else by_label.get(name)
        if target is None:
            # A group named only on its nodes gets a frame of its own.
            target = re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_")[:40] or f"g{len(groups) + 1}"
            while target in seen or target in group_ids:
                target += "_"
            group_ids.add(target)
            by_label[name] = target
            groups.append({"id": target, "label": shell.clean(name, 120)})
        member_of.setdefault(node["id"], target)
    for group in groups:
        group["nodes"] = [n["id"] for n in nodes if member_of.get(n["id"]) == group["id"]]
    edges: list[dict[str, Any]] = []
    edges_raw = raw.get("edges") or raw.get("links") or []
    if not isinstance(edges_raw, list):
        raise ValueError("'edges' must be a list of {from, to}")
    if len(edges_raw) > MAX_DIAGRAM_EDGES:
        raise ValueError(f"a diagram holds at most {MAX_DIAGRAM_EDGES} edges")
    known = seen | group_ids
    for index, item in enumerate(edges_raw):
        where = f"edges[{index}]"
        if isinstance(item, (list, tuple)) and len(item) in (2, 3):
            item = {
                "from": item[0],
                "to": item[1],
                **({"label": item[2]} if len(item) == 3 else {}),
            }
        if not isinstance(item, dict):
            raise ValueError(f"{where} must be an object {{from, to}}")
        start, end = str(item.get("from", "")), str(item.get("to", ""))
        for side, name in (("from", start), ("to", end)):
            if name not in known:
                raise ValueError(f"{where}: '{side}' names no node or group: {name!r}")
        if start == end:
            raise ValueError(f"{where}: an edge must join two different nodes")
        try:
            style = edge_style(item)
            heads = edge_heads(item.get("arrow"), item.get("start"), item.get("end"))
        except ValueError as exc:
            raise ValueError(f"{where}: {exc}") from None
        edges.append(
            {
                "from": start,
                "to": end,
                "label": _text(item.get("label", ""), 200),
                "style": style,
                "heads": heads,
            }
        )
    layout_kind = str(raw.get("layout") or "flow").strip().lower()
    if layout_kind not in lay.KINDS:
        raise ValueError(f"'layout' must be one of {', '.join(lay.KINDS)}")
    direction = lay.direction_of(raw.get("direction"), "TB" if layout_kind == "tree" else "LR")
    root = str(raw["root"]) if raw.get("root") not in (None, "") else None
    if root is not None and root not in seen:
        raise ValueError(f"'root' names no node: {root!r}")
    return {
        "normalized": True,
        "nodes": nodes,
        "edges": edges,
        "groups": [g for g in groups if g["nodes"]],
        "layout": layout_kind,
        "direction": direction,
        "root": root,
        "title": _text(raw.get("title", ""), 200),
    }


def _uniform_sizes(nodes: list[dict[str, Any]]) -> dict[str, tuple[float, float]]:
    """One size per kind (and font size): the largest a label needs, within the caps."""
    need = {n["id"]: node_size(n["kind"], n["label"], n["style"]) for n in nodes}
    shared: dict[tuple[str, float], tuple[float, float]] = {}
    for n in nodes:
        if n["kind"] in ("text", "image"):
            continue
        key = (n["kind"], float(n["style"].get("size", LABEL_SIZE)))
        w, h = need[n["id"]]
        old = shared.get(key, (0.0, 0.0))
        shared[key] = (max(old[0], w), max(old[1], h))
    sizes: dict[str, tuple[float, float]] = {}
    for n in nodes:
        if n["kind"] in ("text", "image"):
            w, h = need[n["id"]]
        else:
            w, h = shared[(n["kind"], float(n["style"].get("size", LABEL_SIZE)))]
        sizes[n["id"]] = (float(n.get("w", w)), float(n.get("h", h)))
    return sizes


def _group_columns(most: int) -> int | None:
    """Columns of a group of loose notes, by the fullest group of the diagram, so the
    frames of one diagram are equally wide."""
    if most <= 3:
        return None
    return 2 if most <= 8 else 3


def layout_diagram(diagram: dict[str, Any]) -> dict[str, Any]:
    """Positions for a normalized diagram, from (0, 0).

    Returns ``{"nodes": {id: (x, y, w, h)}, "frames": {id: (x, y, w, h)},
    "title": (x, y) | None, "size": (w, h)}``. A group is laid out inside its
    frame first (as a flow when its members are linked, else as a grid), then
    the frames and the ungrouped nodes are laid out together with the edges
    lifted to them. Nodes with their own ``x``/``y`` stay there and the rest
    goes below them.
    """
    nodes = diagram["nodes"]
    sizes = _uniform_sizes(nodes)
    member_of = {member: g["id"] for g in diagram["groups"] for member in g["nodes"]}
    pinned = [n for n in nodes if "x" in n and "y" in n and n["id"] not in member_of]
    pinned_ids = {n["id"] for n in pinned}
    edges = [(e["from"], e["to"]) for e in diagram["edges"]]
    labeled = any(e["label"] for e in diagram["edges"])
    gap = lay.FLOW_GAP_LABELED if labeled else lay.FLOW_GAP
    direction, kind = diagram["direction"], diagram["layout"]
    columns = _group_columns(max((len(g["nodes"]) for g in diagram["groups"]), default=0))
    inner: dict[str, list[lay.Box]] = {}
    top_boxes: list[lay.Box] = []
    frame_boxes: dict[str, lay.Box] = {}
    pinned_frames: list[lay.Box] = []
    for group in diagram["groups"]:
        members = [lay.Box(n, *sizes[n]) for n in group["nodes"]]
        inside = set(group["nodes"])
        internal = [(s, e) for s, e in edges if s in inside and e in inside]
        if internal and kind != "grid":
            w, h = lay.arrange(
                members,
                internal,
                kind=kind,
                direction=direction,
                gap=gap,
                root=diagram["root"] if diagram["root"] in inside else None,
            )
        else:
            w, h = lay.grid(members, columns=columns or (None if kind == "grid" else len(members)))
        name_w = len(group["label"]) * 9 + 2 * FRAME_PAD
        box = lay.Box(
            group["id"],
            max(w + 2 * FRAME_PAD, name_w, group.get("w", 0)),
            max(h + 2 * FRAME_PAD, group.get("h", 0)),
            top=FRAME_NAME_ROOM,
        )
        for member in members:
            member.x += FRAME_PAD + (box.w - 2 * FRAME_PAD - w) / 2
            member.y += FRAME_PAD
        inner[group["id"]] = members
        frame_boxes[group["id"]] = box
        if "x" in group and "y" in group:
            box.x, box.y = float(group["x"]), float(group["y"])
            pinned_frames.append(box)
        else:
            top_boxes.append(box)
    for n in nodes:
        if n["id"] in member_of or n["id"] in pinned_ids:
            continue
        top_boxes.append(lay.Box(n["id"], *sizes[n["id"]]))
    lifted: list[tuple[str, str]] = []
    for s, e in edges:
        a, b = member_of.get(s, s), member_of.get(e, e)
        if a != b and (a, b) not in lifted:
            lifted.append((a, b))
    root = member_of.get(diagram["root"], diagram["root"]) if diagram["root"] else None
    if top_boxes:
        lay.arrange(top_boxes, lifted, kind=kind, direction=direction, gap=gap, root=root)
    title_at: tuple[float, float] | None = None
    if diagram["title"]:
        size = el.FONT_SIZES["xl"]
        _, title_h = el.estimate_text(diagram["title"], size, el.FONT_HAND)
        for box in top_boxes:
            box.y += title_h + lay.CROSS_GAP
        title_at = (0.0, 0.0)
    fixed = [*pinned_frames]
    for n in pinned:
        w, h = sizes[n["id"]]
        fixed.append(lay.Box(n["id"], w, h, x=float(n["x"]), y=float(n["y"])))
    if fixed and top_boxes:
        dx = min(b.x for b in fixed)
        dy = max(b.y + b.h for b in fixed) + lay.ROW_GAP + FRAME_NAME_ROOM
        for box in top_boxes:
            box.x += dx
            box.y += dy
        if title_at is not None:
            title_at = (dx, dy - lay.ROW_GAP / 2)
    placed: dict[str, tuple[float, float, float, float]] = {}
    frames: dict[str, tuple[float, float, float, float]] = {}
    for box in [*top_boxes, *fixed]:
        if box.key in frame_boxes:
            fx, fy = lay.snap(box.x), lay.snap(box.y)
            frames[box.key] = (fx, fy, box.w, box.h)
            for member in inner[box.key]:
                placed[member.key] = (
                    lay.snap(fx + member.x),
                    lay.snap(fy + member.y),
                    member.w,
                    member.h,
                )
        else:
            placed[box.key] = (lay.snap(box.x), lay.snap(box.y), box.w, box.h)
    rects = [*placed.values(), *frames.values()]
    width = max((r[0] + r[2] for r in rects), default=0.0)
    height = max((r[1] + r[3] for r in rects), default=0.0)
    return {"nodes": placed, "frames": frames, "title": title_at, "size": (width, height)}


def unique_ids(diagram: dict[str, Any], taken: set[str]) -> dict[str, str]:
    """A board id for every node and group id of ``diagram`` that is not in ``taken``.

    A diagram's ids are names inside it ("A", "B"); when the board already has
    one, the new one gets a suffix, and the caller reports the mapping.
    """
    mapping: dict[str, str] = {}
    used = set(taken)
    names = [n["id"] for n in diagram["nodes"]] + [g["id"] for g in diagram["groups"]]
    for name in names:
        final = name
        counter = 2
        while final in used:
            final = f"{name}-{counter}"[:40]
            counter += 1
        used.add(final)
        mapping[name] = final
    return mapping


def diagram_to_elements(
    diagram: Any,
    *,
    origin: tuple[float, float] = (0.0, 0.0),
    now_ms: int | None = None,
    taken: set[str] | frozenset[str] = frozenset(),
    obstacles: list[lay.Rect] | None = None,
    laid_out: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """The elements of ``diagram`` placed with its top-left corner at ``origin``.

    ``diagram`` may be raw (it is normalized here) or already normalized.
    Returns the elements in drawing order (a frame after its members, a label
    after its shape) and the map from the diagram's ids to the board's ids.
    """
    when = now_ms if now_ms is not None else el.now_millis()
    spec = (
        diagram
        if isinstance(diagram, dict) and diagram.get("normalized")
        else normalize_diagram(diagram)
    )
    placement = laid_out or layout_diagram(spec)
    ids = unique_ids(spec, set(taken))
    ox, oy = lay.snap(origin[0]), lay.snap(origin[1])
    member_of = {member: g["id"] for g in spec["groups"] for member in g["nodes"]}
    built: dict[str, list[dict[str, Any]]] = {}
    for node in spec["nodes"]:
        x, y, w, h = placement["nodes"][node["id"]]
        parts = build_node(
            node["kind"],
            node["label"],
            x=ox + x,
            y=oy + y,
            w=w,
            h=h,
            style=node["style"],
            now_ms=when,
            element_id=ids[node["id"]],
            file_id=node.get("file") or None,
        )
        if node.get("link"):
            parts[0]["link"] = node["link"]
        built[node["id"]] = parts
    frames: dict[str, dict[str, Any]] = {}
    for group in spec["groups"]:
        x, y, w, h = placement["frames"][group["id"]]
        frames[group["id"]] = el.frame(
            group["label"] or None,
            x=ox + x,
            y=oy + y,
            width=w,
            height=h,
            now_ms=when,
            element_id=ids[group["id"]],
        )
        for member in group["nodes"]:
            for part in built[member]:
                part["frameId"] = ids[group["id"]]
    shapes = {name: parts[0] for name, parts in built.items()}
    targets = {**shapes, **frames}
    all_new = [p for parts in built.values() for p in parts]
    blockers = list(obstacles or []) + obstacle_rects(all_new, set())
    arrows_in: dict[str, list[dict[str, Any]]] = {g["id"]: [] for g in spec["groups"]}
    arrows_out: list[dict[str, Any]] = []
    pair_count: dict[frozenset[str], int] = {}
    used = set(taken) | set(ids.values())
    for edge in spec["edges"]:
        a, b = targets[edge["from"]], targets[edge["to"]]
        pair = frozenset((edge["from"], edge["to"]))
        nth = pair_count.get(pair, 0)
        pair_count[pair] = nth + 1
        bend = 0.0 if nth == 0 else (40.0 * ((nth + 1) // 2)) * (1 if nth % 2 else -1)
        own = {
            a["id"],
            b["id"],
            *(p["id"] for p in built.get(edge["from"], [])),
            *(p["id"] for p in built.get(edge["to"], [])),
        }
        skip_rects = [el.box_of(p) for p in all_new if p["id"] in own]
        path_obstacles = [r for r in blockers if not any(_inside(r, s) for s in skip_rects)]
        if a.get("type") == "frame" or b.get("type") == "frame":
            path_obstacles = []
        parts = arrow_between(
            a,
            b,
            now_ms=when,
            obstacles=path_obstacles,
            label=edge["label"],
            style=edge["style"],
            start_head=edge["heads"][0],
            end_head=edge["heads"][1],
            bend=bend,
            element_id=_arrow_id(a["id"], b["id"], used),
        )
        group_a, group_b = member_of.get(edge["from"]), member_of.get(edge["to"])
        if group_a is not None and group_a == group_b:
            for part in parts:
                part["frameId"] = ids[group_a]
            arrows_in[group_a].extend(parts)
        else:
            arrows_out.extend(parts)
    ordered: list[dict[str, Any]] = []
    if placement.get("title") is not None and spec["title"]:
        tx, ty = placement["title"]
        ordered.append(
            el.text(
                spec["title"],
                x=ox + tx,
                y=oy + ty,
                now_ms=when,
                font_size=el.FONT_SIZES["xl"],
                font_family=el.FONT_HAND,
            )
        )
    for group in spec["groups"]:
        for member in group["nodes"]:
            ordered.extend(built[member])
        ordered.extend(arrows_in[group["id"]])
        ordered.append(frames[group["id"]])
    for node in spec["nodes"]:
        if node["id"] not in member_of:
            ordered.extend(built[node["id"]])
    ordered.extend(arrows_out)
    return ordered, ids


def _arrow_id(start: str, end: str, used: set[str]) -> str:
    """A readable id for the arrow from ``start`` to ``end`` (``a:b``), unique on the board."""
    stem = f"{start}:{end}"[:56]
    ident, counter = stem, 2
    while ident in used:
        ident = f"{stem}:{counter}"
        counter += 1
    used.add(ident)
    return ident


def _inside(rect: lay.Rect, outer: lay.Rect) -> bool:
    return (
        rect[0] >= outer[0] - 8
        and rect[1] >= outer[1] - 8
        and rect[2] <= outer[2] + 8
        and rect[3] <= outer[3] + 8
    )


# --- the old grammar -----------------------------------------------------------------------

LEGACY_MAX_ITEMS: Final[int] = 300
LEGACY_MAX_LINKS: Final[int] = 300
_LEGACY_TYPES: Final[tuple[str, ...]] = ("note", "text", "shape", "frame", "image")
_LEGACY_COLORS: Final[dict[str, str]] = {
    "yellow": "yellow",
    "pink": "pink",
    "blue": "blue",
    "green": "green",
    "violet": "violet",
    "orange": "orange",
    "gray": "gray",
    "grey": "gray",
    "purple": "violet",
    "amber": "yellow",
    "red": "red",
}
_LEGACY_SHAPES: Final[dict[str, str]] = {
    "rect": "box",
    "rectangle": "box",
    "box": "box",
    "pill": "rounded",
    "capsule": "rounded",
    "rounded": "rounded",
    "ellipse": "ellipse",
    "circle": "ellipse",
    "oval": "ellipse",
    "diamond": "diamond",
    "rhombus": "diamond",
    "decision": "diamond",
}
_MARK_LINK_RE: Final = re.compile(r"\[([^\]\n]+)\]\(([^)\s]+)\)")
_NEED_ITEMS: Final[str] = (
    'A whiteboard needs a scene ({"format": "scene", "elements": [...]}) or, in the older '
    'grammar, "items": a list of 1 to 300 objects such as {"id": "a", "text": "One idea", '
    '"group": "Ideas"}, plus optional "links" ([{"from": "a", "to": "b"}]).'
)


def _plain(value: Any) -> str:
    """Text without its inline marks (bold, italic, code, links), as a reader sees it."""
    text = _MARK_LINK_RE.sub(r"\1", str(value or ""))
    return text.replace("**", "").replace("`", "").replace("*", "")


def _scalar(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return ""
    return str(value)


def _image_size(src: str) -> tuple[float, float]:
    """A box for an embedded picture in its own proportions (4:3 when unreadable)."""
    width_px = height_px = 0
    payload = "".join(src.partition(",")[2].split())[:87_384]
    try:
        data = base64.b64decode(payload[: len(payload) // 4 * 4])
    except (binascii.Error, ValueError):  # not readable: the default proportions
        data = b""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        width_px, height_px = int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    elif data[:6] in (b"GIF87a", b"GIF89a") and len(data) >= 10:
        width_px = int.from_bytes(data[6:8], "little")
        height_px = int.from_bytes(data[8:10], "little")
    elif data[:2] == b"\xff\xd8":
        at = 2
        while at + 9 <= len(data) and data[at] == 0xFF:
            marker = data[at + 1]
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                height_px = int.from_bytes(data[at + 5 : at + 7], "big")
                width_px = int.from_bytes(data[at + 7 : at + 9], "big")
                break
            at += 2 + int.from_bytes(data[at + 2 : at + 4], "big")
    ratio = max(0.4, min(3.0, width_px / height_px)) if width_px > 0 and height_px > 0 else 4 / 3
    return 240.0, lay.snap(240.0 / ratio) or 20.0


def legacy_to_scene(
    spec: Any,
    *,
    store_image: Callable[[str], tuple[str, str] | None] | None = None,
    now_ms: int | None = None,
) -> dict[str, Any]:
    """A scene from the old grammar (``items``, ``links``, ``layout``).

    Notes become yellow sticky boxes, shapes keep their form, items that share
    a ``group`` are gathered into one frame (a ``frame`` item gives it its
    title), links become arrows bound to both ends, and leading text items
    that belong to nothing are the board's heading. An item's own ``x``/``y``
    is kept; the rest is laid out below such items. A picture (a ``data:`` URI)
    is handed to ``store_image``, which keeps the bytes and returns
    ``(file_id, mime_type)``; without it, or when it returns nothing, the
    picture becomes a labelled placeholder. Raises ``NodeError`` when the spec
    holds no item.
    """
    if not isinstance(spec, dict) or not isinstance(spec.get("items"), (list, tuple)):
        raise NodeError(_NEED_ITEMS)
    when = now_ms if now_ms is not None else el.now_millis()
    raws = [item for item in spec["items"] if isinstance(item, (dict, str))][:LEGACY_MAX_ITEMS]
    if not raws:
        raise NodeError(_NEED_ITEMS)
    items: list[dict[str, Any]] = []
    taken: set[str] = set()
    for index, raw in enumerate(raws):
        if isinstance(raw, str):
            raw = {"text": raw}
        wanted = shell.clean(_scalar(raw.get("id")), 40)
        try:
            item_id = el.check_model_id(wanted) if wanted else ""
        except ValueError:  # an id the editor cannot keep: a generated one instead
            item_id = re.sub(r"[^A-Za-z0-9_.:-]+", "-", wanted).strip("-")[:40]
        if not item_id or item_id in taken:
            stem = item_id or "i"
            counter = index + 1
            item_id = f"{stem}{counter}" if not wanted else f"{stem}-{counter}"
            while item_id in taken:
                counter += 1
                item_id = f"{stem}{counter}" if not wanted else f"{stem}-{counter}"
        taken.add(item_id)
        shape_name = _LEGACY_SHAPES.get(_scalar(raw.get("shape")).strip().lower(), "")
        picture = shell.safe_image(_scalar(raw.get("image")))
        kind = _scalar(raw.get("type")).strip().lower()
        if kind not in _LEGACY_TYPES:
            kind = "shape" if shape_name else "image" if picture else "note"
        text = _plain(shell.clean_block(_scalar(raw.get("text")), 400)) or _plain(
            shell.clean(_scalar(raw.get("title")), 80)
        )
        title = shell.clean(_scalar(raw.get("title")), 80) or shell.clean(text, 80)
        color = _LEGACY_COLORS.get(_scalar(raw.get("color")).strip().lower(), "")
        item: dict[str, Any] = {
            "id": item_id,
            "type": kind,
            "text": text,
            "title": title,
            "color": color,
            "shape": shape_name or "box",
            "image": picture,
            "group": shell.clean(_scalar(raw.get("group")), 60),
        }
        x, y = shell.number(raw.get("x")), shell.number(raw.get("y"))
        if x is not None and y is not None:
            item["x"] = max(-20_000.0, min(20_000.0, x))
            item["y"] = max(-20_000.0, min(20_000.0, y))
        for key in ("w", "h"):
            size = shell.number(raw.get(key))
            if size is not None:
                item[key] = max(24.0, min(2_400.0, size))
        items.append(item)
    by_id = {item["id"]: item for item in items}
    links: list[dict[str, Any]] = []
    for entry in shell.as_list(spec.get("links"), LEGACY_MAX_LINKS * 8):
        if not isinstance(entry, dict):
            continue
        start = shell.clean(_scalar(entry.get("from")), 40)
        end = shell.clean(_scalar(entry.get("to")), 40)
        if start not in by_id or end not in by_id or start == end:
            continue
        if by_id[start]["type"] == "frame" or by_id[end]["type"] == "frame":
            continue
        link: dict[str, Any] = {
            "from": start,
            "to": end,
            "label": shell.clean(_scalar(entry.get("label")), 60),
        }
        line_style = _scalar(entry.get("style")).strip().lower()
        if line_style == "dashed":
            link["style"] = "dashed"
        elif line_style == "line":
            link["arrow"] = "none"
        links.append(link)
        if len(links) == LEGACY_MAX_LINKS:
            break
    linked = {link["from"] for link in links} | {link["to"] for link in links}
    # Frames and their members.
    frames = [item for item in items if item["type"] == "frame"]
    frame_by_title = {f["title"]: f for f in reversed(frames) if f["title"]}
    groups: dict[str, dict[str, Any]] = {}
    for frame_item in frames:
        group = {"id": frame_item["id"], "label": frame_item["title"], "nodes": []}
        if "x" in frame_item and "y" in frame_item:
            group.update(x=frame_item["x"], y=frame_item["y"])
            for key in ("w", "h"):
                if key in frame_item:
                    group[key] = frame_item[key]
        groups[frame_item["id"]] = group
    heading: list[dict[str, Any]] = []
    for item in items:
        if item["type"] != "text" or item["group"] or "x" in item or item["id"] in linked:
            break
        heading.append(item)
    if len(heading) == len(items):
        heading = []
    heading_ids = {item["id"] for item in heading}
    files: dict[str, dict[str, Any]] = {}
    nodes: list[dict[str, Any]] = []
    for item in items:
        if item["type"] == "frame" or item["id"] in heading_ids:
            continue
        style: dict[str, Any] = {}
        if item["color"]:
            style["color"] = item["color"]
        node: dict[str, Any] = {"id": item["id"], "label": item["text"], "style": style}
        if item["type"] == "note":
            node["kind"] = "note"
        elif item["type"] == "text":
            node["kind"] = "text"
            if 0 < len(item["text"]) <= 36 and "\n" not in item["text"]:
                style["size"] = float(el.FONT_SIZES["l"])
        elif item["type"] == "image":
            stored = store_image(item["image"]) if (store_image and item["image"]) else None
            if stored:
                file_id, mime = stored
                node["kind"] = "image"
                node["file"] = file_id
                files[file_id] = {"id": file_id, "mimeType": mime, "created": when}
                node["w"], node["h"] = _image_size(item["image"])
            else:
                node["kind"] = "rect"
                node["label"] = f"Picture: {item['text']}" if item["text"] else "Picture"
                style.update(stroke_style="dashed", color=item["color"] or "gray")
        else:
            node["kind"] = item["shape"]
        for key in ("x", "y", "w", "h"):
            if key in item:
                node[key] = item[key]
        if item["group"]:
            target = groups.get(item["group"]) or (
                groups.get(frame_by_title[item["group"]]["id"])
                if item["group"] in frame_by_title
                else None
            )
            if target is None:
                group_id = re.sub(r"[^A-Za-z0-9_]+", "_", item["group"]).strip("_")[:40] or "group"
                while group_id in by_id or group_id in groups:
                    group_id += "_"
                target = {"id": group_id, "label": item["group"], "nodes": []}
                groups[item["group"]] = target
            if "x" not in node:
                target["nodes"].append(item["id"])
        nodes.append(node)
    unique_groups: list[dict[str, Any]] = []
    for group in groups.values():
        if group not in unique_groups:
            unique_groups.append(group)
    diagram: dict[str, Any] = {
        "normalized": True,
        "nodes": nodes,
        "edges": [
            {
                "from": link["from"],
                "to": link["to"],
                "label": link["label"],
                "style": edge_style({"style": link.get("style")}),
                "heads": edge_heads(link.get("arrow")),
            }
            for link in links
        ],
        "groups": [g for g in unique_groups if g["nodes"] or ("x" in g and "y" in g)],
        "layout": "flow",
        "direction": "LR",
        "root": None,
        "title": "",
    }
    # An empty frame item still shows as a frame of its own size.
    for group in diagram["groups"]:
        if not group["nodes"]:
            group.setdefault("w", 320.0)
            group.setdefault("h", 200.0)
    elements: list[dict[str, Any]] = []
    if diagram["nodes"] or diagram["groups"]:
        top = 0.0
        heading_elements: list[dict[str, Any]] = []
        for item in heading:
            size = float(el.FONT_SIZES["xl"] if not heading_elements else el.FONT_SIZES["m"])
            heading_text = el.text(
                item["text"],
                x=0,
                y=top,
                now_ms=when,
                font_size=size,
                font_family=el.FONT_HAND,
                element_id=item["id"],
            )
            heading_elements.append(heading_text)
            top += float(heading_text["height"]) + 8
        placement = layout_diagram(diagram)
        body, _ = diagram_to_elements(
            diagram,
            origin=(0.0, top + (lay.CROSS_GAP if heading_elements else 0.0)),
            now_ms=when,
            laid_out=placement,
        )
        elements = heading_elements + body
    else:
        size = float(el.FONT_SIZES["xl"])
        top = 0.0
        for item in heading or items:
            line = el.text(
                item["text"] or item["title"] or " ",
                x=0,
                y=top,
                now_ms=when,
                font_size=size,
                font_family=el.FONT_HAND,
                element_id=item["id"],
            )
            elements.append(line)
            top += float(line["height"]) + 8
            size = float(el.FONT_SIZES["m"])
    el.sync_indices(elements)
    return {
        "format": "scene",
        "elements": elements,
        "appState": {"viewBackgroundColor": el.WHITE, "gridModeEnabled": False},
        "files": files,
    }


__all__ = [
    "ARROW_GAP",
    "KIND_ALIASES",
    "NODE_KINDS",
    "arrow_between",
    "build_node",
    "colors_for",
    "diagram_to_elements",
    "edge_heads",
    "edge_style",
    "kind_of",
    "layout_diagram",
    "legacy_to_scene",
    "node_size",
    "normalize_diagram",
    "obstacle_rects",
    "parse_style",
    "route",
    "unique_ids",
]
