"""Mermaid flowcharts read into whiteboard diagrams (``board.mermaid``)."""

from __future__ import annotations

import pytest

from dodaios.nodes.board import mermaid
from dodaios.nodes.board.convert import normalize_diagram
from dodaios.nodes.types import NodeError


def nodes(diagram: dict) -> dict[str, dict]:
    return {n["id"]: n for n in diagram["nodes"]}


def edges(diagram: dict) -> list[tuple[str, str]]:
    return [(e["from"], e["to"]) for e in diagram["edges"]]


@pytest.mark.parametrize(
    ("header", "direction"),
    [
        ("flowchart LR", "LR"),
        ("graph TD", "TB"),
        ("flowchart TB", "TB"),
        ("graph RL", "RL"),
        ("flowchart BT", "BT"),
        ("flowchart", "TB"),
        ("graph lr;", "LR"),
    ],
)
def test_the_header_sets_the_direction(header: str, direction: str) -> None:
    assert mermaid.parse(f"{header}\n  A --> B")["direction"] == direction


def test_node_shapes_and_labels() -> None:
    diagram = mermaid.parse(
        "flowchart LR\n"
        "  a[Box] --> b(Round) --> c([Stadium]) --> d{Decide}\n"
        "  e((Circle)) --> f[[Sub]] --> g[(Store)] --> h{{Hex}} --> i>Flag] --> j[/Lean/]\n"
        '  k["Quoted (with) [brackets]<br>second line"] --> l\n'
    )
    shapes = {key: n["shape"] for key, n in nodes(diagram).items()}
    assert shapes == {
        "a": "box",
        "b": "rounded",
        "c": "rounded",
        "d": "diamond",
        "e": "circle",
        "f": "box",
        "g": "box",
        "h": "box",
        "i": "box",
        "j": "box",
        "k": "box",
        "l": "box",
    }
    labels = {key: n["label"] for key, n in nodes(diagram).items()}
    assert labels["k"] == "Quoted (with) [brackets]\nsecond line"
    assert labels["l"] == "l" and labels["g"] == "Store"


def test_edge_kinds_and_labels() -> None:
    diagram = mermaid.parse(
        "graph LR\n"
        "  A --> B\n"
        "  A --- C\n"
        "  A -.-> D\n"
        "  A ==> E\n"
        "  A -->|piped| F\n"
        "  A -- inline --> G\n"
        "  A <--> H\n"
        "  A --o I\n"
        "  A --x J\n"
        "  A ~~~ K\n"
        "  A -. dotted text .-> L\n"
    )
    by_target = {e["to"]: e for e in diagram["edges"]}
    assert "K" not in by_target  # an invisible link draws nothing
    assert by_target["B"] == {"from": "A", "to": "B"}
    assert by_target["C"]["arrow"] == "none"
    assert by_target["D"]["style"] == "dashed"
    assert by_target["E"]["style"] == "bold"
    assert by_target["F"]["label"] == "piped"
    assert by_target["G"]["label"] == "inline"
    assert by_target["H"]["arrow"] == "both"
    assert by_target["I"]["end"] == "circle" and by_target["J"]["end"] == "bar"
    assert by_target["L"]["label"] == "dotted text" and by_target["L"]["style"] == "dashed"
    # What the parser hands on is a diagram the diagram action accepts.
    normalize_diagram(diagram)


def test_chains_ampersands_semicolons_comments_and_skipped_lines() -> None:
    diagram = mermaid.parse(
        "```mermaid\n"
        "flowchart LR\n"
        "  %% a comment line\n"
        "  A --> B --> C; C --> D %% trailing comment\n"
        "  E & F --> G & H\n"
        "  classDef hot fill:#f00\n"
        "  class A hot\n"
        "  style B fill:#0f0\n"
        "  linkStyle 0 stroke:#f00\n"
        "  click A callback\n"
        "  A:::hot --> Z\n"
        "```"
    )
    assert edges(diagram)[:3] == [("A", "B"), ("B", "C"), ("C", "D")]
    assert {("E", "G"), ("E", "H"), ("F", "G"), ("F", "H")} <= set(edges(diagram))
    assert ("A", "Z") in edges(diagram)
    assert "hot" not in nodes(diagram)


def test_subgraphs_become_groups_and_nested_ones_join_the_outer() -> None:
    diagram = mermaid.parse(
        "flowchart LR\n"
        "  X --> A\n"
        "  subgraph back [Back end]\n"
        "    direction TB\n"
        "    A --> B\n"
        "    subgraph inner\n"
        "      C\n"
        "    end\n"
        "  end\n"
        '  subgraph "Front end"\n'
        "    D\n"
        "  end\n"
        "  subgraph solo\n"
        "    E\n"
        "  end\n"
        "  D --> back\n"
        "  E --> inner\n"
    )
    groups = {g["id"]: g for g in diagram["groups"]}
    assert groups["back"]["label"] == "Back end" and groups["back"]["nodes"] == ["A", "B", "C"]
    assert groups["Front_end"]["label"] == "Front end" and groups["Front_end"]["nodes"] == ["D"]
    assert groups["solo"]["nodes"] == ["E"]
    assert "inner" not in groups and "back" not in nodes(diagram)
    # An edge to a subgraph is an edge to its frame; an inner one's goes to the outer frame.
    assert ("D", "back") in edges(diagram) and ("E", "back") in edges(diagram)
    normalize_diagram(diagram)


@pytest.mark.parametrize(
    ("source", "words"),
    [
        ("sequenceDiagram\n  A->>B: hi", "only flowcharts"),
        ("gantt\n  title x", "only flowcharts"),
        ("hello world", "starts with 'flowchart' or 'graph'"),
        ("", "must be the text"),
        ("flowchart LR\n  A[open --> B", "never closes"),
        ("flowchart LR\n  end", "'end' without a 'subgraph'"),
        ("flowchart LR\n  subgraph x\n  A", "has no 'end'"),
        ("flowchart LR\n  A --> ", "expected a node id"),
        ("flowchart LR\n  A ?? B", "cannot read"),
        ("flowchart LR", "no nodes"),
    ],
)
def test_errors_say_what_works(source: str, words: str) -> None:
    with pytest.raises(NodeError, match=words):
        mermaid.parse(source)


def test_limits() -> None:
    with pytest.raises(NodeError, match="longer than"):
        mermaid.parse("flowchart LR\n" + "A --> B\n" * 4000)
    many = "flowchart LR\n" + "\n".join(
        f"  n{i} --> n{i + 1}" for i in range(mermaid.MAX_NODES + 1)
    )
    with pytest.raises(NodeError, match="more than"):
        mermaid.parse(many)


def test_a_redefined_node_keeps_its_last_label_and_shape() -> None:
    diagram = mermaid.parse("flowchart LR\n  A --> B\n  A{Decide again}")
    assert nodes(diagram)["A"] == {"id": "A", "label": "Decide again", "shape": "diamond"}
