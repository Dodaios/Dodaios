"""A slow chat-history write never stalls the event loop.

Every streamed event of a running turn ends in an SQLite commit. On a
Windows PC with a full disk one commit took 15 s on the event loop, and the
Dodaios Bar froze mid-dictation with nothing pasted. The write now runs on a
worker thread, and the events of one chat still arrive in the order they were
sent.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

import pytest

from dodaios.agent_chat.events import make_event
from dodaios.agent_chat.service import AgentChatService
from dodaios.agent_chat.store import AgentChatStore


class _SlowStore(AgentChatStore):
    """A store whose next write waits until the test lets it through."""

    def __init__(self) -> None:
        super().__init__(":memory:")
        self.hold = threading.Event()
        self.hold.set()
        self.writer_threads: list[int] = []

    def append_event(self, session_id: str, event: dict[str, Any]) -> dict[str, Any]:
        self.writer_threads.append(threading.get_ident())
        if not self.hold.wait(timeout=5):
            raise AssertionError("the test never released the write")
        return super().append_event(session_id, event)


@pytest.mark.asyncio
async def test_a_slow_write_leaves_the_loop_free(tmp_path: Path) -> None:
    store = _SlowStore()
    svc = AgentChatService(store)
    session = svc.create_session(provider="openai-codex", cwd=str(tmp_path))

    store.hold.clear()
    emit = asyncio.create_task(
        svc._emit(session.session_id, make_event("notice", {"text": "slow"}))
    )
    ticks = 0
    for _ in range(20):
        await asyncio.sleep(0.01)
        ticks += 1
    assert ticks == 20
    assert not emit.done()

    store.hold.set()
    await asyncio.wait_for(emit, timeout=5)
    assert threading.get_ident() not in store.writer_threads
    texts = [e["payload"].get("text") for e in store.list_events(session.session_id)]
    assert "slow" in texts


@pytest.mark.asyncio
async def test_one_chats_events_keep_their_order(tmp_path: Path) -> None:
    store = _SlowStore()
    svc = AgentChatService(store)
    session = svc.create_session(provider="openai-codex", cwd=str(tmp_path))
    inbox = svc.subscribe(session.session_id)

    store.hold.clear()
    first = asyncio.create_task(
        svc._emit(session.session_id, make_event("notice", {"text": "first"}))
    )
    await asyncio.sleep(0.02)
    second = asyncio.create_task(
        svc._emit(session.session_id, make_event("notice", {"text": "second"}))
    )
    await asyncio.sleep(0.02)
    store.hold.set()
    await asyncio.wait_for(asyncio.gather(first, second), timeout=5)

    got = [inbox.get_nowait() for _ in range(inbox.qsize())]
    assert [e["payload"]["text"] for e in got] == ["first", "second"]
    assert got[0]["seq"] < got[1]["seq"]


def test_the_chat_database_does_not_wait_for_the_disk_at_each_commit(tmp_path: Path) -> None:
    store = AgentChatStore(tmp_path / "agent_chat.db")
    level = store._conn.execute("PRAGMA synchronous").fetchone()[0]
    assert level == 1  # NORMAL
