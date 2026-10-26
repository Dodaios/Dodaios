// @vitest-environment node
/**
 * Adversarial netcode tests: a modified client (garbage, oversized or
 * malformed inputs), inputs arriving in bursts, a client built for another
 * arena, and whole bot duels over a jittery, lossy link (every event reaches
 * both clients exactly once, the end carries the final state, the same seeds
 * replay the same duel).
 */
import { describe, expect, it } from "vitest";
import { BotBrain } from "./bot/brain";
import { botParams, type BotTier } from "./bot/tiers";
import { MatchClient } from "./client";
import { idleControl, makeInput, sanitizeInput } from "./input";
import { observe } from "./observe";
import { PROTOCOL_VERSION, type ClientMsg } from "./protocol";
import { MatchServer } from "./server";
import { createContext, rulesHash, type SimContext } from "./sim";
import { LocalNetwork, type ClientChannel, type LinkOptions } from "./transport";
import { REACTOR_ARENA } from "./arenaReactor";
import { eventKey, type CombatEvent, type MatchState } from "./types";

const TICK_MS = 1000 / 60;

/** A server, one raw channel we drive by hand (the "cheater"), and an honest client. */
function rawRig(ctx: SimContext = createContext()) {
  const net = new LocalNetwork(1);
  const server = new MatchServer({ ctx, seed: 3, snapshotEvery: 1 });
  const la = net.link();
  const lb = net.link();
  server.accept(la.server);
  server.accept(lb.server);
  la.client.send(["h", PROTOCOL_VERSION, "raw", "raw", rulesHash(ctx)]);
  const honest = new MatchClient({ ctx, channel: lb.client, playerId: "honest" });
  let now = 0;
  let seq = 0;
  const steps: CombatEvent[] = [];
  server.onStep((ev) => steps.push(...ev));
  const tick = (send?: unknown) => {
    now += TICK_MS;
    if (send !== undefined) la.client.send(send as ClientMsg);
    net.advance(now);
    server.update(now);
    honest.update(now);
    net.advance(now);
  };
  const input = (mx: unknown, my: unknown, yaw: unknown, pitch: unknown, buttons: unknown) => ["i", -1, [[seq++, mx, my, yaw, pitch, buttons, -1]]];
  return { server, honest, tick, input, steps, get state() { return server.state as MatchState; }, nextSeq: () => seq++, raw: la.client };
}

describe("a modified client", () => {
  it("cannot move faster than the run speed, aim at NaN, or set unknown buttons", () => {
    const r = rawRig();
    for (let i = 0; i < 200; i++) r.tick(r.input(0, 0, 0, 0, 0));
    expect(r.state.phase).toBe("live");
    const p0 = { ...r.state.players[0] };
    // A full second of a 10x move stick, both axes.
    for (let i = 0; i < 60; i++) r.tick(r.input(1270, 1270, 0, 0, 0));
    const p1 = r.state.players[0];
    expect(Math.hypot(p1.x - p0.x, p1.z - p0.z)).toBeLessThanOrEqual(4.8 + 1e-6);
    // Strings, nulls and huge numbers where numbers belong.
    r.tick(r.input("x", null, "abc", 1e30, 0xffff));
    r.tick(r.input(Number.MAX_SAFE_INTEGER, -Number.MAX_SAFE_INTEGER, 31415926, -9e9, -1));
    const p = r.state.players[0];
    for (const k of ["x", "z", "vx", "vz", "yaw", "pitch", "heat", "health", "shieldEnergy"] as const) expect(Number.isFinite(p[k]), k).toBe(true);
    expect(Math.abs(p.pitch)).toBeLessThanOrEqual(1.2);
    expect(p.buttons & ~0x7f).toBe(0);
  });

  it("malformed messages are ignored, not thrown", () => {
    const r = rawRig();
    for (let i = 0; i < 10; i++) r.tick(r.input(0, 0, 0, 0, 0));
    const junk: unknown[] = [null, 42, "i", ["i"], ["i", -1, "nope"], ["i", -1, [null, "x", [], ["a"]]], ["p"], ["p", "x"], ["zz", 1]];
    for (const j of junk) expect(() => r.tick(j)).not.toThrow();
    // Still playing, and the honest player is unaffected.
    expect(r.server.finished).toBe(false);
    expect(r.honest.status).toBe("playing");
  });

  it("legal inputs pass the server's sanitising unchanged (so prediction still matches)", () => {
    for (let i = 0; i < 500; i++) {
      const a = (i * 0.731) % (2 * Math.PI) - Math.PI;
      const c = makeInput(i, { ...idleControl(a * 3, Math.sin(i) * 1.5), moveX: Math.cos(i * 1.3) * 1.4, moveY: Math.sin(i * 0.7) * 1.4, fire: i % 2 === 0, dodge: i % 7 === 0 }, i % 3 === 0 ? -1 : i);
      expect(sanitizeInput(c)).toEqual(c);
      expect(Math.hypot(c.mx, c.my)).toBeLessThanOrEqual(1);
    }
  });

  it("a press inside a burst of late inputs is not lost when the server catches up", () => {
    const r = rawRig();
    for (let i = 0; i < 220; i++) r.tick(r.input(0, 0, 0, 0, 0));
    expect(r.state.phase).toBe("live");
    // 200 ms of nothing, then twelve inputs at once; the roll press is in the second.
    const burst = [];
    for (let i = 0; i < 12; i++) burst.push([r.nextSeq(), 0, 127, 0, 0, i === 1 ? 8 : 0, -1]);
    const before = r.steps.length;
    r.tick(["i", -1, burst]);
    for (let i = 0; i < 20; i++) r.tick();
    expect(r.steps.slice(before).filter((e) => e.type === "dodge" && e.player === 0).length).toBe(1);
  });
});

