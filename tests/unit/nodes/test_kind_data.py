"""The ``data`` node type: its spec, its page and its card."""

from __future__ import annotations

import copy
import json
import re
from typing import Any

import pytest

from dodaios.nodes.kinds import data, kind_of
from dodaios.nodes.model import Node
from dodaios.nodes.types import NodeError

SCRIPT = "<script>alert(1)</script>"
BREAKOUT = '"><img src=x onerror=alert(1)>'


def _line_chart(**more: Any) -> dict[str, Any]:
    return {
        "type": "line",
        "title": "Revenue per month",
        "x": ["Jul", "Aug", "Sep", "Oct"],
        "series": [
            {"name": "2026", "data": [36.4, 39.9, 43.1, 48.2]},
            {"name": "2025", "data": [31.0, 33.5, 34.2, 37.8]},
        ],
        **more,
    }


def _bar_chart(**more: Any) -> dict[str, Any]:
    chart = {"type": "bar", "title": "By channel", "x": ["Shop", "Retail"], "data": [742, 111]}
    return {**chart, **more}


FULL: dict[str, Any] = {
    "summary": "Sales through October.",
    "sections": [
        {
            "title": "October",
            "text": "Revenue grew for the **third month**.",
            "metrics": [
                {"label": "Revenue", "value": "48.2k €", "delta": "+12 %", "detail": "vs. Sep"},
                {"label": "Returns", "value": "3.8 %", "delta": "−0.5 pts"},
                {"label": "Orders", "value": 1204},
            ],
            "charts": [_line_chart(wide=True, value="48.2k €", delta="+12 %"), _bar_chart()],
        },
        {
            "title": "Products",
            "tables": [
                {
                    "title": "Top products",
                    "columns": ["Product", "Units", "Revenue", "Launched"],
                    "rows": [
                        ["Filter set", 412, "14,420 €", "2024-03-01"],
                        ["Bottle", 388, "9,700 €", "2025-01-15"],
                        ["Carafe", 97.5, "–", "2025-06-30"],
                    ],
                }
            ],
        },
    ],
}


def _node(spec: dict[str, Any], title: str = "Sales 2026", **more: Any) -> Node:
    return Node(
        id="0123456789ab",
        type="data",
        title=title,
        spec=spec,
        slug="s",
        page_path="p.html",
        created_at=1_700_000_000,
        updated_at=1_700_000_600,
        **more,
    )


_EDIT_MARKS = re.compile(
    r' data-(?:at|src|as|better)="[^"]*"| data-(?:multiline|refresh)\b'
)


def _drawn(html: str) -> str:
    """The page without the marks of the edit mode. Those carry stored values
    as escaped attributes, which are data and never drawn."""
    return _EDIT_MARKS.sub("", html)


def _body(html: str) -> str:
    """What the page DRAWS: without its head (the kit's own styles and scripts
    are not searched) and without the marks of the edit mode."""
    return _drawn(html[html.index("<main") : html.index("</main>")])


# ------------------------------------------------------------------ normalize


def test_normalize_is_idempotent_and_drops_unknown_keys() -> None:
    raw = copy.deepcopy(FULL)
    raw["theme"] = "dark"
    raw["sections"][0]["layout"] = "grid"
    raw["sections"][0]["metrics"][0]["icon"] = "star"
    raw["sections"][0]["charts"][0]["colors"] = ["red"]
    spec = data.normalize(raw)
    assert data.normalize(spec) == spec
    assert set(spec) == {"summary", "sections"}
    first = spec["sections"][0]
    assert set(first) == {"title", "text", "metrics", "charts", "tables"}
    assert first["metrics"][0] == {
        "label": "Revenue", "value": "48.2k €", "detail": "vs. Sep", "delta": "+12 %",
    }
    assert first["metrics"][2] == {"label": "Orders", "value": "1204"}
    chart = first["charts"][0]
    assert chart["wide"] is True and "colors" not in chart
    assert chart["series"][1] == {"name": "2025", "data": [31, 33.5, 34.2, 37.8]}
    assert first["charts"][1]["series"] == [{"name": "By channel", "data": [742, 111]}]
    assert spec["sections"][1]["tables"][0]["rows"][2] == ["Carafe", 97.5, "–", "2025-06-30"]


