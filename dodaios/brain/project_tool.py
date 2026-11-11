"""``project``: the lead's long-horizon work, tracked across hours, days and sessions.

When the owner asks for multi-step or multi-day work, the lead creates a project: the
goal, the success criteria and a plan of sub-goals (who does each, what it waits for, what
evidence proves it). Sub-goals run as ordinary jobs; ``link`` attaches the ``job_id`` a
hand-off returned. Progress is read from the jobs ledger (and ``verify_delegate`` where a
sub-goal asks for verified evidence), never from what a model claims. A review runs on its
own and writes one short line into this conversation only when something changed or the
owner must decide. ``close`` completes the project only when every sub-goal is done and an
independent evaluator judges the success criteria met on that evidence.
"""

from __future__ import annotations

import logging
from typing import Any, Final

from dodaios.core.protocols import ExecutionContext, ToolResult
from dodaios.projects.engine import ProjectError, get_engine

log = logging.getLogger(__name__)

_READS: Final[frozenset[str]] = frozenset({"status", "list"})
_ACTIONS: Final[tuple[str, ...]] = (
    "create", "plan", "link", "note", "status", "list", "pause", "resume", "close",
)

_SUBGOAL_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "id": {"type": "string", "description": "Short stable id, e.g. s1."},
        "title": {"type": "string", "description": "What this sub-goal delivers."},
        "owner": {
            "type": "string",
            "description": "lead, agent:<name>, pane:<id>, team (a team thread) or owner.",
        },
        "depends_on": {"type": "array", "items": {"type": "string"}},
        "evidence": {
            "type": "string",
            "enum": ["job", "verified", "owner"],
            "description": (
                "What proves it done: job (the job's own record), verified (that plus "
                "verify_delegate: use it when the result matters) or owner (only the "
                "owner can confirm)."
            ),
        },
    },
    "required": ["id", "title"],
}


class ProjectTool:
    name = "project"
    risk_tier = "monitor"
    is_action_tool = False
    description = (
        "Long-horizon projects: use when the owner asks for multi-step or multi-day work. "
        "actions: create (title, goal, criteria[] = how we know it is met, subgoals[] with id, "
        "title, owner, depends_on, evidence), plan (project_id + subgoals[] to add or edit "
        "pending ones, drop[] to skip, criteria[]), link (project_id, subgoal_id, job_id: "
        "attach the job you started for a ready sub-goal), note, status (project_id: refreshes "
        "from the jobs ledger and says which sub-goals are ready; without project_id lists "
        "open projects), pause, resume, close (outcome complete: only when every sub-goal is "
        "done and an independent check says the criteria are met, else it tells what is "
        "missing; outcome abandon asks the owner first). Sub-goals are started with the usual "
        "tools (delegate_to_agent, workspace-orchestrate, team_thread): link their job_id. "
        "You cannot mark a sub-goal done: only job evidence can."
    )
    schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "action": {"type": "string", "enum": list(_ACTIONS)},
            "project_id": {"type": "string"},
            "title": {"type": "string", "description": "create: a short project name."},
            "goal": {"type": "string", "description": "create: the owner's goal in their terms."},
            "criteria": {
                "type": "array",
                "items": {"type": "string"},
                "description": "create/plan: observable success criteria.",
            },
            "subgoals": {"type": "array", "items": _SUBGOAL_SCHEMA},
            "drop": {"type": "array", "items": {"type": "string"}},
            "subgoal_id": {"type": "string", "description": "link/note: the sub-goal."},
            "job_id": {"type": "string", "description": "link: the job_id a hand-off returned."},
            "text": {"type": "string", "description": "note: why, or what to try next."},
            "outcome": {"type": "string", "enum": ["complete", "abandon"]},
            "reason": {"type": "string", "description": "close abandon: why."},
            "review_every_hours": {
                "type": "integer",
                "minimum": 1,
                "description": "create: how often the review runs (default 24).",
            },
            "stall_days": {
                "type": "integer",
                "minimum": 1,
                "description": "create: days without progress before the watchdog flags it (3).",
            },
        },
        "required": ["action"],
    }

    def risk_tier_for_args(self, args: dict[str, Any]) -> str:
        if args.get("action") in _READS:
            return "safe"
        return "ask" if args.get("action") == "close" and args.get("outcome") == "abandon" else (
            "monitor"
        )

    def read_only_for_args(self, args: dict[str, Any]) -> bool:
        return args.get("action") in _READS

    def describe_args(self, args: dict[str, Any]) -> dict[str, str]:
        action = str(args.get("action") or "")
        out = {"level": "read" if action in _READS else "modify"}
        if args.get("title") or args.get("goal"):
            out["task"] = str(args.get("title") or args.get("goal"))[:240]
        elif args.get("project_id"):
            out["task"] = str(args["project_id"])
        return out

    async def execute(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        from dodaios.orchestrator import jobs

        args = args or {}
        action = str(args.get("action") or "")
        if action not in _ACTIONS:
            return ToolResult(False, "", f"'action' must be one of: {', '.join(_ACTIONS)}.")
        session, _turn = jobs.owner_of(ctx)
        engine = get_engine()
        pid = str(args.get("project_id") or "").strip()
        try:
            return ToolResult(True, await self._run(engine, action, pid, args, session))
        except ProjectError as exc:  # a refusal the model reads in the tool result
            return ToolResult(False, "", str(exc))
        except Exception as exc:  # noqa: BLE001 - the project store is a courtesy surface
            log.warning("project tool: %s failed", action, exc_info=True)
            return ToolResult(False, "", f"The projects store is unavailable: {exc}")

    @staticmethod
    async def _run(engine: Any, action: str, pid: str, args: dict[str, Any], session: str) -> Any:
        if action == "list" or (action == "status" and not pid):
            return {"projects": engine.summaries()}
        if action == "create":
            goal = str(args.get("goal") or "").strip()
            if not goal:
                raise ProjectError("create needs a goal.")
            hours = args.get("review_every_hours")
            project = engine.create(
                title=str(args.get("title") or ""),
                goal=goal,
                criteria=list(args.get("criteria") or []),
                subgoals=list(args.get("subgoals") or []),
                owner_session=session,
                review_every_s=int(hours) * 3600 if hours else None,
                stall_days=args.get("stall_days"),
            )
            view = engine.view(project)
            if not project.criteria:
                view["hint"] = "No success criteria yet: add them with plan, or it cannot close."
            return view
        if not pid:
            raise ProjectError(f"{action} needs a project_id.")
        if action == "status":
            return await engine.status(pid)
        if action == "plan":
            project = await engine.plan(
                pid,
                subgoals=args.get("subgoals"),
                drop=args.get("drop"),
                criteria=args.get("criteria"),
                session=session,
            )
            return engine.view(project)
        if action == "link":
            project = await engine.link_job(
                pid, str(args.get("subgoal_id") or ""), str(args.get("job_id") or ""),
                session=session,
            )
            return engine.view(project)
        if action == "note":
            project = await engine.note(
                pid, str(args.get("subgoal_id") or ""), str(args.get("text") or ""),
                session=session,
            )
            return engine.view(project)
        if action in ("pause", "resume"):
            project = await engine.set_status(pid, "paused" if action == "pause" else "active")
            return engine.view(project)
        outcome = str(args.get("outcome") or "complete")
        result = await engine.close(
            pid, outcome, reason=str(args.get("reason") or ""), session=session
        )
        return result.to_dict()


__all__ = ["ProjectTool"]
