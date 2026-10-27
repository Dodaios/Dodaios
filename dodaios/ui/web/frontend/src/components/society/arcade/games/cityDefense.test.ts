import { describe, expect, it } from "vitest";
import { idleInput, RETRO_STEP, seededRandom, type RetroInput } from "../retroGame";
import game, {
  BOLT_R, COOL_RATE, DOME_BONUS, DOME_X, FULL_COLONY_BONUS, GROUND_Y, HEAT_BOLT, HEAT_PULSE, PULSE_R, RING_S, SEEDER_POINTS,
  SHARD_POINTS, SPARE_DOME_EVERY, TOWER_X, TOWER_Y, WIDTH,
  addShard, canFire, domesStanding, multiplier, ringRadius, type DefenseState,
} from "./cityDefense";

const rnd = seededRandom(17);
const run = (s: DefenseState, input: RetroInput, seconds: number) => {
  for (let t = 0; t < seconds; t += RETRO_STEP) game.step(s, input, RETRO_STEP, rnd);
};
/** A wave in progress with the sky held empty, so one rule can be watched at a time. */
const quiet = (): DefenseState => {
  const s = game.create(seededRandom(4));
  run(s, idleInput(), 2);
  for (const w of s.shards) w.active = false;
  s.toLaunch = 5;
  s.salvoTimer = 999;
  s.seederTimer = 999;
  return s;
};
const pressA = (): RetroInput => {
  const input = idleInput();
  input.a = true;
  input.pressed.a = true;
  return input;
};
const pressB = (): RetroInput => {
  const input = idleInput();
  input.b = true;
  input.pressed.b = true;
  return input;
};
const click = (x: number, y: number): RetroInput => ({ ...idleInput(), pointer: { x, y, down: true, clicked: true } });
const activeBolts = (s: DefenseState) => s.bolts.filter((m) => m.active);
const activeShards = (s: DefenseState) => s.shards.filter((w) => w.active).length;

function fakeContext(): { ctx: CanvasRenderingContext2D; depth: () => number; rects: () => number } {
  let depth = 0, rects = 0;
  const finite = (...v: number[]) => {
    if (!v.every(Number.isFinite)) throw new Error(`non-finite draw arguments ${v.join(",")}`);
  };
  const noop = () => {};
  const ctx = {
    fillStyle: "", strokeStyle: "", lineWidth: 1, globalAlpha: 1, lineCap: "butt",
    fillRect: (x: number, y: number, w: number, h: number) => { finite(x, y, w, h); rects += 1; },
    strokeRect: (x: number, y: number, w: number, h: number) => finite(x, y, w, h),
    beginPath: noop, closePath: noop, fill: noop, stroke: noop,
    moveTo: (x: number, y: number) => finite(x, y),
    lineTo: (x: number, y: number) => finite(x, y),
    arc: (x: number, y: number, r: number) => { finite(x, y, r); if (r < 0) throw new Error("negative radius"); },
    translate: (x: number, y: number) => finite(x, y),
    save: () => { depth += 1; },
    restore: () => { depth -= 1; },
  };
  return { ctx: ctx as unknown as CanvasRenderingContext2D, depth: () => depth, rects: () => rects };
}

