/**
 * Walking a figure along a waypoint path at a fixed speed, turning smoothly
 * towards the direction of travel. Pure: callers own the Mover and the clock.
 */
import type { Point } from "./officeLayout";

/** Metres per second. */
export const WALK_SPEED = 1.35;
export const RUN_SPEED = 3.2;
/** Maximum turn rate in radians per second. */
export const TURN_RATE = 10;

export interface Mover {
  x: number;
  z: number;
  /** Rotation about +y; 0 = the figure faces +z. */
  heading: number;
  /** Remaining waypoints; the first one is the next target. */
  path: Point[];
}

const TAU = Math.PI * 2;

/** Wrap an angle into (-π, π]. */
export function wrapAngle(angle: number): number {
  let a = angle % TAU;
  if (a <= -Math.PI) a += TAU;
  else if (a > Math.PI) a -= TAU;
  return a;
}

/** Turn `current` towards `target` along the shorter way by at most `maxStep` radians. */
export function turnToward(current: number, target: number, maxStep: number): number {
  const diff = wrapAngle(target - current);
  if (Math.abs(diff) <= maxStep) return wrapAngle(target);
  return wrapAngle(current + Math.sign(diff) * maxStep);
}

/**
 * Advance the mover by speed × dt metres along its path, consuming reached
 * waypoints. Mutates `m`. `arrived` is true once the path is empty.
 */
export function stepMover(m: Mover, speed: number, dt: number): { moved: number; arrived: boolean } {
  let budget = Math.max(0, speed * dt);
  let moved = 0;
  let dirX = 0, dirZ = 0;
  while (m.path.length > 0 && budget > 0) {
    const next = m.path[0];
    const dx = next.x - m.x, dz = next.z - m.z;
    const dist = Math.hypot(dx, dz);
    if (dist <= budget) {
      m.x = next.x; m.z = next.z;
      budget -= dist; moved += dist;
      m.path.shift();
    } else {
      m.x += (dx / dist) * budget; m.z += (dz / dist) * budget;
      moved += budget; budget = 0;
    }
    if (dist > 1e-9) { dirX = dx; dirZ = dz; }
  }
  // Drop waypoints that coincide with the current position.
  while (m.path.length > 0 && Math.hypot(m.path[0].x - m.x, m.path[0].z - m.z) < 1e-9) m.path.shift();
  if (dirX !== 0 || dirZ !== 0) m.heading = turnToward(m.heading, Math.atan2(dirX, dirZ), TURN_RATE * dt);
  return { moved, arrived: m.path.length === 0 };
}

/** Two bodies never come closer than this (centre to centre), in metres. */
export const BODY_SPACING = 0.62;

/**
 * Local avoidance: a sideways-biased push away from nearby bodies, strongest
 * when they touch. Zero when nobody is within `radius`. Pure.
 */
export function separation(self: Point, heading: number, others: Iterable<Point>, radius = BODY_SPACING * 1.4): Point {
  let x = 0, z = 0;
  const fx = Math.sin(heading), fz = Math.cos(heading);
  for (const o of others) {
    const dx = self.x - o.x, dz = self.z - o.z;
    const d = Math.hypot(dx, dz);
    if (d < 1e-6 || d >= radius) continue;
    const w = (radius - d) / radius;
    x += (dx / d) * w; z += (dz / d) * w;
    // Someone straight ahead: add a sidestep to the right so two walkers pass instead of pushing head-on.
    const ahead = -(dx * fx + dz * fz) / d;
    if (ahead > 0.6) { x += fz * w * 0.8; z += -fx * w * 0.8; }
  }
  return { x, z };
}

/** True when a point keeps the spacing from every other body. */
export function clearOfBodies(p: Point, others: Iterable<Point>, spacing = BODY_SPACING): boolean {
  for (const o of others) if (Math.hypot(p.x - o.x, p.z - o.z) < spacing) return false;
  return true;
}

/**
 * May a figure step from `from` to `next` among `others`? Yes when the step
 * keeps the spacing from everyone, or when every body it would touch there is
 * one it already touches and the step does not bring it closer. Only touching
 * bodies count: a far-away figure must never veto the way out of a crowd,
 * or someone pinned in a corner could not move at all.
 */
