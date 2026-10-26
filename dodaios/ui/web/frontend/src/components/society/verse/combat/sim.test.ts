// @vitest-environment node
import { describe, expect, it } from "vitest";
import { makeInput, idleControl } from "./input";
import { createContext, createMatch, spreadDeg, step } from "./sim";
import { count, liveMatch, place, runner } from "./testing";
import { DEFAULT_TUNING, withTuning } from "./tuning";
import type { CombatEvent } from "./types";

/** No spread, bloom or recoil: every bolt goes where it is aimed. */
const EXACT = withTuning(DEFAULT_TUNING, {
  blaster: {
    hipSpreadDeg: 0, adsSpreadDeg: 0, moveSpreadHipDeg: 0, moveSpreadAdsDeg: 0,
    bloomPerShotHipDeg: 0, bloomPerShotAdsDeg: 0, recoilPitchHipDeg: 0, recoilPitchAdsDeg: 0, recoilYawDeg: 0,
  },
});
const ONE_SHOT = withTuning(EXACT, { blaster: { damageNear: 500, damageFar: 500 } });

// A clear 16 m lane on the west floor of the reactor hall.
const A = { x: 38.8, z: 12 };
const B = { x: 38.8, z: 28 };

function first<T extends CombatEvent["type"]>(ev: CombatEvent[], type: T): Extract<CombatEvent, { type: T }> {
  const e = ev.find((x) => x.type === type);
  if (!e) throw new Error(`no ${type} event`);
  return e as Extract<CombatEvent, { type: T }>;
}

describe("match flow", () => {
  it("counts down, then starts round 1 with the players at opposite spawns", () => {
    const ctx = createContext();
    let s = createMatch(ctx, { seed: 3, playerIds: ["me", "bot"] });
    expect(s.phase).toBe("countdown");
    const [p, o] = s.players;
    expect(Math.hypot(p.x - o.x, p.z - o.z)).toBeGreaterThan(25);
    const events: CombatEvent[] = [];
    for (let i = 0; i < DEFAULT_TUNING.match.countdownTicks; i++) {
      // Movement and fire are ignored during the countdown.
      const res = step(s, [makeInput(i, { ...idleControl(), moveY: 1, fire: true }), null], ctx);
      s = res.state;
      events.push(...res.events);
    }
    expect(s.phase).toBe("live");
    expect(events[0].type).toBe("countdown");
    expect(count(events, "round_start")).toBe(1);
    expect(count(events, "shot")).toBe(0);
    expect(s.players[0].x).toBe(p.x);
  });
});

