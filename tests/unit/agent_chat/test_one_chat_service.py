"""Every builder of the agent-chat service shares one build: one service per app.

Live 2026-11-14 the app built two services right after a restart: the boot
reattach went through the routes' locked builder, while the agents' MCP tools
and the code builder built their own without the lock. Both carried on the
thread turns the turn host kept running; the host handed each turn to the later
one, and the service the window talked to forgot the agent was still working.
A message typed then no longer waited in the queue: it started a second turn
at once, beside the one that kept running.
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from typing import Any

import pytest

import dodaios.agent_chat.service as service_module
from dodaios.agent_chat.app_service import service_from_state
from dodaios.core import runtime_refs
from dodaios.mcp.agents import context as mcp_context
from dodaios.self_build.code.loop import _chat_from
from dodaios.ui.web.agent_chat_routes import _service_from_state


@pytest.fixture
def slow_state(monkeypatch: pytest.MonkeyPatch) -> tuple[SimpleNamespace, list[Any]]:
    # No app loop in this test: the builder must not wait for one.
    monkeypatch.setattr(service_module, "remember_app_loop", lambda loop=None: None)
    built: list[Any] = []

    def factory() -> object:
        # Slow like the real build (SQLite, restart recovery), so the
        # builders overlap.
        time.sleep(0.15)
        service = object()
        built.append(service)
        return service

    state = SimpleNamespace(agent_chat=None, agent_chat_factory=factory)
    monkeypatch.setattr(runtime_refs, "get_web_app", lambda: SimpleNamespace(state=state))
    return state, built


def test_the_routes_mcp_tools_and_code_builder_build_one_service_together(
    slow_state: tuple[SimpleNamespace, list[Any]],
) -> None:
    state, built = slow_state
    got: list[Any] = []
    lock = threading.Lock()
    builders = [
        lambda: _service_from_state(state),
        mcp_context.chat_service,
        _chat_from(state),
    ] * 2

    def run(build: Any) -> None:
        service = build()
        with lock:
            got.append(service)

    threads = [threading.Thread(target=run, args=(build,)) for build in builders]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert len(built) == 1, "a second service would take the running turns away"
    assert len(got) == len(builders)
    assert all(service is built[0] for service in got)
    assert state.agent_chat is built[0]


def test_a_failed_build_is_a_typed_refusal_for_the_agents_tools(monkeypatch) -> None:
    monkeypatch.setattr(service_module, "remember_app_loop", lambda loop=None: None)

    def broken() -> object:
        raise OSError("disk full")

    state = SimpleNamespace(agent_chat=None, agent_chat_factory=broken)
    monkeypatch.setattr(runtime_refs, "get_web_app", lambda: SimpleNamespace(state=state))

    assert service_from_state(state) is None
    with pytest.raises(mcp_context.EcosystemUnavailable):
        mcp_context.chat_service()
    with pytest.raises(RuntimeError):
        _chat_from(state)()
    assert state.agent_chat is None


def test_an_app_without_a_chat_service_says_so(monkeypatch) -> None:
    state = SimpleNamespace(agent_chat=None, agent_chat_factory=None)
    monkeypatch.setattr(runtime_refs, "get_web_app", lambda: SimpleNamespace(state=state))

    with pytest.raises(mcp_context.EcosystemUnavailable, match="no chat service"):
        mcp_context.chat_service()
