"""Element factory: scene elements the embedded editor accepts as they are.

The whiteboard's scene is the element JSON of ``@excalidraw/excalidraw``
0.18.1 (MIT). Everything the assistant puts on a board is built here, so the
editor never has to repair what it loads: every field of the element type is
present, a label is a text element bound to its container (``containerId`` on
the text, ``boundElements`` on the box), an arrow is bound to the shapes it
joins and its points start at ``[0, 0]`` relative to its own ``x``/``y``.

The constants below were read from the package itself (its type definitions
and its production bundle): the font family ids (``FONT_FAMILY``), each
font's line height, the default element properties, the bound text padding,
and the colour palette, which is open-color 1.9.1 at the five shades the
editor's colour picker offers (0, 2, 4, 6, 8); a stroke uses the darkest of
them, a fill the second lightest, as the editor's own quick picks do.

Text sizes are estimates (the editor measures with the real font when it
loads a scene and refreshes the dimensions of every text element), so the
estimate leans wide: a box sized from it never ends up too small for its
label.

Fractional indices: the editor orders elements by their ``index`` when it
reconciles two versions of a scene, and its comparison is unstable for an
element without one. :func:`sync_indices` gives every element a valid index
the way the editor's own ``syncInvalidIndices`` does (valid ones are kept,
each run of invalid ones gets keys between its neighbours), using a port of
the ``fractional-indexing`` package the editor depends on.
"""

from __future__ import annotations

import math
import re
import secrets
import time
import unicodedata
from typing import Any, Final

# --- fonts ------------------------------------------------------------------------

#: The editor's font family ids (``FONT_FAMILY`` in the package).
FONT_IDS: Final[dict[str, int]] = {
    "Virgil": 1,
    "Helvetica": 2,
    "Cascadia": 3,
    "Excalifont": 5,
    "Nunito": 6,
    "Lilita One": 7,
    "Comic Shanns": 8,
    "Liberation Sans": 9,
}
FONT_HAND: Final[int] = 5
FONT_NORMAL: Final[int] = 6
FONT_CODE: Final[int] = 8

#: What a model may call a font, and the family id it means.
FONT_NAMES: Final[dict[str, int]] = {
    "hand": FONT_HAND,
    "hand-drawn": FONT_HAND,
    "handdrawn": FONT_HAND,
    "handwritten": FONT_HAND,
    "sketch": FONT_HAND,
    "excalifont": FONT_HAND,
    "virgil": FONT_HAND,
    "normal": FONT_NORMAL,
    "sans": FONT_NORMAL,
    "sans-serif": FONT_NORMAL,
    "clean": FONT_NORMAL,
    "nunito": FONT_NORMAL,
    "helvetica": FONT_NORMAL,
    "code": FONT_CODE,
    "mono": FONT_CODE,
    "monospace": FONT_CODE,
    "comic shanns": FONT_CODE,
    "cascadia": FONT_CODE,
    "heading": 7,
    "display": 7,
    "lilita one": 7,
}

#: Unitless line height per font family, from the package's font metrics.
LINE_HEIGHTS: Final[dict[int, float]] = {
    1: 1.25,
    2: 1.15,
    3: 1.2,
    5: 1.25,
    6: 1.35,
    7: 1.15,
    8: 1.25,
    9: 1.15,
}

#: The editor's font size steps (small, medium, large, very large).
FONT_SIZES: Final[dict[str, int]] = {"s": 16, "m": 20, "l": 28, "xl": 36}
DEFAULT_FONT_SIZE: Final[int] = 20
MIN_FONT_SIZE: Final[int] = 8
MAX_FONT_SIZE: Final[int] = 120

#: Width of one character as a share of the font size: leans wide on purpose.
_CHAR_SHARE: Final[dict[int, float]] = {5: 0.62, 1: 0.62, 6: 0.56, 7: 0.56, 8: 0.62, 3: 0.62}

#: The editor keeps this much room between a container's edge and its label.
BOUND_TEXT_PADDING: Final[int] = 5

# --- colours ----------------------------------------------------------------------

BLACK: Final[str] = "#1e1e1e"
WHITE: Final[str] = "#ffffff"
TRANSPARENT: Final[str] = "transparent"

