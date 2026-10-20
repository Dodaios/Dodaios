"""The ship's rulebook is consistent and well paced."""

from __future__ import annotations

from dodaios.progression.rules import (
    LOOK_UNLOCKS,
    MAX_LEVEL,
    RANK_IDS,
    RANK_TIERS,
    RANKS,
    RETIRED_SOURCES,
    REWARDS,
    RULES,
    RULES_BY_SOURCE,
    SLOTS,
    SUBJECT_KINDS,
    TITLES,
    VERSE_DECKS,
    WORLD_ACTIONS,
    level_for_xp,
    looks_between,
    progress_for_xp,
    rank_for,
    rewards_between,
    subject_kind,
    tier_start,
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
        "daily_visit", "deck_discovered", "simulator_round", "simulator_record",
        "team_briefing", "inspection", "walk_together",
    }
    limits = {
        source: (r.xp, r.cooldown_s, r.daily_cap, r.once_per_ref, r.kind)
        for source, r in RULES_BY_SOURCE.items() if source in WORLD_ACTIONS
    }
    assert limits == {
        "daily_visit": (25, 0, 0, True, "person"),
        "deck_discovered": (20, 0, 0, True, "person"),
        "simulator_round": (8, 45, 80, False, "person"),
        "simulator_record": (15, 45, 60, False, "person"),
        "team_briefing": (10, 600, 40, False, "person"),
        "inspection": (15, 0, 30, True, "person"),
        "walk_together": (3, 20, 60, False, "pet"),
    }


def test_retired_sources_are_never_paid_again():
    assert RETIRED_SOURCES.isdisjoint(RULES_BY_SOURCE)
    for gone in ("holodeck_round", "holodeck_record", "warp_jump", "floor_discovered",
                 "dog_petted", "arcade_round", "team_meeting"):
        assert gone in RETIRED_SOURCES


def test_a_days_world_actions_stay_a_garnish():
    # Playing everything aboard on one day pays about one ordinary day of work, not more.
    daily = sum(
        r.daily_cap or r.xp for r in RULES
        if r.trigger == "world" and r.kind == "person" and r.source != "deck_discovered"
    )
    assert daily <= 250


def test_the_server_rules_keep_their_amounts():
    amounts = {r.source: r.xp for r in RULES if r.trigger == "server"}
    assert amounts == {
        "chat_turn": 5, "voice_turn": 5, "quest_posted": 15, "quest_completed": 20,
        "agent_hired": 50, "mission_completed": 30, "task_done": 40, "task_blocked": 8,
        "quest_done": 60, "answered_teammate": 5, "jarvis_answered": 4, "delegated": 10,
    }


def test_the_decks_are_the_capital_ships():
    assert VERSE_DECKS == ("bridge", "ops", "engineering", "hangar")


def test_the_ladder_climbs_from_recruit_to_fleet_admiral_in_four_tiers():
    assert RANKS == (
        (1, "recruit", "deck"),
        (3, "deckhand", "deck"),
        (5, "technician", "deck"),
        (8, "senior_technician", "deck"),
        (11, "ensign", "line"),
        (14, "lieutenant", "line"),
        (17, "senior_lieutenant", "line"),
        (21, "commander", "line"),
        (25, "captain", "line"),
        (29, "line_captain", "command"),
        (33, "commodore", "command"),
        (37, "rear_admiral", "flag"),
        (41, "vice_admiral", "flag"),
        (45, "admiral", "flag"),
        (50, "fleet_admiral", "flag"),
    )
    levels = [level for level, _, _ in RANKS]
    assert levels[0] == 1 and levels[-1] == MAX_LEVEL
    assert levels == sorted(set(levels))
    # Tiers come in order and none is skipped.
    order = [RANK_TIERS.index(tier) for _, _, tier in RANKS]
    assert order == sorted(order) and {tier for _, _, tier in RANKS} == set(RANK_TIERS)
    assert len(RANK_IDS) == len(set(RANK_IDS)) == len(RANKS)
    for kind in SUBJECT_KINDS:
        assert [rank for _, rank in TITLES[kind]] == list(RANK_IDS)
    assert [tier_start(tier) for tier in RANK_TIERS] == [1, 11, 29, 37]


