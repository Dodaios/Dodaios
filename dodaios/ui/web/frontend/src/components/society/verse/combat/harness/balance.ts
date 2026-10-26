/**
 * Balance runs: many headless duels per pairing, both slots alternated, and
 * the numbers that tell whether the duel is fair and skill-based: win rate,
 * round length, time to kill, accuracy, parries, blocks, overheats, perfect
 * vents, and the win rate of each spawn side.
 */
import { createContext, type SimContext } from "../sim";
import { DEFAULT_TUNING, TICK_RATE, type CombatTuning } from "../tuning";
import { runDuel, type DuelResult } from "./duel";
import { strategy, TRICK_IDS, type StrategyId } from "./strategies";

export interface PairingReport {
  a: StrategyId;
  b: StrategyId;
  duels: number;
  /** Share of duels a won (draws count half). */
  winRateA: number;
  /** Share of decided rounds a won. */
  roundWinRateA: number;
  draws: number;
  roundsPerDuel: number;
  roundSeconds: number;
  timeoutRounds: number;
  ttkSeconds: number;
  /** Per side of the pairing: a then b. */
  accuracy: [number, number];
  headshotShare: [number, number];
  parriesPerRound: [number, number];
  blocksPerRound: [number, number];
  /** Share of the bolts reaching a player that the shield parried. */
  parryRate: [number, number];
  overheatsPerRound: [number, number];
  perfectVentRate: [number, number];
  dodgesPerRound: [number, number];
  /** Round win rate of spawn side 0 (both players together). */
  side0RoundWinRate: number;
}

export interface BalanceOptions {
  pairings: readonly (readonly [StrategyId, StrategyId])[];
  duels: number;
  seed?: number;
  tuning?: CombatTuning;
  onPairing?: (r: PairingReport) => void;
}

const sum = (xs: readonly number[]) => xs.reduce((a, b) => a + b, 0);
const ratio = (a: number, b: number) => (b > 0 ? a / b : 0);

export function runPairing(ctx: SimContext, a: StrategyId, b: StrategyId, duels: number, seed0: number): { report: PairingReport; results: DuelResult[] } {
  const results: DuelResult[] = [];
  let winsA = 0;
  let draws = 0;
  const S = [[0, 0], [0, 0]].map(() => ({ shots: 0, hits: 0, heads: 0, parries: 0, blocks: 0, overheats: 0, perfect: 0, ventTries: 0, dodges: 0, incoming: 0 }));
  let rounds = 0;
  let roundTicks = 0;
  let timeouts = 0;
  let side0Wins = 0;
  let decided = 0;
  let roundsA = 0;
  const ttk: number[] = [];
  for (let i = 0; i < duels; i++) {
    const swap = i % 2 === 1;
    const seed = (seed0 + i * 7919) >>> 0;
    const r = runDuel({ ctx, seed, players: swap ? [strategy(b), strategy(a)] : [strategy(a), strategy(b)] });
    results.push(r);
    const slotA = swap ? 1 : 0;
    if (r.winner === slotA) winsA++;
    else if (r.winner < 0) draws++;
    for (const [k, slot] of [[0, slotA], [1, 1 - slotA]] as const) {
      const st = r.stats[slot];
      const acc = S[k];
      acc.shots += st.shots; acc.hits += st.hits; acc.heads += st.headshots; acc.parries += st.parries; acc.blocks += st.blocks;
      acc.overheats += st.overheats; acc.perfect += st.perfectVents; acc.ventTries += st.perfectVents + st.ventMisses; acc.dodges += st.dodges;
      acc.incoming += r.incoming[slot];
    }
    rounds += r.rounds.length;
    for (const rd of r.rounds) {
      roundTicks += rd.ticks;
      if (rd.reason === "time") timeouts++;
      if (rd.winner >= 0) { decided++; if (rd.sides[rd.winner] === 0) side0Wins++; if (rd.winner === slotA) roundsA++; }
    }
    ttk.push(...r.ttk);
  }
  const per = (k: 0 | 1, f: (x: (typeof S)[number]) => number) => f(S[k]);
  const pair = (f: (x: (typeof S)[number]) => number): [number, number] => [per(0, f), per(1, f)];
  const report: PairingReport = {
    a, b, duels,
    winRateA: (winsA + draws / 2) / duels,
    roundWinRateA: ratio(roundsA, decided),
    draws,
    roundsPerDuel: rounds / duels,
    roundSeconds: ratio(roundTicks, rounds) / TICK_RATE,
    timeoutRounds: timeouts,
    ttkSeconds: ratio(sum(ttk), ttk.length) / TICK_RATE,
    accuracy: pair((x) => ratio(x.hits, x.shots)),
    headshotShare: pair((x) => ratio(x.heads, x.hits)),
    parriesPerRound: pair((x) => ratio(x.parries, rounds)),
    blocksPerRound: pair((x) => ratio(x.blocks, rounds)),
    parryRate: pair((x) => ratio(x.parries, x.incoming)),
    overheatsPerRound: pair((x) => ratio(x.overheats, rounds)),
    perfectVentRate: pair((x) => ratio(x.perfect, x.ventTries)),
    dodgesPerRound: pair((x) => ratio(x.dodges, rounds)),
    side0RoundWinRate: ratio(side0Wins, decided),
  };
  return { report, results };
}

