/**
 * The duel bot: one more client. Each tick it reads an Observation (exactly
 * what a person at the screen could know) and answers with a ControlState,
 * which becomes an InputCommand through the same path as a human's keys.
 *
 * Layers:
 * - Perception memory: sightings of the opponent go into a short history and
 *   are used `trackLatency` late; a new sighting is acted on only after a
 *   sampled reaction time; shots heard and hits taken give a rough direction.
 * - Tactics, chosen by utility a few times a second with hysteresis: fight in
 *   the open (strafe, hold a range), take cover and peek, retreat to
 *   regenerate, push a weakened or overheated opponent, flank, hunt.
 * - Reflexes: incoming bolts it saw are answered (after a reaction delay) by
 *   a timed parry, a dodge roll or a block; vents are timed with an error;
 *   fresh shields are baited and their drop punished.
 * - Aim: AimController (speed-limited, wandering error), partial lead and
 *   partial recoil compensation.
 *
 * Deterministic for a given seed and observation sequence.
 */
import { isWalkable, lineOfSight, nearestWalkable, type Arena, type CoverSpot } from "../arena";
import { idleControl, type ControlState } from "../input";
import { angleDiff, DEG, forwardX, forwardZ, rightX, rightZ, yawOf } from "../math";
import type { BoltSighting, EnemySighting, Observation } from "../observe";
import { Rng } from "../rng";
import { CHEST_HEIGHT, muzzleOf } from "../sim";
import { TICK_RATE, type CombatTuning } from "../tuning";
import { AimController } from "./aim";
import { findRoute, navGraph, type Pt } from "./nav";
import type { BotParams } from "./tiers";

export type BotAction = "fight" | "cover" | "retreat" | "push" | "flank" | "hunt" | "camp" | "circle" | "watch";

/** Policy overrides used by the balance harness to script degenerate strategies. */
export interface BotOverrides {
  /**
   * Forced tactic. Besides the bot's own: "camp" (sit in cover near the own
   * spawn), "circle" (close in and orbit the opponent at point blank),
   * "watch" (hold a spot that sees the other spawn, pre-aimed).
   */
  action?: BotAction;
  fire?: "auto" | "spam" | "never";
  shield?: "auto" | "never" | "always" | "flick" | "block";
  dodge?: "auto" | "never" | "spam";
  /** "edge": fire up to the heat cap, then vent at once (and time it). */
  vent?: "auto" | "never" | "edge";
  /** "jiggle": reverse the strafe every 140..300 ms (A-D spam). */
  strafe?: "auto" | "jiggle";
  /** Once ahead on health, break off and hide until found (play for the clock). */
  hideWhenAhead?: boolean;
  /** Preferred fighting distance, metres (default from aggression: 15 down to 8). */
  range?: number;
  /** How hard it walks in on a distant target without a reason to (0..0.8; default APPROACH_DRIFT). */
  approach?: number;
  /** Where a camper settles. */
  campAt?: Pt;
}

interface Sighting extends EnemySighting { tick: number }

const ms = (v: number) => Math.round((v * TICK_RATE) / 1000);

/** Radial pull toward a distant target when there is no reason to close in (the strafe is 1). */
const APPROACH_DRIFT = 0.2;

export class BotBrain {
  readonly slot: number;
  private readonly rng: Rng;
  readonly aim: AimController;
  /** Last decision, for debugging and tests. */
  action: BotAction = "fight";
  aware = false;

  private sightings: Sighting[] = [];
  private lastSeen: Sighting | null = null;
  private reactAt = Infinity;
  private aimHead = false;
  private leadErr = 0;
  /** Last cue of where the opponent is (tick = when the bot may act on it, at = when it came). */
  private heard: { x: number; z: number; tick: number; at: number } | null = null;

  private nextDecision = 0;
  private actionSince = 0;
  private route: Pt[] | null = null;
  private routeIdx = 0;
  private routeGoal: Pt | null = null;
  private routeAt = -100000;
  private stuckCheck = { tick: 0, x: 0, z: 0 };
  private strafeDir = 1;
  private nextStrafe = 0;
  private cover: { spot: CoverSpot; peek: Pt | null; state: "go" | "hide" | "peek"; until: number } | null = null;
  private flankAt: Pt | null = null;

  private bolts = new Map<number, { react: number; decided: boolean; seen: number }>();
  private shieldPlan: { raiseAt: number; lowerAt: number } | null = null;
  private dodgePlan: { at: number; dx: number; dz: number } | null = null;
  private ventPressAt = -1;
  private ventCycle = -1;
  private lastVentPress = -100;
  private enemyShieldSince = -100000;
  private enemyShieldDropAt = -100000;
  private baitThisRaise = false;
  private lastPerceivedShield = false;
  /** Ticks of enemy shots heard (for its firing rhythm), and when I was last hit. */
  private enemyShots: number[] = [];
  private rhythm = { shot: -1, react: 0, done: true };
  private lastHurtTick = -100000;
  private pressureNext = 0;
  private blockStarted = -100000;
  /** This round's approach: waypoints toward the other spawn. */
  private lane: Pt[] = [];
  private laneIdx = 0;
  /** Tick of the last sighting whose place has been checked. */
  private investigated = -1;

  constructor(
    slot: number,
    readonly params: BotParams,
    private readonly arena: Arena,
    private readonly tuning: CombatTuning,
    seed: number,
    readonly overrides: BotOverrides = {},
  ) {
    this.slot = slot;
    this.rng = new Rng(seed);
    this.aim = new AimController(params, this.rng.fork(1));
  }

  // ------------------------------------------------------------ perception

  private sampleReaction(scale = 1): number {
    const [m, sd] = this.params.reactionMs;
    return ms(Math.max(m * 0.6, this.rng.normal(m, sd)) * scale);
  }

