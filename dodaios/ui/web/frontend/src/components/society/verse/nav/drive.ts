/**
 * Moving a body by direct control (the commander under the keys) over the
 * cooked nav grid. Pure.
 *
 * A move is cut into steps of at most half a cell, so it never tunnels
 * through a thin wall. A step goes only onto walkable floor, never up or
 * down more than the grid's largest step, and never squeezes diagonally
 * between two blocked cells. When the full step is blocked the body slides
 * along the wall on whichever axis is still free, the way a person keeps
 * walking when they brush a bulkhead at an angle.
 */
import type { NavGrid } from "../content/deck";
import { cellIndex, isWalkable, nearestWalkable, type Point } from "./pathfind";

/** Extra test for a step's end point (other bodies); true = the point is free. */
export type FreeAt = (p: Point) => boolean;

function canStep(grid: NavGrid, a: Point, b: Point, free?: FreeAt): boolean {
  const ib = cellIndex(grid, b.x, b.z);
  if (ib < 0 || grid.walkable[ib] !== 1) return false;
  const ia = cellIndex(grid, a.x, a.z);
  if (ia >= 0 && ia !== ib && grid.walkable[ia] === 1) {
    if (Math.abs(grid.heights[ib] - grid.heights[ia]) > grid.maxStep) return false;
    // A diagonal step needs both cells it passes between.
    const ca = ia % grid.cols, ra = (ia - ca) / grid.cols;
    const cb = ib % grid.cols, rb = (ib - cb) / grid.cols;
    if (ca !== cb && ra !== rb && (grid.walkable[ra * grid.cols + cb] !== 1 || grid.walkable[rb * grid.cols + ca] !== 1)) return false;
  }
  return !free || free(b);
}

/**
 * Where a body at `from` ends up after trying to move by (dx, dz) metres.
 * Blocked moves slide along walls; a fully blocked move stays put.
 */
export function driveStep(grid: NavGrid, from: Point, dx: number, dz: number, free?: FreeAt): Point {
  const length = Math.hypot(dx, dz);
  if (length < 1e-6) return from;
  // Standing off the floor (placed on a blocked cell): step back onto the nearest floor first.
  if (!isWalkable(grid, from.x, from.z)) {
    const floor = nearestWalkable(grid, from, 2);
    if (!floor) return from;
    const d = Math.hypot(floor.x - from.x, floor.z - from.z);
    if (d <= length) return floor;
    return { x: from.x + ((floor.x - from.x) / d) * length, z: from.z + ((floor.z - from.z) / d) * length };
  }
  const steps = Math.max(1, Math.ceil(length / (grid.cell * 0.5)));
  const sx = dx / steps;
  const sz = dz / steps;
  let p = from;
  for (let i = 0; i < steps; i++) {
    const both = { x: p.x + sx, z: p.z + sz };
    if (canStep(grid, p, both, free)) { p = both; continue; }
    const alongX = { x: p.x + sx, z: p.z };
    if (Math.abs(sx) > 1e-9 && canStep(grid, p, alongX, free)) { p = alongX; continue; }
    const alongZ = { x: p.x, z: p.z + sz };
    if (Math.abs(sz) > 1e-9 && canStep(grid, p, alongZ, free)) { p = alongZ; continue; }
    break;
  }
  return p;
}