#: open-color 1.9.1 at the shades 0, 2, 4, 6, 8: the editor's palette.
#: ``indigo`` and ``lime`` are not in the editor's picker but are the same
#: family, so a model that asks for them gets the matching shades.
PALETTE: Final[dict[str, tuple[str, str, str, str, str]]] = {
    "gray": ("#f8f9fa", "#e9ecef", "#ced4da", "#868e96", "#343a40"),
    "red": ("#fff5f5", "#ffc9c9", "#ff8787", "#fa5252", "#e03131"),
    "pink": ("#fff0f6", "#fcc2d7", "#f783ac", "#e64980", "#c2255c"),
    "grape": ("#f8f0fc", "#eebefa", "#da77f2", "#be4bdb", "#9c36b5"),
    "violet": ("#f3f0ff", "#d0bfff", "#9775fa", "#7950f2", "#6741d9"),
    "indigo": ("#edf2ff", "#bac8ff", "#748ffc", "#4c6ef5", "#3b5bdb"),
    "blue": ("#e7f5ff", "#a5d8ff", "#4dabf7", "#228be6", "#1971c2"),
    "cyan": ("#e3fafc", "#99e9f2", "#3bc9db", "#15aabf", "#0c8599"),
    "teal": ("#e6fcf5", "#96f2d7", "#38d9a9", "#12b886", "#099268"),
    "green": ("#ebfbee", "#b2f2bb", "#69db7c", "#40c057", "#2f9e44"),
    "lime": ("#f4fce3", "#d8f5a2", "#a9e34b", "#82c91e", "#66a80f"),
    "yellow": ("#fff9db", "#ffec99", "#ffd43b", "#fab005", "#f08c00"),
    "orange": ("#fff4e6", "#ffd8a8", "#ffa94d", "#fd7e14", "#e8590c"),
    "bronze": ("#f8f1ee", "#eaddd7", "#d2bab0", "#a18072", "#846358"),
}
#: The shade a stroke and a fill take from a palette colour.
STROKE_SHADE: Final[int] = 4
FILL_SHADE: Final[int] = 1

_COLOR_ALIASES: Final[dict[str, str]] = {
    "grey": "gray",
    "purple": "violet",
    "magenta": "grape",
    "amber": "yellow",
    "gold": "yellow",
    "brown": "bronze",
    "navy": "indigo",
    "turquoise": "teal",
    "mint": "teal",
}
_HEX_RE: Final = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")

#: The fill of a sticky note, and its edge: the editor's light and strong yellow.
NOTE_FILL: Final[str] = PALETTE["yellow"][FILL_SHADE]
NOTE_STROKE: Final[str] = PALETTE["yellow"][STROKE_SHADE]


def color_names() -> list[str]:
    """Every colour name a model may use."""
    return ["black", "white", "transparent", *PALETTE]


def resolve_color(value: Any, role: str = "stroke") -> str:
    """A colour for an element field from a palette name, a shade or a hex code.

    ``role`` is ``stroke`` or ``fill``: a bare palette name means the shade the
    editor uses for that role. ``"blue-3"`` picks a shade (0 lightest to 4
    darkest), ``"light blue"`` the lightest, ``"dark blue"`` the darkest.
    Raises ``ValueError`` with the choices.
    """
    raw = str(value or "").strip().lower()
    if not raw:
        raise ValueError("a colour is empty")
    if raw in ("none", "transparent", "no", "clear"):
        return TRANSPARENT
    if raw == "black":
        return BLACK
    if raw == "white":
        return WHITE
    if _HEX_RE.match(raw):
        if len(raw) == 4:
            raw = "#" + "".join(ch * 2 for ch in raw[1:])
        return raw
    shade: int | None = None
    name = raw
    for prefix, chosen in (("light ", 0), ("dark ", 4), ("pale ", 0), ("strong ", 4)):
        if name.startswith(prefix):
            name, shade = name[len(prefix) :].strip(), chosen
    match = re.match(r"^([a-z]+)[\s._-]?([0-4])$", name)
    if match:
        name, shade = match.group(1), int(match.group(2))
    name = _COLOR_ALIASES.get(name, name)
    shades = PALETTE.get(name)
    if shades is None:
        raise ValueError(
            f"unknown colour {value!r}; use a palette name ({', '.join(color_names())}), "
            "optionally with a shade 0-4 like 'blue-1', or a hex code like '#1971c2'"
        )
    if shade is None:
        shade = STROKE_SHADE if role == "stroke" else FILL_SHADE
    return shades[shade]


def color_name(hex_value: Any) -> str:
    """The palette name of ``hex_value`` (``blue``, ``blue-0`` …), else the value itself."""
    value = str(hex_value or "").lower()
    if value in (TRANSPARENT, BLACK, WHITE):
        return {TRANSPARENT: "none", BLACK: "black", WHITE: "white"}[value]
    for name, shades in PALETTE.items():
        if value == shades[STROKE_SHADE] or value == shades[FILL_SHADE]:
            return name
        if value in shades:
            return f"{name}-{shades.index(value)}"
    return value


# --- ids, seeds, time ---------------------------------------------------------------

_ID_ALPHABET: Final[str] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
_MODEL_ID_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,39}$")
MAX_INT31: Final[int] = 2**31 - 1


