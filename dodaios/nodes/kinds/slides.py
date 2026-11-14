"""The node type ``slides``: a deck, played in the window like a keynote.

The person asks for "a deck about the third quarter"; the model writes a list
of slides in a small grammar (a layout name and that layout's fields) and this
module turns it into ONE self-contained page: a 16:9 stage that scales to the
window, keyboard and touch navigation, an overview of all slides and a panel
for the speaker notes.

Why the model writes a grammar and not the slides' HTML: a deck is judged by
its typography, and typography is exactly what a model gets wrong when it
writes markup by hand (a title that runs off the frame, five sizes on one
slide, a different margin on every page). Here the model only decides what a
slide SAYS and which of eleven compositions carries it; the sizes, the grid
and the fitting are fixed in this file, so every deck reads as one family
with the rest of the node pages and a later look change reaches every deck
without rebuilding one.

How a slide keeps its shape at every window size: it is laid out once at a
logical 1280 x 720 px and scaled as a whole with a CSS transform the page
script computes (rounded to whole pixels, no compositing layer, so text stays
sharp). The layout is therefore the same in a 360 px pane, in the overview's
miniatures (the very same elements, scaled further down) and on the printed
page. Texts are bounded in :func:`normalize`; a slide's body starts at a size
picked from its amount of text, and the page script shrinks a body that still
overflows, because the fonts of the machine that shows the deck are not known
here.

Pure functions, no I/O; every piece of text from a spec is escaped by the
helpers of :mod:`dodaios.nodes.shell` on its way into the page.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable
from typing import Any, Final

from dodaios.artifacts.design_guide import THEME_CSS
from dodaios.artifacts.report_blocks import parse_chart, render_chart
from dodaios.nodes.bridge import TITLE_PATH
from dodaios.nodes.shell import (
    MAX_IMAGE_CHARS,
    as_list,
    attr,
    clean,
    clean_block,
    color,
    document,
    esc,
    inline,
    lines,
    pick,
    safe_image,
)
from dodaios.nodes.types import NodeError

# --- the grammar ---------------------------------------------------------------

THEMES: Final[tuple[str, ...]] = ("auto", "light", "dark")
LAYOUTS: Final[tuple[str, ...]] = (
    "title",
    "section",
    "bullets",
    "columns",
    "quote",
    "stats",
    "chart",
    "table",
    "image",
    "steps",
    "closing",
)

MAX_SLIDES: Final[int] = 60
MAX_BULLETS: Final[int] = 6
BULLET_CHARS: Final[int] = 160
MAX_COLUMNS: Final[int] = 3
MAX_COLUMN_BULLETS: Final[int] = 4
COLUMN_BULLET_CHARS: Final[int] = 80
#: A closing slide's points stand in one row under its name.
MAX_CLOSING_BULLETS: Final[int] = 4
CLOSING_BULLET_CHARS: Final[int] = 100
MAX_STATS: Final[int] = 4
STAT_VALUE_CHARS: Final[int] = 12
MAX_STEPS: Final[int] = 6
MAX_TABLE_COLUMNS: Final[int] = 8
MAX_TABLE_ROWS: Final[int] = 10
CELL_CHARS: Final[int] = 60
#: Horizontal bars are one row each; more than this does not fit a slide.
MAX_BAR_ROWS: Final[int] = 10
NOTE_CHARS: Final[int] = 1_200

#: The one-line texts of a slide and how long each may be.
_LINES: Final[dict[str, int]] = {
    "kicker": 60,
    "title": 110,
    "subtitle": 180,
    "text": 280,
    "quote": 320,
    "by": 80,
    "caption": 140,
}

#: What each layout shows. Every other field of a slide is dropped.
_FIELDS: Final[dict[str, tuple[str, ...]]] = {
    "title": ("kicker", "title", "subtitle"),
    "section": ("kicker", "title", "subtitle"),
    "bullets": ("kicker", "title", "text", "bullets"),
    "columns": ("kicker", "title", "columns"),
    "quote": ("quote", "by"),
    "stats": ("kicker", "title", "stats"),
    "chart": ("kicker", "title", "text", "chart"),
    "table": ("kicker", "title", "table", "caption"),
    "image": ("kicker", "title", "image", "caption"),
    "steps": ("kicker", "title", "steps"),
    "closing": ("kicker", "title", "subtitle", "bullets"),
}

#: The field a layout cannot do without. A slide that asks for a layout but
#: lacks it gets the layout its fields do fit.
_CORE: Final[dict[str, tuple[str, ...]]] = {
    "title": ("title",),
    "section": ("title",),
    "bullets": ("title", "text", "bullets"),
    "columns": ("columns",),
    "quote": ("quote",),
    "stats": ("stats",),
    "chart": ("chart",),
    "table": ("table",),
    "image": ("image",),
    "steps": ("steps",),
    "closing": ("title",),
}

#: Layouts named after their one structured field, most specific first: this
#: is the order a slide without a ``layout`` is matched in.
_BY_FIELD: Final[tuple[str, ...]] = (
    "stats",
    "chart",
    "table",
    "image",
    "steps",
    "columns",
    "quote",
)

#: What a model may call a layout.
#: How an image slide fills its picture's box: ``cover`` crops the picture to
#: the box (a photo), ``contain`` shows all of it (a screenshot, a diagram, a
#: logo), on the slide's quiet ground.
IMAGE_FITS: Final[tuple[str, ...]] = ("cover", "contain")

_LAYOUT_ALIASES: Final[dict[str, str]] = {
    "cover": "title",
    "opening": "title",
    "divider": "section",
    "chapter": "section",
    "list": "bullets",
    "text": "bullets",
    "content": "bullets",
    "comparison": "columns",
    "compare": "columns",
    "two-column": "columns",
    "numbers": "stats",
    "metrics": "stats",
    "kpis": "stats",
    "graph": "chart",
    "picture": "image",
    "photo": "image",
    "process": "steps",
    "timeline": "steps",
    "end": "closing",
    "thanks": "closing",
    "summary": "closing",
}

_CONTROL_RE: Final = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_NUMERIC_CELL_RE: Final = re.compile(
    r"^[+\-−–]?\s?[$€£¥]?\s?\d[\d.,\s]*\s?(?:[%‰]|[A-Za-z€$£¥°/²³µ]{1,5})?$"
)

_NO_SLIDES: Final[str] = (
    'A deck needs "slides": a list of 1 to 60 slides, each an object with a "layout" '
    f'({", ".join(LAYOUTS)}) and that layout\'s fields, at least a "title".'
)


def _text(value: Any, limit: int) -> str:
    """One line from a spec value, at most ``limit`` characters.

    A longer text ends in an ellipsis, and nothing is left dangling at the
    cut, so clipping a clipped text changes nothing.
    """
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return ""
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e15:
        value = int(value)
    text = clean(_CONTROL_RE.sub("", str(value)), limit + 1)
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def _block(value: Any, limit: int) -> str:
    """Several lines from a spec value (speaker notes), line breaks kept."""
    if isinstance(value, (list, tuple)):
        value = "\n".join(str(part) for part in value if isinstance(part, (str, int, float)))
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return ""
    text = re.sub(r"\n{3,}", "\n\n", _CONTROL_RE.sub("", clean_block(value, limit + 1)))
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text.strip()


def _texts(value: Any, count: int, limit: int) -> list[str]:
    """A list of one-line texts; an item may be a string or ``{"text": …}``."""
    found = []
    for item in as_list(value, 4 * count):
        if isinstance(item, dict):
            item = item.get("text") or item.get("title")
        text = _text(item, limit)
        if text:
            found.append(text)
    return found[:count]


def _bullets(value: Any, where: str) -> list[str]:
    del where
    return _texts(value, MAX_BULLETS, BULLET_CHARS)


def _columns(value: Any, where: str) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for raw in as_list(value, 12):
        if isinstance(raw, str):
            raw = {"text": raw}
        if not isinstance(raw, dict):
            continue
        column: dict[str, Any] = {}
        for key, limit in (("title", 60), ("text", 200)):
            text = _text(raw.get(key), limit)
            if text:
                column[key] = text
        bullets = _texts(raw.get("bullets"), MAX_COLUMN_BULLETS, COLUMN_BULLET_CHARS)
        if bullets:
            column["bullets"] = bullets
        if column:
            found.append(column)
    if len(found) == 1:
        raise NodeError(
            f'{where}: "columns" needs 2 or 3 columns, each {{"title", "text", "bullets"}}; '
            'for one column use the "bullets" layout.'
        )
    return found[:MAX_COLUMNS]


def _stats(value: Any, where: str) -> list[dict[str, str]]:
    del where
    found: list[dict[str, str]] = []
    for raw in as_list(value, 12):
        if not isinstance(raw, dict):
            raw = {"value": raw}
        number = _text(raw.get("value"), STAT_VALUE_CHARS)
        if not number:
            continue
        stat = {"value": number}
        for key, limit in (("label", 48), ("detail", 80)):
            text = _text(raw.get(key), limit)
            if text:
                stat[key] = text
        found.append(stat)
    return found[:MAX_STATS]


def _steps(value: Any, where: str) -> list[dict[str, str]]:
    del where
    found: list[dict[str, str]] = []
    for raw in as_list(value, 18):
        if not isinstance(raw, dict):
            raw = {"title": raw}
        step = {}
        for key, limit in (("title", 48), ("text", 140)):
            text = _text(raw.get(key), limit)
            if text:
                step[key] = text
        if step:
            found.append(step)
    return found[:MAX_STEPS]


def _table(value: Any, where: str) -> dict[str, Any]:
    if value in (None, "", [], {}):
        return {}
    hint = (
        f'{where}: "table" must be {{"columns": [up to {MAX_TABLE_COLUMNS} names], '
        f'"rows": [up to {MAX_TABLE_ROWS} lists of cells]}}.'
    )
    if not isinstance(value, dict):
        raise NodeError(hint)
    names = value.get("columns") or value.get("headers")
    columns = [_text(name, 32) for name in as_list(names, MAX_TABLE_COLUMNS)]
    if not any(columns):
        raise NodeError(hint)
    rows: list[list[str]] = []
    for raw in as_list(value.get("rows"), 4 * MAX_TABLE_ROWS):
        if isinstance(raw, dict):
            cells = [raw.get(name) for name in columns]
        elif isinstance(raw, (list, tuple)):
            cells = list(raw)[: len(columns)]
        else:
            continue
        row = [_text(cell, CELL_CHARS) for cell in cells]
        row += [""] * (len(columns) - len(row))
        if any(row):
            rows.append(row)
    if not rows:
        raise NodeError(hint)
    return {"columns": columns, "rows": rows[:MAX_TABLE_ROWS]}


def _image(value: Any, where: str) -> str:
    if value in (None, ""):
        return ""
    source = safe_image(value)
    if not source:
        raise NodeError(
            f'{where}: "image" must be a data:image/png, jpeg, gif or webp;base64 URI of at '
            f"most {MAX_IMAGE_CHARS} characters (the page has no network, so no web address); "
            "leave it out or pick another layout."
        )
    return source


def _plain_number(value: float | None) -> float | int | None:
    if value is None:
        return None
    return int(value) if value.is_integer() and abs(value) < 1e15 else value


def _chart_spec(parsed: dict[str, Any]) -> dict[str, Any]:
    """A parsed chart as the JSON the chart reader accepts again."""
    rows = MAX_BAR_ROWS if parsed["type"] == "bar" else len(parsed["x"])
    chart: dict[str, Any] = {"type": parsed["type"]}
    for key in ("title", "note", "unit", "value", "delta"):
        if parsed[key]:
            chart[key] = parsed[key]
    # What the shared grammar grew later (stacked bars, chosen colours) is kept
    # as the reader returned it, so a slide's chart loses nothing in a save.
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


def _chart(value: Any, where: str) -> dict[str, Any]:
    """The slide's chart in the report chart grammar, or ``NodeError``.

    Read by :func:`dodaios.artifacts.report_blocks.parse_chart`, the same
    reader the reports use, so a chart that is accepted here is drawn.
    """
    if value in (None, "", [], {}):
        return {}
    hint = (
        f'{where}: "chart" must be {{"type": "line" | "area" | "column" | "bar" | "pie" | '
        '"donut", "x": [2 or more labels], "series": [{"name": …, "data": [one number per '
        'label]}]}, with optional "unit", "title", "note", "stacked" and "colors".'
    )
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
        chart = _chart_spec(parsed)
        if any(all(point is None for point in entry["data"]) for entry in chart["series"]):
            raise NodeError(hint)
    return chart if isinstance(chart, dict) else {}


_PARSERS: Final[dict[str, Callable[[Any, str], Any]]] = {
    "bullets": _bullets,
    "columns": _columns,
    "stats": _stats,
    "chart": _chart,
    "table": _table,
    "image": _image,
    "steps": _steps,
}
_ALL_FIELDS: Final[tuple[str, ...]] = (*_LINES, *_PARSERS)


def _read(key: str, value: Any, where: str, strict: bool) -> Any:
    limit = _LINES.get(key)
    if limit:
        return _text(value, limit)
    try:
        return _PARSERS[key](value, where)
    except NodeError:  # a field the asked-for layout does not show is left out, not refused
        if strict:
            raise
        return None


def _infer(found: dict[str, Any], first: bool) -> str:
    """The layout that fits the fields a slide carries."""
    for name in _BY_FIELD:
        if found.get(name):
            return name
    if found.get("bullets") or found.get("text"):
        return "bullets"
    if found.get("title"):
        return "title" if first else "section"
    return ""


def _slide(raw: Any, position: int, first: bool) -> dict[str, Any] | None:
    """One clean slide, or ``None`` for an entry with nothing to show."""
    if isinstance(raw, str):
        raw = {"title": raw}
    if not isinstance(raw, dict):
        return None
    where = f"Slide {position + 1} (/slides/{position})"
    asked = _text(raw.get("layout"), 24).lower()
    asked = _LAYOUT_ALIASES.get(asked, asked)
    if asked not in LAYOUTS:
        asked = ""
    shown = _FIELDS[asked] if asked else _ALL_FIELDS
    found: dict[str, Any] = {}
    for key in _ALL_FIELDS:
        value = _read(key, raw.get(key), where, strict=key in shown)
        if value:
            found[key] = value
    layout = asked if asked and any(found.get(key) for key in _CORE[asked]) else ""
    layout = layout or _infer(found, first)
    # A slide that names its layout and holds some of that layout's texts, but
    # fits no layout (an opening whose title the person is writing anew, a
    # quote with only its author yet), keeps its layout: dropping it would
    # lose what it holds in the middle of an edit.
    if not layout and asked and any(found.get(key) for key in _FIELDS[asked]):
        layout = asked
    if not layout:
        return None
    slide: dict[str, Any] = {"layout": layout}
    for key in _FIELDS[layout]:
        if key in found:
            slide[key] = found[key]
    if layout == "closing" and "bullets" in slide:
        slide["bullets"] = _texts(slide["bullets"], MAX_CLOSING_BULLETS, CLOSING_BULLET_CHARS)
    if layout == "image" and pick(_text(raw.get("fit"), 12), IMAGE_FITS, "cover") == "contain":
        slide["fit"] = "contain"
    notes = _block(raw.get("notes"), NOTE_CHARS)
    if notes:
        slide["notes"] = notes
    return slide


def _accent(value: Any) -> str:
    """The deck's accent as the spec keeps it: a color name or a CSS color."""
    name = _text(value, 40).lower()
    if not name or name == "accent":
        return ""
    return name if color(name) else ""


