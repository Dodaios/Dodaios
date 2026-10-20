/**
 * The Verse's copy of the level system's ids and reward levels
 * (dodaios/progression/rules.py): subject kinds, reward slots, rewards with
 * the level each kind opens them at, XP sources and world actions, plus the
 * level curve. tests/unit/progression/test_frontend_parity.py pins every list
 * here to the Python rulebook: add an id in Python first, then here.
 *
 * The client keeps its own copy of the rewards and the curve so the Verse
 * still reads right when the running backend is older than this build (the
 * desktop app keeps its Python until it restarts). The rank ladder itself
 * lives in `verse/ranks/ranks.ts`.
 */

export const SUBJECT_KINDS = ["person", "agent", "pet"] as const;
export type SubjectKind = (typeof SUBJECT_KINDS)[number];

/** What a level opens: a uniform for the commander's figure, a ribbon on the service record. */
export const SLOTS = ["uniform", "ribbon"] as const;
export type Slot = (typeof SLOTS)[number];

export const REWARD_IDS = [
  "uniform_deck", "uniform_line", "uniform_command", "uniform_flag",
  "ribbon_good_conduct", "ribbon_meritorious", "ribbon_distinguished", "ribbon_fleet_cross",
] as const;
export type RewardId = (typeof REWARD_IDS)[number];
export type UniformRewardId = Extract<RewardId, `uniform_${string}`>;
export type RibbonId = Extract<RewardId, `ribbon_${string}`>;

/** The level each subject kind opens a reward at; null = never for that kind. */
export type RewardLevels = Record<SubjectKind, number | null>;

/** The rulebook's `REWARDS`, in its order. */
export const REWARD_LEVELS: Readonly<Record<RewardId, RewardLevels>> = {
  uniform_deck: { person: 1, agent: null, pet: null },
  uniform_line: { person: 11, agent: null, pet: null },
  uniform_command: { person: 29, agent: null, pet: null },
  uniform_flag: { person: 37, agent: null, pet: null },
  ribbon_good_conduct: { person: 6, agent: 4, pet: null },
  ribbon_meritorious: { person: 19, agent: 16, pet: null },
  ribbon_distinguished: { person: 31, agent: 27, pet: null },
  ribbon_fleet_cross: { person: 47, agent: 43, pet: null },
};

export const XP_SOURCES = [
  "chat_turn", "voice_turn", "quest_posted", "quest_completed", "agent_hired", "mission_completed",
  "daily_visit", "deck_discovered", "simulator_round", "simulator_record", "team_briefing", "inspection",
  "task_done", "task_blocked", "quest_done", "answered_teammate",
  "jarvis_answered", "delegated", "walk_together",
] as const;
export type XpSource = (typeof XP_SOURCES)[number];

/** The world actions the ship itself reports (`trigger: "world"` in the rulebook). */
export type WorldAction = "daily_visit" | "deck_discovered" | "simulator_round" | "simulator_record"
  | "team_briefing" | "inspection" | "walk_together";

export const MAX_LEVEL = 50;

/** XP from `level` to the next (the rulebook's `xp_to_next`); 0 at the cap. */
export function xpToNext(level: number): number {
  if (level >= MAX_LEVEL) return 0;
  const l = Math.max(1, Math.floor(level));
  const raw = 40 + 25 * (l - 1) ** 1.1;
  return Math.round(raw / 5) * 5;
}

/** Total XP at which each level starts, index 0 = level 1 (the server's `level_xp`). */
export const LEVEL_XP: readonly number[] = (() => {
  const totals = [0];
  for (let level = 1; level < MAX_LEVEL; level++) totals.push(totals[level - 1] + xpToNext(level));
  return totals;
})();

/** The level `totalXp` reaches on the curve. */
export function levelForXp(totalXp: number, curve: readonly number[] = LEVEL_XP): number {
  let level = 1;
  while (level < curve.length && totalXp >= curve[level]) level += 1;
  return level;
}

export function slotOf(reward: RewardId): Slot {
  return reward.slice(0, reward.indexOf("_")) as Slot;
}

/** The reward's name inside its slot; for a uniform, the rank tier it belongs to. */
export function rewardKey(reward: RewardId): string {
  return reward.slice(reward.indexOf("_") + 1);
}

export function isRewardId(value: unknown): value is RewardId {
  return typeof value === "string" && (REWARD_IDS as readonly string[]).includes(value);
}

export function isXpSource(value: unknown): value is XpSource {
  return typeof value === "string" && (XP_SOURCES as readonly string[]).includes(value);
}
