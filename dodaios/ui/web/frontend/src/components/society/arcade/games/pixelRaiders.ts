/**
 * "Pixel Raiders": a staggered swarm of four rows sways from side to side on
 * a smooth wave, sinking a few pixels at the end of every sweep. The fewer
 * raiders are left, the wider and faster the swarm sweeps. Raiders on the
 * swarm's front line shoot back (some aimed at the fighter, some at random).
 *
 * The fighter is covered by one long energy barrier of short segments. The
 * barrier is one-way: the fighter's own shots pass through it, raider shots
 * drain a segment, and a drained segment slowly recharges. Now and then a
 * courier drone zigzags across the top; shooting it drops a capsule that
 * gives rapid fire for a while. Raider points grow with every wave. Clearing
 * the swarm brings the next one, starting lower and sweeping faster; the
 * swarm reaching the fighter ends the run.
 */
import type { RetroDrawInfo, RetroGame, RetroInput, RetroStatus } from "../retroGame";
import {
  clamp, drawNumber, drawParticles, drawSprite, drawStars, emitBurst, makeParticles, sprite, starField, stepParticles,
  type Particle, type PixelSprite,
} from "./games3Kit";

export const WIDTH = 256;
export const HEIGHT = 240;

export const COLS = 9;
export const ROWS = 4;
export const CELL_W = 22;
export const CELL_H = 18;
/** Odd rows sit half a cell to the right, so the swarm is a staggered lattice. */
export const STAGGER = CELL_W / 2;
const ALIEN_H = 8;
/** Pixels the swarm sinks at the end of each sweep. */
export const SINK_Y = 6;
const SINK_SPEED = 30;
/** The swarm's living edge never comes closer than this to a side wall. */
export const EDGE_MARGIN = 6;

/** Which raider kind each row holds (top to bottom), their widths and base points. */
const ROW_KIND = [0, 1, 2, 2] as const;
const KIND_W = [11, 13, 9] as const;
export const KIND_POINTS = [40, 25, 15] as const;
/** Extra points per raider for every wave survived, up to WAVE_BONUS_CAP waves. */
export const WAVE_BONUS = 5;
const WAVE_BONUS_CAP = 6;
const KIND_COLOR = ["#ffb547", "#ff6b5a", "#9d7bff"] as const;

export const PLAYER_Y = 210;
export const PLAYER_W = 11;
const PLAYER_H = 9;
const PLAYER_SPEED = 95;
const PLAYER_START_X = Math.round((WIDTH - PLAYER_W) / 2);
export const MAX_SHOTS = 2;
const RAPID_SHOTS = 3;
const SHOT_SPEED = 250;
const SHOT_COOLDOWN = 0.34;
const RAPID_COOLDOWN = 0.14;
const GROUND_Y = 226;

export const MAX_BOMBS = 6;

/** The energy barrier: one row of short segments with small gaps, each with a few charge points. */
export const SEGMENTS = 22;
export const SEG_W = 9;
const SEG_GAP = 2;
export const SEG_HP = 3;
export const BARRIER_Y = 182;
const BARRIER_H = 3;
export const BARRIER_X = Math.round((WIDTH - (SEGMENTS * (SEG_W + SEG_GAP) - SEG_GAP)) / 2);
/** Seconds for a drained segment to win back one charge point. */
export const RECHARGE_S = 4;

const COURIER_W = 12;
const COURIER_H = 7;
const COURIER_Y = 24;
const COURIER_SPEED = 44;
export const COURIER_POINTS = 80;
const CAPSULE_SPEED = 46;
/** Seconds of rapid fire a caught capsule gives. */
export const RAPID_S = 8;

const DEATH_S = 1.4;
const CLEAR_S = 1.6;
const EXTRA_LIFE_EVERY = 2500;
const MAX_LIVES = 5;