export function stepClearOfBodies(next: Point, from: Point, others: Iterable<Point>, spacing = BODY_SPACING): boolean {
  for (const o of others) {
    const after = Math.hypot(next.x - o.x, next.z - o.z);
    if (after >= spacing) continue;
    if (after < Math.hypot(from.x - o.x, from.z - o.z)) return false;
  }
  return true;
}

/**
 * Nudge a mover sideways out of others' way, only onto walkable ground.
 * Called after `stepMover`; the path pulls it back on the next frames.
 */
export function applySeparation(m: Mover, push: Point, dt: number, walkable: (p: Point) => boolean, maxSpeed = 0.9): void {
  const len = Math.hypot(push.x, push.z);
  if (len < 1e-6) return;
  const step = Math.min(len, 1) * maxSpeed * dt;
  const nx = m.x + (push.x / len) * step, nz = m.z + (push.z / len) * step;
  if (walkable({ x: nx, z: nz })) { m.x = nx; m.z = nz; }
}

/**
 * Walk the path while steering around other bodies: the heading blends the
 * next waypoint with a push away from anyone close, and the walker slows when
 * someone stands right ahead. Falls back to plain path following whenever the
 * steered step would leave walkable ground.
 */
export function stepMoverAvoiding(m: Mover, speed: number, dt: number, others: readonly Point[], walkable: (p: Point) => boolean): { moved: number; arrived: boolean } {
  if (m.path.length === 0) return { moved: 0, arrived: true };
  const next = m.path[0];
  const dx = next.x - m.x, dz = next.z - m.z;
  const dist = Math.hypot(dx, dz);
  const push = separation(m, m.heading, others, 1.2);
  const pushLen = Math.hypot(push.x, push.z);
  if (pushLen < 1e-3 || dist < 0.2) return stepMover(m, speed, dt);
  let ax = dx / dist + push.x * 1.6, az = dz / dist + push.z * 1.6;
  const len = Math.hypot(ax, az) || 1;
  ax /= len; az /= len;
  // Slow down while someone blocks the way ahead.
  let slow = 1;
  for (const o of others) {
    const ox = o.x - m.x, oz = o.z - m.z;
    const d = Math.hypot(ox, oz);
    if (d < 0.95 && d > 1e-6 && (ox * dx + oz * dz) / (d * dist) > 0.7) slow = Math.min(slow, Math.max(0.25, (d - BODY_SPACING) / 0.4));
  }
  const step = Math.min(speed * slow * dt, dist);
  const cand = { x: m.x + ax * step, z: m.z + az * step };
  if (!walkable(cand)) return stepMover(m, speed, dt);
  m.x = cand.x; m.z = cand.z;
  if (Math.hypot(next.x - m.x, next.z - m.z) < 0.12) m.path.shift();
  m.heading = turnToward(m.heading, Math.atan2(ax, az), TURN_RATE * dt);
  return { moved: step, arrived: m.path.length === 0 };
}

/** An agent's pace on a long leg: a walk across the campus is brisk, a few steps in the studio are not. */
export const BRISK_SPEED = 2.1;
const BRISK_FROM_M = 9;
const BRISK_FULL_M = 26;

/** Walking speed for a route with `remaining` metres left: WALK_SPEED on short legs, up to BRISK_SPEED on long ones. */
export function paceFor(remaining: number): number {
  const t = Math.min(1, Math.max(0, (remaining - BRISK_FROM_M) / (BRISK_FULL_M - BRISK_FROM_M)));
  return WALK_SPEED + (BRISK_SPEED - WALK_SPEED) * t;
}

/** An agent on its way to its screen walks briskly from this much route on. */
const HURRY_FROM_M = 3;
const HURRY_FULL_M = 8;

/**
 * The pace of an agent that has somewhere it must be (its screen, once it
 * works): brisk on anything but the last steps. A working agent that strolls
 * home from the far end of the campus is "working" and absent for too long.
 */
export function hurryPaceFor(remaining: number): number {
  const t = Math.min(1, Math.max(0, (remaining - HURRY_FROM_M) / (HURRY_FULL_M - HURRY_FROM_M)));
  return Math.max(paceFor(remaining), WALK_SPEED + (BRISK_SPEED - WALK_SPEED) * t);
}

/** The person's click-to-move jogs while more than this much route is left, and has settled to a walk by the last metres. */
const CLICK_JOG_FULL_M = 22;
const CLICK_WALK_WITHIN_M = 7;

