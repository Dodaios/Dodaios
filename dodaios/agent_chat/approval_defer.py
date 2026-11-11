"""An approval card never freezes the chat: it is set aside when the person moves on.

A turn that asks for an approval waits for the click. When the person writes
something else while the card is open, the chat must answer instead of queueing
that message behind a decision nobody has made yet. Here the waiting card is
*deferred*:

* the call that asked is told "not approved yet, did not run, the person moved
  on" (a refusal that says why, never a silent "no") and its turn finishes, so
  the chat's seat is free for the new message and other jobs go on;
* the card stays open on screen, marked as set aside (``approval_deferred``);
* when the person answers it later, an Allow starts a turn of its own that
  tells the lead to run exactly that call (with the person's edits, if any); the
  call then meets its own card's answer instead of asking a second time. A Deny
  just closes the card.

The one-shot grant is bound to the exact tool and arguments the card showed. It
is consumed by the first call that matches, expires after :data:`GRANT_TTL_S`,
and lives in memory like the rest of the chat's approval state. It stands in for
the click only: the call still goes through the executor's blacklist and
outbound checks.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from dataclasses import dataclass
from typing import Any, Final

from .events import make_event

log = logging.getLogger(__name__)

#: How long an Allow of a set-aside card stays valid for the call that follows.
GRANT_TTL_S: Final[float] = 3600.0
#: How often the continuation checks whether the chat's seat is free.
_POLL_S: Final[float] = 0.5

#: What the refused call is told while its card stays open.
DEFER_NOTICE: Final[str] = (
    "Not approved yet: the person moved on to another message, so this call did NOT run. "
    "Their approval card stays open. If they approve it later you are asked to run it then. "
    "Do not retry it now and do not claim it was done; continue with the new message."
)


def call_key(name: str, args: dict[str, Any]) -> str:
    """The identity of one exact call: its bare tool name and canonical arguments."""
    from .approval_bridge import _bare

    try:
        body = json.dumps(args or {}, sort_keys=True, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        body = repr(sorted((args or {}).items(), key=lambda kv: str(kv[0])))
    return f"{_bare(name)}\n{body}"


@dataclass(slots=True)
class Deferred:
    """One card set aside: what it asked, so a later answer can act on it."""

    session_id: str
    turn_id: str
    approval_id: str
    call_id: str
    name: str
    args: dict[str, Any]
    summary: str


class DeferredApprovals:
    """The cards set aside per chat, and the grants their Allow leaves behind."""

    def __init__(self, service: Any) -> None:
        self._service = service
        self._deferred: dict[str, Deferred] = {}
        #: ``(session_id, call_key) -> expires monotonic``
        self._grants: dict[tuple[str, str], float] = {}
        self._tasks: set[asyncio.Task[None]] = set()

    # ------------------------------------------------------------ setting aside

    def pending(self, session_id: str) -> list[str]:
        return [a for a, d in self._deferred.items() if d.session_id == session_id]

    def get(self, approval_id: str) -> Deferred:
        return self._deferred[approval_id]

    def session_of(self, approval_id: str) -> str:
        item = self._deferred.get(approval_id)
        return item.session_id if item is not None else ""

    async def set_aside(self, item: Deferred) -> None:
        """Keep ``item``'s card open and say on it that the chat moved on."""
        self._deferred[item.approval_id] = item
        await self._service._emit(
            item.session_id,
            make_event(
                "approval_deferred",
                {"turn_id": item.turn_id, "approval_id": item.approval_id},
            ),
        )

    def forget_session(self, session_id: str) -> None:
        for approval_id in self.pending(session_id):
            self._deferred.pop(approval_id, None)
        for key in [k for k in self._grants if k[0] == session_id]:
            self._grants.pop(key, None)

    # ------------------------------------------------------------------ grants

    def take_grant(self, session_id: str, name: str, args: dict[str, Any]) -> bool:
        """Whether this exact call was approved on a card that had been set aside."""
        now = time.monotonic()
        self._grants = {k: v for k, v in self._grants.items() if v > now}
        return self._grants.pop((session_id, call_key(name, args)), None) is not None

    # ------------------------------------------------------------------ answers

    def answer(
        self,
        approval_id: str,
        decision: str,
        changed: dict[str, dict[str, str]],
        new_args: dict[str, Any],
    ) -> bool:
        """The person answered a card that was set aside; settles it in the background."""
        item = self._deferred.pop(approval_id, None)
        if item is None:
            return False
        task = asyncio.ensure_future(self._settle(item, decision, changed, new_args))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return True

    async def _settle(
        self,
        item: Deferred,
        decision: str,
        changed: dict[str, dict[str, str]],
        new_args: dict[str, Any],
    ) -> None:
        svc = self._service
        approved = decision in ("allow", "allow_always")
        try:
            await svc._emit(
                item.session_id,
                make_event(
                    "approval_resolved",
                    {
                        "turn_id": item.turn_id,
                        "approval_id": item.approval_id,
                        "decision": "allow" if approved else "deny",
                        "deferred": True,
                        **({"edited": changed} if approved and changed else {}),
                    },
                ),
            )
            if not approved:
                return
            self._grants[(item.session_id, call_key(item.name, new_args))] = (
                time.monotonic() + GRANT_TTL_S
            )
            await self._continue(item, new_args, changed)
        except Exception:  # noqa: BLE001 — the card is answered; the failure is logged
            log.warning("agent chat: deferred approval %s not continued", item.approval_id,
                        exc_info=True)

    async def _continue(
        self, item: Deferred, args: dict[str, Any], changed: dict[str, dict[str, str]]
    ) -> None:
        """Start the turn that runs the approved call once the chat has room for it."""
        from .approval_preview import edits_note
        from .send_queue import has_waiting
        from .service import NoSuchSession, SessionBusy

        svc = self._service
        body = json.dumps(args, ensure_ascii=False, indent=2, default=str)
        note = edits_note(changed)
        prompt = (
            "[The person approved the action you were waiting on. It did not run earlier "
            "because they had moved on to another message. Run it now, exactly once, with "
            f"tool `{item.name}` and exactly these arguments, then tell them it is done.\n"
            f"{body}\n{note}]"
        )
        label = item.summary or item.name
        while True:
            if not svc.is_running(item.session_id) and not has_waiting(svc, item.session_id):
                try:
                    await svc.send(
                        item.session_id, prompt, display_text=label, background_result=True
                    )
                except SessionBusy:
                    pass
                except NoSuchSession:
                    return
                else:
                    return
            if (item.session_id, call_key(item.name, args)) not in self._grants:
                return  # expired while waiting for the seat
            await asyncio.sleep(_POLL_S + random.uniform(0, _POLL_S / 2))  # noqa: S311


__all__ = ["DEFER_NOTICE", "GRANT_TTL_S", "Deferred", "DeferredApprovals", "call_key"]
