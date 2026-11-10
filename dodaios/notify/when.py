"""When is "Friday at 9"? Plain-speech times without a model call.

Covers what people say to set a reminder, in the shipped input languages
(English, German, Spanish, Portuguese): relative spans ("in 20 minutes"),
day words ("tomorrow", "day after tomorrow"), weekdays, parts of the day
("evening"), clock times ("at 9", "9:30", "5 pm", "17 Uhr") and dates
("14.11.", "Nov 14", "2026-11-14"). Anything else returns ``None`` and the
caller asks.

Every result is an aware ``datetime`` in the person's zone. A date without a
time gets :data:`DEFAULT_HOUR`; a time without a date means today, or
tomorrow when the time has passed. The matched words are reported as spans so
the reminder text can be cleaned of them ("remind me Friday at 9 about the
taxes" -> "the taxes").
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Final

DEFAULT_HOUR: Final[int] = 9

#: Hour each part of the day stands for.
PARTS: Final[dict[str, int]] = {
    "morning": 8,
    "noon": 12,
    "afternoon": 15,
    "evening": 19,
    "night": 20,
}


@dataclass(frozen=True)
class ParsedWhen:
    at: datetime
    #: Character spans of the words that named the time, for stripping.
    spans: tuple[tuple[int, int], ...] = field(default_factory=tuple)
    #: Whether the person named a clock time (else the default hour was used).
    has_time: bool = True


_W = r"(?<![\w])"
_E = r"(?![\w])"


def _alts(*words: str) -> str:
    return "(?:" + "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True)) + ")"


# -- vocabulary (non-English words are input vocabulary, not output text) ---

_MINUTES = _alts("minutes", "minute", "mins", "min", "minuten", "minutos", "minuto")  # i18n-allow
_HOURS = _alts("hours", "hour", "hrs", "hr", "stunden", "stunde", "horas", "hora")  # i18n-allow
_DAYS = _alts("days", "day", "tagen", "tage", "tag", "días", "dias", "día", "dia")  # i18n-allow
_WEEKS = _alts("weeks", "week", "wochen", "woche", "semanas", "semana")  # i18n-allow
_IN = _alts("in", "en", "em", "dentro de", "daqui a")  # i18n-allow
_NUM_WORDS: Final[dict[str, int]] = {
    "a": 1,
    "an": 1,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "ten": 10,
    "einer": 1,
    "einem": 1,
    "eine": 1,
    "ein": 1,
    "zwei": 2,
    "drei": 3,  # i18n-allow
    "vier": 4,
    "fünf": 5,  # i18n-allow
    "zehn": 10,  # i18n-allow
    "un": 1,
    "una": 1,
    "uno": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,  # i18n-allow
    "diez": 10,
    "um": 1,
    "uma": 1,
    "dois": 2,
    "duas": 2,
    "três": 3,
    "quatro": 4,  # i18n-allow
    "dez": 10,  # i18n-allow
    "half an": 0,
    "halbe": 0,
    "halben": 0,
    "media": 0,
    "meia": 0,  # i18n-allow — half an hour
}
_NUM = (
    r"(\d{1,3}|" + "|".join(re.escape(w) for w in sorted(_NUM_WORDS, key=len, reverse=True)) + ")"
)

_RELATIVE = re.compile(rf"{_W}{_IN}\s+{_NUM}\s+({_MINUTES}|{_HOURS}|{_DAYS}|{_WEEKS}){_E}", re.I)

_DAY_WORDS: Final[dict[str, int]] = {
    "today": 0,
    "tonight": 0,
    "tomorrow": 1,
    "day after tomorrow": 2,
    "the day after tomorrow": 2,
    "heute": 0,
    "heute abend": 0,
    "morgen": 1,
    "übermorgen": 2,  # i18n-allow
    "hoy": 0,
    "esta noche": 0,
    "mañana": 1,
    "pasado mañana": 2,  # i18n-allow
    "hoje": 0,
    "hoje à noite": 0,
    "amanhã": 1,
    "depois de amanhã": 2,  # i18n-allow
}
#: Day words that also name an evening.
_NIGHT_WORDS: Final[frozenset[str]] = frozenset(
    {"tonight", "heute abend", "esta noche", "hoje à noite"}  # i18n-allow
)
_DAY_WORD = re.compile(
    _W + "(" + "|".join(re.escape(w) for w in sorted(_DAY_WORDS, key=len, reverse=True)) + ")" + _E,
    re.I,
)

_WEEKDAYS: Final[dict[str, int]] = {
    "monday": 0,
    "mon": 0,
    "tuesday": 1,
    "tue": 1,
    "tues": 1,
    "wednesday": 2,
    "wed": 2,
    "thursday": 3,
    "thu": 3,
    "thurs": 3,
    "friday": 4,
    "fri": 4,
    "saturday": 5,
    "sat": 5,
    "sunday": 6,
    "sun": 6,
    "montag": 0,
    "dienstag": 1,
    "mittwoch": 2,
    "donnerstag": 3,
    "freitag": 4,  # i18n-allow
    "samstag": 5,
    "sonnabend": 5,
    "sonntag": 6,  # i18n-allow
    "lunes": 0,
    "martes": 1,
    "miércoles": 2,
    "miercoles": 2,
    "jueves": 3,  # i18n-allow
    "viernes": 4,  # i18n-allow
    "sábado": 5,
    "sabado": 5,
    "domingo": 6,  # i18n-allow
    "segunda": 0,
    "segunda-feira": 0,
    "terça": 1,
    "terça-feira": 1,
    "quarta": 2,  # i18n-allow
    "quarta-feira": 2,
    "quinta": 3,
    "quinta-feira": 3,
    "sexta": 4,
    "sexta-feira": 4,  # i18n-allow
}
_NEXT = _alts(
    "next",
    "nächsten",  # i18n-allow
    "nächste",  # i18n-allow
    "kommenden",
    "el próximo",
    "próximo",
    "próxima",  # i18n-allow
    "na",  # i18n-allow
)
_ON = _alts(
    "on",
    "am",
    "el",
    "na",
    "no",
    "this",
    "diesen",
    "este",
    "esta",
    "nesta",
    "neste",  # i18n-allow
)
_WEEKDAY = re.compile(
    rf"{_W}(?:({_NEXT})\s+|{_ON}\s+)?("
    + "|".join(re.escape(w) for w in sorted(_WEEKDAYS, key=len, reverse=True))
    + rf"){_E}\.?",
    re.I,
)
_NEXT_WEEK = re.compile(
    rf"{_W}(?:next week|nächste woche|la próxima semana|la semana que viene|"  # i18n-allow
    rf"na próxima semana|semana que vem){_E}",  # i18n-allow
    re.I,
)

_PART_WORDS: Final[dict[str, str]] = {
    "morning": "morning",
    "noon": "noon",
    "midday": "noon",
    "afternoon": "afternoon",
    "evening": "evening",
    "night": "night",
    "früh": "morning",  # i18n-allow
    "morgens": "morning",
    "vormittag": "morning",  # i18n-allow
    "mittag": "noon",  # i18n-allow
    "mittags": "noon",
    "nachmittag": "afternoon",
    "nachmittags": "afternoon",  # i18n-allow
    "abend": "evening",
    "abends": "evening",
    "nachts": "night",  # i18n-allow
    "mañana por la": "morning",
    "mediodía": "noon",
    "tarde": "afternoon",  # i18n-allow
    "noche": "night",  # i18n-allow
    "manhã": "morning",
    "meio-dia": "noon",
    "noite": "night",  # i18n-allow
}
_PART = re.compile(
    rf"{_W}(?:in the|am|por la|pela|de|à|at)?\s*("  # i18n-allow
    + "|".join(re.escape(w) for w in sorted(_PART_WORDS, key=len, reverse=True))
    + rf"){_E}",
    re.I,
)

_AT = _alts("at", "um", "a las", "a la", "às", "à", "as")  # i18n-allow
_CLOCK = re.compile(
    rf"{_W}(?:{_AT}\s+)?(\d{{1,2}})(?::(\d{{2}})|[h.](\d{{2}})|\s*h(?![\w]))?"
    rf"(?:\s*(a\.?m\.?|p\.?m\.?)|\s*(uhr))?{_E}",  # i18n-allow
    re.I,
)
_NOON_MIDNIGHT: Final[dict[str, int]] = {
    "noon": 12,
    "midnight": 0,
    "mitternacht": 0,
    "medianoche": 0,
    "meia-noite": 0,  # i18n-allow
}

_MONTHS: Final[dict[str, int]] = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
    "januar": 1,
    "februar": 2,
    "märz": 3,  # i18n-allow
    "mai": 5,
    "juni": 6,
    "juli": 7,
    "okt": 10,  # i18n-allow
    "oktober": 10,
    "dez": 12,
    "dezember": 12,  # i18n-allow
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,  # i18n-allow
    "julio": 7,  # i18n-allow
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,  # i18n-allow
    "diciembre": 12,
    "janeiro": 1,
    "fevereiro": 2,
    "março": 3,
    "maio": 5,
    "junho": 6,  # i18n-allow
    "julho": 7,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,  # i18n-allow
}
_MONTH = "(" + "|".join(re.escape(m) for m in sorted(_MONTHS, key=len, reverse=True)) + r")\.?"
_ISO_DATE = re.compile(rf"{_W}(\d{{4}})-(\d{{2}})-(\d{{2}})(?:[T ](\d{{2}}):(\d{{2}}))?{_E}")
_NUMERIC_DATE = re.compile(rf"{_W}(\d{{1,2}})[./](\d{{1,2}})(?:[./](\d{{2,4}}))?(?![\d:])")
_DAY_MONTH = re.compile(
    rf"{_W}(\d{{1,2}})(?:st|nd|rd|th)?\.?\s+(?:of\s+|de\s+)?{_MONTH}{_E}",
    re.I,  # i18n-allow
)
_MONTH_DAY = re.compile(rf"{_W}{_MONTH}\s+(\d{{1,2}})(?:st|nd|rd|th)?{_E}", re.I)


def _overlaps(span: tuple[int, int], taken: list[tuple[int, int]]) -> bool:
    return any(span[0] < end and start < span[1] for start, end in taken)


def parse_when(text: str, *, now: datetime) -> ParsedWhen | None:
    """The moment ``text`` names, relative to ``now`` (aware), else ``None``."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    source = text or ""
    spans: list[tuple[int, int]] = []
    date: datetime | None = None
    delta: timedelta | None = None
    clock: time | None = None
    has_time = False
    part_hour: int | None = None

    # 1. Relative spans: "in 20 minutes".
    for match in _RELATIVE.finditer(source):
        amount = _amount(match.group(1))
        unit = match.group(2).lower()
        if amount is None:
            continue
        if re.fullmatch(_MINUTES, unit, re.I):
            step = timedelta(minutes=amount if amount else 30)
        elif re.fullmatch(_HOURS, unit, re.I):
            step = timedelta(hours=amount) if amount else timedelta(minutes=30)
        elif re.fullmatch(_DAYS, unit, re.I):
            step = timedelta(days=amount or 1)
        else:
            step = timedelta(weeks=amount or 1)
        delta = (delta or timedelta()) + step
        spans.append(match.span())
    # 2. Explicit dates.
    for pattern in (_ISO_DATE, _DAY_MONTH, _MONTH_DAY, _NUMERIC_DATE):
        for match in pattern.finditer(source):
            if _overlaps(match.span(), spans):
                continue
            found = _date_of(pattern, match, now)
            if found is None:
                continue
            date = found
            if pattern is _ISO_DATE and match.group(4):
                clock = time(int(match.group(4)), int(match.group(5)))
                has_time = True
            spans.append(match.span())
            break
        if date is not None:
            break
    # 3. "next week", day words, weekdays.
    if date is None:
        match = _NEXT_WEEK.search(source)
        if match and not _overlaps(match.span(), spans):
            ahead = (7 - now.weekday()) % 7 or 7
            date = now + timedelta(days=ahead)
            spans.append(match.span())
    if date is None:
        for match in _DAY_WORD.finditer(source):
            if _overlaps(match.span(), spans):
                continue
            word = match.group(1).lower()
            date = now + timedelta(days=_DAY_WORDS[word])
            if word in _NIGHT_WORDS:
                part_hour = PARTS["night"]
            spans.append(match.span())
            break
    if date is None:
        for match in _WEEKDAY.finditer(source):
            if _overlaps(match.span(), spans):
                continue
            target = _WEEKDAYS[match.group(2).lower()]
            ahead = (target - now.weekday()) % 7
            if match.group(1) and ahead == 0:
                ahead = 7
            date = now + timedelta(days=ahead)
            spans.append(match.span())
            break
    # 4. Clock time and parts of the day.
    for match in _CLOCK.finditer(source):
        if _overlaps(match.span(), spans):
            continue
        parsed = _clock_of(match)
        if parsed is None:
            continue
        clock = parsed
        has_time = True
        spans.append(match.span())
        break
    if clock is None:
        for match in _PART.finditer(source):
            if _overlaps(match.span(), spans):
                continue
            part_hour = PARTS[_PART_WORDS[match.group(1).lower()]]
            spans.append(match.span())
            break
        for word, hour in _NOON_MIDNIGHT.items():
            match = re.search(_W + re.escape(word) + _E, source, re.I)
            if match and not _overlaps(match.span(), spans):
                clock = time(hour, 0)
                has_time = True
                spans.append(match.span())
                break

    if delta is None and date is None and clock is None and part_hour is None:
        return None

    # -- resolve
    if delta is not None and date is None:
        at = now + delta
        if clock is not None:
            at = at.replace(hour=clock.hour, minute=clock.minute, second=0, microsecond=0)
        elif part_hour is not None and delta >= timedelta(days=1):
            at = at.replace(hour=part_hour, minute=0, second=0, microsecond=0)
        else:
            at = at.replace(second=0, microsecond=0)
        return ParsedWhen(at=at, spans=tuple(sorted(spans)), has_time=has_time or clock is not None)

    hour, minute = DEFAULT_HOUR, 0
    if clock is not None:
        hour, minute = clock.hour, clock.minute
    elif part_hour is not None:
        hour = part_hour
    if date is None:
        # A time alone: today while it is still ahead, else tomorrow.
        at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if at <= now:
            at += timedelta(days=1)
        if delta is not None:
            at += delta
        return ParsedWhen(at=at, spans=tuple(sorted(spans)), has_time=has_time)
    # A named day is kept even when its time has passed ("today at 9" said at
    # 10): such a reminder is delivered at once instead of moving a day.
    at = date.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if delta is not None:
        at += delta
    return ParsedWhen(at=at, spans=tuple(sorted(spans)), has_time=has_time)


