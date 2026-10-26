/**
 * The duel simulation: a pure, deterministic fixed-tick step.
 *
 *   step(state, inputs, ctx) -> { state, events }
 *
 * - `state` is plain JSON (MatchState); the input state is never mutated.
 * - `inputs[slot]` is that player's InputCommand for this tick, or null to
 *   repeat their last one (held buttons stay held, presses are not repeated).
 * - No clock, no Math.random: randomness is hashed from the match seed and
 *   the shot or bolt it belongs to, so a client predicting its own shot gets
 *   the server's spread.
 * - Continuous values are quantised at the end of every step, so a snapshot
 *   on the wire carries the exact state and a client's replay matches the
 *   server's bit for bit.
 *
 * Order inside a tick: aim and presses for every player, then shields,
 * dodges, vents and sights, then movement, then firing, then bolts, then
 * regeneration and timers, then the round rules.
 */
import { buildArena, isWalkable, moveBody, nearestWalkable, raycastWorld, type Arena, type ArenaDef } from "./arena";
import { REACTOR_ARENA } from "./arenaReactor";
import { PITCH_LIMIT, sanitizeInput } from "./input";
import { approach, clamp, DEG, dirFromAngles, forwardX, forwardZ, lerp, q, rightX, rightZ, wrapAngle } from "./math";
import { sweepCapsule, sweepCylinder, sweepOut } from "./raycast";
import { hash2, rand01, SALT } from "./rng";
import { DEFAULT_TUNING, TICK_DT, tuningHash, type CombatTuning } from "./tuning";
import {
  BTN, EDGE_BUTTONS,
  type BoltState, type CombatEvent, type EndReason, type InputCommand, type MatchConfig, type MatchState, type PlayerState, type PlayerStats,
} from "./types";

export interface SimContext {
  arena: Arena;
  tuning: CombatTuning;
}

export function createContext(def: ArenaDef = REACTOR_ARENA, tuning: CombatTuning = DEFAULT_TUNING): SimContext {
  return { arena: buildArena(def, tuning.body.radius), tuning };
}

/**
 * Everything both ends of a duel must agree on for prediction to match the
 * server: the tuning and the arena (a re-laid-out room predicts walls in the
 * wrong places). Compared in the handshake.
 */
export function rulesHash(ctx: SimContext): number {
  const text = JSON.stringify(ctx.arena.def);
  let h = tuningHash(ctx.tuning);
  for (let i = 0; i < text.length; i++) h = hash2(h, text.charCodeAt(i));
  return h >>> 0;
}

export interface MatchSetup {
  seed: number;
  playerIds: readonly string[];
  config?: Partial<MatchConfig>;
}

export interface StepResult {
  state: MatchState;
  events: CombatEvent[];
}

/** Chest height used to aim parries and by the bots. */
export const CHEST_HEIGHT = 1.15;

// ---------------------------------------------------------------- creation

function emptyStats(): PlayerStats {
  return { shots: 0, hits: 0, headshots: 0, damageDealt: 0, damageTaken: 0, blocks: 0, parries: 0, deflects: 0, dodges: 0, overheats: 0, perfectVents: 0, ventMisses: 0, kills: 0 };
}

function newPlayer(slot: number, id: string): PlayerState {
  return {
    slot, id, side: slot, x: 0, z: 0, vx: 0, vz: 0, yaw: 0, pitch: 0, recoilPitch: 0, recoilYaw: 0,
    alive: true, health: 0, lastDamageTick: -100000, mx: 0, my: 0, buttons: 0, lastSeq: -1,
    heat: 0, lastShotTick: -100000, nextShotTick: 0, bloom: 0, shotCount: 0,
    ventStart: -1, ventEnd: -1, ventWinStart: -1, ventWinEnd: -1, ventFromHeat: 0, ventForced: false, ventAttempted: false,
    ads: 0, sprinting: false, sprintEndTick: -100000,
    shieldUp: false, shieldEnergy: 0, shieldRaisedAt: -100000, shieldLoweredAt: -100000, shieldBrokenUntil: 0, shieldNeedsRelease: false, shieldParryUsed: false, parryReadyAt: 0,
    dodgeStart: -100000, dodgeUntil: -100000, dodgeReadyAt: 0, dodgeDx: 0, dodgeDz: 0,
    stats: emptyStats(),
  };
}

/** Which side (spawn) a slot takes in a round: alternating, the first round by the seed. */
export function sideFor(seed: number, slot: number, round: number): number {
  return (slot + round - 1 + (hash2(seed, 0x51de) & 1)) % 2;
}

