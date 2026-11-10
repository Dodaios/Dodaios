"""Plain-speech times (dodaios/notify/when.py)."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from dodaios.notify.when import DEFAULT_HOUR, clean_text, parse_when, strip_when

BERLIN = ZoneInfo("Europe/Berlin")
#: A Tuesday, mid-morning.
NOW = datetime(2026, 11, 10, 10, 30, tzinfo=BERLIN)


def _at(text: str) -> datetime:
    parsed = parse_when(text, now=NOW)
    assert parsed is not None, text
    return parsed.at


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("remind me Friday at 9 about the taxes", datetime(2026, 11, 13, 9, 0, tzinfo=BERLIN)),
        ("tomorrow call Anna", datetime(2026, 11, 11, DEFAULT_HOUR, 0, tzinfo=BERLIN)),
        ("in 20 minutes take the pizza out", datetime(2026, 11, 10, 10, 50, tzinfo=BERLIN)),
        ("in 2 hours", datetime(2026, 11, 10, 12, 30, tzinfo=BERLIN)),
        ("dentist on 14.11. at 15:30", datetime(2026, 11, 14, 15, 30, tzinfo=BERLIN)),
        ("Nov 14 pay the rent", datetime(2026, 11, 14, DEFAULT_HOUR, 0, tzinfo=BERLIN)),
        ("next week plan the trip", datetime(2026, 11, 16, DEFAULT_HOUR, 0, tzinfo=BERLIN)),
        ("tonight water the plants", datetime(2026, 11, 10, 20, 0, tzinfo=BERLIN)),
        ("at 5 pm call the bank", datetime(2026, 11, 10, 17, 0, tzinfo=BERLIN)),
        ("2026-12-01 09:00 renew passport", datetime(2026, 12, 1, 9, 0, tzinfo=BERLIN)),
        ("in 3 days at 10 check the offer", datetime(2026, 11, 13, 10, 0, tzinfo=BERLIN)),
        # A bare time that already passed today means tomorrow.
        ("at 8:00 stretch", datetime(2026, 11, 11, 8, 0, tzinfo=BERLIN)),
        # A date earlier in the year means next year.
        ("on 3.1. taxes", datetime(2027, 1, 3, DEFAULT_HOUR, 0, tzinfo=BERLIN)),
    ],
)
def test_english_phrases(text: str, expected: datetime) -> None:
    assert _at(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "erinnere mich morgen um 9 Uhr an die Steuer",  # i18n-allow
            datetime(2026, 11, 11, 9, 0, tzinfo=BERLIN),
        ),
        (
            "übermorgen abend Oma anrufen",  # i18n-allow
            datetime(2026, 11, 12, 19, 0, tzinfo=BERLIN),
        ),
        ("in einer Stunde Wäsche", datetime(2026, 11, 10, 11, 30, tzinfo=BERLIN)),  # i18n-allow
        (
            "recuérdame el viernes a las 18:00 comprar leche",
            datetime(2026, 11, 13, 18, 0, tzinfo=BERLIN),
        ),
        ("lembra-me amanhã às 8h de enviar o email", datetime(2026, 11, 11, 8, 0, tzinfo=BERLIN)),
    ],
)
def test_other_input_languages(text: str, expected: datetime) -> None:
    assert _at(text) == expected


def test_the_time_words_are_stripped_from_the_text() -> None:
    cases = {
        "remind me Friday at 9 about the taxes": "the taxes",
        "remind me tomorrow to call Anna": "call Anna",
        "in 20 minutes take the pizza out": "take the pizza out",
        "dentist on 14.11. at 15:30": "dentist",
        "erinnere mich morgen um 9 Uhr an die Steuer": "die Steuer",
        "recuérdame el viernes a las 18:00 comprar leche": "comprar leche",
        "lembra-me amanhã às 8h de enviar o email": "enviar o email",
    }
    for text, expected in cases.items():
        parsed = parse_when(text, now=NOW)
        assert parsed is not None
        assert strip_when(text, parsed) == expected, text


def test_nothing_time_like_returns_none() -> None:
    assert parse_when("mail Anna about the offer", now=NOW) is None
    # A bare number is a quantity, not a clock time.
    assert parse_when("buy 3 apples", now=NOW) is None
    assert parse_when("", now=NOW) is None


def test_has_time_tells_a_named_clock_from_the_default_hour() -> None:
    assert parse_when("Friday at 9", now=NOW).has_time is True
    assert parse_when("Friday", now=NOW).has_time is False
    assert parse_when("in 10 minutes", now=NOW).has_time is False


def test_next_weekday_skips_today() -> None:
    assert _at("next tuesday") == datetime(2026, 11, 17, DEFAULT_HOUR, 0, tzinfo=BERLIN)
    assert _at("tuesday") == datetime(2026, 11, 10, DEFAULT_HOUR, 0, tzinfo=BERLIN)


def test_now_must_be_aware() -> None:
    with pytest.raises(ValueError):
        parse_when("tomorrow", now=datetime(2026, 11, 10, 10, 30))


def test_clean_text_drops_the_lead_in() -> None:
    assert clean_text("remind me to call Anna") == "call Anna"
    assert clean_text("Erinnere mich daran, die Steuer zu machen") == "die Steuer zu machen"
    assert clean_text("water the plants") == "water the plants"
