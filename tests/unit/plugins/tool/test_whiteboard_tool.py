"""The ``whiteboard`` tool: every operation, its errors, its cards and its registration.

Boards are real whiteboard nodes in a temporary store, so the tool, the
actions and the whiteboard kind are tested together.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest

from dodaios.nodes.store import NodeStore
from dodaios.orchestrator import jobs
from dodaios.plugins.tool import whiteboard as wb_tool
from dodaios.plugins.tool.whiteboard import GUIDE, MAX_READ_CHARS, WhiteboardTool

REPO = Path(__file__).resolve().parents[4]
FLOW = "flowchart LR\n  A[Plan] --> B{Ready?}\n  B -->|yes| C([Ship])"


@pytest.fixture(autouse=True)
def ledger():
    store = jobs.JobLedger(":memory:")
    jobs.set_ledger(store)
    try:
        yield store
    finally:
        jobs.set_ledger(None)
        store.close()


@pytest.fixture
def cards(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict]]:
    posted: list[tuple[str, dict]] = []

    async def fake_post(session_id: str, payload: dict) -> bool:
        posted.append((session_id, payload))
        return True

    monkeypatch.setattr(wb_tool, "post_card", fake_post)
    return posted


def _ctx(session: str = "lead-1", **config: Any) -> SimpleNamespace:
    return SimpleNamespace(
        trace_id=uuid4(),
        user_utterance="",
        config={"approval_ref": f"agent-chat:{session}", "output_language": "de", **config},
        memory_read=None,
    )


def _tool(tmp_path: Path) -> tuple[WhiteboardTool, NodeStore]:
    store = NodeStore(root=tmp_path)
    return WhiteboardTool(store=store), store


async def _board(tool: WhiteboardTool, store: NodeStore, **args: Any) -> str:
    result = await tool.execute({"operation": "create", "title": "Plan", **args}, _ctx())
    assert result.success, result.error
    return store.list_nodes()[0].id


def _live(store: NodeStore, board: str) -> dict[str, dict[str, Any]]:
    scene = store.get(board).spec
    return {e["id"]: e for e in scene["elements"] if not e["isDeleted"]}


async def test_guide_hands_out_every_action(tmp_path: Path) -> None:
    from dodaios.nodes.board.ops import ACTIONS

    tool, _ = _tool(tmp_path)
    result = await tool.execute({"operation": "guide"}, _ctx())
    assert result.success and result.output == GUIDE
    for name in ACTIONS:
        assert f"- {name}" in GUIDE or f"{name}:" in GUIDE or f"/ {name}" in GUIDE, name


def test_the_description_is_short_and_points_to_the_guide() -> None:
    assert len(WhiteboardTool.description) < 800
    assert "'guide'" in WhiteboardTool.description
    assert WhiteboardTool.schema["properties"]["operation"]["enum"] == [
        "guide",
        "list",
        "create",
        "read",
        "edit",
        "duplicate",
        "revert",
    ]


async def test_create_with_a_flowchart_makes_a_board_and_shows_its_card(
    tmp_path: Path, cards, ledger
) -> None:
    tool, store = _tool(tmp_path)
    result = await tool.execute(
        {"operation": "create", "title": "Release", "mermaid": FLOW}, _ctx()
    )
    assert result.success
    node = store.list_nodes()[0]
    assert node.type == "whiteboard" and node.title == "Release" and node.language == "de"
    assert "flowchart: 3 nodes, 2 arrows" in result.output and node.id in result.output
    live = _live(store, node.id)
    assert {"A", "B", "C", "A:B", "B:C"} <= set(live)
    assert cards == [
        (
            "lead-1",
            {
                "kind": "report",
                "text": "Release",
                "summary": "",
                "artifact": node.visual_id,
                "sections": 0,
                "node_type": "whiteboard",
            },
        )
    ]
    (job,) = ledger.recent(owner_session="lead-1")
    assert job.target == f"node:{node.id}" and job.state == "done"


async def test_create_without_anything_is_an_empty_board(tmp_path: Path, cards) -> None:
    tool, store = _tool(tmp_path)
    result = await tool.execute({"operation": "create"}, _ctx())
    assert result.success
    node = store.list_nodes()[0]
    assert node.title == "Whiteboard" and node.spec["elements"] == []


async def test_create_with_a_diagram_and_actions(tmp_path: Path, cards) -> None:
    tool, store = _tool(tmp_path)
    board = await _board(
        tool,
        store,
        diagram={
            "nodes": [{"id": "x", "label": "X"}, {"id": "y", "label": "Y"}],
            "edges": [["x", "y"]],
        },
        actions=[{"do": "add", "type": "note", "id": "n", "label": "Hi", "near": "x"}],
    )
    assert {"x", "y", "x:y", "n"} <= set(_live(store, board))


async def test_a_bad_action_on_create_makes_no_board(tmp_path: Path, cards) -> None:
    tool, store = _tool(tmp_path)
    result = await tool.execute(
        {
            "operation": "create",
            "title": "X",
            "actions": [{"do": "connect", "from": "a", "to": "b"}],
        },
        _ctx(),
    )
    assert not result.success and "actions[0] (connect)" in result.error
    assert store.list_nodes() == [] and cards == []


async def test_read_lists_the_elements_with_ids(tmp_path: Path, cards) -> None:
    tool, store = _tool(tmp_path)
    board = await _board(tool, store, mermaid=FLOW)
    result = await tool.execute({"operation": "read", "board": "Plan"}, _ctx())
    reading = json.loads(result.output)
    assert reading["board"] == board and reading["version"] == 1
    entries = {e["id"]: e for e in reading["elements"]}
    assert entries["B"]["type"] == "diamond" and entries["B:C"]["label"] == "yes"
    narrowed = json.loads(
        (await tool.execute({"operation": "read", "board": board, "query": "ship"}, _ctx())).output
    )
    assert [e["id"] for e in narrowed["elements"]] == ["C"]
    raw = json.loads(
        (
            await tool.execute(
                {"operation": "read", "board": board, "ids": ["A"], "raw": True}, _ctx()
            )
        ).output
    )
    assert raw["raw"][0]["type"] == "rectangle" and raw["raw"][1]["containerId"] == "A"
    bad = await tool.execute({"operation": "read", "board": board, "ids": "A"}, _ctx())
    assert not bad.success and "'ids' must be a list" in bad.error


async def test_a_very_large_reading_is_cut_and_says_so(tmp_path: Path, cards, monkeypatch) -> None:
    tool, store = _tool(tmp_path)
    board = await _board(tool, store, mermaid=FLOW)
    monkeypatch.setattr(wb_tool, "MAX_READ_CHARS", 100)
    result = await tool.execute({"operation": "read", "board": board}, _ctx())
    assert result.success and "narrow it with 'query'" in result.output
    assert MAX_READ_CHARS == 60_000


async def test_edit_applies_actions_as_a_new_version(tmp_path: Path, cards) -> None:
    tool, store = _tool(tmp_path)
    board = await _board(tool, store, mermaid=FLOW)
    cards.clear()
    result = await tool.execute(
        {
            "operation": "edit",
            "board": board,
            "title": "Plan v2",
            "actions": [
                {"do": "add", "type": "note", "id": "risk", "label": "Legal review", "near": "B"},
                {"do": "connect", "from": "risk", "to": "B", "style": "dashed"},
                {"do": "layout", "kind": "flow"},
            ],
        },
        _ctx(),
    )
    assert result.success, result.error
    node = store.get(board)
    assert node.version == 2 and node.title == "Plan v2"
    assert result.output.startswith("Board 'Plan v2' is now version 2.")
    assert "0: added note 'risk'" in result.output and "2: laid out" in result.output
    assert "risk:B" not in _live(store, board) and any(
        e["type"] == "arrow" and e["startBinding"]["elementId"] == "risk"
        for e in _live(store, board).values()
    )
    assert len(cards) == 1 and cards[0][1]["node_type"] == "whiteboard"


async def test_edit_works_on_what_is_stored_now(tmp_path: Path, cards) -> None:
    """A stroke the person saved after the model's last read is kept."""
    tool, store = _tool(tmp_path)
    board = await _board(tool, store, mermaid=FLOW)
    scene = store.get(board).spec
    person = dict(scene["elements"][0], id="person-stroke", index="a9", version=1)
    store.save_scene(board, {**scene, "elements": [*scene["elements"], person]})
    result = await tool.execute(
        {
            "operation": "edit",
            "board": board,
            "actions": [{"do": "add", "type": "box", "label": "New"}],
        },
        _ctx(),
    )
    assert result.success
    assert "person-stroke" in _live(store, board)


