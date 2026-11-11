"""Duel statistics: one row per ``duel.result`` and the running totals.

A duel reports one result per set: ``won`` or ``lost`` for a finished set, ``unfinished``
for a set left mid-way. Every result lands here, whether it paid XP or not,
so the service record can show sets, wins, K/D, headshots, finishers and the
best streak, per opponent tier and per weapon.

The tables live in the progression database next to the XP ledger
(``<data_dir>/progression.db``), opened on first use (AP-26). ``match_id`` is
the primary key, so a result sent twice is stored once. Parsing clamps what a
client could inflate (more than one kill per two seconds of match time) and
reports every clamp, so the service can log it.
"""

from __future__ import annotations

import json
import math
import sqlite3
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .rules import DUEL_END_REASONS, DUEL_OUTCOMES, DUEL_SECONDS_PER_KILL, duel_tier_key

__all__ = [
    "DuelResult",
    "DuelResultError",
    "DuelStatsStore",
    "DuelWeapon",
    "SCHEMA_VERSION",
    "parse_duel_result",
]

#: Largest count any one stat may carry; anything above is a broken client.
_MAX_COUNT = 1_000_000
#: Longest set the store believes (a day of match time).
_MAX_MATCH_TIME_S = 86_400.0
_MAX_ID = 80
_MAX_WEAPONS = 32
#: Tier keys the bridge's ``duel_stats.by_tier`` may carry.
BRIDGE_TIERS: tuple[str, ...] = ("normal", "hard", "elite", "adaptive")

_STAT_FIELDS: tuple[str, ...] = (
    "kills",
    "deaths",
    "headshots",
    "finishers",
    "melee_kills",
    "shots_fired",
    "shots_hit",
    "damage_dealt",
    "damage_taken",
    "walls_breached",
    "bulwarks_placed",
    "best_streak",
)


class DuelResultError(ValueError):
    """A ``duel.result`` the server cannot read; the bridge answers ``bad_request``."""

    code = "bad_request"


@dataclass(frozen=True, slots=True)
class DuelWeapon:
    weapon_id: str
    kills: int = 0
    headshots: int = 0
    shots_fired: int = 0
    shots_hit: int = 0


@dataclass(frozen=True, slots=True)
class DuelResult:
    match_id: str
    session_id: str
    set_index: int
    mode: str
    ruleset: str
    opponent_kind: str
    tier: str
    adaptive: bool
    started_at: float
    ended_at: float
    match_time_s: float
    end_reason: str
    outcome: str
    score_player: int
    score_opponent: int
    stats: dict[str, int]
    weapons: tuple[DuelWeapon, ...] = ()
    build_version: str = ""
    build_changelist: str = ""
    #: What parsing had to clamp, ``field: sent -> kept``; empty for a plausible result.
    clamped: tuple[str, ...] = field(default=())

    @property
    def tier_key(self) -> str:
        return duel_tier_key(self.opponent_kind, self.tier, self.adaptive)


# ------------------------------------------------------------------ parsing


def _text(value: Any, name: str, *, required: bool = False, limit: int = _MAX_ID) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise DuelResultError(f"{name} must be a string")
    value = value.strip()
    if required and not value:
        raise DuelResultError(f"{name} is required")
    return value[:limit]


def _count(value: Any, name: str) -> int:
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DuelResultError(f"{name} must be a number")
    if isinstance(value, float) and not math.isfinite(value):
        raise DuelResultError(f"{name} must be finite")
    return max(0, min(_MAX_COUNT, int(value)))


