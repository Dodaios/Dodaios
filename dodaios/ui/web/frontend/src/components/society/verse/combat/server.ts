/**
 * The authoritative duel server. It owns the MatchState; players (human or
 * bot, local or remote) only send InputCommands.
 *
 * - Accepts channels; a duel starts once two players said hello with the
 *   same protocol version and tuning.
 * - Runs the fixed 60 Hz step on its own clock (`update(nowMs)`).
 * - Each player's inputs go into a queue; one is applied per tick. A late
 *   player's last input is repeated (held buttons stay held, presses are not
 *   repeated); a queue that grows past `maxQueue` is trimmed so a player who
 *   fell behind catches up instead of lagging forever.
 * - Every `snapshotEvery` ticks each player gets the full state, the last
 *   input it applied for them (`ackSeq`, for reconciliation) and the events
 *   of the last two snapshot periods (repeated so a lost snapshot loses no
 *   effects; clients drop duplicates by eventKey).
 * - Leave or a closed channel ends the match for the other player.
 *
 * Runs in the browser today (in-process, LocalNetwork) and unchanged in Node
 * behind a WebSocket later.
 */
import { decodeInput, encodeState, PROTOCOL_VERSION, type ClientMsg, type EncodedInput, type ServerMsg } from "./protocol";
import { createMatch, endMatch, rulesHash, step, type SimContext } from "./sim";
import { TICK_RATE } from "./tuning";
import { EDGE_BUTTONS, type CombatEvent, type InputCommand, type MatchConfig, type MatchState } from "./types";
import type { ServerChannel } from "./transport";

/** Events kept for clients that stop confirming snapshots (ticks). Older ones are dropped. */
const EVENT_WINDOW_TICKS = 90;

const isInt = (v: unknown): v is number => typeof v === "number" && Number.isInteger(v);

export interface MatchServerOptions {
  ctx: SimContext;
  seed: number;
  matchId?: string;
  config?: Partial<MatchConfig>;
  /** Send a snapshot every N ticks (1 = 60 Hz in-process, 2 = 30 Hz over a network). */
  snapshotEvery?: number;
  /** Inputs buffered per player before the oldest are dropped. */
  maxQueue?: number;
  /** Rewind shots to what the shooter saw (PvP over a network). */
  lagCompensation?: boolean;
}

interface Conn {
  channel: ServerChannel;
  playerId: string;
  name: string;
  slot: number;
  queue: InputCommand[];
  lastQueued: number;
  /** Newest snapshot tick the client says it has (from its input messages). */
  snapAck: number;
  unsub: (() => void)[];
}

export class MatchServer {
  state: MatchState | null = null;
  readonly matchId: string;
  private readonly ctx: SimContext;
  private readonly opts: Required<Omit<MatchServerOptions, "ctx" | "config" | "matchId">> & { config?: Partial<MatchConfig> };
  private readonly hash: number;
  private conns: Conn[] = [];
  private lobby: { channel: ServerChannel; unsub: (() => void)[] }[] = [];
  private acc = 0;
  private lastNow: number | null = null;
  private recent: CombatEvent[] = [];
  private listeners = new Set<(events: readonly CombatEvent[], state: MatchState) => void>();
  private ended = false;

  constructor(o: MatchServerOptions) {
    this.ctx = o.ctx;
    this.matchId = o.matchId ?? `duel-${(o.seed >>> 0).toString(36)}`;
    this.opts = { seed: o.seed, snapshotEvery: o.snapshotEvery ?? 2, maxQueue: o.maxQueue ?? 6, lagCompensation: o.lagCompensation ?? false, config: o.config };
    this.hash = rulesHash(o.ctx);
  }

  /** Every step's events and the new state (for logging or a spectator). */
  onStep(cb: (events: readonly CombatEvent[], state: MatchState) => void): () => void {
    this.listeners.add(cb);
    return () => this.listeners.delete(cb);
  }

  accept(channel: ServerChannel): void {
    const entry = { channel, unsub: [] as (() => void)[] };
    entry.unsub.push(channel.onMessage((msg) => this.lobbyMessage(entry, msg)));
    this.lobby.push(entry);
  }

  private lobbyMessage(entry: { channel: ServerChannel; unsub: (() => void)[] }, msg: ClientMsg): void {
    if (!Array.isArray(msg) || msg[0] !== "h") return;
    const [, v, playerId, name, hash] = msg;
    const reject = (why: string) => { entry.channel.send(["r", why]); entry.channel.close(); };
    if (v !== PROTOCOL_VERSION) return reject(`protocol ${v} != ${PROTOCOL_VERSION}`);
    if (hash !== this.hash) return reject("tuning or arena differs");
    if (typeof playerId !== "string" || playerId.length === 0 || playerId.length > 64) return reject("bad player id");
    if (this.state || this.conns.length >= 2) return reject("match full");
    if (this.conns.some((c) => c.playerId === playerId)) return reject("duplicate player");
    for (const u of entry.unsub) u();
    this.lobby = this.lobby.filter((l) => l !== entry);
    const conn: Conn = { channel: entry.channel, playerId, name: String(name ?? playerId).slice(0, 64), slot: this.conns.length, queue: [], lastQueued: -1, snapAck: -1, unsub: [] };
    conn.unsub.push(conn.channel.onMessage((m) => this.message(conn, m)));
    conn.unsub.push(conn.channel.onClose(() => this.drop(conn, "disconnect")));
    this.conns.push(conn);
    if (this.conns.length === 2) this.start();
  }

