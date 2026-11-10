"""The lead's morning brief: one scheduled routine that reports into the conversation.

The brief is an ordinary lead routine (``society/routines.py``) marked with
:data:`BRIEF_TAG`. Its result lands in the lead's one conversation like every
lead routine result (``agent_chat/lead.py``), as a written card, never spoken.
Like every unattended run it never bills a provider key: the routine runner
holds a run whose seat would (``routine_runner._hold_unattended_run_off_keys``).

Off until the person turns it on.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Final

log = logging.getLogger(__name__)

BRIEF_TAG: Final[str] = "lead-brief:morning"
BRIEF_TITLE: Final[str] = "Morning brief"
DEFAULT_TIME: Final[str] = "08:00"

BRIEF_PROMPT: Final[str] = (
    "Write the user's morning brief for today. Cover, most important first and "
    "only what applies: today's calendar (time, title, place); messages that wait "
    "for the user's reply; work you or the user's agents finished since the last "
    "brief and work that waits on the user; open decisions; anything due today "
    "that you know from memory. Keep it short and grouped under plain headings. "
    "Read only: do not send, change, book or delete anything."
)

#: The brief's sections per proactivity topic (``proactive_settings.TOPICS``).
_BRIEF_SECTIONS: Final[dict[str, str]] = {
    "calendar": "today's calendar (time, title, place)",
    "mail": "messages that wait for the user's reply",
    "agents": (
        "work you or the user's agents finished since the last brief and work "
        "that waits on the user; open decisions"
    ),
    "deadlines": "anything due today that you know from memory",
}

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def brief_prompt(settings: Any | None = None) -> str:
    """The brief's prompt, covering only the topics the person left on.

    Without settings, or with every topic on, this is :data:`BRIEF_PROMPT`.
    With every topic off the brief still runs: it then covers the calendar
    alone, so a brief the person turned on never comes back empty.
    """
    from dodaios.agent_chat.proactive_settings import TOPICS

    topics = tuple(settings.topics) if settings is not None else TOPICS
    if set(topics) >= set(TOPICS):
        return BRIEF_PROMPT
    sections = [_BRIEF_SECTIONS[t] for t in TOPICS if t in topics] or [
        _BRIEF_SECTIONS["calendar"]
    ]
    return (
        "Write the user's morning brief for today. Cover, most important first and "
        "only what applies: " + "; ".join(sections) + ". Keep it short and grouped "
        "under plain headings. Read only: do not send, change, book or delete anything."
    )


def _runtime() -> Any | None:
    from dodaios.society.runtime import current_runtime

    return current_runtime()


async def _brief_row(task_store: Any) -> dict[str, Any] | None:
    from dodaios.society.roster import LEAD_AGENT_ID
    from dodaios.society.routines import _tags_of, is_agent_routine

    terminal = {"completed", "cancelled", "failed", "interrupted"}
    for row in await task_store.list(limit=1000):
        if (
            is_agent_routine(row, LEAD_AGENT_ID)
            and BRIEF_TAG in _tags_of(row)
            and row.get("state") not in terminal
        ):
            return row
    return None


def _schedule_of(spec: Any) -> tuple[str, str]:
    trigger = getattr(spec, "trigger", None)
    local_time = str(getattr(trigger, "local_time", "") or DEFAULT_TIME)
    timezone = str(getattr(trigger, "timezone", "") or "")
    return local_time, timezone


async def brief_state() -> dict[str, Any]:
    """``{"available", "enabled", "time", "timezone", "task_id"}`` for the settings UI."""
    runtime = _runtime()
    task_store = runtime.task_services()[0] if runtime is not None else None
    if task_store is None:
        return {"available": False, "enabled": False, "time": DEFAULT_TIME, "timezone": ""}
    row = await _brief_row(task_store)
    if row is None:
        return {"available": True, "enabled": False, "time": DEFAULT_TIME, "timezone": ""}
    spec = await task_store.get_spec(str(row["id"]))
    local_time, timezone = _schedule_of(spec)
    return {
        "available": True,
        "enabled": row.get("state") != "paused",
        "time": local_time,
        "timezone": timezone,
        "task_id": str(row["id"]),
    }


async def set_brief(*, enabled: bool, local_time: str, timezone: str) -> dict[str, Any]:
    """Turn the brief on (at ``local_time`` in ``timezone``) or off.

    On: creates the routine or moves the existing one. Off: deletes it.
    Raises ``ValueError`` on a bad time or zone, ``RuntimeError`` when the
    society runtime or its scheduler is not running.
    """
    from zoneinfo import ZoneInfo

    from dodaios.society.roster import LEAD_AGENT_ID
    from dodaios.society.routines import build_task_spec, create_routine, manage_routine

    runtime = _runtime()
    if runtime is None:
        raise RuntimeError("The agent society is not running")
    task_store, scheduler = runtime.task_services()
    if task_store is None or scheduler is None:
        raise RuntimeError("The task scheduler is unavailable")
    lead = await runtime.roster.get(LEAD_AGENT_ID)
    if lead is None:
        raise RuntimeError("The assistant's agent record is missing")
    existing = await _brief_row(task_store)
    if existing is not None:
        await manage_routine(
            lead, {"task_id": str(existing["id"]), "operation": "delete"}, task_store, scheduler
        )
    if not enabled:
        return await brief_state()
    local_time = (local_time or DEFAULT_TIME).strip()
    if not _TIME_RE.match(local_time):
        raise ValueError("time must be HH:MM")
    timezone = (timezone or "").strip()
    try:
        ZoneInfo(timezone)
    except Exception as exc:  # noqa: BLE001 — any lookup failure is a bad zone
        raise ValueError("timezone must be an IANA zone such as Europe/Berlin") from exc
    from dodaios.agent_chat.proactive_checks import ADAPTIVE_TAG
    from dodaios.agent_chat.proactive_settings import load_settings

    settings = await load_settings(getattr(runtime, "store", None))
    spec = build_task_spec(
        lead,
        title=BRIEF_TITLE,
        prompt=brief_prompt(settings),
        schedule={"kind": "calendar", "local_time": local_time, "timezone": timezone},
    )
    # Adaptive: the next brief sees the previous one and does not repeat it.
    spec = spec.model_copy(update={"tags": (*spec.tags, BRIEF_TAG, ADAPTIVE_TAG)})
    await create_routine(task_store, scheduler, spec)
    log.info("lead brief: scheduled daily at %s %s", local_time, timezone)
    return await brief_state()


__all__ = ["BRIEF_PROMPT", "BRIEF_TAG", "brief_prompt", "brief_state", "set_brief"]