describe("handshake", () => {
  it("rejects a client built for another arena (its predictions would hit other walls)", () => {
    const net = new LocalNetwork(2);
    const server = new MatchServer({ ctx: createContext(), seed: 1 });
    const l = net.link();
    server.accept(l.server);
    const moved = { ...REACTOR_ARENA, spawns: [{ ...REACTOR_ARENA.spawns[0], x: 39.4 }, REACTOR_ARENA.spawns[1]] as const };
    const c = new MatchClient({ ctx: createContext(moved), channel: l.client, playerId: "x" });
    net.advance(10);
    expect(c.status).toBe("rejected");
    expect(c.rejectReason).toContain("arena");
  });
});

interface NetDuel {
  server: MatchServer;
  clients: MatchClient[];
  published: CombatEvent[];
  presented: CombatEvent[][];
  finalServer: MatchState;
}

/** A whole bot duel through server, transport and two clients. */
function netDuel(seed: number, link: LinkOptions, tiers: [BotTier, BotTier] = ["hard", "elite"]): NetDuel {
  const ctx = createContext();
  const net = new LocalNetwork(seed);
  const server = new MatchServer({ ctx, seed, snapshotEvery: 2, lagCompensation: true });
  const links = [net.link(link), net.link(link)];
  for (const l of links) server.accept(l.server);
  const published: CombatEvent[] = [];
  server.onStep((ev) => published.push(...ev));
  const mk = (ch: ClientChannel, i: number) => {
    const box: { b: BotBrain | null } = { b: null };
    return new MatchClient({
      ctx, channel: ch, playerId: `p${i}`,
      controller: (v, slot) => {
        if (!box.b) box.b = new BotBrain(slot, botParams(tiers[i]), ctx.arena, ctx.tuning, seed * 31 + i);
        return box.b.think(observe(v, slot, ctx.arena, ctx.tuning));
      },
    });
  };
  const clients = links.map((l, i) => mk(l.client, i));
  const presented: CombatEvent[][] = [[], []];
  // Uneven frame times, like a real browser.
  let now = 0;
  for (let f = 0; f < 60 * 300 && !clients.every((c) => c.status === "ended"); f++) {
    now += 5 + ((f * 7919) % 13);
    net.advance(now);
    server.update(now);
    net.advance(now);
    for (const [i, c] of clients.entries()) { c.update(now); presented[i].push(...c.drainEvents()); }
    net.advance(now);
  }
  return { server, clients, published, presented, finalServer: server.state as MatchState };
}

describe("a whole duel over a bad link", () => {
  const bad = { latencyMs: 70, jitterMs: 40, loss: 0.15 };

  it("every event reaches both clients exactly once, and the end carries the final state", () => {
    const d = netDuel(7, bad);
    expect(d.finalServer.phase).toBe("ended");
    for (const [i, c] of d.clients.entries()) {
      expect(c.status).toBe("ended");
      // The last thing the client knows is the server's final state.
      expect(c.serverState?.tick).toBe(d.finalServer.tick);
      expect(c.serverState?.scores).toEqual(d.finalServer.scores);
      expect(c.result?.winner).toBe(d.finalServer.winner);
      const keys = d.presented[i].map(eventKey);
      expect(new Set(keys).size).toBe(keys.length); // never twice
      const got = new Set(keys);
      // Everything the server published was presented (own predicted actions count too).
      const missing = d.published.filter((e) => !got.has(eventKey(e)));
      expect(missing.map((e) => e.type)).toEqual([]);
    }
    const kinds = new Set(d.published.map((e) => e.type));
    for (const k of ["shot", "hit", "death", "round_end", "match_end"] as const) expect(kinds.has(k)).toBe(true);
  });

  it("own movement is predicted exactly on a clean link; on a bad one corrections stay small", () => {
    const clean = netDuel(9, { latencyMs: 40 });
    const dirty = netDuel(9, bad);
    for (const c of clean.clients) {
      expect(c.prediction.checked).toBeGreaterThan(300);
      // Only what the client cannot know (the opponent's new hits, deaths) corrects it.
      expect(c.prediction.corrections / c.prediction.checked).toBeLessThan(0.15);
    }
    for (const c of dirty.clients) {
      expect(c.prediction.corrections / c.prediction.checked).toBeLessThan(0.3);
      expect(c.prediction.maxErrorM).toBeLessThan(1.5);
    }
  });

  it("the same seeds replay the same networked duel, event for event", () => {
    const a = netDuel(11, bad);
    const b = netDuel(11, bad);
    expect(JSON.stringify(a.published)).toBe(JSON.stringify(b.published));
    expect(a.finalServer.scores).toEqual(b.finalServer.scores);
  });
});
