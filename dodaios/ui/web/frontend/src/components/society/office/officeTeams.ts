/**
 * Where an agent belongs on the agents floor: its team's studio, the places
 * round the studio board, and where a visitor stands at a teammate's desk.
 *
 * Studios come from the floor plan (`layout.studios`); a floor without them
 * (the coding floor, the arcade) simply has no homes, and every caller keeps
 * its studio-less behaviour. Pure.
 */
import { chairRect, DESK_PITCH_X, deskRect, seatOf, type DeskSlot, type OfficeLayout, type Point, type Rect, type Studio } from "./officeLayout";
import { clearOfBodies } from "./officeMotion";
import { isWalkable, nearestWalkable, type NavGrid } from "./officeNav";

/** A place a figure can stand on that the floor plan does not list as a spot; reserved through the same book by its id. */
export interface Place extends Point { id: string; facing: number }

interface StudioIndex {
  studios: readonly Studio[];
  byAgent: Map<string, Studio>;
  byDept: Map<string, Studio>;
  byTeam: Map<string, Studio>;
  deptOfDesk: Map<string, string>;
}

const indexCache = new WeakMap<OfficeLayout, StudioIndex>();

function indexOf(layout: OfficeLayout): StudioIndex {
  let index = indexCache.get(layout);
  if (!index) {
    const studios = layout.studios ?? [];
    index = {
      studios,
      byAgent: new Map(studios.flatMap((s) => s.members.map((id) => [id, s] as const))),
      byDept: new Map(studios.map((s) => [s.deptId, s])),
      byTeam: new Map(studios.filter((s) => s.teamId !== null).map((s) => [s.teamId as string, s])),
      deptOfDesk: new Map(layout.departments.flatMap((d) => d.desks.map((desk) => [desk.id, d.id] as const))),
    };
    indexCache.set(layout, index);
  }
  return index;
}

/** The floor's studios; empty where the floor plan has none. */
export function studiosOf(layout: OfficeLayout): readonly Studio[] {
  return indexOf(layout).studios;
}

/** The studio an agent belongs to: the one that lists it, else the one its desk stands in. Null without studios. */
export function homeStudio(layout: OfficeLayout, agentId: string, desk: Pick<DeskSlot, "id"> | null): Studio | null {
  const index = indexOf(layout);
  if (index.studios.length === 0) return null;
  const listed = index.byAgent.get(agentId);
  if (listed) return listed;
  const dept = desk ? index.deptOfDesk.get(desk.id) : undefined;
  return dept ? index.byDept.get(dept) ?? null : null;
}

export function studioOfTeam(layout: OfficeLayout, teamId: string): Studio | null {
  return indexOf(layout).byTeam.get(teamId) ?? null;
}

/** The studio's floor: its department's rectangle, or a square round its centre when the department is gone. */
export function studioRect(layout: OfficeLayout, studio: Studio): Rect {
  const dept = layout.departments.find((d) => d.id === studio.deptId);
  if (dept) return { minX: dept.minX, maxX: dept.maxX, minZ: dept.minZ, maxZ: dept.maxZ };
  return { minX: studio.centre.x - 4, maxX: studio.centre.x + 4, minZ: studio.centre.z - 4, maxZ: studio.centre.z + 4 };
}

/** The desks of an agent's studio mates (everyone seated in the same studio, itself excluded). */
export function mateDesks(layout: OfficeLayout, studio: Studio, agentId: string): DeskSlot[] {
  const dept = layout.departments.find((d) => d.id === studio.deptId);
  if (!dept) return [];
  const members = new Set(studio.members);
  return dept.desks.filter((d) => d.agentId !== null && d.agentId !== agentId && members.has(d.agentId));
}

/**
 * Where a visitor stands relative to the chair: in the middle of the gap to the next chair, east or west, a
 * small step back from the chairs' line (the desk's clearance reaches just past that line). There it is out of
 * the aisle behind the chairs, which stays free for everyone walking to a seat, and out of the way the seated
 * colleague gets up (straight back), even with a visitor on either side.
 */
