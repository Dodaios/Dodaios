/**
 * What one player can know: the same information a person at the screen gets.
 *
 * - Their own state in full (it is on their HUD).
 * - The opponent only when in sight: a line of sight from the eye to the
 *   head, chest or hips that no collider blocks, inside the view cone of the
 *   over-the-shoulder camera (or very close by). Health is known always,
 *   because the duel HUD shows both bars.
 * - Bolts only when in sight (they glow, but not through walls).
 * - Shots heard (where they came from) and the direction of a hit taken.
 *
 * A bot reads nothing else, so it cannot see through walls. Works on the
 * authoritative state (headless duels) and on a client's view alike.
 */
import { lineOfSight, raycastWorld, type Arena } from "./arena";
import { angleDiff, DEG, forwardX, forwardZ, q, rightX, rightZ, yawOf } from "./math";
import type { CombatTuning } from "./tuning";
import type { BoltKind, BoltState, CombatEvent, MatchPhase, PlayerState } from "./types";

/**
 * Half the horizontal view of the hip camera (50 deg vertical at 16:9 shows
 * +-40 deg), with a little peripheral margin. Measured from the camera, which
 * sits behind the right shoulder, so close by it shows far more to the sides
 * than this angle from the body would.
 */
export const VIEW_HALF_DEG = 44;
/** The hip camera's place (camera.ts CAMERA_RIGS.hip): right of, above and behind the feet. */
const CAM_RIGHT = 0.55;
const CAM_UP = 1.68;
const CAM_BACK = 2.5;
/** Closer than this, the opponent is noticed whatever the view (heard, felt). */
export const AWARE_RADIUS = 3;
const BOLT_AWARE_RADIUS = 6;
/** Running footsteps carry this far (sprinting further); walking in sights is silent. */
export const FOOTSTEP_RUN_M = 9;
export const FOOTSTEP_SPRINT_M = 16;

export interface WorldView {
  tick: number;
  phase: MatchPhase;
  round: number;
  scores: readonly number[];
  players: readonly PlayerState[];
  bolts: readonly BoltState[];
  /** Events since the previous observation (for shots heard and hits taken). */
  events?: readonly CombatEvent[];
}

export interface EnemySighting {
  x: number;
  z: number;
  vx: number;
  vz: number;
  yaw: number;
  pitch: number;
  shieldUp: boolean;
  shieldBroken: boolean;
  /** Steam from the vents. */
  venting: boolean;
  overheated: boolean;
  ads: boolean;
  dodging: boolean;
  sprinting: boolean;
}

export interface BoltSighting {
  id: number;
  x: number;
  y: number;
  z: number;
  vx: number;
  vy: number;
  vz: number;
  owner: number;
  kind: BoltKind;
}

export interface Observation {
  tick: number;
  phase: MatchPhase;
  round: number;
  scores: readonly number[];
  slot: number;
  me: PlayerState;
  enemySlot: number;
  enemyAlive: boolean;
  enemyHealth: number;
  /** Null when the opponent is out of sight. */
  enemy: EnemySighting | null;
  bolts: BoltSighting[];
  /** Where enemy shots were heard from this tick. */
  heard: { x: number; z: number }[];
  /** Where the bolt that hurt me came from (this tick), if any. */
  hurtFrom: { x: number; z: number } | null;
  /** Footsteps: a running opponent nearby is heard, roughly where it is. */
  footsteps: { x: number; z: number } | null;
  /** HUD ping of the opponent during the reactor surge. */
  ping: { x: number; z: number } | null;
}

/**
 * Where a player's camera is (behind the right shoulder, level), pulled in
 * where a wall is in the way, as the view's camera collision does.
 */
export function cameraPoint(arena: Arena, me: { x: number; z: number; yaw: number }): { x: number; y: number; z: number } {
  const px = me.x + rightX(me.yaw) * CAM_RIGHT;
  const pz = me.z + rightZ(me.yaw) * CAM_RIGHT;
  const bx = px - forwardX(me.yaw) * CAM_BACK;
  const bz = pz - forwardZ(me.yaw) * CAM_BACK;
  if (raycastWorld(arena, me.x, CAM_UP, me.z, px, CAM_UP, pz)) {
    // No room beside the shoulder: the camera stays just behind the head.
    return { x: me.x - forwardX(me.yaw) * 0.3, y: CAM_UP, z: me.z - forwardZ(me.yaw) * 0.3 };
  }
  const hit = raycastWorld(arena, px, CAM_UP, pz, bx, CAM_UP, bz);
  const k = hit ? Math.max(0, hit.t - 0.08) : 1;
  return { x: px + (bx - px) * k, y: CAM_UP, z: pz + (bz - pz) * k };
}

