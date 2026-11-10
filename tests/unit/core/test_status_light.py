"""The status light folds the board, jobs, attention and seat health into counts."""

from __future__ import annotations

import time
from types import SimpleNamespace

from dodaios.brain.seat_health import CLASS_AUTH, SeatHealth, SeatVerdict
from dodaios.core.status_light import MAX_ROWS, build_status_light

BOARD = {
    "needs_you": [],
    "coding_agents": {
        "workspaces": [
            {
                "workspace": "api",
                "agents": [
                    {"terminal_id": "t1", "name": "Agent 1", "state": "busy"},
                    {"terminal_id": "t2", "name": "Agent 2", "state": "needs_input"},
                ],
            }
        ]
    },
    "team": {"working": [{"agent_id": "a1", "name": "Researcher"}], "idle": 2},
    "missions": [
        {"mission_id": "m1", "state": "RUNNING", "request": "Write the report"},
        {"mission_id": "m2", "state": "WAITING_CAPACITY", "request": "Big job"},
    ],
    "tasks": [{"task_id": "k1", "title": "Nightly sync", "state": "running"}],
}


def _job(job_id: str, ref: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        id=job_id, kind="mission", title=f"job {job_id}", state="running", ref=ref
    )


def test_counts_and_links() -> None:
    card = {"kind": "question", "agent_id": "jarvis", "session_id": "s", "ref_id": "q1",
            "summary": "Which database?", "since_ms": 5}
    light = build_status_light(board=BOARD, attention=[card], jobs=[_job("j1")])
    kinds = [row["kind"] for row in light["running"]]
    assert kinds == ["pane", "team", "mission", "task", "job"]
    assert light["counts"] == {"running": 5, "needs_you": 3}
    first = light["needs_you"][0]
    assert first["link"] == {"agent_id": "jarvis", "session_id": "s", "ref_id": "q1"}
    assert {row["kind"] for row in light["needs_you"]} == {"question", "pane", "mission"}
    assert light["tone"] == "calm"


def test_job_of_a_board_mission_is_not_listed_twice() -> None:
    light = build_status_light(board=BOARD, jobs=[_job("j1", ref="m1"), _job("j2")])
    assert [row["id"] for row in light["running"] if row["kind"] == "job"] == ["j2"]


def test_trouble_sets_a_warning_tone() -> None:
    seat = SeatVerdict("openai", "work", CLASS_AUTH, time.time() + 3600, True)
    light = build_status_light(seats=[seat])
    assert light["tone"] == "warn"
    assert light["trouble"][0]["provider"] == "openai"
    assert light["trouble"][0]["blocked"] is True


def test_empty_sources_are_quiet_and_rows_are_bounded() -> None:
    assert build_status_light()["counts"] == {"running": 0, "needs_you": 0}
    many = build_status_light(jobs=[_job(str(n)) for n in range(MAX_ROWS + 10)])
    assert many["counts"]["running"] == MAX_ROWS + 10
    assert len(many["running"]) == MAX_ROWS


def test_seat_health_lists_only_live_verdicts() -> None:
    now = [1000.0]
    health = SeatHealth(clock=lambda: now[0])
    health.record_failure("openai", "work", "401 invalid api key")
    health.record_failure("grok", "", "boom")
    troubled = health.troubled()
    assert [seat.provider for seat in troubled] == ["openai"]
    now[0] += 10 * 24 * 3600
    assert health.troubled() == []
