"""The one way a follow-up order reaches a thread, and what the lead's wait is told meanwhile."""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

import pytest

from dodaios.agent_chat.events import make_event
from dodaios.agent_chat.store import AgentChatStore
from dodaios.orchestrator.verification import probe, prompts, send
from dodaios.orchestrator.verification import recorder as rec
from dodaios.orchestrator.verification.store import VerificationStore

# ---------------------------------------------------------------------- send


class Service:
    """A chat service as far as the send path sees it."""

    def __init__(self, store: AgentChatStore) -> None:
        self.store = store
        self.running: set[str] = set()
        self.questions: list[str] = []
        self.approvals: list[str] = []
        self.calls: list[dict[str, Any]] = []
        self.fail: Exception | None = None

    def is_running(self, session_id: str) -> bool:
        return session_id in self.running

    def pending_questions(self, _session_id: str) -> list[str]:
        return self.questions

    def pending_approvals(self, _session_id: str) -> list[str]:
        return self.approvals

    async def send(self, session_id: str, text: str, **kwargs: Any) -> str:
        if self.fail is not None:
            raise self.fail
        self.calls.append({"session_id": session_id, "text": text, **kwargs})
        return "turn-2"


@pytest.fixture
def chat(tmp_path):
    store = AgentChatStore(tmp_path / "agent_chat.db")
    session = store.create_session(
        provider="claude-api", model="m", effort="low", cwd=str(tmp_path), surface="agent"
    )
    return store, session.session_id


def _ended_turn(store: AgentChatStore, sid: str, status: str = "done") -> None:
    store.append_event(sid, make_event("turn_started", {"turn_id": "t1"}))
    store.append_event(sid, make_event("assistant_text", {"turn_id": "t1", "text": "Done."}))
    store.append_event(sid, make_event("turn_finished", {"turn_id": "t1", "status": status}))


async def test_an_order_goes_out_with_the_app_as_its_author(chat):
    store, sid = chat
    _ended_turn(store, sid)
    service = Service(store)
    turn = await send.follow_up(service, sid, "Fix the test.", run_id="job_1", iteration=0)
    assert turn == "turn-2"
    [call] = service.calls
    assert call["text"] == "Fix the test."
    assert call["direct_user"] is False
    assert call["author"] == {
        "agent_id": prompts.AUTHOR_ID, "name": prompts.AUTHOR_NAME, "run": "job_1",
        "iteration": "0",
    }
    assert send.is_follow_up({"author": call["author"]})
    assert not send.is_follow_up({"author": {"agent_id": "jarvis"}})
    assert not send.is_follow_up({})


@pytest.mark.parametrize(
    ("setup", "reason"),
    [
        (lambda svc, store, sid: svc.running.add(sid), "in a turn"),
        (lambda svc, store, sid: svc.questions.append("q1"), "waits for the person"),
        (lambda svc, store, sid: svc.approvals.append("a1"), "waits for the person"),
        (
            lambda svc, store, sid: store.append_event(
                sid, make_event("plan_ready", {"turn_id": "t1", "plan": "1. do it"})
            ),
            "waits for the person",
        ),
        (
            lambda svc, store, sid: store.append_event(
                sid, make_event("user_message", {"text": "let me do this"})
            ),
            "the person wrote",
        ),
    ],
)
async def test_an_order_is_never_sent_into_a_thread_that_is_not_the_agents(chat, setup, reason):
    store, sid = chat
    _ended_turn(store, sid)
    service = Service(store)
    setup(service, store, sid)
    with pytest.raises(send.Refused, match=reason):
        await send.follow_up(service, sid, "Fix it.", run_id="job_1", iteration=0)
    assert service.calls == []


async def test_a_stopped_turn_or_a_deleted_thread_takes_no_order(chat):
    store, sid = chat
    _ended_turn(store, sid, status="cancelled")
    service = Service(store)
    with pytest.raises(send.Refused, match="stopped"):
        await send.follow_up(service, sid, "Fix it.", run_id="job_1", iteration=0)
    with pytest.raises(send.Refused, match="no longer exists"):
        await send.follow_up(service, "gone", "Fix it.", run_id="job_1", iteration=0)


async def test_a_message_the_lead_wrote_is_not_the_person_stepping_in(chat):
    store, sid = chat
    _ended_turn(store, sid)
    store.append_event(
        sid, make_event("user_message", {"text": "x", "author": {"agent_id": "jarvis"}})
    )
    service = Service(store)
    assert await send.follow_up(service, sid, "Fix.", run_id="job_1", iteration=0) == "turn-2"


async def test_a_refusal_of_the_chat_service_is_a_refusal(chat):
    from dodaios.agent_chat.service import SessionBusy

    store, sid = chat
    _ended_turn(store, sid)
    service = Service(store)
    service.fail = SessionBusy("busy")
    with pytest.raises(send.Refused):
        await send.follow_up(service, sid, "Fix.", run_id="job_1", iteration=0)


