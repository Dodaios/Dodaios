"""The node type ``slides``: the deck grammar, its bounds and the rendered player."""

from __future__ import annotations

import json
import re
from dataclasses import replace
from html.parser import HTMLParser
from typing import Any

import pytest

from dodaios.nodes.kinds import kind_of
from dodaios.nodes.kinds.slides import (
    EXAMPLE,
    GUIDE,
    LAYOUTS,
    MAX_SLIDES,
    normalize,
    preview,
    render,
    starter,
)
from dodaios.nodes.model import Node
from dodaios.nodes.types import NodeError
from tests.unit.nodes.editable import check_editable, editable_fields

PIXEL = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGBg"
    "AAAABQABh6FO1AAAAABJRU5ErkJggg=="
)
CHART = {
    "type": "line",
    "x": ["Jan", "Feb", "Mar"],
    "series": [{"name": "Users", "data": [10, 14, 21]}],
}
TABLE = {"columns": ["Plan", "Price"], "rows": [["Solo", "9 €"], ["Team", "29 €"]]}
SCRIPT = "<script>alert(1)</script>"
BREAKOUT = '"><img src=x onerror=alert(1)>'


def _node(spec: Any, title: str = "Quarterly review", language: str = "en") -> Node:
    return Node(
        id="0123456789ab",
        type="slides",
        title=title,
        spec=normalize(spec),
        slug="s",
        page_path="p.html",
        created_at=1_700_000_000.0,
        updated_at=1_700_000_600.0,
        language=language,
    )


