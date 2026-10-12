"""The three tools of a team lead: assign, board, report.

Offered only in the chats of an agent that currently leads a team
(``surface.society_tools``). None of them starts work by itself:
``society_team_assign`` appends ONE ``ASSIGN`` to the board on the lead's
behalf, and the scheduler — trusted Python — decides whether the member
starts (tier wall, depth, budgets, concurrency). The lifecycle is then read
off the board by ``team_lead.TeamLeads``, which also wakes the lead when a
result arrives, so a lead never waits or polls inside a turn.
"""

from __future__ import annotations

from typing import Any, Final

from jarvis.core.protocols import ToolResult

from .team_lead import TeamLeadError

__all__ = [
    "TEAM_ASSIGN_TOOL_NAME",
    "TEAM_BOARD_TOOL_NAME",
    "TEAM_REPORT_TOOL_NAME",
    "TeamAssignTool",
    "TeamBoardTool",
    "TeamReportTool",
    "team_lead_tools",
]

TEAM_ASSIGN_TOOL_NAME: Final[str] = "society_team_assign"
TEAM_BOARD_TOOL_NAME: Final[str] = "society_team_board"
TEAM_REPORT_TOOL_NAME: Final[str] = "society_team_report"

_MAX_BRIEF: Final[int] = 20_000
_REPORT_STATUSES: Final[tuple[str, ...]] = ("progress", "needs_input", "done", "failed")


def _refused(exc: TeamLeadError) -> ToolResult:
    return ToolResult(success=False, output={"refused": str(exc)}, error=str(exc))


class TeamAssignTool:
    """Hand one task to one member of the team the caller leads."""

    name: str = TEAM_ASSIGN_TOOL_NAME
    # Internal coordination, like a message to a teammate: the scheduler's
    # budgets and caps gate the work, not a card in a chat nobody is watching.
    risk_tier: str = "safe"
    description: str = (
        "Hand ONE task to ONE member of the team you lead. The member works on it in their "
        "own chat, in the background; this call returns at once with the task's state. You "
        "are woken automatically with the result, so never wait or poll after assigning. "
        "Call it once per task, and give every task that can start now in the same turn: "
        "members work in parallel. A busy member is fine: the task starts by itself when "
        "they are free. Write an independently actionable brief, not a paraphrase of the "
        "goal: the objective, what you already know, the scope, and what output proves the "
        "task is done. Never invent URLs, paths, credentials or decisions."
    )
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "member": {
                "type": "string",
                "description": "The member's name as listed for your team.",
            },
            "title": {
                "type": "string",
                "description": "A short name for the task, shown on the team board.",
            },
            "task": {
                "type": "string",
                "description": "The objective and scope of the task, self-contained.",
            },
            "context": {
                "type": "string",
                "description": "Known facts, earlier results and constraints the member needs.",
            },
            "completion_criteria": {
                "type": "string",
                "description": "The output and evidence that establish the task is done.",
            },
        },
        "required": ["member", "title", "task"],
    }
    is_action_tool: bool = True

    def __init__(self, runtime: Any, agent_id: str) -> None:
        self._runtime = runtime
        self._agent_id = agent_id

    async def execute(self, args: dict[str, Any], ctx: Any) -> ToolResult:
        title = str(args.get("title") or "").strip()
        brief = str(args.get("task") or "").strip()
        context = str(args.get("context") or "").strip()
        criteria = str(args.get("completion_criteria") or "").strip()
        if context:
            brief += "\n\nRelevant context:\n" + context
        if criteria:
            brief += "\n\nCompletion criteria:\n" + criteria
        if len(brief) > _MAX_BRIEF:
            return ToolResult(success=False, output=None, error="the task brief exceeds its limit")
        try:
            outcome = await self._runtime.team_leads.assign(
                self._agent_id,
                member=str(args.get("member") or ""),
                title=title,
                brief=brief,
            )
        except TeamLeadError as exc:
            return _refused(exc)
        return ToolResult(
            success=outcome["state"] != "blocked",
            output={
                **outcome,
                "next": "End your turn after assigning; the result wakes you. "
                "This receipt is the start of the task, not its completion.",
            },
            error=outcome["note"] if outcome["state"] == "blocked" else None,
        )


class TeamBoardTool:
    """The caller's team at a glance: mission, members, goals, tasks, results."""

    name: str = TEAM_BOARD_TOOL_NAME
    risk_tier: str = "safe"
    description: str = (
        "Read the board of the team you lead: its mission, who is on it and whether they are "
        "free, every open goal, and each task with its state and result. Read-only. Use it "
        "to check where a goal stands before deciding, never to wait for a result."
    )
    schema: dict[str, Any] = {"type": "object", "properties": {}}

    def __init__(self, runtime: Any, agent_id: str) -> None:
        self._runtime = runtime
        self._agent_id = agent_id

    async def execute(self, args: dict[str, Any], ctx: Any) -> ToolResult:
        try:
            return ToolResult(
                success=True, output=await self._runtime.team_leads.board(self._agent_id)
            )
        except TeamLeadError as exc:
            return _refused(exc)


class TeamReportTool:
    """Report on the team's goal to the person: progress, a question, the result."""

    name: str = TEAM_REPORT_TOOL_NAME
    risk_tier: str = "safe"
    description: str = (
        "Report to the person on the goal your team is working on. status=done closes the "
        "goal: give the complete result, where the output is and what remains open. "
        "status=needs_input pauses the goal on ONE precise question only the person can "
        "answer. status=progress is an interim update on long work; the goal keeps running. "
        "status=failed closes a goal that cannot be reached, with the reason. Write the "
        "summary for the person, in the language they used."
    )
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": list(_REPORT_STATUSES)},
            "summary": {
                "type": "string",
                "description": "What the person should read: the result, the question or why.",
            },
        },
        "required": ["status", "summary"],
    }
    is_action_tool: bool = True

    def __init__(self, runtime: Any, agent_id: str) -> None:
        self._runtime = runtime
        self._agent_id = agent_id

    async def execute(self, args: dict[str, Any], ctx: Any) -> ToolResult:
        status = str(args.get("status") or "").strip().lower()
        if status not in _REPORT_STATUSES:
            return ToolResult(
                success=False, output=None, error="status must be " + " | ".join(_REPORT_STATUSES)
            )
        try:
            outcome = await self._runtime.team_leads.report(
                self._agent_id, status=status, summary=str(args.get("summary") or "")
            )
        except TeamLeadError as exc:
            return _refused(exc)
        return ToolResult(success=True, output=outcome)


def team_lead_tools(runtime: Any, agent_id: str) -> dict[str, Any]:
    """The lead's tools for ``agent_id``; empty unless it leads a team right now."""
    leads = getattr(runtime, "team_leads", None)
    if leads is None or leads.group_led_by(agent_id) is None:
        return {}
    return {
        TeamAssignTool.name: TeamAssignTool(runtime, agent_id),
        TeamBoardTool.name: TeamBoardTool(runtime, agent_id),
        TeamReportTool.name: TeamReportTool(runtime, agent_id),
    }