describe("blaster", () => {
  it("fires five bolts a second that fly at 60 m/s", () => {
    const { ctx, state } = liveMatch({ tuning: EXACT });
    const r = runner(ctx, place(state, A, B));
    const ev = r.run(60, { fire: true });
    expect(count(ev, "shot", 0)).toBe(5);
    const shot = first(ev, "shot");
    const hit = first(ev, "hit");
    // 16 m minus the muzzle reach and the hit capsule's radius, at 1 m per tick.
    expect(hit.tick - shot.tick).toBeGreaterThanOrEqual(14);
    expect(hit.tick - shot.tick).toBeLessThanOrEqual(16);
    expect(hit.target).toBe(1);
  });

  it("loses damage with distance and gains it on the head", () => {
    const { ctx, state } = liveMatch({ tuning: EXACT });
    const near = runner(ctx, place(state, A, { x: 38.8, z: 20 }));
    const e1 = first(near.run(20, { fire: true }), "hit");
    expect(e1.damage).toBeCloseTo(DEFAULT_TUNING.blaster.damageNear, 1);
    const far = runner(ctx, place(state, { x: 38.8, z: 6 }, { x: 38.8, z: 34 }));
    const e2 = first(far.run(40, { fire: true }), "hit");
    expect(e2.damage).toBeLessThan(e1.damage);
    // Aim up at the head: muzzle 1.38 m, head 1.65 m, 8 m away.
    const head = runner(ctx, place(state, A, { x: 38.8, z: 20 }));
    const pitch = Math.atan2(1.68 - 1.38, 7.55);
    const e3 = first(head.run(20, { fire: true, pitch }), "hit");
    expect(e3.headshot).toBe(true);
    expect(e3.damage).toBeCloseTo(e1.damage * DEFAULT_TUNING.health.headshotMul, 1);
  });

  it("overheats on the 12th shot in a row and locks the blaster", () => {
    const { ctx, state } = liveMatch({ tuning: EXACT });
    const r = runner(ctx, place(state, A, B));
    // Firing at the far wall, away from the other player.
    const ev = r.run(12 * 12, { fire: true, yaw: Math.PI });
    const oh = first(ev, "overheat");
    expect(oh.shot).toBe(11);
    expect(r.state.players[0].ventStart).toBeGreaterThanOrEqual(0);
    const more = r.run(60, { fire: true, yaw: Math.PI });
    expect(count(more, "shot", 0)).toBe(0);
    const rest = r.run(DEFAULT_TUNING.blaster.overheatTicks, { fire: true, yaw: Math.PI });
    expect(count(rest, "vent_end", 0)).toBe(1);
    expect(count(rest, "shot", 0)).toBeGreaterThan(0);
  });

  it("a vent press inside the window ends the overheat early; a miss waits it out", () => {
    const { ctx, state } = liveMatch({ tuning: EXACT });
    const s0 = place(state, A, B);
    const good = runner(ctx, s0);
    good.run(12 * 12 - 11, { fire: true, yaw: Math.PI });
    const p = good.state.players[0];
    expect(p.ventForced).toBe(true);
    const wait = p.ventWinStart + 3 - good.state.tick;
    good.run(wait);
    const ev = good.run(1, { vent: true });
    expect(count(ev, "vent_perfect", 0)).toBe(1);
    expect(good.state.players[0].heat).toBe(0);
    expect(good.state.players[0].ventStart).toBe(-1);

    const bad = runner(ctx, s0);
    bad.run(12 * 12 - 11, { fire: true, yaw: Math.PI });
    bad.run(10);
    const miss = bad.run(1, { vent: true });
    expect(count(miss, "vent_miss", 0)).toBe(1);
    // A second press in the window no longer counts.
    const q = bad.state.players[0];
    bad.run(q.ventWinStart + 2 - bad.state.tick);
    expect(count(bad.run(1, { vent: true }), "vent_perfect")).toBe(0);
    expect(bad.state.players[0].ventStart).toBeGreaterThanOrEqual(0);
  });

  it("a manual vent clears heat faster than waiting, a timed one faster still", () => {
    const { ctx, state } = liveMatch({ tuning: EXACT });
    const s0 = place(state, A, B);
    const ticksToCool = (mode: "wait" | "vent" | "perfect") => {
      const r = runner(ctx, s0);
      r.run(8 * 12 - 11, { fire: true, yaw: Math.PI });
      const start = r.state.tick;
      if (mode !== "wait") r.run(1, { vent: true });
      for (let i = 0; i < 600 && r.state.players[0].heat > 0; i++) {
        const p = r.state.players[0];
        r.run(1, { vent: mode === "perfect" && p.ventStart >= 0 && r.state.tick === p.ventWinStart + 1 });
      }
      return r.state.tick - start;
    };
    const wait = ticksToCool("wait");
    const vent = ticksToCool("vent");
    const perfect = ticksToCool("perfect");
    expect(vent).toBeLessThan(wait);
    expect(perfect).toBeLessThan(vent);
  });

  it("aiming down sights tightens the cone and moving widens it", () => {
    const { ctx, state } = liveMatch();
    const r = runner(ctx, place(state, A, B));
    const hip = spreadDeg(DEFAULT_TUNING, r.state.players[0]);
    r.run(30, { ads: true });
    const ads = spreadDeg(DEFAULT_TUNING, r.state.players[0]);
    expect(ads).toBeLessThan(hip / 3);
    r.run(30, { moveX: 1 });
    expect(spreadDeg(DEFAULT_TUNING, r.state.players[0])).toBeGreaterThan(hip);
  });
});

