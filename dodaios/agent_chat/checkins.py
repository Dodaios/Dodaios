"""Check-ins: "check on me in 25 minutes, I'm writing the report".

A focus companion. The person names a span and, if they like, what they
are doing; :func:`parse_checkin` reads that from their words (English and
German), :func:`schedule_checkin` turns it into one one-shot lead routine
(``after_delay``) whose only job is a short, warm check-in posted into the
conversation when the time is up. It is a lead routine like the brief, so
it runs unattended on the subscription or local seat and never bills a key;
it is quiet (:data:`~proactive_checks.QUIET_TAG`), so no start card appears,
only the check-in itself.

The post-turn hook (``surface_kits``) calls :func:`note_user_text` with the
person's words. When the lead already scheduled something during that
turn, nothing is added: one check-in per request.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Final

log = logging.getLogger(__name__)

CHECKIN_TAG: Final[str] = "lead-checkin"
CHECKIN_TITLE: Final[str] = "Check-in"
MIN_MINUTES: Final[int] = 1
MAX_MINUTES: Final[int] = 12 * 60
_MAX_DOING_CHARS: Final[int] = 160

_NUMBER_WORDS: Final[dict[str, int]] = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "ten": 10,
    "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "an": 1, "a": 1, "half an": 0,
}

_REQUESTS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(
        r"\bcheck (?:back )?(?:in )?(?:on|with) me (?:again )?in\s+(?P<n>\d{1,3}|[a-z]+(?: an)?)"
        r"\s*(?P<unit>minutes?|mins?|min|hours?|hrs?|h)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:melde dich|frag(?:e)?(?: nach)?|hak(?:e)?(?: nach)?|check(?:e)? mich) "  # i18n-allow
        r"in\s+(?P<n>\d{1,3}|einer|einer halben|zwei|drei|fünf|zehn|zwanzig|dreißig)"  # i18n-allow
        r"\s*(?P<unit>minuten?|min|stunden?|std|h)\b",  # i18n-allow
        re.IGNORECASE,
    ),
)
_GERMAN_NUMBERS: Final[dict[str, int]] = {
    "einer": 1, "einer halben": 0, "zwei": 2, "drei": 3, "fünf": 5, "zehn": 10,  # i18n-allow
    "zwanzig": 20, "dreißig": 30,  # i18n-allow
}

#: What the person says they are doing, after the request or before it.
_DOING: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(
        r"\bI(?:'m| am)\s+(?:going to be\s+|about to\s+)?(?P<doing>(?:working on|doing|writing|"
        r"reading|studying|cleaning|coding|preparing|practising|practicing|reviewing|"
        r"finishing|on)\b[^.!?\n]{0,160})",
        re.IGNORECASE,
    ),
    re.compile(r"\bwhile I\s+(?P<doing>[^.!?\n]{3,160})", re.IGNORECASE),
    re.compile(
        r"\bich\s+(?P<doing>(?:arbeite|schreibe|lese|lerne|mache)\b[^.!?\n]{0,160})",  # i18n-allow
        re.IGNORECASE,
    ),
)


@dataclass(frozen=True)
class CheckinRequest:
    minutes: int
    doing: str


def _minutes(number: str, unit: str) -> int | None:
    key = number.strip().lower()
    if key.isdigit():
        count = int(key)
    elif key in _NUMBER_WORDS:
        count = _NUMBER_WORDS[key]
    elif key in _GERMAN_NUMBERS:
        count = _GERMAN_NUMBERS[key]
    else:
        return None
    hours = unit.lower().startswith(("h", "std", "stunde"))  # i18n-allow
    if count == 0:  # "half an hour"
        return 30 if hours else None
    minutes = count * 60 if hours else count
    return minutes if MIN_MINUTES <= minutes <= MAX_MINUTES else None


def parse_checkin(text: str) -> CheckinRequest | None:
    """The check-in a message asks for, or ``None`` when it asks for none."""
    text = " ".join((text or "").split())
    for pattern in _REQUESTS:
        match = pattern.search(text)
        if match is None:
            continue
        minutes = _minutes(match.group("n"), match.group("unit"))
        if minutes is None:
            return None
        doing = ""
        for hint in _DOING:
            found = hint.search(text)
            if found:
                doing = found.group("doing").strip(" ,;:-")[:_MAX_DOING_CHARS]
                break
        return CheckinRequest(minutes=minutes, doing=doing)
    return None


def checkin_prompt(request: CheckinRequest) -> str:
    span = (
        f"{request.minutes} minutes" if request.minutes < 120 else f"{request.minutes // 60} hours"
    )
    doing = f' They said they were "{request.doing}".' if request.doing else ""
    return (
        f"The user asked you to check in on them after {span}; that time is up.{doing} "
        "Write one or two short, warm sentences: ask how it went and whether they want "
        "to carry on or take a break. No headings, no lists, no new tasks, no tools. "
        "Do not schedule anything."
    )


def _runtime() -> Any | None:
    from dodaios.society.runtime import current_runtime

    return current_runtime()


async def schedule_checkin(request: CheckinRequest) -> dict[str, Any]:
    """One one-shot lead routine that posts the check-in when the time is up.

    Returns ``{"task_id", "minutes", "doing"}``. Raises ``ValueError`` on a
    span outside :data:`MIN_MINUTES`..:data:`MAX_MINUTES` and
    ``RuntimeError`` when the society or its scheduler is not running.
    """
    from dodaios.agent_chat.proactive_checks import QUIET_TAG
    from dodaios.society.roster import LEAD_AGENT_ID
    from dodaios.society.routines import build_task_spec, create_routine

    if not MIN_MINUTES <= request.minutes <= MAX_MINUTES:
        raise ValueError(f"minutes must be between {MIN_MINUTES} and {MAX_MINUTES}")
    runtime = _runtime()
    if runtime is None:
        raise RuntimeError("The agent society is not running")
    task_store, scheduler = runtime.task_services()
    if task_store is None or scheduler is None:
        raise RuntimeError("The task scheduler is unavailable")
    lead = await runtime.roster.get(LEAD_AGENT_ID)
    if lead is None:
        raise RuntimeError("The assistant's agent record is missing")
    spec = build_task_spec(
        lead,
        title=CHECKIN_TITLE,
        prompt=checkin_prompt(request),
        schedule={"kind": "after_delay", "delay_seconds": request.minutes * 60},
    )
    spec = spec.model_copy(update={"tags": (*spec.tags, CHECKIN_TAG, QUIET_TAG)})
    task_id = await create_routine(task_store, scheduler, spec)
    log.info("lead check-in: in %s min", request.minutes)
    return {"task_id": task_id, "minutes": request.minutes, "doing": request.doing}


def _scheduled_already(tool_names: tuple[str, ...]) -> bool:
    """Whether the lead's own turn already created a routine or reminder."""
    return any(
        key in name.lower() for name in tool_names for key in ("routine", "schedule", "remind")
    )


async def note_user_text(text: str, *, tool_names: tuple[str, ...] = ()) -> dict[str, Any] | None:
    """Schedule the check-in a message asks for, unless the turn already did."""
    request = parse_checkin(text)
    if request is None or _scheduled_already(tool_names):
        return None
    try:
        return await schedule_checkin(request)
    except (ValueError, RuntimeError):
        log.info("lead check-in: not scheduled", exc_info=True)
        return None


__all__ = [
    "CHECKIN_TAG",
    "CHECKIN_TITLE",
    "MAX_MINUTES",
    "MIN_MINUTES",
    "CheckinRequest",
    "checkin_prompt",
    "note_user_text",
    "parse_checkin",
    "schedule_checkin",
]
