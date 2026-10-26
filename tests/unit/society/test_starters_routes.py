"""Starters install through the normal create path on every runtime and seat.

Headless: no keys, no network. The external runtimes' setup is faked, so a
Hermes or OpenClaw agent is created exactly as the dialog would create it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dodaios.agent_chat.service import resolve_runner
from dodaios.society.runtime import SocietyRuntime
from dodaios.society.starters import load_starters
from dodaios.tasks.store import TaskStore
from dodaios.ui.web.society_routes import router


@pytest.fixture
def ensured(monkeypatch) -> list[str]:
    from dodaios.agent_runtimes import manager

    calls: list[str] = []

    async def _ensure(runtime: str, *args, **kwargs):
        calls.append(runtime)

    monkeypatch.setattr(manager, "ensure", _ensure)
    return calls


def _client(tmp_path: Path, task_store: TaskStore | None = None):
    runtime = SocietyRuntime(tmp_path, seed_starter_team=False)
    app = FastAPI()
    app.include_router(router)
    app.state.society_factory = lambda: runtime
    if task_store is not None:
        app.state.task_store = task_store
        app.state.task_scheduler = None
    return TestClient(app), runtime


#: (seat, expected runner) — brain/API seat, the Claude and Codex CLIs, and
#: the two ACP runtimes.
SEATS = [
    ({"provider": "openai", "model": "gpt-5.2"}, None),
    ({"provider": "claude-api", "account_id": "subscription"}, None),
    ({"provider": "openai-codex"}, None),
    ({"provider": "openai", "runtime": "hermes"}, "hermes-cli"),
    ({"provider": "openai", "runtime": "openclaw"}, "openclaw-cli"),
]


def test_gallery_lists_every_starter(tmp_path: Path):
    client, runtime = _client(tmp_path)
    with client:
        try:
            body = client.get("/api/society/starters").json()
        finally:
            client.portal.call(runtime.close)
    assert body["total"] == len(load_starters())
    assert body["areas"][0] == "coding"
    first = body["starters"][0]
    assert {"id", "area", "icon", "name", "outcome", "tools", "summary", "first_message"} <= set(
        first
    )


@pytest.mark.parametrize("seat,runner", SEATS, ids=lambda v: str(v))
def test_every_starter_creates_an_agent_on_every_runtime(
    tmp_path: Path, ensured: list[str], seat: dict, runner: str | None
):
    client, runtime = _client(tmp_path)
    with client:
        try:
            for starter in load_starters():
                res = client.post(
                    "/api/society/starters/install",
                    json={"starter_id": starter.id, "seat": seat},
                )
                assert res.status_code == 200, (starter.id, res.text)
                body = res.json()
                agent = body["agent"]
                assert agent["provider"] == seat["provider"]
                assert agent["runtime"] == seat.get("runtime", "jarvis")
                assert agent["approval_mode"] == "bypass"
                assert agent["approval_rules"]["always_allow"] == []
                assert agent["approval_rules"]["require_approval"] == list(
                    starter.template.get("require_approval", [])
                )
                assert body["first_message"] == starter.first_message
                assert body["routine"] is None
                resolved = resolve_runner(
                    agent["provider"],
                    surface="society",
                    runtime="" if agent["runtime"] == "jarvis" else agent["runtime"],
                    account_id=agent.get("account_id", ""),
                )
                assert resolved != "unknown"
                if runner:
                    assert resolved == runner
        finally:
            client.portal.call(runtime.close)
    if seat.get("runtime"):
        assert set(ensured) == {seat["runtime"]}


def test_install_applies_name_tools_and_companion(tmp_path: Path, ensured: list[str]):
    client, runtime = _client(tmp_path)
    companion = {"shape": "drop", "color": "#c9a227"}
    with client:
        try:
            res = client.post(
                "/api/society/starters/install",
                json={
                    "starter_id": "meeting-prep",
                    "name": "Morning Desk",
                    "tools": ["plugin:google_calendar", "core:run-shell"],
                    "seat": {"provider": "openai", "companion": companion},
                },
            )
            assert res.status_code == 200, res.text
            agent = res.json()["agent"]
            assert agent["name"] == "Morning Desk"
            assert agent["focus"] == ["plugin:google_calendar"]
            assert agent["avatar"]["companion"]["shape"] == "drop"
            # Same starter again: a free name, never the first agent adopted.
            again = client.post(
                "/api/society/starters/install",
                json={"starter_id": "meeting-prep", "name": "Morning Desk"},
            ).json()
            assert again["agent"]["name"] == "Morning Desk 2"
            assert again["renamed_from"] == "Morning Desk"
        finally:
            client.portal.call(runtime.close)


def test_install_refuses_bad_requests(tmp_path: Path):
    client, runtime = _client(tmp_path)
    with client:
        try:
            both = client.post(
                "/api/society/starters/install",
                json={"starter_id": "editor", "template": {"schema": 1}},
            )
            assert both.status_code == 422
            neither = client.post("/api/society/starters/install", json={})
            assert neither.status_code == 422
            unknown = client.post("/api/society/starters/install", json={"starter_id": "nope"})
            assert unknown.status_code == 404
            reserved = client.post(
                "/api/society/starters/install", json={"starter_id": "editor", "name": "Jarvis"}
            )
            assert reserved.status_code == 422
            extra = client.post(
                "/api/society/starters/install",
                json={"starter_id": "editor", "seat": {"approval_mode": "bypass"}},
            )
            assert extra.status_code == 422
        finally:
            client.portal.call(runtime.close)


def test_imported_template_previews_then_installs_on_the_dialog_seat(tmp_path: Path):
    client, runtime = _client(tmp_path)
    template = {
        "schema": 1,
        "name": "Imported helper",
        "instructions": "Maintain the task list.\n\n- Keep it short.",
        "require_approval": ["plugin:gmail:send"],
        "focus": ["core:search-web"],
    }
    with client:
        try:
            before = client.get("/api/society/agents").json()["total"]
            preview = client.post(
                "/api/society/starters/preview",
                json={"template": {"kind": "agent", "agent": template}},
            ).json()
            assert preview["ok"] is True
            assert preview["template"]["name"] == "Imported helper"
            assert preview["summary"]["asks_before"] == 1
            assert preview["summary"]["instructions_rules"] == 1
            bad = client.post(
                "/api/society/starters/preview",
                json={"template": {**template, "provider": "openai"}},
            ).json()
            assert bad["ok"] is False and any("provider" in e for e in bad["errors"])
            # A preview creates nothing.
            assert client.get("/api/society/agents").json()["total"] == before
            res = client.post(
                "/api/society/starters/install",
                json={"template": template, "seat": {"provider": "openai", "model": "gpt-5.2"}},
            )
            assert res.status_code == 200, res.text
            agent = res.json()["agent"]
            assert agent["model"] == "gpt-5.2"
            assert agent["approval_rules"]["require_approval"] == ["plugin:gmail:send"]
            assert res.json()["first_message"] == ""
            narrowed = client.post(
                "/api/society/starters/install",
                json={"template": template, "tools": ["core:run-shell"]},
            ).json()["agent"]
            assert "core:search-web" not in narrowed["focus"]
            assert "core:run-shell" not in narrowed["focus"]
            refused = client.post(
                "/api/society/starters/install",
                json={"template": {**template, "provider": "openai"}},
            )
            assert refused.status_code == 422
        finally:
            client.portal.call(runtime.close)


def test_imported_figure_stays_under_the_dialog_companion(tmp_path: Path):
    client, runtime = _client(tmp_path)
    template = {
        "schema": 1,
        "name": "Figure check",
        "instructions": "Keep the notes tidy.",
        "avatar": {"archetype": "scout"},
    }
    companion = {"shape": "drop", "color": "#c9a227"}
    with client:
        try:
            res = client.post(
                "/api/society/starters/install",
                json={"template": template, "seat": {"provider": "openai", "companion": companion}},
            )
            assert res.status_code == 200, res.text
            avatar = res.json()["agent"]["avatar"]
            # The template's checked figure stays; the dialog's companion wins.
            assert avatar["archetype"] == "scout"
            assert avatar["companion"]["shape"] == "drop"
        finally:
            client.portal.call(runtime.close)


async def test_routine_is_created_only_when_ticked(tmp_path: Path):
    import httpx

    store = TaskStore(tmp_path / "tasks.db")
    await store.init()
    runtime = SocietyRuntime(tmp_path / "society", seed_starter_team=False)
    app = FastAPI()
    app.include_router(router)
    app.state.society_factory = lambda: runtime
    app.state.task_store = store
    app.state.task_scheduler = None
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            plain = await client.post(
                "/api/society/starters/install", json={"starter_id": "daily-briefing"}
            )
            assert plain.json()["routine"] is None
            no_zone = await client.post(
                "/api/society/starters/install",
                json={"starter_id": "daily-briefing", "with_routine": True},
            )
            assert no_zone.json()["routine_error"] == "timezone_required"
            ticked = await client.post(
                "/api/society/starters/install",
                json={
                    "starter_id": "daily-briefing",
                    "with_routine": True,
                    "timezone": "Europe/Berlin",
                },
            )
            body = ticked.json()
            assert ticked.status_code == 200, ticked.text
            assert body["routine_error"] is None
            assert body["routine"]["title"].endswith("Morning briefing")
            agent_id = body["agent"]["agent_id"]
            routines = (await client.get(f"/api/society/agents/{agent_id}/routines")).json()
            assert routines["total"] == 1
            # A starter without a routine ignores the tick.
            quiet = await client.post(
                "/api/society/starters/install",
                json={"starter_id": "editor", "with_routine": True, "timezone": "UTC"},
            )
            assert quiet.json()["routine"] is None and quiet.json()["routine_error"] is None
    finally:
        await runtime.close()
        await store.close()


def test_routine_without_a_task_store_keeps_the_agent(tmp_path: Path):
    client, runtime = _client(tmp_path)
    with client:
        try:
            before = client.get("/api/society/agents").json()["total"]
            res = client.post(
                "/api/society/starters/install",
                json={"starter_id": "daily-briefing", "with_routine": True, "timezone": "UTC"},
            )
            assert res.status_code == 200
            assert res.json()["routine"] is None
            assert res.json()["routine_error"]
            assert client.get("/api/society/agents").json()["total"] == before + 1
        finally:
            client.portal.call(runtime.close)
