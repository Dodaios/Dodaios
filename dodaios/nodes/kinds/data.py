"""The ``data`` node: a dashboard, a page of numbers that is scanned, not read.

A dashboard answers "where do we stand" at a glance, so its grammar is the
three things a glance takes in, grouped into sections: a row of current
values (``metrics``), pictures of a course or a ranking (``charts``) and the
long tail as a table (``tables``). The model writes values, never layout:
which chart sits beside which, what a wide window shows in two columns and a
narrow one in one, and which table column is a column of numbers are decided
here, the same way for every dashboard.

The charts are the report's charts. A chart in this spec is the JSON object a
report's fenced ``chart`` block takes, validated and drawn by
:mod:`dodaios.artifacts.report_blocks`, so a figure looks the same in a
document and on a dashboard and there is one place that knows how to draw it.
A chart whose numbers do not line up is refused when the spec is written, not
left out when the page is drawn: the model learns of it while it can still
send the chart again.

Pure functions, no I/O.
"""

from __future__ import annotations

import json
import re
from typing import Any, Final

# `_delta_class` is the kit's reading of a change ("+12 %" up, "−3" down): the
# same rule colors a delta in a report's chart head and on a dashboard.
from dodaios.artifacts.report_blocks import (
    _delta_class,
    format_number,
    parse_chart,
    render_chart,
)
from dodaios.nodes import shell
from dodaios.nodes.types import NodeError

MAX_SECTIONS: Final[int] = 12
MAX_METRICS: Final[int] = 8
MAX_CHARTS: Final[int] = 8
MAX_TABLES: Final[int] = 4
MAX_COLUMNS: Final[int] = 12
MAX_ROWS: Final[int] = 200
MAX_SUMMARY_CHARS: Final[int] = 600
MAX_TITLE_CHARS: Final[int] = 120
MAX_TEXT_CHARS: Final[int] = 600
MAX_LABEL_CHARS: Final[int] = 80
MAX_VALUE_CHARS: Final[int] = 40
MAX_DETAIL_CHARS: Final[int] = 120
MAX_CELL_CHARS: Final[int] = 300
#: Where the numbers come from, named under the title: "orders.csv",
#: "Notion: Projects", "Portfolio at the broker".
MAX_SOURCES: Final[int] = 8
MAX_SOURCE_CHARS: Final[int] = 80

#: What the card in the library shows of a dashboard.
PREVIEW_METRICS: Final[int] = 3
PREVIEW_BARS: Final[int] = 8

_PARTS: Final[tuple[str, ...]] = ("metrics", "charts", "tables")
_WHAT_TO_SEND: Final[str] = (
    "A data node's spec is an object {\"summary\": \"…\", \"sources\": [\"…\"], \"sections\": "
    "[{\"title\", \"text\", \"metrics\": [...], \"charts\": [...], \"tables\": [...]}]} with at "
    "least one metric, chart or table."
)
_CHART_RULES: Final[str] = (
    "'type' is line, area, column, bar, pie or donut; 'x' (the labels) and every series' "
    "'data' must be lists of the same length with 2 or more points (a bar chart at most 24, "
    "a pie or donut 12 with exactly one series of values >= 0, the others at most 366); the "
    "values must be numbers (null for a gap); two or more series each need a 'name', and "
    "there are at most 6."
)

_CONTROL_RE: Final = re.compile(r"[\x00-\x1f\x7f]")


# ------------------------------------------------------------------ normalize