/** Two animation frames per raider kind: a faceted prism, a split-wing glider and a spore orb. */
const ALIEN_SPRITES: readonly (readonly [PixelSprite, PixelSprite])[] = [
  [
    sprite(["....###....", "...#####...", "..##.#.##..", ".####.####.", "###.###.###", ".####.####.", "..##.#.##..", "....###...."]),
    sprite(["....###....", "...##.##...", "..#######..", ".###.#.###.", "####.#.####", ".###.#.###.", "..#######..", "....###...."]),
  ],
  [
    sprite(["##.........##", ".##.......##.", "..##.###.##..", "...#######...", "..####.####..", ".##..###..##.", "##....#....##", "............."]),
    sprite(["............#", "#.........##.", ".##.###.##...", "..#########..", "..####.####..", "...#.###.#...", "..##..#..##..", ".##.......##."]),
  ],
  [
    sprite(["..#####..", ".##...##.", "##.###.##", "#.#####.#", "##.###.##", ".##...##.", "..#####..", "....#...."]),
    sprite(["..#####..", ".#######.", "##.....##", "#..###..#", "##.....##", ".#######.", "..#####..", "...#.#..."]),
  ],
];
const BURST_SPRITE = sprite(["..#...#..", "#..#.#..#", ".#.....#.", "...#.#...", ".#.....#.", "#..#.#..#", "..#...#.."]);
const PLAYER_SPRITE = sprite([
  ".....#.....",
  "....###....",
  "....#.#....",
  "...##.##...",
  "#..#####..#",
  "##.#####.##",
  "###########",
  ".##..#..##.",
  ".#.......#.",
]);
const WRECK_SPRITES = [
  sprite(["..#...#....", ".....#..#..", "#..#.#.....", "...##.##.#.", "#..#.###...", "##.#.#.#.##", "#.#####.###", ".#...#..#..", ".#.......#."]),
  sprite(["#....#...#.", "...#....#..", "..#.#.#....", ".#.#..##...", "...###.#..#", "##..###.#.#", "####.######", "..#..#..#..", "#.......#.."]),
];
const COURIER_SPRITE = sprite([
  "..########..",
  ".#..#..#..#.",
  "############",
  "#.##.##.##.#",
  "############",
  ".#........#.",
  "#..........#",
]);
const CAPSULE_SPRITE = sprite([".##.", "####", "#..#", "####", ".##."]);
const LIFE_SPRITE = sprite(["..#..", ".###.", "#####", "#.#.#"]);

export type RaidersPhase = "play" | "dying" | "clear" | "over";

export interface Shot { active: boolean; x: number; y: number }
/** A raider shot. `kind` 0 straight, 1 zigzag (aimed), 2 fast dart. */
export interface Bomb { active: boolean; x: number; y: number; kind: number; speed: number }
interface Burst { active: boolean; x: number; y: number; t: number; color: string }
interface Popup { active: boolean; x: number; y: number; t: number; value: number }

export interface RaidersState {
  phase: RaidersPhase;
  /** Seconds left in a dying / clear phase. */
  timer: number;
  /** Total seconds simulated; zero means the run has not started (attract screen). */
  elapsed: number;
  score: number;
  lives: number;
  wave: number;
  nextLifeAt: number;
  px: number;
  cooldown: number;
  /** Seconds of rapid fire left (from a caught capsule). */
  rapid: number;
  shots: Shot[];
  bombs: Bomb[];
  /** One flag per raider, row-major (ROWS × COLS). */
  alive: Uint8Array;
  aliveCount: number;
  /** Top-left of the swarm's lattice (row 0, column 0), and the depth it is sinking to. */
  fx: number;
  fy: number;
  targetFy: number;
  /** The sway's angle in radians; each half turn is one sweep. */
  sway: number;
  frame: 0 | 1;
  fireTimer: number;
  /** Charge points per barrier segment, and each segment's recharge clock. */
  barrier: Uint8Array;
  recharge: Float32Array;
  courier: { active: boolean; x: number; y: number; dir: 1 | -1 };
  courierTimer: number;
  capsule: { active: boolean; x: number; y: number };
  bursts: Burst[];
  popups: Popup[];
  particles: Particle[];
  shake: number;
}

/** How fast the swarm sweeps (radians per second): calm when full, frantic with one raider left, faster each wave. */
export function swayRate(alive: number, wave: number): number {
  const fill = clamp((alive - 1) / (ROWS * COLS - 1), 0, 1);
  return (0.9 + 5.2 * (1 - fill) * (1 - fill)) * Math.min(1.6, 1 + 0.08 * (wave - 1));
}

/** The swarm's top edge at the start of a wave: each wave starts lower, up to a limit. */
export function waveStartY(wave: number): number {
  return 38 + Math.min(wave - 1, 6) * 8;
}

/** What one raider of `kind` is worth in `wave`. */
export function alienPoints(kind: number, wave: number): number {
  return KIND_POINTS[kind] + WAVE_BONUS * Math.min(wave - 1, WAVE_BONUS_CAP);
}

function maxBombs(wave: number): number {
  return Math.min(MAX_BOMBS, 2 + Math.floor(wave / 2));
}

