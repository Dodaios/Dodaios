"""Diagrams, layouts and the old whiteboard grammar turned into scene elements
(``board.convert`` and ``board.layout``)."""

from __future__ import annotations

from typing import Any

import pytest

from dodaios.nodes.board import convert as cv
from dodaios.nodes.board import elements as el
from dodaios.nodes.board import layout as lay
from dodaios.nodes.board.scene import normalize_scene
from dodaios.nodes.types import NodeError

NOW = 1_731_500_000_000
PNG_1x1 = (
    "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAIAAAABCAYAAAD0In+KAAAAC0lEQVR4"
    "nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII="
)


def by_id(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {e["id"]: e for e in items}


def labels(items: list[dict[str, Any]]) -> dict[str, str]:
    return {
        e["containerId"]: e["originalText"]
        for e in items
        if e["type"] == "text" and e.get("containerId")
    }


def assert_loadable(items: list[dict[str, Any]]) -> None:
    index = by_id(items)
    for position, e in enumerate(items):
        if e["type"] == "text" and e.get("containerId"):
            assert items.index(index[e["containerId"]]) < position
            assert {"id": e["id"], "type": "text"} in index[e["containerId"]]["boundElements"]
        if e["type"] == "arrow":
            assert e["points"][0] == [0, 0]
            for side in ("startBinding", "endBinding"):
                assert {"id": e["id"], "type": "arrow"} in index[e[side]["elementId"]][
                    "boundElements"
                ]
        if e["type"] == "frame":
            assert all(later.get("frameId") != e["id"] for later in items[position + 1 :])


# --- layout --------------------------------------------------------------------------------


def boxes(n: int, w: float = 100, h: float = 60) -> list[lay.Box]:
    return [lay.Box(f"b{i}", w, h) for i in range(n)]


def no_overlap(items: list[lay.Box]) -> bool:
    return all(
        not lay.overlaps(a.rect(), b.rect()) for i, a in enumerate(items) for b in items[i + 1 :]
    )


def test_flow_layers_follow_the_edges_and_a_loop_does_not_turn_it() -> None:
    items = boxes(4)
    w, h = lay.flow(items, [("b0", "b1"), ("b1", "b2"), ("b2", "b3"), ("b3", "b1")], direction="LR")
    xs = [b.x for b in items]
    assert xs == sorted(xs) and len(set(xs)) == 4
    assert min(b.x for b in items) == 0 and w == max(b.x + b.w for b in items)
    items = boxes(3)
    lay.flow(items, [("b0", "b1"), ("b0", "b2")], direction="TB")
    assert items[1].y == items[2].y > items[0].y and no_overlap(items)
    items = boxes(3)
    lay.flow(items, [("b0", "b1"), ("b1", "b2")], direction="RL")
    assert items[0].x > items[1].x > items[2].x


def test_tree_centres_a_parent_over_its_children() -> None:
    items = boxes(4)
    lay.tree(items, [("b0", "b1"), ("b0", "b2"), ("b0", "b3")], direction="TB")
    kids = items[1:]
    assert all(k.y > items[0].y for k in kids) and no_overlap(items)
    assert items[0].cx == pytest.approx((kids[0].cx + kids[-1].cx) / 2)


def test_mindmap_spreads_branches_to_both_sides() -> None:
    items = boxes(7)
    lay.mindmap(items, [("b0", f"b{i}") for i in range(1, 7)], root="b0")
    centre = items[0].cx
    assert sum(b.cx > centre for b in items[1:]) == 3 and sum(b.cx < centre for b in items[1:]) == 3
    assert no_overlap(items)


def test_grid_pack_and_arrange() -> None:
    items = boxes(7)
    lay.grid(items, columns=3)
    assert len({b.y for b in items}) == 3 and no_overlap(items)
    blocks = [lay.Box(f"k{i}", 400, 300) for i in range(5)]
    lay.pack(blocks)
    assert no_overlap(blocks) and len({b.y for b in blocks}) >= 2
    items = boxes(6)
    lay.arrange(items, [("b0", "b1"), ("b2", "b3")], kind="flow", direction="LR")
    assert no_overlap(items)


def test_free_spot_avoids_everything() -> None:
    occupied = [(0.0, 0.0, 200.0, 100.0), (260.0, 0.0, 400.0, 400.0)]
    assert lay.free_spot([], 100, 100) == (0.0, 0.0)
    x, y = lay.free_spot(occupied, 100, 100)
    assert x >= 400 and lay.is_free((x, y, x + 100, y + 100), occupied)
    for side in ("right", "left", "below", "above", "near"):
        x, y = lay.free_spot(occupied, 120, 80, anchor=occupied[0], side=side)
        assert lay.is_free((x, y, x + 120, y + 80), occupied), side
    x, y = lay.free_spot(occupied, 120, 80, anchor=occupied[0], side="below")
    assert y >= 100


def test_direction_words() -> None:
    assert lay.direction_of("TD") == "TB" and lay.direction_of("down") == "TB"
    assert lay.direction_of("sideways", "LR") == "LR"


# --- diagrams --------------------------------------------------------------------------------


def test_normalize_diagram_fills_ids_and_says_what_is_wrong() -> None:
    spec = cv.normalize_diagram(
        {"nodes": ["Plan", {"label": "Do", "type": "decision"}], "edges": [["n1", "n2", "then"]]}
    )
    assert [n["id"] for n in spec["nodes"]] == ["n1", "n2"] and spec["nodes"][1][
        "kind"
    ] == "diamond"
    assert (
        spec["edges"][0]["label"] == "then"
        and spec["layout"] == "flow"
        and spec["direction"] == "LR"
    )
    for raw, words in [
        ({}, "'nodes' must be a list"),
        ({"nodes": [{"id": "a"}, {"id": "a"}]}, r"nodes\[1\]: the id 'a' is used twice"),
        (
            {"nodes": [{"id": "a"}], "edges": [{"from": "a", "to": "b"}]},
            r"edges\[0\]: 'to' names no node",
        ),
        ({"nodes": [{"id": "a"}], "layout": "spiral"}, "'layout' must be one of"),
        ({"nodes": [{"id": "a", "type": "frame"}]}, "a diagram node is one of"),
        (
            {"nodes": [{"id": "a"}], "groups": [{"id": "g", "nodes": ["x"]}]},
            r"groups\[0\]: no node",
        ),
        (
            {"nodes": [{"id": "a"}, {"id": "b"}], "edges": [{"from": "a", "to": "a"}]},
            "two different",
        ),
        ({"nodes": [{"id": "a", "color": "plaid"}]}, "unknown colour"),
    ]:
        with pytest.raises(ValueError, match=words):
            cv.normalize_diagram(raw)


def test_a_group_named_on_its_nodes_becomes_a_frame() -> None:
    spec = cv.normalize_diagram(
        {"nodes": [{"id": "a", "group": "Team A"}, {"id": "b", "group": "Team A"}, "c"]}
    )
    assert spec["groups"] == [{"id": "Team_A", "label": "Team A", "nodes": ["a", "b"]}]


def test_diagram_elements_frames_arrows_and_sizes() -> None:
    items, ids = cv.diagram_to_elements(
        {
            "direction": "LR",
            "nodes": [
                {"id": "a", "label": "Short"},
                {"id": "b", "label": "A box with a rather long label that wraps"},
                {"id": "c", "label": "Yes?", "type": "diamond"},
                {"id": "d", "label": "Note", "type": "note"},
            ],
            "edges": [
                {"from": "a", "to": "b"},
                {"from": "b", "to": "c", "label": "ask"},
                {"from": "a", "to": "g"},
            ],
            "groups": [{"id": "g", "label": "Group", "nodes": ["b", "c"]}],
        },
        origin=(100, 200),
        now_ms=NOW,
    )
    assert_loadable(items)
    index = by_id(items)
    assert ids == {"a": "a", "b": "b", "c": "c", "d": "d", "g": "g"}
    # One size per kind: the short box is as wide as the long one.
    assert (
        index["a"]["width"] == index["b"]["width"] and index["a"]["height"] == index["b"]["height"]
    )
    assert index["b"]["frameId"] == index["c"]["frameId"] == "g"
    assert index["b:c"]["frameId"] == "g" and labels(items)["b:c"] == "ask"
    assert index["a:g"]["endBinding"]["elementId"] == "g"
    assert index["d"]["backgroundColor"] == el.NOTE_FILL
    for e in items:
        if e["type"] in ("rectangle", "diamond", "frame"):
            assert e["x"] % 20 == 0 and e["y"] % 20 == 0
    assert min(e["x"] for e in items if e["type"] != "arrow") >= 100
    frame = index["g"]
    for member in ("b", "c"):
        x0, y0, x1, y1 = el.box_of(index[member])
        assert frame["x"] < x0 and x1 < frame["x"] + frame["width"] and frame["y"] < y0
    scene = {"format": "scene", "elements": items, "appState": {}, "files": {}}
    el.sync_indices(items)
    assert normalize_scene(normalize_scene(scene)) == normalize_scene(scene)


def test_ids_already_on_the_board_get_a_suffix() -> None:
    items, ids = cv.diagram_to_elements(
        {"nodes": [{"id": "a"}, {"id": "b"}], "edges": [["a", "b"]]}, taken={"a", "a-2"}, now_ms=NOW
    )
    assert ids == {"a": "a-3", "b": "b"}
    assert by_id(items)["a-3:b"]["startBinding"]["elementId"] == "a-3"


def test_parallel_edges_bend_apart() -> None:
    items, _ = cv.diagram_to_elements(
        {"nodes": ["x", "y"], "edges": [["n1", "n2"], ["n2", "n1"]]}, now_ms=NOW
    )
    arrows = [e for e in items if e["type"] == "arrow"]
    assert len(arrows) == 2 and len(arrows[1]["points"]) == 3


def test_an_arrow_bends_around_a_shape_in_its_way() -> None:
    a = el.shape("rectangle", x=0, y=0, width=100, height=60, now_ms=NOW, element_id="a")
    b = el.shape("rectangle", x=600, y=0, width=100, height=60, now_ms=NOW, element_id="b")
    blocker = el.shape("rectangle", x=300, y=0, width=100, height=60, now_ms=NOW, element_id="c")
    points = cv.route(a, b, cv.obstacle_rects([blocker], set()))
    assert len(points) == 3 and not (0 <= points[1][1] <= 60)


def test_title_and_layout_kinds() -> None:
    items, _ = cv.diagram_to_elements(
        {
            "title": "Org",
            "layout": "tree",
            "nodes": ["CEO", "CTO", "CFO"],
            "edges": [["n1", "n2"], ["n1", "n3"]],
        },
        now_ms=NOW,
    )
    title = items[0]
    assert title["type"] == "text" and title["text"] == "Org" and title["fontSize"] == 36
    index = by_id(items)
    assert index["n2"]["y"] > index["n1"]["y"] and index["n2"]["y"] == index["n3"]["y"]
    assert title["y"] + title["height"] <= index["n1"]["y"]


# --- the old grammar ----------------------------------------------------------------------------


def test_legacy_board_becomes_a_scene() -> None:
    scene = cv.legacy_to_scene(
        {
            "layout": "auto",
            "items": [
                {"type": "text", "text": "Launch board"},
                {"id": "a", "text": "Interview **five** customers", "group": "Now"},
                {"id": "b", "text": "Draft the pricing page", "group": "Now", "color": "blue"},
                {"id": "c", "text": "Open the beta", "group": "Next", "color": "green"},
                {"id": "s", "type": "shape", "shape": "diamond", "text": "Go?"},
                {"id": "p", "type": "shape", "shape": "pill", "text": "Ship"},
                {"id": "f", "type": "frame", "title": "Later"},
                {"id": "l", "text": "Later idea", "group": "f"},
            ],
            "links": [
                {"from": "b", "to": "c", "label": "unblocks"},
                {"from": "s", "to": "p", "style": "dashed"},
                {"from": "a", "to": "zzz"},
            ],
        },
        now_ms=NOW,
    )
    assert normalize_scene(scene) == scene
    items = scene["elements"]
    assert_loadable(items)
    index = by_id(items)
    assert (
        items[0]["type"] == "text"
        and items[0]["text"] == "Launch board"
        and items[0]["fontSize"] == 36
    )
    assert (
        index["a"]["backgroundColor"] == el.NOTE_FILL
        and labels(items)["a"] == "Interview five customers"
    )
    assert index["b"]["backgroundColor"] == el.resolve_color("blue", "fill")
    frames = {e["name"]: e for e in items if e["type"] == "frame"}
    assert set(frames) == {"Now", "Next", "Later"}
    assert index["a"]["frameId"] == frames["Now"]["id"] and index["l"]["frameId"] == "f"
    assert index["s"]["type"] == "diamond" and index["p"]["type"] == "rectangle"
    arrows = [e for e in items if e["type"] == "arrow"]
    assert {(a["startBinding"]["elementId"], a["endBinding"]["elementId"]) for a in arrows} == {
        ("b", "c"),
        ("s", "p"),
    }
    assert any(a["strokeStyle"] == "dashed" for a in arrows)


def test_legacy_coordinates_are_kept_and_the_rest_goes_below() -> None:
    scene = cv.legacy_to_scene(
        {
            "layout": "free",
            "items": [
                {"id": "x", "text": "Pinned", "x": 500, "y": 40},
                {"id": "y", "text": "Loose"},
            ],
        },
        now_ms=NOW,
    )
    index = by_id(scene["elements"])
    assert (index["x"]["x"], index["x"]["y"]) == (500, 40)
    assert index["y"]["y"] > 40 + index["x"]["height"]


def test_legacy_pictures_are_stored_or_become_placeholders() -> None:
    spec = {"items": [{"id": "pic", "type": "image", "image": PNG_1x1, "text": "Logo"}]}
    placeholder = cv.legacy_to_scene(spec, now_ms=NOW)
    box = by_id(placeholder["elements"])["pic"]
    assert box["type"] == "rectangle" and box["strokeStyle"] == "dashed"
    assert labels(placeholder["elements"])["pic"] == "Picture: Logo"
    kept: list[str] = []

    def store(data_url: str) -> tuple[str, str]:
        kept.append(data_url)
        return "file1", "image/png"

    stored = cv.legacy_to_scene(spec, store_image=store, now_ms=NOW)
    image = by_id(stored["elements"])["pic"]
    assert kept == [PNG_1x1] and image["type"] == "image" and image["fileId"] == "file1"
    assert image["width"] == 240 and image["height"] == 120  # its own 2:1 proportions
    assert stored["files"]["file1"]["mimeType"] == "image/png"
    assert normalize_scene(stored) == stored


def test_legacy_without_items_is_refused_and_odd_ids_are_fixed() -> None:
    with pytest.raises(NodeError, match="items"):
        cv.legacy_to_scene({"elements": "no"})
    with pytest.raises(NodeError, match="items"):
        cv.legacy_to_scene({"items": [1, 2]})
    scene = cv.legacy_to_scene(
        {"items": [{"id": "has space", "text": "x"}, {"id": "has space", "text": "y"}, "plain"]}
    )
    ids = [e["id"] for e in scene["elements"] if e["type"] == "rectangle"]
    assert len(set(ids)) == 3 and all(el.check_model_id(i) for i in ids)


def test_legacy_of_only_texts_lays_them_out_as_labels() -> None:
    scene = cv.legacy_to_scene(
        {"items": [{"type": "text", "text": "Title"}, {"type": "text", "text": "Sub"}]}
    )
    texts = scene["elements"]
    assert [t["text"] for t in texts] == ["Title", "Sub"]
    assert not lay.overlaps(el.box_of(texts[0]), el.box_of(texts[1]))


def _frames(items: list[dict[str, Any]]) -> list[tuple[float, float, float, float]]:
    return [el.box_of(e) for e in items if e["type"] == "frame"]


def _gap(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    """The free space between two boxes (negative when they overlap)."""
    return max(b[0] - a[2], a[0] - b[2], b[1] - a[3], a[1] - b[3])


def test_unlinked_groups_stand_side_by_side_top_aligned_a_block_gap_apart() -> None:
    # Two groups with no link between them, as in a board that compares two
    # pull requests: a flow in one frame, a fan-out in the other.
    items, _ = cv.diagram_to_elements(
        {
            "direction": "LR",
            "nodes": [
                {"id": "a1", "label": "Before: the first call freezes"},
                {"id": "a2", "label": "Warm the model at start"},
                {"id": "a3", "label": "Reacts at once", "type": "ellipse"},
                {"id": "a4", "label": "5 files, tests", "type": "note"},
                {"id": "b0", "label": "4 features in one PR"},
                {"id": "b1", "label": "Animated view"},
                {"id": "b2", "label": "Window minimises"},
                {"id": "b3", "label": "Stop button"},
                {"id": "b4", "label": "Split it up", "type": "diamond"},
            ],
            "edges": [
                ["a1", "a2"],
                ["a2", "a3"],
                ["b0", "b1"],
                ["b0", "b2"],
                ["b0", "b3"],
                {"from": "b0", "to": "b4", "style": "dashed"},
            ],
            "groups": [
                {"id": "pr1", "label": "PR one", "nodes": ["a1", "a2", "a3", "a4"]},
                {"id": "pr2", "label": "PR two", "nodes": ["b0", "b1", "b2", "b3", "b4"]},
            ],
        },
        now_ms=NOW,
    )
    first, second = _frames(items)
    assert first[1] == second[1]  # top-aligned: the names stand on one line
    assert second[0] - first[2] >= lay.BLOCK_GAP
    shapes = [el.box_of(e) for e in items if e["type"] not in ("arrow", "text", "frame")]
    for index, a in enumerate(shapes):
        for b in shapes[index + 1 :]:
            assert _gap(a, b) > 0


@pytest.mark.parametrize("kind", ["flow", "tree", "mindmap", "grid"])
@pytest.mark.parametrize("direction", ["LR", "TB"])
def test_frames_keep_clear_of_each_other_in_every_layout(kind: str, direction: str) -> None:
    items, _ = cv.diagram_to_elements(
        {
            "layout": kind,
            "direction": direction,
            "nodes": [
                {"id": "hub", "label": "Hub"},
                {"id": "x", "label": "A label of some length here"},
                {"id": "y", "label": "Short"},
                {"id": "z", "label": "Another one", "type": "diamond"},
                {"id": "w", "label": "Loose", "type": "note"},
            ],
            "edges": [["hub", "x"], ["hub", "y"], ["hub", "z"]],
            "groups": [
                {"id": "gx", "label": "First group with a long name", "nodes": ["x"]},
                {"id": "gy", "label": "Second", "nodes": ["y"]},
                {"id": "gz", "label": "Third", "nodes": ["z"]},
                {"id": "gw", "label": "Fourth", "nodes": ["w"]},
            ],
        },
        now_ms=NOW,
    )
    frames = _frames(items)
    assert len(frames) == 4
    for frame in frames:
        assert frame[2] - frame[0] == pytest.approx(round((frame[2] - frame[0]) / 20) * 20)
    for index, a in enumerate(frames):
        for b in frames[index + 1 :]:
            assert _gap(a, b) >= lay.CROSS_GAP


def test_a_long_link_takes_a_wide_bend_round_a_wall() -> None:
    a = el.shape("rectangle", x=0, y=0, width=100, height=60, now_ms=NOW, element_id="a")
    b = el.shape("rectangle", x=600, y=0, width=100, height=60, now_ms=NOW, element_id="b")
    # Too tall for the usual bends: only a wide one gets past.
    wall = el.shape("rectangle", x=300, y=-500, width=100, height=1060, now_ms=NOW, element_id="w")
    obstacles = cv.obstacle_rects([wall], set())
    points = cv.route(a, b, obstacles)
    assert len(points) == 3
    assert not any(
        cv._segment_hits(points[i], points[i + 1], rect)
        for i in range(len(points) - 1)
        for rect in obstacles
    )


def test_with_no_clear_way_the_link_crosses_the_fewest_boxes() -> None:
    a = el.shape("rectangle", x=0, y=0, width=100, height=60, now_ms=NOW, element_id="a")
    b = el.shape("rectangle", x=600, y=0, width=100, height=60, now_ms=NOW, element_id="b")
    # A wall no bend gets round, and two more boxes on the straight line.
    wall = el.shape("rectangle", x=300, y=-5000, width=60, height=10060, now_ms=NOW, element_id="w")
    near = el.shape("rectangle", x=180, y=0, width=60, height=60, now_ms=NOW, element_id="n")
    far = el.shape("rectangle", x=440, y=0, width=60, height=60, now_ms=NOW, element_id="f")
    obstacles = cv.obstacle_rects([wall, near, far], set())
    points = cv.route(a, b, obstacles)
    crossed = sum(
        1
        for rect in obstacles
        if any(cv._segment_hits(points[i], points[i + 1], rect) for i in range(len(points) - 1))
    )
    assert crossed == 1
