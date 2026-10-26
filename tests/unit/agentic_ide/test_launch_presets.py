"""Saved workspace lineups: what is saved is what a fresh process reads back."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.agentic_ide import launch_presets


@pytest.fixture
def client() -> TestClient:
    from dodaios.ui.web.agentic_ide_routes import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


MIXED = {
    "name": "Mixed squad",
    "agents": [
        {"agent": "claude", "count": 2},
        {"agent": "codex", "count": 1},
        {"agent": "kimi", "count": 1},
    ],
}


def test_a_first_run_has_no_presets_and_says_so() -> None:
    assert launch_presets.list_presets() == []
    assert launch_presets.stored() is False


def test_saved_presets_are_on_disk(_ui_prefs_in_tmp: Path) -> None:
    saved = launch_presets.save_presets([MIXED])

    on_disk = json.loads(
        _ui_prefs_in_tmp.with_name("launch_presets.json").read_text(encoding="utf-8")
    )
    assert on_disk["presets"] == saved
    assert saved[0]["agents"] == MIXED["agents"]
    assert saved[0]["id"]
    assert launch_presets.stored() is True


def test_an_emptied_list_still_counts_as_stored() -> None:
    """Deleting every preset must not bring the starter presets back."""
    launch_presets.save_presets([MIXED])
    launch_presets.save_presets([])

    assert launch_presets.list_presets() == []
    assert launch_presets.stored() is True


def test_cleaning_merges_repeats_and_drops_junk() -> None:
    cleaned = launch_presets.clean_presets(
        [
            {
                "name": "  Duo ",
                "agents": [
                    {"agent": "codex", "count": 1},
                    {"agent": "codex", "count": 1},
                    {"agent": "bad name!", "count": 3},
                ],
            },
            {"name": "duo", "agents": [{"agent": "claude", "count": 1}]},
            {"name": "", "agents": [{"agent": "claude", "count": 1}]},
            {"name": "Empty", "agents": []},
            "not a preset",
        ]
    )

    assert [preset["name"] for preset in cleaned] == ["Duo"]
    assert cleaned[0]["agents"] == [{"agent": "codex", "count": 2}]


def test_a_broken_file_reads_as_no_presets(_ui_prefs_in_tmp: Path) -> None:
    _ui_prefs_in_tmp.with_name("launch_presets.json").write_text("{not json", encoding="utf-8")

    assert launch_presets.list_presets() == []


def test_routes_round_trip(client: TestClient) -> None:
    assert client.get("/api/agentic-ide/launch-presets").json() == {
        "ok": True,
        "presets": [],
        "stored": False,
    }

    res = client.put("/api/agentic-ide/launch-presets", json={"presets": [MIXED]})
    assert res.status_code == 200

    body = client.get("/api/agentic-ide/launch-presets").json()
    assert body["stored"] is True
    assert body["presets"][0]["name"] == "Mixed squad"
    assert body["presets"][0]["agents"] == MIXED["agents"]


def test_route_rejects_a_preset_without_agents(client: TestClient) -> None:
    res = client.put(
        "/api/agentic-ide/launch-presets", json={"presets": [{"name": "x", "agents": []}]}
    )
    assert res.status_code == 422