def test_sources_are_named_once_clipped_and_capped() -> None:
    spec = data.normalize(
        {
            "sources": [" orders.csv ", "Notion: Projects", "ORDERS.CSV", "", 7, None, "x" * 200]
            + [f"Source {n}" for n in range(20)],
            "metrics": [{"label": "A", "value": "1"}],
        }
    )
    sources = spec["sources"]
    assert sources[:3] == ["orders.csv", "Notion: Projects", "7"]
    assert len(sources[3]) <= data.MAX_SOURCE_CHARS
    assert len(sources) == data.MAX_SOURCES
    assert list(spec) == ["summary", "sources", "sections"]
    assert data.normalize(spec) == spec
    # One source may come as a plain string.
    lone = data.normalize({"sources": "My portfolio", "metrics": [{"label": "A", "value": "1"}]})
    assert lone["sources"] == ["My portfolio"]


def test_top_level_parts_become_one_untitled_first_section() -> None:
    spec = data.normalize(
        {
            "metrics": [{"label": "Users", "value": "12"}],
            "charts": _bar_chart(),
            "sections": [{"title": "More", "tables": [{"columns": ["A"], "rows": [["x"]]}]}],
        }
    )
    assert [section["title"] for section in spec["sections"]] == ["", "More"]
    assert spec["sections"][0]["metrics"] == [{"label": "Users", "value": "12"}]
    assert len(spec["sections"][0]["charts"]) == 1
    assert "metrics" not in spec and "charts" not in spec
    assert data.normalize(spec) == spec


def test_lists_are_capped_and_texts_clipped() -> None:
    metric = {"label": "L" * 200, "value": "V" * 200, "detail": "D" * 400, "delta": "+" + "1" * 99}
    table = {
        "title": "T" * 300,
        "columns": [f"C{index}" for index in range(20)],
        "rows": [[f"cell {row} " + "x" * 600] * 20 for row in range(300)],
    }
    section = {
        "title": "S" * 300,
        "text": "word " * 400,
        "metrics": [metric] * 12,
        "charts": [_bar_chart()] * 12,
        "tables": [table] * 7,
    }
    spec = data.normalize({"summary": "s " * 900, "sections": [section] * 20})
    assert len(spec["summary"]) <= data.MAX_SUMMARY_CHARS
    assert len(spec["sections"]) == data.MAX_SECTIONS == 12
    first = spec["sections"][0]
    assert len(first["title"]) <= 120 and len(first["text"]) <= 600
    assert len(first["metrics"]) == data.MAX_METRICS == 8
    assert len(first["charts"]) == data.MAX_CHARTS == 8
    assert len(first["tables"]) == data.MAX_TABLES == 4
    assert len(first["metrics"][0]["label"]) <= 80 and len(first["metrics"][0]["value"]) <= 40
    kept = first["tables"][0]
    assert len(kept["columns"]) == 12 and len(kept["rows"]) == data.MAX_ROWS == 200
    assert all(len(row) == 12 for row in kept["rows"]) and len(kept["rows"][0][0]) <= 300
    assert data.normalize(spec) == spec


def test_table_rows_are_fitted_to_the_columns() -> None:
    spec = data.normalize(
        {
            "tables": [
                {
                    "columns": ["Name", "Count", "Done"],
                    "rows": [
                        ["a", 1, True, "extra"],
                        ["b"],
                        {"name": "c", "COUNT": 3},
                        ["", None, ""],
                        [float("nan"), 2.0, {"no": "cell"}],
                    ],
                }
            ]
        }
    )
    assert spec["sections"][0]["tables"][0]["rows"] == [
        ["a", 1, "yes"],
        ["b", "", ""],
        ["c", 3, ""],
        ["", 2, ""],
    ]


@pytest.mark.parametrize(
    "spec",
    [None, "numbers", [], {}, {"summary": "only words"}, {"sections": [{"title": "Empty"}]}],
)
def test_a_spec_with_nothing_to_show_is_refused(spec: Any) -> None:
    with pytest.raises(NodeError) as raised:
        data.normalize(spec)
    message = str(raised.value)
    assert "'sections'" not in message and '"sections"' in message
    assert message.count(". ") == 0 and message.endswith(".")