def new_id() -> str:
    """A 21-character id like the editor's own (nanoid alphabet)."""
    return "".join(secrets.choice(_ID_ALPHABET) for _ in range(21))


def new_seed() -> int:
    return secrets.randbelow(MAX_INT31 - 1) + 1


def new_nonce() -> int:
    return secrets.randbelow(MAX_INT31)


def now_millis() -> int:
    return int(time.time() * 1000)


def check_model_id(value: Any) -> str:
    """An id a model chose, if it is a usable one; raises ``ValueError``."""
    text = (
        str(value).strip() if isinstance(value, (str, int)) and not isinstance(value, bool) else ""
    )
    if not _MODEL_ID_RE.match(text):
        raise ValueError(
            f"id {value!r} is not usable: 1-40 letters, digits, '_', '-', '.' or ':', "
            "starting with a letter or digit"
        )
    return text


# --- text measures ------------------------------------------------------------------


def _units(text: str) -> float:
    """Width of ``text`` in Latin characters (a wide CJK glyph counts as two)."""
    return float(sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text))


def line_height(font_family: int) -> float:
    return LINE_HEIGHTS.get(font_family, 1.25)


def char_width(font_size: float, font_family: int) -> float:
    return font_size * _CHAR_SHARE.get(font_family, 0.62)


def estimate_text(text: str, font_size: float, font_family: int) -> tuple[float, float]:
    """Width and height the editor will give ``text`` (no wrapping), leaning wide."""
    lines = (text or "").split("\n") or [""]
    width = max((_units(line) for line in lines), default=0.0) * char_width(font_size, font_family)
    height = len(lines) * font_size * line_height(font_family)
    return math.ceil(width), math.ceil(height)


def wrap_text(text: str, max_width: float, font_size: float, font_family: int) -> str:
    """``text`` with line breaks so no line is wider than ``max_width`` (by estimate).

    Words are kept whole; a single word longer than a line is broken. The
    editor wraps a label again with the real font, so this only has to be
    close: it decides the height a box needs.
    """
    room = max(1.0, max_width / char_width(font_size, font_family))
    out: list[str] = []
    for paragraph in (text or "").split("\n"):
        words = paragraph.split(" ")
        line = ""
        for word in words:
            candidate = word if not line else f"{line} {word}"
            if _units(candidate) <= room:
                line = candidate
                continue
            if line:
                out.append(line)
            while _units(word) > room:
                cut = max(1, int(room))
                out.append(word[:cut])
                word = word[cut:]
            line = word
        out.append(line)
    return "\n".join(out)


def label_room(kind: str, width: float, height: float) -> tuple[float, float]:
    """Width and height a label may use inside a container (the editor's rule)."""
    pad = BOUND_TEXT_PADDING * 2
    if kind == "ellipse":
        return round(width / 2 * math.sqrt(2)) - pad, round(height / 2 * math.sqrt(2)) - pad
    if kind == "diamond":
        return round(width / 2) - pad, round(height / 2) - pad
    return width - pad, height - pad


def container_for_text(kind: str, text_w: float, text_h: float) -> tuple[float, float]:
    """The smallest container of ``kind`` that holds a label of this size."""
    pad = BOUND_TEXT_PADDING * 2
    if kind == "ellipse":
        return round((text_w + pad) / math.sqrt(2) * 2), round((text_h + pad) / math.sqrt(2) * 2)
    if kind == "diamond":
        return 2 * (text_w + pad), 2 * (text_h + pad)
    return text_w + pad, text_h + pad


# --- elements -----------------------------------------------------------------------

#: Defaults of the editor (``DEFAULT_ELEMENT_PROPS``), except roughness: see style.
DEFAULT_STROKE_WIDTH: Final[int] = 2
DEFAULT_ROUGHNESS: Final[int] = 1
ROUND_ADAPTIVE: Final[dict[str, int]] = {"type": 3}
ROUND_PROPORTIONAL: Final[dict[str, int]] = {"type": 2}


def base(
    kind: str,
    *,
    x: float,
    y: float,
    width: float,
    height: float,
    now_ms: int,
    element_id: str | None = None,
    stroke: str = BLACK,
    fill: str = TRANSPARENT,
    fill_style: str = "solid",
    stroke_width: float = DEFAULT_STROKE_WIDTH,
    stroke_style: str = "solid",
    roughness: int = DEFAULT_ROUGHNESS,
    opacity: int = 100,
    roundness: dict[str, int] | None = None,
    angle: float = 0.0,
) -> dict[str, Any]:
    """The fields every element has, at version 1."""
    return {
        "id": element_id or new_id(),
        "type": kind,
        "x": tidy(x),
        "y": tidy(y),
        "width": tidy(max(0.0, width)),
        "height": tidy(max(0.0, height)),
        "angle": tidy(angle),
        "strokeColor": stroke,
        "backgroundColor": fill,
        "fillStyle": fill_style,
        "strokeWidth": stroke_width,
        "strokeStyle": stroke_style,
        "roughness": roughness,
        "opacity": opacity,
        "groupIds": [],
        "frameId": None,
        "index": None,
        "roundness": dict(roundness) if roundness else None,
        "seed": new_seed(),
        "version": 1,
        "versionNonce": new_nonce(),
        "isDeleted": False,
        "boundElements": None,
        "updated": now_ms,
        "link": None,
        "locked": False,
    }


