/**
 * The coding floor's open-plan dressing as data: tree planters closing every
 * cross aisle at the windows; beside each outer neighbourhood a phone booth
 * and a planter trough along the glass, either side of its window spot; and
 * down the concourse, the floor's main street, a grove — a tall tree in a
 * round planter ringed by a bench — in the middle of every row of
 * neighbourhoods.
 *
 * Pure and shared: the layout adds every item to its obstacles, the renderer
 * builds each piece inside the same box. The window pieces stand in the
 * 1.6 m strip between the neighbourhoods and the glass; the groves stand on
 * the concourse's centre line, clear of the cross aisles and the town square.
 */
import type { Rect } from "./officeLayout";

export type AmbienceKind = "tree" | "booth" | "trough" | "grove";

export interface AmbienceItem extends Rect {
  id: string;
  kind: AmbienceKind;
  /** The side the piece's front looks at: a booth's door faces into the office. */
  facing: "east" | "west";
  /** Height of the piece in metres (a tree's crown top). */
  h: number;
  /** The neighbourhood a booth belongs to (its tint index): the booth wears that team's colour. */
  tint?: number;
}

/** A tree planter's square footprint, and how far its centre stands out from the neighbourhood column. */
export const TREE_BOX = 0.84;
const TREE_OUT = 0.8;
/** Troughs: depth, and the band they stand in, measured out from the neighbourhood column. */
const TROUGH_DEPTH = 0.32;
const TROUGH_OUT = 1.04;
/** A phone booth: depth across the strip, length along it, and its gap to the neighbourhood column. */
export const BOOTH = { d: 1.0, len: 1.15, out: 0.28, h: 2.25 } as const;
/** Half the gap left round a neighbourhood's window spot, and the margin at its ends. */
const WINDOW_GAP = 0.85;
const END_MARGIN = 0.35;
const MIN_RUN = 1.2;
/** A grove's round footprint (its square box) on the concourse. */
export const GROVE_BOX = 2.1;

export const TROUGH_H = 0.46;
export const TREE_H = 2.35;
export const GROVE_H = 4.4;

/** Where the aisles are: the neighbourhood rows and the room strips north and south of them. */
export interface AmbienceFrame {
  departments: readonly (Rect & { tint?: number })[];
  rooms: readonly Rect[];
}

/** Every ambience piece of a coding floor, in a stable order. */
export function codingAmbience({ departments, rooms }: AmbienceFrame): AmbienceItem[] {
  if (departments.length === 0) return [];
  const colMinX = Math.min(...departments.map((d) => d.minX));
  const colMaxX = Math.max(...departments.map((d) => d.maxX));
  const firstZ = Math.min(...departments.map((d) => d.minZ));
  const lastZ = Math.max(...departments.map((d) => d.maxZ));
  const north = rooms.filter((r) => r.maxZ <= firstZ + 1e-6).map((r) => r.maxZ);
  const south = rooms.filter((r) => r.minZ >= lastZ - 1e-6).map((r) => r.minZ);
  const items: AmbienceItem[] = [];

  // Cross aisles: in front of the north rooms, between neighbourhood rows, in front of the south strip.
  const rowStarts = [...new Set(departments.map((d) => d.minZ))].sort((a, b) => a - b);
  const aisles: number[] = [];
  if (north.length > 0) aisles.push((Math.max(...north) + firstZ) / 2);
  for (let i = 1; i < rowStarts.length; i += 1) {
    const above = Math.max(...departments.filter((d) => d.minZ === rowStarts[i - 1]).map((d) => d.maxZ));
    aisles.push((above + rowStarts[i]) / 2);
  }
  if (south.length > 0) aisles.push((lastZ + Math.min(...south)) / 2);
  aisles.forEach((z, i) => {
    for (const [side, x] of [["west", colMinX - TREE_OUT], ["east", colMaxX + TREE_OUT]] as const) {
      items.push({
        id: `tree-${side}-${i}`, kind: "tree", facing: side === "west" ? "east" : "west", h: TREE_H,
        minX: x - TREE_BOX / 2, maxX: x + TREE_BOX / 2, minZ: z - TREE_BOX / 2, maxZ: z + TREE_BOX / 2,
      });
    }
  });

  // Beside each outer neighbourhood: a phone booth in the run north of its window spot, a trough in the run south of it.
  departments.forEach((dept, index) => {
    const zc = (dept.minZ + dept.maxZ) / 2;
    const runs = [[dept.minZ + END_MARGIN, zc - WINDOW_GAP], [zc + WINDOW_GAP, dept.maxZ - END_MARGIN]] as const;
    for (const side of ["west", "east"] as const) {
      const outer = side === "west" ? dept.minX <= colMinX + 1e-6 : dept.maxX >= colMaxX - 1e-6;
      if (!outer) continue;
      const facing = side === "west" ? "east" : "west";
      runs.forEach(([z0, z1], run) => {
        if (z1 - z0 < MIN_RUN) return;
        if (run === 0) {
          const [minX, maxX] = side === "west"
            ? [colMinX - BOOTH.out - BOOTH.d, colMinX - BOOTH.out]
            : [colMaxX + BOOTH.out, colMaxX + BOOTH.out + BOOTH.d];
          items.push({ id: `booth-${index}-${side}`, kind: "booth", facing, h: BOOTH.h, tint: dept.tint ?? index,
            minX, maxX, minZ: z0, maxZ: z0 + BOOTH.len });
          return;
        }
        const [minX, maxX] = side === "west"
          ? [colMinX - TROUGH_OUT - TROUGH_DEPTH, colMinX - TROUGH_OUT]
          : [colMaxX + TROUGH_OUT, colMaxX + TROUGH_OUT + TROUGH_DEPTH];
        items.push({ id: `trough-${index}-${side}`, kind: "trough", facing, h: TROUGH_H, minX, maxX, minZ: z0, maxZ: z1 });
      });
    }
  });

  // The main street: a grove in the middle of every row, on the concourse's centre line.
  const west = departments.filter((d) => d.minX <= colMinX + 1e-6);
  const east = departments.filter((d) => d.maxX >= colMaxX - 1e-6 && d.minX > colMinX + 1e-6);
  if (west.length > 0 && east.length > 0) {
    const cx = (Math.max(...west.map((d) => d.maxX)) + Math.min(...east.map((d) => d.minX))) / 2;
    rowStarts.forEach((start, i) => {
      const row = departments.filter((d) => d.minZ === start);
      const z = (start + Math.max(...row.map((d) => d.maxZ))) / 2;
      items.push({
        id: `grove-${i}`, kind: "grove", facing: "east", h: GROVE_H,
        minX: cx - GROVE_BOX / 2, maxX: cx + GROVE_BOX / 2, minZ: z - GROVE_BOX / 2, maxZ: z + GROVE_BOX / 2,
      });
    });
  }
  return items;
}