def normalize(spec: Any) -> dict[str, Any]:
    """A clean deck: known fields only, texts clipped, lists capped.

    Raises:
        NodeError: with one sentence that says what to send, when there is no
            slide to show or a slide's chart, table, columns or image cannot
            be drawn.
    """
    if isinstance(spec, (list, tuple)):
        spec = {"slides": list(spec)}
    if not isinstance(spec, dict):
        raise NodeError(_NO_SLIDES)
    slides: list[dict[str, Any]] = []
    for position, raw in enumerate(as_list(spec.get("slides"), 10 * MAX_SLIDES)):
        if len(slides) == MAX_SLIDES:
            break
        slide = _slide(raw, position, first=not slides)
        if slide:
            slides.append(slide)
    if not slides:
        raise NodeError(_NO_SLIDES)
    deck: dict[str, Any] = {"theme": pick(spec.get("theme"), THEMES, "auto")}
    accent = _accent(spec.get("accent"))
    if accent:
        deck["accent"] = accent
    deck["slides"] = slides
    return deck


def preview(spec: dict[str, Any]) -> dict[str, Any]:
    """What the library draws on the deck's card."""
    deck = spec if isinstance(spec, dict) else {}
    slides = [slide for slide in as_list(deck.get("slides"), MAX_SLIDES) if isinstance(slide, dict)]
    first = slides[0] if slides else {}
    title = _text(first.get("title"), 60) or next(
        (_text(slide.get("title"), 60) for slide in slides if slide.get("title")), ""
    )
    subtitle = first.get("subtitle") or first.get("text") or first.get("quote") or ""
    return {
        "title": title,
        "subtitle": _text(subtitle, 80),
        "count": len(slides),
        "dark": deck.get("theme") == "dark",
        "accent": color(_accent(deck.get("accent"))),
    }


def starter(title: str, language: str) -> dict[str, Any]:
    """A fresh deck: an opening slide, one with points, a closing one.

    The placeholder words are English in every language; they are few and
    the first edit replaces them.
    """
    del language
    return normalize(
        {
            "slides": [
                {"layout": "title", "title": title or "Untitled deck", "subtitle": "Subtitle"},
                {
                    "layout": "bullets",
                    "title": "The point of this slide",
                    "bullets": ["First point", "Second point", "Third point"],
                },
                {"layout": "closing", "title": "Next steps", "subtitle": "What happens now"},
            ]
        }
    )


