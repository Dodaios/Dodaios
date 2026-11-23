"""``bench.db``: the tasks the assistant measures itself with, and every result.

``tasks``    one row per task. A task is never deleted; one that no longer
             applies is retired. Its split is stored with it and never
             changes (it is a hash of the task's group).
``results``  one row per run of a task under one arm. Append-only: the app
             cannot edit what it measured about itself (a trigger refuses
             UPDATE and DELETE).
``series``   the learned advantage over time: per night, domain and split, the
             assistant as it is against the assistant as it ships. Append-only.
``nights``   what each night did: practised, tried, kept, taken back. Append-only.
``meta``     small state of the kernel itself (how much of the error budget a
             split has used).

Learners never get this store. They get :class:`PracticeView`, which answers
with practice tasks only, so a task the assistant is graded on cannot reach
what proposes changes.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any, Final

from dodaios.rsi.storage import Db, Schema, open_db

from .model import LEARNER_SPLITS, Domain, Result, Source, Split, Task

__all__ = ["DB_NAME", "BenchStore", "PracticeView"]

DB_NAME: Final = "bench.db"
SCHEMA: Final = Schema(
    "bench.db",
    (
        """
        CREATE TABLE IF NOT EXISTS tasks (
            id          TEXT PRIMARY KEY,
            domain      TEXT NOT NULL,
            source      TEXT NOT NULL,
            grp         TEXT NOT NULL,
            split       TEXT NOT NULL,
            payload     TEXT NOT NULL,
            check_json  TEXT NOT NULL,
            digest      TEXT NOT NULL,
            created_ms  INTEGER NOT NULL,
            retired_ms  INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS tasks_domain ON tasks(domain, split, retired_ms);
        CREATE TABLE IF NOT EXISTS results (
            seq          INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id      TEXT NOT NULL,
            task_digest  TEXT NOT NULL,
            arm          TEXT NOT NULL,
            score        REAL NOT NULL,
            cost_usd     REAL NOT NULL DEFAULT 0,
            tokens       INTEGER NOT NULL DEFAULT 0,
            wall_ms      INTEGER NOT NULL DEFAULT 0,
            seat         TEXT NOT NULL DEFAULT '',
            void         TEXT NOT NULL DEFAULT '',
            detail       TEXT NOT NULL DEFAULT '',
            ts_ms        INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS results_task ON results(task_id, arm, task_digest);
        CREATE TRIGGER IF NOT EXISTS results_no_update BEFORE UPDATE ON results
        BEGIN SELECT RAISE(ABORT, 'benchmark results are append-only'); END;
        CREATE TRIGGER IF NOT EXISTS results_no_delete BEFORE DELETE ON results
        BEGIN SELECT RAISE(ABORT, 'benchmark results are append-only'); END;
        """,
        """
        CREATE TABLE meta (
            key    TEXT PRIMARY KEY,
            value  TEXT NOT NULL
        );
        CREATE TABLE series (
            seq             INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_ms           INTEGER NOT NULL,
            app             TEXT NOT NULL,
            domain          TEXT NOT NULL,
            split           TEXT NOT NULL,
            source          TEXT NOT NULL,
            now_score       REAL NOT NULL,
            factory_score   REAL NOT NULL,
            diff            REAL NOT NULL,
            low             REAL NOT NULL,
            high            REAL NOT NULL,
            n               INTEGER NOT NULL,
            now_tokens      REAL NOT NULL DEFAULT 0,
            factory_tokens  REAL NOT NULL DEFAULT 0,
            arm_now         TEXT NOT NULL DEFAULT '',
            arm_factory     TEXT NOT NULL DEFAULT ''
        );
        CREATE INDEX series_domain ON series(domain, split, ts_ms);
        CREATE TABLE nights (
            seq    INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_ms  INTEGER NOT NULL,
            app    TEXT NOT NULL,
            body   TEXT NOT NULL
        );
        CREATE TRIGGER series_no_update BEFORE UPDATE ON series
        BEGIN SELECT RAISE(ABORT, 'the measured series is append-only'); END;
        CREATE TRIGGER series_no_delete BEFORE DELETE ON series
        BEGIN SELECT RAISE(ABORT, 'the measured series is append-only'); END;
        CREATE TRIGGER nights_no_update BEFORE UPDATE ON nights
        BEGIN SELECT RAISE(ABORT, 'the record of a night is append-only'); END;
        CREATE TRIGGER nights_no_delete BEFORE DELETE ON nights
        BEGIN SELECT RAISE(ABORT, 'the record of a night is append-only'); END;
        """,
    ),
)


def _now() -> int:
    return int(time.time() * 1000)


def _dump(value: Any) -> str:
    return json.dumps(dict(value), sort_keys=True, ensure_ascii=False, default=str)


class BenchStore:
    """The kernel's handle on ``bench.db``."""

    def __init__(self, path: Path | str) -> None:
        self._db: Db = open_db(path, SCHEMA)

    @property
    def readonly(self) -> bool:
        return self._db.readonly

    def close(self) -> None:
        self._db.close()

    # --------------------------------------------------------------- tasks

    def put_tasks(self, tasks: Iterable[Task]) -> int:
        """Add tasks, and take over corrected content of known ones. Returns how many are new.

        A known task keeps its split and its creation time whatever the new
        content says: nothing moves a task between splits.
        """
        added = 0
        with self._db.lock:
            for task in tasks:
                known = self._db.conn.execute(
                    "SELECT digest FROM tasks WHERE id = ?", (task.id,)
                ).fetchone()
                if known is None:
                    self._db.conn.execute(
                        "INSERT INTO tasks (id, domain, source, grp, split, payload, check_json,"
                        " digest, created_ms) VALUES (?,?,?,?,?,?,?,?,?)",
                        (
                            task.id,
                            task.domain.value,
                            task.source.value,
                            task.group,
                            task.split.value,
                            _dump(task.payload),
                            _dump(task.check),
                            task.digest,
                            task.created_ms or _now(),
                        ),
                    )
                    added += 1
                elif known["digest"] != task.digest:
                    self._db.conn.execute(
                        "UPDATE tasks SET payload = ?, check_json = ?, digest = ?, retired_ms = 0"
                        " WHERE id = ?",
                        (_dump(task.payload), _dump(task.check), task.digest, task.id),
                    )
            self._db.conn.commit()
        return added

    def retire(self, task_ids: Iterable[str]) -> None:
        """Take tasks out of use (their memory was forgotten, their repository is gone)."""
        with self._db.lock:
            self._db.conn.executemany(
                "UPDATE tasks SET retired_ms = ? WHERE id = ? AND retired_ms = 0",
                [(_now(), task_id) for task_id in task_ids],
            )
            self._db.conn.commit()

    def scrub(self, task_ids: Iterable[str]) -> None:
        """Retire tasks and erase what they say (the memory they were about was forgotten).

        The row stays, so results that name the task still add up; its text is gone.
        """
        with self._db.lock:
            self._db.conn.executemany(
                "UPDATE tasks SET retired_ms = ?, payload = '{}', check_json = '{}', digest = ''"
                " WHERE id = ?",
                [(_now(), task_id) for task_id in task_ids],
            )
            self._db.conn.commit()

    def tasks(
        self,
        domain: Domain,
        *,
        splits: Sequence[Split] = (),
        source: Source | None = None,
    ) -> list[Task]:
        """Tasks in use, in a stable order (by id)."""
        sql = "SELECT * FROM tasks WHERE domain = ? AND retired_ms = 0"
        args: list[Any] = [domain.value]
        if splits:
            sql += f" AND split IN ({','.join('?' for _ in splits)})"  # noqa: S608
            args += [s.value for s in splits]
        if source is not None:
            sql += " AND source = ?"
            args.append(source.value)
        with self._db.lock:
            rows = self._db.conn.execute(sql + " ORDER BY id", args).fetchall()
        return [
            Task(
                id=row["id"],
                domain=Domain(row["domain"]),
                source=Source(row["source"]),
                group=row["grp"],
                payload=json.loads(row["payload"]),
                check=json.loads(row["check_json"]),
                created_ms=row["created_ms"],
            )
            for row in rows
        ]

    def groups(self, domain: Domain, split: Split, sources: Sequence[Source] = ()) -> int:
        """How many groups of tasks in use a split holds (the unit the error budget counts)."""
        sql = "SELECT COUNT(DISTINCT grp) FROM tasks WHERE domain=? AND split=? AND retired_ms=0"
        args: list[Any] = [domain.value, split.value]
        if sources:
            sql += f" AND source IN ({','.join('?' for _ in sources)})"  # noqa: S608
            args += [s.value for s in sources]
        with self._db.lock:
            return int(self._db.conn.execute(sql, args).fetchone()[0])

    def counts(self) -> dict[str, dict[str, int]]:
        """Tasks in use per domain and split."""
        with self._db.lock:
            rows = self._db.conn.execute(
                "SELECT domain, split, COUNT(*) AS n FROM tasks WHERE retired_ms = 0"
                " GROUP BY domain, split"
            ).fetchall()
        out: dict[str, dict[str, int]] = {}
        for row in rows:
            out.setdefault(row["domain"], {})[row["split"]] = int(row["n"])
        return out

    # ------------------------------------------------------------- results

    def add_results(self, results: Iterable[Result]) -> None:
        with self._db.lock:
            self._db.conn.executemany(
                "INSERT INTO results (task_id, task_digest, arm, score, cost_usd, tokens,"
                " wall_ms, seat, void, detail, ts_ms) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        r.task_id,
                        r.task_digest,
                        r.arm,
                        float(r.score),
                        float(r.cost_usd),
                        int(r.tokens),
                        int(r.wall_ms),
                        r.seat,
                        r.void,
                        r.detail[:500],
                        r.ts_ms or _now(),
                    )
                    for r in results
                ],
            )
            self._db.conn.commit()

    def results(self, arm: str, *, task_ids: Sequence[str] = ()) -> list[Result]:
        """Every stored result of an arm, oldest first."""
        sql, args = "SELECT * FROM results WHERE arm = ?", [arm]
        if task_ids:
            sql += f" AND task_id IN ({','.join('?' for _ in task_ids)})"  # noqa: S608
            args += list(task_ids)
        with self._db.lock:
            rows = self._db.conn.execute(sql + " ORDER BY seq", args).fetchall()
        return [
            Result(
                task_id=row["task_id"],
                task_digest=row["task_digest"],
                arm=row["arm"],
                score=row["score"],
                cost_usd=row["cost_usd"],
                tokens=row["tokens"],
                wall_ms=row["wall_ms"],
                seat=row["seat"],
                void=row["void"],
                detail=row["detail"],
                ts_ms=row["ts_ms"],
            )
            for row in rows
        ]


    # ---------------------------------------------------- the kernel's own state

    def get_meta(self, key: str) -> dict[str, Any]:
        with self._db.lock:
            row = self._db.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return dict(json.loads(row["value"])) if row is not None else {}

    def set_meta(self, key: str, value: dict[str, Any]) -> None:
        with self._db.lock:
            self._db.conn.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, json.dumps(value, sort_keys=True)),
            )
            self._db.conn.commit()

    def add_series(self, rows: Iterable[dict[str, Any]]) -> None:
        """Append measured points of the learned advantage."""
        with self._db.lock:
            self._db.conn.executemany(
                "INSERT INTO series (ts_ms, app, domain, split, source, now_score, factory_score,"
                " diff, low, high, n, now_tokens, factory_tokens, arm_now, arm_factory)"
                " VALUES (:ts_ms, :app, :domain, :split, :source, :now_score, :factory_score,"
                " :diff, :low, :high, :n, :now_tokens, :factory_tokens, :arm_now, :arm_factory)",
                list(rows),
            )
            self._db.conn.commit()

    def series(
        self, *, domain: str = "", split: str = "", limit: int = 2000
    ) -> list[dict[str, Any]]:
        """The measured points, oldest first."""
        sql, args = "SELECT * FROM series WHERE 1=1", []
        if domain:
            sql += " AND domain = ?"
            args.append(domain)
        if split:
            sql += " AND split = ?"
            args.append(split)
        with self._db.lock:
            rows = self._db.conn.execute(sql + " ORDER BY seq DESC LIMIT ?", [*args, limit])
            found = [dict(r) for r in rows.fetchall()]
        return list(reversed(found))

    def add_night(self, app: str, body: dict[str, Any]) -> None:
        with self._db.lock:
            self._db.conn.execute(
                "INSERT INTO nights (ts_ms, app, body) VALUES (?, ?, ?)",
                (_now(), app, json.dumps(body, sort_keys=True, default=str)),
            )
            self._db.conn.commit()

    def nights(self, limit: int = 30) -> list[dict[str, Any]]:
        """The most recent nights, newest first."""
        with self._db.lock:
            rows = self._db.conn.execute(
                "SELECT ts_ms, app, body FROM nights ORDER BY seq DESC LIMIT ?", (limit,)
            ).fetchall()
        return [{"ts_ms": r["ts_ms"], "app": r["app"], **json.loads(r["body"])} for r in rows]


class PracticeView:
    """What a learner may see of the benchmark: practice tasks, and nothing else."""

    def __init__(self, store: BenchStore) -> None:
        self._store = store

    def tasks(self, domain: Domain, *, source: Source | None = None) -> list[Task]:
        return self._store.tasks(domain, splits=tuple(LEARNER_SPLITS), source=source)
