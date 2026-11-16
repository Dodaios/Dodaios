"""Durable storage of rituals: one SQLite file (``rituals.db``), two tables.

Opened like the standing-task store: one connection in WAL mode behind a lock.
``rituals`` holds what the person wrote; ``ritual_days`` holds one row per
ritual and local day: what was gathered ahead, and whether the ritual ran.
"Its phrase started it today" is decided by one conditional update, so the
same phrase heard twice in one moment cannot start it twice.
"""

from __future__ import annotations

import builtins
import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any, Final

from .models import Ritual, RitualDay, RitualStep

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS rituals (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    phrases TEXT NOT NULL DEFAULT '[]',
    enabled INTEGER NOT NULL DEFAULT 1,
    window_from TEXT NOT NULL DEFAULT '',
    window_to TEXT NOT NULL DEFAULT '',
    weekdays TEXT NOT NULL DEFAULT '[]',
    once_per_day INTEGER NOT NULL DEFAULT 1,
    prepare_from TEXT NOT NULL DEFAULT '',
    steps TEXT NOT NULL DEFAULT '[]',
    task_id TEXT NOT NULL DEFAULT '',
    origin TEXT NOT NULL DEFAULT 'owner',
    created_ms INTEGER NOT NULL,
    updated_ms INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS ritual_days (
    ritual_id TEXT NOT NULL,
    day TEXT NOT NULL,
    prep_state TEXT NOT NULL DEFAULT '',
    prep_attempts INTEGER NOT NULL DEFAULT 0,
    prep_error TEXT NOT NULL DEFAULT '',
    prep_session TEXT NOT NULL DEFAULT '',
    prepared_ms INTEGER,
    steps_hash TEXT NOT NULL DEFAULT '',
    spoken TEXT NOT NULL DEFAULT '',
    written TEXT NOT NULL DEFAULT '',
    fired_ms INTEGER,
    fired_via TEXT NOT NULL DEFAULT '',
    results TEXT NOT NULL DEFAULT '[]',
    delivered_ms INTEGER,
    phrase_ms INTEGER,
    PRIMARY KEY (ritual_id, day)
);
"""

_RITUAL_COLUMNS: Final[str] = (
    "id, name, phrases, enabled, window_from, window_to, weekdays, once_per_day, "
    "prepare_from, steps, task_id, origin, created_ms, updated_ms"
)
_DAY_COLUMNS: Final[str] = (
    "ritual_id, day, prep_state, prep_attempts, prep_error, prep_session, prepared_ms, "
    "steps_hash, spoken, written, fired_ms, fired_via, results, delivered_ms, phrase_ms"
)
#: The columns of a day :meth:`RitualStore.patch_day` may write.
_DAY_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "prep_state", "prep_attempts", "prep_error", "prep_session", "prepared_ms",
        "steps_hash", "spoken", "written", "fired_ms", "fired_via", "results", "delivered_ms",
    }
)


class RitualStore:
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

    # ---------------------------------------------------------------- rituals

    def save(self, ritual: Ritual) -> None:
        """Insert or replace the ritual's row."""
        names = [name.strip() for name in _RITUAL_COLUMNS.split(",")]
        marks = ",".join("?" for _ in names)
        updates = ", ".join(
            f"{name}=excluded.{name}" for name in names if name not in ("id", "created_ms")
        )
        with self._lock:
            self._conn.execute(
                f"INSERT INTO rituals ({_RITUAL_COLUMNS}) VALUES ({marks}) "  # noqa: S608
                f"ON CONFLICT(id) DO UPDATE SET {updates}",
                (
                    ritual.id, ritual.name,
                    json.dumps(list(ritual.phrases), ensure_ascii=False),
                    int(ritual.enabled), ritual.window_from, ritual.window_to,
                    json.dumps(list(ritual.weekdays)), int(ritual.once_per_day),
                    ritual.prepare_from,
                    json.dumps([step.to_dict() for step in ritual.steps], ensure_ascii=False),
                    ritual.task_id, ritual.origin, ritual.created_ms, ritual.updated_ms,
                ),
            )
            self._conn.commit()

    def get(self, ritual_id: str) -> Ritual | None:
        with self._lock:
            row = self._conn.execute(
                f"SELECT {_RITUAL_COLUMNS} FROM rituals WHERE id = ?",  # noqa: S608
                (str(ritual_id),),
            ).fetchone()
        return _ritual(row) if row else None

    def list(self) -> list[Ritual]:
        """Oldest first, so the list keeps its order."""
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {_RITUAL_COLUMNS} FROM rituals "  # noqa: S608
                "ORDER BY created_ms ASC, rowid ASC"
            ).fetchall()
        return [_ritual(row) for row in rows]

    def delete(self, ritual_id: str) -> bool:
        """Remove the ritual and its days; ``False`` when there was none."""
        with self._lock:
            cursor = self._conn.execute("DELETE FROM rituals WHERE id = ?", (str(ritual_id),))
            self._conn.execute("DELETE FROM ritual_days WHERE ritual_id = ?", (str(ritual_id),))
            self._conn.commit()
            return cursor.rowcount > 0

    # ------------------------------------------------------------------- days

    def day(self, ritual_id: str, day: str) -> RitualDay | None:
        with self._lock:
            row = self._conn.execute(
                f"SELECT {_DAY_COLUMNS} FROM ritual_days "  # noqa: S608
                "WHERE ritual_id = ? AND day = ?",
                (str(ritual_id), str(day)),
            ).fetchone()
        return _day(row) if row else None

    def days(self, day: str) -> builtins.list[RitualDay]:
        """Every ritual's row of one day."""
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {_DAY_COLUMNS} FROM ritual_days WHERE day = ?",  # noqa: S608
                (str(day),),
            ).fetchall()
        return [_day(row) for row in rows]

    def claim_fire(self, ritual_id: str, day: str, at_ms: int, via: str) -> bool:
        """Start the ritual by its phrase for today; ``False`` when the phrase
        already started it on this day.

        One conditional update decides it, so of two starts in the same moment
        exactly one gets ``True``.
        """
        with self._lock:
            self._ensure_day(ritual_id, day)
            cursor = self._conn.execute(
                "UPDATE ritual_days SET phrase_ms = ?, fired_ms = ?, fired_via = ?, "
                "results = '[]', delivered_ms = NULL "
                "WHERE ritual_id = ? AND day = ? AND phrase_ms IS NULL",
                (int(at_ms), int(at_ms), str(via), str(ritual_id), str(day)),
            )
            self._conn.commit()
            return cursor.rowcount == 1

    def record_fire(self, ritual_id: str, day: str, at_ms: int, via: str) -> None:
        """Mark a start that is not the phrase's one start of the day: a click,
        the assistant on request, a ritual that may repeat. It neither uses up
        the phrase nor is held back by it."""
        with self._lock:
            self._ensure_day(ritual_id, day)
            self._conn.execute(
                "UPDATE ritual_days SET fired_ms = ?, fired_via = ?, results = '[]', "
                "delivered_ms = NULL WHERE ritual_id = ? AND day = ?",
                (int(at_ms), str(via), str(ritual_id), str(day)),
            )
            self._conn.commit()

    def claim_delivery(self, ritual_id: str, day: str, at_ms: int) -> bool:
        """Mark what a start is owed as handed over; ``False`` when it was already.

        One conditional update, so of two hand-overs in the same moment exactly
        one posts its card.
        """
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE ritual_days SET delivered_ms = ? "
                "WHERE ritual_id = ? AND day = ? AND fired_ms IS NOT NULL "
                "AND delivered_ms IS NULL",
                (int(at_ms), str(ritual_id), str(day)),
            )
            self._conn.commit()
            return cursor.rowcount == 1

    def patch_day(self, ritual_id: str, day: str, **fields: Any) -> RitualDay:
        """Write ``fields`` on the day's row (created when missing) and return it."""
        unknown = set(fields) - _DAY_FIELDS
        if unknown:
            raise ValueError(f"not a day field: {sorted(unknown)}")
        values = dict(fields)
        if "results" in values:
            values["results"] = json.dumps(
                [str(line) for line in values["results"]], ensure_ascii=False
            )
        with self._lock:
            self._ensure_day(ritual_id, day)
            if values:
                assignments = ", ".join(f"{name} = ?" for name in values)
                self._conn.execute(
                    f"UPDATE ritual_days SET {assignments} "  # noqa: S608
                    "WHERE ritual_id = ? AND day = ?",
                    (*values.values(), str(ritual_id), str(day)),
                )
            self._conn.commit()
            row = self._conn.execute(
                f"SELECT {_DAY_COLUMNS} FROM ritual_days "  # noqa: S608
                "WHERE ritual_id = ? AND day = ?",
                (str(ritual_id), str(day)),
            ).fetchone()
        return _day(row)

    def prune(self, before_day: str) -> int:
        """Drop the days before ``before_day``; returns how many rows went."""
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM ritual_days WHERE day < ?", (str(before_day),)
            )
            self._conn.commit()
            return cursor.rowcount

    def _ensure_day(self, ritual_id: str, day: str) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO ritual_days (ritual_id, day) VALUES (?, ?)",
            (str(ritual_id), str(day)),
        )


