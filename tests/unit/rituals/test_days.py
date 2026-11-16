"""Which day a moment counts for: windows over midnight, and gathering before the window."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from dodaios.rituals import days, prepare, service
from dodaios.rituals.models import RitualError
from tests.unit.rituals.conftest import MONDAY_0830, MORNING, settle


def _at(hour: int, minute: int = 0, *, days_later: int = 0) -> datetime:
    return MONDAY_0830.replace(hour=hour, minute=minute) + timedelta(days=days_later)


#: A ritual for the evening that ends after midnight.
NIGHT = {
    "name": "Good night",
    "phrases": ["Good night"],
    "window_from": "22:00",
    "window_to": "02:00",
    "steps": [{"when": "now", "text": "Dim the lights."}],
}


async def _code(awaitable) -> str:
    with pytest.raises(RitualError) as caught:
        await awaitable
    return caught.value.code


# ── a window over midnight ──────────────────────────────────────────────────────


async def test_the_morning_part_of_a_window_over_midnight_belongs_to_the_evening(society) -> None:
    ritual = await service.create(**NIGHT)
    assert days.ritual_day(ritual, _at(23, 30)) == date(2026, 3, 2)
    assert days.ritual_day(ritual, _at(0, 30, days_later=1)) == date(2026, 3, 2)
    # After the window closed, the next evening is a new day.
    assert days.ritual_day(ritual, _at(3, 0, days_later=1)) == date(2026, 3, 3)


async def test_once_a_day_holds_for_the_whole_evening_over_midnight(society) -> None:
    ritual = await service.create(**NIGHT)
    first = await service.fire(ritual.id, via="chat", now=_at(23, 30))
    assert first["today"]["day"] == "2026-03-02"
    # Half an hour after midnight it is still the same evening: the phrase was used.
    assert await _code(service.fire(ritual.id, via="chat", now=_at(0, 30, days_later=1))) == "state"
    found = service.find_match("Good night", wake_phrase="", now=_at(0, 30, days_later=1))
    assert found is not None and found.blocked == "done_today"
    # The next evening it starts again.
    assert service.find_match("Good night", wake_phrase="", now=_at(22, 30, days_later=1)).fires
    await settle()


async def test_the_weekday_of_a_window_over_midnight_is_the_evening_it_opened_on(
    society,
) -> None:
    friday_2300 = _at(23, 0, days_later=4)
    assert friday_2300.weekday() == 4
    ritual = await service.create(**{**NIGHT, "weekdays": [4]})
    assert service.why_not(ritual, friday_2300, phrase_used=False) == ""
    # 00:30 on Saturday is still Friday night.
    assert service.why_not(ritual, friday_2300 + timedelta(minutes=90), phrase_used=False) == ""
    # Saturday night is not Friday's.
    saturday_2300 = friday_2300 + timedelta(days=1)
    assert service.why_not(ritual, saturday_2300, phrase_used=False) == "day"
    # And Friday 00:30 belongs to Thursday night.
    assert service.why_not(ritual, _at(0, 30, days_later=4), phrase_used=False) == "day"


async def test_the_panel_shows_the_evening_after_midnight(society) -> None:
    ritual = await service.create(**NIGHT)
    await service.fire(ritual.id, via="chat", now=_at(23, 30))
    after_midnight = _at(0, 30, days_later=1)
    assert service.today_of(ritual.id, now=after_midnight).day == "2026-03-02"
    (listed,) = service.overview(now=after_midnight)["rituals"]
    assert listed["today"]["day"] == "2026-03-02"
    await settle()


# ── gathering before the window ─────────────────────────────────────────────────


async def test_gathering_before_midnight_is_for_the_next_morning(society) -> None:
    ritual = await service.create(
        **{**MORNING, "window_from": "06:00", "window_to": "09:00", "prepare_from": "23:00"}
    )
    sunday_2300 = _at(23, 0, days_later=-1)
    assert prepare.due(ritual, sunday_2300, None)
    # The run at 23:00 on Sunday gathers for Monday's start, which looks there.
    assert days.gather_day(ritual, sunday_2300).isoformat() == "2026-03-02"
    assert service.ritual_day_of(ritual, _at(7, 0)) == "2026-03-02"
    # Inside the window it is the window's own day.
    assert days.gather_day(ritual, _at(7, 0)).isoformat() == "2026-03-02"


async def test_the_weekday_of_a_gathering_is_the_one_of_the_start_it_prepares(society) -> None:
    ritual = await service.create(
        **{
            **MORNING, "window_from": "06:00", "window_to": "09:00", "prepare_from": "23:00",
            "weekdays": [0],
        }
    )
    # Sunday 23:00 gathers for Monday morning, Monday 23:00 for Tuesday's (not on the list).
    assert prepare.due(ritual, _at(23, 0, days_later=-1), None)
    assert not prepare.due(ritual, _at(23, 0), None)


async def test_a_gathering_time_that_makes_no_sense_is_refused(society) -> None:
    morning = {**MORNING, "window_from": "06:00", "window_to": "09:00"}
    # Inside the window, and up to twelve hours before it opens, are fine.
    for fine in ("06:00", "07:30", "05:00", "18:00"):
        assert (await service.create(**{**morning, "name": f"r {fine}", "prepare_from": fine,
                                        "phrases": [f"phrase {fine}"]})).prepare_from == fine
    # After the window closed and long before the next one, it is no time to gather.
    assert await _code(service.create(**{**morning, "name": "late", "phrases": ["late one"],
                                         "prepare_from": "10:00"})) == "invalid"
    assert days.prepare_problem("06:00", "09:00", "17:59")
    assert days.prepare_problem("", "", "17:59") == ""
    # A window over midnight takes a time before it, or inside it.
    assert days.prepare_problem("22:00", "02:00", "21:00") == ""
    assert days.prepare_problem("22:00", "02:00", "01:00") == ""
    assert days.prepare_problem("22:00", "02:00", "03:00")
