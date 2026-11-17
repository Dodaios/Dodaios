"""Boards the assistant draws look finished: a clean look, sizes that follow the
text, dashboards as top-aligned panels, edges aligned when placed beside
something, and every new element marked as the assistant's.

The last test replays the call that started this work (a growth report: a
title, five sections of stat cards as one grid diagram, a frame of notes),
reconstructed in English, and checks the board it makes.
"""

from __future__ import annotations

from typing import Any

from dodaios.nodes.board import check
from dodaios.nodes.board import convert as cv
from dodaios.nodes.board import elements as el
from dodaios.nodes.board.ops import ASSISTANT_MARK, apply_actions
from dodaios.nodes.board.scene import empty_scene, normalize_scene

NOW = 1_731_500_000_000


def run(scene: dict[str, Any], *actions: dict[str, Any]) -> dict[str, Any]:
    result, _ = apply_actions(scene, list(actions), now_ms=NOW)
    return result


def live(scene: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {e["id"]: e for e in scene["elements"] if not e["isDeleted"]}


def label_of(scene: dict[str, Any], container: str) -> dict[str, Any]:
    return next(
        e for e in scene["elements"] if e["type"] == "text" and e.get("containerId") == container
    )


# --- A: the clean look ------------------------------------------------------------------


def test_everything_is_drawn_clean_in_the_sans_font_unless_asked() -> None:
    scene = run(
        empty_scene(),
        {"do": "add", "type": "text", "id": "t", "text": "Heading", "size": "xl"},
        {
            "do": "diagram",
            "nodes": [{"id": "a", "label": "Plan"}, {"id": "b", "label": "Ship"}],
            "edges": [{"from": "a", "to": "b", "label": "then"}],
        },
        {"do": "add", "type": "note", "id": "n", "label": "Remember"},
    )
    elements = live(scene)
    assert all(e["roughness"] == 0 for e in elements.values())
    texts = [e for e in elements.values() if e["type"] == "text"]
    assert texts and all(e["fontFamily"] == el.FONT_NORMAL for e in texts)
    assert elements["a"]["roundness"] == el.ROUND_ADAPTIVE  # rounded corners on boxes
    assert elements["a"]["strokeWidth"] == elements["b"]["strokeWidth"]
    sketch = run(
        empty_scene(),
        {"do": "add", "type": "box", "id": "s", "label": "Sketch", "roughness": 1, "font": "hand"},
    )
    assert live(sketch)["s"]["roughness"] == 1
    assert label_of(sketch, "s")["fontFamily"] == el.FONT_HAND


# --- B: sizes follow the text ------------------------------------------------------------


def test_widths_are_shared_and_heights_follow_each_label() -> None:
    spec = cv.normalize_diagram(
        {
            "nodes": [
                {"id": "short", "label": "20 contributors"},
                {"id": "long", "label": "389 stars\n+44 in 7 days\n(week before +33)"},
            ],
            "edges": [{"from": "short", "to": "long"}],
        }
    )
    placed = cv.layout_diagram(spec)["nodes"]
    assert placed["short"][2] == placed["long"][2]
    assert placed["short"][3] < placed["long"][3]


def test_a_label_of_several_lines_runs_wider_instead_of_wrapping() -> None:
    label = "389 GitHub stars\n+44 in 7 days\n(week before +33, so +33 %)"
    scene = run(empty_scene(), {"do": "diagram", "nodes": [{"id": "stat", "label": label}]})
    box = live(scene)["stat"]
    assert box["width"] > 280  # wider than a one-line box may grow
    assert label_of(scene, "stat")["text"].count("\n") == 2  # still three lines


def test_a_row_of_a_group_shares_its_height_and_rows_differ() -> None:
    scene = run(
        empty_scene(),
        {
            "do": "diagram",
            "layout": "grid",
            "nodes": [
                {"id": "a", "label": "One"},
                {"id": "b", "label": "Two"},
                {"id": "c", "label": "Three\nlines\nhere"},
                {"id": "d", "label": "Four"},
            ],
            "groups": [{"id": "g", "label": "Numbers", "nodes": ["a", "b", "c", "d"]}],
        },
    )
    boxes = live(scene)
    assert boxes["a"]["height"] == boxes["b"]["height"]
    assert boxes["c"]["height"] == boxes["d"]["height"] > boxes["a"]["height"]
    assert boxes["a"]["y"] == boxes["b"]["y"] and boxes["c"]["y"] == boxes["d"]["y"]


def test_notes_added_together_get_one_size() -> None:
    scene = run(
        empty_scene(),
        {
            "do": "add",
            "items": [
                {"type": "note", "label": "Short"},
                {"type": "note", "label": "A much longer note that needs several lines to fit"},
                {"type": "note", "label": "Mid length note"},
            ],
        },
    )
    notes = [e for e in live(scene).values() if e["id"].startswith("note-")]
    assert len(notes) == 3
    assert len({(n["width"], n["height"]) for n in notes}) == 1


# --- C: a grid of frames is a dashboard ---------------------------------------------------


def _dashboard() -> dict[str, Any]:
    return run(
        empty_scene(),
        {
            "do": "diagram",
            "layout": "grid",
            "nodes": [
                {"id": "a1", "label": "One"},
                {"id": "a2", "label": "Two"},
                {"id": "a3", "label": "Three"},
                {"id": "a4", "label": "Four"},
                {"id": "b1", "label": "Five"},
                {"id": "c1", "label": "Six\nwith more\ntext"},
            ],
            "groups": [
                {"id": "ga", "label": "Big", "nodes": ["a1", "a2", "a3", "a4"]},
                {"id": "gb", "label": "Small", "nodes": ["b1"]},
                {"id": "gc", "label": "Tall", "nodes": ["c1"]},
            ],
        },
    )


def test_frames_of_a_grid_are_top_aligned_and_one_height_per_row() -> None:
    elements = live(_dashboard())
    frames = [elements[f] for f in ("ga", "gb", "gc")]
    rows: dict[float, list[dict[str, Any]]] = {}
    for frame in frames:
        rows.setdefault(frame["y"], []).append(frame)
    assert len(rows) < 3  # side by side, not a column
    for row in rows.values():
        assert len({f["height"] for f in row}) == 1
    for frame in frames:
        assert frame["x"] % 20 == 0 and frame["y"] % 20 == 0
    # Members start at the frame's top-left padding.
    for frame_id, first in (("ga", "a1"), ("gb", "b1"), ("gc", "c1")):
        assert elements[first]["x"] == elements[frame_id]["x"] + cv.FRAME_PAD
        assert elements[first]["y"] == elements[frame_id]["y"] + cv.FRAME_PAD
    assert check.problems(_dashboard()) == []


def test_the_layout_action_lines_up_frames_as_panels() -> None:
    scene = run(
        empty_scene(),
        {"do": "add", "type": "frame", "id": "f1", "name": "A", "x": 0, "y": 0, "w": 300, "h": 200},
        {"do": "add", "type": "frame", "id": "f2", "name": "B", "x": 500, "y": 140, "w": 300},
        {"do": "layout", "kind": "grid", "ids": ["f1", "f2"]},
    )
    f1, f2 = live(scene)["f1"], live(scene)["f2"]
    assert f1["y"] == f2["y"] and f1["height"] == f2["height"]
    assert f2["x"] - (f1["x"] + f1["width"]) == 40


# --- D: placed beside something, edges line up ---------------------------------------------


def test_below_aligns_left_edges_and_right_of_aligns_tops() -> None:
    scene = run(
        empty_scene(),
        {"do": "add", "type": "text", "id": "title", "text": "Report", "size": "xl"},
        {
            "do": "diagram",
            "below": "title",
            "nodes": [{"id": f"n{i}", "label": f"Step {i}"} for i in range(6)],
            "edges": [{"from": f"n{i}", "to": f"n{i + 1}"} for i in range(5)],
        },
        {"do": "add", "type": "box", "id": "side", "label": "Aside", "right_of": "n5"},
    )
    elements = live(scene)
    title = elements["title"]
    diagram_left = min(elements[f"n{i}"]["x"] for i in range(6))
    assert diagram_left == title["x"]
    assert min(elements[f"n{i}"]["y"] for i in range(6)) >= title["y"] + title["height"]
    assert elements["side"]["y"] == elements["n5"]["y"]
    assert check.problems(scene) == []


# --- F: the assistant's elements are marked -------------------------------------------------


def test_every_new_element_is_marked_and_the_mark_survives_normalizing() -> None:
    person = el.shape("rectangle", x=0, y=400, width=100, height=60, now_ms=NOW, element_id="p")
    person["customData"] = {"mine": True}
    start = normalize_scene({**empty_scene(), "elements": [person]})
    scene = run(
        start,
        {"do": "add", "type": "box", "id": "a", "label": "A", "x": 0, "y": 0},
        {"do": "add", "type": "box", "id": "b", "label": "B", "right_of": "a"},
        {"do": "connect", "from": "a", "to": "b", "label": "goes"},
        {"do": "update", "id": "p", "label": "now labelled"},
    )
    assert normalize_scene(scene) == scene
    elements = live(scene)
    made = [e for e in elements.values() if e["id"] != "p"]
    assert len(made) >= 6  # two boxes, two labels, an arrow and its label, p's new label
    assert all(e["customData"] == ASSISTANT_MARK for e in made)
    # The person's element keeps its own data and is not claimed.
    assert elements["p"]["customData"] == {"mine": True}
    existing = run(
        normalize_scene({**empty_scene(), "elements": []}),
        {"do": "add", "type": "box", "id": "c", "label": "C"},
    )
    assert live(existing)["c"]["customData"]["by"] == "assistant"


# --- the call that started this ---------------------------------------------------------------


GROWTH_REPORT: list[dict[str, Any]] = [
    {
        "do": "add",
        "type": "text",
        "id": "title",
        "label": "Growth report · as of 16 Nov 2026",
        "size": "xl",
    },
    {
        "do": "diagram",
        "layout": "grid",
        "below": "title",
        "nodes": [
            {
                "id": "stars",
                "label": "389 GitHub stars\n+44 in 7 days\n(week before +33, so +33 %)",
            },
            {"id": "forks", "label": "136 forks\n+12 since 8 Nov"},
            {"id": "contrib", "label": "20 contributors"},
            {"id": "month", "label": "Stars per month\nJul 5 · Aug 27 · Sep 43\nOct 230 · Nov 84"},
            {"id": "pypi_w", "label": "PyPI downloads\n1,007 in 7 days\n(week before: 70)"},
            {"id": "pypi_m", "label": "1,884 downloads / 30 days\n141 yesterday"},
            {"id": "views", "label": "Repo views 1-14 Nov\n7,241 (3,015 visitors)"},
            {"id": "views_wow", "label": "Week 2 vs. week 1\n+43 % views\n+23 % visitors"},
            {"id": "refs", "label": "Top sources (visitors)\nsite 355 · GitHub 251\nsearch 223"},
            {"id": "commits", "label": "6,597 commits in total\n470 in 7 days\n917 in 30 days"},
            {"id": "prs", "label": "~530 merged PRs in 7 days\n(bots included)"},
            {"id": "issues", "label": "Issues: 35 open\n38 new / 57 closed (7 days)"},
            {"id": "release", "label": "Release: v5.3.4 live\nv5.5.1 as a draft"},
            {
                "id": "social",
                "label": "Social posts last week\n6 posts · 11 reactions · 9 comments\nTop: a tip",
            },
        ],
        "groups": [
            {
                "id": "g_github",
                "label": "Community",
                "nodes": ["stars", "forks", "contrib", "month"],
            },
            {"id": "g_pypi", "label": "Usage", "nodes": ["pypi_w", "pypi_m"]},
            {"id": "g_traffic", "label": "Reach", "nodes": ["views", "views_wow", "refs"]},
            {
                "id": "g_dev",
                "label": "Development",
                "nodes": ["commits", "prs", "issues", "release"],
            },
            {"id": "g_social", "label": "Social", "nodes": ["social"]},
        ],
    },
    {"do": "add", "type": "frame", "id": "g_take", "name": "Takeaways", "w": 900, "h": 320},
    {
        "do": "add",
        "items": [
            {
                "type": "note",
                "label": "Downloads x14 in one week: the releases pull",
                "inside": "g_take",
            },
            {"type": "note", "label": "Stars pace about 5 a day", "inside": "g_take"},
            {"type": "note", "label": "Forums bring real visitors: post there", "inside": "g_take"},
            {
                "type": "note",
                "label": "Careful: downloads count CI and bots too",
                "inside": "g_take",
            },
        ],
    },
    {"do": "layout", "kind": "grid", "frame": "g_take", "columns": 4},
]


def test_the_growth_report_comes_out_tidy() -> None:
    scene = run(empty_scene(), *GROWTH_REPORT)
    elements = live(scene)
    # A one-line card is not as tall as the longest card on the board.
    assert elements["contrib"]["height"] < elements["social"]["height"]
    assert elements["contrib"]["width"] == elements["social"]["width"]
    # Cards in one row of a section share a height.
    assert elements["stars"]["height"] == elements["forks"]["height"]
    # Frames that stand in one row have one top and one height.
    frames = [e for e in elements.values() if e["type"] == "frame"]
    for a in frames:
        for b in frames:
            if a is not b and a["y"] < b["y"] + b["height"] and b["y"] < a["y"] + a["height"]:
                assert a["y"] == b["y"] and a["height"] == b["height"], (a["id"], b["id"])
    # The diagram starts where the title starts; the notes are one size.
    assert min(e["x"] for e in frames) == elements["title"]["x"]
    notes = [e for e in elements.values() if e.get("frameId") == "g_take" and e["type"] != "text"]
    assert len({(n["width"], n["height"], n["y"]) for n in notes}) == 1
    assert check.report(scene) == "Check: all clear (no overlaps, labels fit, frames aligned)."
