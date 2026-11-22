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
    "CHECKING",
    "ENDED",
    "INTERRUPTED",
    "OPEN_STATES",
    "RUNNING",
    "STATES",
    "VerificationStore",
]

RUNNING: Final[str] = "running"
#: A turn of the run ended and what it left is being checked; a follow-up order
#: may still come (``[rsi] verify = "enforce"`` only).
CHECKING: Final[str] = "checking"
#: The run is over and recorded. ``verdict`` says how it was judged, when it was.
ENDED: Final[str] = "ended"
#: The run was open when the app stopped and its end could not be read back.
INTERRUPTED: Final[str] = "interrupted"
STATES: Final[tuple[str, ...]] = (RUNNING, CHECKING, ENDED, INTERRUPTED)
OPEN_STATES: Final[frozenset[str]] = frozenset({RUNNING, CHECKING})

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
    tree_id           TEXT NOT NULL DEFAULT '',
    head_sha          TEXT NOT NULL DEFAULT '',
    landing           TEXT NOT NULL DEFAULT '',
    ci_status         TEXT NOT NULL DEFAULT '',
    evidence_due_ms   INTEGER,
    verdict           TEXT NOT NULL DEFAULT '',
    verdict_reason    TEXT NOT NULL DEFAULT '',
    iteration         INTEGER NOT NULL DEFAULT 0,
    follow_ups        INTEGER NOT NULL DEFAULT 0,
    signatures_json   TEXT NOT NULL DEFAULT '[]',
    heartbeat_ms      INTEGER,
    policy_id         TEXT NOT NULL DEFAULT '',
    arm               TEXT NOT NULL DEFAULT ''
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
CREATE TABLE IF NOT EXISTS workdirs (
    folder      TEXT PRIMARY KEY,
    repo_id     TEXT NOT NULL DEFAULT '',
    root        TEXT NOT NULL DEFAULT '',
    branch      TEXT NOT NULL DEFAULT '',
    base_sha    TEXT NOT NULL DEFAULT '',
    head_sha    TEXT NOT NULL DEFAULT '',
    session_id  TEXT NOT NULL DEFAULT '',
    created_ms  INTEGER NOT NULL,
    removed_ms  INTEGER
);
CREATE INDEX IF NOT EXISTS idx_workdirs_repo ON workdirs(repo_id, removed_ms);
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
    ("head_sha", "TEXT NOT NULL DEFAULT ''"),
    ("landing", "TEXT NOT NULL DEFAULT ''"),
    ("ci_status", "TEXT NOT NULL DEFAULT ''"),
    ("evidence_due_ms", "INTEGER"),
    ("verdict", "TEXT NOT NULL DEFAULT ''"),
    ("verdict_reason", "TEXT NOT NULL DEFAULT ''"),
    ("iteration", "INTEGER NOT NULL DEFAULT 0"),
    ("follow_ups", "INTEGER NOT NULL DEFAULT 0"),
    ("signatures_json", "TEXT NOT NULL DEFAULT '[]'"),
    ("heartbeat_ms", "INTEGER"),
    ("policy_id", "TEXT NOT NULL DEFAULT ''"),
    ("arm", "TEXT NOT NULL DEFAULT ''"),
)

