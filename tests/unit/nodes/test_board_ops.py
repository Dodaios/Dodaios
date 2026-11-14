"""The whiteboard actions (``board.ops``) and the element factory they build on.

Every scene an action produces is checked against what the embedded editor
needs to load it without repair: labels bound both ways and after their box,
arrows bound at both ends with points from (0, 0), a frame after its
children, valid ascending fractional indices.
"""

from __future__ import annotations

import copy
from typing import Any

import pytest

from dodaios.nodes.board import elements as el
from dodaios.nodes.board import layout as lay
from dodaios.nodes.board.ops import ACTIONS, MAX_ACTIONS, apply_actions, describe
from dodaios.nodes.board.scene import empty_scene, normalize_scene
from dodaios.nodes.types import NodeError

NOW = 1_731_500_000_000


def run(scene: dict[str, Any], *actions: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    result, report = apply_actions(scene, list(actions), now_ms=NOW)
    check(result)
    return result, report


def by_id(scene: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {e["id"]: e for e in scene["elements"]}


def live(scene: dict[str, Any]) -> list[dict[str, Any]]:
    return [e for e in scene["elements"] if not e["isDeleted"]]


def label_of(scene: dict[str, Any], container_id: str) -> dict[str, Any] | None:
    for e in live(scene):
        if e["type"] == "text" and e.get("containerId") == container_id:
            return e
    return None


def check(scene: dict[str, Any]) -> None:
    """What the editor needs to load ``scene`` as it is."""
    assert normalize_scene(scene) == scene, "the scene must already be normal"
    elements = scene["elements"]
    index = by_id(scene)
    keys = [e["index"] for e in elements]
    assert all(el.valid_index(k) for k in keys)
    assert keys == sorted(keys) and len(set(keys)) == len(keys)
    for position, e in enumerate(elements):
        if e["isDeleted"]:
            continue
        if e["type"] == "text" and e.get("containerId"):
            container = index[e["containerId"]]
            assert not container["isDeleted"]
            assert {"id": e["id"], "type": "text"} in (container["boundElements"] or [])
            assert elements.index(container) < position
        if e["type"] in ("arrow", "line"):
            assert e["points"][0] == [0, 0]
            for side in ("startBinding", "endBinding"):
                if e.get(side):
                    target = index[e[side]["elementId"]]
                    assert not target["isDeleted"]
                    assert {"id": e["id"], "type": "arrow"} in (target["boundElements"] or [])
        if e["type"] == "frame":
            for later in elements[position + 1 :]:
                assert later.get("frameId") != e["id"] or later["isDeleted"], (
                    "a child after its frame"
                )


def rect(e: dict[str, Any]) -> tuple[float, float, float, float]:
    return el.box_of(e)


def units(scene: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        e
        for e in live(scene)
        if e["type"] not in ("arrow", "line") and not (e["type"] == "text" and e.get("containerId"))
    ]


def assert_no_overlap(scene: dict[str, Any]) -> None:
    things = units(scene)
    for i, a in enumerate(things):
        for b in things[i + 1 :]:
            if a.get("frameId") == b["id"] or b.get("frameId") == a["id"]:
                continue
            assert not lay.overlaps(rect(a), rect(b)), (a["id"], b["id"])


# --- the element factory -------------------------------------------------------------


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        (None, None, "a0"),
        (None, "a0", "Zz"),
        (None, "Zz", "Zy"),
        ("a0", None, "a1"),
        ("a1", None, "a2"),
        ("a0", "a1", "a0V"),
        ("a1", "a2", "a1V"),
        ("a0V", "a1", "a0l"),
        ("Zz", "a0", "ZzV"),
        ("Zz", "a1", "a0"),
        (None, "Y00", "Xzzz"),
        ("bzz", None, "c000"),
        ("a0", "a0V", "a0G"),
        ("a0", "a0G", "a08"),
        ("b125", "b129", "b127"),
        ("a0", "a1V", "a1"),
        ("Zz", "a01", "a0"),
        (None, "a0V", "a0"),
        (None, "b999", "b99"),
    ],
)
def test_fractional_keys_match_the_package_the_editor_uses(a, b, expected) -> None:
    assert el.key_between(a, b) == expected


