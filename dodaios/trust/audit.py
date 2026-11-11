"""The owner's audit log: every action that went through the tool gateway.

One append-only list. The ``ToolExecutor`` writes a row for every call that
reaches it, whatever became of it: ran, failed, was blocked, refused, timed
out, was cancelled, or waits for a spoken "yes". A row says when, which tool,
who or what started it (the owner's own turn, a routine, a trigger, an agent),
how it was approved, how it ended, and the receipt of what it did.

Tamper-proof against the agent, in three layers:

* the only writer is the executor (code, never a tool); no tool, no route and
  no MCP surface exposes a write, edit or delete;
* the table refuses ``UPDATE`` and ``DELETE`` (triggers), so a stray statement
  cannot change history;
* rows form a hash chain (``row_hash`` covers the row and ``prev_hash``):
  :meth:`AuditLog.verify` reports the first row that was changed, removed or
  inserted behind the log's back, including after the triggers were dropped.

The log never raises into a call: a log that cannot write is a warning, not a
failed action.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Final

log = logging.getLogger(__name__)

OUTCOMES: Final[tuple[str, ...]] = (
    "executed",
    "failed",
    "blocked",
    "denied",
    "timeout",
    "unavailable",
    "cancelled",
    "awaiting_confirmation",
)

ORIGINS: Final[tuple[str, ...]] = ("owner", "routine", "trigger", "agent")

APPROVAL_MODES: Final[tuple[str, ...]] = (
    "auto_tier",
    "always_rule",
    "owner_click",
    "explicit_intent",
    "stance",
    "grant",
    "none",
    "other",
)

_COLUMNS: Final[tuple[str, ...]] = (
    "id",
    "ts_ms",
    "day",
    "trace_id",
    "tool",
    "action",
    "origin",
    "origin_detail",
    "session_id",
    "approval",
    "approval_by",
    "tier",
    "effect",
    "outcome",
    "error",
    "duration_ms",
    "args_preview",
    "receipt_state",
    "receipt",
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    ts_ms INTEGER NOT NULL,
    day TEXT NOT NULL,
    trace_id TEXT NOT NULL DEFAULT '',
    tool TEXT NOT NULL,
    action TEXT NOT NULL DEFAULT '',
    origin TEXT NOT NULL,
    origin_detail TEXT NOT NULL DEFAULT '',
    session_id TEXT NOT NULL DEFAULT '',
    approval TEXT NOT NULL DEFAULT 'none',
    approval_by TEXT NOT NULL DEFAULT '',
    tier TEXT NOT NULL DEFAULT '',
    effect TEXT NOT NULL DEFAULT '',
    outcome TEXT NOT NULL,
    error TEXT NOT NULL DEFAULT '',
    duration_ms INTEGER NOT NULL DEFAULT 0,
    args_preview TEXT NOT NULL DEFAULT '',
    receipt_state TEXT NOT NULL DEFAULT '',
    receipt TEXT NOT NULL DEFAULT '',
    prev_hash TEXT NOT NULL,
    row_hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS audit_day ON audit(day);
CREATE INDEX IF NOT EXISTS audit_tool ON audit(tool);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit
BEGIN SELECT RAISE(ABORT, 'the audit log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit
BEGIN SELECT RAISE(ABORT, 'the audit log is append-only'); END;
"""

_GENESIS = "0" * 64

_INSERT = (
    "INSERT INTO audit ("  # noqa: S608 — column names are constants, values are bound
    + ", ".join(_COLUMNS)
    + ", prev_hash, row_hash) VALUES ("
    + ", ".join("?" for _ in _COLUMNS)
    + ", ?, ?)"
)


# ----------------------------------------------------------------- derivation


def origin_of(config_snapshot: dict[str, Any] | None) -> tuple[str, str]:
    """Who or what started this call: ``(origin, detail)``.

    Read from the trusted run context, never from tool arguments: a scheduled
    or chained task sets ``current_trigger_path`` before its run, so the
    ancestry is there for every call the run makes.
    """
    cfg = config_snapshot or {}
    try:
        from dodaios.core.protocols import current_started_by_user, current_trigger_path

        path = tuple(current_trigger_path.get())
        by_user = bool(current_started_by_user.get())
    except Exception:  # noqa: BLE001 — an unreadable context is an unknown origin, not an error
        path, by_user = (), False
    if path:
        detail = " > ".join(path)
        if by_user:
            detail += " (run now)"
        return ("trigger" if len(path) > 1 else "routine"), detail[:200]
    source = str(cfg.get("tool_origin") or "").strip()
    session = str(cfg.get("approval_ref") or "").removeprefix("agent-chat:")
    if source in ("", "agent-chat", "realtime", "trust-undo", "brain"):
        detail = {"realtime": "voice", "trust-undo": "undo"}.get(source, "chat")
        return "owner", (f"{detail} {session}".strip())[:200]
    parts = [source]
    for key in ("mission_id", "worker_id"):
        if cfg.get(key):
            parts.append(f"{key}={cfg[key]}")
    return "agent", " ".join(parts)[:200]


