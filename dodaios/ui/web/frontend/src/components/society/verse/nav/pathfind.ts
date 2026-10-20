/**
 * Walking on the cooked nav grid: A* over 0.2 m cells (8-connected, never
 * cutting a blocked corner), then string-pulling so a path is a few straight
 * legs between the corners it has to turn at, not a staircase of cells.
 *
 * The cook erodes the grid by a body radius, so a walkable cell is one a
 * person can stand in. Search buffers are kept per grid and reused, so a
 * search allocates nothing but its result. Pure apart from that cache.
 */
import type { NavGrid } from "../content/deck";

export interface Point { x: number; z: number }

const SQRT2 = Math.SQRT2;
/** Searches give up past this many expanded cells (a 300 × 1000 deck has 300k). */
const MAX_EXPANDED = 400_000;

export function cellIndex(grid: NavGrid, x: number, z: number): number {
  const c = Math.floor((x - grid.x0) / grid.cell);
  const r = Math.floor((z - grid.z0) / grid.cell);
  if (c < 0 || r < 0 || c >= grid.cols || r >= grid.rows) return -1;
  return r * grid.cols + c;
}

export function cellCentre(grid: NavGrid, index: number): Point {
  const c = index % grid.cols;
  const r = (index - c) / grid.cols;
  return { x: grid.x0 + (c + 0.5) * grid.cell, z: grid.z0 + (r + 0.5) * grid.cell };
}

export function isWalkable(grid: NavGrid, x: number, z: number): boolean {
  const i = cellIndex(grid, x, z);
  return i >= 0 && grid.walkable[i] === 1;
}

/** Floor height under (x, z), metres; 0 off the grid or on a blocked cell. */
export function floorHeight(grid: NavGrid, x: number, z: number): number {
  const i = cellIndex(grid, x, z);
  return i >= 0 && grid.walkable[i] === 1 ? grid.heights[i] : 0;
}

/** The walkable cell nearest to (x, z) within `maxM` metres, by rings; -1 when none. */
export function nearestWalkableCell(grid: NavGrid, x: number, z: number, maxM = 12): number {
  const c0 = Math.floor((x - grid.x0) / grid.cell);
  const r0 = Math.floor((z - grid.z0) / grid.cell);
  const inside = (c: number, r: number) => c >= 0 && r >= 0 && c < grid.cols && r < grid.rows;
  if (inside(c0, r0) && grid.walkable[r0 * grid.cols + c0] === 1) return r0 * grid.cols + c0;
  const maxRing = Math.ceil(maxM / grid.cell);
  for (let ring = 1; ring <= maxRing; ring++) {
    let best = -1;
    let bestD = Infinity;
    for (let dr = -ring; dr <= ring; dr++) {
      const edge = Math.abs(dr) === ring;
      for (let dc = -ring; dc <= ring; dc += edge ? 1 : 2 * ring) {
        const c = c0 + dc;
        const r = r0 + dr;
        if (!inside(c, r) || grid.walkable[r * grid.cols + c] !== 1) continue;
        const d = dc * dc + dr * dr;
        if (d < bestD) { bestD = d; best = r * grid.cols + c; }
      }
    }
    if (best >= 0) return best;
  }
  return -1;
}

export function nearestWalkable(grid: NavGrid, p: Point, maxM = 12): Point | null {
  if (isWalkable(grid, p.x, p.z)) return p;
  const i = nearestWalkableCell(grid, p.x, p.z, maxM);
  return i < 0 ? null : cellCentre(grid, i);
}

interface Buffers { g: Float64Array; from: Int32Array; seen: Uint32Array; closed: Uint32Array; gen: number }
const buffers = new WeakMap<NavGrid, Buffers>();

function buffersFor(grid: NavGrid): Buffers {
  let b = buffers.get(grid);
  const n = grid.cols * grid.rows;
  if (!b || b.g.length !== n) {
    b = { g: new Float64Array(n), from: new Int32Array(n), seen: new Uint32Array(n), closed: new Uint32Array(n), gen: 0 };
    buffers.set(grid, b);
  }
  b.gen = (b.gen + 1) >>> 0 || 1;
  return b;
}