#: The run columns a caller may set after the run started.
_MUTABLE: Final[frozenset[str]] = frozenset(
    {
        "domain_post", "provider", "runner", "model_requested", "model_resolved", "effort",
        "harness_version", "harness_line", "state", "turn_id", "turn_status", "tokens_in",
        "tokens_out", "tokens_cached", "cost_usd", "wall_ms", "mixed_model",
        "person_intervened", "ended_ms", "gate_status", "churn_lines", "tree_id",
        "head_sha", "landing", "ci_status", "evidence_due_ms", "verdict", "verdict_reason",
        "iteration", "follow_ups", "signatures_json", "heartbeat_ms",
    }
)
#: Every column a new run may carry.
_INSERTABLE: Final[tuple[str, ...]] = (
    "run_id", "root_span_id", "owner_session", "owner_turn", "session_id", "repo_id",
    "workdir", "isolated", "base_sha", "brief_text", "domains_json", "primary_domain",
    "domain_source", "provider", "model_requested", "effort", "state", "boot_id", "started_ms",
    "policy_id", "arm",
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

    def root_follow_ups(self, root_span_id: str) -> int:
        """Follow-up orders all runs of one request of the person got together."""
        if not root_span_id:
            return 0
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(SUM(follow_ups), 0) FROM runs WHERE root_span_id = ?",
                (root_span_id,),
            ).fetchone()
        return int(row[0]) if row is not None else 0

    def reviews_since(self, since_ms: int) -> int:
        """Reviews started at or after ``since_ms``, across every run."""
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM steps WHERE step = 'review_intent' AND ts_ms >= ?",
                (int(since_ms),),
            ).fetchone()
        return int(row[0]) if row is not None else 0

    def root_reviews(self, root_span_id: str) -> int:
        """Reviews started for all runs of one request of the person."""
        if not root_span_id:
            return 0
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM steps JOIN runs ON runs.run_id = steps.run_id "
                "WHERE steps.step = 'review_intent' AND runs.root_span_id = ?",
                (root_span_id,),
            ).fetchone()
        return int(row[0]) if row is not None else 0

    def evidence_due(self) -> list[dict[str, Any]]:
        """Runs whose landing and checks are to be read again, soonest first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM runs WHERE evidence_due_ms IS NOT NULL ORDER BY evidence_due_ms"
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

    # -------------------------------------------------------------- workdirs

    def add_workdir(
        self,
        folder: str,
        *,
        repo_id: str,
        root: str,
        branch: str,
        base_sha: str,
        created_ms: int,
    ) -> None:
        """Record a worktree the app made for a thread that is about to be opened.

        ``root`` is the repository's main checkout, ``base_sha`` the commit the
        worktree started from.
        """
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO workdirs (folder, repo_id, root, branch, base_sha, "
                "head_sha, session_id, created_ms, removed_ms) VALUES (?,?,?,?,?,'','',?,NULL)",
                (folder, repo_id, root, branch, base_sha, int(created_ms)),
            )
            self._conn.commit()

    def bind_workdir(self, folder: str, session_id: str) -> None:
        """Name the thread that runs in an app-made worktree."""
        with self._lock:
            self._conn.execute(
                "UPDATE workdirs SET session_id = ? WHERE folder = ?", (session_id, folder)
            )
            self._conn.commit()

    def workdir(self, folder: str) -> dict[str, Any] | None:
        """The record of the app-made worktree at ``folder``, there or put away."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM workdirs WHERE folder = ?", (folder,)
            ).fetchone()
        return dict(row) if row is not None else None

    def workdirs(self, *, repo_id: str = "") -> list[dict[str, Any]]:
        """App-made worktrees that are on disk (not put away), oldest first."""
        query = "SELECT * FROM workdirs WHERE removed_ms IS NULL"
        args: tuple[Any, ...] = ()
        if repo_id:
            query += " AND repo_id = ?"
            args = (repo_id,)
        with self._lock:
            rows = self._conn.execute(query + " ORDER BY created_ms", args).fetchall()
        return [dict(row) for row in rows]

    def workdirs_away(self) -> int:
        """How many app-made worktrees are put away and may be asked for again."""
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM workdirs WHERE removed_ms IS NOT NULL AND session_id != ''"
            ).fetchone()
        return int(row[0]) if row is not None else 0

    def close_workdir(
        self, folder: str, removed_ms: int, *, branch: str = "", head_sha: str = ""
    ) -> None:
        """Note that an app-made worktree was put away, and what it was on then."""
        with self._lock:
            self._conn.execute(
                "UPDATE workdirs SET removed_ms = ?, "
                "branch = CASE WHEN ? != '' THEN ? ELSE branch END, "
                "head_sha = CASE WHEN ? != '' THEN ? ELSE head_sha END WHERE folder = ?",
                (int(removed_ms), branch, branch, head_sha, head_sha, folder),
            )
            self._conn.commit()

    def reopen_workdir(self, folder: str) -> None:
        """Note that a worktree that was put away is on disk again."""
        with self._lock:
            self._conn.execute("UPDATE workdirs SET removed_ms = NULL WHERE folder = ?", (folder,))
            self._conn.commit()

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