# --------------------------------------------------------------------- probe


@pytest.fixture
def checking(tmp_path):
    store = VerificationStore(tmp_path / "verification.db")
    made = rec.RunRecorder(store, SimpleNamespace(store=None), verify="enforce")
    rec.set_recorder(made)
    try:
        yield store
    finally:
        rec.set_recorder(None)
        store.close()


def _run(store: VerificationStore, state: str, *, started_ms: int = 0, **fields: Any) -> None:
    store.start_run(
        "job_1", "s1", state="running", started_ms=started_ms or int(time.time() * 1000)
    )
    store.update_run("job_1", state=state, **fields)


COMPLETED = {"status": "completed", "report": "All done.", "evidence": "thread completion"}


def test_while_the_output_is_checked_the_wait_is_told_it_still_runs(checking):
    now = int(time.time() * 1000)
    _run(checking, "checking", ended_ms=now, heartbeat_ms=now, iteration=1)
    answer = probe.shape("job_1", COMPLETED)
    assert answer["status"] == "running"
    assert answer["progress"] == f"check:1:{now}"
    # Its progress moves with the check's signs of life, so the wait does not give up.
    checking.update_run("job_1", heartbeat_ms=now + 1)
    assert probe.shape("job_1", COMPLETED)["progress"] != answer["progress"]


def test_a_turn_that_runs_speaks_for_itself(checking):
    _run(checking, "running")
    found = {"status": "running", "progress": "41"}
    assert probe.shape("job_1", found) is found


@pytest.mark.parametrize("status", ["needs_input", "stopped"])
def test_a_thread_that_needs_the_person_is_passed_on_at_once(checking, status):
    _run(checking, "checking", heartbeat_ms=int(time.time() * 1000))
    found = {"status": status, "report": "It asks: which database?"}
    assert probe.shape("job_1", found) is found


@pytest.mark.parametrize(
    ("verdict", "status", "detail", "says"),
    [
        ("verified", "completed", "verified", "Checked by the app"),
        ("unverified", "completed", "unverified", "Not verified by the app"),
        ("failed", "failed", "failed", "The app's check failed it"),
        ("superseded", "superseded", "superseded", "Not judged"),
        ("needs_decision", "needs_input", "needs_decision", "asks for a decision"),
    ],
)
def test_the_verdict_is_told_in_words_the_jobs_ledger_knows(
    checking, verdict, status, detail, says
):
    from dodaios.orchestrator import jobs

    _run(checking, "ended", verdict=verdict, verdict_reason="pull request #4 is merged")
    answer = probe.shape("job_1", COMPLETED)
    assert (answer["status"], answer["detail"]) == (status, detail)
    assert says in str(answer.get("evidence") or answer.get("report"))
    # A question waits for the person ("blocked" moves on with the answer); every
    # other verdict closes the job in a word the ledger knows.
    wanted = {"needs_input": "blocked", "superseded": "cancelled", "failed": "failed"}
    assert jobs.state_from_status(answer["status"]) == wanted.get(status, "done")


def test_the_agents_own_answer_rides_along_with_a_completed_verdict(checking):
    _run(checking, "ended", verdict="verified", verdict_reason="checks pass")
    assert probe.shape("job_1", COMPLETED)["report"] == "All done."


def test_a_check_that_went_silent_leaves_the_threads_own_word(checking):
    old = int(time.time() * 1000) - probe.STALE_MS - 1000
    _run(checking, "checking", started_ms=old - 5000, ended_ms=old, heartbeat_ms=old)
    assert probe.shape("job_1", COMPLETED) is COMPLETED
    # Without a word of its own the wait keeps waiting.
    assert probe.shape("job_1", None)["status"] == "running"


def test_an_order_whose_record_is_still_being_written_is_not_over(checking):
    current = rec.recorder()
    current.note_submission(job_id="job_7", session_id="s7", prompt="Fix", started_ms=1)
    assert probe.shape("job_7", COMPLETED) == {"status": "running", "progress": "check:noted"}
    asks = {"status": "needs_input", "report": "It asks."}
    assert probe.shape("job_7", asks) is asks
    current.process_pending()
    assert not current.is_noted("job_7")


def test_without_enforcement_or_a_record_nothing_changes(checking, tmp_path):
    assert probe.shape("job_unknown", COMPLETED) is COMPLETED
    assert probe.shape("", COMPLETED) is COMPLETED
    observing = rec.RunRecorder(checking, SimpleNamespace(store=None), verify="observe")
    rec.set_recorder(observing)
    _run(checking, "checking", heartbeat_ms=int(time.time() * 1000))
    assert probe.shape("job_1", COMPLETED) is COMPLETED
    rec.set_recorder(None)
    assert probe.shape("job_1", COMPLETED) is COMPLETED
