"""A whiteboard's page: the scene drawn once as SVG, to look at.

The board is edited in the app by the embedded editor; this page is what
everything else shows: the card in the library and in the chat, a shared
file, a printout. So it is read-only and self-contained like every node page
(:func:`dodaios.nodes.shell.document`): no network, no storage, both themes.

What it draws, and why it differs from the editor: every element type a board
keeps (:mod:`.scene`), with clean lines instead of the editor's hand-drawn
strokes. A page that copies the sketchy look would need the editor's random
stroke generator and fonts; clean geometry from the same coordinates reads as
the same board and stays small. A text is set where the editor measured it
(its own ``x``/``y``, its stored line breaks); the page uses the app's font,
so a line may run a little longer or shorter than in the editor.

The dark theme does what the editor does: the whole drawing is inverted
(``invert(93%) hue-rotate(180deg)``), so a black stroke on white becomes a
light stroke on near-black and the colours keep their hue; pictures are
inverted back so they look as they are.

Safety: every text from the scene reaches the page through the shell's
escaping helpers; every number in an attribute is formatted here from a float;
a colour is one of the forms :func:`.scene.color` lets through; a picture is
embedded as a ``data:`` URI only after its bytes were read as PNG, JPEG, GIF
or WebP (:mod:`.files`), and only up to a page budget.
"""

from __future__ import annotations

import base64
import math
from pathlib import Path
from typing import Any, Final

from dodaios.nodes import shell
from dodaios.nodes.board import files as board_files
from dodaios.nodes.board.scene import (
    LINE_HEIGHTS,
    color,
    element_box,
    empty_scene,
    is_scene,
    live_elements,
    normalize_scene,
    scene_bounds,
)
from dodaios.nodes.types import NodeError

#: The base64 text of the pictures one page may embed; the rest are drawn as
#: labelled boxes. A page is opened in a card and shared as one file.
IMAGE_BUDGET_CHARS: Final[int] = 3 * 1024 * 1024
#: Air around the drawing when the page fits it into the window.
_PAD: Final[float] = 32.0
#: The view of an empty board.
_EMPTY_BOX: Final[tuple[float, float, float, float]] = (0.0, 0.0, 800.0, 500.0)
_MAX_SPOKEN: Final[int] = 500
_SPOKEN_CHARS: Final[int] = 200

#: Font metrics per family id: units per em, ascender, descender (the
#: package's ``FONT_METADATA``), to place the first line the way the editor does.
_METRICS: Final[dict[int, tuple[float, float, float]]] = {
    1: (1000.0, 886.0, -374.0),
    2: (2048.0, 1577.0, -471.0),
    3: (2048.0, 1900.0, -480.0),
    5: (1000.0, 886.0, -374.0),
    6: (1000.0, 1011.0, -353.0),
    7: (1000.0, 923.0, -220.0),
    8: (1000.0, 750.0, -250.0),
    9: (2048.0, 1854.0, -434.0),
}
_MONO_FAMILIES: Final[frozenset[int]] = frozenset({3, 8})

#: How the editor draws a frame (its ``FRAME_STYLE``).
_FRAME_STROKE: Final[str] = "#bbb"
_FRAME_NAME: Final[str] = "#999999"
_FRAME_RADIUS: Final[float] = 8.0
_FRAME_NAME_SIZE: Final[float] = 14.0


def _n(value: float) -> str:
    """A number for an attribute, formatted from a float: at most two decimals."""
    number = float(value)
    if not math.isfinite(number):
        return "0"
    text = f"{number:.2f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def _f(element: dict[str, Any], key: str, default: float = 0.0) -> float:
    value = element.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    number = float(value)
    return number if math.isfinite(number) else default


class _Defs:
    """The ``<defs>`` a page needs: fill patterns, frame clips, the picture filter."""

    def __init__(self) -> None:
        self.parts: list[str] = []
        self._patterns: dict[tuple[str, str, float], str] = {}

    def pattern(self, style: str, fill: str, gap: float) -> str:
        key = (style, fill, gap)
        known = self._patterns.get(key)
        if known:
            return known
        ident = f"wb-p{len(self._patterns) + 1}"
        self._patterns[key] = ident
        size = _n(gap)
        lines = (
            f'<line x1="0" y1="0" x2="0" y2="{size}" stroke="{shell.attr(fill)}" stroke-width="1"/>'
        )
        if style == "cross-hatch":
            lines += (
                f'<line x1="0" y1="0" x2="{size}" y2="0" stroke="{shell.attr(fill)}" '
                'stroke-width="1"/>'
            )
        self.parts.append(
            f'<pattern id="{ident}" patternUnits="userSpaceOnUse" width="{size}" '
            f'height="{size}" patternTransform="rotate(-45)">{lines}</pattern>'
        )
        return ident


