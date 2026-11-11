"""The self-change registry's storage: ``self_changes.db``.

Three tables, all written by code in this package only (no tool, route or MCP
surface writes them from the agent's side):

``changes``      one row per versioned change: what, who, why, the exact text
                 before and after, the diff, the state.
``history``      every state move, append-only (triggers refuse UPDATE/DELETE).
``evaluations``  every regression result a gate produced, append-only. The agent
                 cannot edit its own grade: nothing here updates or deletes one.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from .surfaces import State, Surface

DB_NAME: Final = "self_changes.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS changes (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    surface TEXT NOT NULL,
    target TEXT NOT NULL,
    version INTEGER NOT NULL,
    before_text TEXT,
    after_text TEXT,
    diff TEXT NOT NULL DEFAULT '',
    author TEXT NOT NULL,
    turn TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL,
    core INTEGER NOT NULL DEFAULT 0,
    core_reasons TEXT NOT NULL DEFAULT '[]',
    gate TEXT NOT NULL DEFAULT '{}',
    note TEXT NOT NULL DEFAULT '',
    ref TEXT NOT NULL DEFAULT '',
    created_ms INTEGER NOT NULL,
    updated_ms INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS changes_target ON changes(surface, target);
CREATE INDEX IF NOT EXISTS changes_ref ON changes(ref);
CREATE TABLE IF NOT EXISTS history (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    change_id TEXT NOT NULL,
    ts_ms INTEGER NOT NULL,
    src TEXT NOT NULL,
    dst TEXT NOT NULL,
    actor TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS evaluations (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    change_id TEXT NOT NULL,
    ts_ms INTEGER NOT NULL,
    suite TEXT NOT NULL,
    status TEXT NOT NULL,
    score REAL,
    detail TEXT NOT NULL DEFAULT ''
);
CREATE TRIGGER IF NOT EXISTS history_no_update BEFORE UPDATE ON history
BEGIN SELECT RAISE(ABORT, 'the self-change history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS history_no_delete BEFORE DELETE ON history
BEGIN SELECT RAISE(ABORT, 'the self-change history is append-only'); END;
CREATE TRIGGER IF NOT EXISTS evaluations_no_update BEFORE UPDATE ON evaluations
BEGIN SELECT RAISE(ABORT, 'evaluation results are append-only'); END;
CREATE TRIGGER IF NOT EXISTS evaluations_no_delete BEFORE DELETE ON evaluations
BEGIN SELECT RAISE(ABORT, 'evaluation results are append-only'); END;
CREATE TRIGGER IF NOT EXISTS changes_no_delete BEFORE DELETE ON changes
BEGIN SELECT RAISE(ABORT, 'a recorded self-change is never deleted'); END;
"""


@dataclass(slots=True)
class Change:
    id: str
    surface: Surface
    target: str
    version: int
    before: str | None
    after: str | None
    diff: str
    author: str
    turn: str
    reason: str
    state: State
    core: bool
    core_reasons: list[str]
    gate: dict[str, Any]
    note: str
    ref: str
    created_ms: int
    updated_ms: int
    seq: int = 0

    def public(self, *, with_text: bool = False) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": self.id,
            "surface": self.surface.value,
            "target": self.target,
            "version": self.version,
            "diff": self.diff,
            "author": self.author,
            "turn": self.turn,
            "reason": self.reason,
            "state": self.state.value,
            "core": self.core,
            "core_reasons": self.core_reasons,
            "gate": self.gate,
            "note": self.note,
            "created_ms": self.created_ms,
            "updated_ms": self.updated_ms,
        }
        if with_text:
            out["before"], out["after"] = self.before, self.after
        return out


def _now() -> int:
    return int(time.time() * 1000)


