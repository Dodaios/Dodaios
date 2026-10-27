/**
 * "Road Hopper": steer a little courier bot from the street up to the three
 * delivery pads on the rooftop. It crosses four lanes of traffic, a quay and
 * a canal on the way. One hop per press (holding a direction does not keep
 * hopping). On the canal only hover barges and ice floes carry the bot; the
 * water, a floe that cracks and sinks, or being carried off the edge cost a
 * life, and so does the battery running flat. Between the pads runs a live
 * fence that zaps. Lighting all three pads starts the next level with faster
 * lanes; now and then a parcel waits on a pad for a bonus.
 *
 * The lanes never store moving objects: each lane is a fixed pattern of
 * items plus one scrolling `shift`, so the world costs no allocations.
 */
import type { RetroDrawInfo, RetroGame, RetroInput, RetroStatus } from "../retroGame";
import {
  clamp, drawNumber, drawParticles, drawSprite, emitBurst, makeParticles, sprite, stepParticles,
  type Particle, type PixelSprite,
} from "./games3Kit";

export const WIDTH = 256;
export const HEIGHT = 224;
export const CELL = 16;

export const HOME_ROW = 1;
export const START_ROW = 11;
export const START_X = WIDTH / 2;
/** Rows 2–5 are canal, row 6 the quay, rows 7–10 road. */
export const CANAL_TOP = 2;
export const CANAL_BOTTOM = 5;
export const QUAY_ROW = 6;
export const ROAD_TOP = 7;
export const ROAD_BOTTOM = 10;

export const HOP_S = 0.1;
/** Seconds of battery per bot. */
export const BATTERY_TIME = 40;
const DEATH_S = 1.2;
const LEVEL_S = 2;
/** Half the bot's width for traffic; a canal carrier must hold its centre. */
const BOT_HALF = 6;
export const PAD_X: readonly number[] = [48, 128, 208];
/** How far off a pad's centre a landing still counts. */
const PAD_CATCH = 10;
export const PARCEL_BONUS = 250;
export const PAD_POINTS = 100;
/** Points per whole second of battery left when a pad lights up. */
export const BATTERY_POINTS = 5;
export const ROW_POINTS = 5;
export const LEVEL_POINTS = 750;
/** Items are placed so they start fully off the left edge; any item is at most this long. */
const MARGIN = 96;

export type LaneKind = "barge" | "floe" | "bus" | "van" | "scooter" | "sweeper";

export interface LaneDef {
  row: number;
  kind: LaneKind;
  /** Pixels per second at level 1; positive moves right. */
  speed: number;
  /** Length of one repeat of the pattern; must be at least WIDTH + MARGIN. */
  period: number;
  offsets: readonly number[];
  lens: readonly number[];
  /** Floes that crack and sink now and then. */
  sinks?: readonly boolean[];
}

export const LANES: readonly LaneDef[] = [
  { row: 2, kind: "barge", speed: 36, period: 384, offsets: [0, 128, 256], lens: [64, 64, 64] },
  { row: 3, kind: "floe", speed: -44, period: 352, offsets: [0, 88, 176, 264], lens: [32, 32, 32, 32], sinks: [false, true, false, false] },
  { row: 4, kind: "barge", speed: 56, period: 448, offsets: [0, 224], lens: [96, 96] },
  { row: 5, kind: "floe", speed: -30, period: 384, offsets: [0, 128, 256], lens: [48, 48, 48], sinks: [false, false, true] },
  { row: 7, kind: "bus", speed: -32, period: 384, offsets: [0, 192], lens: [40, 40] },
  { row: 8, kind: "scooter", speed: 80, period: 384, offsets: [0, 192], lens: [16, 16] },
  { row: 9, kind: "van", speed: -44, period: 384, offsets: [0, 128, 256], lens: [24, 24, 24] },
  { row: 10, kind: "sweeper", speed: 30, period: 352, offsets: [0, 117, 234], lens: [16, 16, 16] },
];
const LANE_OF_ROW: readonly number[] = Array.from({ length: 16 }, (_, row) => LANES.findIndex((l) => l.row === row));

/** Floe sink cycle in seconds, and when (within it) a sinking floe cracks, is gone, and refreezes. */
const SINK_CYCLE = 6;
const SINK_CRACK = 3.5;
const SINK_GONE = 4.3;
const SINK_BACK = 5.4;