export function segmentX(seg: number): number {
  return BARRIER_X + seg * (SEG_W + SEG_GAP);
}

/** Charge points left in the whole barrier (tests and balance). */
export function barrierCharge(state: RaidersState): number {
  let n = 0;
  for (let i = 0; i < SEGMENTS; i += 1) n += state.barrier[i];
  return n;
}

/** Left pixel of the raider at (row, col), relative to the swarm's origin. */
function localX(row: number, col: number): number {
  return col * CELL_W + (row % 2) * STAGGER + (CELL_W - KIND_W[ROW_KIND[row]]) / 2;
}

/** Left pixel of the raider at (row, col). */
export function alienX(state: RaidersState, row: number, col: number): number {
  return state.fx + localX(row, col);
}

export function alienY(state: RaidersState, row: number): number {
  return state.fy + row * CELL_H;
}

/** Bounds of the living swarm relative to its origin: [left, right, maxRow]; false when it is empty. */
function swarmBounds(state: RaidersState, out: number[]): boolean {
  let left = Infinity, right = -Infinity, maxRow = -1;
  for (let r = 0; r < ROWS; r += 1) {
    for (let c = 0; c < COLS; c += 1) {
      if (!state.alive[r * COLS + c]) continue;
      const x = localX(r, c);
      if (x < left) left = x;
      if (x + KIND_W[ROW_KIND[r]] > right) right = x + KIND_W[ROW_KIND[r]];
      if (r > maxRow) maxRow = r;
    }
  }
  out[0] = left; out[1] = right; out[2] = maxRow;
  return maxRow >= 0;
}
const bounds = [0, 0, 0];

/** Where the swarm's origin wants to be at the current sway: centred, swinging as wide as the walls allow. */
function swayTargetX(state: RaidersState): number {
  if (!swarmBounds(state, bounds)) return state.fx;
  const [left, right] = bounds;
  const reach = Math.max(0, (WIDTH - 2 * EDGE_MARGIN - (right - left)) / 2);
  return WIDTH / 2 - (left + right) / 2 + reach * Math.sin(state.sway);
}

function startWave(state: RaidersState, random: () => number): void {
  state.alive.fill(1);
  state.aliveCount = ROWS * COLS;
  state.sway = 0;
  state.fx = 0;
  state.fx = swayTargetX(state);
  state.fy = waveStartY(state.wave);
  state.targetFy = state.fy;
  state.frame = 0;
  state.fireTimer = 1.2 + random();
  for (const s of state.shots) s.active = false;
  for (const b of state.bombs) b.active = false;
  state.barrier.fill(SEG_HP);
  state.recharge.fill(0);
  state.courier.active = false;
  state.capsule.active = false;
  state.courierTimer = 12 + random() * 10;
}

function create(random: () => number): RaidersState {
  const state: RaidersState = {
    phase: "play", timer: 0, elapsed: 0, score: 0, lives: 3, wave: 1, nextLifeAt: EXTRA_LIFE_EVERY,
    px: PLAYER_START_X, cooldown: 0, rapid: 0,
    shots: Array.from({ length: RAPID_SHOTS }, () => ({ active: false, x: 0, y: 0 })),
    bombs: Array.from({ length: MAX_BOMBS }, () => ({ active: false, x: 0, y: 0, kind: 0, speed: 0 })),
    alive: new Uint8Array(ROWS * COLS), aliveCount: 0,
    fx: 0, fy: 0, targetFy: 0, sway: 0, frame: 0, fireTimer: 0,
    barrier: new Uint8Array(SEGMENTS), recharge: new Float32Array(SEGMENTS),
    courier: { active: false, x: 0, y: COURIER_Y, dir: 1 }, courierTimer: 0,
    capsule: { active: false, x: 0, y: 0 },
    bursts: Array.from({ length: 8 }, () => ({ active: false, x: 0, y: 0, t: 0, color: "#fff" })),
    popups: Array.from({ length: 3 }, () => ({ active: false, x: 0, y: 0, t: 0, value: 0 })),
    particles: makeParticles(120),
    shake: 0,
  };
  startWave(state, random);
  return state;
}

function addScore(state: RaidersState, points: number): void {
  state.score += points;
  if (state.score >= state.nextLifeAt) {
    state.nextLifeAt += EXTRA_LIFE_EVERY;
    state.lives = Math.min(MAX_LIVES, state.lives + 1);
  }
}

