"""What the gate found about one change: the record a decision rests on.

The gate compares two states of the assistant on the same tasks (the change
applied against the state it was measured from) and answers one of four
things. The registry acts on the answer and stores the whole record, so every
change that is live can show the numbers that let it in.

``accept``      the change is better where it claimed to be, and nowhere
                clearly worse.
``reject``      it is worse, or it broke a hard rule.
``undecided``   not enough tasks yet; the change stays a candidate.
``unmeasured``  no check exists that could tell (a jury that cannot be
                trusted, a domain without tasks). Nothing is applied on it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

__all__ = ["Effect", "Evidence", "Verdict"]


class Verdict(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"
    UNDECIDED = "undecided"
    UNMEASURED = "unmeasured"


@dataclass(frozen=True, slots=True)
class Effect:
    """The measured difference in one domain: candidate minus baseline, per task."""

    domain: str
    #: Mean per-task difference of the scores (-1.0 to 1.0).
    diff: float
    #: Bounds of a confidence sequence: valid however often the gate looked.
    low: float
    high: float
    #: Pairs that counted.
    n: int
    #: Mean cost per task: candidate minus baseline, in USD.
    cost_diff: float = 0.0

    def public(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Evidence:
    verdict: Verdict
    #: The domain the change claimed to improve, and what was measured there.
    target: Effect | None = None
    #: Every other measured domain (the change must not clearly lose there).
    others: tuple[Effect, ...] = ()
    #: Fingerprint id of the state the change was measured against. A change is
    #: only applied while the live state still has this id.
    baseline: str = ""
    #: The split the numbers come from.
    split: str = ""
    #: Share of the error budget this decision used up.
    alpha: float = 0.0
    reason: str = ""

    @property
    def accepted(self) -> bool:
        return self.verdict is Verdict.ACCEPT

    def public(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "target": self.target.public() if self.target else None,
            "others": [e.public() for e in self.others],
            "baseline": self.baseline,
            "split": self.split,
            "alpha": self.alpha,
            "reason": self.reason,
        }
