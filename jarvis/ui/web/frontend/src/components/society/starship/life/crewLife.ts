/**
 * What a crew member does next. Pure and deterministic per agent: the real
 * run state decides the place (working sits at its own console, waiting
 * stands at it and waves for the captain, paused rests in a pod), a running
 * round of its team gathers it at the division's holo-table, and an idle
 * agent lives a seeded day between its console, the mess, the lounge, the
 * windows and the gardens. Nothing here starts or stops work.
 */
import type { AgentRunState } from "../../data";
import type { Activity } from "../crew/rig";
import { hash } from "../plan/builder";
import type { DeckPlan, Place, PlaceKind, Vec2 } from "../plan/types";

export type Reason = "work" | "wait" | "rest" | "idle" | "round" | "called" | "arrive";

export interface Intent {
  placeId: string | null;
  target: Vec2;
  yaw: number;
  /** What the body does once there. */
  activity: Activity;
  seatY: number;
  /** When an idle stay ends (ms since epoch); Infinity for state-bound places. */
  untilMs: number;
  reason: Reason;
}

/** Who holds which free place, so nobody sits on anybody. */
export class PlaceBook {
  private readonly byPlace = new Map<string, string>();
  private readonly byAgent = new Map<string, string>();

  holder(placeId: string): string | undefined { return this.byPlace.get(placeId); }

  reserve(placeId: string, agentId: string): boolean {
    const held = this.byPlace.get(placeId);
    if (held && held !== agentId) return false;
    this.release(agentId);
    this.byPlace.set(placeId, agentId);
    this.byAgent.set(agentId, placeId);
    return true;
  }

  release(agentId: string): void {
    const place = this.byAgent.get(agentId);
    if (place) { this.byPlace.delete(place); this.byAgent.delete(agentId); }
  }

  /** Forget places a rebuilt plan no longer has. */
  retain(ids: ReadonlySet<string>): void {
    for (const [place, agent] of [...this.byPlace]) if (!ids.has(place)) { this.byPlace.delete(place); this.byAgent.delete(agent); }
  }
}

export interface CrewState {
  agentId: string;
  state: AgentRunState;
  /** The division (room id) the agent belongs to, if it is seated. */
  division: string | null;
}

export interface RoundView {
  running: boolean;
  speakerId: string | null;
}

export interface LifeContext {
  plan: DeckPlan;
  book: PlaceBook;
  nowMs: number;
  /** Running rounds by division room id. */
  rounds: ReadonlyMap<string, RoundView>;
  /** A gathering the captain called (by place: a division room id or "mess"). */
  called: { place: string; agentIds: readonly string[] } | null;
  /** How many idle decisions this agent made so far (feeds its seed). */
  turn: number;
  /** The place it took last time, so the same is not taken twice in a row. */
  last: string | null;
  /** Where the agent stands now. */
  at: Vec2;
}

const IDLE_WEIGHTS: Partial<Record<PlaceKind, number>> = {
  console: 26, mess: 16, lounge: 14, window: 14, galley: 9, stroll: 11, table: 10,
};

function rng(seed: number): () => number {
  let s = seed >>> 0 || 1;
  return () => { s ^= s << 13; s >>>= 0; s ^= s >> 17; s ^= s << 5; s >>>= 0; return s / 4294967296; };
}

function activityAt(place: Place, state: AgentRunState, reason: Reason): Activity {
  if (place.pose === "rest") return "rest";
  if (place.pose === "sit") return place.kind === "console" && state === "working" ? "type" : "sit";
  if (reason === "wait") return "wave";
  if (place.kind === "galley") return "lean";
  if (place.kind === "table") return reason === "round" ? "listen" : "talk";
  return "stand";
}

function intentFor(place: Place, state: AgentRunState, reason: Reason, untilMs: number): Intent {
  return { placeId: place.id, target: { x: place.x, z: place.z }, yaw: place.yaw, activity: activityAt(place, state, reason), seatY: place.seatY, untilMs, reason };
}

/** A standing place in front of the agent's own console (for waiting). */
function standAtConsole(seat: Place): Intent {
  return { placeId: null, target: { x: seat.x, z: seat.z }, yaw: seat.yaw, activity: "wave", seatY: 0, untilMs: Infinity, reason: "wait" };
}

