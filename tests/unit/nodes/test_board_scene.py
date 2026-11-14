"""A whiteboard's scene: validation, the merge of two copies, and its bounds."""

from __future__ import annotations

import copy
import json
import math
from typing import Any

import pytest

from dodaios.nodes.board.scene import (
    KEEP_TOMBSTONES,
    MAX_ELEMENTS,
    MAX_TOMBSTONES,
    TOMBSTONE_AGE_MS,
    empty_scene,
    is_scene,
    live_elements,
    merge_scene,
    normalize_scene,
    rotated_box,
    scene_bounds,
)
from dodaios.nodes.types import NodeError

NOW_MS = 1_731_500_000_000


def _el(ident: str, kind: str = "rectangle", **fields: Any) -> dict[str, Any]:
    return {"id": ident, "type": kind, "x": 0, "y": 0, "width": 100, "height": 50, **fields}


def _scene(*elements: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return normalize_scene({"format": "scene", "elements": list(elements), **extra})


# ------------------------------------------------------------------ normalize


def test_an_empty_scene_is_a_scene_with_defaults() -> None:
    assert normalize_scene({"elements": []}) == empty_scene()
    assert empty_scene() == {
        "format": "scene",
        "elements": [],
        "appState": {"viewBackgroundColor": "#ffffff", "gridModeEnabled": False},
        "files": {},
    }
    assert is_scene({"format": "scene"}) and is_scene({"elements": []})
    assert not is_scene({"items": []}) and not is_scene([])


@pytest.mark.parametrize("raw", [None, [], "scene", {"elements": "x"}, {"elements": {}}])
def test_something_that_is_no_scene_is_refused_with_what_to_send(raw: Any) -> None:
    with pytest.raises(NodeError, match="whiteboard tool"):
        normalize_scene(raw)


def test_every_kept_type_gets_all_its_fields() -> None:
    scene = _scene(
        _el("r", "rectangle"),
        _el("e", "ellipse"),
        _el("d", "diamond"),
        _el("t", "text", text="Hi"),
        _el("a", "arrow", points=[[0, 0], [10, 10]]),
        _el("l", "line", points=[[0, 0], [10, 0]]),
        _el("f", "freedraw", points=[[0, 0], [1, 1]], pressures=[0.5, 0.7]),
        _el("i", "image", fileId="abc"),
        _el("fr", "frame", name="Group"),
    )
    by_id = {element["id"]: element for element in scene["elements"]}
    base = {
        "id", "type", "x", "y", "width", "height", "angle", "strokeColor", "backgroundColor",
        "fillStyle", "strokeWidth", "strokeStyle", "roughness", "opacity", "groupIds", "frameId",
        "roundness", "seed", "version", "versionNonce", "index", "isDeleted", "boundElements",
        "updated", "link", "locked",
    }  # fmt: skip
    assert set(by_id["r"]) == base
    assert set(by_id["t"]) == base | {
        "text", "originalText", "fontSize", "fontFamily", "textAlign", "verticalAlign",
        "containerId", "autoResize", "lineHeight",
    }  # fmt: skip
    linear = {"points", "lastCommittedPoint", "startBinding", "endBinding", "startArrowhead",
              "endArrowhead"}  # fmt: skip
    assert set(by_id["a"]) == base | linear | {"elbowed"}
    assert set(by_id["l"]) == base | linear
    assert set(by_id["f"]) == base | {
        "points",
        "pressures",
        "simulatePressure",
        "lastCommittedPoint",
    }
    assert set(by_id["i"]) == base | {"fileId", "status", "scale", "crop"}
    assert set(by_id["fr"]) == base | {"name"}
    assert by_id["a"]["endArrowhead"] == "arrow" and by_id["a"]["startArrowhead"] is None
    assert by_id["l"]["endArrowhead"] is None
    assert by_id["t"]["fontFamily"] == 5 and by_id["t"]["lineHeight"] == 1.25
    assert by_id["t"]["originalText"] == "Hi"


def test_normalize_is_idempotent_and_json_safe() -> None:
    raw = {
        "elements": [
            _el("r", angle=7.5, x=1.23456, strokeWidth=99, opacity=150, roughness=-3),
            _el("t", "text", text="a\r\nb\x00c", fontFamily=6, fontSize=0),
            _el("a", "arrow", points=[[0, 0], [1e12, float("nan")], [3, 4]], elbowed=True),
            _el("f", "freedraw", points=[[0, 0]] * 3, pressures=[2, -1, "x"]),
        ],
        "appState": {"viewBackgroundColor": "#ABC", "gridModeEnabled": True, "zoom": 3},
        "files": {"abc": {"id": "abc", "mimeType": "image/png", "created": 5, "dataURL": "data:"}},
    }
    once = normalize_scene(raw)
    assert normalize_scene(copy.deepcopy(once)) == once
    json.dumps(once, allow_nan=False)
    rect, text, arrow, stroke = once["elements"]
    assert rect["x"] == 1.23 and 0 <= rect["angle"] < 2 * math.pi
    assert rect["strokeWidth"] == 64 and rect["opacity"] == 100 and rect["roughness"] == 0
    assert text["text"] == "a\nbc" and text["fontSize"] == 1 and text["lineHeight"] == 1.35
    assert arrow["points"] == [[0, 0], [3, 4]]  # the point with no finite number is gone
    assert arrow["fixedSegments"] is None and arrow["startIsSpecial"] is None
    assert stroke["pressures"] == [1, 0, 0.5]
    assert once["appState"] == {"viewBackgroundColor": "#abc", "gridModeEnabled": True}
    assert once["files"] == {"abc": {"id": "abc", "mimeType": "image/png", "created": 5}}


@pytest.mark.parametrize(
    ("value", "kept"),
    [
        ("#1e1e1e", "#1e1e1e"),
        ("#FFF", "#fff"),
        ("#ffec99aa", "#ffec99aa"),
        ("transparent", "transparent"),
        ("Red", "red"),
        ("url(#x)", "#1e1e1e"),
        ('#fff" onload="x', "#1e1e1e"),
        ("rgb(1,2,3)", "#1e1e1e"),
        ("expression(alert(1))", "#1e1e1e"),
        (12, "#1e1e1e"),
    ],
)
def test_a_colour_is_hex_or_a_known_word(value: Any, kept: str) -> None:
    assert _scene(_el("r", strokeColor=value))["elements"][0]["strokeColor"] == kept


@pytest.mark.parametrize(
    ("link", "kept"),
    [
        ("https://example.com/a", "https://example.com/a"),
        ("mailto:a@b.c", "mailto:a@b.c"),
        ("javascript:alert(1)", None),
        ("data:text/html,x", None),
        ("https://x\n.com", None),
        ("https://" + "a" * 3000, None),
    ],
)
def test_a_link_is_kept_only_to_the_web_or_mail(link: str, kept: str | None) -> None:
    assert _scene(_el("r", link=link))["elements"][0]["link"] == kept


def test_web_loading_types_and_the_selection_are_dropped_quietly() -> None:
    scene = _scene(
        _el("a", "embeddable", link="https://x"),
        _el("b", "iframe"),
        _el("c", "magicframe"),
        _el("d", "selection"),
        _el("e"),
    )
    assert [element["id"] for element in scene["elements"]] == ["e"]


def test_an_unknown_type_or_a_bad_id_names_the_element() -> None:
    with pytest.raises(NodeError, match=r"elements\[1\].*'box'.*rectangle"):
        normalize_scene({"elements": [_el("a"), _el("b", "box")]})
    with pytest.raises(NodeError, match=r"elements\[0\] needs an 'id'"):
        normalize_scene({"elements": [_el("a b")]})
    with pytest.raises(NodeError, match=r"elements\[0\] must be an object"):
        normalize_scene({"elements": ["rect"]})


def test_a_repeated_id_keeps_the_first_element() -> None:
    scene = _scene(_el("a", x=1), _el("a", x=2))
    assert [(element["id"], element["x"]) for element in scene["elements"]] == [("a", 1)]


def test_unknown_fields_are_dropped_and_small_custom_data_is_kept() -> None:
    element = _scene(_el("a", customData={"tag": "x", "n": [1, 2]}, onclick="x", html="<b>"))[
        "elements"
    ][0]
    assert not {"onclick", "html"} & set(element)
    assert element["customData"] == {"n": [1, 2], "tag": "x"}
    for bad in ({"x": float("nan")}, {"x": "y" * 5_000}, ["list"], "text"):
        assert "customData" not in _scene(_el("a", customData=bad))["elements"][0]


def test_bindings_and_bound_elements_are_cleaned() -> None:
    scene = _scene(
        _el(
            "r",
            boundElements=[
                {"id": "t", "type": "text"},
                {"id": "t", "type": "text"},
                {"id": "x", "type": "image"},
                "junk",
            ],
            frameId="bad id",
            groupIds=["g1", "g1", "bad id", 3],
            roundness={"type": 3, "value": -4},
            index="a0V",
        ),
        _el(
            "a",
            "arrow",
            startBinding={"elementId": "r", "focus": 5, "gap": -2, "fixedPoint": [0.5, 9e9]},
            endBinding={"elementId": ""},
            startArrowhead="dot",
            endArrowhead="rocket",
        ),
    )
    rect, arrow = scene["elements"]
    assert rect["boundElements"] == [{"id": "t", "type": "text"}]
    assert rect["frameId"] is None and rect["groupIds"] == ["g1"]
    assert rect["roundness"] == {"type": 3, "value": 0} and rect["index"] == "a0V"
    assert arrow["startBinding"] == {
        "elementId": "r",
        "focus": 1,
        "gap": 0,
        "fixedPoint": [0.5, 10],
    }
    assert arrow["endBinding"] is None
    assert (arrow["startArrowhead"], arrow["endArrowhead"]) == ("dot", None)


def test_files_keep_only_pictures_whose_id_matches_their_key() -> None:
    scene = _scene(
        files={
            "a": {"id": "a", "mimeType": "image/webp", "created": 1, "lastRetrieved": 2},
            "b": {"id": "c", "mimeType": "image/png"},
            "svg": {"id": "svg", "mimeType": "image/svg+xml"},
            "bad/id": {"id": "bad/id", "mimeType": "image/png"},
        }
    )
    assert scene["files"] == {
        "a": {"id": "a", "mimeType": "image/webp", "created": 1, "lastRetrieved": 2}
    }


def test_an_image_keeps_its_flip_and_crop() -> None:
    crop = {"x": 1, "y": 2, "width": 30, "height": 40, "naturalWidth": 100, "naturalHeight": 80}
    image = _scene(_el("i", "image", fileId="f", scale=[-0.3, 1], crop=crop, status="saved"))[
        "elements"
    ][0]
    assert image["scale"] == [-1, 1] and image["crop"] == crop and image["status"] == "saved"
    assert _scene(_el("i", "image", crop={"x": 1}))["elements"][0]["crop"] is None


def test_too_many_live_elements_is_refused_but_tombstones_do_not_count() -> None:
    many = [_el(f"e{n}") for n in range(MAX_ELEMENTS + 1)]
    with pytest.raises(NodeError, match="at most"):
        normalize_scene({"elements": many})
    dead = [_el(f"d{n}", isDeleted=True, updated=n) for n in range(MAX_TOMBSTONES + 3)]
    scene = normalize_scene({"elements": [*many[:-1], *dead]})
    assert len(live_elements(scene)) == MAX_ELEMENTS
    kept_dead = [element["id"] for element in scene["elements"] if element["isDeleted"]]
    assert len(kept_dead) == MAX_TOMBSTONES and "d0" not in kept_dead


def test_a_text_is_clipped_and_keeps_its_line_breaks() -> None:
    text = _scene(_el("t", "text", text="x" * 30_000 + "\n"))["elements"][0]["text"]
    assert len(text) == 20_000


# --------------------------------------------------------------------- merge


def test_the_higher_version_wins_and_a_tie_goes_to_the_lower_nonce() -> None:
    stored = _scene(
        _el("a", x=1, version=3, versionNonce=9),
        _el("b", x=1, version=2, versionNonce=5),
        _el("c", x=1, version=2, versionNonce=1),
    )
    incoming = _scene(
        _el("a", x=2, version=4, versionNonce=9),
        _el("b", x=2, version=2, versionNonce=4),
        _el("c", x=2, version=2, versionNonce=7),
    )
    merged, stored_newer = merge_scene(stored, incoming, now_ms=NOW_MS)
    assert {element["id"]: element["x"] for element in merged["elements"]} == {
        "a": 2,
        "b": 2,
        "c": 1,
    }
    assert stored_newer


def test_an_incoming_scene_that_is_newer_everywhere_needs_no_answer() -> None:
    stored = _scene(_el("a", version=1), _el("b", version=1))
    incoming = _scene(_el("b", version=2), _el("a", version=1), _el("c"))
    merged, stored_newer = merge_scene(stored, incoming, now_ms=NOW_MS)
    assert not stored_newer
    assert merged["elements"] == incoming["elements"]


def test_what_only_the_stored_scene_has_stays_after_its_predecessor() -> None:
    stored = _scene(_el("x0"), _el("a"), _el("x1"), _el("x2"), _el("b"), _el("x3"))
    incoming = _scene(_el("b"), _el("a"), _el("n"))
    merged, stored_newer = merge_scene(stored, incoming, now_ms=NOW_MS)
    assert [element["id"] for element in merged["elements"]] == [
        "x0", "b", "x3", "a", "x1", "x2", "n",
    ]  # fmt: skip
    assert stored_newer


def test_a_tombstone_only_on_disk_does_not_ask_the_editor_to_reload() -> None:
    stored = _scene(_el("a"), _el("gone", isDeleted=True, version=2))
    incoming = _scene(_el("a"))
    merged, stored_newer = merge_scene(stored, incoming, now_ms=NOW_MS)
    assert not stored_newer
    assert [element["id"] for element in merged["elements"]] == ["a", "gone"]


def test_a_deletion_on_either_side_is_not_undone_by_an_older_copy() -> None:
    stored = _scene(_el("a", isDeleted=True, version=5))
    incoming = _scene(_el("a", version=4))
    merged, stored_newer = merge_scene(stored, incoming, now_ms=NOW_MS)
    assert merged["elements"][0]["isDeleted"] and stored_newer
    merged, stored_newer = merge_scene(incoming, stored, now_ms=NOW_MS)
    assert merged["elements"][0]["isDeleted"] and not stored_newer


def test_files_are_joined_and_the_incoming_view_state_wins() -> None:
    picture = {"id": "p", "mimeType": "image/png", "created": 1}
    other = {"id": "q", "mimeType": "image/gif", "created": 2}
    stored = _scene(files={"p": picture}, appState={"viewBackgroundColor": "#000"})
    incoming = _scene(files={"q": other}, appState={"viewBackgroundColor": "#fff"})
    merged, stored_newer = merge_scene(stored, incoming, now_ms=NOW_MS)
    assert merged["files"] == {"q": other, "p": picture}
    assert merged["appState"]["viewBackgroundColor"] == "#fff"
    assert stored_newer


def test_old_tombstones_beyond_the_keep_are_pruned_young_ones_stay() -> None:
    old = NOW_MS - TOMBSTONE_AGE_MS - 100_000
    dead = [_el(f"d{n}", isDeleted=True, updated=old + n) for n in range(KEEP_TOMBSTONES + 5)]
    young = [_el(f"y{n}", isDeleted=True, updated=NOW_MS) for n in range(3)]
    incoming = _scene(_el("a"), *dead, *young)
    merged, _ = merge_scene(empty_scene(), incoming, now_ms=NOW_MS)
    ids = {element["id"] for element in merged["elements"]}
    assert {"d0", "d1", "d2", "d3", "d4", "d5", "d6", "d7"}.isdisjoint(ids)
    assert {"a", "y0", "y1", "y2", "d8"} <= ids
    assert sum(1 for element in merged["elements"] if element["isDeleted"]) == KEEP_TOMBSTONES


def test_the_merged_scene_is_normalized() -> None:
    stored = _scene(_el("a", version=3), _el("t", "text", text="x"))
    incoming = _scene(_el("a", version=2), _el("n"))
    merged, _ = merge_scene(stored, incoming, now_ms=NOW_MS)
    assert normalize_scene(merged) == merged


# -------------------------------------------------------------------- bounds


def test_bounds_cover_live_elements_points_and_rotation() -> None:
    elements = _scene(
        _el("r", x=10, y=20, width=100, height=50),
        _el("a", "arrow", x=200, y=0, points=[[0, 0], [50, -40]]),
        _el("gone", x=-9_999, isDeleted=True),
    )["elements"]
    assert scene_bounds(elements) == (10, -40, 250, 70)
    assert scene_bounds([]) == (0, 0, 0, 0)
    turned = _scene(_el("r", x=0, y=0, width=100, height=20, angle=math.pi / 2))["elements"][0]
    x0, y0, x1, y1 = rotated_box(turned)
    assert (round(x0), round(y0), round(x1), round(y1)) == (40, -40, 60, 60)
