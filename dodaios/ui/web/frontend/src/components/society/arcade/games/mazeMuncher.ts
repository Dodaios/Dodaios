/**
 * "Maze Muncher": the maze-chase cabinet.
 *
 * A little mint scrubber drone vacuums a symmetric maze of data dots while
 * four violet "glitch bugs" (robot beetles) hunt it. The maze is this game's
 * own: 21 × 21 tiles with a wrap tunnel through the middle row and a pen in
 * the centre the bugs start in. Turns are buffered: a direction pressed before
 * a junction is taken at the junction, a reversal is taken at once.
 *
 * Each bug has its own habit: the tracker heads straight for the drone, the
 * warden guards whichever power orb is still left nearest the drone, the echo
 * shadows the drone's mirror image across the maze, and the roamer wanders
 * until the drone comes within reach, then pounces. Every bug takes its own
 * short patrol break back to its home block now and then, staggered so they
 * never all let up at once. Eating a power orb shorts the bugs out for a while
 * (shorter on later levels); zapped bugs pay 150 more than the one before and
 * reboot inside the pen. A bonus gem shows up twice per level. Clearing every
 * dot starts the next, faster level; three lives.
 *
 * Positions are in tile units with tile centres on integer coordinates;
 * movers only change direction exactly on a centre, which keeps the grid
 * logic simple and exact.
 */
import type { RetroDrawInfo, RetroGame, RetroInput, RetroStatus } from "../retroGame";
import { drawDigits, drawSparks, emitSpark, sparkPool, stepSparks, type Spark } from "./games2Kit";

/**
 * The maze: `#` wall, `.` dot, `o` power orb, ` ` open without a dot,
 * `T` tunnel mouth (open, wraps to the other side), `P` pen inside, `-` pen door.
 */
export const MAZE: readonly string[] = [
  "#####################",
  "#.........#.........#",
  "#o##.####.#.####.##o#",
  "#...................#",
  "#.##.#.#######.#.##.#",
  "#....#....#....#....#",
  "####.####.#.####.####",
  "####.#.........#.####",
  "####.#.###-###.#.####",
  "T......#PPPPP#......T",
  "####.#.#######.#.####",
  "####.#.........#.####",
  "####.#.#######.#.####",
  "#.........#.........#",
  "#.##.####.#.####.##.#",
  "#o.#...... ......#.o#",
  "##.#.#.#######.#.#.##",
  "#....#....#....#....#",
  "#.#######.#.#######.#",
  "#...................#",
  "#####################",
];
export const MAZE_W = 21;
export const MAZE_H = 21;

/** Directions: up, left, down, right (also the tie-break order of the bugs); -1 is standing still. */
export const UP = 0, LEFT = 1, DOWN = 2, RIGHT = 3, NONE = -1;
const DX = [0, -1, 0, 1];
const DY = [-1, 0, 1, 0];
const OPPOSITE = [DOWN, RIGHT, UP, LEFT];

export const PLAYER_START_X = 10, PLAYER_START_Y = 15;
/** The tile just above the pen door: bugs leave the pen from here. */
export const EXIT_X = 10, EXIT_Y = 7;
export const PEN_Y = 9;
const PEN_X = [10, 10, 9, 11];
export const BONUS_X = 10, BONUS_Y = 11;
const TUNNEL_ROW = 9;

export const DOT_POINTS = 5;
export const ORB_POINTS = 25;
/** Bugs zapped during one power orb: each pays 150 more than the one before. */
export const CHAIN_POINTS: readonly number[] = [150, 300, 450, 600];
export const BONUS_POINTS: readonly number[] = [250, 500, 750, 1000, 1500, 2000, 2500, 3000];
export const START_LIVES = 3;
export const READY_TIME = 1.6;
export const DYING_TIME = 1.4;
export const CLEAR_TIME = 2;
const EAT_PAUSE = 0.35;
const BONUS_TIME = 9;
/** Seconds a zapped bug spends rebooting in the pen before it comes out again. */
export const REBOOT_TIME = 3;
/** Each bug hunts for HUNT_TIME, then patrols its home block for PATROL_TIME; the cycles are staggered. */
export const HUNT_TIME = 12;
export const PATROL_TIME = 4;
const CYCLE_OFFSET = [0, 3, 6, 9];
const RELEASE_TIME = [0, 1, 5, 9];
const RELEASE_DOTS = [0, 0, 25, 50];
/** Each bug's home tile, inside the maze, that it patrols around on a break. */
const HOME_X = [17, 3, 17, 3];
const HOME_Y = [3, 3, 17, 17];
/** The roamer pounces once the drone is this close (squared tiles). */
const POUNCE_DIST2 = 25;
const EPS = 1e-6;

/** Bug indices by habit. */
export const TRACKER = 0, WARDEN = 1, ECHO = 2, ROAMER = 3;

