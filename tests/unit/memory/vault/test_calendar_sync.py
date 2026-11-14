"""Calendar appointments become short-lived memories (ADR-0044)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from dodaios.memory.vault import calendar_sync
from dodaios.memory.vault import runtime as vault_runtime
from dodaios.memory.vault.store import MemoryVault


class Clock:
    def __init__(self) -> None:
        self.value = "2026-11-09T09:00:00+00:00"

    def __call__(self) -> str:
        return self.value


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def vault(tmp_path: Path, clock: Clock):
    v = MemoryVault(tmp_path / "vault.db", clock=clock)
    vault_runtime.set_active(v)
    yield v
    vault_runtime.set_active(None)


def _event(eid: str, summary: str, start: str, end: str, **extra: Any) -> dict[str, Any]:
    return {"id": eid, "summary": summary, "start": start, "end": end, **extra}


def test_events_become_due_ephemeral_memories(vault):
    events = [
        _event(
            "e1",
            "Dentist",
            "2026-11-12T09:00:00+00:00",
            "2026-11-12T10:00:00+00:00",
            location="Main St 1",
        ),
        _event("e2", "Holiday", "2026-11-20", "2026-11-21"),
    ]
    assert calendar_sync.apply_events(vault, events) == {"added": 2, "updated": 0, "ended": 0}
    texts = {m.text: m for m in vault.list(kind="ephemeral")}
    dentist = texts["Appointment: Dentist on 2026-11-12 09:00–10:00 (Main St 1)."]
    assert dentist.due_at == "2026-11-12T09:00:00+00:00"
    assert dentist.valid_to == "2026-11-12T10:00:00+00:00"
    assert "Appointment: Holiday on 2026-11-20." in texts
    assert "Dentist" in vault_runtime.turn_block("when is my dentist appointment")
    assert "Dentist" not in vault.profile_block()
    # A second identical sync changes nothing.
    assert calendar_sync.apply_events(vault, events) == {"added": 0, "updated": 0, "ended": 0}


def test_moved_and_cancelled_events(vault, clock):
    calendar_sync.apply_events(
        vault, [_event("e1", "Dentist", "2026-11-12T09:00:00+00:00", "2026-11-12T10:00:00+00:00")]
    )
    moved = [_event("e1", "Dentist", "2026-11-13T09:00:00+00:00", "2026-11-13T10:00:00+00:00")]
    assert calendar_sync.apply_events(vault, moved)["updated"] == 1
    assert [m.text for m in vault.list(kind="ephemeral")] == [
        "Appointment: Dentist on 2026-11-13 09:00–10:00."
    ]
    assert calendar_sync.apply_events(vault, [])["ended"] == 1
    assert vault.list(kind="ephemeral") == []


def test_past_appointments_drop_out_on_their_own(vault, clock):
    calendar_sync.apply_events(
        vault, [_event("e1", "Call", "2026-11-09T10:00:00+00:00", "2026-11-09T11:00:00+00:00")]
    )
    clock.value = "2026-11-09T12:00:00+00:00"
    assert vault.list(kind="ephemeral") == []


def test_sync_handles_a_disconnected_calendar(vault):
    async def disconnected(**_: Any) -> dict[str, Any]:
        return {"ok": False, "status": 401, "error": "not connected"}

    async def connected(**_: Any) -> dict[str, Any]:
        return {
            "ok": True,
            "data": {
                "events": [
                    _event(
                        "e1", "Dentist", "2026-11-12T09:00:00+00:00", "2026-11-12T10:00+00:00"
                    )
                ]
            },
        }

    assert asyncio.run(calendar_sync.sync(vault, disconnected)) is None
    assert asyncio.run(calendar_sync.sync(vault, connected)) == {
        "added": 1,
        "updated": 0,
        "ended": 0,
    }


BERLIN = ZoneInfo("Europe/Berlin")


def test_times_are_stored_in_utc_and_the_sentence_reads_on_the_persons_clock(vault, clock):
    """The vault compares UTC text: an event in +01:00 comes due at its moment, not an hour late."""
    events = [
        _event("e1", "Dentist", "2026-11-12T10:15:00+01:00", "2026-11-12T11:00:00+01:00"),
        # A calendar kept in UTC still reads on the person's clock.
        _event("e2", "Call", "2026-11-12T12:00:00Z", "2026-11-12T12:15:00Z"),
    ]
    calendar_sync.apply_events(vault, events, zone=BERLIN)
    by_text = {m.text: m for m in vault.list(kind="ephemeral")}
    dentist = by_text["Appointment: Dentist on 2026-11-12 10:15–11:00."]
    assert (dentist.due_at, dentist.valid_to) == (
        "2026-11-12T09:15:00+00:00",
        "2026-11-12T10:00:00+00:00",
    )
    assert "Appointment: Call on 2026-11-12 13:00–13:15." in by_text
    clock.value = "2026-11-12T09:16:00+00:00"
    assert [m.text for m in vault.upcoming(days=0)] == [dentist.text]
    # Over at 11:00 Berlin, not at 11:00 UTC.
    clock.value = "2026-11-12T10:01:00+00:00"
    assert dentist.id not in [m.id for m in vault.list(kind="ephemeral")]


def test_an_entry_that_only_says_busy_says_so_and_keeps_what_the_rail_needs(vault):
    events = [
        _event(
            "b1",
            "Busy",
            "2026-11-14T10:15:00+01:00",
            "2026-11-14T15:00:00+01:00",
            calendar="Team availability",
            calendar_id="x@group.calendar.google.com",
            url="https://www.google.com/calendar/event?eid=abc",
        ),
        # Shared as free/busy only: no title of its own, whatever the entry is called.
        _event(
            "f1",
            "(no title)",
            "2026-11-14T16:00:00+01:00",
            "2026-11-14T17:00:00+01:00",
            calendar="Team",
            calendar_access="freeBusyReader",
        ),
        _event(
            "d1",
            "Dentist",
            "2026-11-15T09:00:00+01:00",
            "2026-11-15T09:30:00+01:00",
            calendar="me@example.com",
            calendar_primary=True,
            location="Main St 1",
        ),
        _event("h1", "Holiday", "2026-11-20", "2026-11-23", calendar="Holidays in Germany"),
    ]
    calendar_sync.apply_events(vault, events, zone=BERLIN)
    by_event = {m.source["event_id"]: m for m in vault.list(kind="ephemeral")}
    busy = by_event["b1"]
    assert busy.text == (
        'Appointment: busy, no details shared (calendar "Team availability") '
        "on 2026-11-14 10:15–15:00."
    )
    assert busy.source == {
        "via": "calendar",
        "provider": "google_calendar",
        "event_id": "b1",
        "title": "",
        "busy_only": True,
        "calendar": "Team availability",
        "all_day": False,
        "start": "2026-11-14T09:15:00+00:00",
        "end": "2026-11-14T14:00:00+00:00",
        "location": "",
        "url": "https://www.google.com/calendar/event?eid=abc",
    }
    assert by_event["f1"].source["busy_only"] is True
    assert by_event["f1"].text.startswith('Appointment: busy, no details shared (calendar "Team")')
    # The primary calendar's name is the account's address: not worth showing.
    dentist = by_event["d1"]
    assert (dentist.source["title"], dentist.source["calendar"]) == ("Dentist", "")
    assert dentist.text == "Appointment: Dentist on 2026-11-15 09:00–09:30 (Main St 1)."
    # A whole-day entry keeps its dates and starts at midnight on the person's clock.
    holiday = by_event["h1"]
    assert holiday.text == "Appointment: Holiday from 2026-11-20 to 2026-11-22."
    assert holiday.source["all_day"] is True
    assert (holiday.source["start"], holiday.source["end"]) == ("2026-11-20", "2026-11-23")
    assert holiday.due_at == "2026-11-19T23:00:00+00:00"


def test_the_same_appointment_on_two_calendars_is_one_memory(vault):
    """Two feeds of one availability: the same block in UTC and in +01:00 is one reminder."""
    v1 = _event("v1", "Busy", "2026-11-18T18:30:00Z", "2026-11-18T19:00:00Z", calendar="a")
    v2 = _event("v2", "Busy", "2026-11-18T19:30:00+01:00", "2026-11-18T20:00:00+01:00")
    v2["calendar"] = "b"
    other = _event("o1", "Busy", "2026-11-18T21:00:00+01:00", "2026-11-18T22:00:00+01:00")
    counts = calendar_sync.apply_events(vault, [v1, v2, other], zone=BERLIN)
    assert counts == {"added": 2, "updated": 0, "ended": 0}
    assert len(vault.list(kind="ephemeral")) == 2
    # One calendar drops it, the other still has it: the appointment stays.
    assert calendar_sync.apply_events(vault, [v2, other], zone=BERLIN)["ended"] == 0
    assert len(vault.list(kind="ephemeral")) == 2


def test_duplicates_written_before_the_merge_become_one(vault):
    """Memories of one block from two calendars, as older syncs wrote them, are merged."""
    old1 = vault.remember(
        "Appointment: Busy on 2026-11-18 18:30.",
        "ephemeral",
        origin="imported",
        source={"via": "calendar", "event_id": "v1"},
        valid_to="2026-11-18T19:00:00Z",
        due_at="2026-11-18T18:30:00Z",
    ).memory
    old2 = vault.remember(
        "Appointment: Busy on 2026-11-18 19:30.",
        "ephemeral",
        origin="imported",
        source={"via": "calendar", "event_id": "v2"},
        valid_to="2026-11-18T20:00:00+01:00",
        due_at="2026-11-18T19:30:00+01:00",
    ).memory
    vault.set_meta(calendar_sync.META_KEY, json.dumps({"v1": old1.id, "v2": old2.id}))
    v1 = _event("v1", "Busy", "2026-11-18T18:30:00Z", "2026-11-18T19:00:00Z")
    v2 = _event("v2", "Busy", "2026-11-18T19:30:00+01:00", "2026-11-18T20:00:00+01:00")
    assert calendar_sync.apply_events(vault, [v1, v2], zone=BERLIN) == {
        "added": 0,
        "updated": 1,
        "ended": 1,
    }
    [memory] = vault.list(kind="ephemeral")
    assert memory.supersedes_id == old1.id
    assert memory.due_at == "2026-11-18T18:30:00+00:00"
    assert memory.text == "Appointment: busy, no details shared on 2026-11-18 19:30–20:00."


def test_a_ticked_off_appointment_stays_off_until_it_moves(vault):
    """Done while the event still runs: the next hourly sync must not bring it back."""
    from dodaios.notify import reminders

    event = _event("e1", "Workshop", "2026-11-09T08:30:00+00:00", "2026-11-09T12:00:00+00:00")
    calendar_sync.apply_events(vault, [event])
    [memory] = vault.list(kind="ephemeral")
    assert reminders.mark_done(vault, memory.id)
    assert calendar_sync.apply_events(vault, [event]) == {"added": 0, "updated": 0, "ended": 0}
    assert vault.list(kind="ephemeral") == []
    # Moved to another day, it is a new appointment and comes due again.
    moved = _event("e1", "Workshop", "2026-11-10T08:30:00+00:00", "2026-11-10T12:00:00+00:00")
    assert calendar_sync.apply_events(vault, [moved])["added"] == 1


def test_an_appointment_the_sync_ended_comes_back_when_the_calendar_shows_it_again(vault):
    """Only the person's own Done keeps it off; a sync that lost the event brings it back."""
    event = _event("e1", "Workshop", "2026-11-10T08:30:00+00:00", "2026-11-10T12:00:00+00:00")
    calendar_sync.apply_events(vault, [event])
    assert calendar_sync.apply_events(vault, [])["ended"] == 1
    assert calendar_sync.apply_events(vault, [event])["added"] == 1