function spawnBurst(state: RaidersState, x: number, y: number, color: string): void {
  const slot = state.bursts.find((b) => !b.active) ?? state.bursts[0];
  slot.active = true; slot.x = x; slot.y = y; slot.t = 0.2; slot.color = color;
}

function popup(state: RaidersState, x: number, y: number, value: number): void {
  const p = state.popups.find((q) => !q.active) ?? state.popups[0];
  p.active = true; p.x = x; p.y = y; p.t = 1.2; p.value = value;
}

/** The barrier segment under x, or -1 for a gap or outside the barrier. */
function segmentAt(x: number): number {
  const rel = x - BARRIER_X;
  if (rel < 0) return -1;
  const seg = Math.floor(rel / (SEG_W + SEG_GAP));
  if (seg >= SEGMENTS || rel - seg * (SEG_W + SEG_GAP) >= SEG_W) return -1;
  return seg;
}

/** A raider shot at (x, y) hits a charged segment: drain it and report the hit. */
function hitBarrier(state: RaidersState, x: number, y: number, random: () => number): boolean {
  if (y < BARRIER_Y || y >= BARRIER_Y + BARRIER_H) return false;
  const seg = segmentAt(x);
  if (seg < 0 || state.barrier[seg] === 0) return false;
  state.barrier[seg] -= 1;
  state.recharge[seg] = 0;
  emitBurst(state.particles, x, BARRIER_Y, 5, 30, "#4fb3ff", random, 0.3);
  return true;
}

function killAlien(state: RaidersState, row: number, col: number, random: () => number): void {
  state.alive[row * COLS + col] = 0;
  state.aliveCount -= 1;
  const kind = ROW_KIND[row];
  addScore(state, alienPoints(kind, state.wave));
  const x = alienX(state, row, col), y = alienY(state, row);
  spawnBurst(state, x + KIND_W[kind] / 2, y + ALIEN_H / 2, KIND_COLOR[kind]);
  emitBurst(state.particles, x + KIND_W[kind] / 2, y + ALIEN_H / 2, 10, 70, KIND_COLOR[kind], random, 0.45);
  if (state.aliveCount === 0) {
    state.phase = "clear";
    state.timer = CLEAR_S;
    for (const b of state.bombs) b.active = false;
    state.courier.active = false;
  }
}

/** The raider hit by a point, as row * COLS + col, or -1. */
function alienAt(state: RaidersState, x: number, y: number): number {
  const row = Math.floor((y - state.fy) / CELL_H);
  if (row < 0 || row >= ROWS) return -1;
  const col = Math.floor((x - state.fx - (row % 2) * STAGGER) / CELL_W);
  if (col < 0 || col >= COLS || !state.alive[row * COLS + col]) return -1;
  const ax = alienX(state, row, col), ay = alienY(state, row);
  return x >= ax && x < ax + KIND_W[ROW_KIND[row]] && y >= ay && y < ay + ALIEN_H ? row * COLS + col : -1;
}

function killPlayer(state: RaidersState, random: () => number): void {
  state.phase = "dying";
  state.timer = DEATH_S;
  state.lives = Math.max(0, state.lives - 1);
  state.shake = 0.4;
  state.rapid = 0;
  for (const b of state.bombs) b.active = false;
  for (const s of state.shots) s.active = false;
  state.capsule.active = false;
  emitBurst(state.particles, state.px + PLAYER_W / 2, PLAYER_Y + 4, 28, 90, "#f2c14e", random, 0.9);
  emitBurst(state.particles, state.px + PLAYER_W / 2, PLAYER_Y + 4, 14, 60, "#ffffff", random, 0.6);
}

/**
 * Move the swarm by `dt`: advance the sway, follow it sideways, sink at the
 * end of every sweep, burn through barrier segments it reaches, and end the
 * run when it reaches the fighter.
 */
