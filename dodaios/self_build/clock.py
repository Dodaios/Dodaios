"""The person's wall clock for the self-building loop.

Habits are counted, and routines scheduled, on the person's own clock. The
zone their UI reported (``dodaios.tasks.context``) is used whenever it is
known. Until the UI has reported one (a fresh start, a headless install, a
call made before any window opened), the loop falls back to this computer's
own zone and says so in the log once: on a desktop the computer is the
person's, and without any zone habits would not be counted at all and a
routine build would wait in ``building`` forever.

The computer's zone is read as an IANA name, because a routine stores its
zone by name: ``TZ``, ``/etc/timezone`` or the ``/etc/localtime`` link on
POSIX, the registry's zone key on Windows. Every candidate is checked against
the offsets the operating system itself reports over the coming year, and
when no named candidate matches, the first well-known zone with the same
offsets is taken (same offsets means the same wall clock for every run).
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Final

log = logging.getLogger(__name__)

#: Offsets are compared at this many instants over the next year.
_SAMPLES: Final[int] = 26
_SAMPLE_STEP: Final[timedelta] = timedelta(days=14)

#: Windows zone keys and their IANA zones (the CLDR "001" mapping, common ones).
#: Each is still checked against the system's offsets before it is used.
WINDOWS_ZONES: Final[dict[str, str]] = {
    "UTC": "Etc/UTC",
    "GMT Standard Time": "Europe/London",
    "Greenwich Standard Time": "Atlantic/Reykjavik",
    "W. Europe Standard Time": "Europe/Berlin",
    "Romance Standard Time": "Europe/Paris",
    "Central Europe Standard Time": "Europe/Budapest",
    "Central European Standard Time": "Europe/Warsaw",
    "E. Europe Standard Time": "Europe/Chisinau",
    "FLE Standard Time": "Europe/Kiev",
    "GTB Standard Time": "Europe/Bucharest",
    "Russian Standard Time": "Europe/Moscow",
    "Turkey Standard Time": "Europe/Istanbul",
    "Israel Standard Time": "Asia/Jerusalem",
    "Egypt Standard Time": "Africa/Cairo",
    "South Africa Standard Time": "Africa/Johannesburg",
    "W. Central Africa Standard Time": "Africa/Lagos",
    "E. Africa Standard Time": "Africa/Nairobi",
    "Morocco Standard Time": "Africa/Casablanca",
    "Arab Standard Time": "Asia/Riyadh",
    "Arabian Standard Time": "Asia/Dubai",
    "Iran Standard Time": "Asia/Tehran",
    "Pakistan Standard Time": "Asia/Karachi",
    "India Standard Time": "Asia/Kolkata",
    "Nepal Standard Time": "Asia/Kathmandu",
    "Bangladesh Standard Time": "Asia/Dhaka",
    "SE Asia Standard Time": "Asia/Bangkok",
    "China Standard Time": "Asia/Shanghai",
    "Singapore Standard Time": "Asia/Singapore",
    "Taipei Standard Time": "Asia/Taipei",
    "Tokyo Standard Time": "Asia/Tokyo",
    "Korea Standard Time": "Asia/Seoul",
    "W. Australia Standard Time": "Australia/Perth",
    "Cen. Australia Standard Time": "Australia/Adelaide",
    "E. Australia Standard Time": "Australia/Brisbane",
    "AUS Eastern Standard Time": "Australia/Sydney",
    "New Zealand Standard Time": "Pacific/Auckland",
    "Hawaiian Standard Time": "Pacific/Honolulu",
    "Alaskan Standard Time": "America/Anchorage",
    "Pacific Standard Time": "America/Los_Angeles",
    "US Mountain Standard Time": "America/Phoenix",
    "Mountain Standard Time": "America/Denver",
    "Central Standard Time": "America/Chicago",
    "Central Standard Time (Mexico)": "America/Mexico_City",
    "Canada Central Standard Time": "America/Regina",
    "Eastern Standard Time": "America/New_York",
    "SA Pacific Standard Time": "America/Bogota",
    "Atlantic Standard Time": "America/Halifax",
    "Newfoundland Standard Time": "America/St_Johns",
    "Pacific SA Standard Time": "America/Santiago",
    "E. South America Standard Time": "America/Sao_Paulo",
    "Argentina Standard Time": "America/Buenos_Aires",
}

#: Tried first when only the offsets are known, so a match reads familiar.
_WELL_KNOWN: Final[tuple[str, ...]] = (
    "Europe/London",
    "Europe/Berlin",
    "Europe/Paris",
    "Europe/Madrid",
    "Europe/Rome",
    "Europe/Lisbon",
    "Europe/Athens",
    "Europe/Helsinki",
    "Europe/Moscow",
    "Europe/Istanbul",
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Phoenix",
    "America/Los_Angeles",
    "America/Anchorage",
    "Pacific/Honolulu",
    "America/Halifax",
    "America/Mexico_City",
    "America/Bogota",
    "America/Sao_Paulo",
    "America/Buenos_Aires",
    "Africa/Lagos",
    "Africa/Johannesburg",
    "Africa/Cairo",
    "Africa/Nairobi",
    "Asia/Dubai",
    "Asia/Kolkata",
    "Asia/Bangkok",
    "Asia/Shanghai",
    "Asia/Singapore",
    "Asia/Tokyo",
    "Asia/Seoul",
    "Australia/Perth",
    "Australia/Brisbane",
    "Australia/Adelaide",
    "Australia/Sydney",
    "Pacific/Auckland",
    "Etc/UTC",
)

_lock = threading.Lock()
_logged: set[str] = set()


def _zone(name: str) -> Any | None:
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except (KeyError, ValueError, OSError):  # an unknown or malformed zone name
        return None


def _system_offsets(start: float) -> tuple[timedelta | None, ...]:
    """What the operating system says the local offset is at each sample instant."""
    out: list[timedelta | None] = []
    for i in range(_SAMPLES):
        ts = start + i * _SAMPLE_STEP.total_seconds()
        try:
            out.append(datetime.fromtimestamp(ts).astimezone().utcoffset())
        except (OverflowError, OSError, ValueError):  # a platform without that instant
            out.append(None)
    return tuple(out)


def _matches(zone: Any, start: float, offsets: tuple[timedelta | None, ...]) -> bool:
    for i, expected in enumerate(offsets):
        if expected is None:
            continue
        moment = datetime.fromtimestamp(start + i * _SAMPLE_STEP.total_seconds(), tz=UTC)
        if moment.astimezone(zone).utcoffset() != expected:
            return False
    return True


def _tz_variable() -> str:
    return (os.environ.get("TZ") or "").strip().lstrip(":")


def _posix_candidates() -> list[str]:
    names: list[str] = []
    try:
        text = Path("/etc/timezone").read_text(encoding="utf-8").strip()
        if text:
            names.append(text.split()[0])
    except OSError:  # no such file on this system
        pass
    try:
        target = os.path.realpath("/etc/localtime")
        marker = "zoneinfo" + os.sep
        if marker in target:
            names.append(target.split(marker, 1)[1].replace(os.sep, "/"))
    except OSError:  # no localtime link
        pass
    return names


def _windows_candidates() -> list[str]:
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\TimeZoneInformation",
        ) as key:
            value, _kind = winreg.QueryValueEx(key, "TimeZoneKeyName")
    except OSError:  # an unreadable registry: the offsets decide
        return []
    mapped = WINDOWS_ZONES.get(str(value).strip().rstrip("\x00"))
    return [mapped] if mapped else []


@lru_cache(maxsize=1)
def _system_zone_cached(_hour: int) -> str | None:
    start = time.time()
    offsets = _system_offsets(start)
    candidates: list[str] = []
    env = _tz_variable()
    if env:
        candidates.append(env)
    candidates += _windows_candidates() if sys.platform == "win32" else _posix_candidates()
    for name in candidates:
        zone = _zone(name)
        if zone is not None and _matches(zone, start, offsets):
            return name
    for name in _WELL_KNOWN:
        zone = _zone(name)
        if zone is not None and _matches(zone, start, offsets):
            return name
    try:
        from zoneinfo import available_timezones

        names = sorted(n for n in available_timezones() if "/" in n and not n.startswith("Etc/"))
    except Exception:  # noqa: BLE001 - no zone database: nothing can be named
        return None
    for name in names:
        zone = _zone(name)
        if zone is not None and _matches(zone, start, offsets):
            return name
    return None


def system_zone_name() -> str | None:
    """This computer's zone as an IANA name, or ``None`` when none matches. Blocking.

    Read at most once an hour (a moved laptop is noticed within the hour).
    """
    return _system_zone_cached(int(time.time() // 3600))


def person_zone_name() -> str | None:
    """The zone the person's UI reported, else this computer's (logged once)."""
    from dodaios.tasks.context import turn_timezone

    reported = turn_timezone()
    if reported and _zone(reported) is not None:
        return reported
    fallback = system_zone_name()
    if fallback:
        with _lock:
            fresh = fallback not in _logged
            _logged.add(fallback)
        if fresh:
            log.info(
                "self_build: the UI has not reported a time zone; habits and routines use "
                "this computer's zone %s until it does",
                fallback,
            )
    return fallback


def person_zone() -> Any | None:
    name = person_zone_name()
    return _zone(name) if name else None


def reset_for_tests() -> None:
    _system_zone_cached.cache_clear()
    with _lock:
        _logged.clear()


__all__ = [
    "WINDOWS_ZONES",
    "person_zone",
    "person_zone_name",
    "reset_for_tests",
    "system_zone_name",
]
