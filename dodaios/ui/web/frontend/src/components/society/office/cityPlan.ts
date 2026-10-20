/**
 * The plan of the city round the Dodaios tower: a dense megacity on a street
 * grid far below the floor, its flying traffic, the light beams over its
 * tallest roofs and the singularity it is built round. Pure and tested; the
 * drawing lives in SingularityCity.tsx.
 *
 * The camera always looks down at the floor (the horizon never shows), so the
 * city is composed to be seen from above: roofs, avenues and traffic lanes
 * read at every zoom, and the singularity hovers over the rooftops off to
 * the north where it shows beside the floor in the home view.
 *
 * Out of the way by construction: nothing stands within `CITY.clear` metres
 * of the slab, every roof within `CITY.lowReach` metres lies at least
 * `CITY.nearRoof` below the floor (lower the nearer it is), and every
 * traffic lane flies above the roofs it circles.
 */
import type { Rect } from "./officeLayout";

/** The city's street level, metres below the floor. */
export const GROUND_Y = -330;

export const CITY = {
  /** The street grid: a cell per lot, an avenue every `avenueEvery` cells. */
  cell: 36,
  avenueEvery: 2,
  /** Half widths of a street and an avenue, in metres from the grid line. */
  street: 2.6,
  avenue: 4.6,
  /** Empty plaza round the building before the first tower, from the slab's edge. */
  clear: 70,
  /** How far the city reaches from the building's middle. */
  radius: 700,
  /** Within this distance of the slab's edge roofs stay well below the floor... */
  lowReach: 330,
  /** ...at least this far below at the edge of `lowReach`, `nearDrop` metres more at the plaza's edge. */
  nearRoof: -70,
  nearDrop: 100,
} as const;

/** The singularity: where it hovers (bearing from the building's middle, distance, height) and its parts' sizes. */
export const SINGULARITY = {
  bearing: [-0.3, -0.95] as const,
  distance: 470,
  y: -205,
  core: 17,
  disc: { inner: 22, outer: 112, tilt: 0.2 },
  /** No ordinary tower within this distance of the core's foot: the disc floats over a clear crater. */
  crater: 150,
  /** The core district: tall spires on a ring round the crater, their crowns lit gold. */
  spires: 18,
  spireRing: [172, 212] as const,
  /** Inside the crater, so no ring ever cuts a tower. */
  rings: [
    { radius: 84, tilt: [0.32, 0.1] as const, speed: 0.05 },
    { radius: 102, tilt: [-0.22, 0.38] as const, speed: -0.035 },
    { radius: 120, tilt: [0.12, -0.3] as const, speed: 0.024 },
  ],
} as const;

/** Tower classes; the drawing has one geometry (and one draw call) per class. */
export const TOWER_KINDS = ["block", "setback", "prism", "spire"] as const;
export type TowerKind = (typeof TOWER_KINDS)[number];

export interface Tower {
  kind: TowerKind;
  x: number;
  z: number;
  /** Footprint and height in metres; the foot stands on `GROUND_Y`. */
  w: number;
  d: number;
  h: number;
  /** Rotation about y (prisms and spires only; blocks follow the grid). */
  rot: number;
  /** Per-tower look: a random seed, the share of lit windows, light seams on its corners, a lit crown. */
  seed: number;
  lit: number;
  seams: boolean;
  crown: boolean;
  /** 0 cool white, 1 cyan, 2 gold: the colour of its seams and crown. */
  accent: 0 | 1 | 2;
}

export interface Lane {
  /** An ellipse round (cx, cz) at height y; omega is radians per second, its sign the direction. */
  cx: number;
  cz: number;
  rx: number;
  rz: number;
  y: number;
  omega: number;
  cars: number;
  bob: number;
}

export interface Beam {
  x: number;
  y: number;
  z: number;
  height: number;
  radius: number;
  accent: 0 | 1 | 2;
}

export interface Beacon {
  x: number;
  y: number;
  z: number;
  /** 0 a slow red aviation light, 1 a white strobe. */
  kind: 0 | 1;
  phase: number;
}

export interface CityPlan {
  /** The building's middle (the plaza's centre); the street grid runs on absolute multiples of `CITY.cell`. */
  centre: { x: number; z: number };
  towers: Tower[];
  lanes: Lane[];
  beams: Beam[];
  beacons: Beacon[];
  singularity: { x: number; y: number; z: number };
}

export function lcg(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state * 1664525 + 1013904223) >>> 0;
    return state / 0x1_0000_0000;
  };
}

/** Distance from a point to a rectangle (0 inside it). */
export function distanceToRect(x: number, z: number, r: Rect): number {
  const dx = Math.max(r.minX - x, 0, x - r.maxX), dz = Math.max(r.minZ - z, 0, z - r.maxZ);
  return Math.hypot(dx, dz);
}

