"""An in-memory stand-in for ``dodaios.standing_tasks.service``.

The lead tool and the HTTP routes call the service's module-level functions. This fake
has the same functions with the same signatures, keeps tasks in a dict and records every
call, so their tests need no task store, scheduler or society runtime.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from types import ModuleType
from typing import Any

import pytest

from dodaios.core.protocols import current_started_by_user
from dodaios.standing_tasks.models import (
    AUTONOMY,
    DEFAULT_INTERVAL_MIN,
    MAX_INTERVAL_MIN,
    MAX_OPEN,
    MIN_INTERVAL_MIN,
    StandingError,
    StandingRun,
    StandingTask,
)

NOW_MS = 1_800_000_000_000


class FakeStandingService:
    def __init__(self) -> None:
        self.tasks: dict[str, StandingTask] = {}
        self.runs: dict[str, list[StandingRun]] = {}
        #: ``(function name, keyword arguments)`` in call order.
        self.calls: list[tuple[str, dict[str, Any]]] = []
        #: Raised by the next call of any function, then cleared.
        self.fail: Exception | None = None
        #: Whether ``run_now`` was called inside ``started_by_user()``.
        self.run_started_by_user: bool | None = None

    # ------------------------------------------------------------------ helpers

    def add(self, standing_id: str = "st_00000001", **fields: Any) -> StandingTask:
        base: dict[str, Any] = {
            "id": standing_id,
            "title": "Meta ads campaign",
            "goal": "Keep the cost per lead under 4 EUR.",
            "how": "",
            "autonomy": "prepare",
            "limits": "",
            "state": "active",
            "interval_min": DEFAULT_INTERVAL_MIN,
            "origin": "owner",
            "reason": "",
            "notes": "",
            "task_id": "task-1",
            "created_ms": NOW_MS,
            "updated_ms": NOW_MS,
            "last_run_ms": None,
            "next_run_ms": NOW_MS + DEFAULT_INTERVAL_MIN * 60_000,
            "last_outcome": "",
            "last_summary": "",
            "runs": 0,
        }
        base.update(fields)
        task = StandingTask(**base)
        self.tasks[task.id] = task
        return task

    def _note(self, name: str, **kwargs: Any) -> None:
        self.calls.append((name, kwargs))
        if self.fail is not None:
            error, self.fail = self.fail, None
            raise error

    def _existing(self, standing_id: str) -> StandingTask:
        task = self.tasks.get(standing_id)
        if task is None:
            raise StandingError("not_found", f"No standing task {standing_id}.")
        return task

    def _set(self, standing_id: str, **changes: Any) -> StandingTask:
        task = replace(self._existing(standing_id), **changes)
        self.tasks[task.id] = task
        return task

    def called(self, name: str) -> list[dict[str, Any]]:
        return [kwargs for called, kwargs in self.calls if called == name]

    # ------------------------------------------------------------ the service

    async def list_tasks(self, *, include_ended: bool = False) -> list[StandingTask]:
        self._note("list_tasks", include_ended=include_ended)
        return [t for t in self.tasks.values() if include_ended or t.state != "ended"]

    async def get_task(self, standing_id: str) -> StandingTask | None:
        self._note("get_task", standing_id=standing_id)
        return self.tasks.get(standing_id)

    async def runs_of(self, standing_id: str, limit: int = 20) -> list[StandingRun]:
        self._note("runs_of", standing_id=standing_id, limit=limit)
        return list(self.runs.get(standing_id, []))[:limit]

    async def propose(
        self,
        *,
        title: str,
        goal: str,
        how: str = "",
        autonomy: str = "prepare",
        limits: str = "",
        interval_min: int = DEFAULT_INTERVAL_MIN,
        reason: str = "",
    ) -> StandingTask:
        self._note(
            "propose", title=title, goal=goal, how=how, autonomy=autonomy, limits=limits,
            interval_min=interval_min, reason=reason,
        )
        return self.add(
            f"st_{len(self.tasks) + 1:08x}", title=title, goal=goal, how=how,
            autonomy=autonomy, limits=limits, interval_min=interval_min, reason=reason,
            state="proposed", origin="suggested", task_id="", next_run_ms=None,
        )

    async def take_on(
        self,
        *,
        title: str,
        goal: str,
        how: str = "",
        autonomy: str = "prepare",
        limits: str = "",
        interval_min: int = DEFAULT_INTERVAL_MIN,
        origin: str = "owner",
        origin_session: str = "",
        timezone: str = "",
    ) -> StandingTask:
        self._note(
            "take_on", title=title, goal=goal, how=how, autonomy=autonomy, limits=limits,
            interval_min=interval_min, origin=origin, origin_session=origin_session,
            timezone=timezone,
        )
        return self.add(
            f"st_{len(self.tasks) + 1:08x}", title=title, goal=goal, how=how,
            autonomy=autonomy, limits=limits, interval_min=interval_min, origin=origin,
            task_id=f"task-{len(self.tasks) + 1}",
            next_run_ms=NOW_MS + interval_min * 60_000,
        )

    async def accept(self, standing_id: str, *, origin_session: str = "") -> StandingTask:
        self._note("accept", standing_id=standing_id, origin_session=origin_session)
        if self._existing(standing_id).state != "proposed":
            raise StandingError("state", "Only a proposal can be accepted.")
        return self._set(standing_id, state="active", task_id="task-accepted")

    async def decline(self, standing_id: str) -> StandingTask:
        self._note("decline", standing_id=standing_id)
        return self._set(standing_id, state="ended")

    async def update(
        self,
        standing_id: str,
        *,
        title: str | None = None,
        goal: str | None = None,
        how: str | None = None,
        autonomy: str | None = None,
        limits: str | None = None,
        interval_min: int | None = None,
    ) -> StandingTask:
        given = {
            "title": title, "goal": goal, "how": how, "autonomy": autonomy,
            "limits": limits, "interval_min": interval_min,
        }
        changes = {key: value for key, value in given.items() if value is not None}
        self._note("update", standing_id=standing_id, **changes)
        return self._set(standing_id, **changes)

    async def pause(self, standing_id: str) -> StandingTask:
        self._note("pause", standing_id=standing_id)
        return self._set(standing_id, state="paused")

    async def resume(self, standing_id: str) -> StandingTask:
        self._note("resume", standing_id=standing_id)
        return self._set(standing_id, state="active")

    async def end(self, standing_id: str) -> StandingTask:
        self._note("end", standing_id=standing_id)
        return self._set(standing_id, state="ended")

    async def run_now(self, standing_id: str) -> StandingTask:
        self._note("run_now", standing_id=standing_id)
        self.run_started_by_user = bool(current_started_by_user.get())
        return self._existing(standing_id)

    async def report(
        self,
        standing_id: str,
        *,
        outcome: str,
        summary: str,
        notes: str | None = None,
        actions: tuple[str, ...] = (),
        next_check_min: int | None = None,
        session_id: str = "",
    ) -> StandingTask:
        self._note(
            "report", standing_id=standing_id, outcome=outcome, summary=summary, notes=notes,
            actions=actions, next_check_min=next_check_min, session_id=session_id,
        )
        task = self._existing(standing_id)
        changes: dict[str, Any] = {
            "last_outcome": outcome, "last_summary": summary, "runs": task.runs + 1,
            "last_run_ms": NOW_MS,
        }
        if notes is not None:
            changes["notes"] = notes
        if next_check_min is not None:
            changes["interval_min"] = next_check_min
        return self._set(standing_id, **changes)

    async def add_note(self, standing_id: str, text: str) -> StandingTask:
        self._note("add_note", standing_id=standing_id, text=text)
        task = self._existing(standing_id)
        return self._set(standing_id, notes=f"{task.notes}\n{text}".strip())

    async def overview(self) -> dict[str, Any]:
        self._note("overview")
        return {
            "available": True,
            "tasks": [t.to_dict() for t in self.tasks.values() if t.state != "ended"],
            "limits": {
                "min_interval_min": MIN_INTERVAL_MIN,
                "max_interval_min": MAX_INTERVAL_MIN,
                "default_interval_min": DEFAULT_INTERVAL_MIN,
                "max_open": MAX_OPEN,
            },
            "autonomy": list(AUTONOMY),
        }


_FUNCTIONS = (
    "list_tasks", "get_task", "runs_of", "propose", "take_on", "accept", "decline", "update",
    "pause", "resume", "end", "run_now", "report", "add_note", "overview",
)


def install(monkeypatch: pytest.MonkeyPatch) -> FakeStandingService:
    """Make ``dodaios.standing_tasks.service`` answer from a fresh fake for one test."""
    import dodaios.standing_tasks as package

    fake = FakeStandingService()
    module = ModuleType("dodaios.standing_tasks.service")
    for name in _FUNCTIONS:
        setattr(module, name, getattr(fake, name))
    monkeypatch.setitem(sys.modules, "dodaios.standing_tasks.service", module)
    monkeypatch.setattr(package, "service", module, raising=False)
    return fake
