"""Free elements, backgrounds and the deck's look for the ``slides`` type.

A layout (``slides.py``) decides how a slide's texts sit: the model and the
person write WHAT a slide says and the layout makes it read well. A real deck
needs more than that: a logo in the corner, an arrow onto a number, a picture
beside a text, a coloured band, a picture behind the whole slide. That is
what this module adds, on top of every layout:

* ``elements``: objects placed freely on the slide's logical 1280 x 720 px
  canvas, in drawing order (the last on top): a ``text`` box, a ``shape``
  (that may hold text), a ``line`` or arrow, an ``image``, a ``table`` and a
  ``chart``. Each carries its box (``x``, ``y``, ``w``, ``h``), its rotation,
  opacity, an optional link and an optional entrance animation.
* ``background``: a colour, a gradient or a picture behind the slide, with a
  dimming veil for text on a photo. Set on the deck it is every slide's.
* ``tone``: a slide drawn light or dark whatever the deck's theme is (a dark
  chapter divider in a light deck). A dark background picks it by itself.
* the deck's ``font``, ``transition`` and ``footer``, and a slide's
  ``transition``, ``hidden`` and ``footer``.

Everything is bounded and checked here, so the renderer can trust it: a
colour is a token, a hex or rgb()/hsl(); a font is one of a fixed list of
families (as a class, never a free style); a picture is a ``data:`` URI. The
editor (``frontend/…/editors/slides/elements.tsx``) draws the very same
markup, so change both sides together (the markup fixture test checks it).

Pure functions, no I/O.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any, Final

from dodaios.artifacts.report_blocks import parse_chart, render_chart
from dodaios.nodes.shell import (
    MAX_IMAGE_CHARS,
    as_list,
    attr,
    clean,
    clean_block,
    color,
    esc,
    inline,
    number,
    safe_image,
    safe_link,
)
from dodaios.nodes.types import NodeError

# --- the grammar ---------------------------------------------------------------

#: The logical slide, in px; elements are placed in it.
SLIDE_W: Final[int] = 1280
SLIDE_H: Final[int] = 720

ELEMENT_TYPES: Final[tuple[str, ...]] = ("text", "shape", "line", "image", "table", "chart")
#: Shapes drawn as a CSS box (crisp corners at any size).
BOX_SHAPES: Final[tuple[str, ...]] = ("rect", "rounded", "ellipse")
#: Shapes drawn as an SVG path on a 100 x 100 box, stretched to the element.
PATH_SHAPES: Final[dict[str, str]] = {
    "triangle": "M50 0L100 100L0 100Z",
    "diamond": "M50 0L100 50L50 100L0 50Z",
    "pentagon": "M50 0L100 38L81 100L19 100L0 38Z",
    "hexagon": "M25 0L75 0L100 50L75 100L25 100L0 50Z",
    "star": (
        "M50 0L61.8 35.1L98.9 35.1L68.9 56.8L80.3 91.9L50 70.2L19.7 91.9L31.1 56.8"
        "L1.1 35.1L38.2 35.1Z"
    ),
    "arrow": "M0 30L62 30L62 4L100 50L62 96L62 70L0 70Z",
    "chevron": "M0 0L72 0L100 50L72 100L0 100L28 50Z",
    "parallelogram": "M22 0L100 0L78 100L0 100Z",
    "trapezoid": "M20 0L80 0L100 100L0 100Z",
    "callout": "M0 0L100 0L100 76L42 76L22 100L24 76L0 76Z",
    "plus": "M36 0L64 0L64 36L100 36L100 64L64 64L64 100L36 100L36 64L0 64L0 36L36 36Z",
}
SHAPES: Final[tuple[str, ...]] = (*BOX_SHAPES, *PATH_SHAPES)
_SHAPE_ALIASES: Final[dict[str, str]] = {
    "rectangle": "rect",
    "box": "rect",
    "square": "rect",
    "round": "rounded",
    "pill": "rounded",
    "circle": "ellipse",
    "oval": "ellipse",
    "arrow-right": "arrow",
    "speech": "callout",
    "bubble": "callout",
}

#: Font families an element or the deck may take: a class each, never a free style.
FONTS: Final[dict[str, str]] = {
    "sans": "var(--font)",
    "serif": 'Georgia,"Times New Roman",serif',
    "mono": 'ui-monospace,"Cascadia Mono",Consolas,"Courier New",monospace',
    "rounded": (
        'ui-rounded,"SF Pro Rounded","Arial Rounded MT Bold","Segoe UI Variable Display",'
        "system-ui,sans-serif"
    ),
    "condensed": (
        '"Bahnschrift SemiCondensed","Arial Narrow","Roboto Condensed",'
        "sans-serif-condensed,sans-serif"
    ),
    "geometric": '"Century Gothic",Futura,Avenir,"Avenir Next","Segoe UI",sans-serif',
    "classic": 'Garamond,"EB Garamond","Palatino Linotype",Palatino,Georgia,serif',
    "arial": "Arial,Helvetica,sans-serif",
    "helvetica": '"Helvetica Neue",Helvetica,Arial,sans-serif',
    "verdana": "Verdana,Geneva,sans-serif",
    "trebuchet": '"Trebuchet MS","Gill Sans",sans-serif',
    "tahoma": "Tahoma,Verdana,sans-serif",
    "segoe": '"Segoe UI",system-ui,sans-serif',
    "georgia": "Georgia,serif",
    "times": '"Times New Roman",Times,serif',
    "palatino": '"Palatino Linotype",Palatino,"Book Antiqua",serif',
    "courier": '"Courier New",Courier,monospace',
    "impact": 'Impact,"Arial Black",sans-serif',
}
#: The deck's own type pairings: a family for the whole slide, or headings apart.
DECK_FONTS: Final[tuple[str, ...]] = (
    "sans",
    "serif",
    "editorial",
    "mono",
    "rounded",
    "condensed",
    "geometric",
    "classic",
)
TRANSITIONS: Final[tuple[str, ...]] = ("none", "fade", "slide", "rise", "zoom")
ANIMATIONS: Final[tuple[str, ...]] = ("fade", "rise", "slide", "zoom", "pop", "wipe")
ALIGNS: Final[tuple[str, ...]] = ("left", "center", "right", "justify")
VALIGNS: Final[tuple[str, ...]] = ("top", "middle", "bottom")
LISTS: Final[tuple[str, ...]] = ("none", "bullet", "number")
DASHES: Final[tuple[str, ...]] = ("solid", "dash", "dot")
ENDS: Final[tuple[str, ...]] = ("none", "arrow", "dot")
FITS: Final[tuple[str, ...]] = ("cover", "contain", "fill")
TONES: Final[tuple[str, ...]] = ("light", "dark")

MAX_ELEMENTS: Final[int] = 40
TEXT_CHARS: Final[int] = 2_000
CELL_CHARS: Final[int] = 160
MAX_TABLE_ROWS: Final[int] = 14
MAX_TABLE_COLUMNS: Final[int] = 8
_ID_RE: Final = re.compile(r"^[A-Za-z0-9_-]{1,24}$")
_CONTROL_RE: Final = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

#: Colours a spec may name besides the kit's (``shell.NAMED_COLORS``).
_PLAIN_COLORS: Final[dict[str, str]] = {
    "white": "#ffffff",
    "black": "#000000",
    "transparent": "transparent",
}

#: What an element of each type keeps; anything else is dropped.
_COMMON: Final[tuple[str, ...]] = ("id", "rotate", "opacity", "link", "anim", "click", "locked")


# --- small readers -----------------------------------------------------------------


def _num(value: float) -> int | float:
    """A number as the spec keeps it: whole numbers as ints, else one decimal."""
    rounded = round(value, 1)
    return int(rounded) if float(rounded).is_integer() else rounded


def _bounded(value: Any, low: float, high: float) -> int | float | None:
    found = number(value)
    if found is None:
        return None
    return _num(max(low, min(high, found)))


def _flag(value: Any) -> bool:
    return value is True or (isinstance(value, str) and value.strip().lower() in ("true", "yes"))


def _word(value: Any, allowed: tuple[str, ...], aliases: dict[str, str] | None = None) -> str:
    text = str(value or "").strip().lower() if isinstance(value, (str, int, float)) else ""
    if aliases:
        text = aliases.get(text, text)
    return text if text in allowed else ""


def spec_color(value: Any) -> str:
    """A colour as the spec keeps it (a name lowercased, or the CSS text), else ``""``."""
    if not isinstance(value, str):
        return ""
    text = value.strip()
    lower = text.lower()
    if lower in _PLAIN_COLORS:
        return lower
    if not text or lower in ("none", "default"):
        return ""
    if color(text):
        return lower if color(lower) and not text.startswith(("#", "rgb", "hsl")) else text
    return ""


def css_color(value: Any) -> str:
    """The CSS for a colour the spec keeps; the deck's accent is ``var(--da)``."""
    text = str(value or "")
    lower = text.lower()
    if lower == "accent":
        return "var(--da)"
    if lower in _PLAIN_COLORS:
        return _PLAIN_COLORS[lower]
    return color(text)


