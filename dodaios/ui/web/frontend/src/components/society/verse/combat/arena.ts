/**
 * The duel arena: a compact, renderer-independent description of a room
 * (bounds, solid colliders, drops and the walkways across them) and the
 * runtime built from it once: a fine movement grid eroded by the body radius,
 * world raycasts for bolts and sight lines, and cover spots for the bot.
 *
 * Coordinates are the deck's world frame (x right, z toward the camera,
 * y up, metres), so an arena overlays its deck one to one.
 */
import { sweepBox, sweepCylinder, sweepOut, type SweepOut } from "./raycast";
import type { Surface } from "./types";

export interface ArenaBox { kind: "box"; id: string; x0: number; x1: number; z0: number; z1: number; y0: number; y1: number }
export interface ArenaCylinder { kind: "cyl"; id: string; x: number; z: number; r: number; y0: number; y1: number }
export type ArenaCollider = ArenaBox | ArenaCylinder;

/** A round drop in the floor (a shaft). Bolts fly over it; bodies cannot enter it. */
export interface ArenaVoid { x: number; z: number; r: number }

/** Floor across a void: a ring around its axis, or a radial walkway. */
export type ArenaBridge =
  | { kind: "annulus"; x: number; z: number; r0: number; r1: number }
  /** `yawDeg`: direction from the axis, 0 = +Z, 90 = +X. */
  | { kind: "spoke"; x: number; z: number; yawDeg: number; r0: number; r1: number; halfWidth: number };

/** A doorway in the bounds: bolts leave through it without an impact. */
export interface ArenaOpening { x0: number; x1: number; z0: number; z1: number; y1: number }

export interface ArenaPoint { x: number; z: number; yaw: number }

export interface ArenaDef {
  id: string;
  name: string;
  /** The deck and room it overlays. */
  deck: string;
  room: string;
  bounds: { x0: number; x1: number; z0: number; z1: number; ceiling: number };
  colliders: readonly ArenaCollider[];
  voids: readonly ArenaVoid[];
  bridges: readonly ArenaBridge[];
  openings: readonly ArenaOpening[];
  /** Spawn of side 0 and side 1 (players swap sides every round). */
  spawns: readonly [ArenaPoint, ArenaPoint];
  /** Where a duel can be started from (consoles in the room). */
  terminals: readonly (ArenaPoint & { id: string })[];
  centre: { x: number; z: number };
}

export interface MoveGrid {
  cell: number;
  x0: number;
  z0: number;
  cols: number;
  rows: number;
  /** 1 = a body centre may stand here (already eroded by the body radius). */
  walk: Uint8Array;
}

export interface CoverSpot {
  x: number;
  z: number;
  /** The collider that gives the cover, and the direction from it to the spot. */
  collider: string;
  nx: number;
  nz: number;
}

export interface Arena {
  def: ArenaDef;
  bodyRadius: number;
  grid: MoveGrid;
  cover: readonly CoverSpot[];
}

/** Colliders at least this tall hide a standing body. */
export const COVER_HEIGHT = 1.7;
const GRID_CELL = 0.1;

// ---------------------------------------------------------------- floor

export function inVoid(def: ArenaDef, x: number, z: number): boolean {
  for (const v of def.voids) {
    const dx = x - v.x;
    const dz = z - v.z;
    if (dx * dx + dz * dz < v.r * v.r) return true;
  }
  return false;
}

export function onBridge(def: ArenaDef, x: number, z: number): boolean {
  for (const b of def.bridges) {
    const dx = x - b.x;
    const dz = z - b.z;
    if (b.kind === "annulus") {
      const d2 = dx * dx + dz * dz;
      if (d2 >= b.r0 * b.r0 && d2 <= b.r1 * b.r1) return true;
    } else {
      const a = (b.yawDeg * Math.PI) / 180;
      const along = dx * Math.sin(a) + dz * Math.cos(a);
      const lateral = dx * Math.cos(a) - dz * Math.sin(a);
      if (along >= b.r0 && along <= b.r1 && Math.abs(lateral) <= b.halfWidth) return true;
    }
  }
  return false;
}

/** True where there is deck under (x, z) (bounds, not over a drop unless on a walkway). */
export function hasFloor(def: ArenaDef, x: number, z: number): boolean {
  const b = def.bounds;
  if (x < b.x0 || x > b.x1 || z < b.z0 || z > b.z1) return false;
  return !inVoid(def, x, z) || onBridge(def, x, z);
}