def tidy(value: float) -> float | int:
    """A coordinate as stored: two decimals, an int when whole."""
    rounded = round(float(value), 2)
    return int(rounded) if rounded == int(rounded) else rounded


def shape(kind: str, **fields: Any) -> dict[str, Any]:
    """A rectangle, ellipse or diamond with the editor's rounding for its kind."""
    if kind not in ("rectangle", "ellipse", "diamond"):
        raise ValueError(f"not a shape: {kind}")
    if "roundness" not in fields:
        fields["roundness"] = (
            ROUND_ADAPTIVE
            if kind == "rectangle"
            else ROUND_PROPORTIONAL
            if kind == "diamond"
            else None
        )
    return base(kind, **fields)


def text(
    content: str,
    *,
    x: float,
    y: float,
    now_ms: int,
    font_size: float = DEFAULT_FONT_SIZE,
    font_family: int = FONT_HAND,
    align: str = "left",
    valign: str = "top",
    color: str = BLACK,
    element_id: str | None = None,
    container_id: str | None = None,
    original: str | None = None,
    opacity: int = 100,
) -> dict[str, Any]:
    """A text element; its size is the estimate of ``content``."""
    width, height = estimate_text(content, font_size, font_family)
    element = base(
        "text",
        x=x,
        y=y,
        width=width,
        height=height,
        now_ms=now_ms,
        element_id=element_id,
        stroke=color,
        opacity=opacity,
    )
    element.update(
        {
            "text": content,
            "originalText": original if original is not None else content,
            "fontSize": font_size,
            "fontFamily": font_family,
            "textAlign": align,
            "verticalAlign": valign,
            "containerId": container_id,
            "autoResize": True,
            "lineHeight": line_height(font_family),
        }
    )
    return element


def add_bound(container: dict[str, Any], bound_id: str, bound_type: str) -> None:
    """Record ``bound_id`` in the container's ``boundElements`` (once)."""
    bound = list(container.get("boundElements") or [])
    if not any(entry.get("id") == bound_id for entry in bound):
        bound.append({"id": bound_id, "type": bound_type})
    container["boundElements"] = bound


def drop_bound(container: dict[str, Any], bound_id: str) -> None:
    bound = [entry for entry in container.get("boundElements") or [] if entry.get("id") != bound_id]
    container["boundElements"] = bound or None


def place_label(label: dict[str, Any], container: dict[str, Any]) -> None:
    """Wrap and centre a bound label in its container (a box or an arrow)."""
    font_size = float(label.get("fontSize") or DEFAULT_FONT_SIZE)
    family = int(label.get("fontFamily") or FONT_HAND)
    original = str(label.get("originalText") or label.get("text") or "")
    if container.get("type") in ("arrow", "line"):
        start, end = linear_ends(container)
        length = math.dist(start, end)
        room_w = max(font_size * 11, length * 0.7)
        wrapped = wrap_text(original, room_w, font_size, family)
        width, height = estimate_text(wrapped, font_size, family)
        mid = linear_mid(container)
        label.update(text=wrapped, width=width, height=height)
        label["x"] = tidy(mid[0] - width / 2)
        label["y"] = tidy(mid[1] - height / 2)
        return
    room_w, _ = label_room(container["type"], float(container["width"]), float(container["height"]))
    wrapped = wrap_text(original, max(room_w, font_size), font_size, family)
    width, height = estimate_text(wrapped, font_size, family)
    width = min(width, max(room_w, 1.0))
    label.update(text=wrapped, width=tidy(width), height=tidy(height))
    cx = float(container["x"]) + float(container["width"]) / 2
    cy = float(container["y"]) + float(container["height"]) / 2
    label["x"] = tidy(cx - width / 2)
    valign = label.get("verticalAlign") or "middle"
    if valign == "top":
        label["y"] = tidy(float(container["y"]) + BOUND_TEXT_PADDING)
    elif valign == "bottom":
        label["y"] = tidy(
            float(container["y"]) + float(container["height"]) - BOUND_TEXT_PADDING - height
        )
    else:
        label["y"] = tidy(cy - height / 2)


