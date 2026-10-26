/**
 * The presentation state of a duel for one frame: plain data for the 3D view
 * and the HUD, already smoothed between simulation ticks. React-free.
 */
import { lerp, lerpAngle } from "./math";
import { canRaiseShield, fireBlock, parryOpen, spreadDeg, surgeActive, type SimContext } from "./sim";
import { TICK_DT, TICK_RATE } from "./tuning";
import type { BoltKind, EndReason, MatchPhase, MatchState, PlayerState } from "./types";

export interface PlayerView {
  slot: number;
  id: string;
  /** The player this view belongs to (the camera follows them). */
  local: boolean;
  side: number;
  x: number;
  z: number;
  /** Body facing (= aim yaw). */
  yaw: number;
  pitch: number;
  /** Where the blaster actually points (aim plus recoil), radians. */
  aimYaw: number;
  aimPitch: number;
  vx: number;
  vz: number;
  speed: number;
  alive: boolean;
  health: number;
  healthMax: number;
  shieldUp: boolean;
  /** 0..1 */
  shieldEnergy: number;
  shieldBroken: boolean;
  /** The parry window is open right now (for a flash on the shield). */
  parrying: boolean;
  ads: number;
  sprinting: boolean;
  dodging: boolean;
  /** 0..1 through the roll (0 when not rolling). */
  dodgeProgress: number;
  venting: boolean;
  overheated: boolean;
  /** 0..1 heat (vents glow with it). */
  heat: number;
}

export interface BoltView {
  id: number;
  owner: number;
  shooter: number;
  kind: BoltKind;
  x: number;
  y: number;
  z: number;
  /** Unit direction of travel. */
  dx: number;
  dy: number;
  dz: number;
  speed: number;
  ageTicks: number;
}

export interface HudState {
  health: number;
  healthMax: number;
  /** 0..1 */
  heat: number;
  overheated: boolean;
  venting: boolean;
  /** 0..1 through the vent cycle, and its perfect window as fractions (null when not venting). */
  ventProgress: number;
  ventWindow: readonly [number, number] | null;
  /** A timing press was already spent on this vent. */
  ventAttempted: boolean;
  /** 0..1 */
  shieldEnergy: number;
  shieldUp: boolean;
  shieldBroken: boolean;
  /** Seconds until a broken shield comes back. */
  shieldBrokenLeft: number;
  shieldCanRaise: boolean;
  /** The next raise gets a parry window (no whiff lock). */
  parryReady: boolean;
  dodgeReady: boolean;
  /** 0..1 of the dodge cooldown still to run. */
  dodgeCooldown: number;
  /** Crosshair cone half-angle, degrees. */
  spreadDeg: number;
  ads: number;
  sprinting: boolean;
  canFire: boolean;
  recoilPitchDeg: number;
  recoilYawDeg: number;
  enemyHealth: number;
  enemyHealthMax: number;
}

export interface MatchView {
  tick: number;
  phase: MatchPhase;
  round: number;
  scores: readonly number[];
  roundsToWin: number;
  winner: number | null;
  endReason: EndReason | null;
  /** Seconds left in the countdown (0 outside it). */
  countdown: number;
  /** Seconds left before the round times out (live only). */
  roundTimeLeft: number;
  /** Reactor surge: no health regeneration, positions pinged. */
  surge: boolean;
}

export interface ViewState {
  status: string;
  slot: number;
  match: MatchView;
  players: PlayerView[];
  bolts: BoltView[];
  /** The local player's HUD; null for a spectator. */
  hud: HudState | null;
}

function playerView(ctx: SimContext, p: PlayerState, tick: number, local: boolean): PlayerView {
  const t = ctx.tuning;
  const dodging = tick < p.dodgeUntil;
  return {
    slot: p.slot, id: p.id, local, side: p.side, x: p.x, z: p.z, yaw: p.yaw, pitch: p.pitch,
    aimYaw: p.yaw + (p.recoilYaw * Math.PI) / 180, aimPitch: p.pitch + (p.recoilPitch * Math.PI) / 180,
    vx: p.vx, vz: p.vz, speed: Math.hypot(p.vx, p.vz), alive: p.alive, health: p.health, healthMax: t.health.max,
    shieldUp: p.shieldUp, shieldEnergy: p.shieldEnergy / t.shield.energyMax, shieldBroken: p.shieldBrokenUntil > tick,
    parrying: parryOpen(t, p, tick), ads: p.ads, sprinting: p.sprinting, dodging,
    dodgeProgress: dodging ? (tick - p.dodgeStart) / t.dodge.durationTicks : 0,
    venting: p.ventStart >= 0, overheated: p.ventStart >= 0 && p.ventForced, heat: p.heat / 100,
  };
}

