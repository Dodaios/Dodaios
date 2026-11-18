"""The assistant words what it tells on its own (``agent_chat/proactive_voice.py``)."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from dodaios.agent_chat import proactive_voice as pv

ZONE = ZoneInfo("Europe/Berlin")
NOW = datetime(2026, 11, 18, 10, 28, tzinfo=ZONE)


def _due(title: str, start: str, end: str) -> dict[str, Any]:
    return {
        "kind": "reminder_due",
        "title": title,
        "source": "google_calendar",
        "reminder": False,
        "start": start,
        "end": end,
        "memory_id": f"m_{title}",
    }


def _situation(svc: Any, session_id: str, extra: list[str]) -> pv.Situation:
    return pv.Situation(
        now=NOW,
        language="de",
        assistant_name="George",
        later_today=extra,
        failed_today=["Täglicher Mail-Check 9:30 (failed): usage limit"],
    )


def _desk(write: pv.Writer) -> pv.VoiceDesk:
    return pv.VoiceDesk(write=write, situation=_situation, settle_s=0.05, timeout_s=1.0)


def test_items_told_at_once_are_one_message_in_the_model_words() -> None:
    prompts: list[str] = []
    stored: list[dict[str, Any]] = []

    async def write(prompt: str) -> str:
        prompts.append(prompt)
        return "Gleich ist Pause bis 10:45, danach hast du eine halbe Stunde für Mails."

    async def store(payload: dict[str, Any]) -> None:
        stored.append(payload)

    async def run() -> None:
        desk = _desk(write)
        pause = _due("Pause", "2026-11-18T09:30:00Z", "2026-11-18T09:45:00Z")
        mails = _due("Mails & Inbox", "2026-11-18T09:45:00Z", "2026-11-18T10:15:00Z")
        pause[pv.CONTEXT_KEY] = ["Deep Work 2: a calendar appointment; time 11:15-13:00"]
        await asyncio.gather(
            desk.tell(None, "s1", pause, store), desk.tell(None, "s1", mails, store)
        )

    asyncio.run(run())
    assert len(prompts) == 1
    prompt = prompts[0]
    assert "Pause" in prompt and "Mails & Inbox" in prompt and "10:30-10:45" in prompt
    assert "Täglicher Mail-Check" in prompt and "Deep Work 2" in prompt
    assert "German" in prompt and "George" in prompt
    assert [p["title"] for p in stored] == ["Pause", "Mails & Inbox"]
    assert stored[0]["voice"].startswith("Gleich ist Pause") and stored[0]["voice_by"] == "model"
    assert stored[1].get("voice_covered") is True and "voice" not in stored[1]
    assert all(pv.CONTEXT_KEY not in p for p in stored)


def test_without_a_model_the_message_is_a_written_sentence_in_the_person_language() -> None:
    stored: list[dict[str, Any]] = []

    async def no_seat(prompt: str) -> None:
        return None

    async def store(payload: dict[str, Any]) -> None:
        stored.append(payload)

    tidy = {"kind": "memory_tidy", "text": "Tidied the memory: merged 2", "merged": 2, "retired": 1}
    asyncio.run(_desk(no_seat).tell(None, "s1", tidy, store))
    assert stored[0]["voice_by"] == "phrase"
    assert stored[0]["voice"] == (
        "Ich habe mein Gedächtnis über dich aufgeräumt: 2 doppelte Einträge zusammengeführt "
        "und einen veralteten Eintrag entfernt. Unter Memory kannst du es dir ansehen."
    )


def test_a_slow_model_never_holds_the_notice_back() -> None:
    stored: list[dict[str, Any]] = []

    async def slow(prompt: str) -> str:
        await asyncio.sleep(5)
        return "too late"

    async def store(payload: dict[str, Any]) -> None:
        stored.append(payload)

    desk = pv.VoiceDesk(write=slow, situation=_situation, settle_s=0.0, timeout_s=0.05)
    item = _due("Pause", "2026-11-18T09:30:00Z", "2026-11-18T09:45:00Z")
    asyncio.run(desk.tell(None, "s1", item, store))
    assert stored[0]["voice"] == "Pause beginnt um 10:30 und geht bis 10:45."


def test_the_model_reply_is_kept_only_when_it_is_a_message() -> None:
    assert pv.clean('"Gleich ist Pause."') == "Gleich ist Pause."
    assert pv.clean("") == ""
    assert pv.clean("x" * (pv.MAX_CHARS + 1)) == ""


def test_only_unworded_kinds_are_worded() -> None:
    assert pv.wants_voice({"kind": "reminder_due"})
    assert pv.wants_voice({"kind": "memory_tidy"})
    assert not pv.wants_voice({"kind": "reminder_due", "voice": "x"})
    assert not pv.wants_voice({"kind": "society_result"})


def test_later_today_lists_what_is_still_coming() -> None:
    rows = [
        {"id": "a", "title": "Deep Work 2", "source": "google_calendar", "reminder": False,
         "start": "2026-11-18T10:15:00Z", "end": "2026-11-18T12:00:00Z"},
        {"id": "b", "title": "Yesterday", "source": "google_calendar", "reminder": False,
         "start": "2026-11-17T10:15:00Z"},
        {"id": "c", "title": "Pause", "source": "google_calendar", "reminder": False,
         "start": "2026-11-18T09:30:00Z"},
    ]
    lines = pv.later_today(rows, now=NOW, exclude={"c"})
    assert lines == ["Deep Work 2: a calendar appointment (google_calendar); time 11:15-13:00"]
