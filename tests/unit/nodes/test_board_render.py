"""A whiteboard's page: the scene drawn as SVG, safe, offline, both themes."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from dodaios.nodes.board import files as board_files
from dodaios.nodes.board import render as board_render
from dodaios.nodes.board.render import drawing, render
from dodaios.nodes.board.scene import normalize_scene
from dodaios.nodes.model import Node

SCRIPT = "<script>alert(1)</script>"
BREAKOUT = '"><img src=x onerror=alert(1)>'
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d4944415478da63fcff9f010005fe02fea7d6a4b90000000049454e44ae426082"
)


def _el(ident: str, kind: str = "rectangle", **fields: Any) -> dict[str, Any]:
    return {"id": ident, "type": kind, "x": 0, "y": 0, "width": 100, "height": 50, **fields}


def _node(*elements: dict[str, Any], track: str = "", spec: Any = None, **scene: Any) -> Node:
    return Node(
        id="0123456789ab",
        type="whiteboard",
        title="Plan",
        spec=spec if spec is not None else normalize_scene({"elements": list(elements), **scene}),
        slug="s",
        page_path="p.html",
        created_at=1_700_000_000,
        updated_at=1_700_000_600,
        track=track,
    )


def _svg(page: str) -> str:
    start = page.index('<svg class="wb-svg"')
    return page[start : page.index("</svg></div>", start)]


def test_the_page_is_one_offline_document_and_the_same_node_gives_the_same_page() -> None:
    node = _node(_el("r"), _el("t", "text", text="Hello"))
    page = render(node)
    assert page.startswith("<!doctype html>") and page == render(node)
    assert '<meta name="dodaios-node-type" content="whiteboard">' in page
    assert not re.search(r"""(?:src|href)=["']?(?:https?:)?//""", page)
    assert "url(http" not in page and "@import" not in page


def test_every_shape_is_drawn_with_clean_geometry() -> None:
    svg = _svg(
        render(
            _node(
                _el("r", roundness={"type": 3}, backgroundColor="#ffec99"),
                _el("e", "ellipse", x=200),
                _el("d", "diamond", x=400),
                _el("a", "arrow", x=0, y=200, points=[[0, 0], [100, 0]], strokeStyle="dashed"),
                _el(
                    "l",
                    "line",
                    x=0,
                    y=300,
                    points=[[0, 0], [50, 50], [100, 0]],
                    roundness={"type": 2},
                    strokeStyle="dotted",
                ),  # fmt: skip
                _el("f", "freedraw", x=0, y=400, points=[[0, 0], [3, 4], [8, 2], [12, 9]]),
            )
        )
    )
    assert '<rect x="0" y="0" width="100" height="50" rx="12.5" ry="12.5" fill="#ffec99"' in svg
    assert '<ellipse cx="250" cy="25" rx="50" ry="25" fill="none"' in svg
    assert '<polygon points="450,0 500,25 450,50 400,25"' in svg
    assert 'd="M0 200L100 200"' in svg and 'stroke-dasharray="8 10"' in svg
    assert 'd="M75 209.1L100 200L75 190.9"' in svg  # the arrowhead
    assert "C" in re.search(r'<path d="(M0 300[^"]*)"', svg).group(1)  # curved line
    assert 'stroke-dasharray="1.5 8"' in svg
    assert re.search(r'<path d="M0 400Q', svg)


def test_fills_hatch_with_patterns_and_transparent_stays_empty() -> None:
    svg = _svg(
        render(
            _node(
                _el("h", backgroundColor="#a5d8ff", fillStyle="hachure"),
                _el("c", backgroundColor="#a5d8ff", fillStyle="cross-hatch", x=200),
                _el("n", x=400),
            )
        )
    )
    assert svg.count("<pattern ") == 2 and 'fill="url(#wb-p1)"' in svg
    assert 'fill="url(#wb-p2)"' in svg and 'stroke="#a5d8ff"' in svg
    assert '<rect x="400" y="0" width="100" height="50" fill="none"' in svg


def test_text_keeps_its_lines_alignment_and_size() -> None:
    svg = _svg(
        render(
            _node(
                _el(
                    "t",
                    "text",
                    x=10,
                    y=20,
                    width=200,
                    text="One\nTwo",
                    textAlign="center",
                    fontSize=20,
                    fontFamily=5,
                ),  # fmt: skip
                _el("c", "text", x=0, y=200, text="code", fontFamily=8),
            )
        )
    )
    spans = re.findall(r'<tspan x="([^"]+)" y="([^"]+)">([^<]*)</tspan>', svg)
    assert spans[:2] == [("110", "37.62", "One"), ("110", "62.62", "Two")]
    assert 'text-anchor="middle"' in svg and 'font-size="20"' in svg
    assert 'class="wb-t wb-mono"' in svg


def test_every_text_from_the_scene_is_escaped() -> None:
    page = render(
        _node(
            _el("t", "text", text=SCRIPT + BREAKOUT),
            _el("f", "frame", name=SCRIPT, width=300, height=200),
        )
    )
    assert SCRIPT not in page and "<img" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page


def test_a_title_reaches_the_page_escaped() -> None:
    node = _node(_el("r"))
    page = render(Node(**{**node.__dict__, "title": BREAKOUT}))
    assert BREAKOUT not in page and "&quot;&gt;&lt;img" in page


def test_opacity_rotation_and_deleted_elements() -> None:
    svg = _svg(
        render(
            _node(
                _el("o", opacity=40),
                _el("r", x=100, y=0, width=100, height=50, angle=3.14159265 / 2),
                _el("gone", x=900, isDeleted=True),
            )
        )
    )
    assert '<g opacity="0.4">' in svg
    assert 'transform="rotate(90 150 25)"' in svg
    assert 'x="900"' not in svg