function placeForRound(s: MatchState, ctx: SimContext): void {
  const t = ctx.tuning;
  for (const p of s.players) {
    p.side = sideFor(s.seed, p.slot, s.round);
    const sp = ctx.arena.def.spawns[p.side];
    p.x = sp.x; p.z = sp.z; p.vx = 0; p.vz = 0; p.yaw = sp.yaw; p.pitch = 0;
    p.recoilPitch = 0; p.recoilYaw = 0;
    p.alive = true; p.health = t.health.max; p.lastDamageTick = -100000;
    p.heat = 0; p.lastShotTick = -100000; p.nextShotTick = 0; p.bloom = 0;
    p.ventStart = -1; p.ventEnd = -1; p.ventWinStart = -1; p.ventWinEnd = -1; p.ventFromHeat = 0; p.ventForced = false; p.ventAttempted = false;
    p.ads = 0; p.sprinting = false; p.sprintEndTick = -100000;
    p.shieldUp = false; p.shieldEnergy = t.shield.energyMax; p.shieldRaisedAt = -100000; p.shieldLoweredAt = -100000;
    p.shieldBrokenUntil = 0; p.shieldNeedsRelease = (p.buttons & BTN.SHIELD) !== 0;
    p.shieldParryUsed = false; p.parryReadyAt = 0;
    p.dodgeStart = -100000; p.dodgeUntil = -100000; p.dodgeReadyAt = 0; p.dodgeDx = 0; p.dodgeDz = 0;
  }
  s.bolts = [];
}

export function createMatch(ctx: SimContext, setup: MatchSetup): MatchState {
  if (setup.playerIds.length !== 2) throw new Error("A duel takes exactly two players");
  const m = ctx.tuning.match;
  const config: MatchConfig = {
    roundsToWin: m.roundsToWin, maxRounds: m.maxRounds, countdownTicks: m.countdownTicks,
    roundEndTicks: m.roundEndTicks, roundTimeLimitTicks: m.roundTimeLimitTicks,
    surgeAfterTicks: m.surgeAfterTicks, pingEveryTicks: m.pingEveryTicks, ...setup.config,
  };
  const s: MatchState = {
    v: 1, seed: setup.seed >>> 0, tick: 0, phase: "countdown", phaseStart: 0, phaseEndsAt: config.countdownTicks,
    round: 1, roundStartTick: 0, scores: [0, 0], winner: null, endReason: null, config,
    players: setup.playerIds.map((id, slot) => newPlayer(slot, id)),
    bolts: [], nextBoltId: 1, history: { ticks: [], poses: [] },
  };
  placeForRound(s, ctx);
  quantise(s);
  return s;
}

// ---------------------------------------------------------------- helpers

export function copyState(s: MatchState): MatchState {
  return {
    ...s,
    scores: s.scores.slice(),
    players: s.players.map((p) => ({ ...p, stats: { ...p.stats } })),
    bolts: s.bolts.map((b) => ({ ...b })),
    history: { ticks: s.history.ticks.slice(), poses: s.history.poses.slice() },
  };
}

/** Damage of a bolt after flying `dist` metres (before the headshot factor). */
export function boltDamage(t: CombatTuning, dist: number, mul: number): number {
  const b = t.blaster;
  const k = clamp((dist - b.falloffStart) / (b.falloffEnd - b.falloffStart), 0, 1);
  return lerp(b.damageNear, b.damageFar, k) * mul;
}

/** Current cone half-angle of a player's blaster, degrees (the crosshair size). */
export function spreadDeg(t: CombatTuning, p: PlayerState): number {
  const b = t.blaster;
  const speed = Math.min(1, Math.hypot(p.vx, p.vz) / t.move.run);
  return lerp(b.hipSpreadDeg, b.adsSpreadDeg, p.ads) + p.bloom + lerp(b.moveSpreadHipDeg, b.moveSpreadAdsDeg, p.ads) * speed;
}

/** Muzzle position of a player (world). */
export function muzzleOf(t: CombatTuning, p: { x: number; z: number; yaw: number }): { x: number; y: number; z: number } {
  const bd = t.body;
  return {
    x: p.x + forwardX(p.yaw) * bd.muzzleForward + rightX(p.yaw) * bd.muzzleRight,
    y: bd.muzzleHeight,
    z: p.z + forwardZ(p.yaw) * bd.muzzleForward + rightZ(p.yaw) * bd.muzzleRight,
  };
}

/** Why a player cannot fire right now, or null. */
export function fireBlock(t: CombatTuning, p: PlayerState, tick: number): "shield" | "dodge" | "vent" | "sprint" | "cycle" | null {
  if (p.shieldUp) return "shield";
  if (tick < p.dodgeUntil + t.dodge.recoverTicks) return "dodge";
  if (p.ventStart >= 0) return "vent";
  if (p.sprinting || tick < p.sprintEndTick + t.move.sprintToFireTicks) return "sprint";
  if (tick < p.nextShotTick) return "cycle";
  return null;
}

export function canRaiseShield(t: CombatTuning, p: PlayerState, tick: number): boolean {
  return p.alive && tick >= p.shieldBrokenUntil && p.shieldEnergy >= t.shield.raiseMinEnergy
    && tick - p.shieldLoweredAt >= t.shield.reRaiseTicks && tick >= p.dodgeUntil;
}

/** Parry window open for this raise: right after raising, and not locked by a whiff. */
export function parryOpen(t: CombatTuning, p: PlayerState, tick: number): boolean {
  return p.shieldUp && p.shieldRaisedAt >= p.parryReadyAt && tick - p.shieldRaisedAt <= t.shield.parryWindowTicks;
}

