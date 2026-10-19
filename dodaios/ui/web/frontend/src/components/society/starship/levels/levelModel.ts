/**
 * The pure side of the ship's level UI: what an insignia shows, the ladder
 * with the viewer's place on it, the rewards per shelf, the ship's log and
 * the rules in plain groups. The service record and the promotion ceremony
 * only lay these out; tests check them without a DOM.
 */
import type { RewardRow, AwardRow, SubjectLevel, XpRuleRow } from "../../progression/progressionApi";
import { rewardKey, slotOf, type RewardId, type Slot, type SubjectKind } from "../../progression/levelCatalog";
import { RANKS, rankFor, type Rank, type RankTier } from "./ranks";
import { destinationById, type Destination } from "../space/destinations";

// ------------------------------------------------------------------ insignia

/**
 * How a rank's insignia is drawn. Enlisted: silver chevrons (cadet an empty
 * bar, chief petty officer three chevrons over a rocker). Warrant: one gold
 * pip on a silver-edged bar. Officers: gold pips, some hollow. Flag: a gold
 * bar under one to four stars.
 */
export type InsigniaSpec =
  | { kind: "bar" }
  | { kind: "chevrons"; count: number; rocker: boolean }
  | { kind: "pips"; solid: number; hollow: number; warrant: boolean }
  | { kind: "flag"; stars: number };

const INSIGNIA: Record<string, InsigniaSpec> = {
  cadet: { kind: "bar" },
  crewman: { kind: "chevrons", count: 1, rocker: false },
  specialist: { kind: "chevrons", count: 2, rocker: false },
  petty_officer: { kind: "chevrons", count: 3, rocker: false },
  chief_petty_officer: { kind: "chevrons", count: 3, rocker: true },
  warrant_officer: { kind: "pips", solid: 1, hollow: 0, warrant: true },
  ensign: { kind: "pips", solid: 1, hollow: 0, warrant: false },
  lieutenant_junior_grade: { kind: "pips", solid: 1, hollow: 1, warrant: false },
  lieutenant: { kind: "pips", solid: 2, hollow: 0, warrant: false },
  lieutenant_commander: { kind: "pips", solid: 2, hollow: 1, warrant: false },
  commander: { kind: "pips", solid: 3, hollow: 0, warrant: false },
  captain: { kind: "pips", solid: 4, hollow: 0, warrant: false },
  commodore: { kind: "flag", stars: 1 },
  rear_admiral: { kind: "flag", stars: 2 },
  vice_admiral: { kind: "flag", stars: 3 },
  admiral: { kind: "flag", stars: 4 },
};

/** The insignia of a rank id; an id this build does not know wears the cadet's bar. */
export function insigniaFor(rankId: string): InsigniaSpec {
  return INSIGNIA[rankId] ?? INSIGNIA.cadet;
}

export function isPromotion(previousLevel: number, level: number): boolean {
  return rankFor(level).id !== rankFor(previousLevel).id;
}

// ------------------------------------------------------------------ XP

/** Total XP at which `level` starts, from the server's curve (0 before it arrives). */
export function levelStartXp(levelXp: readonly number[], level: number): number {
  return levelXp[Math.max(0, level - 1)] ?? 0;
}

/** XP still missing until `level` (0 once reached; null when the curve does not reach it). */
export function xpToReach(levelXp: readonly number[], totalXp: number, level: number): number | null {
  const at = levelXp[level - 1];
  if (at === undefined) return null;
  return Math.max(0, at - totalXp);
}

// ------------------------------------------------------------------ ranks

export type RungState = "held" | "current" | "ahead";
export interface Rung { rank: Rank; state: RungState; xpToGo: number | null }
export interface TierGroup { tier: RankTier; rungs: Rung[] }

export const TIER_ORDER: readonly RankTier[] = ["enlisted", "warrant", "officer", "flag"];

/** The whole ladder grouped by tier, with the viewer's place on it. */
export function rankLadder(level: number, totalXp: number, levelXp: readonly number[]): TierGroup[] {
  const current = rankFor(level).id;
  return TIER_ORDER.map((tier) => ({
    tier,
    rungs: RANKS.filter((r) => r.tier === tier).map((rank) => ({
      rank,
      state: rank.id === current ? "current" : rank.level <= level ? "held" : "ahead",
      xpToGo: rank.level > level ? xpToReach(levelXp, totalXp, rank.level) : null,
    })),
  }));
}

// ------------------------------------------------------------------ rewards

export interface Shelf { slot: Slot; items: { reward: RewardRow; level: number; open: boolean; xpToGo: number | null }[] }

