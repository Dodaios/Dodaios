"""How much the lead comes to the person on its own, and about what.

One setting with three levels (``off`` / ``important`` / ``everything``),
four topic switches (mail, calendar, agents, deadlines) and the rhythm of the
"needs you" checks (every 1, 3 or 6 hours inside waking hours). The brief
and the checks (``proactive.py``, ``proactive_checks.py``) read it when they
word their prompts, so what the person turned off never shows up.

Stored as one JSON row in the society store's meta table; off by default.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, replace
from typing import Any, Final

log = logging.getLogger(__name__)

LEVELS: Final[tuple[str, ...]] = ("off", "important", "everything")
TOPICS: Final[tuple[str, ...]] = ("mail", "calendar", "agents", "deadlines")
INTERVALS: Final[tuple[int, ...]] = (1, 3, 6)
DEFAULT_INTERVAL_HOURS: Final[int] = 3
#: Checks run inside these local hours only (first and last hour inclusive).
DEFAULT_FROM_HOUR: Final[int] = 8
DEFAULT_TO_HOUR: Final[int] = 22
META_KEY: Final[str] = "lead_proactive"

#: What each topic means for the model, in one line.
TOPIC_LINES: Final[dict[str, str]] = {
    "mail": "messages that wait for the user's reply or need a decision",
    "calendar": "today's and tomorrow's appointments, especially changes and clashes",
    "agents": "work the user's agents finished, got stuck on or need the user for",
    "deadlines": "deadlines, plans and promises due today or overdue, from memory",
}


@dataclass(frozen=True)
class ProactiveSettings:
    level: str = "off"
    topics: tuple[str, ...] = TOPICS
    interval_hours: int = DEFAULT_INTERVAL_HOURS
    from_hour: int = DEFAULT_FROM_HOUR
    to_hour: int = DEFAULT_TO_HOUR
    #: The person's IANA zone as the page last reported it.
    timezone: str = ""

    @property
    def enabled(self) -> bool:
        return self.level != "off"

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "topics": list(self.topics),
            "interval_hours": self.interval_hours,
            "from_hour": self.from_hour,
            "to_hour": self.to_hour,
            "timezone": self.timezone,
        }

    @classmethod
    def from_dict(cls, data: Any) -> ProactiveSettings:
        """A settings object from any stored or posted shape; unknown values fall back."""
        if not isinstance(data, dict):
            return cls()
        level = str(data.get("level") or "off").strip().lower()
        if level not in LEVELS:
            level = "off"
        raw_topics = data.get("topics")
        if isinstance(raw_topics, list | tuple):
            topics = tuple(t for t in TOPICS if t in {str(x).strip().lower() for x in raw_topics})
        else:
            topics = TOPICS
        interval = _int(data.get("interval_hours"), DEFAULT_INTERVAL_HOURS)
        if interval not in INTERVALS:
            interval = DEFAULT_INTERVAL_HOURS
        from_hour = min(23, max(0, _int(data.get("from_hour"), DEFAULT_FROM_HOUR)))
        to_hour = min(23, max(0, _int(data.get("to_hour"), DEFAULT_TO_HOUR)))
        if to_hour < from_hour:
            from_hour, to_hour = DEFAULT_FROM_HOUR, DEFAULT_TO_HOUR
        return cls(
            level=level,
            topics=topics,
            interval_hours=interval,
            from_hour=from_hour,
            to_hour=to_hour,
            timezone=str(data.get("timezone") or "").strip(),
        )

    def with_timezone(self, timezone: str) -> ProactiveSettings:
        return replace(self, timezone=timezone) if timezone else self


def _int(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):  # a non-number keeps the default; nothing to report
        return fallback


def topic_sentences(settings: ProactiveSettings) -> list[str]:
    """The topic lines the person left on, in catalogue order."""
    return [TOPIC_LINES[t] for t in TOPICS if t in settings.topics]


def level_sentence(settings: ProactiveSettings) -> str:
    """What "worth saying" means at this level."""
    if settings.level == "everything":
        return (
            "Mention everything new or changed in these areas since the last check, "
            "briefly, even small items."
        )
    return (
        "Mention only what the user must act on soon or would regret missing: a "
        "reply someone waits for, a meeting about to start or moved, an agent "
        "that is blocked on them, a deadline today. Routine mail, newsletters "
        "and things that can wait a day are not worth an interruption."
    )


def _store() -> Any | None:
    from dodaios.society.runtime import current_runtime

    runtime = current_runtime()
    return getattr(runtime, "store", None) if runtime is not None else None


async def load_settings(store: Any | None = None) -> ProactiveSettings:
    """The saved settings, or the defaults when nothing was saved or no store runs."""
    store = store if store is not None else _store()
    if store is None:
        return ProactiveSettings()
    try:
        raw = await store.get_meta(META_KEY, "")
    except Exception:  # noqa: BLE001 — an unreadable row reads as the defaults
        log.warning("lead proactive: settings unreadable", exc_info=True)
        return ProactiveSettings()
    if not raw:
        return ProactiveSettings()
    try:
        return ProactiveSettings.from_dict(json.loads(raw))
    except ValueError:
        log.warning("lead proactive: stored settings are not JSON; using defaults")
        return ProactiveSettings()


async def save_settings(settings: ProactiveSettings, store: Any | None = None) -> None:
    """Persist ``settings``; raises ``RuntimeError`` without a society store."""
    store = store if store is not None else _store()
    if store is None:
        raise RuntimeError("The agent society is not running")
    await store.set_meta(META_KEY, json.dumps(settings.to_dict(), ensure_ascii=False))


__all__ = [
    "DEFAULT_INTERVAL_HOURS",
    "INTERVALS",
    "LEVELS",
    "META_KEY",
    "TOPICS",
    "TOPIC_LINES",
    "ProactiveSettings",
    "level_sentence",
    "load_settings",
    "save_settings",
    "topic_sentences",
]
