"""The one way a follow-up order reaches a coding thread.

A follow-up order is a message the app writes into a thread after it checked
what the thread's turn left behind (:mod:`driver`). Every one goes through
:func:`follow_up`, which sends only when the thread is the agent's to work in:

* the thread exists and is at rest;
* nothing in it waits for the person (a question, an approval, a plan);
* its last turn ended by itself, not by a stop;
* the person did not write into it since.

Otherwise it raises :class:`Refused` and nothing is written. The message
carries the app as its author, so the thread shows who wrote it and neither the
recorder nor the result hand-back reads it as the person stepping in.
"""

from __future__ import annotations

from typing import Any

from . import prompts

__all__ = ["Refused", "follow_up", "is_follow_up"]

_LOOK_BACK = 400


class Refused(RuntimeError):
    """The follow-up order was not sent; the message says why."""


def is_follow_up(payload: dict[str, Any]) -> bool:
    """True for the ``user_message`` payload of a follow-up order."""
    author = payload.get("author")
    return isinstance(author, dict) and author.get("agent_id") == prompts.AUTHOR_ID


def _why_not(service: Any, session_id: str) -> str:
    """Why the thread takes no follow-up order now, or ``""`` when it does."""
    from dodaios.society.coding_threads import last_turn, open_plan, open_question

    if service.store.get_session(session_id) is None:
        return "the thread no longer exists"
    if service.is_running(session_id):
        return "the thread is in a turn"
    if service.pending_questions(session_id) or service.pending_approvals(session_id):
        return "the thread waits for the person"
    events = service.store.list_events(session_id, tail=_LOOK_BACK) or []
    if open_question(events) or open_plan(events):
        return "the thread waits for the person"
    if last_turn(events)[0] == "cancelled":
        return "the thread's last turn was stopped"
    for event in reversed(events):
        if event.get("kind") == "turn_finished":
            break
        payload = event.get("payload") or {}
        if event.get("kind") == "user_message" and not payload.get("author"):
            return "the person wrote into the thread"
    return ""


async def follow_up(
    service: Any, session_id: str, prompt: str, *, run_id: str, iteration: int
) -> str:
    """Send one follow-up order into ``session_id``. Returns the id of the turn it started."""
    from dodaios.agent_chat.service import NoSuchSession, SessionBusy

    reason = _why_not(service, session_id)
    if reason:
        raise Refused(reason)
    try:
        return str(
            await service.send(
                session_id,
                prompt,
                # The app wrote this, not the person: no steering, no
                # end-of-turn question card.
                direct_user=False,
                author={
                    "agent_id": prompts.AUTHOR_ID,
                    "name": prompts.AUTHOR_NAME,
                    "run": run_id,
                    "iteration": str(iteration),
                },
            )
        )
    except (NoSuchSession, SessionBusy, ValueError) as exc:
        raise Refused(str(exc) or type(exc).__name__) from exc