def label_for(
    container: dict[str, Any],
    content: str,
    *,
    now_ms: int,
    font_size: float = DEFAULT_FONT_SIZE,
    font_family: int = FONT_HAND,
    color: str = BLACK,
    align: str = "center",
    element_id: str | None = None,
) -> dict[str, Any]:
    """A label bound to ``container``, wrapped and centred in it."""
    label = text(
        content,
        x=float(container["x"]),
        y=float(container["y"]),
        now_ms=now_ms,
        font_size=font_size,
        font_family=font_family,
        align=align,
        valign="middle",
        color=color,
        element_id=element_id,
        container_id=container["id"],
        original=content,
    )
    add_bound(container, label["id"], "text")
    place_label(label, container)
    return label


def fit_container(
    kind: str,
    content: str,
    *,
    font_size: float,
    font_family: int,
    min_size: tuple[float, float],
    max_text_width: float,
    padding: float = 16.0,
    grid: float = 20.0,
) -> tuple[float, float]:
    """A container size that holds ``content`` comfortably, on the grid."""
    wrapped = wrap_text(content, max_text_width, font_size, font_family)
    text_w, text_h = estimate_text(wrapped, font_size, font_family)
    need_w, need_h = container_for_text(kind, text_w + 2 * padding, text_h + 2 * padding * 0.75)
    width = max(min_size[0], snap_up(need_w, grid))
    height = max(min_size[1], snap_up(need_h, grid))
    return width, height


def snap_up(value: float, grid: float) -> float:
    return math.ceil(value / grid - 1e-9) * grid if grid > 0 else value


# --- linear elements ----------------------------------------------------------------


def linear(
    kind: str,
    points: list[tuple[float, float]],
    *,
    now_ms: int,
    element_id: str | None = None,
    stroke: str = BLACK,
    stroke_width: float = DEFAULT_STROKE_WIDTH,
    stroke_style: str = "solid",
    roughness: int = DEFAULT_ROUGHNESS,
    opacity: int = 100,
    start_head: str | None = None,
    end_head: str | None = "arrow",
    curved: bool = False,
) -> dict[str, Any]:
    """An arrow or line through absolute ``points`` (at least two)."""
    if len(points) < 2:
        raise ValueError("a line needs at least two points")
    origin_x, origin_y = points[0]
    rel = [[tidy(px - origin_x), tidy(py - origin_y)] for px, py in points]
    xs = [p[0] for p in rel]
    ys = [p[1] for p in rel]
    element = base(
        kind,
        x=origin_x,
        y=origin_y,
        width=max(xs) - min(xs),
        height=max(ys) - min(ys),
        now_ms=now_ms,
        element_id=element_id,
        stroke=stroke,
        stroke_width=stroke_width,
        stroke_style=stroke_style,
        roughness=roughness,
        opacity=opacity,
        roundness=ROUND_PROPORTIONAL if curved or kind == "arrow" else None,
    )
    element.update(
        {
            "points": rel,
            "lastCommittedPoint": None,
            "startBinding": None,
            "endBinding": None,
            "startArrowhead": start_head if kind == "arrow" else None,
            "endArrowhead": end_head if kind == "arrow" else None,
        }
    )
    if kind == "arrow":
        element["elbowed"] = False
    return element


def set_points(element: dict[str, Any], points: list[tuple[float, float]]) -> None:
    """Move a linear element onto new absolute ``points``."""
    origin_x, origin_y = points[0]
    rel = [[tidy(px - origin_x), tidy(py - origin_y)] for px, py in points]
    xs = [p[0] for p in rel]
    ys = [p[1] for p in rel]
    element.update(
        x=tidy(origin_x),
        y=tidy(origin_y),
        points=rel,
        width=tidy(max(xs) - min(xs)),
        height=tidy(max(ys) - min(ys)),
    )


def absolute_points(element: dict[str, Any]) -> list[tuple[float, float]]:
    x0, y0 = float(element.get("x", 0)), float(element.get("y", 0))
    return [(x0 + float(p[0]), y0 + float(p[1])) for p in element.get("points") or [[0, 0]]]


def linear_ends(element: dict[str, Any]) -> tuple[tuple[float, float], tuple[float, float]]:
    pts = absolute_points(element)
    return pts[0], pts[-1]