def test_many_keys_between_are_ordered_and_valid() -> None:
    keys = el.keys_between("a0", "a1", 50)
    assert keys == sorted(keys) and len(set(keys)) == 50
    assert all("a0" < k < "a1" and el.valid_index(k) for k in keys)
    assert el.keys_between(None, None, 3) == ["a0", "a1", "a2"]


def test_sync_indices_keeps_valid_ones_and_fills_the_gaps() -> None:
    items = [
        {"id": "a", "index": "a1"},
        {"id": "b", "index": None},
        {"id": "c", "index": "a2"},
        {"id": "d", "index": "a0"},
        {"id": "e", "index": "bad!"},
    ]
    changed = el.sync_indices(items)
    keys = [i["index"] for i in items]
    assert keys[0] == "a1" and keys[2] == "a2"
    assert keys == sorted(keys) and all(el.valid_index(k) for k in keys)
    assert changed == {"b", "d", "e"}


def test_colours_by_palette_name_shade_and_hex() -> None:
    assert el.resolve_color("blue") == "#1971c2"
    assert el.resolve_color("blue", "fill") == "#a5d8ff"
    assert el.resolve_color("light blue", "fill") == "#e7f5ff"
    assert el.resolve_color("blue-3") == "#228be6"
    assert el.resolve_color("Grey") == "#343a40"
    assert el.resolve_color("#ABC") == "#aabbcc"
    assert el.resolve_color("none") == "transparent"
    assert el.color_name("#1971c2") == "blue" and el.color_name("#e7f5ff") == "blue-0"
    with pytest.raises(ValueError, match="palette name"):
        el.resolve_color("chartreuse")


def test_fonts_and_sizes_are_the_editors() -> None:
    assert (
        el.Palette.font("hand") == 5
        and el.Palette.font("normal") == 6
        and el.Palette.font("code") == 8
    )
    assert el.Palette.font_size("xl") == 36 and el.Palette.font_size(500) == el.MAX_FONT_SIZE
    assert el.LINE_HEIGHTS[6] == 1.35
    with pytest.raises(ValueError):
        el.Palette.font("comic sans")


def test_an_arrow_end_lies_on_the_outline_of_its_shape() -> None:
    box = el.shape("rectangle", x=0, y=0, width=200, height=100, now_ms=NOW)
    assert el.outline_point(box, (500, 50), 0) == pytest.approx((200, 50))
    ellipse = el.shape("ellipse", x=0, y=0, width=200, height=100, now_ms=NOW)
    assert el.outline_point(ellipse, (100, 500), 5) == pytest.approx((100, 105))
    diamond = el.shape("diamond", x=0, y=0, width=200, height=100, now_ms=NOW)
    px, py = el.outline_point(diamond, (300, 150), 0)
    assert abs(px - 100) / 100 + abs(py - 50) / 50 == pytest.approx(1.0)


def test_text_is_wrapped_to_the_room_it_has() -> None:
    wrapped = el.wrap_text("one two three four five six", 80, 20, el.FONT_HAND)
    assert "\n" in wrapped
    assert max(el.estimate_text(line, 20, el.FONT_HAND)[0] for line in wrapped.split("\n")) <= 80


# --- add, connect, ids ---------------------------------------------------------------


def test_add_and_connect_by_the_ids_the_model_chose() -> None:
    scene, report = run(
        empty_scene(),
        {"do": "add", "type": "box", "id": "a", "label": "Start"},
        {"do": "add", "type": "diamond", "id": "b", "label": "Ready?"},
        {"do": "connect", "from": "a", "to": "b", "label": "then", "id": "ab"},
    )
    index = by_id(scene)
    assert index["a"]["type"] == "rectangle" and index["b"]["type"] == "diamond"
    arrow = index["ab"]
    assert arrow["startBinding"]["elementId"] == "a" and arrow["endBinding"]["elementId"] == "b"
    assert arrow["endArrowhead"] == "arrow" and arrow["startArrowhead"] is None
    assert label_of(scene, "a")["text"] == "Start" and label_of(scene, "ab")["text"] == "then"
    assert all(e["version"] == 1 and e["updated"] == NOW for e in scene["elements"])
    assert len(report) == 3 and "'ab'" in report[2]
    # The arrow starts and ends just outside the shapes.
    start = (arrow["x"], arrow["y"])
    end = (arrow["x"] + arrow["points"][-1][0], arrow["y"] + arrow["points"][-1][1])
    assert start[0] >= index["a"]["x"] + index["a"]["width"]
    assert end[0] < index["b"]["x"] + index["b"]["width"] / 2


