/**
 * The first-person viewmodel's motion and visibility rules (docs/verse/realtime.md,
 * "First-person viewmodel"). Pure state and maths, no three.js:
 *
 * - who is drawn: the commander's own arms in first person, their
 *   third-person body hidden once the camera is close to (or inside) the head;
 * - walk bob: a step dip and a sideways sway per stride, scaled by the ground speed;
 * - idle sway: a slow breathing drift while standing;
 * - look lag: the arms trail a turn of the view a little and settle back;
 * - recoil: a damped spring kicked by every shot (the blaster jumps back and up).
 *
 * prefers-reduced-motion drops the bob, the idle sway and the look lag and
 * halves the recoil. Every offset is in the viewmodel camera's space: x right,
 * y up, z toward the viewer (metres), and pitch (muzzle up), yaw (muzzle left),
 * roll (top to the left) in radians.
 */

/** Below this share of the third ↔ first person blend the third-person body is drawn. */
export const HIDE_BODY_FIRST_SHARE = 0.3;
/** Closer than this behind the pivot (a wall pushed the third-person camera in), the body is hidden too, metres. */
export const HIDE_BODY_BELOW_M = 0.55;

export interface VisibilityInput {
  /** The eye-level view is on screen. */
  eyeOn: boolean;
  /** How far the deck camera has blended into first person (0 third .. 1 first). */
  firstShare: number;
  /** The deck camera's distance behind the commander in third person, metres. */
  thirdDistance: number;
  /** A duel is on: its camera's share of first person (0..1), else null. */
  duelFirstShare: number | null;
}

export interface Visibility {
  /** Draw the viewmodel arms. */
  arms: boolean;
  /** Which arms: the deck's empty hands or the duel's blaster grip. */
  mode: "deck" | "duel";
  /** Hide the commander's (or the duellist's) own third-person body from the eye camera. */
  hideOwnBody: boolean;
  /** 0..1: how far the arms have come up into view (they rise as the camera blends into the head). */
  raise: number;
}

function clamp01(v: number): number {
  return v <= 0 ? 0 : v >= 1 ? 1 : v;
}

function smoothstep(a: number, b: number, v: number): number {
  const t = clamp01((v - a) / (b - a));
  return t * t * (3 - 2 * t);
}

/**
 * Who is drawn this frame. The arms come in once the third-person body is
 * hidden (past HIDE_BODY_FIRST_SHARE of the blend), rising into view as the
 * blend completes, so there is never a frame with both or neither. Pure.
 */
export function viewmodelVisibility(v: VisibilityInput): Visibility {
  if (v.duelFirstShare !== null) {
    const s = clamp01(v.duelFirstShare);
    const hide = s > HIDE_BODY_FIRST_SHARE;
    return { arms: v.eyeOn && hide, mode: "duel", hideOwnBody: hide, raise: smoothstep(HIDE_BODY_FIRST_SHARE, 1, s) };
  }
  const s = clamp01(v.firstShare);
  const first = s > HIDE_BODY_FIRST_SHARE;
  return {
    arms: v.eyeOn && first,
    mode: "deck",
    hideOwnBody: v.eyeOn && (first || v.thirdDistance < HIDE_BODY_BELOW_M),
    raise: smoothstep(HIDE_BODY_FIRST_SHARE, 1, s),
  };
}