def _text(value: Any, limit: int) -> str:
    if isinstance(value, (list, tuple)):
        value = "\n".join(str(part) for part in value if isinstance(part, (str, int, float)))
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return ""
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e15:
        value = int(value)
    text = _CONTROL_RE.sub("", clean_block(str(value), limit + 1))
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def _line(value: Any, limit: int) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return ""
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e15:
        value = int(value)
    text = clean(_CONTROL_RE.sub("", str(value)), limit + 1)
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def _image(value: Any, where: str) -> str:
    source = safe_image(value)
    if not source:
        raise NodeError(
            f'{where}: "image" must be the absolute path of a PNG, JPEG or WebP file on this '
            f"computer or a data:image URI of at most {MAX_IMAGE_CHARS} characters (the page "
            "has no network, so no web address)."
        )
    return source


# --- the chart grammar (shared with a chart slide) ---------------------------------


def _plain_number(value: float | None) -> float | int | None:
    if value is None:
        return None
    return int(value) if value.is_integer() and abs(value) < 1e15 else value


def chart_spec(parsed: dict[str, Any], max_bar_rows: int = 10) -> dict[str, Any]:
    """A parsed chart as the JSON the chart reader accepts again."""
    rows = max_bar_rows if parsed["type"] == "bar" else len(parsed["x"])
    chart: dict[str, Any] = {"type": parsed["type"]}
    for key in ("title", "note", "unit", "value", "delta"):
        if parsed[key]:
            chart[key] = parsed[key]
    if parsed.get("stacked"):
        chart["stacked"] = True
    chart["x"] = list(parsed["x"][:rows])
    series = []
    for name, data in parsed["series"]:
        entry: dict[str, Any] = {"name": name} if name else {}
        entry["data"] = [_plain_number(point) for point in data[:rows]]
        series.append(entry)
    chart["series"] = series
    colors = parsed.get("colors")
    if isinstance(colors, (list, tuple)) and any(colors):
        chart["colors"] = list(colors)
    return chart


CHART_HINT: Final[str] = (
    '"chart" must be {"type": "line" | "area" | "column" | "bar" | "pie" | "donut", '
    '"x": [2 or more labels], "series": [{"name": …, "data": [one number per label]}]}, '
    'with optional "unit", "title", "note", "stacked" and "colors".'
)


def read_chart(value: Any, where: str) -> dict[str, Any]:
    """A chart in the report chart grammar, or ``NodeError`` with what to send."""
    if value in (None, "", [], {}):
        return {}
    hint = f"{where}: {CHART_HINT}"
    chart = value
    # Twice: the reader trims what it clips, and the second reading settles it.
    for _ in range(2):
        try:
            source = chart if isinstance(chart, str) else json.dumps(chart)
        except (TypeError, ValueError) as error:
            raise NodeError(hint) from error
        parsed = parse_chart(source)
        if parsed is None:
            raise NodeError(hint)
        chart = chart_spec(parsed)
        if any(all(point is None for point in entry["data"]) for entry in chart["series"]):
            raise NodeError(hint)
    return chart if isinstance(chart, dict) else {}