@pytest.mark.parametrize(
    "broken",
    [
        {"type": "line", "title": "Uneven", "x": ["a", "b", "c"], "data": [1, 2]},
        {"type": "line", "title": "One point", "x": ["a"], "data": [1]},
        {"type": "line", "title": "Words", "x": ["a", "b"], "data": [1, "many"]},
        {"type": "pie", "title": "Unknown type", "x": ["a", "b"], "data": [1, 2]},
        {"type": "line", "title": "No data", "x": ["a", "b"]},
        {
            "type": "line",
            "title": "Unnamed series",
            "x": ["a", "b"],
            "series": [{"data": [1, 2]}, {"data": [2, 1]}],
        },
    ],
)
def test_a_chart_that_cannot_be_drawn_is_named_with_the_rule(broken: dict[str, Any]) -> None:
    spec = {"sections": [{"charts": [_bar_chart()]}, {"charts": [_bar_chart(), broken]}]}
    with pytest.raises(NodeError) as raised:
        data.normalize(spec)
    message = str(raised.value)
    assert message.startswith(f"Chart 2 in section 2 ({broken['title']!r}) cannot be drawn.")
    assert "same length" in message and "2 or more points" in message and "numbers" in message


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ({"sections": "none"}, "'sections' must be a list of section objects."),
        ({"sections": ["words"]}, "Section 1 must be an object"),
        ({"metrics": "many"}, "Section 1: 'metrics' must be a list of metric objects."),
        ({"metrics": [{"label": "Users"}]}, "Metric 1 in section 1 needs a 'label'"),
        ({"metrics": ["12"]}, "Metric 1 in section 1 must be an object"),
        ({"charts": ["line"]}, "Chart 1 in section 1 must be an object"),
        ({"tables": [{"rows": [[1, 2]]}]}, "Table 1 in section 1 needs 'columns'"),
        ({"tables": [[1, 2]]}, "Table 1 in section 1 must be an object"),
    ],
)
def test_a_part_of_the_wrong_shape_is_refused_by_name(spec: Any, expected: str) -> None:
    with pytest.raises(NodeError, match=re.escape(expected)):
        data.normalize(spec)


def test_starter_and_example_are_valid_specs() -> None:
    starter = data.starter("My numbers", "en")
    assert data.normalize(starter) == starter
    assert '<div class="metrics"' in data.render(_node(starter))
    example = data.normalize(data.EXAMPLE)
    assert data.normalize(example) == example
    assert data.render(_node(example)).count('class="tile') == 2


def test_guide_is_compact_and_carries_the_example() -> None:
    # The grammar plus the rule that an analysis is read from real sources.
    assert len(data.GUIDE) <= 3_200
    assert json.dumps(data.EXAMPLE, ensure_ascii=False) in data.GUIDE
    assert "Never invent" in data.GUIDE and "'track'" in data.GUIDE
    assert data.normalize(data.EXAMPLE)["sources"]
    assert kind_of("data").guide == data.GUIDE
    assert kind_of("dashboard").render is data.render


# --------------------------------------------------------------------- render


def test_a_small_dashboard_renders_a_complete_page() -> None:
    node = _node(data.normalize({"metrics": [{"label": "Users", "value": "12"}]}))
    html = data.render(node)
    assert html == data.render(node)
    assert html.startswith("<!doctype html>") and html.rstrip().endswith("</html>")
    assert "<title>Sales 2026</title>" in html
    body = _body(html)
    assert body.startswith('<main class="page wide dash">')
    assert "<h1>Sales 2026</h1>" in body
    assert '<div class="label">Users</div><div class="value">12</div>' in body
    assert "<h2>" not in body and 'class="summary"' not in body
    assert "dash-grid" not in body and "<table" not in body
    assert '<p class="node-meta">' not in body


def test_a_full_dashboard_shows_every_part() -> None:
    node = _node(data.normalize(FULL))
    html = data.render(node)
    assert html == data.render(node)
    body = _body(html)
    assert '<p class="summary">Sales through October.</p>' in body
    assert body.count('<section class="section">') == 2
    assert "<h2>October</h2>" in body and "<h2>Products</h2>" in body
    assert '<p class="dash-text">Revenue grew for the <strong>third month</strong>.</p>' in body
    assert '<div class="metrics" style="--n:3">' in body
    assert body.count('<figure class="card chart split">') == 2
    assert '<div class="plot"><svg ' in body and '<div class="bars">' in body
    assert '<div class="legend">' in body
    assert "<h3>Top products</h3>" in body
    assert '<table class="table" data-sort>' in body


