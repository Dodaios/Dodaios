"""Comments on a node: one quiet one-shot lead routine per batch, out of the conversation."""

from __future__ import annotations

from pathlib import Path

import pytest

from dodaios.agent_chat import proactive_checks
from dodaios.nodes import comments, refresh
from dodaios.nodes.comments import NodeComment
from dodaios.nodes.types import NodeError
from tests.unit.nodes.test_refresh import (  # noqa: F401 - fake_kinds is an autouse fixture
    _parcels,
    _society,
    _store,
    _TaskStore,
    fake_kinds,
)


async def test_a_batch_is_one_quiet_one_shot_lead_routine_with_every_comment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tasks = _TaskStore()
    _society(monkeypatch, tasks)
    store = _store(tmp_path)
    node = _parcels(store)

    task_id = await comments.send_comments(
        store,
        node.id,
        [
            NodeComment("Make the intro shorter", quote="Welcome", where="§ Intro"),
            NodeComment("   "),
            NodeComment("A brighter picture", where="/slides/2"),
        ],
    )

    assert [row["id"] for row in tasks.rows] == [task_id]
    spec = tasks.rows[0]["spec"]
    assert spec.trigger.type == "after_delay"
    assert comments.tag_for(node.id) in spec.tags
    # Quiet: no start card in the conversation.
    assert proactive_checks.quiet_routine(spec.tags)
    # Not the refresh routine's tag: a refresh would take it for its own.
    assert refresh.tag_for(node.id) not in spec.tags
    prompt = spec.action.prompt
    assert '1. on "Welcome" (§ Intro): Make the intro shorter' in prompt
    assert "2. (/slides/2): A brighter picture" in prompt
    assert "3." not in prompt  # the empty comment is dropped
    assert node.id in prompt and proactive_checks.NOTHING in prompt


async def test_an_unknown_node_or_no_comment_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tasks = _TaskStore()
    _society(monkeypatch, tasks)
    store = _store(tmp_path)
    node = _parcels(store)
    with pytest.raises(NodeError):
        await comments.send_comments(store, "nope", [NodeComment("x")])
    with pytest.raises(NodeError):
        await comments.send_comments(store, node.id, [NodeComment(" ")])
    assert tasks.rows == []


async def test_nothing_is_sent_while_the_society_is_down(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _society(monkeypatch, None)
    store = _store(tmp_path)
    node = _parcels(store)
    with pytest.raises(RuntimeError):
        await comments.send_comments(store, node.id, [NodeComment("x")])


def test_the_comments_tag_is_its_own() -> None:
    assert comments.is_comments_tag(comments.tag_for("n1"))
    assert not comments.is_comments_tag(refresh.tag_for("n1"))
