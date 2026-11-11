"""Stable ids, short cards with spill, and a three-hop chain of recall."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from dodaios.agent_chat import recall, token_efficiency
from dodaios.agent_chat.events import make_event
from dodaios.agent_chat.runner_brain import brain_history_from_events
from dodaios.agent_chat.store import AgentChatStore
from dodaios.orchestrator import jobs
from dodaios.plugins.tool.recall_tool import RecallTool

LONG_REPORT = "Finding one: the build is green. " + ("detail " * 700)  # about 5000 chars


@pytest.fixture
def store():
    s = AgentChatStore(":memory:")
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def ledger():
    led = jobs.JobLedger(":memory:")
    jobs.set_ledger(led)
    try:
        yield led
    finally:
        jobs.set_ledger(None)
        led.close()


def _lead(store: AgentChatStore, title: str = "Lead") -> str:
    session = store.create_session(
        provider="x", model="m", effort="", cwd=".", title=title, surface="jarvis"
    )
    store.set_lead_session_id(session.session_id)
    return session.session_id


def _add(store: AgentChatStore, sid: str, event_kind: str, /, **payload: Any) -> int:
    return store.append_event(sid, make_event(event_kind, payload))["seq"]


def _run(coro):
    return asyncio.run(coro)


def _events_with_reports(store: AgentChatStore, sid: str) -> list[dict[str, Any]]:
    _add(store, sid, "user_message", text="please look at the build")
    _add(store, sid, "notice", kind="society_result", text=LONG_REPORT, agent_name="Scout")
    _add(store, sid, "assistant_text", text="Scout says the build is green.")
    _add(store, sid, "user_message", text="and the docs?")
    _add(store, sid, "notice", kind="society_result", text=LONG_REPORT, agent_name="Scout")
    return store.list_events(sid)


# ------------------------------------------------------------------ inline & spill


def test_an_answered_long_report_becomes_a_card_and_a_new_one_stays_whole(store):
    sid = _lead(store)
    events = _events_with_reports(store, sid)
    texts = [m.content for m in brain_history_from_events(events, recall_ids=True)]
    reports = [t for t in texts if t.startswith("Recorded delegation result")]
    assert len(reports) == 2
    answered, fresh = reports
    assert "[ev:2]" in answered and 'recall("ev:2")' in answered
    assert len(answered) < recall.CARD_HEAD + 300
    assert "Finding one" in answered
    assert "[ev:5]" in fresh and "more characters not shown" not in fresh
    assert len(fresh) > 4000  # the report nobody has answered yet is read whole


def test_without_recall_ids_the_history_is_unchanged(store):
    sid = _lead(store)
    events = _events_with_reports(store, sid)
    reports = [
        m.content
        for m in brain_history_from_events(events)
        if m.content.startswith("Recorded delegation result")
    ]
    assert all("[ev:" not in r and "recall(" not in r for r in reports)
    assert all(len(r) > 4000 for r in reports)


def test_a_short_answered_report_stays_whole(store):
    sid = _lead(store)
    _add(store, sid, "notice", kind="coding_result", text="Merged the fix.", assignment_id="a1")
    _add(store, sid, "assistant_text", text="Done.")
    events = store.list_events(sid)
    text = brain_history_from_events(events, recall_ids=True)[0].content
    assert "Merged the fix." in text and "recall(" not in text


def test_trigger_notice_card_names_the_event_id(store):
    sid = _lead(store)
    _add(
        store,
        sid,
        "notice",
        kind="event_trigger",
        text="A mail needs you.",
        decision_id="d1",
        trigger_event_id="mail:m1",
    )
    card = brain_history_from_events(store.list_events(sid), recall_ids=True)[0].content
    assert "ev:1" in card and "trg:mail:m1" in card


def test_catch_up_block_carries_cards_with_ids(store):
    from dodaios.agent_chat.dodaios_harness import since_last_turn_block

    sid = _lead(store)
    _add(store, sid, "turn_started", turn_id="t1", runner="claude-cli")
    _add(store, sid, "turn_finished", turn_id="t1", status="done")
    _add(store, sid, "notice", kind="society_result", text=LONG_REPORT)
    _add(store, sid, "assistant_text", text="Spoken answer.")
    block = since_last_turn_block(store.list_events(sid), recall_ids=True)
    assert 'recall("ev:N")' in block and "[ev:3]" in block and 'recall("ev:3")' in block
    assert len(block) < 2000


def test_the_reread_metric_drops_for_a_synthetic_lead_conversation(store):
    sid = _lead(store)
    for day in range(12):
        _add(store, sid, "user_message", text=f"question {day}")
        _add(store, sid, "notice", kind="society_result", text=LONG_REPORT)
        _add(store, sid, "assistant_text", text=f"answer {day}")
    events = store.list_events(sid)
    before = token_efficiency.history_chars(events, spill=False)
    after = token_efficiency.history_chars(events, spill=True)
    turn = [make_event("user_message", {"text": "next question"})]
    share_before = token_efficiency.context_split({}, history_chars=before, turn_events=turn)
    share_after = token_efficiency.context_split({}, history_chars=after, turn_events=turn)
    print(f"re-read chars {before} -> {after}; share {share_before} -> {share_after}")
    assert after < before * 0.3
    assert share_after["reread_share"] <= share_before["reread_share"]


# ------------------------------------------------------------------------ recall


def _sources(store, ledger, **extra) -> recall.Sources:
    return recall.Sources(
        store=store, lead_session=store.lead_session_id() or "", ledger=ledger, **extra
    )


def test_recall_an_event_gives_summary_page_cursor_and_neighbours(store, ledger):
    sid = _lead(store)
    _events_with_reports(store, sid)
    card = _run(recall.Recall(_sources(store, ledger)).recall("ev:2"))
    assert card["id"] == "ev:2" and card["notice"] == "society_result"
    assert card["summary"].startswith("Finding one")
    assert len(card["text"]) == recall.PAGE_CHARS and card["more"] == recall.PAGE_CHARS
    assert card["related"]["prev"] == "ev:1" and card["related"]["next"] == "ev:3"
    rest = _run(recall.Recall(_sources(store, ledger)).recall("ev:2", more=card["more"]))
    assert rest["text"] and "more" not in rest
    assert len(card["text"]) + len(rest["text"]) == card["chars"]


def test_an_answer_names_the_message_it_replies_to(store, ledger):
    sid = _lead(store)
    _events_with_reports(store, sid)
    card = _run(recall.Recall(_sources(store, ledger)).recall("ev:3"))
    assert card["related"]["replied_to"] == "ev:1"


def test_unknown_ids_say_so_and_list_the_forms(store, ledger):
    _lead(store)
    for raw in ("nonsense", "ev:999", "job_000000000000", "thread:nope", "trg:x", "agent:y"):
        card = _run(recall.Recall(_sources(store, ledger)).recall(raw))
        assert card["found"] is False and card["id_forms"]


def test_job_thread_and_artifact_cards_link_to_each_other(store, ledger):
    lead = _lead(store)
    worker = store.create_session(
        provider="x", model="m", effort="", cwd=".", title="Fix the build", surface="society"
    )
    store.set_thread_owner(worker.session_id, owner_session=lead, owner_name="Lead")
    jid = jobs.start("artifact", owner=(lead, "t1"), title="Build report", target="x")
    jobs.finish(jid, "done", summary="Built the page.", result_ref="artifact:v1")
    rc = recall.Recall(_sources(store, ledger))
    job = _run(rc.recall(f"job:{jid}"))
    assert job["related"]["thread"] == f"thread:{lead}"
    assert job["related"]["result"] == "artifact:v1"
    art = _run(rc.recall("artifact:v1"))
    assert art["related"]["job"] == f"job:{jid}"
    thread = _run(rc.recall(f"thread:{lead}"))
    assert f"job:{jid}" in thread["related"]["jobs"]
    assert f"thread:{worker.session_id}" in thread["related"]["started"]
    owner = _run(rc.recall(f"thread:{worker.session_id}"))["related"]["started_by"]
    assert owner == f"thread:{lead}"


def test_bare_job_ids_and_the_tool_result_is_valid_bounded_json(store, ledger):
    sid = _lead(store)
    jid = jobs.start("mission", owner=(sid, ""), title="x" * 50)
    tool = RecallTool(_sources(store, ledger))
    ok = _run(tool.execute({"id": jid}, None))
    assert ok.success and json.loads(ok.output)["type"] == "job"
    _events_with_reports(store, sid)
    page = _run(tool.execute({"id": "ev:2"}, None))
    assert json.loads(page.output)["more"] == recall.PAGE_CHARS
    bad = _run(tool.execute({"id": "ev:404"}, None))
    assert not bad.success and "nothing" in bad.error


def test_a_user_message_is_recallable_by_the_id_a_search_returns(store, ledger):
    sid = _lead(store)
    seq = _add(store, sid, "user_message", text="the thing from Tuesday mail")
    card = _run(recall.Recall(_sources(store, ledger)).recall(f"ev:{seq}"))
    assert card["who"] == "user" and "Tuesday" in card["text"]


# ------------------------------------------------------------- chain of recall


class _Triggers:
    """A stand-in for the trigger service's ``lookup``."""

    def __init__(self, record: dict[str, Any]) -> None:
        self.record = record

    async def __call__(self, event_id: str) -> dict[str, Any] | None:
        return self.record if event_id == self.record["event"]["event_id"] else None