export type BugMode = "pen" | "leaving" | "active" | "rebooting";

export interface Mover { x: number; y: number; dir: number }

export interface Probe extends Mover {
  /** The buffered direction, taken at the next centre where it is open. */
  want: number;
  /** Distance travelled, for the chewing animation. */
  chew: number;
}

export interface Bug extends Mover {
  index: number;
  mode: BugMode;
  /** Shorted out by a power orb: slow, aimless and safe to zap. */
  frightened: boolean;
  /** Seconds of reboot left while `mode` is "rebooting". */
  reboot: number;
}

export type MazePhase = "ready" | "play" | "dying" | "clear";

export interface Popup { x: number; y: number; value: number; time: number }

export interface MazeState {
  /** One entry per tile: 0 nothing, 1 dot, 2 power orb. */
  dots: Uint8Array;
  dotsLeft: number;
  totalDots: number;
  player: Probe;
  bugs: Bug[];
  score: number;
  lives: number;
  level: number;
  over: boolean;
  phase: MazePhase;
  phaseTimer: number;
  frightTimer: number;
  /** Bugs zapped during the current power orb. */
  chain: number;
  /** Short freeze after zapping a bug, while its points show. */
  eatPause: number;
  roundTime: number;
  dotsThisRound: number;
  bonusTimer: number;
  bonusShown: number;
  popups: Popup[];
  sparks: Spark[];
  ticks: number;
}

function tileAt(tx: number, ty: number): string {
  if (ty < 0 || ty >= MAZE_H) return "#";
  const x = ((tx % MAZE_W) + MAZE_W) % MAZE_W;
  return MAZE[ty][x];
}

/** Whether a mover may stand on this tile (the pen and its door are only entered by script). */
export function isOpen(tx: number, ty: number): boolean {
  const c = tileAt(tx, ty);
  return c !== "#" && c !== "P" && c !== "-";
}

function openDir(m: Mover, dir: number): boolean {
  return isOpen(Math.round(m.x) + DX[dir], Math.round(m.y) + DY[dir]);
}

function atCentre(m: Mover): boolean {
  return Math.abs(m.x - Math.round(m.x)) < EPS && Math.abs(m.y - Math.round(m.y)) < EPS;
}

function wrapX(m: Mover): void {
  if (m.x < -0.5) m.x += MAZE_W;
  else if (m.x > MAZE_W - 0.5) m.x -= MAZE_W;
}

export function levelSpeed(level: number): number {
  return Math.min(1.3, 1 + (level - 1) * 0.06);
}

export function frightDuration(level: number): number {
  return Math.max(1.5, 7 - (level - 1) * 1.1);
}

function fillDots(s: MazeState): void {
  let n = 0;
  for (let y = 0; y < MAZE_H; y += 1) {
    for (let x = 0; x < MAZE_W; x += 1) {
      const c = MAZE[y][x];
      const v = c === "." ? 1 : c === "o" ? 2 : 0;
      s.dots[y * MAZE_W + x] = v;
      if (v) n += 1;
    }
  }
  s.dotsLeft = n;
  s.totalDots = n;
  s.bonusShown = 0;
  s.bonusTimer = 0;
}

/** Put everyone back at their start (after a lost life or a cleared level). */
function resetRound(s: MazeState): void {
  const p = s.player;
  p.x = PLAYER_START_X; p.y = PLAYER_START_Y; p.dir = NONE; p.want = LEFT; p.chew = 0;
  for (const b of s.bugs) {
    b.frightened = false;
    b.reboot = 0;
    if (b.index === 0) { b.x = EXIT_X; b.y = EXIT_Y; b.dir = LEFT; b.mode = "active"; }
    else { b.x = PEN_X[b.index]; b.y = PEN_Y; b.dir = UP; b.mode = "pen"; }
  }
  s.frightTimer = 0; s.chain = 0; s.eatPause = 0;
  s.roundTime = 0; s.dotsThisRound = 0; s.bonusTimer = 0;
  s.phase = "ready"; s.phaseTimer = READY_TIME;
}

export function createMaze(): MazeState {
  const s: MazeState = {
    dots: new Uint8Array(MAZE_W * MAZE_H), dotsLeft: 0, totalDots: 0,
    player: { x: 0, y: 0, dir: NONE, want: LEFT, chew: 0 },
    bugs: [0, 1, 2, 3].map((index) => ({ index, x: 0, y: 0, dir: UP, mode: "pen" as BugMode, frightened: false, reboot: 0 })),
    score: 0, lives: START_LIVES, level: 1, over: false, phase: "ready", phaseTimer: READY_TIME,
    frightTimer: 0, chain: 0, eatPause: 0, roundTime: 0, dotsThisRound: 0,
    bonusTimer: 0, bonusShown: 0,
    popups: [0, 1, 2].map(() => ({ x: 0, y: 0, value: 0, time: 0 })),
    sparks: sparkPool(48), ticks: 0,
  };
  fillDots(s);
  resetRound(s);
  return s;
}

