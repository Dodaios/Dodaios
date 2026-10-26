/**
 * The players the balance harness pits against each other:
 *
 * - the bot tiers (normal, hard, elite);
 * - "skilled", a stand-in for a skilled person: human reaction times
 *   (200..250 ms), good but imperfect mouse aim, decent timing; it plays
 *   every mechanic, so its results estimate how a practised player fares;
 * - one-trick strategies: a base player (the hard bot unless named) with one
 *   behaviour forced, so a result shows what the trick itself is worth.
 *   "elite+dodger" is the elite bot rolling all the time, "skilled+circle" a
 *   skilled person orbiting at point blank, plain "dodger" = "hard+dodger".
 */
import { BotBrain, type BotOverrides } from "../bot/brain";
import { botParams, type BotParams, type BotTier } from "../bot/tiers";
import type { ControllerFactory } from "./duel";

export type BaseId = BotTier | "skilled" | "average";

export type TrickId =
  | "spam"      // holds the trigger whenever it sees the opponent, never vents, never shields
  | "turtle"    // shield up all the time, never fires
  | "blocker"   // blocks every bolt it sees (no planned parries), fires otherwise
  | "camper"    // sits in cover near its spawn and waits
  | "dodger"    // rolls whenever the roll is ready
  | "flicker"   // flicks the shield for parries as fast as the lockout allows
  | "rusher"    // runs straight at the opponent
  | "circle"    // closes in and orbits the opponent at point blank, firing
  | "jiggle"    // reverses its strafe every 140..300 ms (A-D spam)
  | "hider"     // once ahead on health, breaks off and hides (plays for the clock)
  | "edge"      // fires to the edge of an overheat, then vents at once, timed
  | "parrier"   // tries to parry every bolt it sees, nothing else
  | "watcher"   // holds a spot that sees the other spawn, pre-aimed
  | "kiter"     // keeps 28 m away and fights from range, in sights
  | "brawler";  // fights at 6 m (close, but not hugging)

export type StrategyId = BaseId | TrickId | `${BaseId}+${TrickId}`;

/**
 * A skilled person as bot numbers: reaction 225 +- 18 ms (nearly all within
 * 200..250 ms), a visual-motor tracking delay of 110 ms, aim error a little
 * above the elite bot's but much faster flicks, heads more often, vents and
 * parries timed by eye (55..60 ms sd), and aims at the middle of an A-D
 * wobble once it sees one. Between the hard and elite tiers on paper; what
 * decides its games is the same rules and perception as the bots'.
 */
export const SKILLED_HUMAN: BotParams = {
  tier: "elite",
  reactionMs: [225, 18],
  trackLatencyMs: 110,
  aimNoiseDeg: 1.0,
  aimNoiseRate: 2.0,
  acquireErrorDeg: 4.0,
  acquireMs: 380,
  turnRateDeg: 900,
  aimStiffness: 14,
  leadSkill: 0.85,
  leadNoise: 0.18,
  motionWindowMs: 250,
  recoilComp: 0.8,
  fireTolerance: 1.5,
  heatCap: 90,
  ventTimingSdMs: 60,
  parryChance: 0.5,
  parryTimingSdMs: 55,
  blockChance: 0.65,
  dodgeChance: 0.3,
  strafeMs: [300, 800],
  coverUse: 0.7,
  flankUse: 0.55,
  aggression: 0.65,
  baitPunish: 0.6,
  decisionMs: 200,
  headAim: 0.3,
  adsRange: 11,
  hearingErrorM: 3,
};

/**
 * An average player: slower (270 +- 40 ms) and looser aim, overheats now and
 * then, parries rarely. Where the normal tier should be a fair fight.
 */