export function swaySwarm(state: RaidersState, dt: number, random: () => number): void {
  if (state.aliveCount <= 0) return;
  const rate = swayRate(state.aliveCount, state.wave);
  const before = Math.floor(state.sway / Math.PI);
  state.sway += rate * dt;
  if (Math.floor(state.sway / Math.PI) > before) state.targetFy += SINK_Y;
  state.frame = Math.floor(state.sway / (Math.PI / 4)) % 2 === 0 ? 0 : 1;
  // Follow the sway; a sudden change of reach (an outer column falls) is eased in, never jumped.
  const target = swayTargetX(state);
  const maxMove = Math.max(70, rate * WIDTH * 0.6) * dt;
  state.fx += clamp(target - state.fx, -maxMove, maxMove);
  state.fy = Math.min(state.targetFy, state.fy + SINK_SPEED * dt);

  swarmBounds(state, bounds);
  const bottom = state.fy + bounds[2] * CELL_H + ALIEN_H;
  if (bottom > BARRIER_Y) {
    // Raiders grind through every segment they sink into.
    for (let r = 0; r <= bounds[2]; r += 1) {
      if (alienY(state, r) + ALIEN_H <= BARRIER_Y) continue;
      for (let c = 0; c < COLS; c += 1) {
        if (!state.alive[r * COLS + c]) continue;
        const ax = alienX(state, r, c);
        for (let x = ax; x < ax + KIND_W[ROW_KIND[r]]; x += 2) {
          const seg = segmentAt(x);
          if (seg >= 0) { state.barrier[seg] = 0; state.recharge[seg] = 0; }
        }
      }
    }
  }
  if (bottom >= PLAYER_Y && state.phase === "play") {
    // The swarm has landed: the run is over no matter how many lives are left.
    killPlayer(state, random);
    state.lives = 0;
  }
}

/** A raider on the swarm's front line: nothing living below it that would catch its shot. */
function frontLine(state: RaidersState, row: number, col: number): boolean {
  const cx = localX(row, col) + KIND_W[ROW_KIND[row]] / 2;
  for (let r = row + 1; r < ROWS; r += 1) {
    for (let c = 0; c < COLS; c += 1) {
      if (!state.alive[r * COLS + c]) continue;
      const x = localX(r, c);
      if (cx >= x - 1 && cx <= x + KIND_W[ROW_KIND[r]] + 1) return false;
    }
  }
  return true;
}

/** Fire a raider shot: from the front-line raider nearest the fighter, or from a random one. */
function alienFire(state: RaidersState, random: () => number): void {
  let active = 0;
  for (const b of state.bombs) if (b.active) active += 1;
  if (active >= maxBombs(state.wave)) return;
  const aimed = random() < 0.45;
  const target = state.px + PLAYER_W / 2;
  let pick = -1, best = Infinity, count = 0;
  for (let i = 0; i < ROWS * COLS; i += 1) {
    if (!state.alive[i] || !frontLine(state, Math.floor(i / COLS), i % COLS)) continue;
    count += 1;
    if (aimed) {
      const r = Math.floor(i / COLS);
      const d = Math.abs(alienX(state, r, i % COLS) + KIND_W[ROW_KIND[r]] / 2 - target);
      if (d < best) { best = d; pick = i; }
    }
  }
  if (!aimed && count > 0) {
    let n = Math.floor(random() * count);
    for (let i = 0; i < ROWS * COLS && pick < 0; i += 1) {
      if (state.alive[i] && frontLine(state, Math.floor(i / COLS), i % COLS) && n-- === 0) pick = i;
    }
  }
  const bomb = state.bombs.find((b) => !b.active);
  if (!bomb || pick < 0) return;
  const row = Math.floor(pick / COLS);
  bomb.active = true;
  bomb.x = Math.round(alienX(state, row, pick % COLS) + KIND_W[ROW_KIND[row]] / 2);
  bomb.y = alienY(state, row) + ALIEN_H;
  bomb.kind = aimed ? 1 : random() < 0.3 ? 2 : 0;
  bomb.speed = 70 + 6 * Math.min(state.wave, 8) + (bomb.kind === 2 ? 30 : 0);
}

function stepShots(state: RaidersState, dt: number, random: () => number): void {
  for (const shot of state.shots) {
    if (!shot.active) continue;
    // Move in 2-pixel steps so a fast shot never skips over a raider.
    const steps = Math.max(1, Math.ceil((SHOT_SPEED * dt) / 2));
    const stepLen = (SHOT_SPEED * dt) / steps;
    for (let i = 0; i < steps && shot.active; i += 1) {
      shot.y -= stepLen;
      if (shot.y < 12) { shot.active = false; break; }
      const hit = alienAt(state, shot.x, shot.y);
      if (hit >= 0) {
        shot.active = false;
        killAlien(state, Math.floor(hit / COLS), hit % COLS, random);
        break;
      }
      const k = state.courier;
      if (k.active && shot.x >= k.x && shot.x < k.x + COURIER_W && shot.y >= k.y && shot.y < k.y + COURIER_H) {
        shot.active = false;
        k.active = false;
        addScore(state, COURIER_POINTS);
        popup(state, k.x + COURIER_W / 2, k.y, COURIER_POINTS);
        emitBurst(state.particles, k.x + COURIER_W / 2, k.y + 3, 18, 80, "#5ee0c8", random, 0.6);
        const cap = state.capsule;
        cap.active = true; cap.x = Math.round(k.x + COURIER_W / 2 - 2); cap.y = k.y + COURIER_H;
        break;
      }
      for (const b of state.bombs) {
        if (b.active && Math.abs(b.x - shot.x) <= 1.5 && shot.y >= b.y - 1 && shot.y <= b.y + 7) {
          b.active = false;
          shot.active = false;
          emitBurst(state.particles, shot.x, shot.y, 6, 40, "#ffffff", random, 0.3);
          break;
        }
      }
    }
  }
}

