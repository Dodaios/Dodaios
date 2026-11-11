"""Google Calendar: new invites, changes and cancellations (``updatedMin``), and starts soon."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Final

from ..event import TriggerEvent
from .base import Api, Poll, ProviderError

_BASE: Final[str] = "https://www.googleapis.com/calendar/v3"
MAX_CALENDARS: Final[int] = 10
SOON_MINUTES: Final[int] = 15
_SOON_REMEMBERED: Final[int] = 100


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _start(item: dict[str, Any]) -> str:
    start = item.get("start") or {}
    return str(start.get("dateTime") or start.get("date") or "")


class CalendarProducer:
    id = "google_calendar"
    source = "calendar"

    def __init__(self, api: Api, soon_minutes: int = SOON_MINUTES) -> None:
        self._api = api
        self._soon = soon_minutes

    async def connected(self) -> bool:
        return await self._api.connected()

    async def _calendars(self) -> list[tuple[str, str]]:
        response = await self._api.get(
            f"{_BASE}/users/me/calendarList", {"minAccessRole": "reader", "maxResults": 50}
        )
        if response.status_code != 200:
            raise ProviderError(f"calendar: list HTTP {response.status_code}")
        found = [
            (str(c.get("id")), str(c.get("summary") or c.get("id")))
            for c in response.json().get("items") or []
            if c.get("id") and (c.get("selected") or c.get("primary"))
        ]
        return found[:MAX_CALENDARS]

    async def poll(self, cursor: dict[str, Any], now: float) -> Poll:
        moment = datetime.fromtimestamp(now, UTC)
        updated_min = str(cursor.get("updated_min") or "")
        if not updated_min:  # the first poll only marks the present
            return Poll([], {"updated_min": _iso(moment), "soon_seen": []})
        calendars = await self._calendars()
        events: list[TriggerEvent] = []
        for calendar_id, name in calendars:
            response = await self._api.get(
                f"{_BASE}/calendars/{calendar_id}/events",
                {"updatedMin": updated_min, "showDeleted": "true", "maxResults": 100},
            )
            if response.status_code in (404, 410):  # a calendar that went away
                continue
            if response.status_code != 200:
                raise ProviderError(f"calendar: events HTTP {response.status_code}")
            for item in response.json().get("items") or []:
                event = _change(item, name, updated_min, now)
                if event is not None:
                    events.append(event)
        soon_seen = [str(i) for i in cursor.get("soon_seen") or []]
        window_end = moment + timedelta(minutes=self._soon)
        for calendar_id, name in calendars:
            response = await self._api.get(
                f"{_BASE}/calendars/{calendar_id}/events",
                {"timeMin": _iso(moment), "timeMax": _iso(window_end), "singleEvents": "true",
                 "orderBy": "startTime", "maxResults": 25},
            )
            if response.status_code != 200:
                continue
            for item in response.json().get("items") or []:
                key = f"soon:{item.get('id')}:{_start(item)}"
                if key in soon_seen or not _soon_ok(item):
                    continue
                soon_seen.append(key)
                events.append(TriggerEvent(
                    source="calendar", scope=name, thread_key=str(item.get("id") or ""),
                    summary=f"Starting soon: {item.get('summary') or 'Event'} ({_start(item)})",
                    ids=(key,), received_at=now, raw_ref=str(item.get("htmlLink") or ""),
                    labels=("starting_soon",),
                ))
        return Poll(events, {
            "updated_min": _iso(moment - timedelta(seconds=1)),
            "soon_seen": soon_seen[-_SOON_REMEMBERED:],
        })


def _soon_ok(item: dict[str, Any]) -> bool:
    if item.get("status") == "cancelled" or "dateTime" not in (item.get("start") or {}):
        return False  # all-day entries are not "starting"
    mine = next((a for a in item.get("attendees") or [] if a.get("self")), None)
    return not (mine and mine.get("responseStatus") == "declined")


def _change(
    item: dict[str, Any], calendar: str, updated_min: str, now: float
) -> TriggerEvent | None:
    organizer = item.get("organizer") or {}
    if organizer.get("self"):  # the owner's own edits are not news
        return None
    mine = next((a for a in item.get("attendees") or [] if a.get("self")), None)
    if item.get("status") == "cancelled":
        kind = "Cancelled"
    elif mine and mine.get("responseStatus") == "needsAction" and str(
        item.get("created") or ""
    ) >= updated_min:
        kind = "Invite"
    else:
        kind = "Changed"
    title = item.get("summary") or "Event"
    return TriggerEvent(
        source="calendar", scope=calendar,
        sender=str(organizer.get("email") or "").lower(),
        thread_key=str(item.get("id") or ""),
        summary=f"{kind}: {title} ({_start(item)})" if _start(item) else f"{kind}: {title}",
        ids=(f"{item.get('id')}:{item.get('updated')}",), received_at=now,
        raw_ref=str(item.get("htmlLink") or ""), labels=(kind.lower(),),
    )
