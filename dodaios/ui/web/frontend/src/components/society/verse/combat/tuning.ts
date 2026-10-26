/**
 * Every balance number of the duel in one place. Durations are in ticks of
 * the fixed simulation step (60 Hz), speeds in metres per second, angles in
 * degrees, energy/heat/health in points. The defaults are the values the
 * balance harness settled on (docs/verse/combat.md, "Tuned numbers").
 *
 * Server and clients must run the same tuning: the handshake compares
 * `tuningHash`.
 */
import { hash2 } from "./rng";

export const TICK_RATE = 60;
export const TICK_DT = 1 / TICK_RATE;

/** Seconds to whole ticks. */
export function ticks(seconds: number): number {
  return Math.round(seconds * TICK_RATE);
}

export interface BodyTuning {
  /** Movement radius (the arena grid is eroded by it). */
  radius: number;
  /** Bolt hit capsule: radius and the y range of its core segment. */
  hitRadius: number;
  hitBottom: number;
  hitTop: number;
  /** A hit at or above this height is a headshot. */
  headFrom: number;
  eyeHeight: number;
  /** Muzzle offset from the feet: up, forward along the aim, to the right. */
  muzzleHeight: number;
  muzzleForward: number;
  muzzleRight: number;
}

export interface MoveTuning {
  run: number;
  /** Speed factor when moving straight back (lerped by how backward the input is). */
  backMul: number;
  adsMul: number;
  shieldMul: number;
  sprint: number;
  /** Sprint needs the move input within this many degrees of straight ahead. */
  sprintConeDeg: number;
  accel: number;
  decel: number;
  /** After sprinting stops, the blaster comes up after this many ticks. */
  sprintToFireTicks: number;
}

export interface DodgeTuning {
  durationTicks: number;
  distance: number;
  cooldownTicks: number;
  /** Ticks at the start of the roll in which bolts pass through. */
  iframeTicks: number;
  /** Ticks after the roll before the blaster fires again. */
  recoverTicks: number;
}

export interface HealthTuning {
  max: number;
  regenDelayTicks: number;
  regenPerSec: number;
  headshotMul: number;
}

export interface BlasterTuning {
  fireIntervalTicks: number;
  boltSpeed: number;
  boltRadius: number;
  boltMaxRange: number;
  damageNear: number;
  damageFar: number;
  falloffStart: number;
  falloffEnd: number;
  heatPerShot: number;
  heatCoolDelayTicks: number;
  heatCoolPerSec: number;
  /** Forced vent after an overheat, and its perfect-timing window (ticks from the start). */
  overheatTicks: number;
  overheatWindow: readonly [number, number];
  /** Manual vent: base ticks plus ticks per point of heat; the window is a fraction of that. */
  ventBaseTicks: number;
  ventTicksPerHeat: number;
  ventWindowFrac: readonly [number, number];
  /** Cone half-angles (degrees). */
  hipSpreadDeg: number;
  adsSpreadDeg: number;
  /** Extra spread at full run speed. */
  moveSpreadHipDeg: number;
  moveSpreadAdsDeg: number;
  bloomPerShotHipDeg: number;
  bloomPerShotAdsDeg: number;
  bloomMaxHipDeg: number;
  bloomMaxAdsDeg: number;
  bloomRecoverDegPerSec: number;
  bloomRecoverDelayTicks: number;
  /** Recoil kicks the aim up (and a little sideways); it recovers on its own. */
  recoilPitchHipDeg: number;
  recoilPitchAdsDeg: number;
  recoilYawDeg: number;
  recoilRecoverDegPerSec: number;
  adsInTicks: number;
  adsOutTicks: number;
}

export interface ShieldTuning {
  energyMax: number;
  raiseMinEnergy: number;
  raiseCost: number;
  drainPerSec: number;
  /** Energy lost per point of damage a normal block absorbs. */
  blockCostPerDamage: number;
  regenDelayTicks: number;
  regenPerSec: number;
  brokenTicks: number;
  /** The shield covers this half-angle either side of the aim yaw. */
  arcHalfDeg: number;
  radius: number;
  height: number;
  /** A bolt meeting the shield within this many ticks of raising it is parried. */
  parryWindowTicks: number;
  /**
   * Whiff penalty: a raise whose parry window met no bolt leaves the parry
   * window off for raises within this many ticks after it is lowered.
   * Timed parries stay strong; flicking the shield earns nothing.
   */
  parryWhiffLockTicks: number;
  /** Ticks after lowering before it can be raised again. */
  reRaiseTicks: number;
  /** A normal block deflects (instead of absorbing) with this chance. */
  deflectChance: number;
  deflectSpreadDeg: number;
  deflectDamageMul: number;
  parryDamageMul: number;
  parrySpeedMul: number;
  parryAimErrorDeg: number;
  /** A bolt is absorbed instead of reflected once it has been reflected this often. */
  maxReflections: number;
}

export interface MatchTuning {
  roundsToWin: number;
  maxRounds: number;
  countdownTicks: number;
  roundEndTicks: number;
  roundTimeLimitTicks: number;
  /**
   * Anti-stalemate "reactor surge": this long into a round, health stops
   * regenerating and both players' positions are pinged on the HUD every
   * `pingEveryTicks`.
   */
  surgeAfterTicks: number;
  pingEveryTicks: number;
}

