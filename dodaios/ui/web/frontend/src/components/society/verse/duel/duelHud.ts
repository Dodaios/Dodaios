/**
 * What the duel's HUD shows, as plain data: the combat core's per-frame
 * view (health, shield, heat and vent window, the match clock and score)
 * plus the short-lived things the events bring (hit markers, the direction
 * a hit came from, call-outs, round banners). React-free and pure apart
 * from the feed's own memory of recent events, so it is tested without a
 * renderer; `hud/DuelHud.tsx` draws it.
 */
import type { CombatEvent } from "../combat/types";
import type { ViewState } from "../combat/view";

/** How long things stay on screen, ms. */
export const HUD_TIMES = {
  hitMarker: 260,
  killMarker: 520,
  damageArc: 1100,
  hurt: 380,
  callout: 900,
  fight: 900,
  ping: 1200,
} as const;

/** Low health: the screen edge pulses below this share. */
export const LOW_HEALTH = 0.3;

export type HitMarkerKind = "hit" | "head" | "kill";
export type CalloutKey = "parry" | "parried" | "perfect_vent" | "vent_miss" | "overheat" | "shield_break" | "deflect";

interface Timed { at: number }

/** The events' memory for the HUD: fed every frame with that frame's events. */
export class DuelHudFeed {
  hit: (Timed & { kind: HitMarkerKind }) | null = null;
  damage: (Timed & { fromX: number; fromZ: number; amount: number })[] = [];
  hurtAt = -Infinity;
  callout: (Timed & { key: CalloutKey }) | null = null;
  fightAt = -Infinity;
  ping: (Timed & { x: number; z: number }) | null = null;
  /** The last round's end, for its banner while the pause runs. */
  roundEnd: { round: number; winner: number; reason: "kill" | "time" | "trade" } | null = null;

  reset(): void {
    this.hit = null;
    this.damage = [];
    this.hurtAt = -Infinity;
    this.callout = null;
    this.fightAt = -Infinity;
    this.ping = null;
    this.roundEnd = null;
  }

  /** Take one frame's events; `slot` is the person's, `now` ms. */
  ingest(events: readonly CombatEvent[], slot: number, now: number): void {
    for (const e of events) {
      switch (e.type) {
        case "hit":
          if (e.owner === slot && e.target !== slot) {
            const kind: HitMarkerKind = e.health <= 0 ? "kill" : e.headshot ? "head" : "hit";
            // A kill marker is not replaced by a plain one in the same instant.
            if (!(this.hit && this.hit.kind === "kill" && now - this.hit.at < HUD_TIMES.killMarker)) this.hit = { at: now, kind };
          }
          if (e.target === slot) {
            this.damage.push({ at: now, fromX: e.fromX, fromZ: e.fromZ, amount: e.damage });
            if (this.damage.length > 6) this.damage.shift();
            this.hurtAt = now;
          }
          break;
        case "parry":
          if (e.player === slot) this.callout = { at: now, key: "parry" };
          else if (e.target === slot) this.callout = { at: now, key: "parried" };
          break;
        case "deflect":
          if (e.player === slot) this.callout = { at: now, key: "deflect" };
          break;
        case "vent_perfect":
          if (e.player === slot) this.callout = { at: now, key: "perfect_vent" };
          break;
        case "vent_miss":
          if (e.player === slot) this.callout = { at: now, key: "vent_miss" };
          break;
        case "overheat":
          if (e.player === slot) this.callout = { at: now, key: "overheat" };
          break;
        case "shield_break":
          if (e.player === slot) this.callout = { at: now, key: "shield_break" };
          break;
        case "round_start":
          this.fightAt = now;
          this.roundEnd = null;
          break;
        case "round_end":
          this.roundEnd = { round: e.round, winner: e.winner, reason: e.reason };
          break;
        case "ping":
          if (e.player !== slot) this.ping = { at: now, x: e.x, z: e.z };
          break;
        default:
          break;
      }
    }
  }
}

export type Banner =
  | { kind: "countdown"; value: number }
  | { kind: "fight" }
  | { kind: "round"; outcome: "won" | "lost" | "draw"; reason: "kill" | "time" | "trade" };

export interface HudModel {
  phase: string;
  round: number;
  myScore: number;
  theirScore: number;
  roundsToWin: number;
  /** Seconds left in the round (whole seconds, live only), null otherwise. */
  timeLeft: number | null;
  surge: boolean;
  health: number;
  healthFrac: number;
  lowHealth: boolean;
  enemyHealthFrac: number;
  shieldFrac: number;
  shieldUp: boolean;
  shieldBroken: boolean;
  shieldBrokenLeft: number;
  shieldCanRaise: boolean;
  parryReady: boolean;
  heat: number;
  overheated: boolean;
  venting: boolean;
  ventProgress: number;
  ventWindow: readonly [number, number] | null;
  ventAttempted: boolean;
  canFire: boolean;
  dodgeReady: boolean;
  dodgeCooldown: number;
  ads: number;
  spreadDeg: number;
  /** Crosshair: the hit marker on it, fading (alpha 0..1). */
  hitMarker: { kind: HitMarkerKind; alpha: number } | null;
  /** Where hits came from: clockwise from straight ahead, degrees, fading. */
  damageArcs: { angleDeg: number; alpha: number }[];
  /** Red flash at the screen edge after a hit taken, 0..1. */
  hurt: number;
  callout: { key: CalloutKey; alpha: number } | null;
  banner: Banner | null;
  /** The opponent's pinged position (reactor surge), fading. */
  ping: { x: number; z: number; alpha: number } | null;
}

