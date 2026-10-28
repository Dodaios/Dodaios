/**
 * What a duellist's body plays, frame by frame: the animation state of one
 * fighter, pure and three.js-free (the figure applies it to the skeleton).
 *
 * Layers, in the order the figure applies them:
 *
 * - **Base** (weights sum to 1): the ready stance (or the low cover stance),
 *   a step-turn when the aim swings far round a standing body, eight-way
 *   locomotion from two gaits (combat walk and run, four headings each) plus
 *   the sprint, and the one-shots that own the whole body: the dodge roll,
 *   the knockout fall and the get-up. Locomotion clips share one normalised
 *   phase (0 = left foot down) that advances at ground speed over the blended
 *   stride, so the planted feet hold still at any speed and heading.
 * - **Additive**: directional flinches and the stagger after eating one's own
 *   reflected bolt.
 * - **Procedural** (the figure): the aim offset over spine, chest and head,
 *   the blaster in both hands by IK (ready, sights, sprint carry, lowered
 *   behind the shield, tipped while venting, low behind cover), recoil kicks,
 *   the shield arm, a lean into acceleration and a peek lean out of cover.
 *
 * The clips come from the character pipeline (`art/verse/characters/anim_combat.py`).
 */
import { clamp, wrapAngle } from "../combat/math";

/** Clip names of the duel set (the character contract owns them). */
export const DUEL_CLIPS = {
  idle: "A_Combat_Idle",
  cover: "A_Combat_Cover",
  sprint: "A_Combat_Sprint",
  turnL: "A_Combat_Turn_L",
  turnR: "A_Combat_Turn_R",
  roll: "A_Combat_Roll",
  death: "A_Combat_Death",
  getUp: "A_Combat_GetUp",
  stagger: "A_Combat_Stagger",
  hitF: "A_Combat_Hit_F",
  hitB: "A_Combat_Hit_B",
  hitL: "A_Combat_Hit_L",
  hitR: "A_Combat_Hit_R",
} as const;

export const ADDITIVE_CLIPS: readonly string[] = [DUEL_CLIPS.stagger, DUEL_CLIPS.hitF, DUEL_CLIPS.hitB, DUEL_CLIPS.hitL, DUEL_CLIPS.hitR];

/** Clip lengths and timings (seconds), as authored. */
export const TIMING = {
  turn: 0.6,
  /** A step-turn turns the body this far (radians). */
  turnAngle: Math.PI / 2,
  roll: 0.6,
  /** The sim's roll lasts this long; the clip's recovery runs on after it. */
  rollSim: 0.4,
  death: 1.4,
  getUp: 1.5,
  hit: 0.5,
  stagger: 1.0,
} as const;

/** One locomotion clip: its ground speed (m/s), heading (radians, 0 = forward, + = the body's left), cycle length. */
export interface LocoClip {
  name: string;
  gait: "walk" | "run" | "sprint";
  speed: number;
  heading: number;
  seconds: number;
}

const DEG = Math.PI / 180;
const HEADINGS: ReadonlyArray<readonly ["F" | "L" | "B" | "R", number]> = [["F", 0], ["L", 90], ["B", 180], ["R", -90]];

/** The authored set, for a manifest without speeds. */
export const DEFAULT_LOCO: readonly LocoClip[] = [
  ...HEADINGS.map(([d, h]) => ({ name: `A_Combat_Walk_${d}`, gait: "walk" as const, speed: d === "B" ? 1.872 : 2.4, heading: h * DEG, seconds: 20 / 30 })),
  ...HEADINGS.map(([d, h]) => ({ name: `A_Combat_Run_${d}`, gait: "run" as const, speed: d === "B" ? 3.744 : 4.8, heading: h * DEG, seconds: 18 / 30 })),
  { name: DUEL_CLIPS.sprint, gait: "sprint", speed: 7.0, heading: 0, seconds: 16 / 30 },
];

/** The manifest's clip table (`characters.json` `clips`): loop, seconds and, for locomotion, speed and heading in degrees. */
export type ClipTable = Readonly<Record<string, { loop?: boolean; seconds?: number; speed?: number; heading?: number }>>;

