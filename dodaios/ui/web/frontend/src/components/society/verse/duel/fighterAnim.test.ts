import { describe, expect, it } from "vitest";
import {
  DEFAULT_LOCO, DUEL_CLIPS, FighterAnimator, flinchSide, headingWeights, locoClips, locomotionBlend, TIMING,
  type FighterFrame, type FighterInput,
} from "./fighterAnim";

const DEG = Math.PI / 180;
const run = DEFAULT_LOCO.filter((c) => c.gait === "run");

function strideDir(weights: Map<string, number>): number {
  let f = 0;
  let l = 0;
  for (const c of DEFAULT_LOCO) {
    const w = weights.get(c.name) ?? 0;
    f += Math.cos(c.heading) * c.speed * c.seconds * w;
    l += Math.sin(c.heading) * c.speed * c.seconds * w;
  }
  return Math.atan2(l, f);
}

function sum(m: Map<string, number>): number {
  let s = 0;
  for (const w of m.values()) s += w;
  return s;
}

function input(over: Partial<FighterInput> = {}): FighterInput {
  return {
    x: 0, z: 0, vx: 0, vz: 0, aimYaw: 0, aimPitch: 0, alive: true, dodging: false, dodgeProgress: 0,
    sprinting: false, shieldUp: false, ads: 0, venting: false, ...over,
  };
}

function baseSum(f: FighterFrame): number {
  return f.base.reduce((s, c) => s + c.weight, 0);
}

function weightOf(f: FighterFrame, name: string): number {
  return f.base.filter((c) => c.name === name).reduce((s, c) => s + c.weight, 0);
}

describe("heading weights", () => {
  it("plays the one clip whose heading the motion matches", () => {
    expect(headingWeights(0, run).get("A_Combat_Run_F")).toBeCloseTo(1);
    expect(headingWeights(90 * DEG, run).get("A_Combat_Run_L")).toBeCloseTo(1);
    expect(headingWeights(-90 * DEG, run).get("A_Combat_Run_R")).toBeCloseTo(1);
    expect(headingWeights(180 * DEG, run).get("A_Combat_Run_B")).toBeCloseTo(1);
  });

  it("blends the two neighbours so the blended stride points where the body moves", () => {
    for (let a = -179; a <= 180; a += 7) {
      const w = headingWeights(a * DEG, run);
      expect(sum(w)).toBeCloseTo(1, 6);
      expect(w.size).toBeLessThanOrEqual(2);
      const err = Math.atan2(Math.sin(strideDir(w) - a * DEG), Math.cos(strideDir(w) - a * DEG));
      expect(Math.abs(err)).toBeLessThan(1e-6);
    }
  });

  it("weights a diagonal toward the shorter stride (backpedal is slower)", () => {
    const w = headingWeights(135 * DEG, run);
    expect(w.get("A_Combat_Run_B")!).toBeGreaterThan(w.get("A_Combat_Run_L")!);
  });
});

describe("locomotion blend", () => {
  it("walks slowly, runs at full speed and mixes the gaits in between", () => {
    const slow = locomotionBlend(DEFAULT_LOCO, 0, 2, 0);
    expect(slow.weights.get("A_Combat_Walk_F")).toBeCloseTo(1);
    const fast = locomotionBlend(DEFAULT_LOCO, 0, 4.8, 0);
    expect(fast.weights.get("A_Combat_Run_F")).toBeCloseTo(1);
    const mid = locomotionBlend(DEFAULT_LOCO, 0, 3.2, 0);
    expect(mid.weights.get("A_Combat_Walk_F")! > 0 && mid.weights.get("A_Combat_Run_F")! > 0).toBe(true);
    for (const b of [slow, fast, mid]) expect(sum(b.weights)).toBeCloseTo(1, 6);
  });

  it("hands the body to the sprint by its share", () => {
    const b = locomotionBlend(DEFAULT_LOCO, 0, 7, 1);
    expect(b.weights.get(DUEL_CLIPS.sprint)).toBeCloseTo(1);
    expect(b.stride).toBeCloseTo(7 * (16 / 30), 6);
  });

  it("strides as far as the blended clips travel per cycle", () => {
    const b = locomotionBlend(DEFAULT_LOCO, 0, 4.8, 0);
    expect(b.stride).toBeCloseTo(4.8 * (18 / 30), 6);
  });

  it("reads speeds and headings from the manifest and scales them with the body", () => {
    const table = { A_Combat_Run_F: { speed: 5, heading: 0, seconds: 0.6 }, A_Combat_Run_L: { speed: 5, heading: 90 } };
    const clips = locoClips(table, new Set(["A_Combat_Run_F", "A_Combat_Run_L"]), 0.5);
    expect(clips.map((c) => c.name)).toEqual(["A_Combat_Run_F", "A_Combat_Run_L"]);
    expect(clips[0].speed).toBeCloseTo(2.5);
    expect(clips[1].heading).toBeCloseTo(Math.PI / 2);
  });
});