class _Markup(HTMLParser):
    """What a browser would make of a page: its tags, attributes and scripts."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[str] = []
        self.attributes: set[str] = set()
        self.image_sources: list[str] = []
        self.scripts: list[str] = []
        self._in_script = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(tag)
        self.attributes.update(name for name, _ in attrs)
        if tag == "img":
            self.image_sources.extend(value or "" for name, value in attrs if name == "src")
        self._in_script = tag == "script"

    def handle_endtag(self, tag: str) -> None:
        self._in_script = False

    def handle_data(self, data: str) -> None:
        if self._in_script:
            self.scripts.append(data)


def _parsed(html: str) -> _Markup:
    markup = _Markup()
    markup.feed(html)
    markup.close()
    return markup


_EDIT_MARKS = re.compile(r' data-(?:at|src)="[^"]*"| data-(?:multiline|refresh)\b')


def _drawn(html: str) -> str:
    """What the page DRAWS: the deck without the page's head and scripts, and
    without the marks of the edit mode (``data-src`` carries a stored text as an
    escaped attribute, which is data and never drawn)."""
    start = html.index('<div class="dk"')
    return _EDIT_MARKS.sub("", html[start : html.index("<script>", start)])


def _every_layout(text: str = "Text") -> dict[str, Any]:
    """A deck with one slide per layout, the same text in every text field."""
    chart = {
        "type": "column",
        "title": text,
        "note": text,
        "unit": text[:12],
        "x": [text, f"{text} 2"],
        "series": [{"name": text, "data": [1, 2]}, {"name": f"{text} b", "data": [2, 3]}],
    }
    return {
        "slides": [
            {"layout": "title", "kicker": text, "title": text, "subtitle": text, "notes": text},
            {"layout": "section", "kicker": text, "title": text, "subtitle": text},
            {"layout": "bullets", "kicker": text, "title": text, "text": text, "bullets": [text]},
            {
                "layout": "columns",
                "title": text,
                "columns": [
                    {"title": text, "text": text, "bullets": [text]},
                    {"title": text, "text": text, "bullets": [text]},
                ],
            },
            {"layout": "quote", "quote": text, "by": text},
            {
                "layout": "stats",
                "title": text,
                "stats": [{"value": text, "label": text, "detail": text}],
            },
            {"layout": "chart", "title": "Chart", "text": text, "chart": chart},
            {
                "layout": "table",
                "title": text,
                "caption": text,
                "table": {"columns": [text, text], "rows": [[text, text]]},
            },
            {"layout": "image", "title": text, "image": PIXEL, "caption": text},
            {"layout": "image", "image": PIXEL, "caption": text},
            {"layout": "steps", "title": text, "steps": [{"title": text, "text": text}]},
            {"layout": "closing", "title": text, "subtitle": text, "bullets": [text]},
        ]
    }


# ----------------------------------------------------------------- normalize


def test_normalize_keeps_the_fields_of_the_layout_and_is_idempotent() -> None:
    spec = normalize(
        {
            "theme": "DARK",
            "accent": "Green",
            "author": "dropped",
            "slides": [
                {
                    "layout": "bullets",
                    "title": "  Growth   came from\nexisting customers ",
                    "bullets": ["One", "", "Two"],
                    "stats": [{"value": "1"}],
                    "subtitle": "not shown on a bullets slide",
                    "colour": "red",
                    "notes": "Say it slowly.\r\nThen pause.",
                }
            ],
        }
    )

    assert spec == {
        "theme": "dark",
        "accent": "green",
        "slides": [
            {
                "layout": "bullets",
                "title": "Growth came from existing customers",
                "bullets": ["One", "Two"],
                "notes": "Say it slowly.\nThen pause.",
            }
        ],
    }
    assert normalize(spec) == spec


def test_normalize_is_idempotent_for_every_layout_and_for_clipped_texts() -> None:
    long = "word " * 400
    for source in (_every_layout(), _every_layout(long), EXAMPLE, starter("Deck", "en")):
        once = normalize(source)
        assert normalize(once) == once
        assert json.loads(json.dumps(once)) == once


def test_normalize_bounds_every_list_and_text() -> None:
    long = "x" * 5_000
    spec = normalize(
        {
            "slides": [
                {"layout": "bullets", "title": long, "text": long, "bullets": [long] * 20},
                {"title": "Columns", "columns": [{"title": long, "bullets": [long] * 9}] * 7},
                {"title": "Stats", "stats": [{"value": long, "label": long}] * 9},
                {"title": "Steps", "steps": [{"title": long, "text": long}] * 12},
                {
                    "title": "Table",
                    "table": {"columns": ["c"] * 20, "rows": [[long] * 20] * 30},
                },
                {"quote": long, "by": long, "notes": long},
                {"layout": "closing", "title": "End", "bullets": [long] * 9},
                *[{"title": f"Slide {index}"} for index in range(100)],
            ]
        }
    )
    bullets, columns, stats, steps, table, quote, closing = spec["slides"][:7]

    assert len(spec["slides"]) == MAX_SLIDES
    assert len(bullets["title"]) == 110 and bullets["title"].endswith("…")
    assert len(bullets["text"]) == 280
    assert len(bullets["bullets"]) == 6 and all(len(b) == 160 for b in bullets["bullets"])
    assert len(columns["columns"]) == 3
    assert len(columns["columns"][0]["bullets"]) == 4
    assert len(columns["columns"][0]["bullets"][0]) == 80
    assert len(closing["bullets"]) == 4 and all(len(b) == 100 for b in closing["bullets"])
    assert len(stats["stats"]) == 4 and len(stats["stats"][0]["value"]) == 12
    assert len(steps["steps"]) == 6 and len(steps["steps"][0]["text"]) == 140
    assert len(table["table"]["columns"]) == 8
    assert len(table["table"]["rows"]) == 10
    assert all(len(row) == 8 for row in table["table"]["rows"])
    assert len(table["table"]["rows"][0][0]) == 60
    assert len(quote["quote"]) == 320 and len(quote["notes"]) == 1_200


def test_a_bar_chart_keeps_the_rows_that_fit_a_slide() -> None:
    labels = [f"Row {index}" for index in range(20)]
    chart = {"type": "bar", "x": labels, "series": [{"name": "n", "data": list(range(20))}]}

    kept = normalize({"slides": [{"title": "Ranking", "chart": chart}]})["slides"][0]["chart"]

    assert kept["x"] == labels[:10]
    assert kept["series"] == [{"name": "n", "data": list(range(10))}]


def test_a_chart_is_kept_in_the_report_chart_grammar() -> None:
    lone = {"type": "area", "title": "Users", "x": ["a", "b"], "data": [1.5, None], "unit": "k"}

    kept = normalize({"slides": [{"chart": lone}]})["slides"][0]

    assert kept["layout"] == "chart"
    assert kept["chart"] == {
        "type": "area",
        "title": "Users",
        "unit": "k",
        "x": ["a", "b"],
        "series": [{"name": "Users", "data": [1.5, None]}],
    }
    # The chart may also arrive as the JSON text the chat's chart block carries.
    assert normalize({"slides": [{"chart": json.dumps(lone)}]})["slides"][0] == kept


@pytest.mark.parametrize(
    ("fields", "layout"),
    [
        ({"title": "T", "stats": [{"value": "4"}], "bullets": ["a"]}, "stats"),
        ({"title": "T", "chart": CHART, "text": "t"}, "chart"),
        ({"title": "T", "table": TABLE}, "table"),
        ({"image": PIXEL}, "image"),
        ({"title": "T", "steps": ["One", "Two"]}, "steps"),
        ({"title": "T", "columns": [{"title": "A"}, {"title": "B"}]}, "columns"),
        ({"quote": "Q", "by": "Someone"}, "quote"),
        ({"title": "T", "bullets": ["a"]}, "bullets"),
        ({"title": "T", "text": "Only a paragraph"}, "bullets"),
        ({"title": "T", "subtitle": "S"}, "section"),
        ({"layout": "no-such-layout", "title": "T", "bullets": ["a"]}, "bullets"),
        ({"layout": "KPIs", "stats": [{"value": "1"}]}, "stats"),
        ({"layout": "timeline", "steps": ["One"]}, "steps"),
    ],
)
def test_a_missing_layout_follows_from_the_fields(fields: dict[str, Any], layout: str) -> None:
    spec = normalize({"slides": [{"title": "Opening"}, fields]})

    assert spec["slides"][1]["layout"] == layout


def test_the_first_slide_with_only_a_title_opens_the_deck() -> None:
    spec = normalize({"slides": ["Launch plan", {"title": "Part one"}, {"notes": "nothing"}]})

    assert [slide["layout"] for slide in spec["slides"]] == ["title", "section"]
    assert spec["slides"][0]["title"] == "Launch plan"


def test_a_layout_without_its_content_becomes_the_one_the_fields_fit() -> None:
    spec = normalize(
        {
            "slides": [
                {"layout": "stats", "title": "No numbers", "bullets": ["but points"]},
                {"layout": "chart", "title": "No chart"},
                {"layout": "quote", "title": "T", "columns": [{"title": "only one"}]},
            ]
        }
    )

    assert [slide["layout"] for slide in spec["slides"]] == ["bullets", "section", "section"]
    assert spec["slides"][0]["bullets"] == ["but points"]


def test_a_spec_may_be_the_bare_list_of_slides() -> None:
    assert normalize([{"title": "Only slide"}])["slides"] == [
        {"layout": "title", "title": "Only slide"}
    ]


@pytest.mark.parametrize("spec", [None, {}, {"slides": []}, {"slides": [{}, 3]}, "deck", 7])
def test_a_deck_without_a_slide_is_refused_with_what_to_send(spec: Any) -> None:
    with pytest.raises(NodeError, match='"slides": a list of 1 to 60 slides') as raised:
        normalize(spec)

    assert "bullets" in str(raised.value)


@pytest.mark.parametrize(
    ("slide", "message"),
    [
        ({"chart": {"type": "pie", "x": ["a", "b"], "data": [1, 2]}}, '"chart" must be'),
        ({"chart": {"type": "line", "x": ["a", "b"], "data": [1]}}, "one number per label"),
        ({"layout": "chart", "chart": "not json"}, '"chart" must be'),
        ({"columns": [{"title": "alone"}]}, "2 or 3 columns"),
        ({"image": "https://example.org/a.png"}, "no web address"),
        ({"image": "data:image/svg+xml;base64,PHN2Zz4="}, '"image" must be'),
        ({"table": {"columns": ["a"]}}, '"table" must be'),
        ({"table": [["a", "b"]]}, '"table" must be'),
    ],
)
def test_content_that_cannot_be_drawn_is_refused_by_slide(
    slide: dict[str, Any], message: str
) -> None:
    with pytest.raises(NodeError, match=r"Slide 2 \(/slides/1\): ") as raised:
        normalize({"slides": [{"title": "Opening"}, slide]})

    assert message in str(raised.value)
    assert "\n" not in str(raised.value)


def test_an_unusable_field_the_layout_does_not_show_is_dropped_not_refused() -> None:
    spec = normalize(
        {"slides": [{"layout": "bullets", "title": "T", "bullets": ["a"], "chart": {"x": 1}}]}
    )

    assert spec["slides"] == [{"layout": "bullets", "title": "T", "bullets": ["a"]}]


def test_theme_and_accent_accept_only_known_values() -> None:
    slides = [{"title": "T"}]

    assert normalize({"theme": "neon", "slides": slides})["theme"] == "auto"
    assert "accent" not in normalize({"accent": "red;background:url(x)", "slides": slides})
    assert "accent" not in normalize({"accent": "</style><script>", "slides": slides})
    assert "accent" not in normalize({"accent": "accent", "slides": slides})
    assert normalize({"accent": "#E4572E", "slides": slides})["accent"] == "#e4572e"


def test_control_characters_never_reach_a_slide() -> None:
    spec = normalize({"slides": [{"title": "A\x000\x00B", "bullets": ["`x`\x00 0\x00"]}]})

    assert spec["slides"][0]["title"] == "A0B"
    assert "\x00" not in render(_node(spec))


# -------------------------------------------------------------------- render


def test_render_is_deterministic_and_carries_every_slide() -> None:
    spec = _every_layout()
    for index, slide in enumerate(spec["slides"]):
        if "title" in slide:
            slide["title"] = f"Unique title {index}"
    node = _node(spec)

    html = render(node)

    assert html == render(node)
    assert html.startswith("<!doctype html>")
    assert '<body class="fill">' in html
    assert html.count('<li class="dk-cell') == len(spec["slides"])
    assert f"/ {len(spec['slides'])}</p>" in html
    for slide in spec["slides"]:
        if "title" in slide:
            assert slide["title"] in html
    # Every layout has its own composition.
    for layout in LAYOUTS:
        assert f'class="sl l-{layout}' in html
    assert 'class="sl l-bleed"' in html
    assert 'class="card chart"' in html
    assert f'<img src="{PIXEL}"' in html


def test_render_escapes_every_text_field() -> None:
    harmless = _parsed(render(_node(_every_layout("Text"), title="Text")))

    for payload in (SCRIPT, BREAKOUT, f"{SCRIPT} {BREAKOUT}", f"x{BREAKOUT}"):
        html = render(_node(_every_layout(payload), title=payload))
        markup = _parsed(html)

        assert SCRIPT not in html
        assert "<img src=x" not in html
        assert "&lt;" in html
        # Read as a browser reads it, the page is the same page: no tag, no
        # attribute and no script that the harmless deck does not have too.
        assert markup.tags == harmless.tags
        assert markup.attributes == harmless.attributes
        assert not any(name.startswith("on") for name in markup.attributes)
        assert markup.image_sources == [PIXEL, PIXEL]
        assert markup.scripts == harmless.scripts


def test_render_never_takes_a_style_or_a_script_from_the_spec() -> None:
    spec = {
        "theme": 'dark"><script>alert(1)</script>',
        "accent": "#fff;}</style><script>alert(1)</script>",
        "slides": [{"layout": 'title"><script>alert(1)</script>', "title": "T"}],
    }

    html = render(_node(spec))

    assert SCRIPT not in html
    assert "--da:" not in html.split("<body", 1)[1]


def test_the_page_references_nothing_outside_itself() -> None:
    html = render(_node(_every_layout("See [the source](https://example.org/a)")))

    for reference in ('src="http', "src='http", "url(", "@import", "<link", "<iframe"):
        assert reference not in html
    # A link in a text stays a link; the page script hands it to the app.
    assert '<a href="https://example.org/a" rel="noopener noreferrer">the source</a>' in html


def test_the_player_has_its_controls_and_names_them() -> None:
    html = render(_node(EXAMPLE))

    for label in ("Previous slide", "Next slide", "All slides", "Speaker notes"):
        assert f'aria-label="{label}"' in html
    assert 'aria-live="polite"' in html
    assert 'class="dk-progress"' in html
    assert "history.replaceState" in html and "ResizeObserver" in html
    assert "@media print" in html
    assert 'aria-roledescription="slide"' in html
    assert 'aria-label="Slide 1: Q3 in review"' in html


def test_speaker_notes_are_in_the_page_with_their_line_breaks() -> None:
    spec = {"slides": [{"title": "One"}, {"title": "Two", "notes": "First line\nSecond **line**"}]}

    html = _drawn(render(_node(spec)))

    note = '<div class="dk-note" data-i="1" hidden>First line<br>Second <strong>line</strong>'
    assert note in html
    assert '<p class="dk-note-none">' in html


def test_a_fixed_theme_carries_its_tokens_on_the_deck() -> None:
    slides = [{"title": "T"}]
    auto = render(_node({"slides": slides}))
    dark = render(_node({"theme": "dark", "accent": "orange", "slides": slides}))
    light = render(_node({"theme": "light", "accent": "#0A7", "slides": slides}))

    assert '<div class="dk" tabindex="-1">' in auto
    assert ".dk[data-theme=" not in auto
    assert '<div class="dk" data-theme="dark" style="--da:var(--s2)" tabindex="-1">' in dark
    assert '@media screen{.dk[data-theme="dark"]{color-scheme:dark;' in dark
    assert "--bg:#141413" in dark.split('.dk[data-theme="dark"]{', 1)[1].split("}", 1)[0]
    assert '<div class="dk" data-theme="light" style="--da:#0a7" tabindex="-1">' in light
    assert "--bg:#FDFDFC" in light.split('.dk[data-theme="light"]{', 1)[1].split("}", 1)[0]


def test_the_deck_styles_use_tokens_only() -> None:
    html = render(_node(_every_layout()))
    own = html.split("html,body{height:100%}", 1)[1].split("</style>", 1)[0]
    deck = own.split(".dk{", 1)[1]

    # No colour of its own: everything is a token or a mix of tokens.
    assert "#" not in deck
    assert "rgb(" not in deck and "hsl(" not in deck


def test_a_table_aligns_its_number_columns() -> None:
    html = _drawn(render(_node({"slides": [{"title": "Plans", "table": TABLE}]})))

    assert "<th>Plan</th>" in html and '<th class="n">Price</th>' in html
    assert "<td>Solo</td>" in html and '<td class="n">9 €</td>' in html


def test_a_chart_slide_does_not_repeat_its_title_in_the_chart() -> None:
    chart = {**CHART, "title": "Users per month"}
    html = render(_node({"slides": [{"title": "Users per month", "chart": chart}]}))

    assert html.count("Users per month</h") == 1
    assert 'class="legend"' not in html
    assert "<svg viewBox=" in html


def test_sections_are_numbered_in_order() -> None:
    spec = {"slides": ["Deck", {"title": "A"}, {"title": "x", "bullets": ["y"]}, {"title": "B"}]}

    html = render(_node(spec))

    assert '<div class="sl-mark"><span>01</span>' in html
    assert '<div class="sl-mark"><span>02</span>' in html


def test_a_stored_spec_no_rule_accepts_still_renders_a_page() -> None:
    node = Node(
        id="0123456789ab",
        type="slides",
        title="Old deck",
        spec={"slides": [{"title": "Chart", "chart": {"x": "no longer a chart"}}]},
        slug="s",
        page_path="p.html",
        created_at=1.0,
        updated_at=2.0,
    )

    html = render(node)

    assert "<title>Old deck</title>" in html
    assert '<li class="dk-cell' not in html


# ---------------------------------------------------------------- edit mode


def _fields(spec: Any, title: str = "Quarterly review") -> list[Any]:
    """The page's fields, checked against the spec the node holds."""
    node = _node(spec, title=title)
    fields = check_editable(render(node), node.spec, node.title)
    paths = [field.at for field in fields]
    assert len(paths) == len(set(paths)), "a place of the spec is offered twice"
    return fields


