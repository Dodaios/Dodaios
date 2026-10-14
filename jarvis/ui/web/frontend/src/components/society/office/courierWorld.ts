/**
 * What the courier can hit while it flies: every tower of the city, the
 * Dodaios tower itself and the floor on top of it, the sky pad and its
 * bridge, the street level, the singularity's core, and a soft border round
 * the city. Pure and tested.
 *
 * The ship is a row of spheres along its keel (courierFlight.ts); a collider
 * pushes each sphere out along the nearest surface normal. Towers are looked
 * up in a coarse spatial hash, so a step costs a handful of box tests.
 */
import { GROUND_Y, SINGULARITY, type CityPlan } from "./cityPlan";
import type { Rect } from "./officeLayout";
import type { SkyPad } from "./skyPad";
import { SKY_PAD } from "./skyPad";

export interface Box3D { minX: number; maxX: number; minY: number; maxY: number; minZ: number; maxZ: number }

export interface CourierWorld {
  boxes: Box3D[];
  /** Cell size of the spatial hash and the boxes in each cell (indices into `boxes`). */
  cell: number;
  hash: Map<string, number[]>;
  /** Spheres that cannot be entered (the singularity's core). */
  spheres: { x: number; y: number; z: number; r: number }[];
  ground: number;
  /** The city's middle and the radius and height the ship is turned back at. */
  centre: { x: number; z: number };
  border: number;
  ceiling: number;
}

export interface Contact { nx: number; ny: number; nz: number; depth: number }

/** The floor and its window walls stand this high over the slab; the ship cannot fly through the office. */
const OFFICE_HEIGHT = 4.2;
const HASH_CELL = 40;

function addBox(world: CourierWorld, box: Box3D) {
  const index = world.boxes.push(box) - 1;
  for (let i = Math.floor(box.minX / world.cell); i <= Math.floor(box.maxX / world.cell); i += 1) {
    for (let j = Math.floor(box.minZ / world.cell); j <= Math.floor(box.maxZ / world.cell); j += 1) {
      const key = `${i},${j}`;
      const list = world.hash.get(key);
      if (list) list.push(index); else world.hash.set(key, [index]);
    }
  }
}

export function buildCourierWorld(plan: CityPlan, bounds: Rect, skyPad?: SkyPad): CourierWorld {
  const world: CourierWorld = {
    boxes: [], cell: HASH_CELL, hash: new Map(), spheres: [], ground: GROUND_Y,
    centre: plan.centre, border: 760, ceiling: 420,
  };
  for (const t of plan.towers) {
    // Prisms and spires are boxed by their full footprint whatever their turn; a tower is never thinner than that.
    const half = Math.max(t.w, t.d) / 2;
    addBox(world, { minX: t.x - half, maxX: t.x + half, minY: GROUND_Y, maxY: GROUND_Y + t.h, minZ: t.z - half, maxZ: t.z + half });
  }
  // The Dodaios tower and the floor on it, office and window walls included.
  addBox(world, { ...bounds, minY: GROUND_Y, maxY: OFFICE_HEIGHT });
  if (skyPad) {
    const { pad, bridge } = skyPad;
    addBox(world, { minX: bounds.maxX, maxX: bridge.maxX, minY: -SKY_PAD.thickness, maxY: 0, minZ: skyPad.gap.minZ, maxZ: skyPad.gap.maxZ });
    // The pad's deck as the box inside its disc (the ship lands on its middle; the rim is open air).
    const inner = pad.r * Math.SQRT1_2;
    addBox(world, { minX: pad.x - inner, maxX: pad.x + inner, minY: -SKY_PAD.thickness, maxY: 0, minZ: pad.z - inner, maxZ: pad.z + inner });
  }
  world.spheres.push({ ...plan.singularity, r: SINGULARITY.core * 1.15 });
  return world;
}

