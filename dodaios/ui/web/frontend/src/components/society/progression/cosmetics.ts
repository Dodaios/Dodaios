/**
 * What a level has opened, and which uniform the commander wears. Pure: the
 * level comes from the server, the unlock levels from the rulebook (or the
 * client's copy of it), the commander's choice from browser storage.
 *
 * The quartermaster issues the work uniform on day one and each higher
 * tier's dress the day its first rank is reached. "auto" wears the uniform of
 * the highest tier issued; a chosen uniform that is not issued yet (another
 * profile's choice, a reset ledger) falls back to automatic.
 */
import type { RewardRow, SubjectLevel } from "./progressionApi";
import { LEVEL_XP, SLOTS, rewardKey, type SubjectKind } from "./levelCatalog";
import { RANK_TIERS, type UniformId } from "../verse/ranks/ranks";

export type UniformChoice = UniformId | "auto";

export function unlockedFor(rewards: readonly RewardRow[], kind: SubjectKind, level: number): RewardRow[] {
  return rewards.filter((r) => { const at = r.levels[kind]; return at !== null && level >= at; });
}

function isUniformId(value: string): value is UniformId {
  return (RANK_TIERS as readonly string[]).includes(value);
}

/** The uniforms issued to the commander at `level`, lowest tier first; the work uniform always. */
export function issuedUniforms(rewards: readonly RewardRow[], level: number): UniformId[] {
  const issued = unlockedFor(rewards, "person", level)
    .filter((r) => r.slot === "uniform")
    .map((r) => rewardKey(r.rewardId))
    .filter(isUniformId);
  const set = new Set<UniformId>(["deck", ...issued]);
  return RANK_TIERS.filter((tier) => set.has(tier));
}

/** The uniform the commander wears at `level` with `choice`. */
export function uniformFor(rewards: readonly RewardRow[], level: number, choice: UniformChoice = "auto"): UniformId {
  const issued = issuedUniforms(rewards, level);
  if (choice !== "auto" && issued.includes(choice)) return choice;
  return issued[issued.length - 1] ?? "deck";
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

/** XP gathered into the current level and the level's size, from the server's curve (or the client's copy). */
export function progressFor(levelXp: readonly number[], totalXp: number, level: number): { into: number; size: number } {
  const curve = levelXp.length > 1 ? levelXp : LEVEL_XP;
  const start = curve[level - 1] ?? 0;
  const next = curve[level];
  return { into: Math.max(0, totalXp - start), size: next === undefined ? 0 : Math.max(1, next - start) };
}

/** XP still missing until `level` is reached, from `totalXp`; 0 once there. */
export function xpUntilLevel(levelXp: readonly number[], totalXp: number, level: number): number {
  const curve = levelXp.length > 1 ? levelXp : LEVEL_XP;
  const target = curve[Math.max(0, Math.min(curve.length, level) - 1)] ?? 0;
  return Math.max(0, target - totalXp);
}

/** A subject's place on its level bar, 0..1 (1 at the cap). */
export function levelFraction(subject: Pick<SubjectLevel, "xpIntoLevel" | "xpForNext"> | undefined): number {
  if (!subject) return 0;
  if (subject.xpForNext <= 0) return 1;
  return Math.max(0, Math.min(1, subject.xpIntoLevel / subject.xpForNext));
}

const UNIFORM_KEY = "dodaios.verse.uniform.v1";

export function loadUniformChoice(): UniformChoice {
  try {
    const raw = typeof localStorage === "undefined" ? null : localStorage.getItem(UNIFORM_KEY);
    return raw !== null && isUniformId(raw) ? raw : "auto";
  } catch (error) {
    // Blocked storage: the commander wears the highest issued uniform, which is the default anyway.
    console.debug("Verse uniform choice unavailable", error);
    return "auto";
  }
}

export function saveUniformChoice(choice: UniformChoice): void {
  try {
    localStorage.setItem(UNIFORM_KEY, choice);
  } catch (error) {
    console.debug("Verse uniform choice not saved", error);
  }
}
