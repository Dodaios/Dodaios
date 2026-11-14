"""The blocks a report can carry beyond running text.

A report is written as Markdown (:mod:`.report`), and plain Markdown knows
headings, lists, tables and quotes. The page's block kit
(:mod:`.design_guide`) knows more: a metric row, a callout with a tone, a
chart whose marks answer on hover, numbered steps, a list of sources. This
module is the bridge. It reads what Markdown already produced and turns five
shapes into kit blocks:

* a fenced ``chart`` block (the same JSON the chat draws, ``CHART_GUIDANCE``
  in ``core/response_style.py``) becomes a chart card: a line, an area,
  columns or bars (grouped, or stacked with ``"stacked": true``), or a pie or
  donut that cuts one series into the shares of a whole;
* a fenced ``metrics`` block, one ``value | label | detail`` per line, becomes
  the metric row;
* a quote that opens with ``[!NOTE]``, ``[!TIP]``, ``[!IMPORTANT]``,
  ``[!WARNING]`` or ``[!CAUTION]`` becomes a callout in that tone;
* a list whose every item is one web link becomes the numbered source list;
* a numbered list whose every item opens with a bold title becomes steps.

Anything that does not fit its shape exactly stays what Markdown made of it,
so nothing is ever drawn from numbers that do not line up. Pure functions, no
I/O; every piece of text is escaped on the way out.
"""

from __future__ import annotations

import json
import math
import re
from html import escape, unescape
from typing import Any, Final
from urllib.parse import urlsplit

MAX_SERIES: Final[int] = 6
MAX_POINTS: Final[int] = 366
MAX_BAR_ROWS: Final[int] = 24
MAX_METRICS: Final[int] = 6
#: Up to this many values a one-series column chart is drawn as labelled columns.
MAX_LABELLED_COLUMNS: Final[int] = 14
#: A pie or donut with more slices than this cannot be read; a bar chart can.
MAX_SLICES: Final[int] = 12
#: A donut's hole, as a share of its radius.
_DONUT_HOLE: Final[float] = 0.58
_MAX_SOURCE_CHARS: Final[int] = 60_000

_TYPES: Final[dict[str, str]] = {
    "line": "line", "lines": "line", "area": "area",
    "column": "column", "columns": "column", "bar": "bar", "bars": "bar",
    "pie": "pie", "donut": "donut", "doughnut": "donut",
}
#: The kinds that cut one series into slices, and the kinds that can stack.
_ROUND: Final = frozenset({"pie", "donut"})
_STACKABLE: Final = frozenset({"column", "bar"})
_UNIT_BEFORE: Final = frozenset({"$", "£", "¥", "US$"})
_COMMA_DECIMAL: Final = frozenset({"de", "es", "pt", "fr", "it", "nl"})
_NUMBER_RE: Final = re.compile(r"^-?\d+(?:\.\d+)?(?:e[+-]?\d+)?$", re.IGNORECASE)
_HEX_RE: Final = re.compile(r"^#[0-9a-f]{6}$", re.IGNORECASE)


# ------------------------------------------------------------------- numbers


def format_number(value: float, language: str) -> str:
    """A number as the page's language writes it: ``1.234,5`` or ``1,234.5``."""
    size = abs(value)
    digits = 0 if size >= 1000 else 1 if size >= 100 else 2 if size >= 1 else 4
    text = f"{value:,.{digits}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if (language or "").strip().lower()[:2] in _COMMA_DECIMAL:
        text = text.replace(",", "\x00").replace(".", ",").replace("\x00", ".")
    return text.replace("-", "−")


def with_unit(value: str, unit: str) -> str:
    """A value with its unit: ``$12.50``, ``4.2%``, ``142.3 USD``."""
    if not unit:
        return value
    if unit in _UNIT_BEFORE:
        return f"−{unit}{value[1:]}" if value.startswith("−") else f"{unit}{value}"
    return f"{value}%" if unit == "%" else f"{value} {unit}"


def _ticks(low: float, high: float, target: int = 5) -> list[float]:
    """Round axis values that cover ``low … high``."""
    if high <= low:
        high = low + 1.0
    raw = (high - low) / max(1, target)
    power = 10 ** math.floor(math.log10(raw))
    step = next(m * power for m in (1, 2, 2.5, 5, 10) if m * power >= raw)
    first = math.floor(low / step) * step
    out: list[float] = []
    value = first
    while value < high + step * 0.999 and len(out) < 12:
        out.append(round(value, 10))
        value += step
    return out


