/**
 * "City Defense": crystal shards fall on four glass habitat domes. One lance
 * tower in the middle of the colony shoots them down: aim the reticle (mouse,
 * or arrow keys) and fire a bolt that bursts into a ring at that point. Any
 * shard caught in a ring shatters, and its own smaller ring can catch the
 * next one (chain reactions).
 *
 * The tower has no ammunition; it has heat. Every bolt warms it, it cools
 * down on its own, and a tower pushed past its limit jams until it has fully
 * cooled. The secondary button fires a pulse: a slower, much wider ring that
 * costs a lot of heat. A shard striking the tower jams it at once.
 *
 * Later waves bring weaving shards that swing side to side, and a drifting
 * seeder that sows more of them. Each wave ends with a bonus per dome still
 * standing (and extra for a full colony); every 7,500 points earns a spare
 * dome that rebuilds a lost one. When the last dome falls and no spare is
 * waiting, the run is over.
 */
import type { RetroDrawInfo, RetroGame, RetroInput, RetroStatus } from "../retroGame";
import {
  clamp, drawNumber, drawParticles, drawSprite, drawStars, emitBurst, makeParticles, sprite, starField, stepParticles,
  type Particle,
} from "./games3Kit";

export const WIDTH = 320;
export const HEIGHT = 240;
export const GROUND_Y = 222;
/** The reticle stays in the sky. */
const AIM_TOP = 10;
const AIM_BOTTOM = 190;
const AIM_SPEED = 170;

export const DOME_X: readonly number[] = [52, 116, 204, 268];
const DOME_R = 13;
export const TOWER_X = WIDTH / 2;
/** Where bolts leave the tower (the tip of its spire). */
export const TOWER_Y = 196;

/** Heat added by one bolt and by one pulse; the tower jams at 1. */
export const HEAT_BOLT = 0.2;
export const HEAT_PULSE = 0.55;
/** Heat shed per second. */
export const COOL_RATE = 0.35;
const BOLT_SPEED = 230;
const PULSE_SPEED = 150;

const RING_GROW = 0.4;
const RING_HOLD = 0.2;
const RING_FADE = 0.5;
export const RING_S = RING_GROW + RING_HOLD + RING_FADE;
export const BOLT_R = 15;
export const PULSE_R = 30;
/** A shard shattered in the air bursts into a smaller ring of its own. */
export const CHAIN_R = 12;
const IMPACT_R = 10;
/** How close to a dome or the tower an impact must be to break it. */
const DOME_HIT = 14;
const TOWER_HIT = 10;

const MAX_BOLTS = 8;
const MAX_SHARDS = 40;
const MAX_RINGS = 48;

export const SHARD_POINTS = 20;
export const SEEDER_POINTS = 150;
export const DOME_BONUS = 150;
/** Extra at the end of a wave in which no dome was lost. */
export const FULL_COLONY_BONUS = 500;
export const SPARE_DOME_EVERY = 7500;
const READY_S = 1.6;
const BONUS_S = 2.6;
const LOST_S = 2.2;

export type DefensePhase = "ready" | "play" | "bonus" | "lost" | "over";

export interface Bolt { active: boolean; ox: number; oy: number; x: number; y: number; tx: number; ty: number; vx: number; vy: number; left: number; r: number }
/**
 * A falling shard. It travels along a straight base path (`bx`, `y`); a
 * weaving shard swings `weave` pixels either side of it.
 */
export interface Shard { active: boolean; bx: number; x: number; y: number; vx: number; vy: number; ty: number; weave: number; phase: number }
/** A ring: `friendly` ones (ours and chains) shatter what they touch in the air; impacts only break the ground. */
export interface Ring { active: boolean; x: number; y: number; age: number; r: number; friendly: boolean }
export interface Seeder { active: boolean; x: number; y: number; vx: number; vy: number; dropTimer: number; t: number }