def test_every_text_of_a_deck_is_a_field_at_its_place_in_the_stored_spec() -> None:
    spec = _every_layout()
    spec["slides"][2]["notes"] = "Line one\nLine two"
    for deck in (
        EXAMPLE,
        starter("Offsite plan", "en"),
        spec,
        _every_layout("**Bold** [l](https://x.org)"),
    ):
        fields = _fields(deck)
        assert fields and not any(field.refresh for field in fields)


def test_a_small_deck_offers_exactly_its_texts() -> None:
    spec = {
        "slides": [
            {"layout": "title", "kicker": "K", "title": "Deck", "subtitle": "Sub"},
            {"layout": "bullets", "title": "Points", "text": "Lede", "bullets": ["a", "b"]},
            {"layout": "stats", "stats": [{"value": "9%", "label": "Churn", "detail": "d"}]},
            {"layout": "table", "title": "T", "table": TABLE, "caption": "c", "notes": "n"},
            {"layout": "quote", "quote": "Q", "by": "B"},
            {
                "layout": "columns",
                "columns": [{"title": "A", "bullets": ["x"]}, {"text": "B"}],
            },
            {"layout": "steps", "steps": [{"title": "One", "text": "first"}]},
            {"layout": "chart", "title": "C", "text": "aside", "chart": CHART},
            {"layout": "image", "image": PIXEL, "caption": "Pic"},
        ]
    }

    paths = {field.at for field in _fields(spec)}

    assert paths == {
        "@title",
        "/slides/0/kicker",
        "/slides/0/title",
        "/slides/0/subtitle",
        "/slides/1/title",
        "/slides/1/text",
        "/slides/1/bullets/0",
        "/slides/1/bullets/1",
        "/slides/2/stats/0/value",
        "/slides/2/stats/0/label",
        "/slides/2/stats/0/detail",
        "/slides/3/title",
        "/slides/3/table/columns/0",
        "/slides/3/table/columns/1",
        "/slides/3/table/rows/0/0",
        "/slides/3/table/rows/0/1",
        "/slides/3/table/rows/1/0",
        "/slides/3/table/rows/1/1",
        "/slides/3/caption",
        "/slides/3/notes",
        "/slides/4/quote",
        "/slides/4/by",
        "/slides/5/columns/0/title",
        "/slides/5/columns/0/bullets/0",
        "/slides/5/columns/1/text",
        "/slides/6/steps/0/title",
        "/slides/6/steps/0/text",
        "/slides/7/title",
        "/slides/7/text",
        "/slides/8/caption",
    }


