/**
 * One walk of a figure to a place, from the first step to the arrival: the
 * route, the pace, and everything that can go wrong on the way.
 *
 * - The route is recomputed when steering carried the figure off it, and when
 *   the floor plan changed under its feet (teams are created and deleted while
 *   people walk).
 * - A figure that stops getting anywhere first takes a detour round whoever
 *   stands in its way. After two detours that did not help it is placed when
 *   its target is a few steps away (on its reserved seat, or on the nearest
 *   free ground beside the target); further away it gives the walk up, and its
 *   owner plans again from where it stands. Nobody is moved across the floor,
 *   unless the caller insists (`far`: a place the agent's real state demands,
 *   after it failed to get there twice).
 * - A walk has a time budget, so a figure that keeps moving without arriving
 *   (back and forth in a doorway) ends the same way.
 *
 * Pure: the caller owns the mover, the clock and the list of other bodies.
 */
import type { Point } from "./officeLayout";
import { clearOfBodies, newStuckWatch, paceFor, stepWalker, watchProgress, WALK_SPEED, BODY_SPACING, type Mover, type StuckWatch } from "./officeMotion";
import { findPath, isWalkable, nearestWalkable, type NavGrid } from "./officeNav";

/** Blocked by a body this close to a place to stand, the figure has arrived: it stops beside whoever is there. */
const NEAR_ENOUGH_M = 0.5;
/** A figure is placed at a target this close; a target further away is given up instead. */
export const PLACE_WITHIN_M = 3;
/** A walk may take this many times its expected duration, plus a margin, before it ends by placement or is given up. */
const BUDGET_FACTOR = 3;
const BUDGET_MARGIN_S = 8;
/** Seconds between two route repairs after steering left the route. */
const REPATH_EVERY_S = 0.4;
/** Bodies further away than this play no part in a detour. */
const DETOUR_RANGE_M = 7;
/** A body blocks the cells this close to its centre while a detour is planned: the spacing two bodies keep, and a little more. */
const DETOUR_BODY_M = BODY_SPACING + 0.08;

/**
 * What happened on this step besides walking: a detour round a body
 * ("replan"), a placement ("rescue"), a repaired route ("repath"), an arrival
 * beside an occupied place ("near"), a walk given up because the way stays
 * closed ("blocked"), or a target that can no longer be reached on the new
 * floor plan ("lost"). After "blocked" and "lost" the walk is over without an
 * arrival: the caller plans again.
 */
export type WalkEvent = "replan" | "rescue" | "repath" | "near" | "blocked" | "lost" | null;

export interface Walk {
  target: Point;
  /** The floor plan the route was computed on. */
  grid: NavGrid;
  watch: StuckWatch;
  elapsedS: number;
  budgetS: number;
  /** Metres of route left, for the pace. */
  remaining: number;
  /** The whole route's length when the walk began. */
  length: number;
  sinceRepathS: number;
  /** Counters for the dev handle: detours, placements and route repairs on this walk. */
  replans: number;
  rescues: number;
  repaths: number;
}

export interface WalkResult { moved: number; arrived: boolean; event: WalkEvent }

export function pathLength(from: Point, path: readonly Point[]): number {
  let total = 0;
  let at = from;
  for (const p of path) { total += Math.hypot(p.x - at.x, p.z - at.z); at = p; }
  return total;
}

function budgetFor(length: number): number {
  return (length / WALK_SPEED) * BUDGET_FACTOR + BUDGET_MARGIN_S;
}

/** A figure getting up looks for a way out round anyone standing this close to its seat. */
const SEAT_EXIT_RANGE_M = 1.6;

/**
 * Start walking `m` to `target`. Null when no route exists; the caller places
 * the figure instead. A figure that starts inside a footprint (it gets up
 * from a seat) leaves on the side where nobody of `bodies` stands.
 */