# --- elements ----------------------------------------------------------------------


def _box(raw: dict[str, Any], element: dict[str, Any], default: tuple[float, float]) -> None:
    """``x``, ``y``, ``w``, ``h`` of a boxed element, inside sane bounds."""
    width, height = default
    element["x"] = _bounded(raw.get("x"), -SLIDE_W, 2 * SLIDE_W) or 0
    element["y"] = _bounded(raw.get("y"), -SLIDE_H, 2 * SLIDE_H) or 0
    element["w"] = _bounded(raw.get("w", raw.get("width")), 4, 2 * SLIDE_W) or _num(width)
    element["h"] = _bounded(raw.get("h", raw.get("height")), 4, 2 * SLIDE_H) or _num(height)


def _common(raw: dict[str, Any], element: dict[str, Any]) -> None:
    ident = raw.get("id")
    if isinstance(ident, str) and _ID_RE.match(ident):
        element["id"] = ident
    rotate = _bounded(raw.get("rotate"), -360, 360)
    if rotate:
        element["rotate"] = rotate
    opacity = _bounded(raw.get("opacity"), 0, 100)
    if opacity is not None and opacity < 100:
        element["opacity"] = opacity
    link = safe_link(raw.get("link"))
    if link:
        element["link"] = link
    anim = _word(raw.get("anim"), ANIMATIONS)
    if anim:
        element["anim"] = anim
        if _flag(raw.get("click")):
            element["click"] = True
    if _flag(raw.get("locked")):
        element["locked"] = True


def _fill_and_stroke(raw: dict[str, Any], element: dict[str, Any], *, radius: bool) -> None:
    fill = spec_color(raw.get("fill"))
    if fill:
        element["fill"] = fill
    stroke = spec_color(raw.get("stroke") or raw.get("border"))
    width = _bounded(raw.get("stroke_width", raw.get("border_width")), 0, 40)
    if stroke and width != 0:
        element["stroke"] = stroke
        element["stroke_width"] = width if width is not None else 2
        dash = _word(raw.get("dash"), DASHES)
        if dash and dash != "solid":
            element["dash"] = dash
    if radius:
        corner = _bounded(raw.get("radius"), 0, 400)
        if corner:
            element["radius"] = corner
    if _flag(raw.get("shadow")):
        element["shadow"] = True


def _text_style(raw: dict[str, Any], element: dict[str, Any], *, shape: bool) -> None:
    element["text"] = _text(raw.get("text"), TEXT_CHARS)
    size = _bounded(raw.get("size"), 8, 240)
    if size is not None:
        element["size"] = size
    font = _word(raw.get("font"), tuple(FONTS))
    if font:
        element["font"] = font
    ink = spec_color(raw.get("color"))
    if ink:
        element["color"] = ink
    for key in ("bold", "italic", "underline", "strike", "caps"):
        if _flag(raw.get(key)):
            element[key] = True
    align = _word(raw.get("align"), ALIGNS)
    if align and align != ("center" if shape else "left"):
        element["align"] = align
    valign = _word(raw.get("valign"), VALIGNS, {"center": "middle"})
    if valign and valign != ("middle" if shape else "top"):
        element["valign"] = valign
    height = _bounded(raw.get("line"), 0.8, 3)
    if height is not None:
        element["line"] = height
    spacing = _bounded(raw.get("spacing"), -0.1, 0.5)
    if spacing:
        element["spacing"] = spacing
    kind = _word(raw.get("list"), LISTS, {"bullets": "bullet", "numbers": "number"})
    if kind and kind != "none":
        element["list"] = kind
    padding = _bounded(raw.get("padding"), 0, 120)
    if padding is not None:
        element["padding"] = padding


def _table_rows(raw: dict[str, Any], where: str) -> list[list[str]]:
    hint = (
        f'{where}: a table element needs "rows": up to {MAX_TABLE_ROWS} lists of up to '
        f'{MAX_TABLE_COLUMNS} short cells (the first row is the header unless "head": false).'
    )
    source = raw.get("rows")
    columns = raw.get("columns") or raw.get("headers")
    if isinstance(columns, list) and columns and isinstance(source, list):
        source = [columns, *source]
    rows: list[list[str]] = []
    for row in as_list(source, 4 * MAX_TABLE_ROWS):
        if isinstance(row, dict):
            row = list(row.values())
        if not isinstance(row, (list, tuple)):
            continue
        rows.append([_line(cell, CELL_CHARS) for cell in list(row)[:MAX_TABLE_COLUMNS]])
        if len(rows) == MAX_TABLE_ROWS:
            break
    if not rows or not any(rows):
        raise NodeError(hint)
    width = max(len(row) for row in rows)
    if width == 0:
        raise NodeError(hint)
    return [row + [""] * (width - len(row)) for row in rows]