def test_things_without_an_id_get_short_readable_ones() -> None:
    scene, _ = run(
        empty_scene(),
        {"do": "add", "items": [{"type": "note", "label": "x"}, {"type": "note", "label": "y"}]},
    )
    assert {"note-1", "note-2"} <= set(by_id(scene))


def test_a_sticky_note_is_a_yellow_filled_box() -> None:
    scene, _ = run(empty_scene(), {"do": "add", "type": "sticky", "id": "n", "label": "Remember"})
    note = by_id(scene)["n"]
    assert note["type"] == "rectangle" and note["backgroundColor"] == el.NOTE_FILL
    assert note["fillStyle"] == "solid" and note["width"] == 200
    assert describe(scene)["elements"][0]["type"] == "note"


def test_auto_placement_flows_in_rows_and_never_overlaps() -> None:
    scene, _ = run(
        empty_scene(),
        {"do": "add", "type": "box", "id": "big", "label": "x", "x": 0, "y": 0, "w": 400, "h": 400},
    )
    scene, _ = run(
        scene, {"do": "add", "items": [{"type": "note", "label": f"Idea {i}"} for i in range(9)]}
    )
    assert_no_overlap(scene)
    notes = [e for e in live(scene) if e["id"].startswith("note-")]
    assert all(n["x"] >= 400 for n in notes)
    assert len({n["y"] for n in notes}) >= 2  # wrapped into rows
    assert all(n["x"] % 20 == 0 and n["y"] % 20 == 0 for n in notes)


def test_placement_beside_an_element_and_inside_a_frame() -> None:
    scene, _ = run(
        empty_scene(),
        {"do": "add", "type": "box", "id": "a", "label": "A", "x": 0, "y": 0},
        {"do": "add", "type": "note", "id": "r", "label": "right", "right_of": "a"},
        {"do": "add", "type": "note", "id": "d", "label": "below", "below": "a"},
        {"do": "add", "type": "note", "id": "n", "label": "near", "near": "a"},
    )
    index = by_id(scene)
    assert index["r"]["x"] >= index["a"]["x"] + index["a"]["width"]
    assert index["d"]["y"] >= index["a"]["y"] + index["a"]["height"]
    assert_no_overlap(scene)
    scene, _ = run(
        scene,
        {
            "do": "add",
            "type": "frame",
            "id": "f",
            "name": "Ideas",
            "x": 0,
            "y": 600,
            "w": 300,
            "h": 200,
        },
        {
            "do": "add",
            "items": [{"type": "note", "label": f"{i}", "inside": "f"} for i in range(4)],
        },
    )
    index = by_id(scene)
    inside = [e for e in live(scene) if e.get("frameId") == "f" and e["type"] == "rectangle"]
    assert len(inside) == 4
    frame = index["f"]
    for e in inside:
        x0, y0, x1, y1 = rect(e)
        assert frame["x"] <= x0 and x1 <= frame["x"] + frame["width"]
        assert frame["y"] <= y0 and y1 <= frame["y"] + frame["height"]
    assert frame["height"] > 200  # it grew to hold them


def test_lines_drawings_texts_and_frames_around_things() -> None:
    scene, _ = run(
        empty_scene(),
        {
            "do": "add",
            "type": "line",
            "id": "l",
            "points": [[0, 0], [100, 50], [200, 0]],
            "style": "dashed",
        },
        {"do": "add", "type": "freedraw", "id": "d", "points": [[0, 200], [10, 210], [30, 205]]},
        {
            "do": "add",
            "type": "text",
            "id": "t",
            "text": "Heading",
            "size": "xl",
            "x": 0,
            "y": -100,
        },
        {"do": "add", "type": "box", "id": "a", "label": "A", "x": 400, "y": 0},
        {"do": "add", "type": "box", "id": "b", "label": "B", "x": 700, "y": 0},
        {"do": "add", "type": "frame", "id": "f", "name": "Pair", "children": ["a", "b"]},
    )
    index = by_id(scene)
    assert index["l"]["strokeStyle"] == "dashed" and index["l"]["startArrowhead"] is None
    assert index["d"]["type"] == "freedraw" and index["d"]["points"][0] == [0, 0]
    assert index["t"]["fontSize"] == 36
    assert index["a"]["frameId"] == "f" and label_of(scene, "a")["frameId"] == "f"
    assert index["f"]["x"] < index["a"]["x"]


