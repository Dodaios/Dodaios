"""Rituals: what may be written, when a sentence starts one, and what a start does."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from dodaios.rituals import prepare, service
from dodaios.rituals.models import (
    MAX_PHRASES,
    MAX_RITUALS,
    MAX_STEP_CHARS,
    MAX_STEPS,
    Ritual,
    RitualError,
)
from dodaios.rituals.store import get_store
from tests.unit.rituals.conftest import LEAD_SESSION, MONDAY_0830, MORNING, WAKE_PHRASE, settle


async def _code(awaitable) -> str:
    with pytest.raises(RitualError) as caught:
        await awaitable
    assert caught.value.message
    return caught.value.code


def _at(hour: int, minute: int = 0, *, days: int = 0) -> datetime:
    return MONDAY_0830.replace(hour=hour, minute=minute) + timedelta(days=days)


# ── models ──────────────────────────────────────────────────────────────────────


async def test_to_dict_has_exactly_the_contract_keys(society) -> None:
    ritual = await service.create(**MORNING)
    assert list(ritual.to_dict()) == [
        "id", "name", "phrases", "enabled", "window_from", "window_to", "weekdays",
        "once_per_day", "prepare_from", "steps", "task_id", "origin", "created_ms",
        "updated_ms",
    ]
    assert [list(step) for step in ritual.to_dict()["steps"]] == [["id", "when", "text"]] * 2


# ── writing one ─────────────────────────────────────────────────────────────────


async def test_a_new_ritual_is_on_for_every_day_and_once_a_day(society) -> None:
    ritual = await service.create(**MORNING)
    assert ritual.id.startswith("rit_") and len(ritual.id) == 12
    assert ritual.enabled and ritual.once_per_day and ritual.origin == "owner"
    assert (ritual.window_from, ritual.window_to, ritual.weekdays) == ("", "", ())
    assert [step.when for step in ritual.steps] == ["now", "ahead"]
    assert all(step.id.startswith("s_") for step in ritual.steps)
    assert service.get(ritual.id) == ritual
    assert service.list_rituals() == [ritual]


async def test_a_ritual_needs_a_name_a_phrase_and_a_step(society) -> None:
    assert await _code(service.create(**{**MORNING, "name": "  "})) == "invalid"
    assert await _code(service.create(**{**MORNING, "name": "n" * 61})) == "invalid"
    assert await _code(service.create(**{**MORNING, "phrases": []})) == "invalid"
    assert await _code(service.create(**{**MORNING, "phrases": [" "]})) == "invalid"
    assert await _code(service.create(**{**MORNING, "steps": []})) == "invalid"
    assert await _code(service.create(**MORNING, origin="nobody")) == "invalid"
    assert service.list_rituals() == []


async def test_a_phrase_must_be_short_and_more_than_an_address(society) -> None:
    too_many = [f"phrase number {index}" for index in range(MAX_PHRASES + 1)]
    assert await _code(service.create(**{**MORNING, "phrases": too_many})) == "invalid"
    long = "one two three four five six seven"
    assert await _code(service.create(**{**MORNING, "phrases": [long]})) == "invalid"
    # The wake phrase alone would start the ritual on everything said.
    assert await _code(service.create(**{**MORNING, "phrases": [WAKE_PHRASE]})) == "invalid"
    # The voice path answers this one itself, before any ritual is looked at.
    assert await _code(service.create(**{**MORNING, "phrases": ["Brief me"]})) == "invalid"


async def test_the_same_phrase_twice_is_kept_once(society) -> None:
    ritual = await service.create(
        **{**MORNING, "phrases": ["Good morning", "good  MORNING!", "Morning"]}
    )
    assert ritual.phrases == ("Good morning", "Morning")


async def test_steps_say_when_and_what(society) -> None:
    def with_steps(steps):
        return service.create(**{**MORNING, "steps": steps})

    assert await _code(with_steps([{"when": "later", "text": "x"}])) == "invalid"
    assert await _code(with_steps([{"when": "now", "text": "  "}])) == "invalid"
    assert await _code(with_steps([{"when": "now", "text": "x" * (MAX_STEP_CHARS + 1)}])) == (
        "invalid"
    )
    assert await _code(with_steps(["play music"])) == "invalid"
    many = [{"when": "now", "text": f"step {index}"} for index in range(MAX_STEPS + 1)]
    assert await _code(with_steps(many)) == "invalid"


async def test_a_time_window_needs_both_ends_and_real_times(society) -> None:
    def with_window(start, end):
        return service.create(**{**MORNING, "window_from": start, "window_to": end})

    assert await _code(with_window("08:00", "")) == "invalid"
    assert await _code(with_window("8 o'clock", "10:00")) == "invalid"
    assert await _code(with_window("24:00", "10:00")) == "invalid"
    assert await _code(with_window("08:00", "08:00")) == "invalid"
    ritual = await with_window("05:00", "11:00")
    assert (ritual.window_from, ritual.window_to) == ("05:00", "11:00")


async def test_weekdays_are_numbers_and_all_seven_means_every_day(society) -> None:
    assert await _code(service.create(**{**MORNING, "weekdays": [7]})) == "invalid"
    assert await _code(service.create(**{**MORNING, "weekdays": ["mon"]})) == "invalid"
    weekdays = await service.create(**{**MORNING, "weekdays": [4, 0, 0, 2]})
    assert weekdays.weekdays == (0, 2, 4)
    every = await service.create(
        **{**MORNING, "name": "Every day", "phrases": ["Hello day"], "weekdays": range(7)}
    )
    assert every.weekdays == ()


async def test_a_name_and_a_phrase_each_belong_to_one_ritual(society) -> None:
    await service.create(**MORNING)
    same_name = {**MORNING, "name": "good MORNING", "phrases": ["Rise and shine"]}
    assert await _code(service.create(**same_name)) == "conflict"
    same_phrase = {**MORNING, "name": "Another", "phrases": ["Start the day", "good morning!"]}
    assert await _code(service.create(**same_phrase)) == "conflict"
    assert len(service.list_rituals()) == 1


async def test_at_most_twenty_rituals(society) -> None:
    for index in range(MAX_RITUALS):
        await service.create(
            **{**MORNING, "name": f"Ritual {index}", "phrases": [f"start number {index}"]}
        )
    one_more = {**MORNING, "name": "One more", "phrases": ["start one more"]}
    assert await _code(service.create(**one_more)) == "limit"


# ── changing and removing ───────────────────────────────────────────────────────


async def test_only_what_is_given_changes(society) -> None:
    ritual = await service.create(**MORNING)
    changed = await service.update(ritual.id, enabled=False, window_from="05:00", window_to="11:00")
    assert changed.enabled is False and changed.window_from == "05:00"
    assert changed.steps == ritual.steps and changed.phrases == ritual.phrases
    assert changed.created_ms == ritual.created_ms and changed.updated_ms >= ritual.updated_ms
    assert await _code(service.update(ritual.id, colour="blue")) == "invalid"
    assert await _code(service.update(ritual.id, name="")) == "invalid"
    assert await _code(service.update("rit_missing", enabled=True)) == "not_found"


async def test_a_reworded_step_keeps_its_id_and_a_new_one_gets_one(society) -> None:
    ritual = await service.create(**MORNING)
    first, second = ritual.steps
    changed = await service.update(
        ritual.id,
        steps=[
            {"id": first.id, "when": "now", "text": "Play something calm."},
            {"when": "ahead", "text": "My open pull requests."},
            {"id": second.id, "when": "ahead", "text": second.text},
        ],
    )
    assert [step.id for step in changed.steps][0] == first.id
    assert changed.steps[0].text == "Play something calm."
    assert changed.steps[2] == second
    assert changed.steps[1].id not in {first.id, second.id}


async def test_a_change_may_not_take_another_rituals_phrase(society) -> None:
    await service.create(**MORNING)
    evening = await service.create(
        name="Evening", phrases=["Good evening"], steps=[{"when": "now", "text": "Dim the lights."}]
    )
    assert await _code(service.update(evening.id, phrases=["Good morning"])) == "conflict"
    # Its own phrase is no clash.
    kept = await service.update(evening.id, phrases=["Good evening", "Evening time"])
    assert kept.phrases == ("Good evening", "Evening time")


async def test_removing_a_ritual_forgets_its_days(society) -> None:
    ritual = await service.create(**MORNING)
    await service.fire(ritual.id, via="button", force=True, now=MONDAY_0830)
    await service.remove(ritual.id)
    assert service.get(ritual.id) is None
    assert get_store().day(ritual.id, "2026-03-02") is None
    assert await _code(service.remove(ritual.id)) == "not_found"


# ── does a sentence start it ────────────────────────────────────────────────────


async def test_a_sentence_that_names_no_ritual_matches_nothing(society) -> None:
    await service.create(**MORNING)
    assert service.find_match("What is the weather like?", now=MONDAY_0830) is None
    assert service.find_match("", now=MONDAY_0830) is None
    assert service.find_match("Good morning, what is on today?", now=MONDAY_0830) is None


async def test_the_phrase_starts_it_with_the_address_around_it(society) -> None:
    ritual = await service.create(**MORNING)
    found = service.find_match("Hey Nova, good morning!", now=MONDAY_0830)
    assert found is not None and found.ritual == ritual
    assert found.phrase == "Good morning" and found.fires and found.blocked == ""


async def test_the_configured_wake_phrase_is_read_unless_one_is_given(society) -> None:
    await service.create(**MORNING)
    society.wake_phrase = "Hey Athena"
    assert service.find_match("Athena, good morning", now=MONDAY_0830) is not None
    assert service.find_match("Nova, good morning", now=MONDAY_0830) is None
    assert service.find_match("Nova, good morning", wake_phrase="Nova", now=MONDAY_0830)


async def test_outside_its_window_the_phrase_is_only_a_greeting(society) -> None:
    ritual = await service.create(**{**MORNING, "window_from": "05:00", "window_to": "11:00"})
    assert service.find_match("Good morning", now=_at(5, 0)).fires
    assert service.find_match("Good morning", now=_at(11, 0)).fires
    late = service.find_match("Good morning", now=_at(11, 1))
    assert late.ritual == ritual and not late.fires and late.blocked == "time"
    assert service.find_match("Good morning", now=_at(4, 59)).blocked == "time"


async def test_a_window_may_run_over_midnight(society) -> None:
    await service.create(
        name="Night", phrases=["Good night"], window_from="22:00", window_to="02:00",
        steps=[{"when": "now", "text": "Stop the music."}],
    )
    assert service.find_match("Good night", now=_at(23, 30)).fires
    assert service.find_match("Good night", now=_at(1, 15)).fires
    assert service.find_match("Good night", now=_at(12, 0)).blocked == "time"


async def test_weekdays_and_the_switch_hold_it_back(society) -> None:
    ritual = await service.create(**{**MORNING, "weekdays": [0, 1, 2, 3, 4]})
    assert service.find_match("Good morning", now=MONDAY_0830).fires
    saturday = _at(8, 30, days=5)
    assert service.find_match("Good morning", now=saturday).blocked == "day"
    await service.update(ritual.id, enabled=False)
    assert service.find_match("Good morning", now=MONDAY_0830).blocked == "off"


async def test_the_second_time_on_a_day_is_a_greeting_unless_it_may_repeat(society) -> None:
    ritual = await service.create(**MORNING)
    await service.fire(ritual.id, via="voice", now=MONDAY_0830)
    assert service.find_match("Good morning", now=_at(9, 0)).blocked == "done_today"
    # The next day it starts again.
    assert service.find_match("Good morning", now=_at(8, 30, days=1)).fires
    await service.update(ritual.id, once_per_day=False)
    assert service.find_match("Good morning", now=_at(9, 0)).fires


# ── a start ─────────────────────────────────────────────────────────────────────


async def test_a_start_posts_the_card_and_runs_the_steps_for_this_moment(society) -> None:
    ritual = await service.create(**MORNING)
    result = await service.fire(ritual.id, via="voice", now=MONDAY_0830)
    await settle()

    assert result["ritual"]["id"] == ritual.id
    assert result["today"]["fired_via"] == "voice" and result["today"]["day"] == "2026-03-02"
    # Nothing was gathered for the news yet: the card says more follows.
    assert result["pending"] is True
    (card, late) = society.notices
    assert card["pending"] is True
    # No scheduler is behind this world, so nothing can be gathered: the start
    # hears that in a second card instead of waiting for good.
    assert late["late"] is True and late["status"] == "failed"
    assert late["text"] == "The task scheduler is not running."
    assert card["kind"] == "society_result" and card["status"] == "done"
    assert card["source"] == "ritual" and card["via"] == "voice"
    assert (card["ritual_id"], card["ritual_title"]) == (ritual.id, "Good morning")
    assert card["agent_name"] == "Nova"
    # They started it where they are: the card is not sent to their phone as well.
    assert card["push"] is False
    # Nothing was gathered yet, and the steps for the moment answer for themselves.
    assert card["text"] == ""

    (turn,) = society.chat.sent
    assert turn["session_id"] == LEAD_SESSION
    # The person asked for it, but typed nothing: the timeline shows only the answer.
    assert turn["background_result"] is True and turn["display_text"] == "Good morning"
    assert "1. Play my favourite music." in turn["text"]
    assert "AI news" not in turn["text"]


async def test_what_was_gathered_ahead_leads_the_card(society) -> None:
    ritual = await service.create(**MORNING)
    get_store().patch_day(
        ritual.id, "2026-03-02", prep_state="ready", prepared_ms=1,
        steps_hash=prepare.steps_hash(ritual), written="## News\n- A new model came out.",
    )
    result = await service.fire(ritual.id, via="chat", now=MONDAY_0830)
    await settle()
    (card,) = society.notices
    # The card carries what was gathered, not the list of steps for the moment.
    assert card["text"] == "## News\n- A new model came out."
    # It was ready: handed over with the start, nothing follows.
    assert card["pending"] is False and result["pending"] is False
    assert result["today"]["delivered_ms"] is not None


async def test_what_was_gathered_for_other_steps_is_not_handed_over(society) -> None:
    ritual = await service.create(**MORNING)
    get_store().patch_day(
        ritual.id, "2026-03-02", prep_state="ready", prepared_ms=1,
        steps_hash="another-set-of-steps", written="## Yesterday's question",
    )
    result = await service.fire(ritual.id, via="chat", now=MONDAY_0830)
    await settle()
    assert result["pending"] is True
    assert society.notices[0]["text"] == ""


async def test_a_ritual_without_steps_for_this_moment_starts_no_turn(society) -> None:
    ritual = await service.create(
        name="Briefing", phrases=["Catch me up"],
        steps=[{"when": "ahead", "text": "My open pull requests."}],
    )
    await service.fire(ritual.id, via="chat", now=MONDAY_0830)
    await settle()
    assert society.chat.sent == []
    assert society.notices[0]["text"] == "" and society.notices[0]["pending"] is True


async def test_the_steps_wait_for_a_busy_conversation(society) -> None:
    ritual = await service.create(**MORNING)
    society.chat.running = True
    await service.fire(ritual.id, via="button", force=True, now=MONDAY_0830)
    assert society.chat.sent == []
    society.chat.running = False
    # Another turn takes the seat once more before the steps get it.
    society.chat.refusals = 1
    await settle()
    assert len(society.chat.sent) == 1


async def test_the_steps_give_up_on_a_conversation_that_stays_busy(
    society, monkeypatch: pytest.MonkeyPatch
) -> None:
    ritual = await service.create(**MORNING)
    monkeypatch.setattr(service, "SEAT_WAIT_S", 0.05)
    society.chat.running = True
    await service.fire(ritual.id, via="button", force=True, now=MONDAY_0830)
    await settle()
    assert society.chat.sent == []
    # The start itself counted.
    assert service.today_of(ritual.id, now=MONDAY_0830).fired_via == "button"
    # The card said it started; the person also hears which steps did not run.
    (dropped,) = [card for card in society.cards() if card.get("steps_not_run")]
    assert dropped["late"] is True and dropped["status"] == "failed"
    assert dropped["text"] == "1. Play my favourite music."


async def test_a_phrase_does_not_start_what_its_conditions_hold_back(society) -> None:
    ritual = await service.create(**{**MORNING, "window_from": "05:00", "window_to": "11:00"})
    assert await _code(service.fire(ritual.id, via="voice", now=_at(13, 0))) == "state"
    await service.fire(ritual.id, via="voice", now=MONDAY_0830)
    assert await _code(service.fire(ritual.id, via="chat", now=_at(9, 0))) == "state"
    await settle()
    assert len(society.start_cards()) == 1 and len(society.chat.sent) == 1
    assert await _code(service.fire(ritual.id, via="telepathy", now=MONDAY_0830)) == "invalid"
    assert await _code(service.fire("rit_missing", via="voice", now=MONDAY_0830)) == "not_found"


async def test_a_click_does_not_use_up_the_phrase(society) -> None:
    """Trying a ritual with "Run now" in the morning must not silence its phrase."""
    ritual = await service.create(**MORNING)
    await service.fire(ritual.id, via="button", force=True, now=_at(7, 0))
    assert service.find_match("Good morning", now=MONDAY_0830).fires
    await service.fire(ritual.id, via="voice", now=MONDAY_0830)
    assert service.find_match("Good morning", now=_at(9, 0)).blocked == "done_today"
    # And a click after the phrase starts it again without freeing the phrase.
    await service.fire(ritual.id, via="button", force=True, now=_at(9, 30))
    assert service.find_match("Good morning", now=_at(9, 45)).blocked == "done_today"
    await settle()
    assert [card["via"] for card in society.start_cards()] == ["button", "voice", "button"]


async def test_a_click_starts_it_whatever_the_clock_says_and_again(society) -> None:
    ritual = await service.create(
        **{**MORNING, "window_from": "05:00", "window_to": "11:00", "enabled": False}
    )
    await service.fire(ritual.id, via="button", force=True, now=_at(13, 0))
    await service.fire(ritual.id, via="button", force=True, now=_at(13, 5))
    await settle()
    assert len(society.start_cards()) == 2 and len(society.chat.sent) == 2


async def test_two_starts_in_the_same_moment_do_not_both_go_through(society) -> None:
    ritual = await service.create(**MORNING)
    # The claim is the store's: the second one finds the day taken.
    assert get_store().claim_fire(ritual.id, "2026-03-02", 1, "voice") is True
    assert await _code(service.fire(ritual.id, via="chat", now=MONDAY_0830)) == "state"
    assert society.notices == []


async def test_a_card_that_cannot_be_posted_does_not_undo_the_start(society) -> None:
    ritual = await service.create(**MORNING)

    async def broken(agent, payload) -> None:
        raise RuntimeError("chat is down")

    society.post_chat_notice = broken
    await service.fire(ritual.id, via="voice", now=MONDAY_0830)
    await settle()
    assert service.today_of(ritual.id, now=MONDAY_0830).fired_ms is not None
    assert len(society.chat.sent) == 1


async def test_without_the_assistant_a_start_is_refused_and_claims_nothing(
    society, monkeypatch: pytest.MonkeyPatch
) -> None:
    ritual = await service.create(**MORNING)
    monkeypatch.setattr(service, "_runtime", lambda: None)
    # No wake phrase to read: the fixed address words still work.
    assert service.find_match("Hey, good morning", now=MONDAY_0830).fires
    assert await _code(service.fire(ritual.id, via="voice", now=MONDAY_0830)) == "unavailable"
    # The day is still free for the start that can be seen.
    assert service.today_of(ritual.id, now=MONDAY_0830) is None
    assert society.notices == [] and society.chat.sent == []


# ── the overview ────────────────────────────────────────────────────────────────


async def test_the_overview_lists_every_ritual_with_its_day(society) -> None:
    morning = await service.create(**MORNING)
    evening = await service.create(
        name="Evening", phrases=["Good evening"], steps=[{"when": "now", "text": "Dim the lights."}]
    )
    await service.fire(morning.id, via="voice", now=MONDAY_0830)
    view = service.overview(now=MONDAY_0830)
    assert view["available"] is True
    assert [row["id"] for row in view["rituals"]] == [morning.id, evening.id]
    assert view["rituals"][0]["today"]["fired_via"] == "voice"
    assert view["rituals"][1]["today"] is None
    assert view["limits"]["max_rituals"] == MAX_RITUALS
    assert view["limits"]["when"] == ["now", "ahead"]
    # The next day nothing has happened yet.
    tomorrow = service.overview(now=_at(8, 30, days=1))
    assert tomorrow["rituals"][0]["today"] is None


async def test_the_prompt_for_this_moments_steps_numbers_them(society) -> None:
    ritual: Ritual = await service.create(
        name="Focus", phrases=["Focus time"],
        steps=[
            {"when": "now", "text": "Pause the music."},
            {"when": "now", "text": "Open my notes."},
        ],
    )
    prompt = service.now_prompt(ritual, ritual.steps_at("now"))
    assert '"Focus"' in prompt
    assert prompt.endswith("1. Pause the music.\n2. Open my notes.]")


async def test_a_ritual_held_back_does_not_hide_another_ones_exact_phrase(society) -> None:
    await service.create(**{**MORNING, "window_from": "06:00", "window_to": "07:00"})
    other = await service.create(
        name="Other", phrases=["Good morning Nova"], steps=[{"when": "now", "text": "x"}]
    )
    found = service.find_match("Good morning Nova", wake_phrase=WAKE_PHRASE, now=MONDAY_0830)
    assert found is not None and found.fires
    assert found.ritual.id == other.id and found.phrase == "Good morning Nova"
    # Both start now: the longer phrase is the one that was said.
    early = MONDAY_0830.replace(hour=6, minute=30)
    found = service.find_match("Good morning Nova", wake_phrase=WAKE_PHRASE, now=early)
    assert found is not None and found.ritual.id == other.id
    # "Good morning" alone is still the first one's, held back by its window.
    found = service.find_match("Good morning", wake_phrase=WAKE_PHRASE, now=MONDAY_0830)
    assert found is not None and found.ritual.name == "Good morning" and found.blocked == "time"


async def test_a_switch_keeps_working_after_the_wake_word_changed(society) -> None:
    ritual = await service.create(**{**MORNING, "phrases": ["Good morning", "Morning Max"]})
    # The wake word is now "Hey Max": "Morning Max" alone would no longer be accepted
    # as new, but the ritual already has it, so a switch still saves.
    society.wake_phrase = "Hey Morning Max"
    switched = await service.update(ritual.id, enabled=False)
    assert switched.enabled is False and switched.phrases == ("Good morning", "Morning Max")
