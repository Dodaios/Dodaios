"""'What's on today?' answered from the written brief or dated memories."""

from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest

from dodaios.speech import spoken_brief


@pytest.mark.parametrize(
    "text",
    [
        "What's on today?",
        "what is on for today",
        "What do I have today?",
        "Brief me.",
        "Today's agenda, please",
        "Was steht heute an?",
        "Was habe ich heute?",
        "Wie sieht mein Tag aus?",
        "Qué tengo hoy?",
        "O que tenho hoje?",
    ],
)
def test_brief_requests_are_recognised(text: str) -> None:
    assert spoken_brief.is_brief_request(text)


@pytest.mark.parametrize(
    "text",
    [
        "Open the browser", "What's the weather today?", "Move that to 3 pm",
        "Was kostet das heute?", "",
    ],
)
def test_other_turns_are_left_to_the_brain(text: str) -> None:
    assert not spoken_brief.is_brief_request(text)


def test_spoken_form_drops_markup_and_stops_at_a_sentence() -> None:
    written = (
        "## Calendar\n"
        "- **09:00** Dentist ([map](https://example.test/x))\n"
        "- 15:00 Call with Anna\n\n"
        "## Waiting on you\n"
        "1. Reply to the landlord\n"
    )
    spoken = spoken_brief.spoken_form(written)
    assert spoken == (
        "Calendar. 09:00 Dentist (map). 15:00 Call with Anna. "
        "Waiting on you. Reply to the landlord."
    )
    long = " ".join(f"Sentence number {i}." for i in range(400))
    cut = spoken_brief.spoken_form(long, max_chars=200)
    assert len(cut) <= 200 and cut.endswith(".")


def _memory(text: str, due_at: str | None):
    return SimpleNamespace(text=text, due_at=due_at)


def test_compose_lists_today_with_times_and_what_is_still_open() -> None:
    now = datetime(2026, 11, 10, 7, 30)
    memories = [
        _memory(
            "Appointment: Dentist on 2026-11-10 09:00 (Main Street).",
            "2026-11-10T09:00:00+01:00",
        ),
        _memory("Appointment: Call with Anna on 2026-11-10 15:00.", "2026-11-10T15:00:00+01:00"),
        _memory("Send the tax forms.", "2026-11-09"),
        _memory("Appointment: Gym on 2026-11-11 18:00.", "2026-11-11T18:00:00+01:00"),
    ]
    text = spoken_brief.compose_from_memories(memories, now=now, language="en")
    assert text == (
        "Today: at 09:00, Dentist (Main Street); at 15:00, Call with Anna. "
        "Still open: Send the tax forms."
    )
    de = spoken_brief.compose_from_memories(memories[:1], now=now, language="de")
    assert de == "Heute: um 09:00 Dentist (Main Street)."


def test_compose_says_so_when_nothing_is_due() -> None:
    now = datetime(2026, 11, 10, 7, 30)
    assert "Nothing is scheduled" in spoken_brief.compose_from_memories([], now=now, language="en")
    assert "nichts geplant" in spoken_brief.compose_from_memories(
        [_memory("Later", "2026-12-01")], now=now, language="de"
    )


def test_written_brief_today_takes_the_routines_newest_result_of_today() -> None:
    now = datetime(2026, 11, 10, 9, 0)
    today_ms = int(datetime(2026, 11, 10, 8, 0).timestamp() * 1000)
    yesterday_ms = int(datetime(2026, 11, 9, 8, 0).timestamp() * 1000)
    events = [
        {"seq": 1, "ts_ms": yesterday_ms, "kind": "notice",
         "payload": {"kind": "society_result", "task_id": "brief", "text": "Old brief"}},
        {"seq": 2, "ts_ms": today_ms, "kind": "notice",
         "payload": {"kind": "society_result", "task_id": "other", "text": "Other routine"}},
        {"seq": 3, "ts_ms": today_ms, "kind": "notice",
         "payload": {"kind": "society_result", "task_id": "brief", "text": "## Today\n- Dentist"}},
        {"seq": 4, "ts_ms": today_ms, "kind": "assistant_text", "payload": {"text": "hi"}},
    ]
    found = spoken_brief.written_brief_today(events, task_id="brief", now=now)
    assert found == "## Today\n- Dentist"
    # Yesterday's brief is not today's.
    assert spoken_brief.written_brief_today(events[:1], task_id="brief", now=now) is None
    assert spoken_brief.written_brief_today(events, task_id="", now=now) is None


def test_build_prefers_the_written_brief_and_falls_back_to_memories(monkeypatch) -> None:
    async def task_id() -> str:
        return "brief"

    monkeypatch.setattr(spoken_brief, "_brief_task_id", task_id)
    monkeypatch.setattr(
        spoken_brief, "_read_written_brief", lambda _tid, _now: "- **Dentist** at nine"
    )
    assert asyncio.run(spoken_brief.build(language="en")) == "Dentist at nine."

    monkeypatch.setattr(spoken_brief, "_read_written_brief", lambda _tid, _now: None)
    now = datetime(2026, 11, 10, 7, 0)
    monkeypatch.setattr(
        spoken_brief, "_read_upcoming",
        lambda: [_memory("Appointment: Dentist on 2026-11-10 09:00.", "2026-11-10T09:00:00")],
    )
    assert asyncio.run(spoken_brief.build(language="en", now=now)) == "Today: at 09:00, Dentist."


def test_build_never_raises(monkeypatch) -> None:
    async def boom() -> str:
        raise RuntimeError("no society")

    monkeypatch.setattr(spoken_brief, "_brief_task_id", boom)
    def broken() -> list:
        raise OSError("db")

    monkeypatch.setattr(spoken_brief, "_read_upcoming", broken)
    text = asyncio.run(spoken_brief.build(language="es"))
    assert "nada previsto" in text
