"""The watchdog's own memory: findings, an action log, job progress, settings.

A small SQLite file of its own (``watchdog.db``), never the chat store or the
jobs ledger, so the watchdog neither shares their locks nor can wedge on them.
It remembers three things the dedupe and the repair-once rule depend on:

* which findings are open and which the person was already told about;
* whether the one automatic repair of a finding was already tried;
* when each job's evidence last CHANGED (a job row's own timestamp moves on every
  read, so "no progress" is measured from a fingerprint kept here).

Writes are best effort for the caller: a store problem never stops a scan.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Final

from dodaios.orchestrator.watchdog.checks import Finding

#: A resolved finding that comes back is announced again only after this long.
RENOTIFY_S: Final[int] = 6 * 3600
_PROGRESS_KEEP_S: Final[int] = 7 * 24 * 3600
_EVENTS_KEEP: Final[int] = 2000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS findings (
    key TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    evidence TEXT NOT NULL DEFAULT '{}',
    actions TEXT NOT NULL DEFAULT '[]',
    open_ref TEXT NOT NULL DEFAULT '',
    repair TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL DEFAULT 'open',
    first_ms INTEGER NOT NULL,
    last_ms INTEGER NOT NULL,
    seen INTEGER NOT NULL DEFAULT 1,
    notified_ms INTEGER NOT NULL DEFAULT 0,
    repair_attempts INTEGER NOT NULL DEFAULT 0,
    repair_result TEXT NOT NULL DEFAULT '',
    judged INTEGER NOT NULL DEFAULT 0,
    judge_note TEXT NOT NULL DEFAULT '',
    quiet INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_ms INTEGER NOT NULL,
    event TEXT NOT NULL,
    key TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts_ms);
CREATE TABLE IF NOT EXISTS progress (
    job_id TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    since_ms INTEGER NOT NULL,
    seen_ms INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

DEFAULT_SETTINGS: Final[dict[str, Any]] = {
    "checks": True,
    "judge": False,
    "interval_min": 5,
}


def now_ms() -> int:
    return int(time.time() * 1000)


class WatchdogStore:
    def __init__(self, path: Path | str) -> None:
        self._path = str(path)
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False, timeout=5.0)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            if self._path != ":memory:":
                self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------ settings

    def settings(self) -> dict[str, Any]:
        raw = self.kv_get("settings")
        out = dict(DEFAULT_SETTINGS)
        try:
            stored = json.loads(raw) if raw else {}
        except ValueError:
            stored = {}
        if isinstance(stored, dict):
            for name, default in DEFAULT_SETTINGS.items():
                if name in stored and isinstance(stored[name], type(default)):
                    out[name] = stored[name]
        out["interval_min"] = min(60, max(1, int(out["interval_min"])))
        return out

    def save_settings(self, **changes: Any) -> dict[str, Any]:
        merged = {**self.settings(), **{k: v for k, v in changes.items() if k in DEFAULT_SETTINGS}}
        self.kv_set("settings", json.dumps(merged))
        return self.settings()

    def kv_get(self, key: str, default: str = "") -> str:
        with self._lock:
            row = self._conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row else default

    def kv_set(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO kv (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            self._conn.commit()

    # ------------------------------------------------------------ findings

    def upsert(self, finding: Finding, *, now: int | None = None) -> bool:
        """Record a detection; ``True`` when the finding is new or came back."""
        now = now if now is not None else now_ms()
        with self._lock:
            row = self._conn.execute(
                "SELECT state, notified_ms FROM findings WHERE key = ?", (finding.key,)
            ).fetchone()
            fields = (
                finding.kind, finding.title, json.dumps(finding.evidence, default=str),
                json.dumps(list(finding.actions)), finding.open_ref, finding.repair,
            )
            if row is None:
                self._conn.execute(
                    "INSERT INTO findings (key, kind, title, evidence, actions, open_ref, "
                    "repair, first_ms, last_ms) VALUES (?,?,?,?,?,?,?,?,?)",
                    (finding.key, *fields, now, now),
                )
                is_new = True
            else:
                reopened = row["state"] == "resolved"
                notified = int(row["notified_ms"])
                renotify = reopened and notified and now - notified >= RENOTIFY_S * 1000
                self._conn.execute(
                    "UPDATE findings SET kind=?, title=?, evidence=?, actions=?, open_ref=?, "
                    "repair=?, last_ms=?, seen=seen+1, "
                    "state=CASE WHEN state='dismissed' THEN 'dismissed' ELSE 'open' END, "
                    "notified_ms=CASE WHEN ? THEN 0 ELSE notified_ms END WHERE key=?",
                    (*fields, now, 1 if renotify else 0, finding.key),
                )
                is_new = bool(reopened and (renotify or not row["notified_ms"]))
            self._conn.commit()
        return is_new

    def resolve_missing(self, seen_keys: set[str], *, now: int | None = None) -> list[str]:
        """Close open findings the latest scan no longer sees; returns their keys."""
        now = now if now is not None else now_ms()
        with self._lock:
            rows = self._conn.execute("SELECT key FROM findings WHERE state = 'open'").fetchall()
            gone = [r["key"] for r in rows if r["key"] not in seen_keys]
            for key in gone:
                self._conn.execute(
                    "UPDATE findings SET state='resolved', last_ms=? WHERE key=?", (now, key)
                )
            self._conn.commit()
        return gone

    def get(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM findings WHERE key = ?", (key,)).fetchone()
        return _finding_row(row) if row else None

    def open_findings(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM findings WHERE state = 'open' ORDER BY first_ms DESC LIMIT ?",
                (max(1, limit),),
            ).fetchall()
        return [_finding_row(r) for r in rows]

    def to_notify(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM findings WHERE state = 'open' AND notified_ms = 0 AND quiet = 0 "
                "ORDER BY first_ms"
            ).fetchall()
        return [_finding_row(r) for r in rows]

    def mark_notified(self, keys: list[str], *, now: int | None = None) -> None:
        now = now if now is not None else now_ms()
        with self._lock:
            for key in keys:
                self._conn.execute("UPDATE findings SET notified_ms=? WHERE key=?", (now, key))
            self._conn.commit()

    def mark_quiet(self, key: str, note: str = "") -> None:
        """A finding the judge found harmless: logged, never announced."""
        with self._lock:
            self._conn.execute(
                "UPDATE findings SET quiet=1, judge_note=? WHERE key=?", (note, key)
            )
            self._conn.commit()

    def dismiss(self, key: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE findings SET state='dismissed' WHERE key=?", (key,)
            )
            self._conn.commit()
        return cur.rowcount > 0

    def claim_repair(self, key: str) -> bool:
        """Take the one automatic repair of a finding; ``False`` if it was used."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE findings SET repair_attempts = repair_attempts + 1 "
                "WHERE key = ? AND repair_attempts = 0",
                (key,),
            )
            self._conn.commit()
        return cur.rowcount > 0

    def set_repair_result(self, key: str, text: str) -> None:
        with self._lock:
            self._conn.execute("UPDATE findings SET repair_result=? WHERE key=?", (text[:300], key))
            self._conn.commit()

    def set_judged(self, key: str, note: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE findings SET judged=1, judge_note=? WHERE key=?", (note[:300], key)
            )
            self._conn.commit()

    # ---------------------------------------------------------------- log

    def log(
        self, event: str, *, key: str = "", kind: str = "", detail: str = "", now: int | None = None
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO events (ts_ms, event, key, kind, detail) VALUES (?,?,?,?,?)",
                (now if now is not None else now_ms(), event, key, kind, detail[:400]),
            )
            self._conn.execute(
                "DELETE FROM events WHERE id <= (SELECT MAX(id) FROM events) - ?", (_EVENTS_KEEP,)
            )
            self._conn.commit()

    def events_since(self, since_ms: int, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT ts_ms, event, key, kind, detail FROM events WHERE ts_ms >= ? "
                "ORDER BY id DESC LIMIT ?",
                (since_ms, max(1, limit)),
            ).fetchall()
        return [dict(r) for r in rows]

    # ----------------------------------------------------------- progress

    def track_progress(self, job_id: str, fingerprint: str, *, now: int | None = None) -> int:
        """When this job's evidence last changed (now, the first time or on a change)."""
        now = now if now is not None else now_ms()
        with self._lock:
            row = self._conn.execute(
                "SELECT fingerprint, since_ms FROM progress WHERE job_id = ?", (job_id,)
            ).fetchone()
            if row is not None and row["fingerprint"] == fingerprint:
                since = int(row["since_ms"])
                self._conn.execute("UPDATE progress SET seen_ms=? WHERE job_id=?", (now, job_id))
            else:
                since = now
                self._conn.execute(
                    "INSERT INTO progress (job_id, fingerprint, since_ms, seen_ms) "
                    "VALUES (?,?,?,?) "
                    "ON CONFLICT(job_id) DO UPDATE SET fingerprint=excluded.fingerprint, "
                    "since_ms=excluded.since_ms, seen_ms=excluded.seen_ms",
                    (job_id, fingerprint, since, now),
                )
            self._conn.execute(
                "DELETE FROM progress WHERE seen_ms < ?", (now - _PROGRESS_KEEP_S * 1000,)
            )
            self._conn.commit()
        return since


def _finding_row(row: sqlite3.Row) -> dict[str, Any]:
    out = dict(row)
    for name in ("evidence", "actions"):
        try:
            out[name] = json.loads(out.get(name) or ("{}" if name == "evidence" else "[]"))
        except ValueError:
            out[name] = {} if name == "evidence" else []
    return out


__all__ = ["DEFAULT_SETTINGS", "RENOTIFY_S", "WatchdogStore", "now_ms"]