export type HopperPhase = "play" | "dying" | "levelup" | "over";
export type Direction = 0 | 1 | 2 | 3; // up, right, down, left
export type DeathKind = "crash" | "sink" | "drained";

export interface Hop { active: boolean; t: number; fromX: number; fromRow: number; toX: number; toRow: number }
interface Popup { active: boolean; x: number; y: number; t: number; value: number }

export interface HopperState {
  phase: HopperPhase;
  timer: number;
  /** Total seconds simulated; zero means the run has not started (attract screen). */
  elapsed: number;
  score: number;
  lives: number;
  level: number;
  /** The bot's centre x in pixels and its row. */
  x: number;
  row: number;
  facing: Direction;
  hop: Hop;
  /** A direction pressed during a hop, taken as soon as the bot lands; -1 for none. */
  queued: number;
  /** The highest row (smallest index) reached by this bot; new rows score. */
  bestRow: number;
  battery: number;
  pads: Uint8Array;
  parcelPad: number;
  parcelLeft: number;
  parcelTimer: number;
  /** Scroll of each lane's pattern, parallel to LANES. */
  shifts: number[];
  sinkClock: number;
  deathKind: DeathKind;
  particles: Particle[];
  popups: Popup[];
}

/** Lane speeds grow 15 % per level, up to double. */
export function levelFactor(level: number): number {
  return Math.min(2, 1 + 0.15 * (level - 1));
}

function mod(a: number, m: number): number {
  return ((a % m) + m) % m;
}

/** Left edge of item `i` of lane `lane` for a given scroll. */
export function itemX(lane: number, i: number, shift: number): number {
  const def = LANES[lane];
  return mod(def.offsets[i] + shift, def.period) - MARGIN;
}

/** 0 solid, 1 cracking (still rideable), 2 sunk. */
export function sinkState(lane: number, i: number, clock: number): 0 | 1 | 2 {
  if (!LANES[lane].sinks?.[i]) return 0;
  const t = mod(clock + i * 1.7, SINK_CYCLE);
  return t < SINK_CRACK ? 0 : t < SINK_GONE ? 1 : t < SINK_BACK ? 2 : 1;
}

/** Whether a bot centred at x on a canal row stands on something that floats. */
export function carrierAt(state: HopperState, row: number, x: number): boolean {
  const lane = LANE_OF_ROW[row];
  if (lane < 0) return false;
  const def = LANES[lane];
  for (let i = 0; i < def.offsets.length; i += 1) {
    const x0 = itemX(lane, i, state.shifts[lane]);
    if (x >= x0 + 1 && x <= x0 + def.lens[i] - 1 && sinkState(lane, i, state.sinkClock) !== 2) return true;
  }
  return false;
}

/** Whether a bot centred at x on a road row touches a vehicle. */
export function vehicleAt(state: HopperState, row: number, x: number): boolean {
  const lane = LANE_OF_ROW[row];
  if (lane < 0) return false;
  const def = LANES[lane];
  for (let i = 0; i < def.offsets.length; i += 1) {
    const x0 = itemX(lane, i, state.shifts[lane]);
    if (x + BOT_HALF > x0 + 1 && x - BOT_HALF < x0 + def.lens[i] - 1) return true;
  }
  return false;
}

export function isCanal(row: number): boolean {
  return row >= CANAL_TOP && row <= CANAL_BOTTOM;
}

function isRoad(row: number): boolean {
  return row >= ROAD_TOP && row <= ROAD_BOTTOM;
}

function respawn(state: HopperState): void {
  state.phase = "play";
  state.x = START_X;
  state.row = START_ROW;
  state.facing = 0;
  state.hop.active = false;
  state.queued = -1;
  state.bestRow = START_ROW;
  state.battery = BATTERY_TIME;
}

function create(random: () => number): HopperState {
  const state: HopperState = {
    phase: "play", timer: 0, elapsed: 0, score: 0, lives: 3, level: 1,
    x: START_X, row: START_ROW, facing: 0,
    hop: { active: false, t: 0, fromX: 0, fromRow: 0, toX: 0, toRow: 0 },
    queued: -1, bestRow: START_ROW, battery: BATTERY_TIME,
    pads: new Uint8Array(PAD_X.length), parcelPad: -1, parcelLeft: 0, parcelTimer: 7 + random() * 5,
    shifts: LANES.map((l) => Math.floor(random() * l.period)),
    sinkClock: 0, deathKind: "crash",
    particles: makeParticles(80),
    popups: Array.from({ length: 3 }, () => ({ active: false, x: 0, y: 0, t: 0, value: 0 })),
  };
  respawn(state);
  return state;
}

