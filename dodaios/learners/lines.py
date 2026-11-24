"""The line learner: tries the lead's message without one of its standing lines.

Every lead message carries standing lines (``dodaios_harness.message_lines``);
each costs tokens on every message and stays in the conversation. Some may no
longer be needed. This learner tries, on the practice tasks, the message with
one line taken out, and proposes the drop that loses nothing there and saves
the most. It proposes at most ONE drop per night, and only drops: putting a
line back is what an undo, or the gate's own check of a change in effect, does.

It only ever offers a line the kernel lists as learnable
(:data:`dodaios.rsi.lines.LEARNABLE`): a line whose effect the ``first_move``
domain can see. Taking out a line whose effect no measurement sees (the reply's
shape, a brief's wording) would pass the gate as "as good and cheaper" while
the harm happens where nothing looks; the kernel's list keeps those out, and
this learner has no way around it.

The gate decides on other tasks, as for every learner: a drop goes in only
when it is as good and at least 5 % cheaper there, or better.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from typing import Any, Final

from dodaios.learners.tuner import MIN_SAVING, Proposal, Trial, TryValues
from dodaios.rsi import lines

__all__ = ["MAX_LOSS", "LineLearner"]

#: How much lower the practice score may be for a drop still to be proposed. The
#: practice tasks are few and a model answers a little differently each time;
#: the gate, on other tasks, is what decides.
MAX_LOSS: Final[float] = 0.02


class LineLearner:
    def propose(
        self,
        current: Mapping[str, Any],
        try_values: TryValues,
        *,
        skip: Collection[tuple[str, Any]] = (),
    ) -> Proposal | None:
        """The one drop worth proposing, or ``None``.

        ``current`` holds the switches in effect; ``try_values`` runs the practice
        tasks with some switches set; ``skip`` names drops the gate turned down lately.
        """
        moves: list[tuple[str, Trial]] = []
        base: Trial | None = None
        for name in lines.LEARNABLE:  # never a line the kernel does not list
            if not bool(current.get(name, True)) or (name, False) in skip:
                continue
            if base is None:
                base = try_values({})
                if base.n == 0:
                    return None
            moves.append((name, try_values({name: False})))
        if base is None or not moves:
            return None

        def ratio(trial: Trial) -> float:
            return trial.cost / base.cost if base.cost > 0 else 1.0

        kept = [
            (name, trial)
            for name, trial in moves
            if trial.n and trial.score >= base.score - MAX_LOSS and ratio(trial) <= 1.0 - MIN_SAVING
        ]
        if not kept:
            return None
        name, trial = min(kept, key=lambda move: (move[1].cost, move[0]))
        return Proposal(
            name, False, True, round(trial.score - base.score, 6), ratio(trial), len(moves)
        )