function lowerShield(t: CombatTuning, p: PlayerState, tick: number, ev: CombatEvent[]): void {
  if (!p.shieldUp) return;
  p.shieldUp = false;
  p.shieldLoweredAt = tick;
  // A raise whose window met nothing was a whiff: no parry window for a while.
  if (!p.shieldParryUsed && p.shieldRaisedAt >= p.parryReadyAt) p.parryReadyAt = tick + t.shield.parryWhiffLockTicks;
  ev.push({ type: "shield_down", tick, player: p.slot });
}

function breakShield(t: CombatTuning, p: PlayerState, tick: number, ev: CombatEvent[]): void {
  p.shieldEnergy = 0;
  p.shieldUp = false;
  p.shieldLoweredAt = tick;
  p.shieldBrokenUntil = tick + t.shield.brokenTicks;
  p.shieldNeedsRelease = true;
  ev.push({ type: "shield_break", tick, player: p.slot });
}

function endMatchIn(s: MatchState, winner: number, reason: EndReason, ev: CombatEvent[]): void {
  if (s.phase === "ended") return;
  s.phase = "ended";
  s.phaseStart = s.tick + 1;
  s.phaseEndsAt = s.tick + 1;
  s.winner = winner;
  s.endReason = reason;
  s.bolts = [];
  ev.push({ type: "match_end", tick: s.tick, winner, reason, scores: s.scores.slice() });
}

/**
 * End a match from outside the step (a player left, the server cancelled).
 * Pure: returns a new state.
 */
export function endMatch(state: MatchState, winner: number, reason: EndReason): StepResult {
  const s = copyState(state);
  const events: CombatEvent[] = [];
  endMatchIn(s, winner, reason, events);
  return { state: s, events };
}

// ---------------------------------------------------------------- step

export function step(state: MatchState, inputs: ReadonlyArray<InputCommand | null | undefined>, ctx: SimContext): StepResult {
  const s = copyState(state);
  const ev: CombatEvent[] = [];
  const T = s.tick;
  if (s.phase === "ended") {
    s.tick = T + 1;
    return { state: s, events: ev };
  }
  if (s.phase === "countdown" && T === s.phaseStart) ev.push({ type: "countdown", tick: T, round: s.round, endsAt: s.phaseEndsAt });

  // 1. Aim and buttons.
  const pressedOf: number[] = [];
  const cmdOf: (InputCommand | null)[] = [];
  for (const p of s.players) {
    const raw = inputs[p.slot] ?? null;
    // Legal commands pass unchanged; anything else (a modified client) is made legal.
    const inp = raw ? sanitizeInput(raw, p.yaw, p.pitch) : null;
    cmdOf.push(inp);
    const buttons = inp ? inp.buttons : p.buttons & ~EDGE_BUTTONS;
    pressedOf.push(buttons & ~p.buttons);
    p.buttons = buttons;
    if (inp) {
      p.mx = inp.mx;
      p.my = inp.my;
      p.yaw = wrapAngle(inp.yaw);
      p.pitch = clamp(inp.pitch, -PITCH_LIMIT, PITCH_LIMIT);
      p.lastSeq = inp.seq;
    }
    if ((p.buttons & BTN.SHIELD) === 0) p.shieldNeedsRelease = false;
  }
  for (const p of s.players) {
    if (pressedOf[p.slot] & BTN.FORFEIT) {
      endMatchIn(s, 1 - p.slot, "forfeit", ev);
      return finish(s, ev, ctx);
    }
  }

  if (s.phase === "live") {
    const t = ctx.tuning;
    // 2. Shield, dodge, vent, sights, sprint.
    for (const p of s.players) {
      if (!p.alive) continue;
      const seq = p.lastSeq;
      const pressed = pressedOf[p.slot];
      const held = p.buttons;
      // Dodge first: it drops the shield.
      if ((pressed & BTN.DODGE) && T >= p.dodgeReadyAt && T >= p.dodgeUntil) {
        let wx = rightX(p.yaw) * p.mx + forwardX(p.yaw) * p.my;
        let wz = rightZ(p.yaw) * p.mx + forwardZ(p.yaw) * p.my;
        let l = Math.hypot(wx, wz);
        if (l < 0.1) { wx = -forwardX(p.yaw); wz = -forwardZ(p.yaw); l = 1; }
        p.dodgeDx = wx / l;
        p.dodgeDz = wz / l;
        p.dodgeStart = T;
        p.dodgeUntil = T + t.dodge.durationTicks;
        p.dodgeReadyAt = T + t.dodge.cooldownTicks;
        if (p.sprinting) { p.sprinting = false; p.sprintEndTick = T; }
        if (p.shieldUp) { lowerShield(t, p, T, ev); p.shieldNeedsRelease = true; }
        p.stats.dodges++;
        ev.push({ type: "dodge", tick: T, player: p.slot, seq, dx: q(p.dodgeDx, 1000), dz: q(p.dodgeDz, 1000) });
      }
      const dodging = T < p.dodgeUntil;
      // Shield: up while held (after a fresh press once it broke or a dodge dropped it).
      const wantUp = (held & BTN.SHIELD) !== 0 && !p.shieldNeedsRelease;
      if (p.shieldUp && !wantUp) lowerShield(t, p, T, ev);
      else if (!p.shieldUp && wantUp && canRaiseShield(t, p, T)) {
        p.shieldUp = true;
        p.shieldRaisedAt = T;
        p.shieldParryUsed = false;
        p.shieldEnergy = Math.max(0, p.shieldEnergy - t.shield.raiseCost);
        if (p.sprinting) { p.sprinting = false; p.sprintEndTick = T; }
        ev.push({ type: "shield_up", tick: T, player: p.slot, seq });
      }
      // Vent: start one, or time the press inside a running one.
      if (pressed & BTN.VENT) {
        if (p.ventStart >= 0) {
          if (!p.ventAttempted && T >= p.ventWinStart && T <= p.ventWinEnd) {
            p.ventStart = -1;
            p.heat = 0;
            p.nextShotTick = Math.min(p.nextShotTick, T + 1);
            p.stats.perfectVents++;
            ev.push({ type: "vent_perfect", tick: T, player: p.slot, seq });
            ev.push({ type: "vent_end", tick: T, player: p.slot });
          } else if (!p.ventAttempted && T > p.ventStart) {
            p.ventAttempted = true;
            p.stats.ventMisses++;
            ev.push({ type: "vent_miss", tick: T, player: p.slot, seq });
          }
        } else if (p.heat >= 5) {
          startVent(t, p, T, false, seq, ev);
        }
      }
      // Sights and sprint.
      const adsWanted = (held & BTN.ADS) !== 0 && !p.shieldUp && !dodging && !p.sprinting;
      p.ads = approach(p.ads, adsWanted ? 1 : 0, adsWanted ? 1 / t.blaster.adsInTicks : 1 / t.blaster.adsOutTicks);
      const mlen = Math.hypot(p.mx, p.my);
      const sprintOk = (held & BTN.SPRINT) !== 0 && mlen > 0.3 && p.my / mlen >= Math.cos(t.move.sprintConeDeg * DEG)
        && !p.shieldUp && !dodging && (held & (BTN.FIRE | BTN.ADS)) === 0;
      if (p.sprinting && !sprintOk) p.sprintEndTick = T;
      p.sprinting = sprintOk;
    }
    // 3. Movement.
    for (const p of s.players) if (p.alive) movePlayer(s, p, ctx, T);
    // 4. Firing: every player's trigger first, then the lag-compensated
    // fast-forward of the new bolts, so a rewound bolt can never stop the
    // other player's shot of the same tick (no advantage for slot 0).
    const fired: { bolt: BoltState; cmd: InputCommand | null }[] = [];
    for (const p of s.players) {
      if (!p.alive || (p.buttons & BTN.FIRE) === 0 || fireBlock(t, p, T) !== null) continue;
      fired.push({ bolt: fire(s, p, ctx, T, ev), cmd: cmdOf[p.slot] });
    }
    for (const f of fired) rewindBolt(s, f.bolt, ctx, T, f.cmd, ev);
    // 5. Bolts.
    updateBolts(s, ctx, T, ev);
    // 6. Heat, bloom, recoil, shield and health regeneration (no health back once the reactor surges).
    const surge = surgeActive(s, T);
    for (const p of s.players) if (p.alive) regenerate(t, p, T, ev, !surge);
    if (surge) {
      const since = T - s.roundStartTick - s.config.surgeAfterTicks;
      if (since === 0) ev.push({ type: "surge", tick: T, round: s.round });
      if (since % s.config.pingEveryTicks === 0) {
        for (const p of s.players) if (p.alive) ev.push({ type: "ping", tick: T, player: p.slot, x: q(p.x, 100), z: q(p.z, 100) });
      }
    }
  }

  // 7. Round rules.
  rules(s, ctx, T, ev);
  return finish(s, ev, ctx);
}