export interface DefenseState {
  phase: DefensePhase;
  timer: number;
  /** Total seconds simulated; zero means the run has not started (attract screen). */
  elapsed: number;
  score: number;
  wave: number;
  nextSpareAt: number;
  /** Spare domes waiting to rebuild a lost one at the end of the wave. */
  spares: number;
  cx: number;
  cy: number;
  /** Last pointer position seen, so a resting mouse does not undo keyboard aiming. */
  lastPx: number;
  lastPy: number;
  /** Tower heat, 0 cold to 1 jammed. */
  heat: number;
  /** The tower is jammed and will not fire until it has fully cooled. */
  jammed: boolean;
  domes: Uint8Array;
  /** Domes standing when the wave began, for the full-colony bonus. */
  domesAtStart: number;
  bolts: Bolt[];
  shards: Shard[];
  rings: Ring[];
  seeder: Seeder;
  /** Shards (including the seeder's) still to come this wave. */
  toLaunch: number;
  salvoTimer: number;
  seederTimer: number;
  /** The last wave's bonus tally, for the bonus screen. */
  bonusDomes: number;
  bonusFull: boolean;
  particles: Particle[];
  shake: number;
}

/** Score multiplier: ×1 for waves 1–3, ×2 for 4–6 … up to ×4. */
export function multiplier(wave: number): number {
  return Math.min(4, 1 + Math.floor((wave - 1) / 3));
}

export function shardSpeed(wave: number): number {
  return Math.min(64, 18 + wave * 3.5);
}

function wavePayload(wave: number): number {
  return Math.min(32, 8 + wave * 2);
}

/** Radius of a ring at a given age: it grows, holds and fades. */
export function ringRadius(age: number, max: number): number {
  if (age < RING_GROW) return (max * age) / RING_GROW;
  if (age < RING_GROW + RING_HOLD) return max;
  return Math.max(0, max * (1 - (age - RING_GROW - RING_HOLD) / RING_FADE));
}

export function domesStanding(state: DefenseState): number {
  let n = 0;
  for (const d of state.domes) n += d;
  return n;
}

function startWave(state: DefenseState, random: () => number): void {
  state.phase = "ready";
  state.timer = READY_S;
  state.heat = 0;
  state.jammed = false;
  for (const b of state.bolts) b.active = false;
  for (const s of state.shards) s.active = false;
  for (const r of state.rings) r.active = false;
  state.seeder.active = false;
  state.toLaunch = wavePayload(state.wave);
  state.salvoTimer = 0.4;
  state.seederTimer = 9 + random() * 8;
  state.domesAtStart = domesStanding(state);
}

function create(random: () => number): DefenseState {
  const state: DefenseState = {
    phase: "ready", timer: 0, elapsed: 0, score: 0, wave: 1, nextSpareAt: SPARE_DOME_EVERY, spares: 0,
    cx: WIDTH / 2, cy: 110, lastPx: -1, lastPy: -1, heat: 0, jammed: false,
    domes: new Uint8Array(DOME_X.length).fill(1), domesAtStart: DOME_X.length,
    bolts: Array.from({ length: MAX_BOLTS }, () => ({ active: false, ox: 0, oy: 0, x: 0, y: 0, tx: 0, ty: 0, vx: 0, vy: 0, left: 0, r: 0 })),
    shards: Array.from({ length: MAX_SHARDS }, () => ({ active: false, bx: 0, x: 0, y: 0, vx: 0, vy: 0, ty: 0, weave: 0, phase: 0 })),
    rings: Array.from({ length: MAX_RINGS }, () => ({ active: false, x: 0, y: 0, age: 0, r: 0, friendly: false })),
    seeder: { active: false, x: 0, y: 0, vx: 0, vy: 0, dropTimer: 0, t: 0 },
    toLaunch: 0, salvoTimer: 0, seederTimer: 0, bonusDomes: 0, bonusFull: false,
    particles: makeParticles(160),
    shake: 0,
  };
  startWave(state, random);
  return state;
}

function addScore(state: DefenseState, points: number): void {
  state.score += points;
  while (state.score >= state.nextSpareAt) {
    state.spares += 1;
    state.nextSpareAt += SPARE_DOME_EVERY;
  }
}

function spawnRing(state: DefenseState, x: number, y: number, r: number, friendly: boolean): void {
  let slot: Ring | undefined;
  for (const b of state.rings) if (!b.active) { slot = b; break; }
  if (!slot) return;
  slot.active = true; slot.x = x; slot.y = y; slot.age = 0; slot.r = r; slot.friendly = friendly;
}

