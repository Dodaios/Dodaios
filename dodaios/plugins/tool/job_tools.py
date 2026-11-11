"""``job_status`` and ``await_jobs``: the lead's handle on work it started.

Every async hand-off (a mission, an artifact, an assignment to a team agent, a
prompt into a coding pane, a team thread) returns a ``job_id`` and writes a row
in the jobs ledger (:mod:`dodaios.orchestrator.jobs`). These two tools read it:

* ``job_status`` answers "what became of it" now, summary-first;
* ``await_jobs`` waits up to a timeout the model chooses, polling the same local
  evidence reads the delegation wait uses (no model call, nothing dispatched),
  and says which jobs finished and which are still running.

Both only read evidence. A job is ``done`` only when its own record says so; a
wait that runs out reports the job as still running, never as done.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Final

from dodaios.core.protocols import ExecutionContext, ToolResult
from dodaios.orchestrator import jobs

log = logging.getLogger(__name__)

#: Below the 600 s tool timeout the chat CLIs apply to an MCP call.
MAX_AWAIT_S: Final[float] = 540.0
DEFAULT_AWAIT_S: Final[float] = 60.0
POLL_S: Final[float] = 1.5
_MAX_IDS: Final[int] = 50
_DEFAULT_LIST: Final[int] = 20
_MAX_LIST: Final[int] = 100


def _ids(raw: Any) -> list[str] | None:
    """Clean job ids from the model's argument; ``None`` when it is not a list."""
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return None
    out: list[str] = []
    for item in raw:
        value = str(item or "").strip()
        if value and value not in out:
            out.append(value)
    return out


async def _read(ids: list[str]) -> tuple[list[jobs.Job], list[str]]:
    """The jobs for ``ids`` as the evidence shows them now, plus unknown ids."""
    ledger = jobs.get_ledger()
    found = [(i, ledger.get(i)) for i in ids]
    unknown = [i for i, job in found if job is None]
    rows = [job for _, job in found if job is not None]
    fresh = await asyncio.gather(*(jobs.refresh(job) for job in rows))
    return list(fresh), unknown


def _view(job: jobs.Job, *, full: bool = False) -> dict[str, Any]:
    row = job.to_dict()
    if job.state == "blocked":
        row["needs_attention"] = True
    if full and job.kind == "async_tool" and job.settled:
        from dodaios.orchestrator import async_tools

        saved = async_tools.read_result(job.id)
        if saved is not None:
            row["result"] = saved
    return row