export const MOTION = {
  /** Metres walked per step: the bob dips once per step and sways once per stride (two steps). */
  stepM: 0.75,
  /** Bob at walking speed: vertical dip, sideways sway (metres) and roll (radians). */
  bobY: 0.011,
  bobX: 0.008,
  bobRoll: 0.018,
  /** The bob grows with speed up to this multiple of a walk (a run). */
  bobMax: 1.7,
  /** Time constant of the bob's fade in and out, seconds. */
  bobEaseS: 0.12,
  /** Idle breathing: vertical and sideways drift (metres), periods (seconds). */
  idleY: 0.0022,
  idleX: 0.0016,
  idlePeriodY: 3.9,
  idlePeriodX: 6.3,
  /** Look lag: share of a turn the arms trail (radians per radian), its limit and settle time. */
  lagGain: 0.55,
  lagMax: 0.07,
  lagS: 0.09,
  /** Sideways and vertical shift per radian of lag, metres. */
  lagShift: 0.22,
  /** Recoil spring: stiffness and damping (per second²/per second); a shot's kick (velocity). */
  recoilK: 380,
  recoilC: 30,
  recoilKick: 6.5,
  /** Recoil per unit of spring displacement: back (metres), muzzle up (radians). */
  recoilBack: 0.2,
  recoilPitch: 0.4,
  recoilUp: 0.04,
  /** Aiming down the sights: share of bob, sway and recoil that is left. */
  adsCalm: 0.25,
  adsRecoil: 0.5,
  /** Reduced motion: share of the recoil that is left. */
  reducedRecoil: 0.5,
} as const;

export interface Offsets {
  x: number;
  y: number;
  z: number;
  pitch: number;
  yaw: number;
  roll: number;
}

export function zeroOffsets(out?: Offsets): Offsets {
  const o = out ?? { x: 0, y: 0, z: 0, pitch: 0, yaw: 0, roll: 0 };
  o.x = 0; o.y = 0; o.z = 0; o.pitch = 0; o.yaw = 0; o.roll = 0;
  return o;
}

/**
 * The walk bob at stride `phase` (radians; π per step) and `amount` (1 at a
 * walk): the arms dip at every footfall and sway toward the planted foot once
 * per stride. Added into `out`. Pure.
 */
export function walkBob(phase: number, amount: number, out: Offsets): Offsets {
  const s = Math.sin(phase);
  const c = Math.cos(phase);
  out.y -= MOTION.bobY * amount * s * s;
  out.x += MOTION.bobX * amount * c;
  out.roll += MOTION.bobRoll * amount * c;
  return out;
}

/** The idle breathing drift at time `t` seconds, scaled by `amount` (0..1). Added into `out`. Pure. */
export function idleSway(t: number, amount: number, out: Offsets): Offsets {
  out.y += MOTION.idleY * amount * Math.sin((t * 2 * Math.PI) / MOTION.idlePeriodY);
  out.x += MOTION.idleX * amount * Math.sin((t * 2 * Math.PI) / MOTION.idlePeriodX + 0.7);
  out.roll += 0.004 * amount * Math.sin((t * 2 * Math.PI) / MOTION.idlePeriodX);
  return out;
}

/**
 * One step of a damped spring pulled to 0 (semi-implicit Euler in sub-steps
 * of at most 1/120 s, so a slow frame never blows it up). Pure; returns the
 * new [position, velocity].
 */
export function springStep(x: number, v: number, dt: number, k: number, c: number): [number, number] {
  let left = Math.max(0, dt);
  while (left > 1e-9) {
    const h = Math.min(left, 1 / 120);
    v += (-k * x - c * v) * h;
    x += v * h;
    left -= h;
  }
  return [x, v];
}

export interface MotionInput {
  /** Seconds since the last frame. */
  dt: number;
  /** Ground speed, metres per second. */
  speed: number;
  /** The body's walking speed (the bob is 1 at it). */
  walkSpeed: number;
  /** How far the view turned this frame, radians: yaw positive to the right, pitch positive up. */
  turnYaw: number;
  turnPitch: number;
  /** Aiming down the sights, 0..1. */
  ads: number;
  /** prefers-reduced-motion. */
  reduced: boolean;
}

/**
 * The viewmodel's own motion over time: stride phase, eased bob amount, look
 * lag and the recoil spring. `step` once per frame, `fire` per shot; read
 * `offsets` after a step.
 */
export class ViewmodelMotion {
  readonly offsets: Offsets = zeroOffsets();
  /** Stride phase, radians (π per step). */
  phase = 0;
  /** The bob's eased amount (0 standing .. bobMax running). */
  bob = 0;
  /** Look lag, radians (yaw positive right, pitch positive up). */
  lagYaw = 0;
  lagPitch = 0;
  /** Recoil spring displacement and velocity. */
  recoil = 0;
  recoilV = 0;
  /** Seconds of motion so far (the idle breathing's clock). */
  time = 0;