def _amount(token: str) -> int | None:
    token = token.lower()
    if token.isdigit():
        return int(token)
    return _NUM_WORDS.get(token)


def _clock_of(match: re.Match[str]) -> time | None:
    hour = int(match.group(1))
    minute_text = match.group(2) or match.group(3)
    meridiem = (match.group(4) or "").replace(".", "").lower()
    uhr = bool(match.group(5))
    whole = match.group(0).lower()
    explicit_at = bool(re.match(rf"{_AT}\s", whole, re.I))
    hour_mark = bool(re.search(r"\dh(?![\w])|\dh\d", whole))
    if not (minute_text is not None or meridiem or uhr or hour_mark or explicit_at):
        # A bare number ("buy 3 apples") is not a time.
        return None
    if meridiem == "pm" and hour < 12:
        hour += 12
    if meridiem == "am" and hour == 12:
        hour = 0
    if hour > 23:
        return None
    minute = int(minute_text) if minute_text is not None else 0
    if minute > 59:
        return None
    return time(hour, minute)


def _date_of(pattern: re.Pattern[str], match: re.Match[str], now: datetime) -> datetime | None:
    try:
        if pattern is _ISO_DATE:
            return now.replace(
                year=int(match.group(1)), month=int(match.group(2)), day=int(match.group(3))
            )
        if pattern is _DAY_MONTH:
            day, month = int(match.group(1)), _MONTHS[match.group(2).lower()]
        elif pattern is _MONTH_DAY:
            month, day = _MONTHS[match.group(1).lower()], int(match.group(2))
        else:
            day, month = int(match.group(1)), int(match.group(2))
            year_text = match.group(3)
            if year_text:
                year = int(year_text)
                year = year + 2000 if year < 100 else year
                return now.replace(year=year, month=month, day=day)
        candidate = now.replace(month=month, day=day)
        if candidate.date() < now.date():
            candidate = candidate.replace(year=now.year + 1)
        return candidate
    except ValueError:  # a day that does not exist (31.02.) is not a date
        return None


