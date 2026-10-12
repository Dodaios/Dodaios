/**
 * What each figure on the office map does, decided client-side and
 * deterministically from a seeded random stream.
 *
 * The map is a projection of the roster: it never starts work, and idle life
 * (coffee, couch, wandering) costs zero model calls. Working, waiting and
 * paused agents mirror their real run state; only idle agents pick hobbies.
 *
 * On a floor with team studios an agent belongs somewhere: its idle life
 * happens mostly in and around its own studio (its desk, the studio board, a
 * teammate's desk, a stroll between the benches), and only sometimes at the
 * shared places. Two things outrank idle life because they are real: a round
 * of its team (it stands at the studio board) and a message it sent a
 * colleague (it walks over). A floor without studios keeps the plain idle
 * day.
 */
import type { AgentRunState } from "../data";
import { seatOf, standOf, type DeskSlot, type OfficeLayout, type Point, type Rect, type Spot, type SpotKind, type Studio } from "./officeLayout";
import { BODY_SPACING, clearOfBodies, WALK_SPEED } from "./officeMotion";
import { isWalkable, nearestWalkable, randomWalkablePoint, type NavGrid } from "./officeNav";
import { homeStudio, huddlePlaces, leadPlace, studioOfTeam, studioRect, visitSlots, type Place } from "./officeTeams";

export type Pose = "sit" | "stand" | "sleep" | "wave" | "talk" | "work";

export type ActivityKind =
  | "work" | "wait" | "desk" | "coffee" | "couch" | "nap" | "window" | "shelf" | "arcade"
  | "cooler" | "beanbag" | "meeting" | "board" | "wander" | "visit" | "called"
  // Team life: at the own studio board, at a teammate's desk, strolling in the own studio, walking a message over.
  | "huddle" | "mate" | "studio" | "handoff";

export interface Plan {
  kind: ActivityKind;
  target: Point;
  /** Heading to settle into on arrival; null = keep the walking heading. */
  facing: number | null;
  pose: Pose;
  dwellMs: number;
  spotId: string | null;
  /** Agent id being visited. */
  with: string | null;
}