function popup(state: HopperState, x: number, y: number, value: number): void {
  const p = state.popups.find((q) => !q.active) ?? state.popups[0];
  p.active = true; p.x = x; p.y = y; p.t = 1.2; p.value = value;
}

function die(state: HopperState, kind: DeathKind, random: () => number): void {
  state.phase = "dying";
  state.timer = DEATH_S;
  state.deathKind = kind;
  state.lives = Math.max(0, state.lives - 1);
  state.hop.active = false;
  state.queued = -1;
  const cy = state.row * CELL + CELL / 2;
  if (kind === "sink") emitBurst(state.particles, state.x, cy, 16, 50, "#8ff5e8", random, 0.7);
  else emitBurst(state.particles, state.x, cy, 14, 45, "#ffc64a", random, 0.6);
}

function startHop(state: HopperState, dir: Direction): void {
  state.facing = dir;
  let toRow = state.row, toX = state.x;
  if (dir === 0) toRow = Math.max(HOME_ROW, state.row - 1);
  else if (dir === 2) toRow = Math.min(START_ROW, state.row + 1);
  else toX = state.x + (dir === 1 ? CELL : -CELL);
  // On land the bot stays on screen; on the canal the current may carry it off.
  if (!isCanal(state.row)) toX = clamp(toX, CELL / 2, WIDTH - CELL / 2);
  if (toRow === state.row && toX === state.x) return;
  const h = state.hop;
  h.active = true; h.t = 0; h.fromX = state.x; h.fromRow = state.row; h.toX = toX; h.toRow = toRow;
}

function pressedDirection(input: RetroInput): number {
  const p = input.pressed;
  return p.up ? 0 : p.right ? 1 : p.down ? 2 : p.left ? 3 : -1;
}

/** Arrive on the rooftop: light a pad (with any parcel bonus), or get zapped by the fence or a lit pad. */
function reachRoof(state: HopperState, random: () => number): void {
  const pad = PAD_X.findIndex((px) => Math.abs(state.x - px) <= PAD_CATCH);
  if (pad < 0 || state.pads[pad]) {
    die(state, "crash", random);
    return;
  }
  state.pads[pad] = 1;
  let points = PAD_POINTS + BATTERY_POINTS * Math.floor(state.battery);
  if (state.parcelPad === pad) {
    points += PARCEL_BONUS;
    state.parcelPad = -1;
    state.parcelTimer = 7 + random() * 6;
  }
  state.score += points;
  popup(state, PAD_X[pad], HOME_ROW * CELL + 2, points);
  emitBurst(state.particles, PAD_X[pad], HOME_ROW * CELL + 8, 12, 40, "#5ff0d0", random, 0.6);
  if (state.pads.every((b) => b === 1)) {
    state.score += LEVEL_POINTS;
    state.phase = "levelup";
    state.timer = LEVEL_S;
    state.hop.active = false;
    state.parcelPad = -1;
  } else {
    respawn(state);
  }
}

/** The bot sits on `row` at `x`: is it still running? Returns false after wrecking it. */
function survives(state: HopperState, random: () => number): boolean {
  if (isRoad(state.row) && vehicleAt(state, state.row, state.x)) {
    die(state, "crash", random);
    return false;
  }
  if (isCanal(state.row)) {
    if (state.x < 2 || state.x > WIDTH - 2 || !carrierAt(state, state.row, state.x)) {
      die(state, "sink", random);
      return false;
    }
  }
  return true;
}

function land(state: HopperState, random: () => number): void {
  const h = state.hop;
  h.active = false;
  state.x = h.toX;
  state.row = h.toRow;
  if (state.row < state.bestRow) {
    state.score += ROW_POINTS * (state.bestRow - state.row);
    state.bestRow = state.row;
  }
  if (state.row === HOME_ROW) {
    reachRoof(state, random);
    return;
  }
  if (!survives(state, random)) return;
  if (state.queued >= 0) {
    const dir = state.queued as Direction;
    state.queued = -1;
    startHop(state, dir);
  }
}

function laneSpeed(lane: number, level: number): number {
  return LANES[lane].speed * levelFactor(level);
}

