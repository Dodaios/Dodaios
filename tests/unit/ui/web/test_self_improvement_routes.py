"""HTTP API of the Self-improvement page: what it shows, the stop, and undo."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.rsi import night as nights
from dodaios.rsi import params
from dodaios.ui.web.self_improvement_routes import router
from tests.unit.rsi import fakeworld
from tests.unit.rsi.fakeworld import BLIND, LIMIT, SCORE


@pytest.fixture
def box(tmp_path: Path, monkeypatch):
    """A sandbox two nights in: one change let in and confirmed, a second on trial."""
    built = fakeworld.sandbox(tmp_path, monkeypatch, plant={SCORE: BLIND})
    built.night.run()
    built.night.run()
    yield built
    built.close()


@pytest.fixture
def http(box) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.state.self_improvement = nights.NightService(box.night, lambda: True)
    return TestClient(app)


def test_the_page_gets_what_was_measured_what_is_in_effect_and_what_the_nights_did(http) -> None:
    splits = fakeworld.splits()
    body = http.get("/api/self-improvement").json()
    assert set(body) == {
        "status",
        "limits",
        "domains",
        "series",
        "stack",
        "candidates",
        "nights",
        "resting",
        "now_ms",
    }
    status = body["status"]
    assert status["paused"] is False and status["last_night_ms"] > 0
    assert status["next_night_ms"] == status["last_night_ms"] + 20 * 3600 * 1000
    assert status["decides_on"] == ["made"] and status["own_tasks"] is True
    assert body["limits"] == {
        "idle_after_s": 900.0,
        "every_s": 72000.0,
        "budget_share": 0.2,
        "max_model_calls": 8,
    }

    (domain,) = body["domains"]
    assert domain["domain"] == "recall" and domain["measured"] is True
    assert domain["tasks"] == splits and domain["tasks_total"] == fakeworld.TASKS
    point = domain["point"]
    assert point["n"] == splits["sealed"] and point["diff"] == 0.0
    assert (point["now_tokens"], point["factory_tokens"]) == (50, 150)
    assert [p["split"] for p in body["series"]] == ["sealed", "sealed"]

    newest, first = body["stack"]  # newest first
    assert (first["target"], first["before"], first["after"]) == (SCORE, BLIND, 8.0)
    assert first["state"] == "live" and first["default"] == 0.0 and first["doc"]
    assert first["author"] == "tuner" and "practice tasks" in first["reason"]
    admitted = first["admitted"]
    assert admitted["verdict"] == "accept" and admitted["split"] == "select"
    assert admitted["n"] == splits["select"] and admitted["low"] > 0.3
    assert admitted["reason"].startswith("better on")
    assert first["last_check"]["split"] == "guard" and first["last_check"]["n"] == splits["guard"]
    assert (newest["target"], newest["before"], newest["after"]) == (LIMIT, None, 2)
    assert newest["state"] == "trial" and newest["last_check"] is None
    assert newest["admitted"]["cost_diff"] == -100.0

    last, before = body["nights"]  # newest first
    assert last["settled"][0]["outcome"] == "kept" and last["decided"][0]["target"] == LIMIT
    assert before["decided"][0]["outcome"] == "admitted" and before["proposed"][0]["value"] == 8.0
    # The planted value did not come through the registry: it is no learned change.
    assert body["resting"] == [] and body["candidates"] == []


def test_the_person_can_stop_the_loop_and_take_a_change_back(http, box) -> None:
    assert http.post("/api/self-improvement/pause", json={"paused": True}).json()["paused"]
    assert http.get("/api/self-improvement").json()["status"]["paused"] is True
    assert box.night.run().paused
    assert http.post("/api/self-improvement/pause", json={"paused": False}).status_code == 200

    newest, first = http.get("/api/self-improvement").json()["stack"]
    undone = http.post(f"/api/self-improvement/changes/{newest['id']}/undo")
    assert undone.status_code == 200 and undone.json()["reverted"] == [newest["id"]]
    assert params.get(LIMIT) == 6 and params.get(SCORE) == 8.0  # only that one
    assert [row["id"] for row in http.get("/api/self-improvement").json()["stack"]] == [
        first["id"]
    ]
    again = http.post(f"/api/self-improvement/changes/{newest['id']}/undo")
    assert again.status_code == 409  # nothing in effect to take back
    assert http.post("/api/self-improvement/changes/nope/undo").status_code == 409
    http.post(f"/api/self-improvement/changes/{first['id']}/undo")
    assert params.get(SCORE) == BLIND  # the exact value from before the first learned change


def test_without_the_service_the_page_is_told_so() -> None:
    app = FastAPI()
    app.include_router(router)
    assert TestClient(app).get("/api/self-improvement").status_code == 503


def test_there_is_no_route_that_lets_a_change_in_or_writes_a_result() -> None:
    paths = {(tuple(sorted(route.methods)), route.path) for route in router.routes}
    assert paths == {
        (("GET",), "/api/self-improvement"),
        (("POST",), "/api/self-improvement/pause"),
        (("POST",), "/api/self-improvement/changes/{change_id}/undo"),
    }
    source = Path(__file__).resolve().parents[4] / "dodaios/ui/web/self_improvement_routes.py"
    text = source.read_text(encoding="utf-8")
    for verb in ("admit(", "decline(", "settle(", "propose(", "add_results", "record_evidence"):
        assert verb not in text