EXAMPLE: Final[dict[str, Any]] = {
    "accent": "green",
    "slides": [
        {
            "layout": "title",
            "kicker": "Board update",
            "title": "Q3 in review",
            "subtitle": "Revenue, retention, next steps",
        },
        {
            "layout": "stats",
            "title": "Two numbers carried the quarter",
            "stats": [
                {"value": "€4.2M", "label": "Revenue", "detail": "+18% on Q2"},
                {"value": "94%", "label": "Retention"},
            ],
        },
        {
            "layout": "chart",
            "title": "Revenue grew every month",
            "text": "September passed **1.5M**.",
            "chart": {
                "type": "column",
                "unit": "k€",
                "x": ["Jul", "Aug", "Sep"],
                "series": [{"name": "Revenue", "data": [1310, 1390, 1500]}],
            },
            "notes": "Pause on September.",
        },
        {"layout": "closing", "title": "Next: the mobile app", "bullets": ["Beta on 1 Dec"]},
    ],
}

GUIDE: Final[str] = (
    'Type "slides": a deck, played as a 16:9 presentation (keys, overview, notes).\n'
    'Spec: {"theme": "auto" | "light" | "dark" ("auto" follows the app), "accent": blue, '
    'orange, green, amber, violet, pink or a hex, "slides": [1-60 slides]}.\n'
    'A slide: {"layout": …, its fields, "notes": speaker notes}; other fields are dropped.\n'
    "- title: kicker, title, subtitle. Opens the deck.\n"
    "- section: kicker, title, subtitle. A chapter divider.\n"
    "- bullets: kicker, title, text, bullets (up to 6, 160 chars each).\n"
    "- columns: kicker, title, columns: 2-3 of {title, text, bullets (up to 4, short)}.\n"
    "- quote: quote (up to 320 chars), by.\n"
    '- stats: kicker, title, stats: 1-4 of {value (up to 12 chars, "94%"), label, detail}.\n'
    '- chart: kicker, title, text (short, beside it), chart: {"type": line|area|column|bar|'
    'pie|donut, "x": [labels], "series": [{"name", "data": [a number per label]}], "unit", '
    '"note", "stacked": true (column/bar), "colors": ["#hex" per series or slice]}; pie and '
    "donut: one series; bars: up to 10 rows.\n"
    '- table: kicker, title, caption, table: {"columns": [up to 8], "rows": [up to 10 lists '
    "of short cells]}.\n"
    "- image: kicker, title, caption, image (a data:image/…;base64 URI, never a web address), "
    'fit: "contain" shows all of it (screenshots), default crops; no title: full-bleed.\n'
    "- steps: kicker, title, steps: up to 6 of {title, text}, numbered.\n"
    "- closing: kicker, title, subtitle, bullets (up to 4, 100 chars). Ends the deck.\n"
    'Without "layout" it follows from the fields (stats, chart, table, image, steps, columns, '
    "quote, else bullets; only a title: opens or divides the deck). Undrawable content is "
    "refused with the reason.\n"
    "Limits: title 110 chars (best under 60), subtitle 180, text 280, kicker 60, caption 140, "
    "notes 1200; longer is clipped. Bullets, text, captions and notes take **bold**, "
    "*italic*, `code`, [links](https://…).\n"
    "Write a keynote: one idea per slide, a title that states the point, few words, real "
    "numbers with units, the detail in the notes.\n"
    "Example:\n" + json.dumps(EXAMPLE, ensure_ascii=False, separators=(",", ":"))
)


# --- the page ------------------------------------------------------------------


def _tokens(opening: str) -> str:
    """The declarations of one token block of the kit's stylesheet."""
    start = THEME_CSS.index(opening) + len(opening)
    return THEME_CSS[start : THEME_CSS.index("}", start)]


#: A deck with a fixed theme carries that theme's tokens on its own root, so
#: it stays dark (or light) whatever the app around it shows. Read from the
#: kit, not copied, so the two can never drift apart. Dark is ``screen`` only,
#: like the kit's: a printed deck is always on white.
_FORCED_THEME_CSS: Final[dict[str, str]] = {
    "light": f'.dk[data-theme="light"]{{{_tokens(":root{")}}}',
    "dark": ('@media screen{.dk[data-theme="dark"]{' + _tokens(':root[data-theme="dark"]{') + "}}"),
}

