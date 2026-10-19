/**
 * The agents floor's fittings between the rooms, as data: what makes a team
 * studio a place (low screens round it, a storage cabinet, a sofa, a standing
 * table, planted front edges) and what furnishes the commons (the atrium's
 * step seating, the café's kitchen run and island, focus booths, benches,
 * planters, olive trees in pots and a few large trees).
 *
 * The campus plan (`campusLayout.ts`) places every piece, adds its footprint
 * to the floor's obstacles and gives it the spots people use it from. Pure
 * and shared: navigation reads the same boxes the renderer
 * (`AgentsFloorAmbience.tsx`) builds each piece inside. Every piece is a few
 * entries of instanced meshes there, so furnishing another studio costs no
 * extra draw calls.
 */
import type { Point, Rect } from "./officeLayout";

export type AgentsAmbienceKind =
  | "olive" | "tree" | "bench" | "planter"
  // A team studio's own pieces.
  | "screen" | "cabinet" | "sofa" | "hightable"
  // The commons.
  | "booth" | "steps" | "counter" | "island"
  // On the free plot: a stack of moving crates, waiting for a team.
  | "crate";

export type Compass = "north" | "south" | "east" | "west";

export interface AgentsAmbienceItem extends Rect {
  id: string;
  kind: AgentsAmbienceKind;
  /** The side the piece's front looks at. A bench runs north-south and faces east or west. */
  facing: Compass;
  /** Height of the piece in metres (a tree's crown top). */
  h: number;
  /** A team studio's colour index, for the pieces that wear it; absent = the floor's neutral oak and linen. */
  tint?: number;
}

/** An olive pot's square footprint, and a large tree's. */
export const OLIVE_BOX = 0.8;
export const TREE_BOX = 1.2;
/** Depth of a bench (its seat, front to back) and of a planter box. */
export const BENCH_DEPTH = 0.4;
export const PLANTER_DEPTH = 0.34;

export const OLIVE_H = 2.3;
export const TREE_H = 4.2;
export const BENCH_H = 0.46;
export const PLANTER_H = 0.52;

/** A studio's low screen: felt below, glass above. */
export const SCREEN = { t: 0.08, h: 1.3 } as const;
export const CABINET = { w: 1.6, d: 0.45, h: 1.0 } as const;
/** A two-seat sofa; its seat is at the height a seated figure's couch pose expects. */
export const SOFA = { w: 2.0, d: 0.85, h: 0.8 } as const;
export const HIGH_TABLE = { r: 0.4, h: 1.08 } as const;
/** A focus booth: three felt walls, a roof and a glass front with the doorway. */
export const BOOTH = { w: 1.3, d: 1.3, h: 2.25, wall: 0.08 } as const;
/** Step seating: three tiers rising towards the back. */
export const STEPS = { d: 2.4, tier: 0.8, rise: 0.45, tiers: 3 } as const;
/** The café's kitchen run with its shelf wall, and the island in front of it. */
export const COUNTER = { d: 0.65, h: 2.1 } as const;
export const ISLAND = { w: 2.6, d: 0.9, h: 0.95 } as const;
export const CRATE = { w: 0.9, d: 0.6, h: 0.9 } as const;

/** Rotation about +y that turns a piece's front (its local +z) towards `facing`. */
export function yawOf(facing: Compass): number {
  return facing === "south" ? 0 : facing === "east" ? Math.PI / 2 : facing === "north" ? Math.PI : -Math.PI / 2;
}

/** A piece's own width (along its front) and depth, whatever way it is turned. */
export function ownSize(item: Pick<AgentsAmbienceItem, "facing" | keyof Rect>): { w: number; d: number } {
  const dx = item.maxX - item.minX, dz = item.maxZ - item.minZ;
  return item.facing === "east" || item.facing === "west" ? { w: dz, d: dx } : { w: dx, d: dz };
}

/** A point of a piece's own frame (x along its front, z towards its front, origin in its middle) on the floor plan. */
export function toFloor(item: Pick<AgentsAmbienceItem, "facing" | keyof Rect>, lx: number, lz: number): Point {
  const yaw = yawOf(item.facing), cos = Math.cos(yaw), sin = Math.sin(yaw);
  return { x: (item.minX + item.maxX) / 2 + lx * cos + lz * sin, z: (item.minZ + item.maxZ) / 2 - lx * sin + lz * cos };
}