function step(state: HopperState, input: RetroInput, dt: number, random: () => number): void {
  stepParticles(state.particles, dt, 30);
  if (state.phase === "over") return;
  state.elapsed += dt;
  state.sinkClock += dt;
  for (let i = 0; i < LANES.length; i += 1) state.shifts[i] = mod(state.shifts[i] + laneSpeed(i, state.level) * dt, LANES[i].period);
  for (const p of state.popups) if (p.active && (p.t -= dt) <= 0) p.active = false;

  if (state.phase === "dying") {
    state.timer -= dt;
    if (state.timer <= 0) {
      if (state.lives <= 0) state.phase = "over";
      else respawn(state);
    }
    return;
  }
  if (state.phase === "levelup") {
    state.timer -= dt;
    if (state.timer <= 0) {
      state.level += 1;
      state.pads.fill(0);
      state.parcelTimer = 7 + random() * 5;
      respawn(state);
    }
    return;
  }

  // A parcel waits on a dark pad now and then.
  if (state.parcelPad >= 0) {
    state.parcelLeft -= dt;
    if (state.parcelLeft <= 0) {
      state.parcelPad = -1;
      state.parcelTimer = 7 + random() * 6;
    }
  } else if ((state.parcelTimer -= dt) <= 0) {
    let dark = 0;
    for (const b of state.pads) if (!b) dark += 1;
    let pick = Math.floor(random() * dark);
    for (let i = 0; i < state.pads.length && dark > 0; i += 1) {
      if (!state.pads[i] && pick-- === 0) { state.parcelPad = i; state.parcelLeft = 5; }
    }
    state.parcelTimer = 7 + random() * 6;
  }

  state.battery -= dt;
  if (state.battery <= 0) {
    state.battery = 0;
    die(state, "drained", random);
    return;
  }

  const dir = pressedDirection(input);
  const h = state.hop;
  if (h.active) {
    if (dir >= 0) state.queued = dir;
    // A hop that starts on the canal keeps drifting with what it left.
    if (isCanal(h.fromRow)) {
      const drift = laneSpeed(LANE_OF_ROW[h.fromRow], state.level) * dt;
      h.fromX += drift;
      h.toX += drift;
    }
    h.t += dt;
    if (h.t >= HOP_S) land(state, random);
    return;
  }
  if (dir >= 0) {
    startHop(state, dir as Direction);
    if (h.active) return;
  }
  // Standing still: the canal carries the bot; traffic or water may end it.
  if (isCanal(state.row)) state.x += laneSpeed(LANE_OF_ROW[state.row], state.level) * dt;
  survives(state, random);
}

function status(state: HopperState): RetroStatus {
  return { score: state.score, lives: state.lives, level: state.level, over: state.phase === "over" };
}

// ---- Drawing --------------------------------------------------------------

/** Rotate a square bitmap a quarter turn clockwise `turns` times. */
function rotateRows(rows: readonly string[], turns: number): string[] {
  let out = rows.slice();
  for (let t = 0; t < turns; t += 1) {
    const n = out.length;
    const next: string[] = [];
    for (let y = 0; y < n; y += 1) {
      let line = "";
      for (let x = 0; x < n; x += 1) line += out[n - 1 - x][y];
      next.push(line);
    }
    out = next;
  }
  return out;
}

/** The courier bot seen from above, facing up: two treads, a sensor bar at the front, a parcel bay. */
const BOT_BODY = [
  "....#..#....",
  "...######...",
  "..#......#..",
  "##.######.##",
  "##.######.##",
  "##.##..##.##",
  "##.##..##.##",
  "##.######.##",
  "##.######.##",
  "##.######.##",
  "...######...",
  "............",
];
/** The same with the treads mid-roll, for a hop. */
const BOT_ROLL = [
  "....#..#....",
  "...######...",
  "#.#......#.#",
  ".#.######.#.",
  "#..######..#",
  ".#.##..##.#.",
  "#..##..##..#",
  ".#.######.#.",
  "#..######..#",
  ".#.######.#.",
  "...######...",
  "............",
];
const BOT_VISOR = [
  "............", "............", "...######...", "............", "............", "............",
  "............", "............", "............", "............", "............", "............",
];
const BOT_PARCEL = [
  "............", "............", "............", "............", "............", ".....##.....",
  ".....##.....", "............", "............", "............", "............", "............",
];
const turned = (rows: readonly string[]) => [0, 1, 2, 3].map((t) => sprite(rotateRows(rows, t)));
/** [direction] for each layer. */
const BOT: readonly PixelSprite[] = turned(BOT_BODY);
const BOT_HOP: readonly PixelSprite[] = turned(BOT_ROLL);
const VISOR: readonly PixelSprite[] = turned(BOT_VISOR);
const PARCEL: readonly PixelSprite[] = turned(BOT_PARCEL);
const WRECK = sprite(["#..#....#..#", ".##..##..##.", "..#.####.#..", "#.##....##.#", "..#.####.#..", ".##..##..##.", "#..#....#..#"]);
const PARCEL_BOX = sprite(["######", "#.##.#", "######", "######"]);
const LIFE_ICON = sprite([".####.", "#....#", "######", "#.##.#"]);

