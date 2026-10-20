/**
 * Crew life: where each crew member should be and what they do there, from
 * their real duty status (BRIEF §8). Pure and deterministic.
 *
 * Two steps. `intentOf` decides the venue and activity for one member from
 * its status, its part in a team round and a seeded off-duty routine; it
 * knows nothing of sockets. `placeOnDeck` then hands out the sockets of the
 * deck on screen to the members whose venue is there, with reservations so
 * nobody shares a seat, and keeps everyone's previous socket when it still
 * can so the crew does not reshuffle on every roster refresh.
 *
 * Home consoles are handed out across the whole roster in service order, not
 * only to whoever sits right now, so an officer's console never changes
 * because a colleague went to the mess.
 */
import type { Deck, Socket } from "../content/deck";
import type { DeckId } from "../decks";
import { byServiceOrder, hash32, type CrewMember } from "./crew";

export type Activity =
  | "sit_type" | "stand_wait" | "stand_alert" | "sit_rest" | "stand_rest" | "sleep" | "talk" | "listen"
  /** A trooper at a sentry post. */
  | "stand_guard";

export type Venue =
  | "console" | "terminal" | "briefing" | "mess" | "corridor" | "viewport" | "bunk" | "workshop";

export interface Intent {
  deck: DeckId;
  venue: Venue;
  activity: Activity;
  /** Turn toward the commander (waiting for the person) rather than the socket's facing. */
  faceCommander: boolean;
}

export type RoundPart = "speaker" | "listener";

/** How long an off-duty member stays at one venue before the seeded routine moves them on. */
export const IDLE_SLOT_MS = 6 * 60_000;

interface IdleVenue { venue: Venue; deck: DeckId; activity: Activity; weight: number }

const OFFICER_IDLE: readonly IdleVenue[] = [
  { venue: "mess", deck: "ops", activity: "sit_rest", weight: 5 },
  { venue: "corridor", deck: "ops", activity: "stand_rest", weight: 2 },
  { venue: "viewport", deck: "bridge", activity: "stand_rest", weight: 3 },
];

function pick<T extends { weight: number }>(options: readonly T[], seed: number): T {
  const total = options.reduce((s, o) => s + o.weight, 0);
  let x = seed % total;
  for (const o of options) {
    if (x < o.weight) return o;
    x -= o.weight;
  }
  return options[options.length - 1];
}

/** The off-duty venue of a member at `nowMs`; each member changes venue on its own clock. */
export function idleVenueOf(memberId: string, nowMs: number): IdleVenue {
  const offset = hash32(`${memberId}:phase`) % IDLE_SLOT_MS;
  const slot = Math.floor((nowMs + offset) / IDLE_SLOT_MS);
  return pick(OFFICER_IDLE, hash32(`${memberId}:${slot}`));
}

/** `messCall`: the commander called the off-duty crew to the mess. */
export function intentOf(member: CrewMember, part: RoundPart | undefined, nowMs: number, messCall = false): Intent {
  if (member.role === "technician") {
    switch (member.status) {
      case "working": return { deck: "engineering", venue: "terminal", activity: "sit_type", faceCommander: false };
      case "waiting": return { deck: "engineering", venue: "terminal", activity: "stand_wait", faceCommander: true };
      case "error": return { deck: "engineering", venue: "terminal", activity: "stand_alert", faceCommander: false };
      default: return { deck: "engineering", venue: "workshop", activity: "stand_rest", faceCommander: false };
    }
  }
  if (member.status === "paused") return { deck: "ops", venue: "bunk", activity: "sleep", faceCommander: false };
  if (part === "speaker" && member.status !== "waiting") return { deck: "bridge", venue: "briefing", activity: "talk", faceCommander: false };
  switch (member.status) {
    case "working": return { deck: "bridge", venue: "console", activity: "sit_type", faceCommander: false };
    case "waiting": return { deck: "bridge", venue: "console", activity: "stand_wait", faceCommander: true };
    case "error": return { deck: "bridge", venue: "console", activity: "stand_alert", faceCommander: false };
    default: {
      if (part === "listener") return { deck: "bridge", venue: "briefing", activity: "listen", faceCommander: false };
      if (messCall) return { deck: "ops", venue: "mess", activity: "sit_rest", faceCommander: false };
      const idle = idleVenueOf(member.id, nowMs);
      return { deck: idle.deck, venue: idle.venue, activity: idle.activity, faceCommander: false };
    }
  }
}