/** The highest a roof may come at this distance from the slab's edge (metres, floor = 0); Infinity beyond `lowReach`. */
export function roofLimit(edgeDistance: number): number {
  if (edgeDistance >= CITY.lowReach) return Infinity;
  const nearness = 1 - Math.max(0, edgeDistance - CITY.clear) / (CITY.lowReach - CITY.clear);
  return CITY.nearRoof - nearness * CITY.nearDrop;
}

/**
 * The city's anchor: the grid line nearest the building's middle. The city is laid out from it and every lot
 * draws its own random numbers from its absolute grid cell, so a floor that grows or shrinks by a few metres
 * keeps the same city round it (only the plaza and the roof limits follow the new edge).
 */
export function cityAnchor(bounds: Rect): { x: number; z: number; i: number; j: number } {
  const i = Math.round((bounds.minX + bounds.maxX) / 2 / CITY.cell), j = Math.round((bounds.minZ + bounds.maxZ) / 2 / CITY.cell);
  return { x: i * CITY.cell, z: j * CITY.cell, i, j };
}

/** A lot's own random numbers, from its absolute grid cell. */
function lotRandom(i: number, j: number): () => number {
  let h = Math.imul(i, 0x27d4eb2d) ^ Math.imul(j, 0x165667b1) ^ 0x5ec7a1;
  h = Math.imul(h ^ (h >>> 15), 0x2c1b3c6d);
  return lcg(h ^ (h >>> 13));
}

export function singularityPosition(bounds: Rect): { x: number; y: number; z: number } {
  const { x: cx, z: cz } = cityAnchor(bounds);
  const [bx, bz] = SINGULARITY.bearing, len = Math.hypot(bx, bz);
  return { x: cx + (bx / len) * SINGULARITY.distance, y: SINGULARITY.y, z: cz + (bz / len) * SINGULARITY.distance };
}

/** The half width of the street on an (absolute) grid line: avenues on every `avenueEvery`-th line. */
function streetHalf(line: number): number {
  return ((line % CITY.avenueEvery) + CITY.avenueEvery) % CITY.avenueEvery === 0 ? CITY.avenue : CITY.street;
}

/** How many traffic lanes circle the building, and the room a lane keeps above the roofs beneath it. */
const BUILDING_LANES = 7;
const LANE_HEADROOM = 8;

/** How far (metres, roughly) a point lies from a lane's ellipse. */
function laneDistance(lane: Lane, x: number, z: number): number {
  const dx = (x - lane.cx) / lane.rx, dz = (z - lane.cz) / lane.rz;
  return Math.abs(Math.hypot(dx, dz) - 1) * Math.min(lane.rx, lane.rz);
}

/** The highest roof (metres, floor = 0) a tower of this reach may have here: under the roof limit and below every lane over it. */
function roofCap(x: number, z: number, reach: number, bounds: Rect, lanes: readonly Lane[]): number {
  let cap = roofLimit(distanceToRect(x, z, bounds));
  for (const lane of lanes) {
    if (laneDistance(lane, x, z) < reach + 3) cap = Math.min(cap, lane.y - lane.bob - LANE_HEADROOM);
  }
  return cap;
}