def test_three_hops_from_a_notice_to_the_result_of_the_work(store, ledger):
    """Notice -> trigger event -> the routine's result: every hop uses a returned id."""
    lead = _lead(store)
    _add(store, lead, "user_message", text="earlier chat")
    notice = _add(
        store,
        lead,
        "notice",
        kind="event_trigger",
        text="Mail from Tom about the invoice.",
        decision_id="d7",
        trigger_event_id="mail:m42",
    )
    _add(store, lead, "assistant_text", text="I will keep an eye on it.")
    result = _add(
        store,
        lead,
        "notice",
        kind="society_result",
        status="done",
        source="routine",
        text="The invoice is paid. Reference 8841.",
        task_id="routine-9",
    )
    _add(store, lead, "user_message", text="what happened with that mail from Tuesday?")
    record = {
        "event": {
            "event_id": "mail:m42",
            "source": "mail",
            "sender": "tom@example.com",
            "scope": "inbox",
            "thread_key": "invoice-thread",
            "summary": "Invoice 8841",
            "raw_ref": "https://mail.example/m42",
        },
        "waiting": False,
        "decisions": [
            {
                "id": "d7",
                "action": "act",
                "policy_text": "pay invoices",
                "reason": "fits",
                "mode": "auto",
                "outcome": "started",
                "job": "routine-9",
            }
        ],
        "same_thread": ["mail:m43"],
    }
    rc = recall.Recall(_sources(store, ledger, triggers=_Triggers(record)))

    hop1 = _run(rc.recall(f"ev:{notice}"))
    assert hop1["related"]["trigger"] == "trg:mail:m42"
    hop2 = _run(rc.recall(hop1["related"]["trigger"]))
    assert hop2["thread_key"] == "invoice-thread"
    assert hop2["related"]["notice"] == f"ev:{notice}"
    assert hop2["related"]["same_thread"] == ["trg:mail:m43"]
    hop3 = _run(rc.recall(hop2["related"]["result"]))
    assert hop3["id"] == f"ev:{result}"
    assert "Reference 8841" in hop3["text"]