  private perceive(obs: Observation): void {
    const tick = obs.tick;
    const e = obs.enemy;
    if (e) {
      const fresh = !this.lastSeen || tick - this.lastSeen.tick > 12;
      if (fresh) {
        this.reactAt = tick + this.sampleReaction();
        this.aim.acquire(tick + ms(this.params.trackLatencyMs));
        this.aimHead = this.rng.chance(this.params.headAim);
        this.leadErr = this.rng.normal(0, this.params.leadNoise);
      }
      const s: Sighting = { ...e, tick };
      this.sightings.push(s);
      if (this.sightings.length > 90) this.sightings.shift();
      this.lastSeen = s;
    } else if (!obs.enemyAlive) {
      this.lastSeen = null;
    }
    const err = this.params.hearingErrorM;
    if (obs.heard.length > 0) {
      this.enemyShots.push(tick);
      if (this.enemyShots.length > 4) this.enemyShots.shift();
      this.rhythm = { shot: tick, react: tick + this.sampleReaction(0.9), done: false };
    }
    if (obs.hurtFrom) this.lastHurtTick = tick;
    if (e) return;
    // Cues without sight: shots, footsteps, the surge ping, the direction of a hit.
    const me = obs.me;
    let cue: { x: number; z: number; err: number } | null = null;
    if (obs.ping) cue = { ...obs.ping, err: 0.5 };
    for (const h of obs.heard) cue = { ...h, err };
    if (!cue && obs.footsteps) cue = { ...obs.footsteps, err: err * 1.5 };
    if (!cue && obs.hurtFrom) {
      const dx = obs.hurtFrom.x - me.x;
      const dz = obs.hurtFrom.z - me.z;
      const l = Math.hypot(dx, dz) || 1;
      cue = { x: me.x + (dx / l) * 12, z: me.z + (dz / l) * 12, err };
    }
    if (cue) {
      // A stream of cues keeps the first reaction time instead of postponing it.
      const act = this.heard && tick - this.heard.at < 60 ? this.heard.tick : tick + this.sampleReaction();
      this.heard = { x: cue.x + this.rng.normal(0, cue.err), z: cue.z + this.rng.normal(0, cue.err), tick: act, at: tick };
    }
  }

  /** What the bot "sees" now: the sighting `trackLatency` old, extrapolated. Null when not (yet) aware. */
  private perceived(tick: number): Sighting | null {
    if (tick < this.reactAt || !this.lastSeen) return null;
    const lat = ms(this.params.trackLatencyMs);
    let s: Sighting | null = null;
    for (let i = this.sightings.length - 1; i >= 0; i--) {
      if (this.sightings[i].tick <= tick - lat) { s = this.sightings[i]; break; }
    }
    if (!s) s = this.sightings[0] ?? null;
    if (!s || tick - s.tick > lat + 8) return null;
    // The motion read: how it moved over the last moments, not this instant,
    // so a target that keeps reversing (A-D strafing) is aimed at the middle
    // of its wobble instead of chased. Rolls are read as they happen.
    let vx = s.vx;
    let vz = s.vz;
    const win = ms(this.params.motionWindowMs);
    if (win > 0 && !s.dodging && this.reversals(s.tick) >= 2) {
      for (let i = this.sightings.length - 1; i >= 0; i--) {
        const o = this.sightings[i];
        if (o.tick > s.tick - win) continue;
        if (o.tick >= s.tick - win - 4 && !o.dodging) {
          const span = (s.tick - o.tick) / TICK_RATE;
          vx = (s.x - o.x) / span;
          vz = (s.z - o.z) / span;
        }
        break;
      }
    }
    // Extrapolate over the latency with the bot's motion read.
    const dt = ((tick - s.tick) / TICK_RATE) * this.params.leadSkill;
    return { ...s, vx, vz, x: s.x + vx * dt, z: s.z + vz * dt };
  }

  /** How often the target turned its running round in the 0.7 s before `tick` (sampled every 0.1 s). */
  private reversals(tick: number): number {
    let n = 0;
    let prev: Sighting | null = null;
    let next = tick;
    for (let i = this.sightings.length - 1; i >= 0; i--) {
      const s = this.sightings[i];
      if (s.tick > next) continue;
      if (s.tick < tick - 42) break;
      if (prev && Math.hypot(s.vx, s.vz) > 1.5 && Math.hypot(prev.vx, prev.vz) > 1.5 && s.vx * prev.vx + s.vz * prev.vz < 0) n++;
      prev = s;
      next = s.tick - 6;
    }
    return n;
  }

  // ------------------------------------------------------------ main