def approval_of(
    *, needs_confirm: bool, approved_by: str | None, decision_by: str | None, tier: str
) -> tuple[str, str]:
    """How the call was cleared: ``(mode, raw label)``."""
    by = (approved_by or "").strip()
    if not needs_confirm:
        if (decision_by or "") == "whitelist":
            return "always_rule", "whitelist"
        return "auto_tier", tier
    if by == "explicit-intent":
        return "explicit_intent", by
    if by == "user":
        return "owner_click", by
    if by in ("bypass", "chat-bypass", "chat-accept-edits"):
        return "stance", by
    if by.startswith(("scheduled-task:", "skill-runner:")):
        return "grant", by
    if by == "auto":
        return "auto_tier", by
    return "other", by


# ---------------------------------------------------------------------- store


def _row_hash(prev: str, fields: dict[str, Any]) -> str:
    body = json.dumps(
        fields, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":")
    )
    return hashlib.sha256((prev + body).encode("utf-8")).hexdigest()


class AuditLog:
    """Append-only audit store (SQLite). Only the executor appends."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._last_hash = _GENESIS

    def _db(self) -> sqlite3.Connection:
        if self._conn is None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self._path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.executescript(_SCHEMA)
            row = conn.execute("SELECT row_hash FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
            self._last_hash = row["row_hash"] if row else _GENESIS
            self._conn = conn
        return self._conn

    def new_id(self) -> str:
        return uuid.uuid4().hex[:16]

    def record(self, entry: dict[str, Any]) -> dict[str, Any] | None:
        """Append one row. Returns the stored row, or ``None`` when it could not be written."""
        now = int(time.time() * 1000)
        ts_ms = int(entry.get("ts_ms") or now)
        fields: dict[str, Any] = {
            "id": str(entry.get("id") or self.new_id()),
            "ts_ms": ts_ms,
            "day": time.strftime("%Y-%m-%d", time.localtime(ts_ms / 1000)),
            "trace_id": str(entry.get("trace_id") or ""),
            "tool": str(entry.get("tool") or "")[:200],
            "action": str(entry.get("action") or "")[:80],
            "origin": str(entry.get("origin") or "owner"),
            "origin_detail": str(entry.get("origin_detail") or "")[:200],
            "session_id": str(entry.get("session_id") or "")[:80],
            "approval": str(entry.get("approval") or "none"),
            "approval_by": str(entry.get("approval_by") or "")[:120],
            "tier": str(entry.get("tier") or ""),
            "effect": str(entry.get("effect") or ""),
            "outcome": str(entry.get("outcome") or "failed"),
            "error": str(entry.get("error") or "")[:500],
            "duration_ms": int(entry.get("duration_ms") or 0),
            "args_preview": str(entry.get("args_preview") or "")[:500],
            "receipt_state": str((entry.get("receipt") or {}).get("state") or ""),
            "receipt": json.dumps(entry.get("receipt") or {}, ensure_ascii=False, default=str)
            if entry.get("receipt")
            else "",
        }
        try:
            with self._lock:
                conn = self._db()
                prev = self._last_hash
                digest = _row_hash(prev, fields)
                conn.execute(
                    _INSERT,
                    [*(fields[c] for c in _COLUMNS), prev, digest],
                )
                conn.commit()
                self._last_hash = digest
        except Exception:  # noqa: BLE001 — a log that cannot write never costs the action
            log.warning("audit: could not record %s", fields["tool"], exc_info=True)
            return None
        return self._public(fields)

    @staticmethod
    def _public(fields: dict[str, Any]) -> dict[str, Any]:
        row = {k: v for k, v in fields.items() if k != "receipt"}
        raw = fields.get("receipt") or ""
        try:
            row["receipt"] = json.loads(raw) if raw else None
        except ValueError:  # a damaged receipt column reads as "no receipt"; the row still lists
            row["receipt"] = None
        return row

    def query(
        self,
        *,
        day: str = "",
        tool: str = "",
        origin: str = "",
        outcome: str = "",
        limit: int = 200,
        before_seq: int = 0,
    ) -> dict[str, Any]:
        """Newest first. ``next_before`` pages further back."""
        where, params = self._where(day, tool, origin, outcome)
        if before_seq:
            where.append("seq < ?")
            params.append(int(before_seq))
        limit = max(1, min(int(limit), 5000))
        sql = "SELECT * FROM audit"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY seq DESC LIMIT ?"
        with self._lock:
            rows = self._db().execute(sql, [*params, limit + 1]).fetchall()
        page = rows[:limit]
        items = [{**self._public(dict(r)), "seq": r["seq"]} for r in page]
        return {
            "entries": items,
            "next_before": page[-1]["seq"] if len(rows) > limit and page else None,
        }

    def get(self, row_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db().execute("SELECT * FROM audit WHERE id = ?", (row_id,)).fetchone()
        return {**self._public(dict(row)), "seq": row["seq"]} if row else None

    @staticmethod
    def _where(day: str, tool: str, origin: str, outcome: str) -> tuple[list[str], list[Any]]:
        where: list[str] = []
        params: list[Any] = []
        for column, value in (("day", day), ("origin", origin), ("outcome", outcome)):
            if value:
                where.append(f"{column} = ?")
                params.append(value)
        if tool:
            where.append("lower(tool) = ?")
            params.append(tool.lower())
        return where, params

    def facets(self) -> dict[str, list[str]]:
        """The days and tools present, for the filter menus."""
        with self._lock:
            conn = self._db()
            days = [
                r[0]
                for r in conn.execute("SELECT DISTINCT day FROM audit ORDER BY day DESC LIMIT 90")
            ]
            tools = [r[0] for r in conn.execute("SELECT DISTINCT tool FROM audit ORDER BY tool")]
        return {"days": days, "tools": tools}

    def export(self, fmt: str = "json", **filters: Any) -> tuple[str, str]:
        """``(media_type, body)`` for every row matching the filters, oldest first."""
        where, params = self._where(
            str(filters.get("day") or ""),
            str(filters.get("tool") or ""),
            str(filters.get("origin") or ""),
            str(filters.get("outcome") or ""),
        )
        sql = "SELECT * FROM audit" + (  # noqa: S608 — fixed clauses, values are bound
            " WHERE " + " AND ".join(where) if where else ""
        )
        with self._lock:
            cursor = self._db().execute(sql + " ORDER BY seq", params)
            rows = [self._public(dict(r)) for r in cursor]
        if fmt == "csv":
            buf = io.StringIO()
            columns = [c for c in _COLUMNS if c != "receipt"] + ["receipt_summary", "receipt_links"]
            writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                receipt = row.get("receipt") or {}
                writer.writerow(
                    {
                        **row,
                        "receipt_summary": receipt.get("summary", ""),
                        "receipt_links": " ".join(receipt.get("links") or []),
                    }
                )
            return "text/csv; charset=utf-8", buf.getvalue()
        return "application/json", json.dumps(rows, ensure_ascii=False, indent=1)

    def verify(self) -> dict[str, Any]:
        """Walk the chain. ``ok`` is false at the first row that does not match."""
        prev = _GENESIS
        count = 0
        with self._lock:
            rows = self._db().execute("SELECT * FROM audit ORDER BY seq").fetchall()
        for row in rows:
            fields = {c: row[c] for c in _COLUMNS}
            if row["prev_hash"] != prev or _row_hash(prev, fields) != row["row_hash"]:
                return {"ok": False, "rows": count, "broken_at": row["seq"]}
            prev = row["row_hash"]
            count += 1
        return {"ok": True, "rows": count, "broken_at": None}

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None


_DEFAULT: list[AuditLog] = []


def audit_log() -> AuditLog:
    """The process-wide log under the data dir (built on first use)."""
    if not _DEFAULT:
        from dodaios.core.config import DATA_DIR

        _DEFAULT.append(AuditLog(Path(DATA_DIR) / "trust" / "audit.db"))
    return _DEFAULT[0]


def set_audit_log(log_: AuditLog | None) -> None:
    """Swap the process-wide log (tests, a custom data dir)."""
    _DEFAULT.clear()
    if log_ is not None:
        _DEFAULT.append(log_)


__all__ = [
    "APPROVAL_MODES",
    "ORIGINS",
    "OUTCOMES",
    "AuditLog",
    "approval_of",
    "audit_log",
    "origin_of",
    "set_audit_log",
]
