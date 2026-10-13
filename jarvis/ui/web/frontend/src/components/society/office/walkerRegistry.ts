/**
 * Where every agent stands right now, written by the walkers each frame and
 * read by the player (who is nearby?) and the HUD (focus the camera on X).
 * A plain module map: per-frame positions must never become React state.
 */
import type { Point } from "./officeLayout";

export const agentPositions = new Map<string, Point>();

/** Agent ids the office has already seen; a newcomer arrives by the elevator. */
export const knownAgents = new Set<string>();

/** Agents sitting at their own desk right now — their monitor shows their chat. */
export const seatedAtDesk = new Set<string>();

/**
 * Agents flying along at the person's shoulder right now (Gigi). They are no
 * obstacle and no "nearby" target: they would always be the closest one.
 */
export const companions = new Set<string>();

/** Other solid bodies on the floor that are not agents (the office dog), by id. */
export const extraBodies = new Map<string, Point>();

/**
 * Every body except `selfId`: all agents, the extra bodies (the office dog) plus, optionally, the person's character.
 * Gigi counts too — it hovers at chest height, so walking "under" it would pass
 * through it — except while it follows the person as a companion.
 */
export function* bodiesExcept(selfId: string | null, player: Point | null): Generator<Point> {
  for (const [id, p] of agentPositions) if (id !== selfId && !companions.has(id)) yield p;
  for (const [id, p] of extraBodies) if (id !== selfId) yield p;
  if (player) yield player;
}

/**
 * The person's pet (Jarvis) as drawn right now: ground position, the height
 * of its body centre and of its top, and its size. Written by `GigiFlyer`
 * each frame; the level system's cosmetics and celebrations follow it.
 */
export const petBody = { x: 0, z: 0, y: 0, top: 0.5, sizeM: 0.5, active: false };

/**
 * The bodies within `radius` of `at`, without `selfId`: what a walker steers round. Fills and returns `out`,
 * so a walker reuses one array instead of allocating a list of the whole floor every frame.
 */
export function bodiesNear(selfId: string | null, at: Point, radius: number, player: Point | null, out: Point[] = []): Point[] {
  out.length = 0;
  // The same bodies as `bodiesExcept`, walked in place: this runs for every walker on every frame.
  for (const [id, p] of agentPositions) {
    if (id !== selfId && !companions.has(id) && Math.abs(p.x - at.x) <= radius && Math.abs(p.z - at.z) <= radius) out.push(p);
  }
  for (const [id, p] of extraBodies) {
    if (id !== selfId && Math.abs(p.x - at.x) <= radius && Math.abs(p.z - at.z) <= radius) out.push(p);
  }
  if (player && Math.abs(player.x - at.x) <= radius && Math.abs(player.z - at.z) <= radius) out.push(player);
  return out;
}

/** Write where an agent stands; its entry is moved in place, so a frame of forty walkers allocates nothing. */
export function placeAgent(agentId: string, x: number, z: number): void {
  const at = agentPositions.get(agentId);
  if (at) { at.x = x; at.z = z; } else agentPositions.set(agentId, { x, z });
}

/** What one walker is doing right now, for the dev handle (`window.__officeLife`); written in development builds only. */
export interface WalkerDebug {
  id: string;
  name: string;
  state: string;
  /** The team whose studio the agent sits in; null = the pool, or a floor without studios. */
  team: string | null;
  studio: string | null;
  /** Its part in a running round of its team: none, gather, speaker or busy. */
  role: string;
  plan: string | null;
  phase: "travel" | "dwell";
  target: Point | null;
  spot: string | null;
  with: string | null;
  at: Point;
  /** Waypoints and metres left on the current walk. */
  pathLength: number;
  remainingM: number;
  /**
   * The current walk by the walker's own clock (the frame time it was actually given, not wall time and not
   * what a stepping script assumes): seconds walked so far and the average speed along the route in m/s.
   * Both are 0 while it stands.
   */
  walkS: number;
  speed: number;
  /** Seconds without progress on the current walk (the stuck watch). */
  stuckS: number;
  /**
   * Since the walker mounted: detours round a body, safe placements, route repairs, arrivals beside an occupied
   * place, walks given up because the way stayed closed, targets a new floor plan walled off.
   */
  replans: number;
  rescues: number;
  repaths: number;
  near: number;
  blocked: number;
  lost: number;
}

export const walkerDebug = new Map<string, WalkerDebug>();