def test_a_used_id_is_refused_and_a_deleted_one_is_taken_over() -> None:
    scene, _ = run(empty_scene(), {"do": "add", "type": "box", "id": "a", "label": "A"})
    with pytest.raises(
        NodeError, match=r"actions\[0\] \(add\): the id 'a' is already on the board"
    ):
        apply_actions(scene, [{"do": "add", "type": "box", "id": "a"}], now_ms=NOW)
    scene, _ = run(scene, {"do": "delete", "ids": ["a"]})
    tomb = by_id(scene)["a"]
    assert tomb["isDeleted"] and tomb["version"] == 2
    scene, _ = run(scene, {"do": "add", "type": "ellipse", "id": "a", "label": "Again"})
    back = by_id(scene)["a"]
    assert not back["isDeleted"] and back["type"] == "ellipse" and back["version"] == 3


# --- all or nothing, errors ----------------------------------------------------------------


def test_a_failing_action_changes_nothing_and_names_itself() -> None:
    scene, _ = run(empty_scene(), {"do": "add", "type": "box", "id": "a"})
    before = copy.deepcopy(scene)
    with pytest.raises(NodeError) as caught:
        apply_actions(
            scene,
            [{"do": "add", "type": "box", "id": "b"}, {"do": "connect", "from": "a", "to": "nope"}],
            now_ms=NOW,
        )
    message = str(caught.value)
    assert (
        message.startswith("actions[1] (connect):")
        and "'nope'" in message
        and "Nothing was changed" in message
    )
    assert scene == before


@pytest.mark.parametrize(
    ("action", "words"),
    [
        ({"do": "paint"}, "'do' must be one of"),
        ({"do": "add", "type": "hexagon"}, "unknown type"),
        ({"do": "add", "type": "box", "color": "chartreuse"}, "unknown colour"),
        ({"do": "add", "type": "box", "x": 5}, "both 'x' and 'y'"),
        ({"do": "add", "type": "text"}, "a text needs 'text'"),
        ({"do": "add", "type": "image", "file": "missing"}, "uploaded"),
        ({"do": "add", "type": "box", "id": "has space"}, "not usable"),
        ({"do": "move", "ids": ["a"]}, "'move' needs"),
        ({"do": "align", "ids": ["a"], "to": "left"}, "at least two"),
        ({"do": "layout", "kind": "spiral"}, "'kind' must be one of"),
        ({"do": "mermaid", "source": "sequenceDiagram\n A->>B: hi"}, "flowcharts"),
        ({"do": "update", "id": "a", "type": "ellipse"}, "cannot change its type"),
        ({"do": "add", "type": "box", "link": "javascript:alert(1)"}, "'link' must start"),
    ],
)
def test_errors_say_what_to_fix(action, words) -> None:
    scene, _ = run(empty_scene(), {"do": "add", "type": "box", "id": "a"})
    with pytest.raises(NodeError, match=words):
        apply_actions(scene, [action], now_ms=NOW)


def test_bad_action_lists_are_refused() -> None:
    with pytest.raises(NodeError, match="'actions' must be a list"):
        apply_actions(empty_scene(), [], now_ms=NOW)
    with pytest.raises(NodeError, match=f"at most {MAX_ACTIONS}"):
        apply_actions(empty_scene(), [{"do": "grid"}] * (MAX_ACTIONS + 1), now_ms=NOW)
    with pytest.raises(NodeError, match=r"actions\[0\] must be an object"):
        apply_actions(empty_scene(), ["add"], now_ms=NOW)


def test_every_action_named_in_the_list_exists() -> None:
    from dodaios.nodes.board.ops import _Actions

    assert all(callable(getattr(_Actions, name, None)) for name in ACTIONS)


# --- versions ----------------------------------------------------------------------------