# --- strokes and fills ---------------------------------------------------------------------------


def _stroke(element: dict[str, Any], *, width: float | None = None) -> str:
    stroke = color(element.get("strokeColor"), "#1e1e1e")
    if stroke == "transparent":
        return ' stroke="none"'
    size = width if width is not None else max(0.1, _f(element, "strokeWidth", 2.0))
    attrs = (
        f' stroke="{shell.attr(stroke)}" stroke-width="{_n(size)}" stroke-linecap="round" '
        'stroke-linejoin="round"'
    )
    style = element.get("strokeStyle")
    if style == "dashed":
        attrs += f' stroke-dasharray="8 {_n(8 + size)}"'
    elif style == "dotted":
        attrs += f' stroke-dasharray="1.5 {_n(6 + size)}"'
    return attrs


def _fill(element: dict[str, Any], defs: _Defs) -> str:
    background = color(element.get("backgroundColor"), "transparent")
    if background == "transparent":
        return ' fill="none"'
    style = element.get("fillStyle")
    if style in ("hachure", "cross-hatch", "zigzag"):
        gap = max(4.0, _f(element, "strokeWidth", 2.0) * 4.0)
        kind = "cross-hatch" if style == "cross-hatch" else "hachure"
        return f' fill="url(#{defs.pattern(kind, background, round(gap, 2))})"'
    return f' fill="{shell.attr(background)}"'


def _corner(element: dict[str, Any], size: float) -> float:
    """The corner radius the editor gives a shape of ``size`` (its smaller side)."""
    roundness = element.get("roundness")
    if not isinstance(roundness, dict):
        return 0.0
    kind = roundness.get("type")
    if kind in (1, 2):
        return size * 0.25
    if kind == 3:
        fixed = roundness.get("value")
        radius = (
            float(fixed)
            if isinstance(fixed, (int, float)) and not isinstance(fixed, bool)
            else 32.0
        )
        return size * 0.25 if size <= radius / 0.25 else radius
    return 0.0


# --- shapes --------------------------------------------------------------------------------------


def _rectangle(element: dict[str, Any], defs: _Defs) -> str:
    x, y = _f(element, "x"), _f(element, "y")
    w, h = _f(element, "width"), _f(element, "height")
    radius = min(_corner(element, min(w, h)), w / 2, h / 2)
    rounded = f' rx="{_n(radius)}" ry="{_n(radius)}"' if radius > 0 else ""
    return (
        f'<rect x="{_n(x)}" y="{_n(y)}" width="{_n(w)}" height="{_n(h)}"{rounded}'
        f"{_fill(element, defs)}{_stroke(element)}/>"
    )


def _ellipse(element: dict[str, Any], defs: _Defs) -> str:
    w, h = _f(element, "width"), _f(element, "height")
    cx, cy = _f(element, "x") + w / 2, _f(element, "y") + h / 2
    return (
        f'<ellipse cx="{_n(cx)}" cy="{_n(cy)}" rx="{_n(w / 2)}" ry="{_n(h / 2)}"'
        f"{_fill(element, defs)}{_stroke(element)}/>"
    )


def _diamond(element: dict[str, Any], defs: _Defs) -> str:
    x, y = _f(element, "x"), _f(element, "y")
    w, h = _f(element, "width"), _f(element, "height")
    corners = ((x + w / 2, y), (x + w, y + h / 2), (x + w / 2, y + h), (x, y + h / 2))
    points = " ".join(f"{_n(px)},{_n(py)}" for px, py in corners)
    return f'<polygon points="{points}"{_fill(element, defs)}{_stroke(element)}/>'


# --- lines, arrows, strokes ----------------------------------------------------------------------