/**
 * The pace of the person's character on a click-to-move route with
 * `remaining` metres left: `walk` near the target, `run` on a long way, a
 * smooth change in between. A long click crosses the campus at a jog; the
 * last steps are a walk, so the character does not overshoot what it was
 * sent to.
 */
export function clickPaceFor(remaining: number, walk: number, run: number): number {
  const t = Math.min(1, Math.max(0, (remaining - CLICK_WALK_WITHIN_M) / (CLICK_JOG_FULL_M - CLICK_WALK_WITHIN_M)));
  return walk + (run - walk) * t;
}

/** Above this angle between where a figure faces and where it must go, it turns before it walks. */
const TURN_FIRST_RAD = 0.5;
/** The crawl left while turning on the spot, as a share of the pace: feet never glide sideways. */
const TURN_CRAWL = 0.08;
/** Avoidance fades out this close to the route's end, so a figure can reach a place beside a seated colleague. */
const AVOID_FADE_M = 1.5;
/** A waypoint a steered figure passed this closely counts as reached. */
const WAYPOINT_REACH_M = 0.14;

export interface WalkStep {
  /** Metres actually covered this step. */
  moved: number;
  arrived: boolean;
  /** Nothing was free: a body or a wall is in the way. */
  blocked: boolean;
  /** Steering carried the figure off its route: the straight line to the next waypoint leaves the floor. */
  offPath: boolean;
}

/** True when the first `maxLen` metres of a→b lie on walkable ground (sampled every 0.1 m). */
export function segmentWalkable(a: Point, b: Point, walkable: (p: Point) => boolean, maxLen = 1.5): boolean {
  const dx = b.x - a.x, dz = b.z - a.z;
  const len = Math.hypot(dx, dz);
  if (len < 1e-6) return true;
  const reach = Math.min(len, maxLen);
  for (let d = 0.1; d <= reach + 1e-9; d += 0.1) {
    if (!walkable({ x: a.x + (dx / len) * d, z: a.z + (dz / len) * d })) return false;
  }
  return true;
}

/**
 * One step of a figure along its path among other bodies. Unlike
 * `stepMoverAvoiding` it never leaves walkable ground and never steps into
 * anybody: every candidate step (steered, straight, then a slide to the right
 * or left) is checked against the floor and the bodies, and when none is free
 * the figure waits. It turns before it walks, faces where it actually moves,
 * and lands exactly on the last waypoint.
 *
 * Two legs may cross blocked cells, as the route itself does: the first steps
 * out of a seat, and the final step onto a seat inside a footprint. Both go
 * straight along the route. Getting up, a figure still waits for whoever
 * stands in its way; the seat it walks to is reserved, so bodies do not veto
 * that last step.
 */