const VISIT_SIDE_M = DESK_PITCH_X / 2;
const VISIT_BACK_M = 0.3;

/**
 * Where visitors stand at a desk: between its chair and the next one, east
 * and west. Only places on walkable ground count. The gap between two chairs
 * belongs to both desks, so a place's id is its position (`visit:<x>,<z>`):
 * the visitors of two neighbouring desks can never be given the same patch of
 * floor. A place is a step from where the owner of the desk to its west stands
 * while it waits for the person; that owner holds the place meanwhile, and
 * callers skip one somebody already stands at.
 */
export function visitSlots(desk: DeskSlot, grid: NavGrid): Place[] {
  const seat = seatOf(desk);
  // Behind the chair is away from the desk.
  const back = desk.facing === "north" ? 1 : -1;
  const candidates: Point[] = [
    { x: seat.x + VISIT_SIDE_M, z: seat.z + back * VISIT_BACK_M },
    { x: seat.x - VISIT_SIDE_M, z: seat.z + back * VISIT_BACK_M },
  ];
  return candidates.flatMap((p) => (isWalkable(grid, p)
    ? [{ id: `visit:${p.x.toFixed(2)},${p.z.toFixed(2)}`, x: p.x, z: p.z, facing: Math.atan2(seat.x - p.x, seat.z - p.z) }]
    : []));
}

/** The person's character keeps this far from everybody when a click sends it somewhere: beside a figure, never in it. */
export const PERSON_CLEAR_M = 0.75;
/** A click this close to a bench desk's chair or top means that desk. */
const DESK_CLICK_MARGIN_M = 0.3;
/** How far behind a chair the person stands when both places beside it are taken. */
const BEHIND_CHAIR_M = 1.0;

function within(rect: Rect, p: Point, margin: number): boolean {
  return p.x >= rect.minX - margin && p.x <= rect.maxX + margin && p.z >= rect.minZ - margin && p.z <= rect.maxZ + margin;
}

/**
 * Where the person's character stands when a click (or "walk there") names
 * `goal`. Free floor is the goal itself. A click on a bench desk, on its
 * chair or on whoever sits there resolves to a standing place at that desk:
 * beside the chair where a visiting colleague would stand, else behind it.
 * Anything else solid or occupied (a couch, a counter, a standing agent)
 * resolves to the nearest free floor beside it. The person never ends up on a
 * chair, in a desk or inside a figure; taking a seat is its own action (the
 * executive chair and Mission Control's chair have one).
 *
 * `bodies` are everybody else's positions. Null only when there is no floor
 * within reach at all.
 */
export function standingPlaceFor(layout: OfficeLayout, grid: NavGrid, goal: Point, bodies: readonly Point[]): Point | null {
  const free = (p: Point) => isWalkable(grid, p) && clearOfBodies(p, bodies, PERSON_CLEAR_M);
  if (free(goal)) return { x: goal.x, z: goal.z };
  const nearest = (candidates: readonly Point[]): Point | null => candidates.filter(free)
    .reduce<Point | null>((best, p) => (!best || Math.hypot(p.x - goal.x, p.z - goal.z) < Math.hypot(best.x - goal.x, best.z - goal.z) ? p : best), null);

  // A bench desk (sittable desks carry a size and keep their own sit action).
  const desk = layout.departments.flatMap((d) => d.desks)
    .filter((d) => within(deskRect(d), goal, DESK_CLICK_MARGIN_M) || within(chairRect(seatOf(d)), goal, DESK_CLICK_MARGIN_M))
    .reduce<DeskSlot | null>((best, d) => {
      const seat = seatOf(d);
      return !best || Math.hypot(seat.x - goal.x, seat.z - goal.z) < Math.hypot(seatOf(best).x - goal.x, seatOf(best).z - goal.z) ? d : best;
    }, null);
  if (desk) {
    const seat = seatOf(desk);
    const back = desk.facing === "north" ? 1 : -1;
    const beside = nearest([...visitSlots(desk, grid), { x: seat.x, z: seat.z + back * BEHIND_CHAIR_M }]);
    if (beside) return { x: beside.x, z: beside.z };
  }
  // The nearest floor to the goal, when nobody is in the way there (the executive chair is sat on from it).
  const cell = nearestWalkable(grid, goal, 1.2);
  if (cell && free(cell)) return cell;
  // Else the nearest free floor round the goal, ring by ring.
  for (let radius = 0.2; radius <= 3.01; radius += 0.2) {
    const ring: Point[] = [];
    for (let i = 0; i < 16; i += 1) {
      const angle = (i / 16) * Math.PI * 2;
      ring.push({ x: goal.x + Math.sin(angle) * radius, z: goal.z + Math.cos(angle) * radius });
    }
    const found = nearest(ring);
    if (found) return found;
  }
  // Crowded all round: free ground at least; the walk stops beside whoever stands there.
  return nearestWalkable(grid, goal);
}

