"""Free elements, backgrounds, tones, fonts, transitions and hidden slides of a deck."""

from __future__ import annotations

import re
from typing import Any

import pytest

from dodaios.nodes.kinds.slide_elements import (
    MAX_ELEMENTS,
    SHAPES,
    auto_tone,
    read_background,
    read_element,
)
from dodaios.nodes.kinds.slides import normalize, render
from dodaios.nodes.model import Node
from dodaios.nodes.types import NodeError

PIXEL = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4"
    "nGNgYGD4DwABBAEAwS2OUAAAAABJRU5ErkJggg=="
)
SCRIPT = "<script>alert(1)</script>"


def _node(spec: Any) -> Node:
    return Node(
        id="0123456789ab",
        type="slides",
        title="Deck",
        spec=normalize(spec),
        slug="s",
        page_path="p.html",
        created_at=1.0,
        updated_at=2.0,
        language="en",
    )


def _deck(*elements: dict[str, Any], **slide: Any) -> dict[str, Any]:
    return {"slides": [{"layout": "blank", "elements": list(elements), **slide}]}


def _elements(spec: dict[str, Any]) -> list[dict[str, Any]]:
    return normalize(spec)["slides"][0].get("elements", [])


# ----------------------------------------------------------------- the grammar


def test_every_element_type_is_kept_with_its_fields_and_is_idempotent() -> None:
    spec = _deck(
        {"type": "text", "x": 10, "y": 20, "w": 300, "h": 80, "text": "Hi", "bold": True},
        {"type": "shape", "shape": "star", "fill": "amber", "text": "Star"},
        {"type": "line", "x1": 0, "y1": 0, "x2": 100, "y2": 50, "end": "arrow"},
        {"type": "image", "image": PIXEL, "fit": "contain"},
        {"type": "table", "rows": [["A", "B"], ["1", "2"]]},
        {"type": "chart", "chart": {"type": "pie", "x": ["a", "b"], "series": [{"data": [1, 2]}]}},
    )
    once = normalize(spec)
    assert normalize(once) == once
    kinds = [element["type"] for element in once["slides"][0]["elements"]]
    assert kinds == ["text", "shape", "line", "image", "table", "chart"]
    text = once["slides"][0]["elements"][0]
    assert text == {"type": "text", "x": 10, "y": 20, "w": 300, "h": 80, "text": "Hi", "bold": True}


def test_aliases_name_the_types_and_shapes_a_model_reaches_for() -> None:
    found = _elements(
        _deck(
            {"type": "arrow", "x1": 0, "y1": 0, "x2": 10, "y2": 0},
            {"type": "textbox", "text": "x"},
            {"shape": "circle"},
            {"type": "shape", "shape": "speech"},
        )
    )
    assert found[0]["type"] == "line" and found[0]["end"] == "arrow"
    assert found[1]["type"] == "text"
    assert found[2] == {**found[2], "type": "shape", "shape": "ellipse"}
    assert found[3]["shape"] == "callout"


def test_numbers_are_bounded_and_rounded() -> None:
    element = read_element(
        {
            "type": "text",
            "x": -99_999,
            "y": 12.345,
            "w": 0,
            "h": 99_999,
            "rotate": 9_999,
            "opacity": -5,
            "size": 1_000,
            "line": 9,
            "spacing": 3,
        },
        "here",
    )
    assert element is not None
    assert element["x"] == -1280 and element["y"] == 12.3
    assert element["w"] == 4 and element["h"] == 1440
    assert element["rotate"] == 360 and element["opacity"] == 0
    assert element["size"] == 240 and element["line"] == 3 and element["spacing"] == 0.5


def test_a_slide_holds_at_most_forty_elements() -> None:
    many = [{"type": "text", "text": str(n)} for n in range(MAX_ELEMENTS + 10)]
    assert len(_elements(_deck(*many))) == MAX_ELEMENTS


@pytest.mark.parametrize(
    ("element", "words"),
    [
        ({"type": "video"}, '"type"'),
        ({"type": "image", "image": "https://example.org/a.png"}, "no network"),
        ({"type": "table", "rows": "nope"}, "rows"),
        ({"type": "chart", "chart": {"type": "pie"}}, "chart"),
    ],
)
def test_an_element_that_cannot_be_drawn_is_refused_with_its_place(
    element: dict[str, Any], words: str
) -> None:
    with pytest.raises(NodeError) as caught:
        normalize(_deck({"type": "text", "text": "ok"}, element))
    message = str(caught.value)
    assert words in message
    assert "Slide 1" in message and "element 2" in message


