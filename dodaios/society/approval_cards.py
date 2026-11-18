"""An approval that waits in place shows as a card in the conversation.

A row in the approvals table is the truth (``approvals.py``); the browser
panel and the needs-you surfaces are projections of it. The conversation was
not one of them: a browser run that paused on a click, or a tool whose gate
wanted a person, waited where the person was not looking, and the chat that
started the work showed nothing.

``open_card`` posts one card into the agent's conversation (the lead's cards
go to the lead conversation): what is asked, in words, with Yes and No. The
buttons answer the same row every other surface answers. ``close_card`` says
how it ended; the timeline patches the card, it adds no second row.
"""

from __future__ import annotations

import logging
from typing import Any, Final

__all__ = ["BLOCKED_KIND", "NOTICE_KIND", "close_card", "note_blocked", "open_card"]

log = logging.getLogger(__name__)

NOTICE_KIND: Final[str] = "approval_request"
#: A card for an action that never runs (``action_policy.Severity.BLOCK``).
BLOCKED_KIND: Final[str] = "action_blocked"


async def open_card(
    runtime: Any,
    agent: Any,
    approval_id: str,
    *,
    what: str,
    where: str = "",
    detail: str = "",
    label: str = "",
    browser: bool = False,
    severity: str = "ask",
    kind: str = "",
) -> None:
    """Post the card and, when the person is elsewhere, the desktop notification.

    ``what`` is the question's substance in words, ``where`` the site or
    tool, ``detail`` what the page says about it. ``label`` is the text of the
    control a browser step is about to press: with it the card asks in the
    person's own language ("May I click "Cancel subscription" on ...?").
    ``severity`` is ``ask`` or ``confirm`` (money and accounts, asked in every
    mode: the card says so) and ``kind`` what the step does (``buy``, ``send``).
    Posting never fails the work: the browser panel still shows the ask.
    """
    try:
        await runtime.post_chat_notice(
            agent,
            {
                "kind": NOTICE_KIND,
                "status": "pending",
                "approval_id": approval_id,
                "text": what[:500],
                "where": where[:200],
                "detail": detail[:500],
                "label": label[:160],
                "browser": browser,
                "severity": severity,
                "step_kind": kind,
                "agent_id": agent.agent_id,
            },
        )
    except Exception:  # noqa: BLE001 — the panel and the queue still show the ask
        log.warning("approval card: not posted for %s", approval_id, exc_info=True)
    try:
        from dodaios.notify.notifier import current_notifier
        from dodaios.notify.reminders import notification_language, phrase

        notifier = current_notifier()
        if notifier is not None:
            lang = notification_language(what)
            await notifier.notify(
                "needs_you",
                phrase("needs_you_title", lang, agent=phrase("an_agent", lang)),
                what[:300],
                session_id=str(getattr(agent, "session_id", "") or ""),
            )
    except Exception:  # noqa: BLE001 — a notification is a convenience, never a failure
        log.debug("approval card: notification not sent", exc_info=True)


async def note_blocked(runtime: Any, agent: Any, finding: Any, where: str = "") -> None:
    """Post a card that says an action was refused for good and why (``action_policy``).

    It has no buttons: nothing the person clicks makes a blocked action run.
    """
    from urllib.parse import urlsplit

    host = (urlsplit(where).hostname or where or "").removeprefix("www.")
    try:
        await runtime.post_chat_notice(
            agent,
            {
                "kind": BLOCKED_KIND,
                "status": "blocked",
                "category": str(getattr(finding, "category", "")),
                "text": str(getattr(finding, "reason", ""))[:500],
                "where": host[:200],
                "agent_id": agent.agent_id,
            },
        )
    except Exception:  # noqa: BLE001 — the agent's tool result still says it was blocked
        log.warning("blocked card: not posted for %s", host, exc_info=True)


async def close_card(runtime: Any, agent: Any, approval_id: str, status: str) -> None:
    """Tell the card how it ended: ``approved``, ``declined`` or ``expired``."""
    try:
        await runtime.post_chat_notice(
            agent,
            {"kind": f"{NOTICE_KIND}_done", "approval_id": approval_id, "status": status},
        )
    except Exception:  # noqa: BLE001 — the card then keeps its buttons; the row is right
        log.warning("approval card: not closed for %s", approval_id, exc_info=True)