export interface Placement extends Intent {
  /** The socket the member goes to. */
  socket: Socket;
}

function bySocketOrder(a: Socket, b: Socket): number {
  return a.order - b.order || a.id.localeCompare(b.id);
}

/**
 * Seats with a screen of the same id: the bridge's consoles, engineering's
 * terminals. A seat that belongs to a station (the ready room's desk, a
 * simulator pod) is the commander's or the station's, not a crew console.
 */
export function consoleSeats(deck: Deck): Socket[] {
  const screens = new Set(deck.sockets.filter((s) => s.kind === "screen").map((s) => s.id));
  return deck.sockets.filter((s) => s.kind === "seat" && !s.station && screens.has(s.id)).sort(bySocketOrder);
}

/** The seats around the deck's first team table (a team station's member seats). */
export function teamTableSeats(deck: Deck): Socket[] {
  const table = deck.stations.find((s) => s.kind === "team");
  const ids = new Set(table?.sockets.seat ?? []);
  return deck.sockets.filter((s) => s.kind === "seat" && ids.has(s.id)).sort(bySocketOrder);
}

/** The sockets a venue offers on a deck, in hand-out order; dedicated sockets before waypoints. */
export function venueSockets(deck: Deck, venue: Venue): Socket[] {
  const s = deck.sockets;
  const of = (kind: Socket["kind"], test: (group: string) => boolean) => s.filter((x) => x.kind === kind && test(x.group)).sort(bySocketOrder);
  const is = (name: string) => (group: string) => group === name;
  const has = (name: string) => (group: string) => group.includes(name);
  switch (venue) {
    case "console":
    case "terminal": return consoleSeats(deck);
    case "briefing": return teamTableSeats(deck);
    case "mess": return [...of("seat", is("mess")), ...of("stand", is("mess"))];
    case "corridor": return [...of("stand", is("corridor")), ...of("waypoint", has("corridor"))];
    case "viewport": return [...of("stand", is("viewport")), ...of("waypoint", (g) => g.includes("viewport") || /^vp(_|$)/.test(g))];
    case "bunk": return of("bunk", () => true);
    case "workshop": return [...of("stand", is("workshop")), ...of("stand", is("corridor")), ...of("waypoint", (g) => !g.startsWith("patrol"))];
  }
}

/** Statuses that need a console now (working at it, or standing at it for the commander). */
const AT_CONSOLE: ReadonlySet<CrewMember["status"]> = new Set(["working", "waiting", "error"]);

/**
 * Home consoles (officers) and terminals (technicians) for the whole roster,
 * in service order, keeping each member's previous one while it is free.
 * When there are more members than consoles, those on duty come first: an
 * off-duty member gives up a console before a working one goes without.
 */
export function homeSeats(deck: Deck, crew: readonly CrewMember[], role: CrewMember["role"], previous: ReadonlyMap<string, string>): Map<string, string> {
  const seats = venueSockets(deck, role === "officer" ? "console" : "terminal");
  const ids = new Set(seats.map((s) => s.id));
  const members = crew.filter((m) => m.role === role).sort(byServiceOrder);
  const out = new Map<string, string>();
  const taken = new Set<string>();
  const keep = (group: readonly CrewMember[]) => {
    for (const m of group) {
      const kept = previous.get(m.id);
      if (kept && ids.has(kept) && !taken.has(kept)) { out.set(m.id, kept); taken.add(kept); }
    }
  };
  const fill = (group: readonly CrewMember[], spare: ReadonlySet<string>) => {
    for (const m of group) {
      if (out.has(m.id)) continue;
      // Seats nobody else holds first; another member's only when none is left.
      const seat = seats.find((s) => !taken.has(s.id) && !spare.has(s.id)) ?? seats.find((s) => !taken.has(s.id));
      if (!seat) return;
      out.set(m.id, seat.id);
      taken.add(seat.id);
    }
  };
  const onDuty = members.filter((m) => AT_CONSOLE.has(m.status));
  const offDuty = members.filter((m) => !AT_CONSOLE.has(m.status));
  const heldOffDuty = new Set(offDuty.map((m) => previous.get(m.id)).filter((id): id is string => !!id));
  keep(onDuty);
  fill(onDuty, heldOffDuty);
  keep(offDuty);
  fill(offDuty, new Set());
  return out;
}

