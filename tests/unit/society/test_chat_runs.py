"""Chat turns count as agent runs on the Record (dodaios/society/chat_runs.py)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from dodaios.agent_chat.events import make_event
from dodaios.agent_chat.service import AgentChatService
from dodaios.agent_chat.store import AgentChatStore
from dodaios.society.chat_runs import ChatRunLedger
from dodaios.society.events import MsgType, SocietyEnvelope
from dodaios.society.store import SocietyStore


@pytest.fixture
async def store(tmp_path: Path):
    s = SocietyStore(tmp_path / "society.db")
    await s.open()
    try:
        yield s
    finally:
        await s.close()


def _result(agent: str, run_id: str) -> SocietyEnvelope:
    return SocietyEnvelope(
        msg_type=MsgType.RESULT,
        from_agent=agent,
        trace_id="t",
        payload={"run_id": run_id, "status": "done", "done": "x", "output": []},
    )


def _session(chat: AgentChatStore, session_id: str, runtime: str = "") -> None:
    chat.create_session(
        session_id=session_id,
        surface="society",
        provider="claude-cli",
        model="",
        effort="",
        cwd=".",
        runtime=runtime,
    )


def _finish(turn_id: str, status: str = "done") -> dict[str, Any]:
    return make_event("turn_finished", {"turn_id": turn_id, "status": status})


async def _settle(ledger: ChatRunLedger) -> None:
    for _ in range(5):
        await asyncio.sleep(0)
    if ledger._writes:
        await asyncio.gather(*list(ledger._writes))


async def test_chat_turns_count_as_runs_and_activity(store: SocietyStore):
    assert (await store.agent_stats("ada"))["runs"] == 0
    added = await store.record_chat_turns([
        ("t1", "ada", "society:ada", 1_000, "done"),
        ("t2", "ada", "society:ada", 2_000, "error"),
    ])
    assert added == 2
    stats = await store.agent_stats("ada")
    assert stats["runs"] == 2
    assert stats["last_active_ms"] == 2_000
    # Idempotent by turn id.
    assert await store.record_chat_turns([("t1", "ada", "society:ada", 1_000, "done")]) == 0
    assert (await store.agent_stats("ada"))["runs"] == 2
    assert (await store.agent_stats("bob"))["runs"] == 0


async def test_a_board_dispatch_counts_once(store: SocietyStore):
    # The dispatched turn finished in the chat and sent its RESULT.
    await store.record_chat_turns([("t1", "ada", "society:ada", 1_000, "done")])
    await store.append_and_publish(_result("ada", "turn:t1"))
    # A mission RESULT is a run with no chat turn behind it.
    await store.append_and_publish(_result("ada", "mission-7"))
    assert (await store.agent_stats("ada"))["runs"] == 2


async def test_listener_counts_every_society_chat_once(store: SocietyStore):
    chat = AgentChatStore()
    service = AgentChatService(chat)
    for sid, runtime in (
        ("society:ada", "claude-cli"),
        ("society:ada:routine:r1:abc", ""),
        ("society:ada:with:bob", "hermes"),
        ("society:cat", "openclaw"),
    ):
        _session(chat, sid, runtime)
    plain = chat.create_session(provider="claude-cli", model="", effort="", cwd=".")
    runtime = SimpleNamespace(store=store, chat_service=lambda: service)
    ledger = ChatRunLedger(runtime)
    await ledger.start()
    try:
        await service._emit("society:ada", _finish("a1"))
        await service._emit("society:ada", _finish("a1"))  # a duplicate completion
        text = make_event("assistant_text", {"turn_id": "a2", "text": "hi"})
        await service._emit("society:ada", text)
        await service._emit("society:ada:routine:r1:abc", _finish("r1"))
        await service._emit("society:ada:with:bob", _finish("p1", "cancelled"))
        await service._emit("society:cat", _finish("c1"))
        await service._emit(plain.session_id, _finish("x1"))
        await _settle(ledger)
        ada = await store.agent_stats("ada")
        assert ada["runs"] == 3
        assert ada["last_active_ms"] is not None
        assert (await store.agent_stats("cat"))["runs"] == 1
    finally:
        await ledger.close()
    assert service._event_listeners == []


async def test_earlier_turns_are_read_back_once(store: SocietyStore):
    chat = AgentChatStore()
    _session(chat, "society:ada")
    _session(chat, "society:ada:routine:r1:abc")
    chat.append_event("society:ada", _finish("old1"))
    chat.append_event("society:ada:routine:r1:abc", _finish("old2"))
    chat.append_event("society:ada", make_event("turn_started", {"turn_id": "old3"}))
    assert [row[1] for row in chat.finished_turns("society:")] == ["old1", "old2"]
    service = SimpleNamespace(
        store=chat,
        add_event_listener=lambda _fn: None,
        remove_event_listener=lambda _fn: None,
    )
    runtime = SimpleNamespace(store=store, chat_service=lambda: service)
    first = ChatRunLedger(runtime)
    await first.start()
    await first.close()
    assert (await store.agent_stats("ada"))["runs"] == 2
    # Backfilled once: a turn the chat store gains later is the listener's job.
    chat.append_event("society:ada", _finish("old4"))
    second = ChatRunLedger(runtime)
    await second.start()
    await second.close()
    assert (await store.agent_stats("ada"))["runs"] == 2


async def test_results_without_a_run_id_leave_chat_turns_counted(store: SocietyStore):
    # A RESULT with no run_id must not hide the chat turns (SQL NULL in IN).
    await store.append_and_publish(
        SocietyEnvelope(
            msg_type=MsgType.RESULT,
            from_agent="ada",
            trace_id="t",
            payload={"status": "done", "done": "x", "output": []},
        )
    )
    await store.record_chat_turns([
        ("t1", "ada", "society:ada", 1_000, "done"),
        ("t2", "ada", "society:ada", 2_000, "done"),
    ])
    await store.append_and_publish(_result("ada", "turn:t2"))
    # Another agent's RESULT for the same turn id does not dedupe ada's turn.
    await store.append_and_publish(_result("bob", "turn:t1"))
    assert (await store.agent_stats("ada"))["runs"] == 3
