"""Enter pressed in a pane's own window tells the self-building loop.

The prompt a Claude pane reports next is then the person's (docs/self-build.md,
"Prompts typed into a pane"). Typing without Enter, and a newline inside a
bracketed paste, press nothing.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.agentic_ide import session as session_mod
from dodaios.agentic_ide.session import Registry
from tests.fakes.fake_pty_manager import FakePtyManager


@pytest.fixture
def registry(monkeypatch: pytest.MonkeyPatch) -> Registry:
    monkeypatch.setattr(session_mod, "agent_argv", lambda name: (f"/usr/bin/{name}",))
    reg = Registry(pty_manager=FakePtyManager())
    monkeypatch.setattr(session_mod, "get_registry", lambda: reg)
    from dodaios.ui.web import agentic_ide_routes

    monkeypatch.setattr(agentic_ide_routes, "get_registry", lambda: reg)
    monkeypatch.setattr(agentic_ide_routes, "credentials_valid", lambda _scope: True)
    return reg


@pytest.fixture
def presses(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    from dodaios.self_build import app

    seen: list[str] = []
    monkeypatch.setattr(app, "pane_keyboard_submit", seen.append)
    return seen


@pytest.fixture
def client(registry: Registry) -> Iterator[TestClient]:
    from dodaios.ui.web.agentic_ide_routes import router

    api = FastAPI()
    api.include_router(router)
    with TestClient(api) as ready:
        yield ready


def _wait(predicate: object, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():  # type: ignore[operator]
            return True
        time.sleep(0.02)
    return False


def test_enter_in_the_pane_window_is_reported_and_typing_is_not(
    client: TestClient, registry: Registry, presses: list[str], tmp_path: Path
) -> None:
    session = client.portal.call(registry.start, str(tmp_path), [{"agent": "claude"}])
    term = session.terminals[0]
    with client.websocket_connect(f"/api/agentic-ide/pty/T1?workspace={session.id}") as socket:
        socket.send_json({"t": "i", "d": "count the lines"})
        socket.send_json({"t": "i", "d": "\x1b[200~line one\nline two\x1b[201~"})
        socket.send_json({"t": "i", "d": "\r"})
        assert _wait(lambda: presses == [term.history_id]), presses