def test_texts_drawn_with_marks_keep_the_stored_text_and_notes_take_lines() -> None:
    spec = {
        "slides": [
            {
                "title": "Points",
                "bullets": ["Plain", "With **bold**", "A [link](https://example.org/a)"],
                "notes": "First line\nSecond **line**",
            },
            {"title": "Plain notes", "subtitle": "s", "notes": "Only one line"},
        ]
    }

    fields = {field.at: field for field in _fields(spec)}

    assert fields["/slides/0/bullets/0"].src is None
    assert fields["/slides/0/bullets/1"].src == "With **bold**"
    assert fields["/slides/0/bullets/1"].text == "With bold"
    assert fields["/slides/0/bullets/2"].src == "A [link](https://example.org/a)"
    assert fields["/slides/0/notes"].src == "First line\nSecond **line**"
    assert fields["/slides/0/notes"].multiline and fields["/slides/1/notes"].multiline
    assert not fields["/slides/0/bullets/1"].multiline
    # A field holds only its own text: the drawn marks of the bold and the link.
    page = render(_node(spec))
    assert '<li data-at="/slides/0/bullets/1" data-src="With **bold**">With <strong>bold' in page


def test_the_deck_name_is_a_field_once_and_a_clipped_name_keeps_the_whole() -> None:
    long = "A deck whose name runs on " * 5
    node = _node({"slides": [{"title": "One"}, {"title": "Two"}]}, title=long.strip())

    fields = [field for field in editable_fields(render(node)) if field.at == "@title"]

    assert len(fields) == 1
    assert fields[0].src == long.strip()
    check_editable(render(node), node.spec, node.title)