def _absolute(element: dict[str, Any]) -> list[tuple[float, float]]:
    x, y = _f(element, "x"), _f(element, "y")
    points: list[tuple[float, float]] = []
    for point in element.get("points") or []:
        if isinstance(point, (list, tuple)) and len(point) >= 2:
            px, py = point[0], point[1]
            if isinstance(px, (int, float)) and isinstance(py, (int, float)):
                points.append((x + float(px), y + float(py)))
    return points


def _straight(points: list[tuple[float, float]]) -> str:
    head, *rest = points
    return f"M{_n(head[0])} {_n(head[1])}" + "".join(f"L{_n(px)} {_n(py)}" for px, py in rest)


def _curved(points: list[tuple[float, float]]) -> str:
    """A smooth path through every point (Catmull-Rom as cubic Béziers)."""
    if len(points) < 3:
        return _straight(points)
    path = [f"M{_n(points[0][0])} {_n(points[0][1])}"]
    for index in range(len(points) - 1):
        p0 = points[index - 1] if index > 0 else points[index]
        p1, p2 = points[index], points[index + 1]
        p3 = points[index + 2] if index + 2 < len(points) else p2
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6)
        path.append(f"C{_n(c1[0])} {_n(c1[1])} {_n(c2[0])} {_n(c2[1])} {_n(p2[0])} {_n(p2[1])}")
    return "".join(path)


_HEAD_SIZE: Final[dict[str, float]] = {
    "arrow": 25.0,
    "diamond": 12.0,
    "diamond_outline": 12.0,
    "crowfoot_one": 20.0,
    "crowfoot_many": 20.0,
    "crowfoot_one_or_many": 20.0,
}


def _arrowhead(
    kind: str, tip: tuple[float, float], before: tuple[float, float], element: dict[str, Any]
) -> str:
    """One arrowhead at ``tip``, pointing away from ``before``."""
    dx, dy = tip[0] - before[0], tip[1] - before[1]
    length = math.hypot(dx, dy)
    if length < 1e-6:
        return ""
    ux, uy = dx / length, dy / length
    px, py = -uy, ux
    size = min(_HEAD_SIZE.get(kind, 15.0), length * (0.25 if kind.startswith("diamond") else 0.5))
    stroke = _stroke(element)
    ink = color(element.get("strokeColor"), "#1e1e1e")
    solid = "none" if ink == "transparent" else shell.attr(ink)
    tx, ty = tip

    def back(distance: float, side: float) -> tuple[float, float]:
        return tx - ux * distance + px * side, ty - uy * distance + py * side

    if kind == "arrow":
        spread = size * math.tan(math.radians(20))
        a, b = back(size, spread), back(size, -spread)
        return (
            f'<path d="M{_n(a[0])} {_n(a[1])}L{_n(tx)} {_n(ty)}L{_n(b[0])} {_n(b[1])}" '
            f'fill="none"{stroke}/>'
        )
    if kind in ("triangle", "triangle_outline"):
        spread = size * math.tan(math.radians(25))
        a, b = back(size, spread), back(size, -spread)
        fill = solid if kind == "triangle" else "none"
        return (
            f'<polygon points="{_n(tx)},{_n(ty)} {_n(a[0])},{_n(a[1])} {_n(b[0])},{_n(b[1])}" '
            f'fill="{fill}"{stroke}/>'
        )
    if kind == "bar":
        a, b = back(0, size / 2), back(0, -size / 2)
        return f'<path d="M{_n(a[0])} {_n(a[1])}L{_n(b[0])} {_n(b[1])}" fill="none"{stroke}/>'
    if kind in ("dot", "circle", "circle_outline"):
        radius = size / 2
        cx, cy = back(radius, 0)
        fill = "none" if kind == "circle_outline" else solid
        return f'<circle cx="{_n(cx)}" cy="{_n(cy)}" r="{_n(radius)}" fill="{fill}"{stroke}/>'
    if kind in ("diamond", "diamond_outline"):
        a, b, c = back(size / 2, size / 4), back(size, 0), back(size / 2, -size / 4)
        fill = solid if kind == "diamond" else "none"
        return (
            f'<polygon points="{_n(tx)},{_n(ty)} {_n(a[0])},{_n(a[1])} {_n(b[0])},{_n(b[1])} '
            f'{_n(c[0])},{_n(c[1])}" fill="{fill}"{stroke}/>'
        )
    parts: list[str] = []
    if kind in ("crowfoot_many", "crowfoot_one_or_many"):
        root = back(size, 0)
        a, b = back(0, size / 2), back(0, -size / 2)
        parts.append(
            f'<path d="M{_n(a[0])} {_n(a[1])}L{_n(root[0])} {_n(root[1])}L{_n(b[0])} {_n(b[1])}'
            f'M{_n(root[0])} {_n(root[1])}L{_n(tx)} {_n(ty)}" fill="none"{stroke}/>'
        )
    if kind in ("crowfoot_one", "crowfoot_one_or_many"):
        a, b = back(size * 0.75, size / 2), back(size * 0.75, -size / 2)
        parts.append(
            f'<path d="M{_n(a[0])} {_n(a[1])}L{_n(b[0])} {_n(b[1])}" fill="none"{stroke}/>'
        )
    return "".join(parts)