  think(obs: Observation): ControlState {
    const me = obs.me;
    const tick = obs.tick;
    const out = idleControl(this.aim.yaw, this.aim.pitch);
    if (obs.phase !== "live" || !me.alive) {
      this.resetRound(obs);
      out.yaw = this.aim.yaw;
      out.pitch = this.aim.pitch;
      return out;
    }
    this.perceive(obs);
    const target = this.perceived(tick);
    this.aware = target !== null;
    const visibleNow = obs.enemy !== null;
    this.trackEnemyShield(target, tick);

    if (tick >= this.nextDecision) {
      this.decide(obs, target);
      this.nextDecision = tick + ms(this.params.decisionMs * this.rng.range(0.8, 1.2));
    }

    // Movement.
    const move = this.steer(obs, target);
    // Reflexes.
    this.defend(obs, target);
    let shield = this.shieldWanted(obs);
    let dodge = false;
    if (this.dodgePlan && tick >= this.dodgePlan.at) {
      dodge = tick >= me.dodgeReadyAt;
      if (dodge) { move.x = this.dodgePlan.dx; move.z = this.dodgePlan.dz; shield = false; }
      this.dodgePlan = null;
    }
    if (this.overrides.dodge === "spam" && tick >= me.dodgeReadyAt && target && !shield) {
      dodge = true;
      const side = this.rng.chance(0.5) ? 1 : -1;
      move.x = rightX(this.aim.yaw) * side;
      move.z = rightZ(this.aim.yaw) * side;
    }

    // Aim.
    const aimInfo = this.aimAt(obs, target, move);
    // Fire.
    const fire = !shield && !dodge && this.wantFire(obs, target, visibleNow, aimInfo);
    // Vent.
    const vent = this.wantVent(obs, target, fire);

    out.yaw = this.aim.yaw;
    out.pitch = this.aim.pitch;
    const ml = Math.hypot(move.x, move.z);
    if (ml > 1e-6) {
      const wx = move.x / Math.max(1, ml);
      const wz = move.z / Math.max(1, ml);
      out.moveX = wx * rightX(out.yaw) + wz * rightZ(out.yaw);
      out.moveY = wx * forwardX(out.yaw) + wz * forwardZ(out.yaw);
    }
    out.sprint = move.sprint && !fire && !shield;
    out.fire = fire;
    out.ads = !shield && !dodge && ((aimInfo.dist > this.params.adsRange && target !== null && this.action !== "push" && this.action !== "circle")
      || (this.action === "watch" && target === null && ml < 1e-6));
    out.shield = shield;
    out.dodge = dodge;
    out.vent = vent;
    return out;
  }

  private resetRound(obs: Observation): void {
    this.sightings = [];
    this.lastSeen = null;
    this.reactAt = Infinity;
    this.heard = null;
    this.investigated = -1;
    this.route = null;
    this.cover = null;
    this.flankAt = null;
    this.shieldPlan = null;
    this.dodgePlan = null;
    this.bolts.clear();
    this.ventPressAt = -1;
    this.enemyShots = [];
    this.nextDecision = obs.tick;
    this.lane = this.pickLane(obs.me.side);
    this.laneIdx = 0;
    // Look toward the arena's centre (where the opponent will come from).
    const me = obs.me;
    const c = this.arena.def.centre;
    this.aim.reset(yawOf(c.x - me.x, c.z - me.z), 0);
  }

  /**
   * An approach for the round: through the middle (the walkways) or round
   * either side of the drop, then on to the other spawn.
   */
  private pickLane(side: number): Pt[] {
    const a = this.arena.def.spawns[side];
    const b = this.arena.def.spawns[1 - side];
    const mx = (a.x + b.x) / 2;
    const mz = (a.z + b.z) / 2;
    const l = Math.hypot(b.x - a.x, b.z - a.z) || 1;
    const px = -(b.z - a.z) / l;
    const pz = (b.x - a.x) / l;
    const v = this.arena.def.voids[0];
    const wide = v ? v.r + 2.6 : 6;
    const roll = this.rng.next();
    const sideSign = this.rng.chance(0.5) ? 1 : -1;
    const off = roll < 0.4 ? sideSign * (v ? 5.75 : 0) : (roll < 0.7 ? 1 : -1) * wide;
    const via = nearestWalkable(this.arena, mx + px * off, mz + pz * off, 4) ?? { x: mx, z: mz };
    return [via, { x: b.x, z: b.z }];
  }

  // ------------------------------------------------------------ tactics

  private decide(obs: Observation, target: Sighting | null): void {
    const p = this.params;
    const me = obs.me;
    const tick = obs.tick;
    const forced = this.overrides.action;
    const seenAge = this.lastSeen ? (tick - this.lastSeen.tick) / TICK_RATE : 99;
    const myH = me.health / this.tuning.health.max;
    const enH = obs.enemyHealth / this.tuning.health.max;
    const ref = target ?? this.lastSeen;
    const enemyWeak = ref ? ref.venting || ref.shieldBroken : false;
    let next: BotAction;
    if (forced) next = forced;
    else {
      const score: Record<BotAction, number> = {
        fight: 0.55 + 0.35 * (myH - enH) + (target ? 0.15 : -0.25) + 0.1 * p.aggression,
        cover: p.coverUse * (0.15 + 0.55 * (1 - myH) + 0.4 * (me.heat / 100) + (me.shieldBrokenUntil > tick ? 0.25 : 0) + (enH > myH + 0.2 ? 0.2 : 0)),
        retreat: myH < 0.38 && enH > myH + 0.12 ? p.coverUse * 1.05 : 0,
        push: p.aggression * ((enemyWeak && seenAge < 1.5 ? 0.75 : 0) + (enH < 0.3 && myH > enH + 0.15 ? 0.6 : 0)),
        flank: p.flankUse * ((seenAge > 1.5 && seenAge < 8 ? 0.55 : 0) + (ref && ref.shieldUp ? 0.35 : 0)),
        hunt: seenAge > 2.5 ? 0.65 : 0,
        camp: 0,
        circle: 0,
        watch: 0,
      };
      score[this.action] += 0.18;
      for (const k of Object.keys(score) as BotAction[]) score[k] += this.rng.range(0, 0.08);
      next = "fight";
      for (const k of Object.keys(score) as BotAction[]) if (score[k] > score[next]) next = k;
      if (this.overrides.hideWhenAhead && me.health > obs.enemyHealth + 8) {
        const close = target && Math.hypot(target.x - me.x, target.z - me.z) < 10;
        if (!close) next = "retreat";
      }
    }
    if (next !== this.action) {
      this.action = next;
      this.actionSince = tick;
      this.route = null;
      this.cover = null;
      this.flankAt = null;
    }
    if (next === "cover" || next === "retreat") this.pickCover(obs, next === "retreat");
    if (next === "flank" && !this.flankAt) this.flankAt = this.pickFlank(obs);
  }

  private enemyRef(): Pt | null {
    if (this.lastSeen) return this.lastSeen;
    if (this.heard) return this.heard;
    return null;
  }

