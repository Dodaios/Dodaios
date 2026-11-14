"""Reminders in the vault, the brain dump and the scheduler's delivery."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from dodaios.agent_chat.service import AgentChatService
from dodaios.agent_chat.store import AgentChatStore
from dodaios.memory.vault import MemoryVault
from dodaios.notify import reminders
from dodaios.notify.notifier import Verdict

BERLIN = ZoneInfo("Europe/Berlin")
NOW_LOCAL = datetime(2026, 11, 10, 10, 30, tzinfo=BERLIN)


class Clock:
    def __init__(self, moment: datetime) -> None:
        self.moment = moment

    def __call__(self) -> str:
        return self.moment.astimezone(UTC).isoformat(timespec="seconds")

    def utc(self) -> datetime:
        return self.moment.astimezone(UTC)


@pytest.fixture
def clock() -> Clock:
    return Clock(NOW_LOCAL)


@pytest.fixture
def vault(tmp_path: Path, clock: Clock) -> MemoryVault:
    v = MemoryVault(tmp_path / "vault.db", clock=clock)
    yield v
    v.close()


# ------------------------------------------------------------------- writing


def test_a_reminder_is_a_dated_ephemeral_memory(vault: MemoryVault) -> None:
    due = NOW_LOCAL.replace(hour=15, minute=0)
    result = reminders.create_reminder(vault, "call the bank", due, zone="Europe/Berlin")
    assert result.action == "added"
    memory = result.memory
    assert memory.kind == reminders.REMINDER_KIND
    assert memory.due_at == "2026-11-10T14:00:00+00:00"  # stored in UTC
    assert memory.source["reminder"] is True and memory.source["local"].startswith(
        "2026-11-10T15:00"
    )
    assert memory.valid_to > memory.due_at
    assert reminders.is_reminder(memory)
    # It is what "Coming up" reads.
    assert [m.id for m in vault.upcoming(days=1)] == [memory.id]
    # The always-on profile block does not list it.
    assert "call the bank" not in vault.profile_block()


def test_the_same_reminder_twice_is_one(vault: MemoryVault) -> None:
    due = NOW_LOCAL + timedelta(hours=2)
    first = reminders.create_reminder(vault, "call the bank", due)
    again = reminders.create_reminder(vault, "Call the bank.", due)
    assert again.action == "existing" and again.memory.id == first.memory.id


def test_done_and_snooze(vault: MemoryVault, clock: Clock) -> None:
    due = NOW_LOCAL + timedelta(hours=1)
    memory = reminders.create_reminder(vault, "call the bank", due).memory
    moved = reminders.snooze(vault, memory.id, due + timedelta(hours=3))
    assert moved is not None and moved.id != memory.id
    assert moved.due_at == "2026-11-10T13:30:00+00:00"
    assert moved.source["snoozed_from"] == memory.id
    assert vault.get(memory.id).is_current(clock()) is False
    assert [m.id for m in vault.upcoming(days=1)] == [moved.id]
    assert reminders.mark_done(vault, moved.id) is True
    assert reminders.mark_done(vault, moved.id) is False  # already closed
    assert vault.upcoming(days=1) == []
    assert reminders.snooze(vault, "nope", due) is None


def test_list_due_marks_delivered_and_overdue(vault: MemoryVault, clock: Clock) -> None:
    past = reminders.create_reminder(
        vault, "yesterday thing", NOW_LOCAL - timedelta(hours=2)
    ).memory
    reminders.create_reminder(vault, "later thing", NOW_LOCAL + timedelta(hours=2))
    vault.set_meta("reminder.delivered:" + past.id, clock())
    rows = reminders.list_due(vault, days=1)
    assert [r["text"] for r in rows] == ["yesterday thing", "later thing"]
    assert rows[0]["overdue"] is True and rows[0]["delivered"] is True
    assert rows[1]["overdue"] is False and rows[1]["delivered"] is False


def test_resolve_due_accepts_iso_and_phrases() -> None:
    due, text, has_time = reminders.resolve_due("2026-11-14T09:00", now=NOW_LOCAL, text="taxes")
    assert due == datetime(2026, 11, 14, 9, 0, tzinfo=BERLIN) and text == "taxes" and has_time
    due, text, has_time = reminders.resolve_due(
        "2026-11-14", now=NOW_LOCAL, text="remind me to pay"
    )
    assert due == datetime(2026, 11, 14, 9, 0, tzinfo=BERLIN) and text == "pay" and not has_time
    due, text, _ = reminders.resolve_due("Friday at 9", now=NOW_LOCAL, text="the taxes")
    assert due == datetime(2026, 11, 13, 9, 0, tzinfo=BERLIN) and text == "the taxes"
    # No ``when``: the time is found in the text and removed from it.
    due, text, _ = reminders.resolve_due(
        "", now=NOW_LOCAL, text="remind me Friday at 9 about the taxes"
    )
    assert due == datetime(2026, 11, 13, 9, 0, tzinfo=BERLIN) and text == "the taxes"
    due, text, _ = reminders.resolve_due("", now=NOW_LOCAL, text="mail Anna")
    assert due is None and text == "mail Anna"


# ---------------------------------------------------------------- brain dump


def test_a_brain_dump_becomes_separate_items() -> None:
    items = reminders.split_dump(
        "tomorrow dentist, buy milk, mail Anna about the offer and Friday at 9 the taxes",
        now=NOW_LOCAL,
    )
    assert [(i.text, i.due) for i in items] == [
        ("dentist", datetime(2026, 11, 11, 9, 0, tzinfo=BERLIN)),
        ("buy milk", None),
        ("mail Anna about the offer", None),
        ("the taxes", datetime(2026, 11, 13, 9, 0, tzinfo=BERLIN)),
    ]


def test_a_trailing_time_word_dates_the_item_before_it() -> None:
    items = reminders.split_dump("dentist; tomorrow\nbuy milk", now=NOW_LOCAL)
    assert [(i.text, i.due is not None) for i in items] == [("dentist", True), ("buy milk", False)]


def test_capture_stores_reminders_and_tasks(vault: MemoryVault) -> None:
    rows = reminders.capture_dump(vault, "morgen Zahnarzt, Milch kaufen", now=NOW_LOCAL)
    assert [(r["text"], r["kind"], r["reminder"]) for r in rows] == [
        ("Zahnarzt", reminders.REMINDER_KIND, True),
        ("Milch kaufen", reminders.TASK_KIND, False),
    ]
    assert all(r["op"] == "added" for r in rows)
    assert vault.get(rows[1]["id"]).source["task"] is True
    assert reminders.capture_dump(vault, "", now=NOW_LOCAL) == []


# ------------------------------------------------------------------ scheduler


class _Notifier:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def notify(self, kind: str, title: str, body: str, **kw: Any) -> Verdict:
        self.calls.append({"kind": kind, "title": title, "body": body, **kw})
        return Verdict(True, how="shown")


def _service(tmp_path: Path) -> tuple[AgentChatService, str]:
    svc = AgentChatService(AgentChatStore(":memory:"), assistant_name=lambda: "Dodaios")
    sid = svc.store.create_session(provider="p", model="m", effort="", cwd=str(tmp_path)).session_id
    return svc, sid


async def test_due_reminders_are_delivered_once(
    vault: MemoryVault, clock: Clock, tmp_path: Path
) -> None:
    svc, sid = _service(tmp_path)
    notifier = _Notifier()
    memory = reminders.create_reminder(
        vault, "call the bank", NOW_LOCAL + timedelta(minutes=10)
    ).memory
    later = reminders.create_reminder(vault, "tomorrow thing", NOW_LOCAL + timedelta(days=1)).memory
    scheduler = reminders.ReminderScheduler(
        vault=lambda: vault, target=lambda: (svc, sid), notifier=lambda: notifier, clock=clock.utc
    )
    assert await scheduler.tick() == []  # not yet
    clock.moment = NOW_LOCAL + timedelta(minutes=11)
    assert await scheduler.tick() == [memory.id]
    assert await scheduler.tick() == []  # never twice
    assert later.id not in [m.id for m in vault.upcoming(days=0)]
    events = svc.store.list_events(sid)
    notice = events[-1]
    assert notice["kind"] == "notice"
    assert notice["payload"]["kind"] == reminders.NOTICE_DUE
    assert (
        notice["payload"]["memory_id"] == memory.id and notice["payload"]["text"] == "call the bank"
    )
    call = notifier.calls[0]
    assert call["kind"] == "reminder" and call["body"] == "call the bank"
    assert call["session_id"] == sid and call["message_id"] == f"n-{notice['seq']}"
    assert call["ignore_focus"] is True
    assert reminders.list_due(vault, days=1)[0]["delivered"] is True


async def test_a_very_old_reminder_is_not_told_after_a_long_shutdown(
    vault: MemoryVault, clock: Clock, tmp_path: Path
) -> None:
    svc, sid = _service(tmp_path)
    notifier = _Notifier()
    reminders.create_reminder(vault, "stale", NOW_LOCAL + timedelta(hours=1))
    clock.moment = NOW_LOCAL + reminders.STALE_AFTER + timedelta(days=1)
    scheduler = reminders.ReminderScheduler(
        vault=lambda: vault, target=lambda: (svc, sid), notifier=lambda: notifier, clock=clock.utc
    )
    assert await scheduler.tick() == []
    assert notifier.calls == [] and svc.store.list_events(sid) == []
    # ...and it is not retried either.
    assert reminders.list_due(vault, days=1)[0]["delivered"] is True


async def test_without_a_conversation_the_desktop_still_hears(
    vault: MemoryVault, clock: Clock
) -> None:
    notifier = _Notifier()
    reminders.create_reminder(vault, "call the bank", NOW_LOCAL - timedelta(minutes=1))
    scheduler = reminders.ReminderScheduler(
        vault=lambda: vault, target=lambda: None, notifier=lambda: notifier, clock=clock.utc
    )
    assert len(await scheduler.tick()) == 1
    assert notifier.calls[0]["session_id"] == "" and notifier.calls[0]["body"] == "call the bank"


async def test_no_vault_is_a_quiet_tick() -> None:
    scheduler = reminders.ReminderScheduler(vault=lambda: None, notifier=lambda: None)
    assert await scheduler.tick() == []


def test_person_zone_falls_back_to_utc() -> None:
    assert str(reminders.person_zone("Europe/Berlin")) == "Europe/Berlin"
    assert str(reminders.person_zone("Mars/Olympus")) in ("UTC", str(reminders.person_zone(None)))


# ------------------------------------------------------------ calendar items


def test_rows_say_whose_item_it_is_what_it_is_called_and_when_it_runs(vault: MemoryVault) -> None:
    from dodaios.memory.vault import calendar_sync

    calendar_sync.apply_events(
        vault,
        [
            {
                "id": "e1",
                "summary": "Dentist",
                "start": "2026-11-10T11:00:00+01:00",
                "end": "2026-11-10T11:30:00+01:00",
                "location": "Main St 1",
                "url": "https://calendar.example/e1",
                "calendar": "Family",
            },
            {
                "id": "b1",
                "summary": "Busy",
                "start": "2026-11-10T12:00:00Z",
                "end": "2026-11-10T12:15:00Z",
                "calendar": "availability",
            },
            {"id": "h1", "summary": "Holiday", "start": "2026-11-11", "end": "2026-11-12"},
        ],
        zone=BERLIN,
    )
    reminders.create_reminder(vault, "call the bank", NOW_LOCAL + timedelta(hours=1))
    rows = reminders.list_due(vault, days=2)
    dentist = next(r for r in rows if r["title"] == "Dentist")
    assert dentist["source"] == "google_calendar" and dentist["reminder"] is False
    assert (dentist["start"], dentist["end"]) == (
        "2026-11-10T10:00:00+00:00",
        "2026-11-10T10:30:00+00:00",
    )
    assert (dentist["calendar"], dentist["location"]) == ("Family", "Main St 1")
    assert dentist["url"] == "https://calendar.example/e1"
    assert dentist["all_day"] is False and dentist["busy_only"] is False
    busy = next(r for r in rows if r["busy_only"])
    assert (busy["title"], busy["calendar"]) == ("", "availability")
    holiday = next(r for r in rows if r["title"] == "Holiday")
    assert holiday["all_day"] is True
    assert (holiday["start"], holiday["end"]) == ("2026-11-11", "2026-11-12")
    own = next(r for r in rows if r["reminder"])
    assert (own["source"], own["title"], own["end"], own["url"]) == (
        "dodaios",
        "call the bank",
        None,
        "",
    )


def test_an_appointment_written_before_its_source_fields_still_reads(vault: MemoryVault) -> None:
    """An older sync's memory: title from the sentence, overdue by its moment, not its text."""
    vault.remember(
        "Appointment: Busy on 2026-11-10 10:15.",
        "ephemeral",
        origin="imported",
        source={"via": "calendar", "event_id": "e1"},
        valid_to="2026-11-10T15:00:00+01:00",
        due_at="2026-11-10T10:15:00+01:00",
    )
    vault.remember(
        "Appointment: Holiday on 2026-11-11.",
        "ephemeral",
        origin="imported",
        source={"via": "calendar", "event_id": "h1"},
        valid_to="2026-11-12T00:00:00+00:00",
        due_at="2026-11-11T00:00:00+00:00",
    )
    busy, holiday = reminders.list_due(vault, days=2)
    assert (busy["source"], busy["busy_only"], busy["title"]) == ("google_calendar", True, "")
    # 10:15 +01:00 is 09:15 UTC: past at 09:30 UTC, although its text sorts later.
    assert busy["overdue"] is True
    assert busy["start"] == "2026-11-10T10:15:00+01:00"
    assert busy["end"] == "2026-11-10T15:00:00+01:00"
    assert (holiday["title"], holiday["all_day"], holiday["busy_only"]) == ("Holiday", True, False)


