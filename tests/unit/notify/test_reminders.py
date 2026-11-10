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
