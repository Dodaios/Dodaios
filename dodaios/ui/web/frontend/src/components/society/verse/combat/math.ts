/**
 * Small math for the combat core, in the deck's frame: x to the right, z
 * toward the camera, y up, metres. Yaw is radians about +Y with 0 facing +Z
 * (the socket convention), pitch is radians with positive looking up.
 */

export const DEG = Math.PI / 180;
export const TAU = Math.PI * 2;

export interface Vec2 { x: number; z: number }
export interface Vec3 { x: number; y: number; z: number }

export function clamp(v: number, lo: number, hi: number): number {
  return v < lo ? lo : v > hi ? hi : v;
}

export function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

/** Angle in (-PI, PI]. */
export function wrapAngle(a: number): number {
  a = a % TAU;
  if (a <= -Math.PI) a += TAU;
  else if (a > Math.PI) a -= TAU;
  return a;
}

/** Signed shortest difference b - a. */
export function angleDiff(a: number, b: number): number {
  return wrapAngle(b - a);
}

export function lerpAngle(a: number, b: number, t: number): number {
  return a + angleDiff(a, b) * t;
}

/** Yaw that faces along (dx, dz). */
export function yawOf(dx: number, dz: number): number {
  return Math.atan2(dx, dz);
}

/** Forward on the floor for a yaw. */
export function forwardX(yaw: number): number { return Math.sin(yaw); }
export function forwardZ(yaw: number): number { return Math.cos(yaw); }
/** Right-hand side on the floor for a yaw (forward x up). */
export function rightX(yaw: number): number { return -Math.cos(yaw); }
export function rightZ(yaw: number): number { return Math.sin(yaw); }

/** Unit direction for yaw and pitch. */
export function dirFromAngles(yaw: number, pitch: number): Vec3 {
  const c = Math.cos(pitch);
  return { x: Math.sin(yaw) * c, y: Math.sin(pitch), z: Math.cos(yaw) * c };
}

/** Yaw and pitch of a direction. */
export function anglesOf(dx: number, dy: number, dz: number): { yaw: number; pitch: number } {
  return { yaw: Math.atan2(dx, dz), pitch: Math.atan2(dy, Math.hypot(dx, dz)) };
}

/** Move `v` toward `target` by at most `step`. */
export function approach(v: number, target: number, step: number): number {
  return v < target ? Math.min(target, v + step) : Math.max(target, v - step);
}

/** Round to a fixed grid of 1/scale (snapshot quantisation). */
export function q(v: number, scale: number): number {
  // + 0 turns -0 into 0, so JSON round trips are exact.
  return Math.round(v * scale) / scale + 0;
}
