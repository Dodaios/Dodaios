"""``team_thread``: start, read and steer a team thread, for every lead seat.

A team thread (ADR-0042) gives two to six coding agents on different models one
task to plan, build and review together, with the person able to step in. Until
this tool the lead reached it only through ``run-app-action POST /api/team-threads``
and so never knew the feature existed. This is a thin wrapper over the same
routes the Team Threads view uses.

* ``start`` is an ask-tier action: it spends several model seats on one task.
  It returns the thread id and a ``job_id`` for ``job_status`` / ``await_jobs``.
* ``status`` is summary-first (state, phase, members, usage, open issues and the
  newest entries); ``after`` pages through the rest.
* ``answer`` posts the person's answer or a steer into the thread. When the
  thread waits on a disagreement the answer settles it with one more round.
"""

from __future__ import annotations

from typing import Any, Final

from dodaios.brain.lead_api import bounded, call_app_api, failure
from dodaios.core.protocols import ExecutionContext, ToolResult

_READS: Final[frozenset[str]] = frozenset({"seats", "list", "status"})
_CONTROLS: Final[frozenset[str]] = frozenset({"pause", "resume", "accept", "stop"})
_TEXT_CHARS = 1_500
_DEFAULT_TAIL = 6
_MAX_TAIL = 50
_HINT = "Ask for less: status with a smaller tail, or after=<last seq seen> for the next entries."


def _clip(text: Any, limit: int = _TEXT_CHARS) -> str:
    value = str(text or "")
    return value if len(value) <= limit else value[:limit] + f"… [+{len(value) - limit} chars]"