/** Whether this bug is on its patrol break right now (each bug's cycle is offset from the others). */
export function patrolling(s: MazeState, b: Bug): boolean {
  const cycle = HUNT_TIME + PATROL_TIME;
  const t = (((s.roundTime + CYCLE_OFFSET[b.index]) % cycle) + cycle) % cycle;
  return t >= HUNT_TIME;
}

/**
 * Where a bug is heading right now; its habit decides while it hunts. Returns
 * false when the bug has no target and wanders (the roamer while the drone is far).
 */
export function bugTarget(s: MazeState, b: Bug, out: { x: number; y: number }): boolean {
  const p = s.player;
  const px = Math.round(p.x), py = Math.round(p.y);
  if (patrolling(s, b)) { out.x = HOME_X[b.index]; out.y = HOME_Y[b.index]; return true; }
  switch (b.index) {
    case TRACKER:
      out.x = px; out.y = py; return true;
    case WARDEN: {
      // Guard the power orb still left nearest the drone; with none left, hunt it directly.
      let best = Infinity;
      out.x = px; out.y = py;
      for (let i = 0; i < s.dots.length; i += 1) {
        if (s.dots[i] !== 2) continue;
        const ox = i % MAZE_W, oy = Math.floor(i / MAZE_W);
        const d = (ox - px) * (ox - px) + (oy - py) * (oy - py);
        if (d < best) { best = d; out.x = ox; out.y = oy; }
      }
      return true;
    }
    case ECHO:
      // The drone's mirror image across the maze's centre line.
      out.x = MAZE_W - 1 - px; out.y = py; return true;
    default: {
      const dx = b.x - p.x, dy = b.y - p.y;
      if (dx * dx + dy * dy > POUNCE_DIST2) return false;
      out.x = px; out.y = py; return true;
    }
  }
}

const target = { x: 0, y: 0 };

function chooseBugDir(s: MazeState, b: Bug, random: () => number): number {
  const back = b.dir >= 0 ? OPPOSITE[b.dir] : NONE;
  let count = 0;
  for (let d = 0; d < 4; d += 1) if (d !== back && openDir(b, d)) count += 1;
  if (count === 0) return back >= 0 && openDir(b, back) ? back : NONE;
  if (b.frightened || !bugTarget(s, b, target)) {
    // Shorted-out bugs, and a roamer with nothing in reach, pick a random open way at every junction.
    let pick = Math.floor(random() * count);
    for (let d = 0; d < 4; d += 1) {
      if (d === back || !openDir(b, d)) continue;
      if (pick === 0) return d;
      pick -= 1;
    }
  }
  let best = NONE, bestDist = Infinity;
  const bx = Math.round(b.x), by = Math.round(b.y);
  for (let d = 0; d < 4; d += 1) {
    if (d === back || !openDir(b, d)) continue;
    const dx = bx + DX[d] - target.x, dy = by + DY[d] - target.y;
    const dist = dx * dx + dy * dy;
    if (dist < bestDist) { bestDist = dist; best = d; }
  }
  return best;
}

function choosePlayerDir(p: Probe): number {
  if (p.want >= 0 && openDir(p, p.want)) return p.want;
  if (p.dir >= 0 && openDir(p, p.dir)) return p.dir;
  return NONE;
}

/**
 * Move along the grid by `dist` tiles, choosing a new direction on every tile
 * centre reached. Returns the distance actually travelled.
 */
function advance(s: MazeState, m: Mover, dist: number, bug: Bug | null, random: () => number): number {
  let moved = 0;
  for (let guard = 0; dist > EPS && guard < 8; guard += 1) {
    if (atCentre(m)) {
      m.x = Math.round(m.x); m.y = Math.round(m.y);
      const dir = bug ? chooseBugDir(s, bug, random) : choosePlayerDir(m as Probe);
      if (dir < 0) { if (!bug) m.dir = NONE; return moved; }
      m.dir = dir;
    }
    const horizontal = DX[m.dir] !== 0;
    const sign = DX[m.dir] + DY[m.dir];
    const along = horizontal ? m.x : m.y;
    const next = sign > 0 ? Math.floor(along + EPS) + 1 : Math.ceil(along - EPS) - 1;
    const gap = Math.abs(next - along);
    const stepLen = Math.min(dist, gap);
    if (horizontal) m.x = gap - stepLen < EPS ? next : m.x + sign * stepLen;
    else m.y = gap - stepLen < EPS ? next : m.y + sign * stepLen;
    dist -= stepLen;
    moved += stepLen;
    wrapX(m);
  }
  return moved;
}