function blocksBody(c: ArenaCollider): boolean {
  return c.y0 < 1.0 && c.y1 > 0.15;
}

function insideFootprint(c: ArenaCollider, x: number, z: number): boolean {
  if (c.kind === "box") return x >= c.x0 && x <= c.x1 && z >= c.z0 && z <= c.z1;
  const dx = x - c.x;
  const dz = z - c.z;
  return dx * dx + dz * dz <= c.r * c.r;
}

// ---------------------------------------------------------------- build

const cache = new WeakMap<ArenaDef, Map<number, Arena>>();

/** The runtime arena for a body radius (memoised per definition). */
export function buildArena(def: ArenaDef, bodyRadius: number): Arena {
  let byRadius = cache.get(def);
  if (!byRadius) { byRadius = new Map(); cache.set(def, byRadius); }
  const hit = byRadius.get(bodyRadius);
  if (hit) return hit;
  const grid = rasterise(def, bodyRadius);
  const partial: Arena = { def, bodyRadius, grid, cover: [] };
  const arena: Arena = { ...partial, cover: findCover(partial) };
  byRadius.set(bodyRadius, arena);
  return arena;
}

function rasterise(def: ArenaDef, radius: number): MoveGrid {
  const b = def.bounds;
  const cell = GRID_CELL;
  const cols = Math.ceil((b.x1 - b.x0) / cell);
  const rows = Math.ceil((b.z1 - b.z0) / cell);
  const raw = new Uint8Array(cols * rows);
  const blockers = def.colliders.filter(blocksBody);
  for (let r = 0; r < rows; r++) {
    const z = b.z0 + (r + 0.5) * cell;
    for (let c = 0; c < cols; c++) {
      const x = b.x0 + (c + 0.5) * cell;
      if (!hasFloor(def, x, z)) continue;
      let free = true;
      for (const k of blockers) if (insideFootprint(k, x, z)) { free = false; break; }
      if (free) raw[r * cols + c] = 1;
    }
  }
  // Erode by the body radius: a centre is walkable when every cell within
  // `radius` of it is floor. Cells beyond the grid count as walls.
  const k = Math.ceil(radius / cell);
  const offsets: number[] = [];
  for (let dr = -k; dr <= k; dr++) {
    for (let dc = -k; dc <= k; dc++) {
      if ((dc * dc + dr * dr) * cell * cell <= radius * radius + 1e-9) offsets.push(dc, dr);
    }
  }
  const walk = new Uint8Array(cols * rows);
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      if (!raw[r * cols + c]) continue;
      let ok = true;
      for (let i = 0; i < offsets.length; i += 2) {
        const cc = c + offsets[i];
        const rr = r + offsets[i + 1];
        if (cc < 0 || rr < 0 || cc >= cols || rr >= rows || !raw[rr * cols + cc]) { ok = false; break; }
      }
      if (ok) walk[r * cols + c] = 1;
    }
  }
  return { cell, x0: b.x0, z0: b.z0, cols, rows, walk };
}

// ---------------------------------------------------------------- queries

export function cellOf(grid: MoveGrid, x: number, z: number): number {
  const c = Math.floor((x - grid.x0) / grid.cell);
  const r = Math.floor((z - grid.z0) / grid.cell);
  if (c < 0 || r < 0 || c >= grid.cols || r >= grid.rows) return -1;
  return r * grid.cols + c;
}

export function isWalkable(arena: Arena, x: number, z: number): boolean {
  const i = cellOf(arena.grid, x, z);
  return i >= 0 && arena.grid.walk[i] === 1;
}