function stepBombs(state: RaidersState, dt: number, random: () => number): void {
  for (const b of state.bombs) {
    if (!b.active) continue;
    const steps = Math.max(1, Math.ceil((b.speed * dt) / 2));
    const stepLen = (b.speed * dt) / steps;
    for (let i = 0; i < steps && b.active; i += 1) {
      b.y += stepLen;
      const tip = b.y + 6;
      if (tip >= GROUND_Y) {
        b.active = false;
        emitBurst(state.particles, b.x, GROUND_Y - 1, 4, 25, "#9d7bff", random, 0.3);
        break;
      }
      if (hitBarrier(state, b.x, tip, random)) { b.active = false; break; }
      if (state.phase === "play" && b.x >= state.px && b.x < state.px + PLAYER_W && tip >= PLAYER_Y + 2 && b.y < PLAYER_Y + PLAYER_H) {
        b.active = false;
        killPlayer(state, random);
        return;
      }
    }
  }
}

function stepBarrier(state: RaidersState, dt: number): void {
  for (let i = 0; i < SEGMENTS; i += 1) {
    if (state.barrier[i] >= SEG_HP) continue;
    state.recharge[i] += dt;
    if (state.recharge[i] >= RECHARGE_S) {
      state.recharge[i] = 0;
      state.barrier[i] += 1;
    }
  }
}

function stepCourier(state: RaidersState, dt: number, random: () => number): void {
  const k = state.courier;
  if (k.active) {
    k.x += k.dir * COURIER_SPEED * dt;
    // A zigzag: straight diagonal legs, turning every 24 pixels.
    const leg = ((k.x % 48) + 48) % 48;
    k.y = COURIER_Y + (leg < 24 ? leg : 48 - leg) * 0.35;
    if (k.x < -COURIER_W - 2 || k.x > WIDTH + 2) k.active = false;
  } else {
    state.courierTimer -= dt;
    if (state.courierTimer <= 0 && state.aliveCount >= 6) {
      k.active = true;
      k.dir = random() < 0.5 ? 1 : -1;
      k.x = k.dir > 0 ? -COURIER_W : WIDTH;
      k.y = COURIER_Y;
      state.courierTimer = 18 + random() * 12;
    }
  }
  const cap = state.capsule;
  if (cap.active) {
    cap.y += CAPSULE_SPEED * dt;
    if (cap.y + 5 >= PLAYER_Y && cap.y < PLAYER_Y + PLAYER_H && cap.x + 4 > state.px && cap.x < state.px + PLAYER_W) {
      cap.active = false;
      state.rapid = RAPID_S;
      emitBurst(state.particles, cap.x + 2, PLAYER_Y, 12, 50, "#5ee0c8", random, 0.5);
    } else if (cap.y >= GROUND_Y) {
      cap.active = false;
    }
  }
}