describe("energy shield", () => {
  it("absorbs bolts from the front and pays for them with energy", () => {
    const { ctx, state } = liveMatch({ tuning: EXACT });
    const r = runner(ctx, place(state, A, B));
    r.run(30, {}, { shield: true });
    const ev = r.run(40, { fire: true }, { shield: true });
    expect(count(ev, "hit")).toBe(0);
    expect(count(ev, "block") + count(ev, "deflect")).toBeGreaterThan(2);
    expect(r.state.players[1].health).toBe(100);
    expect(r.state.players[1].shieldEnergy).toBeLessThan(70);
  });

  it("does not cover the back", () => {
    const { ctx, state } = liveMatch({ tuning: EXACT });
    const r = runner(ctx, place(state, A, { ...B, yaw: 0 }));
    r.run(30, {}, { shield: true, yaw: 0 });
    const ev = r.run(40, { fire: true }, { shield: true, yaw: 0 });
    expect(count(ev, "hit")).toBeGreaterThan(0);
  });

  it("parries a bolt met right after raising and sends it back at the shooter", () => {
    const { ctx, state } = liveMatch({ tuning: EXACT });
    const r = runner(ctx, place(state, A, B));
    r.run(1, { fire: true });
    r.run(9);
    const ev = r.run(40, {}, { shield: true });
    const parry = first(ev, "parry");
    expect(parry.player).toBe(1);
    expect(parry.target).toBe(0);
    const back = first(ev, "hit");
    expect(back.target).toBe(0);
    expect(back.owner).toBe(1);
    expect(r.state.players[1].health).toBe(100);
    expect(r.state.players[1].stats.parries).toBe(1);
  });

  it("breaks when empty, drops for the cooldown, and lets bolts through", () => {
    const { ctx, state } = liveMatch({ tuning: EXACT });
    const r = runner(ctx, place(state, A, B));
    r.run(30, {}, { shield: true });
    const ev = r.run(12 * 12, { fire: true }, { shield: true });
    const brk = first(ev, "shield_break");
    expect(brk.player).toBe(1);
    const after = ev.filter((e) => e.tick > brk.tick);
    expect(count(after, "hit")).toBeGreaterThan(0);
    expect(r.state.players[1].shieldUp).toBe(false);
    // Holding the key does not bring it back: it needs a fresh press after the cooldown.
    r.run(DEFAULT_TUNING.shield.brokenTicks + 60, {}, { shield: true });
    expect(r.state.players[1].shieldUp).toBe(false);
    r.run(1);
    r.run(2, {}, { shield: true });
    expect(r.state.players[1].shieldUp).toBe(true);
  });

  it("blocks firing while raised and cannot be flicked faster than the lockout", () => {
    const { ctx, state } = liveMatch({ tuning: EXACT });
    const r = runner(ctx, place(state, A, B));
    const ev = r.run(30, { fire: true, shield: true });
    expect(count(ev, "shot", 0)).toBe(0);
    r.run(1); // lower
    r.run(5, { shield: true }); // too soon
    expect(r.state.players[0].shieldUp).toBe(false);
    r.run(1);
    r.run(DEFAULT_TUNING.shield.reRaiseTicks, { shield: true });
    expect(r.state.players[0].shieldUp).toBe(true);
  });
});

describe("movement", () => {
  const dist = (shape: Parameters<ReturnType<typeof runner>["run"]>[1]) => {
    const { ctx, state } = liveMatch();
    const r = runner(ctx, place(state, A, { x: 70, z: 22 }, ));
    r.state.players[0].yaw = 0;
    r.run(60, typeof shape === "function" ? shape : { yaw: 0, ...shape });
    return Math.hypot(r.state.players[0].x - A.x, r.state.players[0].z - A.z);
  };

  it("runs, sprints, and slows in sights or behind the shield", () => {
    const run = dist({ moveY: 1 });
    const sprint = dist({ moveY: 1, sprint: true });
    const ads = dist({ moveY: 1, ads: true });
    const shield = dist({ moveY: 1, shield: true });
    expect(run).toBeGreaterThan(4.3);
    expect(run).toBeLessThan(4.8);
    expect(sprint).toBeGreaterThan(6.2);
    expect(ads).toBeLessThan(run * 0.75);
    expect(shield).toBeLessThan(run * 0.6);
  });

  it("stops at the shaft's edge but crosses on the catwalk", () => {
    const { ctx, state } = liveMatch();
    const edge = runner(ctx, place(state, { x: 38.8, z: 18 }, { x: 70, z: 30 }));
    edge.run(180, { moveY: 1, yaw: Math.PI / 2 });
    const e = edge.state.players[0];
    expect(Math.hypot(e.x - 54, e.z - 22)).toBeGreaterThan(13.2);
    expect(e.x).toBeGreaterThan(40.5);
    const walk = runner(ctx, place(state, { x: 38.8, z: 22 }, { x: 70, z: 30 }));
    walk.run(180, { moveY: 1, yaw: Math.PI / 2 });
    expect(walk.state.players[0].x).toBeGreaterThan(47.5);
  });

  it("dodge rolls about 4 m and has a cooldown", () => {
    const { ctx, state } = liveMatch();
    const r = runner(ctx, place(state, A, B));
    r.run(1, { dodge: true, moveX: -1 });
    r.run(30);
    const p = r.state.players[0];
    expect(Math.hypot(p.x - A.x, p.z - A.z)).toBeGreaterThan(3.6);
    expect(Math.hypot(p.x - A.x, p.z - A.z)).toBeLessThan(4.4);
    expect(count(r.run(1, { dodge: true }), "dodge")).toBe(0);
    r.run(DEFAULT_TUNING.dodge.cooldownTicks);
    expect(count(r.run(1, { dodge: true }), "dodge")).toBe(1);
  });
});