def _line(value: Any, limit: int) -> str:
    """One clipped line. Trimmed again after the cut, so a second pass keeps it."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return ""
    return shell.clean(_CONTROL_RE.sub(" ", str(value)), limit).rstrip()


def _whole(value: float) -> int | float:
    """``3.0`` as ``3``: the spec is read back by the model, so it stays short."""
    return int(value) if value == int(value) and abs(value) < 2**53 else value


def _entries(value: Any, where: str, what: str) -> list[Any]:
    """The list at ``where``; a lone object counts as a list of one."""
    if value is None:
        return []
    if isinstance(value, dict):
        return [value]
    if not isinstance(value, list):
        raise NodeError(f"{where} must be a list of {what}.")
    return value


def _metric(raw: Any, where: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise NodeError(f"{where} must be an object with 'label' and 'value'.")
    label = _line(raw.get("label"), MAX_LABEL_CHARS)
    value = _line(raw.get("value"), MAX_VALUE_CHARS)
    if not label or not value:
        raise NodeError(
            f"{where} needs a 'label' (two to four words) and a 'value' (the figure with its "
            "unit, as text)."
        )
    metric: dict[str, Any] = {"label": label, "value": value}
    for key, limit in (("detail", MAX_DETAIL_CHARS), ("delta", MAX_VALUE_CHARS)):
        text = _line(raw.get(key), limit)
        if text:
            metric[key] = text
    # A falling return rate is good news: the sign alone cannot say that.
    if "delta" in metric and str(raw.get("better") or "").strip().lower() == "lower":
        metric["better"] = "lower"
    return metric


def _chart(raw: Any, where: str) -> dict[str, Any]:
    """The chart in its one written form, or a ``NodeError`` naming it."""
    if not isinstance(raw, dict):
        raise NodeError(f"{where} must be an object with 'type', 'title', 'x' and 'series'.")
    try:
        parsed = parse_chart(json.dumps(raw))
    except (TypeError, ValueError):  # not JSON data at all: refused like any undrawable chart
        parsed = None
    if parsed is None:
        named = _line(raw.get("title"), 60)
        which = f"{where} ({named!r})" if named else where
        raise NodeError(f"{which} cannot be drawn. {_CHART_RULES}")
    chart: dict[str, Any] = {
        "type": parsed["type"],
        "title": parsed["title"],
        "x": list(parsed["x"]),
        "series": [
            {"name": name, "data": [None if value is None else _whole(value) for value in data]}
            for name, data in parsed["series"]
        ],
    }
    for key in ("unit", "note", "value", "delta"):
        if parsed[key]:
            chart[key] = parsed[key]
    # The shared grammar's newer keys, kept only when they say something so a
    # chart written without them reads back exactly as it was sent.
    if parsed.get("stacked"):
        chart["stacked"] = True
    colors = parsed.get("colors") or []
    if any(colors):
        chart["colors"] = list(colors)
    if raw.get("wide") is True or str(raw.get("wide")).strip().lower() == "true":
        chart["wide"] = True
    return chart


def _cell(value: Any) -> str | int | float:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        number = shell.number(value)
        return "" if number is None else _whole(number)
    if isinstance(value, str):
        return _line(value, MAX_CELL_CHARS)
    return ""


def _table(raw: Any, where: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise NodeError(f"{where} must be an object with 'columns' and 'rows'.")
    rows_in = raw.get("rows") if isinstance(raw.get("rows"), list) else []
    listed = raw.get("columns")
    if not isinstance(listed, list) and rows_in and isinstance(rows_in[0], dict):
        listed = list(rows_in[0])
    columns = [_line(name, MAX_LABEL_CHARS) for name in shell.as_list(listed, MAX_COLUMNS)]
    if not any(columns):
        raise NodeError(
            f"{where} needs 'columns' (a list of column names) and 'rows' (a list of lists "
            "with one cell per column)."
        )
    keys = [name.lower() for name in columns]
    rows: list[list[str | int | float]] = []
    for row in rows_in:
        if isinstance(row, dict):
            by_name = {str(key).strip().lower(): cell for key, cell in row.items()}
            cells = [_cell(by_name.get(key)) for key in keys]
        elif isinstance(row, list):
            cells = [_cell(cell) for cell in row[: len(columns)]]
            cells += [""] * (len(columns) - len(cells))
        else:
            cells = [_cell(row)] + [""] * (len(columns) - 1)
        if any(cell != "" for cell in cells):
            rows.append(cells)
        if len(rows) == MAX_ROWS:
            break
    return {"title": _line(raw.get("title"), MAX_TITLE_CHARS), "columns": columns, "rows": rows}


def _section(raw: Any, number: int) -> dict[str, Any]:
    where = f"Section {number}"
    if not isinstance(raw, dict):
        raise NodeError(
            f"{where} must be an object with 'title', 'text', 'metrics', 'charts' or 'tables'."
        )
    metrics = _entries(raw.get("metrics"), f"{where}: 'metrics'", "metric objects")
    charts = _entries(raw.get("charts"), f"{where}: 'charts'", "chart objects")
    tables = _entries(raw.get("tables"), f"{where}: 'tables'", "table objects")
    return {
        "title": _line(raw.get("title"), MAX_TITLE_CHARS),
        "text": _line(raw.get("text"), MAX_TEXT_CHARS),
        "metrics": [
            _metric(item, f"Metric {index} in section {number}")
            for index, item in enumerate(metrics[:MAX_METRICS], start=1)
        ],
        "charts": [
            _chart(item, f"Chart {index} in section {number}")
            for index, item in enumerate(charts[:MAX_CHARTS], start=1)
        ],
        "tables": [
            _table(item, f"Table {index} in section {number}")
            for index, item in enumerate(tables[:MAX_TABLES], start=1)
        ],
    }


def _sources(value: Any) -> list[str]:
    """The named sources, each once, in the order given."""
    names: list[str] = []
    for raw in shell.as_list(value, MAX_SOURCES * 2):
        name = _line(raw, MAX_SOURCE_CHARS)
        if name and name.lower() not in (known.lower() for known in names):
            names.append(name)
    return names[:MAX_SOURCES]


def normalize(spec: Any) -> dict[str, Any]:
    """The dashboard's clean spec: ``{"summary", "sources", "sections"}``.

    Top-level ``metrics`` / ``charts`` / ``tables`` become one untitled first
    section. A section that holds nothing is left out. ``sources`` is kept
    only when the spec names one.

    Raises:
        NodeError: the spec is not an object, a part has the wrong shape, a
            chart cannot be drawn, or nothing is left to show.
    """
    if not isinstance(spec, dict):
        raise NodeError(_WHAT_TO_SEND)
    listed = _entries(spec.get("sections"), "'sections'", "section objects")
    lead = {key: spec[key] for key in _PARTS if spec.get(key)}
    if lead:
        listed = [lead, *listed]
    sections = []
    for number, raw in enumerate(listed, start=1):
        section = _section(raw, number)
        if any(section[key] for key in ("title", "text", *_PARTS)):
            sections.append(section)
        if len(sections) == MAX_SECTIONS:
            break
    if not any(section[key] for section in sections for key in _PARTS):
        raise NodeError(_WHAT_TO_SEND)
    clean: dict[str, Any] = {"summary": _line(spec.get("summary"), MAX_SUMMARY_CHARS)}
    sources = _sources(spec.get("sources"))
    if sources:
        clean["sources"] = sources
    clean["sections"] = sections
    return clean


# --------------------------------------------------------------------- render

_COMMA_DECIMAL: Final = frozenset({"de", "es", "pt", "fr", "it", "nl"})
_GROUP: Final[str] = "   '’"
#: A cell that reads as one number: a sign, a currency mark or code, the
#: digits, then a short unit ("12 %", "$1,200", "−3.4 pts", "48.2k").
_NUMBER_CELL_RE: Final = re.compile(
    r"^(?P<sign>[+\-−–]?)\s*(?:[$€£¥~≈<>≤≥]{1,2}|[A-Z]{3}\s)?\s*"
    rf"(?P<digits>\d[\d.,{_GROUP}]*?)\s*(?P<unit>[^\d\s.,][^\d]{{0,9}})?$"
)
_GROUPED_RE: Final = re.compile(r"^\d{1,3}(?:[.,]\d{3})+$")
_EMPTY_CELLS: Final = frozenset({"", "-", "–", "—", "n/a", "na"})
_SCALES: Final[dict[str, float]] = {"k": 1e3, "K": 1e3, "M": 1e6, "B": 1e9, "bn": 1e9}


def _cell_number(cell: str | int | float, comma_decimal: bool) -> float | None:
    """The number a table cell stands for, or ``None`` when it is words."""
    if not isinstance(cell, str):
        return float(cell)
    found = _NUMBER_CELL_RE.match(cell.strip())
    if not found:
        return None
    digits = re.sub(rf"(?<=\d)[{_GROUP}](?=\d{{3}}(?!\d))", "", found.group("digits"))
    if not re.fullmatch(r"[\d.,]+", digits) or digits[-1] in ".,":
        return None
    dots, commas = digits.count("."), digits.count(",")
    if dots and commas:
        decimal = "," if digits.rfind(",") > digits.rfind(".") else "."
        grouping = "." if decimal == "," else ","
        if digits.count(decimal) > 1:
            return None
        digits = digits.replace(grouping, "").replace(decimal, ".")
    elif dots or commas:
        mark = "." if dots else ","
        grouped = bool(_GROUPED_RE.match(digits))
        if dots + commas > 1 and not grouped:
            return None  # a date or a version, not a number
        decimal_mark = "," if comma_decimal else "."
        if grouped and (dots + commas > 1 or mark != decimal_mark):
            digits = digits.replace(mark, "")
        else:
            digits = digits.replace(mark, ".")
    value = float(digits)
    unit = (found.group("unit") or "").split()
    value *= _SCALES.get(unit[0], 1.0) if unit else 1.0
    return -value if found.group("sign") in ("-", "−", "–") else value


def _at(path: str, src: str | None = None) -> str:
    """The edit marks of one value of the spec (:mod:`dodaios.nodes.bridge`).

    ``src`` is the value as stored, given when the page draws something else
    (inline marks, a formatted number).
    """
    marks = f' data-at="{shell.attr(path)}"'
    return marks if src is None else f'{marks} data-src="{shell.attr(src)}"'


def _inline_at(path: str, text: str, limit: int) -> tuple[str, str]:
    """A text with inline marks as drawn, and its edit marks."""
    shown = shell.inline(text, limit)
    return shown, _at(path, text if shown != shell.esc(text) else None)


def _metrics(metrics: list[Any], base: str) -> str:
    cells = []
    for index, metric in enumerate(metrics):
        if not isinstance(metric, dict):
            continue
        at = f"{base}/{index}"
        delta = _line(metric.get("delta"), MAX_VALUE_CHARS)
        detail = _line(metric.get("detail"), MAX_DETAIL_CHARS)
        below = ""
        if delta or detail:
            tone = _delta_class(delta)
            lower = metric.get("better") == "lower"
            if lower and tone:
                tone = " up" if tone == " down" else " down"
            # The page's script colors the delta again after the reader changed
            # it; ``data-better`` tells it which way round.
            flip = ' data-better="lower"' if lower else ""
            change = (
                f'<span class="delta{tone}"{flip}{_at(f"{at}/delta")}>{shell.esc(delta)}</span>'
                if delta
                else ""
            )
            said = f'<span{_at(f"{at}/detail")}>{shell.esc(detail)}</span>' if detail else ""
            below = f'<div class="detail">{change}{" " if delta and detail else ""}{said}</div>'
        label = shell.esc(_line(metric.get("label"), MAX_LABEL_CHARS))
        value = shell.esc(_line(metric.get("value"), MAX_VALUE_CHARS))
        cells.append(
            '<div class="metric">'
            f'<div class="label"{_at(f"{at}/label")}>{label}</div>'
            f'<div class="value"{_at(f"{at}/value")}>{value}</div>'
            f"{below}</div>"
        )
    if not cells:
        return ""
    # Rows of even length: five values read as three and two, not four and one.
    per_row = len(cells) if len(cells) <= 4 else 3 if len(cells) <= 6 else 4
    return f'<div class="metrics" style="--n:{per_row}">{"".join(cells)}</div>'


#: The chart types that cut one series into the shares of a whole.
_ROUND: Final = frozenset({"pie", "donut"})
_SPLIT_FIGURE: Final[str] = '<figure class="card chart split">'
_NUMBER_CLASS: Final[str] = ' class="n"'


def _drawable(charts: list[Any]) -> list[tuple[dict[str, Any], bool]]:
    """Every chart that can be drawn, with whether it asked for the whole row."""
    found = []
    for chart in charts:
        if not isinstance(chart, dict):
            continue
        try:
            parsed = parse_chart(json.dumps(chart))
        except (TypeError, ValueError):  # a spec that skipped normalize: nothing to draw
            parsed = None
        if parsed is not None:
            found.append((parsed, chart.get("wide") is True))
    return found


def _charts(charts: list[Any], language: str) -> str:
    drawable = _drawable(charts)
    tiles = []
    column = 0
    for index, (parsed, wide) in enumerate(drawable):
        if not wide and column == 0:
            # A chart left alone in its row takes the row.
            wide = index == len(drawable) - 1 or drawable[index + 1][1]
        column = 0 if wide or column == 1 else 1
        figure = render_chart(parsed, language)
        if parsed["type"] not in _ROUND:
            # A plot on the 700-unit frame scrolls inside its card when the
            # card is narrow. A pie or donut is drawn at its own size beside
            # its legend (the kit's `.pie`) and is never stretched or scrolled.
            figure = figure.replace("<svg ", '<div class="plot"><svg ', 1)
            figure = figure.replace("</svg>", "</svg></div>", 1)
        if parsed["title"] or parsed["value"]:
            figure = figure.replace('<figure class="card chart">', _SPLIT_FIGURE, 1)
        tiles.append(f'<div class="tile{" wide" if wide else ""}">{figure}</div>')
    return f'<div class="dash-grid">{"".join(tiles)}</div>' if tiles else ""


def _is_empty(cell: Any) -> bool:
    return isinstance(cell, str) and cell.strip().lower() in _EMPTY_CELLS


def _number_source(value: int | float) -> str:
    """A stored number as plain digits, the way the reader types one."""
    text = str(value)
    if "e" in text or "E" in text:
        text = f"{value:.15f}".rstrip("0").rstrip(".")
    return text


def _cell_marks(at: str, cell: Any, shown: str) -> str:
    """The edit marks of one table cell; none for a cell the spec does not hold."""
    if isinstance(cell, bool) or not isinstance(cell, (str, int, float)):
        return ""
    if isinstance(cell, str):
        return _at(at, cell if shown != shell.esc(cell) else None)
    return f'{_at(at, _number_source(cell))} data-as="number"'


def _table_html(table: dict[str, Any], language: str, base: str) -> str:
    listed = shell.as_list(table.get("columns"), 99)
    columns = [_line(name, MAX_LABEL_CHARS) for name in listed]
    if not columns:
        return ""
    comma = language.strip().lower()[:2] in _COMMA_DECIMAL
    stored = shell.as_list(table.get("rows"), MAX_ROWS)
    rows: list[list[str | int | float]] = []
    for row in stored:
        cells = list(row[: len(columns)]) if isinstance(row, list) else []
        cells += [""] * (len(columns) - len(cells))
        rows.append(
            [
                cell if isinstance(cell, (str, int, float)) and not isinstance(cell, bool) else ""
                for cell in cells
            ]
        )
    # A column is a column of numbers when every filled cell in it is one.
    values = [
        [None if _is_empty(row[index]) else _cell_number(row[index], comma) for row in rows]
        for index in range(len(columns))
    ]
    numeric = [
        any(value is not None for value in values[index])
        and all(
            value is not None or _is_empty(row[index])
            for row, value in zip(rows, values[index], strict=True)
        )
        for index in range(len(columns))
    ]
    head = "".join(
        f'<th scope="col"{_NUMBER_CLASS if numeric[index] else ""}'
        f'{_at(f"{base}/columns/{index}") if isinstance(listed[index], str) else ""}>'
        f"{shell.esc(name)}</th>"
        for index, name in enumerate(columns)
    )
    body = []
    for at, row in enumerate(rows):
        # Only a cell the stored row holds is a place to write into: a row of
        # another shape is drawn padded, and its padding is no place.
        source = stored[at] if isinstance(stored[at], list) else []
        cells_html = []
        for index, cell in enumerate(row):
            if isinstance(cell, str):
                shown = shell.inline(cell, MAX_CELL_CHARS)
            else:
                shown = shell.esc(format_number(float(cell), language))
            marks = (
                _cell_marks(f"{base}/rows/{at}/{index}", source[index], shown)
                if index < len(source)
                else ""
            )
            if numeric[index]:
                value = values[index][at]
                sort = "" if value is None else f"{value:.12g}"
                cells_html.append(f'<td{_NUMBER_CLASS} data-value="{sort}"{marks}>{shown}</td>')
            else:
                cells_html.append(f"<td{marks}>{shown}</td>")
        body.append(f"<tr>{''.join(cells_html)}</tr>")
    title = _line(table.get("title"), MAX_TITLE_CHARS)
    return (
        '<div class="dash-table">'
        + (f'<h3{_at(f"{base}/title")}>{shell.esc(title)}</h3>' if title else "")
        + '<div class="table-wrap"><table class="table" data-sort>'
        f"<thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div></div>"
    )


def _section_html(section: dict[str, Any], language: str, base: str) -> str:
    title = _line(section.get("title"), MAX_TITLE_CHARS)
    text = _line(section.get("text"), MAX_TEXT_CHARS)
    # A section of words alone is left out once both are empty, which moves
    # every later section up one place: the page is drawn again after such
    # an edit, so its pointers stay true.
    bare = "" if any(section.get(key) for key in _PARTS) else " data-refresh"
    shown, text_at = _inline_at(f"{base}/text", text, MAX_TEXT_CHARS)
    parts = [
        f'<h2{_at(f"{base}/title")}{bare}>{shell.esc(title)}</h2>' if title else "",
        f'<p class="dash-text"{text_at}{bare}>{shown}</p>' if text else "",
        _metrics(shell.as_list(section.get("metrics"), MAX_METRICS), f"{base}/metrics"),
        # A chart's title is drawn inside the report kit's figure
        # (`report_blocks.render_chart`), so it is not offered for editing.
        _charts(shell.as_list(section.get("charts"), MAX_CHARTS), language),
    ]
    parts += [
        _table_html(table, language, f"{base}/tables/{index}")
        for index, table in enumerate(shell.as_list(section.get("tables"), MAX_TABLES))
        if isinstance(table, dict)
    ]
    inner = "".join(parts)
    return f'<section class="section">{inner}</section>' if inner else ""


# A chart is drawn on a fixed 700-unit frame and scaled to its card, so the
# layout keeps every card in the range where that frame reads well: side by
# side only when each card is wide enough, scrolling inside the card on a
# narrow window, and beside its own head when the card spans a wide row.
_CSS: Final[str] = """
::selection{background:var(--accent-soft)}
.page.dash{max-width:1216px}
.dash-head .summary{max-width:700px;margin-top:12px;color:var(--ink-2);text-wrap:pretty}
.dash-head .node-meta{margin-top:14px}
.dash-sources{display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin:14px 0 0;padding:0;
  list-style:none;font-size:13px;line-height:18px;color:var(--ink-2)}