export function beginWalk(grid: NavGrid, m: Mover, target: Point, bodies: readonly Point[] = []): Walk | null {
  const crowded = !isWalkable(grid, m) && bodies.some((b) => Math.hypot(b.x - m.x, b.z - m.z) <= SEAT_EXIT_RANGE_M);
  const path = (crowded ? findDetour(grid, m, target, bodies) : null) ?? findPath(grid, m, target);
  if (!path) return null;
  m.path = path;
  const length = pathLength(m, path);
  return {
    target: { x: target.x, z: target.z }, grid, watch: newStuckWatch(m), elapsedS: 0, budgetS: budgetFor(length),
    remaining: length, length, sinceRepathS: REPATH_EVERY_S, replans: 0, rescues: 0, repaths: 0,
  };
}

/**
 * A route to `to` that also walks round the bodies standing nearby. Null when
 * there is none (they close the only way), so the caller can keep its route.
 */
export function findDetour(grid: NavGrid, from: Point, to: Point, bodies: readonly Point[]): Point[] | null {
  const near = bodies.filter((b) => Math.hypot(b.x - from.x, b.z - from.z) <= DETOUR_RANGE_M
    // Whoever stands on the target itself is not walked round: the figure stops beside them.
    && Math.hypot(b.x - to.x, b.z - to.z) > DETOUR_BODY_M + grid.cell);
  if (near.length === 0) return null;
  // A copy with its own search buffers: the labelled regions of the real grid stay valid.
  const blocked = new Uint8Array(grid.blocked);
  const reach = Math.ceil(DETOUR_BODY_M / grid.cell);
  for (const body of near) {
    const bc = Math.floor((body.x - grid.originX) / grid.cell), br = Math.floor((body.z - grid.originZ) / grid.cell);
    for (let r = Math.max(0, br - reach); r <= Math.min(grid.rows - 1, br + reach); r += 1) {
      for (let c = Math.max(0, bc - reach); c <= Math.min(grid.cols - 1, bc + reach); c += 1) {
        const cx = grid.originX + (c + 0.5) * grid.cell, cz = grid.originZ + (r + 0.5) * grid.cell;
        // The figure's own cell stays free, however close the body stands.
        if (Math.hypot(cx - body.x, cz - body.z) <= DETOUR_BODY_M && Math.hypot(cx - from.x, cz - from.z) > grid.cell) blocked[r * grid.cols + c] = 1;
      }
    }
  }
  return findPath({ ...grid, blocked }, from, to);
}

/** Somebody this close to a seat is on it, however the seat was reserved. */
const ON_SEAT_M = 0.3;

/**
 * Where a figure that cannot walk to `target` is put. A seat inside a
 * footprint is reserved, so it is the place itself (the neighbours on a couch
 * sit closer than two walkers pass); a place to stand is taken when nobody is
 * on it. Otherwise it is the nearest free ground round the target: never on
 * top of anybody.
 */
export function safePlacement(grid: NavGrid, target: Point, bodies: readonly Point[]): Point {
  const free = isWalkable(grid, target) ? clearOfBodies(target, bodies) : clearOfBodies(target, bodies, ON_SEAT_M);
  if (free) return { x: target.x, z: target.z };
  for (const radius of [0.75, 1.1, 1.6, 2.4]) {
    for (let i = 0; i < 8; i += 1) {
      const angle = (i / 8) * Math.PI * 2;
      const p = { x: target.x + Math.sin(angle) * radius, z: target.z + Math.cos(angle) * radius };
      if (isWalkable(grid, p) && clearOfBodies(p, bodies)) return p;
    }
  }
  return nearestWalkable(grid, target) ?? { x: target.x, z: target.z };
}

/**
 * Marks along a route for the person to see where a click sends the
 * character: a dot every `spacing` metres from `from` along `path`, the
 * first one a step ahead, none on the destination itself (it has its own
 * ring). At most `max` dots; a longer route spreads them out.
 */
