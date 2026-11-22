"""``verification.db``: one row per delegated coding run, and every step taken on it.

``runs`` holds what a run was bound to when it started (repository, commit,
domain, requested model, the CLI it runs on) and how it stands now. ``steps``
is the run's history, one row per thing that happened to it; a step is written
once and never changed (the table refuses ``UPDATE`` and ``DELETE``), so the
record a later score is computed from cannot be rewritten after the fact.

SQLite in the app's data directory, opened like the other stores: one
connection in WAL mode behind a lock. A step is keyed by
``(run_id, iteration, step)``, so writing the same step twice is a no-op.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Final

log = logging.getLogger(__name__)

__all__ = [
    "ENDED",
    "INTERRUPTED",
    "OPEN_STATES",
    "RUNNING",
    "STATES",
    "VerificationStore",
]

RUNNING: Final[str] = "running"
#: The run's turn ended and was recorded. Nothing has judged the work yet.
ENDED: Final[str] = "ended"
#: The run was open when the app stopped and its end could not be read back.
INTERRUPTED: Final[str] = "interrupted"
STATES: Final[tuple[str, ...]] = (RUNNING, ENDED, INTERRUPTED)
OPEN_STATES: Final[frozenset[str]] = frozenset({RUNNING})

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id            TEXT PRIMARY KEY,
    root_span_id      TEXT NOT NULL DEFAULT '',
    owner_session     TEXT NOT NULL DEFAULT '',
    owner_turn        TEXT NOT NULL DEFAULT '',
    session_id        TEXT NOT NULL,
    repo_id           TEXT NOT NULL DEFAULT '',
    workdir           TEXT NOT NULL DEFAULT '',
    isolated          INTEGER NOT NULL DEFAULT 0,
    base_sha          TEXT NOT NULL DEFAULT '',
    brief_text        TEXT NOT NULL DEFAULT '',
    domains_json      TEXT NOT NULL DEFAULT '[]',
    primary_domain    TEXT NOT NULL DEFAULT '',
    domain_source     TEXT NOT NULL DEFAULT '',
    domain_post       TEXT NOT NULL DEFAULT '',
    provider          TEXT NOT NULL DEFAULT '',
    runner            TEXT NOT NULL DEFAULT '',
    model_requested   TEXT NOT NULL DEFAULT '',
    model_resolved    TEXT NOT NULL DEFAULT '',
    effort            TEXT NOT NULL DEFAULT '',
    harness_version   TEXT NOT NULL DEFAULT '',
    harness_line      TEXT NOT NULL DEFAULT '',
    state             TEXT NOT NULL,
    turn_id           TEXT NOT NULL DEFAULT '',
    turn_status       TEXT NOT NULL DEFAULT '',
    tokens_in         INTEGER,
    tokens_out        INTEGER,
    tokens_cached     INTEGER,
    cost_usd          REAL,
    wall_ms           INTEGER,
    mixed_model       INTEGER NOT NULL DEFAULT 0,
    person_intervened INTEGER NOT NULL DEFAULT 0,
    boot_id           TEXT NOT NULL DEFAULT '',
    started_ms        INTEGER NOT NULL,
    ended_ms          INTEGER,
    gate_status       TEXT NOT NULL DEFAULT '',
    churn_lines       INTEGER,
    tree_id           TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_runs_session ON runs(session_id, started_ms DESC);
CREATE INDEX IF NOT EXISTS idx_runs_state ON runs(state, started_ms DESC);
CREATE INDEX IF NOT EXISTS idx_runs_cell
    ON runs(primary_domain, model_resolved, runner, started_ms);
CREATE TABLE IF NOT EXISTS steps (
    run_id          TEXT NOT NULL,
    iteration       INTEGER NOT NULL,
    step            TEXT NOT NULL,
    turn_id         TEXT NOT NULL DEFAULT '',
    model_resolved  TEXT NOT NULL DEFAULT '',
    harness_version TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT '',
    detail_json     TEXT NOT NULL DEFAULT '{}',
    ts_ms           INTEGER NOT NULL,
    PRIMARY KEY (run_id, iteration, step)
);
CREATE TRIGGER IF NOT EXISTS steps_no_update BEFORE UPDATE ON steps
BEGIN SELECT RAISE(ABORT, 'steps are append-only'); END;
CREATE TRIGGER IF NOT EXISTS steps_no_delete BEFORE DELETE ON steps
BEGIN SELECT RAISE(ABORT, 'steps are append-only'); END;
"""

#: Columns added after the first release; an older ``verification.db`` gains them on open.
_ADDED_COLUMNS: Final[tuple[tuple[str, str], ...]] = (
    ("gate_status", "TEXT NOT NULL DEFAULT ''"),
    ("churn_lines", "INTEGER"),
    ("tree_id", "TEXT NOT NULL DEFAULT ''"),
)

