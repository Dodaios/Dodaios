"""The person's own messages to the assistant, read from the chat record.

Only what the person wrote counts. A message the app put into the conversation
(a background report, a reminder) carries an ``origin`` and is left out, and
where a message was wrapped around the person's sentence, the sentence itself
is taken (``typed``). The file is opened read-only; nothing is ever written.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

__all__ = ["person_messages"]

log = logging.getLogger(__name__)

#: The surface of the person's one conversation with the assistant.
_LEAD_SURFACE = "jarvis"


def person_messages(db_path: Path) -> list[str]:
    """What the person said to the assistant, oldest first. A missing file gives ``[]``."""
    path = Path(db_path)
    if not path.is_file():
        return []
    try:
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=5.0)
    except sqlite3.Error:
        log.warning("own tasks: the chat record is not readable")
        return []
    out: list[str] = []
    try:
        rows = conn.execute(
            "SELECT e.payload FROM agent_chat_events e"
            " JOIN agent_chat_sessions s ON s.session_id = e.session_id"
            " WHERE e.kind = 'user_message' AND s.surface = ?"
            " ORDER BY e.ts_ms, e.seq",
            (_LEAD_SURFACE,),
        )
        for (raw,) in rows:
            try:
                payload = json.loads(raw or "{}")
            except ValueError:
                continue  # an unreadable event is not a message
            if not isinstance(payload, dict) or payload.get("origin"):
                continue
            text = str(payload.get("typed") or payload.get("text") or "").strip()
            if text:
                out.append(text)
    except sqlite3.Error:
        log.warning("own tasks: the chat record could not be read", exc_info=True)
    finally:
        conn.close()
    return out