# --------------------------------------------------------------- chart: read


def _text(value: Any, limit: int) -> str:
    if not isinstance(value, (str, int, float)) or isinstance(value, bool):
        return ""
    return " ".join(str(value).split())[:limit]


def _point(value: Any) -> float | None | bool:
    """A number, ``None`` for a gap, ``False`` for something that is neither."""
    if value is None:
        return None
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else False
    if isinstance(value, str) and _NUMBER_RE.match(value.strip()):
        return float(value)
    return False


def parse_chart(source: str) -> dict[str, Any] | None:
    """The chart a fenced block describes, or ``None`` when it cannot be drawn.

    Reads the same fields as the chat's reader
    (``frontend/src/lib/chartSpec.ts``), with the same refusals: a list of
    another length would put numbers under the wrong labels. The node
    editors check a chart against the same rules before they save it
    (``frontend/src/components/nodes/editors/charts/chartModel.ts``).

    Beyond the chat's fields: ``"stacked": true`` puts the series of a
    column or bar chart on top of each other; ``pie`` and ``donut`` take
    exactly one series of shares (no negative value, one above zero, at
    most :data:`MAX_SLICES`; a gap leaves its slice out); ``"colors"`` names
    a ``#rrggbb`` per series (per slice for a pie or donut), where anything
    else keeps the kit's colour for that place. The result always carries
    ``stacked`` and ``colors`` (one entry per slot, ``""`` for the kit's).
    """
    if len(source) > _MAX_SOURCE_CHARS:
        return None
    try:
        raw = json.loads(source)
    except ValueError:  # not JSON: the block stays the code block Markdown made of it
        return None
    if not isinstance(raw, dict):
        return None
    kind = _TYPES.get(_text(raw.get("type"), 20).lower() or "line")
    if not kind:
        return None
    labels = raw.get("x") if isinstance(raw.get("x"), list) else raw.get("labels")
    limit = MAX_SLICES if kind in _ROUND else MAX_BAR_ROWS if kind == "bar" else MAX_POINTS
    if not isinstance(labels, list) or not 2 <= len(labels) <= limit:
        return None
    x = [_text(label, 40) for label in labels]
    if not all(x):
        return None
    title = _text(raw.get("title"), 120)
    lone = raw.get("data") if isinstance(raw.get("data"), list) else raw.get("values")
    listed = raw.get("series")
    if not isinstance(listed, list):
        listed = [{"name": title, "data": lone}] if isinstance(lone, list) else []
    if not 1 <= len(listed) <= MAX_SERIES:
        return None
    series: list[tuple[str, list[float | None]]] = []
    for entry in listed:
        if not isinstance(entry, dict):
            return None
        values = entry.get("data") if isinstance(entry.get("data"), list) else entry.get("values")
        if not isinstance(values, list) or len(values) != len(x):
            return None
        data = [_point(value) for value in values]
        if any(value is False for value in data) or all(value is None for value in data):
            return None
        numbers = [None if value is None else float(value) for value in data]
        series.append((_text(entry.get("name"), 60), numbers))
    if len(series) > 1 and not all(name for name, _ in series):
        return None
    if kind in _ROUND:
        if len(series) != 1:
            return None
        shares = [value for value in series[0][1] if value is not None]
        if any(value < 0 for value in shares) or not any(value > 0 for value in shares):
            return None
    slots = len(x) if kind in _ROUND else len(series)
    given = raw.get("colors")
    listed_colours: list[Any] = given if isinstance(given, list) else []
    colours = [
        value.strip().upper()
        if isinstance(value, str) and _HEX_RE.match(value.strip())
        else ""
        for value in (listed_colours + [""] * slots)[:slots]
    ]
    note = raw.get("note") or raw.get("subtitle") or raw.get("source")
    return {
        "type": kind,
        "title": title,
        "note": _text(note, 200),
        "unit": _text(raw.get("unit"), 12),
        "value": _text(raw.get("value"), 40),
        "delta": _text(raw.get("delta"), 40),
        "stacked": raw.get("stacked") is True and kind in _STACKABLE,
        "x": x,
        "series": series,
        "colors": colours,
    }


