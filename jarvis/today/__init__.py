"""The person's own task list: tasks with a priority and an optional due date.

A local SQLite store (``store``) behind a small REST surface
(``jarvis/ui/web/today_routes.py``). Deterministic: no model, no network, no
schedule. It is a separate store on purpose: it never reads or writes the
agents' work (missions, scheduled agent tasks, workflows) or any other data.
"""

from __future__ import annotations

from .store import (
    PRIORITIES,
    STATUSES,
    VIEWS,
    InvalidTask,
    Task,
    TaskNotFound,
    TaskStore,
    today_db_path,
)

__all__ = [
    "PRIORITIES",
    "STATUSES",
    "VIEWS",
    "InvalidTask",
    "Task",
    "TaskNotFound",
    "TaskStore",
    "today_db_path",
]
