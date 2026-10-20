/**
 * Walking along a path and keeping out of each other's way. Pure.
 *
 * A body walks its string-pulled path leg by leg at its own pace; turning is
 * eased so nobody snaps round a corner. Local avoidance is a gentle sideways
 * step away from bodies close ahead plus slowing behind someone walking the
 * same way; a step is only taken onto walkable floor.
 */
import type { NavGrid } from "../content/deck";
import { isWalkable, type Point } from "../nav/pathfind";

export interface Mover {
  x: number;
  z: number;
  /** Facing, radians about +Y (0 faces +Z). */
  yaw: number;
}

/** Yaw that faces from a toward b. */
export function yawTo(ax: number, az: number, bx: number, bz: number): number {
  return Math.atan2(bx - ax, bz - az);
}

/** An angle brought into (−π, π]. */
export function wrapAngle(a: number): number {
  const t = Math.PI * 2;
  let w = ((a % t) + t) % t;
  if (w > Math.PI) w -= t;
  return w;
}

/** Shortest signed angle from a to b, in (−π, π]. */
export function angleDelta(a: number, b: number): number {
  return wrapAngle(b - a);
}

/** Turn toward `target` at most `rate` rad/s, eased; the result stays in (−π, π]. */
export function turnToward(yaw: number, target: number, rate: number, dtS: number): number {
  const d = angleDelta(yaw, target);
  const step = Math.sign(d) * Math.min(Math.abs(d), rate * dtS, Math.abs(d) * Math.min(1, dtS * 10));
  return wrapAngle(yaw + step);
}

/** The angle a fraction `t` of the short way from a to b. */
export function lerpAngle(a: number, b: number, t: number): number {
  return wrapAngle(a + angleDelta(a, b) * t);
}

/**
 * How fast a walker may go while still turning toward its heading: full pace
 * when facing it, down to 35 % at a right angle or more, so feet do not slide
 * through a sharp corner. Pure.
 */
export function turnPace(yaw: number, heading: number): number {
  const off = Math.min(Math.PI / 2, Math.abs(angleDelta(yaw, heading)));
  return 0.35 + 0.65 * Math.cos(off);
}

export class PathFollower {
  private index = 1;

  constructor(readonly points: readonly Point[]) {}

  get done(): boolean {
    return this.index >= this.points.length;
  }

  /** The point the body is heading for, or null at the end. */
  get next(): Point | null {
    return this.done ? null : this.points[this.index];
  }

  get end(): Point {
    return this.points[this.points.length - 1];
  }

  /** Metres left along the path from `at`. */
  remaining(at: Point): number {
    if (this.done) return 0;
    let total = Math.hypot(this.points[this.index].x - at.x, this.points[this.index].z - at.z);
    for (let i = this.index + 1; i < this.points.length; i++) {
      total += Math.hypot(this.points[i].x - this.points[i - 1].x, this.points[i].z - this.points[i - 1].z);
    }
    return total;
  }

  /** Move `distance` metres along the path from `at`; returns the new position. */
  advance(at: Point, distance: number): Point {
    let pos = at;
    let left = distance;
    while (!this.done && left > 0) {
      const target = this.points[this.index];
      const d = Math.hypot(target.x - pos.x, target.z - pos.z);
      if (d <= left) {
        pos = target;
        left -= d;
        this.index++;
      } else {
        pos = { x: pos.x + ((target.x - pos.x) / d) * left, z: pos.z + ((target.z - pos.z) / d) * left };
        left = 0;
      }
    }
    return pos;
  }
}

export interface Neighbour { x: number; z: number; moving: boolean }

/** Personal space, metres. */
export const BODY_RADIUS = 0.32;
const LOOK_AHEAD = 1.1;

/**
 * How a walker adjusts this frame: a sideways offset (metres per second,
 * perpendicular to its heading) and a speed factor, from the bodies near it.
 */
export function avoidance(self: Mover, neighbours: readonly Neighbour[]): { side: number; speed: number } {
  const fx = Math.sin(self.yaw);
  const fz = Math.cos(self.yaw);
  let side = 0;
  let speed = 1;
  for (const n of neighbours) {
    const dx = n.x - self.x;
    const dz = n.z - self.z;
    const d = Math.hypot(dx, dz);
    if (d < 1e-4 || d > LOOK_AHEAD) continue;
    const ahead = dx * fx + dz * fz;
    if (ahead <= 0) continue;
    // Lateral offset of the other body from our line: left is positive.
    const lateral = dx * fz - dz * fx;
    if (Math.abs(lateral) > BODY_RADIUS * 2.2) continue;
    const closeness = 1 - d / LOOK_AHEAD;
    // Step to the side the other body is not on (to the right when dead ahead).
    side += (lateral >= 0 ? -1 : 1) * closeness * 0.9;
    if (n.moving && d < BODY_RADIUS * 3) speed = Math.min(speed, 0.45 + 0.55 * (d / (BODY_RADIUS * 3)));
    if (!n.moving && d < BODY_RADIUS * 2) speed = Math.min(speed, 0.6);
  }
  return { side: Math.max(-1, Math.min(1, side)), speed };
}

/** Apply a sideways step only where it stays on walkable floor. */
export function sidestep(grid: NavGrid, pos: Point, yaw: number, metres: number): Point {
  if (Math.abs(metres) < 1e-5) return pos;
  // Left of the heading is (cos yaw, −sin yaw).
  const moved = { x: pos.x + Math.cos(yaw) * metres, z: pos.z - Math.sin(yaw) * metres };
  return isWalkable(grid, moved.x, moved.z) ? moved : pos;
}
