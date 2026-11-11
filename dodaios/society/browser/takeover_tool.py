"""``request_browser_takeover``: the agent asks the owner to act in its browser.

For what an agent must not or cannot do itself: a CAPTCHA, a single sign-on
page, a second factor, a login nobody stored, a form that needs a person. The
tool posts ONE written card in the lead conversation (the status light lists it
as "needs you", the phone chat gets the same line when its routing allows
decisions), opens a request the browser panel shows, and waits for the owner
to take over and hand back. It never speaks.

What it returns is the hand-back note (``takeover.handback_note``): the page
the owner left and whether anything was typed, never what was typed.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Final

from dodaios.core.protocols import ToolResult

from .takeover import MAX_REASON

log = logging.getLogger(__name__)

__all__ = ["TAKEOVER_TOOL_NAME", "RequestBrowserTakeoverTool", "lead_takeover_tools"]

TAKEOVER_TOOL_NAME: Final[str] = "request_browser_takeover"
NOTICE_KIND: Final[str] = "browser_takeover"
#: How long a request waits for the owner. A request is a question to a person
#: who may be away, so the wait is long; it ends the moment they hand back.
WAIT_S: Final[float] = 3600.0
_SLICE_S: Final[float] = 5.0


def _failure(detail: str) -> ToolResult:
    return ToolResult(success=False, output=None, error=detail)


class RequestBrowserTakeoverTool:
    name: str = TAKEOVER_TOOL_NAME
    risk_tier: str = "safe"
    is_action_tool: bool = False
    description: str = (
        "Ask the user to take over YOUR browser for a step you cannot or must not do: a CAPTCHA, "
        "a single sign-on page, a two-factor code, a login that is not stored, a form that needs "
        "a person. Use it after society_browser reports it is blocked there. It posts one written "
        "card for the user (never spoken), shows them your live browser to act in, and waits "
        "until they hand it back. You get a short note of the page they left it on and whether "
        "they typed anything; what they typed is never shown to you. Then continue with "
        "society_browser. Give a short reason the user can read at a glance. Do not use it for a "
        "website login that society_request_login can store."
    )
    schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": "What the user has to do, in one short sentence.",
            },
        },
        "required": ["reason"],
    }

    def __init__(self, runtime: Any, agent_id: str, *, wait_s: float = WAIT_S) -> None:
        self._runtime = runtime
        self._agent_id = agent_id
        self._wait_s = wait_s

    async def execute(self, args: dict[str, Any], ctx: Any) -> ToolResult:
        reason = " ".join(str(args.get("reason") or "").split())
        if not reason:
            return _failure("invalid request: reason is required")
        rt = self._runtime
        agent = await rt.roster.get(self._agent_id)
        if agent is None:
            return _failure("the browser's agent is not available")
        live = rt.browser.live
        try:
            session = live.sessions.get(self._agent_id)
            if session is None or session.closed:
                session = await live.ensure(agent)
        except Exception as exc:  # noqa: BLE001 — a browser that cannot start is the typed answer
            log.warning("browser takeover: no browser to hand over", exc_info=True)
            return _failure(f"the browser is not available: {type(exc).__name__}")
        request, is_new = session.takeover.request_takeover(reason[:MAX_REASON])
        note: dict[str, Any] | None = None
        try:
            if is_new:
                session.publish({"kind": "takeover_request", **request})
                await self._post_card(request)
            loop = asyncio.get_running_loop()
            deadline = loop.time() + self._wait_s
            while note is None and not session.closed:
                left = deadline - loop.time()
                if left <= 0:
                    break
                note = await session.takeover.wait_handback(min(_SLICE_S, left), request["id"])
        finally:
            if note is None and session.takeover.request is request:
                # Stopped, timed out or the browser went away: the ask is gone.
                session.takeover.request = None
                session.publish({"kind": "takeover_request_cleared"})
        if is_new:
            await self._post_done(request["id"], "handed_back" if note else "expired")
        if note is None:
            return _failure("the user did not take over the browser; ask again if it still matters")
        return ToolResult(success=True, output={"status": "handed_back", **note})

    async def _post_done(self, request_id: str, status: str) -> None:
        """Tell the card it is answered (the timeline patches it, no new row)."""
        from dodaios.notify.reminders import lead_target, post_notice

        target = lead_target()
        if target is None:
            return
        try:
            await post_notice(
                target[0],
                target[1],
                {"kind": f"{NOTICE_KIND}_done", "request_id": request_id, "status": status},
            )
        except Exception:  # noqa: BLE001 — the card then keeps asking; the browser panel is right
            log.warning("browser takeover: card not closed", exc_info=True)

    async def _post_card(self, request: dict[str, Any]) -> None:
        """One written card in the lead conversation, plus the desktop notification."""
        from dodaios.notify.reminders import (
            lead_target,
            notification_language,
            phrase,
            post_notice,
        )

        reason = str(request["reason"])
        session_id = ""
        target = lead_target()
        if target is not None:
            svc, session_id = target
            try:
                await post_notice(
                    svc,
                    session_id,
                    {
                        "kind": NOTICE_KIND,
                        "status": "waiting",
                        "text": reason,
                        "agent_id": self._agent_id,
                        "request_id": request["id"],
                    },
                )
            except Exception:  # noqa: BLE001 — the panel and the status light still show the ask
                log.warning("browser takeover: card not posted", exc_info=True)
        try:
            from dodaios.notify.notifier import current_notifier

            notifier = current_notifier()
            if notifier is not None:
                lang = notification_language(reason)
                await notifier.notify(
                    "needs_you",
                    phrase("needs_you_title", lang, agent=phrase("an_agent", lang)),
                    reason,
                    session_id=session_id,
                )
        except Exception:  # noqa: BLE001 — a notification is a convenience, never a failure
            log.debug("browser takeover: notification not sent", exc_info=True)


def lead_takeover_tools(session: Any = None) -> dict[str, Any]:
    """The lead's request tool, bound to the lead's own browser."""
    from ..routine_runner import is_routine_session
    from ..runtime import current_runtime

    rt = current_runtime()
    session_id = str(getattr(session, "session_id", "") or "")
    if rt is None or (session_id and is_routine_session(session_id)):
        return {}
    return {TAKEOVER_TOOL_NAME: RequestBrowserTakeoverTool(rt, rt.lead_id)}
