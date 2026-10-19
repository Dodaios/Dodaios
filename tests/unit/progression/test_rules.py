"""The ship's rulebook is consistent and well paced."""

from __future__ import annotations

from dodaios.progression.rules import (
    DESTINATION_IDS,
    LOOK_UNLOCKS,
    MAX_LEVEL,
    RANK_TIERS,
    RANKS,
    REWARDS,
    RULES,
    RULES_BY_SOURCE,
    SLOTS,
    SUBJECT_KINDS,
    TITLES,
    WORLD_ACTIONS,
    level_for_xp,
    looks_between,
    progress_for_xp,
    rewards_between,
    subject_kind,
    title_for,
    total_xp_for_level,
    unlocked_rewards,
    xp_to_next,
)


def test_the_first_level_comes_after_a_handful_of_actions():
    assert xp_to_next(1) == 40
    assert level_for_xp(0) == 1
    assert level_for_xp(39) == 1
    assert level_for_xp(40) == 2


def test_every_step_costs_more_than_the_one_before_and_reads_in_fives():
    steps = [xp_to_next(level) for level in range(1, MAX_LEVEL)]
    assert all(step % 5 == 0 for step in steps)
    assert all(later > earlier for earlier, later in zip(steps, steps[1:], strict=False))
    assert xp_to_next(MAX_LEVEL) == 0


def test_the_curve_is_unchanged_so_existing_xp_keeps_its_meaning():
    assert [xp_to_next(level) for level in (1, 2, 10, 49)] == [40, 65, 320, 1805]
    assert total_xp_for_level(MAX_LEVEL) == 43_230


def test_pacing_matches_the_design_targets():
    # ~200 XP on an ordinary day: level 10 inside two weeks, the cap after months.
    assert total_xp_for_level(10) < 200 * 14
    assert 200 * 120 < total_xp_for_level(MAX_LEVEL) < 200 * 365


def test_level_and_progress_round_trip_at_every_boundary():
    for level in range(1, MAX_LEVEL + 1):
        start = total_xp_for_level(level)
        assert level_for_xp(start) == level
        progress = progress_for_xp(start)
        assert (progress.level, progress.into_level) == (level, 0)
        if level > 1:
            assert level_for_xp(start - 1) == level - 1
    capped = progress_for_xp(total_xp_for_level(MAX_LEVEL) + 10_000)
    assert capped.level == MAX_LEVEL and capped.for_next == 0


def test_rules_have_unique_sources_and_pay_a_known_kind():
    sources = [rule.source for rule in RULES]
    assert len(sources) == len(set(sources))
    for rule in RULES:
        assert rule.kind in SUBJECT_KINDS
        assert rule.xp > 0
        assert rule.trigger in ("server", "world")
        # A world action is reported by the client: it must be metered.
        if rule.trigger == "world":
            assert rule.cooldown_s > 0 or rule.once_per_ref, rule.source


def test_the_world_actions_are_the_ships():
    assert WORLD_ACTIONS == {
        "daily_visit", "deck_discovered", "holodeck_round", "holodeck_record",
        "team_briefing", "warp_jump", "walk_together",
    }
    limits = {
        source: (r.xp, r.cooldown_s, r.daily_cap, r.once_per_ref, r.kind)
        for source, r in RULES_BY_SOURCE.items() if source in WORLD_ACTIONS
    }
    assert limits == {
        "daily_visit": (25, 0, 0, True, "person"),
        "deck_discovered": (20, 0, 0, True, "person"),
        "holodeck_round": (8, 45, 80, False, "person"),
        "holodeck_record": (15, 45, 60, False, "person"),
        "team_briefing": (10, 600, 40, False, "person"),
        "warp_jump": (5, 600, 30, False, "person"),
        "walk_together": (3, 20, 60, False, "pet"),
    }
    # The office tower's actions are gone (old ledger rows keep their source strings).
    for gone in ("floor_discovered", "dog_petted", "dog_treat", "arcade_round", "team_meeting"):
        assert gone not in RULES_BY_SOURCE


def test_the_server_rules_keep_their_amounts():
    amounts = {r.source: r.xp for r in RULES if r.trigger == "server"}
    assert amounts == {
        "chat_turn": 5, "voice_turn": 5, "quest_posted": 15, "quest_completed": 20,
        "agent_hired": 50, "mission_completed": 30, "task_done": 40, "task_blocked": 8,
        "quest_done": 60, "answered_teammate": 5, "jarvis_answered": 4, "delegated": 10,
    }


