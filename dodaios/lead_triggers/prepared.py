"""Prepared items: work done in advance, kept until the owner looks at it.

A prepared item is a draft or a proposed fix the assistant made before it was
certain anyone would want it. It is never sent, booked or applied here: it waits
in this store for the owner to open it, and it expires silently when nobody does.
A ``silent`` row records an attempt that produced nothing worth showing (for
example a CI failure that did not reproduce); it is only counted.

States: ``prepared`` (waiting), ``used`` (the owner took it), ``discarded`` (the
owner dropped it), ``expired`` (nobody looked in time), ``silent``.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

KINDS: Final[tuple[str, ...]] = ("meeting_invite", "mail_reply", "ci_failure")
PREPARED: Final[str] = "prepared"
USED: Final[str] = "used"
DISCARDED: Final[str] = "discarded"
EXPIRED: Final[str] = "expired"
SILENT: Final[str] = "silent"
STATES: Final[tuple[str, ...]] = (PREPARED, USED, DISCARDED, EXPIRED, SILENT)
MAX_BODY_CHARS: Final[int] = 20_000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS prepared_items (
    id          TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,
    event_id    TEXT NOT NULL,
    source      TEXT NOT NULL,
    thread_key  TEXT NOT NULL DEFAULT '',
    title       TEXT NOT NULL DEFAULT '',
    body        TEXT NOT NULL DEFAULT '{}',
    state       TEXT NOT NULL,
    policy_id   TEXT NOT NULL DEFAULT '',
    created_ms  INTEGER NOT NULL,
    resolved_ms INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_prepared_thread ON prepared_items(thread_key, state);
CREATE INDEX IF NOT EXISTS idx_prepared_event ON prepared_items(event_id, kind);
"""

_COLUMNS = (
    "id, kind, event_id, source, thread_key, title, body, state, policy_id, created_ms, "
    "resolved_ms"
)


@dataclass(frozen=True, slots=True)
class PreparedItem:
    id: str
    kind: str
    event_id: str
    source: str
    thread_key: str = ""
    title: str = ""
    #: What was prepared (draft text, conflicts, diff...). Data for the owner to read.
    body: dict[str, Any] = field(default_factory=dict)
    state: str = PREPARED
    policy_id: str = ""
    created_ms: int = 0
    resolved_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "kind": self.kind, "event_id": self.event_id, "source": self.source,
            "thread_key": self.thread_key, "title": self.title, "body": dict(self.body),
            "state": self.state, "policy_id": self.policy_id, "created_ms": self.created_ms,
            "resolved_ms": self.resolved_ms,
        }


def _item(row: tuple[Any, ...]) -> PreparedItem:
    try:
        body = json.loads(row[6])
    except ValueError:  # an unreadable body is shown empty, never raised
        body = {}
    return PreparedItem(
        id=row[0], kind=row[1], event_id=row[2], source=row[3], thread_key=row[4], title=row[5],
        body=body if isinstance(body, dict) else {}, state=row[7], policy_id=row[8],
        created_ms=int(row[9]), resolved_ms=int(row[10]),
    )


