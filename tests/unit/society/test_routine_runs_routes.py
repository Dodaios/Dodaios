"""The run history and away-parking routes over the real task store and scheduler."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from dodaios.core.bus import EventBus
from dodaios.society.routine_parking import load_state, save_state
from dodaios.society.store import SocietyStore
from dodaios.tasks.scheduler import TaskScheduler
from dodaios.tasks.store import TaskStore
from dodaios.ui.web.society_routes import router

URL = "/api/society/agents/mail"
BODY = {
    "title": "Inbox",
    "prompt": "Read the inbox.",
    "schedule": {"type": "every", "interval_seconds": 3600},
}


class _Runtime:
    def __init__(self, store: SocietyStore, chat: Any) -> None:
        self.roster = self
        self.store = store
        self._chat = chat

    async def ensure_started(self) -> None:
        pass  # No background society workers are needed for route tests.

    async def resolve(self, agent_id: str) -> Any:
        if agent_id not in ("mail", "other"):
            return None
        return SimpleNamespace(
            agent_id=agent_id,
            name=agent_id,
            title="",
            description="",
            focus=[],
            session_id=f"society:{agent_id}",
        )

    def chat_service(self) -> Any:
        return self._chat


@pytest.fixture
async def api(tmp_path: Path):
    tasks = TaskStore(tmp_path / "tasks.db")
    await tasks.init()
    society = SocietyStore(tmp_path / "society.db")
    await society.open()
    chat_events: dict[str, list[dict[str, Any]]] = {}
    chat = SimpleNamespace(
        store=SimpleNamespace(
            list_events=lambda session_id, tail=None: chat_events.get(session_id, [])
        )
    )
    app = FastAPI()
    app.include_router(router)
    app.state.society = _Runtime(society, chat)
    app.state.task_store = tasks
    app.state.task_scheduler = TaskScheduler(tasks, EventBus())
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield SimpleNamespace(
            client=client,
            tasks=tasks,
            society=society,
            scheduler=app.state.task_scheduler,
            chat_events=chat_events,
        )
    await society.close()
    await tasks.close()


async def test_runs_list_newest_first_with_duration_cost_and_origin(api: Any) -> None:
    task_id = (await api.client.post(f"{URL}/routines", json=BODY)).json()["id"]
    log = api.tasks.append_step
    await log(task_id, "log", {"event": "run_started"})
    await log(task_id, "log", {"event": "routine_chat", "session_id": "old-chat"})
    await log(task_id, "log", {"event": "run_completed", "duration_ms": 900})
    await log(task_id, "log", {"event": "run_now"})
    await log(task_id, "log", {"event": "run_started"})
    await log(
        task_id,
        "log",
        {
            "event": "routine_summary",
            "duration_ms": 1200,
            "cost_usd": 0.02,
            "provider": "codex-cli",
            "model": "gpt",
            "billed_via_key": False,
        },
    )
    await log(task_id, "log", {"event": "agent_result", "text": "Two new mails."})
    await log(task_id, "log", {"event": "run_completed", "duration_ms": 1300})
    api.chat_events["old-chat"] = [
        {"kind": "turn_started", "payload": {"turn_id": "t"}},
        {"kind": "assistant_text", "payload": {"turn_id": "t", "text": "Nothing new."}},
        {"kind": "turn_finished", "payload": {"turn_id": "t", "cost_usd": 0.01}},
    ]

    response = await api.client.get(f"{URL}/routines/{task_id}/runs")
    assert response.status_code == 200, response.text
    runs = response.json()["runs"]
    assert [r["origin"] for r in runs] == ["manual", "automatic"]
    assert runs[0]["duration_ms"] == 1200 and runs[0]["cost_usd"] == 0.02
    assert runs[0]["summary"] == "Two new mails." and "result" not in runs[0]
    assert runs[1]["cost_usd"] == 0.01 and runs[1]["summary"] == "Nothing new."

    activity = (await api.client.get(f"{URL}/routines-activity")).json()
    assert activity["last_runs"][task_id]["origin"] == "manual"
    assert activity["parking"] == {
        "enabled": True,
        "days": 7,
        "banner": False,
        "parked_ids": [],
        "parked_ms": 0,
        "parked_days": 7,
        "unread": 0,
        "never_ask": False,
    }


async def test_runs_belong_to_their_owner(api: Any) -> None:
    task_id = (await api.client.post(f"{URL}/routines", json=BODY)).json()["id"]
    assert (
        await api.client.get(f"/api/society/agents/other/routines/{task_id}/runs")
    ).status_code == 404
    assert (await api.client.get("/api/society/agents/nobody/routines-activity")).status_code == 404


async def test_seen_choice_and_settings_round_trip(api: Any) -> None:
    task_id = (await api.client.post(f"{URL}/routines", json=BODY)).json()["id"]
    seen = (await api.client.post(f"{URL}/routines-seen")).json()
    assert seen["ok"] and seen["seen_ms"] > 0

    await api.scheduler.pause(task_id)
    state = await load_state(api.society, "mail")
    state.banner, state.parked_ids, state.unread = True, [task_id], 4
    await save_state(api.society, "mail", state)
    banner = (await api.client.get(f"{URL}/routines-activity")).json()["parking"]
    assert banner["banner"] and banner["parked_ids"] == [task_id] and banner["unread"] == 4

    answer = await api.client.post(f"{URL}/routines-parking", json={"choice": "keep_running"})
    assert answer.status_code == 200, answer.text
    assert answer.json()["parking"]["banner"] is False
    assert (await api.tasks.get(task_id))["state"] == "scheduled"
    assert (
        await api.client.post(f"{URL}/routines-parking", json={"choice": "nope"})
    ).status_code == 422

    assert (await api.client.get("/api/society/routine-parking")).json() == {"days": 7}
    assert (await api.client.put("/api/society/routine-parking", json={"days": 0})).json() == {
        "days": 0
    }
    off = (await api.client.get(f"{URL}/routines-activity")).json()["parking"]
    assert off["enabled"] is False
    assert (
        await api.client.put("/api/society/routine-parking", json={"days": 400})
    ).status_code == 422
