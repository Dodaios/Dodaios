"""The gate's test: bounds that stay valid at every look, and find a real effect quickly."""

from __future__ import annotations

import numpy as np
import pytest

from dodaios.rsi.sequential import ALPHA, Interval, PairedSequence, _Side, interval_of


def _ternary(rng: np.random.Generator, n: int, shift: float) -> np.ndarray:
    """Per-task differences as a deterministic check gives them: most tie, some win or lose."""
    win, lose = 0.15 + shift / 2, 0.15 - shift / 2
    u = rng.random(n)
    return np.where(u < win, 1.0, np.where(u < win + lose, -1.0, 0.0))


def _ever_better(data: np.ndarray, truth: float = 0.0) -> tuple[bool, int]:
    """Did the lower bound ever rise above ``truth``, and after how many tasks."""
    seq = PairedSequence()
    for i, d in enumerate(data, 1):
        if seq.add(float(d)).low > truth + 1e-9:
            return True, i
    return False, len(data)


def test_a_change_without_effect_is_almost_never_called_better_however_often_we_look() -> None:
    # Looked at after EVERY task and stopped at the first "better": the case an
    # ordinary 95 % test gets wrong about one time in three.
    rng = np.random.default_rng(11)
    runs = 150
    wrong = sum(_ever_better(_ternary(rng, 200, 0.0))[0] for _ in range(runs))
    # The guarantee is 5 %. 150 runs cannot tell 5 % from 8 %; they can tell it from 30 %.
    assert wrong / runs <= 2 * ALPHA, wrong


def test_the_lower_bound_does_not_overshoot_a_real_effect_either() -> None:
    rng = np.random.default_rng(12)
    runs = 100
    wrong = sum(_ever_better(_ternary(rng, 200, 0.2), truth=0.2)[0] for _ in range(runs))
    assert wrong / runs <= 2 * ALPHA, wrong


def test_a_real_effect_is_found_within_a_few_dozen_tasks() -> None:
    rng = np.random.default_rng(13)
    found = [_ever_better(_ternary(rng, 150, 0.3)) for _ in range(60)]
    assert sum(hit for hit, _ in found) >= 57
    assert float(np.median([at for hit, at in found if hit])) <= 40


def test_what_is_ruled_out_is_always_everything_up_to_one_point() -> None:
    # The wealth against a larger claim is never above the wealth against a
    # smaller one. That is why the largest ruled-out grid value is a valid bound.
    rng = np.random.default_rng(14)
    side = _Side(ALPHA, 200)
    for x in rng.random(300) ** 2:
        side.add(float(x))
        assert np.all(np.diff(side._log_wealth) <= 1e-9)
        ruled_out = side._ruled_out
        assert not np.any(ruled_out[1:] & ~ruled_out[:-1])


def test_the_interval_narrows_around_the_truth() -> None:
    assert interval_of([]) == Interval(0.0, -1.0, 1.0, 0)
    ties = interval_of([0.0] * 300)
    assert -0.05 < ties.low <= 0.0 <= ties.high < 0.05
    assert not ties.better and not ties.worse
    few = interval_of([1.0] * 5)
    assert not few.better  # five wins in a row prove nothing yet
    wins = interval_of([1.0] * 12)
    assert wins.better and wins.high == 1.0
    losses = interval_of([-1.0] * 12)
    assert losses.worse and losses.low == -1.0
    assert (wins.low, wins.high) == (-losses.high, -losses.low)


def test_the_bounds_only_ever_tighten() -> None:
    rng = np.random.default_rng(15)
    seq = PairedSequence()
    low, high = -1.0, 1.0
    for d in _ternary(rng, 250, 0.1):
        found = seq.add(float(d))
        assert found.low >= low and found.high <= high
        low, high = found.low, found.high
    assert found.n == 250


def test_the_same_differences_always_give_the_same_interval() -> None:
    data = [1.0, 0.0, -1.0, 0.5, 0.5, 0.0, 1.0] * 20
    assert interval_of(data) == interval_of(data)
    assert interval_of(data, alpha=0.01).low <= interval_of(data, alpha=0.05).low


@pytest.mark.parametrize("bad", [1.5, -1.01, float("nan"), float("inf")])
def test_a_difference_outside_the_scores_range_is_refused(bad: float) -> None:
    with pytest.raises(ValueError):
        PairedSequence().add(bad)


def test_the_level_and_the_grid_are_checked() -> None:
    for alpha in (0.0, 1.0, -0.1):
        with pytest.raises(ValueError):
            PairedSequence(alpha)
    with pytest.raises(ValueError):
        PairedSequence(grid=4)
