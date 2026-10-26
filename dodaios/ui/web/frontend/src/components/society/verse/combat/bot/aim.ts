/**
 * The bot's hand on the mouse. It moves its aim toward where it wants to
 * shoot like a person does: speed-limited, settling with some stiffness,
 * with an error that wanders over time (Ornstein-Uhlenbeck) and a bigger
 * error right after acquiring a new target that fades out.
 */
import { angleDiff, clamp, DEG, wrapAngle } from "../math";
import { PITCH_LIMIT } from "../input";
import type { Rng } from "../rng";
import { TICK_DT } from "../tuning";
import type { BotParams } from "./tiers";

export class AimController {
  yaw = 0;
  pitch = 0;
  /** Current wandering error, degrees. */
  private noiseYaw = 0;
  private noisePitch = 0;
  private acqYaw = 0;
  private acqPitch = 0;
  private acqTick = -100000;

  constructor(private readonly params: BotParams, private readonly rng: Rng) {}

  reset(yaw: number, pitch: number): void {
    this.yaw = yaw;
    this.pitch = pitch;
    this.noiseYaw = 0;
    this.noisePitch = 0;
    this.acqYaw = 0;
    this.acqPitch = 0;
  }

  /** A new target: start with a larger error that fades. */
  acquire(tick: number): void {
    const a = this.rng.range(0, Math.PI * 2);
    const m = Math.abs(this.rng.normal(1, 0.35)) * this.params.acquireErrorDeg;
    this.acqYaw = Math.cos(a) * m;
    this.acqPitch = Math.sin(a) * m * 0.5;
    this.acqTick = tick;
  }

  /** Error currently added to the intended aim, degrees. */
  errorDeg(tick: number): { yaw: number; pitch: number } {
    const fade = Math.exp(-((tick - this.acqTick) * TICK_DT * 1000) / Math.max(1, this.params.acquireMs / 3));
    return { yaw: this.noiseYaw + this.acqYaw * fade, pitch: this.noisePitch + this.acqPitch * fade };
  }

  /**
   * One tick toward the intended aim. `noisy` false skips the error (looking
   * around rather than aiming at someone).
   */
  update(tick: number, wantYaw: number, wantPitch: number, noisy: boolean): void {
    const p = this.params;
    const dt = TICK_DT;
    // OU step: x += -k x dt + sd sqrt(2 k dt) N.
    const k = p.aimNoiseRate;
    const s = p.aimNoiseDeg * Math.sqrt(2 * k * dt);
    this.noiseYaw += -k * this.noiseYaw * dt + s * this.rng.normal();
    this.noisePitch += -k * this.noisePitch * dt + s * 0.6 * this.rng.normal();
    let ty = wantYaw;
    let tp = wantPitch;
    if (noisy) {
      const e = this.errorDeg(tick);
      ty += e.yaw * DEG;
      tp += e.pitch * DEG;
    }
    const maxStep = p.turnRateDeg * DEG * dt;
    const blend = 1 - Math.exp(-p.aimStiffness * dt);
    const dy = angleDiff(this.yaw, ty);
    const dp = tp - this.pitch;
    let sy = dy * blend;
    let sp = dp * blend;
    // A small floor so the aim actually arrives instead of creeping forever.
    const floor = 0.02 * DEG;
    if (Math.abs(dy) < floor) sy = dy; else if (Math.abs(sy) < floor) sy = Math.sign(dy) * floor;
    if (Math.abs(dp) < floor) sp = dp; else if (Math.abs(sp) < floor) sp = Math.sign(dp) * floor;
    const mag = Math.hypot(sy, sp);
    if (mag > maxStep) { sy *= maxStep / mag; sp *= maxStep / mag; }
    this.yaw = wrapAngle(this.yaw + sy);
    this.pitch = clamp(this.pitch + sp, -PITCH_LIMIT, PITCH_LIMIT);
  }

  /** Angle between the current aim and a direction, radians. */
  offFrom(yaw: number, pitch: number): number {
    return Math.hypot(angleDiff(this.yaw, yaw) * Math.cos(pitch), this.pitch - pitch);
  }
}