export function stepWalker(m: Mover, speed: number, dt: number, others: readonly Point[], walkable: (p: Point) => boolean): WalkStep {
  while (m.path.length > 0 && Math.hypot(m.path[0].x - m.x, m.path[0].z - m.z) < 1e-6) m.path.shift();
  if (m.path.length === 0) return { moved: 0, arrived: true, blocked: false, offPath: false };
  const next = m.path[0];
  const final = m.path.length === 1;
  const dx = next.x - m.x, dz = next.z - m.z;
  const dist = Math.hypot(dx, dz);
  const ux = dx / dist, uz = dz / dist;
  const here = walkable(m);
  const seatLeg = final && !walkable(next);
  // On the floor a figure steers; inside a footprint (leaving or taking a seat) it follows the route.
  const steering = here && !seatLeg;

  let sx = ux, sz = uz;
  let slow = 1;
  if (steering && others.length > 0) {
    const end = m.path[m.path.length - 1];
    const fade = Math.min(1, Math.max(0, (Math.hypot(end.x - m.x, end.z - m.z) - 0.3) / (AVOID_FADE_M - 0.3)));
    const push = separation(m, m.heading, others, 1.2);
    if (fade > 0 && Math.hypot(push.x, push.z) > 1e-3) {
      const ax = ux + push.x * 1.6 * fade, az = uz + push.z * 1.6 * fade;
      const len = Math.hypot(ax, az);
      if (len > 1e-6) { sx = ax / len; sz = az / len; }
    }
    // Slow down while someone blocks the way ahead.
    for (const o of others) {
      const ox = o.x - m.x, oz = o.z - m.z;
      const d = Math.hypot(ox, oz);
      if (d < 0.95 && d > 1e-6 && (ox * ux + oz * uz) / d > 0.7) slow = Math.min(slow, Math.max(0.25, (d - BODY_SPACING) / 0.4));
    }
  }
  const pace = Math.max(0, speed * slow * dt);
  const free = (p: Point) => (seatLeg ? true : (steering ? walkable(p) : true) && stepClearOfBodies(p, m, others));
  const at = (cx: number, cz: number, len: number): Point => ({ x: m.x + cx * len, z: m.z + cz * len });

  // The wanted direction first, then straight at the waypoint, then a slide past whatever is in the way (right before left).
  const rx = uz, rz = -ux;
  const candidates: [number, number][] = [[sx, sz]];
  if (sx !== ux || sz !== uz) candidates.push([ux, uz]);
  if (steering) {
    candidates.push([(ux + rx) * Math.SQRT1_2, (uz + rz) * Math.SQRT1_2], [(ux - rx) * Math.SQRT1_2, (uz - rz) * Math.SQRT1_2], [rx, rz], [-rx, -rz]);
  }
  const offPath = steering && !walkable(at(ux, uz, Math.min(pace, dist)));
  let chosen: [number, number] | null = null;
  for (const c of candidates) {
    const straight = c[0] === ux && c[1] === uz;
    if (free(at(c[0], c[1], straight ? Math.min(pace, dist) : pace))) { chosen = c; break; }
  }
  if (!chosen || pace <= 0) {
    m.heading = turnToward(m.heading, Math.atan2(sx, sz), TURN_RATE * dt);
    return { moved: 0, arrived: false, blocked: pace > 0, offPath };
  }
  const [cx, cz] = chosen;
  const straight = cx === ux && cz === uz;
  const off = Math.abs(wrapAngle(Math.atan2(cx, cz) - m.heading));
  m.heading = turnToward(m.heading, Math.atan2(cx, cz), TURN_RATE * dt);
  const align = off < TURN_FIRST_RAD ? 1 : Math.max(TURN_CRAWL, Math.cos(off) / Math.cos(TURN_FIRST_RAD));
  const step = straight ? Math.min(pace * align, dist) : pace * align;
  const to = at(cx, cz, step);
  if (step < pace && !free(to)) return { moved: 0, arrived: false, blocked: true, offPath };
  if (straight && step >= dist - 1e-9) { m.x = next.x; m.z = next.z; m.path.shift(); }
  else {
    m.x = to.x; m.z = to.z;
    if (!final && !straight) {
      const left = Math.hypot(next.x - m.x, next.z - m.z);
      // Pushed past a corner: head for the next waypoint as soon as it is in plain view, never back to this one.
      // A figure on its route takes every corner exactly where the route has it.
      if (left < WAYPOINT_REACH_M || (left < 0.6 && segmentWalkable(m, m.path[1], walkable))) m.path.shift();
    }
  }
  return { moved: step, arrived: m.path.length === 0, blocked: false, offPath };
}

/** Progress that counts as one unit of walking, how long without it before a re-plan, and how many re-plans before a rescue. */
export const STUCK = { progressM: 0.4, replanS: 1.5, maxReplans: 2 } as const;

/** Watches one walk for a figure that stopped getting anywhere. */
export interface StuckWatch { x: number; z: number; idleS: number; replans: number }

export function newStuckWatch(at: Point): StuckWatch {
  return { x: at.x, z: at.z, idleS: 0, replans: 0 };
}

export type StuckVerdict = "ok" | "replan" | "rescue";

/**
 * Feed the watch one frame. Every 0.4 m of real progress is a unit of work
 * and resets it; without progress for 1.5 s it asks for a re-plan, and after
 * two re-plans that did not help for a rescue (a safe placement).
 */
export function watchProgress(watch: StuckWatch, at: Point, dt: number): StuckVerdict {
  if (Math.hypot(at.x - watch.x, at.z - watch.z) >= STUCK.progressM) {
    watch.x = at.x; watch.z = at.z; watch.idleS = 0; watch.replans = 0;
    return "ok";
  }
  watch.idleS += dt;
  if (watch.idleS < STUCK.replanS) return "ok";
  watch.idleS = 0;
  if (watch.replans < STUCK.maxReplans) { watch.replans += 1; return "replan"; }
  watch.replans = 0;
  return "rescue";
}
