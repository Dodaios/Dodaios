"""Trusted turn provenance and the immutable chat completion contract."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ChatTurn:
    session_id: str
    turn_id: str
    user_text: str
    direct_user: bool
    trace_id: str
    #: The turn's own node in the causal trace tree; empty reads as ``turn_id``.
    span_id: str = ""
    #: The node that caused this turn (an assignment event, a lead turn); empty for a root.
    parent_span_id: str = ""
    #: Where the work really came from: chat, routine, trigger, agent, system.
    origin: str = ""


def turn_span_id(turn: ChatTurn | None) -> str:
    """The span id of ``turn``, or ``""`` when no turn is in flight."""
    if turn is None:
        return ""
    return turn.span_id or turn.turn_id


def origin_of(turn: ChatTurn | None) -> str:
    """The real origin of work started under ``turn`` (``voice`` when there is no turn)."""
    if turn is None:
        return "voice"
    if turn.origin:
        return turn.origin
    return "chat" if turn.direct_user else "agent"


current_chat_turn: ContextVar[ChatTurn | None] = ContextVar("current_chat_turn", default=None)

#: The span a vendor CLI's MCP call names in the trusted harness header. Set by
#: the MCP route only, after a strict format check; a tool argument never reaches it.
mcp_span_ref: ContextVar[str | None] = ContextVar("mcp_span_ref", default=None)


@dataclass(frozen=True, slots=True)
class ChatCompletion:
    turn: ChatTurn
    events_json: str
