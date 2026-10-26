/**
 * The duel wire protocol, version 2.
 *
 * Messages are JSON arrays with a one-letter tag (compact, schema-free on the
 * wire, typed here). Numbers in states and inputs are integers on a fixed
 * grid; the simulation quantises its state to the same grid after every
 * step, so encode/decode is lossless and a client replays from exactly the
 * server's state.
 *
 * client -> server
 *   ["h", v, playerId, name, rulesHash]            hello (reliable); rulesHash covers tuning and arena
 *   ["i", lastSnapTick, [input, ...]]               the newest inputs, oldest first;
 *                                                   each send repeats the last few (loss)
 *   ["l"]                                           leave = forfeit (reliable)
 *   ["p", clientMs]                                 ping
 * server -> client
 *   ["w", v, slot, matchId, seed, tuningHash, arenaId, snapshotEvery, config, playerIds]  welcome (reliable)
 *   ["s", tick, ackSeq, state, events]              snapshot (unreliable, full state); the events
 *                                                   since the snapshot the client last confirmed
 *   ["e", winner, reason, scores, tick, ackSeq, state, events]
 *                                                   match over, with the final snapshot (reliable)
 *   ["o", clientMs, serverTick]                     pong
 *   ["r", reason]                                   rejected (reliable)
 *
 * input = [seq, mx*127, my*127, yaw*1e4, pitch*1e4, buttons, viewTick]
 */
import { AIM_SCALE, MOVE_SCALE } from "./input";
import type {
  BoltKind, BoltState, CombatEvent, EndReason, InputCommand, MatchConfig, MatchPhase, MatchState, PlayerState, PlayerStats,
} from "./types";

/** 2: the end message carries the final snapshot; snapshots carry the events since the last confirmed one. */
export const PROTOCOL_VERSION = 2;

export type EncodedInput = [number, number, number, number, number, number, number];
export type EncodedState = (number | (string | number)[] | (string | number)[][])[];

export type ClientMsg =
  | ["h", number, string, string, number]
  | ["i", number, EncodedInput[]]
  | ["l"]
  | ["p", number];

export type ServerMsg =
  | ["w", number, number, string, number, number, string, number, MatchConfig, string[]]
  | ["s", number, number, EncodedState, CombatEvent[]]
  /** Match over; carries the final snapshot (tick, ackSeq, state, events) so it cannot be overtaken by it. */
  | ["e", number, EndReason, number[], number, number, EncodedState, CombatEvent[]]
  | ["o", number, number]
  | ["r", string];

export function isReliable(msg: ClientMsg | ServerMsg): boolean {
  if (!Array.isArray(msg)) return false;
  const t = msg[0];
  return t === "h" || t === "l" || t === "w" || t === "e" || t === "r";
}

// ---------------------------------------------------------------- inputs

export function encodeInput(c: InputCommand): EncodedInput {
  return [c.seq, Math.round(c.mx * MOVE_SCALE), Math.round(c.my * MOVE_SCALE), Math.round(c.yaw * AIM_SCALE), Math.round(c.pitch * AIM_SCALE), c.buttons, c.viewTick];
}

export function decodeInput(e: EncodedInput): InputCommand {
  return { seq: e[0], mx: e[1] / MOVE_SCALE, my: e[2] / MOVE_SCALE, yaw: e[3] / AIM_SCALE, pitch: e[4] / AIM_SCALE, buttons: e[5], viewTick: e[6] };
}

// ---------------------------------------------------------------- state

type NumKey = { [K in keyof PlayerState]: PlayerState[K] extends number | boolean ? K : never }[keyof PlayerState];

/** Player fields in wire order with their grid (0 = boolean). */
export const PLAYER_FIELDS: readonly (readonly [NumKey, number])[] = [
  ["slot", 1], ["side", 1], ["x", 1000], ["z", 1000], ["vx", 1000], ["vz", 1000], ["yaw", AIM_SCALE], ["pitch", AIM_SCALE],
  ["recoilPitch", 1000], ["recoilYaw", 1000], ["alive", 0], ["health", 1000], ["lastDamageTick", 1],
  ["mx", MOVE_SCALE], ["my", MOVE_SCALE], ["buttons", 1], ["lastSeq", 1],
  ["heat", 1000], ["lastShotTick", 1], ["nextShotTick", 1], ["bloom", 1000], ["shotCount", 1],
  ["ventStart", 1], ["ventEnd", 1], ["ventWinStart", 1], ["ventWinEnd", 1], ["ventFromHeat", 1000], ["ventForced", 0], ["ventAttempted", 0],
  ["ads", 1000], ["sprinting", 0], ["sprintEndTick", 1],
  ["shieldUp", 0], ["shieldEnergy", 1000], ["shieldRaisedAt", 1], ["shieldLoweredAt", 1], ["shieldBrokenUntil", 1],
  ["shieldNeedsRelease", 0], ["shieldParryUsed", 0], ["parryReadyAt", 1],
  ["dodgeStart", 1], ["dodgeUntil", 1], ["dodgeReadyAt", 1], ["dodgeDx", 10000], ["dodgeDz", 10000],
];

