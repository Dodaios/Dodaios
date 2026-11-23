"""``briefs.db``: every order handed to a coding agent, and what came of it.

Whether a change to the brief rules helps can only be told from what happened
to real orders. So each order is written down once, with what the person
said, the brief as it was first written and as it was sent, what the check
found, and who received it; and each delivery of it (one per agent) later gets
its outcome: how the run ended and how the done-when points fared.

``briefs`` holds the order, ``deliveries`` one row per agent that received it,
keyed by the job the hand-off returned. The same job id keys the run record
(``dodaios.orchestrator.verification``) when that is switched on, so the two
can be read together; neither needs the other.

SQLite in the app's data directory, opened like the other stores: one
connection in WAL mode behind a lock. Everything here is on the path of a
hand-off, so no function raises into its caller: a fault is logged and the
hand-off goes on without its record.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Final

__all__ = ["BriefLog", "get_log", "new_brief_id", "reset_log"]

log = logging.getLogger(__name__)

DB_NAME: Final[str] = "briefs.db"
#: Rows kept; the oldest orders go first.
MAX_BRIEFS: Final[int] = 5_000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS briefs (
    brief_id       TEXT PRIMARY KEY,
    created_ms     INTEGER NOT NULL,
    writer         TEXT NOT NULL DEFAULT '',
    writer_session TEXT NOT NULL DEFAULT '',
    target_kind    TEXT NOT NULL DEFAULT '',
    folder         TEXT NOT NULL DEFAULT '',
    repo_id        TEXT NOT NULL DEFAULT '',
    kind           TEXT NOT NULL DEFAULT '',
    lenses_json    TEXT NOT NULL DEFAULT '[]',
    person_words   TEXT NOT NULL DEFAULT '',
    first_draft    TEXT NOT NULL DEFAULT '',
    first_findings TEXT NOT NULL DEFAULT '[]',
    prepared       INTEGER NOT NULL DEFAULT 0,
    sent_back      INTEGER NOT NULL DEFAULT 0,
    brief_text     TEXT NOT NULL DEFAULT '',
    findings_json  TEXT NOT NULL DEFAULT '[]',
    criteria_json  TEXT NOT NULL DEFAULT '[]',
    gaps_json      TEXT NOT NULL DEFAULT '[]',
    sent_ms        INTEGER
);
CREATE INDEX IF NOT EXISTS idx_briefs_created ON briefs(created_ms DESC);
CREATE TABLE IF NOT EXISTS deliveries (
    job_id         TEXT PRIMARY KEY,
    brief_id       TEXT NOT NULL,
    thread_id      TEXT NOT NULL DEFAULT '',
    cli            TEXT NOT NULL DEFAULT '',
    model          TEXT NOT NULL DEFAULT '',
    family         TEXT NOT NULL DEFAULT '',
    effort         TEXT NOT NULL DEFAULT '',
    effort_source  TEXT NOT NULL DEFAULT '',
    job_size       TEXT NOT NULL DEFAULT '',
    sent_chars     INTEGER NOT NULL DEFAULT 0,
    sent_ms        INTEGER NOT NULL,
    outcome        TEXT NOT NULL DEFAULT '',
    outcome_ms     INTEGER,
    acceptance     TEXT NOT NULL DEFAULT '[]',
    questions      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_deliveries_brief ON deliveries(brief_id);
CREATE INDEX IF NOT EXISTS idx_deliveries_thread ON deliveries(thread_id, sent_ms DESC);
"""


def new_brief_id() -> str:
    return "brief_" + uuid.uuid4().hex[:20]


def _json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):  # a value that cannot be written is recorded as missing
        return "[]"