def _linear(element: dict[str, Any], defs: _Defs) -> str:
    points = _absolute(element)
    if not points:
        return ""
    if len(points) == 1:
        points = [points[0], points[0]]
    curved = isinstance(element.get("roundness"), dict) and not element.get("elbowed")
    path = _curved(points) if curved else _straight(points)
    closed = (
        element.get("type") == "line"
        and len(points) > 2
        and math.hypot(points[0][0] - points[-1][0], points[0][1] - points[-1][1]) < 1.0
    )
    fill = _fill(element, defs) if closed else ' fill="none"'
    drawn = f'<path d="{path}"{fill}{_stroke(element)}/>'
    start, end = element.get("startArrowhead"), element.get("endArrowhead")
    if isinstance(end, str):
        before = next((p for p in reversed(points[:-1]) if p != points[-1]), points[0])
        drawn += _arrowhead(end, points[-1], before, element)
    if isinstance(start, str):
        before = next((p for p in points[1:] if p != points[0]), points[-1])
        drawn += _arrowhead(start, points[0], before, element)
    return drawn


def _freedraw(element: dict[str, Any]) -> str:
    points = _absolute(element)
    if not points:
        return ""
    width = max(1.0, _f(element, "strokeWidth", 2.0) * 2.5)
    ink = color(element.get("strokeColor"), "#1e1e1e")
    if ink == "transparent":
        return ""
    if len(points) == 1:
        x, y = points[0]
        return f'<circle cx="{_n(x)}" cy="{_n(y)}" r="{_n(width / 2)}" fill="{shell.attr(ink)}"/>'
    # Quadratic curves through the midpoints: a hand's stroke without the
    # corners of a polyline.
    path = [f"M{_n(points[0][0])} {_n(points[0][1])}"]
    for index in range(1, len(points) - 1):
        (x1, y1), (x2, y2) = points[index], points[index + 1]
        path.append(f"Q{_n(x1)} {_n(y1)} {_n((x1 + x2) / 2)} {_n((y1 + y2) / 2)}")
    path.append(f"L{_n(points[-1][0])} {_n(points[-1][1])}")
    return (
        f'<path d="{"".join(path)}" fill="none" stroke="{shell.attr(ink)}" '
        f'stroke-width="{_n(width)}" stroke-linecap="round" stroke-linejoin="round"/>'
    )


# --- text, frames, pictures ----------------------------------------------------------------------


def _text(element: dict[str, Any], halo: str = "") -> str:
    """One text element. ``halo`` is the board's background colour for a
    label that sits on an arrow or a line: drawn as a wide stroke under the
    glyphs, it cuts the line away behind the words, as the editor does."""
    raw = element.get("text")
    if not isinstance(raw, str) or not raw.strip():
        return ""
    family = element.get("fontFamily")
    family = family if isinstance(family, int) and family in _METRICS else 5
    size = max(1.0, _f(element, "fontSize", 20.0))
    line_height = _f(element, "lineHeight", LINE_HEIGHTS.get(family, 1.25)) * size
    units, ascender, descender = _METRICS[family]
    # Where the editor puts the first baseline: the ascender, plus half the
    # room the line height leaves around the glyphs.
    offset = size * ascender / units + (line_height - size * (ascender - descender) / units) / 2
    x, y, width = _f(element, "x"), _f(element, "y"), _f(element, "width")
    align = element.get("textAlign")
    anchor, left = "start", x
    if align == "center":
        anchor, left = "middle", x + width / 2
    elif align == "right":
        anchor, left = "end", x + width
    ink = color(element.get("strokeColor"), "#1e1e1e")
    fill = "none" if ink == "transparent" else shell.attr(ink)
    klass = "wb-t wb-mono" if family in _MONO_FAMILIES else "wb-t"
    spans = "".join(
        f'<tspan x="{_n(left)}" y="{_n(y + offset + index * line_height)}">'
        f"{shell.esc(line)}</tspan>"
        for index, line in enumerate(raw.split("\n"))
    )
    under = (
        f' stroke="{shell.attr(halo)}" stroke-width="{_n(size * 0.5)}" '
        'stroke-linejoin="round" paint-order="stroke"'
        if halo
        else ""
    )
    return (
        f'<text class="{klass}" font-size="{_n(size)}" text-anchor="{anchor}" '
        f'fill="{fill}"{under}>{spans}</text>'
    )