def test_three_hops_from_a_report_to_its_job_thread_and_agent(store, ledger):
    """Report -> job -> thread (and the agent), through returned ids only."""
    lead = _lead(store)
    agent = store.create_session(
        provider="x", model="m", effort="", cwd=".", title="Scout chat", surface="society"
    )
    request_id = "env-77"
    jid = jobs.job_id_for("society_assignment", request_id)
    jobs.start(
        "society_assignment",
        job_id=jid,
        owner=(agent.session_id, ""),
        target="scout",
        title="Scout: check the PR",
    )
    jobs.finish(jid, "done", summary="PR 41 is green", result_ref=f"society:{request_id}")
    report = _add(
        store,
        lead,
        "notice",
        kind="coding_result",
        assignment_id=request_id,
        agent_name="Scout",
        status="done",
        text="PR 41 is green and ready.",
    )

    async def agents(agent_id: str):
        return {
            "agent_id": agent_id,
            "name": "Scout",
            "title": "Reviewer",
            "state": "active",
            "provider": "x",
            "model": "m",
            "session_id": agent.session_id,
        }

    rc = recall.Recall(_sources(store, ledger, agent=agents))
    hop1 = _run(rc.recall(f"ev:{report}"))
    job_ref = hop1["related"]["jobs"][0]
    hop2 = _run(rc.recall(job_ref))
    assert hop2["state"] == "done" and hop2["related"]["result"] == f"ev:{report}"
    thread_ref = hop2["related"]["thread"]
    hop3 = _run(rc.recall(thread_ref))
    assert hop3["summary"] == "Scout chat" and job_ref in hop3["related"]["jobs"]
    who = _run(rc.recall(hop2["related"]["agent"]))
    assert who["related"]["thread"] == thread_ref and job_ref in who["related"]["jobs"]
