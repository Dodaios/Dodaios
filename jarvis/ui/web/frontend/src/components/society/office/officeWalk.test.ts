import { describe, expect, it } from "vitest";
import type { Point } from "./officeLayout";
import { BODY_SPACING, BRISK_SPEED, WALK_SPEED, wrapAngle, type Mover } from "./officeMotion";
import { findPath, isWalkable, type NavGrid } from "./officeNav";
import { advanceWalk, beginWalk, findDetour, pathLength, PLACE_WITHIN_M, routeMarks, safePlacement, type Walk, type WalkEvent } from "./officeWalk";
import { campusOf, roomGrid, wallWithDoor } from "./officeFixtures";

const DT = 1 / 60;

interface Trace { seconds: number; events: WalkEvent[]; offFloor: number; sideways: number; arrived: boolean }

/** Walk `m` to the end of `walk`, checking every frame that it stays on the floor and faces where it goes. */
function walkThrough(walk: Walk, m: Mover, grid: () => NavGrid, bodies: () => Point[], limitS = 400, options: { place?: boolean; far?: boolean } = {}): Trace {
  const trace: Trace = { seconds: 0, events: [], offFloor: 0, sideways: 0, arrived: false };
  const start = { x: m.x, z: m.z };
  while (trace.seconds < limitS) {
    const before = { x: m.x, z: m.z };
    const step = advanceWalk(walk, m, grid(), DT, bodies(), options);
    trace.seconds += DT;
    if (step.event) trace.events.push(step.event);
    if (step.event !== "rescue" && step.moved > 1e-6) {
      // Metres covered while facing more than about 60° away from the direction of travel: gliding.
      const off = Math.abs(wrapAngle(Math.atan2(m.x - before.x, m.z - before.z) - m.heading));
      if (off > 1.05) trace.sideways += step.moved;
      // The first steps out of a seat and the last onto one cross its footprint; everything between is floor.
      const nearEnds = Math.hypot(m.x - start.x, m.z - start.z) < 1.2 || Math.hypot(m.x - walk.target.x, m.z - walk.target.z) < 1.2;
      if (!nearEnds && !isWalkable(grid(), m)) trace.offFloor += 1;
    }
    if (step.arrived) { trace.arrived = true; break; }
    if (step.event === "lost" || step.event === "blocked") break;
  }
  return trace;
}

const mover = (at: Point): Mover => ({ x: at.x, z: at.z, heading: Math.PI, path: [] });

describe("an agent's pace on real routes", () => {
  it("covers a route from the lobby to a desk at the walking pace or better, corners and all", () => {
    const { layout, grid } = campusOf(14, [5, 4]);
    const desks = layout.departments.flatMap((d) => d.desks).filter((d) => d.agentId);
    const seats = desks.map((d) => ({ x: d.x, z: d.facing === "north" ? d.z + 0.62 : d.z - 0.62 }));
    for (const [i, seat] of seats.entries()) {
      // Everybody else sits at their desk while this one walks in.
      const others = seats.filter((_, j) => j !== i);
      const m = mover(layout.spawn);
      const walk = beginWalk(grid, m, seat, others)!;
      const trace = walkThrough(walk, m, () => grid, () => others);
      expect(trace.arrived, `desk ${i}`).toBe(true);
      // Metres of route per second of the walker's own clock.
      expect(walk.length / trace.seconds, `desk ${i}`).toBeGreaterThan(WALK_SPEED);
      expect(walk.length / trace.seconds, `desk ${i}`).toBeLessThanOrEqual(BRISK_SPEED);
    }
  });
});

describe("a walk across the campus", () => {
  it("takes a long diagonal route across a large floor without leaving it, gliding or getting stuck", () => {
    const { layout, grid } = campusOf(60, [10, 9, 8, 7, 6, 6]);
    // The two hangout places furthest apart: one corner of the campus to the other.
    const spots = layout.spots.filter((s) => s.kind !== "huddle");
    const from = spots.reduce((a, b) => (a.x + a.z < b.x + b.z ? a : b));
    const to = spots.reduce((a, b) => (a.x + a.z > b.x + b.z ? a : b));
    const m = mover(from);
    const walk = beginWalk(grid, m, to)!;
    expect(walk).not.toBeNull();
    expect(walk.length).toBeGreaterThan(40);
    const trace = walkThrough(walk, m, () => grid, () => []);
    expect(trace.arrived).toBe(true);
    expect(m.x).toBe(to.x);
    expect(m.z).toBe(to.z);
    expect(trace.offFloor).toBe(0);
    expect(trace.sideways).toBeLessThan(0.2);
    expect(trace.events.filter((e) => e === "rescue" || e === "replan")).toEqual([]);
    // Brisk on the long legs: clearly faster than a stroll, never faster than the brisk pace allows.
    expect(trace.seconds).toBeLessThan(walk.length / WALK_SPEED);
    expect(trace.seconds).toBeGreaterThan(walk.length / BRISK_SPEED);
  });

  it("reaches every desk seat of a large floor exactly, from the lobby", () => {
    const { layout, grid } = campusOf(48, [8, 8, 8, 8]);
    for (const desk of layout.departments.flatMap((d) => d.desks).filter((d) => d.agentId).slice(0, 12)) {
      const seat = { x: desk.x, z: desk.facing === "north" ? desk.z + 0.62 : desk.z - 0.62 };
      const m = mover(layout.spawn);
      const walk = beginWalk(grid, m, seat)!;
      const trace = walkThrough(walk, m, () => grid, () => []);
      expect(trace.arrived, desk.id).toBe(true);
      expect([m.x, m.z], desk.id).toEqual([seat.x, seat.z]);
      expect(trace.offFloor, desk.id).toBe(0);
    }
  });
});

