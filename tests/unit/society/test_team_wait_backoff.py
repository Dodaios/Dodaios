"""A busy member is asked again with a growing delay, not every fifteen seconds."""

from __future__ import annotations

from dodaios.society.team_lead import (
    MAX_WAIT_ATTEMPTS,
    RETRY_DELAY_S,
    RETRY_MAX_DELAY_S,
    wait_retry_delay,
)


def test_the_delay_doubles_from_the_first_knock_up_to_the_cap() -> None:
    delays = [wait_retry_delay(RETRY_DELAY_S, attempt) for attempt in range(8)]
    assert delays == [15.0, 30.0, 60.0, 120.0, 240.0, 300.0, 300.0, 300.0]
    assert RETRY_MAX_DELAY_S == 300.0


def test_a_member_busy_for_an_hour_is_still_waited_for() -> None:
    knocks = range(MAX_WAIT_ATTEMPTS)
    patience_s = sum(wait_retry_delay(RETRY_DELAY_S, attempt) for attempt in knocks)
    assert 90 * 60 <= patience_s <= 3 * 60 * 60
    assert MAX_WAIT_ATTEMPTS <= 40  # a few dozen knocks, not hundreds of board events


def test_tests_with_a_tiny_base_delay_stay_fast() -> None:
    assert wait_retry_delay(0.02, 3) == 0.16
