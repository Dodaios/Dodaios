"""An app restart that loads new code waits for the chat turns it would end."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from dodaios.agent_chat import service as service_mod
from dodaios.agent_chat import turn_host_client
from dodaios.agent_chat.service import AgentChatService
from dodaios.agent_chat.store import AgentChatStore


@pytest.fixture
def chat(tmp_path):
    service = AgentChatService(AgentChatStore(":memory:"))
    yield service
    service.store.close()


def _working(service: AgentChatService, surface: str, tmp_path) -> str:
    """A session on ``surface`` whose turn is running."""
    session = service.store.create_session(
        provider="claude-api", model="m", effort="", cwd=str(tmp_path), surface=surface
    )
    run = service_mod._Running("turn", asyncio.Event())
    run.setup_task = None
    service._running[session.session_id] = run
    return session.session_id


async def test_a_thread_turn_in_the_turn_host_survives_a_restart(chat, tmp_path, monkeypatch):
    monkeypatch.setattr(turn_host_client, "host_available", lambda: True)
    _working(chat, "agent", tmp_path)
    assert chat.turns_a_restart_would_end() == []


async def test_the_front_page_chat_and_a_created_agent_lose_their_turn(
    chat, tmp_path, monkeypatch
):
    monkeypatch.setattr(turn_host_client, "host_available", lambda: True)
    _working(chat, "agent", tmp_path)
    lead = _working(chat, "jarvis", tmp_path)
    member = _working(chat, "society", tmp_path)
    assert chat.turns_a_restart_would_end() == [lead, member]


async def test_without_a_turn_host_a_thread_turn_runs_in_this_process(
    chat, tmp_path, monkeypatch
):
    monkeypatch.setattr(turn_host_client, "host_available", lambda: False)
    thread = _working(chat, "agent", tmp_path)
    assert chat.turns_a_restart_would_end() == [thread]


async def test_a_finished_turn_holds_nothing_back(chat, tmp_path, monkeypatch):
    monkeypatch.setattr(turn_host_client, "host_available", lambda: True)
    lead = _working(chat, "jarvis", tmp_path)
    chat._running.pop(lead)
    assert chat.turns_a_restart_would_end() == []


def _follower_idle(monkeypatch, state) -> bool:
    """What the server tells the follower of main: may the app restart now?"""
    from dodaios.core import main_follow
    from dodaios.ui.web.server import WebServer

    seen: dict = {}
    monkeypatch.setattr(main_follow, "start_follower", lambda **kwargs: seen.update(kwargs))
    server = WebServer.__new__(WebServer)
    server.app = SimpleNamespace(state=state)
    server.cfg = SimpleNamespace(agentic_ide=SimpleNamespace(follow_main=True))
    server._start_main_follower()
    return bool(seen["idle"]())


def test_following_main_restarts_only_when_no_chat_turn_would_be_lost(monkeypatch):
    busy = SimpleNamespace(turns_a_restart_would_end=lambda: ["lead"])
    quiet = SimpleNamespace(turns_a_restart_would_end=lambda: [])

    assert not _follower_idle(monkeypatch, SimpleNamespace(agent_chat=busy))
    assert _follower_idle(monkeypatch, SimpleNamespace(agent_chat=quiet))
    # No window ever opened a chat: the service was never built and runs nothing.
    assert _follower_idle(monkeypatch, SimpleNamespace(agent_chat=None))