/** The deepest contact of a sphere with the world, or null when it is free. */
export function sphereContact(world: CourierWorld, x: number, y: number, z: number, r: number): Contact | null {
  let best: Contact | null = null;
  const consider = (nx: number, ny: number, nz: number, depth: number) => {
    if (depth > 0 && (!best || depth > best.depth)) best = { nx, ny, nz, depth };
  };
  // Street level.
  consider(0, 1, 0, world.ground + r - y);
  const seen = new Set<number>();
  for (let i = Math.floor((x - r) / world.cell); i <= Math.floor((x + r) / world.cell); i += 1) {
    for (let j = Math.floor((z - r) / world.cell); j <= Math.floor((z + r) / world.cell); j += 1) {
      for (const index of world.hash.get(`${i},${j}`) ?? []) {
        if (seen.has(index)) continue;
        seen.add(index);
        const b = world.boxes[index];
        const px = Math.max(b.minX, Math.min(x, b.maxX)), py = Math.max(b.minY, Math.min(y, b.maxY)), pz = Math.max(b.minZ, Math.min(z, b.maxZ));
        const dx = x - px, dy = y - py, dz = z - pz;
        const d = Math.hypot(dx, dy, dz);
        if (d > 1e-6) {
          if (d < r) consider(dx / d, dy / d, dz / d, r - d);
        } else {
          // The centre is inside the box: out through the nearest face.
          const faces: [number, number, number, number][] = [
            [-1, 0, 0, x - b.minX], [1, 0, 0, b.maxX - x], [0, -1, 0, y - b.minY], [0, 1, 0, b.maxY - y], [0, 0, -1, z - b.minZ], [0, 0, 1, b.maxZ - z],
          ];
          const [nx, ny, nz, gap] = faces.reduce((m, f) => (f[3] < m[3] ? f : m));
          consider(nx, ny, nz, gap + r);
        }
      }
    }
  }
  for (const s of world.spheres) {
    const dx = x - s.x, dy = y - s.y, dz = z - s.z, d = Math.hypot(dx, dy, dz) || 1e-6;
    consider(dx / d, dy / d, dz / d, s.r + r - d);
  }
  return best;
}

/** How far along a ray (origin, unit direction) the first box lies, up to `max`; `max` when nothing is hit. */
export function rayDistance(world: CourierWorld, o: { x: number; y: number; z: number }, d: { x: number; y: number; z: number }, max: number): number {
  let best = max;
  if (d.y < -1e-6) best = Math.min(best, (world.ground - o.y) / d.y);
  const seen = new Set<number>();
  const steps = Math.ceil(max / world.cell) + 1;
  for (let s = 0; s <= steps; s += 1) {
    const t = Math.min(max, s * world.cell);
    const cx = Math.floor((o.x + d.x * t) / world.cell), cz = Math.floor((o.z + d.z * t) / world.cell);
    for (let i = cx - 1; i <= cx + 1; i += 1) {
      for (let j = cz - 1; j <= cz + 1; j += 1) {
        for (const index of world.hash.get(`${i},${j}`) ?? []) {
          if (seen.has(index)) continue;
          seen.add(index);
          const hit = rayBox(world.boxes[index], o, d);
          if (hit !== null && hit < best) best = hit;
        }
      }
    }
  }
  return Math.max(0, best);
}

function rayBox(b: Box3D, o: { x: number; y: number; z: number }, d: { x: number; y: number; z: number }): number | null {
  let t0 = 0, t1 = Infinity;
  for (const [origin, dir, lo, hi] of [[o.x, d.x, b.minX, b.maxX], [o.y, d.y, b.minY, b.maxY], [o.z, d.z, b.minZ, b.maxZ]] as const) {
    if (Math.abs(dir) < 1e-9) {
      if (origin < lo || origin > hi) return null;
    } else {
      let a = (lo - origin) / dir, c = (hi - origin) / dir;
      if (a > c) [a, c] = [c, a];
      t0 = Math.max(t0, a); t1 = Math.min(t1, c);
      if (t0 > t1) return null;
    }
  }
  return t0;
}
