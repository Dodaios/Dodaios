"""A routine's run history, derived from what is already stored.

A routine is a task in the Automations scheduler (``routines.py``); every
execution leaves log steps on that task (``run_now``, ``run_started``,
``routine_chat``, ``agent_result``, ``run_completed`` / ``error`` /
``skipped`` …) and, since the run summary step, one ``routine_summary`` step
with the seat, duration and cost of the run's turn. Older runs have no
summary step; their duration and cost are read from the run's own chat
(``turn_finished``) when it still exists.

Nothing here writes, calls a model or bills anything: it is a read-only
projection for the routine detail panel and the routine list.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Final

__all__ = [
    "RoutineRun",
    "enrich_from_chat",
    "parse_runs",
    "run_summary_line",
]

#: The first line of a reply, at most this long, describes a run in a list.
SUMMARY_CHARS: Final[int] = 160

_MARKDOWN_LEAD = re.compile(r"^\s*(?:#{1,6}\s+|[-*+]\s+|>\s*|\d+[.)]\s+)")
_MARKDOWN_INLINE = re.compile(r"(\*\*|__|`+|~~)")


@dataclass
class RoutineRun:
    """One execution of one routine task."""

    id: str
    task_id: str
    #: ``running | completed | failed | cancelled | skipped | pending | waiting | legacy``
    status: str
    #: ``manual`` for Run now / Test run, ``automatic`` for its own trigger.
    origin: str = "automatic"
    started_ms: int | None = None
    finished_ms: int | None = None
    duration_ms: int | None = None
    cost_usd: float | None = None
    #: Whether the run's seat bills a per-token key (``None`` = not recorded).
    billed_via_key: bool | None = None
    provider: str = ""
    model: str = ""
    session_id: str = ""
    summary: str = ""
    error: str = ""
    skip_code: str = ""
    skip_provider: str = ""
    #: Internal: the full result text, for the transcript fallback.
    result: str = field(default="", repr=False)
    #: Internal: a ``routine_summary`` step was recorded, so the chat holds
    #: nothing the history still needs (CLI seats often report no cost).
    recorded: bool = field(default=False, repr=False)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("recorded", None)
        return data


def run_summary_line(text: str, limit: int = SUMMARY_CHARS) -> str:
    """The first meaningful line of a reply, without Markdown furniture."""
    for raw in (text or "").splitlines():
        line = _MARKDOWN_INLINE.sub("", _MARKDOWN_LEAD.sub("", raw)).strip()
        if line and not set(line) <= set("-=*_|:"):
            return line if len(line) <= limit else line[: limit - 1].rstrip() + "…"
    return ""


def _ms(step: dict[str, Any]) -> int:
    return int(int(step.get("timestamp_ns") or 0) / 1_000_000)


def _number(value: Any) -> float | None:
    try:
        return None if value is None or isinstance(value, bool) else float(value)
    except (TypeError, ValueError):  # a non-numeric cost or duration reads as unknown
        return None


def parse_runs(task_id: str, steps: list[dict[str, Any]]) -> list[RoutineRun]:
    """The runs of one task, oldest first, from its log steps.

    Mirrors how the task runner writes a run: an optional ``run_now`` marks
    the next start as the person's own, ``run_started`` opens a run and one
    terminal step (``run_completed``, ``run_cancelled``, ``error``,
    ``deferred``, ``waiting`` or ``skipped``) closes it. Records from before
    explicit run boundaries (a bare ``agent_result``) become ``legacy`` runs.
    """
    runs: list[RoutineRun] = []
    current: RoutineRun | None = None
    manual_next = False
    for step in steps:
        payload = step.get("payload") or {}
        event = str(payload.get("event") or "")
        at = _ms(step)
        text = str(payload.get("message") or payload.get("text") or "")
        if event == "run_now":
            manual_next = True
        elif event == "run_started":
            if current is not None and current.status == "running":
                current.status = "interrupted"
            current = RoutineRun(
                id=f"{task_id}:{step.get('seq')}",
                task_id=task_id,
                status="running",
                origin="manual" if manual_next else "automatic",
                started_ms=at,
            )
            manual_next = False
            runs.append(current)
        elif event == "routine_chat" and current is not None:
            current.session_id = str(payload.get("session_id") or "")
        elif event == "routine_summary" and current is not None:
            current.recorded = True
            current.duration_ms = int(_number(payload.get("duration_ms")) or 0) or None
            current.cost_usd = _number(payload.get("cost_usd"))
            billed = payload.get("billed_via_key")
            current.billed_via_key = billed if isinstance(billed, bool) else None
            current.provider = str(payload.get("provider") or "")
            current.model = str(payload.get("model") or "")
            current.session_id = current.session_id or str(payload.get("session_id") or "")
        elif event == "agent_result":
            if current is not None:
                current.result = text
            else:
                runs.append(
                    RoutineRun(
                        id=f"{task_id}:{step.get('seq')}",
                        task_id=task_id,
                        status="legacy",
                        started_ms=at,
                        finished_ms=at,
                        result=text,
                    )
                )
        elif event == "skipped":
            target = current
            if target is None:
                target = RoutineRun(
                    id=f"{task_id}:{step.get('seq')}",
                    task_id=task_id,
                    status="skipped",
                    started_ms=at,
                )
                runs.append(target)
            target.status = "skipped"
            target.finished_ms = at
            target.skip_code = str(payload.get("code") or "")
            target.skip_provider = str(payload.get("provider") or "")
            target.error = text
            # An older history also logged an "error" right after the skip.
            current = target
        elif event in ("run_completed", "run_cancelled", "error", "deferred", "waiting"):
            status = {
                "run_completed": "completed",
                "run_cancelled": "cancelled",
                "deferred": "pending",
                "waiting": "waiting",
            }.get(event, "failed")
            if current is not None and current.status == "skipped":
                current = None
                continue
            if current is None:
                runs.append(
                    RoutineRun(
                        id=f"{task_id}:{step.get('seq')}",
                        task_id=task_id,
                        status=status,
                        started_ms=at,
                        finished_ms=at,
                        error=text if status != "completed" else "",
                    )
                )
                continue
            current.status = status
            current.finished_ms = at
            if status == "completed":
                duration = _number(payload.get("duration_ms"))
                if duration and current.duration_ms is None:
                    current.duration_ms = int(duration)
            elif text or payload.get("reason"):
                current.error = text or str(payload.get("reason") or "")
            current = None
    for run in runs:
        if run.duration_ms is None and run.started_ms and run.finished_ms:
            run.duration_ms = max(0, run.finished_ms - run.started_ms) or None
        run.summary = run.summary or run_summary_line(run.result)
    return runs


def _first_turn(events: list[dict[str, Any]]) -> tuple[str, dict[str, Any] | None, str]:
    """The routine's own turn in its chat: ``(turn_id, turn_finished, reply)``."""
    turn_id = ""
    for event in events:
        if event.get("kind") == "turn_started":
            turn_id = str((event.get("payload") or {}).get("turn_id") or "")
            break
    finished: dict[str, Any] | None = None
    texts: list[str] = []
    for event in events:
        payload = event.get("payload") or {}
        if turn_id and payload.get("turn_id") not in (None, turn_id):
            continue
        if event.get("kind") == "assistant_text":
            texts.append(str(payload.get("text") or ""))
        elif event.get("kind") == "turn_finished":
            finished = payload
            break
    return turn_id, finished, "\n\n".join(t for t in texts if t.strip())


def enrich_from_chat(run: RoutineRun, chat_store: Any) -> None:
    """Fill duration, cost and summary of a run without a summary step.

    Reads the run's own chat once; a missing store or session leaves the run
    as parsed. Only the routine's first turn counts: later turns are the
    person's follow-up questions in that chat.
    """
    if chat_store is None or not run.session_id or run.recorded:
        return
    if run.cost_usd is not None and run.summary:
        return
    try:
        events = chat_store.list_events(run.session_id)
    except Exception:  # noqa: BLE001 — a closed or missing chat store is not an error here
        return
    _, finished, reply = _first_turn(events)
    if finished is not None:
        if run.cost_usd is None:
            run.cost_usd = _number(finished.get("cost_usd"))
        if run.duration_ms is None:
            run.duration_ms = int(_number(finished.get("duration_ms")) or 0) or None
        if not run.error and finished.get("error"):
            run.error = str(finished.get("error"))
    if not run.summary:
        run.summary = run_summary_line(reply)
