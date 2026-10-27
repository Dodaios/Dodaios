import { describe, expect, it } from "vitest";
import { idleInput, RETRO_STEP, seededRandom, type RetroInput } from "../retroGame";
import game, {
  BARRIER_Y, CELL_H, COLS, COURIER_POINTS, EDGE_MARGIN, HEIGHT, KIND_POINTS, PLAYER_Y, RAPID_S, RECHARGE_S, ROWS, SEGMENTS, SEG_HP,
  SEG_W, SINK_Y, WAVE_BONUS, WIDTH,
  alienPoints, alienX, alienY, barrierCharge, segmentX, swayRate, swaySwarm, waveStartY, type RaidersState,
} from "./pixelRaiders";

const rnd = seededRandom(7);
const run = (s: RaidersState, input: RetroInput, seconds: number) => {
  for (let t = 0; t < seconds; t += RETRO_STEP) game.step(s, input, RETRO_STEP, rnd);
};
/** A run with the swarm's guns and the courier held back, so one rule can be watched at a time. */
const calm = (): RaidersState => {
  const s = game.create(seededRandom(1));
  s.fireTimer = 999;
  s.courierTimer = 999;
  return s;
};
/** The same run; tests that pair it with `runFrozen` keep the swarm where it is. */
const frozen = calm;
/** Step the run without moving the swarm. */
const runFrozen = (s: RaidersState, input: RetroInput, seconds: number) => {
  for (let t = 0; t < seconds; t += RETRO_STEP) {
    const { fx, fy, sway, targetFy } = s;
    game.step(s, input, RETRO_STEP, rnd);
    s.fx = fx; s.fy = fy; s.sway = sway; s.targetFy = targetFy;
  }
};

/** A canvas stand-in that only knows the calls a game may make, and rejects non-finite rectangles. */
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
    arc: (x: number, y: number, r: number) => finite(x, y, r),
    translate: (x: number, y: number) => finite(x, y),
    save: () => { depth += 1; },
    restore: () => { depth -= 1; },
  };
  return { ctx: ctx as unknown as CanvasRenderingContext2D, depth: () => depth, rects: () => rects };
}

/** Left and right pixel of the living swarm. */
const extent = (s: RaidersState): [number, number] => {
  let l = Infinity, r = -Infinity;
  for (let row = 0; row < ROWS; row += 1) {
    for (let c = 0; c < COLS; c += 1) {
      if (!s.alive[row * COLS + c]) continue;
      l = Math.min(l, alienX(s, row, c));
      r = Math.max(r, alienX(s, row, c) + 9);
    }
  }
  return [l, r];
};

