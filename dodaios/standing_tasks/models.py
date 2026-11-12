"""What a standing task is: the task, one run of it, and the limits both obey.

A standing task is an open-ended responsibility the assistant looks after over
time (a campaign, an inbox, a launch). Unlike a routine it carries working
notes from run to run, a pace the assistant adjusts inside bounds, an autonomy
level with limits the owner wrote, and a run log the owner can read.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Final
from uuid import uuid4

#: How much the assistant may do on its own in a run.
#:
#: ``watch``    read only: it looks and tells the owner what changed.
#: ``prepare``  it also gets the next step ready (a draft, a plan); nothing
#:              outside Dodaios changes.
#: ``act``      it may make changes that stay inside the owner's ``limits``.
AUTONOMY: Final[tuple[str, ...]] = ("watch", "prepare", "act")
STATES: Final[tuple[str, ...]] = ("proposed", "active", "paused", "ended")
#: How a run ended. ``failed`` and ``skipped`` are written by the app, never by the model.
OUTCOMES: Final[tuple[str, ...]] = (
    "quiet", "reported", "prepared", "acted", "asked", "failed", "skipped",
)
ORIGINS: Final[tuple[str, ...]] = ("owner", "suggested")

MIN_INTERVAL_MIN: Final[int] = 15
MAX_INTERVAL_MIN: Final[int] = 7 * 24 * 60
DEFAULT_INTERVAL_MIN: Final[int] = 180
#: Proposed, active and paused tasks together.
MAX_OPEN: Final[int] = 12
MAX_NOTES_CHARS: Final[int] = 4000
MAX_TITLE_CHARS: Final[int] = 120
MAX_GOAL_CHARS: Final[int] = 2000
#: Tag of the backing lead routine: ``TAG_PREFIX + task id``.
TAG_PREFIX: Final[str] = "lead-standing:"

OPEN_STATES: Final[frozenset[str]] = frozenset({"proposed", "active", "paused"})

_NOT_WORD = re.compile(r"[^\w]+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class StandingTask:
    id: str
    title: str
    goal: str
    how: str
    autonomy: str
    limits: str
    state: str
    interval_min: int
    origin: str
    reason: str
    notes: str
    #: The backing lead routine's task id, ``""`` while there is none.
    task_id: str
    created_ms: int
    updated_ms: int
    last_run_ms: int | None
    next_run_ms: int | None
    last_outcome: str
    last_summary: str
    runs: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "goal": self.goal,
            "how": self.how,
            "autonomy": self.autonomy,
            "limits": self.limits,
            "state": self.state,
            "interval_min": self.interval_min,
            "origin": self.origin,
            "reason": self.reason,
            "notes": self.notes,
            "task_id": self.task_id,
            "created_ms": self.created_ms,
            "updated_ms": self.updated_ms,
            "last_run_ms": self.last_run_ms,
            "next_run_ms": self.next_run_ms,
            "last_outcome": self.last_outcome,
            "last_summary": self.last_summary,
            "runs": self.runs,
        }


@dataclass(frozen=True, slots=True)
class StandingRun:
    id: str
    standing_id: str
    at_ms: int
    outcome: str
    summary: str
    #: What the run changed, in the assistant's own short words.
    actions: tuple[str, ...]
    #: The pace in force after this run.
    next_interval_min: int
    #: The run's own chat, ``""`` when the run started no chat.
    session_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "standing_id": self.standing_id,
            "at_ms": self.at_ms,
            "outcome": self.outcome,
            "summary": self.summary,
            "actions": list(self.actions),
            "next_interval_min": self.next_interval_min,
            "session_id": self.session_id,
        }


class StandingError(Exception):
    """A request the service refuses.

    ``code`` is one of ``not_found``, ``invalid``, ``state``, ``limit`` and
    ``unavailable``; ``message`` is a sentence a person can read.
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def new_task_id() -> str:
    return "st_" + uuid4().hex[:8]


def new_run_id() -> str:
    return "sr_" + uuid4().hex[:12]


def now_ms() -> int:
    return int(time.time() * 1000)


def clamp_interval(value: Any) -> int:
    """``value`` as whole minutes inside the bounds; the default when it is no number."""
    try:
        minutes = int(float(value))
    except (TypeError, ValueError):  # not a number: fall back to the default pace
        return DEFAULT_INTERVAL_MIN
    return max(MIN_INTERVAL_MIN, min(MAX_INTERVAL_MIN, minutes))


def normalise_title(title: str) -> str:
    """The title as compared for duplicates: case, spacing and punctuation ignored."""
    return _NOT_WORD.sub(" ", str(title or "").casefold()).strip()


__all__ = [
    "AUTONOMY",
    "DEFAULT_INTERVAL_MIN",
    "MAX_GOAL_CHARS",
    "MAX_INTERVAL_MIN",
    "MAX_NOTES_CHARS",
    "MAX_OPEN",
    "MAX_TITLE_CHARS",
    "MIN_INTERVAL_MIN",
    "OPEN_STATES",
    "ORIGINS",
    "OUTCOMES",
    "STATES",
    "TAG_PREFIX",
    "StandingError",
    "StandingRun",
    "StandingTask",
    "clamp_interval",
    "new_run_id",
    "new_task_id",
    "normalise_title",
    "now_ms",
]