export interface DeckPlanInput {
  deck: Deck;
  crew: readonly CrewMember[];
  /** Each member's part in a running team round. */
  rounds: ReadonlyMap<string, RoundPart>;
  nowMs: number;
  /** Last plan's socket keys (`socketKey`) by member, to keep places stable. */
  previous: ReadonlyMap<string, string>;
  /** Last plan's home consoles by member (seat ids), kept while their members are elsewhere. */
  homes?: ReadonlyMap<string, string>;
  messCall?: boolean;
}

export interface DeckPlan {
  placements: Map<string, Placement>;
  /** Home console (seat id) of every member who has one on this deck, placed here now or not. */
  homes: Map<string, string>;
}

/** A socket's key, unique on a deck (a seat and its screen share an id). */
export function socketKey(socket: Pick<Socket, "kind" | "id">): string {
  return `${socket.kind}:${socket.id}`;
}

/** The deck where a role has its consoles. */
const HOME_DECK: Record<CrewMember["role"], DeckId> = { officer: "bridge", technician: "engineering" };

/**
 * Placements of the members whose intent puts them on `deck` (members with no
 * free socket there are left out) and the home consoles of the deck.
 */
export function placeOnDeck({ deck, crew, rounds, nowMs, previous, homes: lastHomes, messCall = false }: DeckPlanInput): DeckPlan {
  const out = new Map<string, Placement>();
  const seatsById = new Map(consoleSeats(deck).map((s) => [s.id, s]));
  const previousSeats = new Map([...(lastHomes ?? []), ...[...previous].filter(([, key]) => key.startsWith("seat:")).map(([id, key]) => [id, key.slice(5)] as const)]);
  const homes = new Map<string, string>();
  for (const role of ["officer", "technician"] as const) {
    if (HOME_DECK[role] === deck.id) for (const [id, seat] of homeSeats(deck, crew, role, previousSeats)) homes.set(id, seat);
  }
  const taken = new Set<string>();
  const here: { member: CrewMember; intent: Intent }[] = [];
  for (const member of [...crew].sort(byServiceOrder)) {
    const intent = intentOf(member, rounds.get(member.id), nowMs, messCall);
    if (intent.deck === deck.id) here.push({ member, intent });
  }
  // Consoles and terminals first: they are reserved per member, whether it sits now or not.
  for (const home of homes.values()) taken.add(`seat:${home}`);
  for (const { member, intent } of here) {
    if (intent.venue !== "console" && intent.venue !== "terminal") continue;
    const seat = seatsById.get(homes.get(member.id) ?? "");
    if (seat) out.set(member.id, { ...intent, socket: seat });
  }
  // Every other venue: keep the previous socket, else a seeded free one so a group spreads out.
  for (const { member, intent } of here) {
    if (intent.venue === "console" || intent.venue === "terminal") continue;
    const free = venueSockets(deck, intent.venue).filter((s) => !taken.has(socketKey(s)));
    if (free.length === 0) continue;
    const kept = previous.get(member.id);
    const choice = free.find((s) => socketKey(s) === kept)
      ?? (intent.venue === "briefing" ? free[0] : free[hash32(`${member.id}:${intent.venue}`) % free.length]);
    out.set(member.id, { ...intent, socket: choice });
    taken.add(socketKey(choice));
  }
  return { placements: out, homes };
}