/** Move straight towards a point (pen moves are scripted, not on the grid). Returns true on arrival. */
function glide(m: Mover, tx: number, ty: number, dist: number): boolean {
  const dx = tx - m.x, dy = ty - m.y;
  const len = Math.hypot(dx, dy);
  if (len <= dist) { m.x = tx; m.y = ty; return true; }
  m.x += (dx / len) * dist;
  m.y += (dy / len) * dist;
  if (Math.abs(dx) > Math.abs(dy)) m.dir = dx < 0 ? LEFT : RIGHT;
  else m.dir = dy < 0 ? UP : DOWN;
  return false;
}

function inTunnel(m: Mover): boolean {
  return Math.round(m.y) === TUNNEL_ROW && (m.x < 3.5 || m.x > MAZE_W - 4.5);
}

function popup(s: MazeState, x: number, y: number, value: number): void {
  let slot = s.popups[0];
  for (const p of s.popups) if (p.time < slot.time) slot = p;
  slot.x = x; slot.y = y; slot.value = value; slot.time = 1;
}

function burst(s: MazeState, x: number, y: number, color: string, count: number, random: () => number): void {
  for (let i = 0; i < count; i += 1) {
    const a = random() * Math.PI * 2, v = 20 + random() * 50;
    emitSpark(s.sparks, tileCx(x), tileCy(y), Math.cos(a) * v, Math.sin(a) * v, 0.35 + random() * 0.35, 2, color);
  }
}

function held(input: RetroInput, dir: number): boolean {
  return dir === UP ? input.up : dir === LEFT ? input.left : dir === DOWN ? input.down : input.right;
}

function readInput(p: Probe, input: RetroInput): void {
  const pr = input.pressed;
  if (pr.up) p.want = UP;
  else if (pr.left) p.want = LEFT;
  else if (pr.down) p.want = DOWN;
  else if (pr.right) p.want = RIGHT;
  else {
    // Two keys held and the buffered one let go: switch to the one still held.
    if (p.want >= 0 && !held(input, p.want)) for (let d = 0; d < 4; d += 1) if (held(input, d)) { p.want = d; break; }
  }
  if (p.dir >= 0 && p.want === OPPOSITE[p.dir]) p.dir = p.want;
}

function eatDots(s: MazeState, random: () => number): void {
  const p = s.player;
  const tx = ((Math.round(p.x) % MAZE_W) + MAZE_W) % MAZE_W, ty = Math.round(p.y);
  const i = ty * MAZE_W + tx;
  const v = s.dots[i];
  if (v !== 0) {
    s.dots[i] = 0;
    s.dotsLeft -= 1;
    s.dotsThisRound += 1;
    if (v === 2) {
      s.score += ORB_POINTS;
      s.frightTimer = frightDuration(s.level);
      s.chain = 0;
      for (const b of s.bugs) {
        if (b.mode !== "active") continue;
        b.frightened = true;
        if (b.dir >= 0) b.dir = OPPOSITE[b.dir];
      }
      burst(s, tx, ty, PROBE_COLOR, 10, random);
    } else {
      s.score += DOT_POINTS;
    }
    const eaten = s.totalDots - s.dotsLeft;
    if (s.bonusShown < 2 && eaten >= Math.floor(s.totalDots * (s.bonusShown === 0 ? 0.3 : 0.7))) {
      s.bonusShown += 1;
      s.bonusTimer = BONUS_TIME;
    }
    if (s.dotsLeft === 0) { s.phase = "clear"; s.phaseTimer = CLEAR_TIME; }
  }
  if (s.bonusTimer > 0 && Math.abs(p.x - BONUS_X) < 0.6 && Math.abs(p.y - BONUS_Y) < 0.6) {
    const points = BONUS_POINTS[Math.min(s.level - 1, BONUS_POINTS.length - 1)];
    s.score += points;
    s.bonusTimer = 0;
    popup(s, BONUS_X, BONUS_Y, points);
    burst(s, BONUS_X, BONUS_Y, bonusColor(s.level), 12, random);
  }
}

function moveBug(s: MazeState, b: Bug, dt: number, random: () => number): void {
  const k = levelSpeed(s.level);
  switch (b.mode) {
    case "pen":
      if (s.roundTime >= RELEASE_TIME[b.index] / k || s.dotsThisRound >= RELEASE_DOTS[b.index]) b.mode = "leaving";
      return;
    case "leaving": {
      const step = 3.5 * dt;
      if (Math.abs(b.x - EXIT_X) > EPS) { glide(b, EXIT_X, b.y, step); return; }
      if (glide(b, EXIT_X, EXIT_Y, step)) { b.mode = "active"; b.dir = LEFT; b.frightened = false; }
      return;
    }
    case "rebooting":
      b.reboot -= dt;
      if (b.reboot <= 0) { b.reboot = 0; b.mode = "leaving"; }
      return;
    default: {
      const speed = inTunnel(b) ? 3.6 : b.frightened ? 4.2 : 6.8 * k;
      advance(s, b, speed * dt, b, random);
    }
  }
}

