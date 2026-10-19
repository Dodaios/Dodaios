/**
 * The shared vocabulary of the starship's deck plans.
 *
 * A deck plan is pure data: rooms, walls with their doorways, furniture
 * footprints, the seats and standing places people use, and the stations the
 * captain interacts with. The renderer draws it, the navigation grid is
 * rasterised from it and the crew's life picks its places from it, so all
 * three always agree. Units are metres; x runs to starboard (east), z towards
 * the stern (south), y up. A yaw of 0 faces +z.
 */
import type { AgentRunState, AgentTier } from "../../data";

export type DeckId = "bridge" | "ops" | "engineering" | "holodeck" | "honors";

/** The turbolift's order, top of the ship first. */
export const DECKS: readonly DeckId[] = ["bridge", "ops", "engineering", "holodeck", "honors"];

/** The number painted beside a deck's turbolift doors. */
export function deckNumber(deck: DeckId): number {
  return DECKS.indexOf(deck) + 1;
}

export interface Vec2 { x: number; z: number }

/** Axis-aligned rectangle. */
export interface Rect { x0: number; z0: number; x1: number; z1: number }

export function rect(x0: number, z0: number, x1: number, z1: number): Rect {
  return { x0: Math.min(x0, x1), z0: Math.min(z0, z1), x1: Math.max(x0, x1), z1: Math.max(z0, z1) };
}

export function rectCentre(r: Rect): Vec2 {
  return { x: (r.x0 + r.x1) / 2, z: (r.z0 + r.z1) / 2 };
}

export function rectContains(r: Rect, p: Vec2, margin = 0): boolean {
  return p.x >= r.x0 - margin && p.x <= r.x1 + margin && p.z >= r.z0 - margin && p.z <= r.z1 + margin;
}

/** One person the plan seats: an agent of the roster or a coding pane projected into one. */
export interface CrewInput {
  agentId: string;
  name: string;
  tier: AgentTier;
  state: AgentRunState;
  createdMs: number;
}

export interface TeamInput {
  id: string;
  name: string;
  members: readonly string[];
  createdMs: number;
  leadId: string | null;
}

/**
 * What a wall is made of. `hull` is the ship's outer skin (thick, with a window
 * band where `windows` says so), `bulkhead` an inner wall, `glass` a framed
 * glass partition, `rail` a waist-high railing people cannot pass.
 */
export type WallKind = "hull" | "bulkhead" | "glass" | "rail";

export interface Wall {
  id: string;
  kind: WallKind;
  a: Vec2;
  b: Vec2;
  /** Thickness in metres. */
  t: number;
  /** A hull wall with a window band (the renderer cuts it; navigation does not care). */
  windows?: boolean;
}

/** A doorway: a gap in a wall that people walk through. `slides` doors open as someone comes near. */
export interface Door {
  id: string;
  at: Vec2;
  /** Clear width of the opening. */
  width: number;
  /** The wall's direction at the door: "x" = the wall runs east-west. */
  axis: "x" | "z";
  slides: boolean;
}

export type FloorFinish = "deck" | "carpet" | "grate" | "ceramic" | "holo" | "honor";

export type RoomKind =
  | "corridor" | "plaza" | "division" | "lounge" | "mess" | "quarters" | "quartermaster" | "transporter"
  | "lift" | "bridge" | "readyroom" | "engineering" | "bay" | "core" | "holodeck" | "hall";

export interface Room {
  id: string;
  kind: RoomKind;
  rect: Rect;
  floor: FloorFinish;
  /** The accent the room's trims and floor lines take (a team's colour, gold for command). */
  accent: string;
  /** i18n key or literal name (a team's name) shown on the room's sign; null = no sign. */
  sign: { key: string } | { text: string } | null;
  /** Where the sign hangs, if the room has one. */
  signAt?: Vec2 & { yaw: number };
}