/** The locomotion clips a body can play: the manifest's numbers where it has them, the authored ones otherwise. */
export function locoClips(table: ClipTable | undefined, available: ReadonlySet<string>, scale = 1): LocoClip[] {
  return DEFAULT_LOCO.filter((c) => available.has(c.name)).map((c) => {
    const info = table?.[c.name];
    return {
      ...c,
      speed: (typeof info?.speed === "number" ? info.speed : c.speed) * scale,
      heading: typeof info?.heading === "number" ? info.heading * DEG : c.heading,
      seconds: typeof info?.seconds === "number" && info.seconds > 0 ? info.seconds : c.seconds,
    };
  });
}

export function smootherstep(x: number): number {
  const t = clamp(x, 0, 1);
  return t * t * t * (t * (6 * t - 15) + 10);
}

function smoothstep(x: number): number {
  const t = clamp(x, 0, 1);
  return t * t * (3 - 2 * t);
}

/** Exponential approach of `cur` to `want` at `rate` per second. */
function approach(cur: number, want: number, rate: number, dt: number): number {
  return cur + (want - cur) * (1 - Math.exp(-rate * dt));
}

/**
 * Weights of one gait's headings so that the blended stride points along
 * `angle` (radians, 0 = forward, + = left): the two neighbouring headings,
 * weighted by the angle and their strides. Pure; sums to 1.
 */
export function headingWeights(angle: number, clips: readonly LocoClip[]): Map<string, number> {
  const out = new Map<string, number>();
  if (!clips.length) return out;
  const a = wrapAngle(angle);
  // The two clips whose headings bracket the angle.
  let lo: LocoClip | null = null;
  let hi: LocoClip | null = null;
  let loGap = Infinity;
  let hiGap = Infinity;
  for (const c of clips) {
    const d = wrapAngle(a - c.heading);
    if (d >= 0 && d < loGap) { loGap = d; lo = c; }
    if (d <= 0 && -d < hiGap) { hiGap = -d; hi = c; }
  }
  if (!lo || !hi || lo === hi || loGap + hiGap < 1e-6) {
    const only = lo ?? hi ?? clips[0];
    out.set(only.name, 1);
    return out;
  }
  // Solve w_lo * S_lo * u_lo + w_hi * S_hi * u_hi parallel to u(a).
  const span = loGap + hiGap;
  const sLo = lo.speed * lo.seconds;
  const sHi = hi.speed * hi.seconds;
  const wLo = Math.sin(hiGap) / Math.max(1e-6, sLo);
  const wHi = Math.sin(loGap) / Math.max(1e-6, sHi);
  const sum = wLo + wHi;
  if (sum < 1e-9 || span > Math.PI - 1e-6) {
    out.set(loGap <= hiGap ? lo.name : hi.name, 1);
    return out;
  }
  out.set(lo.name, wLo / sum);
  out.set(hi.name, (out.get(hi.name) ?? 0) + wHi / sum);
  return out;
}

export interface LocoBlend {
  /** Clip name -> weight within locomotion (sums to 1). */
  weights: Map<string, number>;
  /** Ground distance one full cycle covers along the move direction (metres). */
  stride: number;
}

/**
 * The locomotion mix for moving at `speed` (m/s) towards `angle` (body-relative
 * radians): the combat walk below about 2.5 m/s, the run above 3.9, both in
 * between; the sprint (forward only) by `sprint` (0..1). Pure.
 */
