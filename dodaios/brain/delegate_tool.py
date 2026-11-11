"""``delegate``: the lead's one front door for handing work to someone else.

The lead used to choose between a dozen overlapping hand-off tools
(``delegate_to_agent``, ``workspace-orchestrate``, ``team_thread``,
``spawn_worker``, ``society-create-routine``, ``run-skill``, ...). Every overlap
was a routing decision a model could get wrong, and keyword gates then
overrode the model silently. ``delegate`` makes the decision explicit and typed:

``target`` says WHO gets the work:

* ``agent:<id or name>``: a named agent of the user's team (name resolution and
  the clarification question are the ones ``delegate_to_agent`` already has;
  ``agent`` alone lets the lead pick the agent whose hands fit);
* ``pane:<stable id>``: a coding pane of the Agentic IDE, by terminal id or call-sign;
* ``team_thread``: several coding agents on different models plan, build and
  review one task together;
* ``mission``: one background frontier worker in its own checkout;
* ``routine``: work on a schedule for an agent;
* ``skill:<slug>``: an installed skill's instructions, loaded for this turn.

The tool validates the target, routes to the existing specialised
implementation (which keeps its gates, approval tier and idempotency), and
ALWAYS answers ``{job_id, target, state}``. A job id comes from the jobs ledger
(:mod:`dodaios.orchestrator.jobs`); a hand-off the implementation did not
ledger gets a row here, so the lead always has a handle for ``job_status`` and
``await_jobs``. A refused or unresolved hand-off has no job: ``job_id`` is
``null`` and ``state`` says why (``needs_clarification``, ``refused``, ``failed``).

``wait: until_done`` then waits on that job with ``await_jobs`` (bounded by
``wait_timeout_s``); a wait that runs out reports the job as still running.

The specialised tools stay registered: voice and the other surfaces keep them.
On the lead they are reached through ``find_tools`` and through this tool.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping
from typing import Any, Final

from dodaios.core.protocols import ExecutionContext, ToolResult
from dodaios.orchestrator import jobs
from dodaios.society.communication import REPLY_POLICY_SCHEMA

log = logging.getLogger(__name__)

__all__ = [
    "DELEGATE_NAME",
    "DELEGATE_OVERLAPS",
    "DelegateTool",
    "parse_target",
]

DELEGATE_NAME: Final[str] = "delegate"

#: Tools ``delegate`` routes to. On the lead surfaces they leave the direct set
#: and sit behind ``find_tools``; every other surface keeps them as they were.
DELEGATE_OVERLAPS: Final[tuple[str, ...]] = (
    "spawn_worker",
    "delegate_to_agent",
    "message_agent",
    "ask_agent",
    "create_artifact",
    "living_page",
    "workspace-orchestrate",
    "team_thread",
    "society-create-routine",
    "run_skill",
)

TARGET_KINDS: Final[tuple[str, ...]] = (
    "agent",
    "pane",
    "team_thread",
    "mission",
    "routine",
    "skill",
)
#: Kinds that need nothing after the colon, and the words that mean them.
_BARE_KINDS: Final[Mapping[str, str]] = {
    "team_thread": "team_thread",
    "team-thread": "team_thread",
    "team": "team_thread",
    "mission": "mission",
    "routine": "routine",
    "agent": "agent",
}
_MAX_WAIT_S: Final[float] = 540.0
_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_JOB_TEXT_RE = re.compile(r"job_id:\s*(job_[0-9a-f]+)")

#: The tool that implements each kind (hyphen/underscore spellings both tried).
_IMPLEMENTATION: Final[Mapping[str, tuple[str, ...]]] = {
    "agent": ("delegate_to_agent", "delegate-to-agent"),
    "pane": ("workspace-orchestrate", "workspace_orchestrate"),
    "team_thread": ("team_thread", "team-thread"),
    "mission": ("spawn_worker", "spawn-worker"),
    "routine": ("society-create-routine", "society_create_routine"),
    "skill": ("run_skill", "run-skill"),
}
#: The jobs-ledger kind a hand-off gets when its implementation wrote no row.
_LEDGER_KIND: Final[Mapping[str, str]] = {
    "agent": "society_assignment",
    "pane": "ide_submission",
    "team_thread": "team_thread",
    "mission": "mission",
    "routine": "routine",
    "skill": "mission",
}


def parse_target(raw: Any) -> tuple[str, str] | str:
    """``(kind, ref)`` for a typed target, or the reason it is not one.

    ``ref`` is empty for the kinds that take none and for a bare ``agent``.
    """
    text = str(raw or "").strip()
    if not text:
        return (
            "target is required: agent:<name>, pane:<id>, team_thread, mission, routine "
            "or skill:<slug>."
        )
    head, sep, tail = text.partition(":")
    kind = head.strip().lower().replace(" ", "_")
    ref = tail.strip()
    if kind in ("agent", "pane", "skill"):
        if kind in ("pane", "skill") and not ref:
            what = "id" if kind == "pane" else "slug"
            return f"target '{kind}' needs what comes after the colon ({kind}:<{what}>)."
        if kind == "skill" and not _SLUG_RE.match(ref):
            return f"'{ref}' is not a skill slug."
        return kind, ref
    bare = _BARE_KINDS.get(kind.replace("-", "_")) or _BARE_KINDS.get(kind)
    if bare and not ref:
        return bare, ""
    if bare and ref:
        return f"target '{bare}' takes nothing after the colon; got '{ref}'."
    return (
        f"unknown target '{text}'. Use agent:<name>, pane:<id>, team_thread, mission, "
        "routine or skill:<slug>."
    )


def _canonical(name: str) -> str:
    return name.strip().lower().replace("-", "_")


def _find_job_id(value: Any, depth: int = 0) -> str | None:
    """The job id an implementation put in its result, wherever it put it."""
    if depth > 4:
        return None
    if isinstance(value, dict):
        direct = value.get("job_id")
        if isinstance(direct, str) and direct.strip():
            return direct.strip()
        for item in value.values():
            found = _find_job_id(item, depth + 1)
            if found:
                return found
    elif isinstance(value, (list, tuple)):
        for item in value:
            found = _find_job_id(item, depth + 1)
            if found:
                return found
    elif isinstance(value, str):
        match = _JOB_TEXT_RE.search(value)
        if match:
            return match.group(1)
    return None


def _first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


class DelegateTool:
    """Hand work to an agent, a pane, a team thread, a mission, a routine or a skill."""

    name: str = DELEGATE_NAME
    risk_tier: str = "monitor"
    is_action_tool: bool = True
    description: str = (
        "THE way to hand work to someone else. Pick the target, give the task, get a job_id "
        "back. target: 'agent:<name>' (one of the user's named team agents; 'agent' alone "
        "lets the lead pick the best fit), 'pane:<terminal id or call-sign>' (a coding agent "
        "already open in the Agentic IDE), 'team_thread' (several coding agents on different "
        "models plan, build and review one task; asks the person first), 'mission' (one "
        "background worker in its own checkout, for a real work product), 'routine' (work on a "
        "schedule: options.agent, options.title, options.schedule), 'skill:<slug>' (load an "
        "installed skill's instructions to follow now). Always returns {job_id, target, "
        "state}: the handle for job_status, await_jobs and verify_delegate. Never say the work "
        "is done from this result: it only says it was handed over. wait='until_done' also "
        "waits up to wait_timeout_s seconds on that job and reports what the job's own record "
        "says; a wait that runs out reports it as still running. A name that is not clearly "
        "one agent returns needs_clarification with a question to ask first. Not for answers "
        "you can give yourself, knowledge questions, or status reads (work_board, "
        "society_status). Turn the user's intent into a brief: objective, known target, "
        "context, constraints and completion evidence. Target-specific extras go in options "
        "(pane: workspace_id, request_id, while_busy; team_thread: cwd, seats, mode, title; "
        "mission: action; routine: agent, title, schedule, announce_on_success; "
        "agent: refs)."
    )
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "description": (
                    "agent:<id or name> | pane:<stable id or call-sign> | team_thread | "
                    "mission | routine | skill:<slug>"
                ),
            },
            "task": {
                "type": "string",
                "description": (
                    "The actionable brief: objective, scope, constraints, completion evidence."
                ),
            },
            "context": {
                "type": "string",
                "description": "Relevant prior decisions and facts; omit secrets.",
            },
            "completion_criteria": {
                "type": "string",
                "description": "The output required and the evidence that shows it is done.",
            },
            "reply": REPLY_POLICY_SCHEMA,
            "wait": {
                "type": "string",
                "enum": ["none", "until_done"],
                "description": (
                    "none (default): return the job_id now. until_done: also wait on the job "
                    "for up to wait_timeout_s seconds."
                ),
            },
            "wait_timeout_s": {
                "type": "number",
                "description": f"With wait=until_done: seconds to wait, 1 to {int(_MAX_WAIT_S)}.",
            },
            "options": {
                "type": "object",
                "description": "Target-specific extras, see the tool description.",
            },
        },
        "required": ["target", "task"],
    }

    def __init__(
        self,
        sources: Callable[[], Mapping[str, Any]],
        *,
        store_resolver: Callable[[], Any | None] | None = None,
    ) -> None:
        self._sources = sources
        self._store_resolver = store_resolver

    # -- approval tier follows the implementation ---------------------------------

    def risk_tier_for_args(self, args: dict[str, Any]) -> str:
        parsed = parse_target((args or {}).get("target"))
        if isinstance(parsed, tuple) and parsed[0] == "team_thread":
            return "ask"  # several model seats on one task
        return self.risk_tier

    def describe_args(self, args: dict[str, Any]) -> dict[str, str]:
        return {
            "target": str((args or {}).get("target") or ""),
            "task": str((args or {}).get("task") or "")[:240],
        }

    # -- execution ----------------------------------------------------------------

    async def execute(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        args = args or {}
        invalid = self._validate(args)
        if isinstance(invalid, ToolResult):
            return invalid
        kind, ref, wait, timeout = invalid
        tool = self._implementation(kind)
        target = f"{kind}:{ref}" if ref else kind
        if tool is None:
            return _answer(
                target, "failed", None, False, error=f"The {kind} hand-off is not available here."
            )
        dispatch_args = {
            k: args.get(k)
            for k in ("target", "task", "context", "completion_criteria", "reply", "options")
            if args.get(k) not in (None, "", {})
        }

        async def dispatch() -> ToolResult:
            return await self._route(kind, ref, tool, args, ctx)

        result = await self._once(dispatch_args, ctx, dispatch)
        output = result.output if isinstance(result.output, dict) else {}
        if wait == "until_done" and isinstance(output.get("job_id"), str):
            output = await self._wait(output, timeout)
            return ToolResult(
                success=result.success, output=output, artifacts=result.artifacts
            )
        return result

    def _validate(self, args: dict[str, Any]) -> tuple[str, str, str, float] | ToolResult:
        parsed = parse_target(args.get("target"))
        if isinstance(parsed, str):
            return ToolResult(False, None, parsed)
        if not str(args.get("task") or "").strip():
            return ToolResult(False, None, "task is required: say what the work is.")
        wait = str(args.get("wait") or "none").strip().lower()
        if wait not in ("none", "until_done"):
            return ToolResult(False, None, "wait must be 'none' or 'until_done'.")
        raw_timeout = args.get("wait_timeout_s")
        try:
            timeout = float(raw_timeout) if raw_timeout is not None else 60.0
        except (TypeError, ValueError):  # the model is told, in the result, to send seconds
            return ToolResult(False, None, "wait_timeout_s must be a number of seconds.")
        options = args.get("options")
        if options is not None and not isinstance(options, dict):
            return ToolResult(False, None, "options must be an object.")
        return parsed[0], parsed[1], wait, min(max(timeout, 1.0), _MAX_WAIT_S)

    def _implementation(self, kind: str) -> Any | None:
        tools = self._sources()
        by_name = {_canonical(name): tool for name, tool in tools.items()}
        for name in _IMPLEMENTATION[kind]:
            tool = by_name.get(_canonical(name))
            if tool is not None:
                return tool
        return None

    async def _once(
        self, dispatch_args: dict[str, Any], ctx: ExecutionContext, run: Callable[[], Any]
    ) -> ToolResult:
        """A repeat of the same hand-off in one turn gets the first receipt."""
        store = None
        if self._store_resolver is not None:
            try:
                store = self._store_resolver()
            except Exception:  # noqa: BLE001 - no society store means no deduplication
                log.debug("delegate: no idempotency store", exc_info=True)
        if store is None:
            return await run()
        from dodaios.society.idempotency import idempotency_key, run_once

        return await run_once(store, idempotency_key(ctx, DELEGATE_NAME, dispatch_args), run)

    async def _wait(self, output: dict[str, Any], wait_s: float) -> dict[str, Any]:
        from dodaios.plugins.tool.job_tools import AwaitJobsTool

        job_id = str(output["job_id"])
        waited = await AwaitJobsTool().execute(
            {"ids": [job_id], "timeout_s": wait_s}, None  # type: ignore[arg-type]
        )
        data = waited.output if isinstance(waited.output, dict) else {}
        rows = [*(data.get("finished") or []), *(data.get("still_running") or [])]
        row = next((r for r in rows if isinstance(r, dict) and r.get("job_id") == job_id), None)
        merged = {**output, "wait": data}
        if row:
            merged["state"] = row.get("state", merged.get("state"))
            for key in ("summary", "result_ref", "error"):
                if row.get(key):
                    merged[key] = row[key]
        return merged

    # -- routing ------------------------------------------------------------------

    async def _route(
        self, kind: str, ref: str, tool: Any, args: dict[str, Any], ctx: ExecutionContext
    ) -> ToolResult:
        task = str(args.get("task") or "").strip()
        options = dict(args.get("options") or {})
        context = str(args.get("context") or "").strip()
        criteria = str(args.get("completion_criteria") or "").strip()
        target = f"{kind}:{ref}" if ref else kind
        if kind == "agent":
            under = {
                "agent": ref,
                "task": task,
                **({"context": context} if context else {}),
                **({"completion_criteria": criteria} if criteria else {}),
                **({"reply_policy": args["reply"]} if args.get("reply") else {}),
                **({"refs": options["refs"]} if options.get("refs") else {}),
            }
        elif kind == "pane":
            return await self._route_pane(ref, tool, task, criteria, context, options, ctx)
        elif kind == "team_thread":
            under = {
                "action": "start",
                "task": _brief(task, context, criteria),
                **{k: options[k] for k in ("cwd", "seats", "mode", "title") if k in options},
            }
        elif kind == "mission":
            under = {
                "utterance": task,
                "context_hints": [h for h in (context, criteria) if h],
                "action": str(options.get("action") or task[:80]),
                "target": str(options.get("target") or ""),
            }
        elif kind == "routine":
            under = {
                "agent_id": str(options.get("agent") or options.get("agent_id") or ""),
                "title": str(options.get("title") or task[:80]),
                "prompt": _brief(task, context, criteria),
                "schedule": options.get("schedule"),
                **(
                    {"announce_on_success": options["announce_on_success"]}
                    if options.get("announce_on_success")
                    else {}
                ),
            }
            missing = [k for k in ("agent_id", "schedule") if not under.get(k)]
            if missing:
                return _answer(
                    target,
                    "needs_clarification",
                    None,
                    False,
                    error="A routine needs options.agent and options.schedule.",
                    detail={"missing": ["agent" if m == "agent_id" else m for m in missing]},
                )
        else:  # skill
            under = {"skill_name": ref, "args": {"task": task}}
        return await self._call(kind, target, tool, under, ctx, summary_task=task)

    async def _route_pane(
        self,
        ref: str,
        tool: Any,
        task: str,
        criteria: str,
        context: str,
        options: dict[str, Any],
        ctx: ExecutionContext,
    ) -> ToolResult:
        """Resolve the pane first (that is the validation), then send under its request id."""
        target = f"pane:{ref}"
        scope = {k: options[k] for k in ("workspace_id", "workspace", "project_id", "project")
                 if options.get(k)}
        resolved = await _run(tool, {"action": "resolve", "terminal_id": ref, **scope}, ctx)
        data = resolved.output if isinstance(resolved.output, dict) else {}
        if not resolved.success or data.get("status") != "resolved":
            status = str(data.get("status") or "failed")
            state = "needs_clarification" if status == "needs_clarification" else "failed"
            return _answer(
                target, state, None, False,
                error=_first_text(data.get("reason"), resolved.error)
                or "The pane did not resolve.",
                detail=data or None,
            )
        found = data.get("target") if isinstance(data.get("target"), dict) else {}
        send: dict[str, Any] = {
            "action": "send",
            **found,
            "request_id": options.get("request_id") or data.get("request_id"),
            "prompt": _brief(task, context, criteria),
            **{k: options[k] for k in ("while_busy", "image_refs") if k in options},
        }
        return await self._call("pane", target, tool, send, ctx, summary_task=task)

    async def _call(
        self,
        kind: str,
        target: str,
        tool: Any,
        under: dict[str, Any],
        ctx: ExecutionContext,
        *,
        summary_task: str,
    ) -> ToolResult:
        try:
            result = await _run(tool, under, ctx)
        except Exception as exc:  # noqa: BLE001 - a failed hand-off is a result, not a crash
            log.warning("delegate: %s hand-off raised", kind, exc_info=True)
            return _answer(target, "failed", None, False, error=f"{type(exc).__name__}: {exc}")
        data = result.output if isinstance(result.output, dict) else None
        artifacts_id = _find_job_id(list(result.artifacts))
        job_id = _find_job_id(result.output) or artifacts_id
        if not result.success:
            status = str((data or {}).get("status") or (data or {}).get("state") or "")
            state = (
                "needs_clarification"
                if status == "needs_clarification"
                else "refused" if status == "refused" else "failed"
            )
            return _answer(
                target, state, job_id, False,
                error=result.error or _first_text(result.output),
                detail=data if data is not None else result.output,
            )
        if not job_id:
            job_id = self._ledger_fallback(kind, target, summary_task, ctx, under)
        state = str((data or {}).get("state") or "running")
        if state not in jobs.STATES:
            state = "running"
        if kind == "routine" and job_id:
            jobs.finish(job_id, "done", summary="The routine is scheduled.")
            state = "done"
        if kind == "skill" and job_id:
            jobs.finish(job_id, "done", summary=f"Instructions of {target} loaded for this turn.")
            state = "done"
        return _answer(
            target, state, job_id, True, detail=data if data is not None else result.output,
            artifacts=result.artifacts,
        )

    @staticmethod
    def _ledger_fallback(
        kind: str, target: str, task: str, ctx: ExecutionContext, under: dict[str, Any]
    ) -> str | None:
        """A job row for a hand-off whose implementation wrote none."""
        state = "running" if kind in ("mission", "team_thread", "agent") else "blocked"
        job_id = jobs.start(
            _LEDGER_KIND[kind], target=target, title=task[:120], ctx=ctx, state=state,
        )
        if job_id and state == "blocked":
            jobs.finish(
                job_id,
                "blocked",
                summary="Handed over; the implementation recorded no completion evidence.",
            )
        return job_id


def _brief(task: str, context: str, criteria: str) -> str:
    brief = task
    if context:
        brief += "\n\nRelevant context:\n" + context
    if criteria:
        brief += "\n\nCompletion criteria:\n" + criteria
    return brief


async def _run(tool: Any, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
    clean = {k: v for k, v in args.items() if v is not None}
    return await tool.execute(clean, ctx)


def _answer(
    target: str,
    state: str,
    job_id: str | None,
    success: bool,
    *,
    error: str = "",
    detail: Any = None,
    artifacts: tuple[Any, ...] = (),
) -> ToolResult:
    output: dict[str, Any] = {"job_id": job_id, "target": target, "state": state}
    if error:
        output["error"] = error
    if detail is not None:
        output["detail"] = detail
    if success and job_id:
        output["next_step"] = (
            "Handed over, not done. Check job_status or await_jobs before you say it is finished."
        )
    return ToolResult(
        success=success, output=output, error=None if success else (error or state),
        artifacts=artifacts,
    )