def test_hostile_texts_in_a_field_are_data_and_never_markup() -> None:
    harmless = _parsed(render(_node(_every_layout("**Text** *x*"), title="Text")))

    for payload in (SCRIPT, BREAKOUT, f"{SCRIPT} {BREAKOUT}"):
        text = f"**{payload}** *x*"
        node = _node(_every_layout(text), title=payload)
        html = render(node)
        markup = _parsed(html)
        fields = check_editable(html, node.spec, node.title)

        assert SCRIPT not in html and "<img src=x" not in html
        assert SCRIPT not in _drawn(html)
        # The stored text is in data-src, attribute-escaped, and comes back whole.
        assert any(field.src == text for field in fields)
        assert f'data-src="{text}"' not in html
        assert markup.tags == harmless.tags
        assert markup.attributes == harmless.attributes
        assert not any(name.startswith("on") for name in markup.attributes)
        assert markup.scripts == harmless.scripts


def test_a_stored_deck_that_does_not_line_up_offers_no_field_of_a_slide() -> None:
    drawn = {"slides": [{"title": "One"}, {"title": "Two", "bullets": ["a"]}]}
    # Stored under older rules: an empty entry the reader drops, a text with
    # extra spaces the reader cleans. No place in it can be named for sure.
    shifted = replace(_node(drawn), spec={"slides": [{}, *drawn["slides"]]})
    spaced = replace(
        _node(drawn), spec={"slides": [{"title": "One  "}, {"title": "Two", "bullets": ["a"]}]}
    )

    assert [f.at for f in editable_fields(render(shifted))] == ["@title"]
    paths = [f.at for f in check_editable(render(spaced), spaced.spec, spaced.title)]
    assert "/slides/0/title" not in paths and "/slides/1/bullets/0" in paths