def _delta_class(delta: str) -> str:
    sign = re.match(r"^\s*([+\-−–])?\s*[^\d]*(\d[\d.,]*)", delta)
    if not sign or not re.search(r"[1-9]", sign.group(2)):
        return ""
    return " down" if sign.group(1) and sign.group(1) != "+" else " up"


# --------------------------------------------------------------- chart: draw

_W, _H, _LEFT, _RIGHT, _TOP, _BOTTOM = 700.0, 280.0, 48.0, 24.0, 20.0, 34.0


def _paint(spec: dict[str, Any], slot: int) -> str:
    """The colour of slot ``slot``: the chart's own, else the kit's series token.

    The kit has six series tokens and never cycles them; a pie's slices past
    the sixth take a lighter mix of the token six places before, so twelve
    slices stay twelve tells.
    """
    own = (spec.get("colors") or [])[slot : slot + 1]
    if own and own[0]:
        return own[0]
    if slot < 6:
        return f"var(--s{slot + 1})"
    return f"color-mix(in srgb, var(--s{slot - 5}) 55%, var(--bg))"


def _lone_paint(spec: dict[str, Any]) -> str:
    """`` style="--c:…"`` for a one-series chart with its own colour, else ""."""
    own = (spec.get("colors") or [""])[0]
    return f";--c:{own}" if own else ""


def _statement(label: str, name: str, value: float | None, unit: str, language: str) -> str:
    amount = "–" if value is None else with_unit(format_number(value, language), unit)
    return f"{label} · {name}: {amount}" if name else f"{label}: {amount}"


def _labelled_columns(spec: dict[str, Any], language: str) -> str:
    """One series, few values: the kit's columns, each with its value on top."""
    name, data = spec["series"][0]
    paint = _lone_paint(spec)
    values = [value or 0.0 for value in data]
    top = max((abs(value) for value in values), default=0.0) or 1.0
    key = max(range(len(values)), key=lambda index: values[index])
    cells = []
    for index, (label, value) in enumerate(zip(spec["x"], data, strict=True)):
        share = round(max(0.0, (value or 0.0)) / top * 100)
        shown = "–" if value is None else format_number(value, language)
        tip = _statement(label, "", value, spec["unit"], language)
        cells.append(
            f'<div class="col{" is-key" if index == key else ""}" style="--v:{share}{paint}" '
            f'data-tip="{escape(tip, quote=True)}" tabindex="0">'
            f"<b>{escape(shown)}</b><i></i><span>{escape(label)}</span></div>"
        )
    return f'<div class="cols">{"".join(cells)}</div>'


def _bars(spec: dict[str, Any], language: str) -> str:
    """One series of named things: horizontal bars, longest marked."""
    _, data = spec["series"][0]
    paint = _lone_paint(spec)
    values = [value or 0.0 for value in data]
    top = max((abs(value) for value in values), default=0.0) or 1.0
    key = max(range(len(values)), key=lambda index: values[index])
    rows = []
    for index, (label, value) in enumerate(zip(spec["x"], data, strict=True)):
        share = round(max(0.0, (value or 0.0)) / top * 100)
        shown = (
            "–" if value is None else with_unit(format_number(value, language), spec["unit"])
        )
        tip = _statement(label, "", value, spec["unit"], language)
        rows.append(
            f'<div class="bar{" is-key" if index == key else ""}" style="--v:{share}{paint}" '
            f'data-tip="{escape(tip, quote=True)}" tabindex="0">'
            f"<span>{escape(label)}</span><i></i><b>{escape(shown)}</b></div>"
        )
    return f'<div class="bars">{"".join(rows)}</div>'


