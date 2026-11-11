"""Value-of-information asking, measured from the ask log and the lead's turns.

Every question the ask-gate scored has a row in ``dodaios.trust.ask_log``.
This module turns the rows into rates (read-only, no model calls):

* ``needless_rate``: of the cards shown, the share the owner did not need to
  be asked: the answer was already in memory, or the owner said so ("you knew
  that", "just do it", in the answer or in the next message);
* ``should_have_asked_rate``: of the questions the gate answered by assuming
  (memory aside), the share where the owner's next message corrected or undid
  the action ("no, ...", "undo that");
* ``questions_per_turn`` and the mean turn utility with and without a card,
  the points of the questions-versus-success curve.

The correction and undo words are the score's own (``signals``); the lessons
learned from corrections feed the same signals, so both stay in step.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dodaios.agent_chat.ask_gate import ASK, ASSUME, TRIMMED
from dodaios.trust.ask_log import is_needless_signal

from .config import ScoreConfig
from .signals import _CORRECTION, _UNDO, REPEAT_WINDOW_MS, turn_utility
from .turns import Turn

_ASSUMED = frozenset({ASSUME, TRIMMED})


@dataclass(slots=True)
class _Located:
    row: dict[str, Any]
    turn: Turn | None


def _locate(row: dict[str, Any], turns: list[Turn]) -> Turn | None:
    """The lead turn the question belongs to: same session, latest start before it."""
    best: Turn | None = None
    for t in turns:
        if t.session_id != row.get("session_id") or t.ts_ms > int(row["ts_ms"]):
            continue
        if t.next_ts_ms and t.next_ts_ms <= int(row["ts_ms"]):
            continue
        if best is None or t.ts_ms > best.ts_ms:
            best = t
    return best


def _follow_up(turn: Turn | None, ts_ms: int) -> str:
    """The owner's next message when it came soon enough to be about this action."""
    if turn is None or not turn.next_text or turn.next_ts_ms - ts_ms > REPEAT_WINDOW_MS:
        return ""
    return turn.next_text


def _rate(part: int, whole: int) -> float | None:
    return part / whole if whole else None


def ask_report(
    rows: list[dict[str, Any]], turns: list[Turn], cfg: ScoreConfig | None = None
) -> dict[str, Any]:
    """The value-of-information component of the agent score."""
    cfg = cfg or ScoreConfig()
    located = [_Located(r, _locate(r, turns)) for r in rows]
    asked = [x for x in located if x.row["decision"] == ASK]
    assumed = [x for x in located if x.row["decision"] in _ASSUMED]
    from_memory = [x for x in located if x.row["decision"] == "answer_from_memory"]

    needless: list[dict[str, Any]] = []
    for x in asked:
        why = str(x.row.get("needless") or "")
        if not why and is_needless_signal(_follow_up(x.turn, int(x.row["ts_ms"]))):
            why = "owner_said_so"
        if why:
            needless.append({"question": x.row["question"], "why": why})

    should: list[dict[str, Any]] = []
    for x in assumed:
        text = _follow_up(x.turn, int(x.row["ts_ms"]))
        if text and (_CORRECTION.search(text) or _UNDO.search(text)):
            should.append({"question": x.row["question"], "reason": x.row.get("reason", "")})

    with_card: list[float] = []
    without_card: list[float] = []
    asked_turns = {id(x.turn) for x in asked if x.turn is not None}
    for t in turns:
        (with_card if id(t) in asked_turns else without_card).append(turn_utility(t, cfg).utility)

    def mean(values: list[float]) -> float | None:
        return sum(values) / len(values) if values else None

    return {
        "questions": len(rows),
        "asked": len(asked),
        "answered_from_memory": len(from_memory),
        "acted_with_assumption": len(assumed),
        "needless": len(needless),
        "should_have_asked": len(should),
        "needless_rate": _rate(len(needless), len(asked)),
        "should_have_asked_rate": _rate(len(should), len(assumed)),
        "questions_per_turn": _rate(len(asked), len(turns)),
        "utility_with_question": mean(with_card),
        "utility_without_question": mean(without_card),
        "needless_examples": needless[:5],
        "should_have_asked_examples": should[:5],
    }


def format_lines(report: dict[str, Any]) -> list[str]:
    """The component as plain text lines for the score table."""

    def pct(v: float | None) -> str:
        return "-" if v is None else f"{v * 100:.1f}%"

    return [
        "Asking (value of information):",
        f"  cards shown {report['asked']}, answered from memory {report['answered_from_memory']}, "
        f"acted with an assumption {report['acted_with_assumption']}",
        f"  needless questions: {report['needless']} ({pct(report['needless_rate'])} of cards)",
        f"  should have asked: {report['should_have_asked']} "
        f"({pct(report['should_have_asked_rate'])} of assumptions)",
    ]


__all__ = ["ask_report", "format_lines"]