function collide(s: MazeState, random: () => number): void {
  const p = s.player;
  for (const b of s.bugs) {
    if (b.mode !== "active") continue;
    if (Math.abs(b.x - p.x) > 0.6 || Math.abs(b.y - p.y) > 0.6) continue;
    if (b.frightened) {
      const points = CHAIN_POINTS[Math.min(s.chain, CHAIN_POINTS.length - 1)];
      s.chain += 1;
      s.score += points;
      popup(s, b.x, b.y, points);
      burst(s, b.x, b.y, BUG_COLORS[b.index], 14, random);
      // The zapped bug drops out of the maze and reboots in its pen slot.
      b.frightened = false;
      b.mode = "rebooting";
      b.reboot = REBOOT_TIME;
      b.x = PEN_X[b.index]; b.y = PEN_Y; b.dir = UP;
      s.eatPause = EAT_PAUSE;
    } else {
      s.lives -= 1;
      s.phase = "dying";
      s.phaseTimer = DYING_TIME;
      return;
    }
  }
}

export function stepMaze(s: MazeState, input: RetroInput, dt: number, random: () => number): void {
  s.ticks += 1;
  stepSparks(s.sparks, dt, 0);
  for (const p of s.popups) p.time = Math.max(0, p.time - dt);
  if (s.over) return;
  readInput(s.player, input);

  if (s.phase !== "play") {
    s.phaseTimer -= dt;
    if (s.phase === "dying" && s.phaseTimer < DYING_TIME * 0.25 && s.phaseTimer + dt >= DYING_TIME * 0.25) {
      burst(s, s.player.x, s.player.y, PROBE_COLOR, 16, random);
    }
    if (s.phaseTimer > 0) return;
    if (s.phase === "dying") {
      if (s.lives <= 0) { s.over = true; return; }
      resetRound(s);
    } else if (s.phase === "clear") {
      s.level += 1;
      fillDots(s);
      resetRound(s);
    } else {
      s.phase = "play";
    }
    return;
  }

  if (s.eatPause > 0) { s.eatPause -= dt; return; }
  s.roundTime += dt;
  if (s.bonusTimer > 0) s.bonusTimer = Math.max(0, s.bonusTimer - dt);

  if (s.frightTimer > 0) {
    s.frightTimer -= dt;
    if (s.frightTimer <= 0) { s.frightTimer = 0; for (const b of s.bugs) b.frightened = false; }
  }

  const p = s.player;
  p.chew += advance(s, p, 7.2 * levelSpeed(s.level) * dt, null, random);
  eatDots(s, random);
  if (s.phase !== "play") return;
  collide(s, random);
  if (s.phase !== "play" || s.eatPause > 0) return;
  for (const b of s.bugs) moveBug(s, b, dt, random);
  collide(s, random);
}

// ---------------------------------------------------------------- drawing

export const TILE = 10;
const OY = 14;
export const WIDTH = MAZE_W * TILE;
export const HEIGHT = MAZE_H * TILE + OY * 2;

function tileCx(x: number): number { return x * TILE + TILE / 2; }
function tileCy(y: number): number { return OY + y * TILE + TILE / 2; }

/** Wall outlines as line segments (x1, y1, x2, y2), traced once: every wall edge facing open floor. */
const WALL_SEGMENTS: number[] = (() => {
  const out: number[] = [];
  // The pen counts as floor here, so its walls are outlined on the inside too.
  const solid = (x: number, y: number) => x < 0 || x >= MAZE_W || y < 0 || y >= MAZE_H || MAZE[y][x] === "#";
  const inset = 2;
  for (let y = 0; y < MAZE_H; y += 1) {
    for (let x = 0; x < MAZE_W; x += 1) {
      if (MAZE[y][x] !== "#") continue;
      const l = x * TILE, t = OY + y * TILE, r = l + TILE, b = t + TILE;
      // An edge is outlined where the neighbour is floor; the line sits just inside the wall.
      if (!solid(x, y - 1)) out.push(l, t + inset, r, t + inset);
      if (!solid(x, y + 1)) out.push(l, b - inset, r, b - inset);
      if (!solid(x - 1, y)) out.push(l + inset, t, l + inset, b);
      if (!solid(x + 1, y)) out.push(r - inset, t, r - inset, b);
    }
  }
  return out;
})();

/** One violet family for all four bugs; they differ by shade and by the shape of their crest. */
const BUG_COLORS = ["#b48cff", "#8f6bff", "#d4b2ff", "#7a5ae6"];
const SHORTED = "#59606e";
const PROBE_COLOR = "#5ef2c2";
const WALL_GOLD = "#b8933a";
const BONUS_COLORS = ["#5ef2c2", "#e9b949", "#9ad8ff", "#f08ad0", "#c7f06a", "#ffffff", "#ffb48a", "#d4b2ff"];

