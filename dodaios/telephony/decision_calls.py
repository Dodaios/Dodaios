"""Calls that carry exactly one decision for the owner.

The assistant never calls uncalled. The one exception is the owner's own
opt-in "call me for urgent decisions" (``dodaios.notify.urgent_call``): it
places an outbound call whose opening states the decision once. While such a
call is registered here, what the owner says is read as a short answer, not
sent to the brain: yes, no or later. The answer settles the same approval or
question card the app shows, the call says what happened and ends. Hanging up
is the owner's kill switch and never needs more than the hang-up itself.
"""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

YES, NO, LATER = "yes", "no", "later"

_LATER = (
    "later", "not now", "wait", "remind me", "snooze", "not yet",
    "später", "spaeter", "nicht jetzt", "nachher", "warte", "noch nicht", "gleich",  # i18n-allow: spoken German
)
_NO = (
    "no", "nope", "deny", "denied", "decline", "reject", "stop", "don't", "do not", "cancel",
    "nein", "ablehnen", "lehn", "nicht", "abbrechen", "auf keinen fall",  # i18n-allow: spoken German
)
_YES = (
    "yes", "yeah", "yep", "sure", "ok", "okay", "allow", "approve", "go ahead", "do it",
    "confirm", "ja", "jawohl", "klar", "mach", "genehmigt", "erlaubt", "erlauben", "passt",
)


def _has(text: str, words: tuple[str, ...]) -> bool:
    return any(re.search(rf"(?<!\w){re.escape(w)}(?!\w)", text) for w in words)


def classify_answer(text: str) -> str | None:
    """``yes``, ``no`` or ``later`` for a short spoken answer, ``None`` when unclear.

    A "later" wins over a "no" ("not now"), and any "no" wins over a "yes"
    ("no, do it tomorrow"): when in doubt nothing runs.
    """
    said = " ".join((text or "").lower().replace("’", "'").split())
    if not said:
        return None
    if _has(said, _LATER):
        return LATER
    if _has(said, _NO):
        return NO
    if _has(said, _YES):
        return YES
    return None


@dataclass(slots=True)
class DecisionCall:
    """What one registered call does with the owner's answer."""

    #: Settle the card; returns the sentence to say before the call ends.
    resolve: Callable[[str], Awaitable[str]]
    #: Said when the answer was unclear (once; a second unclear answer means later).
    reprompt: str = ""
    #: Said when the call ends without a decision.
    later_reply: str = ""
    #: Whether a "yes" can be taken (a question with no clear recommendation cannot).
    accepts_yes: bool = True
    asked_again: bool = field(default=False)


_lock = threading.Lock()
_calls: dict[str, DecisionCall] = {}


def register(call_sid: str, call: DecisionCall) -> None:
    if call_sid:
        with _lock:
            _calls[call_sid] = call


def get(call_sid: str) -> DecisionCall | None:
    with _lock:
        return _calls.get(call_sid)


def discard(call_sid: str) -> None:
    with _lock:
        _calls.pop(call_sid, None)


def clear() -> None:
    """Tests only."""
    with _lock:
        _calls.clear()


__all__ = [
    "LATER", "NO", "YES", "DecisionCall", "classify_answer", "clear", "discard", "get", "register",
]