def read_element(raw: Any, where: str) -> dict[str, Any] | None:
    """One clean element, ``None`` for an entry that is no object, or ``NodeError``."""
    if not isinstance(raw, dict):
        return None
    kind = _word(
        raw.get("type"),
        ELEMENT_TYPES,
        {"textbox": "text", "picture": "image", "arrow": "line", "graph": "chart"},
    )
    if not kind and raw.get("shape"):
        kind = "shape"
    if not kind:
        raise NodeError(f'{where}: an element needs a "type": {", ".join(ELEMENT_TYPES)}.')
    element: dict[str, Any] = {"type": kind}
    if kind == "line":
        if str(raw.get("type", "")).strip().lower() == "arrow" and "end" not in raw:
            raw = {**raw, "end": "arrow"}
        for key, low, high, fallback in (
            ("x1", -SLIDE_W, 2 * SLIDE_W, 0),
            ("y1", -SLIDE_H, 2 * SLIDE_H, 0),
            ("x2", -SLIDE_W, 2 * SLIDE_W, 200),
            ("y2", -SLIDE_H, 2 * SLIDE_H, 0),
        ):
            found = _bounded(raw.get(key), low, high)
            element[key] = found if found is not None else fallback
        ink = spec_color(raw.get("color") or raw.get("stroke"))
        if ink:
            element["color"] = ink
        width = _bounded(raw.get("width", raw.get("stroke_width")), 1, 40)
        if width is not None:
            element["width"] = width
        dash = _word(raw.get("dash"), DASHES)
        if dash and dash != "solid":
            element["dash"] = dash
        for key in ("start", "end"):
            end = _word(raw.get(key), ENDS)
            if end and end != "none":
                element[key] = end
        _common(raw, element)
        element.pop("rotate", None)
        return element
    if kind == "text":
        _box(raw, element, (480, 120))
        _text_style(raw, element, shape=False)
        _fill_and_stroke(raw, element, radius=True)
    elif kind == "shape":
        _box(raw, element, (240, 240))
        element["shape"] = _word(raw.get("shape"), SHAPES, _SHAPE_ALIASES) or "rect"
        _text_style(raw, element, shape=True)
        if not element["text"]:
            del element["text"]
        _fill_and_stroke(raw, element, radius=element["shape"] == "rect")
    elif kind == "image":
        _box(raw, element, (480, 320))
        element["image"] = _image(raw.get("image") or raw.get("src"), where)
        fit = _word(raw.get("fit"), FITS)
        if fit and fit != "cover":
            element["fit"] = fit
        alt = _line(raw.get("alt"), 140)
        if alt:
            element["alt"] = alt
        _fill_and_stroke(raw, element, radius=True)
        element.pop("fill", None)
    elif kind == "table":
        _box(raw, element, (720, 320))
        element["rows"] = _table_rows(raw, where)
        if raw.get("head") is False or str(raw.get("head")).lower() == "false":
            element["head"] = False
        size = _bounded(raw.get("size"), 8, 72)
        if size is not None:
            element["size"] = size
        font = _word(raw.get("font"), tuple(FONTS))
        if font:
            element["font"] = font
        for key in ("color", "fill", "stroke"):
            found = spec_color(raw.get(key))
            if found:
                element[key] = found
        align = _word(raw.get("align"), ALIGNS)
        if align and align != "left":
            element["align"] = align
    else:  # chart
        _box(raw, element, (720, 400))
        chart = read_chart(
            raw.get("chart")
            or {
                k: v
                for k, v in raw.items()
                if k in ("x", "series", "unit", "title", "note", "stacked", "colors")
            }
            | ({"type": raw["kind"]} if raw.get("kind") else {}),
            where,
        )
        if not chart:
            raise NodeError(f"{where}: {CHART_HINT}")
        element["chart"] = chart
    _common(raw, element)
    return element