def test_only_what_changed_gets_a_new_version() -> None:
    scene, _ = run(
        empty_scene(),
        {"do": "add", "type": "box", "id": "a", "label": "A", "x": 0, "y": 0},
        {"do": "add", "type": "box", "id": "b", "label": "B", "x": 400, "y": 0},
    )
    nonce_b = by_id(scene)["b"]["versionNonce"]
    later, _ = apply_actions(scene, [{"do": "update", "id": "a", "color": "red"}], now_ms=NOW + 5)
    index = by_id(later)
    assert index["a"]["version"] == 2 and index["a"]["updated"] == NOW + 5
    assert index["a"]["strokeColor"] == "#e03131" and index["a"]["backgroundColor"] == "#fff5f5"
    assert index["b"]["version"] == 1 and index["b"]["versionNonce"] == nonce_b
    assert index["b"]["updated"] == NOW


# --- update, style, delete -------------------------------------------------------------------


def test_update_labels_texts_frames_and_arrows() -> None:
    scene, _ = run(
        empty_scene(),
        {"do": "add", "type": "box", "id": "a", "x": 0, "y": 0},
        {"do": "add", "type": "box", "id": "b", "label": "B", "x": 400, "y": 0},
        {"do": "add", "type": "text", "id": "t", "text": "Old", "x": 0, "y": 300},
        {"do": "add", "type": "frame", "id": "f", "name": "F", "x": 0, "y": 600},
        {"do": "connect", "from": "a", "to": "b", "id": "ab"},
    )
    long = "A much longer label that will need several lines inside this small box to fit"
    scene, _ = run(
        scene,
        {"do": "update", "id": "a", "label": long},
        {"do": "update", "id": "b", "label": ""},
        {"do": "update", "id": "t", "text": "New", "size": "l", "font": "code"},
        {"do": "update", "id": "f", "name": "Renamed"},
        {"do": "update", "id": "ab", "label": "flows", "style": "dotted", "arrow": "both"},
    )
    index = by_id(scene)
    label = label_of(scene, "a")
    assert label["originalText"] == long and "\n" in label["text"]
    assert index["a"]["height"] > 80  # grew for the label
    assert label_of(scene, "b") is None
    assert (
        index["t"]["text"] == "New"
        and index["t"]["fontSize"] == 28
        and index["t"]["fontFamily"] == 8
    )
    assert index["f"]["name"] == "Renamed"
    assert index["ab"]["strokeStyle"] == "dotted" and index["ab"]["startArrowhead"] == "arrow"
    assert label_of(scene, "ab")["text"] == "flows"


def test_a_label_can_name_the_thing() -> None:
    scene, _ = run(empty_scene(), {"do": "add", "type": "box", "id": "a", "label": "Payments"})
    scene, _ = run(scene, {"do": "style", "ids": ["Payments"], "color": "green", "font": "normal"})
    assert by_id(scene)["a"]["strokeColor"] == "#2f9e44"
    assert label_of(scene, "a")["fontFamily"] == 6


def test_delete_takes_the_arrows_and_a_frame_its_contents() -> None:
    scene, _ = run(
        empty_scene(),
        {"do": "add", "type": "box", "id": "a", "x": 0, "y": 0},
        {"do": "add", "type": "box", "id": "b", "label": "B", "x": 400, "y": 0},
        {"do": "add", "type": "box", "id": "c", "x": 800, "y": 0},
        {"do": "connect", "from": "a", "to": "b", "id": "ab"},
        {"do": "connect", "from": "b", "to": "c", "id": "bc"},
        {"do": "frame", "ids": ["c"], "name": "Box", "frame_id": "f"},
    )
    gone, report = run(scene, {"do": "delete", "ids": ["b"]})
    index = by_id(gone)
    assert index["b"]["isDeleted"] and index["ab"]["isDeleted"] and index["bc"]["isDeleted"]
    assert label_of(gone, "b") is None
    assert "deleted 3" in report[0]
    kept, _ = run(scene, {"do": "delete", "ids": ["b"], "keep_arrows": True})
    index = by_id(kept)
    assert not index["ab"]["isDeleted"] and index["ab"]["endBinding"] is None
    framed, _ = run(scene, {"do": "delete", "ids": ["f"]})
    assert by_id(framed)["c"]["isDeleted"]
    released, _ = run(scene, {"do": "delete", "ids": ["f"], "keep_contents": True})
    assert not by_id(released)["c"]["isDeleted"] and by_id(released)["c"]["frameId"] is None