function finish(s: MatchState, ev: CombatEvent[], ctx: SimContext): StepResult {
  quantise(s);
  // Pose history for lag compensation.
  const h = s.history;
  h.ticks.push(s.tick);
  const pose: number[] = [];
  for (const p of s.players) pose.push(p.x, p.z);
  h.poses.push(pose);
  const keep = ctx.tuning.lagComp.historyTicks;
  if (h.ticks.length > keep) { h.ticks.splice(0, h.ticks.length - keep); h.poses.splice(0, h.poses.length - keep); }
  s.tick += 1;
  return { state: s, events: ev };
}

function startVent(t: CombatTuning, p: PlayerState, T: number, forced: boolean, seq: number, ev: CombatEvent[]): void {
  const b = t.blaster;
  const dur = forced ? b.overheatTicks : Math.round(b.ventBaseTicks + b.ventTicksPerHeat * p.heat);
  p.ventStart = T;
  p.ventEnd = T + dur;
  if (forced) {
    p.ventWinStart = T + b.overheatWindow[0];
    p.ventWinEnd = T + b.overheatWindow[1];
  } else {
    p.ventWinStart = T + Math.round(dur * b.ventWindowFrac[0]);
    p.ventWinEnd = T + Math.round(dur * b.ventWindowFrac[1]);
  }
  p.ventFromHeat = p.heat;
  p.ventForced = forced;
  p.ventAttempted = false;
  ev.push({ type: "vent_start", tick: T, player: p.slot, seq, forced, end: p.ventEnd, winStart: p.ventWinStart, winEnd: p.ventWinEnd });
}

