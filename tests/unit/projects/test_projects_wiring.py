"""Projects in the watchdog, the agent score and the `/project` command."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from dodaios.agent_chat.control import ChatControls
from dodaios.agent_chat.control_types import COMMANDS, ChatControlState
from dodaios.evals import agent_score
from dodaios.orchestrator.watchdog import checks
from dodaios.orchestrator.watchdog.checks import ProjectView, Snapshot
from dodaios.orchestrator.watchdog.live import LiveActions
from dodaios.projects.engine import ProjectEngine, set_engine
from dodaios.projects.models import DAY_MS, now_ms

from .test_projects import Clock, _create

NOW = 1_800_000_000_000


def _view(**kw: Any) -> ProjectView:
    base: dict[str, Any] = {
        "id": "prj_1",
        "title": "Prototype",
        "status": "active",
        "progress_ms": NOW - 4 * DAY_MS,
        "stall_days": 3,
        "open_subgoals": 2,
    }
    base.update(kw)
    return ProjectView(**base)


# ---------------------------------------------------------------- watchdog


def test_a_stalled_project_becomes_a_finding_with_resume_rescope_close() -> None:
    found = [
        f
        for f in checks.run_checks(Snapshot(NOW, projects=[_view()]))
        if f.kind == checks.KIND_PROJECT
    ]
    assert len(found) == 1
    finding = found[0]
    assert finding.evidence["idle_days"] == 4 and finding.evidence["project_id"] == "prj_1"
    assert finding.actions == (
        checks.ACT_RESUME_PROJECT,
        checks.ACT_RESCOPE_PROJECT,
        checks.ACT_CLOSE_PROJECT,
        checks.ACT_DISMISS,
    )


def test_recent_paused_or_closed_projects_are_not_findings() -> None:
    quiet = [
        _view(progress_ms=NOW - 2 * DAY_MS),  # inside its stall window
        _view(status="paused"),  # the owner's own choice
        _view(stall_days=7),  # a longer window of its own
    ]
    assert not [
        f for f in checks.run_checks(Snapshot(NOW, projects=quiet)) if f.kind == checks.KIND_PROJECT
    ]


async def test_the_watchdog_actions_resume_rescope_and_close(store) -> None:
    clock = Clock()
    engine = ProjectEngine(store, clock=clock)
    set_engine(engine)
    try:
        project = _create(engine)
        actions = LiveActions(None, None)
        clock.days(5)
        assert await actions.rescope_project(project.id)
        held = store.get(project.id)
        assert held.status == "blocked" and held.decision_kind == "rescope"
        assert await actions.resume_project(project.id)
        resumed = store.get(project.id)
        assert resumed.status == "active" and resumed.last_progress_ms == clock.now
        assert await actions.close_project(project.id)
        assert store.get(project.id).status == "abandoned"
        assert not await actions.resume_project(project.id)  # closed: no effect
        assert not await actions.resume_project("prj_unknown")
    finally:
        set_engine(None)


async def test_watchdog_sources_read_open_projects_from_the_store(store) -> None:
    from dodaios.orchestrator.watchdog.live import LiveSources
    from dodaios.projects.store import get_store

    engine = ProjectEngine(store, clock=Clock(NOW - 4 * DAY_MS))
    project = _create(engine)
    views = LiveSources._projects()
    assert get_store() is store
    assert [(v.id, v.open_subgoals) for v in views] == [(project.id, 3)]
    assert checks.run_checks(Snapshot(NOW, projects=views))[0].kind == checks.KIND_PROJECT


# ---------------------------------------------------------------- agent score


def test_the_agent_score_report_carries_the_long_horizon_component(tmp_path: Path, store) -> None:
    chat_db = tmp_path / "agent_chat.db"
    sqlite3.connect(chat_db).close()
    assert agent_score._project_component(tmp_path / "missing.db") is None

    path = tmp_path / "projects.db"
    from dodaios.projects.store import ProjectStore

    disk = ProjectStore(path)
    clock = Clock(now_ms() - 10 * DAY_MS)
    engine = ProjectEngine(disk, clock=clock)
    _create(engine)
    clock.days(1)
    engine_plan = engine.store.list()[0]
    engine_plan.days.append("2099-01-01")  # evidence on a second day: multi-session
    disk.save(engine_plan)
    disk.close()

    component = agent_score._project_component(path)
    assert component["multi_session_projects"] == 1 and component["stalled"] == 1
    table = agent_score.format_table(
        {
            "method": "m",
            "turns": 0,
            "lifetime": {
                "score": None,
                "rated_windows": 0,
                "not_rated_windows": 0,
                "trend_per_week": None,
                "efficiency": None,
                "forgetting": [],
            },
            "latest_window": None,
            "windows": [],
            "projects": component,
        }
    )
    assert "Long-horizon projects" in table and "completion rate" in table


# ---------------------------------------------------------------- /project command


def test_the_project_command_is_registered() -> None:
    assert any(c["name"] == "project" and c["kind"] == "control" for c in COMMANDS)


async def test_the_project_command_lists_and_confirms(store) -> None:
    engine = ProjectEngine(store, clock=Clock())
    set_engine(engine)
    try:
        project = _create(engine)
        controls = ChatControls.__new__(ChatControls)
        state = ChatControlState(session_id="lead-1")
        listed = await controls._project("lead-1", "", state)
        assert listed["projects"][0]["id"] == project.id
        confirmed = await controls._project("lead-1", f"confirm {project.id} c", state)
        assert [s["state"] for s in confirmed["project"]["subgoals"]] == ["pending"] * 2 + ["done"]
    finally:
        set_engine(None)