def test_clear_background_grid_lock() -> None:
    scene, _ = run(
        empty_scene(),
        {"do": "add", "type": "box", "id": "a"},
        {"do": "lock"},
        {"do": "background", "color": "yellow"},
        {"do": "grid", "on": True},
    )
    assert by_id(scene)["a"]["locked"] and scene["appState"]["gridModeEnabled"]
    assert scene["appState"]["viewBackgroundColor"] == "#fff9db"
    scene, _ = run(scene, {"do": "unlock", "ids": ["a"]}, {"do": "clear"})
    assert not live(scene) and not by_id(scene)["a"]["locked"]


# --- moving and arranging ---------------------------------------------------------------------


def _pair_scene() -> dict[str, Any]:
    scene, _ = run(
        empty_scene(),
        {"do": "add", "type": "box", "id": "a", "label": "A", "x": 0, "y": 0},
        {"do": "add", "type": "box", "id": "b", "label": "B", "x": 400, "y": 0},
        {"do": "connect", "from": "a", "to": "b", "id": "ab", "label": "go"},
    )
    return scene


def test_move_carries_the_label_and_the_arrow_follows() -> None:
    scene = _pair_scene()
    moved, _ = run(scene, {"do": "move", "ids": ["b"], "by": [0, 300]})
    index = by_id(moved)
    assert index["b"]["y"] == 300 and label_of(moved, "b")["y"] > 300
    arrow = index["ab"]
    end_y = arrow["y"] + arrow["points"][-1][1]
    assert end_y > 250  # re-routed down to the box
    assert index["ab"]["version"] == 2
    together, _ = run(scene, {"do": "move", "ids": ["a", "b"], "to": [100, 100]})
    index = by_id(together)
    assert (index["a"]["x"], index["a"]["y"]) == (100, 100)
    assert index["ab"]["points"] == by_id(scene)["ab"]["points"]  # moved as it is
    beside, _ = run(scene, {"do": "move", "ids": ["a"], "below": "b"})
    assert by_id(beside)["a"]["y"] >= 80


def test_moving_a_frame_moves_its_contents() -> None:
    scene, _ = run(
        empty_scene(),
        {"do": "add", "type": "frame", "id": "f", "x": 0, "y": 0, "w": 400, "h": 300},
        {"do": "add", "type": "note", "id": "n", "label": "in", "inside": "f"},
    )
    x = by_id(scene)["n"]["x"]
    moved, _ = run(scene, {"do": "move", "ids": ["f"], "by": [500, 0]})
    assert by_id(moved)["n"]["x"] == x + 500


def test_resize_align_distribute() -> None:
    scene, _ = run(
        empty_scene(),
        {"do": "add", "type": "box", "id": "a", "label": "A", "x": 0, "y": 0},
        {"do": "add", "type": "box", "id": "b", "label": "B", "x": 300, "y": 37},
        {"do": "add", "type": "box", "id": "c", "label": "C", "x": 1000, "y": 90},
        {"do": "add", "type": "text", "id": "t", "text": "Title", "x": 0, "y": 400},
    )
    scene, _ = run(
        scene,
        {"do": "resize", "ids": ["a"], "w": 240, "h": 120},
        {"do": "resize", "ids": ["t"], "scale": 2},
        {"do": "align", "ids": ["a", "b", "c"], "to": "top"},
        {"do": "distribute", "ids": ["a", "b", "c"], "axis": "horizontal"},
    )
    index = by_id(scene)
    assert (index["a"]["width"], index["a"]["height"]) == (240, 120)
    assert index["t"]["fontSize"] == 40
    assert index["a"]["y"] == index["b"]["y"] == index["c"]["y"] == 0
    gap1 = index["b"]["x"] - (index["a"]["x"] + index["a"]["width"])
    gap2 = index["c"]["x"] - (index["b"]["x"] + index["b"]["width"])
    assert gap1 == pytest.approx(gap2)


