"""The error budget of a split: how often the gate may ask the same tasks.

Every decision the gate makes on a split can be wrong by chance: at the level
:data:`ALPHA`, one decision in twenty lets in a change that is not better. One
such decision is fine. A hundred candidates tried on the same hundred tasks
are not: some would pass by luck, and a learner that keeps proposing would in
the end fit those very tasks.

So the tasks of a split are a budget of :data:`MAX_DECISIONS` decisions. Each
is made at :data:`ALPHA`. When the budget is used up the gate decides nothing
more on that split, and candidates wait, until new tasks arrive: when the
split has grown by a quarter (and by at least five groups) a new epoch starts,
and decisions rest on tasks the earlier candidates were never tried on.

What this guarantees, and what it does not. Each single decision errs with at
most 5 %. Over a whole epoch that is at most 0.6 wrongly admitted changes on
average. It is not a guarantee that none slips in. That is what the second
measurement is for: every admitted change has to hold again on the guard
tasks, which no candidate was ever decided on, and is checked there again
night after night (:mod:`dodaios.rsi.gate.rules`).
"""

from __future__ import annotations

from typing import Final

from dodaios.rsi.bench.model import Domain, Split
from dodaios.rsi.bench.store import BenchStore

__all__ = ["ALPHA", "MAX_DECISIONS", "AlphaLedger"]

#: Level of every single decision.
ALPHA: Final[float] = 0.05
#: Decisions one epoch of one split may make.
MAX_DECISIONS: Final[int] = 12
#: Growth of a split (in groups) that opens a new epoch.
_GROWTH: Final[float] = 0.25
_MIN_NEW_GROUPS: Final[int] = 5


class AlphaLedger:
    """Counts the decisions per domain and split, in ``bench.db``."""

    def __init__(self, store: BenchStore) -> None:
        self._store = store

    @staticmethod
    def _key(domain: Domain, split: Split) -> str:
        return f"alpha:{domain.value}:{split.value}"

    def state(self, domain: Domain, split: Split) -> dict[str, int]:
        found = self._store.get_meta(self._key(domain, split))
        return {
            "epoch": int(found.get("epoch", 1)),
            "decisions": int(found.get("decisions", 0)),
            "groups": int(found.get("groups", 0)),
        }

    def _current(self, domain: Domain, split: Split, groups: int) -> dict[str, int]:
        """The state a decision made now would count against (a new epoch after growth)."""
        state = self.state(domain, split)
        grown = groups - state["groups"]
        if state["decisions"] and grown >= max(_MIN_NEW_GROUPS, state["groups"] * _GROWTH):
            return {"epoch": state["epoch"] + 1, "decisions": 0, "groups": groups}
        if not state["decisions"]:
            state["groups"] = groups
        return state

    def left(self, domain: Domain, split: Split, groups: int) -> int:
        """How many decisions this split can still make with ``groups`` groups."""
        return max(0, MAX_DECISIONS - self._current(domain, split, groups)["decisions"])

    def spend(self, domain: Domain, split: Split, groups: int) -> float:
        """Take one decision. Returns its level, or 0.0 when the split is used up."""
        state = self._current(domain, split, groups)
        if state["decisions"] >= MAX_DECISIONS:
            return 0.0
        state["decisions"] += 1
        self._store.set_meta(self._key(domain, split), state)
        return ALPHA
