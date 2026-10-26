/**
 * How duel messages travel. Server and clients only see a Channel; what is
 * behind it is a detail:
 *
 * - LocalNetwork: in-process links on a virtual clock, with optional
 *   latency, jitter and loss (seeded) for tests and for practising against
 *   lag. Messages go through JSON on the way, like on a real wire.
 * - socketChannel: a thin adapter for a WebSocket (browser or Node) for the
 *   later PvP server. A WebSocket is reliable and ordered; the protocol also
 *   tolerates an unreliable channel (inputs are repeated, snapshots are full).
 */
import { isReliable, type ClientMsg, type ServerMsg } from "./protocol";
import { Rng } from "./rng";

export interface Channel<Out, In> {
  send(msg: Out): void;
  /** Subscribe; returns the unsubscribe. */
  onMessage(cb: (msg: In) => void): () => void;
  onClose(cb: () => void): () => void;
  close(): void;
  readonly open: boolean;
}

export type ClientChannel = Channel<ClientMsg, ServerMsg>;
export type ServerChannel = Channel<ServerMsg, ClientMsg>;

export interface LinkOptions {
  /** One-way delay, ms. */
  latencyMs?: number;
  /** Extra random delay 0..jitter, ms (unreliable messages may arrive out of order). */
  jitterMs?: number;
  /** Chance an unreliable message is dropped. */
  loss?: number;
}

interface Packet { at: number; order: number; text: string; deliver: (text: string) => void }

class Endpoint<Out, In> implements Channel<Out, In> {
  open = true;
  peer: Endpoint<In, Out> | null = null;
  private listeners = new Set<(msg: In) => void>();
  private closers = new Set<() => void>();
  private lastReliableAt = 0;

  constructor(private readonly net: LocalNetwork, private readonly opts: Required<LinkOptions>, private readonly rng: Rng, readonly stats: { sent: number; bytes: number; dropped: number }) {}

  send(msg: Out): void {
    if (!this.open || !this.peer) return;
    const text = JSON.stringify(msg);
    this.stats.sent++;
    this.stats.bytes += text.length;
    const reliable = isReliable(msg as unknown as ClientMsg | ServerMsg);
    if (!reliable && this.opts.loss > 0 && this.rng.next() < this.opts.loss) { this.stats.dropped++; return; }
    let at = this.net.now + this.opts.latencyMs + (this.opts.jitterMs > 0 ? this.rng.next() * this.opts.jitterMs : 0);
    if (reliable) { at = Math.max(at, this.lastReliableAt); this.lastReliableAt = at; }
    const peer = this.peer;
    this.net.enqueue(at, (t) => peer.receive(t), text);
  }

  receive(text: string): void {
    if (!this.open) return;
    const msg = JSON.parse(text) as In;
    for (const l of [...this.listeners]) l(msg);
  }

  onMessage(cb: (msg: In) => void): () => void {
    this.listeners.add(cb);
    return () => this.listeners.delete(cb);
  }

  onClose(cb: () => void): () => void {
    this.closers.add(cb);
    return () => this.closers.delete(cb);
  }

  close(): void {
    if (!this.open) return;
    this.open = false;
    for (const c of [...this.closers]) c();
    const peer = this.peer;
    if (peer && peer.open) this.net.enqueue(this.net.now + this.opts.latencyMs, () => peer.close(), "");
  }
}

/** In-process network on a virtual clock (milliseconds). */
export class LocalNetwork {
  now = 0;
  private queue: Packet[] = [];
  private order = 0;
  private readonly rng: Rng;

  constructor(seed = 1) {
    this.rng = new Rng(seed);
  }

  /** A client/server pair of channels. */
  link(opts: LinkOptions = {}): { client: ClientChannel; server: ServerChannel; stats: { up: { sent: number; bytes: number; dropped: number }; down: { sent: number; bytes: number; dropped: number } } } {
    const o: Required<LinkOptions> = { latencyMs: opts.latencyMs ?? 0, jitterMs: opts.jitterMs ?? 0, loss: opts.loss ?? 0 };
    const up = { sent: 0, bytes: 0, dropped: 0 };
    const down = { sent: 0, bytes: 0, dropped: 0 };
    const client = new Endpoint<ClientMsg, ServerMsg>(this, o, this.rng.fork(this.order + 1), up);
    const server = new Endpoint<ServerMsg, ClientMsg>(this, o, this.rng.fork(this.order + 2), down);
    client.peer = server;
    server.peer = client;
    this.order += 2;
    return { client, server, stats: { up, down } };
  }

  enqueue(at: number, deliver: (text: string) => void, text: string): void {
    this.queue.push({ at, order: this.order++, text, deliver });
  }

  /** Move the clock and deliver everything due, in time order. */
  advance(nowMs: number): void {
    this.now = Math.max(this.now, nowMs);
    for (;;) {
      let best = -1;
      for (let i = 0; i < this.queue.length; i++) {
        const p = this.queue[i];
        if (p.at > this.now) continue;
        if (best < 0 || p.at < this.queue[best].at || (p.at === this.queue[best].at && p.order < this.queue[best].order)) best = i;
      }
      if (best < 0) return;
      const [p] = this.queue.splice(best, 1);
      p.deliver(p.text);
    }
  }

  get pending(): number {
    return this.queue.length;
  }
}

/** The part of a WebSocket the adapter needs (browser WebSocket and Node `ws` both fit). */
export interface SocketLike {
  readonly readyState: number;
  send(data: string): void;
  close(): void;
  addEventListener(type: "message", cb: (ev: { data: unknown }) => void): void;
  addEventListener(type: "close", cb: () => void): void;
}

/** A Channel over a WebSocket (JSON text frames). */
export function socketChannel<Out, In>(ws: SocketLike): Channel<Out, In> {
  const listeners = new Set<(msg: In) => void>();
  const closers = new Set<() => void>();
  let open = true;
  ws.addEventListener("message", (ev) => {
    if (typeof ev.data !== "string") return;
    let msg: In;
    try { msg = JSON.parse(ev.data) as In; } catch { return; }
    for (const l of [...listeners]) l(msg);
  });
  ws.addEventListener("close", () => {
    if (!open) return;
    open = false;
    for (const c of [...closers]) c();
  });
  return {
    get open() { return open && ws.readyState === 1; },
    send(msg: Out) { if (open && ws.readyState === 1) ws.send(JSON.stringify(msg)); },
    onMessage(cb) { listeners.add(cb); return () => listeners.delete(cb); },
    onClose(cb) { closers.add(cb); return () => closers.delete(cb); },
    close() { if (open) { open = false; ws.close(); for (const c of [...closers]) c(); } },
  };
}