export function planCity(bounds: Rect): CityPlan {
  const rand = lcg(0x5ec7a1);
  const anchor = cityAnchor(bounds), cx = anchor.x, cz = anchor.z;
  // The building's own middle: the plaza and the traffic circle it, the street grid hangs off the anchor.
  const bx = (bounds.minX + bounds.maxX) / 2, bz = (bounds.minZ + bounds.maxZ) / 2;
  const sing = singularityPosition(bounds);

  // Flying traffic first, so the towers under it can stay below it: ellipses round the building, high over the
  // rooftops where the camera sees them from every side, and fast rings round the singularity.
  const lanes: Lane[] = [];
  const half = Math.hypot(bounds.maxX - bounds.minX, bounds.maxZ - bounds.minZ) / 2;
  for (let i = 0; i < BUILDING_LANES; i += 1) {
    const r = half + CITY.clear + 18 + i * 34 + rand() * 12;
    // An ellipse no narrower than r in either direction, so no lane cuts across the plaza.
    const stretch = 1 + rand() * 0.3;
    const [rx, rz] = i % 2 === 0 ? [r * stretch, r] : [r, r * stretch];
    const y = -62 - rand() * 34;
    const dir = i % 2 === 0 ? 1 : -1;
    lanes.push({ cx: bx + (rand() - 0.5) * 12, cz: bz + (rand() - 0.5) * 12, rx, rz, y, omega: (dir * (16 + rand() * 10)) / r, cars: Math.round((2 * Math.PI * r) / 18), bob: 1 + rand() * 2.5 });
  }
  const buildingLanes = [...lanes];
  for (let i = 0; i < 3; i += 1) {
    const r = SINGULARITY.crater - 8 - i * 14;
    lanes.push({ cx: sing.x, cz: sing.z, rx: r, rz: r, y: sing.y - 30 - i * 9, omega: ((i % 2 === 0 ? 1 : -1) * (30 + i * 6)) / r, cars: Math.round((2 * Math.PI * r) / 11), bob: 0.6 });
  }

  const towers: Tower[] = [];
  const cell = CITY.cell, span = Math.ceil(CITY.radius / cell) + 1;
  // Ordinary towers keep clear of the crater and of the ring of spires round it.
  const districtClear = SINGULARITY.spireRing[1] + 16;
  for (let i = -span; i < span; i += 1) {
    for (let j = -span; j < span; j += 1) {
      // The lot between grid lines i..i+1 and j..j+1, less the streets round it and a pavement.
      const gi = anchor.i + i, gj = anchor.j + j;
      const x0 = gi * cell + streetHalf(gi) + 1.5, x1 = (gi + 1) * cell - streetHalf(gi + 1) - 1.5;
      const z0 = gj * cell + streetHalf(gj) + 1.5, z1 = (gj + 1) * cell - streetHalf(gj + 1) - 1.5;
      const mx = (x0 + x1) / 2, mz = (z0 + z1) / 2;
      const fromCentre = Math.hypot(mx - cx, mz - cz);
      const lot = lotRandom(gi, gj);
      const roll = lot(), sizeA = lot(), sizeB = lot(), heightRoll = lot(), kindRoll = lot(), lookRoll = lot(), seed = lot(), slideX = lot(), slideZ = lot(), turn = lot();
      if (fromCentre > CITY.radius) continue;
      const lotW = x1 - x0, lotD = z1 - z0;
      // The tower must clear the plaza with all of its lot, not just its middle.
      if (distanceToRect(mx, mz, bounds) - Math.hypot(lotW, lotD) / 2 < CITY.clear) continue;
      if (Math.hypot(mx - sing.x, mz - sing.z) - Math.hypot(lotW, lotD) / 2 < districtClear) continue;
      // Thinner towards the city's rim, where a gap reads as distance.
      if (roll > 0.9 - (fromCentre / CITY.radius) * 0.25) continue;
      const far = Math.min(1, fromCentre / CITY.radius);
      let h = 70 + heightRoll * heightRoll * (130 + far * 170);
      const kind: TowerKind = h > 220 && kindRoll < 0.45 ? "spire" : kindRoll < 0.42 ? "block" : kindRoll < 0.75 ? "setback" : "prism";
      const w = Math.min(lotW, 13 + sizeA * 16), d = kind === "prism" || kind === "spire" ? w : Math.min(lotD, 13 + sizeB * 16);
      const x = x0 + w / 2 + (lotW - w) * slideX, z = z0 + d / 2 + (lotD - d) * slideZ;
      h = Math.min(h, roofCap(x, z, Math.hypot(w, d) / 2, bounds, buildingLanes) - GROUND_Y);
      if (h < 30) continue;
      towers.push({
        kind, x, z, w, d, h,
        rot: kind === "prism" || kind === "spire" ? turn * Math.PI : 0,
        seed, lit: 0.1 + lookRoll * 0.16, seams: lookRoll > 0.62, crown: h > 170 && lookRoll > 0.35,
        accent: lookRoll > 0.86 ? 2 : lookRoll > 0.72 ? 1 : 0,
      });
    }
  }
  // The core district: a ring of gold-crowned spires round the crater.
  for (let i = 0; i < SINGULARITY.spires; i += 1) {
    const angle = (i / SINGULARITY.spires) * Math.PI * 2 + rand() * 0.12;
    const r = SINGULARITY.spireRing[0] + rand() * (SINGULARITY.spireRing[1] - SINGULARITY.spireRing[0]);
    const x = sing.x + Math.cos(angle) * r, z = sing.z + Math.sin(angle) * r;
    const w = 16 + rand() * 8;
    const h = Math.min(230 + rand() * 120, roofCap(x, z, w / 2, bounds, buildingLanes) - GROUND_Y);
    towers.push({ kind: "spire", x, z, w, d: w, h, rot: rand() * Math.PI, seed: rand(), lit: 0.3, seams: true, crown: true, accent: 2 });
  }

  // Light beams over the tallest far roofs (the singularity's jets are drawn with them).
  const tallest = [...towers].sort((a, b) => b.h - a.h).filter((t) => distanceToRect(t.x, t.z, bounds) > CITY.lowReach * 0.6).slice(0, 9);
  const beams: Beam[] = tallest.map((t) => ({ x: t.x, y: GROUND_Y + t.h, z: t.z, height: 340, radius: 1.1, accent: t.accent === 0 ? 1 : t.accent }));

  // Aviation lights on every tall roof, a strobe on some.
  const beacons: Beacon[] = [];
  for (const t of towers) {
    if (t.h < 150) continue;
    beacons.push({ x: t.x, y: GROUND_Y + t.h + 1.5, z: t.z, kind: t.seed > 0.82 ? 1 : 0, phase: t.seed });
  }
  return { centre: { x: bx, z: bz }, towers, lanes, beams, beacons, singularity: sing };
}