def _frame(element: dict[str, Any]) -> str:
    x, y = _f(element, "x"), _f(element, "y")
    w, h = _f(element, "width"), _f(element, "height")
    outline = (
        f'<rect x="{_n(x)}" y="{_n(y)}" width="{_n(w)}" height="{_n(h)}" '
        f'rx="{_n(_FRAME_RADIUS)}" ry="{_n(_FRAME_RADIUS)}" fill="none" '
        f'stroke="{_FRAME_STROKE}" stroke-width="2"/>'
    )
    name = element.get("name")
    if not isinstance(name, str) or not name:
        return outline
    return outline + (
        f'<text class="wb-t" x="{_n(x)}" y="{_n(y - 8)}" font-size="{_n(_FRAME_NAME_SIZE)}" '
        f'fill="{_FRAME_NAME}">{shell.esc(name)}</text>'
    )


class _Pictures:
    """Reads a board's pictures for the page, within :data:`IMAGE_BUDGET_CHARS`."""

    def __init__(self, run_dir: Path | None) -> None:
        self.run_dir = run_dir
        self.left = IMAGE_BUDGET_CHARS
        self._seen: dict[str, str] = {}

    def uri(self, ident: Any) -> str:
        if self.run_dir is None or not isinstance(ident, str):
            return ""
        if ident in self._seen:
            return self._seen[ident]
        found = board_files.read(self.run_dir, ident)
        uri = ""
        if found is not None:
            data, mime = found
            encoded = base64.b64encode(data).decode("ascii")
            if len(encoded) <= self.left:
                self.left -= len(encoded)
                uri = f"data:{mime};base64,{encoded}"
        self._seen[ident] = uri
        return uri


def _image(element: dict[str, Any], pictures: _Pictures) -> str:
    x, y = _f(element, "x"), _f(element, "y")
    w, h = _f(element, "width"), _f(element, "height")
    uri = pictures.uri(element.get("fileId"))
    if not uri:
        size = max(10.0, min(16.0, h / 3))
        return (
            f'<rect x="{_n(x)}" y="{_n(y)}" width="{_n(w)}" height="{_n(h)}" fill="#f1f3f5" '
            'stroke="#adb5bd" stroke-width="1" stroke-dasharray="6 6"/>'
            f'<text class="wb-t" x="{_n(x + w / 2)}" y="{_n(y + h / 2 + size / 3)}" '
            f'font-size="{_n(size)}" text-anchor="middle" '
            'fill="#868e96">Image</text>'
        )
    href = shell.attr(uri)
    crop = element.get("crop")
    if isinstance(crop, dict) and _f(crop, "width") > 0 and _f(crop, "height") > 0:
        picture = (
            f'<svg x="{_n(x)}" y="{_n(y)}" width="{_n(w)}" height="{_n(h)}" '
            f'viewBox="{_n(_f(crop, "x"))} {_n(_f(crop, "y"))} {_n(_f(crop, "width"))} '
            f'{_n(_f(crop, "height"))}" preserveAspectRatio="none">'
            f'<image href="{href}" width="{_n(_f(crop, "naturalWidth"))}" '
            f'height="{_n(_f(crop, "naturalHeight"))}" preserveAspectRatio="none"/></svg>'
        )
    else:
        picture = (
            f'<image href="{href}" x="{_n(x)}" y="{_n(y)}" width="{_n(w)}" height="{_n(h)}" '
            'preserveAspectRatio="none"/>'
        )
    scale = element.get("scale")
    flip_x = isinstance(scale, list) and len(scale) == 2 and scale[0] == -1
    flip_y = isinstance(scale, list) and len(scale) == 2 and scale[1] == -1
    flip = ""
    if flip_x or flip_y:
        cx, cy = x + w / 2, y + h / 2
        flip = (
            f' transform="translate({_n(cx)} {_n(cy)}) scale({-1 if flip_x else 1} '
            f'{-1 if flip_y else 1}) translate({_n(-cx)} {_n(-cy)})"'
        )
    return f'<g class="wb-img"{flip}>{picture}</g>'


