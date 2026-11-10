"""Real turn outcomes feed seat health, and a repeated failure reaches the lead.

Every agent-chat runner ends a turn with one ``turn_finished`` event, so the
service reports it here once. A failed turn records the seat's failure class
(:mod:`dodaios.brain.seat_health`); an answered turn clears the seat. When a
society agent fails the same way :data:`~dodaios.brain.seat_health.NOTICE_STREAK`
times in a row, ONE written notice goes into the lead conversation with the
cause and where to fix it (a button to open the right screen). The notice is
never spoken and no seat is ever switched: the owner decides.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Final

from dodaios.brain import seat_health as sh

log = logging.getLogger(__name__)

__all__ = ["NOTICE_KIND", "notice_payload", "observe_turn_finished"]

NOTICE_KIND: Final[str] = "seat_trouble"

_CAUSE: Final[dict[str, str]] = {
    sh.CLASS_QUOTA: "its usage limit is reached",
    sh.CLASS_RATE: "the provider keeps rate limiting it",
    sh.CLASS_AUTH: "its login or key was rejected",
    sh.CLASS_MODEL: "its model is not available on this account",
}
#: The one-click fix paths: ``section`` is a sidebar section id of the app.
_FIXES: Final[dict[str, tuple[tuple[str, str], ...]]] = {
    sh.CLASS_QUOTA: (("Switch the model", "agents"), ("Open API keys", "apikeys")),
    sh.CLASS_RATE: (("Switch the model", "agents"),),
    sh.CLASS_AUTH: (("Sign in again or replace the key", "apikeys"),
                    ("Switch the model", "agents")),
    sh.CLASS_MODEL: (("Switch the model", "agents"),),
}


def notice_payload(
    agent_name: str, agent_id: str, provider: str, failure: sh.SeatFailure
) -> dict[str, Any]:
    """The lead-conversation notice for a repeated seat failure."""
    cause = _CAUSE.get(failure.cls, "it keeps failing")
    text = f"{agent_name} could not work the last {failure.streak} times: {cause} ({provider})."
    if failure.cls in (sh.CLASS_QUOTA, sh.CLASS_RATE) and failure.until:
        text += f" It should be usable again around {sh._clock(failure.until)}."
    text += " Nothing was switched; you choose what happens next."
    return {
        "kind": NOTICE_KIND,
        "text": text,
        "agent_name": agent_name,
        "agent_id": agent_id,
        "provider": provider,
        "failure_class": failure.cls,
        "fixes": [{"label": label, "section": section}
                  for label, section in _FIXES.get(failure.cls, ())],
    }


def observe_turn_finished(service: Any, session_id: str, event: dict[str, Any]) -> None:
    """Report one finished turn. Never raises into the chat."""
    try:
        _observe(service, session_id, event)
    except Exception:  # noqa: BLE001 — a health record must never cost the turn it describes
        log.debug("seat outcomes: could not record %s", session_id, exc_info=True)


def _observe(service: Any, session_id: str, event: dict[str, Any]) -> None:
    payload = event.get("payload") or {}
    if str(payload.get("status") or "") == "cancelled":
        return
    session = service.store.get_session(session_id)
    if session is None or not session.provider:
        return
    health = sh.get_seat_health()
    error = payload.get("error")
    if not (isinstance(error, str) and error.strip()):
        health.record_success(session.provider, session.account_id, model=session.model)
        return
    failure = health.record_failure(
        session.provider, session.account_id, error, model=session.model
    )
    if failure.notify and session_id.startswith("society:"):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # no running loop (sync caller): the record holds the facts
            return
        loop.create_task(_post_notice(session_id, session.provider, failure))


async def _post_notice(session_id: str, provider: str, failure: sh.SeatFailure) -> None:
    from dodaios.society.runtime import current_runtime

    rt = current_runtime()
    if rt is None:
        return
    try:
        agents = rt.roster.snapshot()
        agent = next((a for a in agents if a.session_id == session_id), None)
        lead = next((a for a in agents if a.agent_id == rt.lead_id), None)
        if agent is None or lead is None:
            return
        from dodaios.society.display_name import display_name

        await rt.post_chat_notice(
            lead, notice_payload(display_name(agent), agent.agent_id, provider, failure)
        )
    except Exception:  # noqa: BLE001 — a notice is a convenience; the record already holds the facts
        log.warning("seat outcomes: notice not posted for %s", session_id, exc_info=True)
