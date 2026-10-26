/**
 * A duel client: what a player's machine runs, human or bot.
 *
 * - Every 1/60 s it turns the current control state into an InputCommand,
 *   sends it (with the last few for loss), and steps its own copy of the
 *   match with it at once (prediction), so its own commander answers the
 *   keys without waiting for the server.
 * - On a snapshot it takes the server's state, drops the inputs the server
 *   has applied (ackSeq) and replays the rest (reconciliation). The state is
 *   quantised on both sides, so a replay matches the server exactly unless
 *   the opponent did something the client could not know.
 * - The opponent is shown from the snapshots, interpolated a little in the
 *   past (snapshot interpolation), never from guesses.
 * - Events of its own actions (shots, dodges, shield, vents) are played from
 *   the prediction at once; everything else from the server. Each event is
 *   played once (eventKey).
 */
import { buildView, type ViewState } from "./view";
import { idleControl, makeInput, type ControlState } from "./input";
import { lerpAngle } from "./math";
import { decodeState, encodeInput, PROTOCOL_VERSION, type EncodedState, type ServerMsg } from "./protocol";
import { rulesHash, step, type SimContext } from "./sim";
import { TICK_RATE } from "./tuning";
import { eventKey, type CombatEvent, type EndReason, type InputCommand, type MatchConfig, type MatchState, type PlayerState } from "./types";
import type { ClientChannel } from "./transport";
import type { WorldView } from "./observe";

export type ClientStatus = "connecting" | "playing" | "ended" | "rejected" | "closed";

export interface MatchClientOptions {
  ctx: SimContext;
  channel: ClientChannel;
  playerId: string;
  name?: string;
  /** How far behind the newest snapshot the opponent is shown, ticks (default: 2 snapshot periods + 2). */
  interpDelayTicks?: number;
  /** How many recent inputs each send repeats (default 3). */
  redundancy?: number;
  /**
   * A controller called every tick with what this client can see, instead of
   * `setControl` (bots).
   */
  controller?: (view: WorldView, slot: number) => ControlState;
}

interface Snap { tick: number; state: MatchState; recvMs: number }

/** Own-action events the client plays from its prediction. */
const PREDICTED = new Set<CombatEvent["type"]>(["shot", "dodge", "shield_up", "vent_start", "vent_perfect", "vent_miss", "overheat"]);

export class MatchClient {
  status: ClientStatus = "connecting";
  slot = -1;
  matchId = "";
  config: MatchConfig | null = null;
  rejectReason = "";
  result: { winner: number; reason: EndReason; scores: number[] } | null = null;
  /** Round-trip time estimate, ms. */
  rttMs = 0;
  /** Prediction check: snapshots compared with our guess for the same tick, how many differed, the worst position error (m). */
  readonly prediction = { checked: 0, corrections: 0, maxErrorM: 0 };
  private history = new Map<number, { x: number; z: number; health: number; heat: number; shieldUp: boolean }>();

  private readonly ctx: SimContext;
  private readonly channel: ClientChannel;
  private readonly opts: MatchClientOptions;
  private control: ControlState = idleControl();
  private latch = { dodge: false, vent: false, forfeit: false };
  private seq = 0;
  private pending: InputCommand[] = [];
  private sent: InputCommand[] = [];
  private predicted: MatchState | null = null;
  private prevPredicted: MatchState | null = null;
  private snaps: Snap[] = [];
  private acc = 0;
  private lastNow: number | null = null;
  private now = 0;
  private out: CombatEvent[] = [];
  private seen = new Map<string, number>();
  /** Events (deduplicated, authoritative or own predicted) not yet handed to the controller. */
  private viewEvents: CombatEvent[] = [];
  private snapshotEvery = 1;
  private unsub: (() => void)[] = [];
  private pingAt = 0;

  constructor(o: MatchClientOptions) {
    this.ctx = o.ctx;
    this.channel = o.channel;
    this.opts = o;
    this.unsub.push(o.channel.onMessage((m) => this.message(m)));
    this.unsub.push(o.channel.onClose(() => { if (this.status === "playing" || this.status === "connecting") this.status = "closed"; }));
    o.channel.send(["h", PROTOCOL_VERSION, o.playerId, o.name ?? o.playerId, rulesHash(o.ctx)]);
  }

  /** The player's current wish (keys and mouse). Presses are kept until a command carries them. */
  setControl(c: ControlState): void {
    this.control = c;
    if (c.dodge) this.latch.dodge = true;
    if (c.vent) this.latch.vent = true;
    if (c.forfeit) this.latch.forfeit = true;
  }