def test_children_of_a_frame_are_clipped_and_the_frame_is_named() -> None:
    svg = _svg(
        render(
            _node(
                _el("child", x=10, y=10, frameId="fr"),
                _el("fr", "frame", x=0, y=0, width=300, height=200, name="Ideas"),
            )
        )
    )
    assert '<clipPath id="wb-f1"><rect x="0" y="0" width="300" height="200"' in svg
    assert '<g clip-path="url(#wb-f1)"><rect x="10" y="10"' in svg
    assert ">Ideas</text>" in svg


def test_a_picture_is_embedded_from_the_run_folder(tmp_path: Path) -> None:
    file_id = board_files.store_bytes(tmp_path, PNG, "image/png")
    node = _node(
        _el("i", "image", fileId=file_id, scale=[-1, 1]), _el("m", "image", x=300, fileId="missing")
    )
    page = board_render.render(node, run_dir=tmp_path)
    assert 'href="data:image/png;base64,iVBORw0KGgo' in page
    assert 'class="wb-img" transform="translate(50 25) scale(-1 1) translate(-50 -25)"' in page
    assert page.count(">Image</text>") == 1
    # Without the folder (the plain renderer) every picture is a labelled box.
    assert render(node).count(">Image</text>") == 2


def test_pictures_beyond_the_page_budget_become_boxes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    file_id = board_files.store_bytes(tmp_path, PNG, "image/png")
    monkeypatch.setattr(board_render, "IMAGE_BUDGET_CHARS", 10)
    page = board_render.render(_node(_el("i", "image", fileId=file_id)), run_dir=tmp_path)
    assert "data:image/png" not in page and ">Image</text>" in page


def test_a_cropped_picture_shows_its_crop(tmp_path: Path) -> None:
    file_id = board_files.store_bytes(tmp_path, PNG, "image/png")
    crop = {"x": 1, "y": 2, "width": 30, "height": 40, "naturalWidth": 100, "naturalHeight": 80}
    svg = drawing(
        normalize_scene({"elements": [_el("i", "image", fileId=file_id, crop=crop)]}),
        run_dir=tmp_path,
    )
    assert 'viewBox="1 2 30 40" preserveAspectRatio="none"><image' in svg
    assert 'width="100" height="80"' in svg


def test_the_dark_theme_inverts_the_drawing_and_pictures_back() -> None:
    page = render(_node(_el("r"), appState={"viewBackgroundColor": "#fff9db"}))
    assert ':root[data-theme="dark"] .wb-canvas{filter:invert(93%) hue-rotate(180deg)}' in page
    assert ".wb-img{filter:url(#wb-reinvert)}" in page and 'id="wb-reinvert"' in page
    assert 'class="wb-canvas" style="background:#fff9db"' in page


def test_the_view_fits_the_drawing_and_an_empty_board_says_so() -> None:
    page = render(_node(_el("r", x=1000, y=500, width=400, height=300)))
    box = re.search(r'viewBox="([^"]+)"', page).group(1).split()
    x, y, w, h = map(float, box)
    assert x < 1000 and y < 500 and x + w > 1400 and y + h > 800
    empty = render(_node())
    assert "This whiteboard is empty." in empty and 'viewBox="0 0 800 500"' in empty


def test_numbers_are_formatted_from_floats() -> None:
    svg = _svg(render(_node(_el("r", x=1 / 3, y=-0.001, width=10.25, height=2))))
    assert '<rect x="0.33" y="0" width="10.25" height="2"' in svg
    assert board_render._n(float("nan")) == "0" and board_render._n(-0.001) == "0"


def test_a_spec_that_is_no_scene_still_opens_as_an_empty_board() -> None:
    for spec in ({"items": [{"text": "old"}]}, {"elements": "broken"}):
        page = render(_node(spec=spec))
        assert "This whiteboard is empty." in page


def test_a_screen_reader_gets_the_words_and_a_kept_node_its_upkeep_line() -> None:
    page = render(
        _node(_el("t", "text", text="Launch plan"), _el("f", "frame", name="Week 1"), track="x")
    )
    assert '<ul class="visually-hidden"><li>Launch plan</li><li>Week 1</li></ul>' in page
    assert 'class="wb-meta"' in page and "data-updated" in page
    assert 'class="wb-meta"' not in render(_node(_el("r")))


def test_arrowheads_of_every_kind_are_drawn() -> None:
    for head in board_render._HEAD_SIZE.keys() | {"triangle", "bar", "dot", "circle_outline"}:
        svg = _svg(render(_node(_el("a", "arrow", points=[[0, 0], [200, 0]], endArrowhead=head))))
        assert svg.count("<path") + svg.count("<polygon") + svg.count("<circle") >= 2, head


def test_a_label_on_an_arrow_cuts_the_line_away_behind_its_words() -> None:
    arrow = _el(
        "a1",
        "arrow",
        points=[[0, 0], [200, 0]],
        width=200,
        height=0,
        boundElements=[{"id": "t1", "type": "text"}],
    )
    label = _el("t1", "text", text="yes", containerId="a1", x=90, y=-10, width=30, height=25)
    boxed = _el("t2", "text", text="Box", x=0, y=100, width=40, height=25)
    svg = drawing(
        normalize_scene(
            {
                "format": "scene",
                "elements": [arrow, label, boxed],
                "appState": {"viewBackgroundColor": "#fff9db"},
            }
        )
    )
    texts = re.findall(r"<text[^>]*>", svg)
    assert len(texts) == 2
    on_line = next(t for t in texts if "paint-order" in t)
    assert 'stroke="#fff9db"' in on_line
    assert sum("paint-order" in t for t in texts) == 1
