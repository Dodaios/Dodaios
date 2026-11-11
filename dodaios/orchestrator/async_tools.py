"""Slow tools as background jobs: the call returns "started" at once, the result arrives later.

A tool that can run for minutes (a shell build, a browser task) used to hold the
chat's turn: the person's next message waited behind it and a stop could only
abandon it. Here the executor runs such a tool under a short budget:

* it finishes inside the budget: the result is returned as always (fast calls
  are unchanged);
* it does not: the call returns ``{"started": true, "job_id": ...}``, the work
  goes on as a job in the jobs ledger, and the chat's turn is held (or hands its
  seat to the next message) through the delegated-work wait of ADR-0041. When the
  job ends, its result is delivered into the conversation the way every other
  delegated result is, as a continuation of the request that started it;
* ``job_stop`` cancels the work; a stop of the person's turn while the call is
  still inside its budget cancels it too.

Nothing is lost: the finished result is written to a file next to the ledger
before the ledger row closes, so a restart that comes between "finished" and
"delivered" still reports it. A job whose process died with the app is reported
``interrupted``, never ``done``.

Opt-in per tool class. A tool is backgrounded when its name is in the configured
list (default: ``run_shell``, ``society_browser``) or it declares
``long_running = True`` (optionally ``long_running_budget_s``). Tools that already
return a job id (missions, artifacts, team threads) are not wrapped. Only a call
from a conversation that can receive a later result is backgrounded; a voice call
or an unattended task keeps the synchronous contract.

Environment overrides: ``DODAIOS_ASYNC_TOOLS`` (a comma list that replaces the
default, ``off`` empties it) and ``DODAIOS_ASYNC_TOOL_BUDGET_S``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from dodaios.core.delegated_work import (
    DelegatedWork,
    can_register_delegated_work,
    register_delegated_work,
)
from dodaios.core.protocols import ExecutionContext, ToolResult
from dodaios.orchestrator import jobs

log = logging.getLogger(__name__)

#: Tools backgrounded by default: they run for as long as their command or task does.
DEFAULT_TOOLS: Final[frozenset[str]] = frozenset({"run_shell", "society_browser"})
#: How long a call may run before it is handed off. Short enough that the person
#: is not kept waiting, long enough that ordinary calls finish synchronously.
DEFAULT_BUDGET_S: Final[float] = 20.0
#: Never wrapped: they read or end jobs, or already return a job id of their own.
NEVER: Final[frozenset[str]] = frozenset(
    {
        "job_status", "await_jobs", "job_stop", "work_board", "spawn_worker", "create_artifact",
        "delegate_to_agent", "message_agent", "team_thread", "computer_use",
    }
)
#: How much of a result the delivery to the conversation carries; the full
#: result stays readable with ``job_status(ids=[...], full=true)``.
REPORT_CHARS: Final[int] = 4000

RESULT_REF_PREFIX: Final[str] = "async_tool:"
_memory_results: dict[str, dict[str, Any]] = {}


@dataclass(slots=True)
class _Running:
    task: asyncio.Task[Any]
    tool: str
    started: float


_running: dict[str, _Running] = {}


# -- configuration -----------------------------------------------------------------


def _norm(name: str) -> str:
    return name.strip().lower().replace("-", "_")


def configured_tools() -> frozenset[str]:
    raw = os.environ.get("DODAIOS_ASYNC_TOOLS")
    if raw is None:
        return DEFAULT_TOOLS
    if raw.strip().lower() in {"off", "none", "false", "0"}:
        return frozenset()
    return frozenset(_norm(part) for part in raw.split(",") if part.strip())


def budget_s(tool: Any = None) -> float:
    declared = getattr(tool, "long_running_budget_s", None)
    raw = declared if declared is not None else os.environ.get("DODAIOS_ASYNC_TOOL_BUDGET_S")
    try:
        value = float(raw) if raw is not None else DEFAULT_BUDGET_S
    except (TypeError, ValueError):  # a bad override falls back to the default
        return DEFAULT_BUDGET_S
    return max(value, 0.0)


def is_long_running(tool: Any) -> bool:
    name = _norm(str(getattr(tool, "name", "")))
    if not name or name in NEVER:
        return False
    return bool(getattr(tool, "long_running", False)) or name in configured_tools()


def _eligible(tool: Any, ctx: ExecutionContext) -> bool:
    if not is_long_running(tool):
        return False
    config = getattr(ctx, "config", None)
    ref = str(config.get("approval_ref") or "") if isinstance(config, dict) else ""
    # Only a chat turn is told when the work ends (the wait that holds the turn).
    return ref.startswith("agent-chat:") and can_register_delegated_work()


# -- the result file ---------------------------------------------------------------


def _results_dir() -> Path | None:
    path = getattr(jobs.get_ledger(), "path", None)
    if not path or path == ":memory:":
        return None
    return Path(path).parent / "async_tool_results"


def _write_result(job_id: str, record: dict[str, Any]) -> None:
    folder = _results_dir()
    if folder is None:
        _memory_results[job_id] = record
        return
    try:
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{job_id}.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(record, ensure_ascii=False, default=str), "utf-8")
        temporary.replace(target)
    except OSError:
        log.warning("async tool: result of %s not saved to disk", job_id, exc_info=True)
        _memory_results[job_id] = record


def read_result(job_id: str) -> dict[str, Any] | None:
    """The saved result of a finished job: ``{"success", "output", "error"}``."""
    if job_id in _memory_results:
        return _memory_results[job_id]
    folder = _results_dir()
    if folder is None:
        return None
    try:
        data = json.loads((folder / f"{job_id}.json").read_text("utf-8"))
    except (OSError, ValueError):  # no result saved (yet), or an unreadable file
        return None
    return data if isinstance(data, dict) else None


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):  # not JSON-serialisable: its plain text form is the report
        return str(value)


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def report_for(job: jobs.Job) -> str | None:
    """What the conversation is told when ``job`` settled (the result, clipped)."""
    record = read_result(job.id)
    if record is None:
        return None
    label = job.title or job.target or "The tool"
    if record.get("success"):
        body = _clip(_text(record.get("output")), REPORT_CHARS) or "It returned no output."
        return (
            f"{label} finished. Result:\n{body}\n"
            f'(full result: job_status with ids ["{job.id}"] and full true)'
        )
    return f"{label} failed: {record.get('error') or 'no reason given'}"


# -- the run ------------------------------------------------------------------------


def _settle(job_id: str, label: str, task: asyncio.Task[Any]) -> None:
    """The work ended: save the result, then close the ledger row."""
    _running.pop(job_id, None)
    if task.cancelled():
        jobs.finish(job_id, "cancelled", summary=f"{label} was stopped.")
        return
    error = task.exception()
    if error is not None:
        log.warning("async tool %s: %s raised", job_id, label, exc_info=error)
        record: dict[str, Any] = {
            "success": False,
            "output": None,
            "error": f"{type(error).__name__}: {error}",
        }
    else:
        result = task.result()
        record = {
            "success": bool(getattr(result, "success", False)),
            "output": getattr(result, "output", None),
            "error": getattr(result, "error", None),
        }
    _write_result(job_id, record)
    if record["success"]:
        jobs.finish(
            job_id,
            "done",
            summary=_clip(_text(record["output"]), 400) or f"{label} finished.",
            result_ref=RESULT_REF_PREFIX + job_id,
        )
    else:
        jobs.finish(
            job_id,
            "failed",
            error=str(record["error"] or "the tool failed"),
            result_ref=RESULT_REF_PREFIX + job_id,
        )


def _interrupted(job: jobs.Job) -> dict[str, Any]:
    return {
        "status": "interrupted",
        "report": (
            f"{job.title or 'The tool'} was still running when the app restarted. "
            "Its result was not captured. Run it again if it still matters."
        ),
    }


def _probe(job_id: str):
    async def probe() -> dict[str, Any] | None:
        job = jobs.get_ledger().get(job_id)
        if job is None:
            return {"status": "failed", "report": "The record of this job is gone."}
        if job.settled:
            row: dict[str, Any] = {
                "status": job.state,
                "report": report_for(job)
                or job.summary
                or job.error
                or f"{job.title or 'The job'} ended as {job.state}.",
            }
            if job.result_ref:
                row["result_ref"] = job.result_ref
            return row
        entry = _running.get(job_id)
        if entry is None:
            return _interrupted(job)
        if entry.task.done():
            return None  # the settle callback is about to close the row
        minutes = int((time.monotonic() - entry.started) // 60)
        return {"status": "running", "progress": f"running, {minutes} min"}

    return probe


def _rehydrate(job: jobs.Job):
    """After a restart: a result that was saved but not yet delivered is still there."""
    if read_result(job.id) is None:
        return None

    async def probe() -> dict[str, Any] | None:
        record = read_result(job.id)
        if record is None:
            return _interrupted(job)
        ok = bool(record.get("success"))
        jobs.finish(
            job.id,
            "done" if ok else "failed",
            summary=_clip(_text(record.get("output")), 400) if ok else "",
            error="" if ok else str(record.get("error") or "the tool failed"),
            result_ref=RESULT_REF_PREFIX + job.id,
        )
        fresh = jobs.get_ledger().get(job.id) or job
        return {
            "status": "done" if ok else "failed",
            "report": report_for(fresh) or "",
            "result_ref": RESULT_REF_PREFIX + job.id,
        }

    return probe


jobs.register_rehydrator("async_tool", _rehydrate)


def _title(tool: Any, args: dict[str, Any]) -> str:
    name = str(getattr(tool, "name", "tool"))
    detail = ""
    for key in ("command", "goal", "task", "url", "query"):
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            detail = " ".join(value.split())
            break
    return f"{name}: {_clip(detail, 100)}" if detail else name


async def run_tool(tool: Any, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
    """``tool.execute`` for the executor: synchronous for fast calls, a job for slow ones."""
    if not _eligible(tool, ctx):
        return await tool.execute(args, ctx)
    # A task of its own so that a hand-off leaves the work running when the call returns.
    task = asyncio.ensure_future(tool.execute(args, ctx))
    try:
        await asyncio.wait({task}, timeout=budget_s(tool))
    except asyncio.CancelledError:
        # The turn was stopped while the call was still its own: end the work too.
        task.cancel()
        raise
    if task.done():
        return task.result()
    handed = _hand_off(tool, args, ctx, task)
    if handed is None:
        return await task  # no ledger to hold it: keep the call synchronous
    return handed


def _hand_off(
    tool: Any, args: dict[str, Any], ctx: ExecutionContext, task: asyncio.Task[Any]
) -> ToolResult | None:
    name = str(getattr(tool, "name", "tool"))
    title = _title(tool, args)
    job_id = jobs.new_job_id()
    probe = _probe(job_id)
    started = jobs.start(
        "async_tool", job_id=job_id, ctx=ctx, title=title, target=name, probe=probe,
        meta={"tool": name},
    )
    if started is None:
        return None
    work = DelegatedWork(key=f"async:{job_id}", name=title, probe=jobs.probe_for(job_id) or probe)
    if not register_delegated_work(work):
        jobs.finish(job_id, "cancelled", summary="No conversation could receive the result.")
        return None
    _running[job_id] = _Running(task=task, tool=name, started=time.monotonic())
    task.add_done_callback(lambda done: _settle(job_id, title, done))
    return ToolResult(
        True,
        {
            "started": True,
            "job_id": job_id,
            "tool": name,
            "note": (
                f"{name} is still running and continues in the background. Its result "
                "arrives in this conversation on its own when it ends; do not wait for "
                "it or poll. Answer the person now. job_status shows it and "
                f'job_stop("{job_id}") cancels it.'
            ),
        },
    )


def cancel_running(job_id: str) -> bool:
    """Cancel the work of a job in this process without touching its row."""
    entry = _running.get(job_id)
    if entry is None or entry.task.done():
        return False
    entry.task.cancel()
    return True


def stop(job_id: str) -> str:
    """Cancel a running async job: ``stopped``, ``finished`` or ``unknown``."""
    job = jobs.get_ledger().get(job_id)
    if job is None or job.kind != "async_tool":
        return "unknown"
    if job.settled:
        return "finished"
    entry = _running.get(job_id)
    label = job.title or "The tool"
    if entry is None or entry.task.done():
        # Its process is gone (a restart): close the row honestly.
        jobs.finish(job_id, "cancelled", summary=f"{label} was stopped on request.")
        return "stopped"
    jobs.finish(job_id, "cancelled", summary=f"{label} was stopped on request.")
    entry.task.cancel()
    return "stopped"


__all__ = [
    "DEFAULT_BUDGET_S",
    "DEFAULT_TOOLS",
    "RESULT_REF_PREFIX",
    "budget_s",
    "configured_tools",
    "is_long_running",
    "read_result",
    "report_for",
    "run_tool",
    "stop",
]