export interface LagCompTuning {
  /** Pose history kept for rewinding (ticks). */
  historyTicks: number;
  /** A shot is fast-forwarded through at most this many past ticks. */
  maxRewindTicks: number;
}

export interface CombatTuning {
  body: BodyTuning;
  move: MoveTuning;
  dodge: DodgeTuning;
  health: HealthTuning;
  blaster: BlasterTuning;
  shield: ShieldTuning;
  match: MatchTuning;
  lagComp: LagCompTuning;
}

export const DEFAULT_TUNING: CombatTuning = {
  body: {
    radius: 0.3,
    hitRadius: 0.34,
    hitBottom: 0.34,
    hitTop: 1.46,
    headFrom: 1.5,
    eyeHeight: 1.62,
    muzzleHeight: 1.38,
    muzzleForward: 0.45,
    muzzleRight: 0.22,
  },
  move: {
    run: 4.8,
    backMul: 0.78,
    adsMul: 0.6,
    shieldMul: 0.5,
    sprint: 7.0,
    sprintConeDeg: 50,
    accel: 34,
    decel: 42,
    sprintToFireTicks: ticks(0.15),
  },
  dodge: {
    durationTicks: ticks(0.4),
    distance: 4.0,
    cooldownTicks: ticks(2.0),
    iframeTicks: 0,
    recoverTicks: ticks(0.2),
  },
  health: {
    max: 100,
    regenDelayTicks: ticks(5),
    regenPerSec: 10,
    headshotMul: 1.5,
  },
  blaster: {
    fireIntervalTicks: 12,
    boltSpeed: 60,
    boltRadius: 0.06,
    boltMaxRange: 90,
    damageNear: 15,
    damageFar: 9,
    falloffStart: 12,
    falloffEnd: 32,
    heatPerShot: 9,
    heatCoolDelayTicks: ticks(0.3),
    heatCoolPerSec: 35,
    overheatTicks: ticks(2.5),
    overheatWindow: [ticks(0.9), ticks(1.25)],
    ventBaseTicks: ticks(0.5),
    ventTicksPerHeat: 0.6,
    ventWindowFrac: [0.3, 0.52],
    hipSpreadDeg: 1.6,
    adsSpreadDeg: 0.3,
    moveSpreadHipDeg: 1.0,
    moveSpreadAdsDeg: 0.3,
    bloomPerShotHipDeg: 0.45,
    bloomPerShotAdsDeg: 0.2,
    bloomMaxHipDeg: 3.5,
    bloomMaxAdsDeg: 1.5,
    bloomRecoverDegPerSec: 5,
    bloomRecoverDelayTicks: ticks(0.1),
    recoilPitchHipDeg: 0.55,
    recoilPitchAdsDeg: 0.35,
    recoilYawDeg: 0.2,
    recoilRecoverDegPerSec: 9,
    adsInTicks: ticks(0.18),
    adsOutTicks: ticks(0.12),
  },
  shield: {
    energyMax: 100,
    raiseMinEnergy: 20,
    raiseCost: 6,
    drainPerSec: 8,
    blockCostPerDamage: 0.9,
    regenDelayTicks: ticks(0.9),
    regenPerSec: 20,
    brokenTicks: ticks(3),
    arcHalfDeg: 60,
    radius: 0.8,
    height: 2.0,
    parryWindowTicks: ticks(0.15),
    parryWhiffLockTicks: ticks(1.0),
    reRaiseTicks: ticks(0.4),
    deflectChance: 0.4,
    deflectSpreadDeg: 40,
    deflectDamageMul: 0.5,
    parryDamageMul: 1.0,
    parrySpeedMul: 1.2,
    parryAimErrorDeg: 1.2,
    maxReflections: 3,
  },
  match: {
    roundsToWin: 2,
    maxRounds: 5,
    countdownTicks: ticks(3),
    roundEndTicks: ticks(2.5),
    roundTimeLimitTicks: ticks(90),
    surgeAfterTicks: ticks(40),
    pingEveryTicks: ticks(1.5),
  },
  lagComp: {
    historyTicks: 32,
    maxRewindTicks: 15,
  },
};

/** Deep-merge partial overrides onto a tuning (for tests and the harness). */
export function withTuning(base: CombatTuning, patch: DeepPartial<CombatTuning>): CombatTuning {
  const out = JSON.parse(JSON.stringify(base)) as CombatTuning;
  for (const [group, values] of Object.entries(patch)) {
    if (!values) continue;
    Object.assign((out as unknown as Record<string, object>)[group], values);
  }
  return out;
}

export type DeepPartial<T> = { [K in keyof T]?: T[K] extends object ? Partial<T[K]> : T[K] };

/** Stable hash of a tuning, compared in the handshake. */
export function tuningHash(t: CombatTuning): number {
  const text = JSON.stringify(t);
  let h = 0x811c9dc5;
  for (let i = 0; i < text.length; i++) h = hash2(h, text.charCodeAt(i));
  return h >>> 0;
}
