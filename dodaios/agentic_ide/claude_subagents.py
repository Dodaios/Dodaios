"""A Claude Code session's sub-agent records, read for what they ran.

A lead that delegates its work through the Agent tool keeps none of the
delegated commands in its own record. Claude Code files each sub-agent's own
conversation beside it: ``<project>/<session-id>/subagents/agent-<id>.jsonl``,
every row marked ``isSidechain``. The commands in them belong to the session's
thread.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from loguru import logger

from dodaios.agentic_ide import agent_sessions, agent_transcript


def _files(session_id: str, home: Path | None) -> list[Path]:
    projects = agent_sessions._claude_home(home) / "projects"
    if not projects.is_dir():
        return []
    return sorted(projects.glob(f"*/{session_id}/subagents/*.jsonl"))


def _session(agent: str, session_id: str) -> str:
    """The session id when this CLI keeps sub-agent records this module reads."""
    session = str(session_id or "").strip()
    return session if agent_transcript._agent_key(agent) == "claude" else ""


def stamp(agent: str, session_id: str, *, home: Path | None = None) -> tuple[int, int, int] | None:
    """Count, total size and newest modification time of the sub-agent records.

    ``None`` for a CLI without such records or when a file vanished mid-look;
    ``(0, 0, 0)`` for a session that spawned none.
    """
    session = _session(agent, session_id)
    if not session:
        return None
    try:
        infos = [path.stat() for path in _files(session, home)]
    except OSError as exc:
        logger.debug("Sub-agent records of {} not stat-able: {}", session, exc)
        return None
    return (
        len(infos),
        sum(info.st_size for info in infos),
        max((info.st_mtime_ns for info in infos), default=0),
    )


def read_events(
    agent: str, session_id: str, *, home: Path | None = None
) -> list[dict[str, Any]] | None:
    """The tool events of every sub-agent the session spawned, oldest first.

    ``[]`` when there are none; ``None`` when a record cannot be read now.
    """
    session = _session(agent, session_id)
    if not session:
        return []
    events: list[dict[str, Any]] = []
    try:
        for path in _files(session, home):
            log = agent_transcript._claude_events(session, home, False, path)
            events.extend(getattr(log, "events", []))
    except OSError as exc:
        logger.warning("Sub-agent records of {} unreadable: {}", session, exc)
        return None
    events.sort(key=lambda event: event.get("ts_ms") or 0)
    return events
