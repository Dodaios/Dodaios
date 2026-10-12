/**
 * Team meetings in the team room: which chair each member takes, and how far
 * the meeting has got (who already sits at the table, who is still on the way,
 * who keeps working at their desk). Pure, so the panel and tests share it.
 */
import type { SocietyAgent } from "../data";
import type { OfficeLayout, Point, Studio } from "./officeLayout";
import { buildNavGrid, type NavGrid } from "./officeNav";
import { huddlePlaces, leadPlace } from "./officeTeams";
import type { Summon, TeamMeeting } from "./officeStore";

/** A meeting holds its members at the table this long unless it is ended earlier. */
export const MEETING_MS = 10 * 60_000;

/** How close to its chair a member must be to count as seated, in metres. */
const SEATED_WITHIN_M = 0.35;
/** The same for a member without a chair, who stops about a step (1.2 m) from its point. */
const STANDING_WITHIN_M = 1.6;

export interface MeetingSeat { target: Point; spotId?: string }

/**
 * A chair for every member, middle chairs first and facing pairs together, so
 * a small team sits across from each other. Members beyond the chairs stand at
 * the table's short ends.
 */
export function meetingSeats(layout: OfficeLayout, members: readonly string[]): Record<string, MeetingSeat> {
  const table = layout.furniture.find((f) => f.kind === "meetingTable");
  const centre = table ? { x: table.x, z: table.z } : layout.spawn;
  const chairs = layout.spots.filter((s) => s.kind === "meeting")
    .sort((a, b) => Math.abs(a.x - centre.x) - Math.abs(b.x - centre.x) || a.x - b.x || a.z - b.z);
  const seats: Record<string, MeetingSeat> = {};
  members.forEach((id, i) => {
    const chair = chairs[i];
    if (chair) { seats[id] = { target: { x: chair.x, z: chair.z }, spotId: chair.id }; return; }
    const extra = i - chairs.length;
    const side = extra % 2 === 0 ? 1 : -1;
    seats[id] = { target: { x: centre.x + side * (2.4 + 0.5 * Math.floor(extra / 2)), z: centre.z } };
  });
  return seats;
}

const gridCache = new WeakMap<OfficeLayout, NavGrid>();

/**
 * A place at a studio's own board for every member, the arc nearest the board
 * first: what "Meet" started from that studio's board hands to
 * `startMeeting` instead of the team room's chairs. Members beyond the places
 * of the arcs get none and stay where they are. The team's lead, when it is
 * among them, gets the centre of the front arc. Like every meeting, it never
 * moves a working member. `grid` is the floor's navigation grid when the
 * caller has it; without one it is built from the layout (once per layout).
 */
export function boardSeats(layout: OfficeLayout, studio: Studio, members: readonly string[], grid?: NavGrid | null): Record<string, MeetingSeat>;
/** The same, with the grid named before the studio; both orders are kept so no caller breaks. */
export function boardSeats(layout: OfficeLayout, grid: NavGrid | null | undefined, studio: Studio, members: readonly string[]): Record<string, MeetingSeat>;
export function boardSeats(
  layout: OfficeLayout, second: Studio | NavGrid | null | undefined, third: Studio | readonly string[], fourth?: NavGrid | null | readonly string[],
): Record<string, MeetingSeat> {
  // (layout, studio, members, grid?) has the member list third; (layout, grid, studio, members) has it last.
  const membersThird = Array.isArray(third);
  const studio = (membersThird ? second : third) as Studio;
  const members = (membersThird ? third : fourth) as readonly string[];
  const grid = (membersThird ? fourth : second) as NavGrid | null | undefined;
  const board = studio.board;
  if (!board) return {};
  let floor = grid ?? gridCache.get(layout);
  if (!floor) { floor = buildNavGrid(layout); gridCache.set(layout, floor); }
  const all = huddlePlaces(layout, floor, studio);
  // A team's lead, when it is among those called, stands at the centre of the front arc.
  const centre = studio.leadId && members.includes(studio.leadId) ? leadPlace(all, studio) : null;
  const places = all.filter((p) => p.id !== centre?.id)
    .map((p, i) => ({ p, i, from: Math.hypot(p.x - board.x, p.z - board.z) }))
    .sort((a, b) => Math.round((a.from - b.from) * 10) || a.i - b.i);
  const seats: Record<string, MeetingSeat> = {};
  let next = 0;
  for (const id of members) {
    const place = centre && id === studio.leadId ? centre : places[next++]?.p;
    if (place) seats[id] = { target: { x: place.x, z: place.z }, spotId: place.id };
  }
  return seats;
}

export interface MeetingProgress {
  /** Members sitting (or standing) at their place at the table. */
  seated: string[];
  /** Members on their way to the table. */
  arriving: string[];
  /** Members that keep working at their desk: a meeting never interrupts real work. */
  busy: string[];
  /** Members no longer in the office (removed or retired agents). */
  missing: string[];
}

export function meetingProgress(
  meeting: TeamMeeting, agents: readonly SocietyAgent[], summons: Record<string, Summon>, positions: ReadonlyMap<string, Point>,
): MeetingProgress {
  const progress: MeetingProgress = { seated: [], arriving: [], busy: [], missing: [] };
  for (const id of meeting.members) {
    const agent = agents.find((a) => a.agentId === id);
    if (!agent) { progress.missing.push(id); continue; }
    if (agent.state === "working") { progress.busy.push(id); continue; }
    const where = positions.get(id);
    const summon = summons[id];
    // A chair is exact; a member standing at the table's end stops a step short of its point.
    const within = summon?.spotId ? SEATED_WITHIN_M : STANDING_WITHIN_M;
    if (where && summon && Math.hypot(where.x - summon.target.x, where.z - summon.target.z) <= within) progress.seated.push(id);
    else progress.arriving.push(id);
  }
  return progress;
}

/** Minutes left in a meeting, rounded up; 0 once it is over. */
export function minutesLeft(meeting: TeamMeeting, nowMs: number): number {
  return Math.max(0, Math.ceil((meeting.untilMs - nowMs) / 60_000));
}