def test_group_and_ungroup() -> None:
    scene = _pair_scene()
    scene, report = run(scene, {"do": "group", "ids": ["a", "b"]})
    group = by_id(scene)["a"]["groupIds"][-1]
    assert group in by_id(scene)["b"]["groupIds"] and group in label_of(scene, "a")["groupIds"]
    assert group in report[0]
    scene, _ = run(scene, {"do": "ungroup", "ids": ["a"]})
    assert by_id(scene)["a"]["groupIds"] == [] and by_id(scene)["b"]["groupIds"] == []


def test_frame_action_wraps_and_puts_into() -> None:
    scene = _pair_scene()
    scene, _ = run(scene, {"do": "add", "type": "box", "id": "c", "x": 0, "y": 600})
    scene, _ = run(scene, {"do": "frame", "ids": ["a", "b"], "name": "Pair", "frame_id": "f"})
    index = by_id(scene)
    assert index["a"]["frameId"] == index["ab"]["frameId"] == "f"
    scene, _ = run(scene, {"do": "frame", "ids": ["c"], "into": "f"})
    frame, c = by_id(scene)["f"], by_id(scene)["c"]
    assert c["frameId"] == "f" and frame["y"] + frame["height"] >= c["y"] + c["height"]
    with pytest.raises(NodeError, match="frame cannot go into another frame"):
        apply_actions(
            scene,
            [
                {"do": "add", "type": "frame", "id": "g", "x": 2000, "y": 0},
                {"do": "frame", "ids": ["g"], "into": "f"},
            ],
            now_ms=NOW,
        )


def test_order_front_and_back() -> None:
    scene = _pair_scene()
    scene, _ = run(scene, {"do": "order", "ids": ["a"], "to": "front"})
    order = [e["id"] for e in scene["elements"] if not (e["type"] == "text")]
    assert order[-1] == "a"
    scene, _ = run(scene, {"do": "order", "ids": ["a"], "to": "back"})
    assert scene["elements"][0]["id"] == "a"


def _chain(n: int) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = [
        {
            "do": "add",
            "type": "box",
            "id": f"s{i}",
            "label": f"Step {i}",
            "x": (i * 137) % 500,
            "y": (i * 291) % 700,
        }
        for i in range(n)
    ]
    actions.append({"do": "connect", "chain": [f"s{i}" for i in range(n)]})
    return actions


def test_layout_flow_reads_along_the_arrows() -> None:
    scene, _ = run(empty_scene(), *_chain(5))
    scene, _ = run(scene, {"do": "layout", "kind": "flow", "direction": "LR"})
    xs = [by_id(scene)[f"s{i}"]["x"] for i in range(5)]
    assert xs == sorted(xs) and len(set(xs)) == 5
    assert_no_overlap(scene)
    down, _ = run(scene, {"do": "layout", "kind": "flow", "direction": "TB"})
    ys = [by_id(down)[f"s{i}"]["y"] for i in range(5)]
    assert ys == sorted(ys)


def test_layout_tree_mindmap_and_grid_do_not_overlap() -> None:
    actions: list[dict[str, Any]] = [
        {"do": "add", "type": "box", "id": "root", "label": "Root", "x": 0, "y": 0}
    ]
    for i in range(6):
        actions.append(
            {"do": "add", "type": "box", "id": f"c{i}", "label": f"Child {i}", "x": 0, "y": 0 + i}
        )
        actions.append({"do": "connect", "from": "root", "to": f"c{i}"})
    # Things placed on top of each other on purpose: the layout sorts them out.
    scene, _ = apply_actions(empty_scene(), [actions[0], {"do": "grid"}], now_ms=NOW)
    scene, _ = run(scene, *[a for a in actions[1:] if a["do"] == "add"])
    scene, _ = run(scene, *[a for a in actions[1:] if a["do"] == "connect"])
    tree, _ = run(scene, {"do": "layout", "kind": "tree", "root": "root"})
    assert_no_overlap(tree)
    index = by_id(tree)
    assert all(index[f"c{i}"]["y"] > index["root"]["y"] for i in range(6))
    mind, _ = run(scene, {"do": "layout", "kind": "mindmap", "root": "root"})
    assert_no_overlap(mind)
    index = by_id(mind)
    centre = index["root"]["x"]
    assert any(index[f"c{i}"]["x"] < centre for i in range(6)) and any(
        index[f"c{i}"]["x"] > centre for i in range(6)
    )
    grid, _ = run(scene, {"do": "layout", "kind": "grid", "columns": 3})
    assert_no_overlap(grid)


