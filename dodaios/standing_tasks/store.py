"""Durable storage of standing tasks: one SQLite file (``standing_tasks.db``), two tables.

Opened like the project store: one connection in WAL mode behind a lock. A
task, its notes and its run log survive a restart, a new chat and a different
seat; nothing about them lives in a model's context.
"""

from __future__ import annotations

import builtins
import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any, Final

from .models import StandingRun, StandingTask

log = logging.getLogger(__name__)

#: How many runs of one task are kept; older ones are dropped.
MAX_RUNS_PER_TASK: Final[int] = 200

_SCHEMA = """
CREATE TABLE IF NOT EXISTS standing_tasks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    goal TEXT NOT NULL,
    how TEXT NOT NULL DEFAULT '',
    autonomy TEXT NOT NULL,
    limits TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL,
    interval_min INTEGER NOT NULL,
    origin TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    task_id TEXT NOT NULL DEFAULT '',
    created_ms INTEGER NOT NULL,
    updated_ms INTEGER NOT NULL,
    last_run_ms INTEGER,
    next_run_ms INTEGER,
    last_outcome TEXT NOT NULL DEFAULT '',
    last_summary TEXT NOT NULL DEFAULT '',
    runs INTEGER NOT NULL DEFAULT 0,
    origin_session TEXT NOT NULL DEFAULT '',
    origin_permission TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS standing_tasks_state ON standing_tasks(state);
CREATE TABLE IF NOT EXISTS standing_runs (
    id TEXT PRIMARY KEY,
    standing_id TEXT NOT NULL,
    at_ms INTEGER NOT NULL,
    outcome TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    actions TEXT NOT NULL DEFAULT '[]',
    next_interval_min INTEGER NOT NULL,
    session_id TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS standing_runs_task ON standing_runs(standing_id, at_ms);
"""

_TASK_COLUMNS: Final[str] = (
    "id, title, goal, how, autonomy, limits, state, interval_min, origin, reason, notes, "
    "task_id, created_ms, updated_ms, last_run_ms, next_run_ms, last_outcome, last_summary, runs"
)
_RUN_COLUMNS: Final[str] = (
    "id, standing_id, at_ms, outcome, summary, actions, next_interval_min, session_id"
)