def test_every_promotion_takes_a_little_longer_than_the_one_before():
    # ~200 XP on an ordinary day: the first promotion on day one, none further than six weeks.
    starts = [total_xp_for_level(level) for level, _, _ in RANKS]
    gaps = [high - low for low, high in zip(starts, starts[1:], strict=False)]
    assert gaps[0] <= 200
    assert all(later > earlier for earlier, later in zip(gaps, gaps[1:], strict=False))
    assert max(gaps) <= 200 * 45


def test_titles_and_ranks_follow_the_ladder():
    assert title_for("person", 1) == "recruit"
    assert title_for("person", 2) == "recruit"
    assert title_for("agent", 3) == "deckhand"
    assert title_for("person", 13) == "ensign"
    assert title_for("pet", 29) == "line_captain"
    assert title_for("pet", MAX_LEVEL) == "fleet_admiral"
    assert rank_for(36) == (33, "commodore", "command")
    assert rank_for(0) == (1, "recruit", "deck")


def test_rewards_are_unique_named_by_their_slot_and_within_the_cap():
    ids = [reward.reward_id for reward in REWARDS]
    assert len(ids) == len(set(ids))
    for reward in REWARDS:
        assert reward.slot in SLOTS
        assert reward.reward_id.startswith(reward.slot + "_")
        for kind in SUBJECT_KINDS:
            level = reward.level_for(kind)
            assert level is None or 1 <= level <= MAX_LEVEL


def test_the_commanders_uniforms_open_with_the_rank_tiers():
    uniforms = [(r.reward_id, r.person) for r in REWARDS if r.slot == "uniform"]
    assert uniforms == [
        ("uniform_deck", 1), ("uniform_line", 11), ("uniform_command", 29), ("uniform_flag", 37),
    ]
    assert [r.reward_id.removeprefix("uniform_") for r in REWARDS if r.slot == "uniform"] == list(
        RANK_TIERS
    )
    # Officers wear their tier's uniform without earning it; the drone wears its rank only.
    assert all(r.agent is None and r.pet is None for r in REWARDS if r.slot == "uniform")


def test_ribbons_are_few_and_shared_by_the_commander_and_the_crew():
    ribbons = [(r.reward_id, r.person, r.agent) for r in REWARDS if r.slot == "ribbon"]
    assert ribbons == [
        ("ribbon_good_conduct", 6, 4),
        ("ribbon_meritorious", 19, 16),
        ("ribbon_distinguished", 31, 27),
        ("ribbon_fleet_cross", 47, 43),
    ]
    assert unlocked_rewards("pet", MAX_LEVEL) == []
    assert {r.slot for r in unlocked_rewards("person", MAX_LEVEL)} == set(SLOTS)
    assert {r.slot for r in unlocked_rewards("agent", MAX_LEVEL)} == {"ribbon"}


def test_rewards_between_names_only_what_the_climb_crossed():
    assert rewards_between("person", 1, 5) == []
    assert [r.reward_id for r in rewards_between("person", 5, 6)] == ["ribbon_good_conduct"]
    assert {r.reward_id for r in rewards_between("person", 10, 20)} == {
        "uniform_line", "ribbon_meritorious",
    }
    assert rewards_between("person", 11, 11) == []
    assert [r.reward_id for r in rewards_between("agent", 1, 4)] == ["ribbon_good_conduct"]
    # The work uniform is issued on day one, never "opened" by a climb.
    assert all(r.reward_id != "uniform_deck" for r in rewards_between("person", 1, MAX_LEVEL))


def test_subject_ids_name_their_kind():
    assert subject_kind("person") == "person"
    assert subject_kind("agent:scout") == "agent"
    assert subject_kind("pet:ember") == "pet"
    assert subject_kind("pet:") is None
    assert subject_kind("robot:x") is None


def test_every_agent_look_is_open_from_the_start():
    assert LOOK_UNLOCKS and all(level == 1 for level in LOOK_UNLOCKS.values())
    assert looks_between(1, 50) == []
