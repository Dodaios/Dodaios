"""TaskStore: the person's tasks in their own local SQLite file.

One table, one file (``<data_dir>/today/tasks.db``), created on first use so
nothing runs on the boot path. Every call opens a short-lived connection in
WAL mode; the store holds no state of its own between calls.

The values a task can take are defined once here (``PRIORITIES``,
``STATUSES``) and repeated in the table's CHECK constraints and the REST
models; ``tests/unit/today/test_task_store.py`` keeps the three in step.

Ordering is deterministic. An open task falls into one of four buckets:
overdue, due today, high priority without either, everything else. Inside a
bucket: priority, then due date (undated last), then age. The "today" view is
the first three buckets; "open" adds the fourth; "done" lists completed tasks,
newest first.
"""

from __future__ import annotations

import sqlite3
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final

PRIORITIES: Final[tuple[str, ...]] = ("high", "normal", "low")
STATUSES: Final[tuple[str, ...]] = ("open", "done")
VIEWS: Final[tuple[str, ...]] = ("today", "open", "done", "all")

TITLE_MAX_CHARS: Final[int] = 200
NOTES_MAX_CHARS: Final[int] = 2000

_PRIORITY_RANK: Final[dict[str, int]] = {name: rank for rank, name in enumerate(PRIORITIES)}
_BUCKET_OVERDUE, _BUCKET_DUE_TODAY, _BUCKET_HIGH, _BUCKET_REST = range(4)
_TODAY_BUCKETS: Final[frozenset[int]] = frozenset(
    {_BUCKET_OVERDUE, _BUCKET_DUE_TODAY, _BUCKET_HIGH}
)
_SCHEMA_VERSION: Final[int] = 1

_SCHEMA: Final[str] = f"""
CREATE TABLE IF NOT EXISTS tasks (
    id           TEXT PRIMARY KEY,
    title        TEXT NOT NULL CHECK (length(trim(title)) BETWEEN 1 AND {TITLE_MAX_CHARS}),
    notes        TEXT CHECK (notes IS NULL OR length(notes) <= {NOTES_MAX_CHARS}),
    priority     TEXT NOT NULL DEFAULT 'normal'
                 CHECK (priority IN ({", ".join(f"'{p}'" for p in PRIORITIES)})),
    due_date     TEXT CHECK (due_date IS NULL OR date(due_date) IS due_date),
    status       TEXT NOT NULL DEFAULT 'open'
                 CHECK (status IN ({", ".join(f"'{s}'" for s in STATUSES)})),
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    completed_at TEXT,
    CHECK ((status = 'done') = (completed_at IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS tasks_status_due ON tasks (status, due_date);
"""


class TaskNotFound(LookupError):
    """No task has this id."""


class InvalidTask(ValueError):
    """A field value the store does not accept; the message names the field."""


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    notes: str | None
    priority: str
    due_date: str | None
    status: str
    created_at: str
    updated_at: str
    completed_at: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def today_db_path(data_dir: str | Path) -> Path:
    """The task file inside the app's data directory (``cfg.memory.data_dir``)."""
    return Path(data_dir) / "today" / "tasks.db"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _clean_title(value: Any) -> str:
    if not isinstance(value, str):
        raise InvalidTask("title must be text")
    title = " ".join(value.split())
    if not title:
        raise InvalidTask("title must not be empty")
    if len(title) > TITLE_MAX_CHARS:
        raise InvalidTask(f"title is longer than {TITLE_MAX_CHARS} characters")
    return title