class BriefLog:
    """The record of orders and their deliveries."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(self.path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.executescript(_SCHEMA)
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # ------------------------------------------------------------------ writes

    def note_attempt(
        self,
        brief_id: str,
        *,
        writer: str,
        writer_session: str = "",
        target_kind: str = "",
        folder: str = "",
        repo_id: str = "",
        kind: str = "",
        lenses: list[str] | None = None,
        person_words: str = "",
        draft: str = "",
        findings: list[dict[str, str]] | None = None,
        criteria: list[dict[str, str]] | None = None,
        gaps: list[str] | None = None,
        sent_back: bool = False,
        prepared: bool = False,
    ) -> None:
        """Write an order's attempt: the first one creates the row, a revision completes it."""
        now = int(time.time() * 1000)
        with self._lock:
            known = self._db.execute(
                "SELECT brief_id FROM briefs WHERE brief_id = ?", (brief_id,)
            ).fetchone()
            if known is None:
                self._db.execute(
                    "INSERT INTO briefs (brief_id, created_ms, writer, writer_session, "
                    "target_kind, folder, repo_id, kind, lenses_json, person_words, first_draft, "
                    "first_findings, prepared, sent_back, brief_text, findings_json, "
                    "criteria_json, gaps_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        brief_id, now, writer, writer_session, target_kind, folder, repo_id,
                        kind, _json(lenses or []), person_words, draft, _json(findings or []),
                        int(prepared), int(sent_back), draft, _json(findings or []),
                        _json(criteria or []), _json(gaps or []),
                    ),
                )
                self._db.execute(
                    "DELETE FROM briefs WHERE brief_id IN (SELECT brief_id FROM briefs "
                    "ORDER BY created_ms DESC LIMIT -1 OFFSET ?)",
                    (MAX_BRIEFS,),
                )
            else:
                self._db.execute(
                    "UPDATE briefs SET brief_text = ?, findings_json = ?, criteria_json = ?, "
                    "gaps_json = ?, kind = ?, lenses_json = ?, "
                    "sent_back = MAX(sent_back, ?), prepared = MAX(prepared, ?) "
                    "WHERE brief_id = ?",
                    (
                        draft, _json(findings or []), _json(criteria or []), _json(gaps or []),
                        kind, _json(lenses or []), int(sent_back), int(prepared), brief_id,
                    ),
                )
            self._db.commit()

    def note_delivery(
        self,
        brief_id: str,
        job_id: str,
        *,
        thread_id: str = "",
        cli: str = "",
        model: str = "",
        family: str = "",
        effort: str = "",
        effort_source: str = "",
        job_size: str = "",
        sent_chars: int = 0,
    ) -> None:
        """Write that an order reached one agent under ``job_id``."""
        now = int(time.time() * 1000)
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO deliveries (job_id, brief_id, thread_id, cli, model, "
                "family, effort, effort_source, job_size, sent_chars, sent_ms) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    job_id, brief_id, thread_id, cli, model, family, effort, effort_source,
                    job_size, int(sent_chars), now,
                ),
            )
            self._db.execute(
                "UPDATE briefs SET sent_ms = COALESCE(sent_ms, ?) WHERE brief_id = ?",
                (now, brief_id),
            )
            self._db.commit()

    def note_outcome(
        self, job_id: str, outcome: str, acceptance: list[dict[str, str]] | None = None
    ) -> None:
        """Write how a delivery ended; a later end of the same job replaces an earlier one."""
        with self._lock:
            self._db.execute(
                "UPDATE deliveries SET outcome = ?, outcome_ms = ?, acceptance = ? "
                "WHERE job_id = ?",
                (outcome, int(time.time() * 1000), _json(acceptance or []), job_id),
            )
            self._db.commit()

    def note_question(self, job_id: str, continued_as: str = "") -> None:
        """Count a question the agent asked while it worked on a delivery.

        An answered question lets the work go on under a new job
        (``continued_as``): the delivery follows it there, so the order's end
        is written to the same row.
        """
        with self._lock:
            self._db.execute(
                "UPDATE deliveries SET questions = questions + 1 WHERE job_id = ?", (job_id,)
            )
            if continued_as and continued_as != job_id:
                self._db.execute(
                    "UPDATE OR REPLACE deliveries SET job_id = ? WHERE job_id = ?",
                    (continued_as, job_id),
                )
            self._db.commit()

    # ------------------------------------------------------------------- reads

    def brief(self, brief_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM briefs WHERE brief_id = ?", (brief_id,)
            ).fetchone()
        return dict(row) if row is not None else None

    def delivery(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM deliveries WHERE job_id = ?", (job_id,)
            ).fetchone()
        return dict(row) if row is not None else None

    def orders_to_thread(self, thread_id: str) -> int:
        """How many orders this thread has received so far."""
        with self._lock:
            row = self._db.execute(
                "SELECT COUNT(*) AS n FROM deliveries WHERE thread_id = ?", (thread_id,)
            ).fetchone()
        return int(row["n"]) if row is not None else 0

    def standing_order(self, thread_id: str) -> tuple[Any, int] | None:
        """The last order to a thread that named done-when points: ``(ticket, sent_ms)``."""
        from dodaios.briefs import done
        from dodaios.briefs.gate import Ticket

        with self._lock:
            row = self._db.execute(
                "SELECT b.brief_id, b.kind, b.writer, b.criteria_json, d.sent_ms "
                "FROM deliveries d JOIN briefs b ON b.brief_id = d.brief_id "
                "WHERE d.thread_id = ? AND b.criteria_json NOT IN ('', '[]') "
                "ORDER BY d.sent_ms DESC LIMIT 1",
                (thread_id,),
            ).fetchone()
        if row is None:
            return None
        try:
            points = json.loads(row["criteria_json"] or "[]")
        except ValueError:  # an unreadable cell names no points
            return None
        criteria = tuple(
            done.Criterion(
                str(point.get("text") or ""), str(point.get("kind") or done.KIND_OTHER),
                str(point.get("target") or ""),
            )
            for point in points
            if isinstance(point, dict) and point.get("text")
        )
        if not criteria:
            return None
        ticket = Ticket(
            brief_id=str(row["brief_id"]), kind=str(row["kind"] or ""),
            writer=str(row["writer"] or ""), criteria=criteria,
        )
        return ticket, int(row["sent_ms"] or 0)

    def rows(self, *, since_ms: int = 0, limit: int = 2_000) -> list[dict[str, Any]]:
        """Orders with their deliveries, newest first, for the report."""
        with self._lock:
            briefs = [
                dict(row)
                for row in self._db.execute(
                    "SELECT * FROM briefs WHERE created_ms >= ? ORDER BY created_ms DESC LIMIT ?",
                    (since_ms, limit),
                )
            ]
            by_brief: dict[str, list[dict[str, Any]]] = {}
            for row in self._db.execute(
                "SELECT * FROM deliveries WHERE sent_ms >= ? ORDER BY sent_ms", (since_ms,)
            ):
                by_brief.setdefault(row["brief_id"], []).append(dict(row))
        for brief in briefs:
            brief["deliveries"] = by_brief.get(brief["brief_id"], [])
        return briefs


_LOG: BriefLog | None = None
_LOG_LOCK = threading.Lock()


def get_log() -> BriefLog | None:
    """The process-wide log in the app's data directory, ``None`` when it cannot open."""
    global _LOG
    with _LOG_LOCK:
        if _LOG is None:
            try:
                from dodaios.core import config as core_config

                _LOG = BriefLog(core_config.DATA_DIR / DB_NAME)
            except Exception:  # noqa: BLE001 - no record is better than no hand-off
                log.warning("brief log: cannot open %s", DB_NAME, exc_info=True)
                return None
        return _LOG


def reset_log() -> None:
    """Forget the open log (tests point the data directory elsewhere)."""
    global _LOG
    with _LOG_LOCK:
        if _LOG is not None:
            try:
                _LOG.close()
            except sqlite3.Error:
                log.debug("brief log: close failed", exc_info=True)
        _LOG = None
