"""A Claude Code session's sub-agent records, read for what they ran.

A lead that delegates its work through the Agent tool keeps none of the
delegated commands in its own record. Claude Code files each sub-agent's own
conversation beside it: ``<project>/<session-id>/subagents/agent-<id>.jsonl``,
every row marked ``isSidechain``. The commands in them belong to the session's
thread.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from loguru import logger

from dodaios.agentic_ide import agent_sessions, agent_transcript

#: path -> (size, mtime, tool events): a record that has not grown is not read again.
_parsed: dict[Path, tuple[int, int, list[dict[str, Any]]]] = {}
_parsed_lock = threading.Lock()
#: Enough of a result to tell whether a call succeeded and what it created.
_HEAD, _TAIL = 600, 300


def _lean(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Only the tool calls and results, results cut to their head and tail."""
    kept = []
    for event in events:
        if event.get("kind") not in {"tool_call", "tool_result"}:
            continue
        payload = event.get("payload") or {}
        output = payload.get("output")
        if isinstance(output, str) and len(output) > _HEAD + _TAIL:
            payload = {**payload, "output": output[:_HEAD] + " " + output[-_TAIL:]}
            event = {**event, "payload": payload}
        kept.append(event)
    return kept


def _read_file(path: Path, session: str, home: Path | None) -> list[dict[str, Any]]:
    info = path.stat()
    with _parsed_lock:
        known = _parsed.get(path)
    if known is not None and known[:2] == (info.st_size, info.st_mtime_ns):
        return known[2]
    log = agent_transcript._claude_events(session, home, False, path)
    events = _lean(list(getattr(log, "events", [])))
    with _parsed_lock:
        if len(_parsed) >= 400:
            _parsed.clear()
        _parsed[path] = (info.st_size, info.st_mtime_ns, events)
    return events


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


def read_files(
    agent: str, session_id: str, *, home: Path | None = None
) -> list[tuple[Path, tuple[int, int], list[dict[str, Any]]]] | None:
    """Each sub-agent record: its path, its (size, mtime) and its tool events.

    A record that has not grown since the last call is not read again. ``[]``
    when there are none; ``None`` when a record cannot be read now.
    """
    session = _session(agent, session_id)
    if not session:
        return []
    found = []
    try:
        for path in _files(session, home):
            info = path.stat()
            found.append((path, (info.st_size, info.st_mtime_ns), _read_file(path, session, home)))
    except OSError as exc:
        logger.warning("Sub-agent records of {} unreadable: {}", session, exc)
        return None
    return found


def read_events(
    agent: str, session_id: str, *, home: Path | None = None
) -> list[dict[str, Any]] | None:
    """The tool events of every sub-agent the session spawned, oldest first."""
    files = read_files(agent, session_id, home=home)
    if files is None:
        return None
    events = [event for _, _, each in files for event in each]
    events.sort(key=lambda event: event.get("ts_ms") or 0)
    return events