def _clean_notes(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidTask("notes must be text")
    notes = value.strip()
    if len(notes) > NOTES_MAX_CHARS:
        raise InvalidTask(f"notes are longer than {NOTES_MAX_CHARS} characters")
    return notes or None


def _clean_priority(value: Any) -> str:
    if value not in _PRIORITY_RANK:
        raise InvalidTask(f"priority must be one of {', '.join(PRIORITIES)}")
    return str(value)


def _clean_due_date(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        raise InvalidTask("due_date must be a calendar date, not a time")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip()).isoformat()
        except ValueError as exc:
            raise InvalidTask("due_date must be a date in the form YYYY-MM-DD") from exc
    raise InvalidTask("due_date must be a date in the form YYYY-MM-DD")


_UNSET: Final[Any] = object()


class TaskStore:
    """CRUD and ordering for the person's tasks. Thread-safe by construction:
    every call uses its own connection and SQLite serialises the writes."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        clock: Callable[[], datetime] = _utc_now,
        today: Callable[[], date] = date.today,
    ) -> None:
        self._db_path = Path(db_path)
        self._clock = clock
        self._today = today

    @property
    def db_path(self) -> Path:
        return self._db_path

    # -- connection -------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path, timeout=5.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        if conn.execute("PRAGMA user_version").fetchone()[0] < _SCHEMA_VERSION:
            conn.executescript(_SCHEMA)
            conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
        return conn

    def _now(self) -> str:
        return self._clock().astimezone(UTC).isoformat(timespec="seconds")

    @staticmethod
    def _row(row: sqlite3.Row) -> Task:
        return Task(**{key: row[key] for key in row.keys()})

    def _fetch(self, conn: sqlite3.Connection, task_id: str) -> Task:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            raise TaskNotFound(task_id)
        return self._row(row)

    # -- reading ----------------------------------------------------------------

    def get(self, task_id: str) -> Task:
        conn = self._connect()
        try:
            return self._fetch(conn, task_id)
        finally:
            conn.close()

    def list_tasks(self, view: str = "today", *, on: date | None = None) -> list[Task]:
        """The tasks of one view, in display order (see the module docstring)."""
        if view not in VIEWS:
            raise InvalidTask(f"view must be one of {', '.join(VIEWS)}")
        day = on or self._today()
        conn = self._connect()
        try:
            rows = conn.execute("SELECT * FROM tasks").fetchall()
        finally:
            conn.close()
        tasks = [self._row(row) for row in rows]
        open_tasks = sorted(
            (t for t in tasks if t.status == "open"), key=lambda t: self._open_key(t, day)
        )
        done_tasks = sorted(
            (t for t in tasks if t.status == "done"),
            key=lambda t: (t.completed_at or "", t.id),
            reverse=True,
        )
        if view == "today":
            return [t for t in open_tasks if self.bucket(t, day) in _TODAY_BUCKETS]
        if view == "open":
            return open_tasks
        if view == "done":
            return done_tasks
        return open_tasks + done_tasks

    @staticmethod
    def bucket(task: Task, day: date) -> int:
        """0 overdue, 1 due today, 2 high priority, 3 everything else (open tasks)."""
        if task.due_date is not None:
            due = date.fromisoformat(task.due_date)
            if due < day:
                return _BUCKET_OVERDUE
            if due == day:
                return _BUCKET_DUE_TODAY
        if task.priority == "high":
            return _BUCKET_HIGH
        return _BUCKET_REST

    @classmethod
    def _open_key(cls, task: Task, day: date) -> tuple[int, int, str, str, str]:
        return (
            cls.bucket(task, day),
            _PRIORITY_RANK[task.priority],
            task.due_date or "9999-12-31",
            task.created_at,
            task.id,
        )

    # -- writing ----------------------------------------------------------------

    def add(
        self,
        title: str,
        *,
        notes: str | None = None,
        priority: str = "normal",
        due_date: date | str | None = None,
    ) -> Task:
        values = (
            uuid.uuid4().hex,
            _clean_title(title),
            _clean_notes(notes),
            _clean_priority(priority),
            _clean_due_date(due_date),
        )
        now = self._now()
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO tasks (id, title, notes, priority, due_date, status, "
                "created_at, updated_at, completed_at) VALUES (?, ?, ?, ?, ?, 'open', ?, ?, NULL)",
                (*values, now, now),
            )
            return self._fetch(conn, values[0])
        finally:
            conn.close()

    def update(
        self,
        task_id: str,
        *,
        title: Any = _UNSET,
        notes: Any = _UNSET,
        priority: Any = _UNSET,
        due_date: Any = _UNSET,
    ) -> Task:
        """Change the given fields; ``notes=None`` / ``due_date=None`` clear them."""
        changes: dict[str, Any] = {}
        if title is not _UNSET:
            changes["title"] = _clean_title(title)
        if notes is not _UNSET:
            changes["notes"] = _clean_notes(notes)
        if priority is not _UNSET:
            changes["priority"] = _clean_priority(priority)
        if due_date is not _UNSET:
            changes["due_date"] = _clean_due_date(due_date)
        conn = self._connect()
        try:
            self._fetch(conn, task_id)
            if changes:
                changes["updated_at"] = self._now()
                assignments = ", ".join(f"{column} = ?" for column in changes)
                conn.execute(
                    f"UPDATE tasks SET {assignments} WHERE id = ?",  # noqa: S608 — fixed column names
                    (*changes.values(), task_id),
                )
            return self._fetch(conn, task_id)
        finally:
            conn.close()

    def complete(self, task_id: str) -> Task:
        """Mark done. Completing a done task keeps its first completion time."""
        now = self._now()
        conn = self._connect()
        try:
            self._fetch(conn, task_id)
            conn.execute(
                "UPDATE tasks SET status = 'done', completed_at = ?, updated_at = ? "
                "WHERE id = ? AND status = 'open'",
                (now, now, task_id),
            )
            return self._fetch(conn, task_id)
        finally:
            conn.close()

    def reopen(self, task_id: str) -> Task:
        """Mark open again. Reopening an open task changes nothing."""
        now = self._now()
        conn = self._connect()
        try:
            self._fetch(conn, task_id)
            conn.execute(
                "UPDATE tasks SET status = 'open', completed_at = NULL, updated_at = ? "
                "WHERE id = ? AND status = 'done'",
                (now, task_id),
            )
            return self._fetch(conn, task_id)
        finally:
            conn.close()

    def delete(self, task_id: str) -> None:
        conn = self._connect()
        try:
            cursor = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            if cursor.rowcount == 0:
                raise TaskNotFound(task_id)
        finally:
            conn.close()