def _plot(spec: dict[str, Any], language: str) -> str:
    """Lines, an area, or grouped or stacked columns on one value axis, as inline SVG."""
    kind: str = spec["type"]
    series: list[tuple[str, list[float | None]]] = spec["series"]
    labels: list[str] = spec["x"]
    count = len(labels)
    columns = kind in ("column", "bar")
    stacked = columns and bool(spec.get("stacked")) and len(series) > 1
    present = [value for _, data in series for value in data if value is not None]
    if stacked:
        # A stack reaches from the sum of its negative parts to that of its positive ones.
        present = [
            total
            for index in range(count)
            for total in (
                sum(max(0.0, data[index] or 0.0) for _, data in series),
                sum(min(0.0, data[index] or 0.0) for _, data in series),
            )
        ]
    low, high = min(present), max(present)
    # Columns are measured from zero. A line may leave zero when its values
    # sit far above it, so a flat-looking course still shows its movement.
    if columns or (low >= 0 and low < high * 0.5) or low == high:
        low = min(low, 0.0)
    if columns:
        high = max(high, 0.0)
    ticks = _ticks(low, high)
    floor, ceiling = ticks[0], ticks[-1]
    span = (ceiling - floor) or 1.0
    width, height = _W - _LEFT - _RIGHT, _H - _TOP - _BOTTOM
    band = width / count

    def at_x(index: int) -> float:
        if columns:
            return _LEFT + band * (index + 0.5)
        return _LEFT + (width * index / (count - 1) if count > 1 else width / 2)

    def at_y(value: float) -> float:
        return _TOP + height * (1 - (value - floor) / span)

    parts: list[str] = []
    for tick in ticks:
        y = at_y(tick)
        parts.append(
            f'<line class="{"axis" if tick == 0 else "gridline"}" x1="{_LEFT:.0f}" '
            f'x2="{_W - _RIGHT:.0f}" y1="{y:.1f}" y2="{y:.1f}"/>'
            f'<text class="tick" x="{_LEFT - 8:.0f}" y="{y + 4:.1f}" text-anchor="end">'
            f"{escape(format_number(tick, language))}</text>"
        )
    # As many x labels as fit side by side; the last one only when it has room.
    room = max(len(label) for label in labels) * 6.4 + 14
    pitch = band if columns else (width / (count - 1) if count > 1 else width)
    every = max(1, math.ceil(room / pitch))
    shown = list(range(0, count, every))
    if shown[-1] != count - 1 and (count - 1 - shown[-1]) * pitch >= room:
        shown.append(count - 1)
    for index in shown:
        anchor = "end" if index == count - 1 and not columns and count > 1 else "middle"
        parts.append(
            f'<text class="tick" x="{at_x(index):.1f}" y="{_H - 12:.0f}" '
            f'text-anchor="{anchor}">{escape(labels[index])}</text>'
        )
    rises = [0.0] * count
    falls = [0.0] * count
    for slot, (_, data) in enumerate(series):
        colour = f' style="--c:{_paint(spec, slot)}"'
        if stacked:
            bar = min(band * 0.72, 40.0)
            for index, value in enumerate(data):
                if not value:
                    continue
                start = rises[index] if value > 0 else falls[index]
                end = start + value
                if value > 0:
                    rises[index] = end
                else:
                    falls[index] = end
                top_y, bottom_y = at_y(max(start, end)), at_y(min(start, end))
                parts.append(
                    f'<rect class="colbar" x="{at_x(index) - bar / 2:.1f}" y="{top_y:.1f}" '
                    f'width="{bar:.1f}" height="{max(1.0, bottom_y - top_y):.1f}"{colour}/>'
                )
            continue
        if columns:
            group = min(band * 0.72, 28.0 * len(series))
            bar = group / len(series)
            base = at_y(max(floor, 0.0))
            for index, value in enumerate(data):
                if value is None:
                    continue
                left = at_x(index) - group / 2 + bar * slot
                y = at_y(value)
                top_y, size = (y, base - y) if value >= 0 else (base, y - base)
                parts.append(
                    f'<rect class="colbar" x="{left + 1:.1f}" y="{top_y:.1f}" '
                    f'width="{max(1.0, bar - 2):.1f}" height="{max(1.0, size):.1f}" rx="2"'
                    f"{colour}/>"
                )
            continue
        runs: list[list[tuple[float, float]]] = [[]]
        for index, value in enumerate(data):
            if value is None:
                if runs[-1]:
                    runs.append([])
                continue
            runs[-1].append((at_x(index), at_y(value)))
        for run in (run for run in runs if run):
            path = " ".join(
                f"{'M' if step == 0 else 'L'}{px:.1f},{py:.1f}" for step, (px, py) in enumerate(run)
            )
            if kind == "area" and len(series) == 1 and len(run) > 1:
                base = at_y(max(floor, 0.0))
                parts.append(
                    f'<path class="area" d="{path} L{run[-1][0]:.1f},{base:.1f} '
                    f'L{run[0][0]:.1f},{base:.1f} Z"{colour}/>'
                )
            parts.append(f'<path class="line" d="{path}"{colour}/>')
        last = next(
            (index for index in range(count - 1, -1, -1) if data[index] is not None), None
        )
        if last is not None and len(series) <= 4:
            value = data[last]
            assert value is not None
            px, py = at_x(last), at_y(value)
            parts.append(
                f'<circle class="dot" cx="{px:.1f}" cy="{py:.1f}" r="4"{colour}/>'
                f'<text class="mark-label" x="{px - 8:.1f}" y="{py - 10:.1f}" '
                f'text-anchor="end">{escape(format_number(value, language))}</text>'
            )
    hit = band if columns else (width / (count - 1) if count > 1 else width)
    for index, label in enumerate(labels):
        lines = [
            _statement(label, name if len(series) > 1 else "", data[index], spec["unit"], language)
            for name, data in series
        ]
        tip = lines[0] if len(lines) == 1 else label + " — " + "; ".join(
            line.split(" · ", 1)[1] for line in lines
        )
        if stacked:
            total = sum(data[index] or 0.0 for _, data in series)
            tip += " (" + with_unit(format_number(total, language), spec["unit"]) + ")"
        parts.append(
            f'<rect class="hit" x="{at_x(index) - hit / 2:.1f}" y="{_TOP:.0f}" '
            f'width="{hit:.1f}" height="{height:.0f}" '
            f'data-tip="{escape(tip, quote=True)}" tabindex="0"/>'
        )
    described = spec["title"] or ", ".join(name for name, _ in series if name)
    return (
        f'<svg viewBox="0 0 {_W:.0f} {_H:.0f}" role="img" '
        f'aria-label="{escape(described, quote=True)}">{"".join(parts)}</svg>'
    )


