import { BOARD_COLUMNS, type BoardActivity, type BoardColumn } from "../agentBoard";

/**
 * The pure half of the simulation: where each agent stands and where the
 * camera stands to see them all.
 *
 * The floor is the Agents board laid flat. Its four columns are four fields,
 * and an agent stands in the field its work is in. Inside a field the agents
 * fill rows from the front, in the order the board lists them, so the ones
 * that work or ask stand nearest the viewer.
 */

/** One agent as the simulation needs it. */
export interface SimAgent {
  /** The board item's id. */
  id: string;
  /** The coding CLI's id ("" when unknown) and its name. */
  agent: string;
  agentLabel: string;
  title: string;
  place: BoardColumn;
  activity: BoardActivity;
  /** The words of the card's footer, already translated. */
  stateLabel: string;
}

/** The side of the square one agent stands in, in metres. */
export const CELL_M = 1.85;
/** The free strip between two fields side by side. */
export const GAP_M = 0.5;
/** The free strip between two fields one behind the other: room for a field's name. */
export const ROW_GAP_M = 1.3;
/** The margin between a field's edge and its first agent. */
export const PAD_M = 0.35;
/** How tall a figure with its name tag stands, for framing. */
export const HEAD_ROOM_M = 1.6;
/** The camera's height above the floor, as an angle from the horizon. */
export const CAMERA_PITCH = 0.78;
/** What the camera looks at: a point a little above the floor's centre. */
export const LOOK_AT_Y = 0.35;
/** The share of the picture the floor may fill; the rest is margin for names and the key. */
const FILL = 0.9;
const MAX_COLUMNS = 5;
/** The fields in one row of the floor: all four, two by two, or one behind the other. */
const FIELDS_PER_ROW = [4, 2, 1] as const;

export interface SimField {
  column: BoardColumn;
  /** Centre and size on the floor. */
  x: number;
  z: number;
  width: number;
  depth: number;
  count: number;
}

export interface SimSpot {
  id: string;
  x: number;
  z: number;
}

export interface SimLayout {
  fields: SimField[];
  spots: Map<string, SimSpot>;
  /** The whole floor, centred on the origin. */
  width: number;
  depth: number;
}

interface Plan {
  perRow: number;
  columns: number;
  fieldWidth: number;
  fieldDepth: number;
  width: number;
  depth: number;
}

function planFor(perRow: number, columns: number, fullest: number): Plan {
  const rows = Math.max(1, Math.ceil(fullest / columns));
  const fieldRows = BOARD_COLUMNS.length / perRow;
  const fieldWidth = columns * CELL_M + 2 * PAD_M;
  const fieldDepth = rows * CELL_M + 2 * PAD_M;
  return {
    perRow,
    columns,
    fieldWidth,
    fieldDepth,
    width: perRow * fieldWidth + (perRow - 1) * GAP_M,
    depth: fieldRows * fieldDepth + (fieldRows - 1) * ROW_GAP_M,
  };
}

/** The shape the floor has on screen, seen from the camera's height: width over height. */
function seenAspect(plan: Pick<Plan, "width" | "depth">): number {
  return plan.width / (plan.depth * Math.sin(CAMERA_PITCH) + HEAD_ROOM_M * Math.cos(CAMERA_PITCH));
}

/**
 * Lay the agents out.
 *
 * Every field has the same size, set by the fullest one, so a field never
 * moves because another one filled up by one agent. The fields stand in one
 * row, two by two or one behind the other, and are as many agents wide as
 * brings the floor's shape nearest the panel's (`aspect`, width over height):
 * a wide panel gets a wide floor and a narrow side panel a deep one.
 */
export function layoutSimulation(agents: readonly Pick<SimAgent, "id" | "place">[], aspect = 2): SimLayout {
  const byColumn = new Map<BoardColumn, string[]>(BOARD_COLUMNS.map((column) => [column, []]));
  for (const agent of agents) byColumn.get(agent.place)?.push(agent.id);
  const fullest = Math.max(1, ...[...byColumn.values()].map((ids) => ids.length));
  const wanted = Math.max(0.3, aspect);
  let plan = planFor(4, 2, fullest);
  let best = Infinity;
  for (const perRow of FIELDS_PER_ROW) {
    for (let columns = 1; columns <= Math.min(MAX_COLUMNS, Math.max(2, fullest)); columns += 1) {
      const candidate = planFor(perRow, columns, fullest);
      const miss = Math.abs(Math.log(seenAspect(candidate) / wanted));
      if (miss < best - 1e-9) {
        best = miss;
        plan = candidate;
      }
    }
  }

  const fields: SimField[] = [];
  const spots = new Map<string, SimSpot>();
  BOARD_COLUMNS.forEach((column, index) => {
    const ids = byColumn.get(column) ?? [];
    const x = -plan.width / 2 + plan.fieldWidth / 2 + (index % plan.perRow) * (plan.fieldWidth + GAP_M);
    // The first fields stand at the back, as the first lines of a page stand on top.
    const z = -plan.depth / 2 + plan.fieldDepth / 2 + Math.floor(index / plan.perRow) * (plan.fieldDepth + ROW_GAP_M);
    fields.push({ column, x, z, width: plan.fieldWidth, depth: plan.fieldDepth, count: ids.length });
    ids.forEach((id, at) => {
      const row = Math.floor(at / plan.columns);
      const inRow = Math.min(plan.columns, ids.length - row * plan.columns);
      const slot = at % plan.columns;
      spots.set(id, {
        id,
        // A row that is not full stands centred in its field.
        x: x + (slot - (inRow - 1) / 2) * CELL_M,
        // Row 0 is the front row: the edge nearest the viewer.
        z: z + plan.fieldDepth / 2 - PAD_M - CELL_M / 2 - row * CELL_M,
      });
    });
  });
  return { fields, spots, width: plan.width, depth: plan.depth };
}

/** A stable number in [0, 1) for an id: each agent's own rhythm, the same on every draw. */
export function phaseOf(id: string): number {
  let hash = 2166136261;
  for (let index = 0; index < id.length; index += 1) {
    hash ^= id.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return ((hash >>> 0) % 10_000) / 10_000;
}

/**
 * How far back the camera stands so the whole floor, and the figures on it,
 * are in view. The camera looks down at `CAMERA_PITCH` on the floor's centre.
 */
export function cameraDistance(layout: Pick<SimLayout, "width" | "depth">, aspect: number, fovDeg: number): number {
  const half = Math.tan((fovDeg * Math.PI) / 360) * FILL;
  const wide = half * Math.max(0.2, aspect);
  const sin = Math.sin(CAMERA_PITCH);
  const cos = Math.cos(CAMERA_PITCH);
  // The corners of the box the floor and its figures fill; the front edge
  // reaches a little further, for the fields' names.
  const corners: [number, number, number][] = [];
  for (const x of [-layout.width / 2, layout.width / 2]) {
    for (const y of [0, HEAD_ROOM_M]) {
      for (const z of [-layout.depth / 2, layout.depth / 2 + 0.9]) corners.push([x, y - LOOK_AT_Y, z]);
    }
  }
  const fits = (distance: number) => corners.every(([x, y, z]) => {
    // The corner in the camera's own axes: how far ahead it is, and how far up.
    const ahead = distance - (y * sin + z * cos);
    const up = y * cos - z * sin;
    return ahead > 0.1 && Math.abs(x) <= ahead * wide && Math.abs(up) <= ahead * half;
  });
  let near = 2;
  let far = 400;
  for (let step = 0; step < 40; step += 1) {
    const middle = (near + far) / 2;
    if (fits(middle)) far = middle;
    else near = middle;
  }
  return far;
}