def test_the_page_keeps_working_in_edit_mode() -> None:
    html = render(_node(_every_layout()))

    # Sizes that follow a text are kept in step after a save, without a redraw.
    assert '"node-field-saved"' in html and "follow(sl)" in html
    # An emptied text may take its slide or point out: only then is it redrawn.
    assert 'setAttribute("data-refresh","")' in html
    assert not any(field.refresh for field in editable_fields(html))
    # Edit mode opens the notes and shows the deck's name in the bar.
    assert '"data-node-mode"' in html
    assert ':root[data-node-mode="edit"] .dk-name{visibility:visible}' in html


# ------------------------------------------------- preview, starter, the guide


def test_preview_has_exactly_the_card_values() -> None:
    assert preview(normalize(EXAMPLE)) == {
        "title": "Q3 in review",
        "subtitle": "Revenue, retention, next steps",
        "count": 4,
        "dark": False,
        "accent": "var(--s3)",
    }


def test_preview_is_bounded_and_reads_the_theme() -> None:
    spec = normalize(
        {
            "theme": "dark",
            "accent": "#E4572E",
            "slides": [{"quote": "q" * 300}, {"title": "t" * 110, "subtitle": "s" * 180}],
        }
    )

    card = preview(spec)

    assert list(card) == ["title", "subtitle", "count", "dark", "accent"]
    assert len(card["title"]) == 60 and card["title"].startswith("ttt")
    assert len(card["subtitle"]) == 80 and card["subtitle"].startswith("qqq")
    assert card["count"] == 2 and card["dark"] is True and card["accent"] == "#e4572e"
    assert preview({}) == {"title": "", "subtitle": "", "count": 0, "dark": False, "accent": ""}


