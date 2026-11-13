"""``GET /api/status-light`` folds the sources and never fails the app."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.ui.web import status_light_routes as routes


def _client(monkeypatch, *, board, cards) -> TestClient:
    async def fake_board():
        return board

    async def fake_cards(_request):
        return cards

    monkeypatch.setattr(routes, "_board", fake_board)
    monkeypatch.setattr(routes, "_attention_cards", fake_cards)
    monkeypatch.setattr(routes, "_cache", None)
    app = FastAPI()
    app.include_router(routes.router)
    return TestClient(app)


def test_route_returns_the_summary(monkeypatch) -> None:
    board = {"missions": [{"mission_id": "m1", "state": "RUNNING", "request": "Report"}]}
    cards = [{"kind": "approval", "agent_id": "a", "session_id": "s", "ref_id": "r",
              "summary": "Run a command", "since_ms": 1}]
    body = _client(monkeypatch, board=board, cards=cards).get("/api/status-light").json()
    assert body["counts"]["running"] >= 1
    assert body["counts"]["needs_you"] == 1
    assert body["needs_you"][0]["link"]["agent_id"] == "a"
    assert body["tone"] in {"calm", "warn"}


def test_route_answers_without_any_source(monkeypatch) -> None:
    body = _client(monkeypatch, board={}, cards=[]).get("/api/status-light").json()
    assert body["counts"] == {"running": 0, "needs_you": 0, "prepared": 0}


def test_two_reads_within_the_window_share_one_fold(monkeypatch) -> None:
    calls = []

    async def counting_board():
        calls.append(1)
        return {}

    client = _client(monkeypatch, board={}, cards=[])
    monkeypatch.setattr(routes, "_board", counting_board)
    client.get("/api/status-light")
    client.get("/api/status-light")
    assert len(calls) == 1


def test_a_row_names_who_it_is_about(monkeypatch) -> None:
    board = {"coding_agents": {"workspaces": [{
        "workspace": "Library", "workspace_id": "w1",
        "agents": [{"terminal_id": "t2", "name": "T2", "cli": "claude", "state": "needs_input"}],
    }]}}
    cards = [{"kind": "question", "agent_id": "a1", "agent_name": "Researcher",
              "session_id": "s", "ref_id": "q1", "summary": "Which database?", "since_ms": 1}]
    body = _client(monkeypatch, board=board, cards=cards).get("/api/status-light").json()
    card, pane = body["needs_you"]
    assert card["agent_name"] == "Researcher"
    # The CLI's product name stands beside its id, so the app need not know the products.
    assert pane["agent"] == "claude"
    assert pane["agent_label"] == "Claude Code"
    assert pane["link"] == {"section": "agentic-ide", "workspace_id": "w1", "pane": "T2"}


def test_an_unknown_coding_cli_keeps_its_id_as_its_name(monkeypatch) -> None:
    board = {"coding_agents": {"workspaces": [{
        "workspace": "api",
        "agents": [
            {"terminal_id": "t9", "name": "T9", "cli": "no-such-cli", "state": "needs_input"},
        ],
    }]}}
    body = _client(monkeypatch, board=board, cards=[]).get("/api/status-light").json()
    assert body["needs_you"][0]["agent_label"] == "no-such-cli"