# --- one element, the whole drawing --------------------------------------------------------------


def _shape_of(element: dict[str, Any], defs: _Defs, pictures: _Pictures, halo: str = "") -> str:
    kind = element.get("type")
    if kind == "rectangle":
        return _rectangle(element, defs)
    if kind == "ellipse":
        return _ellipse(element, defs)
    if kind == "diamond":
        return _diamond(element, defs)
    if kind in ("arrow", "line"):
        return _linear(element, defs)
    if kind == "freedraw":
        return _freedraw(element)
    if kind == "text":
        return _text(element, halo)
    if kind == "frame":
        return _frame(element)
    if kind == "image":
        return _image(element, pictures)
    return ""


def _placed(element: dict[str, Any], drawn: str, clip: str) -> str:
    """``drawn`` with the element's opacity, rotation and frame clip."""
    if not drawn:
        return ""
    attrs = ""
    opacity = _f(element, "opacity", 100.0)
    if opacity < 100:
        attrs += f' opacity="{_n(max(0.0, opacity) / 100)}"'
    angle = _f(element, "angle")
    if angle:
        x0, y0, x1, y1 = element_box(element)
        attrs += (
            f' transform="rotate({_n(math.degrees(angle))} {_n((x0 + x1) / 2)} '
            f'{_n((y0 + y1) / 2)})"'
        )
    if attrs:
        drawn = f"<g{attrs}>{drawn}</g>"
    if clip:
        drawn = f'<g clip-path="url(#{clip})">{drawn}</g>'
    return drawn


def _view_box(elements: list[dict[str, Any]]) -> tuple[float, float, float, float]:
    """``(x, y, width, height)`` of the drawing with air for strokes and frame names."""
    if not elements:
        return _EMPTY_BOX
    x0, y0, x1, y1 = scene_bounds(elements)
    if any(element.get("type") == "frame" and element.get("name") for element in elements):
        y0 -= 24.0
    widest = max((_f(element, "strokeWidth", 2.0) for element in elements), default=2.0)
    margin = _PAD + widest * 3
    x0, y0, x1, y1 = x0 - margin, y0 - margin, x1 + margin, y1 + margin
    # A dot or a single word is not blown up to fill the window.
    width, height = max(x1 - x0, 320.0), max(y1 - y0, 200.0)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return cx - width / 2, cy - height / 2, width, height


def _spoken(elements: list[dict[str, Any]]) -> str:
    """The board's words as a list, for a screen reader (the drawing itself is an image)."""
    entries: list[str] = []
    for element in elements:
        if element.get("type") == "frame" and element.get("name"):
            entries.append(f"<li>{shell.esc(shell.clean(element['name'], _SPOKEN_CHARS))}</li>")
        elif element.get("type") == "text" and isinstance(element.get("text"), str):
            words = shell.clean(element["text"], _SPOKEN_CHARS)
            if words:
                entries.append(f"<li>{shell.esc(words)}</li>")
        if len(entries) == _MAX_SPOKEN:
            break
    return f'<ul class="visually-hidden">{"".join(entries)}</ul>' if entries else ""