describe("flinch side", () => {
  it("names the side a bolt arrives from, relative to the body's facing", () => {
    expect(flinchSide(0, 0, 0, 0, 5)).toBe("F");
    expect(flinchSide(0, 0, 0, 0, -5)).toBe("B");
    expect(flinchSide(0, 0, 0, 5, 0)).toBe("L");
    expect(flinchSide(0, 0, 0, -5, 0)).toBe("R");
    expect(flinchSide(0, 0, Math.PI / 2, 5, 0)).toBe("F");
  });
});

describe("fighter animator", () => {
  const dt = 1 / 60;

  it("advances the gait phase at ground speed over the stride, so feet do not slide", () => {
    const a = new FighterAnimator(DEFAULT_LOCO);
    let f = a.update(dt, input());
    for (let i = 0; i < 120; i += 1) f = a.update(dt, input({ vz: 4.8 }));
    const before = f.phase;
    f = a.update(0.05, input({ vz: 4.8 }));
    const advanced = (f.phase - before + 1) % 1;
    expect(advanced).toBeCloseTo((0.05 * 4.8) / (4.8 * (18 / 30)), 6);
    expect(weightOf(f, "A_Combat_Run_F")).toBeGreaterThan(0.95);
  });

  it("strafes and backpedals with the legs still facing the aim", () => {
    const a = new FighterAnimator(DEFAULT_LOCO);
    let f = a.update(dt, input());
    for (let i = 0; i < 90; i += 1) f = a.update(dt, input({ vx: 4.8 }));
    expect(f.legsYaw).toBeCloseTo(0, 3);
    expect(weightOf(f, "A_Combat_Run_L")).toBeGreaterThan(0.95);
    for (let i = 0; i < 90; i += 1) f = a.update(dt, input({ vz: -3.7 }));
    expect(weightOf(f, "A_Combat_Run_B") + weightOf(f, "A_Combat_Walk_B")).toBeGreaterThan(0.95);
  });

  it("keeps the base layer's weights summing to one through every state", () => {
    const a = new FighterAnimator(DEFAULT_LOCO);
    const script: Array<[number, Partial<FighterInput>]> = [
      [30, {}], [40, { vz: 4.8 }], [20, { vx: -4.8, aimYaw: 0.4 }], [12, { dodging: true, vx: 10 }],
      [30, {}], [40, { aimYaw: 2 }], [20, { alive: false }], [90, { alive: false }], [120, {}],
      [20, { vz: 7, sprinting: true }], [10, { shieldUp: true }],
    ];
    let t = 0;
    for (const [n, over] of script) {
      for (let i = 0; i < n; i += 1) {
        t += dt;
        const p = input({ ...over, dodgeProgress: over.dodging ? Math.min(1, (i * dt) / TIMING.rollSim) : 0 });
        const f = a.update(dt, p);
        expect(baseSum(f)).toBeCloseTo(1, 5);
        for (const c of f.base) expect(c.weight).toBeGreaterThanOrEqual(0);
      }
    }
    expect(t).toBeGreaterThan(5);
  });

  it("step-turns a standing body when the aim swings far, and the legs end on the aim", () => {
    const a = new FighterAnimator(DEFAULT_LOCO);
    a.update(dt, input());
    let f = a.update(dt, input({ aimYaw: Math.PI / 2 }));
    expect(f.base.some((c) => c.name === DUEL_CLIPS.turnL)).toBe(true);
    for (let i = 0; i < 60; i += 1) f = a.update(dt, input({ aimYaw: Math.PI / 2 }));
    expect(f.legsYaw).toBeCloseTo(Math.PI / 2, 3);
    expect(f.base.some((c) => c.name === DUEL_CLIPS.turnL && c.weight > 0.01)).toBe(false);
    // A small swing is the spine's job, not the legs'.
    f = a.update(dt, input({ aimYaw: Math.PI / 2 + 0.5 }));
    expect(f.base.some((c) => c.name === DUEL_CLIPS.turnL || c.name === DUEL_CLIPS.turnR)).toBe(false);
    expect(f.twist).toBeCloseTo(0.5, 3);
  });

  it("rolls the roll's way, lets go of the blaster, and takes it back after the recovery", () => {
    const a = new FighterAnimator(DEFAULT_LOCO);
    a.update(dt, input());
    let f = a.update(dt, input({ dodging: true, vx: 10, dodgeProgress: 0.05 }));
    for (let i = 1; i < 24; i += 1) f = a.update(dt, input({ dodging: true, vx: 10, dodgeProgress: (i * dt) / TIMING.rollSim }));
    expect(f.legsYaw).toBeCloseTo(Math.PI / 2, 2);
    expect(weightOf(f, DUEL_CLIPS.roll)).toBeGreaterThan(0.95);
    expect(f.ik).toBe(0);
    for (let i = 0; i < 30; i += 1) f = a.update(dt, input());
    expect(weightOf(f, DUEL_CLIPS.roll)).toBe(0);
    expect(f.ik).toBe(1);
  });

  it("falls away from the shooter, stays down, and gets up when revived", () => {
    const a = new FighterAnimator(DEFAULT_LOCO);
    a.update(dt, input());
    a.knockedOut(0, 0, 0, -10);
    let f = a.update(dt, input({ alive: false }));
    for (let i = 0; i < 200; i += 1) f = a.update(dt, input({ alive: false }));
    expect(Math.abs(f.legsYaw)).toBeCloseTo(Math.PI, 2);
    const death = f.base.find((c) => c.name === DUEL_CLIPS.death);
    expect(death?.weight).toBeCloseTo(1);
    expect(death?.time).toBeCloseTo(TIMING.death);
    expect(f.ik).toBe(0);
    f = a.update(dt, input({ alive: true }));
    expect(weightOf(f, DUEL_CLIPS.getUp)).toBeGreaterThan(0.9);
    for (let i = 0; i < 120; i += 1) f = a.update(dt, input());
    expect(weightOf(f, DUEL_CLIPS.getUp)).toBe(0);
    expect(weightOf(f, DUEL_CLIPS.idle)).toBeCloseTo(1);
  });

  it("does not keep the corpse when a death event arrives after the body is alive again", () => {
    // DuelLayer poses the body, then routes the frame's events. A death from the
    // round already over must not pin the fallen clip while the next round walks.
    const a = new FighterAnimator(DEFAULT_LOCO);
    a.update(dt, input());
    a.knockedOut(0, 0, 0, -10);
    a.update(dt, input({ alive: false }));
    for (let i = 0; i < 40; i += 1) a.update(dt, input({ alive: false }));
    let f = a.update(dt, input({ alive: true }));
    a.knockedOut(0, 0, 0, -10);
    for (let i = 0; i < 180; i += 1) f = a.update(dt, input({ alive: true, vz: 4.8 }));
    expect(weightOf(f, DUEL_CLIPS.death)).toBe(0);
    expect(weightOf(f, DUEL_CLIPS.getUp)).toBe(0);
    expect(weightOf(f, "A_Combat_Run_F")).toBeGreaterThan(0.9);
  });

  it("does not lay the body down when the death event arrives while the view is still alive", () => {
    const a = new FighterAnimator(DEFAULT_LOCO);
    a.update(dt, input());
    a.knockedOut(0, 0, 0, -10);
    let f = a.update(dt, input({ alive: true, vz: 4.8 }));
    for (let i = 0; i < 30; i += 1) f = a.update(dt, input({ alive: true, vz: 4.8 }));
    expect(weightOf(f, DUEL_CLIPS.death)).toBe(0);
    expect(weightOf(f, "A_Combat_Run_F")).toBeGreaterThan(0.5);
  });

  it("turns toward the shooter when the death event arrives in the same frame as the dead view", () => {
    const a = new FighterAnimator(DEFAULT_LOCO);
    a.update(dt, input());
    let f = a.update(dt, input({ alive: false }));
    a.knockedOut(0, 0, 0, -10);
    for (let i = 0; i < 200; i += 1) f = a.update(dt, input({ alive: false }));
    expect(Math.abs(f.legsYaw)).toBeCloseTo(Math.PI, 2);
    expect(weightOf(f, DUEL_CLIPS.death)).toBeCloseTo(1);
  });

  it("forgets a fall direction that never became a knockout", () => {
    const a = new FighterAnimator(DEFAULT_LOCO);
    a.update(dt, input({ aimYaw: 0 }));
    a.knockedOut(0, 0, 0, -10);
    a.update(dt, input({ alive: true }));
    let f = a.update(dt, input({ alive: false }));
    for (let i = 0; i < 200; i += 1) f = a.update(dt, input({ alive: false }));
    expect(Math.abs(f.legsYaw)).toBeLessThan(0.2);
    expect(weightOf(f, DUEL_CLIPS.death)).toBeCloseTo(1);
  });

  it("flinches additively toward the hit and staggers on its own reflected bolt", () => {
    const a = new FighterAnimator(DEFAULT_LOCO);
    a.update(dt, input());
    a.hit(0, 0, -5, 0, false, false);
    let f = a.update(dt, input());
    expect(f.additive.map((c) => c.name)).toEqual([DUEL_CLIPS.hitR]);
    a.hit(0, 0, 0, 5, true, true);
    f = a.update(dt, input());
    expect(f.additive.map((c) => c.name).sort()).toEqual([DUEL_CLIPS.hitF, DUEL_CLIPS.hitR, DUEL_CLIPS.stagger].sort());
    for (let i = 0; i < 70; i += 1) f = a.update(dt, input());
    expect(f.additive).toEqual([]);
  });

  it("kicks on a shot and settles again", () => {
    const a = new FighterAnimator(DEFAULT_LOCO);
    a.update(dt, input());
    a.shot(false);
    let peak = 0;
    let f = a.update(dt, input());
    for (let i = 0; i < 60; i += 1) { f = a.update(dt, input()); peak = Math.max(peak, f.recoil); }
    expect(peak).toBeGreaterThan(0.1);
    expect(Math.abs(f.recoil)).toBeLessThan(0.01);
  });

  it("shows the bot low behind cover and leans it out to peek", () => {
    const a = new FighterAnimator(DEFAULT_LOCO);
    let f = a.update(dt, input());
    for (let i = 0; i < 90; i += 1) f = a.update(dt, input({ cover: "hide" }));
    expect(weightOf(f, DUEL_CLIPS.cover)).toBeGreaterThan(0.9);
    for (let i = 0; i < 90; i += 1) f = a.update(dt, input({ cover: "peek", peekSide: -1 }));
    expect(weightOf(f, DUEL_CLIPS.cover)).toBeLessThan(0.1);
    expect(f.peek).toBeLessThan(-0.9);
  });
});