function step(state: RaidersState, input: RetroInput, dt: number, random: () => number): void {
  if (state.phase === "over") {
    stepParticles(state.particles, dt, 40);
    return;
  }
  state.elapsed += dt;
  state.shake = Math.max(0, state.shake - dt);
  stepParticles(state.particles, dt, 40);
  for (const b of state.bursts) if (b.active && (b.t -= dt) <= 0) b.active = false;
  for (const p of state.popups) if (p.active && (p.t -= dt) <= 0) p.active = false;

  if (state.phase === "dying") {
    state.timer -= dt;
    if (state.timer <= 0) {
      if (state.lives <= 0) {
        state.phase = "over";
      } else {
        state.phase = "play";
        state.px = PLAYER_START_X;
        state.cooldown = 0.4;
        state.fireTimer = Math.max(state.fireTimer, 1);
      }
    }
    return;
  }
  if (state.phase === "clear") {
    stepShots(state, dt, random);
    state.timer -= dt;
    if (state.timer <= 0) {
      state.wave += 1;
      state.phase = "play";
      startWave(state, random);
    }
    return;
  }

  // The fighter.
  const move = (input.right ? 1 : 0) - (input.left ? 1 : 0);
  state.px = clamp(state.px + move * PLAYER_SPEED * dt, 4, WIDTH - 4 - PLAYER_W);
  state.cooldown -= dt;
  state.rapid = Math.max(0, state.rapid - dt);
  // A tap shorter than one frame still fires: the press edge counts like a held button.
  if ((input.a || input.pressed.a) && state.cooldown <= 0) {
    let active = 0;
    for (const s of state.shots) if (s.active) active += 1;
    const shot = state.shots.find((s) => !s.active);
    if (shot && active < (state.rapid > 0 ? RAPID_SHOTS : MAX_SHOTS)) {
      shot.active = true;
      shot.x = Math.round(state.px) + 5;
      shot.y = PLAYER_Y - 1;
      state.cooldown = state.rapid > 0 ? RAPID_COOLDOWN : SHOT_COOLDOWN;
    }
  }
  stepShots(state, dt, random);
  if (state.phase !== "play") return;

  swaySwarm(state, dt, random);
  if (state.phase !== "play") return;
  state.fireTimer -= dt;
  if (state.fireTimer <= 0) {
    alienFire(state, random);
    state.fireTimer = (0.45 + random() * 0.9) * Math.max(0.45, 1 - 0.08 * (state.wave - 1));
  }
  stepBombs(state, dt, random);
  if (state.phase !== "play") return;
  stepBarrier(state, dt);
  stepCourier(state, dt, random);
}

function status(state: RaidersState): RetroStatus {
  return { score: state.score, lives: state.lives, level: state.wave, over: state.phase === "over" };
}

const STARS = starField(46, WIDTH, 190, 11);
const SEG_COLOR = ["", "rgba(79,179,255,0.35)", "rgba(79,179,255,0.65)", "#4fb3ff"];