def drawing(scene: dict[str, Any], *, run_dir: Path | None = None, label: str = "") -> str:
    """The scene as one ``<svg>`` (no page around it)."""
    elements = live_elements(scene)
    defs = _Defs()
    defs.parts.append(
        # Inverts a picture back in the dark theme, where the whole drawing is
        # inverted: hue turned half round, then each channel flipped.
        '<filter id="wb-reinvert" color-interpolation-filters="sRGB">'
        '<feColorMatrix type="hueRotate" values="180"/><feComponentTransfer>'
        '<feFuncR type="table" tableValues="1 0"/><feFuncG type="table" tableValues="1 0"/>'
        '<feFuncB type="table" tableValues="1 0"/></feComponentTransfer></filter>'
    )
    pictures = _Pictures(run_dir)
    frames: dict[str, str] = {}
    for element in elements:
        if element.get("type") == "frame":
            ident = f"wb-f{len(frames) + 1}"
            frames[str(element.get("id"))] = ident
            defs.parts.append(
                f'<clipPath id="{ident}"><rect x="{_n(_f(element, "x"))}" '
                f'y="{_n(_f(element, "y"))}" width="{_n(_f(element, "width"))}" '
                f'height="{_n(_f(element, "height"))}" rx="{_n(_FRAME_RADIUS)}"/></clipPath>'
            )
    # A label on an arrow or a line gets the board's background behind it.
    linear = {str(e.get("id")) for e in elements if e.get("type") in ("arrow", "line")}
    background = color(scene.get("appState", {}).get("viewBackgroundColor"), "#ffffff")
    halo = "#ffffff" if background == "transparent" else background
    shapes: list[str] = []
    for element in elements:
        clip = "" if element.get("type") == "frame" else frames.get(str(element.get("frameId")), "")
        on_line = element.get("type") == "text" and str(element.get("containerId")) in linear
        drawn = _shape_of(element, defs, pictures, halo if on_line else "")
        shapes.append(_placed(element, drawn, clip))
    x, y, width, height = _view_box(elements)
    box = f"{_n(x)} {_n(y)} {_n(width)} {_n(height)}"
    return (
        f'<svg class="wb-svg" id="wb-svg" xmlns="http://www.w3.org/2000/svg" viewBox="{box}" '
        f'data-box="{box}" preserveAspectRatio="xMidYMid meet" role="img" '
        f'aria-label="{shell.attr(label)}">'
        f"<defs>{''.join(defs.parts)}</defs>{''.join(shapes)}</svg>"
    )


# --- the page ------------------------------------------------------------------------------------

_CSS: Final[str] = """
.wb{position:fixed;inset:0;overflow:hidden;background:var(--bg);touch-action:none;cursor:grab;
  -webkit-user-select:none;user-select:none}
.wb:focus-visible{outline-offset:-2px}
.wb.is-panning{cursor:grabbing}
.wb-canvas{position:absolute;inset:0}
.wb-svg{display:block;width:100%;height:100%}
.wb-t{white-space:pre;font-family:var(--font,system-ui,sans-serif)}
.wb-mono{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
@media screen and (prefers-color-scheme:dark){
:root:not([data-theme="light"]) .wb-canvas{filter:invert(93%) hue-rotate(180deg)}
:root:not([data-theme="light"]) .wb-img{filter:url(#wb-reinvert)}}
@media screen{:root[data-theme="dark"] .wb-canvas{filter:invert(93%) hue-rotate(180deg)}
:root[data-theme="dark"] .wb-img{filter:url(#wb-reinvert)}}
.wb-empty{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;
  color:var(--ink-3);font-size:14px;line-height:20px;pointer-events:none}
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
.wb{position:relative;inset:auto;height:180mm}
.wb-canvas{filter:none!important}.wb-img{filter:none!important}
.wb-tools,.wb-meta{display:none}}
"""