def _stacked_bars(spec: dict[str, Any], language: str) -> str:
    """Named things, each a bar made of its series' parts, the total at its end.

    Bars grow from zero, so a negative part has no length; its statement
    still says what it is.
    """
    series: list[tuple[str, list[float | None]]] = spec["series"]
    totals = [
        sum(max(0.0, data[index] or 0.0) for _, data in series) for index in range(len(spec["x"]))
    ]
    top = max(totals, default=0.0) or 1.0
    rows = []
    for index, label in enumerate(spec["x"]):
        parts = []
        for slot, (name, data) in enumerate(series):
            value = data[index]
            share = max(0.0, value or 0.0) / top * 100
            tip = _statement(label, name, value, spec["unit"], language)
            parts.append(
                f'<i style="--v:{share:.2f};--c:{_paint(spec, slot)}" '
                f'data-tip="{escape(tip, quote=True)}" tabindex="0"></i>'
            )
        shown = with_unit(format_number(totals[index], language), spec["unit"])
        rows.append(
            f'<div class="bar stacked"><span>{escape(label)}</span>'
            f'<div class="stack">{"".join(parts)}</div><b>{escape(shown)}</b></div>'
        )
    return f'<div class="bars">{"".join(rows)}</div>'


def _arc(cx: float, cy: float, outer: float, inner: float, start: float, end: float) -> str:
    """The path of one slice from angle ``start`` to ``end`` (radians, clockwise from
    twelve o'clock); a ring segment when ``inner`` is above zero."""

    def at(radius: float, angle: float) -> tuple[float, float]:
        return cx + radius * math.sin(angle), cy - radius * math.cos(angle)

    large = 1 if end - start > math.pi else 0
    x1, y1 = at(outer, start)
    x2, y2 = at(outer, end)
    if inner <= 0:
        return (
            f"M{cx:.2f},{cy:.2f} L{x1:.2f},{y1:.2f} "
            f"A{outer:.2f},{outer:.2f} 0 {large} 1 {x2:.2f},{y2:.2f} Z"
        )
    x3, y3 = at(inner, end)
    x4, y4 = at(inner, start)
    return (
        f"M{x1:.2f},{y1:.2f} A{outer:.2f},{outer:.2f} 0 {large} 1 {x2:.2f},{y2:.2f} "
        f"L{x3:.2f},{y3:.2f} A{inner:.2f},{inner:.2f} 0 {large} 0 {x4:.2f},{y4:.2f} Z"
    )


