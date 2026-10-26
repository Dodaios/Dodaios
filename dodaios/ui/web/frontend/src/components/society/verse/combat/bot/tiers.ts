/**
 * Bot difficulty as plain numbers. Every tier is human-like and imperfect:
 * it reacts after a sampled delay, tracks with a wandering error, leads a
 * moving target only partly, mistimes some vents and parries, and decides a
 * few times a second rather than every frame.
 */

export type BotTier = "normal" | "hard" | "elite";

export interface BotParams {
  tier: BotTier;
  /** Delay from first sight (of the opponent or of a bolt) to acting on it, ms: mean and sd. */
  reactionMs: readonly [number, number];
  /** Visual-motor delay while tracking a target already in sight, ms. */
  trackLatencyMs: number;
  /** Wandering aim error (Ornstein-Uhlenbeck): stationary sd in degrees and how fast it wanders (1/s). */
  aimNoiseDeg: number;
  aimNoiseRate: number;
  /** Extra error on acquiring a target, degrees, decaying over `acquireMs`. */
  acquireErrorDeg: number;
  acquireMs: number;
  /** Mouse speed limit (deg/s) and how quickly the aim settles (1/s). */
  turnRateDeg: number;
  aimStiffness: number;
  /** Fraction of the correct lead on a moving target, and the relative noise on its velocity estimate. */
  leadSkill: number;
  leadNoise: number;
  /**
   * The target's motion is read over this many ms (its average velocity), so
   * A-D strafing is aimed at the middle instead of chased; 0 = this instant.
   */
  motionWindowMs: number;
  /** Fraction of the recoil climb pulled back down. */
  recoilComp: number;
  /** Fires when the aim is within this multiple of the target's angular half-width. */
  fireTolerance: number;
  /** Stops firing at this heat (unless finishing a weak opponent). */
  heatCap: number;
  /** Timing error of a vent press, ms (sd). */
  ventTimingSdMs: number;
  /** Chance to try a parry on an incoming bolt it saw, and the timing error, ms (sd). */
  parryChance: number;
  parryTimingSdMs: number;
  /** Chance to hold a block against a stream of bolts it cannot answer. */
  blockChance: number;
  /** Chance to dodge-roll out of a bolt's path it saw coming. */
  dodgeChance: number;
  /** Strafe direction changes every this many ms (range). */
  strafeMs: readonly [number, number];
  /** Weights of the tactics. */
  coverUse: number;
  flankUse: number;
  aggression: number;
  /** Holds fire into a fresh shield and punishes the moment it drops. */
  baitPunish: number;
  /** Re-plans this often, ms. */
  decisionMs: number;
  /** Fraction of engagements aimed at the head. */
  headAim: number;
  /** Aims down sights beyond this distance, metres. */
  adsRange: number;
  /** Error on where a heard shot came from, metres. */
  hearingErrorM: number;
}

export const BOT_TIERS: Readonly<Record<BotTier, BotParams>> = {
  normal: {
    tier: "normal",
    reactionMs: [305, 60],
    trackLatencyMs: 150,
    aimNoiseDeg: 1.6,
    aimNoiseRate: 1.6,
    acquireErrorDeg: 7,
    acquireMs: 650,
    turnRateDeg: 380,
    aimStiffness: 8,
    leadSkill: 0.6,
    leadNoise: 0.35,
    motionWindowMs: 0,
    recoilComp: 0.35,
    fireTolerance: 2.0,
    heatCap: 101,
    ventTimingSdMs: 160,
    parryChance: 0.25,
    parryTimingSdMs: 110,
    blockChance: 0.42,
    dodgeChance: 0.12,
    strafeMs: [700, 1500],
    coverUse: 0.4,
    flankUse: 0.2,
    aggression: 0.5,
    baitPunish: 0.0,
    decisionMs: 320,
    headAim: 0,
    adsRange: 13,
    hearingErrorM: 4,
  },
  hard: {
    tier: "hard",
    reactionMs: [255, 50],
    trackLatencyMs: 120,
    aimNoiseDeg: 1.15,
    aimNoiseRate: 1.9,
    acquireErrorDeg: 4.5,
    acquireMs: 450,
    turnRateDeg: 520,
    aimStiffness: 12,
    leadSkill: 0.8,
    leadNoise: 0.22,
    motionWindowMs: 200,
    recoilComp: 0.7,
    fireTolerance: 1.6,
    heatCap: 86,
    ventTimingSdMs: 85,
    parryChance: 0.45,
    parryTimingSdMs: 65,
    blockChance: 0.6,
    dodgeChance: 0.25,
    strafeMs: [450, 1050],
    coverUse: 0.65,
    flankUse: 0.45,
    aggression: 0.6,
    baitPunish: 0.55,
    decisionMs: 220,
    headAim: 0.15,
    adsRange: 10,
    hearingErrorM: 2.5,
  },
  elite: {
    tier: "elite",
    reactionMs: [215, 40],
    trackLatencyMs: 95,
    aimNoiseDeg: 0.92,
    aimNoiseRate: 2.2,
    acquireErrorDeg: 3.6,
    acquireMs: 340,
    turnRateDeg: 720,
    aimStiffness: 17,
    leadSkill: 0.9,
    leadNoise: 0.14,
    motionWindowMs: 300,
    recoilComp: 0.85,
    fireTolerance: 1.3,
    heatCap: 80,
    ventTimingSdMs: 50,
    parryChance: 0.65,
    parryTimingSdMs: 42,
    blockChance: 0.75,
    dodgeChance: 0.35,
    strafeMs: [300, 820],
    coverUse: 0.85,
    flankUse: 0.7,
    aggression: 0.7,
    baitPunish: 0.9,
    decisionMs: 160,
    headAim: 0.25,
    adsRange: 9,
    hearingErrorM: 1.5,
  },
};

export function botParams(tier: BotTier, patch: Partial<BotParams> = {}): BotParams {
  return { ...BOT_TIERS[tier], ...patch };
}