_CSS: Final[str] = """
.dk{position:fixed;inset:0;display:flex;flex-direction:column;background:var(--bg-2);
  color:var(--ink);--da:var(--accent);--k:.5;--m:.18;--fx:0px;--fy:0px}
.dk:focus{outline:0}
.dk-view{position:relative;flex:1 1 0;min-height:0;overflow:hidden}
.dk-cells{margin:0;padding:0;list-style:none}
.dk-cell{position:absolute;inset:0;opacity:0;visibility:hidden}
.dk-cell.is-current{opacity:1;visibility:visible}
.dk.is-ready .dk-cell{transform:translateX(18px);
  transition:opacity .16s ease,visibility 0s linear .16s}
.dk.is-ready[data-dir="back"] .dk-cell{transform:translateX(-18px)}
.dk.is-ready .dk-cell.was-current,.dk.is-ready .dk-cell.is-current{transform:none}
.dk.is-ready .dk-cell.is-current{
  transition:opacity .32s ease,transform .32s cubic-bezier(.2,.7,.2,1),visibility 0s}
.dk.is-switching .dk-cell{transition:none!important}
.dk-frame{position:absolute;left:var(--fx);top:var(--fy);width:calc(1280px*var(--k));
  height:calc(720px*var(--k));overflow:hidden;border-radius:calc(12px*var(--k));
  background:var(--bg);box-shadow:0 0 0 1px var(--line)}
.dk-pick,.dk-no{display:none}
/* The overview: the same cells, in a grid, each slide scaled further down. */
.dk.is-overview .dk-view{overflow:auto}
.dk.is-overview .dk-cells{display:grid;grid-template-columns:repeat(auto-fill,minmax(236px,1fr));
  gap:28px 24px;max-width:1480px;margin:0 auto;padding:32px 28px 40px}
.dk.is-overview .dk-cell{position:relative;inset:auto;opacity:1!important;
  visibility:visible!important;transform:none!important;transition:none!important}
.dk.is-overview .dk-frame{position:relative;left:auto;top:auto;width:100%;height:auto;
  aspect-ratio:16/9;border-radius:8px}
.dk.is-overview .sl{transform:scale(var(--m))}
.dk.is-overview .dk-pick{display:block;position:absolute;left:0;top:0;width:100%;
  aspect-ratio:16/9;padding:0;border:0;border-radius:8px;background:transparent;cursor:pointer}
.dk.is-overview .dk-pick:hover{box-shadow:0 0 0 2px var(--line-2)}
.dk.is-overview .is-current .dk-pick{box-shadow:0 0 0 2px var(--da)}
.dk.is-overview .dk-no{display:block;margin-top:10px;font-size:12px;line-height:16px;
  color:var(--ink-2);font-variant-numeric:tabular-nums}
.dk.is-overview .is-current .dk-no{color:var(--ink);font-weight:500}
/* Speaker notes and the control bar. */
.dk-notes{flex:none;max-height:34%;overflow:auto;padding:16px 24px 20px;background:var(--bg);
  border-top:1px solid var(--line);font-size:15px;line-height:24px}
.dk-notes-in{max-width:720px;margin:0 auto}
.dk-notes h2{margin-bottom:6px;font-size:12px;line-height:16px;font-weight:500;
  letter-spacing:0;color:var(--ink-2)}
.dk-note-none{color:var(--ink-2)}
.dk-bar{position:relative;flex:none;display:grid;grid-template-columns:1fr auto 1fr;
  align-items:center;gap:12px;height:48px;padding:0 12px 0 20px;background:var(--bg);
  border-top:1px solid var(--line)}
.dk-progress{position:absolute;left:0;right:0;top:-1px;height:2px}
.dk-progress i{display:block;width:0;height:100%;background:var(--da);transition:width .3s ease}
/* Every slide's footer names the deck; the bar does so where no slide is read. */
.dk-name{visibility:hidden;min-width:0;overflow:hidden;font-size:13px;line-height:20px;
  color:var(--ink-2);white-space:nowrap;text-overflow:ellipsis}
.dk.is-overview .dk-name{visibility:visible}
:root[data-node-mode="edit"] .dk-name{visibility:visible}
.dk-nav,.dk-tools{display:flex;align-items:center;gap:2px}
.dk-tools{justify-content:flex-end}
.dk-btn{appearance:none;display:grid;place-items:center;width:32px;height:32px;padding:0;border:0;
  border-radius:8px;background:transparent;color:var(--ink-2);cursor:pointer}
.dk-btn:hover{background:var(--bg-2);color:var(--ink)}
.dk-btn[aria-pressed="true"]{background:var(--bg-3);color:var(--ink)}
.dk-btn[aria-disabled="true"]{opacity:.35;cursor:default}
.dk-btn[aria-disabled="true"]:hover{background:transparent;color:var(--ink-2)}
.dk-btn svg{width:18px;height:18px;fill:none;stroke:currentColor;stroke-width:1.6;
  stroke-linecap:round;stroke-linejoin:round}
.dk-count{min-width:60px;font-size:13px;line-height:20px;color:var(--ink-2);text-align:center;
  font-variant-numeric:tabular-nums}
.dk-count b{color:var(--ink);font-weight:500}
/* A slide: 1280 x 720 logical pixels, scaled as a whole. */
.sl{position:absolute;left:0;top:0;width:1280px;height:720px;transform-origin:0 0;
  transform:scale(var(--k));display:flex;flex-direction:column;padding:72px 96px 100px;
  overflow:hidden;background:var(--bg);color:var(--ink);font-size:24px;line-height:1.4}
.sl h1,.sl h2,.sl h3{margin:0;text-wrap:balance}
.sl p,.sl li{text-wrap:pretty}
.sl-kicker{margin-bottom:16px;font-size:19px;line-height:24px;font-weight:500;color:var(--ink-2)}
.sl-head{flex:none;max-width:1000px}
.sl-h{font-size:46px;line-height:1.08;font-weight:600;letter-spacing:-.028em}
.sl-h[data-len="2"]{font-size:40px;line-height:1.1}
.sl-h[data-len="3"]{font-size:34px;line-height:1.14;letter-spacing:-.022em}
.sl-body{flex:1 1 0;min-height:0;margin-top:48px;overflow:hidden}
.sl-foot{position:absolute;left:96px;right:96px;bottom:36px;display:flex;
  justify-content:space-between;gap:32px;font-size:14px;line-height:20px;color:var(--ink-2);
  font-variant-numeric:tabular-nums}
.sl-foot span:first-child{min-width:0;overflow:hidden;white-space:nowrap;text-overflow:ellipsis}
.sl-rule{display:block;width:56px;height:5px;border-radius:3px;background:var(--da)}
.sl-big{max-width:1060px;font-size:92px;line-height:.98;font-weight:600;letter-spacing:-.042em}
.sl-big[data-len="2"]{font-size:74px;line-height:1.02;letter-spacing:-.038em}
.sl-big[data-len="3"]{font-size:58px;line-height:1.06;letter-spacing:-.032em}
.sl-big[data-len="4"]{font-size:46px;line-height:1.1;letter-spacing:-.028em}
.sl-sub{max-width:840px;margin-top:28px;font-size:28px;line-height:1.32;letter-spacing:-.01em;
  color:var(--ink-2)}
/* title: the kicker on top, the name of the deck anchored low. */
.l-title .sl-kicker{margin:0}
.l-title .sl-hero{margin-top:auto}
.l-title .sl-rule{margin-bottom:44px}
/* section: a tinted ground, the chapter's number on a rule, the name in the middle. */
.l-section{background:color-mix(in srgb,var(--da) 9%,var(--bg))}
.sl-mark{display:flex;align-items:center;gap:20px;font-size:20px;line-height:24px;
  font-weight:500;font-variant-numeric:tabular-nums}
.sl-mark i{flex:1;height:1px;background:color-mix(in srgb,var(--ink) 24%,transparent)}
.l-section .sl-hero{margin:auto 0}
/* bullets: the claim on the left, the points as ruled lines on the right. */
.sl-split{flex:1 1 0;min-height:0;display:grid;grid-template-columns:5fr 7fr;
  grid-template-rows:minmax(0,1fr);column-gap:72px}
.sl-split.is-solo{grid-template-columns:minmax(0,1fr)}
.sl-side{min-width:0}
.sl-lede{margin-top:24px;font-size:22px;line-height:1.42;color:var(--ink-2)}
.sl-list{margin:8px 0 0;padding:0;list-style:none;font-size:34px;line-height:1.3;
  letter-spacing:-.018em}
.sl-list[data-fit="2"]{font-size:28px;letter-spacing:-.012em}
.sl-list[data-fit="3"]{font-size:24px;letter-spacing:-.01em}
.sl-list[data-fit="4"]{font-size:21px;letter-spacing:-.006em}
.sl-list[data-fit="5"]{font-size:18px;letter-spacing:0}
.sl-list li{padding:.6em 0 .66em;border-top:1px solid var(--line-2)}
.sl-list li:first-child{border-top-color:var(--ink)}
.sl-prose{margin-top:8px;font-size:30px;line-height:1.36;letter-spacing:-.014em}
/* columns: equal columns under one rule each. */
.sl-cols{display:grid;grid-template-columns:repeat(var(--n),minmax(0,1fr));column-gap:48px;
  align-content:start;font-size:24px}
.sl-cols[data-fit="2"]{font-size:21px}
.sl-cols[data-fit="3"]{font-size:18px}
.sl-col{padding-top:22px;border-top:1px solid var(--ink)}
.sl-col h3{font-size:1.26em;line-height:1.2;font-weight:600;letter-spacing:-.016em}
.sl-col p{margin-top:.62em;line-height:1.45;color:var(--ink-2)}
.sl-col ul{display:grid;gap:.5em;margin:.9em 0 0;padding:0;list-style:none}
.sl-col li{position:relative;padding-left:1.05em;line-height:1.38}
.sl-col li::before{content:"";position:absolute;left:0;top:.56em;width:.32em;height:.32em;
  border-radius:50%;background:var(--da)}
/* quote: the mark in the margin, the words large. */
.l-quote{justify-content:center}
.sl-q{display:grid;grid-template-columns:104px minmax(0,1fr);margin:0 0 24px}
.sl-qmark{height:96px;font:600 184px/1 Georgia,"Times New Roman",serif;color:var(--da)}
.sl-q blockquote{font-size:50px;line-height:1.16;font-weight:500;letter-spacing:-.028em;
  text-wrap:balance}
.sl-q blockquote[data-len="2"]{font-size:40px;line-height:1.2;letter-spacing:-.024em}
.sl-q blockquote[data-len="3"]{font-size:31px;line-height:1.28;letter-spacing:-.018em}
.sl-q figcaption{grid-column:2;display:flex;align-items:center;gap:16px;margin-top:40px;
  font-size:21px;line-height:28px;color:var(--ink-2)}
.sl-q figcaption::before{content:"";flex:none;width:36px;height:1px;background:var(--ink-3)}
/* stats: the numbers low on the slide, a hairline between them. */
.sl-stats{display:grid;grid-template-columns:repeat(var(--n),minmax(0,1fr));align-content:end;
  padding-bottom:20px;font-size:22px}
.sl-stat{min-width:0;padding:6px 36px 2px;border-left:1px solid var(--line-2)}
.sl-stat:first-child{padding-left:0;border-left:0}
.sl-v{font-size:calc(var(--vs)*1em);line-height:1;font-weight:600;letter-spacing:-.045em;
  font-variant-numeric:tabular-nums;white-space:nowrap}
.sl-l{margin-top:.95em;line-height:1.3;font-weight:500}
.sl-d{margin-top:.2em;font-size:.86em;line-height:1.4;color:var(--ink-2)}
/* chart: the chart takes the room, a short reading beside it. */
.sl-chart{display:grid;grid-template-columns:minmax(0,1fr);grid-template-rows:minmax(0,1fr);
  column-gap:64px;font-size:20px}
.sl-chart.has-aside{grid-template-columns:minmax(0,1fr) 292px}
.sl-plot{display:flex;min-width:0;min-height:0}
.sl .card.chart{flex:1;display:flex;flex-direction:column;min-width:0;min-height:0;padding:0;
  border:0;border-radius:0}
.sl .chart h3{font-size:.9em;line-height:1.3;font-weight:500;color:var(--ink-2)}
.sl .chart svg{flex:1 1 0;height:0;min-height:0}
.sl .chart .legend,.sl .chart .note{font-size:.8em;line-height:1.4}
.sl .chart .metric .value{font-size:1.7em}
.sl .chart .metric .detail{font-size:.8em;line-height:1.4}
.sl .cols{flex:1 1 0;height:auto;min-height:180px;gap:14px}
.sl .col{font-size:18px;line-height:26px}
.sl .col i{bottom:38px;width:min(100%,60px);height:calc((100% - 76px)*var(--v)/100);
  border-radius:5px 5px 0 0}
.sl .col b{bottom:calc(44px + (100% - 76px)*var(--v)/100)}
.sl .bars{flex:1 1 0;align-content:center;gap:1.05em;font-size:1.1em;line-height:1.34}
.sl .bar i{height:.9em;border-radius:0 5px 5px 0}
.sl .bars:not(:has(.bar:nth-child(7))){gap:1.2em;font-size:1.3em}
.sl-aside{align-self:end;padding-top:20px;border-top:1px solid var(--ink);font-size:1.05em;
  line-height:1.42;color:var(--ink-2)}
/* table: ruled rows, no box. */
.sl-tab{font-size:26px}
.sl-tab[data-fit="2"]{font-size:22px}
.sl-tab[data-fit="3"]{font-size:19px}
.sl-tab[data-fit="4"]{font-size:16px}
.sl-table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
.sl-table th{padding:0 1.2em .7em 0;border-bottom:1px solid var(--ink);font-size:.8em;
  line-height:1.3;font-weight:500;color:var(--ink-2);text-align:left;vertical-align:bottom}
.sl-table td{padding:.6em 1.2em .62em 0;border-bottom:1px solid var(--line);line-height:1.3;
  vertical-align:top}
.sl-table tr>:last-child{padding-right:0}
.sl-table td:first-child{font-weight:500}
.sl-table .n{text-align:right}
.sl-cap{margin-top:1.1em;font-size:.74em;line-height:1.4;color:var(--ink-2)}
/* image: the picture bleeds off three edges; alone, it is the slide. */
.l-image .sl-head{max-width:440px}
.sl-pic{position:absolute;top:0;right:0;bottom:0;width:52%;margin:0;background:var(--bg-2)}
.sl-pic img,.l-bleed img{display:block;width:100%;height:100%;object-fit:cover}
.sl-note{max-width:440px;margin-top:auto;padding-top:18px;border-top:1px solid var(--line-2);
  font-size:20px;line-height:1.42;color:var(--ink-2)}
.l-image .sl-foot{right:calc(52% + 56px)}
.l-bleed{padding:0}
.l-bleed figure{position:absolute;inset:0;margin:0}
.sl-pic.is-contain img,.l-bleed .is-contain img{object-fit:contain}
.l-bleed .is-contain{background:var(--bg-2)}
.l-bleed figcaption{position:absolute;left:40px;bottom:36px;max-width:780px;padding:10px 16px;
  border-radius:10px;background:var(--bg);font-size:18px;line-height:1.36}
/* steps: numbers on a line that runs to the next one. */
.sl-steps{display:grid;grid-template-columns:repeat(var(--n),minmax(0,1fr));row-gap:44px;
  align-content:center;padding:0 0 24px;list-style:none;font-size:26px}
.sl-steps[data-fit="2"]{font-size:22px}
.sl-steps[data-fit="3"]{font-size:20px}
.sl-step-n{display:flex;align-items:center}
.sl-step-n b{flex:none;display:grid;place-items:center;width:44px;height:44px;
  border:1.5px solid var(--da);border-radius:50%;font-size:18px;line-height:1;font-weight:600;
  font-variant-numeric:tabular-nums}
.sl-step-n i{flex:1;height:1px;margin:0 14px;background:var(--line-2)}
.sl-steps .is-end .sl-step-n i{visibility:hidden}
.sl-steps h3{margin-top:1.05em;padding-right:28px;font-size:1.08em;line-height:1.24;
  font-weight:600;letter-spacing:-.012em}
.sl-steps p{margin-top:.5em;padding-right:28px;font-size:.84em;line-height:1.42;
  color:var(--ink-2)}
/* closing: the mirror of the opening, the name on top, what follows low. */
.l-closing .sl-rule{margin-bottom:40px}
.l-closing.is-bare .sl-hero{margin:auto 0}
.sl-next{flex:0 1 auto;display:grid;grid-template-columns:repeat(var(--n),minmax(0,1fr));
  gap:28px 44px;margin:auto 0 0;padding:32px 0 20px;list-style:none;font-size:21px;
  line-height:1.38}
.sl-next[data-fit="2"]{font-size:18px}
.sl-next li{padding-top:16px;border-top:1px solid var(--ink)}
@media (max-width:560px){
.dk-bar{grid-template-columns:auto 1fr;padding:0 8px}.dk-name{display:none}
.dk-notes{padding:12px 16px 16px}
.dk.is-overview .dk-cells{grid-template-columns:repeat(2,minmax(0,1fr));gap:18px 12px;
  padding:16px 12px 28px}}
@media print{
@page{size:1280px 720px;margin:0}
html,body{height:auto}body.fill{overflow:visible}
.dk{position:static;display:block;background:none}
.dk-bar,.dk-notes,.dk-pick,.dk-no{display:none!important}
.dk-view{overflow:visible!important}
.dk-cells{display:block!important;max-width:none!important;padding:0!important}
.dk-cell{position:relative!important;width:1280px;height:720px;opacity:1!important;
  visibility:visible!important;transform:none!important;break-after:page;break-inside:avoid}
.dk-cell:last-child{break-after:auto}
.dk-frame{position:static!important;width:1280px!important;height:720px!important;
  border-radius:0!important;box-shadow:none}
.sl{transform:none!important}}
"""