/**
 * Two figures walking towards each other's start, each with somewhere it has to be (as an agent going to its
 * screen): a walk given up is begun again from where it stands, and after two of those it may be placed.
 * Returns how close they came and how each walk ended.
 */
function swap(grid: NavGrid, a0: Point, b0: Point) {
  const a = mover(a0), b = mover(b0);
  const walks = { a: beginWalk(grid, a, b0)!, b: beginWalk(grid, b, a0)! };
  const givenUp = { a: 0, b: 0 };
  let closest = Infinity, seconds = 0, doneA = false, doneB = false;
  const events: WalkEvent[] = [];
  const stepOne = (who: "a" | "b", m: Mover, other: Mover, goal: Point): boolean => {
    const s = advanceWalk(walks[who], m, grid, DT, [other], { far: givenUp[who] >= 2 });
    if (s.event) events.push(s.event);
    if (s.event === "blocked") { givenUp[who] += 1; walks[who] = beginWalk(grid, m, goal, [other])!; }
    return s.arrived;
  };
  while (seconds < 120 && !(doneA && doneB)) {
    if (!doneA) doneA = stepOne("a", a, b, b0);
    if (!doneB) doneB = stepOne("b", b, a, a0);
    seconds += DT;
    if (!doneA && !doneB) closest = Math.min(closest, Math.hypot(a.x - b.x, a.z - b.z));
    expect(isWalkable(grid, a) && isWalkable(grid, b)).toBe(true);
  }
  return { a, b, closest, seconds, events, done: doneA && doneB };
}

describe("two walkers meeting head-on", () => {
  it("swap places through a door without touching, each passing on its right", () => {
    const grid = roomGrid(12, 8, wallWithDoor(6, 8, 4, 1.6));
    const result = swap(grid, { x: 2, z: 4 }, { x: 10, z: 4 });
    expect(result.done).toBe(true);
    expect([result.a.x, result.a.z]).toEqual([10, 4]);
    expect([result.b.x, result.b.z]).toEqual([2, 4]);
    expect(result.closest).toBeGreaterThan(BODY_SPACING - 0.03);
    expect(result.events).not.toContain("rescue");
    // No standing about: both are through in little more than the plain walking time.
    expect(result.seconds).toBeLessThan(8 / WALK_SPEED + 6);
  });

  it("pass each other in a narrow aisle", () => {
    // A 1.6 m aisle between two benches: 1.04 m of floor for the two of them.
    const grid = roomGrid(14, 1.6);
    const result = swap(grid, { x: 1, z: 0.8 }, { x: 13, z: 0.8 });
    expect(result.done).toBe(true);
    expect(result.closest).toBeGreaterThan(BODY_SPACING - 0.03);
    expect(result.events).not.toContain("rescue");
  });

  it("still both arrive where a door is too narrow for two: nobody is left standing in it", () => {
    const grid = roomGrid(12, 8, wallWithDoor(6, 8, 4, 1.0));
    const result = swap(grid, { x: 2, z: 4 }, { x: 10, z: 4 });
    expect(result.done).toBe(true);
    expect([result.a.x, result.a.z]).toEqual([10, 4]);
    expect([result.b.x, result.b.z]).toEqual([2, 4]);
  });
});

