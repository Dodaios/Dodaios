"""The life-admin ledger: one SQLite file with the items and the mail candidates."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from collections.abc import Iterable
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Final

from .model import (
    DISMISSED,
    DONE,
    NOTICED,
    OPEN_STATUSES,
    PREPARED,
    RECURRING,
    WAITING,
    Found,
    Item,
)

log = logging.getLogger(__name__)

#: An item overdue by more than this many days no longer asks for anything.
STALE_DAYS: Final[int] = 30

_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id            TEXT PRIMARY KEY,
    kind          TEXT NOT NULL,
    title         TEXT NOT NULL,
    subject       TEXT NOT NULL DEFAULT '',
    due           TEXT,
    status        TEXT NOT NULL,
    evidence      TEXT NOT NULL DEFAULT '{}',
    draft         TEXT,
    version       INTEGER NOT NULL DEFAULT 1,
    shown_version INTEGER NOT NULL DEFAULT 0,
    created_ms    INTEGER NOT NULL,
    updated_ms    INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS candidates (
    ref      TEXT PRIMARY KEY,
    sender   TEXT NOT NULL DEFAULT '',
    subject  TEXT NOT NULL DEFAULT '',
    snippet  TEXT NOT NULL DEFAULT '',
    received TEXT NOT NULL DEFAULT '',
    added_ms INTEGER NOT NULL
);
"""

_COLUMNS = "id,kind,title,subject,due,status,evidence,draft,version,shown_version,created_ms"


def _item(row: tuple[Any, ...]) -> Item:
    (id_, kind, title, subject, due, status, evidence, draft, version, shown, created) = row
    try:
        parsed_due = date.fromisoformat(due) if due else None
    except ValueError:  # an unreadable date reads as "no date"
        parsed_due = None
    return Item(
        id=id_, kind=kind, title=title, subject=subject or "", due=parsed_due, status=status,
        evidence=json.loads(evidence or "{}"), draft=json.loads(draft) if draft else None,
        version=int(version), shown_version=int(shown), created_ms=int(created),
    )


class Ledger:
    """Thread-safe store; one short connection per call."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db:
            db.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path, timeout=10)

    def _run(self, sql: str, args: Iterable[Any] = ()) -> list[tuple[Any, ...]]:
        with self._lock, closing(self._connect()) as db:
            rows = db.execute(sql, tuple(args)).fetchall()
            db.commit()
            return rows

    # -- items ---------------------------------------------------------------

    def upsert(self, found: Found) -> str:
        """Add or refresh an item; returns ``added`` / ``updated`` / ``reopened`` / ``kept``.

        A dismissed item stays dismissed for good. A finished recurring one
        (a birthday) reopens when the next date is later than the old one.
        """
        now = int(time.time() * 1000)
        due = found.due.isoformat() if found.due else None
        with self._lock, closing(self._connect()) as db:
            row = db.execute(
                "SELECT status, due, version FROM items WHERE id=?", (found.item_id,)
            ).fetchone()
            if row is None:
                db.execute(
                    "INSERT INTO items (id,kind,title,subject,due,status,evidence,version,"
                    "shown_version,created_ms,updated_ms) VALUES (?,?,?,?,?,?,?,1,0,?,?)",
                    (found.item_id, found.kind, found.title, found.subject, due, NOTICED,
                     json.dumps(found.evidence, ensure_ascii=False), now, now),
                )
                db.commit()
                return "added"
            status, old_due, version = row
            if status == DISMISSED:
                return "kept"
            if status == DONE:
                if found.kind in RECURRING and due and (old_due or "") < due:
                    db.execute(
                        "UPDATE items SET status=?, due=?, draft=NULL, version=?, updated_ms=? "
                        "WHERE id=?", (NOTICED, due, version + 1, now, found.item_id),
                    )
                    db.commit()
                    return "reopened"
                return "kept"
            if due and due != old_due:
                db.execute(
                    "UPDATE items SET due=?, version=?, updated_ms=? WHERE id=?",
                    (due, version + 1, now, found.item_id),
                )
                db.commit()
                return "updated"
            return "kept"

    def get(self, item_id: str) -> Item | None:
        rows = self._run(f"SELECT {_COLUMNS} FROM items WHERE id=?", (item_id,))  # noqa: S608
        return _item(rows[0]) if rows else None

    def list_open(self, today: date, kinds: Iterable[str] | None = None) -> list[Item]:
        """Open items, soonest first (items without a date last); stale ones left out."""
        floor = (today - timedelta(days=STALE_DAYS)).isoformat()
        marks = ",".join("?" for _ in OPEN_STATUSES)
        rows = self._run(
            f"SELECT {_COLUMNS} FROM items WHERE status IN ({marks}) "  # noqa: S608
            "AND (due IS NULL OR due >= ?) ORDER BY due IS NULL, due, created_ms",
            (*OPEN_STATUSES, floor),
        )
        allowed = set(kinds) if kinds is not None else None
        return [i for i in map(_item, rows) if allowed is None or i.kind in allowed]

    def set_status(self, item_id: str, status: str) -> bool:
        rows = self._run(
            "UPDATE items SET status=?, updated_ms=? WHERE id=? RETURNING id",
            (status, int(time.time() * 1000), item_id),
        )
        return bool(rows)

    def set_draft(self, item_id: str, draft: dict[str, Any]) -> bool:
        """Store a prepared draft: status ``prepared`` and a new version, so the
        owner is told once that something now waits for them."""
        rows = self._run(
            "UPDATE items SET draft=?, status=?, version=version+1, updated_ms=? "
            "WHERE id=? AND status IN ('noticed','prepared','waiting') RETURNING id",
            (json.dumps(draft, ensure_ascii=False), PREPARED, int(time.time() * 1000), item_id),
        )
        return bool(rows)

    def mark_shown(self, items: Iterable[Item]) -> None:
        """The owner has read these at this version; an item with a draft now waits for a yes."""
        for item in items:
            self._run(
                "UPDATE items SET shown_version=?, "
                "status=CASE WHEN status=? AND draft IS NOT NULL THEN ? ELSE status END "
                "WHERE id=?", (item.version, PREPARED, WAITING, item.id),
            )

    # -- mail candidates -----------------------------------------------------

    def add_candidate(
        self, ref: str, sender: str, subject: str, snippet: str, received: str
    ) -> None:
        self._run(
            "INSERT OR IGNORE INTO candidates (ref,sender,subject,snippet,received,added_ms) "
            "VALUES (?,?,?,?,?,?)",
            (ref, sender, subject, snippet, received, int(time.time() * 1000)),
        )

    def candidates(self) -> list[dict[str, str]]:
        rows = self._run(
            "SELECT ref,sender,subject,snippet,received FROM candidates ORDER BY added_ms"
        )
        keys = ("ref", "sender", "subject", "snippet", "received")
        return [dict(zip(keys, r, strict=True)) for r in rows]

    def drop_candidates(self, refs: Iterable[str]) -> None:
        for ref in refs:
            self._run("DELETE FROM candidates WHERE ref=?", (ref,))