def test_the_sources_are_named_under_the_summary() -> None:
    spec = data.normalize({**FULL, "sources": ["orders.csv", "Notion: Projects"]})
    body = _body(data.render(_node(spec)))
    row = body[body.index('<ul class="dash-sources">') :]
    assert body.index('class="summary"') < body.index('<ul class="dash-sources">')
    assert '<li class="icon" aria-hidden="true"><svg ' in row
    assert "<li>orders.csv</li><li>Notion: Projects</li></ul>" in row
    # Without sources there is no row.
    assert "dash-sources" not in _body(data.render(_node(data.normalize(FULL))))


def test_deltas_take_the_kit_tone_and_no_color_of_their_own() -> None:
    body = _body(data.render(_node(data.normalize(FULL))))
    assert '<span class="delta up">+12 %</span> <span>vs. Sep</span>' in body
    assert '<span class="delta down">−0.5 pts</span>' in body
    assert '<div class="detail up">+12 %</div>' in body
    assert "color:" not in body and "#" not in re.sub(r"&#\d+;", "", body)


def test_charts_sit_two_per_row_and_a_lone_chart_takes_the_row() -> None:
    def tiles(charts: list[dict[str, Any]]) -> list[str]:
        body = _body(data.render(_node(data.normalize({"charts": charts}))))
        return re.findall(r'<div class="(tile(?: wide)?)">', body)

    assert tiles([_bar_chart()]) == ["tile wide"]
    assert tiles([_bar_chart(), _bar_chart()]) == ["tile", "tile"]
    assert tiles([_bar_chart(), _bar_chart(), _bar_chart()]) == ["tile", "tile", "tile wide"]
    assert tiles([_bar_chart(wide=True), _bar_chart(), _bar_chart()]) == [
        "tile wide", "tile", "tile",
    ]
    assert tiles([_bar_chart(), _bar_chart(wide=True), _bar_chart()]) == ["tile wide"] * 3


def test_a_column_of_numbers_is_right_aligned_and_sorts_by_value() -> None:
    body = _body(data.render(_node(data.normalize(FULL))))
    assert '<th scope="col">Product</th>' in body
    assert '<th scope="col" class="n">Units</th>' in body
    assert '<th scope="col" class="n">Revenue</th>' in body
    assert '<th scope="col">Launched</th>' in body
    assert '<td class="n" data-value="412">412</td>' in body
    assert '<td class="n" data-value="97.5">97.5</td>' in body
    assert '<td class="n" data-value="14420">14,420 €</td>' in body
    assert '<td class="n" data-value="">–</td>' in body
    assert "<td>2024-03-01</td>" in body


def test_numbers_follow_the_page_language() -> None:
    spec = data.normalize(
        {"tables": [{"columns": ["Item", "Sum"], "rows": [["a", 1234.5], ["b", "1.234,50 €"]]}]}
    )
    body = _body(data.render(_node(spec, language="de")))
    assert '<td class="n" data-value="1234.5">1.234</td>' in body
    assert '<td class="n" data-value="1234.5">1.234,50 €</td>' in body


def test_a_kept_current_dashboard_shows_the_upkeep_line() -> None:
    node = _node(data.normalize(FULL), track="Sales from the shop export.", refreshing=True)
    html = data.render(node)
    assert '<p class="node-meta"><span class="live on">' in html
    assert 'data-updated="1700000600"' in html and "Intl.RelativeTimeFormat" in html


def test_the_page_follows_the_theme_and_carries_no_network_or_storage() -> None:
    html = data.render(_node(data.normalize(FULL), language="de"))
    assert '<html lang="de">' in html
    assert "data-theme" in html and "--bg:" in html
    for forbidden in ("<link", "@import", "url(", 'src="', "fetch(", "XMLHttpRequest"):
        assert forbidden not in _drawn(html)
    assert "localStorage" not in html and "sessionStorage" not in html
    assert "prefers-reduced-motion" in html and "@media print" in html
    assert 'tabindex="0"' in html and '"keydown"' in html