function hud(ctx: SimContext, p: PlayerState, enemy: PlayerState | undefined, tick: number): HudState {
  const t = ctx.tuning;
  const venting = p.ventStart >= 0;
  const len = Math.max(1, p.ventEnd - p.ventStart);
  const block = fireBlock(t, p, tick);
  return {
    health: p.health, healthMax: t.health.max, heat: p.heat / 100, overheated: venting && p.ventForced, venting,
    ventProgress: venting ? (tick - p.ventStart) / len : 0,
    ventWindow: venting ? [(p.ventWinStart - p.ventStart) / len, (p.ventWinEnd - p.ventStart) / len] : null,
    ventAttempted: venting && p.ventAttempted,
    shieldEnergy: p.shieldEnergy / t.shield.energyMax, shieldUp: p.shieldUp, shieldBroken: p.shieldBrokenUntil > tick,
    shieldBrokenLeft: Math.max(0, p.shieldBrokenUntil - tick) * TICK_DT,
    shieldCanRaise: !p.shieldUp && canRaiseShield(t, p, tick),
    parryReady: tick >= p.parryReadyAt,
    dodgeReady: tick >= p.dodgeReadyAt && tick >= p.dodgeUntil,
    dodgeCooldown: Math.max(0, p.dodgeReadyAt - tick) / t.dodge.cooldownTicks,
    spreadDeg: spreadDeg(t, p), ads: p.ads, sprinting: p.sprinting, canFire: block === null || block === "cycle",
    recoilPitchDeg: p.recoilPitch, recoilYawDeg: p.recoilYaw,
    enemyHealth: enemy ? enemy.health : 0, enemyHealthMax: t.health.max,
  };
}

/**
 * Build the frame. `state` is the newest tick, `prev` the one before; the
 * local player and the bolts are blended between them by `alpha` (0..1 into
 * the next tick). `remote[slot]` replaces a remote player (interpolated
 * snapshots); missing entries come from `state`.
 */
export function buildView(
  ctx: SimContext, state: MatchState, prev: MatchState, alpha: number, slot: number,
  remote: readonly (PlayerState | null)[], status: string,
): ViewState {
  const tick = state.tick;
  const players = state.players.map((p) => {
    if (p.slot !== slot) return playerView(ctx, remote[p.slot] ?? p, tick, false);
    const q = prev.players[p.slot];
    const v = playerView(ctx, p, tick, true);
    if (q && q.alive && p.alive && Math.hypot(p.x - q.x, p.z - q.z) < 3) {
      v.x = lerp(q.x, p.x, alpha);
      v.z = lerp(q.z, p.z, alpha);
      v.yaw = lerpAngle(q.yaw, p.yaw, alpha);
      v.pitch = lerp(q.pitch, p.pitch, alpha);
    }
    return v;
  });
  const back = (1 - alpha) * TICK_DT;
  const bolts: BoltView[] = state.bolts.map((b) => {
    const speed = Math.hypot(b.vx, b.vy, b.vz) || 1;
    return {
      id: b.id, owner: b.owner, shooter: b.shooter, kind: b.kind,
      x: b.x - b.vx * back, y: b.y - b.vy * back, z: b.z - b.vz * back,
      dx: b.vx / speed, dy: b.vy / speed, dz: b.vz / speed, speed, ageTicks: tick - b.bornTick,
    };
  });
  const c = state.config;
  const match: MatchView = {
    tick, phase: state.phase, round: state.round, scores: state.scores, roundsToWin: c.roundsToWin,
    winner: state.winner, endReason: state.endReason,
    countdown: state.phase === "countdown" ? Math.max(0, state.phaseEndsAt - tick) / TICK_RATE : 0,
    roundTimeLeft: state.phase === "live" ? Math.max(0, state.roundStartTick + c.roundTimeLimitTicks - tick) / TICK_RATE : 0,
    surge: surgeActive(state, tick),
  };
  const me = slot >= 0 ? state.players[slot] : undefined;
  return {
    status, slot, match, players, bolts,
    hud: me ? hud(ctx, me, state.players.find((p) => p.slot !== slot), tick) : null,
  };
}