/**
 * Send a shard from (x, y) towards (tx, ty) on the ground; `weave` > 0 makes
 * it swing side to side. Returns false when the sky is full.
 */
export function addShard(state: DefenseState, x: number, y: number, tx: number, ty: number, speed: number, weave = 0): boolean {
  let s: Shard | undefined;
  for (const c of state.shards) if (!c.active) { s = c; break; }
  if (!s) return false;
  const dx = tx - x, dy = ty - y;
  const len = Math.max(1, Math.hypot(dx, dy));
  s.active = true; s.bx = x; s.x = x; s.y = y;
  s.vx = (dx / len) * speed; s.vy = (dy / len) * speed;
  s.ty = ty; s.weave = weave; s.phase = 0;
  return true;
}

/** A target on the ground: a standing dome most of the time, sometimes the tower or open ground. */
function pickTarget(state: DefenseState, random: () => number, out: number[]): void {
  const standing = domesStanding(state);
  const roll = random();
  if (standing === 0 || roll < 0.12) {
    out[0] = 12 + random() * (WIDTH - 24);
    out[1] = GROUND_Y;
    return;
  }
  if (roll < 0.22) {
    out[0] = TOWER_X; out[1] = TOWER_Y + 4;
    return;
  }
  let pick = Math.floor(random() * standing);
  for (let i = 0; i < DOME_X.length; i += 1) {
    if (state.domes[i] && pick-- === 0) { out[0] = DOME_X[i]; out[1] = GROUND_Y; return; }
  }
}
const target = [0, 0];

function launchFromSky(state: DefenseState, random: () => number): void {
  pickTarget(state, random, target);
  const weaveChance = state.wave >= 3 ? Math.min(0.4, 0.08 * (state.wave - 2)) : 0;
  const weave = random() < weaveChance ? 10 + random() * 10 : 0;
  // A weaver's base path is kept inside the screen so its swing never leaves it.
  const x = clamp(8 + random() * (WIDTH - 16), 8 + weave, WIDTH - 8 - weave);
  if (addShard(state, x, 0, clamp(target[0], 8 + weave, WIDTH - 8 - weave), target[1], shardSpeed(state.wave), weave)) {
    state.toLaunch -= 1;
  }
}

/**
 * Whether the tower may fire now: a bolt whenever it is not jammed (the bolt
 * that pushes it past its limit jams it), a pulse only while it is cool
 * enough to take the pulse's heat.
 */
export function canFire(state: DefenseState, pulse: boolean): boolean {
  return !state.jammed && (!pulse || state.heat + HEAT_PULSE <= 1 + 1e-9);
}

function fire(state: DefenseState, pulse: boolean): boolean {
  if (!canFire(state, pulse)) return false;
  const cost = pulse ? HEAT_PULSE : HEAT_BOLT;
  let b: Bolt | undefined;
  for (const c of state.bolts) if (!c.active) { b = c; break; }
  if (!b) return false;
  state.heat += cost;
  if (state.heat >= 1 - 1e-9) { state.heat = 1; state.jammed = true; }
  const speed = pulse ? PULSE_SPEED : BOLT_SPEED;
  const dx = state.cx - TOWER_X, dy = state.cy - TOWER_Y;
  const len = Math.max(1, Math.hypot(dx, dy));
  b.active = true; b.ox = TOWER_X; b.oy = TOWER_Y; b.x = TOWER_X; b.y = TOWER_Y;
  b.tx = state.cx; b.ty = state.cy; b.left = len; b.r = pulse ? PULSE_R : BOLT_R;
  b.vx = (dx / len) * speed; b.vy = (dy / len) * speed;
  return true;
}