class JobStatusTool:
    """What became of the work this chat started."""

    name: str = "job_status"
    risk_tier: str = "safe"
    is_action_tool: bool = False
    description: str = (
        "Check jobs you started. Every async hand-off (a mission, an artifact, "
        "delegate_to_agent, message_agent, a prompt to a coding pane, a team thread) "
        "returned a job_id. With 'ids' it reports those jobs; with none it lists this "
        "chat's open jobs first, then the most recent settled ones. Each row says "
        "state (queued, running, done, failed, blocked, interrupted, cancelled), a "
        "result_ref to read the outcome, and a short summary. Read-only and instant: "
        "never poll a shell or a log file instead. 'done' is only reported from the "
        "job's own record."
    )
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "job_ids to report. Omit for this chat's recent jobs.",
            },
            "limit": {
                "type": "integer",
                "description": f"Rows when listing (default {_DEFAULT_LIST}, max {_MAX_LIST}).",
            },
            "open_only": {
                "type": "boolean",
                "description": "When listing, only queued or running jobs.",
            },
            "full": {
                "type": "boolean",
                "description": (
                    "Include the saved full result of a finished background tool call "
                    "(its job_id came back with started: true)."
                ),
            },
        },
    }

    async def execute(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        args = args or {}
        ids = _ids(args.get("ids"))
        if ids is None:
            return ToolResult(False, "", "'ids' must be a list of job_id strings.")
        if len(ids) > _MAX_IDS:
            return ToolResult(False, "", f"At most {_MAX_IDS} ids per call.")
        try:
            if ids:
                rows, unknown = await _read(ids)
            else:
                session, _turn = jobs.owner_of(ctx)
                try:
                    limit = int(args.get("limit") or _DEFAULT_LIST)
                except (TypeError, ValueError):  # a bad limit falls back to the default
                    limit = _DEFAULT_LIST
                listed = jobs.get_ledger().recent(
                    owner_session=session,
                    limit=min(max(limit, 1), _MAX_LIST),
                    open_only=bool(args.get("open_only")),
                )
                rows, unknown = list(
                    await asyncio.gather(*(jobs.refresh(job) for job in listed))
                ), []
        except Exception as exc:  # noqa: BLE001
            log.warning("job_status: ledger unavailable", exc_info=True)
            return ToolResult(False, "", f"The jobs ledger is unavailable: {exc}")
        # The read may have settled some jobs: open ones stay on top.
        rows.sort(key=lambda job: job.settled)
        open_count = sum(1 for job in rows if not job.settled)
        output: dict[str, Any] = {
            "open": open_count,
            "settled": len(rows) - open_count,
            "jobs": [_view(job, full=bool(args.get("full"))) for job in rows],
        }
        if unknown:
            output["unknown_ids"] = unknown
        return ToolResult(True, output)


class AwaitJobsTool:
    """Wait for jobs with a timeout, on evidence."""

    name: str = "await_jobs"
    risk_tier: str = "safe"
    is_action_tool: bool = False
    description: str = (
        "Wait for jobs you started (by job_id) instead of polling a shell. Waits up "
        f"to timeout_s seconds (default {int(DEFAULT_AWAIT_S)}, max {int(MAX_AWAIT_S)}) "
        "for ALL of them to settle, or for the FIRST one with mode 'any', and returns "
        "which finished with their state, result_ref and summary, and which are still "
        "running. A job that is still running when the time is up is reported as "
        "running, never as done: call await_jobs again, or tell the person it is still "
        "going. 'blocked' means the job needs input or could not be verified; "
        "'interrupted' means the app restarted and its outcome is unknown. Verify "
        "results you rely on; a finished job is the worker's own record."
    )
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "job_ids returned by the tools that started the work.",
            },
            "timeout_s": {
                "type": "number",
                "description": (
                    f"Seconds to wait, 1 to {int(MAX_AWAIT_S)} (default {int(DEFAULT_AWAIT_S)})."
                ),
            },
            "mode": {
                "type": "string",
                "enum": ["all", "any"],
                "description": "'all' (default) waits for every job; 'any' returns on the first.",
            },
        },
        "required": ["ids"],
    }

    async def execute(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        args = args or {}
        ids = _ids(args.get("ids"))
        if not ids:
            return ToolResult(False, "", "'ids' must list at least one job_id.")
        if len(ids) > _MAX_IDS:
            return ToolResult(False, "", f"At most {_MAX_IDS} ids per call.")
        try:
            timeout = float(args.get("timeout_s") if args.get("timeout_s") is not None
                            else DEFAULT_AWAIT_S)
        except (TypeError, ValueError):  # said to the model: the call is rejected, not retried
            return ToolResult(False, "", "'timeout_s' must be a number of seconds.")
        timeout = min(max(timeout, 1.0), MAX_AWAIT_S)
        mode = str(args.get("mode") or "all").strip().lower()
        if mode not in ("all", "any"):
            return ToolResult(False, "", "'mode' must be 'all' or 'any'.")
        started = time.monotonic()
        deadline = started + timeout
        try:
            while True:
                rows, unknown = await _read(ids)
                settled = [job for job in rows if job.settled]
                pending = [job for job in rows if not job.settled]
                done = not pending or (mode == "any" and settled)
                if done or not rows:
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                await asyncio.sleep(min(POLL_S, remaining))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("await_jobs: ledger unavailable", exc_info=True)
            return ToolResult(False, "", f"The jobs ledger is unavailable: {exc}")
        waited = round(time.monotonic() - started, 1)
        timed_out = bool(pending) and not (mode == "any" and settled)
        output: dict[str, Any] = {
            "finished": [_view(job) for job in settled],
            "still_running": [_view(job) for job in pending],
            "timed_out": timed_out,
            "waited_s": waited,
        }
        if unknown:
            output["unknown_ids"] = unknown
        if timed_out:
            output["note"] = (
                "The wait ran out. These jobs are still running; they are not done."
            )
        return ToolResult(True, output)


class TraceExplainTool:
    """Why a piece of work took this long and cost this much, from the trace tree."""

    name: str = "trace_explain"
    risk_tier: str = "safe"
    is_action_tool: bool = False
    description: str = (
        "Explain where the time and cost of a piece of work went. Give a job_id (from "
        "delegate_to_agent, spawn_worker, create_artifact...) or a turn_id. It reads the "
        "causal trace tree (lead turn, assignment, agent turn, mission or artifact) and "
        "returns a compact summary: elapsed time, cost, the longest chain, the slowest and "
        "costliest steps, and what failed or is still running. Read-only, instant, no model "
        "call."
    )
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "A job_id or a turn_id."},
            "job_id": {"type": "string", "description": "Same as id, for a job."},
            "turn_id": {"type": "string", "description": "Same as id, for a turn."},
        },
    }

    async def execute(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        from dodaios.orchestrator import traces

        args = args or {}
        target = str(args.get("id") or args.get("job_id") or args.get("turn_id") or "").strip()
        if not target:
            return ToolResult(False, "", "Give a job_id or a turn_id.")
        try:
            root = await asyncio.to_thread(traces.resolve_root, target)
            tree = await asyncio.to_thread(traces.build_tree, root) if root else None
        except Exception as exc:  # noqa: BLE001
            log.warning("trace_explain: trace stores unavailable", exc_info=True)
            return ToolResult(False, "", f"The trace stores are unavailable: {exc}")
        if tree is None:
            return ToolResult(False, "", f"No trace is recorded for {target}.")
        focus = target if target != root else ""
        # A job id is not always the node id (an assignment's node is its event id).
        job = jobs.get_ledger().get(target)
        if job is not None:
            focus = job.span_id or job.id
        return ToolResult(
            True,
            {"root": root, "summary": traces.explain(tree, focus), "nodes": tree["node_count"]},
        )


class JobStopTool:
    """Cancel a slow tool call that went on as a background job."""

    name: str = "job_stop"
    risk_tier: str = "monitor"
    is_action_tool: bool = True
    description: str = (
        "Stop a background job by its job_id. Use it for a slow tool call (a shell "
        "command, a browser task) that came back with started: true and that the "
        "person no longer wants, or that is stuck. The work is cancelled and the job "
        "ends as 'cancelled'. A job that already finished is reported as finished. "
        "Missions, artifacts and agent hand-offs are not stopped here."
    )
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "The job_id of the running job."},
        },
        "required": ["job_id"],
    }

    async def execute(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        job_id = str((args or {}).get("job_id") or "").strip()
        if not job_id:
            return ToolResult(False, "", "'job_id' is required.")
        from dodaios.orchestrator import async_tools

        try:
            outcome = async_tools.stop(job_id)
        except Exception as exc:  # noqa: BLE001
            log.warning("job_stop: ledger unavailable", exc_info=True)
            return ToolResult(False, "", f"The jobs ledger is unavailable: {exc}")
        if outcome == "unknown":
            return ToolResult(
                False, "",
                f"No stoppable background job {job_id}. Only slow tool calls that returned "
                "started: true can be stopped here.",
            )
        return ToolResult(True, {"job_id": job_id, "outcome": outcome})


__all__ = [
    "DEFAULT_AWAIT_S",
    "MAX_AWAIT_S",
    "AwaitJobsTool",
    "JobStatusTool",
    "JobStopTool",
    "TraceExplainTool",
]
