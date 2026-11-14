"""The whiteboard node type: its spec is the editor's scene, the older grammar
still works, its card and its starter."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import pytest

from dodaios.nodes.board import files as board_files
from dodaios.nodes.board.scene import empty_scene, normalize_scene
from dodaios.nodes.kinds import kind_of, whiteboard
from dodaios.nodes.kinds.whiteboard import (
    EXAMPLE,
    GUIDE,
    PREVIEW_COLORS,
    normalize,
    preview,
    render,
    render_in_run,
    starter,
)
from dodaios.nodes.model import Node
from dodaios.nodes.types import NodeError

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d4944415478da63fcff9f010005fe02fea7d6a4b90000000049454e44ae426082"
)


def _el(ident: str, kind: str = "rectangle", **fields: Any) -> dict[str, Any]:
    return {"id": ident, "type": kind, "x": 0, "y": 0, "width": 100, "height": 50, **fields}


def _scene(*elements: dict[str, Any]) -> dict[str, Any]:
    return {"format": "scene", "elements": list(elements)}


@pytest.fixture
def fake_convert(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """A stand-in for board-ops' converter; returns the specs it was given."""
    seen: list[dict[str, Any]] = []

    def legacy_to_scene(spec: Any, *, store_image: Any = None) -> dict[str, Any]:
        if not isinstance(spec, dict) or not spec.get("items"):
            raise NodeError('A whiteboard needs "items".')
        seen.append(spec)
        elements = [
            _el(f"n{index}", "text", y=index * 60, text=str(item.get("text", "")))
            for index, item in enumerate(spec["items"])
        ]
        return {"format": "scene", "elements": elements}

    module = types.ModuleType("dodaios.nodes.board.convert")
    module.legacy_to_scene = legacy_to_scene  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "dodaios.nodes.board.convert", module)
    return seen


def test_the_kind_is_registered_with_the_page_that_has_pictures() -> None:
    kind = kind_of("whiteboard")
    assert kind.render_in_run is render_in_run
    assert kind.normalize is normalize and kind.starter is starter
    assert kind_of("canvas") is kind


def test_a_scene_is_normalized_by_the_scene_rules() -> None:
    raw = _scene(_el("r", strokeColor="javascript:x"), _el("x", "embeddable"))
    clean = normalize(raw)
    assert clean == normalize_scene(raw) == normalize(clean)
    assert [element["id"] for element in clean["elements"]] == ["r"]
    assert normalize({"elements": []}) == empty_scene()


def test_the_older_grammar_becomes_a_scene(fake_convert: list[dict[str, Any]]) -> None:
    clean = normalize(EXAMPLE)
    assert fake_convert == [EXAMPLE]
    assert clean["format"] == "scene"
    assert [element["text"] for element in clean["elements"]] == [
        item["text"] for item in EXAMPLE["items"]
    ]
    with pytest.raises(NodeError, match="items"):
        normalize({"items": []})


@pytest.mark.parametrize("spec", [{}, {"notes": []}, [], "board", None])
def test_anything_else_is_refused_with_what_to_send(spec: Any) -> None:
    with pytest.raises(NodeError, match="whiteboard tool"):
        normalize(spec)


def test_the_starter_is_an_empty_board() -> None:
    assert starter("Board", "de") == empty_scene()
    assert normalize(starter("Board", "en")) == empty_scene()


def test_the_guide_points_to_the_tool_and_names_the_scene() -> None:
    assert "whiteboard tool" in GUIDE and '"format": "scene"' in GUIDE
    assert "rectangle" in GUIDE and "freedraw" in GUIDE
    assert '"items"' in GUIDE  # the older grammar still works with node create


def _card_node(scene: dict[str, Any]) -> Node:
    return Node(
        id="0123456789ab",
        type="whiteboard",
        title="Board",
        spec=normalize(scene),
        slug="s",
        page_path="p.html",
        created_at=0,
        updated_at=0,
    )


def test_the_card_shows_the_first_texts_in_reading_order_with_note_colours() -> None:
    spec = normalize(
        _scene(
            _el(
                "box",
                x=0,
                y=200,
                backgroundColor="#a5d8ff",
                boundElements=[{"id": "l1", "type": "text"}],
            ),
            _el("l1", "text", x=10, y=210, text="Inside a blue box", containerId="box"),
            _el("free", "text", x=0, y=0, text="Heading on top"),
            _el("note", x=300, y=200, backgroundColor="#ffec99"),
            _el("l2", "text", x=310, y=210, text="  A   yellow note  ", containerId="note"),
            _el("plain", x=0, y=400),
            _el("l3", "text", x=0, y=410, text="An empty box", containerId="plain"),
            _el("red", "text", x=0, y=600, text="Red words", strokeColor="#e03131"),
            _el("gone", "text", x=0, y=-100, text="Deleted", isDeleted=True),
            _el("blank", "text", x=0, y=700, text="   "),
        )
    )
    card = preview(spec)
    assert card["notes"] == [
        {"text": "Heading on top", "color": "gray"},
        {"text": "Inside a blue box", "color": "blue"},
        {"text": "A yellow note", "color": "yellow"},
        {"text": "An empty box", "color": "yellow"},
    ]
    # Shapes, free texts and the blank text count; labels inside a shape do not.
    assert card["count"] == 6
    assert all(note["color"] in PREVIEW_COLORS for note in card["notes"])


def test_the_card_of_an_empty_or_broken_board_is_empty() -> None:
    assert preview(empty_scene()) == {"notes": [], "count": 0}
    assert preview({"elements": "broken"}) == {"notes": [], "count": 0}


def test_a_card_text_is_clipped() -> None:
    card = preview(normalize(_scene(_el("t", "text", text="x" * 300))))
    assert len(card["notes"][0]["text"]) == whiteboard.PREVIEW_CHARS


@pytest.mark.parametrize(
    ("hex_color", "name"),
    [
        ("#ffec99", "yellow"),
        ("#b2f2bb", "green"),
        ("#a5d8ff", "blue"),
        ("#d0bfff", "violet"),
        ("#ffd8a8", "orange"),
        ("#ffc9c9", "pink"),
        ("#eebefa", "violet"),
        ("#fcc2d7", "pink"),
        ("#99e9f2", "blue"),
        ("#1e1e1e", None),
        ("#ffffff", None),
        ("transparent", None),
    ],
)
def test_editor_colours_map_to_card_colours(hex_color: str, name: str | None) -> None:
    assert whiteboard._hue_color(hex_color) == name


def test_the_page_with_pictures_reads_them_from_the_run_folder(tmp_path: Path) -> None:
    file_id = board_files.store_bytes(tmp_path, PNG, "image/png")
    node = _card_node(_scene(_el("i", "image", fileId=file_id)))
    assert "data:image/png;base64," in render_in_run(node, tmp_path)
    assert "data:image/png;base64," not in render(node)


def test_the_real_converter_turns_the_example_into_a_scene() -> None:
    convert = pytest.importorskip("dodaios.nodes.board.convert")
    if not hasattr(convert, "legacy_to_scene"):
        pytest.skip("board.convert.legacy_to_scene is not written yet")
    clean = normalize(EXAMPLE)
    assert clean["format"] == "scene" and clean["elements"]
    assert normalize(clean) == clean
    texts = " ".join(element.get("originalText", "") for element in clean["elements"])
    assert "Interview five customers" in texts and "unblocks" in texts