/** Nearest walkable point within `maxM` metres (ring search), or null. */
export function nearestWalkable(arena: Arena, x: number, z: number, maxM = 6): { x: number; z: number } | null {
  if (isWalkable(arena, x, z)) return { x, z };
  const g = arena.grid;
  const c0 = Math.floor((x - g.x0) / g.cell);
  const r0 = Math.floor((z - g.z0) / g.cell);
  const maxRing = Math.ceil(maxM / g.cell);
  for (let ring = 1; ring <= maxRing; ring++) {
    let best = -1;
    let bestD = Infinity;
    for (let dr = -ring; dr <= ring; dr++) {
      const edge = Math.abs(dr) === ring;
      for (let dc = -ring; dc <= ring; dc += edge ? 1 : 2 * ring) {
        const c = c0 + dc;
        const r = r0 + dr;
        if (c < 0 || r < 0 || c >= g.cols || r >= g.rows || !g.walk[r * g.cols + c]) continue;
        const d = dc * dc + dr * dr;
        if (d < bestD) { bestD = d; best = r * g.cols + c; }
      }
    }
    if (best >= 0) {
      const c = best % g.cols;
      const r = (best - c) / g.cols;
      return { x: g.x0 + (c + 0.5) * g.cell, z: g.z0 + (r + 0.5) * g.cell };
    }
  }
  return null;
}

/** A body can walk the straight line a → b. */
export function walkableSegment(arena: Arena, ax: number, az: number, bx: number, bz: number): boolean {
  const len = Math.hypot(bx - ax, bz - az);
  const n = Math.max(1, Math.ceil(len / (arena.grid.cell * 0.5)));
  for (let i = 0; i <= n; i++) {
    const t = i / n;
    if (!isWalkable(arena, ax + (bx - ax) * t, az + (bz - az) * t)) return false;
  }
  return true;
}

export interface MoveResult { x: number; z: number; blockedX: boolean; blockedZ: boolean }

/**
 * Move a body by (dx, dz) over the grid in half-cell steps; a blocked step
 * slides along the free axis. `free` vetoes points (other bodies).
 */
export function moveBody(
  arena: Arena, x: number, z: number, dx: number, dz: number, free?: (x: number, z: number) => boolean,
): MoveResult {
  const len = Math.hypot(dx, dz);
  const out: MoveResult = { x, z, blockedX: false, blockedZ: false };
  if (len < 1e-9) return out;
  if (!isWalkable(arena, x, z)) {
    const p = nearestWalkable(arena, x, z, 2);
    if (p) { out.x = p.x; out.z = p.z; }
    return out;
  }
  const ok = (px: number, pz: number) => isWalkable(arena, px, pz) && (!free || free(px, pz));
  const steps = Math.max(1, Math.ceil(len / (arena.grid.cell * 0.5)));
  const sx = dx / steps;
  const sz = dz / steps;
  let px = x;
  let pz = z;
  for (let i = 0; i < steps; i++) {
    if (ok(px + sx, pz + sz)) { px += sx; pz += sz; continue; }
    if (Math.abs(sx) > 1e-12 && ok(px + sx, pz)) { px += sx; out.blockedZ = true; continue; }
    if (Math.abs(sz) > 1e-12 && ok(px, pz + sz)) { pz += sz; out.blockedX = true; continue; }
    out.blockedX = out.blockedX || Math.abs(sx) > 1e-12;
    out.blockedZ = out.blockedZ || Math.abs(sz) > 1e-12;
    break;
  }
  out.x = px;
  out.z = pz;
  return out;
}

// ---------------------------------------------------------------- raycasts

export interface WorldHit {
  t: number;
  /** "exit": the segment leaves through a doorway; no impact to draw. */
  surface: Surface | "exit";
  collider: string | null;
  nx: number;
  ny: number;
  nz: number;
}

const sw: SweepOut = sweepOut();

/**
 * The first thing the segment a → b meets: a collider, the floor (not over
 * a drop), the ceiling or a wall (or a doorway). Null when it is clear.
 */
