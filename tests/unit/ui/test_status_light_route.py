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