/** A binary min-heap of cell indices keyed by f. */
class Heap {
  private items: number[] = [];
  private keys: number[] = [];
  get size() { return this.items.length; }
  push(item: number, key: number) {
    const items = this.items, keys = this.keys;
    let i = items.length;
    items.push(item); keys.push(key);
    while (i > 0) {
      const p = (i - 1) >> 1;
      if (keys[p] <= key) break;
      items[i] = items[p]; keys[i] = keys[p];
      i = p;
    }
    items[i] = item; keys[i] = key;
  }
  pop(): number {
    const items = this.items, keys = this.keys;
    const top = items[0];
    const lastItem = items.pop() as number;
    const lastKey = keys.pop() as number;
    const n = items.length;
    if (n > 0) {
      let i = 0;
      for (;;) {
        const l = 2 * i + 1;
        if (l >= n) break;
        const r = l + 1;
        const c = r < n && keys[r] < keys[l] ? r : l;
        if (keys[c] >= lastKey) break;
        items[i] = items[c]; keys[i] = keys[c];
        i = c;
      }
      items[i] = lastItem; keys[i] = lastKey;
    }
    return top;
  }
}

const DC = [1, -1, 0, 0, 1, 1, -1, -1];
const DR = [0, 0, 1, -1, 1, -1, 1, -1];

/** Cell indices from start to goal (both walkable), or null when the goal cannot be reached. */
export function aStar(grid: NavGrid, start: number, goal: number): number[] | null {
  const { cols, rows, walkable, heights, maxStep } = grid;
  if (start < 0 || goal < 0 || walkable[start] !== 1 || walkable[goal] !== 1) return null;
  if (start === goal) return [start];
  const b = buffersFor(grid);
  const gc = goal % cols, gr = (goal - gc) / cols;
  const h = (i: number) => {
    const c = i % cols, r = (i - c) / cols;
    const dx = Math.abs(c - gc), dz = Math.abs(r - gr);
    return dx + dz + (SQRT2 - 2) * Math.min(dx, dz);
  };
  const open = new Heap();
  b.g[start] = 0; b.seen[start] = b.gen; b.from[start] = -1;
  open.push(start, h(start));
  let expanded = 0;
  while (open.size > 0) {
    const cur = open.pop();
    if (b.closed[cur] === b.gen) continue;
    if (cur === goal) break;
    b.closed[cur] = b.gen;
    if (++expanded > MAX_EXPANDED) return null;
    const cc = cur % cols, cr = (cur - cc) / cols;
    for (let k = 0; k < 8; k++) {
      const nc = cc + DC[k], nr = cr + DR[k];
      if (nc < 0 || nr < 0 || nc >= cols || nr >= rows) continue;
      const ni = nr * cols + nc;
      if (walkable[ni] !== 1 || b.closed[ni] === b.gen || Math.abs(heights[ni] - heights[cur]) > maxStep) continue;
      // A diagonal step needs both cells it squeezes between.
      if (k >= 4 && (walkable[cr * cols + nc] !== 1 || walkable[nr * cols + cc] !== 1)) continue;
      const ng = b.g[cur] + (k >= 4 ? SQRT2 : 1);
      if (b.seen[ni] === b.gen && ng >= b.g[ni]) continue;
      b.seen[ni] = b.gen; b.g[ni] = ng; b.from[ni] = cur;
      open.push(ni, ng + h(ni));
    }
  }
  if (b.seen[goal] !== b.gen) return null;
  const path: number[] = [];
  for (let i = goal; i !== -1; i = b.from[i]) path.push(i);
  return path.reverse();
}

/**
 * True when a body can walk the straight segment a → b: every cell the
 * segment passes through (exact grid traversal) is walkable, and where it
 * crosses a cell corner both side cells are.
 */
