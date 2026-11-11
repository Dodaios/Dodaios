"""`/api/agentic-ide/resources` — the resource view's poll and its one action.

The route's own job is the context: which process is which pane or thread, and
how each coding CLI of the catalog is recognised. The measuring is the
sampler's and is tested there.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.agent_chat import turn_host_client
from dodaios.agentic_ide import session as ide
from dodaios.ui.web import agentic_ide_resources_routes as routes


class _Sampler:
    def __init__(self) -> None:
        self.contexts: list[object] = []
        self.ended: list[list[str]] = []

    def sample(self, context):
        self.contexts.append(context)
        return {"agents": [], "system": {"cpu_percent": 1.0}}

    def end_tools(self, ids):
        self.ended.append(list(ids))
        return len(ids)


@pytest.fixture
def sampler() -> _Sampler:
    fake = _Sampler()
    routes.reset_for_tests(fake)  # type: ignore[arg-type]
    yield fake
    routes.reset_for_tests(None)


@pytest.fixture
def client(sampler: _Sampler, monkeypatch) -> TestClient:
    ide.reset_registry()
    monkeypatch.setattr(routes, "is_loopback_request", lambda _scope: True)
    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app) as test_client:
        yield test_client
    ide.reset_registry()


def test_the_catalog_names_the_clis_and_skips_names_too_common_to_trust() -> None:
    found = {signature.agent: signature for signature in routes.signatures()}

    assert found["claude"].binaries == ("claude",)
    assert found["claude"].display_name == "Claude Code"
    assert "codex" in found
    every = [binary for signature in found.values() for binary in signature.binaries]
    assert "agent" not in every  # a pane of that CLI is named by its process id instead
    assert len(every) == len(set(every))  # a launch profile over another CLI's binary adds none


def test_a_poll_hands_the_sampler_the_panes_it_can_name(client, sampler, monkeypatch) -> None:
    registry = ide.get_registry()
    monkeypatch.setattr(
        registry,
        "pane_processes",
        lambda: [
            {
                "pid": 4242,
                "history_id": "abc",
                "name": "T1",
                "agent": "claude",
                "display_name": "Claude Code",
                "title": "Fix the login test",
                "workspace_id": "ide_1",
                "workspace_name": "web",
            }
        ],
    )
    monkeypatch.setattr(registry, "runtime_status", lambda: {"host_pid": 77})
    turn = (5151, {"session_id": "s1", "runner": "codex", "cwd": "C:/work/api"})
    monkeypatch.setattr(turn_host_client, "live_processes", lambda: (88, [turn]))

    response = client.get("/api/agentic-ide/resources")

    assert response.status_code == 200
    assert response.json()["system"]["cpu_percent"] == 1.0
    (context,) = sampler.contexts
    pane, thread = context.known_roots
    assert (pane.pid, pane.id, pane.kind, pane.label, pane.detail, pane.workspace) == (
        4242,
        "pane:abc",
        "pane",
        "T1",
        "Fix the login test",
        "web",
    )
    assert (thread.pid, thread.id, thread.kind, thread.agent, thread.workspace) == (
        5151,
        "thread:s1",
        "thread",
        "codex",
        "api",
    )
    assert thread.agent_label == "Codex"
    assert list(context.host_pids) == [77, 88]
    assert any(signature.agent == "claude" for signature in context.signatures)


def test_a_source_that_fails_does_not_empty_the_view(client, sampler, monkeypatch) -> None:
    def broken():
        raise RuntimeError("registry is mid-restore")

    monkeypatch.setattr(ide.get_registry(), "pane_processes", broken)

    assert client.get("/api/agentic-ide/resources").status_code == 200
    (context,) = sampler.contexts
    assert list(context.known_roots) == []
    assert context.signatures  # agents are still recognised by name


def test_ending_tools_passes_the_handles_on(client, sampler) -> None:
    response = client.post("/api/agentic-ide/resources/end", json={"ids": ["12:99", "13:99"]})

    assert response.status_code == 200
    assert response.json() == {"ended": 2}
    assert sampler.ended == [["12:99", "13:99"]]
    assert client.post("/api/agentic-ide/resources/end", json={"ids": []}).status_code == 422


def test_ending_tools_is_refused_from_another_computer(sampler, monkeypatch) -> None:
    monkeypatch.setattr(routes, "is_loopback_request", lambda _scope: False)
    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app) as remote:
        response = remote.post("/api/agentic-ide/resources/end", json={"ids": ["12:99"]})

    assert response.status_code == 403
    assert sampler.ended == []


def test_a_registry_lists_only_panes_with_a_process_on_this_computer(tmp_path) -> None:
    ide.reset_registry()
    registry = ide.get_registry()
    try:
        assert registry.pane_processes() == []
    finally:
        ide.reset_registry()