class StandingStore:
    def __init__(self, path: Path | str) -> None:
        self._path = str(path)
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        with self._lock:
            if self._path != ":memory:":
                self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------ tasks

    def save(self, task: StandingTask) -> None:
        """Insert or replace the task's row. The grant of its chat is kept."""
        marks = ",".join("?" for _ in _TASK_COLUMNS.split(","))
        updates = ", ".join(
            f"{name}=excluded.{name}"
            for name in (c.strip() for c in _TASK_COLUMNS.split(","))
            if name not in ("id", "created_ms")
        )
        with self._lock:
            self._conn.execute(
                f"INSERT INTO standing_tasks ({_TASK_COLUMNS}) VALUES ({marks}) "  # noqa: S608
                f"ON CONFLICT(id) DO UPDATE SET {updates}",
                (
                    task.id, task.title, task.goal, task.how, task.autonomy, task.limits,
                    task.state, task.interval_min, task.origin, task.reason, task.notes,
                    task.task_id, task.created_ms, task.updated_ms, task.last_run_ms,
                    task.next_run_ms, task.last_outcome, task.last_summary, task.runs,
                ),
            )
            self._conn.commit()

    def get(self, standing_id: str) -> StandingTask | None:
        with self._lock:
            row = self._conn.execute(
                f"SELECT {_TASK_COLUMNS} FROM standing_tasks WHERE id = ?",  # noqa: S608
                (str(standing_id),),
            ).fetchone()
        return _task(row) if row else None

    def list(self, *, include_ended: bool = False) -> list[StandingTask]:
        """Oldest first, so a list keeps its order while tasks run."""
        clause = "" if include_ended else "WHERE state != 'ended' "
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {_TASK_COLUMNS} FROM standing_tasks {clause}"  # noqa: S608
                "ORDER BY created_ms ASC, rowid ASC"
            ).fetchall()
        return [_task(row) for row in rows]

    def set_grant(self, standing_id: str, session_id: str, permission: str) -> None:
        """The chat the task was accepted in and the permission mode it had then."""
        with self._lock:
            self._conn.execute(
                "UPDATE standing_tasks SET origin_session = ?, origin_permission = ? WHERE id = ?",
                (session_id, permission, standing_id),
            )
            self._conn.commit()

    def grant(self, standing_id: str) -> tuple[str, str]:
        """``(origin_session, origin_permission)``; empty strings when none was saved."""
        with self._lock:
            row = self._conn.execute(
                "SELECT origin_session, origin_permission FROM standing_tasks WHERE id = ?",
                (standing_id,),
            ).fetchone()
        return (str(row[0] or ""), str(row[1] or "")) if row else ("", "")

    # ------------------------------------------------------------------- runs

    def add_run(self, run: StandingRun) -> None:
        """Insert or replace one run and keep the newest :data:`MAX_RUNS_PER_TASK`."""
        with self._lock:
            self._conn.execute(
                f"INSERT OR REPLACE INTO standing_runs ({_RUN_COLUMNS}) "  # noqa: S608
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    run.id, run.standing_id, run.at_ms, run.outcome, run.summary,
                    json.dumps(list(run.actions), ensure_ascii=False),
                    run.next_interval_min, run.session_id,
                ),
            )
            self._conn.execute(
                "DELETE FROM standing_runs WHERE standing_id = ? AND id NOT IN ("
                "SELECT id FROM standing_runs WHERE standing_id = ? "
                "ORDER BY at_ms DESC, rowid DESC LIMIT ?)",
                (run.standing_id, run.standing_id, MAX_RUNS_PER_TASK),
            )
            self._conn.commit()

    def runs(
        self, standing_id: str, *, limit: int = 20, since_ms: int | None = None
    ) -> builtins.list[StandingRun]:
        """Newest first."""
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {_RUN_COLUMNS} FROM standing_runs "  # noqa: S608
                "WHERE standing_id = ? AND at_ms >= ? ORDER BY at_ms DESC, rowid DESC LIMIT ?",
                (standing_id, int(since_ms or 0), max(1, int(limit))),
            ).fetchall()
        return [_run(row) for row in rows]

    def run_of_session(self, standing_id: str, session_id: str) -> StandingRun | None:
        """The run written from this chat, if there is one."""
        if not session_id:
            return None
        with self._lock:
            row = self._conn.execute(
                f"SELECT {_RUN_COLUMNS} FROM standing_runs "  # noqa: S608
                "WHERE standing_id = ? AND session_id = ? ORDER BY at_ms DESC LIMIT 1",
                (standing_id, session_id),
            ).fetchone()
        return _run(row) if row else None


def _task(row: tuple[Any, ...]) -> StandingTask:
    return StandingTask(
        id=str(row[0]), title=str(row[1]), goal=str(row[2]), how=str(row[3]),
        autonomy=str(row[4]), limits=str(row[5]), state=str(row[6]), interval_min=int(row[7]),
        origin=str(row[8]), reason=str(row[9]), notes=str(row[10]), task_id=str(row[11]),
        created_ms=int(row[12]), updated_ms=int(row[13]),
        last_run_ms=int(row[14]) if row[14] is not None else None,
        next_run_ms=int(row[15]) if row[15] is not None else None,
        last_outcome=str(row[16]), last_summary=str(row[17]), runs=int(row[18]),
    )


def _run(row: tuple[Any, ...]) -> StandingRun:
    try:
        actions = json.loads(row[5] or "[]")
    except ValueError:
        # A row written by hand or cut short: the run still shows, without its list.
        log.warning("standing tasks: the actions of run %s could not be read", row[0])
        actions = []
    return StandingRun(
        id=str(row[0]), standing_id=str(row[1]), at_ms=int(row[2]), outcome=str(row[3]),
        summary=str(row[4]),
        actions=tuple(str(a) for a in actions) if isinstance(actions, list) else (),
        next_interval_min=int(row[6]), session_id=str(row[7]),
    )


_store: StandingStore | None = None
_store_lock = threading.Lock()


def get_store() -> StandingStore:
    """The process store, opened on first use in the app's data directory."""
    global _store
    with _store_lock:
        if _store is None:
            from dodaios.core.config import DATA_DIR

            _store = StandingStore(Path(DATA_DIR) / "standing_tasks.db")
        return _store


def set_store(store: StandingStore | None) -> None:
    """Replace the process store (tests, an embedding host)."""
    global _store
    with _store_lock:
        _store = store
