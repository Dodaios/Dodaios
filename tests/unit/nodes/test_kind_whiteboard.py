"""The whiteboard node: its grammar, its layout and its page."""

from __future__ import annotations

import copy
import json
import re
from html.parser import HTMLParser
from itertools import combinations
from typing import Any

import pytest

from dodaios.nodes.kinds import whiteboard
from dodaios.nodes.kinds.whiteboard import (
    COLORS,
    EXAMPLE,
    GUIDE,
    MAX_ITEMS,
    MAX_LINKS,
    layout,
    normalize,
    preview,
    render,
    starter,
)
from dodaios.nodes.model import Node
from dodaios.nodes.types import NodeError

SCRIPT = "<script>alert(1)</script>"
BREAKOUT = '"><img src=x onerror=alert(1)>'
# A 1x1 PNG, so an image item has a real picture to carry.
PIXEL = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
    "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


def _node(spec: dict[str, Any], *, title: str = "Board", track: str = "") -> Node:
    return Node(
        id="0123456789ab",
        type="whiteboard",
        title=title,
        spec=normalize(spec),
        slug="s",
        page_path="p.html",
        created_at=1_700_000_000,
        updated_at=1_700_000_600,
        track=track,
    )


def _grouped(groups: int, notes: int) -> dict[str, Any]:
    return {
        "items": [
            {"id": f"g{g}n{n}", "text": f"Note {n} of group {g}", "group": f"Group {g}"}
            for g in range(groups)
            for n in range(notes)
        ]
    }


def _rect(box: dict[str, Any]) -> tuple[float, float, float, float]:
    return box["x"], box["y"], box["x"] + box["w"], box["y"] + box["h"]


def _overlap(a: dict[str, Any], b: dict[str, Any]) -> bool:
    ax0, ay0, ax1, ay1 = _rect(a)
    bx0, by0, bx1, by1 = _rect(b)
    return ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1


def _inside(inner: dict[str, Any], outer: dict[str, Any]) -> bool:
    ix0, iy0, ix1, iy1 = _rect(inner)
    ox0, oy0, ox1, oy1 = _rect(outer)
    return ox0 <= ix0 and oy0 <= iy0 and ix1 <= ox1 and iy1 <= oy1


