"""Real app events pay XP exactly once, within every limit, and announce it."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from dodaios.core.bus import EventBus
from dodaios.core.events import (
    JarvisChatTurnFinished,
    MissionCompleted,
    ProgressionAwarded,
    SocietyMessageSent,
    SocietyQuestChanged,
    SocietyResultPosted,
    VoiceTurnCompleted,
)
from dodaios.progression.rules import RULES_BY_SOURCE
from dodaios.progression.service import ProgressionService, UnknownAction
from dodaios.progression.store import ProgressionStore


class Clock:
    """A settable millisecond clock, so cooldowns and days are deterministic."""

    def __init__(self, start_ms: int = 1_790_000_000_000) -> None:
        self.now = start_ms

    def __call__(self) -> int:
        return self.now


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
async def setup(tmp_path: Path, clock: Clock):
    bus = EventBus()
    seen: list[ProgressionAwarded] = []

    async def record(event: ProgressionAwarded) -> None:
        seen.append(event)

    bus.subscribe(ProgressionAwarded, record)
    pet = {"id": "ember"}
    service = ProgressionService(
        tmp_path / "progression.db", bus=bus, pet_id=lambda: pet["id"], clock=clock
    )
    service.attach()
    try:
        yield service, bus, seen, pet
    finally:
        service.close()


def _levels(service: ProgressionService) -> dict[str, tuple[int, int]]:
    return {row["subject_id"]: (row["xp"], row["level"]) for row in service.snapshot()}


async def test_a_finished_jarvis_chat_turn_pays_the_person_and_the_pet(setup):
    service, bus, seen, _ = setup
    await bus.publish(JarvisChatTurnFinished(session_id="s1", turn_id="t1", status="done"))
    await service.drain()
    assert _levels(service) == {"person": (5, 1), "pet:ember": (4, 1)}
    assert {(e.subject_id, e.xp_source, e.xp) for e in seen} == {
        ("person", "chat_turn", 5),
        ("pet:ember", "jarvis_answered", 4),
    }


async def test_the_same_turn_twice_pays_once_and_an_error_turn_never(setup):
    service, bus, _, _ = setup
    for _ in range(2):
        await bus.publish(JarvisChatTurnFinished(session_id="s1", turn_id="t1"))
    await bus.publish(JarvisChatTurnFinished(session_id="s1", turn_id="t2", status="error"))
    await service.drain()
    assert _levels(service)["person"] == (5, 1)


async def test_voice_turns_pay_too(setup):
    service, bus, _, _ = setup
    await bus.publish(VoiceTurnCompleted(session_id="v", turn_id="1"))
    await bus.publish(VoiceTurnCompleted(session_id="v", turn_id="2"))
    await service.drain()
    assert _levels(service)["person"] == (10, 1)


async def test_the_daily_cap_stops_paying_and_a_new_day_pays_again(setup, clock):
    service, bus, _, _ = setup
    cap = RULES_BY_SOURCE["chat_turn"].daily_cap
    for turn in range(cap // 5 + 5):
        await bus.publish(JarvisChatTurnFinished(session_id="s", turn_id=str(turn)))
    await service.drain()
    assert _levels(service)["person"][0] == cap
    clock.now += 24 * 3600 * 1000
    await bus.publish(JarvisChatTurnFinished(session_id="s", turn_id="tomorrow"))
    await service.drain()
    assert _levels(service)["person"][0] == cap + 5


async def test_agents_level_from_finished_work_and_quests(setup):
    service, bus, seen, _ = setup
    await bus.publish(SocietyResultPosted(event_id="e1", agent_id="scout", status="done"))
    await bus.publish(SocietyResultPosted(event_id="e2", agent_id="scout", status="blocked"))
    await bus.publish(SocietyQuestChanged(quest_id="q1", state="open", previous=""))
    await bus.publish(
        SocietyQuestChanged(quest_id="q1", state="done", previous="running", agent_id="scout")
    )
    await service.drain()
    levels = _levels(service)
    assert levels["agent:scout"] == (40 + 8 + 60, 3)
    assert levels["person"] == (15 + 20, 1)
    up = [e for e in seen if e.subject_id == "agent:scout" and e.level > e.previous_level]
    assert up and up[-1].level == 3
    assert up[-1].unlocked == ()
    assert up[-1].title == "deckhand"


async def test_the_lead_is_the_pet_never_an_agent(setup):
    service, bus, _, _ = setup
    await bus.publish(SocietyResultPosted(event_id="e1", agent_id="jarvis", status="done"))
    await bus.publish(
        SocietyMessageSent(event_id="m1", msg_type="ASSIGN", from_agent="jarvis", to_agent="scout")
    )
    await bus.publish(
        SocietyMessageSent(event_id="m2", msg_type="ANSWER", from_agent="scout", to_agent="jarvis")
    )
    await service.drain()
    levels = _levels(service)
    assert "agent:jarvis" not in levels
    assert levels["pet:ember"] == (10, 1)
    assert levels["agent:scout"] == (5, 1)


async def test_the_active_pet_earns_and_each_pet_keeps_its_own_level(setup):
    service, bus, _, pet = setup
    await bus.publish(JarvisChatTurnFinished(session_id="s", turn_id="a"))
    pet["id"] = "miso"
    await bus.publish(JarvisChatTurnFinished(session_id="s", turn_id="b"))
    pet["id"] = "none"
    await bus.publish(JarvisChatTurnFinished(session_id="s", turn_id="c"))
    await service.drain()
    levels = _levels(service)
    assert levels["pet:ember"] == (4, 1)
    assert levels["pet:miso"] == (4, 1)
    assert levels["pet:gigi"] == (4, 1)


async def test_only_approved_missions_pay(setup):
    service, bus, _, _ = setup
    await bus.publish(MissionCompleted(mission_id="m1", status="failed"))
    await bus.publish(MissionCompleted(mission_id="m2", status="approved"))
    await service.drain()
    assert _levels(service)["person"] == (30, 1)


async def test_a_hired_agent_pays_the_person_once(setup):
    service, _, _, _ = setup
    await service.note_agent_hired("scout")
    await service.note_agent_hired("scout")
    await service.note_agent_hired("jarvis")
    await service.drain()
    assert _levels(service)["person"] == (50, 2)


async def test_world_actions_are_metered_on_the_server(setup, clock):
    service, _, _, _ = setup
    assert await service.report_action("simulator_round", ref="neon-snake") is not None
    assert await service.report_action("simulator_round") is None  # cooldown
    clock.now += 46_000
    assert await service.report_action("simulator_round") is not None
    assert await service.report_action("daily_visit", ref="anything") is not None
    assert await service.report_action("daily_visit") is None  # once per day
    for deck in ("bridge", "ops", "engineering", "hangar"):
        assert await service.report_action("deck_discovered", ref=deck) is not None, deck
        assert await service.report_action("deck_discovered", ref=deck) is None, deck
    walked = await service.report_action("walk_together")
    assert walked is not None and walked.subject_id == "pet:ember"


async def test_a_new_day_pays_a_new_visit(setup, clock):
    service, _, _, _ = setup
    first = await service.report_action("daily_visit")
    clock.now += 24 * 3600 * 1000
    second = await service.report_action("daily_visit")
    assert first is not None and second is not None and first.ref != second.ref


async def test_an_inspection_pays_once_per_deck_and_day_within_its_cap(setup, clock):
    service, _, _, _ = setup
    bridge = await service.report_action("inspection", ref="bridge")
    assert bridge is not None and bridge.xp == 15 and bridge.ref.startswith("bridge:")
    assert await service.report_action("inspection", ref="bridge") is None  # once a day
    assert await service.report_action("inspection", ref="ops") is not None
    # Two decks spend the day's cap.
    assert await service.report_action("inspection", ref="hangar") is None
    clock.now += 24 * 3600 * 1000
    assert await service.report_action("inspection", ref="bridge") is not None


async def test_a_team_briefing_keeps_its_team_and_repeats_after_its_cooldown(setup, clock):
    service, _, _, _ = setup
    first = await service.report_action("team_briefing", ref="team-research")
    assert first is not None and first.ref.startswith("team-research@")
    assert await service.report_action("team_briefing", ref="team-research") is None
    clock.now += 601_000
    assert await service.report_action("team_briefing") is not None


async def test_the_daily_caps_of_world_actions_hold(setup, clock):
    service, _, _, _ = setup
    paid = 0
    for _ in range(12):
        award = await service.report_action("team_briefing")
        paid += award.xp if award else 0
        clock.now += 601_000
    assert paid == RULES_BY_SOURCE["team_briefing"].daily_cap


async def test_unknown_or_server_only_actions_are_refused(setup):
    service, _, _, _ = setup
    refused = (
        ("chat_turn", ""), ("cheat", ""), ("deck_discovered", "roof"), ("deck_discovered", ""),
        ("inspection", ""), ("inspection", "holodeck"),
        # The starship's and the office tower's actions are gone.
        ("deck_discovered", "holodeck"), ("deck_discovered", "honors"),
        ("holodeck_round", ""), ("warp_jump", "home"),
        ("floor_discovered", "agents"), ("dog_petted", ""), ("arcade_round", ""),
    )
    for action, ref in refused:
        with pytest.raises(UnknownAction):
            await service.report_action(action, ref=ref)


async def test_old_ledger_rows_with_retired_sources_still_read(setup):
    service, _, _, _ = setup
    await service.award("person", "chat_turn", ref="x")
    conn = service.store._connection()
    for source, xp, ref in (("dog_petted", 3, ""), ("holodeck_round", 8, ""),
                            ("warp_jump", 5, "home@1"), ("deck_discovered", 20, "honors")):
        conn.execute(
            "INSERT INTO progression_awards"
            " (subject_id, source, xp, level_before, level_after, ref, ts_ms)"
            " VALUES ('person', ?, ?, 1, 1, ?, 1)",
            (source, xp, ref),
        )
        conn.execute(
            "UPDATE progression_subjects SET xp = xp + ? WHERE subject_id = 'person'", (xp,)
        )
    assert {row["source"] for row in service.store.recent()} == {
        "chat_turn", "dog_petted", "holodeck_round", "warp_jump", "deck_discovered",
    }
    row = service.snapshot()[0]
    assert row["xp"] == 5 + 3 + 8 + 5 + 20
    assert (row["level"], row["title"]) == (2, "recruit")
    # The new hangar deck still pays, beside an old deck's row.
    assert await service.report_action("deck_discovered", ref="hangar") is not None


async def test_an_old_subject_keeps_its_xp_and_wears_the_new_rank(setup):
    service, _, _, _ = setup
    conn = service.store._connection()
    # A row written by the starship build: 1745 XP is level 11, an old "warrant officer".
    conn.execute(
        "INSERT INTO progression_subjects (subject_id, kind, xp, level, updated_ms)"
        " VALUES ('agent:scout', 'agent', 1745, 11, 1)"
    )
    row = next(r for r in service.snapshot() if r["subject_id"] == "agent:scout")
    assert (row["level"], row["title"]) == (11, "ensign")


def test_the_store_refuses_a_rule_for_the_wrong_kind(tmp_path: Path):
    store = ProgressionStore(tmp_path / "p.db")
    with pytest.raises(ValueError):
        store.award("agent:scout", RULES_BY_SOURCE["chat_turn"])
    store.close()


def test_recent_awards_come_oldest_first_after_a_sequence(tmp_path: Path):
    store = ProgressionStore(tmp_path / "p.db")
    rule = RULES_BY_SOURCE["task_done"]
    first = store.award("agent:a", rule, ref="1")
    store.award("agent:a", rule, ref="2")
    assert first is not None
    rows = store.recent(after_seq=first.seq)
    assert [row["ref"] for row in rows] == ["2"]
    assert rows[0]["kind"] == "agent"
    assert store.latest_seq() == first.seq + 1
    store.close()


async def test_a_broken_bus_never_loses_the_award(tmp_path: Path, clock: Clock):
    class BrokenBus:
        def subscribe(self, *_: Any) -> None:
            return None

        async def publish(self, _: Any) -> None:
            raise RuntimeError("bus down")

    service = ProgressionService(tmp_path / "p.db", bus=BrokenBus(), clock=clock)
    award = await service.award("person", "agent_hired", ref="x")
    assert award is not None and award.xp == 50
    service.close()
