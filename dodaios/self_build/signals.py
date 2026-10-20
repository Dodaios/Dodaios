"""``self_build_signals.db``: what the miner remembers between turns.

The person's own requests (voice and typed, never tool output, web pages or
other agents' words), grouped into needs by their content words; the decide
step's verdicts, so a need answered with "build nothing" is not asked about
again for a while; the lessons of builds that failed their proof; the build
specs the decide step wrote; and which artefact belongs to which build, so a
skill run or a routine run can be counted for the right trial.

Kept apart from ``self_build.db`` (the build ledger) on purpose: the ledger
is the shared contract, this is the miner's private working memory. Turns
older than :data:`RETAIN_DAYS` are dropped.

Plain ``sqlite3`` behind one lock, like the ledger; async callers wrap calls
in ``asyncio.to_thread``.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from .ledger import now_ms

DB_NAME: Final[str] = "self_build_signals.db"
#: Turns are kept this long; every threshold looks at most four weeks back.
RETAIN_DAYS: Final[int] = 60
_DAY_MS: Final[int] = 86_400_000

_SCHEMA: Final[str] = """
CREATE TABLE IF NOT EXISTS turns (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_ms        INTEGER NOT NULL,
    day          INTEGER NOT NULL,
    minute       INTEGER NOT NULL,
    weekday      INTEGER NOT NULL,
    channel      TEXT NOT NULL,
    conversation TEXT NOT NULL,
    agent_id     TEXT NOT NULL DEFAULT '',
    text         TEXT NOT NULL,
    stems        TEXT NOT NULL,
    tools_json   TEXT NOT NULL DEFAULT '[]',
    failed       INTEGER NOT NULL DEFAULT 0,
    correction   INTEGER NOT NULL DEFAULT 0,
    cluster      INTEGER NOT NULL DEFAULT 0,
    lang         TEXT NOT NULL DEFAULT '',
    ref          TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS turns_cluster ON turns(cluster);
CREATE INDEX IF NOT EXISTS turns_ts ON turns(ts_ms);
CREATE INDEX IF NOT EXISTS turns_conversation ON turns(conversation, ts_ms);
CREATE TABLE IF NOT EXISTS clusters (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    signature TEXT NOT NULL UNIQUE,
    stems     TEXT NOT NULL,
    size      INTEGER NOT NULL DEFAULT 0,
    first_ms  INTEGER NOT NULL,
    last_ms   INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS decisions (
    signature   TEXT PRIMARY KEY,
    ts_ms       INTEGER NOT NULL,
    verdict     TEXT NOT NULL,
    occurrences INTEGER NOT NULL DEFAULT 0,
    note        TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS lessons (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    signature TEXT NOT NULL,
    kind      TEXT NOT NULL,
    ts_ms     INTEGER NOT NULL,
    reason    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS lessons_signature ON lessons(signature);
CREATE TABLE IF NOT EXISTS specs (
    build_id  TEXT PRIMARY KEY,
    signature TEXT NOT NULL,
    kind      TEXT NOT NULL,
    spec_json TEXT NOT NULL,
    ts_ms     INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS artefacts (
    key      TEXT PRIMARY KEY,
    build_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_TURN_COLUMNS: Final[str] = (
    "id, ts_ms, day, minute, weekday, channel, conversation, agent_id, text, stems, "
    "tools_json, failed, correction, cluster, lang, ref"
)


@dataclass(frozen=True, slots=True)
class TurnRow:
    """One request of the person, as the miner stored it."""

    id: int
    ts_ms: int
    #: Local calendar day (``date.toordinal()``), minute of the day and weekday
    #: (Monday = 0): the routine thresholds count in the person's own clock.
    day: int
    minute: int
    weekday: int
    channel: str
    conversation: str
    agent_id: str
    text: str
    stems: frozenset[str]
    tools: tuple[str, ...]
    failed: bool
    correction: bool
    cluster: int
    lang: str
    ref: str

    def evidence(self) -> str:
        """The ledger evidence line: where and when, and the person's words."""
        zone = person_zone()
        moment = (
            datetime.fromtimestamp(self.ts_ms / 1000, tz=zone)
            if zone is not None
            else datetime.fromtimestamp(self.ts_ms / 1000).astimezone()
        )
        stamp = moment.strftime("%Y-%m-%d %H:%M")
        quote = " ".join(self.text.split())[:160]
        return f"turn:{self.id} {self.channel} {stamp}: {quote}"


def _turn(row: tuple[Any, ...]) -> TurnRow:
    return TurnRow(
        id=int(row[0]),
        ts_ms=int(row[1]),
        day=int(row[2]),
        minute=int(row[3]),
        weekday=int(row[4]),
        channel=str(row[5]),
        conversation=str(row[6]),
        agent_id=str(row[7]),
        text=str(row[8]),
        stems=frozenset(str(row[9]).split()),
        tools=tuple(json.loads(row[10] or "[]")),
        failed=bool(row[11]),
        correction=bool(row[12]),
        cluster=int(row[13]),
        lang=str(row[14]),
        ref=str(row[15]),
    )


@dataclass(frozen=True, slots=True)
class Cluster:
    id: int
    signature: str
    stems: frozenset[str]
    size: int
    first_ms: int
    last_ms: int


def _cluster(row: tuple[Any, ...]) -> Cluster:
    return Cluster(
        id=int(row[0]),
        signature=str(row[1]),
        stems=frozenset(str(row[2]).split()),
        size=int(row[3]),
        first_ms=int(row[4]),
        last_ms=int(row[5]),
    )


def person_zone() -> Any:
    """The person's own time zone: the one their UI reported, else this computer's.

    Routines run on the person's wall clock, so habits are counted on it too
    (:mod:`.clock`); ``None`` only when no zone can be named at all.
    """
    from .clock import person_zone as zone_of_person

    return zone_of_person()


#: Minute and weekday of a turn made while no zone could be named.
UNKNOWN_CLOCK: Final[int] = -1


def local_clock(ts_ms: int) -> tuple[int, int, int]:
    """``(day ordinal, minute of day, weekday)`` on the person's wall clock.

    Without any zone (none reported and none readable from this computer),
    minute and weekday are :data:`UNKNOWN_CLOCK` and no habit is counted on
    them. The day still counts distinct days.
    """
    zone = person_zone()
    if zone is None:
        moment = datetime.fromtimestamp(ts_ms / 1000).astimezone()
        return moment.date().toordinal(), UNKNOWN_CLOCK, UNKNOWN_CLOCK
    moment = datetime.fromtimestamp(ts_ms / 1000, tz=zone)
    return moment.date().toordinal(), moment.hour * 60 + moment.minute, moment.weekday()


class SignalStore:
    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._lock = threading.RLock()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False, timeout=5.0)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    @property
    def path(self) -> Path:
        return self._path

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------ turns

    def add_turn(
        self,
        *,
        ts_ms: int,
        channel: str,
        conversation: str,
        text: str,
        stems: Iterable[str],
        cluster: int,
        tools: Iterable[str] = (),
        failed: bool = False,
        correction: bool = False,
        agent_id: str = "",
        lang: str = "",
        ref: str = "",
    ) -> TurnRow:
        day, minute, weekday = local_clock(ts_ms)
        with self._lock:
            cursor = self._conn.execute(
                "INSERT INTO turns (ts_ms, day, minute, weekday, channel, conversation, agent_id,"
                " text, stems, tools_json, failed, correction, cluster, lang, ref)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    ts_ms,
                    day,
                    minute,
                    weekday,
                    channel,
                    conversation,
                    agent_id,
                    text[:2000],
                    " ".join(sorted(set(stems))),
                    json.dumps(list(dict.fromkeys(tools))[:24]),
                    int(failed),
                    int(correction),
                    cluster,
                    lang,
                    ref[:200],
                ),
            )
            if cluster:
                self._conn.execute(
                    "UPDATE clusters SET size = size + 1, last_ms = MAX(last_ms, ?) WHERE id = ?",
                    (ts_ms, cluster),
                )
            self._conn.commit()
            row = self._conn.execute(
                f"SELECT {_TURN_COLUMNS} FROM turns WHERE id = ?",  # noqa: S608 — fixed identifiers, bound values
                (cursor.lastrowid,),
            ).fetchone()
        return _turn(row)

    def turns_of(self, cluster: int, *, since_ms: int = 0, limit: int = 500) -> list[TurnRow]:
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {_TURN_COLUMNS} FROM turns WHERE cluster = ? AND ts_ms >= ?"  # noqa: S608 — fixed identifiers, bound values
                " ORDER BY ts_ms LIMIT ?",
                (cluster, since_ms, limit),
            ).fetchall()
        return [_turn(r) for r in rows]

    def turns_in(self, conversation: str, *, since_ms: int, until_ms: int) -> list[TurnRow]:
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {_TURN_COLUMNS} FROM turns WHERE conversation = ?"  # noqa: S608 — fixed identifiers, bound values
                " AND ts_ms >= ? AND ts_ms <= ? ORDER BY ts_ms",
                (conversation, since_ms, until_ms),
            ).fetchall()
        return [_turn(r) for r in rows]

    def recent_turns(self, *, since_ms: int, limit: int = 2000) -> list[TurnRow]:
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {_TURN_COLUMNS} FROM turns WHERE ts_ms >= ?"  # noqa: S608 — fixed identifiers, bound values
                " ORDER BY ts_ms DESC LIMIT ?",
                (since_ms, limit),
            ).fetchall()
        return [_turn(r) for r in rows]

    def turns_by_id(self, ids: Iterable[int]) -> list[TurnRow]:
        values = [int(i) for i in ids]
        if not values:
            return []
        with self._lock:
            rows = self._conn.execute(
                f"SELECT {_TURN_COLUMNS} FROM turns WHERE id IN"  # noqa: S608 — fixed identifiers, bound values
                f" ({','.join('?' * len(values))}) ORDER BY ts_ms",
                values,
            ).fetchall()
        return [_turn(r) for r in rows]

    def prune(self, *, now: int | None = None) -> int:
        cutoff = (now if now is not None else now_ms()) - RETAIN_DAYS * _DAY_MS
        with self._lock:
            cursor = self._conn.execute("DELETE FROM turns WHERE ts_ms < ?", (cutoff,))
            self._conn.execute(
                "DELETE FROM clusters WHERE last_ms < ? AND id NOT IN (SELECT cluster FROM turns)",
                (cutoff,),
            )
            self._conn.commit()
            return int(cursor.rowcount or 0)

    def fill_clocks(self) -> int:
        """Give turns stored without a clock one, now that a zone is known."""
        if person_zone() is None:
            return 0
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, ts_ms FROM turns WHERE minute = ? LIMIT 5000", (UNKNOWN_CLOCK,)
            ).fetchall()
            for turn_id, ts_ms in rows:
                day, minute, weekday = local_clock(int(ts_ms))
                self._conn.execute(
                    "UPDATE turns SET day = ?, minute = ?, weekday = ? WHERE id = ?",
                    (day, minute, weekday, int(turn_id)),
                )
            self._conn.commit()
        return len(rows)

    # ------------------------------------------------------------ clusters

    def clusters_since(self, since_ms: int) -> list[Cluster]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, signature, stems, size, first_ms, last_ms FROM clusters"
                " WHERE last_ms >= ? ORDER BY last_ms DESC LIMIT 5000",
                (since_ms,),
            ).fetchall()
        return [_cluster(r) for r in rows]

    def cluster(self, cluster_id: int) -> Cluster | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, signature, stems, size, first_ms, last_ms FROM clusters WHERE id = ?",
                (cluster_id,),
            ).fetchone()
        return _cluster(row) if row is not None else None

    def new_cluster(self, signature: str, stems: Iterable[str], ts_ms: int) -> Cluster:
        joined = " ".join(sorted(set(stems)))
        with self._lock:
            self._conn.execute(
                "INSERT OR IGNORE INTO clusters (signature, stems, size, first_ms, last_ms)"
                " VALUES (?, ?, 0, ?, ?)",
                (signature, joined, ts_ms, ts_ms),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT id FROM clusters WHERE signature = ?", (signature,)
            ).fetchone()
        found = self.cluster(int(row[0]))
        assert found is not None
        return found

    # ------------------------------------------------------------ verdicts and lessons

    def decision(self, signature: str) -> tuple[int, str, int] | None:
        """``(ts_ms, verdict, occurrences at the time)`` of the last decide verdict."""
        with self._lock:
            row = self._conn.execute(
                "SELECT ts_ms, verdict, occurrences FROM decisions WHERE signature = ?",
                (signature,),
            ).fetchone()
        return (int(row[0]), str(row[1]), int(row[2])) if row else None

    def record_decision(
        self,
        signature: str,
        verdict: str,
        occurrences: int,
        note: str = "",
        *,
        ts_ms: int | None = None,
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO decisions (signature, ts_ms, verdict, occurrences, note)"
                " VALUES (?, ?, ?, ?, ?) ON CONFLICT(signature) DO UPDATE SET"
                " ts_ms = excluded.ts_ms, verdict = excluded.verdict,"
                " occurrences = excluded.occurrences, note = excluded.note",
                (
                    signature,
                    ts_ms if ts_ms is not None else now_ms(),
                    verdict,
                    occurrences,
                    note[:500],
                ),
            )
            self._conn.commit()

    def lessons(self, signature: str) -> list[tuple[str, str]]:
        """``(kind, reason)`` of every failed proof for ``signature``."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT kind, reason FROM lessons WHERE signature = ? ORDER BY ts_ms",
                (signature,),
            ).fetchall()
        return [(str(r[0]), str(r[1])) for r in rows]

    def add_lesson(self, signature: str, kind: str, reason: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO lessons (signature, kind, ts_ms, reason) VALUES (?, ?, ?, ?)",
                (signature, kind, now_ms(), reason[:500]),
            )
            self._conn.commit()

    # ------------------------------------------------------------ specs and artefacts

    def put_spec(self, build_id: str, signature: str, kind: str, spec: dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO specs (build_id, signature, kind, spec_json, ts_ms)"
                " VALUES (?, ?, ?, ?, ?)"
                " ON CONFLICT(build_id) DO UPDATE SET spec_json = excluded.spec_json",
                (build_id, signature, kind, json.dumps(spec, ensure_ascii=False), now_ms()),
            )
            self._conn.commit()

    def spec(self, build_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT spec_json FROM specs WHERE build_id = ?", (build_id,)
            ).fetchone()
        if row is None:
            return None
        value = json.loads(row[0] or "{}")
        return value if isinstance(value, dict) else None

    def bind_artefact(self, key: str, build_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO artefacts (key, build_id) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET build_id = excluded.build_id",
                (key, build_id),
            )
            self._conn.commit()

    def build_for(self, key: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT build_id FROM artefacts WHERE key = ?", (key,)
            ).fetchone()
        return str(row[0]) if row else None

    def unbind_build(self, build_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM artefacts WHERE build_id = ?", (build_id,))
            self._conn.commit()

    # ------------------------------------------------------------ meta

    def take_daily(self, key: str, limit: int, *, now: int | None = None) -> bool:
        """Take one unit of a per-day budget; ``False`` when today's is spent."""
        today = str((now if now is not None else now_ms()) // _DAY_MS)
        with self._lock:
            if self.get_meta(f"{key}:day") != today:
                self.set_meta(f"{key}:day", today)
                self.set_meta(f"{key}:used", "0")
            used = int(self.get_meta(f"{key}:used", "0") or 0)
            if used >= limit:
                return False
            self.set_meta(f"{key}:used", str(used + 1))
            return True

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
