"""Approval cards for a runtime's native tools that cannot ask over ACP.

OpenClaw relays only its exec approvals to the ACP client
(``session/request_permission``); its file tools (``write``, ``edit``,
``apply_patch``) run without asking anyone. Dodaios' gate plugin in the
agent's Gateway (``openclaw_gate``) holds each such call and asks here, over
the Control API (``POST /api/control/runtime/native-approval``), and the
running turn of that chat decides it like any other approval: Bypass allows,
Plan refuses, Ask and Always ask show the card on the tool's row.

The running ACP turn registers its decider for its chat while it runs
(``runner_cli``); a call that arrives while no turn of the chat runs is
refused, never run unasked.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, Final

log = logging.getLogger(__name__)

#: ``decider(call_id, tool, args, title, read_only) -> allow | allow_always |
#: deny | cancel``. ``read_only``: the tool only reads (asked in "Always ask").
Decider = Callable[[str, str, dict[str, Any], str, bool], Awaitable[str]]

#: A decision must reach the plugin before its hook budget runs out
#: (``openclaw_gate.HOOK_TIMEOUT_MS``); an unanswered card is refused then.
DECISION_TIMEOUT_S: Final[float] = 570.0

#: The tool sees this as the reason its call did not run.
NO_TURN: Final[str] = "No Dodaios turn is running for this chat, so the action was not run."
DECLINED: Final[str] = "The person declined this action. Do not try to work around it."
STOPPED: Final[str] = "The turn was stopped before the person decided. Do not continue."
NO_ANSWER: Final[str] = "Nobody answered the approval card in time, so the action was not run."

_DECIDERS: dict[str, Decider] = {}
#: Per chat: the native tools the person allowed with "allow always".
_ALWAYS: dict[str, set[str]] = {}


def register(session_id: str, decider: Decider) -> None:
    """The running turn of ``session_id`` decides its native tool calls."""
    _DECIDERS[session_id] = decider


def unregister(session_id: str, decider: Decider) -> None:
    if _DECIDERS.get(session_id) is decider:
        del _DECIDERS[session_id]


def always_for(session_id: str) -> set[str]:
    """The chat's "allow always" set for native tools (shared, mutable)."""
    return _ALWAYS.setdefault(session_id, set())


def forget(session_id: str) -> None:
    """Drop the chat's remembered answers (a cleared or deleted chat)."""
    _ALWAYS.pop(session_id, None)


async def decide(
    session_id: str,
    tool: str,
    args: dict[str, Any],
    *,
    call_id: str = "",
    title: str = "",
    read_only: bool = False,
) -> tuple[str, str]:
    """``("allow", "")`` or ``("deny", reason)`` for one native tool call."""
    decider = _DECIDERS.get(session_id)
    if decider is None:
        log.info("native gate: %s for %s refused, no turn running", tool, session_id)
        return "deny", NO_TURN
    try:
        decision = await asyncio.wait_for(
            decider(call_id, tool, dict(args or {}), title, read_only),
            timeout=DECISION_TIMEOUT_S,
        )
    except TimeoutError:
        log.info("native gate: nobody answered %s for %s in time; refusing", tool, session_id)
        return "deny", NO_ANSWER
    except Exception:  # noqa: BLE001 — a broken card refuses, it never allows
        log.warning("native gate: deciding %s failed; refusing", tool, exc_info=True)
        return "deny", DECLINED
    if decision in ("allow", "allow_always"):
        return "allow", ""
    if decision == "cancel":
        return "deny", STOPPED
    return "deny", DECLINED


def reset() -> None:
    """Forget every decider and answer (tests)."""
    _DECIDERS.clear()
    _ALWAYS.clear()