  private hiddenFrom(enemy: Pt, x: number, z: number): boolean {
    const ey = this.tuning.body.eyeHeight;
    return !lineOfSight(this.arena, enemy.x, ey, enemy.z, x, 1.6, z) && !lineOfSight(this.arena, enemy.x, ey, enemy.z, x, 1.0, z);
  }

  private seesFrom(enemy: Pt, x: number, z: number): boolean {
    return lineOfSight(this.arena, x, this.tuning.body.eyeHeight, z, enemy.x, CHEST_HEIGHT, enemy.z);
  }

  private pickCover(obs: Observation, far: boolean): void {
    const me = obs.me;
    const enemy = this.enemyRef();
    if (!enemy) { this.cover = null; return; }
    if (this.cover && this.hiddenFrom(enemy, this.cover.spot.x, this.cover.spot.z)) return;
    let best: CoverSpot | null = null;
    let bestScore = -Infinity;
    for (const s of this.arena.cover) {
      const dMe = Math.hypot(s.x - me.x, s.z - me.z);
      if (dMe > 22) continue;
      const dEn = Math.hypot(s.x - enemy.x, s.z - enemy.z);
      if (dEn < 5) continue;
      const score = far ? dEn - dMe * 0.6 : -dMe - Math.abs(dEn - 12) * 0.5;
      if (score <= bestScore) continue;
      if (!this.hiddenFrom(enemy, s.x, s.z)) continue;
      best = s;
      bestScore = score;
    }
    if (!best) { this.cover = null; return; }
    this.cover = { spot: best, peek: far ? null : this.peekFor(best, enemy), state: "go", until: 0 };
  }

  private peekFor(s: CoverSpot, enemy: Pt): Pt | null {
    const tx = s.nz;
    const tz = -s.nx;
    for (const [a, b] of [[1.2, 0], [-1.2, 0], [2.0, 0], [-2.0, 0], [0, 1.0], [2.8, 0], [-2.8, 0]]) {
      const x = s.x + tx * a + s.nx * b;
      const z = s.z + tz * a + s.nz * b;
      if (isWalkable(this.arena, x, z) && this.seesFrom(enemy, x, z)) return { x, z };
    }
    return null;
  }

  private pickFlank(obs: Observation): Pt | null {
    const enemy = this.lastSeen ?? this.heard;
    if (!enemy) return null;
    const me = obs.me;
    const facing = this.lastSeen ? this.lastSeen.yaw : yawOf(me.x - enemy.x, me.z - enemy.z);
    let best: Pt | null = null;
    let bestD = Infinity;
    for (const off of [100, -100, 130, -130, 70, -70]) {
      for (const r of [9, 12, 15]) {
        const a = facing + off * DEG;
        const x = enemy.x + Math.sin(a) * r;
        const z = enemy.z + Math.cos(a) * r;
        if (!isWalkable(this.arena, x, z) || !this.seesFrom(enemy, x, z)) continue;
        const d = Math.hypot(x - me.x, z - me.z);
        if (d < bestD) { bestD = d; best = { x, z }; }
      }
    }
    return best;
  }

  // ------------------------------------------------------------ movement

  private follow(me: Pt, goal: Pt, tick: number): { x: number; z: number; left: number } {
    const replan = !this.route || !this.routeGoal || Math.hypot(goal.x - this.routeGoal.x, goal.z - this.routeGoal.z) > 1.5 || tick - this.routeAt > 90;
    if (replan) {
      this.route = findRoute(this.arena, me, goal);
      this.routeGoal = goal;
      this.routeAt = tick;
      this.routeIdx = 1;
    }
    const r = this.route;
    if (!r || r.length < 2) return { x: 0, z: 0, left: 0 };
    while (this.routeIdx < r.length - 1 && Math.hypot(r[this.routeIdx].x - me.x, r[this.routeIdx].z - me.z) < 0.6) this.routeIdx++;
    const wp = r[Math.min(this.routeIdx, r.length - 1)];
    const dx = wp.x - me.x;
    const dz = wp.z - me.z;
    const l = Math.hypot(dx, dz);
    let left = l;
    for (let i = this.routeIdx + 1; i < r.length; i++) left += Math.hypot(r[i].x - r[i - 1].x, r[i].z - r[i - 1].z);
    if (l < 0.15) return { x: 0, z: 0, left };
    return { x: dx / l, z: dz / l, left };
  }

  private strafe(me: Pt, toEnemyYaw: number, tick: number): { x: number; z: number } {
    const p = this.params;
    if (tick >= this.nextStrafe) {
      const jiggle = this.overrides.strafe === "jiggle";
      this.strafeDir = jiggle || this.rng.chance(0.7) ? -this.strafeDir : this.strafeDir;
      this.nextStrafe = tick + ms(jiggle ? this.rng.range(140, 300) : this.rng.range(p.strafeMs[0], p.strafeMs[1]));
    }
    // Sideways to the line of fire; bend toward or away from the target where the floor ends.
    for (const flip of [1, -1]) {
      const dir = this.strafeDir * flip;
      for (const bend of [0, 30, -30, 60, -60]) {
        const a = toEnemyYaw - (Math.PI / 2) * dir + bend * DEG * dir;
        const sx = Math.sin(a);
        const sz = Math.cos(a);
        if (isWalkable(this.arena, me.x + sx * 0.9, me.z + sz * 0.9)) {
          if (flip < 0) { this.strafeDir = dir; this.nextStrafe = tick + ms(p.strafeMs[0]); }
          return { x: sx, z: sz };
        }
      }
    }
    return { x: 0, z: 0 };
  }

