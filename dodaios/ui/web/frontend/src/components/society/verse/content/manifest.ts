/**
 * The cooked deck manifest (schema `verse.deck/1`) exactly as the cook writes
 * it to `public/verse/decks/<id>/manifest.json`, plus a dependency-free
 * runtime validator and the world → plate pixel mapping.
 *
 * Source of truth for the shape: art/verse/schema/deck.schema.json (the cook
 * and scripts/verse/validate.py use the same schema). All positions are three.js
 * world axes in metres: X screen right, Y up, Z toward the camera. URLs are
 * relative to the manifest.
 */

export const DECK_MANIFEST_SCHEMA = "verse.deck/1";

export type ManifestVec2 = readonly [number, number];
export type ManifestVec3 = readonly [number, number, number];

export const MANIFEST_SOCKET_KINDS = [
  "screen", "seat", "stand", "bunk", "holo", "light", "door", "spawn", "lift", "station", "waypoint",
] as const;
export type ManifestSocketKind = (typeof MANIFEST_SOCKET_KINDS)[number];

export interface ManifestCamera {
  /** Degrees below the horizon (60). */
  pitch_deg: number;
  /** 0: the camera looks toward −Z. */
  yaw_deg: number;
  /** L0 plate pixels per metre along u. */
  px_per_m: number;
  /** Floor-plane point (y = 0) at the plate centre. */
  centre: ManifestVec3;
  right: ManifestVec3;
  up: ManifestVec3;
  /** View direction; camera position = centre − forward · distance. */
  forward: ManifestVec3;
  distance: number;
  frame_w_m: number;
  frame_h_m: number;
  plate_w_px: number;
  plate_h_px: number;
  /** Blender colour management of the plate ("AgX", look "None"). */
  view_transform: string;
  look: string;
  /** Stops; the actors use toneMappingExposure = 2^exposure with AgX tone mapping. */
  exposure: number;
}

/**
 * A tiled mip level between L0 and the overview: the plate downscaled by
 * `divisor` and cut into `tile_px` tiles (edge tiles smaller).
 */
export interface ManifestPlateMip {
  /** Density = px_per_m / divisor (2, 4). */
  divisor: number;
  /** round(plate_w_px / divisor) and round(plate_h_px / divisor). */
  w_px: number;
  h_px: number;
  cols: number;
  rows: number;
  /** Pattern with `{col}` and `{row}`, e.g. "plate/M2_{col}_{row}.avif". */
  tile_url: string;
}

export interface ManifestPlate {
  format: "avif";
  /** Tile edge of L0 and of every mip; the last column/row may be smaller. */
  tile_px: number;
  cols: number;
  rows: number;
  /** L0 tiles: a pattern with `{col}` and `{row}`, e.g. "plate/L0_{col}_{row}.avif". */
  tile_url: string;
  /** Optional mip levels, finest first; absent in older manifests. */
  mips?: readonly ManifestPlateMip[];
  /** Whole plate at reduced resolution (1/4 in older decks, 1/8 next to mips). */
  l1_url: string;
  l1_w_px: number;
  l1_h_px: number;
}

export interface ManifestNav {
  /** 8-bit grey PNG, w × h; row 0 is the far (−Z) edge. 0 = blocked. */
  url: string;
  /** World x of column 0's left edge; world z of row 0's top edge. */
  origin_x: number;
  origin_z: number;
  cell: number;
  w: number;
  h: number;
  /** Walkable pixel value v: floor y = (v − height_zero) · height_step. */
  height_zero: number;
  height_step: number;
  /** Neighbouring cells whose floor heights differ by more are not connected. */
  max_step: number;
  /** Body radius (metres) the walkable area is already eroded by. */
  clearance: number;
  walkable_cells: number;
}

export interface ManifestProbe {
  room: string;
  position: ManifestVec3;
  /** 9 linear-RGB radiance coefficients, three.js SphericalHarmonics3 order and basis. */
  sh: readonly ManifestVec3[];
}

export interface ManifestRoom {
  id: string;
  name: string;
  floor_y: number;
  /** Outline on the floor plane, [x, z]. */
  polygon: readonly ManifestVec2[];
  centre: ManifestVec3;
  area_m2: number;
  main: boolean;
  /** Remaining custom properties of the ROOM_ mesh (e.g. kind). */
  props?: Readonly<Record<string, unknown>>;
}