export const AVERAGE_HUMAN: BotParams = {
  tier: "normal",
  reactionMs: [270, 40],
  trackLatencyMs: 140,
  aimNoiseDeg: 1.45,
  aimNoiseRate: 1.7,
  acquireErrorDeg: 6,
  acquireMs: 550,
  turnRateDeg: 600,
  aimStiffness: 10,
  leadSkill: 0.7,
  leadNoise: 0.3,
  motionWindowMs: 0,
  recoilComp: 0.5,
  fireTolerance: 1.8,
  heatCap: 101,
  ventTimingSdMs: 110,
  parryChance: 0.25,
  parryTimingSdMs: 90,
  blockChance: 0.5,
  dodgeChance: 0.2,
  strafeMs: [400, 1100],
  coverUse: 0.5,
  flankUse: 0.3,
  aggression: 0.6,
  baitPunish: 0.2,
  decisionMs: 280,
  headAim: 0.15,
  adsRange: 12,
  hearingErrorM: 4,
};

const TRICKS: Record<TrickId, { overrides: BotOverrides; params?: Partial<BotParams> }> = {
  spam: { overrides: { fire: "spam", vent: "never", shield: "never", dodge: "never", action: "fight" } },
  turtle: { overrides: { fire: "never", shield: "always", dodge: "never", action: "push" } },
  blocker: { overrides: { shield: "block", dodge: "never" } },
  camper: { overrides: { action: "camp" } },
  dodger: { overrides: { dodge: "spam" } },
  flicker: { overrides: { shield: "flick", dodge: "never" } },
  rusher: { overrides: { action: "push", dodge: "never" } },
  circle: { overrides: { action: "circle", dodge: "never" } },
  jiggle: { overrides: { strafe: "jiggle" } },
  hider: { overrides: { hideWhenAhead: true } },
  edge: { overrides: { vent: "edge" }, params: { heatCap: 100, ventTimingSdMs: 35 } },
  parrier: { overrides: {}, params: { parryChance: 1, blockChance: 0.15, dodgeChance: 0 } },
  watcher: { overrides: { action: "watch" } },
  kiter: { overrides: { range: 28 }, params: { adsRange: 0, aggression: 0.2 } },
  brawler: { overrides: { range: 6 }, params: { adsRange: 30, aggression: 0.9 } },
};

export const TRICK_IDS = Object.keys(TRICKS) as TrickId[];

export const STRATEGIES: readonly StrategyId[] = ["normal", "hard", "elite", "skilled", "average", ...TRICK_IDS];

function baseParams(base: BaseId): BotParams {
  return base === "skilled" ? { ...SKILLED_HUMAN } : base === "average" ? { ...AVERAGE_HUMAN } : botParams(base);
}

/** Split "skilled+dodger" into its base and trick; a bare trick runs on the hard bot. */
export function parseStrategy(id: StrategyId): { base: BaseId; trick: TrickId | null } {
  const [a, b] = id.split("+") as [string, string | undefined];
  if (b) return { base: a as BaseId, trick: b as TrickId };
  if (a === "normal" || a === "hard" || a === "elite" || a === "skilled" || a === "average") return { base: a, trick: null };
  return { base: "hard", trick: a as TrickId };
}

export function strategy(id: StrategyId): ControllerFactory {
  const { base, trick } = parseStrategy(id);
  // Harness experiments: "rangeN" fights at N metres, "approachN" walks in at N/10 without a reason,
  // "mwN" reads the target's motion over N ms.
  const ranged: { overrides: BotOverrides; params?: Partial<BotParams> } | null =
    trick && /^range\d+$/.test(trick) ? { overrides: { range: Number(trick.slice(5)) } }
    : trick && /^approach\d+$/.test(trick) ? { overrides: { approach: Number(trick.slice(8)) / 10 } }
    : trick && /^mw\d+$/.test(trick) ? { overrides: {}, params: { motionWindowMs: Number(trick.slice(2)) } } : null;
  if (trick && !TRICKS[trick] && !ranged) throw new Error(`unknown strategy ${id}`);
  return (slot, seed, ctx) => {
    const t = ranged ?? (trick ? TRICKS[trick] : null);
    const params = { ...baseParams(base), ...((t && "params" in t ? t.params : undefined) ?? {}) };
    const b = new BotBrain(slot, params, ctx.arena, ctx.tuning, seed, t?.overrides ?? {});
    return { label: id, think: (o) => b.think(o) };
  };
}
