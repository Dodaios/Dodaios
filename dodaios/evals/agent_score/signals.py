"""Per-turn utility from evidence the app already recorded.

``turn_utility`` maps one turn to a value in [0, 1]. Every term is a documented
signal with a weight in :mod:`.config`; nothing here calls a model.

Base: ``done`` = 1.0, ``error`` or unfinished = 0.0, ``cancelled`` = the
``cancelled_base`` weight. Then, subtracted (and clamped to [0, 1]):

* ``tool_error``      -- weight x share of the turn's tool calls that failed
* ``verify_failed`` / ``verify_unverified`` -- a ``verify_delegate`` verdict;
  ``verified`` adds the ``verified`` bonus
* ``unbacked_claim``  -- the answer claims an action as done with no tool call
* ``approval_denied`` -- the owner denied (or let expire) an approval card
* ``owner_correction`` -- the owner's next message corrects the answer
* ``repeated_request`` -- the owner's next message asks the same thing again
* ``undo``            -- an undo call, or the owner's next message asks to revert
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Final

from .config import ScoreConfig
from .turns import Turn

#: Opening words of a correction ("no, ...", "that is wrong"), English and German.
_CORRECTION: Final[re.Pattern[str]] = re.compile(
    r"^\s*(no|nope|wrong|that'?s (not|wrong)|that is (not|wrong)|not what i|i said|actually|"
    r"nein|nee|falsch|das stimmt nicht|nicht das|ich meinte|ich sagte|"  # i18n-allow: DE matcher
    r"stattdessen)\b",  # i18n-allow: DE matcher
    re.I,
)
_UNDO: Final[re.Pattern[str]] = re.compile(
    r"\b(undo|revert|roll ?back|take (that|it) back|"
    r"r(ü|ue)ckg(ä|ae)ngig)\b",  # i18n-allow: DE matcher
    re.I,
)
_WORD: Final[re.Pattern[str]] = re.compile(r"\w+", re.UNICODE)
#: A follow-up counts as "the same request again" within this long.
REPEAT_WINDOW_MS: Final[int] = 30 * 60 * 1000
REPEAT_SIMILARITY: Final[float] = 0.6


def _tokens(text: str) -> set[str]:
    return {w for w in _WORD.findall((text or "").lower()) if len(w) > 2}


def is_repeat(first: str, second: str) -> bool:
    """Whether ``second`` is (nearly) ``first`` again: Jaccard similarity of word sets."""
    a, b = _tokens(first), _tokens(second)
    if len(a) < 2 or len(b) < 2:
        return False
    return len(a & b) / len(a | b) >= REPEAT_SIMILARITY


def has_unbacked_claim(turn: Turn) -> bool:
    """The answer says an action was done / is running, and the turn made no tool call."""
    if turn.tools or not turn.answer:
        return False
    from dodaios.brain.action_honesty import has_unbacked_action_claim

    return has_unbacked_action_claim(turn.answer)


@dataclass(slots=True)
class TurnScore:
    utility: float
    signals: dict[str, float] = field(default_factory=dict)


def turn_utility(turn: Turn, cfg: ScoreConfig) -> TurnScore:
    signals: dict[str, float] = {}
    if turn.status == "done":
        value = 1.0
    elif turn.status == "cancelled":
        value = cfg.weight("cancelled_base")
        signals["cancelled"] = value - 1.0
    else:
        value = 0.0
        signals["failed_turn"] = -1.0

    def apply(name: str, amount: float) -> None:
        nonlocal value
        if amount:
            signals[name] = signals.get(name, 0.0) + amount
            value += amount

    if turn.tool_results:
        apply("tool_error", -cfg.weight("tool_error") * turn.tool_errors / turn.tool_results)
    if "failed" in turn.verdicts:
        apply("verify_failed", -cfg.weight("verify_failed"))
    elif "unverified" in turn.verdicts:
        apply("verify_unverified", -cfg.weight("verify_unverified"))
    elif "verified" in turn.verdicts:
        apply("verified", cfg.weight("verified"))
    if has_unbacked_claim(turn):
        apply("unbacked_claim", -cfg.weight("unbacked_claim"))
    if turn.denied_approvals:
        apply("approval_denied", -cfg.weight("approval_denied"))
    soon = bool(turn.next_text) and (turn.next_ts_ms - turn.ts_ms) <= REPEAT_WINDOW_MS
    if soon and is_repeat(turn.text, turn.next_text):
        apply("repeated_request", -cfg.weight("repeated_request"))
    elif soon and _CORRECTION.search(turn.next_text):
        apply("owner_correction", -cfg.weight("owner_correction"))
    if turn.undo_calls or (soon and _UNDO.search(turn.next_text)):
        apply("undo", -cfg.weight("undo"))
    return TurnScore(min(1.0, max(0.0, value)), signals)