export interface ManifestSocket {
  /** Unique per kind. */
  id: string;
  kind: ManifestSocketKind;
  position: ManifestVec3;
  /** Rotation about +Y in degrees; 0 faces +Z (the camera), 90 faces +X (screen right). */
  yaw_deg: number;
  room: string | null;
  station?: string;
  /** Screens: width and height, metres. */
  size?: ManifestVec2;
  /** Screens: unit normal toward the viewer. */
  normal?: ManifestVec3;
  /** Screens: top-left, top-right, bottom-right, bottom-left as seen by the viewer. */
  corners?: readonly ManifestVec3[];
  /** Remaining custom properties of the socket empty (e.g. station_kind, radius). */
  props?: Readonly<Record<string, unknown>>;
}

export interface ManifestStation {
  id: string;
  kind: string;
  room: string | null;
  position: ManifestVec3;
  yaw_deg: number;
  /** Member socket ids by socket kind. */
  sockets: Readonly<Partial<Record<ManifestSocketKind, readonly string[]>>>;
}

export interface DeckManifest {
  schema: typeof DECK_MANIFEST_SCHEMA;
  id: string;
  name: string;
  floor: number;
  quality: "preview" | "final";
  camera: ManifestCamera;
  plate: ManifestPlate;
  occluders: { url: string; triangles: number };
  nav: ManifestNav;
  /** Equirect Radiance HDR in the three.js layout (centre column = +X). */
  env: { url: string; w: number; h: number; position: ManifestVec3 };
  probes: readonly ManifestProbe[];
  rooms: readonly ManifestRoom[];
  sockets: readonly ManifestSocket[];
  stations: readonly ManifestStation[];
  stats: Readonly<Record<string, number | string>>;
}

// ------------------------------------------------------------------ maths

/**
 * L0 plate pixel (origin top-left, y down, continuous: the plate spans
 * [0, plate_w_px] × [0, plate_h_px]) of a world point.
 *
 *   u = (P − C)·R,  v = (P − C)·U
 *   px = plate_w_px / 2 + u · px_per_m
 *   py = plate_h_px / 2 − v · px_per_m
 */
export function worldToPlatePx(camera: ManifestCamera, point: ManifestVec3): { x: number; y: number } {
  const dx = point[0] - camera.centre[0];
  const dy = point[1] - camera.centre[1];
  const dz = point[2] - camera.centre[2];
  const u = dx * camera.right[0] + dy * camera.right[1] + dz * camera.right[2];
  const v = dx * camera.up[0] + dy * camera.up[1] + dz * camera.up[2];
  return {
    x: camera.plate_w_px / 2 + u * camera.px_per_m,
    y: camera.plate_h_px / 2 - v * camera.px_per_m,
  };
}

/** Floor height in metres of a nav pixel value, or null when the cell is blocked. */
export function navHeight(nav: ManifestNav, value: number): number | null {
  return value === 0 ? null : (value - nav.height_zero) * nav.height_step;
}

/** Resolve a manifest-relative URL against the manifest's own URL. */
export function manifestUrl(manifestUrl: string, relative: string): string {
  const base = manifestUrl.slice(0, manifestUrl.lastIndexOf("/") + 1);
  return base + relative;
}

/** A tile pattern filled in for (col, row). */
export function fillTileUrl(pattern: string, col: number, row: number): string {
  return pattern.replace("{col}", String(col)).replace("{row}", String(row));
}

/** URL of the L0 tile at (col, row). */
export function tileUrl(plate: ManifestPlate, col: number, row: number): string {
  return fillTileUrl(plate.tile_url, col, row);
}

// ------------------------------------------------------------------ validation

export class ManifestError extends Error {
  constructor(public readonly path: string, message: string) {
    super(`${path}: ${message}`);
    this.name = "ManifestError";
  }
}

type Json = unknown;

function fail(path: string, message: string): never {
  throw new ManifestError(path, message);
}

function obj(value: Json, path: string): Record<string, Json> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) fail(path, "expected an object");
  return value as Record<string, Json>;
}

function num(value: Json, path: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) fail(path, "expected a finite number");
  return value;
}

