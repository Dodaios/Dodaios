/**
 * Walking on a deck: an occupancy grid rasterised from the plan, A* over it
 * and a line-of-sight pass that turns the cell path into a few straight legs.
 *
 * Everything solid (the hull, bulkheads, glass, rails and solid furniture)
 * is grown by a body's clearance, so a route through free cells keeps every
 * body clear of it. A target inside something solid (a rest pod, a seat
 * tucked against a console) is reached by walking to the nearest free cell
 * and stepping onto it, which is what sitting down looks like.
 */
import { insidePolygon } from "../plan/builder";
import type { DeckPlan, Vec2 } from "../plan/types";

export const CELL = 0.2;
/** How far every body keeps from anything solid. */
export const CLEARANCE = 0.3;

export interface NavGrid {
  x0: number;
  z0: number;
  cols: number;
  rows: number;
  /** 1 = blocked. */
  blocked: Uint8Array;
}

export function cellOf(grid: NavGrid, p: Vec2): [number, number] {
  return [Math.floor((p.x - grid.x0) / CELL), Math.floor((p.z - grid.z0) / CELL)];
}

export function centreOf(grid: NavGrid, c: number, r: number): Vec2 {
  return { x: grid.x0 + (c + 0.5) * CELL, z: grid.z0 + (r + 0.5) * CELL };
}

export function isFree(grid: NavGrid, p: Vec2): boolean {
  const [c, r] = cellOf(grid, p);
  return c >= 0 && r >= 0 && c < grid.cols && r < grid.rows && grid.blocked[r * grid.cols + c] === 0;
}

function distToSegment(p: Vec2, a: Vec2, b: Vec2): number {
  const dx = b.x - a.x, dz = b.z - a.z;
  const len2 = dx * dx + dz * dz || 1e-9;
  const t = Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.z - a.z) * dz) / len2));
  return Math.hypot(p.x - (a.x + dx * t), p.z - (a.z + dz * t));
}

export function buildNavGrid(plan: DeckPlan, clearance = CLEARANCE): NavGrid {
  const pad = 1;
  const x0 = plan.bounds.x0 - pad, z0 = plan.bounds.z0 - pad;
  const cols = Math.ceil((plan.bounds.x1 - plan.bounds.x0 + pad * 2) / CELL);
  const rows = Math.ceil((plan.bounds.z1 - plan.bounds.z0 + pad * 2) / CELL);
  const blocked = new Uint8Array(cols * rows);
  const grid: NavGrid = { x0, z0, cols, rows, blocked };
  // Outside the hull.
  for (let r = 0; r < rows; r += 1) for (let c = 0; c < cols; c += 1) {
    if (!insidePolygon(plan.hull, centreOf(grid, c, r))) blocked[r * cols + c] = 1;
  }
  const mark = (minX: number, minZ: number, maxX: number, maxZ: number, test: (p: Vec2) => boolean) => {
    const c0 = Math.max(0, Math.floor((minX - x0) / CELL)), c1 = Math.min(cols - 1, Math.floor((maxX - x0) / CELL));
    const r0 = Math.max(0, Math.floor((minZ - z0) / CELL)), r1 = Math.min(rows - 1, Math.floor((maxZ - z0) / CELL));
    for (let r = r0; r <= r1; r += 1) for (let c = c0; c <= c1; c += 1) {
      if (blocked[r * cols + c]) continue;
      if (test(centreOf(grid, c, r))) blocked[r * cols + c] = 1;
    }
  };
  for (const wall of plan.walls) {
    const reach = wall.t / 2 + clearance;
    mark(Math.min(wall.a.x, wall.b.x) - reach, Math.min(wall.a.z, wall.b.z) - reach, Math.max(wall.a.x, wall.b.x) + reach, Math.max(wall.a.z, wall.b.z) + reach,
      (p) => distToSegment(p, wall.a, wall.b) <= reach);
  }
  for (const prop of plan.props) {
    if (!prop.solid) continue;
    const cos = Math.cos(prop.yaw), sin = Math.sin(prop.yaw);
    const hw = prop.w / 2 + clearance, hd = prop.d / 2 + clearance;
    const reach = Math.hypot(hw, hd);
    mark(prop.x - reach, prop.z - reach, prop.x + reach, prop.z + reach, (p) => {
      const dx = p.x - prop.x, dz = p.z - prop.z;
      // Into the piece's own frame: its x axis is (cos, -sin), its z axis (sin, cos) for a yaw about +y.
      const lx = dx * cos - dz * sin, lz = dx * sin + dz * cos;
      return Math.abs(lx) <= hw && Math.abs(lz) <= hd;
    });
  }
  return grid;
}

/** The nearest free point to `p` (spiral search), or null if there is none within `maxM`. */
export function nearestFree(grid: NavGrid, p: Vec2, maxM = 6): Vec2 | null {
  if (isFree(grid, p)) return p;
  const [c0, r0] = cellOf(grid, p);
  const maxRing = Math.ceil(maxM / CELL);
  let best: Vec2 | null = null, bestD = Infinity;
  for (let ring = 1; ring <= maxRing; ring += 1) {
    for (let dr = -ring; dr <= ring; dr += 1) for (let dc = -ring; dc <= ring; dc += 1) {
      if (Math.max(Math.abs(dr), Math.abs(dc)) !== ring) continue;
      const c = c0 + dc, r = r0 + dr;
      if (c < 0 || r < 0 || c >= grid.cols || r >= grid.rows || grid.blocked[r * grid.cols + c]) continue;
      const q = centreOf(grid, c, r);
      const d = Math.hypot(q.x - p.x, q.z - p.z);
      if (d < bestD) { bestD = d; best = q; }
    }
    if (best && bestD <= (ring + 0.5) * CELL) return best;
  }
  return best;
}

