"""The blocks a report carries beyond running text, pinned by their shape."""

from __future__ import annotations

import json

from dodaios.artifacts.report import render_body, render_html
from dodaios.artifacts.report_blocks import (
    format_number,
    parse_chart,
    render_chart,
    render_metrics,
    upgrade_blocks,
)

LINE = {
    "type": "line",
    "title": "Stars",
    "unit": "Stars",
    "note": "daily snapshots",
    "value": "287",
    "delta": "+37 in 5 days",
    "x": ["24 Oct", "25 Oct", "26 Oct"],
    "series": [{"name": "Stars", "data": [250, 255, 287]}],
}


def _fence(kind: str, source: str) -> str:
    return f"```{kind}\n{source}\n```\n"


def test_a_chart_fence_becomes_a_chart_card_whose_points_answer() -> None:
    body = render_body("## Course\n\n" + _fence("chart", json.dumps(LINE)), "en").html
    assert '<figure class="card chart">' in body and "<svg" in body
    assert "language-chart" not in body
    assert "<h3>Stars</h3>" in body
    assert 'class="value">287<' in body and 'class="detail up">+37 in 5 days<' in body
    assert '<p class="note">daily snapshots</p>' in body
    # One hit area per point, each with the full statement, reachable by keyboard.
    assert body.count('class="hit"') == 3
    assert 'data-tip="26 Oct: 287 Stars" tabindex="0"' in body


def test_numbers_that_do_not_line_up_stay_a_code_block() -> None:
    broken = dict(LINE, series=[{"name": "Stars", "data": [1, 2]}])
    body = render_body(_fence("chart", json.dumps(broken)), "en").html
    assert "language-chart" in body and "<svg" not in body
    assert parse_chart("not json") is None
    assert parse_chart(json.dumps(dict(LINE, type="radar"))) is None
    seven = [{"name": str(n), "data": [1, 2, 3]} for n in range(7)]
    assert parse_chart(json.dumps(dict(LINE, series=seven))) is None


def test_one_series_of_columns_is_labelled_and_marks_its_largest() -> None:
    spec = parse_chart(json.dumps({"type": "column", "x": ["a", "b", "c"], "data": [4, 76, 17]}))
    assert spec is not None
    html = render_chart(spec, "en")
    assert html.count("data-tip=") == 3
    assert '<div class="col is-key" style="--v:100" data-tip="b: 76"' in html
    assert "<svg" not in html


def test_bars_compare_named_things_and_two_series_get_a_legend() -> None:
    bars = parse_chart(
        json.dumps({"type": "bar", "unit": "%", "x": ["Reddit", "X"], "data": [64, 9]})
    )
    assert bars is not None
    assert 'class="bar is-key" style="--v:100" data-tip="Reddit: 64%"' in render_chart(bars, "en")
    two = parse_chart(
        json.dumps(
            {
                "type": "line",
                "x": ["Mon", "Tue", "Wed"],
                "series": [
                    {"name": "Views", "data": [562, 993, None]},
                    {"name": "Clones", "data": [219, 552, 429]},
                ],
            }
        )
    )
    assert two is not None
    html = render_chart(two, "en")
    assert '<div class="legend">' in html and "--c:var(--s2)" in html
    assert 'data-tip="Tue — Views: 993; Clones: 552"' in html
    assert "Wed — Views: –; Clones: 429" in html


def test_numbers_are_written_the_way_the_page_language_writes_them() -> None:
    assert format_number(1234.5, "de") == "1.234"
    assert format_number(12.5, "de") == "12,5"
    assert format_number(12.5, "en") == "12.5"
    assert format_number(-3, "en") == "−3"


def test_chart_text_is_escaped() -> None:
    spec = parse_chart(
        json.dumps({"type": "bar", "title": "<b>x</b>", "x": ['a"><script>', "b"], "data": [1, 2]})
    )
    assert spec is not None
    html = render_chart(spec, "en")
    assert "<script>" not in html and "<b>x</b>" not in html


def test_a_metrics_fence_becomes_the_metric_row() -> None:
    html = render_metrics("366 | GitHub stars | early November\n130 | Forks\n")
    assert html is not None
    assert html.count('class="metric"') == 2
    assert '<div class="detail">early November</div>' in html
    assert render_metrics("only one field") is None
    body = render_body(_fence("metrics", "1 | <i>a</i>"), "en").html
    assert '<div class="metrics">' in body and "<i>a</i>" not in body


def test_a_quote_with_a_tone_marker_becomes_a_callout() -> None:
    body = render_body("> [!WARNING]\n> **Hard rule** No run without a limit.\n", "en").html
    assert '<div class="callout warn">' in body
    assert '<strong class="lead">Hard rule</strong>' in body
    assert "[!WARNING]" not in body and "<blockquote>" not in body
    # A blank line after the marker leaves no empty paragraph behind.
    spaced = render_body("> [!TIP]\n>\n> **Done** Billing works.\n", "en").html
    assert '<div class="callout good"><p><strong class="lead">Done</strong>' in spaced
    assert "<p></p>" not in spaced
    # A quote without a marker stays a quote: reports quote mails.
    assert "<blockquote>" in render_body("> said by someone\n", "en").html


def test_a_list_of_links_becomes_the_source_list() -> None:
    body = render_body(
        "- [Alpha pricing](https://www.example.org/pricing)\n"
        "- [Beta cloud](https://hub.example.com/blog?a=1&b=2)\n",
        "en",
    ).html
    assert '<ol class="links">' in body
    assert '<span class="site">example.org</span>' in body
    assert '<span class="site">hub.example.com</span>' in body
    mixed = render_body("- [Alpha](https://example.org)\n- plain point\n", "en").html
    assert 'class="links"' not in mixed


def test_a_numbered_list_of_titled_points_becomes_steps() -> None:
    body = render_body(
        "1. **Account and billing:** login, checkout.\n2. **Metering** – every run has a limit.\n",
        "en",
    ).html
    assert '<ol class="steps">' in body
    assert "<h3>Account and billing</h3><p>login, checkout.</p>" in body
    plain = render_body("1. first\n2. second\n", "en").html
    assert 'class="steps"' not in plain
    bullets = render_body("- **A:** x\n- **B:** y\n", "en").html
    assert 'class="steps"' not in bullets


def test_upgrade_leaves_ordinary_html_alone() -> None:
    html = "<p>text</p><ul>\n<li>a</li>\n<li>b</li>\n</ul><pre><code>x</code></pre>"
    assert upgrade_blocks(html) == html


def test_a_report_page_opens_with_name_summary_and_contents() -> None:
    markdown = "".join(f"## Part {n}\n\ntext {n}\n\n" for n in range(1, 5))
    page = render_html(
        title="Plan", summary="The gist.", markdown=markdown, language="de", created_at=0.0
    )
    assert '<main class="page"><h1>Plan</h1><p class="summary">The gist.</p>' in page
    assert '<nav class="toc" aria-label="Auf dieser Seite">' in page
    assert '<a href="#part-3">Part 3</a>' in page and '<h2 id="part-3">Part 3</h2>' in page
    for gone in ("masthead", "eyebrow", "colophon", "gigi"):
        assert gone not in page
    # Three sections are few enough to see at once: no contents box.
    short = render_html(
        title="Plan", summary="", markdown="## A\n\nx\n\n## B\n\ny\n", language="en", created_at=0.0
    )
    assert '<nav class="toc"' not in short and 'class="summary"' not in short