def linear_mid(element: dict[str, Any]) -> tuple[float, float]:
    """Where the editor puts an arrow's label: the middle point, or the middle of
    the middle segment."""
    pts = absolute_points(element)
    if len(pts) % 2 == 1:
        return pts[len(pts) // 2]
    a, b = pts[len(pts) // 2 - 1], pts[len(pts) // 2]
    return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)


def outline_point(
    element: dict[str, Any], toward: tuple[float, float], gap: float
) -> tuple[float, float]:
    """The point on ``element``'s outline in the direction of ``toward``, ``gap`` outside.

    The ray starts at the centre, so an arrow drawn between two such points
    aims at both centres (a binding ``focus`` of 0).
    """
    x, y = float(element["x"]), float(element["y"])
    w, h = max(1.0, float(element["width"])), max(1.0, float(element["height"]))
    cx, cy = x + w / 2, y + h / 2
    dx, dy = toward[0] - cx, toward[1] - cy
    length = math.hypot(dx, dy)
    if length < 1e-6:
        return (x + w + gap, cy)
    ux, uy = dx / length, dy / length
    hw, hh = w / 2, h / 2
    kind = element.get("type")
    if kind == "ellipse":
        t = 1.0 / math.sqrt((ux / hw) ** 2 + (uy / hh) ** 2)
    elif kind == "diamond":
        t = 1.0 / (abs(ux) / hw + abs(uy) / hh)
    else:
        tx = hw / abs(ux) if abs(ux) > 1e-9 else math.inf
        ty = hh / abs(uy) if abs(uy) > 1e-9 else math.inf
        t = min(tx, ty)
    return (cx + ux * (t + gap), cy + uy * (t + gap))


def binding(element_id: str, gap: float) -> dict[str, Any]:
    return {"elementId": element_id, "focus": 0, "gap": tidy(gap)}


# --- other kinds -------------------------------------------------------------------


def frame(name: str | None, **fields: Any) -> dict[str, Any]:
    fields.setdefault("roundness", None)
    element = base("frame", **fields)
    element["name"] = name or None
    return element


def freedraw(points: list[tuple[float, float]], **fields: Any) -> dict[str, Any]:
    if len(points) < 2:
        raise ValueError("a drawing needs at least two points")
    origin_x, origin_y = points[0]
    rel = [[tidy(px - origin_x), tidy(py - origin_y)] for px, py in points]
    xs = [p[0] for p in rel]
    ys = [p[1] for p in rel]
    element = base(
        "freedraw",
        x=origin_x,
        y=origin_y,
        width=max(xs) - min(xs),
        height=max(ys) - min(ys),
        **fields,
    )
    element.update(
        {"points": rel, "pressures": [], "simulatePressure": True, "lastCommittedPoint": None}
    )
    return element


def image(file_id: str, **fields: Any) -> dict[str, Any]:
    element = base("image", **fields)
    element.update({"fileId": file_id, "status": "saved", "scale": [1, 1], "crop": None})
    return element


def box_of(element: dict[str, Any]) -> tuple[float, float, float, float]:
    """``(x0, y0, x1, y1)`` of an element; linear and freedraw by their points."""
    if element.get("type") in ("arrow", "line", "freedraw") and element.get("points"):
        pts = absolute_points(element)
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        return min(xs), min(ys), max(xs), max(ys)
    x, y = float(element.get("x", 0)), float(element.get("y", 0))
    return x, y, x + float(element.get("width", 0)), y + float(element.get("height", 0))


# --- fractional indices -------------------------------------------------------------
# A port of the ``fractional-indexing`` package (base 62 keys), which the editor
# uses to order elements. Keys compare as plain strings.

_DIGITS: Final[str] = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
_SMALLEST_INT: Final[str] = "A" + "0" * 26


def _midpoint(a: str, b: str | None) -> str:
    zero = _DIGITS[0]
    if b is not None and a >= b:
        raise ValueError(f"{a} >= {b}")
    if a[-1:] == zero or (b and b[-1:] == zero):
        raise ValueError("trailing zero")
    if b:
        n = 0
        while (a[n] if n < len(a) else zero) == b[n]:
            n += 1
        if n > 0:
            return b[:n] + _midpoint(a[n:], b[n:])
    digit_a = _DIGITS.index(a[0]) if a else 0
    digit_b = _DIGITS.index(b[0]) if b is not None else len(_DIGITS)
    if digit_b - digit_a > 1:
        return _DIGITS[math.floor(0.5 * (digit_a + digit_b) + 0.5)]
    if b and len(b) > 1:
        return b[:1]
    return _DIGITS[digit_a] + _midpoint(a[1:], None)


def _integer_length(head: str) -> int:
    if "a" <= head <= "z":
        return ord(head) - ord("a") + 2
    if "A" <= head <= "Z":
        return ord("Z") - ord(head) + 2
    raise ValueError(f"invalid order key head: {head}")


def _integer_part(key: str) -> str:
    length = _integer_length(key[0])
    if length > len(key):
        raise ValueError(f"invalid order key: {key}")
    return key[:length]


def valid_index(key: Any) -> bool:
    """Whether ``key`` is a fractional index the editor accepts."""
    if not isinstance(key, str) or not key or key == _SMALLEST_INT:
        return False
    if any(ch not in _DIGITS for ch in key):
        return False
    try:
        integer = _integer_part(key)
    except ValueError:  # a malformed key is simply not valid
        return False
    return not key[len(integer) :].endswith(_DIGITS[0])


def _increment_integer(x: str) -> str | None:
    head, digs = x[0], list(x[1:])
    carry = True
    i = len(digs) - 1
    while carry and i >= 0:
        d = _DIGITS.index(digs[i]) + 1
        if d == len(_DIGITS):
            digs[i] = _DIGITS[0]
        else:
            digs[i] = _DIGITS[d]
            carry = False
        i -= 1
    if carry:
        if head == "Z":
            return "a" + _DIGITS[0]
        if head == "z":
            return None
        h = chr(ord(head) + 1)
        if h > "a":
            digs.append(_DIGITS[0])
        else:
            digs.pop()
        return h + "".join(digs)
    return head + "".join(digs)


def _decrement_integer(x: str) -> str | None:
    head, digs = x[0], list(x[1:])
    borrow = True
    i = len(digs) - 1
    while borrow and i >= 0:
        d = _DIGITS.index(digs[i]) - 1
        if d == -1:
            digs[i] = _DIGITS[-1]
        else:
            digs[i] = _DIGITS[d]
            borrow = False
        i -= 1
    if borrow:
        if head == "a":
            return "Z" + _DIGITS[-1]
        if head == "A":
            return None
        h = chr(ord(head) - 1)
        if h < "Z":
            digs.append(_DIGITS[-1])
        else:
            digs.pop()
        return h + "".join(digs)
    return head + "".join(digs)


def key_between(a: str | None, b: str | None) -> str:
    """A key that sorts strictly between ``a`` and ``b`` (``None`` = open end)."""
    if a is not None and b is not None and a >= b:
        raise ValueError(f"{a} >= {b}")
    if a is None:
        if b is None:
            return "a" + _DIGITS[0]
        ib = _integer_part(b)
        fb = b[len(ib) :]
        if ib == _SMALLEST_INT:
            return ib + _midpoint("", fb)
        if ib < b:
            return ib
        res = _decrement_integer(ib)
        if res is None:
            raise ValueError("cannot decrement any more")
        return res
    if b is None:
        ia = _integer_part(a)
        fa = a[len(ia) :]
        i = _increment_integer(ia)
        return ia + _midpoint(fa, None) if i is None else i
    ia = _integer_part(a)
    fa = a[len(ia) :]
    ib = _integer_part(b)
    fb = b[len(ib) :]
    if ia == ib:
        return ia + _midpoint(fa, fb)
    i = _increment_integer(ia)
    if i is None:
        raise ValueError("cannot increment any more")
    if i < b:
        return i
    return ia + _midpoint(fa, None)


def keys_between(a: str | None, b: str | None, n: int) -> list[str]:
    """``n`` keys in order between ``a`` and ``b``."""
    if n <= 0:
        return []
    if n == 1:
        return [key_between(a, b)]
    if b is None:
        out = [key_between(a, b)]
        for _ in range(n - 1):
            out.append(key_between(out[-1], b))
        return out
    if a is None:
        out = [key_between(a, b)]
        for _ in range(n - 1):
            out.append(key_between(a, out[-1]))
        out.reverse()
        return out
    mid = n // 2
    c = key_between(a, b)
    return [*keys_between(a, c, mid), c, *keys_between(c, b, n - mid - 1)]


def sync_indices(elements: list[dict[str, Any]]) -> set[str]:
    """Give every element a valid, ascending ``index``; returns the ids changed.

    An element keeps its index while it is valid and sorts between the kept
    neighbours; every run of others gets fresh keys between the indices
    around it, as the editor's ``syncInvalidIndices`` does.
    """
    keep = [False] * len(elements)
    last: str | None = None
    # Keep the longest sensible prefix order: an index is kept when it is valid
    # and above the last kept one. A greedy pass is enough for the edits this
    # module makes (appends, a few moves).
    for position, element in enumerate(elements):
        key = element.get("index")
        if isinstance(key, str) and valid_index(key) and (last is None or key > last):
            keep[position] = True
            last = key
    changed: set[str] = set()
    position = 0
    while position < len(elements):
        if keep[position]:
            position += 1
            continue
        start = position
        while position < len(elements) and not keep[position]:
            position += 1
        lower = elements[start - 1]["index"] if start > 0 else None
        upper = elements[position]["index"] if position < len(elements) else None
        for element, key in zip(
            elements[start:position], keys_between(lower, upper, position - start), strict=True
        ):
            element["index"] = key
            changed.add(str(element.get("id")))
    return changed


class Palette:
    """Parsing of the style words a model sends, shared by every action."""

    STROKE_WIDTHS: Final[dict[str, float]] = {"thin": 1, "bold": 2, "extra": 4, "extra-bold": 4}
    ROUGHNESS: Final[dict[str, int]] = {
        "architect": 0,
        "clean": 0,
        "smooth": 0,
        "artist": 1,
        "sketchy": 1,
        "hand-drawn": 1,
        "cartoonist": 2,
        "rough": 2,
    }
    FILL_STYLES: Final[tuple[str, ...]] = ("solid", "hachure", "cross-hatch", "zigzag")
    STROKE_STYLES: Final[tuple[str, ...]] = ("solid", "dashed", "dotted")
    ARROWHEADS: Final[tuple[str, ...]] = (
        "arrow",
        "bar",
        "dot",
        "circle",
        "circle_outline",
        "triangle",
        "triangle_outline",
        "diamond",
        "diamond_outline",
        "crowfoot_one",
        "crowfoot_many",
        "crowfoot_one_or_many",
    )

    @staticmethod
    def font(value: Any) -> int:
        if isinstance(value, int) and not isinstance(value, bool) and value in LINE_HEIGHTS:
            return value
        name = str(value or "").strip().lower()
        if name in FONT_NAMES:
            return FONT_NAMES[name]
        raise ValueError(f"unknown font {value!r}; use hand, normal or code")

    @staticmethod
    def font_size(value: Any) -> float:
        if isinstance(value, str) and value.strip().lower() in FONT_SIZES:
            return float(FONT_SIZES[value.strip().lower()])
        number = number_of(value, "size")
        return float(max(MIN_FONT_SIZE, min(MAX_FONT_SIZE, number)))

    @classmethod
    def stroke_width(cls, value: Any) -> float:
        if isinstance(value, str) and value.strip().lower() in cls.STROKE_WIDTHS:
            return float(cls.STROKE_WIDTHS[value.strip().lower()])
        return float(max(0.5, min(16.0, number_of(value, "stroke_width"))))

    @classmethod
    def roughness(cls, value: Any) -> int:
        if isinstance(value, str) and value.strip().lower() in cls.ROUGHNESS:
            return cls.ROUGHNESS[value.strip().lower()]
        number = int(number_of(value, "roughness"))
        if number not in (0, 1, 2):
            raise ValueError("roughness must be 0 (clean), 1 (sketchy) or 2 (rough)")
        return number

    @classmethod
    def choice(cls, value: Any, allowed: tuple[str, ...], field: str) -> str:
        name = str(value or "").strip().lower()
        if name not in allowed:
            raise ValueError(f"{field} must be one of {', '.join(allowed)}")
        return name

    @classmethod
    def arrowhead(cls, value: Any) -> str | None:
        if value is None or value is False:
            return None
        name = str(value).strip().lower().replace(" ", "_")
        if name in ("", "none", "no", "false"):
            return None
        if name in ("true", "yes"):
            return "arrow"
        if name not in cls.ARROWHEADS:
            raise ValueError(f"arrowhead must be none or one of {', '.join(cls.ARROWHEADS)}")
        return name


def number_of(value: Any, field: str) -> float:
    """A finite number from a model's value; raises ``ValueError`` naming ``field``."""
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a number")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be a number, not {value!r}") from None
    if not math.isfinite(number):
        raise ValueError(f"{field} must be a finite number")
    return number


__all__ = [
    "BLACK",
    "BOUND_TEXT_PADDING",
    "DEFAULT_FONT_SIZE",
    "FONT_CODE",
    "FONT_HAND",
    "FONT_IDS",
    "FONT_NORMAL",
    "FONT_SIZES",
    "LINE_HEIGHTS",
    "NOTE_FILL",
    "NOTE_STROKE",
    "PALETTE",
    "TRANSPARENT",
    "WHITE",
    "Palette",
    "absolute_points",
    "add_bound",
    "base",
    "binding",
    "box_of",
    "check_model_id",
    "color_name",
    "color_names",
    "container_for_text",
    "drop_bound",
    "estimate_text",
    "fit_container",
    "frame",
    "freedraw",
    "image",
    "key_between",
    "keys_between",
    "label_for",
    "label_room",
    "linear",
    "linear_ends",
    "linear_mid",
    "new_id",
    "new_nonce",
    "new_seed",
    "now_millis",
    "number_of",
    "outline_point",
    "place_label",
    "resolve_color",
    "set_points",
    "shape",
    "sync_indices",
    "text",
    "tidy",
    "valid_index",
    "wrap_text",
]
