"""One row per question the ask-gate scored, and how it turned out.

The gate (``dodaios.agent_chat.ask_gate``) decides to ask, answer from memory or
act on an assumption. This log keeps that decision so the agent score can
measure value-of-information asking:

* **needless question**: a card was shown, and the owner's answer was already in
  memory, or the owner said they had said it before ("you knew that", "just do
  it");
* **should have asked**: the lead acted on an assumption, and the owner's next
  message corrected or undid it.

The labels for the second kind need the owner's next message, so they are
derived when the report is built (``dodaios.evals.agent_score.asking``); the
first kind is also set at answer time. The log never raises into a question.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Final

log = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS asks (
    id TEXT PRIMARY KEY,
    ts_ms INTEGER NOT NULL,
    session_id TEXT NOT NULL DEFAULT '',
    agent_id TEXT NOT NULL DEFAULT '',
    question TEXT NOT NULL,
    decision TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    reversibility TEXT NOT NULL DEFAULT '',
    confidence REAL,
    clarify_on INTEGER NOT NULL DEFAULT 0,
    answer_source TEXT NOT NULL DEFAULT '',
    answer TEXT NOT NULL DEFAULT '',
    needless TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS asks_ts ON asks(ts_ms);
"""

_COLUMNS: Final[tuple[str, ...]] = (
    "id",
    "ts_ms",
    "session_id",
    "agent_id",
    "question",
    "decision",
    "reason",
    "reversibility",
    "confidence",
    "clarify_on",
    "answer_source",
    "answer",
    "needless",
)

#: The owner saying the question was not needed ("you knew that", "just do it").
_NEEDLESS: Final[re.Pattern[str]] = re.compile(
    r"\b(you (already )?(knew|know) (that|this|it)|i (already )?(told|said)( it)?( you)?|"
    r"as i (said|told)|just do it|stop asking|don'?t ask|no need to ask|"
    r"du wei(ß|ss)t (das|es)|das hab(e)? ich (dir )?(schon )?gesagt|wie gesagt|"  # i18n-allow: DE
    r"mach(s| es| das)? einfach|frag nicht|sag ich doch|"  # i18n-allow: DE matcher
    r"ya (lo )?sabes|ya te lo (dije|he dicho)|hazlo( ya)?|"
    r"voc(ê|e) j(á|a) sabe|j(á|a) te (disse|falei)|s(ó|o) faz)\b",  # i18n-allow: ES/PT matcher
    re.I,
)


def is_needless_signal(text: str) -> bool:
    """Whether the owner's words say the question was needless."""
    return bool(_NEEDLESS.search(text or ""))


class AskLog:
    """A small SQLite file; thread-safe; a failing write is a warning, never an error."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None

    def _db(self) -> sqlite3.Connection:
        if self._conn is None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self._path, check_same_thread=False, timeout=5.0)
            self._conn.row_factory = sqlite3.Row
            self._conn.executescript(_SCHEMA)
        return self._conn

    def record(
        self,
        *,
        question: str,
        decision: str,
        reason: str = "",
        session_id: str = "",
        agent_id: str = "",
        reversibility: str = "",
        confidence: float | None = None,
        clarify_on: bool = False,
        answer: str = "",
        answer_source: str = "",
        needless: str = "",
        ts_ms: int | None = None,
    ) -> str:
        """Add one row; returns its id (``""`` when the log could not write)."""
        row_id = uuid.uuid4().hex[:16]
        try:
            with self._lock:
                self._db().execute(
                    f"INSERT INTO asks ({', '.join(_COLUMNS)}) VALUES "  # noqa: S608 - constants
                    f"({', '.join('?' for _ in _COLUMNS)})",
                    (
                        row_id,
                        int(ts_ms if ts_ms is not None else time.time() * 1000),
                        session_id,
                        agent_id,
                        question[:600],
                        decision,
                        reason[:300],
                        reversibility,
                        confidence,
                        int(clarify_on),
                        answer_source,
                        answer[:600],
                        needless,
                    ),
                )
                self._db().commit()
        except sqlite3.Error:
            log.warning("ask log: could not write a row", exc_info=True)
            return ""
        return row_id

    def mark_answer(self, row_id: str, *, source: str, answer: str, needless: str = "") -> None:
        """Attach the owner's answer (and the needless label, if it has one) to a card."""
        if not row_id:
            return
        try:
            with self._lock:
                self._db().execute(
                    "UPDATE asks SET answer_source = ?, answer = ?, needless = ? WHERE id = ?",
                    (source, answer[:600], needless, row_id),
                )
                self._db().commit()
        except sqlite3.Error:
            log.warning("ask log: could not update row %s", row_id, exc_info=True)

    def rows(self, since_ms: int = 0, until_ms: int | None = None) -> list[dict[str, Any]]:
        """Rows in the window, oldest first. An unreadable log reads as empty."""
        try:
            with self._lock:
                cur = self._db().execute(
                    "SELECT * FROM asks WHERE ts_ms >= ? AND ts_ms <= ? ORDER BY ts_ms",
                    (since_ms, until_ms if until_ms is not None else 2**62),
                )
                return [dict(r) for r in cur.fetchall()]
        except sqlite3.Error:
            log.warning("ask log: could not read rows", exc_info=True)
            return []

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None


_DEFAULT: list[AskLog] = []


def ask_log() -> AskLog:
    """The process-wide log under the data dir (built on first use)."""
    if not _DEFAULT:
        from dodaios.core.config import DATA_DIR

        _DEFAULT.append(AskLog(Path(DATA_DIR) / "trust" / "ask_log.db"))
    return _DEFAULT[0]


def set_ask_log(log_: AskLog | None) -> None:
    """Swap the process-wide log (tests, a custom data dir)."""
    _DEFAULT.clear()
    if log_ is not None:
        _DEFAULT.append(log_)


__all__ = ["AskLog", "ask_log", "is_needless_signal", "set_ask_log"]