async def test_an_appointment_the_sync_rewrites_is_not_told_twice(
    vault: MemoryVault, clock: Clock, tmp_path: Path
) -> None:
    import json

    from dodaios.memory.vault import calendar_sync

    svc, sid = _service(tmp_path)
    notifier = _Notifier()
    # Written before 2026-11-14: the old sentence and the event's own offset.
    old = vault.remember(
        "Appointment: Workshop on 2026-11-10 10:00.",
        "ephemeral",
        origin="imported",
        source={"via": "calendar", "event_id": "e1"},
        valid_to="2026-11-10T12:00:00+01:00",
        due_at="2026-11-10T10:00:00+01:00",
    ).memory
    vault.set_meta(calendar_sync.META_KEY, json.dumps({"e1": old.id}))
    scheduler = reminders.ReminderScheduler(
        vault=lambda: vault, target=lambda: (svc, sid), notifier=lambda: notifier, clock=clock.utc
    )
    clock.moment = NOW_LOCAL + timedelta(hours=1)
    assert await scheduler.tick() == [old.id]
    event = {
        "id": "e1",
        "summary": "Workshop",
        "start": "2026-11-10T10:00:00+01:00",
        "end": "2026-11-10T12:00:00+01:00",
    }
    assert calendar_sync.apply_events(vault, [event], zone=BERLIN)["updated"] == 1
    [row] = reminders.list_due(vault, days=1)
    assert row["id"] != old.id and row["delivered"] is True
    assert row["due_at"] == "2026-11-10T09:00:00+00:00"
    assert await scheduler.tick() == []
    assert len(notifier.calls) == 1


