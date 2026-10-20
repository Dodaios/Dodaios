/**
 * Who is on the deck on screen and where they are going: the crew placed by
 * crew life, the commander, the companion drone at the commander's heel and
 * the ship's company on their rounds. Pure: the stage feeds it the planner's
 * placements and the looks; ActorsLayer turns it into bodies.
 */
import type { Deck, Socket } from "../content/deck";
import type { CastMember } from "../actors/ActorsLayer";
import type { Look } from "../actors/look";
import type { CharacterContract } from "../actors/characters";
import { hash32, type CrewMember } from "./crew";
import { socketKey, type Placement } from "./planner";
import { commanderTarget, type CommanderOrders } from "./commander";

export const COMMANDER_ID = "commander";
export const COMPANION_ID = "companion";
const COMPANION_MODEL = "SK_Drone_Companion";
const UTILITY_MODEL = "SK_Drone_Utility";
/** At most this many of the ship's company on one deck. */
const MAX_TROOPERS = 3;
const MAX_DRONES = 2;
/** Routes a utility drone drives: service runs, cargo and pad rounds, corridors. */
const DRONE_ROUTE = /^(service|cargo|pad|corridor)/;

/** Waypoint routes of a deck: groups of two or more waypoints, in order. Pure. */
export function routesOf(deck: Pick<Deck, "sockets">): Map<string, Socket[]> {
  const routes = new Map<string, Socket[]>();
  for (const s of deck.sockets) {
    if (s.kind !== "waypoint") continue;
    const list = routes.get(s.group) ?? [];
    list.push(s);
    routes.set(s.group, list);
  }
  for (const [id, list] of routes) {
    if (list.length < 2) routes.delete(id);
    else list.sort((a, b) => a.order - b.order);
  }
  return routes;
}

export interface CommanderState {
  look: Look;
  orders: CommanderOrders;
}

export interface CastInput {
  deck: Deck;
  contract: CharacterContract;
  crew: ReadonlyMap<string, CrewMember>;
  placements: ReadonlyMap<string, Placement>;
  looks: ReadonlyMap<string, Look>;
  /** Members already on this deck when it opened: they are in place, not arriving. */
  aboard: ReadonlySet<string>;
  /** Agents created while the stage was open, still walking in from the shuttle. */
  arriving: ReadonlySet<string>;
  commander: CommanderState;
}

function walkPace(id: string): number {
  // Everyone has their own pace, 1.2–1.45 m/s.
  return 1.2 + (hash32(`${id}:pace`) % 26) / 100;
}

export function buildCast(input: CastInput): CastMember[] {
  const { deck, contract, crew, placements, looks, aboard, arriving, commander } = input;
  const cast: CastMember[] = [];
  for (const [id, p] of placements) {
    const member = crew.get(id);
    if (!member) continue;
    cast.push({
      id,
      body: member.role === "technician" ? "technician" : "officer",
      look: looks.get(id) ?? null,
      goal: { kind: "socket", socket: p.socket, activity: p.activity, faceCommander: p.faceCommander },
      goalKey: `${socketKey(p.socket)}:${p.activity}:${p.faceCommander}`,
      pace: walkPace(id),
      entry: aboard.has(id) ? "placed" : "lift",
    });
  }
  // A new officer comes off the shuttle and heads for the lift to report on the bridge.
  const lift = deck.sockets.find((s) => s.kind === "lift");
  if (deck.id === "hangar" && lift) {
    for (const id of arriving) {
      if (placements.has(id) || !crew.has(id)) continue;
      cast.push({
        id, body: "officer", look: looks.get(id) ?? null,
        goal: { kind: "leave", at: { x: lift.x, z: lift.z } }, goalKey: `arrive:${id}`, pace: walkPace(id), entry: "spawn",
      });
    }
  }
  const t = commanderTarget(deck, commander.orders);
  cast.push({
    id: COMMANDER_ID, body: "officer", look: commander.look,
    goal: { kind: "point", x: t.x, z: t.z }, goalKey: `point:${commander.orders.order}:${t.x.toFixed(2)}:${t.z.toFixed(2)}`,
    pace: 1.45, entry: commander.orders.fromLift ? "lift" : "placed",
  });
  if (contract.models.some((m) => m.id === COMPANION_MODEL)) {
    cast.push({
      id: COMPANION_ID, body: "companion", model: COMPANION_MODEL, look: null,
      goal: { kind: "follow", leaderId: COMMANDER_ID }, goalKey: "follow", pace: 1.7, entry: "placed",
    });
  }
  // The ship's company: troopers on patrol routes and at sentry posts, utility drones on service rounds.
  const trooper = contract.models.some((m) => m.kind === "trooper");
  const utility = contract.models.find((m) => m.id === UTILITY_MODEL);
  let troopers = 0;
  let drones = 0;
  for (const [route, points] of routesOf(deck)) {
    const patrol = route.startsWith("patrol");
    if (patrol ? !trooper || troopers >= MAX_TROOPERS : !utility || drones >= MAX_DRONES || !DRONE_ROUTE.test(route)) continue;
    if (patrol) troopers++; else drones++;
    cast.push({
      id: `ambient:${route}`, body: patrol ? "trooper" : "drone", model: patrol ? undefined : UTILITY_MODEL, look: null,
      goal: { kind: "route", points }, goalKey: `route:${route}`, pace: patrol ? 1.1 : (utility?.driveSpeed ?? 1.2), entry: "placed",
    });
  }
  if (trooper) {
    for (const post of deck.sockets.filter((s) => s.kind === "stand" && s.id.includes("sentry"))) {
      cast.push({
        id: `ambient:${post.id}`, body: "trooper", look: null, goal: { kind: "socket", socket: post, activity: "stand_guard", faceCommander: false },
        goalKey: `post:${post.id}`, pace: 1.1, entry: "placed",
      });
    }
  }
  return cast;
}