def test_render_survives_a_spec_that_skipped_normalize() -> None:
    odd = {
        "summary": 7,
        "sections": [
            "words",
            {"metrics": ["x", {"label": "A", "value": "1"}], "charts": [{"type": "line"}, 3]},
            {"tables": [{"columns": ["A", "B"], "rows": ["x", ["only one"], [None, True]]}]},
        ],
    }
    body = _body(data.render(_node(odd)))
    assert '<div class="value">1</div>' in body and "dash-grid" not in body
    assert "<td>only one</td><td></td>" in body
    card = data.preview(odd)
    assert card == {"metrics": [{"label": "A", "value": "1"}], "bars": [], "chart": "bar"}
    assert "<h1>Sales 2026</h1>" in _body(data.render(_node({})))


# ------------------------------------------------------------------- escaping


@pytest.mark.parametrize("payload", [SCRIPT, BREAKOUT])
def test_no_text_field_reaches_the_page_unescaped(payload: str) -> None:
    chart = {
        "type": "line",
        "title": payload,
        "note": payload,
        "unit": payload,
        "value": payload,
        "delta": payload,
        "x": [payload, f"2 {payload}"],
        "series": [{"name": payload, "data": [1, 2]}, {"name": f"B {payload}", "data": [2, 1]}],
    }
    spec = data.normalize(
        {
            "summary": payload,
            "sources": [payload],
            "sections": [
                {
                    "title": payload,
                    "text": f"{payload} **{payload}** `{payload}` [{payload}](https://a.example/)",
                    "metrics": [
                        {"label": payload, "value": payload, "detail": payload, "delta": payload}
                    ],
                    "charts": [
                        chart,
                        {**chart, "type": "bar", "series": [{"name": payload, "data": [1, 2]}]},
                        {**chart, "type": "column", "series": [{"name": payload, "data": [1, 2]}]},
                    ],
                    "tables": [
                        {
                            "title": payload,
                            "columns": [payload, f"B {payload}"],
                            "rows": [[payload, f"[{payload}](javascript:alert(1))"]],
                        }
                    ],
                }
            ],
        }
    )
    node = _node(spec, title=payload, track="x", note=payload, language=payload)
    html = data.render(node)
    assert payload not in html
    assert "<script>alert" not in html
    assert "<img src=x" not in html
    assert "onerror=alert(1)>" not in html
    assert 'href="javascript:' not in html
    # The one line chart, and the icon in front of the sources.
    assert _body(html).count("<svg ") == 2


# -------------------------------------------------------------------- preview


def test_preview_shows_the_first_values_and_the_first_chart() -> None:
    card = data.preview(data.normalize(FULL))
    assert set(card) == {"metrics", "bars", "chart"}
    assert card["metrics"] == [
        {"label": "Revenue", "value": "48.2k €"},
        {"label": "Returns", "value": "3.8 %"},
        {"label": "Orders", "value": "1204"},
    ]
    assert card["chart"] == "line"
    assert len(card["bars"]) == 4 and card["bars"][-1] == 1.0
    assert all(isinstance(value, float) and 0.0 <= value <= 1.0 for value in card["bars"])
    assert card["bars"] == sorted(card["bars"])


def test_preview_is_bounded_and_scaled() -> None:
    many = data.normalize(
        {
            "metrics": [{"label": f"M{index}", "value": str(index)} for index in range(6)],
            "charts": [
                {"type": "column", "x": [str(i) for i in range(30)], "data": list(range(30))},
                _line_chart(),
            ],
        }
    )
    card = data.preview(many)
    assert len(card["metrics"]) == 3 and card["chart"] == "bar"
    assert len(card["bars"]) == 8 and card["bars"][0] == 0.0 and card["bars"][-1] == 1.0
    below = data.preview(
        data.normalize({"charts": [{"type": "bar", "x": ["a", "b", "c"], "data": [-2, 0, 2]}]})
    )
    assert below["bars"] == [0.0, 0.5, 1.0]
    # A gap is left out; a line that starts near zero is measured from zero.
    gaps = data.preview(
        data.normalize({"charts": [{"type": "area", "x": ["a", "b", "c"], "data": [2, None, 10]}]})
    )
    assert gaps == {"metrics": [], "bars": [0.2, 1.0], "chart": "line"}
    # A line far above zero keeps its movement instead of reading as flat.
    steady = {"type": "line", "x": ["a", "b", "c"], "data": [980, 990, 1000]}
    high = data.preview(data.normalize({"charts": [steady]}))
    assert high["bars"] == [0.2, 0.6, 1.0]
    flat = data.preview(
        data.normalize({"charts": [{"type": "line", "x": ["a", "b"], "data": [0, 0]}]})
    )
    assert flat["bars"] == [0.0, 0.0]


