"""A ritual started by what was said or typed: what starts it, and what the voice says."""

from __future__ import annotations

from datetime import datetime

import pytest

from dodaios.core.events import AnnouncementRequested
from dodaios.rituals import prepare, said, service
from dodaios.rituals.store import get_store
from tests.unit.rituals.conftest import LEAD_SESSION, MORNING, settle

ONLY_NOW = {
    "name": "Evening",
    "phrases": ["Good evening"],
    "steps": [{"when": "now", "text": "Dim the lights."}],
}


def _today() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d")


def _gathered(ritual, spoken: str = "Good morning. One thing today.") -> None:
    get_store().patch_day(
        ritual.id, _today(), prep_state="ready", prepared_ms=1,
        steps_hash=prepare.steps_hash(ritual), spoken=spoken, written="## Today\n- One thing.",
    )


class Bus:
    def __init__(self) -> None:
        self.published: list[object] = []

    async def publish(self, event: object) -> None:
        self.published.append(event)


@pytest.fixture
def bus(monkeypatch: pytest.MonkeyPatch) -> Bus:
    wired = Bus()
    monkeypatch.setattr(said, "_bus", wired)
    return wired


# ── spoken ──────────────────────────────────────────────────────────────────────


async def test_the_phrase_is_answered_with_what_was_gathered(society) -> None:
    ritual = await service.create(**MORNING)
    _gathered(ritual)
    spoken = await said.spoken_answer("Hey Nova, good morning", language="en")
    await settle()
    assert spoken == "Good morning. One thing today."
    # What was said stands in the conversation above the card; no turn answers it.
    assert society.chat.filed == [
        {"session_id": LEAD_SESSION, "text": "Hey Nova, good morning", "reply": ""}
    ]
    (card,) = society.cards()
    assert card["via"] == "voice" and card["pending"] is False
    assert service.today_of(ritual.id).fired_via == "voice"


async def test_with_nothing_gathered_the_voice_says_one_short_line(society) -> None:
    await service.create(**MORNING)
    assert await said.spoken_answer("good morning", language="en") == (
        "On it. The rest is on its way."
    )
    await service.create(**ONLY_NOW)
    assert await said.spoken_answer("good evening", language="de") == "Läuft."  # i18n-allow
    await settle()


async def test_an_ordinary_sentence_is_left_to_the_assistant(society) -> None:
    ritual = await service.create(**{**MORNING, "enabled": False})
    assert await said.spoken_answer("What is the weather like?", language="en") is None
    assert await said.spoken_answer("Good morning, any news?", language="en") is None
    # Its ritual is off: the phrase is a greeting.
    assert await said.spoken_answer("Good morning", language="en") is None
    assert society.cards() == [] and society.chat.filed == []
    assert service.today_of(ritual.id) is None


async def test_the_second_time_on_a_day_is_a_greeting(society) -> None:
    await service.create(**MORNING)
    assert await said.spoken_answer("Good morning", language="en")
    assert await said.spoken_answer("Good morning", language="en") is None
    await settle()
    assert len(society.start_cards()) == 1


async def test_a_phrase_that_cannot_be_looked_at_is_an_ordinary_sentence(
    society, monkeypatch: pytest.MonkeyPatch
) -> None:
    await service.create(**MORNING)

    def broken(*args, **kwargs):
        raise RuntimeError("the store is closed")

    monkeypatch.setattr(service, "find_match", broken)
    assert await said.spoken_answer("Good morning", language="en") is None
    assert await said.typed(society.chat, LEAD_SESSION, "Good morning") == ""


async def test_without_the_assistant_the_phrase_is_an_ordinary_sentence(
    society, monkeypatch: pytest.MonkeyPatch
) -> None:
    ritual = await service.create(**MORNING)
    monkeypatch.setattr(service, "_runtime", lambda: None)
    assert await said.spoken_answer("Good morning", language="en") is None
    # The day is still free for the start that can be seen.
    assert service.today_of(ritual.id) is None


# ── typed ───────────────────────────────────────────────────────────────────────


async def test_the_phrase_typed_into_the_leads_conversation_starts_it(society) -> None:
    ritual = await service.create(**MORNING)
    started = await said.typed(society.chat, LEAD_SESSION, "Good morning")
    await settle()
    assert started == ritual.id
    assert society.chat.filed[0]["text"] == "Good morning"
    assert society.cards()[0]["via"] == "chat"


async def test_a_typed_message_elsewhere_or_with_a_file_is_an_ordinary_message(society) -> None:
    await service.create(**MORNING)
    assert await said.typed(society.chat, "a-coding-thread", "Good morning") == ""
    assert await said.typed(society.chat, LEAD_SESSION, "Good morning", has_attachments=True) == ""
    assert await said.typed(society.chat, LEAD_SESSION, "  ") == ""
    assert await said.typed(society.chat, LEAD_SESSION, "Good morning, and then?") == ""
    assert society.cards() == []


# ── what arrives late ───────────────────────────────────────────────────────────


async def test_what_arrives_after_a_spoken_start_is_said_in_the_call(scheduled, bus: Bus) -> None:
    ritual = await service.create(**MORNING)
    assert await said.spoken_answer("Good morning", language="en") == (
        "On it. The rest is on its way."
    )
    await settle(scheduled)
    tags = ("society", "agent:jarvis", "lead-ritual:" + ritual.id, "lead-quiet")
    await prepare.after_run(
        tags, answer="SPOKEN:\nGood morning. One thing today.\n\nWRITTEN:\n- One thing."
    )
    (event,) = bus.published
    assert isinstance(event, AnnouncementRequested)
    assert event.text == "Good morning. One thing today." and event.kind == "completion"
    assert event.source_layer == "rituals.service"
    # The written card is there either way.
    assert [card.get("late", False) for card in scheduled.cards()] == [False, True]


async def test_what_arrives_after_a_typed_start_is_only_written(scheduled, bus: Bus) -> None:
    ritual = await service.create(**MORNING)
    assert await said.typed(scheduled.chat, LEAD_SESSION, "Good morning") == ritual.id
    await settle(scheduled)
    tags = ("society", "agent:jarvis", "lead-ritual:" + ritual.id, "lead-quiet")
    await prepare.after_run(tags, answer="SPOKEN:\nGood morning.\n\nWRITTEN:\n- One thing.")
    assert bus.published == []
    assert len(scheduled.cards()) == 2


async def test_without_a_bus_a_late_result_is_only_written(scheduled, monkeypatch) -> None:
    monkeypatch.setattr(said, "_bus", None)
    ritual = await service.create(**MORNING)
    await said.spoken_answer("Good morning", language="en")
    await settle(scheduled)
    tags = ("society", "agent:jarvis", "lead-ritual:" + ritual.id, "lead-quiet")
    await prepare.after_run(tags, answer="SPOKEN:\nGood morning.\n\nWRITTEN:\n- One thing.")
    assert len(scheduled.cards()) == 2


def test_the_app_hands_over_its_bus_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(said, "_bus", None)
    wired = Bus()
    said.install(wired)
    assert said._bus is wired