describe("a floor plan that changes under a walker", () => {
  it("finds the new way when a studio is built on its route, and still arrives exactly", () => {
    const before = campusOf(30, [6, 6]);
    const after = campusOf(30, [6, 6, 6, 6]);
    // A walk the new studios stand in the way of: across the studio rows, between two places both plans share.
    const from = before.layout.spawn;
    const to = before.layout.checkpoints.find((c) => c.id === "lead")!;
    expect(isWalkable(after.grid, to)).toBe(true);
    const m = mover(from);
    const walk = beginWalk(before.grid, m, to)!;
    let grid = before.grid;
    for (let i = 0; i < 6 / DT; i += 1) advanceWalk(walk, m, grid, DT, []);
    expect(m.path.length).toBeGreaterThan(0);
    grid = after.grid;
    const trace = walkThrough(walk, m, () => grid, () => []);
    expect(trace.events[0]).toBe("repath");
    expect(trace.arrived).toBe(true);
    expect([m.x, m.z]).toEqual([to.x, to.z]);
    expect(trace.offFloor).toBe(0);
    expect(walk.grid).toBe(after.grid);
  });

  it("reports a target the new plan walls off, instead of walking at a wall for ever", () => {
    const open = roomGrid(12, 8);
    const walled = roomGrid(12, 8, [{ minX: 5.9, maxX: 6.1, minZ: 0, maxZ: 8 }]);
    const m = mover({ x: 2, z: 4 });
    const walk = beginWalk(open, m, { x: 10, z: 4 })!;
    for (let i = 0; i < 60; i += 1) advanceWalk(walk, m, open, DT, []);
    const step = advanceWalk(walk, m, walled, DT, []);
    expect(step).toMatchObject({ arrived: false, event: "lost" });
    expect(m.path).toEqual([]);
  });
});

describe("a walker that stops getting anywhere", () => {
  it("takes a detour round people standing in its way", () => {
    const grid = roomGrid(12, 8);
    // Three people standing shoulder to shoulder across the straight line.
    const standing = [{ x: 6, z: 3.4 }, { x: 6, z: 4 }, { x: 6, z: 4.6 }];
    const m = mover({ x: 2, z: 4 });
    const walk = beginWalk(grid, m, { x: 10, z: 4 })!;
    let closest = Infinity;
    const trace = walkThrough(walk, m, () => grid, () => { closest = Math.min(closest, ...standing.map((b) => Math.hypot(b.x - m.x, b.z - m.z))); return standing; });
    expect(trace.arrived).toBe(true);
    expect([m.x, m.z]).toEqual([10, 4]);
    expect(closest).toBeGreaterThan(BODY_SPACING - 0.03);
    expect(trace.events).not.toContain("rescue");
  });

  it("plans a detour that avoids the bodies, and none where they close the only way", () => {
    const grid = roomGrid(12, 8);
    const direct = findPath(grid, { x: 2, z: 4 }, { x: 10, z: 4 })!;
    const round = findDetour(grid, { x: 2, z: 4 }, { x: 10, z: 4 }, [{ x: 6, z: 4 }])!;
    expect(pathLength({ x: 2, z: 4 }, round)).toBeGreaterThan(pathLength({ x: 2, z: 4 }, direct));
    // A corridor one body wide: whoever stands in it closes it.
    const corridor = roomGrid(12, 1.2);
    expect(findDetour(corridor, { x: 2, z: 0.6 }, { x: 10, z: 0.6 }, [{ x: 6, z: 0.6 }])).toBeNull();
  });

  it("is placed at a target a few steps away after two detours that did not help, and never before", () => {
    const corridor = roomGrid(12, 1.2);
    const blocker = [{ x: 6, z: 0.6 }];
    const m = mover({ x: 4.5, z: 0.6 });
    const target = { x: 7.3, z: 0.6 };
    const walk = beginWalk(corridor, m, target)!;
    const trace = walkThrough(walk, m, () => corridor, () => blocker);
    expect(trace.events).toEqual(["replan", "replan", "rescue"]);
    expect(trace.arrived).toBe(true);
    expect([m.x, m.z]).toEqual([target.x, target.z]);
    // Never through the person in the way: it waited in front of them until it was placed.
    expect(trace.seconds).toBeGreaterThan(4.5);
    expect(walk.rescues).toBe(1);
  });

  it("gives a walk up rather than being moved across the floor, unless it has to be there", () => {
    const corridor = roomGrid(12, 1.2);
    const blocker = [{ x: 6, z: 0.6 }];
    const m = mover({ x: 2, z: 0.6 });
    const walk = beginWalk(corridor, m, { x: 10, z: 0.6 })!;
    const trace = walkThrough(walk, m, () => corridor, () => blocker);
    expect(trace.events).toEqual(["replan", "replan", "blocked"]);
    expect(trace.arrived).toBe(false);
    // It stands where it was stopped, with no route left: its owner plans again from here.
    expect(m.x).toBeLessThan(6);
    expect(Math.hypot(10 - m.x, 0.6 - m.z)).toBeGreaterThan(PLACE_WITHIN_M);
    expect(m.path).toEqual([]);
    expect(walk.rescues).toBe(0);
    // An agent that must be there (its screen while it works) and failed twice is placed after all.
    const again = beginWalk(corridor, m, { x: 10, z: 0.6 })!;
    const insisted = walkThrough(again, m, () => corridor, () => blocker, 400, { far: true });
    expect(insisted.events).toEqual(["replan", "replan", "rescue"]);
    expect([m.x, m.z]).toEqual([10, 0.6]);
  });

  it("stops where it is instead of being placed when it is the person's own character", () => {
    const corridor = roomGrid(12, 1.2);
    const m = mover({ x: 4.5, z: 0.6 });
    const walk = beginWalk(corridor, m, { x: 7.3, z: 0.6 })!;
    const trace = walkThrough(walk, m, () => corridor, () => [{ x: 6, z: 0.6 }], 60, { place: false });
    expect(trace.events).toEqual(["replan", "replan", "blocked"]);
    expect(trace.arrived).toBe(false);
    // In front of the person in its way, at arm's length: not through them, and not at its target.
    expect(m.x).toBeLessThan(6);
    expect(Math.hypot(m.x - 6, m.z - 0.6)).toBeGreaterThan(BODY_SPACING - 0.01);
    expect(m.path).toEqual([]);
  });

  it("stops beside someone who stands on the place it was heading for", () => {
    const grid = roomGrid(12, 8);
    const squatter = [{ x: 9, z: 4 }];
    const m = mover({ x: 2, z: 4 });
    const walk = beginWalk(grid, m, { x: 9, z: 4 })!;
    const trace = walkThrough(walk, m, () => grid, () => squatter);
    expect(trace.arrived).toBe(true);
    expect(trace.events).toContain("near");
    const gap = Math.hypot(m.x - 9, m.z - 4);
    expect(gap).toBeGreaterThan(BODY_SPACING - 0.03);
    expect(gap).toBeLessThan(1.2);
  });

  it("ends a walk that keeps moving without ever arriving: placed when nearly there, given up when not", () => {
    const grid = roomGrid(12, 8);
    const far = mover({ x: 2, z: 4 });
    const long = beginWalk(grid, far, { x: 10, z: 4 })!;
    long.budgetS = 1;
    expect(walkThrough(long, far, () => grid, () => []).events).toEqual(["blocked"]);
    expect(far.x).toBeLessThan(5);
    const near = mover({ x: 8, z: 4 });
    const short = beginWalk(grid, near, { x: 10, z: 4 })!;
    short.budgetS = 0.5;
    expect(walkThrough(short, near, () => grid, () => []).events).toEqual(["rescue"]);
    expect([near.x, near.z]).toEqual([10, 4]);
  });
});

