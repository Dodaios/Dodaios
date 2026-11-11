"""The two ways an urgent decision rings, and how a spoken answer settles its card.

``desktop_ringer`` publishes :class:`UrgentCallRinging` (the call window shows
a silent ringing card the owner answers) plus a desktop notification.
``phone_ringer`` dials the owner's number through the telephony outbound
engine and registers a :class:`DecisionCall`, so the owner's yes / no / later
settles the same approval or question card the app shows.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from dodaios.notify.reminders import notification_language, phrase
from dodaios.notify.urgent_call import RingFn, UrgentCallRinging, UrgentEvent, opening_for

log = logging.getLogger(__name__)


def is_open_fn(service: Any) -> Callable[[UrgentEvent], bool]:
    """Whether the card the event is about still waits for an answer."""

    def _open(event: UrgentEvent) -> bool:
        if event.kind == "watchdog":
            return True
        try:
            if event.kind == "approval":
                return event.ref_id in service.pending_approvals(event.session_id)
            return service._open_card(event.session_id, event.ref_id) is not None  # noqa: SLF001
        except Exception:  # noqa: BLE001 — a card we cannot read is treated as answered: no call
            log.debug("urgent call: could not read the card state", exc_info=True)
            return False

    return _open


def desktop_ringer(service: Any, notifier: Any | None) -> RingFn:
    async def _ring(event: UrgentEvent, _target: str) -> bool:
        bus = None
        try:
            bus = notifier._bus() if notifier is not None else None  # noqa: SLF001
        except Exception:  # noqa: BLE001 — without a bus the notification below still goes out
            log.debug("urgent call: no bus to ring on", exc_info=True)
        agent = _agent_name(service, event)
        if bus is not None:
            await bus.publish(
                UrgentCallRinging(
                    kind=event.kind,
                    ref_id=event.ref_id,
                    session_id=event.session_id,
                    agent=agent,
                    summary=event.summary,
                    source_layer="notify",
                )
            )
        if notifier is not None:
            lang = notification_language(event.summary)
            await notifier.notify(
                "needs_you",
                phrase("call_ring_title", lang, agent=agent),
                event.summary,
                session_id=event.session_id,
                ignore_focus=True,
            )
        return bus is not None or notifier is not None

    return _ring


def _agent_name(service: Any, event: UrgentEvent) -> str:
    if event.agent:
        return event.agent
    name = getattr(service, "assistant_name", None)
    try:
        value = name() if callable(name) else name
    except Exception:  # noqa: BLE001 — a cosmetic name; the phrase has a fallback
        value = None
    return str(value or "").strip()


def decision_for(service: Any, event: UrgentEvent) -> Any:
    """The :class:`DecisionCall` that applies a spoken answer to the event's card."""
    from dodaios.telephony.decision_calls import YES, DecisionCall

    lang = notification_language(event.summary)

    async def _resolve(answer: str) -> str:
        if event.kind == "approval":
            decision = "allow" if answer == YES else "deny"
            ok = bool(service.resolve_approval(event.session_id, event.ref_id, decision))
            if not ok:
                return phrase("call_done_gone", lang)
            return phrase("call_done_allowed" if answer == YES else "call_done_denied", lang)
        if event.kind == "question" and answer == YES and event.recommended:
            ok = bool(
                service.resolve_question(
                    event.session_id, event.ref_id, index=0, option_index=0
                )
            )
            return phrase("call_done_answered" if ok else "call_done_gone", lang)
        # A "no" to a question is not an answer: it stays open.
        return phrase("call_done_open", lang)

    return DecisionCall(
        resolve=_resolve,
        reprompt=phrase("call_reprompt", lang),
        later_reply=phrase("call_done_open", lang),
        accepts_yes=event.accepts_yes,
    )


def phone_ringer(service: Any) -> RingFn:
    async def _ring(event: UrgentEvent, number: str) -> bool:
        from dodaios.plugins.tool.call_contact import _default_call_config
        from dodaios.telephony import decision_calls
        from dodaios.telephony.outbound import place_call

        config = _default_call_config()
        if config is None:
            log.info("urgent call: telephony is not set up; the text escalation stands")
            return False
        opening = opening_for(event, _agent_name(service, event))
        try:
            sid = await asyncio.to_thread(place_call, to=number, opening=opening, **config)
        except Exception:  # noqa: BLE001 — a call that cannot be placed leaves the card open
            log.warning("urgent call: the call could not be placed", exc_info=True)
            return False
        if not sid:
            return False
        decision_calls.register(sid, decision_for(service, event))
        return True

    return _ring


__all__ = ["decision_for", "desktop_ringer", "is_open_fn", "phone_ringer"]