/** A piece w wide (along its front) and d deep, centred on (x, z), its front towards `facing`. */
function oriented(id: string, kind: AgentsAmbienceKind, x: number, z: number, w: number, d: number, facing: Compass, h: number, tint?: number): AgentsAmbienceItem {
  const turned = facing === "east" || facing === "west";
  const halfX = (turned ? d : w) / 2, halfZ = (turned ? w : d) / 2;
  return { id, kind, facing, h, minX: x - halfX, maxX: x + halfX, minZ: z - halfZ, maxZ: z + halfZ, ...(tint === undefined ? {} : { tint }) };
}

/** An olive tree in its pot, centred on (x, z). */
export function olive(id: string, x: number, z: number): AgentsAmbienceItem {
  return oriented(id, "olive", x, z, OLIVE_BOX, OLIVE_BOX, "south", OLIVE_H);
}

/** A large tree in a round stone planter; its crown spreads above head height, beyond its footprint. */
export function tree(id: string, x: number, z: number): AgentsAmbienceItem {
  return oriented(id, "tree", x, z, TREE_BOX, TREE_BOX, "south", TREE_H);
}

/** A bench running north-south from z0 to z1, centred on x, its front towards `facing`. */
export function bench(id: string, x: number, z0: number, z1: number, facing: "east" | "west"): AgentsAmbienceItem {
  return { id, kind: "bench", facing, h: BENCH_H, minX: x - BENCH_DEPTH / 2, maxX: x + BENCH_DEPTH / 2, minZ: Math.min(z0, z1), maxZ: Math.max(z0, z1) };
}

/** A planter box filling `rect`; it may run north-south or east-west. */
export function planter(id: string, rect: Rect): AgentsAmbienceItem {
  return { id, kind: "planter", facing: "south", h: PLANTER_H, minX: rect.minX, maxX: rect.maxX, minZ: rect.minZ, maxZ: rect.maxZ };
}

/** A low screen along a straight line from (x0, z0) to (x1, z1) (north-south or east-west), in a studio's colour. */
export function screen(id: string, x0: number, z0: number, x1: number, z1: number, tint?: number): AgentsAmbienceItem {
  const t = SCREEN.t / 2;
  return {
    id, kind: "screen", facing: "south", h: SCREEN.h, ...(tint === undefined ? {} : { tint }),
    minX: Math.min(x0, x1) - t, maxX: Math.max(x0, x1) + t, minZ: Math.min(z0, z1) - t, maxZ: Math.max(z0, z1) + t,
  };
}

export function cabinet(id: string, x: number, z: number, facing: Compass, tint?: number): AgentsAmbienceItem {
  return oriented(id, "cabinet", x, z, CABINET.w, CABINET.d, facing, CABINET.h, tint);
}

export function sofa(id: string, x: number, z: number, facing: Compass, tint?: number): AgentsAmbienceItem {
  return oriented(id, "sofa", x, z, SOFA.w, SOFA.d, facing, SOFA.h, tint);
}

export function highTable(id: string, x: number, z: number): AgentsAmbienceItem {
  return oriented(id, "hightable", x, z, HIGH_TABLE.r * 2, HIGH_TABLE.r * 2, "south", HIGH_TABLE.h);
}

export function booth(id: string, x: number, z: number, facing: Compass, tint?: number): AgentsAmbienceItem {
  return oriented(id, "booth", x, z, BOOTH.w, BOOTH.d, facing, BOOTH.h, tint);
}

/** Step seating `length` wide, centred on (x, z), its lowest tier towards `facing`. */
export function steps(id: string, x: number, z: number, length: number, facing: Compass): AgentsAmbienceItem {
  return oriented(id, "steps", x, z, length, STEPS.d, facing, STEPS.rise * STEPS.tiers);
}

export function counter(id: string, x: number, z: number, length: number, facing: Compass): AgentsAmbienceItem {
  return oriented(id, "counter", x, z, length, COUNTER.d, facing, COUNTER.h);
}