function bonusColor(level: number): string {
  return BONUS_COLORS[Math.min(level - 1, BONUS_COLORS.length - 1)];
}

function drawGem(ctx: CanvasRenderingContext2D, cx: number, cy: number, r: number, color: string): void {
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.moveTo(cx, cy - r); ctx.lineTo(cx + r, cy - r * 0.2); ctx.lineTo(cx, cy + r); ctx.lineTo(cx - r, cy - r * 0.2);
  ctx.closePath();
  ctx.fill();
  ctx.fillStyle = "rgba(255,255,255,0.6)";
  ctx.beginPath();
  ctx.moveTo(cx, cy - r); ctx.lineTo(cx + r * 0.4, cy - r * 0.2); ctx.lineTo(cx, cy + r * 0.2); ctx.lineTo(cx - r * 0.4, cy - r * 0.2);
  ctx.closePath();
  ctx.fill();
}

/**
 * The scrubber drone: a squat mint hexagon with a dark sensor stripe and two
 * intake prongs at the front that open and close (`open` 0..1). `scale`
 * shrinks it when it shorts out.
 */
function drawProbe(ctx: CanvasRenderingContext2D, cx: number, cy: number, r: number, dir: number, open: number, scale = 1): void {
  if (scale <= 0.02) return;
  const fx = dir >= 0 ? DX[dir] : -1, fy = dir >= 0 ? DY[dir] : 0;
  // Side axis, perpendicular to the facing.
  const sx = -fy, sy = fx;
  const R = r * scale;
  ctx.fillStyle = PROBE_COLOR;
  ctx.beginPath();
  for (let i = 0; i < 6; i += 1) {
    const a = (Math.PI / 3) * i + Math.PI / 6;
    const x = cx + Math.cos(a) * R, y = cy + Math.sin(a) * R * 0.85;
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  }
  ctx.closePath();
  ctx.fill();
  // Intake prongs, splaying open as it vacuums.
  const spread = (0.6 + open * 1.6) * scale;
  ctx.strokeStyle = PROBE_COLOR;
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (const side of [-1, 1]) {
    const bx = cx + fx * R * 0.7 + sx * side * R * 0.5, by = cy + fy * R * 0.7 + sy * side * R * 0.5;
    ctx.moveTo(bx, by);
    ctx.lineTo(bx + fx * R * 0.7 + sx * side * spread, by + fy * R * 0.7 + sy * side * spread);
  }
  ctx.stroke();
  // The sensor stripe across its face, a lit pixel on the leading side.
  ctx.fillStyle = "#0e2a24";
  ctx.fillRect(Math.round(cx - R * 0.6), Math.round(cy - 1), Math.max(1, Math.round(R * 1.2)), 2);
  ctx.fillStyle = "#eafff8";
  ctx.fillRect(Math.round(cx + fx * R * 0.35 - 0.5), Math.round(cy - 1 + fy * 0.5), 1, 1);
}

