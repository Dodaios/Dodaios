/**
 * Small helpers every deck plan is assembled with: a collector that refuses
 * duplicate ids, walls with doorways cut into them, arcs of seats, and the
 * team colours. Pure; no rendering here.
 */
import type { DeckId, DeckPlan, Door, Place, Prop, Rect, Room, Station, Vec2, Wall, WallKind, Division } from "./types";

/** Twelve division colours, picked to stay apart on a dark deck and from the state colours. */
export const DIVISION_COLOURS = [
  "#3fb6ff", "#f2a33a", "#a68cff", "#4fd1a6", "#ff6f91", "#e8d44d",
  "#5b8cff", "#ff8a4c", "#c06bd6", "#35c3c9", "#9bd65b", "#f07ad0",
] as const;

/** The crew without a team wears the ship's own steel blue. */
export const POOL_COLOUR = "#8aa4c8";
/** Command: everything the captain uses, and the leads' marks. */
export const COMMAND_GOLD = "#d9a441";
/** Information: holograms, screens. */
export const HOLO_CYAN = "#5fd4ff";

export function slug(id: string): string {
  return id.replace(/[^A-Za-z0-9_-]/g, "_");
}

export class PlanBuilder {
  readonly rooms: Room[] = [];
  readonly walls: Wall[] = [];
  readonly doors: Door[] = [];
  readonly props: Prop[] = [];
  readonly places: Place[] = [];
  readonly stations: Station[] = [];
  readonly divisions: Division[] = [];
  private readonly ids = new Set<string>();

  constructor(readonly deck: DeckId) {}

  /** Ids are unique per kind of thing: a station may share its prop's id. */
  private claim(kind: string, id: string): string {
    const key = `${kind}:${id}`;
    if (this.ids.has(key)) throw new Error(`duplicate plan id ${key}`);
    this.ids.add(key);
    return id;
  }

  room(room: Room): Room { this.claim("room", room.id); this.rooms.push(room); return room; }
  prop(prop: Prop): Prop { this.claim("prop", prop.id); this.props.push(prop); return prop; }
  place(place: Place): Place { this.claim("place", place.id); this.places.push(place); return place; }
  station(station: Station): Station { this.claim("station", station.id); this.stations.push(station); return station; }
  door(door: Door): Door { this.claim("door", door.id); this.doors.push(door); return door; }

  wall(id: string, kind: WallKind, a: Vec2, b: Vec2, t = kind === "hull" ? 0.5 : kind === "glass" ? 0.12 : kind === "rail" ? 0.1 : 0.24, windows = false): void {
    if (Math.hypot(b.x - a.x, b.z - a.z) < 0.05) return;
    this.walls.push({ id: this.claim("wall", id), kind, a, b, t, windows });
  }

  /**
   * A straight wall from `a` to `b` (axis-aligned) with doorways cut at the
   * given offsets (metres from `a`). Each doorway becomes a `Door`.
   */
  wallWithDoors(id: string, kind: WallKind, a: Vec2, b: Vec2, gaps: { at: number; width: number; slides?: boolean; id?: string }[], t?: number): void {
    const len = Math.hypot(b.x - a.x, b.z - a.z);
    const ux = (b.x - a.x) / len, uz = (b.z - a.z) / len;
    const axis: "x" | "z" = Math.abs(ux) > Math.abs(uz) ? "x" : "z";
    const sorted = [...gaps].sort((p, q) => p.at - q.at);
    let from = 0;
    sorted.forEach((gap, i) => {
      const s = Math.max(0, gap.at - gap.width / 2), e = Math.min(len, gap.at + gap.width / 2);
      this.wall(`${id}:${i}`, kind, { x: a.x + ux * from, z: a.z + uz * from }, { x: a.x + ux * s, z: a.z + uz * s }, t);
      this.door({ id: gap.id ?? `${id}:door${i}`, at: { x: a.x + ux * gap.at, z: a.z + uz * gap.at }, width: gap.width, axis, slides: gap.slides ?? true });
      from = e;
    });
    this.wall(`${id}:${sorted.length}`, kind, { x: a.x + ux * from, z: a.z + uz * from }, b, t);
  }

  build(extra: Pick<DeckPlan, "bounds" | "hull" | "arrival" | "lift"> & { seatOf?: Map<string, Place>; unseated?: string[] }): DeckPlan {
    return {
      deck: this.deck,
      bounds: extra.bounds,
      hull: extra.hull,
      rooms: this.rooms,
      walls: this.walls,
      doors: this.doors,
      props: this.props,
      places: this.places,
      stations: this.stations,
      divisions: this.divisions,
      seatOf: extra.seatOf ?? new Map(),
      arrival: extra.arrival,
      lift: extra.lift,
      unseated: extra.unseated ?? [],
    };
  }
}

/** Bounding box of a polygon. */
export function polygonBounds(points: readonly Vec2[]): Rect {
  let x0 = Infinity, z0 = Infinity, x1 = -Infinity, z1 = -Infinity;
  for (const p of points) { x0 = Math.min(x0, p.x); z0 = Math.min(z0, p.z); x1 = Math.max(x1, p.x); z1 = Math.max(z1, p.z); }
  return { x0, z0, x1, z1 };
}

/** Even-odd point-in-polygon. */
export function insidePolygon(points: readonly Vec2[], p: Vec2): boolean {
  let inside = false;
  for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
    const a = points[i], b = points[j];
    if ((a.z > p.z) !== (b.z > p.z) && p.x < ((b.x - a.x) * (p.z - a.z)) / (b.z - a.z) + a.x) inside = !inside;
  }
  return inside;
}

/** Yaw that faces from `from` towards `to` (0 = +z). */
export function yawTowards(from: Vec2, to: Vec2): number {
  return Math.atan2(to.x - from.x, to.z - from.z);
}

/**
 * Points on an arc round `centre`: `count` evenly spaced over `span` radians,
 * centred on `mid` (the direction, as a yaw, the middle of the arc lies in).
 */
export function arcPoints(centre: Vec2, radius: number, count: number, mid: number, span: number): (Vec2 & { yaw: number })[] {
  const out: (Vec2 & { yaw: number })[] = [];
  if (count <= 0) return out;
  const step = count === 1 ? 0 : span / (count - 1);
  const start = mid - (step * (count - 1)) / 2;
  for (let i = 0; i < count; i += 1) {
    const a = start + step * i;
    out.push({ x: centre.x + Math.sin(a) * radius, z: centre.z + Math.cos(a) * radius, yaw: a });
  }
  return out;
}

/** A stable small hash for deterministic choices. */
export function hash(text: string): number {
  let h = 2166136261;
  for (let i = 0; i < text.length; i += 1) { h ^= text.charCodeAt(i); h = Math.imul(h, 16777619); }
  return h >>> 0;
}