/**
 * The arcs a team stands in at its board: each row's distance from the board
 * and the angles (degrees off the board's centre line) of its places. Every
 * place is more than a metre from its neighbours in the row and from the rows
 * before and behind it, so name plates and bubbles stay apart and the person
 * can walk in between. The first row is a conversation's distance from the
 * board; the rows behind it look over its shoulders (the angles interleave).
 */
export const HUDDLE_ARCS: readonly { radius: number; angles: readonly number[] }[] = [
  { radius: 2.2, angles: [-14, 14, -42, 42] },
  { radius: 3.3, angles: [0, -20, 20, -40, 40, -60, 60] },
  { radius: 4.4, angles: [-7.5, 7.5, -22.5, 22.5, -37.5, 37.5] },
];
/**
 * The lead's place in a gathering at the board: the place of the front arc
 * nearest the board's centre line. Null for a studio without a lead (then the
 * arcs have no special place at all) or without a walkable front arc.
 */
export function leadPlace(places: readonly Place[], studio: Pick<Studio, "deptId" | "leadId" | "board">): Place | null {
  const board = studio.board;
  if (!studio.leadId || !board) return null;
  const front = places.filter((p) => p.id.startsWith(`fan:${studio.deptId}:0:`));
  // How far to the side of the board's centre line a place lies.
  const aside = (p: Place) => Math.abs((p.x - board.x) * Math.cos(board.facing) - (p.z - board.z) * Math.sin(board.facing));
  return front.reduce<Place | null>((best, p) => (!best || aside(p) < aside(best) - 1e-6 ? p : best), null);
}

/** The least two places of the arcs are apart; the tests hold the geometry to it. */
export const HUDDLE_SPACE_M = 1.05;

/**
 * Everywhere a team can stand at its board: loose arcs round it, each place
 * facing the board (ids `fan:<deptId>:<row>:<n>`), the row nearest the board
 * first. Only places on walkable ground count. Empty for a studio without a
 * board. The floor plan's own huddle spots mark where the huddle is; the arcs
 * are where people actually stand, with room between them.
 */
export function huddlePlaces(_layout: OfficeLayout, grid: NavGrid, studio: Studio): Place[] {
  if (!studio.board) return [];
  const { x: bx, z: bz, facing } = studio.board;
  const nx = Math.sin(facing), nz = Math.cos(facing);
  // The board's own right-hand direction on the floor.
  const tx = nz, tz = -nx;
  const places: Place[] = [];
  HUDDLE_ARCS.forEach((arc, row) => {
    arc.angles.forEach((degrees, n) => {
      const a = (degrees * Math.PI) / 180;
      const along = Math.cos(a) * arc.radius, across = Math.sin(a) * arc.radius;
      const p = { x: bx + nx * along + tx * across, z: bz + nz * along + tz * across };
      if (isWalkable(grid, p)) places.push({ id: `fan:${studio.deptId}:${row}:${n}`, x: p.x, z: p.z, facing: Math.atan2(bx - p.x, bz - p.z) });
    });
  });
  return places;
}