def _pie(spec: dict[str, Any], language: str) -> str:
    """One series as the shares of a whole: slices beside a legend that lists
    every value and its share. A donut says the total in its hole."""
    _, data = spec["series"][0]
    unit = spec["unit"]
    slices = [
        (index, label, value)
        for index, (label, value) in enumerate(zip(spec["x"], data, strict=True))
        if value is not None and value > 0
    ]
    total = sum(value for _, _, value in slices)
    donut = spec["type"] == "donut"
    size, gap = 240.0, 2.0
    cx = cy = size / 2
    outer = size / 2 - gap
    inner = outer * _DONUT_HOLE if donut else 0.0
    marks: list[str] = []
    legend: list[str] = []
    angle = 0.0
    for index, label, value in slices:
        share = value / total
        sweep = share * 2 * math.pi
        percent = format_number(share * 100, language) + "%"
        amount = with_unit(format_number(value, language), unit)
        tip = escape(f"{label}: {amount} ({percent})", quote=True)
        paint = _paint(spec, index)
        if len(slices) == 1:
            # One slice is the whole: an arc from a point back to itself draws nothing.
            ring = (
                f'<circle class="slice" cx="{cx:.0f}" cy="{cy:.0f}" r="{(outer + inner) / 2:.2f}" '
                f'style="--c:{paint};fill:none;stroke:var(--c);stroke-width:{outer - inner:.2f}"'
                if donut
                else f'<circle class="slice" cx="{cx:.0f}" cy="{cy:.0f}" r="{outer:.2f}" '
                f'style="--c:{paint}"'
            )
            marks.append(f'{ring} data-tip="{tip}" tabindex="0"/>')
        else:
            marks.append(
                f'<path class="slice" d="{_arc(cx, cy, outer, inner, angle, angle + sweep)}" '
                f'style="--c:{paint}" data-tip="{tip}" tabindex="0"/>'
            )
        angle += sweep
        legend.append(
            f'<li><i style="--c:{paint}"></i><span>{escape(label)}</span>'
            f'<b>{escape(amount)}</b><span class="share">{escape(percent)}</span></li>'
        )
    if donut:
        marks.append(
            f'<text class="total" x="{cx:.0f}" y="{cy + 7:.0f}" text-anchor="middle">'
            f"{escape(with_unit(format_number(total, language), unit))}</text>"
        )
    described = spec["title"] or ", ".join(label for _, label, _ in slices)
    return (
        f'<div class="pie"><svg viewBox="0 0 {size:.0f} {size:.0f}" role="img" '
        f'aria-label="{escape(described, quote=True)}">{"".join(marks)}</svg>'
        f'<ol>{"".join(legend)}</ol></div>'
    )


def render_chart(spec: dict[str, Any], language: str) -> str:
    """One chart card on the kit's classes; every mark carries its statement."""
    series = spec["series"]
    lone = len(series) == 1
    stacked = bool(spec.get("stacked")) and not lone
    if spec["type"] in _ROUND:
        body = _pie(spec, language)
    elif spec["type"] == "bar" and stacked:
        body = _stacked_bars(spec, language)
    elif spec["type"] == "bar" and lone:
        body = _bars(spec, language)
    elif spec["type"] == "column" and lone and len(spec["x"]) <= MAX_LABELLED_COLUMNS:
        body = _labelled_columns(spec, language)
    else:
        body = _plot(spec, language)
    head = f"<h3>{escape(spec['title'])}</h3>" if spec["title"] else ""
    if spec["value"]:
        delta = (
            f'<div class="detail{_delta_class(spec["delta"])}">{escape(spec["delta"])}</div>'
            if spec["delta"]
            else ""
        )
        head += f'<div class="metric"><div class="value">{escape(spec["value"])}</div>{delta}</div>'
    legend = ""
    if not lone:
        legend = '<div class="legend">' + "".join(
            f'<span><i style="--c:{_paint(spec, slot)}"></i>{escape(name)}</span>'
            for slot, (name, _) in enumerate(series)
        ) + "</div>"
    note = f'<p class="note">{escape(spec["note"])}</p>' if spec["note"] else ""
    return f'<figure class="card chart">{head}{legend}{body}{note}</figure>'


# ------------------------------------------------------------------- metrics


def render_metrics(source: str) -> str | None:
    """``value | label | detail`` per line, as the metric row."""
    cells = []
    for line in source.splitlines():
        fields = [field.strip() for field in line.strip().strip("|").split("|")]
        if not line.strip():
            continue
        if len(fields) < 2 or not fields[0] or not fields[1]:
            return None
        extra = fields[2] if len(fields) > 2 else ""
        detail = f'<div class="detail">{escape(extra)}</div>' if extra else ""
        cells.append(
            f'<div class="metric"><div class="value">{escape(fields[0])}</div>'
            f'<div class="label">{escape(fields[1])}</div>{detail}</div>'
        )
    if not 1 <= len(cells) <= MAX_METRICS:
        return None
    return f'<div class="metrics">{"".join(cells)}</div>'


