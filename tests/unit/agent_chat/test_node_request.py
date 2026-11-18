"""A new node asked for from the chat ("New" in the Nodes library).

The composer sends the type chip as the message's first line,
``[node: slides]``, with the person's description behind it. The bubble keeps
that line (it draws the chip again from it); the turn receives an explicit
request that names the node type, so the type never rests on the model
reading a bracket.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from dodaios.agent_chat.node_request import expand_node_request, split_node_request
from dodaios.agent_chat.service import AgentChatService
from dodaios.agent_chat.store import AgentChatStore
from dodaios.nodes.types import DISPLAY_NAMES, NODE_TYPES


@pytest.mark.parametrize("kind", NODE_TYPES)
def test_every_type_chip_becomes_a_request_for_that_type(kind: str) -> None:
    text = f"[node: {kind}]\nTen slides on last quarter for Monday"
    assert split_node_request(text) == (kind, "Ten slides on last quarter for Monday")
    request = expand_node_request(text)
    assert request is not None
    assert f'type "{kind}"' in request
    assert f"new {DISPLAY_NAMES[kind]} node" in request
    assert request.endswith("Description: Ten slides on last quarter for Monday")


@pytest.mark.parametrize(
    "text",
    [
        "Ten slides on last quarter",
        "[node: poster]\nA poster",
        "Please make [node: slides] for me",
        "[tools: plugin:gmail]\nRead my mail",
    ],
)
def test_any_other_message_is_left_alone(text: str) -> None:
    assert split_node_request(text) is None
    assert expand_node_request(text) is None


def test_the_bubble_keeps_the_chip_and_the_turn_gets_the_request(tmp_path: Path) -> None:
    svc = AgentChatService(
        AgentChatStore(tmp_path / "db.sqlite"), default_cwd=lambda: str(tmp_path)
    )
    session = svc.store.create_session(
        provider="fakeprov", model="", effort="", cwd=str(tmp_path), surface="jarvis"
    )
    sent = "[node: slides]\nTen slides on last quarter for Monday"

    async def run() -> None:
        # No runner is reachable for "fakeprov": the turn fails after the
        # message is recorded, which is the part under test.
        await svc.send(session.session_id, sent)
        await svc.cancel(session.session_id)

    asyncio.run(run())

    user = next(e for e in svc.store.list_events(session.session_id) if e["kind"] == "user_message")
    payload = user["payload"]
    assert payload["typed"] == sent
    assert payload["text"].startswith('The person chose "New Slides" in the Nodes library')
    assert 'type "slides"' in payload["text"]
    assert payload["text"].endswith("Description: Ten slides on last quarter for Monday")
