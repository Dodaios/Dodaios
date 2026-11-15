"""What a ritual is: its phrases, its steps, when it may start, and one day of it.

A step is a sentence in the person's own words. ``now`` steps happen the moment
the phrase is said; ``ahead`` steps are gathered before that moment (the news,
the open pull requests) and their result waits until it is asked for.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Final
from uuid import uuid4

#: The word a person reads for this feature in text Python writes (tool
#: descriptions, prompts). The interface has its own in the ``rituals`` block
#: of the locale files; nothing else spells it out.
NOUN: Final[str] = "ritual"

#: When a step happens: the moment the phrase is said, or ahead of it.
WHEN: Final[tuple[str, ...]] = ("now", "ahead")
ORIGINS: Final[tuple[str, ...]] = ("owner", "assistant")
#: How a ritual was started.
FIRED_VIA: Final[tuple[str, ...]] = ("voice", "chat", "button", "tool")
#: Where the gathering of today's ``ahead`` steps stands (``""`` = not begun).
PREP_STATES: Final[tuple[str, ...]] = ("", "running", "ready", "failed")

MAX_RITUALS: Final[int] = 20
MAX_NAME_CHARS: Final[int] = 60
MAX_PHRASES: Final[int] = 5
MAX_PHRASE_WORDS: Final[int] = 6
MAX_PHRASE_CHARS: Final[int] = 60
MAX_STEPS: Final[int] = 12
MAX_STEP_CHARS: Final[int] = 500
#: How many days of a ritual's per-day state are kept.
KEEP_DAYS: Final[int] = 30
#: Tag of the backing lead routine: ``TAG_PREFIX + ritual id``.
TAG_PREFIX: Final[str] = "lead-ritual:"

_CLOCK_RE: Final[re.Pattern[str]] = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


class RitualError(Exception):
    """A request the service refuses.

    ``code`` is one of ``not_found``, ``invalid``, ``conflict``, ``state``,
    ``limit`` and ``unavailable``; ``message`` is a sentence a person can read.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class RitualStep:
    id: str
    #: ``now`` or ``ahead``.
    when: str
    #: What should happen, in the person's own words.
    text: str
    #: For a ``now`` step that is exactly one tool call: that call (``tool``,
    #: ``args``, and ``says``, the call in plain words). It is made directly
    #: at the start, with no model (:mod:`dodaios.rituals.instant`). ``None``:
    #: the step is done by a turn.
    call: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        view: dict[str, Any] = {"id": self.id, "when": self.when, "text": self.text}
        if self.call is not None:
            view["call"] = dict(self.call)
        return view


@dataclass(frozen=True, slots=True)
class Ritual:
    id: str
    name: str
    #: What the person says to start it, as they wrote it.
    phrases: tuple[str, ...]
    enabled: bool
    #: ``HH:MM`` on the person's clock; both empty means any time of day.
    window_from: str
    window_to: str
    #: Monday is 0; empty means every day.
    weekdays: tuple[int, ...]
    #: The phrase starts it only the first time on a day.
    once_per_day: bool
    #: ``HH:MM`` from which the ``ahead`` steps are gathered; empty means from
    #: the start of the window (or of the day when there is no window).
    prepare_from: str
    steps: tuple[RitualStep, ...]
    #: The backing lead routine's task id, ``""`` while there is none.
    task_id: str
    origin: str
    created_ms: int
    updated_ms: int

    def steps_at(self, when: str) -> tuple[RitualStep, ...]:
        return tuple(step for step in self.steps if step.when == when)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "phrases": list(self.phrases),
            "enabled": self.enabled,
            "window_from": self.window_from,
            "window_to": self.window_to,
            "weekdays": list(self.weekdays),
            "once_per_day": self.once_per_day,
            "prepare_from": self.prepare_from,
            "steps": [step.to_dict() for step in self.steps],
            "task_id": self.task_id,
            "origin": self.origin,
            "created_ms": self.created_ms,
            "updated_ms": self.updated_ms,
        }


@dataclass(frozen=True, slots=True)
class RitualDay:
    """One local day of one ritual: what was gathered for it and whether it ran."""

    ritual_id: str
    #: ``YYYY-MM-DD`` on the person's clock.
    day: str
    prep_state: str
    prep_attempts: int
    prep_error: str
    #: The chat of the run that gathered (or is gathering) the ``ahead`` steps.
    prep_session: str
    prepared_ms: int | None
    #: Fingerprint of the ``ahead`` steps the result belongs to.
    steps_hash: str
    #: The result in a form made for the ear, and the full written one.
    spoken: str
    written: str
    fired_ms: int | None
    fired_via: str
    #: What each ``now`` step did, in short lines.
    results: tuple[str, ...]
    #: When the gathered result reached the person; ``None`` while it is owed.
    delivered_ms: int | None
    #: When its phrase started it on this day; ``None`` while the phrase is
    #: still free. A click or a start on request does not use the phrase up.
    phrase_ms: int | None = None

    def to_dict(self, *, with_text: bool = False) -> dict[str, Any]:
        view: dict[str, Any] = {
            "day": self.day,
            "prep_state": self.prep_state,
            "prep_error": self.prep_error,
            "prepared_ms": self.prepared_ms,
            "fired_ms": self.fired_ms,
            "fired_via": self.fired_via,
            "results": list(self.results),
            "delivered_ms": self.delivered_ms,
            "phrase_ms": self.phrase_ms,
        }
        if with_text:
            view["spoken"] = self.spoken
            view["written"] = self.written
        return view


def new_ritual_id() -> str:
    return "rit_" + uuid4().hex[:8]


def new_step_id() -> str:
    return "s_" + uuid4().hex[:6]


def now_ms() -> int:
    return int(time.time() * 1000)


def clock(value: Any) -> str:
    """``value`` as ``HH:MM``, ``""`` for none; raises ``ValueError`` for anything else."""
    text = str(value or "").strip()
    if not text:
        return ""
    if _CLOCK_RE.match(text) is None:
        raise ValueError(f"{text!r} is not a time of day (HH:MM)")
    return text


def minutes_of(value: str) -> int:
    """Minutes since midnight of an ``HH:MM`` that :func:`clock` accepted."""
    hours, minutes = value.split(":")
    return int(hours) * 60 + int(minutes)


__all__ = [
    "FIRED_VIA",
    "KEEP_DAYS",
    "MAX_NAME_CHARS",
    "MAX_PHRASES",
    "MAX_PHRASE_CHARS",
    "MAX_PHRASE_WORDS",
    "MAX_RITUALS",
    "MAX_STEPS",
    "MAX_STEP_CHARS",
    "NOUN",
    "ORIGINS",
    "PREP_STATES",
    "TAG_PREFIX",
    "WHEN",
    "Ritual",
    "RitualDay",
    "RitualError",
    "RitualStep",
    "clock",
    "minutes_of",
    "new_ritual_id",
    "new_step_id",
    "now_ms",
]