/** A shard reached the ground: break what stands there. */
function impact(state: DefenseState, x: number, y: number, random: () => number): void {
  spawnRing(state, x, y, IMPACT_R, false);
  emitBurst(state.particles, x, y, 12, 60, "#ff9a4a", random, 0.7);
  for (let i = 0; i < DOME_X.length; i += 1) {
    if (state.domes[i] && Math.abs(DOME_X[i] - x) <= DOME_HIT) {
      state.domes[i] = 0;
      state.shake = 0.35;
      emitBurst(state.particles, DOME_X[i], GROUND_Y - 6, 24, 80, "#bff6ff", random, 1);
    }
  }
  if (Math.abs(TOWER_X - x) <= TOWER_HIT) {
    // The tower is armoured: a hit jams it instead of destroying it.
    state.heat = 1;
    state.jammed = true;
    state.shake = 0.3;
    emitBurst(state.particles, TOWER_X, TOWER_Y, 16, 60, "#ffd35a", random, 0.8);
  }
}

/** Everything in the air moves; rings grow, catch shards and fade. */
function stepWorld(state: DefenseState, dt: number, random: () => number): void {
  const mult = multiplier(state.wave);
  state.heat = Math.max(0, state.heat - COOL_RATE * dt);
  if (state.jammed && state.heat <= 0) state.jammed = false;
  for (const b of state.bolts) {
    if (!b.active) continue;
    const travel = Math.hypot(b.vx, b.vy) * dt;
    if (travel >= b.left) {
      b.active = false;
      spawnRing(state, b.tx, b.ty, b.r, true);
      continue;
    }
    b.left -= travel;
    b.x += b.vx * dt;
    b.y += b.vy * dt;
  }
  for (const s of state.shards) {
    if (!s.active) continue;
    s.bx += s.vx * dt;
    s.y += s.vy * dt;
    s.phase += dt * 3;
    s.x = s.bx + Math.sin(s.phase) * s.weave;
    if (s.y >= s.ty) {
      s.active = false;
      impact(state, s.x, s.ty, random);
    }
  }
  const f = state.seeder;
  if (f.active) {
    f.t += dt;
    f.x += f.vx * dt;
    f.y += f.vy * dt;
    if (f.x < -20 || f.x > WIDTH + 20) f.active = false;
    else if ((f.dropTimer -= dt) <= 0 && state.toLaunch > 0 && f.x > 20 && f.x < WIDTH - 20) {
      pickTarget(state, random, target);
      if (addShard(state, f.x, f.y + 6, clamp(target[0], 20, WIDTH - 20), target[1], shardSpeed(state.wave) * 0.9, 12)) state.toLaunch -= 1;
      f.dropTimer = 1.4 + random() * 1.2;
    }
  }
  for (const r of state.rings) {
    if (!r.active) continue;
    r.age += dt;
    if (r.age >= RING_S) { r.active = false; continue; }
    if (!r.friendly) continue;
    const rad = ringRadius(r.age, r.r);
    const r2 = rad * rad;
    for (const s of state.shards) {
      if (!s.active) continue;
      const dx = s.x - r.x, dy = s.y - r.y;
      if (dx * dx + dy * dy <= r2) {
        s.active = false;
        addScore(state, SHARD_POINTS * mult);
        spawnRing(state, s.x, s.y, CHAIN_R, true);
        emitBurst(state.particles, s.x, s.y, 8, 50, "#ffc4f0", random, 0.5);
      }
    }
    if (f.active) {
      const dx = f.x - r.x, dy = f.y - r.y;
      if (dx * dx + dy * dy <= (rad + 6) * (rad + 6)) {
        f.active = false;
        addScore(state, SEEDER_POINTS * mult);
        spawnRing(state, f.x, f.y, BOLT_R, true);
        emitBurst(state.particles, f.x, f.y, 20, 80, "#b6fff0", random, 0.8);
      }
    }
  }
}

function airborne(state: DefenseState): boolean {
  if (state.seeder.active) return true;
  for (const b of state.bolts) if (b.active) return true;
  for (const s of state.shards) if (s.active) return true;
  for (const r of state.rings) if (r.active) return true;
  return false;
}

function endWave(state: DefenseState): void {
  const mult = multiplier(state.wave);
  state.bonusDomes = domesStanding(state);
  state.bonusFull = state.bonusDomes === DOME_X.length && state.domesAtStart === DOME_X.length;
  addScore(state, (state.bonusDomes * DOME_BONUS + (state.bonusFull ? FULL_COLONY_BONUS : 0)) * mult);
  state.phase = "bonus";
  state.timer = BONUS_S;
}

