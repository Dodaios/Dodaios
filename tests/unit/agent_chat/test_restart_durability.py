"""What the person decided or is waiting for survives an app restart.

Every test builds a second service (or queue owner) over the same database file
as the "restarted" process.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from dodaios.agent_chat import delegation_wait, parked_work, send_queue
from dodaios.agent_chat import service as service_mod
from dodaios.agent_chat.events import make_event
from dodaios.agent_chat.screen_reference import is_away
from dodaios.agent_chat.send_queue import recover_waiting, send_or_queue
from dodaios.agent_chat.service import AgentChatService, SessionBusy
from dodaios.agent_chat.store import AgentChatStore
from dodaios.core.delegated_work import DelegatedWork, register_delegated_work
from dodaios.orchestrator import jobs
from dodaios.tasks.context import client_timezone


async def _until(predicate, limit_s: float = 5.0) -> None:
    deadline = asyncio.get_running_loop().time() + limit_s
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition not reached")
        await asyncio.sleep(0.005)


# --------------------------------------------------------------- send queue


class QueueChat:
    """Just enough of the chat service around a REAL store (one process)."""

    def __init__(self, store: AgentChatStore, *, busy: bool) -> None:
        self.store = store
        self.busy = busy
        self.sent: list[dict] = []

    def is_running(self, session_id: str) -> bool:
        return self.busy

    async def send(self, session_id, text, attachments=None, *, tool_choices=None) -> str:
        if self.busy:
            raise SessionBusy(session_id)
        self.sent.append({
            "text": text, "attachments": attachments, "tool_choices": tool_choices,
            "timezone": client_timezone.get(), "away": is_away(),
        })
        return f"turn-{len(self.sent)}"

    async def post_notice(self, session_id: str, payload: dict) -> None:
        self.store.append_event(session_id, make_event("notice", dict(payload)))

    def notices(self, session_id: str, kind: str) -> list[dict]:
        return [
            e["payload"] for e in self.store.list_events(session_id)
            if e["kind"] == "notice" and e["payload"].get("kind") == kind
        ]


@pytest.fixture
def store(tmp_path: Path):
    built = AgentChatStore(tmp_path / "agent_chat.db")
    yield built
    built.close()


@pytest.fixture(autouse=True)
def ledger():
    ledger = jobs.JobLedger(":memory:")
    jobs.set_ledger(ledger)
    try:
        yield ledger
    finally:
        jobs.set_ledger(None)
        ledger.close()


@pytest.fixture(autouse=True)
def fast_polls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(send_queue, "_POLL_S", 0.005)
    monkeypatch.setattr(parked_work, "_POLL_S", 0.005)
    monkeypatch.setattr(delegation_wait, "POLL_SECONDS", 0.005)


def _lead(store: AgentChatStore) -> str:
    return store.create_session(
        provider="openai", model="", effort="", surface="jarvis", cwd="."
    ).session_id


async def test_waiting_messages_are_queued_again_after_a_restart_in_order(store):
    sid = _lead(store)
    before = QueueChat(store, busy=True)
    tokens = client_timezone.set("Europe/Berlin")
    try:
        _, first = await send_or_queue(before, sid, "first", tool_choices=["web"])
    finally:
        client_timezone.reset(tokens)
    from dodaios.agent_chat.screen_reference import away_from_screen

    with away_from_screen(True):
        _, second = await send_or_queue(
            before, sid, "", [{"name": "plan.pdf", "detail": "text"}]
        )
    assert first and second
    for task in [q.drain for q in before._society_send_queues.values() if q.drain]:
        task.cancel()  # the old process is gone

    after = QueueChat(store, busy=False)
    assert await recover_waiting(after) == 2
    await _until(lambda: len(after.sent) == 2)
    assert after.sent[0] == {
        "text": "first", "attachments": None, "tool_choices": ["web"],
        "timezone": "Europe/Berlin", "away": False,
    }
    assert after.sent[1]["attachments"] == [{"name": "plan.pdf", "detail": "text"}]
    assert after.sent[1]["away"] is True  # the away flag travels with the message
    await _until(lambda: len(after.notices(sid, "message_dequeued")) == 2)
    sent = after.notices(sid, "message_dequeued")
    assert [n["queue_id"] for n in sent] == [first, second]
    assert all(n["status"] == "sent" for n in sent)
    # Nothing is left to recover, so a third boot sends nothing again.
    assert store.sessions_with_waiting_messages() == []
    assert await recover_waiting(QueueChat(store, busy=False)) == 0


async def test_a_message_answered_before_the_restart_is_not_sent_again(store):
    sid = _lead(store)
    before = QueueChat(store, busy=True)
    _, queue_id = await send_or_queue(before, sid, "once")
    before.busy = False
    await _until(lambda: before.sent)
    await _until(lambda: before.notices(sid, "message_dequeued"))
    after = QueueChat(store, busy=False)
    assert await recover_waiting(after) == 0
    assert after.sent == [] and queue_id


async def test_a_stale_message_is_not_resent_but_closed_with_a_written_notice(store):
    sid = _lead(store)
    before = QueueChat(store, busy=True)
    _, queue_id = await send_or_queue(before, sid, "old request")
    for task in [q.drain for q in before._society_send_queues.values() if q.drain]:
        task.cancel()
    with store._lock:
        store._conn.execute(
            "UPDATE agent_chat_queued_messages SET queued_ms = queued_ms - ?",
            (int((send_queue.STALE_AFTER_S + 60) * 1000),),
        )
        store._conn.commit()

    after = QueueChat(store, busy=False)
    assert await recover_waiting(after) == 0
    await asyncio.sleep(0.05)
    assert after.sent == []
    [closed] = after.notices(sid, "message_dequeued")
    assert closed["queue_id"] == queue_id and closed["status"] == "failed"
    assert closed["text"] == "old request" and closed["reason"] == "stale_after_restart"


# -------------------------------------------------------- parked delegation


class Chat:
    """The real chat service with a scripted model in place of a provider."""

    def __init__(self, tmp_path, monkeypatch, store: AgentChatStore) -> None:
        self.store = store
        self.svc = AgentChatService(store)
        self.sid = _lead(store)
        self.prompts: list[tuple[str, str]] = []
        self.pane_done = False
        monkeypatch.setattr(service_mod, "run_brain_turn", self._model)
        monkeypatch.setattr(service_mod, "resolve_runner", lambda *a, **kw: "brain")

    async def _model(self, handle, prompt, *args, **kwargs) -> None:
        index = len(self.prompts)
        self.prompts.append((handle.turn_id, prompt))
        if index == 0:

            async def pane():
                if not self.pane_done:
                    return None
                return {"status": "completed", "report": "The login bug is fixed."}

            assert register_delegated_work(DelegatedWork("society:evt-1", "Agent T2", pane))
        text = "Sent to the agent." if index == 0 else "Here is the result."
        await handle.emit(make_event("assistant_text", {"turn_id": handle.turn_id, "text": text}))
        await handle.emit(make_event(
            "turn_finished", {"turn_id": handle.turn_id, "status": "done", "usage": {}},
        ))

    def restart(self) -> None:
        """The old process dies: its waits stop without any record of a stop."""
        for item in self.svc.parked_work.running(self.sid):
            if item.task is not None:
                item.task.cancel()
        self.svc = AgentChatService(self.store)


async def _park_one_request(chat: Chat) -> None:
    await send_or_queue(chat.svc, chat.sid, "Brief the agent about the login bug.")
    await _until(lambda: any(
        "Waiting for agents" in e["payload"].get("text", "")
        for e in chat.store.list_events(chat.sid) if e["kind"] == "reasoning"
    ))
    # A second message makes the first turn hand its seat over.
    await send_or_queue(chat.svc, chat.sid, "And one more thing.")
    await _until(lambda: chat.svc.parked_work.running(chat.sid))
    await _until(lambda: not chat.svc.is_running(chat.sid))


async def test_a_parked_wait_is_saved_and_continues_once_after_a_restart(
    store, tmp_path, monkeypatch
):
    chat = Chat(tmp_path, monkeypatch, store)
    await _park_one_request(chat)
    [saved] = store.parked_work()
    assert saved["work"] == [{"key": "society:evt-1", "name": "Agent T2"}]
    assert saved["original"].startswith("Brief the agent")
    prompts_before = len(chat.prompts)

    chat.restart()
    reports = {"pane-done": False}

    async def resolver(key, name):
        async def probe():
            if not reports["pane-done"]:
                return None
            return {"status": "completed", "report": "The login bug is fixed."}

        return DelegatedWork(key, name, probe)

    chat.svc.parked_work.resolver = resolver
    await chat.svc.recover_after_restart()
    [again] = chat.svc.parked_work.running(chat.sid)
    assert again.names() == ["Agent T2"] and again.request.startswith("Brief the agent")
    await asyncio.sleep(0.05)
    assert len(chat.prompts) == prompts_before  # nothing is invented while it still works

    reports["pane-done"] = True
    await _until(lambda: len(chat.prompts) == prompts_before + 1)
    assert "The login bug is fixed." in chat.prompts[-1][1]
    await _until(lambda: store.parked_work() == [])
    await asyncio.sleep(0.1)
    assert len(chat.prompts) == prompts_before + 1  # the continuation ran exactly once

    chat.restart()
    await chat.svc.recover_after_restart()
    assert chat.svc.parked_work.running(chat.sid) == []  # and a later boot finds nothing


async def test_work_that_died_with_the_process_reports_interrupted(store, tmp_path, monkeypatch):
    chat = Chat(tmp_path, monkeypatch, store)
    await _park_one_request(chat)
    prompts_before = len(chat.prompts)
    chat.restart()
    # No society runtime in this test: the wait cannot be read again, so it says so.
    await chat.svc.recover_after_restart()
    await _until(lambda: len(chat.prompts) == prompts_before + 1)
    assert "interrupted" in chat.prompts[-1][1]
    assert "restarted" in chat.prompts[-1][1]


async def test_saved_work_is_read_from_the_jobs_ledger(store, tmp_path, monkeypatch):
    chat = Chat(tmp_path, monkeypatch, store)
    await _park_one_request(chat)
    prompts_before = len(chat.prompts)
    job_id = jobs.job_id_for("society_assignment", "evt-1")
    jobs.start("society_assignment", job_id=job_id, title="Agent T2: login bug",
               owner=(chat.sid, "t1"))
    chat.restart()
    monkeypatch.setattr(jobs, "BOOT_ID", "the-next-boot")  # the ledger row is from the old boot
    await chat.svc.recover_after_restart()
    await _until(lambda: len(chat.prompts) == prompts_before + 1)
    # No evidence can be re-read here (no society runtime), so the ledger's rule applies.
    assert "interrupted" in chat.prompts[-1][1]
    assert jobs.get_ledger().get(job_id).state == "interrupted"


async def test_stopping_the_chat_removes_the_saved_wait(store, tmp_path, monkeypatch):
    chat = Chat(tmp_path, monkeypatch, store)
    await _park_one_request(chat)
    assert store.parked_work()
    chat.svc.parked_work.stop(chat.sid)
    assert store.parked_work() == []


async def test_a_saved_wait_of_a_deleted_chat_is_dropped(store, tmp_path, monkeypatch):
    chat = Chat(tmp_path, monkeypatch, store)
    await _park_one_request(chat)
    chat.restart()
    store.delete_session(chat.sid)
    assert store.parked_work() == []  # deleting the chat takes its waits along


async def test_an_old_saved_wait_is_reported_lost_instead_of_answered(
    store, tmp_path, monkeypatch
):
    chat = Chat(tmp_path, monkeypatch, store)
    await _park_one_request(chat)
    prompts_before = len(chat.prompts)
    chat.restart()
    with store._lock:
        store._conn.execute(
            "UPDATE agent_chat_parked_work SET created_ms = created_ms - ?",
            (int((parked_work.STALE_AFTER_S + 60) * 1000),),
        )
        store._conn.commit()
    await chat.svc.recover_after_restart()
    await asyncio.sleep(0.05)
    assert len(chat.prompts) == prompts_before
    lost = [
        e["payload"] for e in store.list_events(chat.sid)
        if e["kind"] == "notice" and e["payload"].get("kind") == "background_result_lost"
    ]
    assert len(lost) == 1 and store.parked_work() == []


# --------------------------------------------------------- approval choices


def test_always_allow_and_narrow_rules_survive_a_restart(store):
    sid = _lead(store)
    first = AgentChatService(store)
    first.always_allowed(sid).add("mcp__mail__read")
    first._tool_always.setdefault(sid, set()).add("Edit")
    first._narrow_rules.setdefault(sid, []).append(
        {"tool": "Bash", "kind": "command", "value": "git status"}
    )
    first.cli_session_rules(sid).extend([{"toolName": "Bash", "ruleContent": "ls"}])

    second = AgentChatService(store)  # the restart
    assert second.always_allowed(sid) == {"mcp__mail__read"}
    assert second._tool_always[sid] == {"Edit"}
    assert second._narrow_rules[sid] == [
        {"tool": "Bash", "kind": "command", "value": "git status"}
    ]
    assert second.cli_session_rules(sid) == [{"toolName": "Bash", "ruleContent": "ls"}]
    # The scope is the chat they were given in.
    other = _lead(store)
    assert second.always_allowed(other) == set()
    assert second._narrow_allows(other, "Bash", {"command": "git status"}) is False


def test_a_revoked_rule_stays_revoked_after_a_restart(store):
    sid = _lead(store)
    first = AgentChatService(store)
    first.always_allowed(sid).add("mcp__mail__read")
    first._tool_always.setdefault(sid, set()).add("mcp__mail__read")
    first._narrow_rules.setdefault(sid, []).append(
        {"tool": "bash", "kind": "folder", "value": "/work"}
    )
    first.forget_standing_rule({"tool": "mcp__mail__read", "kind": "tool"})
    first.forget_standing_rule({"tool": "bash", "kind": "folder", "target": "/work"})

    second = AgentChatService(store)
    assert second.always_allowed(sid) == set()
    assert second._tool_always.get(sid, set()) == set()
    assert second._narrow_rules.get(sid, []) == []


def test_deleting_a_chat_deletes_its_saved_rules(store):
    sid = _lead(store)
    AgentChatService(store).always_allowed(sid).add("Edit")
    store.delete_session(sid)
    assert store.approval_memory() == []


# ------------------------------------------------------------- voice dedup


async def test_a_voice_turn_is_filed_once_even_across_a_restart_and_a_big_backlog(store):
    sid = _lead(store)
    first = AgentChatService(store)
    assert await first.import_voice_turn(sid, "hi", "hello", voice_turn_id="v-1")
    assert await first.import_voice_turn(sid, "hi", "hello", voice_turn_id="v-1") is None
    # The old in-memory set was cleared at 2,000 entries and forgot v-1 then.
    for index in range(2105):
        store.claim_voice_turn(f"filler-{index}", sid)
    assert await first.import_voice_turn(sid, "hi", "hello", voice_turn_id="v-1") is None

    second = AgentChatService(store)  # restart: the bus redelivers the same turn
    assert await second.import_voice_turn(sid, "hi", "hello", voice_turn_id="v-1") is None
    assert len([e for e in store.list_events(sid) if e["kind"] == "user_message"]) == 1
    assert await second.import_voice_turn(sid, "again", "ok", voice_turn_id="v-2")


def test_the_voice_turn_id_is_unique_in_the_database(store):
    assert store.claim_voice_turn("x", "s") is True
    assert store.claim_voice_turn("x", "s") is False
    store.release_voice_turn("x")
    assert store.claim_voice_turn("x", "s") is True


def test_a_service_never_starts_recovery_by_itself(store):
    assert AgentChatService(store)._restart_recovery_task is None
