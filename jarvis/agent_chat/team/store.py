"""Durable state of team threads: the thread, its members and its entries.

Three tables in a database of their own, so the agent chat's schema stays
untouched. ``db_path=":memory:"`` for tests.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Final

__all__ = [
    "ENTRY_KINDS",
    "MODES",
    "PHASES",
    "ROLES",
    "STATES",
    "STEP_STATUSES",
    "TeamThreadStore",
    "now_ms",
]

#: How a team works. ``peers``: everyone plans, one builds, the others review.
#: ``planner_builder``: one member owns a living plan, one builds it step by
#: step, the others review the plan and every step. Twin: ``TEAM_THREAD_MODES``.
MODES: Final[tuple[str, ...]] = ("peers", "planner_builder")

#: What a member does in the planner-and-builder mode. Twin: ``TEAM_THREAD_ROLES``.
ROLES: Final[tuple[str, ...]] = ("planner", "builder", "reviewer")

#: Where one step of the living plan stands. Twin: ``TEAM_PLAN_STEP_STATUSES``.
STEP_STATUSES: Final[tuple[str, ...]] = ("open", "building", "in_review", "changes", "accepted")

#: Lifecycle of a team thread. The TypeScript twin is ``TEAM_THREAD_STATES`` in
#: ``src/lib/teamThreadsApi.ts``; ``tests/unit/agent_chat/test_team_thread_parity.py``
#: keeps the two in step (AP-4).
STATES: Final[tuple[str, ...]] = (
    "running",
    "paused",
    "needs_input",
    "done",
    "stopped",
    "failed",
)

#: The order of work. The first five are the peers' steps, the next three the
#: planner-and-builder steps; both end in ``done``. Twin: ``TEAM_THREAD_PHASES``.
PHASES: Final[tuple[str, ...]] = (
    "draft",
    "challenge",
    "converge",
    "build",
    "review",
    "planning",
    "steps",
    "final",
    "done",
)

#: What an entry of the shared thread is. Twin: ``TEAM_THREAD_ENTRY_KINDS``.
#: ``review`` and ``fix`` are also the final review of the planner-and-builder mode.
ENTRY_KINDS: Final[tuple[str, ...]] = (
    "user",
    "draft",
    "critique",
    "plan",
    "vote",
    "build",
    "review",
    "fix",
    "plan_version",
    "plan_review",
    "step_build",
    "step_review",
    "notice",
    "summary",
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS team_threads (
    team_id     TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    task        TEXT NOT NULL,
    cwd         TEXT NOT NULL,
    state       TEXT NOT NULL,
    phase       TEXT NOT NULL,
    mode        TEXT NOT NULL DEFAULT 'peers',
    reason      TEXT NOT NULL DEFAULT '',  -- why it waits, paused or failed (a short code)
    note        TEXT NOT NULL DEFAULT '',  -- the sentence that goes with the reason
    lang        TEXT NOT NULL DEFAULT '',
    limits_json TEXT NOT NULL DEFAULT '{}',
    work_json   TEXT NOT NULL DEFAULT '{}', -- rounds, builder, counters, baseline tree
    created_ms  INTEGER NOT NULL,
    updated_ms  INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS team_thread_members (
    team_id     TEXT NOT NULL,
    member_id   TEXT NOT NULL,
    session_id  TEXT NOT NULL UNIQUE,
    provider    TEXT NOT NULL,
    model       TEXT NOT NULL DEFAULT '',
    -- A model the account lists, tried once when the seat's own default is refused.
    fallback_model TEXT NOT NULL DEFAULT '',
    effort      TEXT NOT NULL DEFAULT '',
    name        TEXT NOT NULL,
    family      TEXT NOT NULL DEFAULT '',
    position    INTEGER NOT NULL,
    state       TEXT NOT NULL DEFAULT 'active',  -- active | left
    left_reason TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (team_id, member_id)
);
CREATE TABLE IF NOT EXISTS team_thread_entries (
    seq          INTEGER PRIMARY KEY AUTOINCREMENT,
    team_id      TEXT NOT NULL,
    ts_ms        INTEGER NOT NULL,
    kind         TEXT NOT NULL,
    author       TEXT NOT NULL,   -- a member id, "user" or "team"
    phase        TEXT NOT NULL,
    round        INTEGER NOT NULL DEFAULT 0,
    payload_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_team_thread_entries_team ON team_thread_entries(team_id, seq);
"""


def now_ms() -> int:
    return int(time.time() * 1000)