export function runBalance(o: BalanceOptions): PairingReport[] {
  const ctx = createContext(undefined, o.tuning ?? DEFAULT_TUNING);
  const out: PairingReport[] = [];
  o.pairings.forEach(([a, b], i) => {
    const { report } = runPairing(ctx, a, b, o.duels, (o.seed ?? 1) + i * 104729);
    out.push(report);
    o.onPairing?.(report);
  });
  return out;
}

type Pairing = readonly [StrategyId, StrategyId];

export const TIER_LADDER: readonly Pairing[] = [
  ["hard", "normal"], ["elite", "hard"], ["elite", "normal"], ["normal", "normal"], ["hard", "hard"], ["elite", "elite"],
];

/** The person models against the tiers: where a skilled and an average player stand. */
export const HUMANS: readonly Pairing[] = [
  ["skilled", "normal"], ["skilled", "hard"], ["skilled", "elite"], ["average", "normal"], ["average", "hard"], ["average", "elite"],
];

/** One-trick strategies against the hard bot (same aim, one behaviour forced). */
export const EXPLOITS: readonly Pairing[] = TRICK_IDS.map((t): Pairing => ["hard", t]);

/** A skilled person playing one trick against the elite bot: must not beat plain skilled play. */
export const VS_ELITE: readonly Pairing[] = TRICK_IDS.filter((t) => t !== "turtle").map((t): Pairing => ["elite", `skilled+${t}`]);

/** Tricks against each other: no one trick should beat them all. */
export const CROSS: readonly Pairing[] = [
  ["spam", "blocker"], ["spam", "flicker"], ["dodger", "spam"], ["rusher", "camper"], ["flicker", "rusher"],
  ["dodger", "blocker"], ["dodger", "flicker"], ["blocker", "flicker"], ["blocker", "rusher"], ["kiter", "brawler"],
  ["kiter", "dodger"], ["edge", "blocker"], ["jiggle", "kiter"], ["normal", "spam"], ["normal", "turtle"],
];

export function formatReport(r: PairingReport): string {
  const f = (v: number, d = 2) => v.toFixed(d);
  const p = (v: number) => `${(v * 100).toFixed(0)}%`;
  return `${r.a.padEnd(7)} vs ${r.b.padEnd(7)} n=${r.duels} winA=${p(r.winRateA)} roundsA=${p(r.roundWinRateA)} draws=${r.draws} rounds=${f(r.roundsPerDuel)} round=${f(r.roundSeconds, 1)}s timeouts=${r.timeoutRounds} ttk=${f(r.ttkSeconds)}s`
    + ` acc=${p(r.accuracy[0])}/${p(r.accuracy[1])} head=${p(r.headshotShare[0])}/${p(r.headshotShare[1])} parry=${p(r.parryRate[0])}/${p(r.parryRate[1])}`
    + ` blocks/rd=${f(r.blocksPerRound[0])}/${f(r.blocksPerRound[1])} oh/rd=${f(r.overheatsPerRound[0])}/${f(r.overheatsPerRound[1])}`
    + ` vent=${p(r.perfectVentRate[0])}/${p(r.perfectVentRate[1])} dodge/rd=${f(r.dodgesPerRound[0])}/${f(r.dodgesPerRound[1])} side0=${p(r.side0RoundWinRate)}`;
}
