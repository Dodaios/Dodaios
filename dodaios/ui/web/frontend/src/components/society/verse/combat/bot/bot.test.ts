// @vitest-environment node
import { describe, expect, it } from "vitest";
import { idleControl, makeInput, type ControlState } from "../input";
import { angleDiff, yawOf } from "../math";
import { canSee, observe } from "../observe";
import { createContext, createMatch, step, type SimContext } from "../sim";
import { liveMatch, place } from "../testing";
import { DEFAULT_TUNING, withTuning } from "../tuning";
import type { CombatEvent, MatchState } from "../types";
import { BotBrain } from "./brain";
import { findRoute, routeLength } from "./nav";
import { botParams, type BotTier } from "./tiers";

/** Run a bot (slot 0) against a scripted opponent (slot 1) that sees the full state. */
function duel(ctx: SimContext, state: MatchState, bot: BotBrain, other: (s: MatchState) => Partial<ControlState>, ticks: number, onTick?: (s: MatchState, ev: CombatEvent[], botCtl: ControlState) => void) {
  let s = state;
  let prev: CombatEvent[] = [];
  const seq = [1000, 1000];
  for (let i = 0; i < ticks && s.phase !== "ended"; i++) {
    const obs = observe({ ...s, events: prev }, 0, ctx.arena, ctx.tuning);
    const c = bot.think(obs);
    const o = s.players[1];
    const res = step(s, [makeInput(seq[0]++, c), makeInput(seq[1]++, { ...idleControl(o.yaw, o.pitch), ...other(s) })], ctx);
    onTick?.(s, res.events, c);
    s = res.state;
    prev = res.events;
  }
  return s;
}

describe("bot fairness", () => {
  it("never shoots at an opponent it has not seen lately (no wall hacks)", () => {
    const ctx = createContext();
    for (const seed of [1, 2, 3]) {
      let s = createMatch(ctx, { seed, playerIds: ["bot", "x"] });
      const bot = new BotBrain(0, botParams("elite"), ctx.arena, ctx.tuning, seed);
      const seenAt: number[] = [];
      let lastSeen = -1000;
      // The opponent wanders round the shaft and never shoots.
      s = duel(ctx, s, bot, (st) => ({ moveY: 1, yaw: st.players[1].yaw + 0.01 }), 60 * 40, (st, ev) => {
        if (canSee(ctx.arena, ctx.tuning, st.players[0], st.players[1])) lastSeen = st.tick;
        for (const e of ev) if (e.type === "shot" && e.player === 0) seenAt.push(st.tick - lastSeen);
      });
      for (const age of seenAt) expect(age).toBeLessThan(20);
    }
  });

  it("answers a new sighting after a human reaction time, faster on higher tiers", () => {
    const delays = (tier: BotTier) => {
      const out: number[] = [];
      for (let seed = 1; seed <= 12; seed++) {
        const { ctx, state } = liveMatch({ seed });
        const s = place(state, { x: 38.8, z: 12, yaw: 0 }, { x: 38.8, z: 26 });
        const bot = new BotBrain(0, botParams(tier), ctx.arena, ctx.tuning, seed);
        let first = -1;
        const t0 = s.tick;
        duel(ctx, s, bot, () => ({}), 120, (st, ev) => { for (const e of ev) if (e.type === "shot" && e.player === 0 && first < 0) first = st.tick - t0; });
        out.push(first);
      }
      return out;
    };
    const normal = delays("normal");
    const elite = delays("elite");
    const mean = (xs: number[]) => xs.reduce((a, b) => a + b, 0) / xs.length;
    for (const d of [...normal, ...elite]) expect(d).toBeGreaterThanOrEqual(7); // >= ~120 ms, never instant
    expect(mean(elite)).toBeLessThan(mean(normal));
    expect(mean(normal)).toBeGreaterThan(18); // ~300 ms and more
  });

  it("leads a target running across its sights", () => {
    const { ctx, state } = liveMatch({ seed: 4 });
    // Bot on the west floor, target 18 m away running north-south.
    const s = place(state, { x: 36, z: 22, yaw: Math.PI / 2 }, { x: 54, z: 8 });
    const bot = new BotBrain(0, botParams("elite", { coverUse: 0, flankUse: 0, aggression: 0 }), ctx.arena, ctx.tuning, 4);
    const leads: number[] = [];
    duel(ctx, s, bot, (st) => ({ moveX: st.tick % 200 < 100 ? 1 : -1, yaw: -Math.PI / 2 }), 600, (st, _ev, c) => {
      const me = st.players[0];
      const o = st.players[1];
      if (!bot.aware || Math.hypot(o.vx, o.vz) < 3) return;
      const toTarget = yawOf(o.x - me.x, o.z - me.z);
      const motion = yawOf(o.vx, o.vz);
      const side = Math.sign(angleDiff(toTarget, motion));
      leads.push(angleDiff(toTarget, c.yaw) * side);
    });
    expect(leads.length).toBeGreaterThan(60);
    const avg = leads.reduce((a, b) => a + b, 0) / leads.length;
    expect(avg).toBeGreaterThan(0.005); // aims ahead, on average
  });

  it("parries some of the bolts it sees coming and blocks or dodges others", () => {
    const exact = withTuning(DEFAULT_TUNING, { blaster: { hipSpreadDeg: 0, adsSpreadDeg: 0, moveSpreadHipDeg: 0, moveSpreadAdsDeg: 0 } });
    const { ctx, state } = liveMatch({ tuning: exact, seed: 8 });
    const s = place(state, { x: 38.8, z: 8 }, { x: 38.8, z: 34 });
    // Defence only: it does not shoot back (so the marksman lives).
    const bot = new BotBrain(0, botParams("elite", { aggression: 0, coverUse: 0, flankUse: 0 }), ctx.arena, ctx.tuning, 8, { fire: "never" });
    let parries = 0;
    let reached = 0;
    // A marksman fires single bolts at the bot every second from 26 m.
    duel(ctx, s, bot, (st) => {
      const me = st.players[1];
      const b = st.players[0];
      return { yaw: yawOf(b.x - me.x, b.z - me.z), pitch: Math.atan2(1.15 - 1.38, Math.hypot(b.x - me.x, b.z - me.z)), fire: st.tick % 60 === 0 };
    }, 60 * 20, (_st, ev) => {
      for (const e of ev) {
        if (e.type === "parry" && e.player === 0) { parries++; reached++; }
        if ((e.type === "block" || e.type === "deflect") && e.player === 0) reached++;
        if (e.type === "hit" && e.target === 0) reached++;
      }
    });
    expect(reached).toBeGreaterThan(4);
    expect(parries).toBeGreaterThan(0);
  });
});

describe("bot navigation", () => {
  it("finds routes round the shaft and over the catwalks", () => {
    const ctx = createContext();
    const west = { x: 38.8, z: 22 };
    const east = { x: 69.2, z: 22 };
    const r = findRoute(ctx.arena, west, east);
    expect(r).not.toBeNull();
    const len = routeLength(r!);
    expect(len).toBeGreaterThan(30);
    expect(len).toBeLessThan(46);
    const ring = findRoute(ctx.arena, west, { x: 54, z: 16.25 });
    expect(ring).not.toBeNull();
  });
});