# The player. It needs nothing from the spec: the slides are in the markup,
# and everything it changes is a class, an attribute or a custom property.
_JS: Final[str] = """
(function(){
var d=document,root=d.querySelector(".dk");if(!root)return;
var view=root.querySelector(".dk-view"),list=function(s){
  return Array.prototype.slice.call(root.querySelectorAll(s));};
var cells=list(".dk-cell"),n=cells.length,cur=0,over=false;if(!n)return;
var curEl=root.querySelector("[data-cur]"),fill=root.querySelector(".dk-progress i");
var notes=root.querySelector(".dk-notes"),none=root.querySelector(".dk-note-none");
var noteEls=list(".dk-note"),btn={};
list("[data-act]").forEach(function(b){btn[b.getAttribute("data-act")]=b;});
function frame(c){return c.querySelector(".dk-frame");}
/* A body that overflows its slide is set smaller, step by step. */
function fitOne(b){
  var f=parseFloat(getComputedStyle(b).fontSize),i=0;
  while(i<14&&(b.scrollHeight>b.clientHeight+1||b.scrollWidth>b.clientWidth+1)){
    f*=.94;b.style.fontSize=f.toFixed(2)+"px";i++;}}
function fit(){list(".sl-body").forEach(fitOne);}
/* The stage: the largest 16:9 box that fits, on whole pixels so text stays sharp. */
function layout(){
  var w=view.clientWidth,h=view.clientHeight;
  if(over){root.style.setProperty("--m",(frame(cells[0]).clientWidth/1280).toFixed(5));return;}
  var pad=w<640?8:20,k=Math.min((w-2*pad)/1280,(h-2*pad)/720);if(!(k>.02))k=.02;
  var sw=Math.max(1,Math.round(1280*k));k=sw/1280;
  root.style.setProperty("--k",k.toFixed(5));
  root.style.setProperty("--fx",Math.round((w-sw)/2)+"px");
  root.style.setProperty("--fy",Math.round((h-720*k)/2)+"px");}
function show(i,keep){
  i=Math.max(0,Math.min(n-1,i));
  if(i!==cur){
    root.setAttribute("data-dir",i<cur?"back":"fwd");void root.offsetWidth;
    cells.forEach(function(c,j){c.classList.toggle("was-current",j===cur);
      c.classList.toggle("is-current",j===i);});
    cur=i;}
  curEl.textContent=String(i+1);
  fill.style.width=((i+1)/n*100).toFixed(3)+"%";
  btn.prev.setAttribute("aria-disabled",i===0?"true":"false");
  btn.next.setAttribute("aria-disabled",i===n-1?"true":"false");
  var has=false;
  noteEls.forEach(function(e){var on=Number(e.getAttribute("data-i"))===i;
    e.hidden=!on;if(on)has=true;});
  none.hidden=has;
  if(!keep){try{history.replaceState(null,"","#"+(i+1));}catch(e){}}}
function pickOf(i){return cells[i].querySelector(".dk-pick");}
function overview(on){
  if(on===over)return;over=on;
  root.classList.add("is-switching");root.classList.toggle("is-overview",on);
  btn.overview.setAttribute("aria-pressed",on?"true":"false");
  cells.forEach(function(c){
    if(on){frame(c).setAttribute("inert","");}else{frame(c).removeAttribute("inert");}});
  layout();
  try{
    if(on){var c=cells[cur];view.scrollTop=c.offsetTop-(view.clientHeight-c.offsetHeight)/2;
      pickOf(cur).focus({preventScroll:true});}
    else{view.scrollTop=0;root.focus({preventScroll:true});}
  }catch(e){}
  setTimeout(function(){root.classList.remove("is-switching");},80);}
function showNotes(on){notes.hidden=!on;
  btn.notes.setAttribute("aria-pressed",on?"true":"false");layout();}
function perRow(){var top=cells[0].offsetTop,c=0;
  while(c<n&&cells[c].offsetTop===top)c++;return c||1;}
root.addEventListener("click",function(e){
  var t=e.target;if(!t||!t.closest)return;
  var b=t.closest("[data-act]");
  if(b){var a=b.getAttribute("data-act");
    if(a==="prev")show(cur-1);else if(a==="next")show(cur+1);
    else if(a==="overview")overview(!over);else if(a==="notes")showNotes(notes.hidden);
    return;}
  var p=t.closest(".dk-pick");
  if(p){show(cells.indexOf(p.parentNode));overview(false);return;}
  if(over||!view.contains(t)||t.closest("a,button,input,select,textarea"))return;
  /* In edit mode, a click that only ends the writing in a field stays on the slide. */
  if(leaving){leaving=false;return;}
  if(window.getSelection&&String(window.getSelection()))return;
  var r=view.getBoundingClientRect(),x=(e.clientX-r.left)/r.width;
  if(x>2/3)show(cur+1);else if(x<1/3)show(cur-1);});
d.addEventListener("keydown",function(e){
  if(e.defaultPrevented||e.metaKey||e.ctrlKey||e.altKey)return;
  var k=e.key,tag=e.target&&e.target.tagName;
  var held=tag==="BUTTON"||tag==="A"||tag==="INPUT"||tag==="TEXTAREA"||tag==="SELECT";
  if(k==="g"||k==="G"||k==="Escape"){overview(!over);e.preventDefault();return;}
  if(k==="n"||k==="N"){showNotes(notes.hidden);e.preventDefault();return;}
  if(over){
    var a=d.activeElement&&d.activeElement.closest?d.activeElement.closest(".dk-cell"):null;
    var at=a?cells.indexOf(a):cur,to=at,row=perRow();
    if(k==="ArrowRight")to=at+1;else if(k==="ArrowLeft")to=at-1;
    else if(k==="ArrowDown")to=at+row;else if(k==="ArrowUp")to=at-row;
    else if(k==="Home")to=0;else if(k==="End")to=n-1;else return;
    to=Math.max(0,Math.min(n-1,to));pickOf(to).focus();e.preventDefault();return;}
  if(k===" "&&held)return;
  if(k==="ArrowRight"||k==="ArrowDown"||k==="PageDown"||(k===" "&&!e.shiftKey))show(cur+1);
  else if(k==="ArrowLeft"||k==="ArrowUp"||k==="PageUp"||(k===" "&&e.shiftKey))show(cur-1);
  else if(k==="Home")show(0);else if(k==="End")show(n-1);else return;
  e.preventDefault();});
var leaving=false;
d.addEventListener("pointerdown",function(){
  var a=d.activeElement;leaving=!!(a&&a.isContentEditable);},true);
/* Edit mode (nodes/bridge.py): what the layout derives from a text follows the
   text as it is typed, saved, cancelled or refused, so the page need not be
   drawn again (that would open slide 1). A field being written or saved holds
   its plain source; otherwise data-src has it, when the slide draws marks. */
function len(el){
  var s=el.getAttribute("data-src");
  if(s===null||el===d.activeElement||/(^| )is-saving( |$)/.test(el.className))s=el.textContent||"";
  return s.length;}
function step(n,bounds){var s=1;bounds.forEach(function(b){if(n>b)s++;});return s;}
function listFit(items,width){var sizes=[34,28,24,21,18];
  for(var s=0;s<sizes.length;s++){
    var size=sizes[s],per=width/(.5*size),rows=0;
    items.forEach(function(li){rows+=Math.max(1,Math.ceil(len(li)/per));});
    if(rows*1.3*size+items.length*1.28*size<=540)return s+1;}
  return sizes.length;}
/* The number cells of a column align right (_NUMERIC_CELL_RE). */
var NUMERIC=/^[+\\-−–]?\\s?[$€£¥]?\\s?\\d[\\d.,\\s]*\\s?(?:[%‰]|[A-Za-z€$£¥°\\/²³µ]{1,5})?$/;
function follow(sl){
  var all=function(s){return Array.prototype.slice.call(sl.querySelectorAll(s));};
  all(".sl-h").forEach(function(h){h.setAttribute("data-len",String(step(len(h),[44,78])));});
  var shift=sl.classList.contains("l-section")||
    (sl.classList.contains("l-closing")&&!sl.classList.contains("is-bare"))?1:0;
  all(".sl-big").forEach(function(h){
    h.setAttribute("data-len",String(Math.min(4,step(len(h),[22,44,76])+shift)));});
  all(".sl-q blockquote").forEach(function(q){
    q.setAttribute("data-len",String(step(len(q),[120,210])));});
  all(".sl-list").forEach(function(u){
    u.setAttribute("data-fit",String(listFit(all(".sl-list>li"),u.closest(".is-solo")?1088:593)));});
  all(".sl-cols").forEach(function(c){var cols=all(".sl-col"),most=0;
    cols.forEach(function(col){var n=0;
      Array.prototype.forEach.call(col.querySelectorAll("h3,p"),function(e){n+=len(e);});
      Array.prototype.forEach.call(col.querySelectorAll("li"),function(e){n+=len(e)+30;});
      most=Math.max(most,n);});
    c.setAttribute("data-fit",String(step(most,cols.length===2?[260,420]:[170,280])));});
  all(".sl-stats").forEach(function(st){var vs=all(".sl-v"),count=Math.max(1,vs.length),most=1;
    vs.forEach(function(v){most=Math.max(most,len(v));});
    var scale=Math.min([9.2,6.8,5.2,4.2][count-1],(1088/count-72)/(.56*most*22));
    st.style.setProperty("--vs",scale.toFixed(2));});
  all(".sl-next").forEach(function(u){var items=all(".sl-next>li"),most=0;
    items.forEach(function(li){most=Math.max(most,len(li));});
    u.setAttribute("data-fit",items.length>3||most>70?"2":"1");});
  all(".sl-table").forEach(function(t){
    var heads=t.tHead?t.tHead.rows[0].cells:[],rows=t.tBodies[0]?t.tBodies[0].rows:[];
    for(var c=0;c<heads.length;c++){var any=false,every=true,r,cell,v;
      for(r=0;r<rows.length;r++){cell=rows[r].cells[c];v=cell?cell.textContent||"":"";
        if(v){any=true;if(!NUMERIC.test(v))every=false;}}
      heads[c].classList.toggle("n",any&&every);
      for(r=0;r<rows.length;r++){if(rows[r].cells[c])rows[r].cells[c].classList.toggle("n",any&&every);}}});
  all(".sl-body").forEach(function(b){b.style.fontSize="";fitOne(b);});}
root.addEventListener("node-field-saved",function(e){
  var t=e.target,sl=t&&t.closest?t.closest(".sl"):null;
  if(sl){follow(sl);return;}
  if(t&&t.getAttribute&&t.getAttribute("data-at")==="@title"){
    var name=t.textContent||"";d.title=name;
    list(".sl-foot span:first-child").forEach(function(s){s.textContent=name;});}});
/* A text emptied may take its point, its row or its slide out of the deck, and
   with it the places the other fields name: then the page is drawn again. */
d.addEventListener("input",function(e){
  var el=e.target&&e.target.closest?e.target.closest("[data-at^='/slides/']"):null;
  if(!el)return;
  if(/\\S/.test(el.textContent||""))el.removeAttribute("data-refresh");
  else el.setAttribute("data-refresh","");
  var sl=el.closest(".sl");if(sl)follow(sl);},true);
/* The bridge has put the page's own text back by now (Escape, nothing changed). */
d.addEventListener("focusout",function(e){
  var sl=e.target&&e.target.closest&&e.target.hasAttribute("data-at")?e.target.closest(".sl"):null;
  if(sl)follow(sl);},true);
/* A refused save: the bridge put the old text back (its listener runs first). */
addEventListener("message",function(e){
  var m=e.data;if(e.source!==window.parent||!m||m.type!=="dodaios-node-edit-state")return;
  list(".sl .is-failed").forEach(function(f){follow(f.closest(".sl"));});});
/* Writing a deck includes its notes: edit mode opens them, and leaving it puts
   the panel back the way the reader had it. */
var notesBefore=null;
function modeChanged(){
  var edit=d.documentElement.getAttribute("data-node-mode")==="edit";
  if(edit&&notesBefore===null){notesBefore=!notes.hidden;showNotes(true);}
  else if(!edit&&notesBefore!==null){showNotes(notesBefore);notesBefore=null;}}
if(window.MutationObserver){new MutationObserver(modeChanged).observe(d.documentElement,
  {attributes:true,attributeFilter:["data-node-mode"]});}
var sx=null,sy=0;
view.addEventListener("touchstart",function(e){
  if(e.touches.length===1){sx=e.touches[0].clientX;sy=e.touches[0].clientY;}else{sx=null;}
},{passive:true});
view.addEventListener("touchend",function(e){
  if(sx===null||over)return;
  var t=e.changedTouches[0],dx=t.clientX-sx,dy=t.clientY-sy;sx=null;
  if(Math.abs(dx)>48&&Math.abs(dx)>Math.abs(dy)*1.5)show(cur+(dx<0?1:-1));
},{passive:true});
function fromHash(){var v=parseInt(String(location.hash).replace("#",""),10);
  return v>=1?Math.min(n,v)-1:-1;}
var q=null;try{q=new URLSearchParams(location.search);}catch(e){}
fit();layout();
var first=fromHash();show(first<0?0:first,true);
if(q&&q.get("notes")==="1")showNotes(true);
if(q&&q.get("overview")==="1")overview(true);
addEventListener("hashchange",function(){var v=fromHash();if(v>=0)show(v,true);});
if(window.ResizeObserver){new ResizeObserver(layout).observe(view);}
else{addEventListener("resize",layout);}
setTimeout(function(){root.classList.add("is-ready");},0);
try{root.focus({preventScroll:true});}catch(e){}
})();
"""