export function raycastWorld(
  arena: Arena, ax: number, ay: number, az: number, bx: number, by: number, bz: number,
): WorldHit | null {
  const def = arena.def;
  const dx = bx - ax;
  const dy = by - ay;
  const dz = bz - az;
  let best: WorldHit | null = null;
  const take = (t: number, surface: WorldHit["surface"], collider: string | null, nx: number, ny: number, nz: number) => {
    if (t >= 0 && t <= 1 && (!best || t < best.t)) best = { t, surface, collider, nx, ny, nz };
  };
  for (const c of def.colliders) {
    const t = c.kind === "box"
      ? sweepBox(ax, ay, az, dx, dy, dz, c.x0, c.y0, c.z0, c.x1, c.y1, c.z1, sw)
      : sweepCylinder(ax, ay, az, dx, dy, dz, c.x, c.z, c.r, c.y0, c.y1, sw);
    if (t >= 0) take(t, "prop", c.id, sw.nx, sw.ny, sw.nz);
  }
  // Floor (y = 0) where there is deck.
  if (dy < 0 && ay >= 0 && by < 0) {
    const t = ay / (ay - by);
    if (hasFloor(def, ax + dx * t, az + dz * t)) take(t, "floor", null, 0, 1, 0);
  }
  const bd = def.bounds;
  if (dy > 0 && ay <= bd.ceiling && by > bd.ceiling) take((bd.ceiling - ay) / dy, "ceiling", null, 0, -1, 0);
  // Walls: the bounds rectangle.
  if (bx < bd.x0 || bx > bd.x1 || bz < bd.z0 || bz > bd.z1) {
    let tw = 1;
    let nx = 0;
    let nz = 0;
    if (bx < bd.x0 && dx < 0) { const t = (bd.x0 - ax) / dx; if (t < tw) { tw = t; nx = 1; nz = 0; } }
    if (bx > bd.x1 && dx > 0) { const t = (bd.x1 - ax) / dx; if (t < tw) { tw = t; nx = -1; nz = 0; } }
    if (bz < bd.z0 && dz < 0) { const t = (bd.z0 - az) / dz; if (t < tw) { tw = t; nx = 0; nz = 1; } }
    if (bz > bd.z1 && dz > 0) { const t = (bd.z1 - az) / dz; if (t < tw) { tw = t; nx = 0; nz = -1; } }
    tw = Math.max(0, tw);
    const px = ax + dx * tw;
    const py = ay + dy * tw;
    const pz = az + dz * tw;
    let exit = false;
    for (const o of def.openings) {
      if (px >= o.x0 - 1e-6 && px <= o.x1 + 1e-6 && pz >= o.z0 - 1e-6 && pz <= o.z1 + 1e-6 && py <= o.y1) { exit = true; break; }
    }
    take(tw, exit ? "exit" : "wall", null, nx, 0, nz);
  }
  return best;
}

/** True when nothing in the world blocks a → b. */
export function lineOfSight(arena: Arena, ax: number, ay: number, az: number, bx: number, by: number, bz: number): boolean {
  const h = raycastWorld(arena, ax, ay, az, bx, by, bz);
  return h === null || h.surface === "exit";
}

// ---------------------------------------------------------------- cover

function findCover(arena: Arena): CoverSpot[] {
  const spots: CoverSpot[] = [];
  const r = arena.bodyRadius;
  const push = (x: number, z: number, id: string, nx: number, nz: number) => {
    if (!isWalkable(arena, x, z)) return false;
    for (const s of spots) if (Math.hypot(s.x - x, s.z - z) < 0.8) return true;
    spots.push({ x, z, collider: id, nx, nz });
    return true;
  };
  for (const c of arena.def.colliders) {
    if (c.y1 < COVER_HEIGHT || c.y0 > 0.5) continue;
    if (c.kind === "cyl") {
      const n = Math.max(8, Math.round((2 * Math.PI * (c.r + 1)) / 1.0));
      for (let i = 0; i < n; i++) {
        const a = (i / n) * Math.PI * 2;
        const nx = Math.sin(a);
        const nz = Math.cos(a);
        for (const off of [0.35, 0.8, 1.4, 2.0, 2.6]) {
          const d = c.r + r + off;
          if (push(c.x + nx * d, c.z + nz * d, c.id, nx, nz)) break;
        }
      }
    } else {
      const sides: [number, number, number, number, number, number][] = [
        // x, z start, x, z end, normal x, normal z
        [c.x0, c.z0, c.x1, c.z0, 0, -1],
        [c.x0, c.z1, c.x1, c.z1, 0, 1],
        [c.x0, c.z0, c.x0, c.z1, -1, 0],
        [c.x1, c.z0, c.x1, c.z1, 1, 0],
      ];
      for (const [x0, z0, x1, z1, nx, nz] of sides) {
        const len = Math.hypot(x1 - x0, z1 - z0);
        const n = Math.max(1, Math.round(len / 1.0));
        for (let i = 0; i <= n; i++) {
          const t = i / n;
          const d = r + 0.35;
          push(x0 + (x1 - x0) * t + nx * d, z0 + (z1 - z0) * t + nz * d, c.id, nx, nz);
        }
      }
    }
  }
  return spots;
}
