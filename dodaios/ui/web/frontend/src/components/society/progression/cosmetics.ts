/**
 * What a level has opened, and which suit the captain wears. Pure: the level
 * comes from the server, the unlock levels from the rulebook, the captain's
 * choice of suit from browser storage. Destinations open here too, but which
 * one the helm has set is the ship store's (`starship/space/destinations.ts`).
 */
import type { RewardRow, SubjectLevel } from "./progressionApi";
import { SLOTS, type SubjectKind, type SuitId } from "./levelCatalog";

/** "auto" wears the finest suit open, "none" the captain's own clothes. */
export type SuitChoice = SuitId | "none" | "auto";

export function unlockedFor(rewards: readonly RewardRow[], kind: SubjectKind, level: number): RewardRow[] {
  return rewards.filter((r) => { const at = r.levels[kind]; return at !== null && level >= at; });
}

/** The suit the captain wears at `level` with `choice`; null = own clothes. A chosen suit that is not open yet falls back to automatic. */
export function suitFor(rewards: readonly RewardRow[], level: number, choice: SuitChoice = "auto"): SuitId | null {
  if (choice === "none") return null;
  const open = unlockedFor(rewards, "person", level).filter((r) => r.slot === "suit");
  const picked = choice !== "auto" ? open.find((r) => r.rewardId === choice) : undefined;
  const best = open.reduce<RewardRow | undefined>((top, r) => (!top || (r.levels.person ?? 0) >= (top.levels.person ?? 0) ? r : top), undefined);
  return ((picked ?? best)?.rewardId as SuitId | undefined) ?? null;
}

/**
 * The rewards a subject kind can ever earn, in the order they open (lowest
 * level first; within one level in slot order).
 */
export function rewardRoad(rewards: readonly RewardRow[], kind: SubjectKind): RewardRow[] {
  return rewards
    .filter((r) => r.levels[kind] !== null)
    .sort((a, b) => (a.levels[kind] ?? 0) - (b.levels[kind] ?? 0) || SLOTS.indexOf(a.slot) - SLOTS.indexOf(b.slot));
}

/** The first reward on the road the subject has not opened yet; undefined once everything is open. */
export function nextUnlock(rewards: readonly RewardRow[], kind: SubjectKind, level: number): RewardRow | undefined {
  return rewardRoad(rewards, kind).find((r) => (r.levels[kind] ?? 0) > level);
}

/** Rewards a climb from `before` to `after` opened, in road order. */
export function rewardsBetween(rewards: readonly RewardRow[], kind: SubjectKind, before: number, after: number): RewardRow[] {
  return rewardRoad(rewards, kind).filter((r) => { const at = r.levels[kind] ?? 0; return at > before && at <= after; });
}

/** XP gathered into the current level and the level's size, from the curve the server sent. */
export function progressFor(levelXp: readonly number[], totalXp: number, level: number): { into: number; size: number } {
  const start = levelXp[level - 1] ?? 0;
  const next = levelXp[level];
  return { into: Math.max(0, totalXp - start), size: next === undefined ? 0 : Math.max(1, next - start) };
}

/** A subject's place on its level bar, 0..1 (1 at the cap). */
export function levelFraction(subject: Pick<SubjectLevel, "xpIntoLevel" | "xpForNext"> | undefined): number {
  if (!subject) return 0;
  if (subject.xpForNext <= 0) return 1;
  return Math.max(0, Math.min(1, subject.xpIntoLevel / subject.xpForNext));
}

const SUIT_KEY = "dodaios.ship.suit.v1";

export function loadSuitChoice(): SuitChoice {
  try {
    const raw = typeof localStorage === "undefined" ? null : localStorage.getItem(SUIT_KEY);
    return raw === "none" || (raw !== null && raw.startsWith("suit_")) ? (raw as SuitChoice) : "auto";
  } catch (error) {
    // Blocked storage: the captain wears the finest suit open, which is the default anyway.
    console.debug("Ship suit choice unavailable", error);
    return "auto";
  }
}

export function saveSuitChoice(choice: SuitChoice): void {
  try {
    localStorage.setItem(SUIT_KEY, choice);
  } catch (error) {
    console.debug("Ship suit choice not saved", error);
  }
}