const BANK_ROWS = [QUAY_ROW, START_ROW] as const;

/** Lane scroll used for drawing: on the attract screen the world drifts on its own. */
function drawShift(state: HopperState, lane: number, attract: boolean, time: number): number {
  return attract ? state.shifts[lane] + LANES[lane].speed * time : state.shifts[lane];
}

function drawVehicle(ctx: CanvasRenderingContext2D, kind: LaneKind, x: number, y: number, len: number, flip: boolean): void {
  const front = flip ? x : x + len - 3;
  if (kind === "bus") {
    ctx.fillStyle = "#3a3f52";
    ctx.fillRect(x + 1, y + 2, len - 2, 12);
    ctx.fillStyle = "#e0a93b";
    ctx.fillRect(x + 1, y + 7, len - 2, 2);
    ctx.fillStyle = "#9fd7e8";
    for (let w = x + 4; w < x + len - 6; w += 7) ctx.fillRect(w, y + 4, 4, 2);
  } else if (kind === "van") {
    ctx.fillStyle = "#c7c2b4";
    ctx.fillRect(x + 1, y + 3, len - 2, 10);
    ctx.fillStyle = "#2f6f73";
    ctx.fillRect(flip ? x + 1 : x + len - 8, y + 3, 7, 10);
  } else if (kind === "scooter") {
    ctx.fillStyle = "#e85d9a";
    ctx.fillRect(x + 2, y + 6, len - 4, 4);
    ctx.fillStyle = "#f2efe6";
    ctx.fillRect(x + 6, y + 4, 4, 8);
  } else {
    ctx.fillStyle = "#7d8a3a";
    ctx.fillRect(x + 2, y + 3, len - 4, 10);
    ctx.fillStyle = "#c9d46a";
    // The spinning brush underneath.
    ctx.fillRect(flip ? x + len - 3 : x, y + 2, 3, 12);
  }
  ctx.fillStyle = "#fff4c8";
  ctx.fillRect(front, y + 4, 3, 1);
  ctx.fillRect(front, y + 11, 3, 1);
}

function drawCarrier(ctx: CanvasRenderingContext2D, def: LaneDef, lane: number, i: number, x: number, y: number, len: number, clock: number): void {
  if (def.kind === "barge") {
    ctx.fillStyle = "#4a4d5a";
    ctx.fillRect(x + 2, y + 2, len - 4, 12);
    ctx.fillStyle = "#6c7082";
    ctx.fillRect(x + 2, y + 2, len - 4, 2);
    ctx.fillStyle = "#c9a227";
    ctx.fillRect(x + 6, y + 8, len - 12, 1);
    // Hover glow under the hull and running lights at both ends.
    ctx.fillStyle = "#5ff0d0";
    ctx.fillRect(x + 4, y + 14, len - 8, 1);
    ctx.fillRect(x + 2, y + 6, 1, 4);
    ctx.fillRect(x + len - 3, y + 6, 1, 4);
    return;
  }
  const sink = sinkState(lane, i, clock);
  for (let t = 0; t < len; t += CELL) {
    const tx = x + t;
    if (sink === 2) {
      ctx.fillStyle = "#2c8a86";
      ctx.fillRect(tx + 3, y + 4, 10, 1);
      ctx.fillRect(tx + 3, y + 11, 10, 1);
      continue;
    }
    ctx.fillStyle = sink === 1 ? "#8fb8c2" : "#dff5fa";
    ctx.fillRect(tx + 1, y + 2, 14, 12);
    ctx.fillStyle = sink === 1 ? "#5c8590" : "#b4dbe6";
    ctx.fillRect(tx + 1, y + 11, 14, 3);
    if (sink === 1) {
      ctx.fillStyle = "#2f5560";
      ctx.fillRect(tx + 4, y + 3, 1, 4);
      ctx.fillRect(tx + 5, y + 7, 4, 1);
      ctx.fillRect(tx + 9, y + 7, 1, 5);
    }
  }
}