async def test_edit_errors_change_nothing(tmp_path: Path, cards) -> None:
    tool, store = _tool(tmp_path)
    board = await _board(tool, store, mermaid=FLOW)
    no_actions = await tool.execute({"operation": "edit", "board": board}, _ctx())
    assert not no_actions.success and "'edit' needs 'actions'" in no_actions.error
    bad = await tool.execute(
        {
            "operation": "edit",
            "board": board,
            "actions": [
                {"do": "add", "type": "box", "id": "ok"},
                {"do": "delete", "ids": ["nope"]},
            ],
        },
        _ctx(),
    )
    assert not bad.success and bad.error.startswith("actions[1] (delete):")
    assert store.get(board).version == 1 and "ok" not in _live(store, board)
    text = await tool.execute(
        {"operation": "edit", "board": board, "actions": json.dumps([{"do": "grid"}])}, _ctx()
    )
    assert text.success and store.get(board).spec["appState"]["gridModeEnabled"]


async def test_the_board_must_exist_and_be_a_whiteboard(tmp_path: Path, cards) -> None:
    tool, store = _tool(tmp_path)
    missing = await tool.execute({"operation": "read"}, _ctx())
    assert not missing.success and "'board' is required" in missing.error
    unknown = await tool.execute({"operation": "read", "board": "Nope"}, _ctx())
    assert not unknown.success and "operation 'list'" in unknown.error
    doc = store.create(type="docs", title="Notes", spec={"markdown": "x"})
    other = await tool.execute(
        {"operation": "edit", "board": doc.id, "actions": [{"do": "grid"}]}, _ctx()
    )
    assert not other.success and "not a whiteboard" in other.error