def test_starter_is_a_small_valid_deck_named_after_the_node() -> None:
    spec = starter("Offsite plan", "de")

    assert normalize(spec) == spec
    assert [slide["layout"] for slide in spec["slides"]] == ["title", "bullets", "closing"]
    assert spec["slides"][0]["title"] == "Offsite plan"
    assert starter("", "en")["slides"][0]["title"]
    assert "Offsite plan" in render(_node(spec, title="Offsite plan"))


def test_the_guide_is_compact_and_its_example_is_a_valid_deck() -> None:
    spec = normalize(EXAMPLE)

    assert len(GUIDE) <= 2_500
    assert json.dumps(EXAMPLE, ensure_ascii=False, separators=(",", ":")) in GUIDE
    assert all(f"- {layout}:" in GUIDE for layout in LAYOUTS)
    assert [slide["layout"] for slide in spec["slides"]] == [
        slide["layout"] for slide in EXAMPLE["slides"]
    ]
    assert spec["slides"][2]["chart"] == EXAMPLE["slides"][2]["chart"]
    assert render(_node(EXAMPLE))


def test_the_type_is_registered_under_its_names() -> None:
    kind = kind_of("deck")

    assert kind.type == "slides"
    assert kind.guide == GUIDE
    assert kind.preview(kind.normalize(EXAMPLE))["count"] == 4
