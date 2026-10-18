"""Read-only project status for the phone: recent missions and their state.

The mission database is opened with ``mode=ro`` so the gateway can never
write to it; a missing or locked file yields an empty list.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MAX_PROMPT_CHARS = 300

#: States that count as still running for the summary.
ACTIVE_STATES = frozenset({"PENDING", "RUNNING", "CRITIQUING", "LOOPING", "WAITING_CAPACITY"})


class ProjectReader:
    """Lists the newest missions from ``missions.db`` without touching it."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)

    def missions(self, limit: int = 50) -> list[dict[str, Any]]:
        if not self._db_path.is_file():
            return []
        uri = f"{self._db_path.resolve().as_uri()}?mode=ro"
        try:
            with sqlite3.connect(uri, uri=True, timeout=2.0) as conn:
                rows = conn.execute(
                    "SELECT id, prompt, state, created_ms, updated_ms, cost_usd "
                    "FROM missions ORDER BY updated_ms DESC LIMIT ?",
                    (max(1, min(limit, 200)),),
                ).fetchall()
        except sqlite3.Error as exc:
            logger.warning("mobile gateway: mission list unavailable, showing none: %s", exc)
            return []
        return [
            {
                "id": row[0],
                "title": " ".join(str(row[1]).split())[:MAX_PROMPT_CHARS],
                "state": str(row[2]),
                "active": str(row[2]) in ACTIVE_STATES,
                "created_ms": int(row[3]),
                "updated_ms": int(row[4]),
                "cost_usd": round(float(row[5] or 0.0), 4),
            }
            for row in rows
        ]