/** A glitch bug: domed robot beetle with antennae, a visor and scuttling legs. */
function drawBug(ctx: CanvasRenderingContext2D, s: MazeState, b: Bug, info: RetroDrawInfo): void {
  const bob = b.mode === "pen" && !info.reduced ? Math.sin(info.time * 5 + b.index * 2) * 1.5 : 0;
  const cx = tileCx(b.x), cy = tileCy(b.y) + bob;
  const lookX = b.dir >= 0 ? DX[b.dir] : 0, lookY = b.dir >= 0 ? DY[b.dir] : 0;
  if (b.mode === "rebooting") {
    // Rebooting: a wireframe shell that fills in from the bottom as the reboot completes.
    const k = 1 - b.reboot / REBOOT_TIME;
    ctx.strokeStyle = BUG_COLORS[b.index];
    ctx.globalAlpha = 0.6;
    ctx.lineWidth = 1;
    ctx.strokeRect(Math.round(cx - 4.5) + 0.5, Math.round(cy - 4) + 0.5, 8, 7);
    ctx.globalAlpha = 1;
    const h = Math.round(7 * k);
    if (h > 0) {
      ctx.fillStyle = BUG_COLORS[b.index];
      ctx.fillRect(Math.round(cx - 4), Math.round(cy + 3) - h, 8, h);
    }
    return;
  }
  {
    let body = BUG_COLORS[b.index];
    if (b.frightened) {
      // Shorted out: a dull grey shell; it flickers back to its own colour as the power wears off.
      const left = s.frightTimer;
      body = SHORTED;
      if (left < 2) {
        if (info.reduced) {
          body = left < 1 ? BUG_COLORS[b.index] : SHORTED;
        } else if (Math.floor(left * 5) % 2 === 0) {
          body = BUG_COLORS[b.index];
        }
      }
    }
    const legPhase = info.reduced ? 0 : Math.floor((info.time * 10 + b.index) % 2);
    ctx.strokeStyle = body;
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let i = -1; i <= 1; i += 1) {
      const lx = cx + i * 3, kick = (i + legPhase) % 2 === 0 ? 1 : 0;
      ctx.moveTo(lx, cy + 3); ctx.lineTo(lx + (i === 0 ? 0 : i), cy + 5 + kick);
    }
    // Antennae.
    ctx.moveTo(cx - 2, cy - 4); ctx.lineTo(cx - 3, cy - 6);
    ctx.moveTo(cx + 2, cy - 4); ctx.lineTo(cx + 3, cy - 6);
    ctx.stroke();
    ctx.fillStyle = body;
    ctx.beginPath();
    ctx.arc(cx, cy, 4.5, Math.PI, 0);
    ctx.lineTo(cx + 4.5, cy + 3);
    ctx.lineTo(cx - 4.5, cy + 3);
    ctx.closePath();
    ctx.fill();
    ctx.fillRect(Math.round(cx - 3.5), Math.round(cy - 7), 1, 1);
    ctx.fillRect(Math.round(cx + 2.5), Math.round(cy - 7), 1, 1);
    // A crest on the dome tells the four habits apart: none, a fin, twin bumps, a ridge.
    if (b.index === WARDEN) ctx.fillRect(Math.round(cx - 0.5), Math.round(cy - 6), 1, 2);
    else if (b.index === ECHO) { ctx.fillRect(Math.round(cx - 2), Math.round(cy - 5), 1, 1); ctx.fillRect(Math.round(cx + 1), Math.round(cy - 5), 1, 1); }
    else if (b.index === ROAMER) ctx.fillRect(Math.round(cx - 2), Math.round(cy - 5), 4, 1);
    if (b.frightened) {
      // A jagged glitch mouth instead of a visor.
      ctx.strokeStyle = "#e8ecf2";
      ctx.beginPath();
      ctx.moveTo(cx - 3, cy + 1); ctx.lineTo(cx - 1.5, cy); ctx.lineTo(cx, cy + 1); ctx.lineTo(cx + 1.5, cy); ctx.lineTo(cx + 3, cy + 1);
      ctx.stroke();
      ctx.fillStyle = "#e8ecf2";
      ctx.fillRect(Math.round(cx - 2), Math.round(cy - 3), 1, 1);
      ctx.fillRect(Math.round(cx + 1), Math.round(cy - 3), 1, 1);
      return;
    }
  }
  // The visor: one lit slit that slides towards where the bug is going.
  ctx.fillStyle = "#120c22";
  ctx.fillRect(Math.round(cx - 3.5), Math.round(cy - 2.5), 7, 3);
  ctx.fillStyle = "#ffe9a8";
  ctx.fillRect(Math.round(cx - 1.5 + lookX * 1.5), Math.round(cy - 1.5 + lookY * 0.5), 3, 1);
}

