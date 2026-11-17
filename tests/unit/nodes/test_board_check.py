"""The board's self-check (``board.check``): one line per problem, naming the ids
and the fix, only for what a call made or changed."""

from __future__ import annotations

from typing import Any

from dodaios.nodes.board import check
from dodaios.nodes.board import elements as el
from dodaios.nodes.board.ops import apply_actions
from dodaios.nodes.board.scene import empty_scene, normalize_scene

NOW = 1_731_500_000_000
CLEAR = "Check: all clear (no overlaps, labels fit, frames aligned)."


def run(scene: dict[str, Any], *actions: dict[str, Any]) -> dict[str, Any]:
    result, _ = apply_actions(scene, list(actions), now_ms=NOW)
    return result


def scene_of(*elements: dict[str, Any]) -> dict[str, Any]:
    return {**empty_scene(), "elements": list(elements)}


def box(ident: str, x: float, y: float, w: float = 160, h: float = 80) -> dict[str, Any]:
    return el.shape("rectangle", x=x, y=y, width=w, height=h, now_ms=NOW, element_id=ident)


def test_a_tidy_board_is_all_clear() -> None:
    scene = run(
        empty_scene(),
        {
            "do": "mermaid",
            "source": "flowchart LR\n  A[Plan] --> B{Ready?}\n  B -->|yes| C([Ship])",
        },
    )
    assert check.problems(scene) == []
    assert check.report(scene) == CLEAR


def test_overlapping_things_are_named_with_the_fix() -> None:
    scene = run(
        empty_scene(),
        {"do": "add", "type": "box", "id": "a", "label": "A", "x": 0, "y": 0},
        {"do": "add", "type": "box", "id": "b", "label": "B", "x": 100, "y": 40},
    )
    (line,) = check.problems(scene)
    assert line.startswith("overlap: a and b overlap") and "move b" in line


def test_a_label_that_does_not_fit_its_box() -> None:
    scene = run(
        empty_scene(),
        {
            "do": "add",
            "type": "box",
            "id": "tiny",
            "label": "A label far too long for a box this small to hold",
            "w": 120,
            "h": 40,
        },
    )
    (line,) = check.problems(scene)
    assert line.startswith("label does not fit: tiny") and "resize tiny h=" in line


def test_a_child_sticking_out_of_its_frame() -> None:
    frame = el.frame("F", x=0, y=0, width=300, height=200, now_ms=NOW, element_id="f")
    child = box("c", 240, 40)
    child["frameId"] = "f"
    (line,) = check.problems(scene_of(child, frame))
    assert line.startswith("outside its frame: c sticks out of frame f by 100 px")


def test_frames_in_one_row_with_different_tops() -> None:
    left = el.frame("L", x=0, y=0, width=300, height=300, now_ms=NOW, element_id="left")
    right = el.frame("R", x=400, y=60, width=300, height=300, now_ms=NOW, element_id="right")
    below = el.frame("B", x=0, y=600, width=300, height=200, now_ms=NOW, element_id="below")
    (line,) = check.problems(scene_of(left, right, below))
    assert line.startswith("frames not aligned: left, right") and "to top" in line


def test_a_box_far_larger_than_its_label() -> None:
    scene = run(
        empty_scene(), {"do": "add", "type": "box", "id": "big", "label": "OK", "w": 400, "h": 400}
    )
    (line,) = check.problems(scene)
    assert line.startswith("too big for its label: big is 400x400")


def test_an_arrow_through_a_shape() -> None:
    a, b, c = box("a", 0, 0), box("b", 600, 0), box("c", 300, 0)
    arrow = el.linear("arrow", [(168, 40), (592, 40)], now_ms=NOW, element_id="a:b")
    arrow["startBinding"] = el.binding("a", 8)
    arrow["endBinding"] = el.binding("b", 8)
    (line,) = check.problems(scene_of(a, b, c, arrow))
    assert line.startswith("arrow through a shape: a:b passes through c")


def test_only_what_the_call_touched_is_reported() -> None:
    # The person's own overlap, stored the way the editor saves it.
    person = normalize_scene(scene_of(box("p1", 0, 0), box("p2", 40, 20)))
    el.sync_indices(person["elements"])
    assert len(check.problems(person)) == 1
    after = run(person, {"do": "add", "type": "box", "id": "new", "label": "New"})
    focus = check.changed_ids(person, after)
    assert "new" in focus and "p1" not in focus
    assert check.report(after, focus) == CLEAR
    moved = run(after, {"do": "move", "ids": ["new"], "to": [20, 10]})
    lines = check.problems(moved, check.changed_ids(after, moved))
    assert lines and all("new" in line for line in lines)


def test_the_report_stays_short() -> None:
    crowd = [box(f"b{i}", i * 10, 0) for i in range(12)]
    text = check.report(scene_of(*crowd))
    lines = text.split("\n")
    assert lines[0].startswith("Check: ") and "issues" in lines[0]
    assert len(lines) == check.MAX_LINES + 2 and lines[-1].startswith("- and ")