  private steer(obs: Observation, target: Sighting | null): { x: number; z: number; sprint: boolean } {
    const me = obs.me;
    const tick = obs.tick;
    const p = this.params;
    const enemy = target ?? this.enemyRef();
    const stuck = this.isStuck(me, tick);
    if (stuck) { this.route = null; this.strafeDir = -this.strafeDir; }
    const go = (goal: Pt, sprintFar = true) => {
      const f = this.follow(me, goal, tick);
      return { x: f.x, z: f.z, sprint: sprintFar && !target && f.left > 7 };
    };
    switch (this.action) {
      case "camp":
      case "watch": {
        if (this.action === "watch" && target) break;
        const spot = this.overrides.campAt ?? (this.action === "watch" ? this.watchSpot(me.side) : this.campSpot(me.side));
        if (Math.hypot(spot.x - me.x, spot.z - me.z) > 0.8) return go(spot);
        return { x: 0, z: 0, sprint: false };
      }
      case "circle": {
        if (!enemy) break;
        const d = Math.hypot(enemy.x - me.x, enemy.z - me.z);
        if (d > 3.4 || !target) return go(enemy, !target);
        // Orbit at about 2.2 m: tangent plus a pull to the radius.
        const toYaw = yawOf(enemy.x - me.x, enemy.z - me.z);
        if (tick >= this.nextStrafe) {
          this.strafeDir = this.rng.chance(0.25) ? -this.strafeDir : this.strafeDir;
          this.nextStrafe = tick + ms(this.rng.range(600, 1400));
        }
        for (const flip of [1, -1]) {
          const dir = this.strafeDir * flip;
          const a = toYaw - (Math.PI / 2) * dir;
          const radial = Math.max(-0.7, Math.min(0.7, (d - 2.2) * 0.9));
          const x = Math.sin(a) + Math.sin(toYaw) * radial;
          const z = Math.cos(a) + Math.cos(toYaw) * radial;
          if (isWalkable(this.arena, me.x + x * 0.8, me.z + z * 0.8)) {
            if (flip < 0) this.strafeDir = dir;
            return { x, z, sprint: false };
          }
        }
        return { x: Math.sin(toYaw), z: Math.cos(toYaw), sprint: false };
      }
      case "cover":
      case "retreat": {
        const c = this.cover;
        if (!c || !enemy) break;
        const d = Math.hypot(c.spot.x - me.x, c.spot.z - me.z);
        if (c.state === "go") {
          if (d > 0.5) return go(c.spot, true);
          c.state = "hide";
          c.until = tick + ms(this.rng.range(500, 1100));
        }
        if (c.state === "hide") {
          const ready = me.heat < 25 && me.ventStart < 0 && (me.shieldBrokenUntil <= tick) && (this.action === "cover" ? me.health > 45 || me.health >= obs.enemyHealth : me.health > 85);
          if (tick >= c.until && ready && c.peek) { c.state = "peek"; c.until = tick + ms(this.rng.range(700, 1500)); }
          if (this.action === "retreat" && target && Math.hypot(target.x - me.x, target.z - me.z) < 8) { this.nextDecision = tick; }
          if (d > 0.4) return go(c.spot, false);
          return { x: 0, z: 0, sprint: false };
        }
        // Peek: step out, shoot, step back in.
        if (c.peek) {
          if (tick >= c.until || me.heat > p.heatCap - 8 || me.health < 30) { c.state = "hide"; c.until = tick + ms(this.rng.range(400, 900)); return go(c.spot, false); }
          if (Math.hypot(c.peek.x - me.x, c.peek.z - me.z) > 0.3) return go(c.peek, false);
        }
        return { x: 0, z: 0, sprint: false };
      }
      case "push": {
        if (!enemy) break;
        const d = Math.hypot(enemy.x - me.x, enemy.z - me.z);
        if (d > 4.5 || !target) return go(enemy);
        const s = this.strafe(me, yawOf(enemy.x - me.x, enemy.z - me.z), tick);
        return { x: s.x, z: s.z, sprint: false };
      }
      case "flank": {
        if (this.flankAt && Math.hypot(this.flankAt.x - me.x, this.flankAt.z - me.z) > 0.8) {
          if (target && tick - this.actionSince > 30) break;
          return go(this.flankAt);
        }
        this.nextDecision = Math.min(this.nextDecision, tick + 6);
        break;
      }
      case "hunt":
        return go(this.searchGoal(me, tick));
      default:
        break;
    }
    // Fight: hold a range and strafe; without sight, close in on the last known position.
    if (!target) {
      const goal = this.searchGoal(me, tick);
      return go(goal, Math.hypot(goal.x - me.x, goal.z - me.z) > 14);
    }
    const yaw = yawOf(target.x - me.x, target.z - me.z);
    const d = Math.hypot(target.x - me.x, target.z - me.z);
    const pref = this.overrides.range ?? 15 - 7 * p.aggression;
    let radial = 0;
    if (d > pref + 3) {
      // Walking straight at a shooter makes the easiest target there is, so
      // close in only with a reason (it is busy or beaten, or out of range);
      // otherwise trade from here and drift in slowly.
      const busy = target.venting || target.shieldBroken;
      const reason = busy || me.health > obs.enemyHealth + 25 || d > 34 || this.overrides.range !== undefined;
      radial = reason ? 0.8 : this.overrides.approach ?? APPROACH_DRIFT;
    } else if (d < pref - 4) radial = -0.6;
    const s = this.strafe(me, yaw, tick);
    let x = s.x + Math.sin(yaw) * radial;
    let z = s.z + Math.cos(yaw) * radial;
    // Without a clear line to the target, walk the route instead.
    if (!this.seesFrom(target, me.x, me.z)) {
      const f = this.follow(me, target, tick);
      x = f.x; z = f.z;
    }
    return { x, z, sprint: false };
  }

  private campSpots: Pt[] = [];

