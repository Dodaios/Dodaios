"""Cross-layer parity guard for the Jarvis-Agent Board status vocabulary.

Agent nodes are in-memory dataclasses serialized directly by the REST snapshot,
so the persistence and Pydantic layers collapse here. This guard keeps the
Python producer and the TypeScript consumer synchronized.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import get_args

from dodaios.agents.registry import NodeStatus

_REPO = Path(__file__).resolve().parents[3]
_STORE = (
    _REPO
    / "dodaios"
    / "ui"
    / "web"
    / "frontend"
    / "src"
    / "store"
    / "dodaiosAgents.ts"
)
def _ts_node_statuses() -> set[str]:
    text = _STORE.read_text(encoding="utf-8")
    match = re.search(r"export type NodeStatus\s*=([^;]+);", text)
    assert match is not None, "TypeScript NodeStatus union is missing"
    return set(re.findall(r'"([^"]+)"', match.group(1)))


def test_node_status_python_and_typescript_parity() -> None:
    python_statuses = set(get_args(NodeStatus))
    assert python_statuses == _ts_node_statuses()


def test_node_status_expected_vocabulary() -> None:
    assert set(get_args(NodeStatus)) == {
        "running",
        "completed",
        "failed",
        "cancelled",
    }