export function decide(member: CrewState, ctx: LifeContext): Intent {
  const { plan, book } = ctx;
  const seat = plan.seatOf.get(member.agentId) ?? null;
  const division = member.division;

  // The captain's call outranks everything but work.
  if (ctx.called && ctx.called.agentIds.includes(member.agentId) && member.state !== "working") {
    const pool = ctx.called.place === "mess"
      ? plan.places.filter((p) => p.kind === "mess" || p.kind === "galley")
      : plan.places.filter((p) => p.kind === "table" && p.division === ctx.called?.place);
    const free = pool.filter((p) => !book.holder(p.id) || book.holder(p.id) === member.agentId);
    const pick = nearest(free, ctx.at);
    if (pick && book.reserve(pick.id, member.agentId)) return intentFor(pick, member.state, "called", Infinity);
  }

  if (member.state === "working" && seat) {
    book.release(member.agentId);
    return intentFor(seat, member.state, "work", Infinity);
  }
  // A round of the agent's team: idle and waiting members gather at the table.
  const round = division ? ctx.rounds.get(division) : undefined;
  if (round?.running && division && member.state !== "paused") {
    const gather = plan.places.filter((p) => p.kind === "table" && p.division === division);
    const own = gather.find((p) => book.holder(p.id) === member.agentId);
    const pick = own ?? nearest(gather.filter((p) => !book.holder(p.id)), ctx.at);
    if (pick && book.reserve(pick.id, member.agentId)) {
      const intent = intentFor(pick, member.state, "round", Infinity);
      if (round.speakerId === member.agentId) intent.activity = "talk";
      return intent;
    }
  }
  if (member.state === "waiting" && seat) {
    book.release(member.agentId);
    return standAtConsole(seat);
  }
  if (member.state === "paused") {
    const pods = plan.places.filter((p) => p.kind === "pod");
    const own = pods.find((p) => book.holder(p.id) === member.agentId);
    const pick = own ?? pods.find((p) => !book.holder(p.id));
    if (pick && book.reserve(pick.id, member.agentId)) return intentFor(pick, member.state, "rest", Infinity);
    if (seat) return { ...intentFor(seat, "idle", "rest", Infinity), activity: "sit" };
  }

  // Idle: a seeded choice of place.
  const random = rng(hash(member.agentId) ^ Math.imul(ctx.turn + 1, 2654435761));
  const stay = 25_000 + random() * 65_000;
  const candidates: { place: Place; weight: number }[] = [];
  for (const place of plan.places) {
    const w = IDLE_WEIGHTS[place.kind];
    if (!w || place.id === ctx.last) continue;
    if (place.kind === "console") { if (place.id !== seat?.id) continue; }
    else if (book.holder(place.id) && book.holder(place.id) !== member.agentId) continue;
    // The own division's table and windows are home; somebody else's division is not a hangout.
    if (place.division && place.division !== division) continue;
    const d = Math.hypot(place.x - ctx.at.x, place.z - ctx.at.z);
    const near = 1 / (1 + d / 18);
    candidates.push({ place, weight: w * (place.division ? 1.4 : 1) * (0.35 + near) });
  }
  const total = candidates.reduce((s, c) => s + c.weight, 0);
  let roll = random() * total;
  for (const c of candidates) {
    roll -= c.weight;
    if (roll <= 0) {
      if (c.place.kind === "console" || book.reserve(c.place.id, member.agentId)) {
        if (c.place.kind === "console") book.release(member.agentId);
        return intentFor(c.place, member.state, "idle", ctx.nowMs + stay);
      }
    }
  }
  // Nowhere free: stay where it is a while.
  book.release(member.agentId);
  return { placeId: null, target: ctx.at, yaw: 0, activity: "stand", seatY: 0, untilMs: ctx.nowMs + 15_000, reason: "idle" };
}

function nearest(list: readonly Place[], at: Vec2): Place | undefined {
  let best: Place | undefined, bd = Infinity;
  for (const p of list) {
    const d = Math.hypot(p.x - at.x, p.z - at.z);
    if (d < bd) { bd = d; best = p; }
  }
  return best;
}
