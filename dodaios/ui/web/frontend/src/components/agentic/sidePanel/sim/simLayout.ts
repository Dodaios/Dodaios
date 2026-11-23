import { BOARD_COLUMNS, type BoardActivity, type BoardColumn, type BoardPlace } from "../agentBoard";

/**
 * The pure half of the simulation: which station an agent stands at, which
 * square of it is its own, and where the camera stands to see them all.
 *
 * The floor is one path of five stations in the order work travels:
 * Building, Checks, In review, Ready, Finished. An agent walks only when its
 * work moves to another station. Inside a station it keeps the square it
 * first took, whatever the others do, so the floor is still while nothing
 * happens.
 */

/** A station of the path: the board's four columns, then the work that is done. */
export type SimStation = BoardColumn | "finished";

export const SIM_STATIONS: readonly SimStation[] = [...BOARD_COLUMNS, "finished"];

/** One agent as the simulation needs it. */
export interface SimAgent {
  /** The board item's id. */
  id: string;
  /** The coding CLI's id ("" when unknown) and its name. */
  agent: string;
  agentLabel: string;
  title: string;
  place: SimStation;
  activity: BoardActivity;
  /** The words of the card's footer, already translated. */
  stateLabel: string;
}

/**
 * The station an agent stands at.
 *
 * The board's column follows the pull request alone, so an agent that is
 * still changing a mergeable pull request stands under "Ready" there. On the
 * floor that reads as "done" while the figure is visibly at work. So an agent
 * that works stands at Building, wherever its pull request is: the later
 * stations hold only work the agent has put down.
 */
export function stationOf(place: BoardPlace, activity: BoardActivity): SimStation {
  return activity === "working" ? "building" : place;
}

/** The side of the square one agent stands in, in metres. */
export const CELL_M = 1.85;
/** The free strip between two stations side by side: room for the arrow. */
export const GAP_M = 1;
/** The free strip between two stations one behind the other: room for a station's name. */
export const ROW_GAP_M = 1.4;
/** The margin between a station's edge and its first agent. */
export const PAD_M = 0.35;
/** How tall a figure stands, for framing. */
export const HEAD_ROOM_M = 1.6;
/** The camera's height above the floor, as an angle from the horizon. */
export const CAMERA_PITCH = 0.78;
/** What the camera looks at: a point a little above the floor's centre. */
export const LOOK_AT_Y = 0.35;
/** The share of the picture the floor may fill; the rest is margin for names and the key. */
const FILL = 0.9;
/** The most agents a station holds in one line, across or deep. */
const MAX_LINE = 8;
/** How much better another shape must fit before the floor is rearranged. */
const RESHAPE_GAIN = 0.35;

/** Which square of which station each agent holds. */
export type SimSlots = ReadonlyMap<string, { place: SimStation; slot: number }>;

/**
 * Give every agent a square.
 *
 * An agent that stays at its station keeps its square. One that arrives takes
 * the first free square, in the order the agents are listed. A square whose
 * agent left stays empty until someone arrives: nobody moves up.
 */
export function assignSlots(
  previous: SimSlots,
  agents: readonly Pick<SimAgent, "id" | "place">[],
): Map<string, { place: SimStation; slot: number }> {
  const next = new Map<string, { place: SimStation; slot: number }>();
  const taken = new Map<SimStation, Set<number>>(SIM_STATIONS.map((station) => [station, new Set<number>()]));
  const arriving: Pick<SimAgent, "id" | "place">[] = [];
  for (const agent of agents) {
    if (next.has(agent.id)) continue;
    const held = previous.get(agent.id);
    if (held && held.place === agent.place && !taken.get(agent.place)?.has(held.slot)) {
      next.set(agent.id, held);
      taken.get(agent.place)?.add(held.slot);
    } else {
      arriving.push(agent);
    }
  }
  for (const agent of arriving) {
    if (next.has(agent.id)) continue;
    const used = taken.get(agent.place);
    if (!used) continue;
    let slot = 0;
    while (used.has(slot)) slot += 1;
    used.add(slot);
    next.set(agent.id, { place: agent.place, slot });
  }
  return next;
}

/** How the path runs: left to right, or from the back to the front. */
export interface SimShape {
  flow: "across" | "down";
  /** Across: the rows of every station. Down: the columns of every station. */
  lines: number;
}