function movePlayer(s: MatchState, p: PlayerState, ctx: SimContext, T: number): void {
  const t = ctx.tuning;
  const dt = TICK_DT;
  if (T < p.dodgeUntil) {
    const n = t.dodge.durationTicks;
    const k = (T - p.dodgeStart + 0.5) / n;
    const v0 = (2 * t.dodge.distance) / (n * dt);
    const v = v0 * Math.max(0, 1 - k);
    p.vx = p.dodgeDx * v;
    p.vz = p.dodgeDz * v;
  } else {
    const wx = rightX(p.yaw) * p.mx + forwardX(p.yaw) * p.my;
    const wz = rightZ(p.yaw) * p.mx + forwardZ(p.yaw) * p.my;
    let max: number;
    if (p.sprinting) max = t.move.sprint;
    else {
      max = t.move.run * lerp(1, t.move.backMul, Math.max(0, -p.my)) * lerp(1, t.move.adsMul, p.ads);
      if (p.shieldUp) max *= t.move.shieldMul;
    }
    const tx = wx * max;
    const tz = wz * max;
    const dvx = tx - p.vx;
    const dvz = tz - p.vz;
    const dv = Math.hypot(dvx, dvz);
    const speeding = tx * tx + tz * tz > p.vx * p.vx + p.vz * p.vz;
    const lim = (speeding ? t.move.accel : t.move.decel) * dt;
    if (dv <= lim) { p.vx = tx; p.vz = tz; } else { p.vx += (dvx / dv) * lim; p.vz += (dvz / dv) * lim; }
  }
  const minD = 2 * t.body.radius;
  const others = s.players.filter((o) => o !== p && o.alive);
  const free = others.length === 0 ? undefined : (x: number, z: number) => {
    for (const o of others) {
      const dn = (x - o.x) ** 2 + (z - o.z) ** 2;
      if (dn < minD * minD && dn < (p.x - o.x) ** 2 + (p.z - o.z) ** 2) return false;
    }
    return true;
  };
  const r = moveBody(ctx.arena, p.x, p.z, p.vx * dt, p.vz * dt, free);
  if (r.blockedX) p.vx = 0;
  if (r.blockedZ) p.vz = 0;
  p.x = r.x;
  p.z = r.z;
  if (!isWalkable(ctx.arena, p.x, p.z)) {
    const n = nearestWalkable(ctx.arena, p.x, p.z, 3);
    if (n) { p.x = n.x; p.z = n.z; }
  }
}

function fire(s: MatchState, p: PlayerState, ctx: SimContext, T: number, ev: CombatEvent[]): BoltState {
  const t = ctx.tuning;
  const b = t.blaster;
  const shot = p.shotCount++;
  const aimYaw = p.yaw + p.recoilYaw * DEG;
  const aimPitch = p.pitch + p.recoilPitch * DEG;
  const cone = spreadDeg(t, p) * DEG;
  const u1 = rand01(s.seed, p.slot, shot, SALT.spreadA);
  const u2 = rand01(s.seed, p.slot, shot, SALT.spreadB);
  const u3 = rand01(s.seed, p.slot, shot, SALT.spreadC);
  const rad = cone * Math.abs(u1 + u2 - 1);
  const ang = 2 * Math.PI * u3;
  const yaw = aimYaw + (rad * Math.cos(ang)) / Math.max(0.2, Math.cos(aimPitch));
  const pitch = aimPitch + rad * Math.sin(ang);
  const d = dirFromAngles(yaw, pitch);
  const m = muzzleOf(t, p);
  // A muzzle poking through a wall fires from the body instead.
  let ox = m.x, oy = m.y, oz = m.z;
  if (raycastWorld(ctx.arena, p.x, m.y, p.z, m.x, m.y, m.z)) { ox = p.x; oz = p.z; }
  const bolt: BoltState = {
    id: s.nextBoltId++, owner: p.slot, shooter: p.slot, kind: "shot",
    x: ox, y: oy, z: oz, vx: d.x * b.boltSpeed, vy: d.y * b.boltSpeed, vz: d.z * b.boltSpeed,
    damageMul: 1, traveled: 0, bornTick: T, reflections: 0,
  };
  s.bolts.push(bolt);
  p.lastShotTick = T;
  p.nextShotTick = T + b.fireIntervalTicks;
  p.bloom = Math.min(lerp(b.bloomMaxHipDeg, b.bloomMaxAdsDeg, p.ads), p.bloom + lerp(b.bloomPerShotHipDeg, b.bloomPerShotAdsDeg, p.ads));
  p.recoilPitch += lerp(b.recoilPitchHipDeg, b.recoilPitchAdsDeg, p.ads);
  p.recoilYaw += (rand01(s.seed, p.slot, shot, SALT.recoilYaw) * 2 - 1) * b.recoilYawDeg;
  p.heat += b.heatPerShot;
  p.stats.shots++;
  ev.push({ type: "shot", tick: T, player: p.slot, bolt: bolt.id, shot, x: q(m.x, 1000), y: q(m.y, 1000), z: q(m.z, 1000), dx: q(d.x, 10000), dy: q(d.y, 10000), dz: q(d.z, 10000), heat: q(Math.min(p.heat, 100), 100), ads: p.ads > 0.5 });
  if (p.heat >= 100) {
    p.heat = 100;
    p.stats.overheats++;
    ev.push({ type: "overheat", tick: T, player: p.slot, shot });
    startVent(t, p, T, true, p.lastSeq, ev);
  }
  return bolt;
}