# ------------------------------------------------------------ the text left

_LEAD_INS = re.compile(
    r"^\s*(?:please\s+)?(?:remind me|reminder|remember|"
    r"erinnere mich|erinner mich|erinnerung|"  # i18n-allow
    r"recuérdame|recuerdame|recordarme|"  # i18n-allow
    r"lembra-me|lembre-me|me lembra|me lembre|lembrete)"  # i18n-allow
    r"\s*[:,]?\s*",
    re.I,
)
_CONNECTORS = re.compile(
    r"^\s*(?:to|about|that|of|at|on|please|"
    r"an|daran|dass|zu|bitte|wegen|über|um|am|"  # i18n-allow
    r"de|que|a|para|sobre|acerca de|do|da|das|dos|en|em|às|à|a las|a la)[,\s]+",  # i18n-allow
    re.I,
)
_TRAILERS = re.compile(
    r"\s+(?:at|on|in|the|and|please|"
    r"um|am|und|bitte|en|em|às|à|a las|a la|y|e|por favor)\s*$",  # i18n-allow
    re.I,
)


def strip_when(text: str, parsed: ParsedWhen) -> str:
    """The reminder text without the words that named the time."""
    pieces: list[str] = []
    cursor = 0
    for start, end in parsed.spans:
        pieces.append(text[cursor:start])
        cursor = end
    pieces.append(text[cursor:])
    rest = " ".join(" ".join(pieces).split())
    for _ in range(4):
        before = rest
        rest = _LEAD_INS.sub("", rest)
        rest = _CONNECTORS.sub("", rest)
        rest = _TRAILERS.sub("", rest)
        rest = rest.strip(" ,.;:!-")
        if rest == before:
            break
    return rest


def clean_text(text: str) -> str:
    """A reminder text without a lead-in ("remind me to call Anna" -> "call Anna")."""
    rest = " ".join((text or "").split())
    for _ in range(3):
        before = rest
        rest = _LEAD_INS.sub("", rest)
        rest = _CONNECTORS.sub("", rest)
        rest = rest.strip(" ,.;:!-")
        if rest == before:
            break
    return rest


__all__ = ["DEFAULT_HOUR", "PARTS", "ParsedWhen", "clean_text", "parse_when", "strip_when"]