  /** A shot: kick the recoil spring (`strength` 1 at the hip). */
  fire(strength = 1): void {
    this.recoilV += MOTION.recoilKick * strength;
  }

  step(m: MotionInput): Offsets {
    const dt = Math.min(0.1, Math.max(0, m.dt));
    this.time += dt;
    const calm = 1 - (1 - MOTION.adsCalm) * clamp01(m.ads);
    // Bob: the phase walks with the ground covered; the amount eases toward the speed's share of a walk.
    const speed = Number.isFinite(m.speed) ? Math.max(0, m.speed) : 0;
    this.phase = (this.phase + (speed * dt * Math.PI) / MOTION.stepM) % (Math.PI * 2);
    const wantBob = m.reduced ? 0 : Math.min(MOTION.bobMax, speed / Math.max(0.1, m.walkSpeed));
    this.bob += (wantBob - this.bob) * (1 - Math.exp(-dt / MOTION.bobEaseS));
    // Look lag: the turn piles up and decays; the arms trail it (a turn of the view leaves them behind).
    const k = Math.exp(-dt / MOTION.lagS);
    if (m.reduced) {
      this.lagYaw = 0;
      this.lagPitch = 0;
    } else {
      const ty = Number.isFinite(m.turnYaw) ? m.turnYaw : 0;
      const tp = Number.isFinite(m.turnPitch) ? m.turnPitch : 0;
      this.lagYaw = clampAbs((this.lagYaw + ty * MOTION.lagGain) * k, MOTION.lagMax);
      this.lagPitch = clampAbs((this.lagPitch + tp * MOTION.lagGain) * k, MOTION.lagMax);
    }
    [this.recoil, this.recoilV] = springStep(this.recoil, this.recoilV, dt, MOTION.recoilK, MOTION.recoilC);

    const o = zeroOffsets(this.offsets);
    walkBob(this.phase, this.bob * calm, o);
    if (!m.reduced) idleSway(this.time, calm, o);
    // Turning right leaves the arms to the left and turned right-to-left; looking up leaves them low.
    o.x -= this.lagYaw * MOTION.lagShift * calm;
    o.y -= this.lagPitch * MOTION.lagShift * calm;
    o.yaw += this.lagYaw * 0.6 * calm;
    o.pitch -= this.lagPitch * 0.4 * calm;
    o.roll -= this.lagYaw * 0.5 * calm;
    const kick = this.recoil * (m.reduced ? MOTION.reducedRecoil : 1) * (1 - (1 - MOTION.adsRecoil) * clamp01(m.ads));
    o.z += kick * MOTION.recoilBack;
    o.pitch += kick * MOTION.recoilPitch;
    o.y += kick * MOTION.recoilUp;
    return o;
  }

  /** Back to rest (a new match, the view changed person). */
  reset(): void {
    this.phase = 0;
    this.bob = 0;
    this.lagYaw = 0;
    this.lagPitch = 0;
    this.recoil = 0;
    this.recoilV = 0;
    zeroOffsets(this.offsets);
  }
}

function clampAbs(v: number, max: number): number {
  return v > max ? max : v < -max ? -max : v;
}

/**
 * The view's turn between two frames from its directions (yaw about +Y with 0
 * facing +Z, pitch positive up): yaw positive for a turn to the right. A jump
 * larger than `maxJump` (a respawn, a cut) counts as no turn. Pure.
 */
export function turnBetween(prevYaw: number, prevPitch: number, yaw: number, pitch: number, maxJump = 0.6): { yaw: number; pitch: number } {
  // The deck's yaw grows to the left (toward +X when facing +Z), so a right turn lowers it.
  const dy = -Math.atan2(Math.sin(yaw - prevYaw), Math.cos(yaw - prevYaw));
  const dp = pitch - prevPitch;
  if (Math.abs(dy) > maxJump || Math.abs(dp) > maxJump) return { yaw: 0, pitch: 0 };
  return { yaw: dy, pitch: dp };
}
