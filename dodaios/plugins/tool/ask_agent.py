"""ask_agent tool: put a question to a named agent and wait for its answer.

``message_agent`` delivers a message and returns at once; the answer comes back
later as a separate report. That is right for work, and wrong for a
conversation: a user who says "ask Scout what it found" or "let me talk to the
Gmail agent" wants the answer in the same breath. This tool sends the question
through the same delivery path and then waits a bounded time for the reply, so
a live call can relay a back-and-forth with one agent.

When the reply does not arrive in time nothing is lost: the wait ends, and the
answer is handed to the conversation when it comes, as any agent report is.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from dodaios.core.protocols import ToolResult
from dodaios.plugins.tool.delegate_to_agent import RuntimeResolver

log = logging.getLogger(__name__)

DEFAULT_WAIT_S = 45
MAX_WAIT_S = 120
_POLL_S = 0.5


def _now() -> float:
    return time.monotonic()


class AskAgentTool:
    name = "ask_agent"
    risk_tier = "safe"
    is_action_tool = True
    description = (
        "Ask one of the user's named Dodaios agents a question and wait for its answer, so "
        "the user can talk with that agent through you. Use it when the user wants to "
        "speak with or ask an agent ('ask Scout what it found', 'let me talk to the Gmail "
        "agent'). Say the answer as that agent's words and name the agent once. While the "
        "user keeps addressing that agent, pass each of their turns on with ask_agent; "
        "answer yourself again when they say so or change the subject. To assign work use "
        "delegate_to_agent; for a note that needs no answer use message_agent. When "
        "answered is false the agent is still thinking: say so, never invent its answer; "
        "it is handed to this conversation when it arrives."
    )
    schema: dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "agent": {"type": "string", "description": "The agent's name or id."},
            "question": {
                "type": "string",
                "description": (
                    "What the user wants to ask or tell the agent, complete in itself: "
                    "the agent does not hear the call."
                ),
            },
            "wait_seconds": {
                "type": "integer",
                "minimum": 5,
                "maximum": MAX_WAIT_S,
                "description": f"How long to wait for the answer (default {DEFAULT_WAIT_S}).",
            },
        },
        "required": ["agent", "question"],
    }

    def __init__(self, *, runtime_resolver: RuntimeResolver) -> None:
        self._resolve = runtime_resolver

    def describe_args(self, args: dict[str, Any]) -> dict[str, Any]:
        return {
            "level": "modify",
            "agent": str(args.get("agent") or ""),
            "task": str(args.get("question") or "")[:240],
        }

    async def execute(self, args: dict[str, Any], ctx: Any) -> ToolResult:
        from dodaios.society.agent_tools import MessageAgentTool
        from dodaios.society.delegation_wait import result_for

        try:
            wait_s = int(args.get("wait_seconds") or DEFAULT_WAIT_S)
        except (TypeError, ValueError):  # a malformed wait falls back to the default
            wait_s = DEFAULT_WAIT_S
        wait_s = max(5, min(MAX_WAIT_S, wait_s))
        from dodaios.society.runtime import reply_awaited_inline

        try:
            runtime = self._resolve()
            if runtime is None:
                return ToolResult(success=False, output=None, error="society unavailable")
            # Started first: tasks the runtime creates must not inherit the mark.
            await runtime.ensure_started()
        except Exception as exc:  # noqa: BLE001 - an honest, inspectable tool failure
            log.warning("ask_agent: the agent team is not available", exc_info=True)
            return ToolResult(success=False, output=None, error=str(exc))
        # The one question sent below is marked as awaited; ``marked`` receives
        # its id, so every way out of this call can lift the mark again.
        marked: list[str] = []
        waiting = reply_awaited_inline.set(marked)
        reply = None
        try:
            try:
                sent = await MessageAgentTool(runtime, runtime.lead_id).execute(
                    {
                        "target": str(args.get("agent") or ""),
                        "text": str(args.get("question") or ""),
                        "kind": "query",
                        "reply_policy": "always",
                    },
                    ctx,
                )
            except Exception as exc:  # noqa: BLE001 - an honest, inspectable tool failure
                log.warning("ask_agent: delivery failed", exc_info=True)
                return ToolResult(success=False, output=None, error=str(exc))
            finally:
                reply_awaited_inline.reset(waiting)
            if not sent.success or not isinstance(sent.output, dict):
                return sent
            agent = str(sent.output.get("target") or args.get("agent") or "")
            request = await runtime.store.get_event(str(sent.output.get("message_id") or ""))
            if request is None:
                return sent
            deadline = _now() + wait_s
            while reply is None and _now() < deadline:
                await asyncio.sleep(_POLL_S)
                reply = await result_for(runtime.store, request)
            if reply is None:
                # An answer that landed while the wait ended was not announced:
                # read once more before calling it pending.
                reply = await result_for(runtime.store, request)
        finally:
            # Also after a failed or uncertain send: a reply that still comes
            # is then announced like any other. An answer read here is said by
            # this call, so its delivery stays quiet even if it runs later.
            for request_id in marked:
                runtime.stop_awaiting_inline(request_id, answered=reply is not None)
        if reply is None:
            return ToolResult(
                success=True,
                output={
                    "agent": agent,
                    "answered": False,
                    "status": "pending",
                    "message_id": request.event_id,
                    "note": (
                        f"{agent} has not answered within {wait_s} seconds. Tell the user "
                        "it is still thinking. The answer is handed to this conversation "
                        "when it arrives; do not ask again."
                    ),
                },
            )
        return ToolResult(
            success=True,
            output={
                "agent": agent,
                "answered": True,
                "status": reply.get("status") or "done",
                "answer": str(reply.get("report") or ""),
                "message_id": request.event_id,
            },
        )
