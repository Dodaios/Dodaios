"""Upcoming calendar appointments as short-lived memories (ADR-0044).

Once an hour, when Google Calendar is connected, the next two weeks of events
become ``ephemeral`` memories ("Appointment: Dentist on 2026-11-12
09:00–10:00") with a due date and an end date. They answer "when is my
dentist?" through the normal recall, feed the coming-up grounding, and come
due as reminders on the rail beside the conversation; after the event they
drop out of every read on their own. A moved or renamed event supersedes its
memory; a cancelled one is ended. No model call is made, nothing is written
back to the calendar, and the user's mail is deliberately not read.

Times. The vault compares its times as text against its UTC clock, so the due
and end times are stored in UTC, as reminders store theirs. Stored with the
event's own offset (until 2026-11-14), a 10:15 +01:00 appointment came due at
10:15 UTC, an hour late, and stayed an hour after it ended. The sentence names
the time on the person's clock: the zone their UI reported, else this
computer's.

What the rail shows beside the sentence is kept in ``source``: the event's
own title, its calendar, its link, start and end, and whether the entry only
says "busy". Such an entry has no title of its own (a calendar shared as
"see only free/busy", or a published availability feed that names every entry
"Busy"), so its sentence says that instead of presenting "Busy" as a name.

One appointment, one memory: the same event on two calendars (an invitation
seen on a shared calendar too, two feeds of the same availability) has the
same title, start and end, and becomes one memory and one reminder.

Ticked off stays ticked off: an appointment the person marked done (or
snoozed) while it still runs is not brought back by the next sync. A moved
event is a new appointment and is told again.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from typing import Any

from dodaios.memory.vault.store import MemoryVault

log = logging.getLogger(__name__)

META_KEY = "calendar_sync"
HORIZON_DAYS = 14
MAX_EVENTS = 50
#: The service these appointments come from; the rail shows its logo.
PROVIDER = "google_calendar"
#: The calendar API's access role of a calendar shared as free/busy only.
FREE_BUSY_ACCESS = "freeBusyReader"
#: The title a published availability feed gives every entry ("Busy" in the
#: feeds of the common calendar services, in the account's language).
BUSY_TITLES = frozenset(
    {"busy", "besetzt", "beschäftigt", "gebucht"}  # i18n-allow: feed titles, matched not shown
    | {"occupé", "occupée", "ocupado", "ocupada", "occupato", "bezet", "忙碌"}
)
#: How an appointment the person ended themselves was ended (``reminders.mark_done``, ``snooze``).
ENDED_BY_PERSON = frozenset({"done", "snoozed"})
_NO_TITLE = "(no title)"
_TWIN = "the same appointment on another calendar"


def _moment(value: str, zone: tzinfo | None) -> tuple[datetime | None, bool]:
    """``(moment, whole_day)`` of an event time: a date-time, or a date for a whole day."""
    value = (value or "").strip()
    if not value:
        return None, False
    if "T" not in value:
        try:
            day = date.fromisoformat(value[:10])
        except ValueError:  # an unreadable date: the event is skipped
            return None, True
        # A whole day starts at midnight on the person's clock.
        return datetime.combine(day, time(), tzinfo=zone or UTC), True
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:  # an unreadable time: the event is skipped
        return None, False
    return (moment if moment.tzinfo is not None else moment.replace(tzinfo=zone or UTC)), False


def _utc(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds")


def _same_moment(stored: str | None, utc: str) -> bool:
    """Whether a stored time (any offset, also an older memory's) is the moment ``utc``."""
    moment, _ = _moment(stored or "", None)
    return moment is not None and _utc(moment) == utc


def _title(event: dict[str, Any]) -> str:
    """The event's own title; "" when it has none."""
    title = " ".join(str(event.get("summary") or "").split())[:160]
    return "" if title == _NO_TITLE else title


def busy_only(event: dict[str, Any]) -> bool:
    """Whether the entry only says "busy": when, but never what."""
    if str(event.get("calendar_access") or "") == FREE_BUSY_ACCESS:
        return True
    return _title(event).casefold() in BUSY_TITLES and not str(event.get("location") or "").strip()


def _calendar_name(event: dict[str, Any]) -> str:
    """The calendar's name, when it tells the person something (not the primary one)."""
    name = " ".join(str(event.get("calendar") or "").split())[:80]
    if event.get("calendar_primary") or name in ("primary", str(event.get("calendar_id") or "")):
        return ""
    return name


def _span(start: datetime, end: datetime, whole_day: bool, zone: tzinfo | None) -> str:
    """'on 2026-11-12 09:00–10:00', 'on 2026-11-20', 'from 2026-11-20 to 2026-11-22'."""
    if whole_day:
        first = start.date()
        # The calendar's end date of a whole-day event is the day after it.
        last = (end - timedelta(days=1)).date() if end > start else first
        return f"on {first}" if last <= first else f"from {first} to {last}"
    begin = start.astimezone(zone) if zone is not None else start
    text = f"on {begin:%Y-%m-%d %H:%M}"
    if end > start:
        finish = end.astimezone(zone) if zone is not None else end
        same_day = finish.date() == begin.date()
        text += f"–{finish:%H:%M}" if same_day else f"–{finish:%Y-%m-%d %H:%M}"
    return text


def event_text(event: dict[str, Any], zone: tzinfo | None = None) -> str:
    """The memory's sentence: what, when on the person's clock, and where."""
    start, whole_day = _moment(str(event.get("start") or ""), zone)
    end, _ = _moment(str(event.get("end") or ""), zone)
    if start is None:
        return f"Appointment: {_title(event) or _NO_TITLE}."
    when = _span(start, end if end is not None and end > start else start, whole_day, zone)
    if busy_only(event):
        calendar = _calendar_name(event)
        what = "busy, no details shared"
        if calendar:
            what += f' (calendar "{calendar}")'
        return f"Appointment: {what} {when}."
    location = " ".join(str(event.get("location") or "").split())[:80]
    text = f"Appointment: {_title(event) or _NO_TITLE} {when}"
    return f"{text} ({location})." if location else f"{text}."


def _source(
    event: dict[str, Any], event_id: str, start: datetime, end: datetime, whole_day: bool
) -> dict[str, Any]:
    """What the rail shows of the appointment besides the sentence."""
    return {
        "via": "calendar",
        "provider": PROVIDER,
        "event_id": event_id,
        "title": "" if busy_only(event) else _title(event),
        "busy_only": busy_only(event),
        "calendar": _calendar_name(event),
        "all_day": whole_day,
        # A whole day keeps its dates; a time is stored in UTC like the due time.
        "start": start.date().isoformat() if whole_day else _utc(start),
        "end": end.date().isoformat() if whole_day else _utc(end),
        "location": " ".join(str(event.get("location") or "").split())[:80],
        "url": str(event.get("url") or ""),
    }


def _key(event: dict[str, Any], due_at: str, valid_to: str) -> tuple[str, str, str]:
    """What makes two events the same appointment: the title, the start and the end."""
    what = "\x00busy" if busy_only(event) else _title(event).casefold()
    return what, due_at, valid_to


def _ended_by_person(vault: MemoryVault, memory: Any, due_at: str) -> bool:
    """Whether the person ended this appointment's reminder (and the event did not move)."""
    if memory.expired_at is not None or not _same_moment(memory.due_at, due_at):
        return False
    return vault.end_reason(memory.id) in ENDED_BY_PERSON


def apply_events(
    vault: MemoryVault, events: list[dict[str, Any]], *, zone: tzinfo | None = None
) -> dict[str, int]:
    """Bring the vault's appointment memories in line with ``events``.

    ``zone`` is the person's clock for the sentence; without one it keeps the
    event's own clock.
    """
    raw = vault.get_meta(META_KEY)
    try:
        known: dict[str, str] = dict(json.loads(raw)) if raw else {}
    except ValueError:  # an unreadable map starts afresh; duplicates are caught by content
        known = {}
    counts = {"added": 0, "updated": 0, "ended": 0}
    seen: set[str] = set()
    # Each appointment of this round to the memory that holds it.
    held: dict[tuple[str, str, str], str] = {}
    now = vault.now()
    for event in events[:MAX_EVENTS]:
        event_id = str(event.get("id") or "")
        start, whole_day = _moment(str(event.get("start") or ""), zone)
        if not event_id or start is None or event.get("status") == "cancelled":
            continue
        end, _ = _moment(str(event.get("end") or ""), zone)
        end = end if end is not None and end > start else start
        seen.add(event_id)
        due_at, valid_to = _utc(start), _utc(end)
        key = _key(event, due_at, valid_to)
        twin = held.get(key)
        if twin is not None:
            # The same appointment on another calendar: one memory, one reminder.
            mine = known.get(event_id)
            if mine and mine != twin and vault.invalidate(mine, reason=_TWIN):
                counts["ended"] += 1
            known[event_id] = twin
            continue
        text = event_text(event, zone)
        source = _source(event, event_id, start, end, whole_day)
        current = vault.get(known[event_id]) if event_id in known else None
        if current is not None and current.is_current(now):
            if current.text == text and current.due_at == due_at and current.valid_to == valid_to:
                held[key] = current.id
                continue
            result = vault.supersede(
                current.id,
                text,
                origin="imported",
                source=source,
                valid_to=valid_to,
                due_at=due_at,
            )
            counts["updated"] += result.action == "superseded"
        elif current is not None and _ended_by_person(vault, current, due_at):
            held[key] = current.id
            continue
        else:
            result = vault.remember(
                text,
                "ephemeral",
                origin="imported",
                source=source,
                confidence=1.0,
                valid_to=valid_to,
                due_at=due_at,
            )
            counts["added"] += result.action == "added"
        if result.memory is not None:
            known[event_id] = result.memory.id
            held[key] = result.memory.id
    still_held = {known[event_id] for event_id in seen if event_id in known}
    for event_id, memory_id in list(known.items()):
        if event_id in seen:
            continue
        known.pop(event_id, None)
        if memory_id in still_held:
            # Gone from one calendar, still on another.
            continue
        memory = vault.get(memory_id)
        if memory is not None and memory.is_current(now):
            # Gone from the next two weeks before it happened: moved far away or cancelled.
            moment, _ = _moment(memory.due_at or "", None)
            if moment is not None and _utc(moment) > now and vault.invalidate(
                memory_id, reason="no longer on the calendar"
            ):
                counts["ended"] += 1
    vault.set_meta(META_KEY, json.dumps(known))
    return counts


def _person_zone() -> tzinfo | None:
    """The person's clock: the zone their UI reported, else this computer's. Blocking."""
    try:
        from zoneinfo import ZoneInfo

        from dodaios.self_build.clock import person_zone_name

        name = person_zone_name()
        return ZoneInfo(name) if name else None
    except Exception:  # noqa: BLE001 — without a zone the sentence keeps the event's own clock
        log.debug("memory calendar sync: no zone for the person's clock", exc_info=True)
        return None


async def sync(
    vault: MemoryVault, fetch: Any = None, *, zone: tzinfo | None = None
) -> dict[str, int] | None:
    """Fetch the next two weeks and apply them; None when the calendar is not connected."""
    if fetch is None:
        from dodaios.plugins.tool.google_calendar_rest import GoogleCalendarRestTool

        fetch = GoogleCalendarRestTool().list_events
    now = datetime.fromisoformat(vault.now())
    try:
        result = await fetch(
            time_min=now.isoformat(),
            time_max=(now + timedelta(days=HORIZON_DAYS)).isoformat(),
            max_results=MAX_EVENTS,
        )
    except Exception:  # noqa: BLE001 — a calendar fault skips this hour's sync
        log.info("memory calendar sync: calendar unavailable", exc_info=True)
        return None
    if not isinstance(result, dict) or not result.get("ok"):
        return None
    events = list((result.get("data") or {}).get("events") or [])
    if zone is None:
        zone = await asyncio.to_thread(_person_zone)
    counts = apply_events(vault, events, zone=zone)
    if any(counts.values()):
        from dodaios.memory.vault import runtime as vault_runtime

        vault_runtime.changed()
        log.info("memory calendar sync: %s", counts)
    return counts