function aim(state: DefenseState, input: RetroInput, dt: number): void {
  const p = input.pointer;
  if (p && (p.x !== state.lastPx || p.y !== state.lastPy || p.clicked)) {
    state.cx = clamp(p.x, 4, WIDTH - 4);
    state.cy = clamp(p.y, AIM_TOP, AIM_BOTTOM);
    state.lastPx = p.x;
    state.lastPy = p.y;
  }
  const dx = (input.right ? 1 : 0) - (input.left ? 1 : 0);
  const dy = (input.down ? 1 : 0) - (input.up ? 1 : 0);
  if (dx || dy) {
    state.cx = clamp(state.cx + dx * AIM_SPEED * dt, 4, WIDTH - 4);
    state.cy = clamp(state.cy + dy * AIM_SPEED * dt, AIM_TOP, AIM_BOTTOM);
  }
}

function step(state: DefenseState, input: RetroInput, dt: number, random: () => number): void {
  stepParticles(state.particles, dt, 60);
  if (state.phase === "over") return;
  state.elapsed += dt;
  state.shake = Math.max(0, state.shake - dt);
  aim(state, input, dt);

  if (state.phase === "ready") {
    if ((state.timer -= dt) <= 0) state.phase = "play";
    return;
  }
  if (state.phase === "bonus") {
    if ((state.timer -= dt) <= 0) {
      // Spare domes rebuild lost ones; with none standing and no spare the run is over.
      for (let i = 0; i < state.domes.length && state.spares > 0; i += 1) {
        if (!state.domes[i]) { state.domes[i] = 1; state.spares -= 1; }
      }
      if (domesStanding(state) === 0) {
        state.phase = "over";
        return;
      }
      state.wave += 1;
      startWave(state, random);
    }
    return;
  }

  stepWorld(state, dt, random);
  if (state.phase === "lost") {
    if ((state.timer -= dt) <= 0) state.phase = "over";
    return;
  }

  if (input.pressed.b) fire(state, true);
  else if (input.pressed.a || input.pointer?.clicked) fire(state, false);

  // The attack: salvoes from the top, and now and then a seeder.
  if (state.toLaunch > 0) {
    if ((state.salvoTimer -= dt) <= 0) {
      const size = Math.min(state.toLaunch, 1 + Math.floor(random() * Math.min(3, 1 + state.wave / 3)));
      for (let i = 0; i < size; i += 1) launchFromSky(state, random);
      state.salvoTimer = Math.max(1.1, 3 - state.wave * 0.18) + random() * 0.9;
    }
    if (state.wave >= 2 && !state.seeder.active && (state.seederTimer -= dt) <= 0) {
      const f = state.seeder;
      f.active = true;
      const dir = random() < 0.5 ? 1 : -1;
      f.x = dir > 0 ? -16 : WIDTH + 16;
      f.y = 24 + random() * 20;
      f.vx = dir * (34 + random() * 14);
      f.vy = 6 + random() * 6;
      f.t = 0;
      f.dropTimer = 1 + random();
      state.seederTimer = 13 + random() * 9;
    }
  }

  if (domesStanding(state) === 0 && state.spares === 0) {
    state.phase = "lost";
    state.timer = LOST_S;
    return;
  }
  if (state.toLaunch <= 0 && !airborne(state)) endWave(state);
}

function status(state: DefenseState): RetroStatus {
  return { score: state.score, lives: domesStanding(state), level: state.wave, over: state.phase === "over" };
}

// ---- Drawing --------------------------------------------------------------

const SKY = ["#041416", "#06191d", "#081e25", "#0c202d", "#121f35", "#1a1d3a"] as const;
const STARS = starField(50, WIDTH, 150, 41);
const SEEDER = sprite([
  "...#####...",
  ".#########.",
  "###.###.###",
  "###########",
  ".#.#.#.#.#.",
  "#..#..#..#.",
  ".#..#..#..#",
]);