/** Deterministic PRNG (mulberry32) seeded from a string hash. */
export function createRng(seed: string): () => number {
  // FNV-1a over the UTF-16 code units, then one avalanche round.
  let h = 0x811c9dc5;
  for (let i = 0; i < seed.length; i += 1) {
    h ^= seed.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  h ^= h >>> 16; h = Math.imul(h, 0x85ebca6b); h ^= h >>> 13;
  let state = h >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Ids of standing places the floor plan does not list: beside a desk (`visit:`) and at a studio board (`fan:`). */
export function isOwnPlace(spotId: string): boolean {
  return spotId.startsWith("visit:") || spotId.startsWith("fan:");
}

/** Exclusive claims on hangout spots: one agent per spot, one spot per agent. */
export class SpotBook {
  private bySpot = new Map<string, string>();
  private byAgent = new Map<string, string>();

  /** Claim a spot for an agent; releases the agent's previous spot. False if another agent holds it. */
  claim(spotId: string, agentId: string): boolean {
    const holder = this.bySpot.get(spotId);
    if (holder !== undefined && holder !== agentId) return false;
    this.release(agentId);
    this.bySpot.set(spotId, agentId);
    this.byAgent.set(agentId, spotId);
    return true;
  }

  release(agentId: string): void {
    const spotId = this.byAgent.get(agentId);
    if (spotId === undefined) return;
    this.byAgent.delete(agentId);
    if (this.bySpot.get(spotId) === agentId) this.bySpot.delete(spotId);
  }

  /**
   * Keep only claims on spots that still exist (after the floor plan was
   * rebuilt). Claims on places the plan does not list (beside a desk, at a
   * studio board) are kept: each belongs to a walker that checks its own
   * plan against the new floor (`planStillValid`) and lets go when the place
   * is gone. Dropping them here would hand an occupied place to the next
   * agent that plans.
   */
  retain(spotIds: ReadonlySet<string>): void {
    for (const [spotId, agentId] of [...this.bySpot]) {
      if (!spotIds.has(spotId) && !isOwnPlace(spotId)) { this.bySpot.delete(spotId); this.byAgent.delete(agentId); }
    }
  }

  holder(spotId: string): string | null {
    return this.bySpot.get(spotId) ?? null;
  }

  /** The spot an agent holds right now, or null. */
  spotOf(agentId: string): string | null {
    return this.byAgent.get(agentId) ?? null;
  }

  isFree(spotId: string): boolean {
    return !this.bySpot.has(spotId);
  }
}

export interface PlanInput {
  agentId: string;
  state: AgentRunState;
  desk: DeskSlot | null;
  layout: OfficeLayout;
  grid: NavGrid;
  rng: () => number;
  book: SpotBook;
  previous: ActivityKind | null;
  workingColleagues: { agentId: string; desk: DeskSlot }[];
  calledTo: Point | null;
  /** Where the agent currently is; lets a called agent stop on its own side of the caller. */
  position?: Point | null;
  /** A team meeting's chair for this agent (a `meeting-*` spot id); it sits there instead of standing by `calledTo`. */
  calledSeat?: string | null;
  /**
   * The agent's team runs a round right now and this agent takes part in it:
   * it stands at the studio board. `speaker` = it is the one contributing at
   * the moment (the only working member a round ever moves). `teamId` names
   * the team when it is not the agent's home studio (an agent in several teams).
   */
  round?: { speaker: boolean; teamId?: string | null } | null;
  /** A real message this agent sent a colleague and has not walked over yet: the receiver, its desk, and whether it sits there. */
  handoff?: { to: string; desk: DeskSlot | null; seated: boolean; at: Point | null } | null;
  /** Studio mates sitting at their own desk right now: worth walking over to. */
  matesAtDesk?: { agentId: string; desk: DeskSlot }[];
  /** The round this agent stood in has just ended: it goes back to its desk before anything else. */
  backToDesk?: boolean;
  /** Where everybody else stands right now; a place beside a desk that somebody already stands at is not offered. */
  bodies?: readonly Point[];
  /** Where the person's character stands: agents at a board leave it room. */
  person?: Point | null;
}

/** Idle activities and their relative weights on a floor without studios. */
const IDLE_WEIGHTS: readonly [ActivityKind, number][] = [
  ["couch", 22], ["coffee", 18], ["window", 12], ["cooler", 8], ["arcade", 8], ["shelf", 7], ["beanbag", 8],
  ["meeting", 5], ["board", 4], ["wander", 10], ["visit", 6], ["desk", 10],
];

/**
 * What an idle agent with a home does next. `desk`, `mate`, `huddle`, `studio`
 * and `near` keep it in and around its studio; `commons` is a trip to a shared
 * place anywhere on the floor; `wander` a stroll in the neighbourhood;
 * `visit` a look at a busy colleague's desk.
 */
export type IdleChoice = "desk" | "mate" | "huddle" | "studio" | "near" | "commons" | "wander" | "visit";

/**
 * A team member: four in five of its idle choices keep it at home, one in seven is a trip to a shared place.
 * A trip earns a long stay (`dwellAfter`), so by the clock it weighs more than by the count; these numbers are
 * tuned for the clock, where a member still spends about two thirds of its idle time in and around its studio.
 */
export const TEAM_IDLE_WEIGHTS: readonly [IdleChoice, number][] = [
  ["desk", 30], ["mate", 14], ["huddle", 12], ["studio", 12], ["near", 12], ["commons", 14], ["wander", 6],
];

/** An agent without a team (the pool studio): its desk is home, but it uses the shared places far more. */
export const POOL_IDLE_WEIGHTS: readonly [IdleChoice, number][] = [
  ["desk", 20], ["studio", 10], ["near", 10], ["visit", 8], ["commons", 40], ["wander", 12],
];

/** Which shared place a trip goes to. */
export const COMMONS_WEIGHTS: readonly [SpotKind, number][] = [
  ["couch", 22], ["coffee", 18], ["window", 12], ["cooler", 8], ["arcade", 8], ["shelf", 7], ["beanbag", 8], ["meeting", 4], ["board", 3],
];

const SPOT_KIND: Partial<Record<ActivityKind, SpotKind>> = {
  couch: "couch", coffee: "coffee", window: "window", cooler: "cooler", arcade: "arcade",
  shelf: "shelf", beanbag: "beanbag", meeting: "meeting", board: "board",
};

const HANGOUT_KINDS: ReadonlySet<SpotKind> = new Set(Object.values(SPOT_KIND));

const CALLED_DISTANCE = 1.2;
const CALLED_DWELL_MS = 15000;
/** How long the sender of a message stays with its receiver. */
export const HANDOFF_DWELL_MS = 8000;
/** Places at the board within this much of the nearest free one count as the same row. */
const HUDDLE_ROW_M = 0.45;
/** An agent at a board keeps this far from the person's character, and makes room when the person comes closer than PERSON_CROWD_M. */
export const PERSON_SPACE_M = 1.25;
export const PERSON_CROWD_M = 0.95;
/** A spot this far beyond the studio's own floor still counts as "round the corner". */
const NEAR_MARGIN_M = 3.5;
/** A stroll in the neighbourhood stays within this distance of the studio's centre. */
const STROLL_RADIUS_M = 12;
/**
 * How far a trip to a shared place reaches: at this distance from the studio a place is half as likely as one
 * next door, at twice the distance a fifth. A handful of agents on a large campus keep to their neighbourhood
 * and the commons at its centre; a full floor ranges further.
 */
export const TRIP_REACH = { fewM: 10, manyM: 20, few: 6, many: 30 } as const;

/** The reach of a trip on a floor with `population` seated agents. */
export function tripReach(population: number): number {
  const t = Math.min(1, Math.max(0, (population - TRIP_REACH.few) / (TRIP_REACH.many - TRIP_REACH.few)));
  return TRIP_REACH.fewM + (TRIP_REACH.manyM - TRIP_REACH.fewM) * t;
}

const populationCache = new WeakMap<OfficeLayout, number>();
/** How many agents have a desk on this floor. */
function populationOf(layout: OfficeLayout): number {
  let count = populationCache.get(layout);
  if (count === undefined) {
    count = layout.lead.desks.filter((d) => d.agentId).length + layout.departments.reduce((n, dept) => n + dept.desks.filter((d) => d.agentId).length, 0);
    populationCache.set(layout, count);
  }
  return count;
}

function between(rng: () => number, minMs: number, maxMs: number): number {
  return Math.round(minMs + rng() * (maxMs - minMs));
}

function pick<T>(rng: () => number, items: readonly T[]): T {
  return items[Math.min(items.length - 1, Math.floor(rng() * items.length))];
}

function weighted<T>(rng: () => number, options: readonly (readonly [T, number])[]): T {
  const total = options.reduce((sum, [, w]) => sum + w, 0);
  let roll = rng() * total;
  for (const [value, w] of options) {
    if (roll < w) return value;
    roll -= w;
  }
  return options[options.length - 1][0];
}

function poseOfSpot(spot: Spot): Pose {
  return spot.pose;
}

/** Claim a random free spot matching `filter`; null when all are taken. */
function claimSpot(input: PlanInput, filter: (s: Spot) => boolean): Spot | null {
  const free = input.layout.spots.filter((s) => filter(s) && input.book.isFree(s.id));
  if (free.length === 0) return null;
  const spot = pick(input.rng, free);
  input.book.claim(spot.id, input.agentId);
  return spot;
}

/** The open office between the north and south strips: the departments' bounding box. */
function openOffice(layout: OfficeLayout): Rect {
  if (layout.departments.length === 0) return layout.floor;
  return {
    minX: Math.min(...layout.departments.map((d) => d.minX)),
    maxX: Math.max(...layout.departments.map((d) => d.maxX)),
    minZ: Math.min(...layout.departments.map((d) => d.minZ)),
    maxZ: Math.max(...layout.departments.map((d) => d.maxZ)),
  };
}

/** How often a stroll draws again when its place turns out to be somebody's, or a bottleneck. */
const STROLL_DRAWS = 6;
/** The ring of points round a place that must be floor for it to count as open ground. */
const STANDING_ROOM: readonly [number, number][] = [0, 1, 2, 3, 4, 5, 6, 7].map((i) => [Math.sin((i * Math.PI) / 4) * 0.7, Math.cos((i * Math.PI) / 4) * 0.7]);

/**
 * A free patch of floor inside `within` to stroll to: open ground, and not where somebody already stands or
 * sits. After a few draws it takes what it has (the walk stops beside whoever is there).
 */
function strollPoint(input: PlanInput, within?: Rect): Point | null {
  let point = randomWalkablePoint(input.grid, input.rng, within);
  const bodies = input.bodies ?? [];
  // Open ground: floor a body's width to every side, so nobody stops for a rest in a doorway or a gap between planters.
  const roomy = (p: Point) => STANDING_ROOM.every(([dx, dz]) => isWalkable(input.grid, { x: p.x + dx, z: p.z + dz }));
  for (let i = 1; i < STROLL_DRAWS && point && !(roomy(point) && clearOfBodies(point, bodies, BODY_SPACING * 1.3)); i += 1) {
    point = randomWalkablePoint(input.grid, input.rng, within);
  }
  return point;
}

function wanderPlan(input: PlanInput, pose: Pose, dwellMs: number): Plan {
  const target = strollPoint(input, openOffice(input.layout))
    ?? randomWalkablePoint(input.grid, input.rng)
    ?? input.layout.spawn;
  return { kind: "wander", target, facing: null, pose, dwellMs, spotId: null, with: null };
}

function spotPlan(kind: ActivityKind, spot: Spot, pose: Pose, dwellMs: number): Plan {
  return { kind, target: { x: spot.x, z: spot.z }, facing: spot.facing, pose, dwellMs, spotId: spot.id, with: null };
}

function placePlan(kind: ActivityKind, place: Place, pose: Pose, dwellMs: number, withId: string | null = null): Plan {
  return { kind, target: { x: place.x, z: place.z }, facing: place.facing, pose, dwellMs, spotId: place.id, with: withId };
}

function deskPlan(desk: DeskSlot, dwellMs: number): Plan {
  const seat = seatOf(desk);
  return { kind: "desk", target: { x: seat.x, z: seat.z }, facing: seat.facing, pose: "sit", dwellMs, spotId: null, with: null };
}

function calledPlan(input: PlanInput, caller: Point): Plan {
  const from = input.position;
  let angle: number;
  if (from && Math.hypot(from.x - caller.x, from.z - caller.z) > 1e-3) angle = Math.atan2(from.x - caller.x, from.z - caller.z);
  else angle = input.rng() * Math.PI * 2;
  const wanted = { x: caller.x + Math.sin(angle) * CALLED_DISTANCE, z: caller.z + Math.cos(angle) * CALLED_DISTANCE };
  const target = nearestWalkable(input.grid, wanted) ?? nearestWalkable(input.grid, caller) ?? wanted;
  const facing = Math.atan2(caller.x - target.x, caller.z - target.z);
  return { kind: "called", target, facing, pose: "talk", dwellMs: CALLED_DWELL_MS, spotId: null, with: null };
}

/** A free place for a visitor at `desk`, claimed; null when the desk has none left. */
function claimVisitSlot(input: PlanInput, desk: DeskSlot): Place | null {
  const free = visitSlots(desk, input.grid).filter((p) => input.book.isFree(p.id) && clearOfBodies(p, input.bodies ?? []));
  if (free.length === 0) return null;
  const place = pick(input.rng, free);
  input.book.claim(place.id, input.agentId);
  return place;
}

/**
 * Looking in on a colleague at their desk. The visitor stands and watches: no
 * talking pose and no bubble, because nothing was said. Talking is kept for
 * exchanges that really happened. Null when both places beside the chair are
 * taken: nobody queues up behind a visitor.
 */
function visitPlan(input: PlanInput, kind: "visit" | "mate", colleague: { agentId: string; desk: DeskSlot }, dwellMs: number): Plan | null {
  const place = claimVisitSlot(input, colleague.desk);
  return place ? placePlan(kind, place, "stand", dwellMs, colleague.agentId) : null;
}

/**
 * A place at the agent's own studio board, the one it already holds first;
 * null when the studio has none left. In a gathering (`gathered`: a round of
 * the team, not an idle look at the board) a team with a lead keeps the
 * centre of the front arc for it: the lead takes that place when it comes,
 * and the others leave it free while any other place is.
 */
function huddlePlan(input: PlanInput, studio: Studio, held: string | null, pose: Pose, dwellMs: number, gathered = false): Plan | null {
  const places = huddlePlaces(input.layout, input.grid, studio);
  const centre = gathered ? leadPlace(places, studio) : null;
  // The lead takes its place, unless the person is standing on it.
  const personThere = !!centre && !!input.person && Math.hypot(centre.x - input.person.x, centre.z - input.person.z) < PERSON_SPACE_M;
  if (centre && !personThere && studio.leadId === input.agentId && input.book.claim(centre.id, input.agentId)) return placePlan("huddle", centre, pose, dwellMs);
  const unclaimed = places.filter((p) => input.book.isFree(p.id));
  const others = centre && studio.leadId !== input.agentId ? unclaimed.filter((p) => p.id !== centre.id) : unclaimed;
  const open = others.length > 0 ? others : unclaimed;
  // Not on the person's toes: the places round where the person stands are left empty while there are others.
  const person = input.person;
  const roomy = person ? open.filter((p) => Math.hypot(p.x - person.x, p.z - person.z) >= PERSON_SPACE_M) : open;
  const free = roomy.length > 0 ? roomy : open;
  if (free.length === 0) return null;
  const kept = held ? free.find((p) => p.id === held) : undefined;
  // The row nearest the board fills up first, then the ones behind it: whoever comes later never has to squeeze
  // through the people already standing there. Within a row the place is the agent's own draw.
  const board = studio.board!;
  const fromBoard = (p: Place) => Math.hypot(p.x - board.x, p.z - board.z);
  const nearest = Math.min(...free.map(fromBoard));
  const row = free.filter((p) => fromBoard(p) <= nearest + HUDDLE_ROW_M);
  const place = kept ?? pick(input.rng, row);
  input.book.claim(place.id, input.agentId);
  return placePlan("huddle", place, pose, dwellMs);
}

/** Walking a real message over: beside the receiver's chair when it sits there, else a step from where it stands. */
function handoffPlan(input: PlanInput): Plan | null {
  const handoff = input.handoff;
  if (!handoff) return null;
  if (handoff.desk && handoff.seated) {
    const place = claimVisitSlot(input, handoff.desk);
    if (place) return placePlan("handoff", place, "talk", HANDOFF_DWELL_MS, handoff.to);
  }
  const at = handoff.at ?? (handoff.desk ? standOf(handoff.desk) : null);
  if (!at) return null;
  const from = input.position;
  const angle = from && Math.hypot(from.x - at.x, from.z - at.z) > 1e-3 ? Math.atan2(from.x - at.x, from.z - at.z) : input.rng() * Math.PI * 2;
  const wanted = { x: at.x + Math.sin(angle) * 0.95, z: at.z + Math.cos(angle) * 0.95 };
  const target = nearestWalkable(input.grid, wanted, 1.5) ?? nearestWalkable(input.grid, at);
  if (!target) return null;
  return { kind: "handoff", target, facing: Math.atan2(at.x - target.x, at.z - target.z), pose: "talk", dwellMs: HANDOFF_DWELL_MS, spotId: null, with: handoff.to };
}

function spotVisit(kind: ActivityKind, spot: Spot, rng: () => number, away: boolean): Plan {
  if (kind === "couch") return spotPlan(kind, spot, "sit", away ? between(rng, 30000, 60000) : between(rng, 20000, 45000));
  return spotPlan(kind, spot, poseOfSpot(spot) === "sleep" ? "sit" : poseOfSpot(spot), away ? between(rng, 15000, 35000) : between(rng, 8000, 25000));
}

/** The plain idle day of a floor without studios. */
function idlePlan(input: PlanInput): Plan {
  const { rng, desk, previous } = input;
  const colleagues = input.workingColleagues.filter((c) => c.agentId !== input.agentId);
  const available = IDLE_WEIGHTS.filter(([kind]) => {
    if (kind === "visit") return colleagues.length > 0;
    if (kind === "desk") return desk !== null;
    return true;
  });
  const options = available.length > 1 ? available.filter(([kind]) => kind !== previous) : available;
  const kind = weighted(rng, options);

  if (kind === "wander") return wanderPlan(input, "stand", between(rng, 6000, 12000));
  if (kind === "desk" && desk) return deskPlan(desk, between(rng, 15000, 30000));
  if (kind === "visit") {
    return visitPlan(input, "visit", pick(rng, colleagues), between(rng, 8000, 15000)) ?? wanderPlan(input, "stand", between(rng, 6000, 12000));
  }
  const spotKind = SPOT_KIND[kind];
  const spot = spotKind ? claimSpot(input, (s) => s.kind === spotKind) : null;
  if (!spot) return wanderPlan(input, "stand", between(rng, 6000, 12000));
  return spotVisit(kind, spot, rng, false);
}

/** Which idle choice an activity came from, so the same one is not taken twice in a row. */
function choiceOf(kind: ActivityKind | null): IdleChoice | null {
  if (kind === null) return null;
  if (kind === "desk" || kind === "mate" || kind === "huddle" || kind === "studio" || kind === "wander" || kind === "visit") return kind;
  return SPOT_KIND[kind] ? "commons" : null;
}

function strollPlan(input: PlanInput, kind: "studio" | "wander", within: Rect): Plan {
  const target = strollPoint(input, within)
    ?? nearestWalkable(input.grid, { x: (within.minX + within.maxX) / 2, z: (within.minZ + within.maxZ) / 2 })
    ?? input.layout.spawn;
  return { kind, target, facing: null, pose: "stand", dwellMs: between(input.rng, 6000, 12000), spotId: null, with: null };
}

/** Idle life with a home: mostly in and around the studio, sometimes at the shared places. */
function homeIdlePlan(input: PlanInput, studio: Studio): Plan {
  const { rng, desk, previous, layout, book } = input;
  const rect = studioRect(layout, studio);
  const mates = (input.matesAtDesk ?? []).filter((m) => m.agentId !== input.agentId);
  const colleagues = input.workingColleagues.filter((c) => c.agentId !== input.agentId);
  const reach = Math.hypot(rect.maxX - rect.minX, rect.maxZ - rect.minZ) / 2 + NEAR_MARGIN_M;
  const fromHome = (s: Point) => Math.hypot(s.x - studio.centre.x, s.z - studio.centre.z);
  // Only kinds an activity exists for; a team room chair is a trip, not a place round the corner.
  const hangout = (s: Spot) => HANGOUT_KINDS.has(s.kind) && s.kind !== "meeting" && book.isFree(s.id);
  const nearby = layout.spots.filter((s) => hangout(s) && fromHome(s) <= reach);

  const table = studio.teamId === null ? POOL_IDLE_WEIGHTS : TEAM_IDLE_WEIGHTS;
  const available = table.filter(([choice]) => {
    if (choice === "desk") return desk !== null;
    if (choice === "mate") return mates.length > 0;
    if (choice === "huddle") return studio.board !== null;
    if (choice === "near") return nearby.length > 0;
    if (choice === "visit") return colleagues.length > 0;
    return true;
  });
  const last = choiceOf(previous);
  const options = available.length > 1 ? available.filter(([choice]) => choice !== last) : available;
  const choice = weighted(rng, options);
  const stroll = () => strollPlan(input, "studio", rect);

  // Its own desk is where an agent with a home spends its longest stretches.
  if (choice === "desk" && desk) return deskPlan(desk, between(rng, 40000, 90000));
  if (choice === "mate") return visitPlan(input, "mate", pick(rng, mates), between(rng, 12000, 24000)) ?? stroll();
  if (choice === "visit") return visitPlan(input, "visit", pick(rng, colleagues), between(rng, 8000, 15000)) ?? stroll();
  if (choice === "huddle") return huddlePlan(input, studio, null, "stand", between(rng, 12000, 25000)) ?? stroll();
  if (choice === "studio") return stroll();
  if (choice === "near") {
    const spot = pick(rng, nearby);
    book.claim(spot.id, input.agentId);
    return spotVisit(spot.kind as ActivityKind, spot, rng, false);
  }
  if (choice === "commons") {
    // Every free shared place is a candidate, weighted by what it is and by how far from home it lies: nobody
    // crosses the campus for a window when there is a coffee round the corner, and a small roster stays near.
    const reachM = tripReach(populationOf(layout));
    const kindWeight = new Map(COMMONS_WEIGHTS);
    const open = layout.spots.filter((s) => kindWeight.has(s.kind) && book.isFree(s.id));
    if (open.length === 0) return stroll();
    const perKind = new Map<SpotKind, number>();
    for (const s of open) perKind.set(s.kind, (perKind.get(s.kind) ?? 0) + 1);
    const spot = weighted(rng, open.map((s) => [s, ((kindWeight.get(s.kind) ?? 0) / (perKind.get(s.kind) ?? 1)) / (1 + (fromHome(s) / reachM) ** 2)] as const));
    book.claim(spot.id, input.agentId);
    return spotVisit(spot.kind as ActivityKind, spot, rng, true);
  }
  const c = studio.centre;
  return strollPlan(input, "wander", { minX: c.x - STROLL_RADIUS_M, maxX: c.x + STROLL_RADIUS_M, minZ: c.z - STROLL_RADIUS_M, maxZ: c.z + STROLL_RADIUS_M });
}

/** Decide the next activity for one agent. Releases its previous spot claim first. */
export function planFor(input: PlanInput): Plan {
  const { agentId, state, desk, book } = input;
  const held = book.spotOf(agentId);
  book.release(agentId);

  // A working agent stays at its screen: the map mirrors real work and never interrupts it, not even visually.
  if (input.calledTo && input.state !== "working") {
    // A meeting seats its members: the assigned chair, else any free chair at the table, else standing by it.
    // A meeting at a studio's own board: the member stands on its place in the arcs.
    if (input.calledSeat?.startsWith("fan:")) {
      const seat = input.calledSeat;
      const at = (input.layout.studios ?? []).filter((s) => seat.startsWith(`fan:${s.deptId}:`))
        .flatMap((s) => huddlePlaces(input.layout, input.grid, s)).find((p) => p.id === seat);
      if (at && book.claim(at.id, agentId)) return placePlan("huddle", at, "stand", Infinity);
    } else if (input.calledSeat) {
      const assigned = input.layout.spots.find((s) => s.id === input.calledSeat);
      if (assigned && book.claim(assigned.id, agentId)) return spotPlan("meeting", assigned, "sit", Infinity);
      const other = claimSpot(input, (s) => s.kind === "meeting");
      if (other) return spotPlan("meeting", other, "sit", Infinity);
    }
    return calledPlan(input, input.calledTo);
  }

  const studio = homeStudio(input.layout, agentId, desk);

  // A round of the agent's team: free members stand at the studio board until it ends. Working members stay at
  // their screen, with one exception that is the round itself: the member contributing right now.
  const roundStudio = (input.round?.teamId ? studioOfTeam(input.layout, input.round.teamId) : null) ?? studio;
  if (input.round && roundStudio && (state === "idle" || (state === "working" && input.round.speaker))) {
    const plan = huddlePlan(input, roundStudio, held, "stand", Infinity, true);
    if (plan) return plan;
  }

  if (state === "working") {
    if (desk) {
      const seat = seatOf(desk);
      return { kind: "work", target: { x: seat.x, z: seat.z }, facing: seat.facing, pose: "work", dwellMs: Infinity, spotId: null, with: null };
    }
    const spot = claimSpot(input, (s) => s.kind === "window");
    if (spot) return spotPlan("work", spot, "work", Infinity);
    return { ...wanderPlan(input, "work", Infinity), kind: "work" };
  }

  if (state === "waiting") {
    if (desk) {
      const stand = standOf(desk);
      // It stands where a visitor to its desk would: holding that place keeps anyone from being sent there meanwhile.
      const beside = visitSlots(desk, input.grid).find((p) => p.x > stand.x - 0.3 && Math.hypot(p.x - stand.x, p.z - stand.z) < BODY_SPACING);
      const held = beside && book.claim(beside.id, agentId) ? beside.id : null;
      return { kind: "wait", target: { x: stand.x, z: stand.z }, facing: stand.facing, pose: "wave", dwellMs: Infinity, spotId: held, with: null };
    }
    const spot = claimSpot(input, (s) => s.pose === "stand" && s.kind !== "huddle");
    if (spot) return spotPlan("wait", spot, "wave", Infinity);
    return { ...wanderPlan(input, "wave", Infinity), kind: "wait" };
  }

  if (state === "paused") {
    const bed = claimSpot(input, (s) => s.pose === "sleep");
    if (bed) return spotPlan("nap", bed, "sleep", Infinity);
    const couch = claimSpot(input, (s) => s.kind === "couch");
    if (couch) return spotPlan("nap", couch, "sit", Infinity);
    if (desk) {
      const seat = seatOf(desk);
      return { kind: "nap", target: { x: seat.x, z: seat.z }, facing: seat.facing, pose: "sit", dwellMs: Infinity, spotId: null, with: null };
    }
    return { ...wanderPlan(input, "sit", Infinity), kind: "nap" };
  }

  const handoff = handoffPlan(input);
  if (handoff) return handoff;
  if (input.backToDesk && desk) return deskPlan(desk, between(input.rng, 12000, 24000));
  return studio ? homeIdlePlan(input, studio) : idlePlan(input);
}

/**
 * Does a plan made on an earlier floor plan still hold on this one? A spot
 * must still exist where it was; a place to stand must still be floor. Plans
 * bound to the agent's own desk are checked by their desk, not here.
 */
export function planStillValid(plan: Plan, layout: OfficeLayout, grid: NavGrid): boolean {
  if (plan.kind === "work" || plan.kind === "wait" || plan.kind === "desk") return true;
  if (plan.spotId && !isOwnPlace(plan.spotId)) {
    const spot = layout.spots.find((s) => s.id === plan.spotId);
    return !!spot && Math.hypot(spot.x - plan.target.x, spot.z - plan.target.z) < 0.05;
  }
  if (plan.spotId) {
    // A place of our own must still be one on this floor: at a studio's board, or beside a desk that stands there.
    const id = plan.spotId;
    const places = id.startsWith("fan:")
      ? (layout.studios ?? []).filter((s) => id.startsWith(`fan:${s.deptId}:`)).flatMap((s) => huddlePlaces(layout, grid, s))
      : layout.departments.flatMap((d) => d.desks).flatMap((d) => visitSlots(d, grid));
    return places.some((p) => p.id === id && Math.hypot(p.x - plan.target.x, p.z - plan.target.z) < 0.05);
  }
  if (plan.kind === "nap") return true;
  return isWalkable(grid, plan.target);
}

/**
 * What a name plate may say an agent is doing. Standing at the studio board
 * and looking in on a studio mate are part of an idle agent's day, and say
 * nothing about teamwork: both read as being in the studio. "At the team
 * board" is kept for a gathering that is real (`gathered`: a running round of
 * the team, or a meeting the person called there).
 */
export function shownActivity(kind: ActivityKind, gathered: boolean): ActivityKind {
  if (kind === "mate") return "studio";
  if (kind === "huddle" && !gathered) return "studio";
  return kind;
}

/** The longest an idle activity is stretched to. */
const LONGEST_DWELL_MS = 150_000;
/** A stay lasts at least this many times as long as the walk to it would take at walking pace. */
const STAY_PER_WALK = 3.2;

/**
 * How long to stay after walking `walkedM` metres to get there. A long way
 * earns a long stay — at least about three times the time the walk would
 * take at walking pace — so a large floor shows people being somewhere, not a
 * crowd in transit. Calls, hand-offs and open-ended stays keep their own time.
 */
export function dwellAfter(plan: Plan, walkedM: number): number {
  if (!Number.isFinite(plan.dwellMs) || plan.kind === "called" || plan.kind === "handoff") return plan.dwellMs;
  return Math.min(LONGEST_DWELL_MS, Math.max(plan.dwellMs, (walkedM / WALK_SPEED) * 1000 * STAY_PER_WALK));
}