/**
 * Lag compensation: the shooter saw the world `rewind` ticks ago, so the new
 * bolt is flown through those ticks against the poses of that time.
 */
function rewindBolt(s: MatchState, bolt: BoltState, ctx: SimContext, T: number, cmd: InputCommand | null, ev: CombatEvent[]): void {
  const rewind = cmd && cmd.viewTick >= 0 ? clamp(T - cmd.viewTick, 0, ctx.tuning.lagComp.maxRewindTicks) : 0;
  for (let k = rewind; k >= 1; k--) {
    const poses = historyAt(s, T - k);
    if (!advanceBolt(s, bolt, ctx, T, ev, poses)) {
      s.bolts.splice(s.bolts.indexOf(bolt), 1);
      break;
    }
  }
}

/** Player positions at a past tick, or null when it is not in the history. */
export function historyAt(s: MatchState, tick: number): number[] | null {
  const i = s.history.ticks.indexOf(tick);
  return i < 0 ? null : s.history.poses[i];
}

const swShield = sweepOut();
const swBody = sweepOut();

/** Fly a bolt one tick. False when it is gone. `poses` overrides where the players stand (lag compensation). */
function advanceBolt(s: MatchState, b: BoltState, ctx: SimContext, T: number, ev: CombatEvent[], poses: number[] | null): boolean {
  const t = ctx.tuning;
  const dt = TICK_DT;
  const ax = b.x, ay = b.y, az = b.z;
  const dx = b.vx * dt, dy = b.vy * dt, dz = b.vz * dt;
  const segLen = Math.hypot(dx, dy, dz);
  let bestT = 2;
  let what: "world" | "shield" | "body" = "world";
  let victim: PlayerState | null = null;
  let nx = 0, ny = 0, nz = 0;
  const world = raycastWorld(ctx.arena, ax, ay, az, ax + dx, ay + dy, az + dz);
  if (world) { bestT = world.t; nx = world.nx; ny = world.ny; nz = world.nz; }
  const hitR = t.body.hitRadius + t.blaster.boltRadius;
  for (const o of s.players) {
    if (!o.alive || o.slot === b.owner) continue;
    if (T - o.dodgeStart < t.dodge.iframeTicks && T < o.dodgeUntil) continue;
    const ox = poses ? poses[o.slot * 2] : o.x;
    const oz = poses ? poses[o.slot * 2 + 1] : o.z;
    if (o.shieldUp) {
      const ts = sweepCylinder(ax, ay, az, dx, dy, dz, ox, oz, t.shield.radius, 0, t.shield.height, swShield);
      if (ts >= 0 && ts < bestT) {
        const px = ax + dx * ts - ox;
        const pz = az + dz * ts - oz;
        const off = Math.abs(wrapAngle(Math.atan2(px, pz) - o.yaw));
        if (off <= t.shield.arcHalfDeg * DEG) {
          bestT = ts; what = "shield"; victim = o;
          const l = Math.hypot(px, pz) || 1;
          nx = px / l; ny = 0; nz = pz / l;
          continue;
        }
      }
    }
    const tb = sweepCapsule(ax, ay, az, dx, dy, dz, ox, oz, t.body.hitBottom, t.body.hitTop, hitR, swBody);
    if (tb >= 0 && tb < bestT) { bestT = tb; what = "body"; victim = o; }
  }
  if (bestT > 1) {
    b.x = ax + dx; b.y = ay + dy; b.z = az + dz;
    b.traveled += segLen;
    if (b.traveled > t.blaster.boltMaxRange || b.y < -4) {
      ev.push({ type: "bolt_expire", tick: T, bolt: b.id });
      return false;
    }
    return true;
  }
  const hx = ax + dx * bestT, hy = ay + dy * bestT, hz = az + dz * bestT;
  const dist = b.traveled + segLen * bestT;
  if (what === "world" && world) {
    if (world.surface === "exit") ev.push({ type: "bolt_expire", tick: T, bolt: b.id });
    else ev.push({ type: "impact", tick: T, bolt: b.id, surface: world.surface, collider: world.collider, x: q(hx, 1000), y: q(hy, 1000), z: q(hz, 1000), nx, ny, nz });
    return false;
  }
  const o = victim as PlayerState;
  const shooter = s.players[b.owner];
  if (what === "body") {
    const head = hy >= t.body.headFrom;
    const dmg = boltDamage(t, dist, b.damageMul) * (head ? t.health.headshotMul : 1);
    o.health -= dmg;
    o.lastDamageTick = T;
    o.stats.damageTaken += dmg;
    if (shooter) {
      shooter.stats.hits++;
      shooter.stats.damageDealt += dmg;
      if (head) shooter.stats.headshots++;
    }
    ev.push({ type: "hit", tick: T, bolt: b.id, owner: b.owner, target: o.slot, damage: q(dmg, 100), headshot: head, health: q(Math.max(0, o.health), 100), x: q(hx, 1000), y: q(hy, 1000), z: q(hz, 1000), fromX: q(ax, 1000), fromZ: q(az, 1000) });
    if (o.health <= 0) {
      o.health = 0;
      o.alive = false;
      o.shieldUp = false;
      o.vx = 0; o.vz = 0;
      if (shooter) shooter.stats.kills++;
      ev.push({ type: "death", tick: T, player: o.slot, killer: b.owner });
    }
    return false;
  }
  // Shield.
  const speed = Math.hypot(b.vx, b.vy, b.vz);
  if (parryOpen(t, o, T)) o.shieldParryUsed = true;
  if (parryOpen(t, o, T) && b.reflections < t.shield.maxReflections) {
    // Perfect parry: straight back at whoever sent it.
    const target = s.players[b.owner];
    let ux: number, uy: number, uz: number;
    if (target && target.alive) {
      const tx = target.x - hx, ty = CHEST_HEIGHT - hy, tz = target.z - hz;
      const l = Math.hypot(tx, ty, tz) || 1;
      const yaw = Math.atan2(tx, tz) + (rand01(s.seed, b.id, T, SALT.parryYaw) * 2 - 1) * t.shield.parryAimErrorDeg * DEG;
      const pitch = Math.asin(clamp(ty / l, -1, 1)) + (rand01(s.seed, b.id, T, SALT.parryPitch) * 2 - 1) * t.shield.parryAimErrorDeg * DEG;
      const d = dirFromAngles(yaw, pitch);
      ux = d.x; uy = d.y; uz = d.z;
    } else {
      const dot = (b.vx * nx + b.vz * nz) / (speed || 1);
      ux = b.vx / speed - 2 * dot * nx; uy = b.vy / speed; uz = b.vz / speed - 2 * dot * nz;
    }
    const v = Math.min(speed * t.shield.parrySpeedMul, t.blaster.boltSpeed * 1.6);
    const from = b.owner;
    b.owner = o.slot;
    b.kind = "parry";
    b.reflections++;
    b.damageMul *= t.shield.parryDamageMul;
    b.traveled = 0;
    b.vx = ux * v; b.vy = uy * v; b.vz = uz * v;
    b.x = hx + ux * 0.05; b.y = hy + uy * 0.05; b.z = hz + uz * 0.05;
    o.stats.parries++;
    ev.push({ type: "parry", tick: T, player: o.slot, bolt: b.id, target: from, x: q(hx, 1000), y: q(hy, 1000), z: q(hz, 1000) });
    return true;
  }
  const cost = boltDamage(t, dist, b.damageMul) * t.shield.blockCostPerDamage;
  o.shieldEnergy -= cost;
  o.stats.blocks++;
  const broke = o.shieldEnergy <= 0;
  if (broke) breakShield(t, o, T, ev);
  if (!broke && rand01(s.seed, b.id, T, SALT.deflectRoll) < t.shield.deflectChance) {
    // Glance off at a seeded angle around the mirror direction.
    const dot = (b.vx * nx + b.vz * nz) / speed;
    const rx = b.vx / speed - 2 * dot * nx;
    const rz = b.vz / speed - 2 * dot * nz;
    const yaw = Math.atan2(rx, rz) + (rand01(s.seed, b.id, T, SALT.deflectYaw) * 2 - 1) * t.shield.deflectSpreadDeg * DEG;
    const pitch = Math.asin(clamp(b.vy / speed, -1, 1)) * 0.5 + (rand01(s.seed, b.id, T, SALT.deflectPitch) * 2 - 1) * 8 * DEG;
    const d = dirFromAngles(yaw, pitch);
    b.owner = o.slot;
    b.kind = "deflect";
    b.reflections++;
    b.damageMul *= t.shield.deflectDamageMul;
    b.traveled = 0;
    b.vx = d.x * speed; b.vy = d.y * speed; b.vz = d.z * speed;
    b.x = hx + d.x * 0.05; b.y = hy + d.y * 0.05; b.z = hz + d.z * 0.05;
    o.stats.deflects++;
    ev.push({ type: "deflect", tick: T, player: o.slot, bolt: b.id, x: q(hx, 1000), y: q(hy, 1000), z: q(hz, 1000) });
    return true;
  }
  ev.push({ type: "block", tick: T, player: o.slot, bolt: b.id, energy: q(Math.max(0, o.shieldEnergy), 100), x: q(hx, 1000), y: q(hy, 1000), z: q(hz, 1000) });
  return false;
}