def test_layout_inside_a_frame_fits_the_frame() -> None:
    scene, _ = run(
        empty_scene(),
        {"do": "add", "type": "frame", "id": "f", "x": 0, "y": 0, "w": 1200, "h": 900},
        *[{"do": "add", "type": "note", "label": f"N{i}", "inside": "f"} for i in range(4)],
    )
    scene, _ = run(scene, {"do": "layout", "kind": "grid", "frame": "f", "columns": 2})
    frame = by_id(scene)["f"]
    assert frame["width"] < 1200 and frame["height"] < 900
    assert_no_overlap(scene)


def test_a_heading_stays_on_top_of_a_layout() -> None:
    scene, _ = run(
        empty_scene(),
        *_chain(3),
        {
            "do": "add",
            "type": "text",
            "id": "h",
            "text": "The process",
            "size": "xl",
            "x": 900,
            "y": 900,
        },
    )
    scene, _ = run(scene, {"do": "layout"})
    index = by_id(scene)
    assert all(index["h"]["y"] + index["h"]["height"] <= index[f"s{i}"]["y"] for i in range(3))


# --- diagrams and mermaid ---------------------------------------------------------------------


def test_diagram_action_places_a_block_beside_the_content() -> None:
    scene, _ = run(
        empty_scene(), {"do": "add", "type": "box", "id": "a", "x": 0, "y": 0, "w": 400, "h": 400}
    )
    scene, report = run(
        scene,
        {
            "do": "diagram",
            "nodes": [{"id": "a", "label": "Taken"}, {"id": "b", "label": "B"}],
            "edges": [{"from": "a", "to": "b"}],
            "groups": [{"id": "g", "label": "G", "nodes": ["a", "b"]}],
        },
    )
    assert "a->a-2" in report[0]
    index = by_id(scene)
    assert index["a-2"]["frameId"] == "g" and index["a-2:b"]["frameId"] == "g"
    assert index["g"]["x"] > 400
    assert_no_overlap(scene)


def test_mermaid_action_draws_the_flowchart() -> None:
    scene, report = run(
        empty_scene(),
        {
            "do": "mermaid",
            "source": "flowchart TD\n  A[Ask] --> B{OK?}\n  B -->|yes| C((Done))\n  B -- no --> A",
        },
    )
    index = by_id(scene)
    assert index["B"]["type"] == "diamond" and index["C"]["type"] == "ellipse"
    assert index["C"]["width"] == index["C"]["height"]
    assert label_of(scene, "B:C")["text"] == "yes"
    assert index["A"]["y"] < index["B"]["y"] < index["C"]["y"]
    assert "3 nodes, 3 arrows" in report[0]


# --- describe ------------------------------------------------------------------------------


def test_describe_folds_labels_and_names_connections() -> None:
    scene = _pair_scene()
    scene, _ = run(scene, {"do": "add", "type": "note", "id": "n", "label": "Remember the budget"})
    reading = describe(scene)
    assert reading["counts"] == {"box": 2, "arrow": 1, "note": 1}
    entries = {e["id"]: e for e in reading["elements"]}
    assert set(entries) == {"a", "b", "ab", "n"}
    assert entries["a"]["label"] == "A" and entries["a"]["stroke"] == "blue"
    assert (
        entries["ab"]["from"] == "a"
        and entries["ab"]["to"] == "b"
        and entries["ab"]["label"] == "go"
    )
    assert entries["n"]["fill"] == "yellow" and len(entries["n"]["box"]) == 4
    assert [e["id"] for e in describe(scene, query="budget")["elements"]] == ["n"]
    only = describe(scene, ids=["a", "zzz"])
    assert [e["id"] for e in only["elements"]] == ["a"] and only["not_found"] == ["zzz"]
    raw = describe(scene, ids=["a"], raw=True)["raw"]
    assert [e["type"] for e in raw] == ["rectangle", "text"]


def test_describe_of_an_empty_or_odd_scene() -> None:
    assert describe(empty_scene())["elements"] == []
    assert describe({})["bounds"] is None