# ------------------------------------------------- what Markdown already made

_FENCE_RE: Final = re.compile(
    r'<pre><code class="language-(chart|metrics)">(.*?)</code></pre>', re.DOTALL
)
_CALLOUT_RE: Final = re.compile(
    r"<blockquote>\s*<p>\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*(?:<br\s*/?>)?\s*"
    r"(.*?)</blockquote>",
    re.DOTALL | re.IGNORECASE,
)
_TONES: Final[dict[str, str]] = {
    "note": "info", "important": "info", "tip": "good", "warning": "warn", "caution": "bad",
}
_EMPTY_OPENING_RE: Final = re.compile(r"^</p>\s*<p>")
_LEAD_RE: Final = re.compile(r"^<strong>(.*?)</strong>\s*(?:<br\s*/?>)?\s*", re.DOTALL)
_FLAT_LIST_RE: Final = re.compile(r"<(ul|ol)>((?:(?!<[uo]l[ >]).)*?)</\1>", re.DOTALL)
_ITEM_RE: Final = re.compile(r"<li>(.*?)</li>", re.DOTALL)
_LINK_ITEM_RE: Final = re.compile(
    r'^\s*(?:<p>)?\s*<a href="(https?://[^"]+)"[^>]*>(.*?)</a>\s*(?:</p>)?\s*$', re.DOTALL
)
_STEP_ITEM_RE: Final = re.compile(
    r"^\s*(?:<p>)?\s*<strong>(.+?)</strong>\s*[:.–—-]?\s*(.*?)(?:</p>)?\s*$", re.DOTALL
)


def _fence(match: re.Match[str], language: str) -> str:
    source = unescape(match.group(2))
    if match.group(1) == "metrics":
        return render_metrics(source) or match.group(0)
    spec = parse_chart(source)
    return render_chart(spec, language) if spec else match.group(0)


def _callout(match: re.Match[str]) -> str:
    tone = _TONES[match.group(1).lower()]
    # A blank quote line after the marker leaves an empty first paragraph.
    body = _EMPTY_OPENING_RE.sub("", match.group(2).strip())
    body = _LEAD_RE.sub(
        lambda lead: f'<strong class="lead">{lead.group(1)}</strong>', body, count=1
    )
    return f'<div class="callout {tone}"><p>{body}</div>'


def _site(url: str) -> str:
    host = urlsplit(url).hostname or ""
    return host[4:] if host.startswith("www.") else host


def _list(match: re.Match[str]) -> str:
    items = _ITEM_RE.findall(match.group(2))
    if len(items) < 2:
        return match.group(0)
    links = [found for found in map(_LINK_ITEM_RE.match, items) if found]
    if len(links) == len(items):
        rows = "".join(
            f'<li><a href="{link.group(1)}">{link.group(2)}'
            f'<span class="site">{escape(_site(unescape(link.group(1))))}</span></a></li>'
            for link in links
        )
        return f'<ol class="links">{rows}</ol>'
    steps = [found for found in map(_STEP_ITEM_RE.match, items) if found]
    if match.group(1) != "ol" or len(steps) != len(items):
        return match.group(0)
    if not any(step.group(2).strip() for step in steps):
        return match.group(0)
    rows = ""
    for step in steps:
        detail = step.group(2).strip()
        rows += f"<li><h3>{step.group(1).rstrip(':. ')}</h3>"
        rows += f"<p>{detail}</p></li>" if detail else "</li>"
    return f'<ol class="steps">{rows}</ol>'


def upgrade_blocks(html: str, language: str = "en") -> str:
    """Markdown's HTML with the five shapes above turned into kit blocks."""
    html = _FENCE_RE.sub(lambda match: _fence(match, language), html)
    html = _CALLOUT_RE.sub(_callout, html)
    return _FLAT_LIST_RE.sub(_list, html)


__all__ = [
    "MAX_LABELLED_COLUMNS",
    "MAX_SLICES",
    "format_number",
    "parse_chart",
    "render_chart",
    "render_metrics",
    "upgrade_blocks",
    "with_unit",
]