def test_colours_fonts_and_links_accept_only_safe_values() -> None:
    element = read_element(
        {
            "type": "text",
            "text": "x",
            "color": "red;}</style><script>",
            "fill": "url(x)",
            "stroke": "#abc",
            "font": "Comic Sans; color:red",
            "link": "javascript:alert(1)",
        },
        "here",
    )
    assert element is not None
    assert "color" not in element and "fill" not in element and "font" not in element
    assert "link" not in element
    assert element["stroke"] == "#abc"
    assert read_element({"type": "text", "color": "Accent", "fill": "white"}, "x") == {
        **read_element({"type": "text"}, "x"),  # type: ignore[dict-item]
        "color": "accent",
        "fill": "white",
    }


def test_a_shape_without_a_known_kind_is_a_rectangle() -> None:
    element = read_element({"type": "shape", "shape": "blob"}, "x")
    assert element is not None and element["shape"] == "rect"
    assert set(SHAPES) >= {"rect", "rounded", "ellipse", "star", "arrow", "callout"}


def test_backgrounds_take_a_colour_a_gradient_or_a_picture() -> None:
    assert read_background("#123456", "x") == {"color": "#123456"}
    assert read_background({"gradient": ["#000", "#fff"]}, "x") == {
        "gradient": {"from": "#000", "to": "#fff", "angle": 135}
    }
    assert read_background({"image": PIXEL, "dim": 140, "fit": "contain"}, "x") == {
        "image": PIXEL,
        "fit": "contain",
        "dim": 90,
    }
    assert read_background({"color": "nope"}, "x") == {}
    with pytest.raises(NodeError):
        read_background({"image": "https://example.org/a.png"}, "x")


def test_a_dark_background_asks_for_light_text_by_itself() -> None:
    assert auto_tone({"color": "#0f172a"}) == "dark"
    assert auto_tone({"color": "#fdf2f8"}) == "light"
    assert auto_tone({"gradient": {"from": "#000000", "to": "#1e293b", "angle": 0}}) == "dark"
    assert auto_tone({"image": PIXEL, "dim": 50}) == "dark"
    assert auto_tone({"image": PIXEL}) == ""
    assert auto_tone({"color": "blue"}) == ""


def test_slide_and_deck_settings_are_kept() -> None:
    spec = normalize(
        {
            "font": "editorial",
            "transition": "zoom",
            "footer": False,
            "background": {"color": "#000"},
            "slides": [
                {
                    "title": "A",
                    "tone": "light",
                    "transition": "none",
                    "hidden": True,
                    "footer": False,
                },
                {"title": "B", "font": "nope", "transition": "spin", "tone": "red"},
            ],
        }
    )
    assert spec["font"] == "editorial" and spec["transition"] == "zoom"
    assert spec["footer"] is False and spec["background"] == {"color": "#000"}
    first, second = spec["slides"]
    assert first["tone"] == "light" and first["transition"] == "none"
    assert first["hidden"] is True and first["footer"] is False
    assert {"tone", "transition", "font"}.isdisjoint(second)


def test_a_slide_of_only_elements_or_only_a_background_is_blank() -> None:
    spec = normalize(
        {"slides": [{"elements": [{"type": "text", "text": "x"}]}, {"background": "#000"}]}
    )
    assert [slide["layout"] for slide in spec["slides"]] == ["blank", "blank"]


def test_an_element_picture_from_a_file_path_key_is_the_image_key() -> None:
    # The store embeds a picture a path names under the key "image" (pictures.py);
    # an image element and a background use that key too.
    element = read_element({"type": "image", "src": PIXEL}, "x")
    assert element is not None and element["image"] == PIXEL


# ----------------------------------------------------------------- the page


