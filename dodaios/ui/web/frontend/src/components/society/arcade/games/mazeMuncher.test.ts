import { describe, expect, it } from "vitest";
import { RETRO_STEP, idleInput, seededRandom, type RetroInput } from "../retroGame";
import mazeMuncher, {
  BONUS_X, BONUS_Y, CHAIN_POINTS, CLEAR_TIME, DOT_POINTS, DOWN, DYING_TIME, ECHO, EXIT_X, EXIT_Y, HUNT_TIME, LEFT, MAZE, MAZE_H, MAZE_W,
  NONE, ORB_POINTS, PATROL_TIME, PEN_Y, PLAYER_START_X, PLAYER_START_Y, READY_TIME, REBOOT_TIME, RIGHT, ROAMER, TRACKER, UP, WARDEN,
  bugTarget, createMaze, frightDuration, isOpen, patrolling, type MazeState,
} from "./mazeMuncher";

/** A 2D context stand-in: every call is a no-op, texts are recorded, non-finite numbers are flagged. */
function fakeContext(texts: string[], bad: string[]): CanvasRenderingContext2D {
  const target: Record<string, unknown> = {
    fillText: (s: unknown) => { texts.push(String(s)); },
    createLinearGradient: () => ({ addColorStop: () => undefined }),
    createRadialGradient: () => ({ addColorStop: () => undefined }),
    measureText: (s: string) => ({ width: s.length * 6 }),
  };
  return new Proxy(target, {
    get: (t, key) => {
      if (typeof key === "string" && key in t) return t[key];
      return (...args: unknown[]) => {
        if (args.some((a) => typeof a === "number" && !Number.isFinite(a))) bad.push(String(key));
      };
    },
    set: (t, key, value) => { t[String(key)] = value; return true; },
  }) as unknown as CanvasRenderingContext2D;
}

const random = seededRandom(5);
const run = (s: MazeState, input: RetroInput, seconds: number) => {
  for (let t = 0; t < seconds; t += RETRO_STEP) mazeMuncher.step(s, input, RETRO_STEP, random);
};
const press = (button: "left" | "right" | "up" | "down"): RetroInput => {
  const input = idleInput();
  input[button] = true;
  input.pressed[button] = true;
  return input;
};
/** A run already playing, with every bug parked in the pen for good. */
const quiet = (): MazeState => {
  const s = createMaze();
  s.phase = "play";
  s.phaseTimer = 0;
  s.roundTime = -1e9;
  s.dotsThisRound = -1e9;
  for (const b of s.bugs) { b.mode = "pen"; b.x = 10; b.y = 9; }
  return s;
};
const place = (s: MazeState, x: number, y: number, dir: number) => {
  s.player.x = x; s.player.y = y; s.player.dir = dir; s.player.want = dir;
};

describe("maze muncher: the maze", () => {
  it("is 21 × 21, mirror-symmetric, with four orbs and a wrap tunnel", () => {
    expect(MAZE).toHaveLength(MAZE_H);
    for (const row of MAZE) {
      expect(row).toHaveLength(MAZE_W);
      expect(row).toBe([...row].reverse().join(""));
    }
    expect(MAZE.join("").split("o")).toHaveLength(5);
    expect(MAZE.some((row) => row[0] === "T" && row[MAZE_W - 1] === "T")).toBe(true);
    expect(isOpen(-1, 9)).toBe(true);
    expect(isOpen(EXIT_X, EXIT_Y + 1)).toBe(false); // the pen door
  });

  it("has no dead ends and every open tile is reachable", () => {
    const open: Array<[number, number]> = [];
    for (let y = 0; y < MAZE_H; y += 1) for (let x = 0; x < MAZE_W; x += 1) if (isOpen(x, y)) open.push([x, y]);
    for (const [x, y] of open) {
      const exits = [[0, -1], [-1, 0], [0, 1], [1, 0]].filter(([dx, dy]) => isOpen(x + dx, y + dy)).length;
      expect(exits, `tile ${x},${y}`).toBeGreaterThanOrEqual(2);
    }
    const seen = new Set<string>([`${PLAYER_START_X},${PLAYER_START_Y}`]);
    const queue: Array<[number, number]> = [[PLAYER_START_X, PLAYER_START_Y]];
    while (queue.length) {
      const [x, y] = queue.shift()!;
      for (const [dx, dy] of [[0, -1], [-1, 0], [0, 1], [1, 0]]) {
        const nx = (x + dx + MAZE_W) % MAZE_W, ny = y + dy;
        if (!isOpen(nx, ny) || seen.has(`${nx},${ny}`)) continue;
        seen.add(`${nx},${ny}`);
        queue.push([nx, ny]);
      }
    }
    expect(seen.size).toBe(open.length);
  });
});

