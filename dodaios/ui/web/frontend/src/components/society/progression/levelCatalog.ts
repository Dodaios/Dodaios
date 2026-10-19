/**
 * The ship's copy of the level system's ids (dodaios/progression/rules.py):
 * subject kinds, reward slots, reward ids, rank ids and XP sources. The
 * server sends levels and amounts; this file only knows the ids, so a
 * surface can name and draw them. tests/unit/progression/test_frontend_parity.py
 * pins every list here to the Python rulebook (AP-4): add an id in Python
 * first, then here. The rank ladder itself (levels, tiers, pips) lives in
 * `starship/levels/ranks.ts`.
 */

export const SUBJECT_KINDS = ["person", "agent", "pet"] as const;
export type SubjectKind = (typeof SUBJECT_KINDS)[number];

/** What a level opens: a suit for the captain's figure, a destination for the helm, a decoration. */
export const SLOTS = ["suit", "destination", "decoration"] as const;
export type Slot = (typeof SLOTS)[number];

export const REWARD_IDS = [
  "suit_field_armor", "suit_command_coat", "suit_dress_whites", "suit_admiral_coat",
  "destination_gas_giant", "destination_crimson_nebula", "destination_ice_moon", "destination_twin_suns",
  "destination_event_horizon", "destination_aurora_world", "destination_galactic_core",
  "decoration_service_ribbon", "decoration_commendation", "decoration_star_medal", "decoration_legion_of_merit",
] as const;
export type RewardId = (typeof REWARD_IDS)[number];
export type SuitId = Extract<RewardId, `suit_${string}`>;

/** The rank ladder, lowest first (the server's `RANKS`, the ship's `ranks.ts`). */
export const RANK_IDS = [
  "cadet", "crewman", "specialist", "petty_officer", "chief_petty_officer", "warrant_officer", "ensign",
  "lieutenant_junior_grade", "lieutenant", "lieutenant_commander", "commander", "captain", "commodore",
  "rear_admiral", "vice_admiral", "admiral",
] as const;
export type RankId = (typeof RANK_IDS)[number];

export const XP_SOURCES = [
  "chat_turn", "voice_turn", "quest_posted", "quest_completed", "agent_hired", "mission_completed",
  "daily_visit", "deck_discovered", "holodeck_round", "holodeck_record", "team_briefing", "warp_jump",
  "task_done", "task_blocked", "quest_done", "answered_teammate",
  "jarvis_answered", "delegated", "walk_together",
] as const;
export type XpSource = (typeof XP_SOURCES)[number];

/** The world actions the ship itself reports (`trigger: "world"` in the rulebook). */
export type WorldAction = "daily_visit" | "deck_discovered" | "holodeck_round" | "holodeck_record"
  | "team_briefing" | "warp_jump" | "walk_together";

export function slotOf(reward: RewardId): Slot {
  return reward.slice(0, reward.indexOf("_")) as Slot;
}

/** The reward's name inside its slot; for a destination, the helm's destination id. */
export function rewardKey(reward: RewardId): string {
  return reward.slice(reward.indexOf("_") + 1);
}

export function isRewardId(value: unknown): value is RewardId {
  return typeof value === "string" && (REWARD_IDS as readonly string[]).includes(value);
}

export function isRankId(value: unknown): value is RankId {
  return typeof value === "string" && (RANK_IDS as readonly string[]).includes(value);
}

export function isXpSource(value: unknown): value is XpSource {
  return typeof value === "string" && (XP_SOURCES as readonly string[]).includes(value);
}
