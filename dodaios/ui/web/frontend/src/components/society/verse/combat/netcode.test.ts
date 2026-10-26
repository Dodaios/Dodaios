// @vitest-environment node
import { describe, expect, it } from "vitest";
import { MatchClient } from "./client";
import { idleControl, makeInput, type ControlState } from "./input";
import { decodeInput, decodeState, encodeInput, encodeState, PROTOCOL_VERSION, wireSize, type ServerMsg } from "./protocol";
import { MatchServer } from "./server";
import { createContext, historyAt, step } from "./sim";
import { liveMatch, place, runner } from "./testing";
import { LocalNetwork, socketChannel, type LinkOptions, type SocketLike } from "./transport";
import { DEFAULT_TUNING, withTuning } from "./tuning";
import type { MatchState } from "./types";

describe("protocol", () => {
  it("round-trips a mid-duel state exactly (all but the server's pose history)", () => {
    const { ctx, state } = liveMatch();
    const r = runner(ctx, place(state, { x: 38.8, z: 12 }, { x: 38.8, z: 28 }));
    r.run(200, (s) => ({ fire: s.tick % 50 < 30, moveX: Math.sin(s.tick / 9), ads: true, vent: s.tick % 97 === 0 }),
      (s) => ({ shield: s.tick % 40 < 15, moveY: -0.5, fire: s.tick % 40 > 20, dodge: s.tick % 77 === 0 }));
    expect(r.state.bolts.length).toBeGreaterThan(0);
    const back = decodeState(JSON.parse(JSON.stringify(encodeState(r.state))), r.state.config);
    expect(back).toEqual({ ...r.state, history: { ticks: [], poses: [] } });
  });

  it("round-trips inputs and keeps a snapshot small", () => {
    const cmd = makeInput(77, { ...idleControl(-2.5, 0.31), moveX: -0.4, moveY: 0.9, fire: true, shield: true }, 1234);
    expect(decodeInput(encodeInput(cmd))).toEqual(cmd);
    const { state } = liveMatch();
    const msg: ServerMsg = ["s", state.tick, 5, encodeState(state), []];
    expect(wireSize(msg)).toBeLessThan(900);
  });
});

describe("local transport", () => {
  it("delays, jitters, drops only unreliable messages, and keeps reliable ones in order", () => {
    const net = new LocalNetwork(3);
    const { client, server, stats } = net.link({ latencyMs: 50, jitterMs: 30, loss: 0.3 });
    const got: string[] = [];
    server.onMessage((m) => got.push(m[0] === "p" ? `p${m[1]}` : m[0]));
    client.send(["h", PROTOCOL_VERSION, "a", "a", 0]);
    for (let i = 0; i < 200; i++) client.send(["p", i]);
    client.send(["l"]);
    net.advance(49);
    expect(got).toEqual([]);
    net.advance(200);
    // Reliable messages all arrive, in their own order (unreliable ones may overtake them).
    expect(got.filter((g) => g === "h" || g === "l")).toEqual(["h", "l"]);
    const pings = got.filter((g) => g.startsWith("p")).length;
    expect(pings).toBeGreaterThan(100);
    expect(pings).toBeLessThan(180);
    expect(stats.up.dropped).toBe(200 - pings);
  });

  it("adapts a WebSocket-like object", () => {
    const handlers: Record<string, ((ev: { data: unknown }) => void)[]> = { message: [], close: [] };
    const sent: string[] = [];
    const ws = {
      readyState: 1,
      send: (d: string) => sent.push(d),
      close: () => undefined,
      addEventListener: (type: string, cb: (ev: { data: unknown }) => void) => handlers[type].push(cb),
    } as unknown as SocketLike;
    const ch = socketChannel<["p", number], ["o", number, number]>(ws);
    const got: unknown[] = [];
    ch.onMessage((m) => got.push(m));
    ch.send(["p", 1]);
    handlers.message[0]({ data: JSON.stringify(["o", 1, 2]) });
    handlers.message[0]({ data: "not json" });
    expect(sent).toEqual(['["p",1]']);
    expect(got).toEqual([["o", 1, 2]]);
  });
});

interface Rig {
  net: LocalNetwork;
  server: MatchServer;
  a: MatchClient;
  b: MatchClient;
  now: number;
  run(ms: number, ca?: (s: MatchState) => Partial<ControlState>, cb?: (s: MatchState) => Partial<ControlState>): void;
}

function rig(link: LinkOptions = {}, opts: { snapshotEvery?: number; lagCompensation?: boolean; skipCountdown?: boolean } = {}): Rig {
  const ctx = createContext();
  const net = new LocalNetwork(5);
  const server = new MatchServer({ ctx, seed: 21, snapshotEvery: opts.snapshotEvery ?? 1, lagCompensation: opts.lagCompensation });
  const la = net.link(link);
  const lb = net.link(link);
  server.accept(la.server);
  server.accept(lb.server);
  const a = new MatchClient({ ctx, channel: la.client, playerId: "a" });
  const b = new MatchClient({ ctx, channel: lb.client, playerId: "b" });
  const r: Rig = {
    net, server, a, b, now: 0,
    run(ms, ca, cb) {
      for (let t = 0; t < ms; t += 4) {
        r.now += 4;
        net.advance(r.now);
        server.update(r.now);
        net.advance(r.now);
        for (const [c, f] of [[a, ca], [b, cb]] as const) {
          const s = c.state;
          if (s && f) { const me = s.players[c.slot]; c.setControl({ ...idleControl(me.yaw, me.pitch), ...f(s) }); }
          c.update(r.now);
        }
        net.advance(r.now);
      }
    },
  };
  r.run(50);
  return r;
}