function updateBolts(s: MatchState, ctx: SimContext, T: number, ev: CombatEvent[]): void {
  const keep: BoltState[] = [];
  for (const b of s.bolts) {
    if (advanceBolt(s, b, ctx, T, ev, null)) keep.push(b);
  }
  s.bolts = keep;
}

/** True once the round has run long enough for the reactor surge. */
export function surgeActive(s: MatchState, tick: number): boolean {
  return s.phase === "live" && tick - s.roundStartTick >= s.config.surgeAfterTicks;
}

function regenerate(t: CombatTuning, p: PlayerState, T: number, ev: CombatEvent[], healthRegen: boolean): void {
  const dt = TICK_DT;
  const b = t.blaster;
  if (p.ventStart >= 0) {
    if (T >= p.ventEnd) {
      p.ventStart = -1;
      p.heat = 0;
      ev.push({ type: "vent_end", tick: T, player: p.slot });
    } else {
      p.heat = p.ventFromHeat * (1 - (T - p.ventStart) / (p.ventEnd - p.ventStart));
    }
  } else if (T - p.lastShotTick > b.heatCoolDelayTicks) {
    p.heat = Math.max(0, p.heat - b.heatCoolPerSec * dt);
  }
  if (T - p.lastShotTick > b.bloomRecoverDelayTicks) p.bloom = Math.max(0, p.bloom - b.bloomRecoverDegPerSec * dt);
  if (T - p.lastShotTick > 3) {
    p.recoilPitch = approach(p.recoilPitch, 0, b.recoilRecoverDegPerSec * dt);
    p.recoilYaw = approach(p.recoilYaw, 0, b.recoilRecoverDegPerSec * dt);
  }
  const sh = t.shield;
  if (p.shieldUp) {
    p.shieldEnergy -= sh.drainPerSec * dt;
    if (p.shieldEnergy <= 0) breakShield(t, p, T, ev);
  } else {
    if (p.shieldBrokenUntil > 0 && T >= p.shieldBrokenUntil) {
      p.shieldBrokenUntil = 0;
      p.shieldLoweredAt = T - sh.regenDelayTicks;
      ev.push({ type: "shield_ready", tick: T, player: p.slot });
    }
    if (p.shieldBrokenUntil === 0 && T - p.shieldLoweredAt >= sh.regenDelayTicks) {
      p.shieldEnergy = Math.min(sh.energyMax, p.shieldEnergy + sh.regenPerSec * dt);
    }
  }
  if (healthRegen && T - p.lastDamageTick >= t.health.regenDelayTicks) p.health = Math.min(t.health.max, p.health + t.health.regenPerSec * dt);
}

