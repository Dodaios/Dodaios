"""Decisions on an agent's proposals reach it as a system note, never as a turn.

Live finding 2026-10-28: confirming one proposal and rejecting another woke
the agent with a fake "Message from user", it thanked for an approval that was
half a rejection, quoted proposal ids and drew duplicate bubbles. The board
envelope now goes to the person, and the agent reads one accurate note in
front of its next message.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from dodaios.agent_chat.events import make_event
from dodaios.society.approvals import Approvals
from dodaios.society.events import MsgType
from dodaios.society.proposals import capability_for, decision_context, resolved_notice
from dodaios.society.roster import Roster
from dodaios.society.store import SocietyStore


@pytest.fixture
async def world(tmp_path: Path):
    store = SocietyStore(tmp_path / "society.db")
    await store.open()
    try:
        yield store, Roster(store), Approvals(store, ttl_ms=60_000)
    finally:
        await store.close()


@pytest.mark.parametrize("approve", [True, False])
async def test_a_proposal_decision_never_queues_an_agent_turn(world, approve):
    store, roster, approvals = world
    await roster.create(name="Writer")
    item = await approvals.enqueue(
        agent_id="writer",
        trace_id="config:writer:society:writer",
        capability=capability_for("rule"),
        action={"kind": "rule", "payload": {"rule": "Always answer in English."}},
        summary="Add a standing rule: Always answer in English.",
    )
    await approvals.resolve(item.id, approve=approve)
    event = (await store.events_for_trace("config:writer:society:writer"))[-1]
    assert event.msg_type is (MsgType.RELEASE if approve else MsgType.VETO)
    assert event.to_agent == "user"
    assert event.payload["agent_id"] == "writer"
    assert await store.pending_deliveries() == []


async def test_other_approvals_still_release_to_the_agent(world):
    store, roster, approvals = world
    await roster.create(name="Mailbox")
    item = await approvals.enqueue(
        agent_id="mailbox", trace_id="mail", capability="plugin:gmail", action={}, summary="x"
    )
    await approvals.resolve(item.id, approve=True)
    assert (await store.events_for_trace("mail"))[-1].to_agent == "mailbox"


def _resolved(status: str, summary: str, text: str = "") -> dict:
    agent = SimpleNamespace(agent_id="writer", name="Writer", title="", description="")
    item = SimpleNamespace(
        id="01a18010-5e86-7736-93b9-3b04015fd851",
        action={"kind": "rule"},
        capability=capability_for("rule"),
        summary=summary,
    )
    return make_event(
        "notice",
        resolved_notice(agent, item, status=status, text=text or status),  # type: ignore[arg-type]
    )


def test_the_note_lists_each_outcome_once_without_ids():
    events = [
        make_event("turn_started", {"turn_id": "t1"}),
        _resolved("applied", "Add a standing rule: Always answer in English."),
        _resolved("rejected", "Add a standing rule: Keep every answer under three sentences."),
        _resolved("failed", "Create routine: QA weekly check", "The task store is unavailable"),
    ]
    note = decision_context(events)
    assert note.startswith("[System note, not from the person")
    assert "Always answer in English.: approved and applied" in note
    assert "three sentences.: rejected; nothing changed" in note
    assert "could not be applied (The task store is unavailable)" in note
    assert "01a18010" not in note
    # Order kept: the person's decisions in the order they made them.
    assert note.index("English") < note.index("three sentences") < note.index("QA weekly")


def test_the_note_is_given_once():
    old = [_resolved("applied", "Old rule"), make_event("turn_started", {"turn_id": "t2"})]
    assert decision_context(old) == ""
    assert decision_context([]) == ""
    assert decision_context([make_event("notice", {"kind": "proposal", "status": "pending"})]) == ""


def test_a_decision_settled_inside_the_turn_is_not_repeated():
    """``mode=apply`` resolves in the agent's own turn; the tool returned it."""
    agent = SimpleNamespace(agent_id="writer", name="Writer", title="", description="")
    item = SimpleNamespace(
        id="p1",
        action={"kind": "rule", "resume_in_place": True},
        capability=capability_for("rule"),
        summary="Add a standing rule: Be brief.",
    )
    inline = make_event(
        "notice",
        resolved_notice(agent, item, status="applied", text="applied"),  # type: ignore[arg-type]
    )
    assert decision_context([inline]) == ""
    assert "Later rule" in decision_context([inline, _resolved("applied", "Later rule")])