describe("safePlacement", () => {
  const grid = roomGrid(12, 8, [{ minX: 5, maxX: 7, minZ: 3, maxZ: 5 }]);
  it("is the seat itself for a place inside a footprint, the place when free, else free ground beside it", () => {
    expect(safePlacement(grid, { x: 6, z: 4 }, [{ x: 6, z: 4.4 }])).toEqual({ x: 6, z: 4 });
    expect(safePlacement(grid, { x: 2, z: 2 }, [])).toEqual({ x: 2, z: 2 });
    const beside = safePlacement(grid, { x: 2, z: 2 }, [{ x: 2, z: 2 }]);
    expect(isWalkable(grid, beside)).toBe(true);
    expect(Math.hypot(beside.x - 2, beside.z - 2)).toBeGreaterThanOrEqual(BODY_SPACING);
  });
});

describe("routeMarks", () => {
  it("dots the route evenly, starts a step ahead and leaves the destination to its ring", () => {
    const marks = routeMarks({ x: 0, z: 0 }, [{ x: 9, z: 0 }, { x: 9, z: 9 }], 0.9, 40);
    expect(marks.length).toBeGreaterThan(15);
    expect(marks[0]).toEqual({ x: 0.9, z: 0 });
    const last = marks[marks.length - 1];
    expect(Math.hypot(last.x - 9, last.z - 9)).toBeGreaterThan(0.4);
    for (let i = 1; i < marks.length; i += 1) {
      expect(Math.abs(marks[i].x - marks[i - 1].x) + Math.abs(marks[i].z - marks[i - 1].z)).toBeCloseTo(0.9, 5);
    }
  });
  it("spreads its dots over a long route and draws none on a short one", () => {
    expect(routeMarks({ x: 0, z: 0 }, [{ x: 200, z: 0 }], 0.9, 40)).toHaveLength(40);
    expect(routeMarks({ x: 0, z: 0 }, [{ x: 1, z: 0 }])).toEqual([]);
  });
});
