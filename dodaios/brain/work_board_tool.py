"""``work_board``: what is running and who needs the person, for every lead seat.

One read-only call that replaces a fan-out of status, task and mission listings
(each of which could overflow the lead's context). It reads the same sources
the voice ``task_status`` board does, summary-first with ``needs_you`` on top.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping
from typing import Any

from dodaios.core.protocols import ExecutionContext, ToolResult
from dodaios.core.work_board import (
    BOARD_SOURCES,
    TASK_SOURCE,
    board_section,
    compact_section,
)

log = logging.getLogger(__name__)

_ERROR_CHARS = 200
# A mission parked on a subscription with no capacity left waits for the person.
_MISSION_NEEDS_YOU_STATES = frozenset({"WAITING_CAPACITY"})


class WorkBoardTool:
    name = "work_board"
    risk_tier = "safe"
    is_action_tool = False
    description = (
        "One board of everything running for the user and who needs them: coding agents "
        "in the Agentic IDE with each workspace's git state, the missions that have not "
        "ended, running routines and the agent team's working members. needs_you comes "
        "first and names what is waiting for the user (an agent showing a question or "
        "stopped, a mission waiting for capacity). Summary-first: busy agents only, idle "
        "ones are counted. Use it for 'what is running', 'what happened', 'who needs me' "
        "instead of calling several list tools; set detail=true for every agent row. For "
        "one agent, workspace or mission use workspace-orchestrate (status, observe), "
        "society_status (mode=agent) or missions-list."
    )
    schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "detail": {
                "type": "boolean",
                "description": "Also list idle and unused coding agents and idle team members.",
            }
        },
    }

    def __init__(self, resolver: Callable[[], Mapping[str, Any]]) -> None:
        # The tools the board reads, looked up per call so a tool that connects
        # later is picked up, and one that is absent leaves its section out.
        self._resolve = resolver

    async def execute(self, args: dict[str, Any], ctx: ExecutionContext) -> ToolResult:
        detail = args.get("detail") is True
        tools = self._resolve()
        sources = [
            source for source in (*BOARD_SOURCES, TASK_SOURCE) if source[1] in tools
        ]
        answers = await asyncio.gather(
            *(tools[tool].execute(dict(call_args), ctx) for _section, tool, call_args in sources),
            return_exceptions=True,
        )
        board: dict[str, Any] = {}
        for (section, tool, _args), answer in zip(sources, answers, strict=True):
            if isinstance(answer, asyncio.CancelledError):
                raise answer
            if isinstance(answer, BaseException):
                log.warning("work_board: %s failed", tool, exc_info=answer)
                board[section] = {"unavailable": "This part could not be read."}
                continue
            rows = board_section(section, answer.output) if answer.success else None
            if rows is None:
                board[section] = {
                    "unavailable": str(answer.error or answer.output or "No answer.")[
                        :_ERROR_CHARS
                    ]
                }
            else:
                board[section] = rows if detail else compact_section(section, rows)
        needs_you = _needs_you(board)
        return ToolResult(success=True, output={"needs_you": needs_you, **board})


def _needs_you(board: dict[str, Any]) -> list[str]:
    needs: list[str] = []
    agents = board.get("coding_agents")
    if isinstance(agents, dict):
        needs.extend(str(name) for name in agents.get("needs_you") or [])
    missions = board.get("missions")
    if isinstance(missions, list):
        needs.extend(
            f"mission {row.get('mission_id')}: waiting for subscription capacity"
            for row in missions
            if isinstance(row, dict) and str(row.get("state")) in _MISSION_NEEDS_YOU_STATES
        )
    return needs
