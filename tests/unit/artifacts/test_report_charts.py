"""The chart kinds beyond the chat's: pie, donut, stacked columns and bars,
and a chart's own colours (``dodaios/artifacts/report_blocks.py``)."""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

from dodaios.artifacts.design_guide import THEME_CSS
from dodaios.artifacts.report import render_body
from dodaios.artifacts.report_blocks import MAX_SLICES, parse_chart, render_chart

SHARES = {"type": "pie", "title": "Channels", "x": ["Web", "Shop", "Phone"], "data": [50, 30, 20]}
TWO = [{"name": "North", "data": [3, 4, -1]}, {"name": "South", "data": [5, None, 2]}]


def _parse(raw: dict[str, Any]) -> dict[str, Any]:
    spec = parse_chart(json.dumps(raw))
    assert spec is not None, raw
    return spec


def test_every_chart_says_whether_it_stacks_and_names_a_colour_per_slot() -> None:
    line = _parse({"type": "line", "x": ["a", "b"], "data": [1, 2]})
    assert line["stacked"] is False and line["colors"] == [""]
    pie = _parse(SHARES)
    assert pie["type"] == "pie" and pie["colors"] == ["", "", ""]
    assert _parse(dict(SHARES, type="doughnut"))["type"] == "donut"


def test_a_pie_draws_one_slice_per_share_with_a_legend_of_values_and_shares() -> None:
    html = render_chart(_parse(SHARES), "en")
    assert '<div class="pie">' in html and html.count('class="slice"') == 3
    assert 'data-tip="Web: 50 (50%)" tabindex="0"' in html
    assert '<li><i style="--c:var(--s1)"></i><span>Web</span><b>50</b>' in html
    assert '<span class="share">30%</span>' in html
    assert 'class="total"' not in html  # only a donut names its total
    # The shares close the circle: the last slice ends where the first began.
    paths = re.findall(r'd="([^"]+)"', html)
    assert paths[0].split(" L")[1].split(" ")[0] == "120.00,2.00"
    assert paths[-1].split(" ")[-2] == "120.00,2.00"


def test_a_donut_has_a_hole_and_says_its_total() -> None:
    html = render_chart(_parse(dict(SHARES, type="donut", unit="%")), "de")
    assert '<text class="total" x="120" y="127" text-anchor="middle">100%</text>' in html
    # A ring segment: two arcs, the inner one drawn back.
    first = re.search(r'<path class="slice" d="([^"]+)"', html)
    assert first is not None and first.group(1).count("A") == 2


def test_a_gap_leaves_its_slice_out_and_one_slice_is_a_whole_circle() -> None:
    html = render_chart(_parse(dict(SHARES, data=[50, None, 0])), "en")
    assert html.count('class="slice"') == 1 and "<circle" in html
    assert html.count("<li>") == 1


@pytest.mark.parametrize(
    "change",
    [
        {"data": [5, -1, 2]},  # no negative share
        {"data": [0, 0, None]},  # nothing to share
        {"series": TWO},  # one series only
        {"x": [str(n) for n in range(MAX_SLICES + 1)], "data": list(range(1, MAX_SLICES + 2))},
    ],
)
def test_a_pie_that_cannot_be_read_stays_unparsed(change: dict[str, Any]) -> None:
    assert parse_chart(json.dumps({**SHARES, **change})) is None


def test_stacked_columns_pile_their_series_and_say_each_total() -> None:
    spec = _parse({"type": "column", "stacked": True, "x": ["Q1", "Q2", "Q3"], "series": TWO})
    assert spec["stacked"] is True
    html = render_chart(spec, "en")
    assert "<svg" in html and html.count('class="colbar"') == 5  # the gap draws nothing
    # Stacked bars share one x and one width per label.
    xs = re.findall(r'<rect class="colbar" x="([\d.]+)"', html)
    assert len(set(xs)) == 3
    assert 'data-tip="Q1 — North: 3; South: 5 (8)"' in html
    grouped = render_chart(_parse({"type": "column", "x": ["Q1", "Q2", "Q3"], "series": TWO}), "en")
    assert len(set(re.findall(r'<rect class="colbar" x="([\d.]+)"', grouped))) == 5


def test_stacked_bars_are_rows_of_parts_with_their_total() -> None:
    spec = _parse({"type": "bar", "stacked": True, "x": ["Ann", "Bo", "Cy"], "series": TWO})
    html = render_chart(spec, "en")
    assert html.count('<div class="bar stacked">') == 3 and html.count('<i style="--v:') == 6
    assert "<b>8</b>" in html and 'data-tip="Bo · South: –"' in html
    assert '<div class="legend">' in html


def test_stacked_is_ignored_where_nothing_can_stack() -> None:
    assert (
        _parse({"type": "line", "stacked": True, "x": ["a", "b"], "data": [1, 2]})["stacked"]
        is False
    )
    assert (
        _parse({"type": "column", "stacked": "yes", "x": ["a", "b"], "data": [1, 2]})["stacked"]
        is False
    )


def test_a_charts_own_colours_replace_the_kit_slots_and_bad_ones_are_dropped() -> None:
    spec = _parse(
        {
            "type": "line",
            "x": ["a", "b"],
            "series": [{"name": "N", "data": [1, 2]}, {"name": "S", "data": [2, 1]}],
            "colors": ["#ff8800", "red"],
        }
    )
    assert spec["colors"] == ["#FF8800", ""]
    html = render_chart(spec, "en")
    assert '<i style="--c:#FF8800"></i>N' in html and '<i style="--c:var(--s2)"></i>S' in html
    pie = render_chart(_parse(dict(SHARES, colors=["", "#00aa00"])), "en")
    assert 'style="--c:#00AA00" data-tip="Shop' in pie
    columns = render_chart(
        _parse({"type": "column", "x": ["a", "b"], "data": [1, 2], "colors": ["#123456"]}), "en"
    )
    assert "--c:#123456" in columns


def test_slices_past_the_sixth_get_a_lighter_tell_not_a_repeat() -> None:
    labels = [f"P{n}" for n in range(8)]
    html = render_chart(_parse({"type": "pie", "x": labels, "data": [1] * 8}), "en")
    assert "color-mix(in srgb, var(--s1) 55%, var(--bg))" in html
    assert "color-mix(in srgb, var(--s2) 55%, var(--bg))" in html


def test_a_fenced_pie_in_a_report_becomes_a_chart_card() -> None:
    body = render_body("```chart\n" + json.dumps(SHARES) + "\n```\n", "en").html
    assert '<figure class="card chart"><h3>Channels</h3><div class="pie">' in body


def test_the_kit_styles_slices_stacks_and_the_pie_legend() -> None:
    for rule in (".chart .slice{", ".pie{", ".pie li{", ".bar.stacked .stack{", ".chart .total{"):
        assert rule in THEME_CSS