class TeamThreadTool:
    name = "team_thread"
    risk_tier = "ask"
    is_action_tool = True
    description = (
        "Team threads: several coding agents on different models plan, build and review ONE "
        "task together (for example Claude plans, Codex builds, Gemini reviews; or three "
        "models plan and compare). Use it when the person asks for several models, a second "
        "opinion across models, or plan-build-review on one task. actions: seats (which seats "
        "are ready), list, start (task + cwd; optional seats[], mode peers|planner_builder, "
        "title; asks the person first; returns team_id and a job_id: check it with job_status "
        "or await_jobs, never claim it done on your own), status (team_id; the state, who is "
        "working, the open issues and the newest entries; after=<seq> for later ones), answer "
        "(team_id + text: the person's answer or a steer; it settles a disagreement the thread "
        "waits on), pause, resume, accept (take the plan or work as it is), stop. For ONE "
        "agent's work use delegate_to_agent or workspace-orchestrate instead."
    )
    schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "seats",
                    "list",
                    "start",
                    "status",
                    "answer",
                    "pause",
                    "resume",
                    "accept",
                    "stop",
                ],
            },
            "task": {"type": "string", "description": "start: the task every member works on."},
            "cwd": {
                "type": "string",
                "description": (
                    "start: the project folder the team works in. Pass it for a task about a "
                    "repository; the chat's own folder is used when omitted."
                ),
            },
            "seats": {
                "type": "array",
                "maxItems": 6,
                "description": (
                    "start: the members, by seat id from `seats`. Omit for the default team "
                    "of the seats that are ready."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "provider": {"type": "string"},
                        "model": {"type": "string"},
                        "effort": {"type": "string"},
                        "role": {"type": "string", "enum": ["planner", "builder", "reviewer"]},
                    },
                    "required": ["provider"],
                },
            },
            "mode": {
                "type": "string",
                "enum": ["peers", "planner_builder"],
                "description": "start: peers (default) or planner_builder (roles per member).",
            },
            "title": {"type": "string", "description": "start: a short title."},
            "team_id": {"type": "string", "description": "status/answer/controls: the thread id."},
            "text": {"type": "string", "description": "answer: the message for the thread."},
            "after": {
                "type": "integer",
                "minimum": 0,
                "description": "status: only entries after this seq (pagination).",
            },
            "tail": {
                "type": "integer",
                "minimum": 1,
                "maximum": _MAX_TAIL,
                "description": f"status: how many newest entries (default {_DEFAULT_TAIL}).",
            },
        },
        "required": ["action"],
    }

    def risk_tier_for_args(self, args: dict[str, Any]) -> str:
        action = args.get("action")
        if action in _READS:
            return "safe"
        return "ask" if action == "start" else "monitor"

    def read_only_for_args(self, args: dict[str, Any]) -> bool:
        return args.get("action") in _READS

    def describe_args(self, args: dict[str, Any]) -> dict[str, str]:
        action = str(args.get("action") or "")
        out = {"level": "read" if action in _READS else "modify"}
        if action == "start":
            out["task"] = _clip(args.get("task"), 240)
            seats = [
                str(s.get("provider") or "") for s in args.get("seats") or [] if isinstance(s, dict)
            ]
            if seats:
                out["agent"] = ", ".join(seats)
        elif args.get("team_id"):
            out["task"] = str(args["team_id"])
        return out

    async def execute(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        action = str(args.get("action") or "")
        if action == "seats":
            return await self._get("The seats", "/api/team-threads/seats", None, self._seats)
        if action == "list":
            return await self._get("The team threads", "/api/team-threads", None, self._list)
        if action == "start":
            return await self._start(args, ctx)
        if action not in {"status", "answer", *_CONTROLS}:
            return ToolResult(success=False, output=None, error=f"Unknown action {action!r}.")
        team_id = str(args.get("team_id") or "").strip()
        if not team_id:
            return ToolResult(
                success=False,
                output=None,
                error=f"{action} needs team_id (see action list).",
            )
        if action == "status":
            tail = min(max(int(args.get("tail") or _DEFAULT_TAIL), 1), _MAX_TAIL)
            after = max(int(args.get("after") or 0), 0)
            return await self._get(
                "The team thread",
                f"/api/team-threads/{team_id}",
                {"after": after} if after else None,
                lambda data: self._status(data, tail=tail, paged=bool(after)),
            )
        if action == "answer":
            text = str(args.get("text") or "").strip()
            if not text:
                return ToolResult(success=False, output=None, error="answer needs text.")
            status, data = await call_app_api(
                "POST", f"/api/team-threads/{team_id}/message", body={"text": text}
            )
        else:
            status, data = await call_app_api("POST", f"/api/team-threads/{team_id}/{action}")
        if status is None or status >= 400:
            return failure(f"Team thread {action}", status, data)
        return ToolResult(
            success=True,
            output=bounded(self._status(data, tail=_DEFAULT_TAIL, paged=False), hint=_HINT),
        )

    async def _get(
        self, what: str, path: str, query: dict[str, Any] | None, shape: Any
    ) -> ToolResult:
        status, data = await call_app_api("GET", path, query=query)
        if status is None or status >= 400:
            return failure(what, status, data)
        return ToolResult(success=True, output=bounded(shape(data), hint=_HINT))

    async def _start(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        task = str(args.get("task") or "").strip()
        if not task:
            return ToolResult(success=False, output=None, error="start needs a task.")
        cwd = str(args.get("cwd") or "").strip() or str((ctx.config or {}).get("cwd") or "")
        if not cwd:
            from dodaios.core.paths import chat_workspace_dir

            cwd = str(chat_workspace_dir())
        body: dict[str, Any] = {"task": task, "cwd": cwd}
        for key in ("seats", "mode", "title"):
            if args.get(key):
                body[key] = args[key]
        status, data = await call_app_api("POST", "/api/team-threads", body=body)
        if status is None or status >= 400:
            return failure("Starting the team thread", status, data)
        shaped = self._status(data, tail=_DEFAULT_TAIL, paged=False)
        if isinstance(data, dict) and data.get("job_id"):
            shaped["job_id"] = data["job_id"]
            shaped["next"] = (
                "The team works in the background. Check job_id with job_status or await_jobs "
                "before telling the person it is done."
            )
        return ToolResult(success=True, output=bounded(shaped, hint=_HINT))

    @staticmethod
    def _seats(data: Any) -> dict[str, Any]:
        data = data if isinstance(data, dict) else {}
        return {
            "seats": [
                {
                    key: row.get(key)
                    for key in ("provider", "label", "model", "ready", "family")
                    if key in row
                }
                for row in data.get("seats") or []
                if isinstance(row, dict)
            ],
            "default": data.get("default") or [],
            "min_members": data.get("min_members"),
            "max_members": data.get("max_members"),
        }

    @staticmethod
    def _list(data: Any) -> dict[str, Any]:
        rows = data.get("threads") if isinstance(data, dict) else []
        return {
            "threads": [
                {
                    "team_id": t.get("team_id"),
                    "title": t.get("title"),
                    "state": t.get("state"),
                    "phase": t.get("phase"),
                    "reason": t.get("reason"),
                    "mode": t.get("mode"),
                    "members": [m.get("name") for m in t.get("members") or []],
                    "updated_ms": t.get("updated_ms"),
                }
                for t in rows or []
                if isinstance(t, dict)
            ]
        }

    @staticmethod
    def _status(data: Any, *, tail: int, paged: bool) -> dict[str, Any]:
        data = data if isinstance(data, dict) else {}
        entries = [e for e in data.get("entries") or [] if isinstance(e, dict)]
        shown = entries[:tail] if paged else entries[-tail:]
        out: dict[str, Any] = {
            key: data.get(key)
            for key in (
                "team_id",
                "title",
                "mode",
                "state",
                "phase",
                "reason",
                "note",
                "usage",
                "rounds",
                "builder",
                "issues",
            )
            if key in data
        }
        out["task"] = _clip(data.get("task"), 600)
        out["members"] = [
            {
                key: m.get(key)
                for key in ("name", "provider", "model", "role", "state", "working", "waiting")
            }
            for m in data.get("members") or []
            if isinstance(m, dict)
        ]
        out["entries"] = [
            {
                "seq": e.get("seq"),
                "kind": e.get("kind"),
                "author": e.get("author"),
                "phase": e.get("phase"),
                "text": _clip((e.get("payload") or {}).get("text")),
            }
            for e in shown
        ]
        out["entries_total"] = len(entries)
        if len(entries) > len(shown):
            out["more"] = "Older entries exist; call status with after=<seq> to page forward."
        return out