_ICONS: Final[dict[str, str]] = {
    "prev": '<path d="M12 4.5 6.5 10l5.5 5.5"/>',
    "next": '<path d="M8 4.5 13.5 10 8 15.5"/>',
    "overview": (
        '<rect x="3.5" y="3.5" width="5" height="5" rx="1.2"/>'
        '<rect x="11.5" y="3.5" width="5" height="5" rx="1.2"/>'
        '<rect x="3.5" y="11.5" width="5" height="5" rx="1.2"/>'
        '<rect x="11.5" y="11.5" width="5" height="5" rx="1.2"/>'
    ),
    "notes": '<rect x="3.5" y="3.5" width="13" height="8" rx="1.6"/><path d="M4 14.5h12M4 17h7"/>',
}


class _Deck:
    """What a slide needs to know about the deck around it.

    It also hands out the edit marks (``data-at`` and friends, see
    :mod:`dodaios.nodes.bridge`): a text is marked only when it is exactly the
    value the stored spec holds at that place, so a deck stored under older
    rules (which :func:`render` reads through :func:`normalize` again) never
    offers a field that would write somewhere else.
    """

    __slots__ = ("index", "language", "section", "stored")

    def __init__(self, language: str, stored: list[Any] | None = None) -> None:
        self.language = language
        self.section = 0
        self.index = 0
        #: The stored spec's slides, or ``None`` when the page draws no marks.
        self.stored = stored

    def _held(self, parts: tuple[str | int, ...]) -> Any:
        value: Any = self.stored[self.index] if self.stored is not None else None
        for part in parts:
            if isinstance(part, int) and isinstance(value, list) and part < len(value):
                value = value[part]
            elif isinstance(part, str) and isinstance(value, dict) and part in value:
                value = value[part]
            else:
                return None
        return value

    def mark(
        self, value: str, *parts: str | int, shown: str | None = None, multiline: bool = False
    ) -> str:
        """The edit marks of one text of the current slide; ``""`` when it is not one."""
        if self.stored is None or self._held(parts) != value:
            return ""
        pointer = "/".join(str(part) for part in ("", "slides", self.index, *parts))
        marks = f' data-at="{attr(pointer)}"'
        if shown is not None and shown != esc(value):
            marks += f' data-src="{attr(value)}"'
        return marks + (" data-multiline" if multiline else "")

    def text(
        self, tag: str, value: str, *parts: str | int, klass: str = "", rich: bool = False
    ) -> str:
        """One text of the current slide as its element, marked for editing.

        ``rich`` draws the inline marks (bold, links); the field then keeps
        the stored text in ``data-src``.
        """
        html = inline(value) if rich else esc(value)
        opening = f'<{tag} class="{klass}"' if klass else f"<{tag}"
        return f"{opening}{self.mark(value, *parts, shown=html)}>{html}</{tag}>"


