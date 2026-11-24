"""The line learner: tries the lead's message with one standing line changed.

Every lead message carries standing lines (``dodaios_harness.message_lines``);
each costs tokens on every message and stays in the conversation. Some may no
longer be needed, and some may work better in another of their fixed wordings.
This learner tries, on the practice tasks, the message with one line taken out
(a switch) or worded another way (a wording), and proposes at most ONE change
per night: the one that scores clearly better there, else the one that loses
nothing and saves the most. It never moves a line back to how it ships:
putting a line back is what an undo, or the gate's own check of a change in
effect, does.

It only ever offers a line the kernel lists as learnable
(:data:`dodaios.rsi.lines.LEARNABLE`), and only the lines of the domain it is
asked about (``current`` holds those): a change whose effect the domain cannot
see (the reply's shape, a brief's wording on a first move) would pass the gate
as "as good and cheaper" while the harm happens where nothing looks. The
kernel's list keeps those out, and this learner has no way around it.

The gate decides on other tasks, as for every learner: a change goes in only
when it is better there, or as good and at least 5 % cheaper.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from typing import Any, Final

from dodaios.learners.tuner import MIN_GAIN, MIN_SAVING, Proposal, Trial, TryValues
from dodaios.rsi import lines

__all__ = ["MAX_LOSS", "LineLearner"]

#: How much lower the practice score may be for a change still to be proposed. The
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
        """The one change worth proposing, or ``None``.

        ``current`` holds the line parameters of the domain asked about, with
        their values in effect; no other line is tried. ``try_values`` runs the
        practice tasks with some of them set; ``skip`` names changes the gate
        turned down lately.
        """
        moves: list[tuple[str, Any, Trial]] = []
        base: Trial | None = None
        for name in lines.LEARNABLE:  # never a line the kernel does not list
            if name not in current:
                continue  # a line of another domain: this one cannot see it
            for value in lines.alternatives(name, current[name]):
                if (name, value) in skip:
                    continue
                if base is None:
                    base = try_values({})
                    if base.n == 0:
                        return None
                moves.append((name, value, try_values({name: value})))
        if base is None or not moves:
            return None

        def ratio(trial: Trial) -> float:
            return trial.cost / base.cost if base.cost > 0 else 1.0

        def proposal(move: tuple[str, Any, Trial]) -> Proposal:
            name, value, trial = move
            gain = round(trial.score - base.score, 6)
            return Proposal(name, value, current[name], gain, ratio(trial), len(moves))

        tried = [move for move in moves if move[2].n]
        gaining = [m for m in tried if m[2].score - base.score >= max(MIN_GAIN, MAX_LOSS)]
        if gaining:
            return proposal(max(gaining, key=lambda m: (m[2].score, -m[2].cost, m[0])))
        kept = [
            m
            for m in tried
            if m[2].score >= base.score - MAX_LOSS and ratio(m[2]) <= 1.0 - MIN_SAVING
        ]
        if not kept:
            return None
        return proposal(min(kept, key=lambda m: (m[2].cost, m[0], str(m[1]))))