export interface SimField {
  column: SimStation;
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

/** The arrow from one station to the next. */
export interface SimLink {
  x: number;
  z: number;
  /** The way it points, as a turn about the vertical: 0 is to the right. */
  turn: number;
}

export interface SimLayout {
  shape: SimShape;
  fields: SimField[];
  spots: Map<string, SimSpot>;
  links: SimLink[];
  /** The whole floor, centred on the origin. */
  width: number;
  depth: number;
}

/** The side of a station that holds this many agents in a line. */
const span = (cells: number) => cells * CELL_M + 2 * PAD_M;

/** The squares each station needs: up to the last one that is held. */
function capacities(slots: SimSlots): number[] {
  const needed = SIM_STATIONS.map(() => 1);
  for (const { place, slot } of slots.values()) {
    const index = SIM_STATIONS.indexOf(place);
    if (index >= 0) needed[index] = Math.max(needed[index], slot + 1);
  }
  return needed;
}

function sizeOf(needed: readonly number[], shape: SimShape): { width: number; depth: number } {
  const other = needed.map((count) => Math.max(1, Math.ceil(count / shape.lines)));
  if (shape.flow === "across") {
    return {
      width: other.reduce((sum, cells) => sum + span(cells), 0) + (other.length - 1) * GAP_M,
      depth: span(shape.lines),
    };
  }
  return {
    width: span(shape.lines),
    depth: other.reduce((sum, cells) => sum + span(cells), 0) + (other.length - 1) * ROW_GAP_M,
  };
}

/** How far a shape's picture is from the panel's: 0 is a perfect fit. */
function miss(needed: readonly number[], shape: SimShape, aspect: number): number {
  const { width, depth } = sizeOf(needed, shape);
  const seen = width / (depth * Math.sin(CAMERA_PITCH) + HEAD_ROOM_M * Math.cos(CAMERA_PITCH));
  return Math.abs(Math.log(seen / Math.max(0.3, aspect)));
}

/**
 * Choose how the path runs for a panel of this shape (`aspect`, width over
 * height): across a wide panel, down a narrow side panel, with as many lines
 * as bring the floor's picture nearest the panel's. The shape in use stays
 * unless another fits clearly better, so one more agent does not rearrange
 * the floor.
 */
export function chooseShape(slots: SimSlots, aspect: number, current?: SimShape): SimShape {
  const needed = capacities(slots);
  const fullest = Math.max(...needed);
  let best: SimShape = { flow: "across", lines: 1 };
  let bestMiss = Infinity;
  for (const flow of ["across", "down"] as const) {
    for (let lines = 1; lines <= Math.min(MAX_LINE, Math.max(2, fullest)); lines += 1) {
      const candidate = miss(needed, { flow, lines }, aspect);
      if (candidate < bestMiss - 1e-9) {
        bestMiss = candidate;
        best = { flow, lines };
      }
    }
  }
  if (current && miss(needed, current, aspect) <= bestMiss + RESHAPE_GAIN) return current;
  return best;
}

/** Lay the stations and their agents out in this shape. */
export function layoutSimulation(slots: SimSlots, shape: SimShape): SimLayout {
  const needed = capacities(slots);
  const { width, depth } = sizeOf(needed, shape);
  const across = shape.flow === "across";
  const counts = SIM_STATIONS.map(() => 0);
  for (const { place } of slots.values()) counts[SIM_STATIONS.indexOf(place)] += 1;

  const fields: SimField[] = [];
  const links: SimLink[] = [];
  let along = 0;
  SIM_STATIONS.forEach((column, index) => {
    const cells = Math.max(1, Math.ceil(needed[index] / shape.lines));
    const length = span(cells);
    // Across, the path runs left to right. Down, it starts at the back, as a page starts at the top.
    fields.push(across
      ? { column, x: -width / 2 + along + length / 2, z: 0, width: length, depth, count: counts[index] }
      : { column, x: 0, z: -depth / 2 + along + length / 2, width, depth: length, count: counts[index] });
    along += length;
    if (index < SIM_STATIONS.length - 1) {
      links.push(across
        ? { x: -width / 2 + along + GAP_M / 2, z: 0, turn: 0 }
        // Beside the station's name, which stands in the middle of the strip.
        : { x: width / 2 - 0.6, z: -depth / 2 + along + ROW_GAP_M / 2, turn: -Math.PI / 2 });
      along += across ? GAP_M : ROW_GAP_M;
    }
  });

  const spots = new Map<string, SimSpot>();
  for (const [id, { place, slot }] of slots) {
    const field = fields[SIM_STATIONS.indexOf(place)];
    if (!field) continue;
    // A square's place depends on its number alone, so a station that grows
    // adds squares at its far end and moves none of the ones in use.
    const column = across ? Math.floor(slot / shape.lines) : slot % shape.lines;
    const row = across ? slot % shape.lines : Math.floor(slot / shape.lines);
    spots.set(id, {
      id,
      x: field.x - field.width / 2 + PAD_M + CELL_M / 2 + column * CELL_M,
      // Row 0 is the front row: the edge nearest the viewer.
      z: field.z + field.depth / 2 - PAD_M - CELL_M / 2 - row * CELL_M,
    });
  }
  return { shape, fields, spots, links, width, depth };
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
  // reaches a little further, for the stations' names.
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