class TeamThreadStore:
    def __init__(self, db_path: Path | str) -> None:
        if str(db_path) != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            if str(db_path) != ":memory:":
                self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)
            columns = {row["name"] for row in self._conn.execute("PRAGMA table_info(team_threads)")}
            if "mode" not in columns:
                # A database from before the planner-and-builder mode: all its threads are peers.
                self._conn.execute(
                    "ALTER TABLE team_threads ADD COLUMN mode TEXT NOT NULL DEFAULT 'peers'"
                )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------ threads

    def create(
        self,
        *,
        title: str,
        task: str,
        cwd: str,
        lang: str,
        limits: dict[str, Any],
        members: list[dict[str, Any]],
        mode: str = "peers",
        work: dict[str, Any] | None = None,
    ) -> str:
        if mode not in MODES:
            raise ValueError(f"unknown team thread mode {mode!r}")
        team_id = uuid.uuid4().hex
        now = now_ms()
        phase = "planning" if mode == "planner_builder" else "draft"
        with self._lock:
            self._conn.execute(
                "INSERT INTO team_threads (team_id, title, task, cwd, state, phase, mode, lang, "
                "limits_json, work_json, created_ms, updated_ms) "
                "VALUES (?, ?, ?, ?, 'running', ?, ?, ?, ?, ?, ?, ?)",
                (
                    team_id,
                    title,
                    task,
                    cwd,
                    phase,
                    mode,
                    lang,
                    json.dumps(limits),
                    json.dumps(work or {}),
                    now,
                    now,
                ),
            )
            for position, member in enumerate(members):
                self._conn.execute(
                    "INSERT INTO team_thread_members (team_id, member_id, session_id, provider, "
                    "model, fallback_model, effort, name, family, position) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        team_id,
                        member["member_id"],
                        member["session_id"],
                        member["provider"],
                        member.get("model", ""),
                        member.get("fallback_model", ""),
                        member.get("effort", ""),
                        member["name"],
                        member.get("family", ""),
                        position,
                    ),
                )
            self._conn.commit()
        return team_id

    def get(self, team_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM team_threads WHERE team_id = ?", (team_id,)
            ).fetchone()
        return self._thread(row) if row else None

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM team_threads ORDER BY created_ms DESC"
            ).fetchall()
        return [self._thread(row) for row in rows]

    def update(self, team_id: str, **fields: Any) -> None:
        """Set columns of a thread; ``limits`` and ``work`` take dictionaries."""
        columns: dict[str, Any] = {}
        for key, value in fields.items():
            if key in ("limits", "work"):
                columns[f"{key}_json"] = json.dumps(value)
            elif key in ("title", "state", "phase", "reason", "note"):
                columns[key] = value
            else:
                raise ValueError(f"unknown team thread field {key!r}")
        columns["updated_ms"] = now_ms()
        assignments = ", ".join(f"{name} = ?" for name in columns)
        with self._lock:
            self._conn.execute(
                f"UPDATE team_threads SET {assignments} WHERE team_id = ?",  # noqa: S608 - fixed names
                (*columns.values(), team_id),
            )
            self._conn.commit()

    def delete(self, team_id: str) -> None:
        with self._lock:
            for table in ("team_thread_entries", "team_thread_members", "team_threads"):
                self._conn.execute(f"DELETE FROM {table} WHERE team_id = ?", (team_id,))  # noqa: S608
            self._conn.commit()

    def interrupt_running(self, *, note: str) -> int:
        """Park every thread a previous process left running; nothing resumes by itself."""
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE team_threads SET state = 'paused', reason = 'interrupted', note = ?, "
                "updated_ms = ? WHERE state = 'running'",
                (note, now_ms()),
            )
            self._conn.commit()
            return int(cursor.rowcount or 0)

    @staticmethod
    def _thread(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["limits"] = json.loads(data.pop("limits_json") or "{}")
        data["work"] = json.loads(data.pop("work_json") or "{}")
        return data

    # ------------------------------------------------------------ members

    def members(self, team_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM team_thread_members WHERE team_id = ? ORDER BY position",
                (team_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def member_left(self, team_id: str, member_id: str, reason: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE team_thread_members SET state = 'left', left_reason = ? "
                "WHERE team_id = ? AND member_id = ?",
                (reason[:500], team_id, member_id),
            )
            self._conn.commit()

    def member_model(self, team_id: str, member_id: str, model: str) -> None:
        """The member runs on ``model`` from here; its fallback is used up."""
        with self._lock:
            self._conn.execute(
                "UPDATE team_thread_members SET model = ?, fallback_model = '' "
                "WHERE team_id = ? AND member_id = ?",
                (model, team_id, member_id),
            )
            self._conn.commit()

    def session_teams(self) -> dict[str, str]:
        """``session_id -> team_id`` for every session that belongs to a team thread."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT session_id, team_id FROM team_thread_members"
            ).fetchall()
        return {str(row["session_id"]): str(row["team_id"]) for row in rows}

    # ------------------------------------------------------------ entries

    def append(
        self,
        team_id: str,
        *,
        kind: str,
        author: str,
        phase: str,
        round: int = 0,  # noqa: A002 - the column's name
        payload: dict[str, Any] | None = None,
    ) -> int:
        if kind not in ENTRY_KINDS:
            raise ValueError(f"unknown team thread entry kind {kind!r}")
        now = now_ms()
        with self._lock:
            cursor = self._conn.execute(
                "INSERT INTO team_thread_entries (team_id, ts_ms, kind, author, phase, round, "
                "payload_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (team_id, now, kind, author, phase, int(round), json.dumps(payload or {})),
            )
            self._conn.execute(
                "UPDATE team_threads SET updated_ms = ? WHERE team_id = ?", (now, team_id)
            )
            self._conn.commit()
            return int(cursor.lastrowid or 0)

    def entries(self, team_id: str, *, after: int = 0) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM team_thread_entries WHERE team_id = ? AND seq > ? ORDER BY seq",
                (team_id, int(after)),
            ).fetchall()
        out = []
        for row in rows:
            data = dict(row)
            data["payload"] = json.loads(data.pop("payload_json") or "{}")
            out.append(data)
        return out
