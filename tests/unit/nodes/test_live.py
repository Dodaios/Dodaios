"""The push half of the live build (``dodaios/nodes/live.py``).

Every write of the node store is announced once, as a ``NodeChanged`` on the
app's bus, with who made it and what it changed. These tests catch what is
published instead of running an app.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from dodaios.core.events import NodeChanged
from dodaios.nodes import kinds as node_kinds
from dodaios.nodes import live, shell
from dodaios.nodes.kinds import NodeKind
from dodaios.nodes.model import Node
from dodaios.nodes.store import NodeStore
from dodaios.nodes.types import NODE_TYPES

AGENT = live.Author(kind=live.ASSISTANT, name="Dodaios", id="lead", session_id="chat-1")


@pytest.fixture(autouse=True)
def stand_in_kinds(monkeypatch: pytest.MonkeyPatch) -> None:
    def render(node: Node) -> str:
        return shell.document(node, body=f"<main>{shell.esc(json.dumps(node.spec))}</main>")

    monkeypatch.setattr(
        node_kinds,
        "_KINDS",
        {
            name: NodeKind(
                type=name,
                normalize=lambda spec: spec,
                render=render,
                preview=lambda spec: {},
                starter=lambda title, language: {"rows": []},
                guide="",
            )
            for name in NODE_TYPES
        },
    )


@pytest.fixture
def published(monkeypatch: pytest.MonkeyPatch) -> list[NodeChanged]:
    events: list[NodeChanged] = []
    monkeypatch.setattr(live, "_publish", events.append)
    return events


@pytest.fixture
def store(tmp_path: Path) -> NodeStore:
    return NodeStore(root=tmp_path)


# ---------------------------------------------------------------- the ops


def test_small_ops_are_sent_as_applied_and_large_values_are_left_out() -> None:
    big = "x" * (live.MAX_VALUE_CHARS + 10)
    ops, rewrite = live.sent_ops(
        [
            {"op": "set", "path": "/rows/0", "value": ["a", 1]},
            {"path": "/title", "value": big},
            {"op": "move", "path": "/rows/2", "to": 0},
            {"op": "replace", "path": "/text", "find": "y" * 900, "value": "z"},
            "not an op",
        ]
    )
    assert rewrite is False
    assert ops[0] == {"op": "set", "path": "/rows/0", "value": ["a", 1]}
    assert ops[1] == {"op": "set", "path": "/title", "value": None, "value_omitted": True}
    assert ops[2] == {"op": "move", "path": "/rows/2", "to": 0}
    assert len(ops[3]["find"]) == live.MAX_FIND_CHARS
    assert len(ops) == 4


def test_a_whole_spec_or_too_many_ops_is_a_rewrite() -> None:
    assert live.sent_ops(None) == ([], True)
    assert live.sent_ops([{"path": f"/rows/{i}", "value": i} for i in range(live.MAX_OPS + 1)]) == (
        [],
        True,
    )


# ------------------------------------------------------- what the store tells


def test_every_write_is_announced_with_its_action_versions_and_ops(
    store: NodeStore, published: list[NodeChanged]
) -> None:
    node = store.create(type="sheets", title="Budget", spec={"rows": []})
    store.update(node.id, changes=[{"op": "append", "path": "/rows", "value": ["rent", 900]}])
    store.update(node.id, spec={"rows": [["food", 300]]})
    store.update(node.id, title="Budget 2027")
    store.revert(node.id)
    store.save_spec(node.id, {"rows": [["mine", 1]]}, base_version=None)

    actions = ["create", "update", "update", "update", "revert", "save"]
    assert [e.action for e in published] == actions
    assert [(e.previous_version, e.version) for e in published] == [
        (0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 6),
    ]
    create, edit, rewrite, rename, revert, save = published
    assert create.ref == node.visual_id and create.slug == node.slug
    assert create.node_type == "sheets"
    assert create.rewrite is False and create.ops == []
    assert edit.rewrite is False
    assert edit.ops == [{"op": "append", "path": "/rows", "value": ["rent", 900]}]
    assert rewrite.rewrite is True and rewrite.ops == []
    # A new title alone changes no content.
    assert rename.rewrite is False and rename.ops == [] and rename.title == "Budget 2027"
    assert revert.rewrite is True and save.rewrite is True
    # Nobody named an author: the person's writes, which never play back.
    assert {e.author_kind for e in published} == {"person"}


def test_a_write_that_changes_nothing_is_not_announced(
    store: NodeStore, published: list[NodeChanged]
) -> None:
    node = store.create(type="docs", title="Notes", spec={"rows": [1]})
    store.save_spec(node.id, {"rows": [1]}, base_version=None)
    assert len(published) == 1


def test_the_named_author_reaches_the_store_through_a_worker_thread(
    store: NodeStore, published: list[NodeChanged]
) -> None:
    async def write() -> Node:
        with live.writing(AGENT):
            return await asyncio.to_thread(
                store.create, type="docs", title="Plan", spec={"rows": []}
            )

    asyncio.run(write())
    (event,) = published
    assert (event.author_kind, event.author_name, event.author_id, event.session_id) == (
        "assistant", "Dodaios", "lead", "chat-1",
    )
    assert live.current_author() is live.PERSON


# ------------------------------------------------------------- publishing


class _Bus:
    def __init__(self) -> None:
        self.events: list[Any] = []

    async def publish(self, event: Any) -> None:
        self.events.append(event)


def test_a_write_in_a_worker_thread_is_published_on_the_loop(
    store: NodeStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    bus = _Bus()
    monkeypatch.setattr(live, "_bus", lambda: bus)

    async def write() -> None:
        with live.writing(AGENT):
            await asyncio.to_thread(store.create, type="docs", title="Plan", spec={"rows": []})
        for _ in range(5):  # the hop onto the loop, then the publish
            await asyncio.sleep(0)

    asyncio.run(write())
    assert [type(e).__name__ for e in bus.events] == ["NodeChanged"]
    assert bus.events[0].author_kind == "assistant"


def test_announcing_never_breaks_a_write(store: NodeStore, monkeypatch: pytest.MonkeyPatch) -> None:
    def broken() -> Any:
        raise RuntimeError("no app")

    monkeypatch.setattr(live, "_bus", broken)
    node = store.create(type="docs", title="Still written", spec={"rows": []})
    assert store.get(node.id) is not None


# ---------------------------------------------------------------- authors


async def test_a_call_without_a_chat_is_the_assistants() -> None:
    author = await live.author_for("")
    assert author.kind == "assistant" and author.id == "lead" and author.session_id == ""
