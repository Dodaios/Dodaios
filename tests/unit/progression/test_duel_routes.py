"""Duel reads over REST, and the refusal of duel XP as a world action (WP21.4, A21.5)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.progression.rules import DUEL_SOURCES, RULES_BY_SOURCE, WORLD_ACTIONS
from dodaios.progression.service import ProgressionService
from dodaios.ui.web.progression_routes import router

from .test_duel_service import duel


@pytest.fixture
def setup(tmp_path: Path):
    app = FastAPI()
    app.include_router(router)
    service = ProgressionService(tmp_path / "progression.db", pet_id=lambda: "miso")
    app.state.progression = service
    with TestClient(app) as client:
        yield client, service
    service.close()


def test_the_first_read_carries_duel_totals(setup):
    client, service = setup
    body = client.get("/api/progression").json()
    assert body["duel_stats"]["matches"] == 0
    client.portal.call(service.record_duel, duel("m1"))
    body = client.get("/api/progression").json()
    stats = body["duel_stats"]
    assert (stats["matches"], stats["wins"], stats["kills"], stats["deaths"]) == (1, 1, 10, 7)
    assert stats["by_tier"]["hard"]["wins"] == 1
    assert {r["source"] for r in body["rules"]} >= set(DUEL_SOURCES)
    assert next(r for r in body["rules"] if r["source"] == "duel_won")["trigger"] == "server"


def test_the_duels_read_lists_recent_sets_newest_first(setup):
    client, service = setup
    for i in range(25):
        client.portal.call(service.record_duel, duel(f"m{i:02d}", set_index=i + 1))
    body = client.get("/api/progression/duels").json()
    assert len(body["duels"]) == 20
    assert body["duel_stats"]["matches"] == 25
    assert body["duels"][0]["set_index"] == 25
    assert len(client.get("/api/progression/duels?limit=3").json()["duels"]) == 3
    assert client.get("/api/progression/duels?limit=0").status_code == 422
    assert client.get("/api/progression/duels?limit=101").status_code == 422


@pytest.mark.parametrize("source", DUEL_SOURCES)
def test_duel_xp_is_never_a_world_action(setup, source):
    client, service = setup
    assert RULES_BY_SOURCE[source].trigger == "server"
    assert source not in WORLD_ACTIONS
    res = client.post("/api/progression/actions", json={"action": source, "ref": "m1"})
    assert res.status_code == 422
    assert service.store.latest_seq() == 0