def test_the_rank_ladder_climbs_from_cadet_to_admiral():
    levels = [level for level, _, _ in RANKS]
    assert levels[0] == 1 and levels[-1] == MAX_LEVEL
    assert levels == sorted(set(levels))
    assert len(RANKS) == 16
    assert RANKS[0][1] == "cadet" and RANKS[-1][1] == "admiral"
    # Tiers come in order: enlisted, warrant, officer, flag; none is skipped.
    tiers = [tier for _, _, tier in RANKS]
    order = [RANK_TIERS.index(tier) for tier in tiers]
    assert order == sorted(order) and set(tiers) == set(RANK_TIERS)
    ids = [rank for _, rank, _ in RANKS]
    assert len(ids) == len(set(ids))
    for kind in SUBJECT_KINDS:
        assert [rank for _, rank in TITLES[kind]] == ids


def test_titles_follow_the_ladder():
    assert title_for("person", 1) == "cadet"
    assert title_for("person", 2) == "cadet"
    assert title_for("agent", 3) == "crewman"
    assert title_for("person", 15) == "warrant_officer"
    assert title_for("pet", 34) == "captain"
    assert title_for("pet", MAX_LEVEL) == "admiral"


def test_rewards_are_unique_named_by_their_slot_and_within_the_cap():
    ids = [reward.reward_id for reward in REWARDS]
    assert len(ids) == len(set(ids))
    for reward in REWARDS:
        assert reward.slot in SLOTS
        assert reward.reward_id.startswith(reward.slot + "_")
        for kind in SUBJECT_KINDS:
            level = reward.level_for(kind)
            assert level is None or 2 <= level <= MAX_LEVEL


def test_rewards_per_kind():
    def by_slot(kind, slot):
        return [
            (r.reward_id, r.level_for(kind))
            for r in REWARDS if r.slot == slot and r.level_for(kind)
        ]

    assert by_slot("person", "suit") == [
        ("suit_field_armor", 6), ("suit_command_coat", 16),
        ("suit_dress_whites", 26), ("suit_admiral_coat", 42),
    ]
    assert [lvl for _, lvl in by_slot("person", "destination")] == [5, 10, 15, 20, 25, 30, 40]
    assert by_slot("person", "decoration") == [
        ("decoration_service_ribbon", 8), ("decoration_commendation", 18),
        ("decoration_star_medal", 36), ("decoration_legion_of_merit", 47),
    ]
    assert [lvl for _, lvl in by_slot("agent", "decoration")] == [3, 16, 32, 44]
    # Androids earn decorations only; the pet wears its rank only.
    assert by_slot("agent", "suit") == [] and by_slot("agent", "destination") == []
    assert {r.slot for r in unlocked_rewards("person", MAX_LEVEL)} == set(SLOTS)
    assert {r.slot for r in unlocked_rewards("agent", MAX_LEVEL)} == {"decoration"}
    assert unlocked_rewards("pet", MAX_LEVEL) == []


def test_every_destination_reward_is_a_helm_destination():
    assert DESTINATION_IDS[0] == "home"
    assert DESTINATION_IDS[1:] == tuple(
        r.reward_id.removeprefix("destination_") for r in REWARDS if r.slot == "destination"
    )


def test_rewards_between_names_only_what_the_climb_crossed():
    assert rewards_between("person", 1, 4) == []
    assert [r.reward_id for r in rewards_between("person", 4, 5)] == ["destination_gas_giant"]
    at_ten = {r.reward_id for r in rewards_between("person", 5, 10)}
    assert at_ten == {"suit_field_armor", "decoration_service_ribbon", "destination_crimson_nebula"}
    assert rewards_between("person", 10, 10) == []
    assert [r.reward_id for r in rewards_between("agent", 1, 3)] == ["decoration_service_ribbon"]


def test_subject_ids_name_their_kind():
    assert subject_kind("person") == "person"
    assert subject_kind("agent:scout") == "agent"
    assert subject_kind("pet:ember") == "pet"
    assert subject_kind("pet:") is None
    assert subject_kind("robot:x") is None


def test_every_agent_look_is_open_from_the_start():
    assert LOOK_UNLOCKS and all(level == 1 for level in LOOK_UNLOCKS.values())
    assert looks_between(1, 50) == []
