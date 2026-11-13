"""A service the person just connected continues the request that needed it.

A Connect card (``dodaios/society/connect_tool.py``, ``connect_offer.py``)
outlives the turn that showed it: the agent ends its reply with "press Connect"
and the sign-in takes as long as it takes. When the card reports the
connection, the chat picks that request up again in a turn of its own, the way
an approval that was set aside does (``approval_defer.py``). Nobody has to type
"done".

The turn starts once the chat's seat is free: after the card's own turn, and
after anything the person started in the meantime. It opens with the line "the
result of your earlier request" (``background_result``), not with a bubble of
the person's.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any, Final

log = logging.getLogger(__name__)

__all__ = ["ConnectResume", "resume_prompt"]

#: How often the continuation checks whether the chat's seat is free.
_POLL_S: Final[float] = 0.5
#: How long it waits for that seat before the person has plainly moved on.
_WAIT_S: Final[float] = 600.0
#: How much of the request the continuation's opening line quotes.
_REQUEST_CHARS: Final[int] = 200


def resume_prompt(label: str, request: str) -> str:
    """What the agent is told when the service it asked for is connected."""
    quoted = f"\nThe request: {request}" if request else ""
    return (
        f"[The person connected {label} on the Connect card in this chat; its tools work "
        f"from now on. If the request that needed {label} is still open, carry it out "
        "now and answer it. If you have answered it since, do not repeat that answer: "
        f"confirm in one short sentence that {label} is connected. Answer in the "
        f"language of that request.{quoted}]"
    )


def _request_of(events: list[dict[str, Any]], turn_id: str) -> str:
    """What the person asked in the turn that showed the card."""
    asked = ""
    for event in events:
        payload = event.get("payload") or {}
        if event.get("kind") == "user_message":
            typed = payload.get("typed")
            asked = typed if isinstance(typed, str) and typed else str(payload.get("text") or "")
        elif event.get("kind") == "turn_started" and payload.get("turn_id") == turn_id:
            break
    return " ".join(asked.split())[:_REQUEST_CHARS]


class ConnectResume:
    """Starts the turn that follows a connected card, once per card."""

    def __init__(self, service: Any) -> None:
        self._service = service
        self._tasks: set[asyncio.Task[None]] = set()

    def connected(self, session_id: str, turn_id: str, label: str) -> None:
        """The card of ``turn_id`` reported its connection; continues in the background."""
        from dodaios.society.roster import PAIR_SESSION_MARKER
        from dodaios.society.routine_runner import is_routine_session

        # A routine's run and a talk between two agents have no person in them.
        if is_routine_session(session_id) or PAIR_SESSION_MARKER in session_id:
            return
        task = asyncio.ensure_future(self._continue(session_id, turn_id, label))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _continue(self, session_id: str, turn_id: str, label: str) -> None:
        from .send_queue import has_waiting
        from .service import NoSuchSession, SessionBusy

        svc = self._service
        try:
            events = await asyncio.to_thread(svc.store.list_events, session_id, tail=400)
            request = _request_of(events, turn_id)
            prompt = resume_prompt(label, request)
            deadline = time.monotonic() + _WAIT_S
            while time.monotonic() < deadline:
                if not svc.is_running(session_id) and not has_waiting(svc, session_id):
                    try:
                        await svc.send(
                            session_id,
                            prompt,
                            display_text=request or label,
                            background_result=True,
                        )
                    except SessionBusy:
                        pass  # another turn took the seat first; try again shortly
                    except NoSuchSession:  # the chat was deleted: nothing left to continue
                        return
                    else:
                        return
                await asyncio.sleep(_POLL_S + random.uniform(0, _POLL_S / 2))  # noqa: S311
            log.info("agent chat: %s connected in %s, its seat stayed busy", label, session_id)
        except Exception:  # noqa: BLE001 — the card is settled; the failure is logged
            log.warning(
                "agent chat: %s connected in %s but the request was not continued",
                label, session_id, exc_info=True,
            )