  private start(): void {
    const ctx = this.ctx;
    this.state = createMatch(ctx, { seed: this.opts.seed, playerIds: this.conns.map((c) => c.playerId), config: this.opts.config });
    const ids = this.conns.map((c) => c.playerId);
    for (const c of this.conns) {
      c.channel.send(["w", PROTOCOL_VERSION, c.slot, this.matchId, this.state.seed, this.hash, ctx.arena.def.id, this.opts.snapshotEvery, this.state.config, ids]);
    }
    this.sendSnapshots();
  }

  /**
   * A client message. Nothing from the wire is trusted: malformed messages are
   * ignored, and inputs are made legal by the simulation (sanitizeInput).
   */
  private message(c: Conn, msg: ClientMsg): void {
    if (!Array.isArray(msg)) return;
    if (msg[0] === "i") {
      const list = msg[2];
      if (!Array.isArray(list)) return;
      if (isInt(msg[1]) && msg[1] > c.snapAck && (!this.state || msg[1] <= this.state.tick)) c.snapAck = msg[1];
      for (const e of list.slice(-32) as EncodedInput[]) {
        if (!Array.isArray(e) || !isInt(e[0])) continue;
        const cmd = decodeInput(e);
        if (cmd.seq <= c.lastQueued) continue;
        c.queue.push(cmd);
        c.lastQueued = cmd.seq;
      }
    } else if (msg[0] === "l") {
      this.drop(c, "forfeit");
    } else if (msg[0] === "p") {
      if (typeof msg[1] === "number") c.channel.send(["o", msg[1], this.state ? this.state.tick : 0]);
    }
  }

  private drop(c: Conn, reason: "forfeit" | "disconnect"): void {
    if (this.state && this.state.phase !== "ended") {
      const res = endMatch(this.state, 1 - c.slot, reason);
      this.state = res.state;
      this.publish(res.events);
      this.finish();
    }
  }

  /** Run every tick due by `nowMs`. */
  update(nowMs: number): void {
    if (this.lastNow === null) this.lastNow = nowMs;
    const dt = Math.min(250, Math.max(0, nowMs - this.lastNow));
    this.lastNow = nowMs;
    if (!this.state || this.ended) return;
    this.acc += dt;
    const tickMs = 1000 / TICK_RATE;
    while (this.acc >= tickMs && this.state && !this.ended) {
      this.acc -= tickMs;
      this.tick();
    }
  }

  /** One authoritative tick (also usable directly by a headless host). */
  tick(): void {
    const s = this.state;
    if (!s || this.ended) return;
    const cmds: (InputCommand | null)[] = [];
    for (const c of this.conns) {
      // A player who fell behind catches up: the oldest inputs are dropped,
      // but their presses (roll, vent, forfeit) carry over into the next one.
      let carry = 0;
      while (c.queue.length > this.opts.maxQueue) carry |= (c.queue.shift() as InputCommand).buttons & EDGE_BUTTONS;
      let cmd = c.queue.shift() ?? null;
      if (cmd && carry) cmd = { ...cmd, buttons: cmd.buttons | carry };
      cmds[c.slot] = cmd && !this.opts.lagCompensation ? { ...cmd, viewTick: -1 } : cmd;
    }
    const res = step(s, cmds, this.ctx);
    this.state = res.state;
    this.publish(res.events);
    if (this.state.tick % this.opts.snapshotEvery === 0 || this.state.phase === "ended") this.sendSnapshots();
    if (this.state.phase === "ended") this.finish();
  }

  private publish(events: readonly CombatEvent[]): void {
    if (!this.state) return;
    const tick = this.state.tick;
    let cut = 0;
    while (cut < this.recent.length && tick - this.recent[cut].tick > EVENT_WINDOW_TICKS) cut++;
    this.recent = (cut > 0 ? this.recent.slice(cut) : this.recent).concat(events);
    for (const l of [...this.listeners]) l(events, this.state);
  }

  /**
   * Events a client still needs: everything since the newest snapshot it
   * confirmed (it got the events up to that tick with it), at least the last
   * two snapshot periods, at most EVENT_WINDOW_TICKS. A lost snapshot thus
   * loses no effect; the client drops repeats by eventKey.
   */
  private eventsFor(c: Conn, tick: number): CombatEvent[] {
    const from = Math.max(tick - EVENT_WINDOW_TICKS, Math.min(c.snapAck - 1, tick - this.opts.snapshotEvery * 2));
    let i = 0;
    while (i < this.recent.length && this.recent[i].tick < from) i++;
    return i === 0 ? this.recent : this.recent.slice(i);
  }

  private sendSnapshots(): void {
    const s = this.state;
    if (!s) return;
    const enc = encodeState(s);
    for (const c of this.conns) {
      const ack = s.players[c.slot].lastSeq;
      c.channel.send(["s", s.tick, ack, enc, this.eventsFor(c, s.tick)] as ServerMsg);
    }
  }

  private finish(): void {
    if (this.ended || !this.state) return;
    this.ended = true;
    const s = this.state;
    const enc = encodeState(s);
    for (const c of this.conns) {
      // Reliable, and with the final snapshot inside: the end can never arrive
      // without the last state and its events (death, round and match end).
      c.channel.send(["e", s.winner ?? -1, s.endReason ?? "cancelled", s.scores.slice(), s.tick, s.players[c.slot].lastSeq, enc, this.eventsFor(c, s.tick)]);
      for (const u of c.unsub) u();
    }
  }

  /** Stop the match now (host closed the duel). */
  cancel(): void {
    if (!this.state || this.ended) return;
    const res = endMatch(this.state, -1, "cancelled");
    this.state = res.state;
    this.publish(res.events);
    this.finish();
  }

  get finished(): boolean {
    return this.ended;
  }
}
