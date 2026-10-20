/**
 * Walking along a route: a body turns towards its next waypoint (and slows
 * while it is still turning), keeps a steady pace, gives way to other bodies
 * in front of it and lands exactly on its last waypoint.
 */
import type { Vec2 } from "../plan/types";

export interface Body {
  x: number;
  z: number;
  yaw: number;
  path: Vec2[];
  /** Current speed (m/s). */
  speed: number;
  /** Walk cycle, in strides. */
  phase: number;
}

export const BODY_GAP = 0.6;
const TURN_RATE = 7;

export function wrapAngle(a: number): number {
  return Math.atan2(Math.sin(a), Math.cos(a));
}

export function turnTowards(yaw: number, goal: number, dt: number, rate = TURN_RATE): number {
  const d = wrapAngle(goal - yaw);
  const step = Math.sign(d) * Math.min(Math.abs(d), rate * dt);
  return wrapAngle(yaw + step);
}

/**
 * Advance `body` along its path for `dt` seconds at up to `pace` m/s.
 * `blocked(x, z)` reports another body in the way. Returns true on arrival
 * (the path is empty).
 */
export function stepAlong(body: Body, dt: number, pace: number, blocked?: (x: number, z: number) => boolean): boolean {
  if (body.path.length === 0) { body.speed = 0; return true; }
  const next = body.path[0];
  const dx = next.x - body.x, dz = next.z - body.z;
  const dist = Math.hypot(dx, dz);
  if (dist < 0.02) {
    body.x = next.x; body.z = next.z;
    body.path.shift();
    return body.path.length === 0;
  }
  const heading = Math.atan2(dx, dz);
  body.yaw = turnTowards(body.yaw, heading, dt);
  const off = Math.abs(wrapAngle(heading - body.yaw));
  // Slow down while facing away; ease into the last metre.
  const last = body.path.length === 1;
  const target = pace * Math.max(0.08, Math.cos(Math.min(off, Math.PI / 2))) * (last ? Math.min(1, 0.35 + dist) : 1);
  body.speed += (target - body.speed) * Math.min(1, dt * 6);
  let step = Math.min(dist, body.speed * dt);
  const nx = body.x + (dx / dist) * step, nz = body.z + (dz / dist) * step;
  if (blocked && blocked(nx, nz)) {
    body.speed *= 0.5;
    step = 0;
    return false;
  }
  body.x = nx; body.z = nz;
  body.phase += step / 1.25;
  if (step >= dist - 1e-6) body.path.shift();
  return body.path.length === 0;
}
