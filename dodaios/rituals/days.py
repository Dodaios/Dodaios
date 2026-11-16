"""Which day a moment belongs to for a ritual, and whether it is inside its window.

A ritual's day is the day its window opens on. A window over midnight
(22:00 to 02:00) opens on the evening and closes on the next morning, so
00:30 still belongs to the evening before: the phrase said at 23:30 and again
at 00:30 is one evening, the ritual's weekdays name that evening, and what is
gathered before 22:00 is for it.

The gathering ahead belongs to the start it prepares: the window that is open,
else the next one to open. A ritual that gathers from 23:00 for a window at
06:00 gathers for the next morning.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Final

from .models import Ritual, minutes_of

_DAY_MINUTES: Final[int] = 24 * 60
#: How long before its window opens a ritual may start gathering.
MAX_LEAD_MINUTES: Final[int] = 12 * 60


def _minute(moment: datetime) -> int:
    return moment.hour * 60 + moment.minute


def wraps(ritual: Ritual) -> bool:
    """Whether the ritual's window runs over midnight."""
    return bool(ritual.window_from) and (
        minutes_of(ritual.window_from) > minutes_of(ritual.window_to)
    )


def inside_window(ritual: Ritual, moment: datetime) -> bool:
    """Whether ``moment`` is inside the ritual's time window (always, without one)."""
    if not ritual.window_from:
        return True
    minute = _minute(moment)
    start, end = minutes_of(ritual.window_from), minutes_of(ritual.window_to)
    if start <= end:
        return start <= minute <= end
    return minute >= start or minute <= end


def ritual_day(ritual: Ritual, moment: datetime) -> date:
    """The day ``moment`` counts for: the day the open window opened on.

    The morning part of a window over midnight belongs to the evening before.
    """
    if wraps(ritual) and _minute(moment) <= minutes_of(ritual.window_to):
        return (moment - timedelta(days=1)).date()
    return moment.date()


def gather_day(ritual: Ritual, moment: datetime) -> date:
    """The day a gathering at ``moment`` is for: the window that is open, else the next one."""
    if not ritual.window_from or inside_window(ritual, moment):
        return ritual_day(ritual, moment)
    ahead = (minutes_of(ritual.window_from) - _minute(moment)) % _DAY_MINUTES
    return (moment + timedelta(minutes=ahead)).date()


def prepare_problem(window_from: str, window_to: str, prepare_from: str) -> str:
    """Why ``prepare_from`` makes no sense for the window, or ``""`` when it does.

    It is the start of the window, a time inside it, or a time at most
    :data:`MAX_LEAD_MINUTES` before it opens. Without a window every time of
    day is inside it.
    """
    if not prepare_from or not window_from:
        return ""
    start, end = minutes_of(window_from), minutes_of(window_to)
    prepare = minutes_of(prepare_from)
    length = (end - start) % _DAY_MINUTES
    if (prepare - start) % _DAY_MINUTES <= length:
        return ""
    if (start - prepare) % _DAY_MINUTES <= MAX_LEAD_MINUTES:
        return ""
    return (
        f"prepare_from: {prepare_from} is not before the window {window_from} to {window_to}; "
        f"gathering starts inside the window or at most {MAX_LEAD_MINUTES // 60} hours "
        "before it opens."
    )


__all__ = [
    "MAX_LEAD_MINUTES",
    "gather_day",
    "inside_window",
    "prepare_problem",
    "ritual_day",
    "wraps",
]