export function routeMarks(from: Point, path: readonly Point[], spacing = 0.9, max = 40): Point[] {
  const total = pathLength(from, path);
  if (total < spacing * 1.5) return [];
  const gap = Math.max(spacing, total / (max + 1));
  const marks: Point[] = [];
  let at = from;
  let next = gap;
  let walked = 0;
  for (const p of path) {
    const leg = Math.hypot(p.x - at.x, p.z - at.z);
    while (leg > 1e-9 && next <= walked + leg && next < total - gap * 0.5 && marks.length < max) {
      const t = (next - walked) / leg;
      marks.push({ x: at.x + (p.x - at.x) * t, z: at.z + (p.z - at.z) * t });
      next += gap;
    }
    walked += leg;
    at = p;
  }
  return marks;
}

function reroute(walk: Walk, m: Mover, path: Point[]): void {
  m.path = path;
  walk.remaining = pathLength(m, path);
}

function place(walk: Walk, m: Mover, grid: NavGrid, bodies: readonly Point[]): WalkResult {
  const spot = safePlacement(grid, walk.target, bodies);
  m.x = spot.x; m.z = spot.z; m.path = [];
  walk.rescues += 1;
  walk.remaining = 0;
  return { moved: 0, arrived: true, event: "rescue" };
}

/**
 * Advance a walk by one frame on the current floor plan `grid`. `bodies` are
 * the other figures (already without the walker itself). With `place: false`
 * (the person's own character) a walk that fails always stops where it is;
 * with `far: true` it is placed however far away its target is.
 */
export function advanceWalk(walk: Walk, m: Mover, grid: NavGrid, dt: number, bodies: readonly Point[],
  options: { speed?: number; place?: boolean; far?: boolean } = {}): WalkResult {
  const mayPlace = options.place !== false;
  const walkable = (p: Point) => isWalkable(grid, p);
  let event: WalkEvent = null;

  if (grid !== walk.grid) {
    // The floor plan changed under the walk: find the new way (a route out of anything that now stands here included).
    walk.grid = grid;
    const path = findPath(grid, m, walk.target);
    if (!path) { m.path = []; return { moved: 0, arrived: false, event: "lost" }; }
    reroute(walk, m, path);
    walk.watch = newStuckWatch(m);
    walk.budgetS = walk.elapsedS + budgetFor(walk.remaining);
    walk.repaths += 1;
    event = "repath";
  }

  walk.elapsedS += dt;
  walk.sinceRepathS += dt;
  const step = stepWalker(m, options.speed ?? paceFor(walk.remaining), dt, bodies, walkable);
  walk.remaining = Math.max(0, walk.remaining - step.moved);
  if (step.arrived) return { moved: step.moved, arrived: true, event };

  if (step.offPath && walk.sinceRepathS >= REPATH_EVERY_S) {
    const path = findPath(grid, m, walk.target);
    if (path) { reroute(walk, m, path); walk.repaths += 1; event = "repath"; }
    walk.sinceRepathS = 0;
  }

  const verdict = walk.elapsedS > walk.budgetS ? "rescue" : watchProgress(walk.watch, m, dt);
  if (verdict === "ok") return { moved: step.moved, arrived: false, event };

  // Someone stands on (or right beside) a place to stand: stop next to them, that is an arrival.
  const left = Math.hypot(walk.target.x - m.x, walk.target.z - m.z);
  if (walkable(walk.target) && walkable(m) && left <= NEAR_ENOUGH_M + BODY_SPACING
    && bodies.some((b) => Math.hypot(b.x - walk.target.x, b.z - walk.target.z) < BODY_SPACING)) {
    m.path = [];
    walk.remaining = 0;
    return { moved: step.moved, arrived: true, event: "near" };
  }
  if (verdict === "replan") {
    const path = findDetour(grid, m, walk.target, bodies) ?? findPath(grid, m, walk.target);
    if (path) reroute(walk, m, path);
    walk.replans += 1;
    return { moved: step.moved, arrived: false, event: "replan" };
  }
  if (!mayPlace || (!options.far && left > PLACE_WITHIN_M)) {
    m.path = [];
    walk.remaining = 0;
    return { moved: step.moved, arrived: false, event: "blocked" };
  }
  return place(walk, m, grid, bodies);
}