class PreparedStore:
    """SQLite rows behind one lock, opened like the other small stores."""

    def __init__(self, path: Path | str = ":memory:") -> None:
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

    def add(
        self,
        *,
        kind: str,
        event_id: str,
        source: str,
        thread_key: str = "",
        title: str = "",
        body: dict[str, Any] | None = None,
        state: str = PREPARED,
        policy_id: str = "",
        now_ms: int | None = None,
    ) -> PreparedItem:
        if kind not in KINDS or state not in (PREPARED, SILENT):
            raise ValueError(f"cannot add a {state!r} item of kind {kind!r}")
        now = int(time.time() * 1000) if now_ms is None else now_ms
        encoded = json.dumps(body or {}, ensure_ascii=False)[:MAX_BODY_CHARS]
        clean_title = " ".join(title.split())[:200]
        with self._lock:
            number = self._conn.execute("SELECT COUNT(*) FROM prepared_items").fetchone()[0]
            item_id = f"pr{now}{number}"
            self._conn.execute(
                f"INSERT INTO prepared_items ({_COLUMNS}) "  # noqa: S608 - constant columns
                "VALUES (?,?,?,?,?,?,?,?,?,?,0)",
                (item_id, kind, event_id, source, thread_key, clean_title, encoded, state,
                 policy_id, now),
            )
            self._conn.commit()
        return PreparedItem(
            item_id, kind, event_id, source, thread_key, clean_title, body or {}, state,
            policy_id, now,
        )

    def has(self, event_id: str, kind: str) -> bool:
        """True while this event already has a row of this kind (waiting or settled)."""
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM prepared_items WHERE event_id = ? AND kind = ? LIMIT 1",
                (event_id, kind),
            ).fetchone()
        return row is not None

    def get(self, item_id: str) -> PreparedItem | None:
        with self._lock:
            row = self._conn.execute(
                f"SELECT {_COLUMNS} FROM prepared_items WHERE id = ?",  # noqa: S608
                (item_id,),
            ).fetchone()
        return _item(row) if row else None

    def waiting(self, thread_key: str = "", limit: int = 50) -> list[PreparedItem]:
        """Items waiting for the owner, newest first; one thread's when a key is given."""
        sql = f"SELECT {_COLUMNS} FROM prepared_items WHERE state = ?"  # noqa: S608
        params: list[Any] = [PREPARED]
        if thread_key:
            sql += " AND thread_key = ?"
            params.append(thread_key)
        sql += " ORDER BY created_ms DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [_item(r) for r in rows]

    def _resolve(self, item_id: str, state: str, now_ms: int | None) -> bool:
        now = int(time.time() * 1000) if now_ms is None else now_ms
        with self._lock:
            cur = self._conn.execute(
                "UPDATE prepared_items SET state = ?, resolved_ms = ? WHERE id = ? AND state = ?",
                (state, now, item_id, PREPARED),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def mark_used(self, item_id: str, now_ms: int | None = None) -> bool:
        return self._resolve(item_id, USED, now_ms)

    def mark_discarded(self, item_id: str, now_ms: int | None = None) -> bool:
        return self._resolve(item_id, DISCARDED, now_ms)

    def expire(self, max_age_s: float, now_ms: int | None = None) -> int:
        """Drop waiting items older than the limit, silently. Returns how many."""
        now = int(time.time() * 1000) if now_ms is None else now_ms
        with self._lock:
            cur = self._conn.execute(
                "UPDATE prepared_items SET state = ?, resolved_ms = ? "
                "WHERE state = ? AND created_ms < ?",
                (EXPIRED, now, PREPARED, now - int(max_age_s * 1000)),
            )
            self._conn.commit()
            return cur.rowcount

    def stats(self, since_ms: int = 0) -> dict[str, Any]:
        """Counts per state (overall and per kind) and the rate the score reads.

        ``use_rate`` is used / (used + discarded + expired): of the items that settled, how
        many the owner took. ``None`` until something settled.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT kind, state, COUNT(*) FROM prepared_items WHERE created_ms >= ? "
                "GROUP BY kind, state",
                (since_ms,),
            ).fetchall()
        total = dict.fromkeys(STATES, 0)
        by_kind: dict[str, dict[str, int]] = {k: dict.fromkeys(STATES, 0) for k in KINDS}
        for kind, state, count in rows:
            if state in total and kind in by_kind:
                total[state] += int(count)
                by_kind[kind][state] += int(count)
        settled = total[USED] + total[DISCARDED] + total[EXPIRED]
        return {
            **total,
            "prepared_total": sum(total[s] for s in (PREPARED, USED, DISCARDED, EXPIRED)),
            "use_rate": round(total[USED] / settled, 4) if settled else None,
            "by_kind": by_kind,
        }