/**
 * Furniture and fittings. Footprints are rotated rectangles (`w` along the
 * piece's own x, `d` along its own z, turned by `yaw`); solid ones block the
 * navigation grid. `ref` ties a piece to an agent (a console), a team (a
 * holo-table) or a station.
 */
export type PropKind =
  | "console" | "consoleChair" | "holoTable" | "transporter" | "transporterConsole" | "liftDoors"
  | "messTable" | "messStool" | "galley" | "sofa" | "lowTable" | "plant" | "pod" | "locker" | "mirror"
  | "divisionPlinth" | "pillar" | "captainChair" | "commandSeat" | "helmConsole" | "viewscreen" | "tacticalRail"
  | "starChart" | "reactor" | "systemsTable" | "bayConsole" | "cabinet" | "rankWall" | "honorCase" | "dais"
  | "crate" | "bench" | "conduit";

export interface Prop {
  id: string;
  kind: PropKind;
  x: number;
  z: number;
  yaw: number;
  w: number;
  d: number;
  /** Height of the piece (for the renderer's proportions and the camera's occlusion). */
  h: number;
  solid: boolean;
  ref?: string;
  /** Accent colour (team colour on a division's console). */
  accent?: string;
}

/**
 * A place someone sits or stands at. `console` seats belong to one agent
 * (`owner`); the rest are free places reserved by whoever goes there.
 */
export type PlaceKind =
  | "console" | "mess" | "lounge" | "window" | "galley" | "pod" | "table" | "stroll" | "chart" | "command" | "captain";

export type Pose = "sit" | "stand" | "rest" | "lean";

export interface Place {
  id: string;
  kind: PlaceKind;
  x: number;
  z: number;
  yaw: number;
  pose: Pose;
  /** Seat height for `sit`, couch height for `rest`. */
  seatY: number;
  owner?: string;
  /** The division (room id) the place belongs to, if any. */
  division?: string;
}

/** Things the captain uses. The renderer rims the prop with this id when the captain stands at it. */
export type StationKind =
  | "transporter" | "lift" | "division" | "newDivision" | "quartermaster" | "mess" | "captain" | "firstOfficer"
  | "helm" | "ops" | "systems" | "holoCabinet" | "rankWall" | "honorCase" | "pods";

export interface Station {
  id: string;
  kind: StationKind;
  /** Where the captain stands to use it. */
  x: number;
  z: number;
  /** How close counts as "at the station". */
  radius: number;
  /** The prop it rims and whose click it takes. */
  propId: string;
  /** Kind-specific reference: a team id (division), a game id (holo cabinet), a reward id (honour case). */
  ref?: string;
}

/** One team's division on the operations deck (or one IDE workspace's bay in engineering). */
export interface Division {
  id: string;
  /** The team (society chat group) or workspace; null = the crew without a team. */
  teamId: string | null;
  name: string;
  colour: string;
  leadId: string | null;
  /** Members seated here, in seating order. */
  members: string[];
  /** The holo-table (or bay console) in the middle. */
  centre: Vec2;
  room: string;
  /** Standing places round the centre for a gathering. */
  gather: Place[];
}

export interface DeckPlan {
  deck: DeckId;
  /** The floor's extent (the hull's bounding box). */
  bounds: Rect;
  /** The hull outline, clockwise from the bow; the renderer extrudes the outer skin from it. */
  hull: Vec2[];
  rooms: Room[];
  walls: Wall[];
  doors: Door[];
  props: Prop[];
  places: Place[];
  stations: Station[];
  divisions: Division[];
  /** The console seat of each agent the plan seats. */
  seatOf: ReadonlyMap<string, Place>;
  /** Where someone new to the deck appears (the transporter, or the lift doors). */
  arrival: Vec2;
  /** Where the captain steps out of the turbolift. */
  lift: Vec2 & { yaw: number };
  /** Agents the plan could not seat (a full deck); the HUD says so. */
  unseated: string[];
}