function rules(s: MatchState, ctx: SimContext, T: number, ev: CombatEvent[]): void {
  const next = T + 1;
  if (s.phase === "countdown") {
    if (next >= s.phaseEndsAt) {
      s.phase = "live";
      s.phaseStart = next;
      s.roundStartTick = next;
      s.phaseEndsAt = next + s.config.roundTimeLimitTicks;
      ev.push({ type: "round_start", tick: T, round: s.round });
    }
    return;
  }
  if (s.phase === "live") {
    const alive = s.players.filter((p) => p.alive);
    let winner: number | null = null;
    let reason: "kill" | "time" | "trade" = "kill";
    if (alive.length === 0) { winner = -1; reason = "trade"; }
    else if (alive.length === 1) winner = alive[0].slot;
    else if (next - s.roundStartTick >= s.config.roundTimeLimitTicks) {
      const [a, b] = s.players;
      winner = a.health > b.health ? a.slot : b.health > a.health ? b.slot : -1;
      reason = "time";
    }
    if (winner === null) return;
    if (winner >= 0) s.scores[winner]++;
    s.bolts = [];
    ev.push({ type: "round_end", tick: T, round: s.round, winner, reason, scores: s.scores.slice() });
    const c = s.config;
    const best = Math.max(...s.scores);
    if (best >= c.roundsToWin) {
      endMatchIn(s, s.scores.indexOf(best), "rounds", ev);
    } else if (s.round >= c.maxRounds) {
      const w = s.scores[0] > s.scores[1] ? 0 : s.scores[1] > s.scores[0] ? 1 : -1;
      endMatchIn(s, w, w < 0 ? "draw" : "rounds", ev);
    } else {
      s.phase = "round_end";
      s.phaseStart = next;
      s.phaseEndsAt = next + c.roundEndTicks;
    }
    return;
  }
  if (s.phase === "round_end" && next >= s.phaseEndsAt) {
    s.round += 1;
    s.phase = "countdown";
    s.phaseStart = next;
    s.phaseEndsAt = next + s.config.countdownTicks;
    placeForRound(s, ctx);
  }
}

/** Snap continuous values to the wire grid (done after every step). */
export function quantise(s: MatchState): void {
  for (const p of s.players) {
    p.x = q(p.x, 1000); p.z = q(p.z, 1000);
    p.yaw = q(p.yaw, 10000); p.pitch = q(p.pitch, 10000);
    p.vx = q(p.vx, 1000); p.vz = q(p.vz, 1000);
    p.recoilPitch = q(p.recoilPitch, 1000); p.recoilYaw = q(p.recoilYaw, 1000);
    p.health = q(p.health, 1000); p.heat = q(p.heat, 1000); p.bloom = q(p.bloom, 1000);
    p.ads = q(p.ads, 1000); p.shieldEnergy = q(p.shieldEnergy, 1000); p.ventFromHeat = q(p.ventFromHeat, 1000);
    p.dodgeDx = q(p.dodgeDx, 10000); p.dodgeDz = q(p.dodgeDz, 10000);
    p.stats.damageDealt = q(p.stats.damageDealt, 100); p.stats.damageTaken = q(p.stats.damageTaken, 100);
  }
  for (const b of s.bolts) {
    b.x = q(b.x, 1000); b.y = q(b.y, 1000); b.z = q(b.z, 1000);
    b.vx = q(b.vx, 1000); b.vy = q(b.vy, 1000); b.vz = q(b.vz, 1000);
    b.traveled = q(b.traveled, 1000); b.damageMul = q(b.damageMul, 10000);
  }
}