async def test_list_shows_only_boards(tmp_path: Path, cards) -> None:
    tool, store = _tool(tmp_path)
    empty = await tool.execute({"operation": "list"}, _ctx())
    assert empty.success and "no whiteboards yet" in empty.output
    store.create(type="docs", title="Notes", spec={"markdown": "x"})
    board = await _board(tool, store, mermaid=FLOW)
    listed = await tool.execute({"operation": "list"}, _ctx())
    assert [b["id"] for b in listed.output] == [board]
    assert listed.output[0]["elements"] == 5


async def test_duplicate_and_revert(tmp_path: Path, cards) -> None:
    tool, store = _tool(tmp_path)
    board = await _board(tool, store, mermaid=FLOW)
    await tool.execute({"operation": "edit", "board": board, "actions": [{"do": "clear"}]}, _ctx())
    assert _live(store, board) == {}
    copy = await tool.execute(
        {"operation": "duplicate", "board": board, "title": "Empty copy"}, _ctx()
    )
    assert copy.success and "Empty copy" in copy.output
    reverted = await tool.execute({"operation": "revert", "board": board}, _ctx())
    assert reverted.success and "now version 3" in reverted.output
    assert "A" in _live(store, board)


async def test_bad_operation(tmp_path: Path) -> None:
    tool, _ = _tool(tmp_path)
    result = await tool.execute({"operation": "draw"}, _ctx())
    assert not result.success and "'operation' must be one of" in result.error


# ------------------------------------------------------------ registration


def test_the_tool_is_router_reachable_registered_and_never_gated() -> None:
    from dodaios.brain.delegate_tool import DELEGATE_OVERLAPS
    from dodaios.brain.factory import ROUTER_TOOLS
    from dodaios.brain.tool_shortlist import DEFAULT_DIRECT
    from dodaios.society.capabilities import capability_id_for_tool

    assert "whiteboard" in ROUTER_TOOLS
    assert WhiteboardTool.name == "whiteboard" and WhiteboardTool.risk_tier == "monitor"
    assert WhiteboardTool()._store is None
    assert "whiteboard" in DEFAULT_DIRECT and "whiteboard" not in DELEGATE_OVERLAPS
    assert capability_id_for_tool("whiteboard") == "plugin:whiteboard"


def test_the_entry_point_resolves_to_the_tool() -> None:
    """Read from pyproject: the installed metadata of a long-lived checkout may
    not know a new entry point until the package is installed again."""
    import importlib

    declared = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    target = declared["project"]["entry-points"]["jarvis.tool"]["whiteboard"]
    module, _, attr = target.partition(":")
    assert getattr(importlib.import_module(module), attr) is WhiteboardTool


def test_the_node_tool_sends_boards_here() -> None:
    from dodaios.plugins.tool.node import TYPE_LINES, NodeTool

    assert "whiteboard tool" in TYPE_LINES["whiteboard"]
    assert "whiteboard tool" in NodeTool.description