def test_preview_without_a_chart_draws_no_bars() -> None:
    card = data.preview(data.normalize({"metrics": [{"label": "Users", "value": "12"}]}))
    assert card == {"metrics": [{"label": "Users", "value": "12"}], "bars": [], "chart": "bar"}
    assert data.preview({}) == {"metrics": [], "bars": [], "chart": "bar"}


def test_a_falling_figure_can_be_the_good_news() -> None:
    metrics = [
        {"label": "Return rate", "value": "3.1 %", "delta": "−0.7 pts", "better": "lower"},
        {"label": "Revenue", "value": "48k", "delta": "−2 %"},
        {"label": "Orders", "value": "12", "better": "lower"},
    ]
    spec = data.normalize({"metrics": metrics})
    kept = spec["sections"][0]["metrics"]

    assert kept[0]["better"] == "lower"
    assert "better" not in kept[1]
    assert "better" not in kept[2]  # nothing to color without a delta
    assert data.normalize(spec) == spec
    page = _body(data.render(_node(spec)))
    assert '<span class="delta up">−0.7 pts</span>' in page
    assert '<span class="delta down">−2 %</span>' in page


# ------------------------------------------------------------------ edit mode


def _fields(spec: dict[str, Any], **more: Any) -> dict[str, Any]:
    """What the page offers to edit, checked against the spec, by path."""
    from tests.unit.nodes.editable import check_editable

    node = _node(spec, **more)
    fields = check_editable(data.render(node), spec, node.title)
    paths = [field.at for field in fields]
    assert len(paths) == len(set(paths)), "a path is offered twice"
    return {field.at: field for field in fields}


@pytest.mark.parametrize(
    "spec",
    [data.normalize(data.EXAMPLE), data.starter("My numbers", "en"), data.normalize(FULL)],
    ids=["example", "starter", "full"],
)
def test_every_text_offered_for_editing_is_the_value_the_spec_holds(spec: dict[str, Any]) -> None:
    fields = _fields(spec)
    assert "@title" in fields
    for index in range(len(spec.get("sources", []))):
        assert f"/sources/{index}" in fields
    # Every metric, column and cell the spec holds is offered.
    for s, section in enumerate(spec["sections"]):
        for m, metric in enumerate(section["metrics"]):
            for key in metric:
                if key != "better":
                    assert f"/sections/{s}/metrics/{m}/{key}" in fields
        for t, table in enumerate(section["tables"]):
            for c in range(len(table["columns"])):
                assert f"/sections/{s}/tables/{t}/columns/{c}" in fields
            for r, row in enumerate(table["rows"]):
                for c in range(len(row)):
                    assert f"/sections/{s}/tables/{t}/rows/{r}/{c}" in fields


def test_a_small_dashboard_offers_exactly_its_texts() -> None:
    spec = data.normalize(
        {
            "summary": "As of today.",
            "metrics": [{"label": "Users", "value": "12", "delta": "+2", "detail": "vs. May"}],
            "charts": [_bar_chart()],
            "sections": [
                {
                    "title": "Detail",
                    "text": "Plain words.",
                    "tables": [{"title": "List", "columns": ["Name", "Count"], "rows": [["a", 3]]}],
                }
            ],
        }
    )
    fields = _fields(spec)
    assert set(fields) == {
        "@title",
        "/summary",
        "/sections/0/metrics/0/label",
        "/sections/0/metrics/0/value",
        "/sections/0/metrics/0/delta",
        "/sections/0/metrics/0/detail",
        "/sections/1/title",
        "/sections/1/text",
        "/sections/1/tables/0/title",
        "/sections/1/tables/0/columns/0",
        "/sections/1/tables/0/columns/1",
        "/sections/1/tables/0/rows/0/0",
        "/sections/1/tables/0/rows/0/1",
    }
    # Plain texts are edited as they are drawn, so they carry no source.
    assert all(fields[path].src is None for path in fields if "/rows/0/1" not in path)
    assert not any(field.multiline or field.refresh for field in fields.values())


def test_a_chart_is_not_offered_for_editing() -> None:
    page = data.render(_node(data.normalize(FULL)))
    for figure in re.findall(r"<figure.*?</figure>", page, flags=re.S):
        assert "data-at=" not in figure