  forfeit(): void {
    if (this.status === "playing") this.channel.send(["l"]);
  }

  private message(m: ServerMsg): void {
    if (!Array.isArray(m)) return;
    switch (m[0]) {
      case "w": {
        this.slot = m[2];
        this.matchId = m[3];
        this.snapshotEvery = Math.max(1, m[7]);
        this.config = m[8];
        this.status = "playing";
        break;
      }
      case "s":
        this.snapshot(m[1], m[2], m[3], m[4]);
        break;
      case "e":
        // The final snapshot rides along, so its events and state are never lost.
        if (m.length >= 8) this.snapshot(m[4], m[5], m[6], m[7]);
        this.result = { winner: m[1], reason: m[2], scores: m[3] };
        this.status = "ended";
        break;
      case "o":
        this.rttMs = Math.max(0, this.now - m[1]);
        break;
      case "r":
        this.rejectReason = m[1];
        this.status = "rejected";
        break;
    }
  }

  private snapshot(tick: number, ack: number, enc: EncodedState, events: readonly CombatEvent[]): void {
    if (!this.config) return;
    const newest = this.snaps[this.snaps.length - 1];
    if (newest && tick <= newest.tick) {
      // Late or duplicate: only its events are of use.
      this.takeEvents(events);
      return;
    }
    const state = decodeState(enc, this.config);
    this.snaps.push({ tick, state, recvMs: this.now });
    if (this.snaps.length > 40) this.snaps.shift();
    this.takeEvents(events);
    this.reconcile(state, ack);
  }

  /** Server events; own actions already played from the prediction are dropped by key. */
  private takeEvents(events: readonly CombatEvent[]): void {
    for (const e of events) this.emit(e);
  }

  private emit(e: CombatEvent): void {
    const k = eventKey(e);
    if (this.seen.has(k)) return;
    this.seen.set(k, e.tick);
    this.out.push(e);
    if (this.opts.controller) this.viewEvents.push(e);
    if (this.seen.size > 2000) {
      const cutoff = e.tick - 600;
      for (const [key, t] of this.seen) if (t < cutoff) this.seen.delete(key);
    }
  }

  private inputsFor(cmd: InputCommand): (InputCommand | null)[] {
    const arr: (InputCommand | null)[] = [null, null];
    arr[this.slot] = cmd;
    return arr;
  }

  private reconcile(server: MatchState, ack: number): void {
    // How well did we predict ourselves? Compare our guess for this tick with the truth.
    const guess = this.history.get(server.tick);
    const truth = server.players[this.slot];
    if (guess && truth) {
      this.prediction.checked++;
      const err = Math.hypot(guess.x - truth.x, guess.z - truth.z);
      if (err > 1e-9 || guess.health !== truth.health || guess.heat !== truth.heat || guess.shieldUp !== truth.shieldUp) this.prediction.corrections++;
      this.prediction.maxErrorM = Math.max(this.prediction.maxErrorM, err);
    }
    this.pending = this.pending.filter((c) => c.seq > ack);
    let s = server;
    let prev = server;
    for (const c of this.pending) {
      prev = s;
      const res = step(s, this.inputsFor(c), this.ctx);
      s = res.state;
      this.predictedEvents(res.events);
    }
    this.prevPredicted = prev;
    this.predicted = s;
    this.remember(s);
  }

  /** Keep our predicted self per tick for the prediction check. */
  private remember(s: MatchState): void {
    const p = s.players[this.slot];
    if (!p) return;
    this.history.set(s.tick, { x: p.x, z: p.z, health: p.health, heat: p.heat, shieldUp: p.shieldUp });
    if (this.history.size > 240) {
      const cutoff = s.tick - 240;
      for (const t of this.history.keys()) if (t < cutoff) this.history.delete(t);
    }
  }

  private predictedEvents(events: readonly CombatEvent[]): void {
    for (const e of events) if ("player" in e && e.player === this.slot && PREDICTED.has(e.type)) this.emit(e);
  }

  /** Advance the client clock: build, send and predict every tick due. */
  update(nowMs: number): void {
    if (this.lastNow === null) this.lastNow = nowMs;
    const dt = Math.min(250, Math.max(0, nowMs - this.lastNow));
    this.lastNow = nowMs;
    this.now = nowMs;
    if (this.status !== "playing" || !this.predicted) return;
    if (nowMs - this.pingAt > 1000) { this.pingAt = nowMs; this.channel.send(["p", nowMs]); }
    this.acc += dt;
    const tickMs = 1000 / TICK_RATE;
    while (this.acc >= tickMs) {
      this.acc -= tickMs;
      this.clientTick();
    }
  }