class _TagReader(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[tuple[str, dict[str, str]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append((tag, {key: value or "" for key, value in attrs}))


def _tags(html: str) -> list[tuple[str, dict[str, str]]]:
    """Every start tag of the page with its attributes, as a parser reads them."""
    reader = _TagReader()
    reader.feed(html)
    reader.close()
    return reader.tags


def _wires(html: str) -> str:
    """The connectors' SVG."""
    found = re.search(r'<svg class="wb-wires".*?</svg>', html, flags=re.S)
    return found.group(0) if found else ""


# --- normalize -------------------------------------------------------------------


def test_normalize_keeps_the_grammar_and_drops_the_rest() -> None:
    spec = normalize(
        {
            "layout": "FREE",
            "theme": "neon",
            "items": [
                {
                    "id": "a",
                    "type": "shape",
                    "shape": "diamond",
                    "text": "  Ship it?  ",
                    "color": "purple",
                    "x": "10",
                    "y": 20.004,
                    "w": 5,
                    "h": 99_999,
                    "rotation": 12,
                    "style": "color:red",
                },
                {"id": "b", "type": "frame", "title": "Later", "group": "nested", "text": "x"},
                "A bare string is a note",
                {"id": "c", "type": "image", "image": PIXEL, "text": "A pixel"},
                {"id": "d", "type": "image", "image": "https://example.org/a.png"},
                {"id": "e", "type": "hologram", "shape": "pill", "color": "teal"},
                42,
            ],
            "links": [{"from": "a", "to": "b", "style": "DASHED", "label": " maybe ", "bend": 3}],
        }
    )
    assert spec["layout"] == "free"
    assert set(spec) == {"items", "links", "layout"}
    first = spec["items"][0]
    assert first == {
        "id": "a",
        "type": "shape",
        "text": "Ship it?",
        "color": "violet",
        "shape": "diamond",
        "x": 10,
        "y": 20,
        "w": 24,
        "h": 2400,
    }
    assert spec["items"][1] == {"id": "b", "type": "frame", "title": "Later"}
    assert spec["items"][2] == {"id": "i1", "type": "note", "text": "A bare string is a note"}
    assert spec["items"][3]["image"] == PIXEL
    assert spec["items"][4] == {"id": "d", "type": "image"}
    # A shape name without a known type makes the item a shape; an unknown color goes.
    assert spec["items"][5] == {"id": "e", "type": "shape", "shape": "pill"}
    assert len(spec["items"]) == 6
    assert spec["links"] == [{"from": "a", "to": "b", "label": "maybe", "style": "dashed"}]


def test_normalize_is_idempotent() -> None:
    raw = {
        "items": [
            {"id": "a" * 39 + " b", "text": "x" * 399 + " tail", "group": "g" * 59 + " h"},
            {"id": "a" * 39 + " b", "text": "line one\r\nline two", "x": 1.23456, "y": -7},
            {"type": "frame", "title": "t" * 79 + " u", "x": 0, "y": 0, "w": 300.129},
            {"text": "no id"},
            {"type": "text", "text": "**Bold** [link](https://example.org)"},
        ],
        "links": [
            {"from": "a" * 39, "to": "i1", "label": "l" * 59 + " m"},
            {"from": "i1", "to": "i2"},
        ],
    }
    once = normalize(raw)
    assert normalize(once) == once
    assert normalize(copy.deepcopy(once)) == once
    for spec in (EXAMPLE, starter("Board", "en"), _grouped(3, 5)):
        clean = normalize(spec)
        assert normalize(clean) == clean
    # JSON round trip: what the store writes is what normalize accepts unchanged.
    assert normalize(json.loads(json.dumps(once))) == once


def test_normalize_bounds_texts_lists_and_numbers() -> None:
    spec = normalize(
        {
            "items": [
                {
                    "id": "k" * 200,
                    "text": "t" * 5_000,
                    "group": "g" * 500,
                    "x": 1e9,
                    "y": -1e9,
                    "w": 1e9,
                    "h": 0,
                },
                {"type": "frame", "title": "f" * 500},
                *({"text": f"n{index}"} for index in range(400)),
            ],
            "links": [{"from": "i1", "to": "i2", "label": "l" * 500}] * 500,
        }
    )
    assert len(spec["items"]) == MAX_ITEMS
    assert len(spec["links"]) == MAX_LINKS
    first = spec["items"][0]
    assert len(first["id"]) == 40 and len(first["text"]) == 400 and len(first["group"]) == 60
    assert (first["x"], first["y"], first["w"], first["h"]) == (20_000, -20_000, 2_400, 24)
    assert len(spec["items"][1]["title"]) == 80
    assert len(spec["links"][0]["label"]) == 60


def test_normalize_drops_coordinates_that_are_not_a_pair_of_numbers() -> None:
    spec = normalize(
        {
            "items": [
                {"id": "a", "text": "only x", "x": 5},
                {"id": "b", "text": "nan", "x": "NaN", "y": 2},
                {"id": "c", "text": "bool", "x": True, "y": 2},
                {"id": "d", "text": "fine", "x": 0, "y": 0},
            ]
        }
    )
    assert ["x" in item for item in spec["items"]] == [False, False, False, True]


@pytest.mark.parametrize(
    "bad",
    [None, "board", [], {}, {"items": []}, {"items": "a note"}, {"items": [None, 3, []]}],
)
def test_an_unusable_spec_tells_the_model_what_to_send(bad: Any) -> None:
    with pytest.raises(NodeError) as raised:
        normalize(bad)
    message = str(raised.value)
    assert '"items"' in message and '"text"' in message


def test_ids_are_generated_for_items_without_one() -> None:
    spec = normalize(
        {"items": [{"text": "a"}, {"id": "i1", "text": "b"}, {"text": "c"}, {"id": 7}]}
    )
    # The stated "i1" is kept by its owner; generated ids step around it.
    assert [item["id"] for item in spec["items"]] == ["i2", "i1", "i3", "7"]


def test_duplicate_ids_are_made_unique_and_links_follow_the_first() -> None:
    spec = normalize(
        {
            "items": [
                {"id": "a", "text": "first"},
                {"id": "a", "text": "second"},
                {"id": "a-2", "text": "third"},
                {"id": "a", "text": "fourth"},
            ],
            "links": [{"from": "a", "to": "a-2"}],
        }
    )
    ids = [item["id"] for item in spec["items"]]
    assert ids == ["a", "a-3", "a-2", "a-4"]
    assert len(set(ids)) == len(ids)
    assert spec["links"] == [{"from": "a", "to": "a-2"}]


def test_links_to_unknown_ids_and_to_itself_are_dropped() -> None:
    spec = normalize(
        {
            "items": [{"id": "a", "text": "a"}, {"id": "b", "text": "b"}],
            "links": [
                {"from": "a", "to": "b"},
                {"from": "a", "to": "ghost"},
                {"from": "ghost", "to": "b"},
                {"from": "a", "to": "a"},
                {"to": "b"},
                "a->b",
                {"from": "b", "to": "a", "style": "wavy"},
            ],
        }
    )
    assert spec["links"] == [{"from": "a", "to": "b"}, {"from": "b", "to": "a"}]


def test_normalize_does_not_write_coordinates_into_an_auto_board() -> None:
    spec = normalize(_grouped(3, 5))
    for item in spec["items"]:
        assert not {"x", "y", "w", "h"} & set(item)


# --- layout ----------------------------------------------------------------------


def test_auto_layout_is_deterministic() -> None:
    spec = _grouped(3, 5)
    spec["links"] = [{"from": "g0n0", "to": "g2n4", "label": "then"}]
    assert layout(spec) == layout(copy.deepcopy(spec))
    assert layout(spec) == layout(normalize(spec))


def test_auto_layout_gathers_groups_into_frames_without_overlap() -> None:
    spec = _grouped(3, 5)
    spec["items"].append({"id": "loose", "text": "Outside every group"})
    boxes = layout(spec)
    frames = [box for box in boxes if box["type"] == "frame"]
    notes = [box for box in boxes if box["type"] == "note"]
    assert [frame["id"] for frame in frames] == ["frame:Group 0", "frame:Group 1", "frame:Group 2"]
    assert len(notes) == 16
    for a, b in combinations(notes, 2):
        assert not _overlap(a, b), (a, b)
    for a, b in combinations(frames, 2):
        assert not _overlap(a, b), (a, b)
    by_id = {box["id"]: box for box in boxes}
    for g, frame in enumerate(frames):
        for n in range(5):
            assert _inside(by_id[f"g{g}n{n}"], frame)
        assert not _overlap(by_id["loose"], frame)
    # Tidy: the frames are equally wide, and a frame's notes share a grid.
    assert len({frame["w"] for frame in frames}) == 1
    first = [by_id[f"g0n{n}"] for n in range(5)]
    assert len({note["x"] for note in first}) in (2, 3)
    assert first[0]["y"] == first[1]["y"]
    gaps = {round(b["x"] - (a["x"] + a["w"]), 2) for a, b in zip(first, first[1:], strict=False)}
    assert len({gap for gap in gaps if gap > 0}) == 1


def test_frames_follow_the_order_their_groups_first_appear() -> None:
    boxes = layout(
        {
            "items": [
                {"id": "a", "text": "a", "group": "Later"},
                {"id": "b", "text": "b", "group": "Sooner"},
                {"id": "c", "text": "c", "group": "Later"},
            ]
        }
    )
    frames = [box for box in boxes if box["type"] == "frame"]
    assert [frame["id"] for frame in frames] == ["frame:Later", "frame:Sooner"]
    assert frames[0]["x"] < frames[1]["x"]


def test_a_frame_item_is_the_frame_of_the_group_that_names_it() -> None:
    boxes = layout(
        {
            "items": [
                {"id": "now", "type": "frame", "title": "Doing now", "color": "green"},
                {"id": "a", "text": "a", "group": "now"},
                {"id": "b", "text": "b", "group": "Doing now"},
            ]
        }
    )
    assert [box["id"] for box in boxes] == ["now", "a", "b"]
    assert _inside(boxes[1], boxes[0]) and _inside(boxes[2], boxes[0])


def test_many_groups_wrap_into_rows_without_overlap() -> None:
    boxes = layout(_grouped(9, 7))
    frames = [box for box in boxes if box["type"] == "frame"]
    assert len({frame["y"] for frame in frames}) > 1
    for a, b in combinations(boxes, 2):
        if a["type"] == "frame" or b["type"] == "frame":
            continue
        assert not _overlap(a, b)
    for a, b in combinations(frames, 2):
        assert not _overlap(a, b)


def test_a_note_grows_with_its_text() -> None:
    short, long = layout(
        {
            "items": [
                {"id": "short", "text": "Hi", "group": "A"},
                {"id": "long", "text": "word " * 80, "group": "B"},
            ]
        }
    )[1::2]
    assert short["id"] == "short" and long["id"] == "long"
    assert long["h"] > short["h"] * 2
    # 400 characters at about twenty a line, twenty pixels each.
    assert long["h"] >= 400 / 21 * 20


def test_linked_shapes_are_layered_left_to_right_along_their_links() -> None:
    spec = {
        "items": [
            {"id": "end", "type": "shape", "text": "End"},
            {"id": "start", "type": "shape", "text": "Start"},
            {"id": "ask", "type": "shape", "shape": "diamond", "text": "OK?"},
            {"id": "yes", "type": "shape", "text": "Yes"},
            {"id": "no", "type": "shape", "text": "No"},
        ],
        "links": [
            {"from": "start", "to": "ask"},
            {"from": "ask", "to": "yes"},
            {"from": "ask", "to": "no"},
            {"from": "yes", "to": "end"},
            {"from": "no", "to": "end"},
            {"from": "end", "to": "start", "style": "dashed"},
        ],
    }
    boxes = {box["id"]: box for box in layout(spec)}
    assert boxes["start"]["x"] < boxes["ask"]["x"] < boxes["yes"]["x"] < boxes["end"]["x"]
    assert boxes["yes"]["x"] == boxes["no"]["x"]
    assert boxes["yes"]["y"] != boxes["no"]["y"]
    for a, b in combinations(boxes.values(), 2):
        assert not _overlap(a, b)

    def middle(name: str) -> float:
        return boxes[name]["y"] + boxes[name]["h"] / 2

    # The branch is centred on the decision, and the end on the branch.
    assert middle("ask") == pytest.approx((middle("yes") + middle("no")) / 2)
    assert middle("end") == pytest.approx(middle("ask"))


def test_free_layout_keeps_the_given_coordinates() -> None:
    spec = {
        "layout": "free",
        "items": [
            {"id": "a", "text": "a", "x": -120, "y": 40},
            {"id": "b", "type": "shape", "text": "b", "x": 300.5, "y": 0, "w": 222, "h": 111},
            {"id": "f", "type": "frame", "title": "Zone", "x": -200, "y": -100, "w": 900, "h": 500},
            {"id": "t", "type": "text", "text": "Label", "x": 0, "y": 600},
        ],
    }
    boxes = {box["id"]: box for box in layout(spec)}
    assert (boxes["a"]["x"], boxes["a"]["y"]) == (-120, 40)
    assert (boxes["a"]["w"], boxes["a"]["h"]) == (200, 160)
    assert boxes["b"] == {"id": "b", "type": "shape", "x": 300.5, "y": 0, "w": 222, "h": 111}
    assert _rect(boxes["f"]) == (-200, -100, 700, 400)
    assert (boxes["t"]["x"], boxes["t"]["y"]) == (0, 600)
    assert layout(spec) == layout(spec)


def test_items_without_a_place_go_below_the_placed_ones() -> None:
    boxes = {
        box["id"]: box
        for box in layout(
            {
                "items": [
                    {"id": "a", "text": "placed", "x": 100, "y": 100},
                    {"id": "b", "text": "flows", "group": "Rest"},
                    {"id": "c", "text": "flows too"},
                ]
            }
        )
    }
    bottom = boxes["a"]["y"] + boxes["a"]["h"]
    assert boxes["b"]["y"] > bottom and boxes["c"]["y"] > bottom
    assert not _overlap(boxes["b"], boxes["c"])


# --- the page --------------------------------------------------------------------


def _hostile(payload: str) -> dict[str, Any]:
    return {
        "layout": payload,
        "items": [
            {
                "id": payload,
                "type": kind,
                "text": payload,
                "title": payload,
                "color": payload,
                "shape": payload,
                "image": payload,
                "group": payload,
                "x": payload,
                "y": payload,
                "w": payload,
                "h": payload,
            }
            for kind in ("note", "text", "shape", "frame", "image", payload)
        ]
        + [
            {
                "id": "plain",
                "text": f"**{payload}** `{payload}` [{payload}](https://e.org/{payload})",
            },
            {"id": "pic", "type": "image", "image": PIXEL, "text": payload},
            {"id": "placed", "type": "shape", "shape": "diamond", "text": payload, "x": 0, "y": 0},
            {"id": "link", "text": f"[x](javascript:alert(1)) [y]({payload})"},
        ],
        "links": [
            {"from": payload, "to": "plain", "label": payload, "style": payload},
            {"from": "plain", "to": payload, "label": payload},
            {"from": "pic", "to": "placed", "label": payload, "style": "dashed"},
        ],
    }


@pytest.mark.parametrize("payload", [SCRIPT, BREAKOUT])
def test_no_text_field_reaches_the_page_unescaped(payload: str) -> None:
    node = _node(_hostile(payload), title=payload)
    assert len(node.spec["links"]) == 3
    html = render(node)
    assert SCRIPT not in html
    assert "<img src=x" not in html
    assert '"><img' not in html
    assert "javascript:" not in html
    # The only scripts and pictures are the page's own.
    assert html.count("<script>") == 2
    assert html.count("<img ") == 1
    # Read the page the way a browser does: no handler attribute anywhere, and
    # every link and picture is one the renderer made itself.
    tags = _tags(html)
    for name, attrs in tags:
        assert not [key for key in attrs if key.startswith("on")], (name, attrs)
    assert [name for name, _ in tags].count("script") == 2
    pictures = [attrs for name, attrs in tags if name == "img"]
    assert len(pictures) == 1 and pictures[0]["src"] == PIXEL
    for name, attrs in tags:
        if name == "a":
            assert attrs["href"].startswith("https://e.org/")


def test_numbers_in_styles_come_from_floats_only() -> None:
    html = render(
        _node(
            {
                "layout": "free",
                "items": [
                    {"id": "a", "text": "a", "x": "12;background:url(//evil)", "y": 3},
                    {"id": "b", "text": "b", "x": 1.23456789, "y": 2, "w": "300px", "h": 99.99},
                ],
                "links": [{"from": "a", "to": "b"}],
            }
        )
    )
    assert "evil" not in html and "300px;" not in html
    for style in re.findall(r'<li[^>]* style="([^"]*)"', html):
        assert re.fullmatch(r"(?:(?:left|top|width|height|min-height):-?\d+(?:\.\d)?px;?)+", style)
    paths = re.findall(r' d="([^"]*)"', _wires(html))
    assert len(paths) == 2
    for path in paths:
        assert re.fullmatch(r"[MCL0-9 .\-]+", path)


def test_render_is_deterministic_and_self_contained() -> None:
    spec = _grouped(3, 5)
    spec["items"].append({"id": "pic", "type": "image", "image": PIXEL, "text": "A pixel"})
    spec["links"] = [
        {"from": "g0n0", "to": "g1n0", "label": "feeds"},
        {"from": "g1n0", "to": "g0n0", "style": "line"},
    ]
    html = render(_node(spec))
    assert html == render(_node(copy.deepcopy(spec)))
    assert html.startswith("<!doctype html>")
    assert '<body class="fill">' in html
    # Nothing is fetched: no address but the embedded picture, no stylesheet, no import.
    assert not re.search(r"""(?:src|href)=["'](?!data:image/)""", html)
    assert "url(" not in html.replace("url(#wb-dots)", "")
    assert "@import" not in html and "<link" not in html
    assert "localStorage" not in html and "fetch(" not in html
    # Colors come from the tokens: the page's own styles carry no hex of their own.
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", whiteboard._CSS)


def test_the_page_is_a_list_with_named_controls() -> None:
    spec = normalize(EXAMPLE)
    html = render(_node(spec, title="Plan"))
    assert '<h1 class="visually-hidden">Plan</h1>' in html
    for label in ("Zoom out", "Reset zoom to 100%", "Zoom in", "Fit all"):
        assert f'aria-label="{label}" title="{label}"' in html
    # Items in reading order: a frame, then its notes.
    order = re.findall(r'<li class="wb-(?:item wb-)?(frame|note)', html)
    assert order == ["frame", "note", "note", "frame", "note"]
    assert html.index("Interview five customers") < html.index("Draft the pricing page")
    assert "<h2>Now</h2>" in html and "<h2>Next</h2>" in html
    # The connector is drawn once, with an arrowhead, and read out with its label.
    assert _wires(html).count('<path d="M') == 2
    assert "Draft the pricing page → Open the beta: </span>unblocks" in html
    assert "dodaios-open-link" in html
    assert "@media print" in html and "size:landscape" in html


def test_note_colors_and_shapes_reach_the_page_as_classes() -> None:
    html = render(
        _node(
            {
                "items": [
                    *({"text": name, "color": name} for name in COLORS),
                    {"type": "shape", "shape": "diamond", "text": "Decide"},
                    {"type": "shape", "shape": "pill", "text": "Start"},
                    {"type": "text", "text": "A heading"},
                    {"type": "text", "text": "A longer label that is clearly not a heading at all"},
                ]
            }
        )
    )
    for name in COLORS:
        assert f'wb-note c-{name}"' in html
    assert 'class="wb-item wb-shape is-diamond c-blue"' in html and "<polygon" in html
    assert 'class="wb-item wb-shape is-pill c-blue"' in html
    assert html.count("wb-text is-big") == 1


def test_inline_marks_and_links_are_rendered() -> None:
    html = render(
        _node({"items": [{"text": "**Bold** and [docs](https://example.org/a?b=1&c=2)"}]})
    )
    assert "<strong>Bold</strong>" in html
    assert '<a href="https://example.org/a?b=1&amp;c=2" rel="noopener noreferrer">docs</a>' in html


def test_an_unusable_stored_spec_still_renders_an_empty_board() -> None:
    node = Node(
        id="0123456789ab",
        type="whiteboard",
        title="Empty",
        spec={},
        slug="s",
        page_path="p.html",
        created_at=1.0,
        updated_at=2.0,
    )
    html = render(node)
    assert '<ul class="wb-items"></ul>' in html
    assert preview({}) == {"notes": [], "count": 0}


def test_a_kept_current_board_shows_when_it_was_refreshed() -> None:
    html = render(_node(EXAMPLE, track="Open tasks from the tracker."))
    assert 'data-updated="1700000600"' in html
    assert "data-updated" not in render(_node(EXAMPLE))


# --- preview, starter, guide ------------------------------------------------------


def test_preview_has_four_texts_notes_first_and_the_count() -> None:
    spec = normalize(
        {
            "items": [
                {"type": "frame", "title": "Frames carry no text"},
                {"text": "**Bold** start with a [link](https://example.org) " + "x" * 80},
                {"type": "image", "image": PIXEL},
                {"type": "shape", "text": "A step", "shape": "pill"},
                {"type": "text", "text": "`code` label", "color": "pink"},
                {"text": "Fourth", "color": "green"},
                {"text": "Fifth"},
            ]
        }
    )
    card = preview(spec)
    assert set(card) == {"notes", "count"}
    assert card["count"] == 7
    # Sticky notes first, then the other items that carry text, in board order.
    assert card["notes"] == [
        {"text": ("Bold start with a link " + "x" * 80)[:40], "color": "yellow"},
        {"text": "Fourth", "color": "green"},
        {"text": "Fifth", "color": "yellow"},
        {"text": "A step", "color": "blue"},
    ]
    for note in card["notes"]:
        assert set(note) == {"text", "color"}
        assert len(note["text"]) <= 40 and note["color"] in COLORS
    assert preview(spec) == preview(spec)
    assert preview({"items": [{"type": "frame", "title": "Only a frame"}]}) == {
        "notes": [],
        "count": 1,
    }


def test_starter_is_a_small_valid_board() -> None:
    spec = starter("My board", "de")
    assert normalize(spec) == spec
    assert len(spec["items"]) == 4 and len(spec["links"]) == 1
    boxes = layout(spec)
    frames = [box for box in boxes if box["type"] == "frame"]
    assert len(frames) == 1
    inside = [box for box in boxes if box["type"] == "note" and _inside(box, frames[0])]
    assert len(inside) == 3
    assert preview(spec)["count"] == 4
    assert "My board" in render(_node(spec, title="My board"))


def test_guide_is_compact_and_its_example_is_valid() -> None:
    assert len(GUIDE) <= 2_500
    spec = normalize(EXAMPLE)
    assert len(spec["items"]) == len(EXAMPLE["items"])
    assert spec["links"] == EXAMPLE["links"]
    assert spec["layout"] == "auto"
    assert len({item["group"] for item in spec["items"]}) == 2
    assert not any("x" in item for item in spec["items"])
    # The guide shows exactly the example the test checks.
    example = json.loads(GUIDE[GUIDE.index("Example:\n") + len("Example:\n") :])
    assert example == EXAMPLE
    for word in ("auto", "group", "frame", "diamond", "dashed", *COLORS):
        assert word in GUIDE


def test_the_kind_registry_loads_the_module() -> None:
    from dodaios.nodes.kinds import kind_of

    kind = kind_of("board")
    assert kind.type == "whiteboard"
    assert kind.normalize is normalize and kind.guide == GUIDE


def test_groups_without_colors_each_get_their_own_paper() -> None:
    items = [
        {"text": "a", "group": "Mail"},
        {"text": "b", "group": "Mail"},
        {"text": "c", "group": "Shop"},
        {"text": "loose"},
    ]
    spec = whiteboard.normalize({"items": items})

    # Nothing is written back: the spec stays what the model sent.
    assert all("color" not in item for item in spec["items"])
    notes = whiteboard.preview(spec)["notes"]
    # One note from each group in turn: Mail, Shop, the loose one, Mail again.
    assert [note["text"] for note in notes] == ["a", "c", "loose", "b"]
    assert [note["color"] for note in notes] == ["yellow", "blue", "yellow", "yellow"]
    page = whiteboard.render(_node(spec))
    assert "c-blue" in page


def test_a_board_that_names_a_color_keeps_its_own_colors() -> None:
    items = [
        {"text": "a", "group": "Mail", "color": "pink"},
        {"text": "b", "group": "Shop"},
    ]
    notes = whiteboard.preview(whiteboard.normalize({"items": items}))["notes"]

    assert [note["color"] for note in notes] == ["pink", "yellow"]