function drawRoof(ctx: CanvasRenderingContext2D, state: HopperState, info: RetroDrawInfo): void {
  const y = HOME_ROW * CELL;
  ctx.fillStyle = "#232329";
  ctx.fillRect(0, y - 2, WIDTH, CELL + 2);
  // The live fence: a dashed gold line that hums between the pads.
  const hum = info.reduced ? 0 : Math.floor(info.time * 8) % 2;
  ctx.fillStyle = "#8a6d1e";
  for (let x = hum; x < WIDTH; x += 3) ctx.fillRect(x, y + 7, 2, 1);
  for (let i = 0; i < PAD_X.length; i += 1) {
    const cx = PAD_X[i];
    ctx.fillStyle = "#232329";
    ctx.fillRect(cx - 11, y, 22, CELL);
    ctx.strokeStyle = state.pads[i] ? "#5ff0d0" : "#c9a227";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.arc(cx, y + 8, 7, 0, Math.PI * 2);
    ctx.stroke();
    if (state.pads[i]) {
      ctx.fillStyle = "#5ff0d0";
      ctx.fillRect(cx - 3, y + 5, 6, 6);
    } else if (state.parcelPad === i) {
      ctx.fillStyle = "#e0a93b";
      const bob = info.reduced ? 0 : Math.floor(info.time * 4) % 2;
      drawSprite(ctx, PARCEL_BOX, cx - 3, y + 6 - bob);
    }
  }
}

