"""Read task lifecycle evidence off the event loop, independently of TUI paint.

Silence is not a completion event. Records from a different process, account,
or earlier submission must never finish the current job. Unsupported or missing
records remain unknown; they do not manufacture a stop.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from loguru import logger

from . import agent_transcript

MAX_TAIL_BYTES = 512_000
FRESH_S = 6.0

#: Claude Code tools that always run in the background and report by a
#: ``<task-notification>`` later; any other tool does when its input sets
#: ``run_in_background`` (a background shell, a background sub-agent).
BACKGROUND_TOOLS = frozenset({"Monitor", "Workflow"})
#: A background task with no notification after this long is assumed lost (the
#: CLI restarted, the notice fell outside the read window): never counted forever.
BACKGROUND_MAX_S = 6 * 3600.0
_NOTICE_ID = re.compile(r"<tool-use-id>([^<]+)</tool-use-id>")
_NOTICE_STATUS = re.compile(r"<status>([^<]+)</status>")


@dataclass(frozen=True)
class Evidence:
    state: str = "unknown"
    at: float = 0.0
    checked_at: float = 0.0
    # The last lifecycle state recorded BEFORE the current submission. Never
    # the state of the current job; it only tells a submission that started
    # no turn (an empty Enter, a slash command) after a finished one apart
    # from a pane with no history at all.
    before: str = ""
    # Background tasks the agent started (shells, sub-agents, monitors) that
    # have not reported back yet. A turn can end while they run: the job is
    # not finished until they are done.
    background: int = 0


def background_launches(row: dict) -> list[str]:
    """Tool-use ids of background tasks a Claude Code assistant row starts. Pure."""
    if row.get("type") != "assistant" or row.get("isSidechain"):
        return []
    message = row.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    out = []
    for block in content if isinstance(content, list) else []:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        tool_input = block.get("input") if isinstance(block.get("input"), dict) else {}
        if block.get("name") in BACKGROUND_TOOLS or tool_input.get("run_in_background") is True:
            out.append(str(block.get("id", "")))
    return [i for i in out if i]


def background_endings(raw: str, row: dict) -> list[str]:
    """Tool-use ids of background tasks this row reports over (or failed to start). Pure."""
    ended = []
    if "<task-notification>" in raw:
        status = _NOTICE_STATUS.search(raw)
        if status is None or status.group(1).strip().lower() not in {"running", "started"}:
            ended.extend(_NOTICE_ID.findall(raw))
    message = row.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if row.get("type") == "user" and isinstance(content, list):
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            if block.get("is_error"):
                ended.append(str(block.get("tool_use_id", "")))
    return [i for i in ended if i]


_readings: dict[tuple, Evidence] = {}
_files: dict[tuple, tuple[tuple, Evidence]] = {}


def _key(term: Any) -> tuple:
    return (
        getattr(term, "agent", ""), getattr(term, "account", None),
        getattr(getattr(term, "resume", None), "id", ""),
        getattr(term, "process_generation", 0), getattr(term, "pty_id", None),
        getattr(term, "last_submit_at", None), getattr(term, "computer_id", ""),
    )


def evidence(term: Any, *, now: float | None = None) -> Evidence | None:
    """Cached evidence only; None means the first observation has not run yet."""
    item = _readings.get(_key(term))
    if item is None:
        return None
    moment = time.time() if now is None else now
    return item if 0 <= moment - item.checked_at <= FRESH_S else Evidence(checked_at=moment)


def transition(agent: str, row: dict) -> tuple[str, float] | None:
    """Only protocol markers change lifecycle, never words in assistant prose."""
    at = (agent_transcript._ts_ms(row.get("timestamp")) or 0) / 1000.0
    kind = row.get("type")
    payload = row.get("payload")
    if agent == "codex" and isinstance(payload, dict):
        ptype = payload.get("type")
        if kind == "event_msg":
            state = {
                "task_started": "working", "user_message": "working",
                "task_complete": "completed", "turn_aborted": "stopped",
            }.get(ptype)
            if ptype == "task_complete" and payload.get("error"):
                state = "failed"
            return (state, at) if state else None
        if kind == "response_item":
            if ptype in {"function_call", "custom_tool_call"}:
                name = str(payload.get("name", "")).rsplit(".", 1)[-1]
                return ("asking" if name in {"request_user_input", "AskUserQuestion"}
                        else "working", at)
            if ptype in {"function_call_output", "custom_tool_call_output", "reasoning"}:
                return "working", at
            if ptype == "message" and payload.get("role") in {"user", "assistant"}:
                return "working", at
    if agent == "claude" and not row.get("isSidechain") and not row.get("isMeta"):
        message = row.get("message")
        if kind == "system" and row.get("subtype") == "turn_duration":
            return "completed", at
        if kind not in {"user", "assistant"} or not isinstance(message, dict):
            return None
        content = message.get("content")
        if kind == "user" and row.get("queueTranscriptOnly"):
            # Claude Code records a queued notice (e.g. "background command did
            # not finish before the previous session ended") without starting a
            # turn. Reading it as work left an idle pane "working" for good.
            return None
        if kind == "user":
            texts = [content] if isinstance(content, str) else [
                b.get("text", "") for b in content or [] if isinstance(b, dict)
            ]
            interrupted = {
                "[Request interrupted by user]", "[Request interrupted by user for tool use]",
            }
            if any(t in interrupted for t in texts):
                return "stopped", at
            return "working", at
        if isinstance(content, list) and any(
            b.get("type") == "tool_use" and b.get("name") == "AskUserQuestion"
            for b in content if isinstance(b, dict)
        ):
            return "asking", at
        if message.get("stop_reason") == "end_turn":
            return "completed", at
        return "working", at
    return None


def _read(key: tuple, now: float) -> Evidence:
    from .session import account_home

    agent, account, session_id, _, _, submitted_at, remote = key
    resolver = {
        "codex": agent_transcript._codex_file, "claude": agent_transcript._claude_file,
    }.get(agent)
    if remote or not session_id or resolver is None:
        return Evidence(checked_at=now)
    try:
        cached = _files.get(key)
        path = Path(cached[0][0]) if cached else resolver(session_id, account_home(agent, account))
        if path is None:
            return Evidence(checked_at=now)
        stat = path.stat()
        signature = (str(path), stat.st_mtime_ns, stat.st_size)
        if cached and cached[0] == signature:
            return replace(cached[1], checked_at=now)
        result = Evidence(checked_at=now)
        before = ""
        pending: dict[str, float] = {}
        # A bounded tail is enough: tool progress keeps a task working even
        # when its start marker lies outside the window. No marker -> unknown.
        with path.open("rb") as handle:
            if stat.st_size > MAX_TAIL_BYTES:
                handle.seek(stat.st_size - MAX_TAIL_BYTES)
                handle.readline()
            for raw in handle:
                try:
                    row = json.loads(raw)
                except (ValueError, UnicodeDecodeError):
                    # a half-written last line is expected while the writer runs
                    result, before = Evidence(checked_at=now), ""
                    continue  # The writer may not have completed its last JSON line.
                if not isinstance(row, dict):
                    continue
                if agent == "claude":
                    row_at = (agent_transcript._ts_ms(row.get("timestamp")) or 0) / 1000.0
                    for launched in background_launches(row):
                        pending[launched] = row_at or now
                    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
                    for ended in background_endings(text, row):
                        pending.pop(ended, None)
                if (
                    agent == "claude" and row.get("type") == "system"
                    and row.get("subtype") == "turn_duration"
                    and result.state in {"stopped", "failed", "asking"}
                ):
                    # Timing bookkeeping must not turn a cancellation or an
                    # unanswered question into a successful turn boundary.
                    continue
                change = transition(agent, row)
                if not change or not 0 < change[1] <= time.time():
                    continue
                if change[1] >= float(submitted_at or 0):
                    result = Evidence(*change, checked_at=now)
                elif not (
                    agent == "claude" and row.get("subtype") == "turn_duration"
                    and before in {"stopped", "failed", "asking"}
                ):
                    before = change[0]
        open_tasks = sum(1 for at in pending.values() if now - at <= BACKGROUND_MAX_S)
        result = replace(result, before=before, background=open_tasks)
        _files[key] = (signature, result)
        return result
    except (OSError, ValueError, TypeError):
        _files.pop(key, None)
        logger.opt(exception=True).debug("Agent task lifecycle record unavailable")
        return Evidence(checked_at=now)


def background_tasks(term: Any) -> int:
    """Background tasks this pane's agent still has running (0 when unknown)."""
    proof = evidence(term)
    return proof.background if proof is not None else 0


async def refresh(registry: Any) -> None:
    """Read one batch in a worker thread; discard results superseded during IO."""
    keys = {_key(t) for s in registry.sessions for t in s.terminals}
    def read_batch() -> dict[tuple, Evidence]:
        now = time.time()
        return {key: _read(key, now) for key in keys}

    readings = await asyncio.to_thread(read_batch)
    alive = {_key(t) for s in registry.sessions for t in s.terminals}
    _readings.clear()
    _readings.update({key: value for key, value in readings.items() if key in alive})
    for key in list(_files):
        if key not in alive:
            del _files[key]


async def probe(term: Any) -> Evidence:
    """Revalidate immediately before returning a result, including auto-resumes."""
    key = _key(term)
    result = await asyncio.to_thread(_read, key, time.time())
    if key != _key(term):
        return Evidence()
    _readings[key] = result
    return result


def reset() -> None:
    _readings.clear()
    _files.clear()
