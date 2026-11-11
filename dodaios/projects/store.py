"""Durable storage of projects: one SQLite file (``projects.db``), one JSON document per project.

Opened like the jobs ledger: one connection in WAL mode behind a lock. A project
survives a restart, a new chat and a different seat; nothing about it lives in a
model's context.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path

from .models import Project

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    owner_session TEXT NOT NULL,
    created_ms INTEGER NOT NULL,
    updated_ms INTEGER NOT NULL,
    closed_ms INTEGER NOT NULL DEFAULT 0,
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS projects_status ON projects(status);
"""


class ProjectStore:
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

    def save(self, project: Project) -> None:
        """Insert or replace the project's row."""
        with self._lock:
            self._conn.execute(
                "INSERT INTO projects (id, status, owner_session, created_ms, updated_ms, "
                "closed_ms, data) VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                "status=excluded.status, owner_session=excluded.owner_session, "
                "updated_ms=excluded.updated_ms, closed_ms=excluded.closed_ms, "
                "data=excluded.data",
                (
                    project.id,
                    project.status,
                    project.owner_session,
                    project.created_ms,
                    project.updated_ms,
                    project.closed_ms,
                    project.model_dump_json(),
                ),
            )
            self._conn.commit()

    def get(self, project_id: str) -> Project | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT data FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
        return self._load(row[0]) if row else None

    def list(self, *, open_only: bool = False, limit: int = 500) -> list[Project]:
        """Newest first. ``open_only`` leaves out complete and abandoned projects."""
        clause = "WHERE status NOT IN ('complete','abandoned') " if open_only else ""
        with self._lock:
            rows = self._conn.execute(
                f"SELECT data FROM projects {clause}ORDER BY updated_ms DESC LIMIT ?",  # noqa: S608
                (max(1, int(limit)),),
            ).fetchall()
        return [p for p in (self._load(r[0]) for r in rows) if p is not None]

    @staticmethod
    def _load(raw: str) -> Project | None:
        try:
            return Project.model_validate_json(raw)
        except ValueError:
            log.warning("projects: a stored project could not be read", exc_info=True)
            return None


_store: ProjectStore | None = None
_store_lock = threading.Lock()


def get_store() -> ProjectStore:
    """The process store, opened on first use in the app's data directory."""
    global _store
    with _store_lock:
        if _store is None:
            from dodaios.core.config import DATA_DIR

            _store = ProjectStore(Path(DATA_DIR) / "projects.db")
        return _store


def set_store(store: ProjectStore | None) -> None:
    """Replace the process store (tests, an embedding host)."""
    global _store
    with _store_lock:
        _store = store
