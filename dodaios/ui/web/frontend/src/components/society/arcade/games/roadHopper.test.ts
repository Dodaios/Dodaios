import { describe, expect, it } from "vitest";
import { idleInput, RETRO_STEP, seededRandom, type RetroButtons, type RetroInput } from "../retroGame";
import game, {
  BATTERY_POINTS, BATTERY_TIME, CELL, HEIGHT, HOME_ROW, LANES, LEVEL_POINTS, PAD_POINTS, PAD_X, PARCEL_BONUS, QUAY_ROW, ROW_POINTS,
  START_ROW, START_X, WIDTH, carrierAt, itemX, levelFactor, sinkState, vehicleAt, type HopperState,
} from "./roadHopper";

const rnd = seededRandom(11);
const run = (s: HopperState, input: RetroInput, seconds: number) => {
  for (let t = 0; t < seconds; t += RETRO_STEP) game.step(s, input, RETRO_STEP, rnd);
};
/** One frame with `dir` going down (an edge), as the overlay reports a fresh key press. */
const press = (dir: keyof RetroButtons): RetroInput => {
  const input = idleInput();
  input[dir] = true;
  input.pressed[dir] = true;
  return input;
};
const hold = (dir: keyof RetroButtons): RetroInput => ({ ...idleInput(), [dir]: true });
const laneOf = (row: number) => LANES.findIndex((l) => l.row === row);
/** Scroll lane `lane` so its first item's left edge sits at `x`, and return that item's length. */
const parkItem = (s: HopperState, lane: number, x: number): number => {
  let shift = 0;
  while (Math.round(itemX(lane, 0, shift)) !== x) shift += 1;
  s.shifts[lane] = shift;
  return LANES[lane].lens[0];
};
const fresh = (): HopperState => {
  const s = game.create(seededRandom(5));
  s.parcelTimer = 999;
  return s;
};

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