def _json_list(raw: Any, what: str, owner: Any) -> builtins.list[Any]:
    try:
        value = json.loads(raw or "[]")
    except ValueError:
        # A row written by hand or cut short: the ritual still shows, without that list.
        log.warning("rituals: the %s of %s could not be read", what, owner)
        return []
    return value if isinstance(value, list) else []


def _ritual(row: tuple[Any, ...]) -> Ritual:
    steps = tuple(
        RitualStep(
            id=str(item.get("id") or ""),
            when=str(item.get("when") or ""),
            text=str(item.get("text") or ""),
            call=dict(item["call"]) if isinstance(item.get("call"), dict) else None,
        )
        for item in _json_list(row[9], "steps", row[0])
        if isinstance(item, dict)
    )
    weekdays = tuple(
        int(day) for day in _json_list(row[6], "weekdays", row[0]) if isinstance(day, int)
    )
    return Ritual(
        id=str(row[0]), name=str(row[1]),
        phrases=tuple(str(phrase) for phrase in _json_list(row[2], "phrases", row[0])),
        enabled=bool(row[3]), window_from=str(row[4]), window_to=str(row[5]),
        weekdays=weekdays, once_per_day=bool(row[7]), prepare_from=str(row[8]),
        steps=steps, task_id=str(row[10]), origin=str(row[11]),
        created_ms=int(row[12]), updated_ms=int(row[13]),
    )


def _day(row: tuple[Any, ...]) -> RitualDay:
    return RitualDay(
        ritual_id=str(row[0]), day=str(row[1]), prep_state=str(row[2]),
        prep_attempts=int(row[3]), prep_error=str(row[4]), prep_session=str(row[5]),
        prepared_ms=int(row[6]) if row[6] is not None else None,
        steps_hash=str(row[7]), spoken=str(row[8]), written=str(row[9]),
        fired_ms=int(row[10]) if row[10] is not None else None,
        fired_via=str(row[11]),
        results=tuple(str(line) for line in _json_list(row[12], "results", row[0])),
        delivered_ms=int(row[13]) if row[13] is not None else None,
        phrase_ms=int(row[14]) if row[14] is not None else None,
    )


_store: RitualStore | None = None
_store_lock = threading.Lock()


def get_store() -> RitualStore:
    """The process store, opened on first use in the app's data directory."""
    global _store
    with _store_lock:
        if _store is None:
            from dodaios.core.config import DATA_DIR

            _store = RitualStore(Path(DATA_DIR) / "rituals.db")
        return _store


def set_store(store: RitualStore | None) -> None:
    """Replace the process store (tests, an embedding host)."""
    global _store
    with _store_lock:
        _store = store