def _seconds(value: Any, name: str) -> float:
    if value is None:
        return 0.0
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DuelResultError(f"{name} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise DuelResultError(f"{name} must be finite")
    return number


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise DuelResultError(f"{name} must be an object")
    return value


def parse_duel_result(data: Any) -> DuelResult:
    """Validate a ``duel.result`` payload and clamp its implausible numbers.

    Raises :class:`DuelResultError` for a payload that is not a result at all
    (no ``match_id``, an unknown ``outcome``, a wrong type). Numbers a client
    could inflate are clamped, never refused: the set still counts.
    """
    if not isinstance(data, Mapping):
        raise DuelResultError("duel.result data must be an object")
    clamped: list[str] = []

    def clamp(name: str, value: int, ceiling: int) -> int:
        if value > ceiling:
            clamped.append(f"{name}: {value} -> {ceiling}")
            return ceiling
        return value

    match_id = _text(data.get("match_id"), "match_id", required=True)
    outcome = _text(data.get("outcome"), "outcome", required=True)
    if outcome not in DUEL_OUTCOMES:
        raise DuelResultError(f"unknown outcome {outcome!r}")
    end_reason = _text(data.get("end_reason"), "end_reason") or "unknown"
    if end_reason not in DUEL_END_REASONS:
        end_reason = "unknown"

    match_time = _seconds(data.get("match_time_s"), "match_time_s")
    if match_time < 0:
        clamped.append(f"match_time_s: {match_time} -> 0")
        match_time = 0.0
    if match_time > _MAX_MATCH_TIME_S:
        clamped.append(f"match_time_s: {match_time} -> {_MAX_MATCH_TIME_S}")
        match_time = _MAX_MATCH_TIME_S

    opponent = _mapping(data.get("opponent"), "opponent")
    adaptive = opponent.get("adaptive", False)
    if not isinstance(adaptive, bool):
        raise DuelResultError("opponent.adaptive must be a boolean")

    raw_stats = _mapping(data.get("stats"), "stats")
    stats = {name: _count(raw_stats.get(name), f"stats.{name}") for name in _STAT_FIELDS}
    # One kill per DUEL_SECONDS_PER_KILL of match time is the most a set can hold.
    kill_ceiling = int(match_time // DUEL_SECONDS_PER_KILL)
    stats["kills"] = clamp("kills", stats["kills"], kill_ceiling)
    stats["deaths"] = clamp("deaths", stats["deaths"], kill_ceiling)
    for name in ("headshots", "finishers", "melee_kills", "best_streak"):
        stats[name] = clamp(name, stats[name], stats["kills"])
    stats["shots_hit"] = clamp("shots_hit", stats["shots_hit"], stats["shots_fired"])

    score = _mapping(data.get("score"), "score")
    score_player = clamp("score.player", _count(score.get("player"), "score.player"), kill_ceiling)
    score_opponent = clamp(
        "score.opponent", _count(score.get("opponent"), "score.opponent"), kill_ceiling
    )

    raw_weapons = data.get("weapons")
    if raw_weapons is None:
        raw_weapons = []
    if not isinstance(raw_weapons, list):
        raise DuelResultError("weapons must be a list")
    merged: dict[str, list[int]] = {}
    for entry in raw_weapons[:_MAX_WEAPONS]:
        entry = _mapping(entry, "weapons[]")
        weapon_id = _text(entry.get("weapon_id"), "weapons[].weapon_id", limit=40)
        if not weapon_id:
            continue
        row = merged.setdefault(weapon_id, [0, 0, 0, 0])
        for i, name in enumerate(("kills", "headshots", "shots_fired", "shots_hit")):
            row[i] = min(_MAX_COUNT, row[i] + _count(entry.get(name), f"weapons[].{name}"))
    weapons: list[DuelWeapon] = []
    kills_left = stats["kills"]
    for weapon_id, (kills, headshots, fired, hit) in merged.items():
        kills = clamp(f"weapons.{weapon_id}.kills", kills, kills_left)
        kills_left -= kills
        headshots = clamp(f"weapons.{weapon_id}.headshots", headshots, kills)
        hit = clamp(f"weapons.{weapon_id}.shots_hit", hit, fired)
        weapons.append(DuelWeapon(weapon_id, kills, headshots, fired, hit))

    build = _mapping(data.get("build"), "build")
    set_index = data.get("set_index", 0)
    if isinstance(set_index, bool) or not isinstance(set_index, (int, float)):
        raise DuelResultError("set_index must be a number")
    return DuelResult(
        match_id=match_id,
        session_id=_text(data.get("session_id"), "session_id"),
        set_index=max(0, int(set_index)),
        mode=_text(data.get("mode"), "mode", limit=40),
        ruleset=_text(data.get("ruleset"), "ruleset", limit=40),
        opponent_kind=_text(opponent.get("kind"), "opponent.kind", limit=20) or "bot",
        tier=_text(opponent.get("tier"), "opponent.tier", limit=20),
        adaptive=adaptive,
        started_at=_seconds(data.get("started_at"), "started_at"),
        ended_at=_seconds(data.get("ended_at"), "ended_at"),
        match_time_s=round(match_time, 3),
        end_reason=end_reason,
        outcome=outcome,
        score_player=score_player,
        score_opponent=score_opponent,
        stats=stats,
        weapons=tuple(weapons),
        build_version=_text(build.get("version"), "build.version", limit=40),
        build_changelist=_text(build.get("changelist"), "build.changelist", limit=40),
        clamped=tuple(clamped),
    )


# ------------------------------------------------------------------ store

#: Bumped with every entry of :data:`_MIGRATIONS`.
SCHEMA_VERSION = 1

_MIGRATIONS: tuple[str, ...] = (
    # 1: results, per-weapon lines.
    """
    CREATE TABLE IF NOT EXISTS duel_results (
        match_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL DEFAULT '',
        set_index INTEGER NOT NULL DEFAULT 0,
        mode TEXT NOT NULL DEFAULT '',
        ruleset TEXT NOT NULL DEFAULT '',
        opponent_kind TEXT NOT NULL DEFAULT 'bot',
        tier TEXT NOT NULL DEFAULT '',
        adaptive INTEGER NOT NULL DEFAULT 0,
        tier_key TEXT NOT NULL DEFAULT 'unknown',
        outcome TEXT NOT NULL CHECK (outcome IN ('won', 'lost', 'unfinished')),
        end_reason TEXT NOT NULL DEFAULT 'unknown',
        started_at REAL NOT NULL DEFAULT 0,
        ended_at REAL NOT NULL DEFAULT 0,
        match_time_s REAL NOT NULL DEFAULT 0,
        score_player INTEGER NOT NULL DEFAULT 0,
        score_opponent INTEGER NOT NULL DEFAULT 0,
        kills INTEGER NOT NULL DEFAULT 0,
        deaths INTEGER NOT NULL DEFAULT 0,
        headshots INTEGER NOT NULL DEFAULT 0,
        finishers INTEGER NOT NULL DEFAULT 0,
        melee_kills INTEGER NOT NULL DEFAULT 0,
        shots_fired INTEGER NOT NULL DEFAULT 0,
        shots_hit INTEGER NOT NULL DEFAULT 0,
        damage_dealt INTEGER NOT NULL DEFAULT 0,
        damage_taken INTEGER NOT NULL DEFAULT 0,
        walls_breached INTEGER NOT NULL DEFAULT 0,
        bulwarks_placed INTEGER NOT NULL DEFAULT 0,
        best_streak INTEGER NOT NULL DEFAULT 0,
        build_version TEXT NOT NULL DEFAULT '',
        build_changelist TEXT NOT NULL DEFAULT '',
        clamped TEXT NOT NULL DEFAULT '[]',
        awards TEXT NOT NULL DEFAULT '[]',
        awards_done INTEGER NOT NULL DEFAULT 0,
        recorded_ms INTEGER NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_duel_results_recorded ON duel_results (recorded_ms);
    CREATE TABLE IF NOT EXISTS duel_weapons (
        match_id TEXT NOT NULL REFERENCES duel_results (match_id),
        weapon_id TEXT NOT NULL,
        kills INTEGER NOT NULL DEFAULT 0,
        headshots INTEGER NOT NULL DEFAULT 0,
        shots_fired INTEGER NOT NULL DEFAULT 0,
        shots_hit INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (match_id, weapon_id)
    );
    """,
)

_RESULT_COLUMNS: tuple[str, ...] = (
    "match_id",
    "session_id",
    "set_index",
    "mode",
    "ruleset",
    "opponent_kind",
    "tier",
    "adaptive",
    "tier_key",
    "outcome",
    "end_reason",
    "started_at",
    "ended_at",
    "match_time_s",
    "score_player",
    "score_opponent",
    *_STAT_FIELDS,
    "build_version",
    "build_changelist",
    "clamped",
    "recorded_ms",
)


def _kd(kills: int, deaths: int) -> float:
    return round(kills / deaths, 2) if deaths > 0 else float(kills)


class DuelStatsStore:
    """The duel tables of the progression database. Synchronous; call off the loop."""

    def __init__(self, path: Path, *, clock: Callable[[], int] | None = None) -> None:
        self._path = Path(path)
        self._clock = clock or (lambda: int(time.time() * 1000))
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()

    def _connection(self) -> sqlite3.Connection:
        if self._conn is None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(
                self._path, isolation_level=None, check_same_thread=False, timeout=5.0
            )
            conn.row_factory = sqlite3.Row
            # The XP ledger may be creating the same file on another thread; a
            # journal-mode switch then reports "locked" without waiting.
            for attempt in range(50):
                try:
                    conn.execute("PRAGMA journal_mode=WAL")
                    self._migrate(conn)
                    break
                except sqlite3.OperationalError as exc:
                    if "locked" not in str(exc) or attempt == 49:
                        conn.close()
                        raise
                    time.sleep(0.05)
            self._conn = conn
        return self._conn

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        """Apply every migration newer than the stored version, each in its own transaction.

        The version lives in its own table, because ``PRAGMA user_version``
        belongs to the whole database and the XP ledger shares it.
        """
        conn.execute(
            "CREATE TABLE IF NOT EXISTS duel_schema (id INTEGER PRIMARY KEY CHECK (id = 1),"
            " version INTEGER NOT NULL)"
        )
        row = conn.execute("SELECT version FROM duel_schema WHERE id = 1").fetchone()
        current = int(row[0]) if row else 0
        for version, script in enumerate(_MIGRATIONS, start=1):
            if version <= current:
                continue
            conn.execute("BEGIN IMMEDIATE")
            try:
                for statement in script.split(";"):
                    if statement.strip():
                        conn.execute(statement)
                conn.execute(
                    "INSERT INTO duel_schema (id, version) VALUES (1, ?)"
                    " ON CONFLICT(id) DO UPDATE SET version = excluded.version",
                    (version,),
                )
            except Exception:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")

    def schema_version(self) -> int:
        with self._lock:
            row = (
                self._connection()
                .execute("SELECT version FROM duel_schema WHERE id = 1")
                .fetchone()
            )
        return int(row[0]) if row else 0

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    # ------------------------------------------------------------ writes

    def insert(self, result: DuelResult) -> bool:
        """Store ``result``; ``False`` when its ``match_id`` is already stored."""
        values: dict[str, Any] = {
            "match_id": result.match_id,
            "session_id": result.session_id,
            "set_index": result.set_index,
            "mode": result.mode,
            "ruleset": result.ruleset,
            "opponent_kind": result.opponent_kind,
            "tier": result.tier,
            "adaptive": int(result.adaptive),
            "tier_key": result.tier_key,
            "outcome": result.outcome,
            "end_reason": result.end_reason,
            "started_at": result.started_at,
            "ended_at": result.ended_at,
            "match_time_s": result.match_time_s,
            "score_player": result.score_player,
            "score_opponent": result.score_opponent,
            **{name: result.stats[name] for name in _STAT_FIELDS},
            "build_version": result.build_version,
            "build_changelist": result.build_changelist,
            "clamped": json.dumps(list(result.clamped)),
            "recorded_ms": self._clock(),
        }
        columns = ", ".join(_RESULT_COLUMNS)
        marks = ", ".join("?" for _ in _RESULT_COLUMNS)
        with self._lock:
            conn = self._connection()
            conn.execute("BEGIN IMMEDIATE")
            try:
                cur = conn.execute(
                    f"INSERT OR IGNORE INTO duel_results ({columns}) VALUES ({marks})",  # noqa: S608 - constant columns
                    tuple(values[c] for c in _RESULT_COLUMNS),
                )
                inserted = cur.rowcount == 1
                if inserted:
                    conn.executemany(
                        "INSERT INTO duel_weapons"
                        " (match_id, weapon_id, kills, headshots, shots_fired, shots_hit)"
                        " VALUES (?, ?, ?, ?, ?, ?)",
                        [
                            (
                                result.match_id,
                                w.weapon_id,
                                w.kills,
                                w.headshots,
                                w.shots_fired,
                                w.shots_hit,
                            )
                            for w in result.weapons
                        ],
                    )
            except Exception:
                conn.execute("ROLLBACK")
                raise
            conn.execute("COMMIT")
        return inserted

    def finish(self, match_id: str, awards: list[dict[str, Any]]) -> None:
        """Mark the result's awards as paid and keep what they were."""
        with self._lock:
            self._connection().execute(
                "UPDATE duel_results SET awards = ?, awards_done = 1 WHERE match_id = ?",
                (json.dumps(awards), match_id),
            )

    def paid_awards(self, subject_id: str, ref: str) -> list[dict[str, Any]]:
        """Every award the XP ledger holds for ``ref``, oldest first.

        The ledger (``progression_awards``, store.py) lives in the same file. A
        resend after a crash between paying and ``finish`` pays nothing new (the
        ledger refuses a repeated ref), so its summaries come from here.
        """
        with self._lock:
            rows = (
                self._connection()
                .execute(
                    "SELECT source, xp, seq FROM progression_awards"
                    " WHERE subject_id = ? AND ref = ? ORDER BY seq",
                    (subject_id, ref),
                )
                .fetchall()
            )
        return [{"xp_source": r[0], "xp": int(r[1]), "seq": int(r[2])} for r in rows]

    # ------------------------------------------------------------ reads

    def get(self, match_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = (
                self._connection()
                .execute("SELECT * FROM duel_results WHERE match_id = ?", (match_id,))
                .fetchone()
            )
        return self._row(row) if row is not None else None

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["adaptive"] = bool(data["adaptive"])
        data["awards_done"] = bool(data["awards_done"])
        data["awards"] = json.loads(data["awards"] or "[]")
        data["clamped"] = json.loads(data["clamped"] or "[]")
        return data

    def count(self) -> int:
        with self._lock:
            row = self._connection().execute("SELECT COUNT(*) FROM duel_results").fetchone()
        return int(row[0]) if row else 0

    def totals(self) -> dict[str, Any]:
        """Running totals over every stored result, per tier and per weapon."""
        aggregate = """
            COUNT(*) AS matches,
            COALESCE(SUM(outcome = 'won'), 0) AS wins,
            COALESCE(SUM(outcome = 'lost'), 0) AS losses,
            COALESCE(SUM(outcome = 'unfinished'), 0) AS unfinished,
            COALESCE(SUM(kills), 0) AS kills,
            COALESCE(SUM(deaths), 0) AS deaths,
            COALESCE(SUM(headshots), 0) AS headshots,
            COALESCE(SUM(finishers), 0) AS finishers,
            COALESCE(SUM(melee_kills), 0) AS melee_kills,
            COALESCE(MAX(best_streak), 0) AS best_streak,
            COALESCE(SUM(match_time_s), 0) AS match_time_s
        """
        with self._lock:
            conn = self._connection()
            total = conn.execute(f"SELECT {aggregate} FROM duel_results").fetchone()  # noqa: S608 - constant SQL
            tiers = conn.execute(
                f"SELECT tier_key, {aggregate} FROM duel_results GROUP BY tier_key"  # noqa: S608 - constant SQL
                " ORDER BY tier_key"
            ).fetchall()
            weapons = conn.execute(
                "SELECT weapon_id, SUM(kills) AS kills, SUM(headshots) AS headshots,"
                " SUM(shots_fired) AS shots_fired, SUM(shots_hit) AS shots_hit"
                " FROM duel_weapons GROUP BY weapon_id ORDER BY weapon_id"
            ).fetchall()

        def block(row: sqlite3.Row) -> dict[str, Any]:
            data = {
                key: int(row[key])
                for key in (
                    "matches",
                    "wins",
                    "losses",
                    "unfinished",
                    "kills",
                    "deaths",
                    "headshots",
                    "finishers",
                    "melee_kills",
                    "best_streak",
                )
            }
            data["kd"] = _kd(data["kills"], data["deaths"])
            data["match_time_s"] = round(float(row["match_time_s"]), 1)
            return data

        result = block(total)
        result["by_tier"] = {row["tier_key"]: block(row) for row in tiers}
        result["by_weapon"] = {
            row["weapon_id"]: {
                "kills": int(row["kills"]),
                "headshots": int(row["headshots"]),
                "shots_fired": int(row["shots_fired"]),
                "shots_hit": int(row["shots_hit"]),
                "accuracy": round(int(row["shots_hit"]) / int(row["shots_fired"]), 3)
                if int(row["shots_fired"]) > 0
                else 0.0,
            }
            for row in weapons
        }
        return result

    def bridge_totals(self) -> dict[str, Any]:
        """The totals as ``verse.bridge/1`` carries them (``duel_stats`` in the golden schema).

        The bridge shape is strict: the core counts, and per bot tier only
        wins and losses; sets against a player or an unknown tier stay out of
        ``by_tier`` but count in the totals.
        """
        full = self.totals()
        keys = (
            "matches",
            "wins",
            "losses",
            "unfinished",
            "kills",
            "deaths",
            "headshots",
            "finishers",
            "best_streak",
        )
        return {
            **{key: full[key] for key in keys},
            "by_tier": {
                tier: {"wins": row["wins"], "losses": row["losses"]}
                for tier, row in full["by_tier"].items()
                if tier in BRIDGE_TIERS
            },
        }

    def recent(self, *, limit: int = 20) -> list[dict[str, Any]]:
        """The newest results first, each with its awards and weapon lines."""
        limit = max(1, min(100, int(limit)))
        with self._lock:
            conn = self._connection()
            rows = conn.execute(
                "SELECT * FROM duel_results ORDER BY recorded_ms DESC, rowid DESC LIMIT ?",
                (limit,),
            ).fetchall()
            ids = [row["match_id"] for row in rows]
            lines: dict[str, list[dict[str, Any]]] = {i: [] for i in ids}
            if ids:
                marks = ", ".join("?" for _ in ids)
                for line in conn.execute(
                    f"SELECT * FROM duel_weapons WHERE match_id IN ({marks})"  # noqa: S608 - placeholders only
                    " ORDER BY kills DESC, weapon_id",
                    ids,
                ).fetchall():
                    entry = dict(line)
                    lines[entry.pop("match_id")].append(entry)
        out = []
        for row in rows:
            data = self._row(row)
            out.append(
                {
                    "match_id": data["match_id"],
                    "session_id": data["session_id"],
                    "set_index": data["set_index"],
                    "mode": data["mode"],
                    "outcome": data["outcome"],
                    "end_reason": data["end_reason"],
                    "opponent": {
                        "kind": data["opponent_kind"],
                        "tier": data["tier"],
                        "adaptive": data["adaptive"],
                    },
                    "tier_key": data["tier_key"],
                    "match_time_s": data["match_time_s"],
                    "score": {"player": data["score_player"], "opponent": data["score_opponent"]},
                    "stats": {name: data[name] for name in _STAT_FIELDS},
                    "kd": _kd(data["kills"], data["deaths"]),
                    "weapons": lines.get(data["match_id"], []),
                    "xp": sum(int(a.get("xp", 0)) for a in data["awards"]),
                    "awards": data["awards"],
                    "clamped": bool(data["clamped"]),
                    "recorded_ms": data["recorded_ms"],
                }
            )
        return out