/** True when the straight line from a to b crosses only free cells. */
export function lineOfSight(grid: NavGrid, a: Vec2, b: Vec2): boolean {
  const len = Math.hypot(b.x - a.x, b.z - a.z);
  const steps = Math.max(1, Math.ceil(len / (CELL * 0.5)));
  for (let i = 0; i <= steps; i += 1) {
    const t = i / steps;
    if (!isFree(grid, { x: a.x + (b.x - a.x) * t, z: a.z + (b.z - a.z) * t })) return false;
  }
  return true;
}

class Heap {
  private readonly items: number[] = [];
  private readonly keys: number[] = [];
  get size() { return this.items.length; }
  push(item: number, key: number) {
    const { items, keys } = this;
    items.push(item); keys.push(key);
    let i = items.length - 1;
    while (i > 0) {
      const p = (i - 1) >> 1;
      if (keys[p] <= keys[i]) break;
      [items[p], items[i]] = [items[i], items[p]]; [keys[p], keys[i]] = [keys[i], keys[p]];
      i = p;
    }
  }
  pop(): number {
    const { items, keys } = this;
    const top = items[0];
    const lastItem = items.pop() as number, lastKey = keys.pop() as number;
    if (items.length > 0) {
      items[0] = lastItem; keys[0] = lastKey;
      let i = 0;
      for (;;) {
        const l = i * 2 + 1, r = l + 1;
        let m = i;
        if (l < items.length && keys[l] < keys[m]) m = l;
        if (r < items.length && keys[r] < keys[m]) m = r;
        if (m === i) break;
        [items[m], items[i]] = [items[i], items[m]]; [keys[m], keys[i]] = [keys[i], keys[m]];
        i = m;
      }
    }
    return top;
  }
}

const SQRT2 = Math.SQRT2;
const NEIGHBOURS: [number, number, number][] = [
  [1, 0, 1], [-1, 0, 1], [0, 1, 1], [0, -1, 1], [1, 1, SQRT2], [1, -1, SQRT2], [-1, 1, SQRT2], [-1, -1, SQRT2],
];

/**
 * A walkable route from `from` to `to` as a list of points (excluding the
 * start). An unreachable target returns null. A blocked start or end is
 * moved to the nearest free cell; a blocked end is then stepped onto.
 */
export function findPath(grid: NavGrid, from: Vec2, to: Vec2): Vec2[] | null {
  const start = nearestFree(grid, from, 3);
  const goal = nearestFree(grid, to, 3);
  if (!start || !goal) return null;
  const [sc, sr] = cellOf(grid, start), [gc, gr] = cellOf(grid, goal);
  const { cols, rows, blocked } = grid;
  const startIdx = sr * cols + sc, goalIdx = gr * cols + gc;
  const g = new Float32Array(cols * rows).fill(Infinity);
  const came = new Int32Array(cols * rows).fill(-1);
  const closed = new Uint8Array(cols * rows);
  const heap = new Heap();
  g[startIdx] = 0;
  heap.push(startIdx, 0);
  const h = (c: number, r: number) => {
    const dx = Math.abs(c - gc), dz = Math.abs(r - gr);
    return (dx + dz) + (SQRT2 - 2) * Math.min(dx, dz);
  };
  let found = startIdx === goalIdx;
  while (heap.size > 0 && !found) {
    const idx = heap.pop();
    if (closed[idx]) continue;
    closed[idx] = 1;
    if (idx === goalIdx) { found = true; break; }
    const c = idx % cols, r = (idx - c) / cols;
    for (const [dc, dr, cost] of NEIGHBOURS) {
      const nc = c + dc, nr = r + dr;
      if (nc < 0 || nr < 0 || nc >= cols || nr >= rows) continue;
      const n = nr * cols + nc;
      if (blocked[n] || closed[n]) continue;
      // No corner cutting.
      if (dc !== 0 && dr !== 0 && (blocked[r * cols + nc] || blocked[nr * cols + c])) continue;
      const ng = g[idx] + cost;
      if (ng < g[n]) { g[n] = ng; came[n] = idx; heap.push(n, ng + h(nc, nr)); }
    }
  }
  if (!found) return null;
  const cells: Vec2[] = [];
  for (let idx = goalIdx; idx !== -1 && idx !== startIdx; idx = came[idx]) {
    const c = idx % cols;
    cells.push(centreOf(grid, c, (idx - c) / cols));
  }
  cells.reverse();
  // String pulling: keep only the corners the straight line cannot skip.
  const legs: Vec2[] = [];
  let anchor = start;
  for (let i = 0; i < cells.length; i += 1) {
    const next = cells[i + 1];
    if (!next || !lineOfSight(grid, anchor, next)) {
      legs.push(cells[i]);
      anchor = cells[i];
    }
  }
  const end = legs[legs.length - 1];
  if (!end || Math.hypot(end.x - goal.x, end.z - goal.z) > 0.01) legs.push(goal);
  if (Math.hypot(goal.x - to.x, goal.z - to.z) > 0.02) legs.push({ x: to.x, z: to.z });
  return legs;
}

export function pathLength(from: Vec2, path: readonly Vec2[]): number {
  let len = 0, prev = from;
  for (const p of path) { len += Math.hypot(p.x - prev.x, p.z - prev.z); prev = p; }
  return len;
}
