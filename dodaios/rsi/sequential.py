"""Bounds on a mean that stay valid however often you look: the gate's test.

The gate runs the same tasks under two states of the assistant and gets one
difference per task (candidate score minus baseline score, between -1 and 1).
It wants to stop as soon as the answer is clear. An ordinary test at 95 % is
only valid when you look once; looking after every task and stopping at the
first "significant" result is wrong far more often than 5 %. One user has few
tasks, so waiting for a fixed large number is not an option either.

A **confidence sequence** solves both: a lower and an upper bound after every
task, such that the chance the true mean EVER leaves the bound, at any look,
is at most ``alpha``. So the gate may look after each task and stop the moment
the lower bound is above zero.

How it is built (testing by betting; Waudby-Smith and Ramdas, "Estimating
means of bounded random variables by betting", 2023). For a claimed mean ``m``
imagine a bettor who starts with 1 and, before each task, stakes a share
``lam`` of the wealth on "the next value is above ``m``". If the true mean is
at most ``m`` the bet is not favourable, and a wealth that grows to ``1 /
alpha`` has probability at most ``alpha`` (Ville's inequality), at any time.
So ``m`` is ruled out once the wealth against it reaches ``1 / alpha``, and the
lower bound is the largest value ruled out so far. The stake only uses earlier
values, larger when they varied little.

The wealth against a larger ``m`` is never above the wealth against a smaller
one, for the same data (shown in the tests). So the values ruled out are
always "everything up to some point", and checking a grid of values is exact
enough: the reported bound is the largest ruled-out grid value.

What the bound is about: the mean over tasks LIKE these (the tasks are a
sample of the person's work), not only over the tasks at hand. The order of
the tasks must not depend on their results: shuffle before looking.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

import numpy as np

__all__ = ["ALPHA", "Interval", "PairedSequence", "interval_of"]

#: One-sided level of each bound: the lower bound is wrong (too high) with at
#: most this probability over a whole run, and so is the upper bound.
ALPHA: Final[float] = 0.05
#: Values of the mean that are tested, evenly spread. 400 gives a resolution of
#: 0.005 on the scale of the differences.
GRID: Final[int] = 400
#: A stake never risks more than this share of the wealth on one task.
_CAP: Final[float] = 0.5


@dataclass(frozen=True, slots=True)
class Interval:
    """Where the mean difference lies, after ``n`` tasks."""

    mean: float
    low: float
    high: float
    n: int

    @property
    def better(self) -> bool:
        """The candidate is better: the whole interval is above zero."""
        return self.low > 0.0

    @property
    def worse(self) -> bool:
        return self.high < 0.0


class _Side:
    """The lower bound of the mean of values in [0, 1], by betting against each grid value."""

    def __init__(self, alpha: float, grid: int) -> None:
        self._claims = np.arange(1, grid, dtype=float) / grid  # the claimed means, in (0, 1)
        self._log_wealth = np.zeros(grid - 1)
        self._ruled_out = np.zeros(grid - 1, dtype=bool)
        self._limit = math.log(1.0 / alpha)
        self._alpha = alpha
        self._cap = _CAP / self._claims  # the largest stake against each claim
        self._n = 0
        self._sum = 0.0
        self._spread = 0.0  # running sum of squared distances to the running mean

    def add(self, x: float) -> None:
        # The stake is fixed BEFORE x is seen: it uses the earlier values only.
        t = self._n + 1
        variance = (0.25 + self._spread) / t
        stake = math.sqrt(2.0 * math.log(1.0 / self._alpha) / (variance * t * math.log(t + 1.0)))
        stakes = np.minimum(stake, self._cap)
        self._log_wealth += np.log1p(stakes * (x - self._claims))
        self._ruled_out |= self._log_wealth >= self._limit
        # Now the value joins the history the next stake is taken from.
        self._n = t
        self._sum += x
        mean = (0.5 + self._sum) / (t + 1)
        self._spread += (x - mean) ** 2

    @property
    def bound(self) -> float:
        """The largest claim ruled out so far; 0.0 while none is."""
        hit = np.flatnonzero(self._ruled_out)
        return float(self._claims[hit[-1]]) if hit.size else 0.0


class PairedSequence:
    """Feed it the per-task differences one by one; read the interval after each."""

    def __init__(self, alpha: float = ALPHA, *, grid: int = GRID) -> None:
        if not 0.0 < alpha < 1.0:
            raise ValueError("alpha is a probability between 0 and 1")
        if grid < 10:
            raise ValueError("the grid needs at least 10 values")
        self.alpha = alpha
        self._lower = _Side(alpha, grid)
        self._upper = _Side(alpha, grid)
        self._n = 0
        self._sum = 0.0

    def add(self, difference: float) -> Interval:
        d = float(difference)
        if not -1.0 <= d <= 1.0:  # also refuses NaN
            raise ValueError(f"a difference of two scores is between -1 and 1, not {difference!r}")
        x = (d + 1.0) / 2.0
        self._lower.add(x)
        self._upper.add(1.0 - x)  # an upper bound of x is a lower bound of 1 - x
        self._n += 1
        self._sum += d
        return self.interval

    def extend(self, differences: Iterable[float]) -> Interval:
        for difference in differences:
            self.add(difference)
        return self.interval

    @property
    def interval(self) -> Interval:
        if self._n == 0:
            return Interval(0.0, -1.0, 1.0, 0)
        low = 2.0 * self._lower.bound - 1.0
        high = 1.0 - 2.0 * self._upper.bound
        return Interval(self._sum / self._n, low, high, self._n)


def interval_of(differences: Iterable[float], *, alpha: float = ALPHA) -> Interval:
    """The interval after all of ``differences``, in the order given."""
    return PairedSequence(alpha).extend(differences)
