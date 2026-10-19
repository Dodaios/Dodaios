"""Portable reply expectations shared by lead and teammate communication.

Policies live in the existing envelope JSON, not in delivery status. Old
assignments still report completion; information and answers close quietly.
"""

from __future__ import annotations

from typing import Any

from .events import MsgType, SocietyEnvelope

REPLY_POLICIES = ("none", "on_error", "always")
REPLY_POLICY_SCHEMA: dict[str, Any] = {
    "type": "string",
    "enum": list(REPLY_POLICIES),
    "description": (
        "Expected reply: none for information or an explicitly silent task; "
        "on_error for work needing only blockers reported; always for a question, "
        "requested result or decision. Choose from the user's intent and context."
    ),
}

def select_reply_policy(value: Any, kind: MsgType) -> str:
    """Validate tool input, preserving compatible defaults for older callers."""
    default = "always" if kind in (MsgType.ASSIGN, MsgType.QUERY, MsgType.PROPOSE) else "none"
    policy = default if value is None else value
    if policy not in REPLY_POLICIES:
        raise ValueError("reply_policy must be none, on_error or always")
    if kind is MsgType.QUERY and policy != "always":
        raise ValueError("a query requires reply_policy=always")
    if kind is MsgType.ANSWER and policy != "none":
        raise ValueError("an answer closes the exchange; use a query for a new question")
    return policy


def reply_policy(env: SocietyEnvelope) -> str:
    """Read older envelopes without failing the receiver on malformed metadata."""
    try:
        return select_reply_policy(env.payload.get("reply_policy"), env.msg_type)
    except (TypeError, ValueError):
        # Invalid old metadata must not hide a requested result.
        return "always" if env.msg_type in (MsgType.ASSIGN, MsgType.QUERY) else "none"


def should_report(env: SocietyEnvelope, status: str) -> bool:
    policy = reply_policy(env)
    return policy == "always" or (policy == "on_error" and status != "done")


def response_instruction(env: SocietyEnvelope) -> str:
    policy = reply_policy(env)
    if env.msg_type is MsgType.ASSIGN:
        return (
            f"Reply expectation: {policy}. Put the outcome and evidence in your final "
            "response; the runtime delivers it. If blocked, send kind 'answer' with "
            "reply_status=blocked to the requesting agent instead."
        )
    if policy == "always":
        return (
            "Reply expectation: always. Answer with society_message_agent kind 'answer' "
            "(reply_status=blocked if you cannot)."
        )
    if policy == "on_error":
        return (
            "Reply expectation: on_error. Reply only if blocked: society_message_agent kind "
            "'answer', reply_status=blocked."
        )
    return "No reply is requested."