export const STAT_FIELDS: readonly (readonly [keyof PlayerStats, number])[] = [
  ["shots", 1], ["hits", 1], ["headshots", 1], ["damageDealt", 100], ["damageTaken", 100], ["blocks", 1], ["parries", 1],
  ["deflects", 1], ["dodges", 1], ["overheats", 1], ["perfectVents", 1], ["ventMisses", 1], ["kills", 1],
];

const PHASES: readonly MatchPhase[] = ["countdown", "live", "round_end", "ended"];
const REASONS: readonly EndReason[] = ["rounds", "forfeit", "disconnect", "draw", "cancelled"];
const KINDS: readonly BoltKind[] = ["shot", "deflect", "parry"];

function encodePlayer(p: PlayerState): (string | number)[] {
  const out: (string | number)[] = [p.id];
  for (const [k, scale] of PLAYER_FIELDS) {
    const v = p[k];
    out.push(scale === 0 ? (v ? 1 : 0) : Math.round((v as number) * scale));
  }
  for (const [k, scale] of STAT_FIELDS) out.push(Math.round(p.stats[k] * scale));
  return out;
}

function decodePlayer(a: (string | number)[]): PlayerState {
  const p = { id: String(a[0]) } as Record<string, unknown>;
  let i = 1;
  for (const [k, scale] of PLAYER_FIELDS) {
    const v = a[i++] as number;
    p[k] = scale === 0 ? v === 1 : v / scale + 0;
  }
  const stats = {} as Record<string, number>;
  for (const [k, scale] of STAT_FIELDS) stats[k] = (a[i++] as number) / scale + 0;
  p.stats = stats;
  return p as unknown as PlayerState;
}

function encodeBolt(b: BoltState): number[] {
  return [b.id, b.owner, b.shooter, KINDS.indexOf(b.kind), Math.round(b.x * 1000), Math.round(b.y * 1000), Math.round(b.z * 1000),
    Math.round(b.vx * 1000), Math.round(b.vy * 1000), Math.round(b.vz * 1000), Math.round(b.damageMul * 10000), Math.round(b.traveled * 1000), b.bornTick, b.reflections];
}

function decodeBolt(a: number[]): BoltState {
  return {
    id: a[0], owner: a[1], shooter: a[2], kind: KINDS[a[3]] ?? "shot",
    x: a[4] / 1000 + 0, y: a[5] / 1000 + 0, z: a[6] / 1000 + 0, vx: a[7] / 1000 + 0, vy: a[8] / 1000 + 0, vz: a[9] / 1000 + 0,
    damageMul: a[10] / 10000 + 0, traveled: a[11] / 1000 + 0, bornTick: a[12], reflections: a[13],
  };
}

/** Everything but the lag-compensation history (the server keeps that to itself). */
export function encodeState(s: MatchState): EncodedState {
  return [
    s.tick, PHASES.indexOf(s.phase), s.phaseStart, s.phaseEndsAt, s.round, s.roundStartTick, s.scores[0], s.scores[1],
    s.winner === null ? -9 : s.winner, s.endReason === null ? -1 : REASONS.indexOf(s.endReason), s.nextBoltId, s.seed,
    s.players.map(encodePlayer), s.bolts.map(encodeBolt),
  ];
}

export function decodeState(e: EncodedState, config: MatchConfig): MatchState {
  const n = (i: number) => e[i] as number;
  return {
    v: 1, tick: n(0), phase: PHASES[n(1)] ?? "live", phaseStart: n(2), phaseEndsAt: n(3), round: n(4), roundStartTick: n(5),
    scores: [n(6), n(7)], winner: n(8) === -9 ? null : n(8), endReason: n(9) < 0 ? null : REASONS[n(9)] ?? "cancelled",
    nextBoltId: n(10), seed: n(11), config,
    players: (e[12] as (string | number)[][]).map(decodePlayer),
    bolts: (e[13] as unknown as number[][]).map(decodeBolt),
    history: { ticks: [], poses: [] },
  };
}

/** Bytes a message takes as JSON text (for budgets and tests). */
export function wireSize(msg: ClientMsg | ServerMsg): number {
  return JSON.stringify(msg).length;
}