describe("city defense", () => {
  it("starts with four domes, a cold tower and a short pause", () => {
    const s = game.create(seededRandom(1));
    expect(game.pointer).toBe(true);
    expect(DOME_X).toHaveLength(4);
    expect(game.status(s)).toEqual({ score: 0, lives: 4, level: 1, over: false });
    expect([s.heat, s.jammed]).toEqual([0, false]);
    expect(s.phase).toBe("ready");
    run(s, idleInput(), 2);
    expect(s.phase).toBe("play");
  });

  it("a click aims there and fires a bolt from the tower, warming it", () => {
    const s = quiet();
    game.step(s, click(290, 90), RETRO_STEP, rnd);
    const [b] = activeBolts(s);
    expect([b.ox, b.oy, b.tx, b.ty, b.r]).toEqual([TOWER_X, TOWER_Y, 290, 90, BOLT_R]);
    expect(s.heat).toBeCloseTo(HEAT_BOLT, 6);
  });

  it("a resting mouse does not undo keyboard aiming", () => {
    const s = quiet();
    game.step(s, { ...idleInput(), pointer: { x: 100, y: 100, down: false, clicked: false } }, RETRO_STEP, rnd);
    run(s, { ...idleInput(), right: true, pointer: { x: 100, y: 100, down: false, clicked: false } }, 0.5);
    expect(s.cx).toBeGreaterThan(160);
  });

  it("the keyboard moves the reticle and fires with the action button", () => {
    const s = quiet();
    run(s, { ...idleInput(), left: true, up: true }, 2);
    expect(s.cx).toBeLessThan(10);
    game.step(s, pressA(), RETRO_STEP, rnd);
    expect(activeBolts(s)).toHaveLength(1);
  });

  it("rapid fire overheats and jams the tower until it has fully cooled", () => {
    const s = quiet();
    s.cx = 160; s.cy = 40;
    let fired = 0;
    for (let i = 0; i < 8; i += 1) {
      const before = activeBolts(s).length;
      game.step(s, pressA(), RETRO_STEP, rnd);
      if (activeBolts(s).length > before) fired += 1;
    }
    // The cooling between shots buys at most one extra bolt before the jam.
    expect(fired).toBeGreaterThanOrEqual(Math.round(1 / HEAT_BOLT));
    expect(fired).toBeLessThanOrEqual(Math.round(1 / HEAT_BOLT) + 1);
    expect(s.jammed).toBe(true);
    expect(canFire(s, false)).toBe(false);
    // Half cooled is not enough: a jam lasts until the heat is all gone.
    run(s, idleInput(), 0.5 / COOL_RATE);
    expect(s.jammed).toBe(true);
    run(s, idleInput(), 0.6 / COOL_RATE);
    expect(s.jammed).toBe(false);
    expect(canFire(s, false)).toBe(true);
  });

  it("the secondary button fires a wide pulse that costs more heat", () => {
    const s = quiet();
    s.cx = 160; s.cy = 100;
    game.step(s, pressB(), RETRO_STEP, rnd);
    const [b] = activeBolts(s);
    expect(b.r).toBe(PULSE_R);
    expect(s.heat).toBeCloseTo(HEAT_PULSE, 2);
    // Too warm for a second pulse right away, but a bolt still fits.
    game.step(s, idleInput(), RETRO_STEP, rnd);
    expect(canFire(s, true)).toBe(false);
    expect(canFire(s, false)).toBe(true);
  });

  it("a bolt bursts at the aim point and its ring shatters a shard", () => {
    const s = quiet();
    s.cx = 160;
    s.cy = 120;
    addShard(s, 160, 118, 160, GROUND_Y, 1);
    game.step(s, pressA(), RETRO_STEP, rnd);
    run(s, idleInput(), 0.6);
    expect(activeShards(s)).toBe(0);
    expect(s.score).toBe(SHARD_POINTS * multiplier(1));
  });

  it("rings grow, hold and fade", () => {
    expect(ringRadius(0, BOLT_R)).toBe(0);
    expect(ringRadius(0.5, BOLT_R)).toBe(BOLT_R);
    expect(ringRadius(RING_S, BOLT_R)).toBeCloseTo(0, 6);
  });

  it("a shattered shard's own ring catches the next one (chain reaction)", () => {
    const s = quiet();
    s.cx = 100;
    s.cy = 100;
    // The second shard is out of reach of our ring but within the first one's.
    addShard(s, 111, 100, 111, GROUND_Y, 0.01);
    addShard(s, 122, 100, 122, GROUND_Y, 0.01);
    expect(122 - 100).toBeGreaterThan(BOLT_R);
    game.step(s, click(100, 100), RETRO_STEP, rnd);
    run(s, idleInput(), 1.5);
    expect(activeShards(s)).toBe(0);
    expect(s.score).toBe(2 * SHARD_POINTS);
  });

  it("a shard reaching a dome breaks it", () => {
    const s = quiet();
    addShard(s, DOME_X[0], GROUND_Y - 4, DOME_X[0], GROUND_Y, 60);
    run(s, idleInput(), 0.3);
    expect(s.domes[0]).toBe(0);
    expect(game.status(s).lives).toBe(3);
  });

  it("a shard striking the tower jams it but does not destroy it", () => {
    const s = quiet();
    addShard(s, TOWER_X, TOWER_Y, TOWER_X, TOWER_Y + 4, 60);
    run(s, idleInput(), 0.2);
    expect(s.jammed).toBe(true);
    expect(domesStanding(s)).toBe(4);
    run(s, idleInput(), 1.2 / COOL_RATE);
    expect(s.jammed).toBe(false);
  });

  it("weaving shards swing side to side around their path", () => {
    const s = quiet();
    addShard(s, 160, 20, 160, GROUND_Y, 20, 14);
    let left = 160, right = 160;
    for (let t = 0; t < 2; t += RETRO_STEP) {
      game.step(s, idleInput(), RETRO_STEP, rnd);
      const w = s.shards.find((x) => x.active);
      if (!w) break;
      left = Math.min(left, w.x);
      right = Math.max(right, w.x);
    }
    expect(left).toBeLessThan(150);
    expect(right).toBeGreaterThan(170);
  });

  it("a seeder caught in a ring is worth extra", () => {
    const s = quiet();
    s.seeder.active = true;
    s.seeder.x = 150;
    s.seeder.y = 60;
    s.seeder.vx = 0;
    s.seeder.vy = 0;
    s.seeder.dropTimer = 99;
    game.step(s, click(150, 60), RETRO_STEP, rnd);
    run(s, idleInput(), 1);
    expect(s.seeder.active).toBe(false);
    expect(s.score).toBe(SEEDER_POINTS);
  });

  it("the wave ends with a bonus per dome, plus extra when the colony stayed whole", () => {
    const s = quiet();
    s.toLaunch = 0;
    run(s, idleInput(), 0.1);
    expect(s.phase).toBe("bonus");
    expect(s.score).toBe(4 * DOME_BONUS + FULL_COLONY_BONUS);
    run(s, idleInput(), 3);
    expect(s.wave).toBe(2);
    expect([s.heat, s.jammed]).toEqual([0, false]);

    const t = quiet();
    t.toLaunch = 0;
    t.domes[3] = 0;
    run(t, idleInput(), 0.1);
    expect(t.score).toBe(3 * DOME_BONUS);
    expect(t.bonusFull).toBe(false);
  });

  it("a spare dome earned by points rebuilds a lost one", () => {
    const s = quiet();
    s.score = SPARE_DOME_EVERY - 10;
    s.toLaunch = 0;
    s.domes[2] = 0;
    run(s, idleInput(), 0.1);
    expect(s.spares).toBe(1);
    run(s, idleInput(), 3);
    expect(domesStanding(s)).toBe(4);
    expect(s.spares).toBe(0);
  });

  it("the multiplier steps up every three waves, up to four", () => {
    expect([1, 3, 4, 6, 7, 10, 30].map(multiplier)).toEqual([1, 1, 2, 2, 3, 4, 4]);
  });

  it("losing every dome ends the run", () => {
    const s = quiet();
    s.domes.fill(0);
    s.domes[3] = 1;
    addShard(s, DOME_X[3], GROUND_Y - 2, DOME_X[3], GROUND_Y, 60);
    run(s, idleInput(), 3);
    expect(game.status(s)).toMatchObject({ lives: 0, over: true });
  });

  it("a whole wave plays out without help and keeps every pool bounded", () => {
    const s = game.create(seededRandom(8));
    s.wave = 6;
    for (let i = 0; i < 60 * 90 && s.phase !== "over" && s.wave === 6; i += 1) {
      game.step(s, idleInput(), RETRO_STEP, rnd);
      expect(s.shards.length).toBe(40);
      for (const w of s.shards) if (w.active) expect(w.x >= 0 && w.x <= WIDTH).toBe(true);
    }
    expect(s.wave === 7 || s.phase === "over" || s.phase === "lost").toBe(true);
  });

  it("draws every phase without throwing, idle and reduced included", () => {
    const s = game.create(seededRandom(3));
    for (const info of [
      { time: 0, reduced: false, idle: true },
      { time: 5.5, reduced: true, idle: true },
      { time: 1, reduced: false, idle: false },
    ]) {
      const fake = fakeContext();
      game.draw(fake.ctx, s, info);
      expect(fake.depth()).toBe(0);
      expect(fake.rects()).toBeGreaterThan(50);
    }
    run(s, idleInput(), 2);
    addShard(s, 100, 10, 120, GROUND_Y, 30, 12);
    game.step(s, click(200, 80), RETRO_STEP, rnd);
    game.step(s, pressB(), RETRO_STEP, rnd);
    s.seeder.active = true;
    s.seeder.x = 80;
    s.seeder.y = 60;
    run(s, idleInput(), 0.3);
    s.shake = 0.3;
    s.spares = 2;
    s.jammed = true;
    game.draw(fakeContext().ctx, s, { time: 2, reduced: false, idle: false });
    game.draw(fakeContext().ctx, s, { time: 2, reduced: true, idle: false });
    s.domes[1] = 0;
    s.phase = "ready";
    game.draw(fakeContext().ctx, s, { time: 2, reduced: false, idle: false });
    s.phase = "bonus";
    s.bonusFull = true;
    game.draw(fakeContext().ctx, s, { time: 2, reduced: false, idle: false });
    s.phase = "over";
    game.draw(fakeContext().ctx, s, { time: 2, reduced: false, idle: false });
    expect(WIDTH).toBe(game.width);
  });
});

