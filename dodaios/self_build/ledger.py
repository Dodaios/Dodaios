"""``self_build.db``: one row per self-built thing, the loop's only record.

Every stage of the self-building loop writes here and nowhere else: the
observer opens a case, builders attach what they created and how to undo it,
the judge attaches its verdict, use and outcome are counted, and the person's
keep / undo decisions land here too. The "Built for you" view reads it.

Plain ``sqlite3`` in WAL mode behind one lock: calls are short, so async
callers wrap them in ``asyncio.to_thread``. Only the server process writes.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, Final

from .records import (
    OPEN_STATES,
    BuildRecord,
    Kind,
    Outcome,
    State,
    TransitionError,
    can_move,
    dumps,
)

log = logging.getLogger(__name__)

DB_NAME: Final[str] = "self_build.db"

_SCHEMA: Final[str] = """
CREATE TABLE IF NOT EXISTS builds (
    id               TEXT PRIMARY KEY,
    kind             TEXT NOT NULL,
    state            TEXT NOT NULL,
    signature        TEXT NOT NULL,
    title            TEXT NOT NULL DEFAULT '',
    case_text        TEXT NOT NULL DEFAULT '',
    evidence_json    TEXT NOT NULL DEFAULT '[]',
    proof_json       TEXT NOT NULL DEFAULT '{}',
    artefact_json    TEXT NOT NULL DEFAULT '{}',
    undo_json        TEXT NOT NULL DEFAULT '{}',
    uses             INTEGER NOT NULL DEFAULT 0,
    outcomes_json    TEXT NOT NULL DEFAULT '{}',
    note             TEXT NOT NULL DEFAULT '',
    created_ms       INTEGER NOT NULL,
    updated_ms       INTEGER NOT NULL,
    trial_started_ms INTEGER NOT NULL DEFAULT 0,
    last_used_ms     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS builds_state ON builds(state);
CREATE INDEX IF NOT EXISTS builds_signature ON builds(signature);
CREATE TABLE IF NOT EXISTS history (
    seq      INTEGER PRIMARY KEY AUTOINCREMENT,
    build_id TEXT NOT NULL,
    ts_ms    INTEGER NOT NULL,
    src      TEXT NOT NULL,
    dst      TEXT NOT NULL,
    note     TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS history_build ON history(build_id);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rejections (
    signature TEXT PRIMARY KEY,
    count     INTEGER NOT NULL DEFAULT 0,
    last_ms   INTEGER NOT NULL DEFAULT 0
);
"""

_COLUMNS: Final[str] = (
    "id, kind, state, signature, title, case_text, evidence_json, proof_json, "
    "artefact_json, undo_json, uses, outcomes_json, note, created_ms, updated_ms, "
    "trial_started_ms, last_used_ms"
)

#: Called after every committed change with the record as it now stands.
ChangeHook = Callable[[BuildRecord], None]


def now_ms() -> int:
    return int(time.time() * 1000)


def _row(row: sqlite3.Row | tuple[Any, ...]) -> BuildRecord:
    return BuildRecord(
        id=str(row[0]),
        kind=Kind(str(row[1])),
        state=State(str(row[2])),
        signature=str(row[3]),
        title=str(row[4]),
        case=str(row[5]),
        evidence=tuple(json.loads(row[6] or "[]")),
        proof=json.loads(row[7] or "{}"),
        artefact=json.loads(row[8] or "{}"),
        undo=json.loads(row[9] or "{}"),
        uses=int(row[10]),
        outcomes={str(k): int(v) for k, v in json.loads(row[11] or "{}").items()},
        note=str(row[12]),
        created_ms=int(row[13]),
        updated_ms=int(row[14]),
        trial_started_ms=int(row[15]),
        last_used_ms=int(row[16]),
    )


class DuplicateBuild(ValueError):
    """An open build already answers this signature."""


class BuildLedger:
    def __init__(self, path: Path, *, on_change: ChangeHook | None = None) -> None:
        self._path = Path(path)
        self._lock = threading.RLock()
        self._on_change = on_change
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False, timeout=5.0)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    @property
    def path(self) -> Path:
        return self._path

    def set_change_hook(self, hook: ChangeHook | None) -> None:
        self._on_change = hook

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------ reads

    def get(self, build_id: str) -> BuildRecord | None:
        with self._lock:
            row = self._conn.execute(
                f"SELECT {_COLUMNS} FROM builds WHERE id = ?", (build_id,)  # noqa: S608 — fixed identifiers, bound values
            ).fetchone()
        return _row(row) if row else None

    def list(
        self,
        *,
        states: Iterable[State] | None = None,
        kinds: Iterable[Kind] | None = None,
        limit: int = 200,
    ) -> list[BuildRecord]:
        sql = f"SELECT {_COLUMNS} FROM builds"  # noqa: S608 — fixed identifiers, bound values
        where: list[str] = []
        args: list[Any] = []
        if states is not None:
            values = [State(s).value for s in states]
            where.append(f"state IN ({','.join('?' * len(values))})" if values else "0")
            args += values
        if kinds is not None:
            values = [Kind(k).value for k in kinds]
            where.append(f"kind IN ({','.join('?' * len(values))})" if values else "0")
            args += values
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY updated_ms DESC LIMIT ?"
        args.append(max(1, int(limit)))
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        return [_row(r) for r in rows]

    def open_for(self, signature: str) -> BuildRecord | None:
        """The open build answering ``signature``, if any."""
        states = [s.value for s in OPEN_STATES]
        with self._lock:
            row = self._conn.execute(
                f"SELECT {_COLUMNS} FROM builds WHERE signature = ? AND state IN "  # noqa: S608 — fixed identifiers, bound values
                f"({','.join('?' * len(states))}) LIMIT 1",
                (signature, *states),
            ).fetchone()
        return _row(row) if row else None

    def ever_for(self, signature: str) -> list[BuildRecord]:
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {_COLUMNS} FROM builds WHERE signature = ? ORDER BY created_ms",  # noqa: S608 — fixed identifiers, bound values
                (signature,),
            ).fetchall()
        return [_row(r) for r in rows]

    def count_since(
        self, since_ms: int, *, kind: Kind | None = None, built_only: bool = False
    ) -> int:
        """Builds opened since ``since_ms`` (``built_only``: past the proposal)."""
        sql = "SELECT COUNT(*) FROM builds WHERE created_ms >= ?"
        args: list[Any] = [since_ms]
        if kind is not None:
            sql += " AND kind = ?"
            args.append(Kind(kind).value)
        if built_only:
            sql += " AND state NOT IN ('proposed', 'rejected')"
        with self._lock:
            return int(self._conn.execute(sql, args).fetchone()[0])

    def count_in(self, states: Iterable[State], *, kind: Kind | None = None) -> int:
        values = [State(s).value for s in states]
        if not values:
            return 0
        sql = f"SELECT COUNT(*) FROM builds WHERE state IN ({','.join('?' * len(values))})"  # noqa: S608 — fixed identifiers, bound values
        args: list[Any] = list(values)
        if kind is not None:
            sql += " AND kind = ?"
            args.append(Kind(kind).value)
        with self._lock:
            return int(self._conn.execute(sql, args).fetchone()[0])

    def history(self, build_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT ts_ms, src, dst, note FROM history WHERE build_id = ? ORDER BY seq",
                (build_id,),
            ).fetchall()
        return [{"ts_ms": r[0], "from": r[1], "to": r[2], "note": r[3]} for r in rows]

    def rejections(self, signature: str) -> int:
        """How often the person rejected or undid a build for ``signature``."""
        with self._lock:
            row = self._conn.execute(
                "SELECT count FROM rejections WHERE signature = ?", (signature,)
            ).fetchone()
        return int(row[0]) if row else 0

    # ------------------------------------------------------------ writes

    def open_case(
        self,
        kind: Kind,
        signature: str,
        title: str,
        *,
        case: str = "",
        evidence: Iterable[str] = (),
        state: State = State.PROPOSED,
    ) -> BuildRecord:
        """Record a new build case. One open build per signature."""
        kind = Kind(kind)
        state = State(state)
        if state not in (State.PROPOSED, State.BUILDING):
            raise TransitionError(f"a build starts as proposed or building, not {state}")
        signature = signature.strip()
        if not signature:
            raise ValueError("signature is required")
        build_id = uuid.uuid4().hex[:16]
        ts = now_ms()
        with self._lock:
            if self.open_for(signature) is not None:
                raise DuplicateBuild(signature)
            self._conn.execute(
                f"INSERT INTO builds ({_COLUMNS}) VALUES "  # noqa: S608 — fixed identifiers, bound values
                "(?, ?, ?, ?, ?, ?, ?, '{}', '{}', '{}', 0, '{}', '', ?, ?, 0, 0)",
                (
                    build_id,
                    kind.value,
                    state.value,
                    signature,
                    title.strip()[:300],
                    case.strip()[:4000],
                    dumps([str(e)[:300] for e in evidence][:50]),
                    ts,
                    ts,
                ),
            )
            self._log(build_id, "", state.value, "opened", ts)
            self._conn.commit()
            record = self.get(build_id)
        assert record is not None
        self._emit(record)
        return record

    def set_state(self, build_id: str, state: State, note: str = "") -> BuildRecord:
        state = State(state)
        ts = now_ms()
        with self._lock:
            record = self._require(build_id)
            if record.state == state:
                return record
            if not can_move(record.state, state):
                raise TransitionError(f"{record.state} -> {state} is not allowed")
            trial = ts if state == State.TRIAL else record.trial_started_ms
            self._conn.execute(
                "UPDATE builds SET state = ?, note = ?, updated_ms = ?, trial_started_ms = ?"
                " WHERE id = ?",
                (state.value, note.strip()[:500], ts, trial, build_id),
            )
            if state in (State.REJECTED, State.UNDONE):
                self._conn.execute(
                    "INSERT INTO rejections (signature, count, last_ms) VALUES (?, 1, ?)"
                    " ON CONFLICT(signature) DO UPDATE SET count = count + 1, last_ms = ?",
                    (record.signature, ts, ts),
                )
            self._log(build_id, record.state.value, state.value, note, ts)
            self._conn.commit()
            updated = self._require(build_id)
        self._emit(updated)
        return updated

    def attach_proof(
        self, build_id: str, *, passed: bool, judge: str, detail: str = ""
    ) -> BuildRecord:
        proof = {"passed": bool(passed), "judge": judge[:120], "detail": detail[:2000]}
        return self._update(build_id, proof_json=dumps(proof))

    def attach_artefact(
        self, build_id: str, artefact: dict[str, Any], undo: dict[str, Any]
    ) -> BuildRecord:
        """Record what was created and what its undoer needs to remove it."""
        return self._update(build_id, artefact_json=dumps(artefact), undo_json=dumps(undo))

    def record_use(self, build_id: str, outcome: Outcome = Outcome.USED) -> BuildRecord:
        outcome = Outcome(outcome)
        ts = now_ms()
        with self._lock:
            record = self._require(build_id)
            outcomes = dict(record.outcomes)
            outcomes[outcome.value] = outcomes.get(outcome.value, 0) + 1
            uses = record.uses + (1 if outcome != Outcome.IGNORED else 0)
            self._conn.execute(
                "UPDATE builds SET uses = ?, outcomes_json = ?, last_used_ms = ?, updated_ms = ?"
                " WHERE id = ?",
                (uses, dumps(outcomes), ts, ts, build_id),
            )
            self._conn.commit()
            updated = self._require(build_id)
        self._emit(updated)
        return updated

    def get_meta(self, key: str, default: str = "") -> str:
        with self._lock:
            row = self._conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return str(row[0]) if row else default

    def set_meta(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            self._conn.commit()

    # ------------------------------------------------------------ internals

    def _require(self, build_id: str) -> BuildRecord:
        record = self.get(build_id)
        if record is None:
            raise KeyError(build_id)
        return record

    def _update(self, build_id: str, **columns: Any) -> BuildRecord:
        ts = now_ms()
        sets = ", ".join(f"{name} = ?" for name in columns)
        with self._lock:
            self._require(build_id)
            self._conn.execute(
                f"UPDATE builds SET {sets}, updated_ms = ? WHERE id = ?",  # noqa: S608 — fixed identifiers, bound values
                (*columns.values(), ts, build_id),
            )
            self._conn.commit()
            updated = self._require(build_id)
        self._emit(updated)
        return updated

    def _log(self, build_id: str, src: str, dst: str, note: str, ts: int) -> None:
        self._conn.execute(
            "INSERT INTO history (build_id, ts_ms, src, dst, note) VALUES (?, ?, ?, ?, ?)",
            (build_id, ts, src, dst, note.strip()[:500]),
        )

    def _emit(self, record: BuildRecord) -> None:
        hook = self._on_change
        if hook is None:
            return
        try:
            hook(record)
        except Exception:  # noqa: BLE001 — a listener must never undo a committed write
            log.warning("self_build: change hook failed", exc_info=True)