def test_the_page_draws_every_element_where_it_is() -> None:
    html = render(
        _node(
            _deck(
                {"type": "text", "x": 10, "y": 20, "w": 300, "h": 80, "text": "Hello **you**"},
                {"type": "shape", "shape": "hexagon", "x": 400, "y": 20, "w": 100, "h": 100},
                {"type": "line", "x1": 0, "y1": 0, "x2": 100, "y2": 0, "end": "arrow"},
                {"type": "image", "image": PIXEL, "x": 1, "y": 2, "w": 3, "h": 4, "fit": "contain"},
                {"type": "table", "rows": [["A"], ["1"]]},
                {
                    "type": "chart",
                    "chart": {"type": "column", "x": ["a", "b"], "series": [{"data": [1, 2]}]},
                },
            )
        )
    )
    assert '<div class="sl-els">' in html
    assert (
        'class="el el-text" data-el="0" style="left:10px;top:20px;width:300px;height:80px"' in html
    )
    assert "Hello <strong>you</strong>" in html
    assert 'class="el el-shape is-hexagon v-m"' in html and 'viewBox="0 0 100 100"' in html
    assert 'class="el el-line"' in html and "<polygon" in html
    assert f'<img src="{PIXEL}" alt="" class="is-contain">' in html
    assert '<table class="el-table has-head"' in html and ">A</th>" in html
    assert 'class="el el-chart"' in html and 'class="card chart"' in html


def test_texts_of_elements_are_escaped() -> None:
    html = render(
        _node(_deck({"type": "text", "text": SCRIPT}, {"type": "table", "rows": [[SCRIPT]]}))
    )
    body = html.split("<body", 1)[1].split("<script>", 1)[0]
    assert SCRIPT not in body
    assert "&lt;script&gt;" in body


def test_animations_carry_their_order_and_clicks_wait() -> None:
    html = render(
        _node(
            _deck(
                {"type": "text", "text": "a", "anim": "fade"},
                {"type": "text", "text": "b", "anim": "rise", "click": True},
                {"type": "text", "text": "c", "anim": "zoom"},
            )
        )
    )
    assert re.search(r'data-anim="fade" style="[^"]*--ad:150ms"', html)
    assert 'data-anim="rise" data-click style=' in html
    assert re.search(r'data-anim="zoom" style="[^"]*--ad:270ms"', html)


def test_backgrounds_tones_fonts_transitions_and_hidden_slides_reach_the_page() -> None:
    html = render(
        _node(
            {
                "font": "serif",
                "transition": "slide",
                "slides": [
                    {"title": "A", "background": {"color": "#0f172a"}},
                    {"title": "B", "hidden": True, "transition": "zoom", "footer": False},
                ],
            }
        )
    )
    assert '<section class="sl l-title f-serif" data-tone="dark"' in html
    assert '<div class="sl-bg" style="background:#0f172a"></div>' in html
    assert '<li class="dk-cell is-hidden" data-i="1" data-tr="zoom">' in html
    assert 'data-i="0" data-tr="slide"' in html
    assert '.sl[data-tone="light"]{' in html
    # The hidden slide drops its footer, the deck's name still in the bar.
    second = html.split('data-i="1"', 1)[1].split("</section>", 1)[0]
    assert "sl-foot" not in second


def test_the_player_skips_hidden_slides_and_builds_on_click() -> None:
    html = render(_node(_deck({"type": "text", "text": "x"})))
    assert "function forward()" in html and "function back()" in html
    assert ".el[data-click]" in html and "is-built" in html
    assert 'q.get("slide")' in html and "is-still" in html


def test_the_footer_can_be_left_off_for_the_whole_deck() -> None:
    html = render(_node({"footer": False, "slides": [{"title": "A"}, {"title": "B"}]}))
    assert '<footer class="sl-foot">' not in html


def test_a_deck_has_room_for_several_pictures_within_a_save() -> None:
    from dodaios.nodes.shell import MAX_IMAGE_CHARS
    from dodaios.nodes.store import SPEC_BYTES_BY_TYPE
    from dodaios.ui.web.nodes_routes import MAX_SPEC_BODY

    assert SPEC_BYTES_BY_TYPE["slides"] >= 8 * MAX_IMAGE_CHARS
    assert SPEC_BYTES_BY_TYPE["slides"] < MAX_SPEC_BODY


def test_an_animation_rule_names_its_animation_where_it_plays() -> None:
    from dodaios.nodes.kinds.slide_elements import ELEMENT_CSS

    # One rule carries the name and the timing (a shorthand alone would reset the name).
    rule = ELEMENT_CSS.split('.ed-stage.is-presenting .el[data-anim="rise"].is-built', 1)[1]
    assert rule.startswith("{animation:el-rise .62s")
    assert "animation-name:" not in ELEMENT_CSS


def test_home_and_end_land_on_a_shown_slide() -> None:
    html = render(_node({"slides": [{"title": "A", "hidden": True}, {"title": "B"}]}))
    assert 'k==="Home")show(seen(0,1)%n)' in html