function drawSky(ctx: CanvasRenderingContext2D, info: RetroDrawInfo): void {
  const band = Math.ceil(GROUND_Y / SKY.length);
  for (let i = 0; i < SKY.length; i += 1) {
    ctx.fillStyle = SKY[i];
    ctx.fillRect(0, i * band, WIDTH, band);
  }
  // A faint aurora ribbon high in the sky; it holds still under reduced motion.
  const t = info.reduced ? 0 : info.time;
  ctx.fillStyle = "#1f6a5c";
  ctx.globalAlpha = 0.35;
  for (let x = 0; x < WIDTH; x += 4) {
    const y = 34 + Math.sin(x * 0.03 + t * 0.4) * 8 + Math.sin(x * 0.011 - t * 0.25) * 6;
    ctx.fillRect(x, Math.round(y), 4, 3);
  }
  ctx.globalAlpha = 1;
}

function drawGround(ctx: CanvasRenderingContext2D): void {
  ctx.fillStyle = "#1c1b22";
  ctx.fillRect(0, GROUND_Y, WIDTH, HEIGHT - GROUND_Y);
  ctx.fillStyle = "#2fd3b5";
  ctx.fillRect(0, GROUND_Y, WIDTH, 1);
  ctx.fillStyle = "#2a2932";
  for (let x = 6; x < WIDTH; x += 14) ctx.fillRect(x, GROUND_Y + 6 + (x % 3) * 3, 6, 2);
}

function drawTower(ctx: CanvasRenderingContext2D, state: DefenseState, info: RetroDrawInfo): void {
  // A slim stepped spire with a glowing tip.
  ctx.fillStyle = "#3a3540";
  ctx.fillRect(TOWER_X - 9, GROUND_Y - 6, 18, 6);
  ctx.fillStyle = "#c9a227";
  ctx.fillRect(TOWER_X - 5, GROUND_Y - 16, 10, 10);
  ctx.fillRect(TOWER_X - 3, TOWER_Y + 2, 6, GROUND_Y - 16 - TOWER_Y - 2);
  ctx.fillStyle = "#e0c25a";
  ctx.fillRect(TOWER_X - 1, TOWER_Y + 2, 2, GROUND_Y - 6 - TOWER_Y - 2);
  const blink = state.jammed && !info.reduced && Math.floor(info.time * 6) % 2 === 0;
  ctx.fillStyle = state.jammed ? (blink ? "#ff5a4a" : "#7a2a24") : "#fff4c8";
  ctx.fillRect(TOWER_X - 1, TOWER_Y - 1, 3, 3);
  // The heat meter beside the tower: teal when cool, through amber to red.
  const h = clamp(state.heat, 0, 1);
  const meterX = TOWER_X + 12, meterTop = GROUND_Y - 22, meterH = 20;
  ctx.fillStyle = "#0b0b10";
  ctx.fillRect(meterX, meterTop, 4, meterH);
  ctx.fillStyle = state.jammed ? "#ff5a4a" : h > 0.6 ? "#ffb347" : "#2fd3b5";
  const fill = Math.round(meterH * h);
  ctx.fillRect(meterX, meterTop + meterH - fill, 4, fill);
}

function drawDomes(ctx: CanvasRenderingContext2D, state: DefenseState): void {
  for (let i = 0; i < DOME_X.length; i += 1) {
    const x = DOME_X[i];
    if (state.domes[i]) {
      ctx.fillStyle = "#7fe8ff";
      ctx.globalAlpha = 0.25;
      ctx.beginPath();
      ctx.arc(x, GROUND_Y, DOME_R, Math.PI, 0);
      ctx.closePath();
      ctx.fill();
      ctx.globalAlpha = 1;
      ctx.strokeStyle = "#a8f2ff";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.arc(x, GROUND_Y, DOME_R, Math.PI, 0);
      ctx.stroke();
      // Ribs and a few lit gardens inside.
      ctx.fillStyle = "#a8f2ff";
      ctx.fillRect(x, GROUND_Y - DOME_R, 1, DOME_R);
      ctx.fillRect(x - DOME_R + 1, GROUND_Y - 6, DOME_R * 2 - 2, 1);
      ctx.fillStyle = "#7ed957";
      for (let k = 0; k < 4; k += 1) ctx.fillRect(x - 8 + k * 5, GROUND_Y - 3, 3, 3);
    } else {
      // A broken dome: a jagged stub of glass on a dark base.
      ctx.fillStyle = "#2a2932";
      ctx.fillRect(x - DOME_R, GROUND_Y - 2, DOME_R * 2, 2);
      ctx.fillStyle = "#4a6a74";
      for (let k = 0; k < 5; k += 1) ctx.fillRect(x - DOME_R + 2 + k * 5, GROUND_Y - 3 - ((k * 3 + i) % 4), 2, 2 + ((k * 3 + i) % 4));
    }
  }
}