describe("rounds", () => {
  it("a kill ends the round, sides swap, and two wins end the match", () => {
    const { ctx, state } = liveMatch({ tuning: ONE_SHOT });
    const r = runner(ctx, place(state, A, B));
    const side0 = r.state.players[0].side;
    const ev = r.run(30, { fire: true });
    expect(first(ev, "death").player).toBe(1);
    const end = first(ev, "round_end");
    expect(end.winner).toBe(0);
    expect(r.state.phase).toBe("round_end");
    r.run(DEFAULT_TUNING.match.roundEndTicks + DEFAULT_TUNING.match.countdownTicks + 1);
    expect(r.state.phase).toBe("live");
    expect(r.state.round).toBe(2);
    expect(r.state.players[0].side).toBe(1 - side0);
    expect(r.state.players[1].health).toBe(100);
    r.state = place(r.state, A, B);
    const ev2 = r.run(30, { fire: true });
    const me = first(ev2, "match_end");
    expect(me.winner).toBe(0);
    expect(me.reason).toBe("rounds");
    expect(r.state.phase).toBe("ended");
  });

  it("forfeit ends the match at once in the other player's favour", () => {
    const { ctx, state } = liveMatch();
    const r = runner(ctx, state);
    const ev = r.run(1, { forfeit: true });
    const me = first(ev, "match_end");
    expect(me.winner).toBe(1);
    expect(me.reason).toBe("forfeit");
  });

  it("health comes back after five quiet seconds", () => {
    const { ctx, state } = liveMatch({ tuning: EXACT });
    const r = runner(ctx, place(state, A, B));
    r.run(13, { fire: true });
    r.run(30);
    const hurt = r.state.players[1].health;
    expect(hurt).toBeLessThan(100);
    r.run(DEFAULT_TUNING.health.regenDelayTicks - 20);
    expect(r.state.players[1].health).toBe(hurt);
    r.run(120);
    expect(r.state.players[1].health).toBeGreaterThan(hurt + 10);
  });
});

describe("determinism", () => {
  const script = (seed: number) => {
    const { ctx, state } = liveMatch({ seed });
    const r = runner(ctx, place(state, A, B));
    r.run(400, (s) => ({ fire: s.tick % 90 < 50, moveX: Math.sin(s.tick / 20), ads: s.tick % 200 < 100 }),
      (s) => ({ shield: s.tick % 70 < 20, moveX: -1, fire: s.tick % 70 > 25, dodge: s.tick % 130 === 0 }));
    return r;
  };

  it("the same seed and inputs give the same states and events", () => {
    const a = script(11);
    const b = script(11);
    expect(JSON.stringify(a.state)).toBe(JSON.stringify(b.state));
    expect(JSON.stringify(a.events)).toBe(JSON.stringify(b.events));
    expect(a.events.length).toBeGreaterThan(20);
  });

  it("a different seed changes the spread", () => {
    expect(JSON.stringify(script(11).events)).not.toBe(JSON.stringify(script(12).events));
  });

  it("the state survives JSON and steps the same after it", () => {
    const a = script(5);
    const copy = JSON.parse(JSON.stringify(a.state));
    expect(copy).toEqual(a.state);
    const ctx = createContext();
    const cmd = makeInput(9999, { ...idleControl(0.3, 0), fire: true, moveY: 1 });
    expect(JSON.stringify(step(copy, [cmd, null], ctx))).toBe(JSON.stringify(step(a.state, [cmd, null], ctx)));
  });

  it("never mutates the state it is given", () => {
    const { ctx, state } = liveMatch();
    const before = JSON.stringify(state);
    step(state, [makeInput(0, { ...idleControl(), fire: true, moveY: 1, dodge: true }), null], ctx);
    expect(JSON.stringify(state)).toBe(before);
  });
});
