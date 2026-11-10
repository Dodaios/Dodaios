"""The lead's morning brief is one tagged lead routine (agent_chat/proactive.py)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from dodaios.agent_chat import proactive
from dodaios.tasks.schema import TaskSpec


class _Store:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    async def insert(self, spec: TaskSpec) -> str:
        task_id = f"task-{len(self.rows) + 1}"
        self.rows.append(
            {"id": task_id, "state": "scheduled", "spec_json": spec.model_dump_json(), "spec": spec}
        )
        return task_id

    async def list(self, state_filter=None, *, limit: int = 100) -> list[dict]:
        return list(self.rows)

    async def get(self, task_id: str) -> dict | None:
        return next((r for r in self.rows if r["id"] == task_id), None)

    async def get_spec(self, task_id: str) -> TaskSpec | None:
        row = await self.get(task_id)
        return row["spec"] if row else None

    async def delete(self, task_id: str) -> bool:
        self.rows = [r for r in self.rows if r["id"] != task_id]
        return True


class _Scheduler:
    def __init__(self, store: _Store) -> None:
        self.store = store

    async def schedule(self, spec: TaskSpec) -> str:
        return await self.store.insert(spec)

    async def cancel_task(self, task_id: str, reason: str = "") -> bool:
        row = await self.store.get(task_id)
        if row:
            row["state"] = "cancelled"
        return True


class _Roster:
    async def get(self, agent_id: str):
        return SimpleNamespace(
            agent_id=agent_id,
            name="Dodaios",
            title="",
            description="",
            focus=(),
            provider="openai",
            model="m",
            effort="low",
            account_id="",
        )


def _runtime(store: _Store) -> SimpleNamespace:
    scheduler = _Scheduler(store)
    return SimpleNamespace(roster=_Roster(), task_services=lambda: (store, scheduler))


def test_brief_turns_on_moves_and_turns_off(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _Store()
    monkeypatch.setattr(proactive, "_runtime", lambda: _runtime(store))

    async def scenario() -> None:
        assert (await proactive.brief_state())["enabled"] is False
        on = await proactive.set_brief(enabled=True, local_time="07:30", timezone="Europe/Berlin")
        assert on["enabled"] and on["time"] == "07:30" and on["timezone"] == "Europe/Berlin"
        spec = store.rows[-1]["spec"]
        assert proactive.BRIEF_TAG in spec.tags
        assert "morning brief" in spec.action.prompt.lower()
        moved = await proactive.set_brief(
            enabled=True, local_time="09:00", timezone="Europe/Berlin"
        )
        assert moved["time"] == "09:00"
        live = [r for r in store.rows if r["state"] not in {"cancelled"}]
        assert len(live) == 1
        off = await proactive.set_brief(enabled=False, local_time="", timezone="")
        assert off["enabled"] is False

    asyncio.run(scenario())


def test_brief_rejects_a_bad_time_or_zone(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _Store()
    monkeypatch.setattr(proactive, "_runtime", lambda: _runtime(store))
    with pytest.raises(ValueError):
        asyncio.run(proactive.set_brief(enabled=True, local_time="25:00", timezone="Europe/Berlin"))
    with pytest.raises(ValueError):
        asyncio.run(proactive.set_brief(enabled=True, local_time="08:00", timezone="Mars/Base"))