describe("server and clients", () => {
  it("start a duel once both said hello, with the same match on both sides", () => {
    const r = rig();
    expect(r.a.status).toBe("playing");
    expect(r.b.status).toBe("playing");
    expect([r.a.slot, r.b.slot].sort()).toEqual([0, 1]);
    expect(r.a.matchId).toBe(r.server.matchId);
  });

  it("predict their own player exactly when nothing else interferes", () => {
    const r = rig();
    r.run(9000, (s) => ({ moveY: 1, moveX: Math.sin(s.tick / 30), fire: s.tick % 120 < 60, ads: s.tick % 200 < 80, sprint: s.tick % 300 < 40, dodge: s.tick % 170 === 0 }));
    expect(r.a.prediction.checked).toBeGreaterThan(300);
    expect(r.a.prediction.corrections).toBe(0);
    expect(r.a.prediction.maxErrorM).toBe(0);
  });

  it("stay close under latency, jitter and loss, and the server applies nearly every input", () => {
    const r = rig({ latencyMs: 70, jitterMs: 25, loss: 0.08 }, { snapshotEvery: 2 });
    r.run(12000, (s) => ({ moveY: 1, moveX: Math.sin(s.tick / 25), fire: s.tick % 90 < 45 }), (s) => ({ moveX: Math.cos(s.tick / 40), fire: s.tick % 70 < 30 }));
    const p = r.a.prediction;
    expect(p.checked).toBeGreaterThan(200);
    // Mispredictions come from lost or late inputs and the opponent's hits; they stay small.
    expect(p.maxErrorM).toBeLessThan(0.75);
    expect(p.corrections / p.checked).toBeLessThan(0.35);
    const server = r.server.state as MatchState;
    const applied = server.players[r.a.slot].lastSeq;
    // About 12 s of inputs, all but the ones still in flight were applied.
    expect(applied).toBeGreaterThan(600);
  });

  it("show the opponent smoothly from snapshots", () => {
    const r = rig({ latencyMs: 40, jitterMs: 15 }, { snapshotEvery: 2 });
    r.run(3500); // through the countdown
    let last: { x: number; z: number } | null = null;
    let worst = 0;
    for (let i = 0; i < 300; i++) {
      r.run(8, undefined, (s) => ({ moveY: 1, moveX: Math.sin(s.tick / 20) }));
      const v = r.a.view();
      const other = v?.players.find((p) => !p.local);
      if (other && last) worst = Math.max(worst, Math.hypot(other.x - last.x, other.z - last.z));
      if (other) last = { x: other.x, z: other.z };
    }
    // 8 ms frames at <= 7 m/s: no teleports.
    expect(worst).toBeLessThan(0.25);
  });

  it("end the match for the other player when one leaves or drops", () => {
    const r = rig();
    r.a.forfeit();
    r.run(50);
    expect(r.b.status).toBe("ended");
    expect(r.b.result?.winner).toBe(r.b.slot);
    expect(r.b.result?.reason).toBe("forfeit");

    const d = rig();
    const ended: string[] = [];
    d.server.onStep((ev) => { for (const e of ev) if (e.type === "match_end") ended.push(e.reason); });
    // Pull the plug on a.
    (d.a as unknown as { channel: { close(): void } }).channel.close();
    d.run(50);
    expect(ended).toEqual(["disconnect"]);
    expect(d.b.result?.winner).toBe(d.b.slot);
  });

  it("reject a client with other balance numbers or a third player", () => {
    const ctx = createContext();
    const net = new LocalNetwork();
    const server = new MatchServer({ ctx, seed: 1 });
    const l1 = net.link();
    server.accept(l1.server);
    const odd = new MatchClient({ ctx: createContext(undefined, withTuning(DEFAULT_TUNING, { blaster: { damageNear: 99 } })), channel: l1.client, playerId: "x" });
    net.advance(10);
    expect(odd.status).toBe("rejected");
    expect(odd.rejectReason).toContain("tuning");
    const r = rig();
    const l3 = r.net.link();
    r.server.accept(l3.server);
    const third = new MatchClient({ ctx: createContext(), channel: l3.client, playerId: "c" });
    r.run(20);
    expect(third.status).toBe("rejected");
  });
});

describe("lag compensation", () => {
  it("flies a late shot through the poses the shooter saw", () => {
    const tuning = withTuning(DEFAULT_TUNING, {
      blaster: { hipSpreadDeg: 0, moveSpreadHipDeg: 0, bloomPerShotHipDeg: 0, recoilPitchHipDeg: 0, recoilYawDeg: 0 },
    });
    const { ctx, state } = liveMatch({ tuning });
    // b stood 6 m ahead of a, then stepped aside; a saw it there 8 ticks ago and fires at it.
    let s = place(state, { x: 38.8, z: 14 }, { x: 38.8, z: 20 });
    const idle = (seq: number) => makeInput(seq, idleControl(0, 0));
    for (let i = 0; i < 10; i++) s = step(s, [idle(i), idle(i)], ctx).state;
    const seen = s.tick - 8;
    expect(historyAt(s, seen)).not.toBeNull();
    s = JSON.parse(JSON.stringify(s));
    s.players[1].x = 41.5; // moved out of the line of fire since
    const shot = (viewTick: number) => {
      let t = s;
      const hits: number[] = [];
      for (let i = 0; i < 30; i++) {
        const res = step(t, [i === 0 ? makeInput(10, { ...idleControl(0, 0), fire: true }, viewTick) : idle(11 + i), idle(11 + i)], ctx);
        t = res.state;
        for (const e of res.events) if (e.type === "hit") hits.push(e.target);
      }
      return hits;
    };
    expect(shot(-1)).toEqual([]);
    expect(shot(seen)).toEqual([1]);
  });
});