export function crate(id: string, x: number, z: number, facing: Compass): AgentsAmbienceItem {
  return oriented(id, "crate", x, z, CRATE.w, CRATE.d, facing, CRATE.h);
}

export function island(id: string, x: number, z: number, facing: Compass): AgentsAmbienceItem {
  return oriented(id, "island", x, z, ISLAND.w, ISLAND.d, facing, ISLAND.h);
}

/** The box round two points of a piece's own frame, on the floor plan. */
function boxOf(item: AgentsAmbienceItem, lx0: number, lz0: number, lx1: number, lz1: number): Rect {
  const a = toFloor(item, lx0, lz0), b = toFloor(item, lx1, lz1);
  return { minX: Math.min(a.x, b.x), maxX: Math.max(a.x, b.x), minZ: Math.min(a.z, b.z), maxZ: Math.max(a.z, b.z) };
}

/**
 * What a walker bumps into at a piece: its footprint — except a focus booth,
 * which is its back and its two side walls, so a person walks in through the
 * front and stands inside.
 */
export function ambienceObstacles(item: AgentsAmbienceItem): Rect[] {
  if (item.kind !== "booth") return [{ minX: item.minX, maxX: item.maxX, minZ: item.minZ, maxZ: item.maxZ }];
  const { w, d } = ownSize(item), t = BOOTH.wall;
  return [
    boxOf(item, -w / 2, -d / 2, w / 2, -d / 2 + t),
    boxOf(item, -w / 2, -d / 2, -w / 2 + t, d / 2),
    boxOf(item, w / 2 - t, -d / 2, w / 2, d / 2),
  ];
}

/** A place at a piece, in the plan: where a figure is and the yaw it looks along. */
export interface AmbiencePlace extends Point { facing: number }

/** The two seats of a sofa. */
export function sofaSeats(item: AgentsAmbienceItem): AmbiencePlace[] {
  return [-0.45, 0.45].map((lx) => ({ ...toFloor(item, lx, 0.05), facing: yawOf(item.facing) }));
}

/** Seats along a bench, one per 1.1 m, looking the way the bench faces. */
export function benchSeats(item: AgentsAmbienceItem): AmbiencePlace[] {
  const length = item.maxZ - item.minZ, count = Math.max(1, Math.floor(length / 1.1));
  const x = (item.minX + item.maxX) / 2;
  return Array.from({ length: count }, (_, i) => ({ x, z: item.minZ + (length * (i + 0.5)) / count, facing: yawOf(item.facing) }));
}

/** Standing places round a high table, each looking at it; `angles` are compass yaws from the table (0 = south of it). */
export function tableStands(item: AgentsAmbienceItem, angles: readonly number[]): AmbiencePlace[] {
  const cx = (item.minX + item.maxX) / 2, cz = (item.minZ + item.maxZ) / 2, reach = HIGH_TABLE.r + 0.42;
  return angles.map((a) => ({ x: cx + Math.sin(a) * reach, z: cz + Math.cos(a) * reach, facing: a + Math.PI }));
}

/** Seats on the lowest tier of step seating, 0.9 m apart. */
export function stepsSeats(item: AgentsAmbienceItem): AmbiencePlace[] {
  const { w, d } = ownSize(item), count = Math.max(1, Math.floor((w - 0.6) / 0.9));
  return Array.from({ length: count }, (_, i) => ({
    ...toFloor(item, (i - (count - 1) / 2) * 0.9, d / 2 - STEPS.tier / 2), facing: yawOf(item.facing),
  }));
}

/** Inside a focus booth, at its shelf. */
export function boothPlace(item: AgentsAmbienceItem): AmbiencePlace {
  return { ...toFloor(item, 0, 0.12), facing: yawOf(item.facing) + Math.PI };
}

/** Standing places in front of a counter or an island, each looking at it. */
export function counterStands(item: AgentsAmbienceItem, offsets: readonly number[]): AmbiencePlace[] {
  const { d } = ownSize(item);
  return offsets.map((lx) => ({ ...toFloor(item, lx, d / 2 + 0.55), facing: yawOf(item.facing) + Math.PI }));
}