export function lineOfSight(grid: NavGrid, a: Point, b: Point): boolean {
  const { cell, x0, z0, cols, rows, walkable, heights, maxStep } = grid;
  let c = Math.floor((a.x - x0) / cell);
  let r = Math.floor((a.z - z0) / cell);
  const ce = Math.floor((b.x - x0) / cell);
  const re = Math.floor((b.z - z0) / cell);
  const ok = (cc: number, rr: number) => cc >= 0 && rr >= 0 && cc < cols && rr < rows && walkable[rr * cols + cc] === 1;
  if (!ok(c, r) || !ok(ce, re)) return false;
  const dx = b.x - a.x, dz = b.z - a.z;
  const stepC = dx > 0 ? 1 : -1, stepR = dz > 0 ? 1 : -1;
  const tdx = dx !== 0 ? cell / Math.abs(dx) : Infinity;
  const tdz = dz !== 0 ? cell / Math.abs(dz) : Infinity;
  const nextX = x0 + (c + (dx > 0 ? 1 : 0)) * cell;
  const nextZ = z0 + (r + (dz > 0 ? 1 : 0)) * cell;
  let tx = dx !== 0 ? (nextX - a.x) / dx : Infinity;
  let tz = dz !== 0 ? (nextZ - a.z) / dz : Infinity;
  let lastH = heights[r * cols + c];
  // Walk cell boundaries until the next one lies past the segment's end (t = 1);
  // the end cell itself was checked above, which also covers an end exactly on a boundary.
  for (;;) {
    if (Math.min(tx, tz) >= 1 - 1e-9) break;
    if (Math.abs(tx - tz) < 1e-9) {
      // Through a corner: both neighbours must be open.
      if (!ok(c + stepC, r) || !ok(c, r + stepR)) return false;
      c += stepC; r += stepR; tx += tdx; tz += tdz;
    } else if (tx < tz) {
      c += stepC; tx += tdx;
    } else {
      r += stepR; tz += tdz;
    }
    if (!ok(c, r)) return false;
    const h = heights[r * cols + c];
    if (Math.abs(h - lastH) > maxStep) return false;
    lastH = h;
  }
  return true;
}

/** Drop every waypoint the body can skip by walking straight. */
export function stringPull(grid: NavGrid, points: readonly Point[]): Point[] {
  if (points.length <= 2) return [...points];
  const out: Point[] = [points[0]];
  let anchor = 0;
  while (anchor < points.length - 1) {
    let next = anchor + 1;
    // The farthest point still in sight; a binary search would miss a wall between two visible points.
    for (let j = points.length - 1; j > anchor + 1; j--) {
      if (lineOfSight(grid, points[anchor], points[j])) { next = j; break; }
    }
    out.push(points[next]);
    anchor = next;
  }
  return out;
}

/**
 * A walkable route from `from` to `to`: the start, the corners, the goal.
 * A goal off the grid is moved to the nearest walkable cell; null when there
 * is no way there.
 */
export function findPath(grid: NavGrid, from: Point, to: Point): Point[] | null {
  const startCell = nearestWalkableCell(grid, from.x, from.z, 2);
  const goalPoint = nearestWalkable(grid, to);
  if (startCell < 0 || !goalPoint) return null;
  const goalCell = cellIndex(grid, goalPoint.x, goalPoint.z);
  const cells = aStar(grid, startCell, goalCell);
  if (!cells) return null;
  const start = isWalkable(grid, from.x, from.z) ? from : cellCentre(grid, startCell);
  if (cells.length === 1) return [start, goalPoint];
  return stringPull(grid, [start, ...cells.slice(1, -1).map((i) => cellCentre(grid, i)), goalPoint]);
}

export function pathLength(points: readonly Point[]): number {
  let total = 0;
  for (let i = 1; i < points.length; i++) total += Math.hypot(points[i].x - points[i - 1].x, points[i].z - points[i - 1].z);
  return total;
}