function draw(ctx: CanvasRenderingContext2D, state: RaidersState, info: RetroDrawInfo): void {
  ctx.fillStyle = "#070a12";
  ctx.fillRect(0, 0, WIDTH, HEIGHT);
  drawStars(ctx, STARS, info.time, info.reduced, "#9fb4d8");

  ctx.save();
  if (state.shake > 0 && !info.reduced) {
    ctx.translate(Math.round(Math.sin(info.time * 83) * state.shake * 5), Math.round(Math.cos(info.time * 71) * state.shake * 3));
  }

  // Before the first step the swarm flexes gently on the title screen.
  const frame = info.idle && state.elapsed === 0 ? Math.floor(info.time * 1.6) % 2 : state.frame;
  for (let r = 0; r < ROWS; r += 1) {
    const kind = ROW_KIND[r];
    ctx.fillStyle = KIND_COLOR[kind];
    const spr = ALIEN_SPRITES[kind][frame];
    for (let c = 0; c < COLS; c += 1) {
      if (state.alive[r * COLS + c]) drawSprite(ctx, spr, alienX(state, r, c), alienY(state, r));
    }
  }
  for (const b of state.bursts) {
    if (!b.active) continue;
    ctx.fillStyle = b.color;
    drawSprite(ctx, BURST_SPRITE, b.x - 4, b.y - 3);
  }

  const k = state.courier;
  if (k.active) {
    ctx.fillStyle = "#5ee0c8";
    drawSprite(ctx, COURIER_SPRITE, k.x, k.y);
    // A beacon blinks on its belly (held lit under reduced motion).
    if (info.reduced || Math.floor(info.time * 6) % 2 === 0) {
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(Math.round(k.x) + 5, Math.round(k.y) + 5, 2, 1);
    }
  }
  if (state.capsule.active) {
    ctx.fillStyle = info.reduced || Math.floor(info.time * 8) % 2 === 0 ? "#5ee0c8" : "#d8fff6";
    drawSprite(ctx, CAPSULE_SPRITE, state.capsule.x, state.capsule.y);
  }
  ctx.fillStyle = "#ffe2a8";
  for (const p of state.popups) {
    if (p.active) drawNumber(ctx, p.value, p.x, p.y + (info.reduced ? 0 : -(1.2 - p.t) * 6), 1, "center");
  }

  // The barrier: brighter segments hold more charge; a drained one shows only a faint socket.
  for (let i = 0; i < SEGMENTS; i += 1) {
    const hp = state.barrier[i];
    const x = segmentX(i);
    if (hp === 0) {
      ctx.fillStyle = "rgba(79,179,255,0.12)";
      ctx.fillRect(x, BARRIER_Y + 1, SEG_W, 1);
      continue;
    }
    ctx.fillStyle = SEG_COLOR[hp];
    ctx.fillRect(x, BARRIER_Y, SEG_W, BARRIER_H);
    if (hp === SEG_HP) {
      ctx.fillStyle = "#d6efff";
      ctx.fillRect(x + 1, BARRIER_Y + 1, SEG_W - 2, 1);
    }
  }

  const shipColor = state.rapid > 0 ? "#5ee0c8" : "#f2c14e";
  if (state.phase === "dying") {
    // The wreck smoulders between two frames; under reduced motion it holds still.
    ctx.fillStyle = "#f2c14e";
    drawSprite(ctx, WRECK_SPRITES[info.reduced ? 0 : Math.floor(info.time * 6) % 2], state.px, PLAYER_Y);
  } else if (state.phase !== "over") {
    ctx.fillStyle = shipColor;
    drawSprite(ctx, PLAYER_SPRITE, state.px, PLAYER_Y);
    // Engine glow under the two nacelles.
    if (!info.reduced) {
      ctx.fillStyle = Math.floor(info.time * 12) % 2 === 0 ? "#ff8a3d" : "#ffd37a";
      ctx.fillRect(Math.round(state.px) + 1, PLAYER_Y + PLAYER_H, 1, 1);
      ctx.fillRect(Math.round(state.px) + PLAYER_W - 2, PLAYER_Y + PLAYER_H, 1, 1);
    }
  }

  ctx.fillStyle = state.rapid > 0 ? "#5ee0c8" : "#ffe2a8";
  for (const shot of state.shots) if (shot.active) ctx.fillRect(shot.x, Math.round(shot.y), 1, 4);
  for (const b of state.bombs) {
    if (!b.active) continue;
    const y = Math.round(b.y);
    if (b.kind === 1) {
      ctx.fillStyle = "#ffb547";
      const phase = Math.floor(y / 3) % 2;
      for (let i = 0; i < 7; i += 1) ctx.fillRect(b.x - 1 + ((i + phase) % 2) * 2, y + i, 1, 1);
    } else if (b.kind === 2) {
      ctx.fillStyle = "#ff6b5a";
      ctx.fillRect(b.x, y, 1, 7);
      ctx.fillRect(b.x - 1, y + 5, 3, 1);
    } else {
      ctx.fillStyle = "#c9b8ff";
      ctx.fillRect(b.x - 1, y, 3, 2);
      ctx.fillRect(b.x, y + 2, 1, 4);
    }
  }
  drawParticles(ctx, state.particles);
  ctx.restore();

  // Ground, score, wave, rapid-fire gauge and spare fighters.
  ctx.fillStyle = "#2d3a56";
  ctx.fillRect(0, GROUND_Y, WIDTH, 1);
  ctx.fillStyle = "#e8edf7";
  drawNumber(ctx, state.score, 6, 5, 2);
  ctx.fillStyle = "#9d7bff";
  drawNumber(ctx, state.wave, WIDTH - 6, 5, 2, "right");
  if (state.rapid > 0) {
    ctx.fillStyle = "#5ee0c8";
    ctx.fillRect(WIDTH - 6 - Math.round(40 * (state.rapid / RAPID_S)), GROUND_Y + 6, Math.round(40 * (state.rapid / RAPID_S)), 2);
  }
  ctx.fillStyle = "#f2c14e";
  for (let i = 0; i < Math.min(state.lives, MAX_LIVES); i += 1) drawSprite(ctx, LIFE_SPRITE, 6 + i * 9, GROUND_Y + 6);

  if (state.phase === "clear") {
    // The coming wave's number, large, while the field resets.
    ctx.fillStyle = "#9d7bff";
    drawNumber(ctx, state.wave + 1, WIDTH / 2, 104, 5, "center");
  }
}

const pixelRaiders: RetroGame<RaidersState> = {
  id: "pixel-raiders",
  width: WIDTH,
  height: HEIGHT,
  create,
  step,
  draw,
  status,
};

export default pixelRaiders;