def test_a_reminder_moved_to_another_time_is_told_again(vault: MemoryVault, clock: Clock) -> None:
    from dodaios.memory.vault import calendar_sync

    event = {"id": "e1", "summary": "Call", "start": "2026-11-10T09:00:00Z"}
    event["end"] = "2026-11-10T10:00:00Z"
    calendar_sync.apply_events(vault, [event])
    [first] = vault.list(kind="ephemeral")
    vault.set_meta("reminder.delivered:" + first.id, clock())
    moved = {**event, "start": "2026-11-10T09:20:00Z", "end": "2026-11-10T10:20:00Z"}
    calendar_sync.apply_events(vault, [moved])
    [row] = reminders.list_due(vault, days=1)
    assert row["id"] != first.id and row["delivered"] is False


def test_an_old_format_appointment_that_ended_is_neither_listed_nor_told(
    vault: MemoryVault, clock: Clock
) -> None:
    """Its end kept the event's offset: as text it still looks current, as a moment it is over."""
    old = vault.remember(
        "Appointment: Busy on 2026-11-10 08:15.",
        "ephemeral",
        origin="imported",
        source={"via": "calendar", "event_id": "e1"},
        # 08:15–09:15 +01:00 is 07:15–08:15 UTC.
        valid_to="2026-11-10T09:15:00+01:00",
        due_at="2026-11-10T08:15:00+01:00",
    ).memory
    later = vault.remember(
        "Appointment: Busy on 2026-11-10 11:00.",
        "ephemeral",
        origin="imported",
        source={"via": "calendar", "event_id": "e2"},
        valid_to="2026-11-10T12:00:00+01:00",
        due_at="2026-11-10T11:00:00+01:00",
    ).memory
    # At 09:00 UTC its end "…T09:15:00+01:00" still sorts after the clock's "…T09:00:00+00:00".
    clock.moment = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)
    assert old.id in [m.id for m in vault.upcoming(days=0)]
    assert [row["id"] for row in reminders.list_due(vault, days=1)] == [later.id]


async def test_the_scheduler_does_not_tell_an_old_format_appointment_after_its_end(
    vault: MemoryVault, clock: Clock
) -> None:
    notifier = _Notifier()
    # 08:15–08:30 +01:00 is 07:15–07:30 UTC; as text it comes due at 08:15 UTC.
    vault.remember(
        "Appointment: Busy on 2026-11-10 08:15.",
        "ephemeral",
        origin="imported",
        source={"via": "calendar", "event_id": "e1"},
        valid_to="2026-11-10T08:30:00+01:00",
        due_at="2026-11-10T08:15:00+01:00",
    )
    clock.moment = datetime(2026, 11, 10, 8, 20, tzinfo=UTC)
    scheduler = reminders.ReminderScheduler(
        vault=lambda: vault, target=lambda: None, notifier=lambda: notifier, clock=clock.utc
    )
    assert await scheduler.tick() == []
    assert notifier.calls == []