/** What the captain can earn, one shelf per slot, each in the order it opens. */
export function rewardShelves(rewards: readonly RewardRow[], level: number, totalXp: number, levelXp: readonly number[]): Shelf[] {
  const slots: Slot[] = ["suit", "destination", "decoration"];
  return slots.map((slot) => ({
    slot,
    items: rewards
      .filter((r) => r.slot === slot && r.levels.person !== null)
      .sort((a, b) => (a.levels.person ?? 0) - (b.levels.person ?? 0))
      .map((reward) => {
        const at = reward.levels.person ?? 0;
        return { reward, level: at, open: level >= at, xpToGo: level >= at ? null : xpToReach(levelXp, totalXp, at) };
      }),
  })).filter((shelf) => shelf.items.length > 0);
}

/** The next reward a kind opens above `level`. */
export function nextReward(rewards: readonly RewardRow[], kind: SubjectKind, level: number): { reward: RewardRow; level: number } | null {
  let best: { reward: RewardRow; level: number } | null = null;
  for (const reward of rewards) {
    const at = reward.levels[kind];
    if (at === null || at <= level) continue;
    if (!best || at < best.level) best = { reward, level: at };
  }
  return best;
}

/** A destination reward's helm destination (the colours its swatch is painted in). */
export function destinationOf(reward: RewardId): Destination | null {
  return slotOf(reward) === "destination" ? destinationById(rewardKey(reward)) : null;
}

// ------------------------------------------------------------------ the ship's log

export type LogLine =
  | { kind: "promoted"; rank: string }
  | { kind: "level"; level: number }
  | { kind: "warp"; destination: string }
  | { kind: "deck"; deck: string }
  | { kind: "source"; source: string };

export interface LogEntry { seq: number; subjectId: string; tsMs: number; xp: number; line: LogLine }

/**
 * The captain's and the companion's latest awards, newest first, each in
 * plain words. A level-up reads as the level (or the promotion) it brought;
 * a source this build no longer knows is still listed.
 */
export function shipLog(recent: readonly AwardRow[], subjectIds: ReadonlySet<string>, limit = 14): LogEntry[] {
  const out: LogEntry[] = [];
  for (let i = recent.length - 1; i >= 0 && out.length < limit; i -= 1) {
    const row = recent[i];
    if (!subjectIds.has(row.subjectId)) continue;
    let line: LogLine;
    if (row.levelAfter > row.levelBefore) {
      line = isPromotion(row.levelBefore, row.levelAfter) ? { kind: "promoted", rank: rankFor(row.levelAfter).id } : { kind: "level", level: row.levelAfter };
    } else if (row.source === "warp_jump" && row.ref) {
      line = { kind: "warp", destination: row.ref.split("@")[0] };
    } else if (row.source === "deck_discovered" && row.ref) {
      line = { kind: "deck", deck: row.ref };
    } else {
      line = { kind: "source", source: row.source };
    }
    out.push({ seq: row.seq, subjectId: row.subjectId, tsMs: row.tsMs, xp: row.xp, line });
  }
  return out;
}

// ------------------------------------------------------------------ rules

export type RuleLimit =
  | { kind: "once_day" }
  | { kind: "once_deck" }
  | { kind: "metered"; cooldownS: number; dailyCap: number }
  | { kind: "none" };

export interface RuleGroup { kind: SubjectKind; rules: { rule: XpRuleRow; limit: RuleLimit }[] }

export function ruleLimit(rule: XpRuleRow): RuleLimit {
  if (rule.source === "daily_visit") return { kind: "once_day" };
  if (rule.source === "deck_discovered") return { kind: "once_deck" };
  if (rule.cooldownS > 0 || rule.dailyCap > 0) return { kind: "metered", cooldownS: rule.cooldownS, dailyCap: rule.dailyCap };
  return { kind: "none" };
}

/** Every rule for the captain, the companion and the crew, the richest first within a group. */
export function ruleGroups(rules: readonly XpRuleRow[]): RuleGroup[] {
  const kinds: SubjectKind[] = ["person", "pet", "agent"];
  return kinds.map((kind) => ({
    kind,
    rules: rules.filter((r) => r.kind === kind).sort((a, b) => b.xp - a.xp).map((rule) => ({ rule, limit: ruleLimit(rule) })),
  })).filter((g) => g.rules.length > 0);
}

// ------------------------------------------------------------------ crew

export interface CrewRow { agentId: string; name: string; level: number; xp: number; rank: Rank }

/** Every android's rank, best first (level, then XP, then name). */
export function crewRanking(agents: readonly { agentId: string; name: string; tier: string }[], subjects: Readonly<Record<string, SubjectLevel>>): CrewRow[] {
  return agents
    .filter((a) => a.tier !== "lead")
    .map((a) => {
      const s = subjects[`agent:${a.agentId}`];
      const level = s?.level ?? 1;
      return { agentId: a.agentId, name: a.name, level, xp: s?.xp ?? 0, rank: rankFor(level) };
    })
    .sort((a, b) => b.level - a.level || b.xp - a.xp || a.name.localeCompare(b.name));
}