  /** The cover spot nearest this side's spawn that the other spawn cannot see. */
  private campSpot(side: number): Pt {
    if (!this.campSpots[side]) {
      const own = this.arena.def.spawns[side];
      const other = this.arena.def.spawns[1 - side];
      let best: Pt = own;
      let bestD = Infinity;
      for (const s of this.arena.cover) {
        const d = Math.hypot(s.x - own.x, s.z - own.z);
        if (d < bestD && this.hiddenFrom(other, s.x, s.z)) { bestD = d; best = s; }
      }
      this.campSpots[side] = best;
    }
    return this.campSpots[side];
  }

  private watchSpots: Pt[] = [];

  /** The cover spot nearest this side's spawn that sees the other spawn (a pre-aimed hold). */
  private watchSpot(side: number): Pt {
    if (!this.watchSpots[side]) {
      const own = this.arena.def.spawns[side];
      const other = this.arena.def.spawns[1 - side];
      let best: Pt = own;
      let bestD = Infinity;
      for (const s of this.arena.cover) {
        const d = Math.hypot(s.x - own.x, s.z - own.z);
        if (d < bestD && this.seesFrom(other, s.x, s.z)) { bestD = d; best = s; }
      }
      this.watchSpots[side] = best;
    }
    return this.watchSpots[side];
  }

  private laneGoal(me: Pt): Pt {
    while (this.laneIdx < this.lane.length - 1 && Math.hypot(this.lane[this.laneIdx].x - me.x, this.lane[this.laneIdx].z - me.z) < 2.5) this.laneIdx++;
    const last = this.lane[this.lane.length - 1];
    if (last && this.laneIdx === this.lane.length - 1 && Math.hypot(last.x - me.x, last.z - me.z) < 2.5) {
      // Lane walked and nobody met: search on toward somewhere else in the room.
      const g = navGraph(this.arena);
      let pick: Pt = this.arena.def.centre;
      for (let i = 0; i < 12; i++) {
        const k = this.rng.int(g.xs.length);
        pick = { x: g.xs[k], z: g.zs[k] };
        if (Math.hypot(pick.x - me.x, pick.z - me.z) > 14) break;
      }
      this.lane.push(pick);
      this.laneIdx = this.lane.length - 1;
    }
    return this.lane[this.laneIdx] ?? this.arena.def.centre;
  }

  /** Where to look for the opponent: a fresh cue, else its last sighting (until checked), else the lane. */
  private searchGoal(me: Pt, tick: number): Pt {
    const cue = this.heard && this.heard.tick <= tick ? this.heard : null;
    if (cue) {
      if (Math.hypot(cue.x - me.x, cue.z - me.z) > 2.5) return cue;
      this.heard = null;
    }
    const seen = this.lastSeen && this.lastSeen.tick > this.investigated ? this.lastSeen : null;
    if (seen) {
      if (Math.hypot(seen.x - me.x, seen.z - me.z) > 2.5) return seen;
      this.investigated = seen.tick;
    }
    return this.laneGoal(me);
  }

  private isStuck(me: Pt, tick: number): boolean {
    const c = this.stuckCheck;
    if (tick - c.tick < 45) return false;
    const moved = Math.hypot(me.x - c.x, me.z - c.z);
    const wasTrying = this.route !== null;
    c.tick = tick; c.x = me.x; c.z = me.z;
    return wasTrying && moved < 0.25 && this.action !== "camp" && !(this.cover && this.cover.state !== "go");
  }

  // ------------------------------------------------------------ reflexes

  private trackEnemyShield(target: Sighting | null, tick: number): void {
    const up = target ? target.shieldUp : false;
    if (up && !this.lastPerceivedShield) {
      this.enemyShieldSince = tick;
      this.baitThisRaise = this.rng.chance(this.params.baitPunish);
    }
    if (!up && this.lastPerceivedShield) this.enemyShieldDropAt = tick;
    this.lastPerceivedShield = up;
  }

  private defend(obs: Observation, target: Sighting | null): void {
    const me = obs.me;
    const tick = obs.tick;
    for (const [id, rec] of this.bolts) if (tick - rec.seen > 120) this.bolts.delete(id);
    if (this.overrides.shield === "always" || this.overrides.shield === "flick") return;
    for (const b of obs.bolts) {
      if (b.owner === this.slot) continue;
      let rec = this.bolts.get(b.id);
      if (!rec) {
        rec = { react: tick + this.sampleReaction(target ? 0.85 : 1), decided: false, seen: tick };
        this.bolts.set(b.id, rec);
      }
      if (rec.decided || tick < rec.react) continue;
      rec.decided = true;
      const thr = threat(b, me);
      if (!thr || thr.miss > 0.75) continue;
      this.answer(obs, tick + Math.max(1, Math.round(thr.t * TICK_RATE)), b);
    }
    if (this.overrides.shield === "never" || this.overrides.shield === "block" || !target) return;
    const p = this.params;
    const sh = this.tuning.shield;
    const interval = this.tuning.blaster.fireIntervalTicks;
    const facingMe = this.shieldCoversMe(target, me);
    // Rhythm parry: a steady stream is read and the next bolt met on time.
    const shots = this.enemyShots;
    const r = this.rhythm;
    if (!r.done && tick >= r.react && shots.length >= 2) {
      r.done = true;
      const gap = shots[shots.length - 1] - shots[shots.length - 2];
      if (Math.abs(gap - interval) <= 1 && facingMe && !this.shieldPlan && this.rng.chance(p.parryChance * 0.75)) {
        const dist = Math.hypot(target.x - me.x, target.z - me.z);
        const arrival = r.shot + interval + Math.round((dist / this.tuning.blaster.boltSpeed) * TICK_RATE);
        const raiseAt = arrival - Math.round(sh.parryWindowTicks / 2) + Math.round(this.rng.normal(0, ms(p.parryTimingSdMs)));
        if (raiseAt >= tick && raiseAt >= me.parryReadyAt && this.canShieldAt(obs, raiseAt)) this.shieldPlan = { raiseAt, lowerAt: raiseAt + sh.parryWindowTicks + 3 };
      }
    }
    // Under pressure and losing the trade: block for a moment, then answer.
    if (!this.shieldPlan && tick >= this.pressureNext) {
      this.pressureNext = tick + ms(250);
      const recentShots = shots.filter((t) => tick - t < 30).length;
      const underFire = tick - this.lastHurtTick < ms(450) || (recentShots >= 2 && facingMe);
      const losing = me.health < obs.enemyHealth - 10 || me.ventStart >= 0 || me.heat >= p.heatCap - 5 || me.health < 35;
      if (underFire && losing && this.rng.chance(p.blockChance * 0.55)) {
        const raiseAt = tick + this.sampleReaction(0.5);
        if (this.canShieldAt(obs, raiseAt)) {
          this.shieldPlan = { raiseAt, lowerAt: raiseAt + ms(this.rng.range(400, 850)) };
          this.blockStarted = raiseAt;
          this.nextDecision = Math.min(this.nextDecision, tick + 3);
        }
      }
    }
  }