function inView(me: PlayerState, cam: { x: number; z: number }, x: number, z: number, aware: number): boolean {
  const dx = x - me.x;
  const dz = z - me.z;
  if (dx * dx + dz * dz <= aware * aware) return true;
  return Math.abs(angleDiff(me.yaw, yawOf(x - cam.x, z - cam.z))) <= VIEW_HALF_DEG * DEG;
}

/**
 * True when `me` can see `other`: inside what the camera shows, with an
 * unblocked line to its head, chest or hips from the eyes or from the camera
 * (the over-the-shoulder view looks round a right-hand corner before the
 * body leaves cover, for people and bots alike).
 */
export function canSee(arena: Arena, t: CombatTuning, me: PlayerState, other: { x: number; z: number }, cam = cameraPoint(arena, me)): boolean {
  if (!inView(me, cam, other.x, other.z, AWARE_RADIUS)) return false;
  const ey = t.body.eyeHeight;
  for (const y of [1.65, 1.15, 0.6]) {
    if (lineOfSight(arena, me.x, ey, me.z, other.x, y, other.z)) return true;
    if (lineOfSight(arena, cam.x, cam.y, cam.z, other.x, y, other.z)) return true;
  }
  return false;
}

export function observe(view: WorldView, slot: number, arena: Arena, t: CombatTuning): Observation {
  const me = view.players[slot];
  const enemySlot = 1 - slot;
  const e = view.players[enemySlot];
  let enemy: EnemySighting | null = null;
  const cam = cameraPoint(arena, me);
  if (e && e.alive && me.alive && canSee(arena, t, me, e, cam)) {
    enemy = {
      x: e.x, z: e.z, vx: e.vx, vz: e.vz, yaw: e.yaw, pitch: e.pitch,
      shieldUp: e.shieldUp, shieldBroken: e.shieldBrokenUntil > view.tick,
      venting: e.ventStart >= 0, overheated: e.ventStart >= 0 && e.ventForced,
      ads: e.ads > 0.5, dodging: view.tick < e.dodgeUntil, sprinting: e.sprinting,
    };
  }
  const bolts: BoltSighting[] = [];
  const ey = t.body.eyeHeight;
  for (const b of view.bolts) {
    if (!inView(me, cam, b.x, b.z, BOLT_AWARE_RADIUS)) continue;
    if (!lineOfSight(arena, me.x, ey, me.z, b.x, b.y, b.z) && !lineOfSight(arena, cam.x, cam.y, cam.z, b.x, b.y, b.z)) continue;
    bolts.push({ id: b.id, x: b.x, y: b.y, z: b.z, vx: b.vx, vy: b.vy, vz: b.vz, owner: b.owner, kind: b.kind });
  }
  const heard: { x: number; z: number }[] = [];
  let hurtFrom: { x: number; z: number } | null = null;
  let ping: { x: number; z: number } | null = null;
  for (const ev of view.events ?? []) {
    if (ev.type === "shot" && ev.player === enemySlot) heard.push({ x: ev.x, z: ev.z });
    else if (ev.type === "hit" && ev.target === slot) hurtFrom = { x: ev.fromX, z: ev.fromZ };
    else if (ev.type === "ping" && ev.player === enemySlot) ping = { x: ev.x, z: ev.z };
  }
  let footsteps: { x: number; z: number } | null = null;
  if (e && e.alive && me.alive && !enemy) {
    const speed = Math.hypot(e.vx, e.vz);
    const range = e.sprinting ? FOOTSTEP_SPRINT_M : FOOTSTEP_RUN_M;
    if (speed > 3 && Math.hypot(e.x - me.x, e.z - me.z) <= range) footsteps = { x: q(e.x, 2), z: q(e.z, 2) };
  }
  return {
    tick: view.tick, phase: view.phase, round: view.round, scores: view.scores, slot, me,
    enemySlot, enemyAlive: !!e && e.alive, enemyHealth: e ? e.health : 0,
    enemy, bolts, heard, hurtFrom, footsteps, ping,
  };
}