export function locomotionBlend(clips: readonly LocoClip[], angle: number, speed: number, sprint: number): LocoBlend {
  const walk = clips.filter((c) => c.gait === "walk");
  const run = clips.filter((c) => c.gait === "run");
  const sprintClip = clips.find((c) => c.gait === "sprint");
  const runShare = walk.length && run.length ? smoothstep((speed - 2.5) / 1.4) : run.length ? 1 : 0;
  const sprintShare = sprintClip ? clamp(sprint, 0, 1) : 0;
  const weights = new Map<string, number>();
  const add = (m: Map<string, number>, k: number) => { for (const [n, w] of m) if (w * k > 0) weights.set(n, (weights.get(n) ?? 0) + w * k); };
  const rest = 1 - sprintShare;
  if (walk.length) add(headingWeights(angle, walk), rest * (1 - runShare));
  if (run.length) add(headingWeights(angle, run), rest * runShare);
  if (sprintClip && sprintShare > 0) weights.set(sprintClip.name, sprintShare);
  // The blended stride: the weighted sum of the clips' per-cycle ground travel vectors.
  let f = 0;
  let l = 0;
  for (const c of clips) {
    const w = weights.get(c.name);
    if (!w) continue;
    const s = c.speed * c.seconds * w;
    f += Math.cos(c.heading) * s;
    l += Math.sin(c.heading) * s;
  }
  return { weights, stride: Math.hypot(f, l) };
}

export type Flinch = "F" | "B" | "L" | "R";

/** Which side a bolt from (fromX, fromZ) hits a body at (x, z) facing `yaw`. Pure. */
export function flinchSide(x: number, z: number, yaw: number, fromX: number, fromZ: number): Flinch {
  const dx = fromX - x;
  const dz = fromZ - z;
  const fwd = dx * Math.sin(yaw) + dz * Math.cos(yaw);
  const left = dx * Math.cos(yaw) - dz * Math.sin(yaw);
  if (Math.abs(fwd) >= Math.abs(left)) return fwd >= 0 ? "F" : "B";
  return left >= 0 ? "L" : "R";
}

/** What the figure knows about its fighter this frame. */
export interface FighterInput {
  x: number;
  z: number;
  vx: number;
  vz: number;
  aimYaw: number;
  aimPitch: number;
  alive: boolean;
  dodging: boolean;
  /** 0..1 through the sim's roll. */
  dodgeProgress: number;
  sprinting: boolean;
  shieldUp: boolean;
  /** 0..1 into the sights. */
  ads: number;
  venting: boolean;
  /** Bot presentation: hiding low behind cover, or peeking out of it to this side (+1 left, -1 right). */
  cover?: "hide" | "peek" | null;
  peekSide?: number;
}

export interface ClipWeight {
  name: string;
  weight: number;
  /** Seconds into the clip. */
  time: number;
}

export interface FighterFrame {
  /** The root's facing (the legs' way), radians. */
  legsYaw: number;
  base: ClipWeight[];
  additive: ClipWeight[];
  /** 0..1: the arms hold the blaster by IK (0 while a one-shot owns the body). */
  ik: number;
  /** Aim relative to the legs (radians) for the spine and head. */
  twist: number;
  pitch: number;
  /** Lean into acceleration (radians; forward, to the left). */
  leanFwd: number;
  leanSide: number;
  /** Blaster carries, 0..1 each. */
  ads: number;
  sprint: number;
  shield: number;
  vent: number;
  cover: number;
  /** 0..1 through the vent's hand motion (reach, pull, back). */
  ventPull: number;
  /** Recoil kick, about 0..1. */
  recoil: number;
  /** The shield arm's shove of a perfect parry, 0..1. */
  parryPush: number;
  /** Lean out of cover (-1 right .. +1 left). */
  peek: number;
  /** Locomotion share of the base layer and its phase (0..1). */
  moving: number;
  phase: number;
}

interface OneShot { t: number; weight: number }

/** Seconds from a shot to the recoil's peak. */
const RECOIL_TAU = 0.045;

/**
 * The animation state of one fighter. Feed it every rendered frame
 * (`update`) and the frame's combat events (`shot`, `hit`, ...).
 */
