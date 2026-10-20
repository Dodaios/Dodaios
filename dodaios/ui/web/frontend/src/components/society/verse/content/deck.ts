/**
 * A deck as the runtime uses it: the plate camera and images, the nav grid,
 * the sockets, stations, rooms and light probes the cook exported, validated
 * and resolved to absolute URLs. `loadDeck.ts` builds one from a cooked
 * manifest (schema verse.deck/1); the stage never reads raw manifest JSON.
 */
import type { DeckId } from "../decks";
import type { PlateCamera } from "../engine/plateMath";
import type { ManifestSocketKind } from "./manifest";

export type SocketKind = ManifestSocketKind;

export interface Socket {
  /** The name after `SOCKET_<kind>_`, e.g. "pit_p_3". Unique per kind. */
  id: string;
  kind: SocketKind;
  x: number;
  y: number;
  z: number;
  /** Facing, radians about +Y; 0 faces +Z (toward the camera). */
  yaw: number;
  room: string | null;
  /** The id without its trailing number ("pit_p_3" → "pit_p"): a row of consoles, a route. */
  group: string;
  /** The trailing number of the id (order along a route), 0 when there is none. */
  order: number;
  /** The station this socket belongs to, if any. */
  station: string | null;
  /** Screens: the exact quad, top-left, top-right, bottom-right, bottom-left (world). */
  corners: readonly (readonly [number, number, number])[] | null;
  /** Screens and holos: width and height, metres. */
  size: readonly [number, number] | null;
  /** The cook's extra properties (a light's `colour` and `blink_hz`, a holo's `radius`). */
  props: Readonly<Record<string, unknown>>;
}

/** Station kinds (the level design's contract with the engine). */
export const STATION_KINDS = [
  "agents_list", "team", "service_record", "mess_call", "games", "quartermaster", "coding_launcher", "create_agent", "lift",
] as const;
export type StationKind = (typeof STATION_KINDS)[number];

export interface Station {
  id: string;
  kind: StationKind;
  room: string | null;
  /** Where the commander stands to use it. */
  x: number;
  y: number;
  z: number;
  /** Member sockets by kind (the team table's seats, a console's screen). */
  sockets: Readonly<Partial<Record<SocketKind, readonly string[]>>>;
}

export interface Room {
  id: string;
  name: string;
  floorY: number;
  /** Floor outline, world (x, z), metres. */
  polygon: readonly (readonly [number, number])[];
  main: boolean;
}

export interface LightProbe {
  room: string | null;
  x: number;
  y: number;
  z: number;
  /** Nine linear-RGB L2 coefficients in three.js SphericalHarmonics3 order. */
  sh: readonly (readonly [number, number, number])[];
}

export interface NavGrid {
  /** Cell edge, metres (0.2). */
  cell: number;
  /** World x and z of the grid's minimum corner (row 0 is the far, −Z, edge). */
  x0: number;
  z0: number;
  cols: number;
  rows: number;
  /** 1 = walkable, row-major (row = z index). */
  walkable: Uint8Array;
  /** Floor height per cell, metres (0 where blocked). */
  heights: Float32Array;
  /** Largest height step a body takes between two neighbouring cells. */
  maxStep: number;
}

/** One tiled image of the plate: L0 (full density) or a mip (downscaled by its divisor). */
export interface PlateLevel {
  /** 1 for L0, else the mip's divisor (2, 4). */
  divisor: number;
  /** Size of this level in its own pixels. */
  width: number;
  height: number;
  /** Tile edge in pixels; edge tiles may be smaller. */
  tileSize: number;
  cols: number;
  rows: number;
  tileUrl: (col: number, row: number) => string;
}

export interface PlateImages {
  /** L0 size in pixels. */
  width: number;
  height: number;
  /** The whole plate at reduced resolution, loaded first. */
  overview: { url: string; width: number; height: number };
  /** L0 tile edge in pixels; edge tiles may be smaller. */
  tileSize: number;
  cols: number;
  rows: number;
  tileUrl: (col: number, row: number) => string;
  /**
   * Every tiled level, finest first: L0 (the same numbers as above), then the
   * mips by growing divisor. Just L0 for a deck cooked without mips.
   */
  levels: readonly PlateLevel[];
}

export interface Deck {
  id: DeckId;
  /** The content folder it was cooked into (the deck id, or "testbed" in development). */
  contentId: string;
  name: string;
  camera: PlateCamera;
  plate: PlateImages;
  /** Depth-only occluder meshes (UCX_), or null when the deck has none. */
  occludersUrl: string | null;
  /** Equirectangular radiance (Radiance HDR) for the characters' reflections. */
  envUrl: string | null;
  /** Blender's exposure (stops) for the plate, applied to the AgX-mapped actors so both match. */
  exposure: number;
  nav: NavGrid;
  sockets: readonly Socket[];
  stations: readonly Station[];
  rooms: readonly Room[];
  probes: readonly LightProbe[];
}

export function socketById(deck: Deck, kind: SocketKind, id: string): Socket | undefined {
  return deck.sockets.find((s) => s.kind === kind && s.id === id);
}