def _step(length: int, bounds: tuple[int, ...]) -> int:
    """1 for a text up to ``bounds[0]`` characters, 2 up to the next, and so on."""
    return 1 + sum(length > bound for bound in bounds)


def _head(slide: dict[str, Any], deck: _Deck, lede: str = "") -> str:
    kicker, title = slide.get("kicker", ""), slide.get("title", "")
    if not kicker and not title and not lede:
        return ""
    parts = deck.text("p", kicker, "kicker", klass="sl-kicker") if kicker else ""
    if title:
        size = _step(len(title), (44, 78))
        parts += f'<h2 class="sl-h" data-len="{size}"{deck.mark(title, "title")}>{esc(title)}</h2>'
    if lede:
        parts += deck.text("p", lede, "text", klass="sl-lede", rich=True)
    return f'<header class="sl-head">{parts}</header>'


def _hero(slide: dict[str, Any], deck: _Deck, *, tag: str, shift: int, rule: bool) -> str:
    """The large name of a title, section or closing slide with its lines."""
    title = slide.get("title", "")
    size = min(4, _step(len(title), (22, 44, 76)) + shift)
    parts = '<i class="sl-rule"></i>' if rule else ""
    if tag != "h1" and slide.get("kicker"):
        parts += deck.text("p", slide["kicker"], "kicker", klass="sl-kicker")
    parts += (
        f'<{tag} class="sl-big" data-len="{size}"{deck.mark(title, "title")}>{esc(title)}</{tag}>'
    )
    if slide.get("subtitle"):
        parts += deck.text("p", slide["subtitle"], "subtitle", klass="sl-sub", rich=True)
    return f'<div class="sl-hero">{parts}</div>'


def _title_slide(slide: dict[str, Any], deck: _Deck) -> str:
    kicker = slide.get("kicker", "")
    top = deck.text("p", kicker, "kicker", klass="sl-kicker") if kicker else ""
    return top + _hero(slide, deck, tag="h1", shift=0, rule=True)


def _section_slide(slide: dict[str, Any], deck: _Deck) -> str:
    mark = f'<div class="sl-mark"><span>{deck.section:02d}</span><i></i></div>'
    return mark + _hero(slide, deck, tag="h2", shift=1, rule=False)


def _list_fit(bullets: list[str], width: float) -> int:
    """The size step (1 is the largest) at which the points fit their column."""
    sizes = (34, 28, 24, 21, 18)
    for step, size in enumerate(sizes, start=1):
        per_line = width / (0.5 * size)
        rows = sum(max(1, math.ceil(len(bullet) / per_line)) for bullet in bullets)
        if rows * 1.3 * size + len(bullets) * 1.28 * size <= 540:
            return step
    return len(sizes)


def _items(deck: _Deck, bullets: list[str], *parts: str | int) -> str:
    """Points as list items, each its own field."""
    return "".join(
        deck.text("li", bullet, *parts, index, rich=True) for index, bullet in enumerate(bullets)
    )


def _bullets_slide(slide: dict[str, Any], deck: _Deck) -> str:
    bullets, text = slide.get("bullets", []), slide.get("text", "")
    if bullets:
        side = _head(slide, deck, lede=text)
        solo = not side
        fit = _list_fit(bullets, 1088 if solo else 593)
        items = _items(deck, bullets, "bullets")
        main = f'<ul class="sl-body sl-list" data-fit="{fit}">{items}</ul>'
    else:
        side = _head(slide, deck)
        solo = not side
        main = deck.text("p", text, "text", klass="sl-body sl-prose", rich=True) if text else ""
        solo = solo or not text
    if side:
        side = f'<div class="sl-side">{side}</div>'
    return f'<div class="sl-split{" is-solo" if solo else ""}">{side}{main}</div>'


def _columns_slide(slide: dict[str, Any], deck: _Deck) -> str:
    columns = slide.get("columns", [])
    cells, longest = "", 0
    for index, column in enumerate(columns):
        bullets = column.get("bullets", [])
        longest = max(
            longest,
            len(column.get("title", ""))
            + len(column.get("text", ""))
            + sum(len(bullet) + 30 for bullet in bullets),
        )
        where = ("columns", index)
        part = deck.text("h3", column["title"], *where, "title") if column.get("title") else ""
        if column.get("text"):
            part += deck.text("p", column["text"], *where, "text", rich=True)
        if bullets:
            part += f"<ul>{_items(deck, bullets, *where, 'bullets')}</ul>"
        cells += f'<div class="sl-col">{part}</div>'
    roomy, tight = (260, 420) if len(columns) == 2 else (170, 280)
    fit = _step(longest, (roomy, tight))
    return (
        _head(slide, deck)
        + f'<div class="sl-body sl-cols" data-fit="{fit}" style="--n:{len(columns)}">{cells}</div>'
    )


def _quote_slide(slide: dict[str, Any], deck: _Deck) -> str:
    quote = slide.get("quote", "")
    by = deck.text("figcaption", slide["by"], "by") if slide.get("by") else ""
    size = _step(len(quote), (120, 210))
    return (
        '<figure class="sl-q"><span class="sl-qmark" aria-hidden="true">&ldquo;</span>'
        f'<blockquote data-len="{size}"{deck.mark(quote, "quote")}>{esc(quote)}</blockquote>'
        f"{by}</figure>"
    )


def _stats_slide(slide: dict[str, Any], deck: _Deck) -> str:
    stats = slide.get("stats", [])
    count = max(1, len(stats))
    # The value as large as its column allows: a little over half an em per character.
    longest = max((len(stat["value"]) for stat in stats), default=1)
    room = 1088 / count - 72
    scale = min((9.2, 6.8, 5.2, 4.2)[count - 1], room / (0.56 * longest * 22))
    cells = ""
    for index, stat in enumerate(stats):
        where = ("stats", index)
        value = deck.text("div", stat["value"], *where, "value", klass="sl-v")
        label = (
            deck.text("div", stat["label"], *where, "label", klass="sl-l")
            if stat.get("label")
            else ""
        )
        detail = (
            deck.text("div", stat["detail"], *where, "detail", klass="sl-d", rich=True)
            if stat.get("detail")
            else ""
        )
        cells += f'<div class="sl-stat">{value}{label}{detail}</div>'
    return (
        _head(slide, deck)
        + f'<div class="sl-body sl-stats" style="--n:{count};--vs:{scale:.2f}">{cells}</div>'
    )


def _chart_slide(slide: dict[str, Any], deck: _Deck) -> str:
    chart = slide.get("chart") or {}
    parsed = parse_chart(json.dumps(chart))
    figure = ""
    if parsed is not None:
        # The slide's title already says what the chart shows.
        if parsed["title"].casefold() == slide.get("title", "").casefold():
            parsed["title"] = ""
        figure = render_chart(parsed, deck.language)
    text = slide.get("text", "")
    aside = deck.text("p", text, "text", klass="sl-aside", rich=True) if text else ""
    return (
        _head(slide, deck)
        + f'<div class="sl-body sl-chart{" has-aside" if aside else ""}">'
        + f'<div class="sl-plot">{figure}</div>{aside}</div>'
    )