# Pan, zoom and fit, by moving the SVG's viewBox. The script reads the
# drawing's box (numbers this module wrote) and nothing from the scene. The
# static viewBox already fits the drawing when the script does not run.
_JS: Final[str] = """
(function(){
var d=document,view=d.getElementById("wb"),svg=d.getElementById("wb-svg");
if(!view||!svg)return;
var label=d.getElementById("wb-zoom");
var box=(svg.getAttribute("data-box")||"").split(" ").map(Number);
if(box.length!==4||box.some(isNaN)||box[2]<=0||box[3]<=0)return;
var s=1,cx=box[0]+box[2]/2,cy=box[1]+box[3]/2,moved=false,MIN=.02,MAX=8;
function draw(){
  var w=svg.clientWidth||1,h=svg.clientHeight||1,vw=w/s,vh=h/s;
  svg.setAttribute("viewBox",(cx-vw/2)+" "+(cy-vh/2)+" "+vw+" "+vh);
  if(label)label.textContent=Math.round(s*100)+"%";
}
function fit(){
  var w=svg.clientWidth,h=svg.clientHeight;if(!w||!h)return;
  s=Math.max(MIN,Math.min(w/box[2],h/box[3],1));
  cx=box[0]+box[2]/2;cy=box[1]+box[3]/2;draw();
}
function zoom(k,px,py){
  var r=svg.getBoundingClientRect(),n=Math.max(MIN,Math.min(MAX,s*k));
  var ox=(px===undefined?0:px-r.left-r.width/2),oy=(py===undefined?0:py-r.top-r.height/2);
  cx+=ox/s-ox/n;cy+=oy/s-oy/n;s=n;moved=true;draw();
}
function pan(dx,dy){cx-=dx/s;cy-=dy/s;moved=true;draw();}
view.addEventListener("wheel",function(e){
  e.preventDefault();
  if(e.ctrlKey||e.metaKey){zoom(Math.exp(-e.deltaY*.01),e.clientX,e.clientY);}
  else{pan(-e.deltaX,-e.deltaY);}
},{passive:false});
var drag=null;
view.addEventListener("pointerdown",function(e){
  if(e.button!==0||e.target.closest(".wb-tools,.wb-meta"))return;
  drag={x:e.clientX,y:e.clientY,id:e.pointerId};
  try{view.setPointerCapture(e.pointerId);}catch(err){}
  view.classList.add("is-panning");
});
view.addEventListener("pointermove",function(e){
  if(!drag||e.pointerId!==drag.id)return;
  pan(e.clientX-drag.x,e.clientY-drag.y);drag.x=e.clientX;drag.y=e.clientY;
});
function end(){drag=null;view.classList.remove("is-panning");}
view.addEventListener("pointerup",end);view.addEventListener("pointercancel",end);
view.addEventListener("keydown",function(e){
  var k=e.key,step=60;
  if(k==="+"||k==="="){zoom(1.25);}else if(k==="-"||k==="_"){zoom(.8);}
  else if(k==="0"){fit();moved=false;}
  else if(k==="ArrowLeft"){pan(step,0);}else if(k==="ArrowRight"){pan(-step,0);}
  else if(k==="ArrowUp"){pan(0,step);}else if(k==="ArrowDown"){pan(0,-step);}
  else{return;}
  e.preventDefault();
});
d.querySelectorAll(".wb-tools button").forEach(function(b){
  b.addEventListener("click",function(){
    var a=b.getAttribute("data-act");
    if(a==="in")zoom(1.25);else if(a==="out")zoom(.8);
    else if(a==="reset"){zoom(1/s);}else if(a==="fit"){fit();moved=false;}
  });
});
addEventListener("resize",function(){if(!moved)fit();else draw();});
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


def _scene_of(node: Any) -> dict[str, Any]:
    """The node's scene; an empty board for a spec that cannot be one (a stored
    node must still open)."""
    spec = getattr(node, "spec", None)
    if not is_scene(spec):
        return empty_scene()
    try:
        return normalize_scene(spec)
    except NodeError:  # a broken stored scene: an empty board, not a crash
        return empty_scene()


def render(node: Any, *, run_dir: Path | None = None) -> str:
    """The board as one self-contained page. ``run_dir`` is the node's run
    directory, where its pictures are; without it pictures are boxes."""
    scene = _scene_of(node)
    title = str(getattr(node, "title", "") or "")
    elements = live_elements(scene)
    background = color(scene["appState"].get("viewBackgroundColor"), "#ffffff")
    meta = shell.upkeep_meta(node)
    empty = "" if elements else '<p class="wb-empty">This whiteboard is empty.</p>'
    body = (
        f'<main class="wb" id="wb" tabindex="0" aria-label="{shell.attr(title)}">'
        f'<h1 class="visually-hidden">{shell.esc(title)}</h1>'
        f'<div class="wb-canvas" style="background:{shell.attr(background)}">'
        f"{drawing(scene, run_dir=run_dir, label=title)}</div>"
        f"{empty}"
        + (f'<div class="wb-meta">{meta}</div>' if meta else "")
        + f"{_spoken(elements)}{_TOOLS}</main>"
    )
    return shell.document(node, body=body, css=_CSS, js=_JS, body_class="fill", kit_js=False)


__all__ = ["IMAGE_BUDGET_CHARS", "drawing", "render"]