  private canShieldAt(obs: Observation, at: number): boolean {
    const me = obs.me;
    const sh = this.tuning.shield;
    return this.overrides.shield !== "never" && me.shieldBrokenUntil <= at && me.shieldEnergy >= sh.raiseMinEnergy + 4
      && at - me.shieldLoweredAt >= sh.reRaiseTicks && at >= me.dodgeUntil;
  }

  private answer(obs: Observation, impact: number, b: BoltSighting): void {
    const p = this.params;
    const me = obs.me;
    const tick = obs.tick;
    const sh = this.tuning.shield;
    const plan = this.shieldPlan;
    if (plan && tick < plan.lowerAt) {
      if (impact <= plan.lowerAt + 2) return;
      if (me.shieldUp || tick >= plan.raiseAt) {
        const long = tick - Math.max(plan.raiseAt, this.blockStarted) > ms(1400);
        if (!long && me.shieldEnergy > 35 && this.rng.chance(p.blockChance)) plan.lowerAt = Math.max(plan.lowerAt, impact + 3);
      }
      return;
    }
    if (this.overrides.shield === "block") {
      if (this.canShieldAt(obs, tick)) this.shieldPlan = { raiseAt: tick, lowerAt: impact + 4 };
      return;
    }
    const exposed = me.ventStart >= 0 || me.heat >= p.heatCap - 5;
    if (this.rng.chance(p.parryChance * (exposed ? 1.2 : 1))) {
      const raiseAt = impact - Math.round(sh.parryWindowTicks / 2) + Math.round(this.rng.normal(0, ms(p.parryTimingSdMs)));
      if (raiseAt >= tick && raiseAt >= me.parryReadyAt && this.canShieldAt(obs, raiseAt)) {
        this.shieldPlan = { raiseAt, lowerAt: raiseAt + sh.parryWindowTicks + 3 };
        return;
      }
    }
    if (this.overrides.dodge !== "never" && tick >= me.dodgeReadyAt && impact - tick >= 5 && this.rng.chance(p.dodgeChance)) {
      // Roll sideways out of the bolt's line, toward the open side.
      const l = Math.hypot(b.vx, b.vz) || 1;
      const px = -b.vz / l;
      const pz = b.vx / l;
      const side = isWalkable(this.arena, me.x + px * 3, me.z + pz * 3) ? 1 : -1;
      this.dodgePlan = { at: tick, dx: px * side, dz: pz * side };
      return;
    }
    if (this.rng.chance(p.blockChance * (exposed ? 1 : 0.3)) && this.canShieldAt(obs, tick) && impact - tick >= 2) {
      this.shieldPlan = { raiseAt: tick, lowerAt: impact + 4 };
    }
  }

  private shieldWanted(obs: Observation): boolean {
    const me = obs.me;
    const tick = obs.tick;
    const mode = this.overrides.shield ?? "auto";
    if (mode === "never") return false;
    // Released for a tick whenever the simulation asks for a fresh press.
    if (mode === "always") return !me.shieldNeedsRelease;
    if (mode === "flick") {
      if (me.shieldUp) return tick - me.shieldRaisedAt < this.tuning.shield.parryWindowTicks + 1;
      return this.lastSeen !== null && !me.shieldNeedsRelease && tick - me.shieldLoweredAt >= this.tuning.shield.reRaiseTicks;
    }
    const plan = this.shieldPlan;
    if (!plan) return false;
    if (tick >= plan.lowerAt) { this.shieldPlan = null; return false; }
    if (me.shieldBrokenUntil > tick) { this.shieldPlan = null; return false; }
    return tick >= plan.raiseAt;
  }

  // ------------------------------------------------------------ aim and fire