  private clientTick(): void {
    if (!this.predicted) return;
    let c = this.control;
    if (this.opts.controller) c = this.opts.controller(this.worldView(), this.slot);
    else {
      c = { ...c, dodge: c.dodge || this.latch.dodge, vent: c.vent || this.latch.vent, forfeit: c.forfeit || this.latch.forfeit };
      this.latch = { dodge: false, vent: false, forfeit: false };
    }
    const viewTick = Math.floor(this.renderTick());
    const cmd = makeInput(this.seq++, c, viewTick);
    this.pending.push(cmd);
    this.sent.push(cmd);
    const red = this.opts.redundancy ?? 3;
    if (this.sent.length > red) this.sent.splice(0, this.sent.length - red);
    this.channel.send(["i", this.snaps.length ? this.snaps[this.snaps.length - 1].tick : -1, this.sent.map(encodeInput)]);
    this.prevPredicted = this.predicted;
    const res = step(this.predicted, this.inputsFor(cmd), this.ctx);
    this.predicted = res.state;
    this.predictedEvents(res.events);
    this.remember(this.predicted);
  }

  /** The server tick the opponent is drawn at (fractional). */
  renderTick(nowMs = this.now): number {
    const newest = this.snaps[this.snaps.length - 1];
    if (!newest) return 0;
    const delay = this.opts.interpDelayTicks ?? this.snapshotEvery * 2 + 2;
    const est = newest.tick + ((nowMs - newest.recvMs) * TICK_RATE) / 1000;
    return Math.min(est, newest.tick + this.snapshotEvery * 3) - delay;
  }

  /** An opponent interpolated between the snapshots around `tick`. */
  private remoteAt(slot: number, tick: number): PlayerState | null {
    const snaps = this.snaps;
    if (snaps.length === 0) return null;
    let a = snaps[0];
    let b = snaps[snaps.length - 1];
    if (tick <= a.tick) return a.state.players[slot];
    if (tick >= b.tick) return b.state.players[slot];
    for (let i = snaps.length - 1; i > 0; i--) {
      if (snaps[i - 1].tick <= tick) { a = snaps[i - 1]; b = snaps[i]; break; }
    }
    const t = (tick - a.tick) / Math.max(1, b.tick - a.tick);
    const pa = a.state.players[slot];
    const pb = b.state.players[slot];
    if (!pa.alive || !pb.alive || Math.hypot(pb.x - pa.x, pb.z - pa.z) > 6) return t < 0.5 ? pa : pb;
    return { ...pb, x: pa.x + (pb.x - pa.x) * t, z: pa.z + (pb.z - pa.z) * t, yaw: lerpAngle(pa.yaw, pb.yaw, t), pitch: pa.pitch + (pb.pitch - pa.pitch) * t, vx: pb.vx, vz: pb.vz };
  }

  /**
   * What this client sees now as a WorldView: its own predicted self, the
   * opponent interpolated, the predicted bolts, and the events that arrived
   * since the last call (each once).
   */
  worldView(): WorldView {
    const p = this.predicted as MatchState;
    const players = p.players.map((pl) => (pl.slot === this.slot ? pl : this.remoteAt(pl.slot, this.renderTick()) ?? pl));
    const events = this.viewEvents;
    this.viewEvents = [];
    return { tick: p.tick, phase: p.phase, round: p.round, scores: p.scores, players, bolts: p.bolts, events };
  }

  /** Presentation state for a frame at `nowMs` (own player smoothed between ticks). */
  view(nowMs = this.now): ViewState | null {
    if (!this.predicted) return null;
    const alpha = Math.min(1, this.acc / (1000 / TICK_RATE));
    const rt = this.renderTick(nowMs);
    const remote = this.predicted.players.map((pl) => (pl.slot === this.slot ? null : this.remoteAt(pl.slot, rt)));
    return buildView(this.ctx, this.predicted, this.prevPredicted ?? this.predicted, alpha, this.slot, remote, this.status);
  }

  /** Events to present since the last call (each once). */
  drainEvents(): CombatEvent[] {
    const out = this.out;
    this.out = [];
    return out;
  }

  /** The predicted match state (own present). */
  get state(): MatchState | null {
    return this.predicted;
  }

  /** The newest authoritative state received. */
  get serverState(): MatchState | null {
    return this.snaps.length ? this.snaps[this.snaps.length - 1].state : null;
  }

  /** Inputs sent but not yet confirmed by the server. */
  get unconfirmed(): number {
    return this.pending.length;
  }

  dispose(): void {
    for (const u of this.unsub) u();
    this.unsub = [];
  }
}