function draw(ctx: CanvasRenderingContext2D, state: HopperState, info: RetroDrawInfo): void {
  const attract = info.idle && state.elapsed === 0;
  const clock = attract ? info.time : state.sinkClock;
  const motion = info.reduced ? 0 : info.time;

  ctx.fillStyle = "#0d0d12";
  ctx.fillRect(0, 0, WIDTH, HEIGHT);

  // The canal with drifting ripples.
  ctx.fillStyle = "#0b3a40";
  ctx.fillRect(0, CANAL_TOP * CELL, WIDTH, (CANAL_BOTTOM - CANAL_TOP + 1) * CELL);
  ctx.fillStyle = "#1f6f73";
  for (let row = CANAL_TOP; row <= CANAL_BOTTOM; row += 1) {
    const drift = Math.floor(mod(motion * 5 + row * 11, 24));
    for (let x = -24 + drift; x < WIDTH; x += 24) ctx.fillRect(x, row * CELL + 4 + (row % 2) * 7, 4, 1);
  }

  drawRoof(ctx, state, info);

  // The quay and the street pavement: warm paving slabs.
  for (const row of BANK_ROWS) {
    ctx.fillStyle = "#3a2f22";
    ctx.fillRect(0, row * CELL, WIDTH, CELL);
    ctx.fillStyle = "#4f402c";
    for (let x = 0; x < WIDTH; x += 16) ctx.fillRect(x + (row % 2) * 8, row * CELL + 1, 7, 6);
    for (let x = 0; x < WIDTH; x += 16) ctx.fillRect(x + 8 - (row % 2) * 8, row * CELL + 9, 7, 6);
  }

  // The road with gold lane markings.
  ctx.fillStyle = "#16161a";
  ctx.fillRect(0, ROAD_TOP * CELL, WIDTH, (ROAD_BOTTOM - ROAD_TOP + 1) * CELL);
  ctx.fillStyle = "#6e5a1c";
  for (let row = ROAD_TOP + 1; row <= ROAD_BOTTOM; row += 1) {
    for (let x = 2; x < WIDTH; x += 12) ctx.fillRect(x, row * CELL, 4, 1);
  }

  // Lane contents.
  for (let lane = 0; lane < LANES.length; lane += 1) {
    const def = LANES[lane];
    const shift = drawShift(state, lane, attract, info.time);
    const y = def.row * CELL;
    for (let i = 0; i < def.offsets.length; i += 1) {
      const x = Math.round(itemX(lane, i, shift));
      const len = def.lens[i];
      if (x >= WIDTH || x + len <= 0) continue;
      if (isCanal(def.row)) drawCarrier(ctx, def, lane, i, x, y, len, clock);
      else drawVehicle(ctx, def.kind, x, y, len, def.speed < 0);
    }
  }

  // The bot, or what is left of it.
  if (state.phase === "dying") {
    const cy = state.row * CELL;
    if (state.deathKind === "sink") {
      ctx.strokeStyle = "#8ff5e8";
      ctx.lineWidth = 1;
      const grow = clamp(1 - state.timer / DEATH_S, 0, 1);
      ctx.strokeRect(Math.round(state.x - 3 - grow * 6) + 0.5, Math.round(cy + 5 - grow * 3) + 0.5, Math.round(6 + grow * 12), Math.round(6 + grow * 6));
    } else {
      ctx.fillStyle = state.deathKind === "drained" ? "#6b6b78" : "#ffc64a";
      drawSprite(ctx, WRECK, state.x - 6, cy + 4);
    }
  } else if (state.phase === "play") {
    const h = state.hop;
    let bx = state.x, by = state.row * CELL, rolling = false;
    if (h.active) {
      const k = clamp(h.t / HOP_S, 0, 1);
      bx = h.fromX + (h.toX - h.fromX) * k;
      by = (h.fromRow + (h.toRow - h.fromRow) * k) * CELL - (info.reduced ? 0 : Math.sin(k * Math.PI) * 3);
      rolling = true;
    }
    ctx.fillStyle = "#050507";
    ctx.fillRect(Math.round(bx) - 4, state.row * CELL + 13, 8, 1);
    ctx.fillStyle = "#d8dce6";
    drawSprite(ctx, (rolling ? BOT_HOP : BOT)[state.facing], bx - 6, by + 2);
    ctx.fillStyle = "#5ff0d0";
    drawSprite(ctx, VISOR[state.facing], bx - 6, by + 2);
    ctx.fillStyle = "#e0a93b";
    drawSprite(ctx, PARCEL[state.facing], bx - 6, by + 2);
  }
  drawParticles(ctx, state.particles);

  ctx.fillStyle = "#5ff0d0";
  for (const p of state.popups) {
    if (p.active) drawNumber(ctx, p.value, p.x, p.y - (info.reduced ? 0 : (1.2 - p.t) * 6), 1, "center");
  }

  // Top: score and level. Bottom: spare bots and the battery.
  ctx.fillStyle = "#f2efe6";
  drawNumber(ctx, state.score, 6, 4, 2);
  ctx.fillStyle = "#e0a93b";
  drawNumber(ctx, state.level, WIDTH - 6, 4, 2, "right");
  ctx.fillStyle = "#d8dce6";
  for (let i = 0; i < Math.min(state.lives, 6); i += 1) drawSprite(ctx, LIFE_ICON, 6 + i * 9, 12 * CELL + 6);
  const frac = clamp(state.battery / BATTERY_TIME, 0, 1);
  const low = state.battery < 10;
  const barX = 40, barW = WIDTH - 52, barY = 13 * CELL + 3;
  // A battery outline with a nub; the charge drains from the right.
  ctx.fillStyle = "#3a3a44";
  ctx.fillRect(barX - 1, barY - 1, barW + 2, 9);
  ctx.fillRect(barX + barW + 1, barY + 2, 2, 3);
  ctx.fillStyle = "#0d0d12";
  ctx.fillRect(barX, barY, barW, 7);
  // The charge turns red when it runs low; it pulses only without reduced motion.
  ctx.globalAlpha = low && !info.reduced && state.phase === "play" ? 0.65 + 0.35 * Math.sin(info.time * 6) : 1;
  ctx.fillStyle = low ? "#ff5a4a" : "#5ff0d0";
  for (let x = 0; x < Math.round(barW * frac); x += 4) ctx.fillRect(barX + 1 + x, barY + 1, Math.min(3, Math.round(barW * frac) - x), 5);
  ctx.globalAlpha = 1;
  ctx.fillStyle = low ? "#ff5a4a" : "#e0a93b";
  drawNumber(ctx, Math.ceil(state.battery), 6, barY - 1, 2);

  if (state.phase === "levelup") {
    ctx.fillStyle = "#e0a93b";
    drawNumber(ctx, state.level + 1, WIDTH / 2, QUAY_ROW * CELL + 1, 3, "center");
  }
}

const roadHopper: RetroGame<HopperState> = {
  id: "road-hopper",
  width: WIDTH,
  height: HEIGHT,
  create,
  step,
  draw,
  status,
};

export default roadHopper;