.dash-sources>.icon{display:inline-flex;color:var(--ink-3)}
.dash-sources>li:not(.icon){padding:3px 10px;border:1px solid var(--line-2);border-radius:999px}
.dash .section{margin-top:56px}
.dash-head+.section{margin-top:36px}
.dash .section>h2+.dash-text{margin-top:6px}
.dash-text{max-width:700px;color:var(--ink-2);text-wrap:pretty}
.dash .metrics{display:flex;flex-wrap:wrap;gap:1px;overflow:hidden;border:1px solid var(--line-2);
  border-radius:var(--radius);background:var(--line)}
.dash .metrics>.metric{flex:1 1 calc(100%/var(--n,4) - 1px);min-width:152px;
  padding:16px 20px 18px;background:var(--bg)}
.dash .metrics .label{margin:0;color:var(--ink-2)}
.dash .metrics .value{margin-top:6px;font-size:28px;line-height:34px;letter-spacing:-.02em}
.dash .metrics .detail{margin-top:4px}
.dash .delta{font-weight:500;font-variant-numeric:tabular-nums}
.dash-grid{display:grid;grid-template-columns:minmax(0,1fr);gap:20px}
.tile{display:grid;min-width:0;container-type:inline-size}
.tile>.card{display:flex;flex-direction:column;margin:0}
.tile>.card>.note{margin-top:auto;padding-top:12px}
.tile>.card>h3{text-wrap:balance}
.plot{overflow-x:auto;padding:4px 0 2px}
.plot svg{min-width:500px;max-width:880px;margin:0 auto}
@container (max-width:700px){.tile .chart .tick,.tile .chart .mark-label{font-size:13px}}
@container (min-width:880px){
.tile>.split{display:grid;grid-template-columns:minmax(200px,248px) minmax(0,1fr);
  grid-template-rows:auto auto auto 1fr;column-gap:40px;align-items:start;padding:20px 24px}
.tile>.split>*{grid-column:1}
.tile>.split>.plot,.tile>.split>.cols,.tile>.split>.bars,.tile>.split>.pie{grid-column:2;grid-row:1/-1;margin-top:0;
  align-self:center}
.tile>.split>.note{grid-row:4;align-self:end}
.tile>.split>.legend{flex-direction:column;gap:6px}
}
@media (min-width:1180px){
.dash-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
.dash-grid>.wide{grid-column:1/-1}
}
.dash-table>h3{margin-bottom:10px}
.dash .table th,.dash .table .n{white-space:nowrap}
.dash .table td:first-child{min-width:132px}
@media (max-width:560px){.dash .metrics>.metric{min-width:132px;padding:14px 16px 16px}
.dash .metrics .value{font-size:24px;line-height:30px}.dash .section{margin-top:44px}}
@media print{.page.dash{max-width:none}.plot{overflow:visible}.plot svg{min-width:0}
.tile{break-inside:avoid}}
:root[data-node-mode="edit"] .dash span[data-at]:empty{display:inline-block;min-width:2ch}
"""

# The kit's script sorts a table on a click only; a column head must answer
# to the keyboard too. A plot that scrolls inside its card opens at its end,
# where the latest value is.
#
# After the reader changed a value in edit mode (`node-field-saved`, see
# `nodes/bridge.py`) the page follows up without being drawn again, so the
# reader keeps their place: a delta takes the color of its new sign (the rule
# of `_delta_class`), a cell of a column of numbers sorts by its new number
# (the rule of `_cell_number`), and a row left without any value goes, as
# `normalize` drops it, with the rows below moving up one place.
_JS: Final[str] = r"""
(function(){var d=document,each=function(l,f){Array.prototype.forEach.call(l,f);};
each(d.querySelectorAll(".plot"),function(p){p.scrollLeft=p.scrollWidth;});
each(d.querySelectorAll("table[data-sort] thead th"),function(th){th.tabIndex=0;});
d.addEventListener("keydown",function(e){
  if(e.key!=="Enter"&&e.key!==" ")return;
  var th=e.target.closest?e.target.closest("table[data-sort] thead th"):null;
  if(th){e.preventDefault();th.click();}});
var comma=/^(de|es|pt|fr|it|nl)/i.test(d.documentElement.lang||"");
var scales={k:1e3,K:1e3,M:1e6,B:1e9,bn:1e9};
var NUM=new RegExp(/^([+\-\u2212\u2013]?)\s*/.source+
  /(?:[$\u20ac\u00a3\u00a5~\u2248<>\u2264\u2265]{1,2}|[A-Z]{3}\s)?\s*/.source+
  /(\d[\d.,\u00a0\u202f '\u2019]*?)\s*([^\d\s.,][^\d]{0,9})?$/.source);
function num(s){
  var m=NUM.exec(String(s).replace(/^\s+|\s+$/g,""));
  if(!m)return "";
  var t=m[2].replace(/(\d)[\u00a0\u202f '\u2019](?=\d{3}(?!\d))/g,"$1");
  if(!/^[\d.,]+$/.test(t)||/[.,]$/.test(t))return "";
  var dots=t.split(".").length-1,commas=t.split(",").length-1;
  if(dots&&commas){
    var dec=t.lastIndexOf(",")>t.lastIndexOf(".")?",":".";
    if(t.split(dec).length>2)return "";
    t=t.split(dec===","?".":",").join("").replace(dec,".");
  }else if(dots||commas){
    var mark=dots?".":",",grouped=/^\d{1,3}(?:[.,]\d{3})+$/.test(t);
    if(dots+commas>1&&!grouped)return "";
    if(grouped&&(dots+commas>1||mark!==(comma?",":".")))t=t.split(mark).join("");
    else t=t.replace(mark,".");
  }
  var n=parseFloat(t),unit=(m[3]||"").split(/\s+/)[0];
  if(Object.prototype.hasOwnProperty.call(scales,unit))n*=scales[unit];
  if(m[1]&&m[1]!=="+")n=-n;
  return isFinite(n)?String(Number(n.toPrecision(12))):"";}
d.addEventListener("node-field-saved",function(e){
  var el=e.target,v=e.detail&&e.detail.value!=null?String(e.detail.value):"";
  if(!el||!el.classList)return;
  if(el.classList.contains("delta")){
    var sign=/^\s*([+\-\u2212\u2013])?\s*[^\d]*(\d[\d.,]*)/.exec(v),tone="";
    if(sign&&/[1-9]/.test(sign[2]))tone=sign[1]&&sign[1]!=="+"?"down":"up";
    if(tone&&el.getAttribute("data-better")==="lower")tone=tone==="up"?"down":"up";
    el.classList.remove("up","down");if(tone)el.classList.add(tone);
    return;}
  if(el.tagName!=="TD")return;
  if(el.hasAttribute("data-value"))el.setAttribute("data-value",num(v));
  var at=/^(.*\/rows\/)(\d+)\/\d+$/.exec(el.getAttribute("data-at")||""),row=el.parentNode;
  if(!at||!row||!row.cells)return;
  for(var i=0;i<row.cells.length;i++){if(/\S/.test(row.cells[i].textContent))return;}
  var body=row.parentNode,gone=Number(at[2]);
  each(body.querySelectorAll("[data-at]"),function(f){
    var k=f.getAttribute("data-at");if(k.indexOf(at[1])!==0)return;
    var rest=k.slice(at[1].length).split("/");
    if(Number(rest[0])>gone)f.setAttribute("data-at",at[1]+(Number(rest[0])-1)+"/"+rest[1]);});
  body.removeChild(row);});
})();
"""


_SOURCE_ICON: Final[str] = (
    '<li class="icon" aria-hidden="true"><svg width="14" height="14" viewBox="0 0 24 24" '
    'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
    'stroke-linejoin="round"><ellipse cx="12" cy="5" rx="9" ry="3"/>'
    '<path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/><path d="M3 12c0 1.66 4 3 9 3s9-1.34 9-3"/>'
    "</svg></li>"
)


def _sources_html(value: Any) -> str:
    """The row of sources under the summary: where these numbers were read."""
    names = _sources(value)
    if not names:
        return ""
    items = "".join(
        f'<li data-at="/sources/{index}">{shell.esc(name)}</li>' for index, name in enumerate(names)
    )
    return f'<ul class="dash-sources">{_SOURCE_ICON}{items}</ul>'


def render(node: Any) -> str:
    """The dashboard as one self-contained page: title, summary, sections."""
    spec = node.spec if isinstance(node.spec, dict) else {}
    language = str(getattr(node, "language", "") or "en")
    summary = _line(spec.get("summary"), MAX_SUMMARY_CHARS)
    # What the reader can write into in edit mode (`nodes/bridge.py`): every
    # text that is one value of the stored spec. The pointers follow the
    # stored lists, which `normalize` has already folded into sections.
    lead = f'<p class="summary" data-at="/summary">{shell.esc(summary)}</p>' if summary else ""
    lead += _sources_html(spec.get("sources"))
    sections = "".join(
        _section_html(section, language, f"/sections/{index}")
        for index, section in enumerate(shell.as_list(spec.get("sections"), MAX_SECTIONS))
        if isinstance(section, dict)
    )
    page = (
        '<main class="page wide dash">'
        f'<header class="dash-head"><h1 data-at="@title">{shell.esc(node.title)}</h1>{lead}'
        f"{shell.upkeep_meta(node)}</header>"
        f"{sections}"
        "</main>"
    )
    return shell.document(node, body=page, css=_CSS, js=_JS)


# -------------------------------------------------------------------- preview


def _scaled(values: list[float], kind: str) -> list[float]:
    """Up to eight values in 0..1, on the baseline the chart itself would use."""
    if len(values) > PREVIEW_BARS:
        last = len(values) - 1
        values = [values[round(step * last / (PREVIEW_BARS - 1))] for step in range(PREVIEW_BARS)]
    if not values:
        return []
    low, high = min(values), max(values)
    # Bars are measured from zero. A line far above zero shows its movement.
    floor = min(low, 0.0)
    if kind == "line" and 0 < high * 0.5 <= low < high:
        floor = low - (high - low) * 0.25
    span = high - floor
    if span <= 0:
        return [0.0 for _ in values]
    return [round(max(0.0, min(1.0, (value - floor) / span)), 3) for value in values]


def preview(spec: dict[str, Any]) -> dict[str, Any]:
    """The card's view of a dashboard: its first values and its first chart."""
    sections = [
        section
        for section in shell.as_list(spec.get("sections") if isinstance(spec, dict) else None, 99)
        if isinstance(section, dict)
    ]
    metrics = [
        {
            "label": _line(metric.get("label"), MAX_LABEL_CHARS),
            "value": _line(metric.get("value"), MAX_VALUE_CHARS),
        }
        for section in sections
        for metric in shell.as_list(section.get("metrics"), MAX_METRICS)
        if isinstance(metric, dict)
    ]
    charts = [
        parsed
        for section in sections
        for parsed, _ in _drawable(shell.as_list(section.get("charts"), MAX_CHARTS))
    ]
    kind = "bar"
    bars: list[float] = []
    if charts:
        kind = "line" if charts[0]["type"] in ("line", "area") else "bar"
        bars = _scaled([value for value in charts[0]["series"][0][1] if value is not None], kind)
    return {"metrics": metrics[:PREVIEW_METRICS], "bars": bars, "chart": kind}


# -------------------------------------------------------------------- starter


def starter(title: str, language: str) -> dict[str, Any]:
    """A fresh dashboard: one row of values, one chart, one table.

    The page shows the title itself, and the few placeholder words are the
    same in every language, so neither argument changes the content.
    """
    return normalize(
        {
            "summary": "A short summary: what these numbers cover and as of when.",
            "sections": [
                {
                    "metrics": [
                        {"label": "First value", "value": "0"},
                        {"label": "Second value", "value": "0"},
                        {"label": "Third value", "value": "0"},
                    ],
                    "charts": [
                        {
                            "type": "column",
                            "title": "A first chart",
                            "x": ["Mon", "Tue", "Wed", "Thu", "Fri"],
                            "data": [3, 5, 4, 6, 5],
                            "note": "Sample values. Ask the assistant to fill this dashboard.",
                        }
                    ],
                    "tables": [
                        {
                            "columns": ["Item", "Value"],
                            "rows": [["First item", 0], ["Second item", 0]],
                        }
                    ],
                }
            ],
        }
    )


# ---------------------------------------------------------------------- guide

EXAMPLE: Final[dict[str, Any]] = {
    "summary": "Sales through October 2026, from the shop's order export of 1 Nov.",
    "sources": ["Shop order export", "returns.xlsx"],
    "sections": [
        {
            "title": "October",
            "text": "Revenue grew for the **third month**; returns stayed under 4 %.",
            "metrics": [
                {"label": "Revenue", "value": "48.2k €", "delta": "+12 %", "detail": "vs. Sep"},
                {"label": "Orders", "value": "1,204", "delta": "+86"},
            ],
            "charts": [
                {
                    "type": "line",
                    "title": "Revenue per month (k €)",
                    "x": ["Jul", "Aug", "Sep", "Oct"],
                    "series": [
                        {"name": "2026", "data": [36.4, 39.9, 43.1, 48.2]},
                        {"name": "2025", "data": [31, 33.5, 34.2, 37.8]},
                    ],
                },
                {
                    "type": "bar",
                    "title": "Orders by channel, October",
                    "x": ["Shop", "Marketplace", "Retail"],
                    "data": [742, 351, 111],
                },
            ],
            "tables": [
                {
                    "title": "Top products",
                    "columns": ["Product", "Units", "Revenue"],
                    "rows": [["Filter set", 412, "14,420 €"], ["Bottle", 388, "9,700 €"]],
                }
            ],
        }
    ],
}

GUIDE: Final[str] = (
    """\
data: an analysis of the person's data, a dashboard to scan, not read.
Read every source the person names before you write a value: files with your file tools, \
apps and accounts with their tools, prices from the web. Never invent or estimate a figure; \
leave out what you could not read and say so in the summary. No source known: ask.
To keep it current ("keep it updated", "live"), give 'track' on create naming each source \
exactly (path, database, account, tickers), and 'every_minutes'.
spec = {"summary": what and as of when, "sources": [where the numbers were read, a few words \
each, up to 8], "sections": [section, …] (up to 12)}. Top-level "metrics", "charts", "tables" are shorthand for one untitled first section.
section = {"title", "text", "metrics": [metric], "charts": [chart], "tables": [table]}; all \
optional. "text" is one short paragraph (**bold**, *italic*, `code`, [link](https://…)).
metric (up to 8) = {"label": two to four words, "value": the figure with its unit as text, \
"detail": optional, "delta": optional change such as "+12 %" or "−3"}. Colored by its \
sign; "better":"lower" flips it.
chart (up to 8) = {"type": "line"|"area"|"column"|"bar"|"pie"|"donut", "title", "x": \
[labels], "series": [{"name", "data": [numbers]}] (up to 6) or "data": [numbers] for one \
series, "unit", "note" (source or assumption), "value" and "delta" (a headline figure above \
the plot), "stacked": true (column/bar: series on top of each other), "colors": [hex per \
series, or per slice], "wide": true}
- "x" and every "data" have the same length, 2 or more points (bar: at most 24); numbers \
only, null for a gap.
- line or area for a course over time, column for a few periods, bar for named things, pie \
or donut for shares of one whole (one series, at most 12 slices). One unit per chart; two \
measures are two charts.
- Charts sit two per row on a wide window. "wide": true takes the whole row; a chart left \
alone in its row takes it too.
table (up to 4) = {"title", "columns": [names] (up to 12), "rows": [[cell, …]] (up to \
200)}. A cell is text or a number; a column of numbers is right-aligned, and the reader can \
sort by any column.
Order: values first, charts below, a table for the long tail. A title says what is \
shown, with unit and period.
Change one value by its path, e.g. /sections/0/metrics/1/value or \
/sections/0/charts/0/series/0/data.
Example:
"""
    + json.dumps(EXAMPLE, ensure_ascii=False)
)


__all__ = [
    "EXAMPLE",
    "GUIDE",
    "MAX_CHARTS",
    "MAX_METRICS",
    "MAX_ROWS",
    "MAX_SECTIONS",
    "MAX_TABLES",
    "normalize",
    "preview",
    "render",
    "starter",
]