describe("road hopper", () => {
  it("has its own field: a wide screen, four canal lanes, four road lanes, three pads", () => {
    expect([WIDTH, HEIGHT]).toEqual([game.width, game.height]);
    expect(WIDTH).toBeGreaterThan(HEIGHT);
    expect(LANES.filter((l) => l.kind === "barge" || l.kind === "floe")).toHaveLength(4);
    expect(LANES.filter((l) => l.row > QUAY_ROW)).toHaveLength(4);
    expect(PAD_X).toHaveLength(3);
    // Every pad is reachable in whole hops from the start column.
    for (const x of PAD_X) expect(Math.abs(x - START_X) % CELL).toBe(0);
  });

  it("starts on the street with three lives and a full battery", () => {
    const s = fresh();
    expect(game.status(s)).toEqual({ score: 0, lives: 3, level: 1, over: false });
    expect([s.x, s.row, s.battery]).toEqual([START_X, START_ROW, BATTERY_TIME]);
    expect(Array.from(s.pads)).toEqual([0, 0, 0]);
  });

  it("hops one cell per press; holding the key does not keep hopping", () => {
    const s = fresh();
    game.step(s, press("left"), RETRO_STEP, rnd);
    run(s, hold("left"), 1);
    expect(s.x).toBe(START_X - CELL);
    run(s, hold("right"), 1);
    expect(s.x).toBe(START_X - CELL);
    expect(s.row).toBe(START_ROW);
  });

  it("animates a hop and takes a press made mid-hop right after landing", () => {
    const s = fresh();
    game.step(s, press("right"), RETRO_STEP, rnd);
    expect(s.hop.active).toBe(true);
    game.step(s, idleInput(), RETRO_STEP, rnd);
    game.step(s, press("right"), RETRO_STEP, rnd);
    run(s, idleInput(), 0.5);
    expect(s.x).toBe(START_X + 2 * CELL);
  });

  it("a vehicle wrecks the bot", () => {
    const s = fresh();
    const row = 9, lane = laneOf(row);
    parkItem(s, lane, 100);
    s.row = row;
    s.x = 110;
    expect(vehicleAt(s, row, s.x)).toBe(true);
    game.step(s, idleInput(), RETRO_STEP, rnd);
    expect(s.phase).toBe("dying");
    expect(s.deathKind).toBe("crash");
    expect(s.lives).toBe(2);
    run(s, idleInput(), 1.5);
    expect([s.phase, s.row, s.x]).toEqual(["play", START_ROW, START_X]);
  });

  it("a hover barge carries the bot along", () => {
    const s = fresh();
    const row = 4, lane = laneOf(row);
    const len = parkItem(s, lane, 60);
    s.row = row;
    s.x = 60 + len / 2;
    run(s, idleInput(), 0.5);
    expect(s.phase).toBe("play");
    // Half a second of drift, give or take the last frame.
    expect(Math.abs(s.x - (60 + len / 2) - LANES[lane].speed * 0.5)).toBeLessThan(2);
  });

  it("open water sinks the bot", () => {
    const s = fresh();
    const row = 2;
    let x = 20;
    while (carrierAt(s, row, x)) x += 4;
    s.row = row;
    s.x = x;
    game.step(s, idleInput(), RETRO_STEP, rnd);
    expect(s.phase).toBe("dying");
    expect(s.deathKind).toBe("sink");
  });

  it("a floe that cracks and sinks drops the bot in the water", () => {
    const s = fresh();
    const row = 3, lane = laneOf(row);
    // Floe 1 of this lane sinks; find a moment it is gone.
    let clock = 0;
    while (sinkState(lane, 1, clock) !== 2) clock += 0.1;
    s.sinkClock = clock;
    s.row = row;
    s.x = itemX(lane, 1, s.shifts[lane]) + 16;
    game.step(s, idleInput(), RETRO_STEP, rnd);
    expect(s.phase).toBe("dying");
    // A cracking floe still holds.
    while (sinkState(lane, 1, clock) !== 1) clock += 0.1;
    const t = fresh();
    t.sinkClock = clock;
    t.row = row;
    t.x = itemX(lane, 1, t.shifts[lane]) + 16;
    expect(carrierAt(t, row, t.x)).toBe(true);
  });

  it("being carried off the edge costs a life", () => {
    const s = fresh();
    const row = 2, lane = laneOf(row);
    parkItem(s, lane, 210);
    s.row = row;
    s.x = WIDTH - 10;
    run(s, idleInput(), 1);
    expect(s.phase).toBe("dying");
    expect(s.lives).toBe(2);
  });

  it("lighting a pad scores the battery left and sends a new bot", () => {
    const s = fresh();
    s.row = 2;
    s.x = PAD_X[0];
    game.step(s, press("up"), RETRO_STEP, rnd);
    run(s, idleInput(), 0.2);
    expect(s.pads[0]).toBe(1);
    expect(s.score).toBeGreaterThanOrEqual(PAD_POINTS + BATTERY_POINTS * (BATTERY_TIME - 1));
    expect([s.row, s.x, s.phase]).toEqual([START_ROW, START_X, "play"]);
  });

  it("the live fence between pads and a lit pad both zap", () => {
    const s = fresh();
    s.row = 2;
    s.x = (PAD_X[0] + PAD_X[1]) / 2;
    game.step(s, press("up"), RETRO_STEP, rnd);
    run(s, idleInput(), 0.2);
    expect(s.phase).toBe("dying");
    expect(s.row).toBe(HOME_ROW);

    const t = fresh();
    t.pads[2] = 1;
    t.row = 2;
    t.x = PAD_X[2];
    game.step(t, press("up"), RETRO_STEP, rnd);
    run(t, idleInput(), 0.2);
    expect(t.phase).toBe("dying");
  });

  it("a parcel waiting on a pad is worth a bonus", () => {
    const s = fresh();
    s.parcelPad = 1;
    s.parcelLeft = 5;
    s.row = 2;
    s.x = PAD_X[1];
    game.step(s, press("up"), RETRO_STEP, rnd);
    run(s, idleInput(), 0.2);
    expect(s.score).toBeGreaterThanOrEqual(PAD_POINTS + PARCEL_BONUS + BATTERY_POINTS * (BATTERY_TIME - 1));
    expect(s.parcelPad).toBe(-1);
  });

  it("lighting all three pads starts a faster level", () => {
    const s = fresh();
    s.pads.set([1, 1, 0]);
    s.row = 2;
    s.x = PAD_X[2];
    game.step(s, press("up"), RETRO_STEP, rnd);
    run(s, idleInput(), 0.2);
    expect(s.phase).toBe("levelup");
    expect(s.score).toBeGreaterThanOrEqual(LEVEL_POINTS);
    run(s, idleInput(), 2.5);
    expect(game.status(s).level).toBe(2);
    expect(Array.from(s.pads)).toEqual([0, 0, 0]);
    expect(levelFactor(2)).toBeGreaterThan(levelFactor(1));
  });

  it("a flat battery costs a life", () => {
    const s = fresh();
    run(s, idleInput(), BATTERY_TIME - 1);
    expect(s.phase).toBe("play");
    run(s, idleInput(), 1.5);
    expect(s.phase).toBe("dying");
    expect(s.deathKind).toBe("drained");
    expect(s.lives).toBe(2);
  });

  it("the last life ends the run", () => {
    const s = fresh();
    s.lives = 1;
    run(s, idleInput(), BATTERY_TIME + 2);
    expect(game.status(s)).toMatchObject({ lives: 0, over: true });
  });

  it("forward hops score once per new row", () => {
    const s = fresh();
    s.row = QUAY_ROW;
    s.bestRow = QUAY_ROW;
    game.step(s, press("down"), RETRO_STEP, rnd);
    run(s, idleInput(), 0.15);
    expect(s.score).toBe(0);

    const t = fresh();
    // Park the nearest vehicle far from the start column so the hop is safe.
    parkItem(t, laneOf(START_ROW - 1), 40);
    game.step(t, press("up"), RETRO_STEP, rnd);
    run(t, idleInput(), 0.15);
    expect(t.score).toBe(ROW_POINTS);
  });

  it("draws every phase without throwing, idle and reduced included", () => {
    const s = game.create(seededRandom(9));
    for (const info of [
      { time: 0, reduced: false, idle: true },
      { time: 4.2, reduced: true, idle: true },
      { time: 1, reduced: false, idle: false },
    ]) {
      const fake = fakeContext();
      game.draw(fake.ctx, s, info);
      expect(fake.depth()).toBe(0);
      expect(fake.rects()).toBeGreaterThan(100);
    }
    s.pads.set([1, 0, 0]);
    s.parcelPad = 2;
    game.step(s, press("left"), RETRO_STEP, rnd);
    game.draw(fakeContext().ctx, s, { time: 2, reduced: false, idle: false });
    s.battery = 3;
    game.draw(fakeContext().ctx, s, { time: 2, reduced: true, idle: false });
    for (const kind of ["crash", "sink", "drained"] as const) {
      s.phase = "dying";
      s.deathKind = kind;
      s.timer = 0.5;
      game.draw(fakeContext().ctx, s, { time: 2, reduced: false, idle: false });
    }
    s.phase = "levelup";
    game.draw(fakeContext().ctx, s, { time: 2, reduced: false, idle: false });
    s.phase = "over";
    game.draw(fakeContext().ctx, s, { time: 2, reduced: true, idle: false });
  });
});