function int(value: Json, path: string, min = 0): number {
  const n = num(value, path);
  if (!Number.isInteger(n) || n < min) fail(path, `expected an integer ≥ ${min}`);
  return n;
}

function str(value: Json, path: string): string {
  if (typeof value !== "string") fail(path, "expected a string");
  return value;
}

function nullableStr(value: Json, path: string): string | null {
  return value === null ? null : str(value, path);
}

function vec(value: Json, path: string, length: 2 | 3): number[] {
  if (!Array.isArray(value) || value.length !== length) fail(path, `expected ${length} numbers`);
  return value.map((item, i) => num(item, `${path}[${i}]`));
}

function list(value: Json, path: string): Json[] {
  if (!Array.isArray(value)) fail(path, "expected an array");
  return value;
}

function checkCamera(value: Json): void {
  const c = obj(value, "camera");
  for (const key of ["pitch_deg", "yaw_deg", "distance", "frame_w_m", "frame_h_m", "exposure"]) {
    num(c[key], `camera.${key}`);
  }
  for (const key of ["px_per_m", "plate_w_px", "plate_h_px"]) int(c[key], `camera.${key}`, 1);
  for (const key of ["centre", "right", "up", "forward"]) vec(c[key], `camera.${key}`, 3);
  str(c.view_transform, "camera.view_transform");
  str(c.look, "camera.look");
}

function checkMip(value: Json, path: string, tile: number, camera: ManifestCamera): void {
  const m = obj(value, path);
  const divisor = int(m.divisor, `${path}.divisor`, 2);
  const w = int(m.w_px, `${path}.w_px`, 1);
  const h = int(m.h_px, `${path}.h_px`, 1);
  // round() on the cook's side; a rounding mode may differ by one pixel, nothing more.
  if (Math.abs(w - camera.plate_w_px / divisor) > 1 || Math.abs(h - camera.plate_h_px / divisor) > 1) {
    fail(path, "w_px/h_px are not the plate divided by divisor");
  }
  const cols = int(m.cols, `${path}.cols`, 1);
  const rows = int(m.rows, `${path}.rows`, 1);
  if (cols !== Math.ceil(w / tile) || rows !== Math.ceil(h / tile)) fail(path, "cols/rows do not cover the level");
  const pattern = str(m.tile_url, `${path}.tile_url`);
  if (!pattern.includes("{col}") || !pattern.includes("{row}")) fail(`${path}.tile_url`, "needs {col} and {row}");
}

function checkPlate(value: Json, camera: ManifestCamera): void {
  const p = obj(value, "plate");
  if (p.format !== "avif") fail("plate.format", 'expected "avif"');
  const tile = int(p.tile_px, "plate.tile_px", 1);
  const cols = int(p.cols, "plate.cols", 1);
  const rows = int(p.rows, "plate.rows", 1);
  const pattern = str(p.tile_url, "plate.tile_url");
  if (!pattern.includes("{col}") || !pattern.includes("{row}")) fail("plate.tile_url", "needs {col} and {row}");
  if (cols !== Math.ceil(camera.plate_w_px / tile) || rows !== Math.ceil(camera.plate_h_px / tile)) {
    fail("plate", "cols/rows do not cover the plate");
  }
  if (p.mips !== undefined) {
    list(p.mips, "plate.mips").forEach((mip, i) => checkMip(mip, `plate.mips[${i}]`, tile, camera));
  }
  str(p.l1_url, "plate.l1_url");
  int(p.l1_w_px, "plate.l1_w_px", 1);
  int(p.l1_h_px, "plate.l1_h_px", 1);
}

function checkNav(value: Json): void {
  const n = obj(value, "nav");
  str(n.url, "nav.url");
  for (const key of ["origin_x", "origin_z", "cell", "height_step", "max_step", "clearance"]) {
    num(n[key], `nav.${key}`);
  }
  for (const key of ["w", "h", "height_zero"]) int(n[key], `nav.${key}`, 1);
  int(n.walkable_cells, "nav.walkable_cells", 1);
}

