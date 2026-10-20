/**
 * The ship's rank ladder, mirrored from the rulebook (dodaios/progression/rules.py
 * `RANKS`; a parity test pins the two). Everyone aboard climbs it: the
 * captain (the person), every android (agent) and the pet.
 *
 * What a rank looks like on a figure: enlisted ranks wear silver pips at the
 * collar, officers gold pips, flag officers four gold pips over a gold bar.
 */

export type RankTier = "enlisted" | "warrant" | "officer" | "flag";

export interface Rank {
  id: string;
  /** First level of the rank. */
  level: number;
  tier: RankTier;
  /** Collar pips on a figure (0–4) and their metal. */
  pips: number;
  gold: boolean;
}

export const RANKS: readonly Rank[] = [
  { id: "cadet", level: 1, tier: "enlisted", pips: 0, gold: false },
  { id: "crewman", level: 3, tier: "enlisted", pips: 1, gold: false },
  { id: "specialist", level: 5, tier: "enlisted", pips: 2, gold: false },
  { id: "petty_officer", level: 7, tier: "enlisted", pips: 3, gold: false },
  { id: "chief_petty_officer", level: 10, tier: "enlisted", pips: 4, gold: false },
  { id: "warrant_officer", level: 13, tier: "warrant", pips: 1, gold: true },
  { id: "ensign", level: 16, tier: "officer", pips: 1, gold: true },
  { id: "lieutenant_junior_grade", level: 19, tier: "officer", pips: 2, gold: true },
  { id: "lieutenant", level: 22, tier: "officer", pips: 2, gold: true },
  { id: "lieutenant_commander", level: 26, tier: "officer", pips: 3, gold: true },
  { id: "commander", level: 30, tier: "officer", pips: 3, gold: true },
  { id: "captain", level: 34, tier: "officer", pips: 4, gold: true },
  { id: "commodore", level: 38, tier: "flag", pips: 4, gold: true },
  { id: "rear_admiral", level: 42, tier: "flag", pips: 4, gold: true },
  { id: "vice_admiral", level: 46, tier: "flag", pips: 4, gold: true },
  { id: "admiral", level: 50, tier: "flag", pips: 4, gold: true },
];

export function rankFor(level: number): Rank {
  let rank = RANKS[0];
  for (const r of RANKS) if (level >= r.level) rank = r;
  return rank;
}

export function nextRank(level: number): Rank | null {
  return RANKS.find((r) => r.level > level) ?? null;
}
