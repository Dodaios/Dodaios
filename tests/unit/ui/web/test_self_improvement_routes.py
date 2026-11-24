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
        "daily_use",
        "now_ms",
    }
    assert body["daily_use"] is None  # this sandbox has no chat record
    status = body["status"]
    assert status["paused"] is False and status["last_night_ms"] > 0
    assert status["next_night_ms"] == status["last_night_ms"] + 20 * 3600 * 1000
    assert status["decides_on"] == ["made"] and status["own_tasks"] is True
    assert body["limits"] == {
        "idle_after_s": 900.0,
        "every_s": 72000.0,
        "budget_share": 0.2,
        "max_model_calls": 8,
        "ramp_model_calls": 24,
        "model_calls_tonight": 8,  # the sandbox's own tasks are enough to decide on
        "first_move_calls": 40,
    }

    domain, lead = body["domains"]
    # The lead's first move is a measured area too; without recorded lead turns it waits.
    assert lead["domain"] == "first_move" and lead["tasks_total"] == 0 and not lead["measured"]
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
    assert [row["id"] for row in http.get("/api/self-improvement").json()["stack"]] == [first["id"]]
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


def test_the_page_lists_a_coding_policy_change_with_the_measurement_that_let_it_in(
    tmp_path: Path, monkeypatch
) -> None:
    import time

    from dodaios.orchestrator.verification.store import VerificationStore
    from dodaios.rsi import trainer
    from dodaios.rsi.policy import ACTIVE, DEFAULT, Policy, PolicyStore
    from dodaios.self_change import Surface
    from tests.unit.rsi import test_replay_and_trainer as loop

    built = fakeworld.sandbox(tmp_path, monkeypatch)
    runs = VerificationStore(tmp_path / "verification.db")
    policies = PolicyStore(tmp_path / "rsi.db")
    built.registry.register_handler(Surface.CODING_POLICY, policies)
    learner = trainer.Trainer(runs, policies, lambda: built.registry, samples=300)
    app = FastAPI()
    app.include_router(router)
    app.state.self_improvement = nights.NightService(built.night, lambda: True)
    http = TestClient(app)
    hold = Policy(hold=True)
    try:
        loop._factory_cell(runs, passing=50, withheld=15)
        assert learner.consider(loop.CELL) == f"candidate {hold.id} on trial"

        body = http.get("/api/self-improvement").json()
        assert body["stack"] == []  # on trial for half the requests: not learned yet
        (trial,) = body["candidates"]
        assert (trial["surface"], trial["state"]) == ("coding_policy", "trial")
        assert trial["policy"]["slot"] == "candidate" and trial["policy"]["kinds"] == ["hold"]
        assert trial["policy"]["claim"] == {"branch": "A", "target": "pass"}
        assert trial["admitted"] is None

        later = int(time.time() * 1000) + 10_000
        for i in range(65):
            loop.record(
                runs,
                policy=hold,
                outputs=[{}],
                started_ms=later,
                verdict="verified" if i < 60 else "failed",
            )
            if i < 42:
                loop.record(runs, outputs=[{}], started_ms=later)
            else:
                loop._withheld(runs, started_ms=later)
        assert learner.consider(loop.CELL) == "trial ended: accept"

        body = http.get("/api/self-improvement").json()
        assert body["candidates"] == []  # the trial ended; its removal is no policy
        (row,) = body["stack"]  # the earlier candidate and its removal are left out
        assert (row["surface"], row["target"]) == ("coding_policy", f"{loop.CELL}#active")
        assert (row["state"], row["author"]) == ("trial", "rsi-selector")
        policy = row["policy"]
        assert policy["kinds"] == ["hold"] and policy["slot"] == "active"
        assert (policy["domain"], policy["model"], policy["harness"]) == (
            "backend",
            "claude-opus-5-5",
            "claude-cli 2.1",
        )
        assert row["before"] == {"hold": False, "p_max": 2, "evidence_wait_s": 2700, "lines": []}
        assert row["after"]["hold"] is True and row["measured"] is True
        admitted = row["admitted"]
        assert (admitted["step"], admitted["verdict"], admitted["metric"]) == (
            "admit",
            "accept",
            "pass",
        )
        assert (admitted["n"], admitted["n_reference"]) == (65, 65)
        assert admitted["diff"] == pytest.approx(18 / 65) and admitted["low"] > 0
        assert admitted["high"] is None  # the selector bounds from below only
        assert admitted["arms"]["candidate"]["pass"] == pytest.approx(60 / 65)
        assert admitted["arms"]["reference"]["pass"] == pytest.approx(42 / 65)
        assert admitted["reason"].startswith("branch A")

        # Take back: the cell runs under the factory policy again, nothing held.
        undone = http.post(f"/api/self-improvement/changes/{row['id']}/undo")
        assert undone.status_code == 200 and undone.json()["reverted"] == [row["id"]]
        assert policies.policy(loop.CELL, ACTIVE) is None
        assert http.get("/api/self-improvement").json()["stack"] == []
        assert DEFAULT.hold is False
    finally:
        runs.close()
        policies.close()
        built.close()
