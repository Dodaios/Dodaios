/**
 * Where the Foundry deck's pieces go, derived from a coding-floor layout: the
 * concourse between the two bay columns, the Core at the spawn point, and one
 * data rail per bay that runs like a circuit trace — out of the bay's inner
 * side, along its own lane of the concourse, to the Core's ring.
 *
 * Pure: the deck draws the rails, the packets ride them. Every point lies on
 * the floor (y = 0) and every rail stays on the concourse and the cross
 * aisles, so nothing is drawn under a desk.
 */
import type { Department, OfficeLayout, Point, Rect } from "./officeLayout";

/** The Core's ring on the floor round the spawn terminal: rails end on its outer edge. */
export const CORE_RING = { inner: 1.35, outer: 2.6 } as const;
/** Distance between two neighbouring rail lanes on the concourse (m). */
export const RAIL_LANE = 0.2;
/** Length of each 45° chamfer where a rail turns (m). */
const CHAMFER = 0.6;

export interface Rail {
  deptId: string;
  /** The bay's tint index: its signal colour. */
  tint: number;
  /** The trace from the bay to the Core's ring, as floor points; consecutive points differ. */
  points: Point[];
  /** Cumulative length at each point; the last entry is the rail's length. */
  lengths: number[];
}

export interface FoundryFrame {
  /** The concourse: the strip between the bay columns, from the north rooms to the south strip. */
  concourse: Rect;
  core: Point;
  rails: Rail[];
}

function withLengths(deptId: string, tint: number, raw: Point[]): Rail {
  const points: Point[] = [];
  for (const p of raw) {
    const last = points[points.length - 1];
    if (!last || Math.hypot(p.x - last.x, p.z - last.z) > 1e-6) points.push(p);
  }
  const lengths = [0];
  for (let i = 1; i < points.length; i += 1) {
    lengths.push(lengths[i - 1] + Math.hypot(points[i].x - points[i - 1].x, points[i].z - points[i - 1].z));
  }
  return { deptId, tint, points, lengths };
}

/** The point at distance `s` along a rail (clamped to its ends), and the direction it runs there. */
export function pointAlong(rail: Rail, s: number): { x: number; z: number; dx: number; dz: number } {
  const { points, lengths } = rail;
  const total = lengths[lengths.length - 1];
  const at = Math.min(Math.max(s, 0), total);
  let i = 1;
  while (i < points.length - 1 && lengths[i] < at) i += 1;
  const a = points[i - 1], b = points[i] ?? a;
  const span = lengths[i] - lengths[i - 1];
  const t = span > 0 ? (at - lengths[i - 1]) / span : 0;
  const len = Math.hypot(b.x - a.x, b.z - a.z) || 1;
  return { x: a.x + (b.x - a.x) * t, z: a.z + (b.z - a.z) * t, dx: (b.x - a.x) / len, dz: (b.z - a.z) / len };
}

/**
 * A rail from a bay to the Core: out of the bay's concourse side at its middle,
 * a 45° turn into its lane, down the lane, and a last 45° turn onto the ring.
 * Bays west of the concourse use lanes west of the centre line, east bays the
 * east ones; farther bays take the inner lanes, so a nearer bay's trace turns
 * into its outer lane before it would cross theirs.
 */
function railFor(dept: Department, concourse: Rect, core: Point, lane: number): Point[] {
  const west = (dept.minX + dept.maxX) / 2 < core.x;
  const side = west ? -1 : 1;
  const startX = west ? dept.maxX : dept.minX;
  const z0 = (dept.minZ + dept.maxZ) / 2;
  const laneX = core.x + side * (CORE_RING.outer * 0.55 + lane * RAIL_LANE);
  const dir = z0 < core.z ? 1 : -1;
  // The lane meets the ring where the ring's outer edge crosses its x.
  const dx = laneX - core.x;
  const ringZ = core.z - dir * Math.sqrt(Math.max(0, CORE_RING.outer ** 2 - dx * dx));
  const turn = Math.min(CHAMFER, Math.abs(laneX - startX) / 2, Math.abs(ringZ - z0) / 2);
  // Into the concourse, then a 45° step towards the Core into the lane.
  const enter = { x: laneX + side * turn, z: z0 };
  const points: Point[] = [{ x: startX, z: z0 }, enter, { x: laneX, z: z0 + dir * turn }];
  // Down the lane to the ring.
  points.push({ x: laneX, z: ringZ });
  // Never leave the concourse: the trace is clamped to it (bays sit right on its edges).
  return points.map((p) => ({ x: Math.min(concourse.maxX, Math.max(concourse.minX, p.x)), z: p.z }));
}

/** The concourse, the Core and every bay's rail for a coding-floor layout; null for any other floor. */
export function foundryFrame(layout: Pick<OfficeLayout, "variant" | "departments" | "furniture" | "rooms">): FoundryFrame | null {
  if (layout.variant !== "coding" || layout.departments.length === 0) return null;
  const terminal = layout.furniture.find((f) => f.kind === "spawnTerminal");
  if (!terminal) return null;
  const core = { x: terminal.x, z: terminal.z };
  const west = layout.departments.filter((d) => (d.minX + d.maxX) / 2 < core.x);
  const east = layout.departments.filter((d) => (d.minX + d.maxX) / 2 >= core.x);
  const firstZ = Math.min(...layout.departments.map((d) => d.minZ));
  const lastZ = Math.max(...layout.departments.map((d) => d.maxZ));
  const north = layout.rooms.filter((r) => r.maxZ <= firstZ + 1e-6).map((r) => r.maxZ);
  const south = layout.rooms.filter((r) => r.minZ >= lastZ - 1e-6).map((r) => r.minZ);
  const concourse: Rect = {
    minX: west.length > 0 ? Math.max(...west.map((d) => d.maxX)) : core.x - 3,
    maxX: east.length > 0 ? Math.min(...east.map((d) => d.minX)) : core.x + 3,
    minZ: north.length > 0 ? Math.max(...north) : firstZ,
    maxZ: south.length > 0 ? Math.min(...south) : lastZ,
  };
  // Lanes per side and per direction, farthest bay innermost.
  const rails: Rail[] = [];
  for (const column of [west, east]) {
    for (const dir of [1, -1]) {
      const group = column
        .filter((d) => ((d.minZ + d.maxZ) / 2 < core.z ? 1 : -1) === dir)
        .sort((a, b) => Math.abs((b.minZ + b.maxZ) / 2 - core.z) - Math.abs((a.minZ + a.maxZ) / 2 - core.z));
      group.forEach((dept, lane) => rails.push(withLengths(dept.id, dept.tint, railFor(dept, concourse, core, lane))));
    }
  }
  rails.sort((a, b) => a.deptId.localeCompare(b.deptId, undefined, { numeric: true }));
  return { concourse, core, rails };
}