export class FighterAnimator {
  private legsYaw = 0;
  private primed = false;
  private clock = 0;
  private phase = 0;
  private moveW = 0;
  private sprintW = 0;
  private shieldW = 0;
  private ventW = 0;
  private coverW = 0;
  private peekW = 0;
  private ventT = 0;
  private wasVenting = false;
  private turn: { t: number; sign: number; from: number } | null = null;
  private turnW = 0;
  private roll: { t: number; yaw: number } | null = null;
  private rollW = 0;
  private death: { t: number; yaw: number } | null = null;
  private getUp: { t: number } | null = null;
  private wasAlive = true;
  private readonly hits = new Map<string, OneShot>();
  /** Shots still kicking: age (s) and size. */
  private readonly kicks: { age: number; size: number }[] = [];
  private parryT = 1;
  private accF = 0;
  private accL = 0;
  private prevVx = 0;
  private prevVz = 0;
  private readonly frame: FighterFrame = {
    legsYaw: 0, base: [], additive: [], ik: 1, twist: 0, pitch: 0, leanFwd: 0, leanSide: 0,
    ads: 0, sprint: 0, shield: 0, vent: 0, cover: 0, ventPull: 0, recoil: 0, parryPush: 0, peek: 0, moving: 0, phase: 0,
  };

  constructor(private readonly loco: readonly LocoClip[], private readonly has: (name: string) => boolean = () => true) {}

  /** A shot left this fighter's blaster. */
  shot(ads: boolean): void {
    this.kicks.push({ age: 0, size: ads ? 0.65 : 1 });
  }

  /** A bolt hit this fighter from (fromX, fromZ); `stagger` when it was their own bolt parried back at them. */
  hit(x: number, z: number, fromX: number, fromZ: number, headshot: boolean, stagger: boolean): void {
    if (!this.wasAlive) return;
    const side = flinchSide(x, z, this.legsYaw, fromX, fromZ);
    const name = { F: DUEL_CLIPS.hitF, B: DUEL_CLIPS.hitB, L: DUEL_CLIPS.hitL, R: DUEL_CLIPS.hitR }[side];
    this.hits.set(name, { t: 0, weight: headshot ? 1.35 : 1 });
    if (stagger) this.hits.set(DUEL_CLIPS.stagger, { t: 0, weight: 1 });
  }

  /** This fighter parried a bolt (the shield arm shoves). */
  parried(): void {
    this.parryT = 0;
  }

  /** Knocked out by a shooter standing at (fromX, fromZ): the body turns to face them and falls back, away. */
  knockedOut(x: number, z: number, fromX: number, fromZ: number): void {
    if (this.death) return;
    const yaw = Math.hypot(fromX - x, fromZ - z) > 0.05 ? Math.atan2(fromX - x, fromZ - z) : this.legsYaw;
    this.death = { t: 0, yaw };
  }

