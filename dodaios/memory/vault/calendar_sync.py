"""Upcoming calendar appointments as short-lived memories (ADR-0044).

Once an hour, when Google Calendar is connected, the next two weeks of events
become ``ephemeral`` memories ("Appointment: Dentist on 2026-11-12 09:00")
with a due date and an end date. They answer "when is my dentist?" through the
normal recall and feed the coming-up grounding; after the event they drop out
of every read on their own. A moved or renamed event supersedes its memory; a
cancelled one is ended. No model call is made, nothing is written back to the
calendar, and the user's mail is deliberately not read.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from dodaios.memory.vault.store import MemoryVault

log = logging.getLogger(__name__)

META_KEY = "calendar_sync"
HORIZON_DAYS = 14
MAX_EVENTS = 50


def _when(value: str) -> str:
    """'2026-11-12T09:00:00+01:00' -> '2026-11-12 09:00'; an all-day date stays a date."""
    return value[:16].replace("T", " ") if "T" in value else value[:10]


def _iso(value: str) -> str:
    return value if "T" in value else value + "T00:00:00+00:00"


def event_text(event: dict[str, Any]) -> str:
    summary = " ".join(str(event.get("summary") or "(no title)").split())[:160]
    text = f"Appointment: {summary} on {_when(str(event.get('start') or ''))}"
    location = " ".join(str(event.get("location") or "").split())[:80]
    return f"{text} ({location})." if location else f"{text}."


def apply_events(vault: MemoryVault, events: list[dict[str, Any]]) -> dict[str, int]:
    """Bring the vault's appointment memories in line with ``events``."""
    raw = vault.get_meta(META_KEY)
    try:
        known: dict[str, str] = dict(json.loads(raw)) if raw else {}
    except ValueError:  # an unreadable map starts afresh; duplicates are caught by content
        known = {}
    counts = {"added": 0, "updated": 0, "ended": 0}
    seen: set[str] = set()
    for event in events[:MAX_EVENTS]:
        event_id = str(event.get("id") or "")
        start, end = str(event.get("start") or ""), str(event.get("end") or "")
        if not event_id or not start or event.get("status") == "cancelled":
            continue
        seen.add(event_id)
        text = event_text(event)
        source = {"via": "calendar", "event_id": event_id}
        current = vault.get(known[event_id]) if event_id in known else None
        if current is not None and current.is_current(vault.now()):
            if current.text == text:
                continue
            result = vault.supersede(
                current.id,
                text,
                origin="imported",
                source=source,
                valid_to=_iso(end or start),
                due_at=_iso(start),
            )
            counts["updated"] += result.action == "superseded"
        else:
            result = vault.remember(
                text,
                "ephemeral",
                origin="imported",
                source=source,
                confidence=1.0,
                valid_to=_iso(end or start),
                due_at=_iso(start),
            )
            counts["added"] += result.action == "added"
        if result.memory is not None:
            known[event_id] = result.memory.id
    for event_id, memory_id in list(known.items()):
        if event_id in seen:
            continue
        memory = vault.get(memory_id)
        if memory is not None and memory.is_current(vault.now()):
            # Gone from the next two weeks before it happened: moved far away or cancelled.
            if (memory.due_at or "") > vault.now() and vault.invalidate(
                memory_id, reason="no longer on the calendar"
            ):
                counts["ended"] += 1
        known.pop(event_id, None)
    vault.set_meta(META_KEY, json.dumps(known))
    return counts


async def sync(vault: MemoryVault, fetch: Any = None) -> dict[str, int] | None:
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
    counts = apply_events(vault, events)
    if any(counts.values()):
        from dodaios.memory.vault import runtime as vault_runtime

        vault_runtime.changed()
        log.info("memory calendar sync: %s", counts)
    return counts