#: The run columns a caller may set after the run started.
_MUTABLE: Final[frozenset[str]] = frozenset(
    {
        "domain_post", "provider", "runner", "model_requested", "model_resolved", "effort",
        "harness_version", "harness_line", "state", "turn_id", "turn_status", "tokens_in",
        "tokens_out", "tokens_cached", "cost_usd", "wall_ms", "mixed_model",
        "person_intervened", "ended_ms", "gate_status", "churn_lines", "tree_id",
    }
)
#: Every column a new run may carry.
_INSERTABLE: Final[tuple[str, ...]] = (
    "run_id", "root_span_id", "owner_session", "owner_turn", "session_id", "repo_id",
    "workdir", "isolated", "base_sha", "brief_text", "domains_json", "primary_domain",
    "domain_source", "provider", "model_requested", "effort", "state", "boot_id", "started_ms",
)
_BRIEF_MAX: Final[int] = 20_000


def _now_ms() -> int:
    return int(time.time() * 1000)


class VerificationStore:
    """SQLite store of runs and their steps. One connection, WAL, a lock around every use."""

    def __init__(self, path: Path | str) -> None:
        self._path = str(path)
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            if self._path != ":memory:":
                self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)
            have = {row[1] for row in self._conn.execute("PRAGMA table_info(runs)")}
            for column, kind in _ADDED_COLUMNS:
                if column not in have:
                    self._conn.execute(f"ALTER TABLE runs ADD COLUMN {column} {kind}")  # noqa: S608
            self._conn.commit()

    @property
    def path(self) -> str:
        return self._path

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------ runs

    def start_run(self, run_id: str, session_id: str, **fields: Any) -> bool:
        """Record a new run. ``False`` when ``run_id`` is already on record."""
        row: dict[str, Any] = {
            "run_id": run_id,
            "session_id": session_id,
            "state": RUNNING,
            "started_ms": _now_ms(),
            **fields,
        }
        unknown = set(row) - set(_INSERTABLE)
        if unknown:
            raise ValueError(f"unknown run fields: {sorted(unknown)}")
        if isinstance(row.get("domains_json"), (list, tuple)):
            row["domains_json"] = json.dumps(list(row["domains_json"]))
        if "brief_text" in row:
            row["brief_text"] = str(row["brief_text"])[:_BRIEF_MAX]
        if "isolated" in row:
            row["isolated"] = int(bool(row["isolated"]))
        columns = ", ".join(row)
        marks = ", ".join("?" for _ in row)
        with self._lock:
            done = self._conn.execute(
                f"INSERT OR IGNORE INTO runs ({columns}) VALUES ({marks})",  # noqa: S608
                tuple(row.values()),
            )
            self._conn.commit()
            return done.rowcount > 0

    def update_run(self, run_id: str, **fields: Any) -> bool:
        """Set fields of a run. ``False`` when no such run exists."""
        unknown = set(fields) - _MUTABLE
        if unknown:
            raise ValueError(f"run fields that cannot be set: {sorted(unknown)}")
        if "state" in fields and fields["state"] not in STATES:
            raise ValueError(f"unknown run state: {fields['state']!r}")
        if not fields:
            return self.get(run_id) is not None
        for flag in ("mixed_model", "person_intervened"):
            if flag in fields:
                fields[flag] = int(bool(fields[flag]))
        assignments = ", ".join(f"{name} = ?" for name in fields)
        with self._lock:
            done = self._conn.execute(
                f"UPDATE runs SET {assignments} WHERE run_id = ?",  # noqa: S608
                (*fields.values(), run_id),
            )
            self._conn.commit()
            return done.rowcount > 0

    def get(self, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return dict(row) if row is not None else None

    def open_runs(self) -> list[dict[str, Any]]:
        """Runs that have not ended, oldest first."""
        marks = ", ".join("?" for _ in OPEN_STATES)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM runs WHERE state IN ({marks}) ORDER BY started_ms",  # noqa: S608
                tuple(sorted(OPEN_STATES)),
            ).fetchall()
        return [dict(row) for row in rows]

    def runs(self, *, since_ms: int = 0, limit: int = 10_000) -> list[dict[str, Any]]:
        """Runs started at or after ``since_ms``, newest first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM runs WHERE started_ms >= ? ORDER BY started_ms DESC LIMIT ?",
                (int(since_ms), int(limit)),
            ).fetchall()
        return [dict(row) for row in rows]

    # ----------------------------------------------------------------- steps

    def add_step(
        self,
        run_id: str,
        iteration: int,
        step: str,
        *,
        turn_id: str = "",
        model_resolved: str = "",
        harness_version: str = "",
        status: str = "",
        detail: dict[str, Any] | None = None,
        ts_ms: int | None = None,
    ) -> bool:
        """Append one step. ``False`` when this step of the run is already on record."""
        with self._lock:
            done = self._conn.execute(
                "INSERT OR IGNORE INTO steps (run_id, iteration, step, turn_id, model_resolved, "
                "harness_version, status, detail_json, ts_ms) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    run_id, int(iteration), step, turn_id, model_resolved, harness_version,
                    status, json.dumps(detail or {}, ensure_ascii=False, default=str),
                    _now_ms() if ts_ms is None else int(ts_ms),
                ),
            )
            self._conn.commit()
            return done.rowcount > 0

    def steps(self, run_id: str) -> list[dict[str, Any]]:
        """The steps of a run in the order they were written."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM steps WHERE run_id = ? ORDER BY ts_ms, rowid", (run_id,)
            ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            try:
                item["detail"] = json.loads(item.pop("detail_json") or "{}")
            except ValueError:  # a damaged detail column reads as no detail
                item["detail"] = {}
            out.append(item)
        return out