  /** Advance by `dt` seconds with this frame's fighter state. */
  update(dtS: number, p: FighterInput): FighterFrame {
    const dt = clamp(dtS, 0, 0.1);
    const f = this.frame;
    this.clock += dt;
    if (!this.primed) { this.legsYaw = p.aimYaw; this.primed = true; this.wasAlive = p.alive; }

    // Life: a knockout without its event still falls; a revived body gets up.
    if (!p.alive && !this.death) this.death = { t: 0, yaw: this.legsYaw };
    if (p.alive && !this.wasAlive) {
      this.death = null;
      this.getUp = { t: 0 };
      this.legsYaw = p.aimYaw;
      this.turn = null;
      this.roll = null;
      this.hits.clear();
    }
    this.wasAlive = p.alive;
    if (this.death) this.death.t = Math.min(TIMING.death, this.death.t + dt);
    if (this.getUp) { this.getUp.t += dt; if (this.getUp.t >= TIMING.getUp) this.getUp = null; }

    // Ground motion, relative to the legs, and a smoothed acceleration for the lean.
    const speed = Math.hypot(p.vx, p.vz);
    if (dt > 0) {
      const ax = (p.vx - this.prevVx) / dt;
      const az = (p.vz - this.prevVz) / dt;
      const s = Math.sin(this.legsYaw);
      const c = Math.cos(this.legsYaw);
      this.accF = approach(this.accF, clamp(ax * s + az * c, -60, 60), 10, dt);
      this.accL = approach(this.accL, clamp(ax * c - az * s, -60, 60), 10, dt);
    }
    this.prevVx = p.vx;
    this.prevVz = p.vz;

    // The roll: faces the roll's way, its recovery runs on after the sim's roll.
    if (p.alive && p.dodging) {
      const yaw = speed > 0.5 ? Math.atan2(p.vx, p.vz) : this.roll?.yaw ?? p.aimYaw + Math.PI;
      if (!this.roll || this.roll.t > TIMING.rollSim + 0.05) this.roll = { t: 0, yaw };
      this.roll.t = Math.max(this.roll.t, clamp(p.dodgeProgress, 0, 1) * TIMING.rollSim);
      this.roll.yaw = yaw;
      this.turn = null;
    } else if (this.roll) {
      this.roll.t += dt;
      if (this.roll.t >= TIMING.roll || !p.alive) this.roll = null;
    }
    // In fast, out over the clip's last 0.16 s.
    this.rollW = this.roll
      ? Math.min(1 - smoothstep((this.roll.t - (TIMING.roll - 0.16)) / 0.16), approach(this.rollW, 1, 40, dt))
      : 0;

    // Legs: face the aim while moving (strafe and backpedal clips carry the direction); standing, step-turn when the aim swings far.
    const moving = p.alive && !p.dodging && speed > 0.3;
    const sprinting = p.alive && p.sprinting && speed > 4.5;
    if (this.death) {
      this.legsYaw += wrapAngle(this.death.yaw - this.legsYaw) * Math.min(1, dt * 25);
    } else if (this.roll) {
      this.legsYaw += wrapAngle(this.roll.yaw - this.legsYaw) * (p.dodging ? Math.min(1, dt * 30) : Math.min(1, dt * 12));
    } else if (moving) {
      this.turn = null;
      const want = sprinting ? Math.atan2(p.vx, p.vz) : p.aimYaw;
      this.legsYaw += wrapAngle(want - this.legsYaw) * Math.min(1, dt * 10);
    } else if (this.turn) {
      this.turn.t += dt;
      const k = smootherstep(this.turn.t / TIMING.turn);
      this.legsYaw = this.turn.from + this.turn.sign * TIMING.turnAngle * k;
      if (this.turn.t >= TIMING.turn) this.turn = null;
    } else if (p.alive && !this.getUp) {
      const off = wrapAngle(p.aimYaw - this.legsYaw);
      if (Math.abs(off) > 70 * DEG && this.has(off > 0 ? DUEL_CLIPS.turnL : DUEL_CLIPS.turnR)) {
        this.turn = { t: 0, sign: Math.sign(off), from: this.legsYaw };
      } else if (Math.abs(off) > 70 * DEG) {
        this.legsYaw += off * Math.min(1, dt * 6);
      }
    }
    this.legsYaw = wrapAngle(this.legsYaw);
    this.turnW = approach(this.turnW, this.turn ? 1 : 0, this.turn ? 25 : 12, dt);

    // Locomotion phase: ground speed over the blended stride, so planted feet hold still.
    this.sprintW = approach(this.sprintW, sprinting ? 1 : 0, 8, dt);
    const angle = wrapAngle(Math.atan2(p.vx, p.vz) - this.legsYaw);
    const blend = locomotionBlend(this.loco, angle, speed, this.sprintW);
    if (blend.stride > 1e-3) this.phase = (this.phase + (dt * speed) / blend.stride) % 1;
    this.moveW = approach(this.moveW, moving ? clamp(speed / 0.9, 0, 1) : 0, moving ? 14 : 10, dt);

    // Carries.
    this.shieldW = approach(this.shieldW, p.alive && p.shieldUp ? 1 : 0, p.shieldUp ? 22 : 12, dt);
    this.ventW = approach(this.ventW, p.alive && p.venting ? 1 : 0, p.venting ? 16 : 10, dt);
    if (p.venting && !this.wasVenting) this.ventT = 0;
    this.wasVenting = p.venting;
    this.ventT += dt;
    const hiding = p.cover === "hide" && speed < 0.8;
    this.coverW = approach(this.coverW, p.alive && hiding ? 1 : 0, 6, dt);
    const peek = p.cover === "peek" ? clamp(p.peekSide ?? 0, -1, 1) : 0;
    this.peekW = approach(this.peekW, peek, 7, dt);
    // Recoil: each shot kicks along t/tau * e^(1 - t/tau) (peak 1 at tau), the kicks add up.
    let recoil = 0;
    for (let i = this.kicks.length - 1; i >= 0; i -= 1) {
      const k = this.kicks[i];
      k.age += dt;
      if (k.age > 0.5) { this.kicks.splice(i, 1); continue; }
      const u = k.age / RECOIL_TAU;
      recoil += k.size * u * Math.exp(1 - u);
    }
    this.parryT = Math.min(1, this.parryT + dt / 0.28);
    for (const [name, h] of this.hits) {
      h.t += dt;
      const len = name === DUEL_CLIPS.stagger ? TIMING.stagger : TIMING.hit;
      if (h.t >= len) this.hits.delete(name);
    }

    // Base layer.
    const base = f.base;
    base.length = 0;
    const deathW = this.death ? smoothstep(this.death.t / 0.08) : 0;
    const getUpW = this.getUp ? 1 - smoothstep((this.getUp.t - (TIMING.getUp - 0.3)) / 0.3) : 0;
    const rollW = p.alive ? this.rollW : 0;
    const special = Math.min(1, deathW + getUpW + rollW);
    if (this.death && deathW > 0) base.push({ name: DUEL_CLIPS.death, weight: deathW, time: this.death.t });
    if (this.getUp && getUpW > 0 && !this.death) base.push({ name: DUEL_CLIPS.getUp, weight: getUpW * (1 - deathW), time: this.getUp.t });
    if (this.roll && rollW > 0 && !this.death) base.push({ name: DUEL_CLIPS.roll, weight: rollW, time: this.roll.t });
    const rest = 1 - special;
    const move = rest * this.moveW;
    const stand = rest - move;
    if (move > 0) {
      for (const c of this.loco) {
        const w = blend.weights.get(c.name);
        if (w) base.push({ name: c.name, weight: move * w, time: this.phase * c.seconds });
      }
    }
    if (stand > 0) {
      const turnShare = this.turn ? this.turnW : 0;
      if (turnShare > 0 && this.turn) {
        base.push({ name: this.turn.sign > 0 ? DUEL_CLIPS.turnL : DUEL_CLIPS.turnR, weight: stand * turnShare, time: Math.min(this.turn.t, TIMING.turn) });
      }
      const still = stand * (1 - turnShare);
      if (this.coverW > 0.001) base.push({ name: DUEL_CLIPS.cover, weight: still * this.coverW, time: this.clock % 2 });
      base.push({ name: DUEL_CLIPS.idle, weight: still * (1 - this.coverW), time: this.clock % 2 });
    }

    const additive = f.additive;
    additive.length = 0;
    if (p.alive) for (const [name, h] of this.hits) additive.push({ name, weight: h.weight, time: h.t });

    f.legsYaw = this.legsYaw;
    f.ik = p.alive ? clamp(1 - special * 1.15, 0, 1) : 0;
    f.twist = clamp(wrapAngle(p.aimYaw - this.legsYaw), -100 * DEG, 100 * DEG) * (1 - special);
    f.pitch = p.aimPitch * (1 - special);
    f.leanFwd = clamp(this.accF * 0.006, -0.16, 0.16) * (1 - special);
    f.leanSide = clamp(this.accL * 0.005, -0.14, 0.14) * (1 - special);
    f.ads = p.alive ? clamp(p.ads, 0, 1) : 0;
    f.sprint = this.sprintW;
    f.shield = this.shieldW;
    f.vent = this.ventW;
    f.cover = this.coverW * (1 - this.moveW);
    f.ventPull = p.venting ? clamp(this.ventT / 0.55, 0, 1) : 1;
    f.recoil = clamp(recoil, 0, 1.6);
    f.parryPush = this.parryT < 1 ? Math.sin(Math.PI * this.parryT) : 0;
    f.peek = this.peekW;
    f.moving = move;
    f.phase = this.phase;
    return f;
  }
}
