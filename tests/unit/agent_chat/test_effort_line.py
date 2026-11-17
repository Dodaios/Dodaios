"""The lead judges for itself how much a task needs, and every node guide says how to work."""

from __future__ import annotations

from dodaios.agent_chat.dodaios_harness import EFFORT_LINE, REPLY_SHAPE_LINE
from dodaios.brain.lead_doctrine import LEAD_DOCTRINE
from dodaios.nodes.types import NODE_TYPES
from dodaios.plugins.tool.node import WORK_METHOD, NodeTool


def test_the_effort_line_leaves_the_judgement_to_the_model() -> None:
    assert "yours to judge" in EFFORT_LINE
    assert "quick question" in EFFORT_LINE and "real work" in EFFORT_LINE
    assert "look at the result and revise" in EFFORT_LINE
    # The reply rules after it are about the text only.
    assert "only your reply text, never how much you think" in EFFORT_LINE
    assert "short chat message" in REPLY_SHAPE_LINE
    assert len(EFFORT_LINE) < 500


def test_the_doctrine_says_it_for_every_runner() -> None:
    assert "yours to judge: small things fast" in LEAD_DOCTRINE


def test_every_node_guide_carries_a_way_to_work() -> None:
    tool = NodeTool()
    for type_name in NODE_TYPES:
        result = tool._guide({"type": type_name})
        assert result.success
        assert "How to work" in result.output, type_name
    # The deck keeps its own, longer method, once.
    deck = tool._guide({"type": "slides"}).output
    assert deck.count("How to work") == 1 and WORK_METHOD not in deck
    assert "A node is real work" in NodeTool.description