describe("pixel raiders", () => {
  it("starts with a full staggered swarm, a charged barrier and three lives", () => {
    const s = game.create(seededRandom(1));
    expect(game.width).toBe(256);
    expect(game.height).toBe(HEIGHT);
    expect(s.aliveCount).toBe(ROWS * COLS);
    expect(game.status(s)).toEqual({ score: 0, lives: 3, level: 1, over: false });
    expect(barrierCharge(s)).toBe(SEGMENTS * SEG_HP);
    expect(s.fy).toBe(waveStartY(1));
    // Odd rows sit half a cell to the right of even rows.
    expect(alienX(s, 1, 0) - alienX(s, 0, 0)).toBeGreaterThan(5);
  });

  it("sways smoothly from side to side and never leaves the screen", () => {
    const s = calm();
    let last = s.fx, biggestJump = 0, minX = Infinity, maxX = -Infinity;
    for (let t = 0; t < 20; t += RETRO_STEP) {
      swaySwarm(s, RETRO_STEP, rnd);
      biggestJump = Math.max(biggestJump, Math.abs(s.fx - last));
      last = s.fx;
      const [l, r] = extent(s);
      minX = Math.min(minX, l);
      maxX = Math.max(maxX, r);
    }
    expect(biggestJump).toBeLessThan(3);
    expect(minX).toBeGreaterThanOrEqual(EDGE_MARGIN - 1);
    expect(maxX).toBeLessThanOrEqual(WIDTH - EDGE_MARGIN + 3);
    // It really swept both ways.
    expect(maxX - minX).toBeGreaterThan(extent(game.create(seededRandom(1)))[1] - extent(game.create(seededRandom(1)))[0] + 20);
  });

  it("sinks a little at the end of every sweep", () => {
    const s = calm();
    const y0 = s.fy;
    const halfTurn = Math.PI / swayRate(s.aliveCount, s.wave);
    for (let t = 0; t < halfTurn * 0.9; t += RETRO_STEP) swaySwarm(s, RETRO_STEP, rnd);
    expect(s.fy).toBe(y0);
    for (let t = 0; t < halfTurn * 0.2 + 0.5; t += RETRO_STEP) swaySwarm(s, RETRO_STEP, rnd);
    expect(s.fy).toBe(y0 + SINK_Y);
  });

  it("sweeps wider once the outer columns are gone", () => {
    const s = calm();
    for (let r = 0; r < ROWS; r += 1) for (const c of [0, 1, COLS - 2, COLS - 1]) s.alive[r * COLS + c] = 0;
    s.aliveCount = ROWS * (COLS - 4);
    let minX = Infinity, maxX = -Infinity;
    for (let t = 0; t < 15; t += RETRO_STEP) {
      swaySwarm(s, RETRO_STEP, rnd);
      const [l, r] = extent(s);
      minX = Math.min(minX, l);
      maxX = Math.max(maxX, r);
    }
    expect(minX).toBeLessThan(EDGE_MARGIN + 4);
    expect(maxX).toBeGreaterThan(WIDTH - EDGE_MARGIN - 6);
  });

  it("sweeps faster as fewer raiders remain and in later waves", () => {
    expect(swayRate(8, 1)).toBeGreaterThan(swayRate(ROWS * COLS, 1));
    expect(swayRate(1, 1)).toBeGreaterThan(swayRate(ROWS * COLS, 1) * 4);
    expect(swayRate(ROWS * COLS, 4)).toBeGreaterThan(swayRate(ROWS * COLS, 1));
    expect(waveStartY(3)).toBeGreaterThan(waveStartY(1));
  });

  it("a shot kills the raider it hits and scores its kind, more in later waves", () => {
    const s = frozen();
    const row = ROWS - 1, col = 4;
    s.shots[0].active = true;
    s.shots[0].x = alienX(s, row, col) + 4;
    s.shots[0].y = alienY(s, row) + 12;
    runFrozen(s, idleInput(), 0.1);
    expect(s.alive[row * COLS + col]).toBe(0);
    expect(s.aliveCount).toBe(ROWS * COLS - 1);
    expect(s.score).toBe(KIND_POINTS[2]);
    expect(s.shots[0].active).toBe(false);
    expect(alienPoints(0, 1)).toBe(KIND_POINTS[0]);
    expect(alienPoints(2, 3)).toBe(KIND_POINTS[2] + 2 * WAVE_BONUS);
    expect(alienPoints(2, 50)).toBe(alienPoints(2, 20));
  });

  it("fires on the action button, at most two shots at once", () => {
    const s = calm();
    s.px = 4;
    run(s, { ...idleInput(), a: true }, 0.4);
    expect(s.shots.filter((x) => x.active).length).toBeGreaterThanOrEqual(1);
    run(s, { ...idleInput(), a: true }, 1);
    expect(s.shots.filter((x) => x.active).length).toBeLessThanOrEqual(2);
  });

  it("a tap shorter than one frame still fires (the press edge alone)", () => {
    const s = calm();
    const tap = idleInput();
    tap.pressed.a = true;
    game.step(s, tap, RETRO_STEP, rnd);
    expect(s.shots.filter((x) => x.active).length).toBe(1);
  });

  it("the barrier lets the fighter's shots through but drains under raider fire, then recharges", () => {
    const s = frozen();
    // A raider-free lane: empty the swarm except one far corner raider.
    s.alive.fill(0);
    s.alive[0] = 1;
    s.aliveCount = 1;
    const x = segmentX(10) + 3;
    s.shots[0].active = true;
    s.shots[0].x = x;
    s.shots[0].y = BARRIER_Y + 10;
    runFrozen(s, idleInput(), 0.15);
    expect(s.shots[0].y).toBeLessThan(BARRIER_Y);
    expect(s.barrier[10]).toBe(SEG_HP);

    s.bombs[0].active = true;
    s.bombs[0].x = x;
    s.bombs[0].y = BARRIER_Y - 12;
    s.bombs[0].speed = 80;
    s.bombs[0].kind = 0;
    runFrozen(s, idleInput(), 0.3);
    expect(s.bombs[0].active).toBe(false);
    expect(s.barrier[10]).toBe(SEG_HP - 1);
    runFrozen(s, idleInput(), RECHARGE_S + 0.1);
    expect(s.barrier[10]).toBe(SEG_HP);
  });

  it("a drained segment no longer stops raider shots", () => {
    const s = frozen();
    s.barrier[5] = 0;
    s.px = 0;
    s.bombs[0].active = true;
    s.bombs[0].x = segmentX(5) + Math.floor(SEG_W / 2);
    s.bombs[0].y = BARRIER_Y - 10;
    s.bombs[0].speed = 80;
    runFrozen(s, idleInput(), 0.25);
    expect(s.bombs[0].y).toBeGreaterThan(BARRIER_Y);
  });

  it("a raider shot costs a life, then the fighter comes back", () => {
    const s = frozen();
    s.px = 100;
    s.bombs[0].active = true;
    s.bombs[0].x = 105;
    s.bombs[0].y = PLAYER_Y - 8;
    s.bombs[0].speed = 80;
    runFrozen(s, idleInput(), 0.2);
    expect(s.lives).toBe(2);
    expect(s.phase).toBe("dying");
    runFrozen(s, idleInput(), 2);
    expect(s.phase).toBe("play");
    expect(game.status(s).over).toBe(false);
  });

  it("the last life lost ends the run", () => {
    const s = frozen();
    s.lives = 1;
    s.px = 100;
    s.bombs[0].active = true;
    s.bombs[0].x = 105;
    s.bombs[0].y = PLAYER_Y - 4;
    s.bombs[0].speed = 80;
    runFrozen(s, idleInput(), 2);
    expect(game.status(s)).toMatchObject({ lives: 0, over: true });
  });

  it("clearing the swarm starts a lower, faster wave with a recharged barrier", () => {
    const s = frozen();
    s.alive.fill(0);
    s.alive[(ROWS - 1) * COLS + 4] = 1;
    s.aliveCount = 1;
    s.barrier.fill(0);
    s.shots[0].active = true;
    s.shots[0].x = alienX(s, ROWS - 1, 4) + 4;
    s.shots[0].y = alienY(s, ROWS - 1) + 10;
    runFrozen(s, idleInput(), 0.1);
    expect(s.phase).toBe("clear");
    run(s, idleInput(), 2);
    expect(s.wave).toBe(2);
    expect(s.aliveCount).toBe(ROWS * COLS);
    expect(s.fy).toBe(waveStartY(2));
    expect(barrierCharge(s)).toBe(SEGMENTS * SEG_HP);
  });

  it("the swarm burns through the barrier and, reaching the fighter, ends the run", () => {
    const s = calm();
    s.fy = BARRIER_Y - (ROWS - 1) * CELL_H - 4;
    s.targetFy = s.fy;
    swaySwarm(s, RETRO_STEP, rnd);
    expect(barrierCharge(s)).toBeLessThan(SEGMENTS * SEG_HP);
    s.fy = PLAYER_Y - (ROWS - 1) * CELL_H - 8 + 1;
    s.targetFy = s.fy;
    swaySwarm(s, RETRO_STEP, rnd);
    run(s, idleInput(), 2);
    expect(game.status(s).over).toBe(true);
  });

  it("the courier drone zigzags by; shooting it scores and drops a rapid-fire capsule", () => {
    const s = frozen();
    s.courierTimer = 0.01;
    runFrozen(s, idleInput(), 0.05);
    expect(s.courier.active).toBe(true);
    const ys = new Set<number>();
    for (let i = 0; i < 60; i += 1) { runFrozen(s, idleInput(), RETRO_STEP); ys.add(Math.round(s.courier.y)); }
    expect(ys.size).toBeGreaterThan(2);

    s.courier.x = 100;
    s.courier.y = 24;
    s.shots[0].active = true;
    s.shots[0].x = 105;
    s.shots[0].y = 36; // above the swarm's top row
    const before = s.score;
    runFrozen(s, idleInput(), 0.1);
    expect(s.courier.active).toBe(false);
    expect(s.score - before).toBe(COURIER_POINTS);
    expect(s.capsule.active).toBe(true);

    // Stand under the capsule and catch it: rapid fire allows a third shot in the air.
    s.px = s.capsule.x - 3;
    runFrozen(s, idleInput(), 5);
    expect(s.capsule.active).toBe(false);
    expect(s.rapid).toBeGreaterThan(RAPID_S - 2);
    s.alive.fill(0); s.alive[0] = 1; s.aliveCount = 1;
    s.px = WIDTH - 20;
    runFrozen(s, { ...idleInput(), a: true }, 0.35);
    expect(s.shots.filter((x) => x.active).length).toBe(3);
  });

  it("raiders shoot back but never more than the cap", () => {
    const s = game.create(seededRandom(3));
    s.courierTimer = 999;
    let most = 0;
    for (let i = 0; i < 1200 && s.phase === "play"; i += 1) {
      game.step(s, idleInput(), RETRO_STEP, rnd);
      most = Math.max(most, s.bombs.filter((b) => b.active).length);
    }
    expect(most).toBeGreaterThan(0);
    expect(most).toBeLessThanOrEqual(2);
  });

  it("is deterministic for a given seed", () => {
    const play = () => {
      const random = seededRandom(99);
      const s = game.create(random);
      for (let i = 0; i < 1500; i += 1) {
        const input = { ...idleInput(), a: i % 20 < 3, left: i % 300 < 150, right: i % 300 >= 150 };
        game.step(s, input, RETRO_STEP, random);
      }
      return [s.score, s.lives, s.aliveCount, s.fx.toFixed(3), s.fy, Array.from(s.barrier).join("")].join("|");
    };
    expect(play()).toBe(play());
  });

  it("draws every phase without throwing, idle and reduced included", () => {
    const s = game.create(seededRandom(2));
    for (const info of [
      { time: 0, reduced: false, idle: true },
      { time: 3.3, reduced: true, idle: true },
      { time: 1.2, reduced: false, idle: false },
    ]) {
      const fake = fakeContext();
      game.draw(fake.ctx, s, info);
      expect(fake.depth()).toBe(0);
      expect(fake.rects()).toBeGreaterThan(100);
    }
    run(s, { ...idleInput(), a: true, right: true }, 3);
    s.courier.active = true;
    s.courier.x = 60;
    s.capsule.active = true;
    s.capsule.x = 80; s.capsule.y = 120;
    s.rapid = 3;
    s.barrier[3] = 0; s.barrier[4] = 1;
    s.popups[0].active = true;
    s.popups[0].t = 1;
    s.popups[0].value = 80;
    s.shake = 0.3;
    game.draw(fakeContext().ctx, s, { time: 2, reduced: false, idle: false });
    s.phase = "dying";
    s.timer = 1;
    game.draw(fakeContext().ctx, s, { time: 2, reduced: false, idle: false });
    game.draw(fakeContext().ctx, s, { time: 2, reduced: true, idle: false });
    s.phase = "clear";
    game.draw(fakeContext().ctx, s, { time: 2, reduced: false, idle: false });
    s.phase = "over";
    game.draw(fakeContext().ctx, s, { time: 2, reduced: false, idle: false });
  });
});