describe("maze muncher: play", () => {
  it("starts with three lives, a full maze and a ready pause", () => {
    const s = mazeMuncher.create(random);
    expect(mazeMuncher.status(s)).toEqual({ score: 0, lives: 3, level: 1, over: false });
    expect(s.dotsLeft).toBe(s.totalDots);
    expect(s.totalDots).toBeGreaterThan(150);
    run(s, idleInput(), READY_TIME / 2);
    expect(s.player.x).toBe(PLAYER_START_X);
    run(s, idleInput(), READY_TIME);
    expect(s.phase).toBe("play");
    expect(s.player.x).toBeLessThan(PLAYER_START_X);
  });

  it("stops at walls", () => {
    const s = quiet();
    place(s, 1, 1, UP);
    run(s, idleInput(), 0.5);
    expect([s.player.x, s.player.y]).toEqual([1, 1]);
    place(s, 4, 1, LEFT);
    run(s, idleInput(), 1);
    expect([s.player.x, s.player.y]).toEqual([1, 1]);
    expect(s.player.dir).toBe(NONE);
  });

  it("takes a buffered turn at the next junction where it is open", () => {
    const s = quiet();
    place(s, 7, 3, LEFT);
    run(s, press("up"), RETRO_STEP);
    // Columns 6 and 5 have walls above: keep running left.
    run(s, idleInput(), 0.3);
    expect(s.player.y).toBe(3);
    expect(s.player.x).toBeLessThan(6);
    run(s, idleInput(), 0.5);
    expect(s.player.x).toBe(4);
    expect(s.player.y).toBe(1); // turned up and ran on to the wall
  });

  it("reverses at once, mid-tile", () => {
    const s = quiet();
    place(s, 7, 3, LEFT);
    run(s, idleInput(), 0.05);
    const x = s.player.x;
    run(s, press("right"), RETRO_STEP);
    expect(s.player.dir).toBe(RIGHT);
    expect(s.player.x).toBeGreaterThan(x);
  });

  it("wraps through the tunnel", () => {
    const s = quiet();
    place(s, 2, 9, LEFT);
    run(s, idleInput(), 0.6);
    expect(s.player.x).toBeGreaterThan(15);
    expect(s.player.y).toBe(9);
  });

  it("eats dots for points", () => {
    const s = quiet();
    place(s, 1, 1, RIGHT);
    const left = s.dotsLeft;
    run(s, idleInput(), 0.6);
    const eaten = left - s.dotsLeft;
    expect(eaten).toBeGreaterThanOrEqual(3);
    expect(s.score).toBe(eaten * DOT_POINTS);
    expect(s.dots[1 * MAZE_W + 2]).toBe(0);
  });

  it("an orb shorts the bugs out, and zapped bugs chain rising points and reboot in the pen", () => {
    const s = quiet();
    const [, a, b] = s.bugs;
    a.mode = "active"; a.x = 9; a.y = 19; a.dir = LEFT;
    b.mode = "active"; b.x = 15; b.y = 19; b.dir = LEFT;
    place(s, 1, 1, DOWN);
    s.dots[1 * MAZE_W + 1] = 0;
    run(s, idleInput(), 0.15);
    expect(s.dots[2 * MAZE_W + 1]).toBe(0);
    expect(s.score).toBe(ORB_POINTS);
    expect(s.frightTimer).toBeGreaterThan(0);
    expect(a.frightened && b.frightened).toBe(true);

    a.x = s.player.x; a.y = s.player.y;
    run(s, idleInput(), RETRO_STEP);
    expect(a.mode).toBe("rebooting");
    // Straight back into the pen: no trip home through the maze.
    expect([a.x, a.y]).toEqual([10, PEN_Y]);
    expect(s.score).toBe(ORB_POINTS + CHAIN_POINTS[0]);
    run(s, idleInput(), 0.6);
    b.x = s.player.x; b.y = s.player.y;
    run(s, idleInput(), RETRO_STEP);
    expect(b.mode).toBe("rebooting");
    expect(s.score - ORB_POINTS - CHAIN_POINTS[0]).toBeGreaterThanOrEqual(CHAIN_POINTS[1]);
    expect(CHAIN_POINTS).toEqual([150, 300, 450, 600]);

    // After its reboot the bug comes out again as a normal bug.
    run(s, idleInput(), REBOOT_TIME + 2);
    expect(["leaving", "active"]).toContain(a.mode);
    expect(a.frightened).toBe(false);
  });

  it("the power wears off, sooner on later levels", () => {
    const s = quiet();
    s.bugs[1].mode = "active"; s.bugs[1].x = 9; s.bugs[1].y = 19; s.bugs[1].dir = LEFT;
    place(s, 1, 1, DOWN);
    run(s, idleInput(), frightDuration(1) + 0.5);
    expect(s.frightTimer).toBe(0);
    expect(s.bugs[1].frightened).toBe(false);
    expect(frightDuration(4)).toBeLessThan(frightDuration(1));
  });

  it("loses a life on touching a bug, then restarts the round with the dots kept", () => {
    const s = quiet();
    place(s, 1, 1, RIGHT);
    run(s, idleInput(), 0.4);
    const left = s.dotsLeft;
    const bug = s.bugs[0];
    bug.mode = "active"; bug.x = s.player.x; bug.y = s.player.y; bug.dir = LEFT;
    run(s, idleInput(), RETRO_STEP);
    expect(s.phase).toBe("dying");
    expect(mazeMuncher.status(s).lives).toBe(2);
    run(s, idleInput(), DYING_TIME + 0.05);
    expect(s.phase).toBe("ready");
    expect([s.player.x, s.player.y]).toEqual([PLAYER_START_X, PLAYER_START_Y]);
    expect(s.dotsLeft).toBe(left);
    expect(s.over).toBe(false);
  });

  it("ends the run when the last life is lost", () => {
    const s = quiet();
    s.lives = 1;
    const bug = s.bugs[0];
    bug.mode = "active"; bug.x = s.player.x; bug.y = s.player.y; bug.dir = LEFT;
    run(s, idleInput(), RETRO_STEP);
    run(s, idleInput(), DYING_TIME + 0.05);
    expect(mazeMuncher.status(s)).toMatchObject({ lives: 0, over: true });
  });

  it("clears the level when the last dot goes and starts a faster one", () => {
    const s = quiet();
    s.dots.fill(0);
    s.dots[1 * MAZE_W + 2] = 1;
    s.dotsLeft = 1;
    place(s, 1, 1, RIGHT);
    run(s, idleInput(), 0.3);
    expect(s.phase).toBe("clear");
    run(s, idleInput(), CLEAR_TIME + 0.05);
    expect(s.level).toBe(2);
    expect(s.dotsLeft).toBe(s.totalDots);
    expect(s.phase).toBe("ready");
  });

  it("shows a bonus gem after enough dots, worth points when eaten", () => {
    const s = quiet();
    let n = 0;
    const need = Math.floor(s.totalDots * 0.3) - 1;
    for (let i = 0; i < s.dots.length && n < need; i += 1) if (s.dots[i] === 1) { s.dots[i] = 0; s.dotsLeft -= 1; n += 1; }
    place(s, 9, 19, RIGHT);
    s.dots[19 * MAZE_W + 10] = 1;
    run(s, idleInput(), 0.3);
    expect(s.bonusTimer).toBeGreaterThan(0);
    const score = s.score;
    place(s, BONUS_X - 1, BONUS_Y, RIGHT);
    run(s, idleInput(), 0.3);
    expect(s.bonusTimer).toBe(0);
    expect(s.score - score).toBeGreaterThanOrEqual(100);
  });

  it("gives each bug its own habit while it hunts", () => {
    const s = quiet();
    s.roundTime = 0; // every bug is hunting at the start of a round
    place(s, 4, 15, LEFT);
    const out = { x: 0, y: 0 };
    const [tracker, warden, echo, roamer] = s.bugs;
    for (const b of s.bugs) { b.x = 18; b.y = 3; }
    expect(s.bugs.some((b) => patrolling(s, b))).toBe(false);

    // The tracker goes straight for the drone.
    expect(bugTarget(s, tracker, out)).toBe(true);
    expect([out.x, out.y]).toEqual([4, 15]);
    // The warden guards the power orb left nearest the drone (bottom left), then the next one.
    expect(bugTarget(s, warden, out)).toBe(true);
    expect([out.x, out.y]).toEqual([1, 15]);
    s.dots[15 * MAZE_W + 1] = 0;
    bugTarget(s, warden, out);
    expect([out.x, out.y]).toEqual([1, 2]);
    // The echo shadows the drone's mirror image.
    bugTarget(s, echo, out);
    expect([out.x, out.y]).toEqual([MAZE_W - 1 - 4, 15]);
    // The roamer wanders while the drone is far, and pounces up close.
    expect(bugTarget(s, roamer, out)).toBe(false);
    roamer.x = 6; roamer.y = 15;
    expect(bugTarget(s, roamer, out)).toBe(true);
    expect([out.x, out.y]).toEqual([4, 15]);
    expect([TRACKER, WARDEN, ECHO, ROAMER]).toEqual([0, 1, 2, 3]);
  });

  it("each bug takes its own patrol break, never all at once", () => {
    const s = quiet();
    const cycle = HUNT_TIME + PATROL_TIME;
    for (let t = 0; t < cycle * 2; t += 0.25) {
      s.roundTime = t;
      const resting = s.bugs.filter((b) => patrolling(s, b)).length;
      expect(resting, `at ${t}s`).toBeLessThan(s.bugs.length);
    }
    // A patrolling bug heads for its own home block, not for the drone.
    s.roundTime = HUNT_TIME + 0.5;
    const tracker = s.bugs[0];
    expect(patrolling(s, tracker)).toBe(true);
    const out = { x: 0, y: 0 };
    place(s, 4, 15, LEFT);
    bugTarget(s, tracker, out);
    expect([out.x, out.y]).not.toEqual([4, 15]);
    expect(isOpen(out.x, out.y)).toBe(true);
  });

  it("the bugs leave the pen and roam without ever standing in a wall", () => {
    const s = createMaze();
    for (let t = 0; t < 30; t += RETRO_STEP) {
      mazeMuncher.step(s, idleInput(), RETRO_STEP, random);
      if (s.phase === "dying") {
        // Keep the round going: lift the bug that made the catch off the drone, so it does not repeat every step.
        s.phase = "play"; s.lives = 3;
        for (const b of s.bugs) {
          if (b.mode === "active" && Math.abs(b.x - s.player.x) < 1 && Math.abs(b.y - s.player.y) < 1) { b.x = EXIT_X; b.y = EXIT_Y; b.dir = LEFT; }
        }
      }
      for (const b of s.bugs) {
        if (b.mode !== "active") continue;
        expect(isOpen(Math.round(b.x), Math.round(b.y)), `bug ${b.index} at ${b.x},${b.y}`).toBe(true);
      }
    }
    expect(s.bugs.filter((b) => b.mode === "active").length).toBeGreaterThanOrEqual(3);
  });

  it("draws every state without throwing, without words and without bad numbers", () => {
    const texts: string[] = [];
    const bad: string[] = [];
    const ctx = fakeContext(texts, bad);
    const s = mazeMuncher.create(random);
    mazeMuncher.draw(ctx, s, { time: 0, reduced: false, idle: true });
    mazeMuncher.draw(ctx, s, { time: 1, reduced: true, idle: true });
    run(s, idleInput(), 3);
    mazeMuncher.draw(ctx, s, { time: 3, reduced: false, idle: false });
    s.frightTimer = 1; for (const b of s.bugs) b.frightened = true;
    s.bonusTimer = 3;
    s.bugs[0].mode = "rebooting";
    s.bugs[0].reboot = REBOOT_TIME / 2;
    mazeMuncher.draw(ctx, s, { time: 4, reduced: false, idle: false });
    mazeMuncher.draw(ctx, s, { time: 4, reduced: true, idle: false });
    s.phase = "dying"; s.phaseTimer = DYING_TIME / 2;
    mazeMuncher.draw(ctx, s, { time: 5, reduced: false, idle: false });
    s.phase = "clear"; s.phaseTimer = 1;
    mazeMuncher.draw(ctx, s, { time: 6, reduced: false, idle: false });
    mazeMuncher.draw(ctx, s, { time: 6, reduced: true, idle: false });
    s.over = true;
    mazeMuncher.draw(ctx, s, { time: 7, reduced: false, idle: false });
    expect(bad).toEqual([]);
    expect(texts.length).toBeGreaterThan(0);
    for (const text of texts) expect(text).not.toMatch(/[A-Za-z]/);
  });
});