def _table_slide(slide: dict[str, Any], deck: _Deck) -> str:
    table = slide.get("table") or {}
    columns: list[str] = table.get("columns", [])
    rows: list[list[str]] = table.get("rows", [])
    numeric = [
        any(row[index] for row in rows)
        and all(_NUMERIC_CELL_RE.match(row[index]) for row in rows if row[index])
        for index in range(len(columns))
    ]

    def cell(tag: str, index: int, text: str, *parts: str | int) -> str:
        klass = ' class="n"' if numeric[index] else ""
        return f"<{tag}{klass}{deck.mark(text, 'table', *parts)}>{esc(text)}</{tag}>"

    head = "".join(cell("th", index, name, "columns", index) for index, name in enumerate(columns))
    body = "".join(
        "<tr>"
        + "".join(cell("td", index, text, "rows", number, index) for index, text in enumerate(row))
        + "</tr>"
        for number, row in enumerate(rows)
    )
    caption = slide.get("caption", "")
    note = deck.text("p", caption, "caption", klass="sl-cap", rich=True) if caption else ""
    fit = min(4, _step(len(rows), (4, 6, 8)) + (1 if len(columns) > 5 else 0))
    return (
        _head(slide, deck)
        + f'<div class="sl-body sl-tab" data-fit="{fit}"><table class="sl-table">'
        + f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>{note}</div>"
    )


def _image_slide(slide: dict[str, Any], deck: _Deck) -> str:
    source = safe_image(slide.get("image"))
    caption = slide.get("caption", "")
    alt = attr(clean(caption or slide.get("title", ""), 140))
    picture = f'<img src="{attr(source)}" alt="{alt}">' if source else ""
    contain = slide.get("fit") == "contain"
    if not slide.get("title"):
        note = deck.text("figcaption", caption, "caption", rich=True) if caption else ""
        opening = '<figure class="is-contain">' if contain else "<figure>"
        return f"{opening}{picture}{note}</figure>"
    note = deck.text("p", caption, "caption", klass="sl-note", rich=True) if caption else ""
    klass = "sl-pic is-contain" if contain else "sl-pic"
    return _head(slide, deck) + note + f'<figure class="{klass}">{picture}</figure>'


def _steps_slide(slide: dict[str, Any], deck: _Deck) -> str:
    steps = slide.get("steps", [])
    per_row = len(steps) if len(steps) <= 4 else 3
    items = ""
    for index, step in enumerate(steps):
        end = index % per_row == per_row - 1 or index == len(steps) - 1
        where = ("steps", index)
        title = deck.text("h3", step["title"], *where, "title") if step.get("title") else ""
        text = deck.text("p", step["text"], *where, "text", rich=True) if step.get("text") else ""
        klass = ' class="is-end"' if end else ""
        items += (
            f'<li{klass}><div class="sl-step-n"><b>{index + 1}</b><i></i></div>{title}{text}</li>'
        )
    fit = _step(len(steps), (3, 4))
    return (
        _head(slide, deck)
        + f'<ol class="sl-body sl-steps" data-fit="{fit}" style="--n:{max(1, per_row)}">'
        + f"{items}</ol>"
    )


def _closing_slide(slide: dict[str, Any], deck: _Deck) -> str:
    bullets = slide.get("bullets", [])
    hero = _hero(slide, deck, tag="h2", shift=1 if bullets else 0, rule=True)
    if not bullets:
        return hero
    per_row = len(bullets)
    fit = 2 if per_row > 3 or max(len(bullet) for bullet in bullets) > 70 else 1
    items = _items(deck, bullets, "bullets")
    return hero + f'<ul class="sl-body sl-next" data-fit="{fit}" style="--n:{per_row}">{items}</ul>'


_SLIDES: Final[dict[str, Callable[[dict[str, Any], _Deck], str]]] = {
    "title": _title_slide,
    "section": _section_slide,
    "bullets": _bullets_slide,
    "columns": _columns_slide,
    "quote": _quote_slide,
    "stats": _stats_slide,
    "chart": _chart_slide,
    "table": _table_slide,
    "image": _image_slide,
    "steps": _steps_slide,
    "closing": _closing_slide,
}


def _slide_label(slide: dict[str, Any], index: int) -> str:
    name = slide.get("title") or slide.get("quote") or slide.get("caption") or ""
    return f"Slide {index + 1}: {clean(name, 80)}" if name else f"Slide {index + 1}"


def _button(action: str, label: str, key: str, *, toggle: bool = False) -> str:
    pressed = ' aria-pressed="false"' if toggle else ""
    return (
        f'<button type="button" class="dk-btn" data-act="{action}" aria-label="{attr(label)}" '
        f'title="{attr(f"{label} ({key})")}"{pressed}>'
        f'<svg viewBox="0 0 20 20" aria-hidden="true">{_ICONS[action]}</svg></button>'
    )


def render(node: Any) -> str:
    """The deck as one self-contained page: the stage, its controls, the notes.

    The spec is read through :func:`normalize` once more, so a deck that was
    stored under older rules is laid out by today's.

    In edit mode (:mod:`dodaios.nodes.bridge`) every text that is one value of
    the stored spec can be written into: ``data-at`` names its place
    (``/slides/2/bullets/0``), ``data-src`` keeps the stored text where the
    slide draws inline marks, and the speaker notes are ``data-multiline``.
    No field asks for the page to be drawn again (that would throw the reader
    back to the first slide); the page script keeps sizes that follow a text
    in step after a save instead.
    """
    try:
        spec = normalize(node.spec)
    except NodeError:  # a stored deck no rule accepts any more still opens, with no slides
        spec = {"theme": "auto", "slides": []}
    slides: list[dict[str, Any]] = spec["slides"]
    theme: str = spec["theme"]
    accent = color(spec.get("accent"))
    deck_title = clean(node.title, 80)
    stored = node.spec.get("slides") if isinstance(node.spec, dict) else None
    # A stored deck whose slides do not line up one to one with the drawn ones
    # offers no field: a place in it could not be named.
    if not isinstance(stored, list) or len(stored) != len(slides):
        stored = None
    deck = _Deck(str(getattr(node, "language", "") or "en"), stored)
    total = len(slides)

    cells, notes = "", ""
    for index, slide in enumerate(slides):
        layout: str = slide["layout"]
        deck.index = index
        if layout == "section":
            deck.section += 1
        classes = f"sl l-{layout}"
        footer = layout != "title"
        if layout == "image" and not slide.get("title"):
            classes, footer = "sl l-bleed", False
        elif layout == "closing" and not slide.get("bullets"):
            classes += " is-bare"
        foot = (
            f'<footer class="sl-foot"><span>{esc(deck_title)}</span>'
            f"<span>{index + 1}</span></footer>"
            if footer
            else ""
        )
        label = _slide_label(slide, index)
        cells += (
            f'<li class="dk-cell{" is-current" if index == 0 else ""}" data-i="{index}">'
            f'<div class="dk-frame"><section class="{classes}" aria-roledescription="slide" '
            f'aria-label="{attr(label)}">{_SLIDES[layout](slide, deck)}{foot}</section></div>'
            f'<button type="button" class="dk-pick" aria-label="{attr(label)}"></button>'
            f'<span class="dk-no" aria-hidden="true">{index + 1}</span></li>'
        )
        if slide.get("notes"):
            hidden = "" if index == 0 else " hidden"
            said = lines(slide["notes"])
            marks = deck.mark(slide["notes"], "notes", shown=said, multiline=True)
            notes += f'<div class="dk-note" data-i="{index}"{marks}{hidden}>{said}</div>'

    first_has_notes = bool(slides and slides[0].get("notes"))
    # The deck's name is a field once, in the bar; the slides' footers repeat it.
    name_marks = f' data-at="{TITLE_PATH}"'
    if deck_title != node.title:
        name_marks += f' data-src="{attr(node.title)}"'
    forced = f' data-theme="{theme}"' if theme != "auto" else ""
    style = f' style="--da:{attr(accent)}"' if accent else ""
    body = (
        f'<div class="dk"{forced}{style} tabindex="-1">'
        f'<main class="dk-view"><ol class="dk-cells">{cells}</ol></main>'
        '<aside class="dk-notes" aria-label="Speaker notes" hidden><div class="dk-notes-in">'
        f"<h2>Speaker notes</h2>{notes}"
        f'<p class="dk-note-none"{" hidden" if first_has_notes else ""}>'
        "No notes for this slide.</p></div></aside>"
        '<nav class="dk-bar" aria-label="Slide controls">'
        '<div class="dk-progress" aria-hidden="true">'
        f'<i style="width:{100 / max(1, total):.3f}%"></i></div>'
        f'<p class="dk-name"{name_marks}>{esc(deck_title)}</p>'
        '<div class="dk-nav">'
        + _button("prev", "Previous slide", "←")
        + '<p class="dk-count" aria-live="polite" aria-atomic="true">'
        f'<span class="visually-hidden">Slide </span><b data-cur>1</b> / {total}</p>'
        + _button("next", "Next slide", "→")
        + '</div><div class="dk-tools">'
        + _button("overview", "All slides", "G", toggle=True)
        + _button("notes", "Speaker notes", "N", toggle=True)
        + "</div></nav></div>"
    )
    css = _CSS + _FORCED_THEME_CSS.get(theme, "")
    return document(node, body=body, css=css, js=_JS, body_class="fill")


__all__ = [
    "EXAMPLE",
    "GUIDE",
    "IMAGE_FITS",
    "LAYOUTS",
    "MAX_SLIDES",
    "normalize",
    "preview",
    "render",
    "starter",
]
