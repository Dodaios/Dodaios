"""What the UI learns when a turn ends, and a reader that fell behind.

* ``turn_finished`` is published only once the session reads as not running,
  so a session list fetched because of it never says ``running: true``.
* A websocket reader whose queue overflowed is told so and its socket closes,
  so the client reconnects and re-syncs from its last seq instead of waiting
  forever on a queue nothing feeds any more.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from dodaios.agent_chat.events import make_event
from dodaios.agent_chat.service import SUBSCRIBER_DROPPED, AgentChatService, _Running
from dodaios.agent_chat.store import AgentChatStore
from dodaios.ui.web.agent_chat_routes import router


@pytest.fixture
def service(tmp_path):
    store = AgentChatStore(":memory:")
    svc = AgentChatService(store)
    yield svc
    store.close()


def _session(svc: AgentChatService, tmp_path) -> str:
    return svc.store.create_session(
        provider="openai", model="fake", effort="", cwd=str(tmp_path)
    ).session_id


async def test_a_full_subscriber_is_told_and_dropped(service, tmp_path) -> None:
    sid = _session(service, tmp_path)
    q = service.subscribe(sid)
    for i in range(q.maxsize):
        q.put_nowait({"kind": "text_delta", "seq": 0, "n": i})
    service._publish_event(sid, make_event("notice", {"text": "one too many"}))
    assert q.qsize() == 1
    assert q.get_nowait() is SUBSCRIBER_DROPPED
    assert q not in service._subscribers.get(sid, set())
    # Later events no longer reach it.
    service._publish_event(sid, make_event("notice", {"text": "after"}))
    assert q.empty()


async def test_the_turn_reads_finished_when_its_turn_finished_is_heard(
    service, tmp_path
) -> None:
    sid = _session(service, tmp_path)
    run = _Running("t1", asyncio.Event())
    cleanup = asyncio.Event()
    run.task = asyncio.create_task(cleanup.wait())
    service._running[sid] = run
    heard: list[tuple[bool, bool]] = []
    service._event_listeners.append(
        lambda s, ev: heard.append((service.reports_running(s), service.is_running(s)))
        if ev["kind"] == "turn_finished"
        else None
    )
    assert service.reports_running(sid)
    service._publish_event(
        sid, make_event("turn_finished", {"turn_id": "t1", "status": "done", "usage": {}})
    )
    # The UI hears "not running"; the task itself still cleans up.
    assert heard == [(False, True)]
    # A send arriving now waits for that cleanup instead of failing busy.
    waiter = asyncio.create_task(service._await_finishing(sid))
    await asyncio.sleep(0.05)
    assert not waiter.done()
    cleanup.set()
    await asyncio.wait_for(waiter, 2)
    assert not service.is_running(sid)


async def test_another_turns_finish_does_not_end_the_running_one(service, tmp_path) -> None:
    sid = _session(service, tmp_path)
    run = _Running("t2", asyncio.Event())
    run.task = asyncio.create_task(asyncio.sleep(5))
    service._running[sid] = run
    try:
        service._publish_event(
            sid, make_event("turn_finished", {"turn_id": "old", "status": "done", "usage": {}})
        )
        assert service.reports_running(sid)
    finally:
        run.task.cancel()


def test_the_websocket_closes_when_its_subscriber_was_dropped(tmp_path) -> None:
    store = AgentChatStore(tmp_path / "chat.db")
    svc = AgentChatService(store)
    sid = _session(svc, tmp_path)
    original = svc.subscribe

    def subscribe_then_fall_behind(session_id):
        q = original(session_id)
        svc._drop_subscriber(session_id, q)
        return q

    svc.subscribe = subscribe_then_fall_behind  # type: ignore[method-assign]
    app = FastAPI()
    app.include_router(router)
    app.state.agent_chat = svc
    try:
        with TestClient(app) as client:
            with client.websocket_connect(f"/api/agent-chat/sessions/{sid}/ws") as ws:
                assert ws.receive_json()["type"] == "snapshot"
                with pytest.raises(WebSocketDisconnect) as closed:
                    ws.receive_json()
                assert closed.value.code == 1013
    finally:
        store.close()
