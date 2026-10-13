"""REST API for the person's own task list (``jarvis/today``).

Endpoints:

- ``GET    /api/today/tasks?view=today|open|done|all`` → tasks in display order
- ``POST   /api/today/tasks``                          → add a task
- ``GET    /api/today/tasks/{task_id}``                → one task
- ``PATCH  /api/today/tasks/{task_id}``                → change title, notes, priority, due date
- ``POST   /api/today/tasks/{task_id}/complete``       → mark done
- ``POST   /api/today/tasks/{task_id}/reopen``         → mark open again
- ``DELETE /api/today/tasks/{task_id}``                → delete (asks first as an app action)

Every route is also an app action, so the assistant reaches the list through
``find-app-action`` / ``run-app-action`` under the person's action policy:
reading runs freely, a change is logged, a delete asks first. Nothing here
calls a model or the network.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field

from jarvis.today.store import (
    NOTES_MAX_CHARS,
    TITLE_MAX_CHARS,
    InvalidTask,
    Task,
    TaskNotFound,
    TaskStore,
    today_db_path,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/today", tags=["today"])

Priority = Literal["high", "normal", "low"]
Status = Literal["open", "done"]
View = Literal["today", "open", "done", "all"]


class TaskOut(BaseModel):
    id: str
    title: str
    notes: str | None
    priority: Priority
    due_date: date | None
    status: Status
    created_at: str
    updated_at: str
    completed_at: str | None


class TaskListOut(BaseModel):
    view: View
    today: date
    tasks: list[TaskOut]


class TaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=TITLE_MAX_CHARS)
    notes: str | None = Field(default=None, max_length=NOTES_MAX_CHARS)
    priority: Priority = "normal"
    due_date: date | None = None


class TaskUpdate(BaseModel):
    """Only the fields sent are changed; ``null`` clears notes or the due date."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=TITLE_MAX_CHARS)
    notes: str | None = Field(default=None, max_length=NOTES_MAX_CHARS)
    priority: Priority | None = None
    due_date: date | None = None


class TaskDeleted(BaseModel):
    id: str
    deleted: bool


def _store(request: Request) -> TaskStore:
    """The app's task store, created on first use (never on the boot path)."""
    store = getattr(request.app.state, "today_store", None)
    if store is not None:
        return store
    config = getattr(request.app.state, "config", None)
    data_dir = getattr(getattr(config, "memory", None), "data_dir", None)
    if not data_dir:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "task list not available")
    store = TaskStore(today_db_path(data_dir))
    request.app.state.today_store = store
    return store


def _out(task: Task) -> TaskOut:
    return TaskOut.model_validate(task.to_dict())


def _not_found(task_id: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"no task with id {task_id}")


def _invalid(exc: InvalidTask) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))


@router.get("/tasks", response_model=TaskListOut)
def list_personal_tasks(request: Request, view: Annotated[View, Query()] = "today") -> TaskListOut:
    """List the person's own to-do tasks.

    ``today`` (default): overdue, due today and high priority. ``open``: every
    open task. ``done``: completed tasks, newest first. ``all``: open, then done.
    """
    store = _store(request)
    day = date.today()
    tasks = store.list_tasks(view, on=day)
    return TaskListOut(view=view, today=day, tasks=[_out(t) for t in tasks])


@router.post("/tasks", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
def add_personal_task(body: TaskCreate, request: Request) -> TaskOut:
    """Add a to-do task to the person's own list.

    Priority is high, normal or low (default normal); the due date is optional.
    """
    try:
        task = _store(request).add(
            body.title, notes=body.notes, priority=body.priority, due_date=body.due_date
        )
    except InvalidTask as exc:
        raise _invalid(exc) from exc
    return _out(task)


@router.get("/tasks/{task_id}", response_model=TaskOut)
def get_personal_task(task_id: str, request: Request) -> TaskOut:
    """Show one of the person's to-do tasks."""
    try:
        return _out(_store(request).get(task_id))
    except TaskNotFound as exc:
        raise _not_found(task_id) from exc


@router.patch("/tasks/{task_id}", response_model=TaskOut)
def update_personal_task(task_id: str, body: TaskUpdate, request: Request) -> TaskOut:
    """Change a to-do task's title, notes, priority or due date."""
    sent = body.model_fields_set
    if "title" in sent and body.title is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "title must not be empty")
    if "priority" in sent and body.priority is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "priority must be set")
    changes = {name: getattr(body, name) for name in sent}
    try:
        return _out(_store(request).update(task_id, **changes))
    except TaskNotFound as exc:
        raise _not_found(task_id) from exc
    except InvalidTask as exc:
        raise _invalid(exc) from exc


@router.post("/tasks/{task_id}/complete", response_model=TaskOut)
def complete_personal_task(task_id: str, request: Request) -> TaskOut:
    """Mark one of the person's to-do tasks as done."""
    try:
        return _out(_store(request).complete(task_id))
    except TaskNotFound as exc:
        raise _not_found(task_id) from exc


@router.post("/tasks/{task_id}/reopen", response_model=TaskOut)
def reopen_personal_task(task_id: str, request: Request) -> TaskOut:
    """Mark a done to-do task as open again."""
    try:
        return _out(_store(request).reopen(task_id))
    except TaskNotFound as exc:
        raise _not_found(task_id) from exc


@router.delete("/tasks/{task_id}", response_model=TaskDeleted)
def delete_personal_task(task_id: str, request: Request) -> TaskDeleted:
    """Delete one of the person's to-do tasks for good."""
    try:
        _store(request).delete(task_id)
    except TaskNotFound as exc:
        raise _not_found(task_id) from exc
    log.info("today: task %s deleted", task_id)
    return TaskDeleted(id=task_id, deleted=True)