def test_texts_with_inline_marks_carry_the_stored_string() -> None:
    spec = data.normalize(
        {
            "sections": [
                {
                    "text": "Revenue grew for the **third month** (see [the shop](https://a.example/)).",
                    "tables": [{"columns": ["Item"], "rows": [["`SKU-1` *new*"], ["plain"]]}],
                }
            ]
        }
    )
    fields = _fields(spec)
    text = fields["/sections/0/text"]
    assert text.src == spec["sections"][0]["text"]
    assert text.text == "Revenue grew for the third month (see the shop)."
    assert fields["/sections/0/tables/0/rows/0/0"].src == "`SKU-1` *new*"
    assert fields["/sections/0/tables/0/rows/1/0"].src is None


def test_a_number_cell_is_edited_as_a_number_and_a_text_cell_as_text() -> None:
    spec = data.normalize(FULL)
    fields = _fields(spec, language="de")
    units = fields["/sections/1/tables/0/rows/0/1"]
    assert (units.kind, units.src) == ("number", "412")
    half = fields["/sections/1/tables/0/rows/2/1"]
    assert (half.kind, half.src) == ("number", "97.5")
    # "14,420 €" is text in the spec, however much it reads as a number.
    revenue = fields["/sections/1/tables/0/rows/0/2"]
    assert (revenue.kind, revenue.src, revenue.text) == ("text", None, "14,420 €")
    page = data.render(_node(spec))
    assert re.search(
        r'<td class="n" data-value="412" data-at="/sections/1/tables/0/rows/0/1" '
        r'data-src="412" data-as="number">412</td>',
        page,
    )
    assert data._number_source(1e-07) == "0.0000001"
    assert data._number_source(1e20) == "100000000000000000000"


def test_a_delta_carries_what_the_page_needs_to_color_it_again() -> None:
    spec = data.normalize(
        {
            "metrics": [
                {"label": "Return rate", "value": "3.1 %", "delta": "−0.7 pts", "better": "lower"},
                {"label": "Revenue", "value": "48k", "delta": "−2 %"},
            ]
        }
    )
    page = data.render(_node(spec))
    assert (
        '<span class="delta up" data-better="lower" data-at="/sections/0/metrics/0/delta">'
        "−0.7 pts</span>"
    ) in page
    assert '<span class="delta down" data-at="/sections/0/metrics/1/delta">−2 %</span>' in page
    # The page recolors it on save instead of being drawn again.
    assert '"node-field-saved"' in page
    assert not any(field.refresh for field in _fields(spec).values())


def test_a_section_of_words_alone_is_drawn_again_after_an_edit() -> None:
    spec = data.normalize(
        {
            "metrics": [{"label": "Users", "value": "12"}],
            "sections": [{"title": "Note", "text": "Only words here."}],
        }
    )
    fields = _fields(spec)
    # Emptied, it would be dropped and move the sections below it up.
    assert fields["/sections/1/title"].refresh and fields["/sections/1/text"].refresh
    assert not fields["/sections/0/metrics/0/value"].refresh


def test_hostile_texts_reach_the_edit_marks_escaped_only() -> None:
    from html.parser import HTMLParser

    spec = data.normalize(
        {
            "sections": [
                {
                    "text": f"**{SCRIPT}** {BREAKOUT}",
                    "tables": [{"columns": [BREAKOUT], "rows": [[f"`{SCRIPT}`"]]}],
                }
            ]
        }
    )
    page = data.render(_node(spec))
    assert SCRIPT not in page and BREAKOUT not in page
    assert "data-src=\"**&lt;script&gt;alert(1)&lt;/script&gt;** &quot;&gt;&lt;img" in page
    fields = _fields(spec)
    assert fields["/sections/0/text"].src == f"**{SCRIPT}** {BREAKOUT}"
    assert fields["/sections/0/tables/0/rows/0/0"].src == f"`{SCRIPT}`"

    class Tags(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.found: list[tuple[str, list[tuple[str, str | None]]]] = []

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            self.found.append((tag, attrs))

    reader = Tags()
    reader.feed(page)
    assert [tag for tag, _ in reader.found].count("script") == page.count("<script>")
    assert [tag for tag, _ in reader.found if tag == "img"] == []
    for _, attrs in reader.found:
        assert not [key for key, _ in attrs if key.startswith("on")]