function fade(now: number, at: number, life: number): number {
  const age = now - at;
  return age < 0 || age >= life ? 0 : 1 - age / life;
}

/**
 * The HUD for this frame. `camYaw` is the camera's heading (the damage
 * arcs are drawn relative to it), radians, yaw 0 facing +Z.
 */
export function buildHudModel(view: ViewState, feed: DuelHudFeed, now: number, camYaw: number): HudModel {
  const h = view.hud;
  const m = view.match;
  const me = view.players[view.slot];
  const slot = view.slot;
  const myScore = m.scores[slot] ?? 0;
  const theirScore = m.scores[1 - slot] ?? 0;

  let hitMarker: HudModel["hitMarker"] = null;
  if (feed.hit) {
    const a = fade(now, feed.hit.at, feed.hit.kind === "kill" ? HUD_TIMES.killMarker : HUD_TIMES.hitMarker);
    if (a > 0) hitMarker = { kind: feed.hit.kind, alpha: a };
  }
  const damageArcs: HudModel["damageArcs"] = [];
  if (me) {
    for (const d of feed.damage) {
      const a = fade(now, d.at, HUD_TIMES.damageArc);
      if (a <= 0) continue;
      const from = Math.atan2(d.fromX - me.x, d.fromZ - me.z);
      const rel = Math.atan2(Math.sin(from - camYaw), Math.cos(from - camYaw));
      damageArcs.push({ angleDeg: (-rel * 180) / Math.PI, alpha: a });
    }
  }
  let callout: HudModel["callout"] = null;
  if (feed.callout) {
    const a = fade(now, feed.callout.at, HUD_TIMES.callout);
    if (a > 0) callout = { key: feed.callout.key, alpha: a };
  }
  let banner: Banner | null = null;
  if (m.phase === "countdown") banner = { kind: "countdown", value: Math.max(1, Math.ceil(m.countdown)) };
  else if (m.phase === "live" && fade(now, feed.fightAt, HUD_TIMES.fight) > 0) banner = { kind: "fight" };
  else if (m.phase === "round_end" && feed.roundEnd) {
    const w = feed.roundEnd.winner;
    banner = { kind: "round", outcome: w === slot ? "won" : w < 0 ? "draw" : "lost", reason: feed.roundEnd.reason };
  }
  let ping: HudModel["ping"] = null;
  if (feed.ping) {
    const a = fade(now, feed.ping.at, HUD_TIMES.ping);
    if (a > 0) ping = { x: feed.ping.x, z: feed.ping.z, alpha: a };
  }
  const healthMax = h?.healthMax ?? 100;
  const health = h?.health ?? 0;
  return {
    phase: m.phase,
    round: m.round,
    myScore,
    theirScore,
    roundsToWin: m.roundsToWin,
    timeLeft: m.phase === "live" ? Math.ceil(m.roundTimeLeft) : null,
    surge: m.surge,
    health: Math.max(0, Math.round(health)),
    healthFrac: Math.max(0, Math.min(1, health / healthMax)),
    lowHealth: health > 0 && health / healthMax < LOW_HEALTH,
    enemyHealthFrac: h ? Math.max(0, Math.min(1, h.enemyHealth / h.enemyHealthMax)) : 0,
    shieldFrac: h?.shieldEnergy ?? 0,
    shieldUp: !!h?.shieldUp,
    shieldBroken: !!h?.shieldBroken,
    shieldBrokenLeft: h?.shieldBrokenLeft ?? 0,
    shieldCanRaise: !!h?.shieldCanRaise,
    parryReady: !!h?.parryReady,
    heat: h?.heat ?? 0,
    overheated: !!h?.overheated,
    venting: !!h?.venting,
    ventProgress: h?.ventProgress ?? 0,
    ventWindow: h?.ventWindow ?? null,
    ventAttempted: !!h?.ventAttempted,
    canFire: !!h?.canFire,
    dodgeReady: !!h?.dodgeReady,
    dodgeCooldown: h?.dodgeCooldown ?? 0,
    ads: h?.ads ?? 0,
    spreadDeg: h?.spreadDeg ?? 0,
    hitMarker,
    damageArcs,
    hurt: fade(now, feed.hurtAt, HUD_TIMES.hurt),
    callout,
    banner,
    ping,
  };
}