class ChangeStore:
    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None

    def _db(self) -> sqlite3.Connection:
        if self._conn is None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self._path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.executescript(_SCHEMA)
            self._conn = conn
        return self._conn

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    @staticmethod
    def _change(row: sqlite3.Row) -> Change:
        return Change(
            id=row["id"],
            surface=Surface(row["surface"]),
            target=row["target"],
            version=row["version"],
            before=row["before_text"],
            after=row["after_text"],
            diff=row["diff"],
            author=row["author"],
            turn=row["turn"],
            reason=row["reason"],
            state=State(row["state"]),
            core=bool(row["core"]),
            core_reasons=json.loads(row["core_reasons"] or "[]"),
            gate=json.loads(row["gate"] or "{}"),
            note=row["note"],
            ref=row["ref"],
            created_ms=row["created_ms"],
            updated_ms=row["updated_ms"],
            seq=row["seq"],
        )

    # ------------------------------------------------------------- writes

    def add(
        self,
        *,
        surface: Surface,
        target: str,
        before: str | None,
        after: str | None,
        diff: str,
        author: str,
        turn: str,
        reason: str,
        state: State,
        core: bool,
        core_reasons: list[str],
        gate: dict[str, Any],
        ref: str = "",
    ) -> Change:
        with self._lock:
            conn = self._db()
            version = (
                conn.execute(
                    "SELECT COALESCE(MAX(version), 0) FROM changes WHERE surface=? AND target=?",
                    (surface.value, target),
                ).fetchone()[0]
                + 1
            )
            now = _now()
            change_id = uuid.uuid4().hex[:16]
            conn.execute(
                "INSERT INTO changes (id, surface, target, version, before_text, after_text, diff,"
                " author, turn, reason, state, core, core_reasons, gate, ref,"
                " created_ms, updated_ms)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    change_id,
                    surface.value,
                    target,
                    version,
                    before,
                    after,
                    diff,
                    author[:120],
                    turn[:120],
                    reason[:500],
                    state.value,
                    int(core),
                    json.dumps(core_reasons),
                    json.dumps(gate, default=str),
                    ref,
                    now,
                    now,
                ),
            )
            conn.execute(
                "INSERT INTO history (change_id, ts_ms, src, dst, actor, note)"
                " VALUES (?,?,?,?,?,?)",
                (change_id, now, "", state.value, author[:120], "recorded"),
            )
            conn.commit()
        return self.get(change_id)  # type: ignore[return-value]

    def move(self, change_id: str, state: State, *, actor: str, note: str = "") -> Change:
        with self._lock:
            conn = self._db()
            row = conn.execute("SELECT state FROM changes WHERE id=?", (change_id,)).fetchone()
            if row is None:
                raise KeyError(change_id)
            now = _now()
            conn.execute(
                "UPDATE changes SET state=?, note=?, updated_ms=? WHERE id=?",
                (state.value, note[:500], now, change_id),
            )
            conn.execute(
                "INSERT INTO history (change_id, ts_ms, src, dst, actor, note)"
                " VALUES (?,?,?,?,?,?)",
                (change_id, now, row["state"], state.value, actor[:120], note[:500]),
            )
            conn.commit()
        return self.get(change_id)  # type: ignore[return-value]

    def set_gate(self, change_id: str, gate: dict[str, Any]) -> None:
        with self._lock:
            conn = self._db()
            conn.execute(
                "UPDATE changes SET gate=? WHERE id=?", (json.dumps(gate, default=str), change_id)
            )
            conn.commit()

    def record_evaluation(
        self, change_id: str, suite: str, status: str, score: float | None, detail: str
    ) -> None:
        """Gate code only. Nothing else in the app writes an evaluation."""
        with self._lock:
            conn = self._db()
            conn.execute(
                "INSERT INTO evaluations (change_id, ts_ms, suite, status, score, detail)"
                " VALUES (?,?,?,?,?,?)",
                (change_id, _now(), suite, status, score, detail[:1000]),
            )
            conn.commit()

    # -------------------------------------------------------------- reads

    def get(self, change_id: str) -> Change | None:
        with self._lock:
            row = self._db().execute("SELECT * FROM changes WHERE id=?", (change_id,)).fetchone()
        return self._change(row) if row else None

    def by_ref(self, ref: str) -> Change | None:
        with self._lock:
            row = (
                self._db()
                .execute("SELECT * FROM changes WHERE ref=? ORDER BY seq DESC LIMIT 1", (ref,))
                .fetchone()
            )
        return self._change(row) if row else None

    def list(
        self, *, since_ms: int = 0, states: tuple[State, ...] = (), limit: int = 200
    ) -> list[Change]:
        sql, args = "SELECT * FROM changes WHERE created_ms >= ?", [since_ms]
        if states:
            sql += f" AND state IN ({','.join('?' for _ in states)})"  # noqa: S608
            args += [s.value for s in states]
        sql += " ORDER BY seq DESC LIMIT ?"
        args.append(limit)
        with self._lock:
            rows = self._db().execute(sql, args).fetchall()
        return [self._change(r) for r in rows]

    def history(self, change_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = (
                self._db()
                .execute(
                    "SELECT ts_ms, src, dst, actor, note FROM history"
                    " WHERE change_id=? ORDER BY seq",
                    (change_id,),
                )
                .fetchall()
            )
        return [dict(r) for r in rows]

    def evaluations(
        self, change_id: str = "", suite: str = "", limit: int = 100
    ) -> list[dict[str, Any]]:
        sql, args = "SELECT * FROM evaluations WHERE 1=1", []
        if change_id:
            sql += " AND change_id=?"
            args.append(change_id)
        if suite:
            sql += " AND suite=?"
            args.append(suite)
        sql += " ORDER BY seq DESC LIMIT ?"
        args.append(limit)
        with self._lock:
            rows = self._db().execute(sql, args).fetchall()
        return [dict(r) for r in rows]
