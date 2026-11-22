"""Lower confidence bounds from randomisation tests, for the policy selector.

The selector asks one question per metric: is the candidate better than the
reference by more than chance, and by at least how much? It answers with a
one-sided lower bound at 95 % (``LCB95``) of the difference in means, found by
inverting a randomisation test:

* **unpaired** (a canary: different orders went to the two arms): the arm
  labels are permuted, only within blocks (version line, repository), and the
  candidate's values are shifted by ``delta``. ``LCB95`` is the smallest
  ``delta`` the test does not reject.
* **paired** (the same task under both arms): the signs of the differences
  are flipped, exactly for up to 20 pairs, else by sampling.

A percentile bootstrap is not used for decisions: on binary metrics with few
wins it gives a bound above zero where an exact test does not (3 wins, 0
losses in 30 tasks: bootstrap above zero, exact p = 0.125).

Sampling is seeded from the data, so the same data always give the same bound.
"""

from __future__ import annotations

import hashlib
import itertools
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final

__all__ = [
    "ALPHA",
    "Bound",
    "paired_lcb",
    "paired_p",
    "unpaired_lcb",
    "unpaired_p",
]

#: One-sided level of every bound.
ALPHA: Final[float] = 0.05
#: Random relabellings per test when exact enumeration is too large.
SAMPLES: Final[int] = 2000
#: Pairs up to which the sign-flip test enumerates every sign pattern.
EXACT_PAIRS: Final[int] = 16
_BISECT_STEPS: Final[int] = 24


@dataclass(frozen=True, slots=True)
class Bound:
    """A difference of means (candidate minus reference) and its lower bound."""

    diff: float
    lcb: float
    n_candidate: int
    n_reference: int
    #: Blocks that had both arms; the others were left out.
    blocks_used: int = 0


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _seed(*parts: object) -> int:
    digest = hashlib.sha256(repr(parts).encode()).hexdigest()
    return int(digest[:16], 16)


# ------------------------------------------------------------------- unpaired


def _blocked(
    candidate: Sequence[tuple[str, float]], reference: Sequence[tuple[str, float]]
) -> dict[str, tuple[list[float], list[float]]]:
    """Values by block, keeping only blocks where both arms have values."""
    blocks: dict[str, tuple[list[float], list[float]]] = {}
    for block, value in candidate:
        blocks.setdefault(block, ([], []))[0].append(float(value))
    for block, value in reference:
        blocks.setdefault(block, ([], []))[1].append(float(value))
    return {key: arms for key, arms in blocks.items() if arms[0] and arms[1]}


def _stat(blocks: dict[str, tuple[list[float], list[float]]], delta: float) -> float:
    """Weighted mean difference over blocks, with the candidate shifted by ``delta``."""
    total = sum(len(a) + len(b) for a, b in blocks.values())
    return sum(
        (len(a) + len(b)) / total * (_mean([x - delta for x in a]) - _mean(b))
        for a, b in blocks.values()
    )


def unpaired_p(
    candidate: Sequence[tuple[str, float]],
    reference: Sequence[tuple[str, float]],
    delta: float = 0.0,
    *,
    samples: int = SAMPLES,
) -> float:
    """One-sided p-value of "the candidate's mean exceeds the reference's by ``delta``".

    Values are ``(block, value)``; labels are permuted within blocks only.
    """
    blocks = _blocked(candidate, reference)
    if not blocks:
        return 1.0
    observed = _stat(blocks, delta)
    # A statistical sample, not a secret: seeded from the data so it repeats.
    rng = random.Random(_seed(sorted(candidate), sorted(reference), round(delta, 12)))  # noqa: S311
    pooled = {
        key: ([x - delta for x in a] + list(b), len(a)) for key, (a, b) in blocks.items()
    }
    at_least = 1  # the observed labelling counts itself
    for _ in range(samples):
        shuffled: dict[str, tuple[list[float], list[float]]] = {}
        for key, (values, n_a) in pooled.items():
            order = values[:]
            rng.shuffle(order)
            shuffled[key] = (order[:n_a], order[n_a:])
        if _stat(shuffled, 0.0) >= observed - 1e-12:
            at_least += 1
    return at_least / (samples + 1)


def _invert(p_of: Callable[[float], float], low: float, high: float) -> float:
    """The smallest ``delta`` in ``[low, high]`` with ``p_of(delta) > ALPHA``.

    ``p_of`` rises with ``delta``: a larger claimed improvement is easier to reject.
    """
    if p_of(low) > ALPHA:
        return low
    if p_of(high) <= ALPHA:
        return high
    for _ in range(_BISECT_STEPS):
        mid = (low + high) / 2
        if p_of(mid) <= ALPHA:
            low = mid
        else:
            high = mid
    return (low + high) / 2


def unpaired_lcb(
    candidate: Sequence[tuple[str, float]],
    reference: Sequence[tuple[str, float]],
    *,
    samples: int = SAMPLES,
) -> Bound:
    """``LCB95`` of mean(candidate) - mean(reference), blocked by the first element."""
    blocks = _blocked(candidate, reference)
    n_a = sum(len(a) for a, _ in blocks.values())
    n_b = sum(len(b) for _, b in blocks.values())
    if not blocks:
        return Bound(0.0, float("-inf"), 0, 0, 0)
    diff = _stat(blocks, 0.0)
    values = [x for a, b in blocks.values() for x in (*a, *b)]
    span = (max(values) - min(values)) or 1.0
    used_a = [(k, x) for k, (a, _) in blocks.items() for x in a]
    used_b = [(k, x) for k, (_, b) in blocks.items() for x in b]
    lcb = _invert(
        lambda d: unpaired_p(used_a, used_b, d, samples=samples), diff - 2 * span, diff
    )
    return Bound(diff, lcb, n_a, n_b, len(blocks))


# --------------------------------------------------------------------- paired


def paired_p(
    differences: Sequence[float], delta: float = 0.0, *, samples: int = SAMPLES
) -> float:
    """One-sided p-value of "the mean difference exceeds ``delta``", by sign flips."""
    shifted = [float(d) - delta for d in differences]
    nonzero = [d for d in shifted if abs(d) > 1e-12]
    if not nonzero:
        return 1.0
    observed = sum(nonzero)
    if len(nonzero) <= EXACT_PAIRS:
        at_least = 0
        total = 0
        for signs in itertools.product((1, -1), repeat=len(nonzero)):
            total += 1
            if sum(s * abs(d) for s, d in zip(signs, nonzero, strict=True)) >= observed - 1e-12:
                at_least += 1
        return at_least / total
    rng = random.Random(_seed(sorted(nonzero)))  # noqa: S311 - a sample, seeded to repeat
    at_least = 1
    for _ in range(samples):
        if sum(abs(d) * rng.choice((1, -1)) for d in nonzero) >= observed - 1e-12:
            at_least += 1
    return at_least / (samples + 1)


def paired_lcb(differences: Sequence[float], *, samples: int = SAMPLES) -> Bound:
    """``LCB95`` of the mean of paired differences (candidate minus reference)."""
    values = [float(d) for d in differences]
    if not values:
        return Bound(0.0, float("-inf"), 0, 0)
    diff = _mean(values)
    span = (max(values) - min(values)) or max(1.0, abs(diff))

    def p_of(delta: float) -> float:
        return paired_p(values, delta, samples=samples)

    lcb = _invert(p_of, diff - 2 * span, diff)
    return Bound(diff, lcb, len(values), len(values))
