"""The tuner: tries nearby parameter values on practice tasks and proposes the best move.

It needs no model. For every parameter a domain measures it tries values
below and above the value in effect (1, 2, 4 and 8 steps away), each alone, on
the practice tasks. Near values find a fine adjustment; far ones matter more,
because the gate can only prove an effect that is large enough to see on its
tasks, and a row of tiny steps would each be turned down as "no clear
difference". Then it proposes at most ONE move:

* the move with the largest gain in score, when that gain is at least
  :data:`MIN_GAIN` (between equal gains the cheaper one);
* else the cheapest move that scores no worse on the practice tasks and saves
  at least :data:`MIN_SAVING` of the cost.

One small move per round keeps what the gate has to measure simple: it can say
which move helped. The gate decides on other tasks, so a move that only fits
the practice tasks does not get in; the tuner may be as greedy as it likes.

It also proposes nothing the gate turned down recently (``skip``): asking the
same question again on the same tasks would only spend the gate's error budget.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from typing import Any, Final

from dodaios.rsi.params import Index, Param

__all__ = ["MIN_GAIN", "MIN_SAVING", "Proposal", "Trial", "Tuner", "neighbours"]

#: The smallest gain in mean practice score worth proposing.
MIN_GAIN: Final[float] = 0.01
#: The smallest saving of cost worth proposing when the score does not rise.
MIN_SAVING: Final[float] = 0.05
#: Steps tried on each side of the value in effect.
_REACH: Final[tuple[int, ...]] = (1, 2, 4, 8)


@dataclass(frozen=True, slots=True)
class Trial:
    """What the practice tasks gave under some values."""

    score: float
    cost: float
    n: int


#: Runs the practice tasks with these values replacing the ones in effect.
TryValues = Callable[[Mapping[str, Any]], Trial]


@dataclass(frozen=True, slots=True)
class Proposal:
    name: str
    value: Any
    #: The value in effect it would replace.
    current: Any
    #: What the tuner saw on the practice tasks: its prediction for the gate.
    gain: float
    cost_ratio: float
    #: How many moves were tried to find it.
    tried: int

    def reason(self) -> str:
        cost = f"{abs(self.cost_ratio - 1):.0%} {'cheaper' if self.cost_ratio < 1 else 'dearer'}"
        return (
            f"on the practice tasks: {self.gain:+.3f} score, {cost}"
            f" ({self.current} -> {self.value}, best of {self.tried} moves)"
        )


def neighbours(param: Param, current: Any) -> list[Any]:
    """The values 1, 2, 4 and 8 steps away from ``current``, inside the limits."""
    if param.kind is bool:
        return [not current]
    step = param.step or (float(param.high or 0) - float(param.low or 0)) / 10 or 1
    found: list[Any] = []
    for reach in _REACH:
        for direction in (-1, 1):
            raw = float(current) + direction * reach * step
            value: Any = round(raw) if param.kind is int else round(raw, 6)
            if param.valid(value) and value != current and value not in found:
                found.append(param.coerce(value))
    return found


class Tuner:
    def __init__(self, index: Index) -> None:
        self._index = index

    def propose(
        self,
        domain: str,
        current: Mapping[str, Any],
        try_values: TryValues,
        *,
        skip: Collection[tuple[str, Any]] = (),
    ) -> Proposal | None:
        """The best single move for ``domain``, or ``None`` when nothing is worth proposing."""
        base = try_values({})
        if base.n == 0:
            return None
        moves: list[tuple[Param, Any, Trial]] = []
        for param in self._index.params:
            if domain not in param.domains:
                continue
            for value in neighbours(param, current[param.name]):
                if (param.name, value) not in skip:
                    moves.append((param, value, try_values({param.name: value})))
        if not moves:
            return None

        def ratio(trial: Trial) -> float:
            if base.cost <= 0:
                return 1.0 if trial.cost <= 0 else float("inf")
            return trial.cost / base.cost

        def proposal(move: tuple[Param, Any, Trial]) -> Proposal:
            param, value, trial = move
            gain = round(trial.score - base.score, 6)
            return Proposal(param.name, value, current[param.name], gain, ratio(trial), len(moves))

        gaining = [m for m in moves if m[2].score - base.score >= MIN_GAIN]
        if gaining:
            return proposal(max(gaining, key=lambda m: (m[2].score, -m[2].cost, m[0].name)))
        saving = [
            m for m in moves if m[2].score >= base.score and ratio(m[2]) <= 1.0 - MIN_SAVING
        ]
        if saving:
            return proposal(min(saving, key=lambda m: (m[2].cost, m[0].name)))
        return None