  private aimAt(obs: Observation, target: Sighting | null, move: { x: number; z: number }): { dist: number; off: number; tol: number; yaw: number; pitch: number } {
    const me = obs.me;
    const tick = obs.tick;
    const t = this.tuning;
    const p = this.params;
    if (target) {
      const m = muzzleOf(t, { x: me.x, z: me.z, yaw: this.aim.yaw });
      const dist = Math.hypot(target.x - m.x, target.z - m.z);
      const flight = dist / t.blaster.boltSpeed;
      const lead = flight * p.leadSkill * (1 + this.leadErr);
      let ax = target.x + target.vx * lead;
      let az = target.z + target.vz * lead;
      if (target.dodging) {
        // A roll slows to a stop: aim where it will end (read with the bot's lead skill).
        const v = Math.hypot(target.vx, target.vz);
        const decel = (2 * t.dodge.distance) / (t.dodge.durationTicks / TICK_RATE) ** 2;
        const rest = v > 0.1 ? ((v * v) / (2 * decel)) * p.leadSkill : 0;
        ax = target.x + (target.vx / Math.max(v, 1e-6)) * rest;
        az = target.z + (target.vz / Math.max(v, 1e-6)) * rest;
      }
      const ay = this.aimHead ? 1.62 : CHEST_HEIGHT;
      const yaw = yawOf(ax - m.x, az - m.z);
      const pitch = Math.atan2(ay - m.y, Math.hypot(ax - m.x, az - m.z));
      // Pull against the recoil climb (partly).
      const cy = yaw - me.recoilYaw * DEG * p.recoilComp;
      const cp = pitch - me.recoilPitch * DEG * p.recoilComp;
      this.aim.update(tick, cy, cp, true);
      const effYaw = this.aim.yaw + me.recoilYaw * DEG;
      const effPitch = this.aim.pitch + me.recoilPitch * DEG;
      const off = Math.hypot(angleDiff(effYaw, yaw) * Math.cos(pitch), effPitch - pitch);
      const tol = Math.atan2(t.body.hitRadius, Math.max(1, dist)) * p.fireTolerance;
      return { dist, off, tol, yaw, pitch };
    }
    // No target: pre-aim where it was last seen (or heard), else look where walking.
    let ref: Pt | null = this.lastSeen && tick - this.lastSeen.tick < 240 ? this.lastSeen : this.heard && this.heard.tick <= tick ? this.heard : null;
    if (!ref && this.action === "watch") ref = this.arena.def.spawns[1 - me.side];
    let yaw = this.aim.yaw;
    const ml = Math.hypot(move.x, move.z);
    if (ref && (ml < 0.1 || Math.hypot(ref.x - me.x, ref.z - me.z) < 18)) yaw = yawOf(ref.x - me.x, ref.z - me.z);
    // Searching: sweep the camera across the way ahead, or turn slowly on the spot.
    else if (ml > 0.1) yaw = yawOf(move.x, move.z) + Math.sin(tick / 40) * 50 * DEG;
    else yaw = this.aim.yaw + 1.5 * DEG;
    this.aim.update(tick, yaw, 0, false);
    return { dist: 0, off: Math.PI, tol: 0, yaw, pitch: 0 };
  }

  private wantFire(obs: Observation, target: Sighting | null, visibleNow: boolean, aim: { dist: number; off: number; tol: number }): boolean {
    const me = obs.me;
    const tick = obs.tick;
    const p = this.params;
    const mode = this.overrides.fire ?? "auto";
    if (mode === "never" || !target || me.ventStart >= 0) return false;
    if (!visibleNow && tick - (this.lastSeen?.tick ?? -1000) > 6) return false;
    if (aim.off > aim.tol) return false;
    // Bolts into a roll mostly miss; skilled bots save the heat for where it ends.
    if (mode !== "spam" && target.dodging && this.rng.chance(p.leadSkill)) return false;
    if (mode === "spam") return true;
    const finishing = obs.enemyHealth < 25;
    const punishing = tick - this.enemyShieldDropAt < ms(450);
    const cap = finishing || punishing ? 100 : p.heatCap;
    if (me.heat + this.tuning.blaster.heatPerShot > cap) return false;
    if (target.shieldUp && this.shieldCoversMe(target, me)) {
      const fresh = tick - this.enemyShieldSince < ms(380);
      if (fresh && this.baitThisRaise) return false;
      // A long block: drain it while the heat allows, else wait it out.
      if (!fresh && me.heat > 55 && this.rng.chance(p.baitPunish)) return false;
    }
    return true;
  }

  private shieldCoversMe(target: Sighting, me: Pt): boolean {
    const toMe = yawOf(me.x - target.x, me.z - target.z);
    return Math.abs(angleDiff(target.yaw, toMe)) <= this.tuning.shield.arcHalfDeg * DEG;
  }

  private wantVent(obs: Observation, target: Sighting | null, firing: boolean): boolean {
    const me = obs.me;
    const tick = obs.tick;
    if (this.overrides.vent === "never") return false;
    if (tick - this.lastVentPress < 2) return false;
    const press = () => { this.lastVentPress = tick; return true; };
    if (this.overrides.vent === "edge" && me.ventStart < 0 && !firing && me.heat + this.tuning.blaster.heatPerShot > this.params.heatCap) return press();
    if (me.ventStart >= 0) {
      if (me.ventAttempted) return false;
      if (this.ventCycle !== me.ventStart) {
        this.ventCycle = me.ventStart;
        const centre = (me.ventWinStart + me.ventWinEnd) / 2;
        const underFire = this.bolts.size > 0 && obs.bolts.some((b) => b.owner !== this.slot);
        const sd = ms(this.params.ventTimingSdMs) * (underFire ? 1.5 : 1);
        this.ventPressAt = Math.max(me.ventStart + 2, Math.round(centre + this.rng.normal(0, sd)));
      }
      return tick === this.ventPressAt ? press() : false;
    }
    if (firing || me.heat < 20) return false;
    const safe = !target || (target.shieldUp && this.shieldCoversMe(target, me)) || target.venting;
    const hiding = this.cover !== null && this.cover.state === "hide";
    if ((safe && me.heat >= 45) || (hiding && me.heat >= 20)) return press();
    return false;
  }
}

/** When a bolt passes closest to me (seconds) and how close (metres); null when moving away. */
export function threat(b: BoltSighting, me: Pt): { t: number; miss: number } | null {
  const vv = b.vx * b.vx + b.vz * b.vz;
  if (vv < 1e-6) return null;
  const ex = me.x - b.x;
  const ez = me.z - b.z;
  const t = (ex * b.vx + ez * b.vz) / vv;
  if (t <= 0) return null;
  const qx = b.x + b.vx * t - me.x;
  const qz = b.z + b.vz * t - me.z;
  return { t, miss: Math.hypot(qx, qz) };
}