export function drawMaze(ctx: CanvasRenderingContext2D, s: MazeState, info: RetroDrawInfo): void {
  ctx.fillStyle = "#0b0b0e";
  ctx.fillRect(0, 0, WIDTH, HEIGHT);

  // Walls: charcoal blocks with a brass edge. A cleared level makes them glow up and down smoothly.
  ctx.fillStyle = "#1c1b21";
  for (let y = 0; y < MAZE_H; y += 1) {
    for (let x = 0; x < MAZE_W; x += 1) {
      if (MAZE[y][x] === "#") ctx.fillRect(x * TILE, OY + y * TILE, TILE, TILE);
    }
  }
  let wall = WALL_GOLD;
  if (s.phase === "clear") {
    const k = info.reduced ? 0.6 : 0.5 + 0.5 * Math.sin((CLEAR_TIME - s.phaseTimer) * Math.PI * 3);
    wall = `rgb(${Math.round(184 + 71 * k)},${Math.round(147 + 98 * k)},${Math.round(58 + 150 * k)})`;
  }
  ctx.strokeStyle = wall;
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let i = 0; i < WALL_SEGMENTS.length; i += 4) {
    ctx.moveTo(WALL_SEGMENTS[i] + 0.5, WALL_SEGMENTS[i + 1] + 0.5);
    ctx.lineTo(WALL_SEGMENTS[i + 2] + 0.5, WALL_SEGMENTS[i + 3] + 0.5);
  }
  ctx.stroke();
  // The pen door: a dashed brass grille.
  ctx.fillStyle = WALL_GOLD;
  for (let i = 0; i < TILE; i += 3) ctx.fillRect(EXIT_X * TILE + i, OY + (EXIT_Y + 1) * TILE + 4, 2, 2);

  // Data dots (tiny plus signs) and power orbs (rings around a core).
  ctx.fillStyle = "#bfeee0";
  const orbR = info.reduced ? 3.5 : 3.2 + Math.sin(info.time * 6) * 0.7;
  for (let y = 0; y < MAZE_H; y += 1) {
    for (let x = 0; x < MAZE_W; x += 1) {
      const v = s.dots[y * MAZE_W + x];
      if (v === 1) {
        ctx.fillRect(x * TILE + 4, OY + y * TILE + 5, 3, 1);
        ctx.fillRect(x * TILE + 5, OY + y * TILE + 4, 1, 3);
      }
    }
  }
  ctx.strokeStyle = PROBE_COLOR;
  ctx.lineWidth = 1;
  for (let y = 0; y < MAZE_H; y += 1) {
    for (let x = 0; x < MAZE_W; x += 1) {
      if (s.dots[y * MAZE_W + x] !== 2) continue;
      ctx.beginPath();
      ctx.arc(tileCx(x), tileCy(y), orbR, 0, Math.PI * 2);
      ctx.stroke();
      ctx.fillStyle = PROBE_COLOR;
      ctx.fillRect(tileCx(x) - 1, tileCy(y) - 1, 2, 2);
    }
  }

  if (s.bonusTimer > 0) drawGem(ctx, tileCx(BONUS_X), tileCy(BONUS_Y), 4, bonusColor(s.level));

  ctx.save();
  ctx.beginPath();
  ctx.rect(0, OY, WIDTH, MAZE_H * TILE);
  ctx.clip();
  const p = s.player;
  if (s.phase === "dying") {
    // The drone shorts out and shrinks away.
    const k = 1 - Math.max(0, s.phaseTimer - DYING_TIME * 0.25) / (DYING_TIME * 0.75);
    if (s.phaseTimer > DYING_TIME * 0.25) drawProbe(ctx, tileCx(p.x), tileCy(p.y), 4.5, p.dir, 0, 1 - k);
  } else if (!s.over) {
    const chew = info.idle || info.reduced ? (info.idle && !info.reduced ? info.time * 2 : 0.25) : p.chew;
    const open = Math.abs(Math.sin(chew * Math.PI));
    drawProbe(ctx, tileCx(p.x), tileCy(p.y), 4.5, p.dir >= 0 ? p.dir : p.want >= 0 ? p.want : LEFT, open);
  }
  if (s.phase !== "dying" && s.phase !== "clear") for (const b of s.bugs) drawBug(ctx, s, b, info);
  ctx.restore();

  drawSparks(ctx, s.sparks);
  for (const pop of s.popups) {
    if (pop.time <= 0) continue;
    ctx.globalAlpha = Math.min(1, pop.time * 2);
    drawDigits(ctx, pop.value, tileCx(pop.x), tileCy(pop.y) - 4 - (info.reduced ? 0 : (1 - pop.time) * 6), 8, PROBE_COLOR, "center", 600);
  }
  ctx.globalAlpha = 1;

  // HUD: score top left, level gem + number top right, lives bottom left, bonus gems bottom right.
  drawDigits(ctx, s.score, 4, 2, 10, "#ffffff", "left", 600);
  drawGem(ctx, WIDTH - 24, 7, 4, bonusColor(s.level));
  drawDigits(ctx, s.level, WIDTH - 4, 2, 10, "#e9b949", "right");
  const spare = s.phase === "dying" ? s.lives : s.lives - 1;
  for (let i = 0; i < Math.max(0, spare); i += 1) drawProbe(ctx, 8 + i * 12, HEIGHT - 7, 4, RIGHT, 0.4);
  for (let i = 0; i < Math.min(s.level, 6); i += 1) drawGem(ctx, WIDTH - 8 - i * 11, HEIGHT - 7, 3.5, bonusColor(s.level - i));
  // The ready pause before a round: a soft ring around the drone (steady when motion is reduced).
  if (s.phase === "ready" && !info.idle) {
    ctx.strokeStyle = "rgba(94,242,194,0.6)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    const r = info.reduced ? 8 : 7 + (s.phaseTimer % 0.8) * 4;
    ctx.arc(tileCx(p.x), tileCy(p.y), r, 0, Math.PI * 2);
    ctx.stroke();
  }
}

const mazeMuncher: RetroGame<MazeState> = {
  id: "maze-muncher",
  width: WIDTH,
  height: HEIGHT,
  create: () => createMaze(),
  step: (state, input, dt, random) => stepMaze(state, input, dt, random),
  draw: (ctx, state, info) => drawMaze(ctx, state, info),
  status: (state): RetroStatus => ({ score: state.score, lives: state.lives, level: state.level, over: state.over }),
};

export default mazeMuncher;