def read_elements(value: Any, where: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for index, raw in enumerate(as_list(value, 4 * MAX_ELEMENTS)):
        element = read_element(raw, f"{where}, element {index + 1} (elements/{index})")
        if element:
            found.append(element)
        if len(found) == MAX_ELEMENTS:
            break
    return found


# --- backgrounds, tone and the slide's own settings -----------------------------------


def read_background(value: Any, where: str) -> dict[str, Any]:
    """A slide's (or the deck's) background, or ``{}``."""
    if isinstance(value, str):
        value = (
            {"image": value}
            if value.strip().startswith(("data:", "/", "~", "file:"))
            or (len(value) > 2 and value[1] == ":")
            else {"color": value}
        )
    if not isinstance(value, dict):
        return {}
    background: dict[str, Any] = {}
    ink = spec_color(value.get("color"))
    if ink:
        background["color"] = ink
    gradient = value.get("gradient")
    if isinstance(gradient, (list, tuple)) and len(gradient) >= 2:
        gradient = {"from": gradient[0], "to": gradient[1]}
    if isinstance(gradient, dict):
        start, end = spec_color(gradient.get("from")), spec_color(gradient.get("to"))
        if start and end:
            angle = _bounded(gradient.get("angle"), 0, 360)
            background["gradient"] = {
                "from": start,
                "to": end,
                "angle": 135 if angle is None else angle,
            }
    if value.get("image") not in (None, ""):
        background["image"] = _image(value.get("image"), f"{where}, background")
        fit = _word(value.get("fit"), ("cover", "contain"))
        if fit == "contain":
            background["fit"] = "contain"
    dim = _bounded(value.get("dim"), 0, 90)
    if dim and ("image" in background or "gradient" in background or "color" in background):
        background["dim"] = dim
    return background


def read_slide_extras(raw: dict[str, Any], where: str) -> dict[str, Any]:
    """What a slide carries besides its layout's fields (all optional)."""
    extras: dict[str, Any] = {}
    background = read_background(raw.get("background"), where)
    if background:
        extras["background"] = background
    tone = _word(raw.get("tone"), TONES)
    if tone:
        extras["tone"] = tone
    transition = _word(raw.get("transition"), TRANSITIONS)
    if transition:
        extras["transition"] = transition
    if _flag(raw.get("hidden")):
        extras["hidden"] = True
    if raw.get("footer") is False:
        extras["footer"] = False
    elements = read_elements(raw.get("elements"), where)
    if elements:
        extras["elements"] = elements
    return extras


def read_deck_extras(spec: dict[str, Any]) -> dict[str, Any]:
    extras: dict[str, Any] = {}
    font = _word(spec.get("font"), DECK_FONTS)
    if font and font != "sans":
        extras["font"] = font
    background = read_background(spec.get("background"), "The deck")
    if background:
        extras["background"] = background
    transition = _word(spec.get("transition"), TRANSITIONS)
    if transition:
        extras["transition"] = transition
    if spec.get("footer") is False:
        extras["footer"] = False
    return extras


# --- drawing ---------------------------------------------------------------------------


def _hex_luminance(value: str) -> float | None:
    """The relative luminance of a hex colour, ``None`` for anything else."""
    text = _PLAIN_COLORS.get(value.lower(), value)
    found = re.fullmatch(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})(?:[0-9a-fA-F]{2})?", text) or (
        re.fullmatch(r"#([0-9a-fA-F]{4})", text)
    )
    if not found:
        return None
    digits = found.group(1)
    if len(digits) in (3, 4):
        digits = "".join(c * 2 for c in digits[:3])
    channels = [int(digits[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def auto_tone(background: dict[str, Any]) -> str:
    """The tone a background asks for by itself: dark on a dark ground, else ``""``."""
    if not background:
        return ""
    if background.get("image") and (background.get("dim") or 0) >= 35:
        return "dark"
    if background.get("image"):
        return ""
    if "gradient" in background:
        lights = [
            _hex_luminance(background["gradient"]["from"]),
            _hex_luminance(background["gradient"]["to"]),
        ]
        if any(light is None for light in lights):
            return ""
        light = sum(lights) / 2  # type: ignore[arg-type]
    elif background.get("color"):
        light = _hex_luminance(background["color"])
        if light is None:
            return ""
    else:
        return ""
    if background.get("dim"):
        light *= 1 - background["dim"] / 100
    return "dark" if light < 0.22 else "light"


def background_html(background: dict[str, Any]) -> str:
    """The layer behind a slide's content."""
    if not background:
        return ""
    style = ""
    if "gradient" in background:
        gradient = background["gradient"]
        style = (
            f"background:linear-gradient({gradient['angle']}deg,"
            f"{css_color(gradient['from'])},{css_color(gradient['to'])})"
        )
    elif background.get("color"):
        style = f"background:{css_color(background['color'])}"
    inner = ""
    source = safe_image(background.get("image"))
    if source:
        klass = ' class="is-contain"' if background.get("fit") == "contain" else ""
        inner += f'<img src="{attr(source)}" alt=""{klass}>'
    if background.get("dim"):
        inner += f'<i class="sl-dim" style="opacity:{_fmt(background["dim"] / 100)}"></i>'
    opening = f'<div class="sl-bg" style="{attr(style)}">' if style else '<div class="sl-bg">'
    return f"{opening}{inner}</div>"


def _fmt(value: float) -> str:
    """A number for a style: up to two decimals, no trailing zeros (as the editor writes it)."""
    rounded = round(value * 100) / 100
    text = f"{rounded:.2f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def _px(value: float) -> str:
    return f"{_fmt(value)}px"


def _box_style(element: dict[str, Any]) -> list[str]:
    parts = [
        f"left:{_px(element['x'])}",
        f"top:{_px(element['y'])}",
        f"width:{_px(element['w'])}",
        f"height:{_px(element['h'])}",
    ]
    if element.get("rotate"):
        parts.append(f"rotate:{_fmt(element['rotate'])}deg")
    if element.get("opacity") is not None:
        parts.append(f"opacity:{_fmt(element['opacity'] / 100)}")
    return parts


def _paint(element: dict[str, Any], parts: list[str], *, box: bool) -> None:
    """Fill, outline and corners of a CSS-drawn element."""
    if box and element.get("fill"):
        parts.append(f"background:{css_color(element['fill'])}")
    if box and element.get("stroke"):
        dash = {"dash": "dashed", "dot": "dotted"}.get(element.get("dash", ""), "solid")
        parts.append(
            f"border:{_px(element.get('stroke_width', 2))} {dash} {css_color(element['stroke'])}"
        )
    if box and element.get("radius"):
        parts.append(f"border-radius:{_px(element['radius'])}")


def _text_classes(element: dict[str, Any], shape: bool) -> list[str]:
    classes = []
    valign = element.get("valign", "middle" if shape else "top")
    if valign == "middle":
        classes.append("v-m")
    elif valign == "bottom":
        classes.append("v-b")
    return classes


def _text_inner_style(element: dict[str, Any], shape: bool) -> str:
    parts = [f"font-size:{_px(element.get('size', 24 if shape else 28))}"]
    if element.get("color"):
        parts.append(f"color:{css_color(element['color'])}")
    elif shape and shape_ink(element.get("fill", "")):
        parts.append(f"color:{shape_ink(element.get('fill', ''))}")
    align = element.get("align", "center" if shape else "left")
    if align != "left":
        parts.append(f"text-align:{align}")
    if element.get("line") is not None:
        parts.append(f"line-height:{_fmt(element['line'])}")
    if element.get("spacing"):
        parts.append(f"letter-spacing:{_fmt(element['spacing'])}em")
    return ";".join(parts)


def shape_ink(fill: str) -> str:
    """The text colour that reads on a shape's own fill, when the fill says it.

    A hex fill gets black or white by its lightness; a transparent shape the
    slide's ink. A fill of the kit's (the accent, a series colour) is left to
    the stylesheet, which knows the theme it is drawn in.
    """
    if not fill:
        return ""
    if fill.lower() == "transparent":
        return "var(--ink)"
    light = _hex_luminance(fill)
    if light is None:
        return ""
    return "#111111" if light > 0.4 else "#ffffff"


def _text_inner_classes(element: dict[str, Any]) -> str:
    classes = ["el-t"]
    if element.get("font"):
        classes.append(f"ff-{element['font']}")
    for key, klass in (
        ("bold", "is-b"),
        ("italic", "is-i"),
        ("underline", "is-u"),
        ("strike", "is-s"),
        ("caps", "is-c"),
    ):
        if element.get(key):
            classes.append(klass)
    return " ".join(classes)


def text_content(text: str, kind: str) -> str:
    """A text element's words as HTML: lines, or a list of its non-empty lines."""
    if kind in ("bullet", "number"):
        tag = "ul" if kind == "bullet" else "ol"
        items = "".join(f"<li>{inline(line)}</li>" for line in text.split("\n") if line.strip())
        return f"<{tag}>{items}</{tag}>"
    return "<br>".join(inline(part) for part in text.split("\n"))


def _opening(
    element: dict[str, Any],
    kind: str,
    classes: list[str],
    style: list[str],
    index: int,
    delay: int | None,
) -> str:
    klass = " ".join(["el", f"el-{kind}", *classes])
    if element.get("shadow"):
        klass += " is-shadow"
    marks = f' data-el="{index}"'
    if element.get("id"):
        marks += f' data-id="{attr(element["id"])}"'
    if element.get("anim"):
        marks += f' data-anim="{element["anim"]}"'
        if element.get("click"):
            marks += " data-click"
        elif delay is not None:
            style = [*style, f"--ad:{delay}ms"]
    return f'<div class="{klass}"{marks} style="{attr(";".join(style))}">'


def _linked(element: dict[str, Any], inner: str) -> str:
    link = element.get("link")
    if not link:
        return inner
    return f'<a class="el-a" href="{attr(link)}" rel="noopener noreferrer">{inner}</a>'


def _arrow_head(x: float, y: float, ux: float, uy: float, size: float) -> str:
    """The points of an arrow head at (x, y) pointing along (ux, uy)."""
    back_x, back_y = x - ux * size * 1.6, y - uy * size * 1.6
    nx, ny = -uy * size, ux * size
    points = [(x, y), (back_x + nx, back_y + ny), (back_x - nx, back_y - ny)]
    return " ".join(f"{_fmt(px)},{_fmt(py)}" for px, py in points)


def line_svg(element: dict[str, Any], index: int, delay: int | None) -> str:
    """A line or an arrow, as an SVG over its bounding box (with room for its ends)."""
    x1, y1, x2, y2 = element["x1"], element["y1"], element["x2"], element["y2"]
    width = element.get("width", 4)
    pad = width * 3 + 4
    left, top = min(x1, x2) - pad, min(y1, y2) - pad
    box_w, box_h = abs(x2 - x1) + 2 * pad, abs(y2 - y1) + 2 * pad
    ink = css_color(element.get("color")) or "var(--ink)"
    a = (x1 - left, y1 - top)
    b = (x2 - left, y2 - top)
    length = math.hypot(b[0] - a[0], b[1] - a[1]) or 1
    ux, uy = (b[0] - a[0]) / length, (b[1] - a[1]) / length
    head = width * 1.8 + 3
    # The stroke stops short of an arrow head, so its square end never shows past the tip.
    start = (
        (a[0] + ux * head * 1.4, a[1] + uy * head * 1.4) if element.get("start") == "arrow" else a
    )
    end = (b[0] - ux * head * 1.4, b[1] - uy * head * 1.4) if element.get("end") == "arrow" else b
    stroke = f"stroke:{ink};stroke-width:{_fmt(width)}"
    dash = element.get("dash")
    if dash == "dash":
        stroke += f";stroke-dasharray:{_fmt(width * 3)} {_fmt(width * 2)}"
    elif dash == "dot":
        stroke += f";stroke-dasharray:0 {_fmt(width * 2)};stroke-linecap:round"
    shapes = (
        f'<line x1="{_fmt(start[0])}" y1="{_fmt(start[1])}" x2="{_fmt(end[0])}" '
        f'y2="{_fmt(end[1])}" style="{stroke}"></line>'
    )
    for key, (px, py), (dx, dy) in (("start", a, (-ux, -uy)), ("end", b, (ux, uy))):
        kind = element.get(key)
        if kind == "arrow":
            tip = _arrow_head(px, py, dx, dy, head)
            shapes += f'<polygon points="{tip}" style="fill:{ink}"></polygon>'
        elif kind == "dot":
            shapes += (
                f'<circle cx="{_fmt(px)}" cy="{_fmt(py)}" r="{_fmt(width * 1.6 + 2)}" '
                f'style="fill:{ink}"></circle>'
            )
    style = [
        f"left:{_px(left)}",
        f"top:{_px(top)}",
        f"width:{_px(box_w)}",
        f"height:{_px(box_h)}",
    ]
    if element.get("opacity") is not None:
        style.append(f"opacity:{_fmt(element['opacity'] / 100)}")
    opening = _opening(element, "line", [], style, index, delay)
    svg = (
        f'<svg class="el-svg" viewBox="0 0 {_fmt(box_w)} {_fmt(box_h)}" aria-hidden="true">'
        f"{shapes}</svg>"
    )
    return f"{opening}{_linked(element, svg)}</div>"


def element_html(
    element: dict[str, Any], index: int, delay: int | None, language: str, marks: Any = None
) -> str:
    """One element of a slide as the page draws it."""
    kind = element["type"]

    def mark(
        value: str, *parts: str | int, shown: str | None = None, multiline: bool = False
    ) -> str:
        if marks is None:
            return ""
        return str(marks(value, "elements", index, *parts, shown=shown, multiline=multiline))

    if kind == "line":
        return line_svg(element, index, delay)
    style = _box_style(element)
    if kind in ("text", "shape"):
        shape = kind == "shape"
        figure = ""
        classes = _text_classes(element, shape)
        name = element.get("shape", "rect") if shape else ""
        if shape:
            classes.insert(0, f"is-{name}")
        if shape and name in PATH_SHAPES:
            paint = [f"fill:{css_color(element.get('fill')) or 'var(--da)'}"]
            if element.get("stroke"):
                paint.append(f"stroke:{css_color(element['stroke'])}")
                paint.append(f"stroke-width:{_fmt(element.get('stroke_width', 2))}")
                if element.get("dash") == "dash":
                    paint.append("stroke-dasharray:8 6")
                elif element.get("dash") == "dot":
                    paint.append("stroke-dasharray:2 5")
            figure = (
                '<svg class="el-svg" viewBox="0 0 100 100" preserveAspectRatio="none" '
                f'aria-hidden="true"><path d="{PATH_SHAPES[name]}" '
                f'vector-effect="non-scaling-stroke" style="{";".join(paint)}"></path></svg>'
            )
        else:
            if shape and not element.get("fill"):
                style.append("background:var(--da)")
            _paint(element, style, box=True)
            if shape and name == "rounded" and not element.get("radius"):
                style.append(f"border-radius:{_px(min(element['w'], element['h']) * 0.18)}")
            elif shape and name == "ellipse":
                style.append("border-radius:50%")
        padding = element.get("padding")
        if padding is None:
            boxed = shape or element.get("fill") or element.get("stroke")
            padding = 16 if boxed else 0
        if padding:
            style.append(f"padding:{_px(padding)}")
        text = element.get("text", "")
        inner = ""
        if text or kind == "text":
            listed = element.get("list", "none")
            html = text_content(text, listed)
            field = mark(text, "text", shown=html, multiline=True) if listed == "none" else ""
            inner = (
                f'<div class="{_text_inner_classes(element)}" '
                f'style="{attr(_text_inner_style(element, shape))}"{field}>{html}</div>'
            )
        opening = _opening(element, kind, classes, style, index, delay)
        return f"{opening}{figure}{_linked(element, inner)}</div>"
    if kind == "image":
        _paint(element, style, box=True)
        source = safe_image(element.get("image"))
        fit = element.get("fit", "cover")
        klass = f' class="is-{fit}"' if fit != "cover" else ""
        alt = attr(element.get("alt", ""))
        picture = f'<img src="{attr(source)}" alt="{alt}"{klass}>' if source else ""
        opening = _opening(element, "image", [], style, index, delay)
        return f"{opening}{_linked(element, picture)}</div>"
    if kind == "table":
        rows = element.get("rows", [])
        head = element.get("head", True)
        table_style = [f"font-size:{_px(element.get('size', 20))}"]
        if element.get("color"):
            table_style.append(f"color:{css_color(element['color'])}")
        if element.get("fill"):
            table_style.append(f"--tf:{css_color(element['fill'])}")
        if element.get("stroke"):
            table_style.append(f"--tl:{css_color(element['stroke'])}")
        align = element.get("align", "left")
        if align != "left":
            table_style.append(f"text-align:{align}")
        body = ""
        for number_, row in enumerate(rows):
            tag = "th" if head and number_ == 0 else "td"
            cells = "".join(
                f"<{tag}{mark(cell, 'rows', number_, column)}>{esc(cell)}</{tag}>"
                for column, cell in enumerate(row)
            )
            body += f"<tr>{cells}</tr>"
        classes = ["el-table"]
        if head:
            classes.append("has-head")
        if element.get("font"):
            classes.append(f"ff-{element['font']}")
        opening = _opening(element, "table", [], style, index, delay)
        return (
            f'{opening}<table class="{" ".join(classes)}" style="{attr(";".join(table_style))}">'
            f"<tbody>{body}</tbody></table></div>"
        )
    # chart
    figure = ""
    parsed = parse_chart(json.dumps(element.get("chart") or {}))
    if parsed is not None:
        figure = render_chart(parsed, language)
    opening = _opening(element, "chart", [], style, index, delay)
    return f"{opening}{figure}</div>"


def elements_html(elements: list[dict[str, Any]], language: str, marks: Any = None) -> str:
    """The layer of a slide's free elements, in drawing order."""
    if not elements:
        return ""
    parts = []
    step = 0
    for index, element in enumerate(elements):
        delay = None
        if element.get("anim") and not element.get("click"):
            delay = 150 + 120 * step
            step += 1
        parts.append(element_html(element, index, delay, language, marks))
    return f'<div class="sl-els">{"".join(parts)}</div>'


# --- styles ------------------------------------------------------------------------

#: The fonts as classes: an element's (``ff-*``) and the deck's (``f-*`` on a slide).
FONT_CSS: Final[str] = (
    "".join(f".ff-{name}{{font-family:{family}}}" for name, family in FONTS.items())
    + "".join(
        f".sl.f-{name}{{font-family:{FONTS[name]}}}"
        for name in ("serif", "mono", "rounded", "geometric", "classic")
    )
    + (
        ".sl.f-editorial :is(.sl-h,.sl-big,.sl-q blockquote,.sl-col h3,.sl-steps h3,.sl-v)"
        f"{{font-family:{FONTS['serif']};font-weight:500;letter-spacing:-.012em}}"
        ".sl.f-condensed :is(.sl-h,.sl-big,.sl-v,.sl-col h3,.sl-steps h3)"
        f"{{font-family:{FONTS['condensed']};letter-spacing:-.01em}}"
        ".sl.f-classic :is(.sl-h,.sl-big){font-weight:500;letter-spacing:-.01em}"
        ".sl.f-serif :is(.sl-h,.sl-big){font-weight:500;letter-spacing:-.02em}"
        ".sl.f-mono :is(.sl-h,.sl-big){letter-spacing:-.04em}"
    )
)

#: Where an element's animation plays: the current slide of the page's player
#: (not in the overview, nor in a picture of one slide) and the editor's
#: presentation; an element that waits for a click only once it is built.
_PLAYING_PAGE: Final[str] = (
    '.dk.is-ready:not(.is-overview):not(.is-still) .dk-cell.is-current .el[data-anim="{name}"]'
)
_PLAYING_EDITOR: Final[str] = '.ed-stage.is-presenting .el[data-anim="{name}"]'
_PLAYING: Final[str] = ",".join(
    f"{where}{state}"
    for where in (_PLAYING_PAGE, _PLAYING_EDITOR)
    for state in (":not([data-click])", ".is-built")
)
_ANIMATE: Final[str] = "{{animation:el-{name} .62s cubic-bezier(.2,.7,.2,1) var(--ad,0ms) both}}"

ELEMENT_CSS: Final[str] = """
.sl{isolation:isolate}
.sl-bg{position:absolute;inset:0;z-index:-1;overflow:hidden;pointer-events:none}
.sl-bg img{display:block;width:100%;height:100%;object-fit:cover}
.sl-bg img.is-contain{object-fit:contain}
.sl-dim{position:absolute;inset:0;background:black}
.l-blank{padding:0}
.sl-els{position:absolute;inset:0;z-index:2;pointer-events:none}
.el{position:absolute;box-sizing:border-box;display:flex;flex-direction:column;
  justify-content:flex-start;pointer-events:auto;color:var(--ink);font-size:24px;line-height:1.25}
.el.v-m{justify-content:center}
.el.v-b{justify-content:flex-end}
.el.is-shadow{filter:drop-shadow(0 12px 22px color-mix(in srgb,black 28%,transparent))}
.el-a{display:contents;color:inherit;text-decoration:none}
.el-t{position:relative;min-width:0;overflow-wrap:break-word;white-space:normal;
  text-wrap:pretty}
.el-t ul,.el-t ol{margin:0;padding-left:1.15em}
.el-t ul{list-style:disc}
.el-t ol{list-style:decimal}
.el-t li+li{margin-top:.32em}
.el-t ul li::marker{color:var(--da)}
.el-t ol li::marker{color:var(--da);font-weight:600}
.el-t a{color:var(--da)}
.el-t.is-b{font-weight:650}
.el-t.is-i{font-style:italic}
.el-t.is-u{text-decoration:underline;text-underline-offset:.12em}
.el-t.is-s{text-decoration:line-through}
.el-t.is-u.is-s{text-decoration:underline line-through}
.el-t.is-c{text-transform:uppercase;letter-spacing:.06em}
.el-shape{color:white}
:root[data-theme="dark"] .el-shape{color:black}
.sl[data-tone="dark"] .el-shape{color:black}
.sl[data-tone="light"] .el-shape{color:white}
.el-shape .el-t{z-index:1}
.el-shape.is-callout .el-t{top:-12%}
.el-svg{position:absolute;inset:0;width:100%;height:100%;overflow:visible}
.el-line{pointer-events:none}
.el-line .el-svg line,.el-line .el-svg polygon,.el-line .el-svg circle{pointer-events:stroke}
.el-image{overflow:hidden}
.el-image img{display:block;width:100%;height:100%;object-fit:cover}
.el-image img.is-contain{object-fit:contain}
.el-image img.is-fill{object-fit:fill}
.el-table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums;
  --tf:color-mix(in srgb,var(--da) 14%,var(--bg));--tl:var(--line-2)}
.el-table td,.el-table th{padding:.45em .7em;border-bottom:1px solid var(--tl);
  vertical-align:top;line-height:1.3;text-align:inherit}
.el-table.has-head tr:first-child>*{background:var(--tf);font-weight:600;
  border-bottom-color:var(--ink)}
.el-chart{font-size:18px}
.el-chart .card.chart{flex:1;display:flex;flex-direction:column;min-width:0;min-height:0;
  margin:0;padding:0;border:0;border-radius:0;background:transparent}
.el-chart .chart svg{flex:1 1 0;height:0;min-height:0}
.el-chart .cols{flex:1 1 0;height:auto;min-height:120px}
.el-chart .bars{flex:1 1 0;align-content:center}
.el-chart .pie{flex:1 1 0;min-height:0;flex-wrap:nowrap}
.el-chart .pie svg{flex:0 1 auto;width:auto;height:100%;max-width:50%}
@keyframes el-fade{from{opacity:0}}
@keyframes el-rise{from{opacity:0;translate:0 32px}}
@keyframes el-slide{from{opacity:0;translate:-64px 0}}
@keyframes el-zoom{from{opacity:0;scale:.82}}
@keyframes el-pop{0%{opacity:0;scale:.5}70%{opacity:1;scale:1.05}100%{scale:1}}
@keyframes el-wipe{from{clip-path:inset(0 100% 0 0)}to{clip-path:inset(0 0 0 0)}}
.dk:not(.is-overview):not(.is-still) .el[data-click]:not(.is-built),
.ed-stage.is-presenting .el[data-click]:not(.is-built){visibility:hidden}
:root[data-node-mode] .dk .el[data-click]{visibility:visible}
.dk.is-ready .dk-cell[data-tr="none"]{transition:none!important;transform:none!important}
.dk.is-ready .dk-cell[data-tr="fade"].is-current{transition:opacity .5s ease,visibility 0s}
.dk.is-ready .dk-cell[data-tr="fade"]{transform:none}
.dk.is-ready .dk-cell[data-tr="slide"]{transform:translateX(100%)}
.dk.is-ready[data-dir="back"] .dk-cell[data-tr="slide"]{transform:translateX(-100%)}
.dk.is-ready .dk-cell[data-tr="slide"].is-current{transform:none;
  transition:opacity .2s ease,transform .55s cubic-bezier(.3,.7,.2,1),visibility 0s}
.dk.is-ready .dk-cell[data-tr="rise"]{transform:translateY(48px)}
.dk.is-ready .dk-cell[data-tr="rise"].is-current{transform:none;
  transition:opacity .45s ease,transform .5s cubic-bezier(.2,.7,.2,1),visibility 0s}
.dk.is-ready .dk-cell[data-tr="zoom"]{transform:scale(.9)}
.dk.is-ready .dk-cell[data-tr="zoom"].is-current{transform:none;
  transition:opacity .45s ease,transform .5s cubic-bezier(.2,.7,.2,1),visibility 0s}
.dk.is-ready .dk-cell[data-tr].was-current:not(.is-current){transform:none}
.dk.is-overview .dk-cell.is-hidden .dk-frame{opacity:.45}
.dk.is-overview .dk-cell.is-hidden .dk-no::after{content:" · hidden"}
@media print{.el{animation:none!important;visibility:visible!important}
.dk-cell.is-hidden{display:none!important}}
@media (prefers-reduced-motion:reduce){.el{animation:none!important}}
""" + "".join(_PLAYING.format(name=name) + _ANIMATE.format(name=name) for name in ANIMATIONS)


#: The tokens a slide of a fixed tone carries on itself.
def tone_css(light_tokens: str, dark_tokens: str) -> str:
    return (
        f'.sl[data-tone="light"]{{{light_tokens}}}'
        f'@media screen{{.sl[data-tone="dark"]{{{dark_tokens}}}}}'
    )


__all__ = [
    "ANIMATIONS",
    "BOX_SHAPES",
    "DECK_FONTS",
    "ELEMENT_CSS",
    "ELEMENT_TYPES",
    "FONTS",
    "FONT_CSS",
    "MAX_ELEMENTS",
    "PATH_SHAPES",
    "SHAPES",
    "TRANSITIONS",
    "auto_tone",
    "background_html",
    "chart_spec",
    "css_color",
    "element_html",
    "elements_html",
    "read_background",
    "read_chart",
    "read_deck_extras",
    "read_element",
    "read_slide_extras",
    "spec_color",
    "text_content",
    "tone_css",
]