function checkSocket(value: Json, path: string): void {
  const s = obj(value, path);
  str(s.id, `${path}.id`);
  const kind = str(s.kind, `${path}.kind`);
  if (!(MANIFEST_SOCKET_KINDS as readonly string[]).includes(kind)) fail(`${path}.kind`, `unknown kind ${kind}`);
  vec(s.position, `${path}.position`, 3);
  num(s.yaw_deg, `${path}.yaw_deg`);
  nullableStr(s.room, `${path}.room`);
  if (s.station !== undefined) str(s.station, `${path}.station`);
  if (kind === "screen") {
    vec(s.size, `${path}.size`, 2);
    vec(s.normal, `${path}.normal`, 3);
    const corners = list(s.corners, `${path}.corners`);
    if (corners.length !== 4) fail(`${path}.corners`, "expected 4 corners");
    corners.forEach((corner, i) => vec(corner, `${path}.corners[${i}]`, 3));
  }
  if (s.props !== undefined) obj(s.props, `${path}.props`);
}

/** Validate parsed JSON as a deck manifest; throws ManifestError naming the first bad field. */
export function parseDeckManifest(value: Json): DeckManifest {
  const m = obj(value, "manifest");
  if (m.schema !== DECK_MANIFEST_SCHEMA) fail("schema", `expected "${DECK_MANIFEST_SCHEMA}"`);
  str(m.id, "id");
  str(m.name, "name");
  int(m.floor, "floor");
  if (m.quality !== "preview" && m.quality !== "final") fail("quality", 'expected "preview" or "final"');
  checkCamera(m.camera);
  const camera = m.camera as ManifestCamera;
  checkPlate(m.plate, camera);
  const occluders = obj(m.occluders, "occluders");
  str(occluders.url, "occluders.url");
  int(occluders.triangles, "occluders.triangles", 1);
  checkNav(m.nav);
  const env = obj(m.env, "env");
  str(env.url, "env.url");
  int(env.w, "env.w", 1);
  int(env.h, "env.h", 1);
  vec(env.position, "env.position", 3);
  list(m.probes, "probes").forEach((probe, i) => {
    const p = obj(probe, `probes[${i}]`);
    str(p.room, `probes[${i}].room`);
    vec(p.position, `probes[${i}].position`, 3);
    const sh = list(p.sh, `probes[${i}].sh`);
    if (sh.length !== 9) fail(`probes[${i}].sh`, "expected 9 coefficients");
    sh.forEach((c, k) => vec(c, `probes[${i}].sh[${k}]`, 3));
  });
  const rooms = list(m.rooms, "rooms");
  if (rooms.length === 0) fail("rooms", "expected at least one room");
  rooms.forEach((room, i) => {
    const r = obj(room, `rooms[${i}]`);
    str(r.id, `rooms[${i}].id`);
    str(r.name, `rooms[${i}].name`);
    num(r.floor_y, `rooms[${i}].floor_y`);
    const polygon = list(r.polygon, `rooms[${i}].polygon`);
    if (polygon.length < 3) fail(`rooms[${i}].polygon`, "expected at least 3 points");
    polygon.forEach((point, k) => vec(point, `rooms[${i}].polygon[${k}]`, 2));
    vec(r.centre, `rooms[${i}].centre`, 3);
    num(r.area_m2, `rooms[${i}].area_m2`);
    if (typeof r.main !== "boolean") fail(`rooms[${i}].main`, "expected a boolean");
    if (r.props !== undefined) obj(r.props, `rooms[${i}].props`);
  });
  list(m.sockets, "sockets").forEach((socket, i) => checkSocket(socket, `sockets[${i}]`));
  list(m.stations, "stations").forEach((station, i) => {
    const s = obj(station, `stations[${i}]`);
    str(s.id, `stations[${i}].id`);
    str(s.kind, `stations[${i}].kind`);
    nullableStr(s.room, `stations[${i}].room`);
    vec(s.position, `stations[${i}].position`, 3);
    num(s.yaw_deg, `stations[${i}].yaw_deg`);
    const members = obj(s.sockets, `stations[${i}].sockets`);
    for (const [kind, ids] of Object.entries(members)) {
      list(ids, `stations[${i}].sockets.${kind}`).forEach((id, k) => str(id, `stations[${i}].sockets.${kind}[${k}]`));
    }
  });
  obj(m.stats, "stats");
  return value as DeckManifest;
}