function drawReticle(ctx: CanvasRenderingContext2D, x: number, y: number, ready: boolean): void {
  ctx.strokeStyle = ready ? "#ffffff" : "#ff8a6a";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.arc(x + 0.5, y + 0.5, 5, 0, Math.PI * 2);
  ctx.stroke();
  ctx.fillStyle = ready ? "#ffffff" : "#ff8a6a";
  ctx.fillRect(x, y, 1, 1);
  ctx.fillRect(x - 9, y, 3, 1);
  ctx.fillRect(x + 7, y, 3, 1);
  ctx.fillRect(x, y - 9, 1, 3);
  ctx.fillRect(x, y + 7, 1, 3);
}

function draw(ctx: CanvasRenderingContext2D, state: DefenseState, info: RetroDrawInfo): void {
  drawSky(ctx, info);
  drawStars(ctx, STARS, info.time, info.reduced, "#bfe8e0");

  ctx.save();
  if (state.shake > 0 && !info.reduced) {
    ctx.translate(Math.round(Math.sin(info.time * 77) * state.shake * 6), Math.round(Math.cos(info.time * 91) * state.shake * 4));
  }
  drawGround(ctx);
  drawDomes(ctx, state);
  drawTower(ctx, state, info);

  // Shards: a magenta crystal with a short fading tail.
  ctx.lineWidth = 1;
  ctx.strokeStyle = "#ff5fd2";
  ctx.globalAlpha = 0.6;
  ctx.beginPath();
  for (const s of state.shards) {
    if (!s.active) continue;
    ctx.moveTo(s.x - s.vx * 0.35, s.y - s.vy * 0.35);
    ctx.lineTo(s.x, s.y);
  }
  ctx.stroke();
  ctx.globalAlpha = 1;
  ctx.fillStyle = "#ffd6f5";
  for (const s of state.shards) {
    if (!s.active) continue;
    const x = Math.round(s.x), y = Math.round(s.y);
    ctx.fillRect(x, y - 2, 1, 5);
    ctx.fillRect(x - 1, y - 1, 3, 3);
  }

  // Our bolts: a gold beam from the tower tip, and a diamond where each will burst.
  ctx.strokeStyle = "#e0a93b";
  ctx.globalAlpha = 0.8;
  ctx.beginPath();
  for (const b of state.bolts) {
    if (!b.active) continue;
    ctx.moveTo(b.ox, b.oy);
    ctx.lineTo(b.x, b.y);
  }
  ctx.stroke();
  ctx.globalAlpha = 1;
  for (const b of state.bolts) {
    if (!b.active) continue;
    ctx.fillStyle = "#fff4c8";
    ctx.fillRect(Math.round(b.x) - 1, Math.round(b.y) - 1, b.r > BOLT_R ? 3 : 2, b.r > BOLT_R ? 3 : 2);
    ctx.fillStyle = "#e0a93b";
    const tx = Math.round(b.tx), ty = Math.round(b.ty);
    ctx.fillRect(tx, ty - 3, 1, 1);
    ctx.fillRect(tx - 3, ty, 1, 1);
    ctx.fillRect(tx + 3, ty, 1, 1);
    ctx.fillRect(tx, ty + 3, 1, 1);
  }

  const f = state.seeder;
  if (f.active) {
    ctx.fillStyle = "#9b7bff";
    const bob = info.reduced ? 0 : Math.round(Math.sin(f.t * 4) * 1.5);
    drawSprite(ctx, SEEDER, f.x - 5, f.y - 3 + bob);
    ctx.fillStyle = "#d8ccff";
    ctx.fillRect(Math.round(f.x) - 2, Math.round(f.y) - 1 + bob, 1, 1);
    ctx.fillRect(Math.round(f.x) + 2, Math.round(f.y) - 1 + bob, 1, 1);
  }

  // Rings: a bright edge around a soft tinted disc; steady colours (no strobing).
  for (const r of state.rings) {
    if (!r.active) continue;
    const rad = ringRadius(r.age, r.r);
    if (rad <= 0.5) continue;
    ctx.fillStyle = r.friendly ? "#2fd3b5" : "#ff7a3a";
    ctx.globalAlpha = 0.22;
    ctx.beginPath();
    ctx.arc(r.x, r.y, rad, 0, Math.PI * 2);
    ctx.fill();
    ctx.globalAlpha = 0.95;
    ctx.strokeStyle = r.friendly ? "#c8fff2" : "#ffc27a";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(r.x, r.y, rad, 0, Math.PI * 2);
    ctx.stroke();
    ctx.globalAlpha = 1;
  }
  ctx.lineWidth = 1;
  drawParticles(ctx, state.particles);
  ctx.restore();

  // The reticle; on the attract screen it drifts lazily across the sky.
  let ax = state.cx, ay = state.cy;
  if (info.idle && state.elapsed === 0 && !info.reduced) {
    ax = WIDTH / 2 + Math.sin(info.time * 0.7) * 90;
    ay = 100 + Math.sin(info.time * 1.1) * 40;
  }
  drawReticle(ctx, Math.round(ax), Math.round(ay), canFire(state, false));

  // Score, wave and spare domes.
  ctx.fillStyle = "#e0a93b";
  drawNumber(ctx, state.score, 6, 5, 2);
  ctx.fillStyle = "#2fd3b5";
  drawNumber(ctx, state.wave, WIDTH - 6, 5, 2, "right");
  ctx.fillStyle = "#a8f2ff";
  for (let i = 0; i < Math.min(state.spares, 5); i += 1) {
    ctx.beginPath();
    ctx.arc(WIDTH - 9 - i * 9, 22, 3, Math.PI, 0);
    ctx.fill();
  }

  if (state.phase === "ready") {
    ctx.fillStyle = "#e0a93b";
    drawNumber(ctx, state.wave, WIDTH / 2, 80, 5, "center");
    // The multiplier as that many small diamonds under the wave number.
    const mult = multiplier(state.wave);
    ctx.fillStyle = "#2fd3b5";
    for (let k = 0; k < mult; k += 1) {
      const x = WIDTH / 2 - (mult - 1) * 6 + k * 12;
      ctx.fillRect(x - 1, 112, 3, 1);
      ctx.fillRect(x - 2, 113, 5, 1);
      ctx.fillRect(x - 1, 114, 3, 1);
    }
  } else if (state.phase === "bonus") {
    // The tally: domes saved with their points, and the full-colony star when earned.
    const mult = multiplier(state.wave);
    ctx.fillStyle = "#a8f2ff";
    ctx.beginPath();
    ctx.arc(WIDTH / 2 - 56, 90, 5, Math.PI, 0);
    ctx.fill();
    drawNumber(ctx, state.bonusDomes, WIDTH / 2 - 44, 84, 1);
    ctx.fillStyle = "#e0a93b";
    drawNumber(ctx, state.bonusDomes * DOME_BONUS * mult, WIDTH / 2 + 60, 84, 1, "right");
    if (state.bonusFull) {
      ctx.fillStyle = "#2fd3b5";
      ctx.fillRect(WIDTH / 2 - 57, 100, 3, 7);
      ctx.fillRect(WIDTH / 2 - 59, 102, 7, 3);
      ctx.fillStyle = "#e0a93b";
      drawNumber(ctx, FULL_COLONY_BONUS * mult, WIDTH / 2 + 60, 100, 1, "right");
    }
  }
}

const cityDefense: RetroGame<DefenseState> = {
  id: "city-defense",
  width: WIDTH,
  height: HEIGHT,
  create,
  step,
  draw,
  status,
  pointer: true,
};

export default cityDefense;
